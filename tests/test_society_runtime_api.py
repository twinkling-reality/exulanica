"""Authenticated API composition using admitted Flatiron data and the real runtime hooks."""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime, SocietyRuntimeBinding
from fastapi.testclient import TestClient

import test_society_runtime as runtime_helpers
from tests_support_api import EVERY_PERMISSION, scratch_database

runtime_world = runtime_helpers.runtime_world
pytestmark = pytest.mark.postgres
TOKEN = "society-runtime-owner-token-long-enough"
STRANGER_TOKEN = "society-runtime-stranger-token-long-enough"
OWNER_HEADERS = {"Authorization": f"Bearer {TOKEN}"}
STRANGER_HEADERS = {"Authorization": f"Bearer {STRANGER_TOKEN}"}


@pytest.fixture
def runtime_app(runtime_world, spine_schema, monkeypatch):
    w = runtime_world
    w["connection"].commit()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(w["workspace"]),
                    "actor": str(w["session"].actor),
                    "permissions": EVERY_PERMISSION,
                },
                STRANGER_TOKEN: {
                    "workspace_id": str(uuid.uuid4()),
                    "actor": str(uuid.uuid4()),
                    "permissions": EVERY_PERMISSION,
                },
            }
        ),
    )
    # Reload the same explicit persisted host configuration into a new runtime each time.
    binding_json = w["binding"].model_dump_json()
    registry_json = json.dumps(w["registry"])

    def make_app():
        database = scratch_database(spine_schema[1])
        runtime = SocietyRuntime(
            store=w["store"],
            bindings=[SocietyRuntimeBinding.model_validate_json(binding_json)],
            reviewed_affordances=json.loads(registry_json),
        )
        return create_app(
            Services(
                database=database,
                readonly_database=database,
                store=w["store"],
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
                society_runtime=runtime,
            ),
            verify=False,
        )

    return w, make_app


def input_history(world):
    return [
        row["document"]
        for row in world["connection"].execute(
            "select document from world_society_input where workspace_id=%s order by input_seq",
            (world["workspace"],),
        )
    ]


def test_real_runtime_http_edit_undo_advance_reload_replay_and_scope(runtime_app):
    w, make_app = runtime_app
    binding = w["binding"]
    version_route = f"/world/versions/{binding.version_id}"
    route = version_route + "/society"
    create_body = {
        "place_id": str(binding.place_id),
        "region_id": binding.region_id,
        "seed": "7a" * 32,
        "profile": "exulanica-society/v2",
    }
    with TestClient(make_app()) as client:
        assert client.post(route, json=create_body).status_code == 401
        response = client.post(route, headers=OWNER_HEADERS, json=create_body)
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["profile"] == "exulanica-society/v2"
        assert first["input_seq"] == 1 and first["current_tick"] == 0
        documents = input_history(w)
        assert len(documents) == 1
        district = documents[0]
        assert district["availability"] == "available"
        # Use a real shared A node, never a new invented navigation position.
        node = district["navigation"]["nodes"][0]
        x, z = node["position_mm"]
        response = client.post(
            version_route + "/objects",
            headers=OWNER_HEADERS,
            json={
                "base_state_sha256": w["version"].state_sha256,
                "object_id": "object:http-rest-pad",
                "asset_sha256": w["plate"].content_sha256,
                "region_id": binding.region_id,
                "transform": {
                    "x_mm": x,
                    "y_mm": 0,
                    "z_mm": z,
                    "yaw_microradians": 0,
                    "scale_milli": 1000,
                },
                "origin_role": "fictional",
            },
        )
        assert response.status_code == 201, response.text
        added = response.json()
        documents = input_history(w)
        assert [d["input_seq"] for d in documents] == [1, 2]
        authored = [t for t in documents[1]["targets"] if t["origin"] == "authored"]
        assert len(authored) == 1 and authored[0]["object_id"] == "object:http-rest-pad"
        assert authored[0]["node_id"] == node["node_id"]
        assert documents[1]["authored_state"]["delta_sha256"] == added["state_sha256"]
        assert documents[1]["district_document_sha256"] == district["district_document_sha256"]
        response = client.post(
            version_route + "/objects/undo",
            headers=OWNER_HEADERS,
            json={"base_state_sha256": added["state_sha256"]},
        )
        assert response.status_code == 200, response.text
        assert response.json()["objects"] == []
        documents = input_history(w)
        assert [d["input_seq"] for d in documents] == [1, 2, 3]
        assert not any(t["origin"] == "authored" for t in documents[2]["targets"])
        assert documents[2]["authored_state"]["delta_sha256"] == w["version"].state_sha256
        response = client.post(
            route + "/steps",
            headers=OWNER_HEADERS,
            json={"base_tick": first["current_tick"], "base_state_sha256": first["state_sha256"]},
        )
        assert response.status_code == 200, response.text
        advanced = response.json()
        assert advanced["current_tick"] == 1 and advanced["input_seq"] == 3
        response = client.get(route + "/events", headers=OWNER_HEADERS)
        assert response.status_code == 200, response.text
        events = response.json()
        assert events["events"]
        response = client.get(route + "/replay", headers=OWNER_HEADERS)
        assert response.status_code == 200, response.text
        replay = response.json()
        assert replay["replay_verified"] and replay["state_sha256"] == advanced["state_sha256"]

    with TestClient(make_app()) as reloaded:
        for suffix, expected in (("", advanced), ("/events", events), ("/replay", replay)):
            response = reloaded.get(route + suffix, headers=OWNER_HEADERS)
            assert response.status_code == 200, response.text
            assert response.json() == expected
            assert reloaded.get(route + suffix, headers=STRANGER_HEADERS).status_code == 404
        assert (
            reloaded.post(
                route + "/steps",
                headers=STRANGER_HEADERS,
                json={
                    "base_tick": advanced["current_tick"],
                    "base_state_sha256": advanced["state_sha256"],
                },
            ).status_code
            == 404
        )
        assert (
            reloaded.post(
                version_route + "/objects/undo",
                headers=STRANGER_HEADERS,
                json={"base_state_sha256": w["version"].state_sha256},
            ).status_code
            == 404
        )
        assert [d["input_seq"] for d in input_history(w)] == [1, 2, 3]
