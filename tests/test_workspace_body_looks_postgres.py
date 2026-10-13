"""A custom body's card offers only admitted looks of its exact scoped body plan."""

from __future__ import annotations

import copy
import dataclasses
import uuid

import pytest
from exulanica.api import thing_card
from exulanica.db.roles import RUNTIME_ROLE
from exulanica.store.local import LocalContentAddressedStore
from exulanica.things.authored import container_of
from exulanica.world.thing_store import ThingStore
from fastapi.testclient import TestClient

import test_society_made_kinds_postgres as made
from conftest import scratch_role_database
from test_society_saved_world_api import OWNER, STRANGER, routes
from test_thing_store_admission import _imported

saved_world = made.saved_world
saved_world_app = made.saved_world_app
world_app = made.world_app
kept = made.kept
pytestmark = pytest.mark.postgres


def test_workspace_body_look_choices_swap_without_changing_society_and_respect_scope(
    world_app, kept, tmp_path, spine_schema
):
    world, make_app, _runtime, database = world_app
    with TestClient(make_app()) as client:
        snapshot = made._society(client, world, kept)
        database = scratch_role_database(spine_schema[1], RUNTIME_ROLE)
        client.app.state.services = dataclasses.replace(
            client.app.state.services, database=database, readonly_database=database
        )
        subject = next(p for p in snapshot["state"]["inhabitants"] if p["came_by"] == "placed")
        scope, _, society = routes(world)
        path = society + "/things/" + subject["id"]
        before = client.get(path, headers=OWNER, params=scope).json()
        assert any(x.get("sha256") == kept.sketch.sha256 for x in before["looks"])
        document = copy.deepcopy(dict(kept.sketch.document))
        document["look"] = "authored-body-alternate"
        document["label"] = "another authored surface"

        def intake(look):
            assert look.body_plan == kept.plan.name
            assert look.document["origin"] == document["origin"]

        with database.session(world["workspace"]) as connection:
            store = ThingStore(
                connection, world["workspace"], LocalContentAddressedStore(tmp_path / "alternates")
            )
            alternate = store.admit_look(
                document, kept.sketch_container, created_by=world["session"].actor, admit=intake
            ).look
        refreshed = client.get(path, headers=OWNER, params=scope).json()
        assert any(x.get("sha256") == alternate.sha256 for x in refreshed["looks"])
        incompatible = _imported()
        with database.session(world["workspace"]) as connection:
            wrong = (
                ThingStore(
                    connection, world["workspace"], LocalContentAddressedStore(tmp_path / "wrong")
                )
                .admit_look(
                    incompatible,
                    container_of("blocky-traveller"),
                    created_by=world["session"].actor,
                    admit=lambda look: None,
                )
                .look
            )
        assert wrong.sha256 not in {
            x.get("sha256") for x in client.get(path, headers=OWNER, params=scope).json()["looks"]
        }
        rejected = client.post(
            path + "/look",
            headers=OWNER,
            params=scope,
            json={"look": {"source": "workspace", "sha256": wrong.sha256}},
        )
        assert rejected.status_code == 422, rejected.text
        assert (
            client.post(
                path + "/look",
                headers=STRANGER,
                params=scope,
                json={"look": {"source": "workspace", "sha256": alternate.sha256}},
            ).status_code
            == 404
        )
        malformed = client.post(
            path + "/look",
            headers=OWNER,
            params=scope,
            json={"look": {"source": "workspace", "sha256": "not-a-digest"}},
        )
        assert malformed.status_code == 422
        shipped = client.post(
            path + "/look",
            headers=OWNER,
            params=scope,
            json={"look": {"look": "blocky-traveller", "version": 1, "sha256": wrong.sha256}},
        )
        assert shipped.status_code == 422 and shipped.json()["code"] == "look_unfit"
        choice = {"source": "workspace", "sha256": alternate.sha256}
        response = client.post(path + "/look", headers=OWNER, params=scope, json={"look": choice})
        assert response.status_code == 200, response.text
        after = response.json()
        assert after["lines"] == before["lines"]
        assert after["society"] == before["society"]
        assert after["thing_id"] == before["thing_id"]
        assert after["look"]["sha256"] == alternate.sha256
        assert (
            client.get(path, headers=OWNER, params=scope).json()["look"]["sha256"]
            == alternate.sha256
        )
        stranger = uuid.uuid4()
        with database.session(stranger) as connection:
            assert thing_card._looks(connection, stranger, kept.kind) == []
        with database.session(world["workspace"]) as connection:
            ThingStore(connection, world["workspace"], None).withdraw_look(
                alternate.look,
                alternate.version,
                "not offered",
                withdrawn_by=world["session"].actor,
            )
        withdrawn = client.get(path, headers=OWNER, params=scope).json()
        assert not any(x.get("sha256") == alternate.sha256 for x in withdrawn["looks"])
        assert withdrawn["look"]["sha256"] == kept.sketch.sha256
        assert (
            client.post(
                path + "/look", headers=OWNER, params=scope, json={"look": choice}
            ).status_code
            == 422
        )
        with database.session(world["workspace"]) as connection:
            ThingStore(connection, world["workspace"], None).erase_creature(
                kept.kind.sha256, erased_by=world["session"].actor
            )
        erased = client.get(path, headers=OWNER, params=scope).json()
        assert erased["looks"] == [] and erased["look"] is None
        assert (
            client.post(
                path + "/look", headers=OWNER, params=scope, json={"look": choice}
            ).status_code
            == 422
        )
