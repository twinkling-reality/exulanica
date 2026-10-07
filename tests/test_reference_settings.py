"""How an installation turns references on: the two settings, a source's configuration, and when
this process builds the worker. No database and no network: nothing here opens either."""

from __future__ import annotations

import dataclasses
import json
import uuid
from decimal import Decimal

import pytest
from exulanica.api.services import Services
from exulanica.db.session import Database
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
from exulanica.models.manifest import load_manifest
from exulanica.references.adapters import ReferenceSourceUnavailable
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.catalogs import load_reference_catalogs
from exulanica.references.settings import (
    REFERENCE_WORKER_ENV,
    REFERENCE_WORKSPACES_ENV,
    ReferenceSettingRefused,
    configured_adapter,
    plays_references_here,
    reference_workspaces,
)
from exulanica.references.worker import ReferenceWorker
from exulanica.store.local import LocalContentAddressedStore

from model_fakes import FakeTransport, RecordingPolicy

WORKSPACE = uuid.UUID("5d0c6f3e-6d0e-4f0a-9a43-6f1d2c0e7b11")
TAVILY = "https://api.tavily.com"
NEBIUS = "https://api.tokenfactory.nebius.com"


def _source():
    return load_reference_catalogs().sources["tavily_search"]


def test_the_variables_are_named_as_the_installation_documents_name_them() -> None:
    assert (REFERENCE_WORKER_ENV, REFERENCE_WORKSPACES_ENV) == (
        "EXULANICA_REFERENCE_WORKER",
        "EXULANICA_REFERENCE_WORKSPACES",
    )


@pytest.mark.parametrize(
    ("value", "here"), [(None, True), ("", True), ("on", True), ("off", False), ("0", False)]
)
def test_references_are_played_here_unless_set_off(value, here) -> None:
    assert plays_references_here(value) is here


def test_an_unrecognised_worker_setting_is_refused_by_name() -> None:
    with pytest.raises(ReferenceSettingRefused) as refused:
        plays_references_here("process")
    assert refused.value.code == "reference_worker_not_recognised"


def test_the_workspace_list_is_read_whole_or_refused() -> None:
    assert reference_workspaces(None) == ()
    assert reference_workspaces(json.dumps([str(WORKSPACE)])) == (WORKSPACE,)
    for value, code in [
        ("not json", "reference_workspaces_not_json"),
        ('{"a": 1}', "reference_workspaces_not_array"),
        ('["not-an-id"]', "reference_workspaces_not_uuid"),
        (json.dumps([str(WORKSPACE), str(WORKSPACE)]), "reference_workspaces_duplicate"),
    ]:
        with pytest.raises(ReferenceSettingRefused) as refused:
            reference_workspaces(value)
        assert refused.value.code == code


def test_a_source_is_configured_only_with_its_origin_declared_and_its_credential_set() -> None:
    both = {EGRESS_ALLOWLIST_ENV: json.dumps([NEBIUS, TAVILY]), "TAVILY_API_KEY": "tvly-test"}
    adapter = configured_adapter(_source(), both)
    assert isinstance(adapter, TavilySearch)
    for environ in (
        {"TAVILY_API_KEY": "tvly-test"},
        {EGRESS_ALLOWLIST_ENV: json.dumps([NEBIUS]), "TAVILY_API_KEY": "tvly-test"},
        {EGRESS_ALLOWLIST_ENV: json.dumps([NEBIUS, TAVILY])},
    ):
        with pytest.raises(ReferenceSourceUnavailable) as refused:
            configured_adapter(_source(), environ)
        assert refused.value.code == "references_not_configured"
        assert "tvly-test" not in str(refused.value)


class _Spending:
    def for_workspace(self, workspace_id):
        raise AssertionError("nothing is spent while a worker is only built")


def _services(tmp_path, **changes) -> Services:
    database = Database(url="postgresql://never-opened.invalid/exulanica")
    services = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path),
        tokens=None,
        executor_shares_the_write_role=True,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=FakeTransport(),
            budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=5),
            policy=RecordingPolicy(),
        ),
        runs_reference_worker=True,
        reference_workspaces=(WORKSPACE,),
        reference_adapter_for=lambda source: None,
        spending=_Spending(),
    )
    return dataclasses.replace(services, **changes)


def test_the_worker_is_built_only_with_a_client_spending_a_workspace_and_sources(tmp_path) -> None:
    assert isinstance(_services(tmp_path).build_reference_worker(), ReferenceWorker)
    for missing in (
        {"model_client": None},
        {"spending": None},
        {"reference_workspaces": ()},
        {"reference_adapter_for": None},
    ):
        assert _services(tmp_path, **missing).build_reference_worker() is None, missing


def test_a_hand_built_services_plays_no_references(tmp_path) -> None:
    database = Database(url="postgresql://never-opened.invalid/exulanica")
    bare = Services(
        database=database,
        readonly_database=database,
        store=LocalContentAddressedStore(tmp_path),
        tokens=None,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    assert (bare.runs_reference_worker, bare.reference_workspaces) == (False, ())
    assert bare.reference_adapter_for is None


def test_no_worker_runs_on_a_public_installation_for_a_source_offered_to_the_operator_only(
    tmp_path,
) -> None:
    from types import SimpleNamespace

    public = SimpleNamespace(profile=SimpleNamespace(id="public"))
    private = SimpleNamespace(profile=SimpleNamespace(id="personal"))
    assert _services(tmp_path, installation=public).build_reference_worker() is None
    assert not _services(tmp_path, installation=public).references_offered_here()
    assert isinstance(
        _services(tmp_path, installation=private).build_reference_worker(), ReferenceWorker
    )


def test_readiness_reports_the_reference_worker_only_where_one_was_built(tmp_path) -> None:
    from types import SimpleNamespace

    from exulanica.api.routes.health import _references_check

    services = _services(tmp_path)

    def request(worker, alive):
        thread = SimpleNamespace(is_alive=lambda: alive)
        return SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(reference_worker=worker, reference_thread=thread)
            )
        )

    unbuilt = _references_check(request(None, False), services)
    assert unbuilt == {"ok": True, "configured": False, "running": False}
    dead = _references_check(request(object(), False), services)
    assert (dead["ok"], dead["configured"], dead["running"]) == (False, True, False)
    alive = _references_check(request(object(), True), services)
    assert (alive["ok"], alive["running"], alive["listed_workspaces"]) == (True, True, 1)
