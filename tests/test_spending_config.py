"""How a process is told to spend, and what its composition then builds.

A process holding a provider's credential must say whether it spends through the durable
authority or within its own fuse alone; neither is chosen for it. Under ``durable`` the model
client, an injected one included, is composed with the authority; under ``process`` it is not,
and readiness says what that means.
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api.account_runtime import load_guest_entry
from exulanica.api.services import build_services
from exulanica.db.session import Database
from exulanica.ingest.worker_command import MODEL_KEY_ENVS, worker_model_client
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.spending import (
    DurableSpending,
    FileSpendingWitness,
    SpendingConfigurationError,
    spending_mode,
)

from model_fakes import FakeTransport

CREDENTIALS = dict.fromkeys(load_manifest().credential_variables(load_manifest().roles), "x")


def _environ(tmp_path, **extra: str) -> dict[str, str]:
    return {
        "EXULANICA_DATABASE_URL": "postgresql://localhost:5433/never-connected-to",
        "EXULANICA_DATA_DIR": str(tmp_path),
        "EXULANICA_DERIVATIVE_WORKER": "off",
        "EXULANICA_API_TOKENS": json.dumps(
            {
                "a-token-long-enough-to-be-accepted-here": {
                    "workspace_id": str(uuid.uuid4()),
                    "actor": str(uuid.uuid4()),
                    "permissions": ["library.read"],
                }
            }
        ),
        **extra,
    }


def _client() -> ModelClient:
    return ModelClient(api_key="test-key-not-real", transport=FakeTransport())


def test_a_process_holding_a_credential_must_say_how_it_spends(tmp_path):
    with pytest.raises(SpendingConfigurationError, match="EXULANICA_SPENDING is not set"):
        build_services(_environ(tmp_path, **CREDENTIALS), model_client=_client())
    with pytest.raises(SpendingConfigurationError, match="durable or process"):
        build_services(
            _environ(tmp_path, EXULANICA_SPENDING="sometimes", **CREDENTIALS),
            model_client=_client(),
        )


def test_durable_composes_even_an_injected_client_with_the_authority(tmp_path):
    # The installation's witness directory, named by an operator command.
    FileSpendingWitness(tmp_path / "witness").ensure_directory_id()
    services = build_services(
        _environ(
            tmp_path,
            EXULANICA_SPENDING="durable",
            EXULANICA_SPENDING_WITNESS_DIR=str(tmp_path / "witness"),
            **CREDENTIALS,
        ),
        model_client=_client(),
    )
    assert isinstance(services.spending, DurableSpending)
    assert services.spending_mode == "durable"
    assert services.model_client is not None
    assert services.model_client.spending_source is services.spending
    assert services.spending.holder.startswith("api:")
    assert not any("SPENDING" in note for note in services.warnings)


def test_a_witness_directory_with_no_marker_is_named_in_readiness(tmp_path):
    services = build_services(
        _environ(
            tmp_path,
            EXULANICA_SPENDING="durable",
            EXULANICA_SPENDING_WITNESS_DIR=str(tmp_path / "not-the-installation-s"),
            **CREDENTIALS,
        ),
        model_client=_client(),
    )
    (note,) = [note for note in services.warnings if "SPENDING_WITNESS_DIR" in note]
    assert "witness_directory_mismatch" in note


def test_durable_without_a_witness_directory_is_named_in_readiness(tmp_path):
    services = build_services(
        _environ(tmp_path, EXULANICA_SPENDING="durable", **CREDENTIALS), model_client=_client()
    )
    assert services.spending is not None and services.spending.witness is None
    assert any("EXULANICA_SPENDING_WITNESS_DIR is not set" in note for note in services.warnings)


def test_process_spends_within_the_fuse_alone_and_readiness_says_so(tmp_path):
    services = build_services(
        _environ(tmp_path, EXULANICA_SPENDING="process", **CREDENTIALS), model_client=_client()
    )
    assert services.spending is None and services.spending_mode == "process"
    assert services.model_client is not None and services.model_client.spending_source is None
    assert any("EXULANICA_SPENDING is process" in note for note in services.warnings)


def test_no_credential_and_no_setting_is_the_no_model_mode(tmp_path):
    services = build_services(_environ(tmp_path))
    assert services.model_client is None and services.spending is None
    assert services.spending_mode is None
    assert spending_mode({}, credentials_configured=False) is None


def test_the_worker_composes_its_client_by_the_same_rule(tmp_path):
    database = Database(url="postgresql://localhost:5433/never-connected-to")
    keys = dict.fromkeys(MODEL_KEY_ENVS, "x")
    with pytest.raises(SpendingConfigurationError):
        worker_model_client(keys, database, model_client=_client())
    durable = worker_model_client(
        {**keys, "EXULANICA_SPENDING": "durable"}, database, model_client=_client()
    )
    assert durable is not None and isinstance(durable.spending_source, DurableSpending)
    assert durable.spending_source.holder.startswith("worker:")
    process = worker_model_client(
        {**keys, "EXULANICA_SPENDING": "process"}, database, model_client=_client()
    )
    assert process is not None and process.spending_source is None
    assert worker_model_client({}, database) is None


GUEST_ENTRY = {
    "EXULANICA_GUEST_ENTRY": "open",
    "EXULANICA_GUEST_ENTRIES_PER_DAY": "10",
    "EXULANICA_ACCOUNT_BROWSER_ORIGINS": '["https://app.test"]',
    "EXULANICA_ACCOUNT_DATABASE_URL": "postgresql://localhost:5433/never-connected-to",
}


def test_a_guest_entry_with_a_model_credential_needs_durable_spending(tmp_path, monkeypatch):
    """A guest's allowance is a grant under the durable authority: under process spending a
    visitor has none and would spend from the fuse every owner shares, so startup refuses."""
    # The account runtime as the environment configures it, without its database check: only its
    # guest entry is read here, and that is parsed from the same settings.
    monkeypatch.setattr(
        "exulanica.api.services.load_account_runtime",
        lambda environ: SimpleNamespace(guest=load_guest_entry(environ)),
    )
    with pytest.raises(SpendingConfigurationError, match="needs EXULANICA_SPENDING=durable"):
        build_services(
            _environ(tmp_path, EXULANICA_SPENDING="process", **GUEST_ENTRY, **CREDENTIALS),
            model_client=_client(),
        )
    # With no model at all a guest spends nothing, and the guest entry starts.
    services = build_services(_environ(tmp_path, **GUEST_ENTRY))
    assert services.accounts is not None and services.accounts.guest is not None
    # Under durable spending it starts with the model.
    FileSpendingWitness(tmp_path / "witness").ensure_directory_id()
    durable = build_services(
        _environ(
            tmp_path,
            EXULANICA_SPENDING="durable",
            EXULANICA_SPENDING_WITNESS_DIR=str(tmp_path / "witness"),
            **GUEST_ENTRY,
            **CREDENTIALS,
        ),
        model_client=_client(),
    )
    assert durable.spending is not None and durable.accounts is not None
