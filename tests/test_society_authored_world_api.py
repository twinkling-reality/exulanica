"""The whole walk through product routes: save a world, furnish it, and let somebody live in it.

Every step here is an authenticated HTTP request against the real application, with the saved
world named the way the world object routes already name one. No district is registered, no
city source is admitted and no model is configured.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
TOKEN = "saved-world-owner-token-long-enough"
STRANGER_TOKEN = "saved-world-stranger-token-long-enough"
OWNER = {"Authorization": f"Bearer {TOKEN}"}
STRANGER = {"Authorization": f"Bearer {STRANGER_TOKEN}"}


@pytest.fixture
def saved_world_app(saved_world, spine_schema, monkeypatch):
    world = saved_world
    world["connection"].commit()
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
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
    # The same explicit persisted host registration, read into a new runtime each time.
    binding_json = world["binding"].model_dump_json()
    registry_json = json.dumps(world["registry"])

    def make_app():
        database = scratch_database(spine_schema[1])
        return create_app(
            Services(
                database=database,
                readonly_database=database,
                store=world["store"],
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
                society_runtime=SocietyRuntime(
                    store=world["store"],
                    authored_bindings=[
                        AuthoredWorldSocietyBinding.model_validate_json(binding_json)
                    ],
                    reviewed_affordances=json.loads(registry_json),
                ),
            ),
            verify=False,
        )

    return world, make_app


def test_a_person_furnishes_their_own_world_and_somebody_rests_in_it(saved_world_app):
    world, make_app = saved_world_app
    binding = world["binding"]
    scope = {"world_id": binding.world_id}
    version_route = f"/world/versions/{binding.version_id}"
    society_route = version_route + "/society"
    with TestClient(make_app()) as client:
        response = client.post(
            version_route + "/objects",
            headers=OWNER,
            params=scope,
            json={
                "base_state_sha256": client.get(version_route, headers=OWNER, params=scope).json()[
                    "state_sha256"
                ],
                "object_id": "object:cushion",
                "asset_sha256": world["plate"].content_sha256,
                "region_id": binding.region_id,
                "transform": {
                    "x_mm": 3000,
                    "y_mm": 0,
                    "z_mm": 5000,
                    "yaw_microradians": 0,
                    "scale_milli": 1000,
                },
                "origin_role": "fictional",
            },
        )
        assert response.status_code == 201, response.text

        create_body = {
            "place_id": str(binding.place_id),
            "region_id": binding.region_id,
            "seed": "7a" * 32,
            "profile": "exulanica-society/v2",
        }
        # Named in another world this workspace holds, the fixture's, the routes look there, where
        # this version does not exist. That is a missing version, not another world's society.
        elsewhere = {"world_id": registered_world(world["connection"], world["workspace"])}
        world["connection"].commit()
        response = client.post(society_route, headers=OWNER, params=elsewhere, json=create_body)
        assert response.status_code == 404
        response = client.post(society_route, headers=OWNER, params=scope, json=create_body)
        assert response.status_code == 200, response.text
        society = response.json()
        assert society["profile"] == "exulanica-society/v2" and society["current_tick"] == 0

        document = (
            world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s and input_seq=1",
                (world["workspace"],),
            )
            .fetchone()["document"]
        )
        [target] = document["targets"]
        assert target["affordance"] == "rest" and target["object_id"] == "object:cushion"

        subject = society["state"]["inhabitants"][0]["id"]
        request_id = str(uuid.uuid4())
        response = client.post(
            society_route + "/actions",
            headers=OWNER,
            params=scope,
            json={
                "idempotency_key": request_id,
                "base_tick": society["current_tick"],
                "base_state_sha256": society["state_sha256"],
                "subject_id": subject,
                "intent": {
                    "kind": "perform",
                    "target_id": target["target_id"],
                    "affordance": "rest",
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "pending"

        response = client.post(
            society_route + "/steps",
            headers=OWNER,
            params=scope,
            json={
                "base_tick": society["current_tick"],
                "base_state_sha256": society["state_sha256"],
            },
        )
        assert response.status_code == 200, response.text
        advanced = response.json()
        assert advanced["current_tick"] == 1

        record = client.get(f"{society_route}/actions/{request_id}", headers=OWNER, params=scope)
        assert record.status_code == 200, record.text
        assert record.json()["consumption"] == {"tick": 1, "disposition": "applied"}
        person = next(p for p in advanced["state"]["inhabitants"] if p["id"] == subject)
        assert person["goal"]["target_id"] == target["target_id"]
        replay = client.get(society_route + "/replay", headers=OWNER, params=scope).json()
        assert replay["replay_verified"]

    # Reload: a process started again from the same registration serves the same world.
    with TestClient(make_app()) as reloaded:
        for suffix, expected in (("", advanced), ("/replay", replay)):
            response = reloaded.get(society_route + suffix, headers=OWNER, params=scope)
            assert response.status_code == 200, response.text
            assert response.json() == expected
            assert (
                reloaded.get(society_route + suffix, headers=STRANGER, params=scope).status_code
                == 404
            )
        # There is no district to present, and the route says that rather than inventing one.
        assert (
            reloaded.get(society_route + "/district", headers=OWNER, params=scope).status_code
            == 404
        )


def test_an_unregistered_saved_world_is_told_why_it_cannot_hold_inhabitants(
    saved_world_app, spine_schema
):
    world, _ = saved_world_app
    binding = world["binding"]
    database = scratch_database(spine_schema[1])
    app = create_app(
        Services(
            database=database,
            readonly_database=database,
            store=world["store"],
            tokens=load_token_directory(),
            executor_shares_the_write_role=True,
            model_client=None,
        ),
        verify=False,
    )
    with TestClient(app) as client:
        response = client.post(
            f"/world/versions/{binding.version_id}/society",
            headers=OWNER,
            params={"world_id": binding.world_id},
            json={
                "place_id": str(binding.place_id),
                "region_id": binding.region_id,
                "seed": "7a" * 32,
                "profile": "exulanica-society/v2",
            },
        )
        assert response.status_code == 424
        assert response.json()["code"] == "unavailable_society_input"
