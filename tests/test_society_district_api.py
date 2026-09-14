"""Authenticated district read against admitted source fixtures and PostgreSQL authority."""

from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes.society_district import router
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.evidence.blob import BlobId
from exulanica.store.base import PurgeAuthorization, privileged_purger
from fastapi.testclient import TestClient

import test_society_runtime as helpers
from tests_support_api import scratch_database

runtime_world = helpers.runtime_world
pytestmark = pytest.mark.postgres
TOKEN = "society-district-scoped-token-for-tests"
FOREIGN = "society-district-other-workspace-test-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def district_app(runtime_world, spine_schema, monkeypatch):
    w = runtime_world
    w["binding"] = w["binding"].model_copy(update={"translation_mm": (12000, 0, -8000)})
    w["runtime"] = SocietyRuntime(
        store=w["store"], bindings=[w["binding"]], reviewed_affordances=w["registry"]
    )
    w["connection"].commit()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {"workspace_id": str(w["workspace"]), "actor": str(w["session"].actor)},
                FOREIGN: {"workspace_id": str(uuid.uuid4()), "actor": str(uuid.uuid4())},
            }
        ),
    )
    db = scratch_database(spine_schema[1])
    services = Services(
        database=db,
        readonly_database=db,
        store=w["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )

    class ConfiguredServices:
        society_runtime = w["runtime"]

        def __getattr__(self, name):
            return getattr(services, name)

    app = create_app(services, verify=False)
    app.state.services = ConfiguredServices()
    if not any(
        getattr(r, "path", None) == "/world/versions/{version_id}/society/district"
        for r in app.routes
    ):
        app.include_router(router)
    return w, app


def test_authenticated_bytes_scope_registration_reload_and_withdrawal(district_app):
    w, app = district_app
    binding = w["binding"]
    route = f"/world/versions/{binding.version_id}/society/district"
    with TestClient(app) as client:
        assert client.get(route).status_code == 401
        foreign = client.get(route, headers={"Authorization": f"Bearer {FOREIGN}"})
        assert foreign.status_code == 404
        assert foreign.headers["cache-control"] == "private, no-store"
        assert (
            client.get(
                f"/world/versions/{uuid.uuid4()}/society/district", headers=HEADERS
            ).status_code
            == 404
        )
        response = client.get(route, headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        body = response.json()
        assert body["profile"] == "exulanica.society-district-view/v1"
        assert body["registration"] == binding.registration()
        assert body["place_id"] == str(binding.place_id)
        for name, sha in [
            ("base", binding.base_artifact_sha256),
            ("interpretation", binding.interpretation_artifact_sha256),
        ]:
            data = body[name + "_json"].encode("utf-8")
            assert data == w["store"].get(BlobId.from_hex(sha))
            assert hashlib.sha256(data).hexdigest() == body[name + "_artifact_sha256"]
        assert body["current_dependencies"] == {
            s.source_sha256: "available" for s in binding.sources
        }
        assert (
            json.loads(body["interpretation_json"])["document_sha256"]
            == body["interpretation_document_sha256"]
        )
        app.state.services.society_runtime = SocietyRuntime(
            store=w["store"], bindings=[binding], reviewed_affordances=w["registry"]
        )
        assert client.get(route, headers=HEADERS).json() == body
        # Reading presentation must not create a society or advance its input/event stream.
        assert (
            w["connection"]
            .execute(
                "select count(*) as n from world_society_input where workspace_id=%s",
                (w["workspace"],),
            )
            .fetchone()["n"]
            == 0
        )
        w["admissions"].withdraw("source", binding.sources[0].admission_id)
        w["connection"].commit()
        denied = client.get(route, headers=HEADERS)
        assert denied.status_code == 424
        assert denied.headers["cache-control"] == "private, no-store"
        assert "base_json" not in denied.json()


@pytest.mark.parametrize(
    "mutation", ["missing-runtime", "missing-blob", "binding-drift", "source-invalidated"]
)
def test_unavailable_dependencies_do_not_return_district_json(district_app, repository, mutation):
    w, app = district_app
    b = w["binding"]
    if mutation == "missing-runtime":
        app.state.services.society_runtime = None
    elif mutation == "missing-blob":
        privileged_purger(
            w["store"],
            PurgeAuthorization(tombstone_id="test", actor="test", reason="isolated missing bytes"),
        ).purge(BlobId.from_hex(b.interpretation_artifact_sha256))
    elif mutation == "binding-drift":
        changed = b.model_copy(update={"interpretation_document_sha256": "f" * 64})
        app.state.services.society_runtime = SocietyRuntime(
            store=w["store"], bindings=[changed], reviewed_affordances=w["registry"]
        )
    else:
        repository.insert_tombstone(
            scope="workspace",
            requested_by=w["session"].actor,
            reason="isolated test source invalidation",
        )
        w["connection"].commit()
        assert w["objects"].version(b.version_id).source_invalidated
    with TestClient(app) as client:
        response = client.get(f"/world/versions/{b.version_id}/society/district", headers=HEADERS)
        assert response.status_code == 424, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert "interpretation_json" not in response.json()


@pytest.mark.parametrize("runtime_world", [{"display": False}], indirect=True)
def test_operation_rights_cannot_be_granted_by_presentation(district_app):
    w, app = district_app
    with TestClient(app) as client:
        response = client.get(
            f"/world/versions/{w['binding'].version_id}/society/district", headers=HEADERS
        )
        assert response.status_code == 424, response.text


def test_configured_but_nonexistent_version_is_not_found(district_app):
    w, app = district_app
    missing = w["binding"].model_copy(update={"version_id": uuid.uuid4()})
    app.state.services.society_runtime = SocietyRuntime(
        store=w["store"], bindings=[missing], reviewed_affordances=w["registry"]
    )
    with TestClient(app) as client:
        response = client.get(
            f"/world/versions/{missing.version_id}/society/district", headers=HEADERS
        )
        assert response.status_code == 404
        assert response.headers["cache-control"] == "private, no-store"
