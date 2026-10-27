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
    NOTES_AND_CREATURES_ENV,
    REFERENCE_PICTURES_ENV,
    REFERENCE_WORKER_ENV,
    REFERENCE_WORKSPACES_ENV,
    ReferenceSettingRefused,
    configured_adapter,
    notes_and_creatures_for_everyone,
    plays_references_here,
    reads_pictures_here,
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
    assert (REFERENCE_WORKER_ENV, REFERENCE_WORKSPACES_ENV, REFERENCE_PICTURES_ENV) == (
        "EXULANICA_REFERENCE_WORKER",
        "EXULANICA_REFERENCE_WORKSPACES",
        "EXULANICA_REFERENCE_PICTURES",
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


@pytest.mark.parametrize(
    ("value", "read"),
    [(None, False), ("", False), ("off", False), ("0", False), ("on", True), (" YES ", True)],
)
def test_pictures_are_read_only_where_set_on(value, read) -> None:
    assert reads_pictures_here(value) is read


def test_an_unrecognised_pictures_setting_is_refused_by_name() -> None:
    with pytest.raises(ReferenceSettingRefused) as refused:
        reads_pictures_here("operator")
    assert refused.value.code == "reference_pictures_not_recognised"


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


def test_a_worker_reads_pictures_only_where_they_are_turned_on(tmp_path) -> None:
    assert _services(tmp_path).build_reference_worker()._picture_source is None
    on = _services(tmp_path, reference_pictures=True)
    assert on.build_reference_worker()._picture_source is not None
    assert on.pictures_offered_to(WORKSPACE)
    assert not _services(tmp_path).pictures_offered_to(WORKSPACE)
    assert not on.pictures_offered_to(uuid.uuid4())
    assert not _services(
        tmp_path, reference_pictures=True, runs_reference_worker=False
    ).pictures_offered_to(WORKSPACE)


def test_a_server_reads_the_pictures_setting_and_is_off_without_it(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from exulanica.api.services import build_services

    monkeypatch.setattr(
        "exulanica.api.services.load_account_runtime", lambda _: SimpleNamespace(guest=None)
    )
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    assert build_services(environ).reference_pictures is False
    assert build_services({**environ, REFERENCE_PICTURES_ENV: "on"}).reference_pictures is True
    with pytest.raises(ReferenceSettingRefused):
        build_services({**environ, REFERENCE_PICTURES_ENV: "sometimes"})


def test_pictures_are_never_offered_on_a_public_installation(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    # Whatever the web source's catalog entry offers: here, as if it were offered to everyone.
    monkeypatch.setattr(Services, "references_offered_here", lambda self: True)
    public = SimpleNamespace(profile=SimpleNamespace(id="public"))
    private = SimpleNamespace(profile=SimpleNamespace(id="personal"))
    assert not _services(
        tmp_path, reference_pictures=True, installation=public
    ).pictures_offered_to(WORKSPACE)
    assert _services(tmp_path, reference_pictures=True, installation=private).pictures_offered_to(
        WORKSPACE
    )


def test_a_public_installation_s_worker_has_no_picture_source(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(Services, "references_offered_here", lambda self: True)
    public = SimpleNamespace(profile=SimpleNamespace(id="public"))
    worker = _services(tmp_path, reference_pictures=True, installation=public)
    assert worker.build_reference_worker()._picture_source is None


# -- web notes and creatures for every workspace (EXULANICA_NOTES_AND_CREATURES) ----------------


@pytest.mark.parametrize(
    ("value", "everyone"),
    [(None, False), ("", False), ("listed", False), ("everyone", True), (" Everyone ", True)],
)
def test_notes_and_creatures_keep_to_the_lists_unless_offered_to_everyone(value, everyone) -> None:
    assert notes_and_creatures_for_everyone(value) is everyone
    assert NOTES_AND_CREATURES_ENV == "EXULANICA_NOTES_AND_CREATURES"


def test_an_unrecognised_offer_of_notes_and_creatures_is_refused_by_name() -> None:
    for value in ("on", "guests", "all"):
        with pytest.raises(ReferenceSettingRefused) as refused:
            notes_and_creatures_for_everyone(value)
        assert refused.value.code == "notes_and_creatures_not_recognised"


def test_a_server_reads_the_offer_and_keeps_to_the_lists_without_it(monkeypatch, tmp_path) -> None:
    from types import SimpleNamespace

    from exulanica.api.services import build_services

    monkeypatch.setattr(
        "exulanica.api.services.load_account_runtime", lambda _: SimpleNamespace(guest=None)
    )
    environ = {"EXULANICA_DATABASE_URL": "postgresql://unused", "EXULANICA_DATA_DIR": str(tmp_path)}
    assert build_services(environ).notes_and_creatures_for_everyone is False
    offered = build_services({**environ, NOTES_AND_CREATURES_ENV: "everyone"})
    assert offered.notes_and_creatures_for_everyone is True
    with pytest.raises(ReferenceSettingRefused):
        build_services({**environ, NOTES_AND_CREATURES_ENV: "sometimes"})


def test_a_public_installation_offers_notes_and_creatures_to_everyone_only_when_set(
    tmp_path,
) -> None:
    """Off by default on a public installation, whatever the lists hold; set, every workspace
    may ask, guests' among them, and the worker looks in every workspace the draft workers do."""
    from types import SimpleNamespace

    public = SimpleNamespace(profile=SimpleNamespace(id="public"))
    stranger = uuid.uuid4()
    stores = SimpleNamespace(looks=SimpleNamespace(for_workspace=lambda workspace: None))
    off = _services(
        tmp_path,
        installation=public,
        reference_workspaces=(),
        runs_creature_worker=True,
        content_stores=stores,
    )
    assert not off.references_offered_here()
    assert not off.serves_references_to(stranger) and not off.serves_creatures_to(stranger)
    assert off.build_reference_worker() is None and off.build_creature_worker() is None

    on = dataclasses.replace(off, notes_and_creatures_for_everyone=True)
    assert on.references_offered_here()
    assert on.serves_references_to(stranger) and on.serves_creatures_to(stranger)
    worker = on.build_reference_worker()
    assert isinstance(worker, ReferenceWorker)
    # A token's workspace stands in for every one the draft workers look in.
    found = dataclasses.replace(on, tokens=SimpleNamespace(workspaces=frozenset({stranger})))
    assert stranger in found.build_reference_worker()._workspaces()
    assert stranger in found.build_creature_worker()._workspaces()
    assert stranger not in dataclasses.replace(
        off, tokens=SimpleNamespace(workspaces=frozenset({stranger}))
    ).offered_workspaces(())
    # Only notes: a person's own pictures and picture searches stay off on a public installation.
    pictured = dataclasses.replace(on, reference_pictures=True, reference_web_pictures=True)
    assert not pictured.pictures_offered_to(stranger)
    assert pictured.build_reference_worker()._picture_source is None


def test_a_guest_holds_the_search_permission_only_where_notes_are_offered_to_everyone(
    tmp_path,
) -> None:
    from exulanica.api.dependencies import browser_permissions
    from exulanica.api.permissions import (
        ACCOUNT_OWNER_PERMISSIONS,
        GUEST_PERMISSIONS,
        Permission,
    )

    listed = _services(tmp_path)
    assert browser_permissions(listed, "guest") == GUEST_PERMISSIONS
    assert Permission.REFERENCES_REQUEST not in browser_permissions(listed, "guest")
    everyone = _services(tmp_path, notes_and_creatures_for_everyone=True)
    assert browser_permissions(everyone, "guest") == GUEST_PERMISSIONS | {
        Permission.REFERENCES_REQUEST
    }
    # Nothing else a guest is withheld comes with it, and an owner's grant is the same either way.
    for withheld in (Permission.INTAKE_WRITE, Permission.DOOR_GRANT, Permission.CONSENT_WRITE):
        assert withheld not in browser_permissions(everyone, "guest")
    assert browser_permissions(everyone, "owner") == ACCOUNT_OWNER_PERMISSIONS
