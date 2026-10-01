"""How a process is told to spend, and what its composition then builds.

A process holding a provider's credential must say whether it spends through the durable
authority or within its own fuse alone; neither is chosen for it. Under ``durable`` the model
client, an injected one included, is composed with the authority; under ``process`` it is not,
and readiness says what that means.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.services import build_services
from exulanica.db.session import Database
from exulanica.ingest.worker_command import MODEL_KEY_ENVS, worker_model_client
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.spending import (
    DurableSpending,
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
