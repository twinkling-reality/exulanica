"""A person's direct request to somebody part way through a stay, as the deployed database takes it.

Every request here goes through ``POST /world/versions/{id}/society/actions`` against the real
application connected as a provisioned runtime role, so the request binding migration 0108
re-creates is what records it. Under an input that records the newest routine a request to
somebody resting is recorded, consumed in the next minute, ends the rest (``called_away``) and
replays; one to the place they are resting at is refused by name. Under an input that records no
routine the same request is refused as it always was, and a walk is left to arrive under either.
"""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.roles import provision_runtime_role
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import build_authored_ground_society_input_v2
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

import test_society_authored_world_postgres as helpers
from conftest import scratch_role_database
from test_society_saved_world_api import OWNER, TOKEN, place, routes
from tests_support_api import EVERY_PERMISSION

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
ROLE = "exulanica_stay_requests_suite"


@pytest.fixture
def app(saved_world, spine_schema, monkeypatch):
    """The application over the saved world, as the runtime role a deployment runs as."""
    world = saved_world
    world["connection"].commit()
    _psycopg, scratch = spine_schema
    provision_runtime_role(world["connection"], role=ROLE)
    database = scratch_role_database(scratch, ROLE)
    with database.session(world["workspace"]) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(world["workspace"]),
                    "actor": str(world["session"].actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    services = Services(
        database=database,
        readonly_database=database,
        store=world["store"],
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
        society_runtime=runtime,
    )
    # A server error is an answer here, never an exception to stop at: it is what this file is for.
    with TestClient(create_app(services, verify=False), raise_server_exceptions=False) as client:
        yield world, client


def _no_routine(monkeypatch) -> None:
    """Compose the world as the runtime did before inputs recorded a routine."""
    import exulanica.api.society_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_authored_ground_society_input_v3",
        build_authored_ground_society_input_v2,
    )


def _inhabited(world, client) -> dict[str, Any]:
    """Three places to rest and one to visit in front of the person, and people brought in."""
    for index, (x_mm, z_mm) in enumerate(((3_000, 5_000), (-3_000, 5_000), (0, 9_000))):
        place(client, world, f"object:plate-{index}", x_mm, z_mm)
    place(client, world, "object:pillar", 6_000, 9_000, asset="pillar")
    scope, _, society = routes(world)
    created = client.post(
        society,
        headers=OWNER,
        params=scope,
        json={
            "region_id": world["binding"].region_id,
            "seed": "7a" * 32,
            "profile": "exulanica-society/v2",
        },
    )
    assert created.status_code in (200, 201), created.text
    return client.get(society, headers=OWNER, params={**scope, "places": "true"}).json()


def _step(world, client, snapshot: dict[str, Any]) -> dict[str, Any]:
    scope, _, society = routes(world)
    stepped = client.post(
        society + "/steps",
        headers=OWNER,
        params=scope,
        json={"base_tick": snapshot["current_tick"], "base_state_sha256": snapshot["state_sha256"]},
    )
    assert stepped.status_code == 200, stepped.text
    return client.get(society, headers=OWNER, params={**scope, "places": "true"}).json()


def _resting(snapshot: dict[str, Any]) -> dict[str, Any] | None:
    return next(
        (
            person
            for person in snapshot["state"]["inhabitants"]
            if person["action"]["kind"] == "rest"
            and person["action"]["status"] == "active"
            and person["action"]["remaining_ticks"] >= 2
        ),
        None,
    )


def _until_resting(world, client) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = _inhabited(world, client)
    for _ in range(40):
        snapshot = _step(world, client, snapshot)
        person = _resting(snapshot)
        if person is not None:
            return snapshot, person
    raise AssertionError("nobody rested in forty minutes")


def _ask(world, client, snapshot, person, target_id):
    scope, _, society = routes(world)
    return client.post(
        society + "/actions",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "base_tick": snapshot["current_tick"],
            "base_state_sha256": snapshot["state_sha256"],
            "subject_id": person["id"],
            "intent": {"kind": "go_to", "target_id": target_id},
        },
    )


def _elsewhere(snapshot, person) -> str:
    """Another place to rest, one nobody is at or on the way to."""
    taken = {
        other["target"]["target_id"]
        for other in snapshot["state"]["inhabitants"]
        if other["target"] is not None
    }
    return next(
        target["target_id"]
        for target in snapshot["places"]["targets"]
        if target["enabled"]
        and target["affordance"] == "rest"
        and target["target_id"] != person["target"]["target_id"]
        and target["target_id"] not in taken
    )


def _other(snapshot, person) -> str:
    """Any other place: a request refused for what the person is doing never reaches it."""
    return next(
        target["target_id"]
        for target in snapshot["places"]["targets"]
        if target["enabled"] and target["target_id"] != (person["target"] or {}).get("target_id")
    )


def _recorded(world) -> int:
    connection = world["connection"]
    row = connection.execute(
        "select count(*) as n from world_society_action_request where workspace_id=%s",
        (world["workspace"],),
    ).fetchone()
    return row["n"]


def test_under_the_newest_routine_a_request_to_somebody_resting_is_taken_and_ends_the_rest(app):
    world, client = app
    snapshot, person = _until_resting(world, client)
    # Asked to go where they are resting now: refused by name, and nothing is recorded.
    here = _ask(world, client, snapshot, person, person["target"]["target_id"])
    assert here.status_code == 409, here.text
    assert here.json() == {"code": "invalid_society_action", "detail": "inhabitant_already_there"}
    assert _recorded(world) == 0
    target_id = _elsewhere(snapshot, person)
    asked = _ask(world, client, snapshot, person, target_id)
    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "pending"
    after = _step(world, client, snapshot)
    moved = next(p for p in after["state"]["inhabitants"] if p["id"] == person["id"])
    assert moved["goal"]["target_id"] == target_id
    assert moved["goal"]["reason"] == "remembered_target_selected"
    connection = world["connection"]
    reasons = [
        row["document"]["reason"]
        for row in connection.execute(
            "select document from world_society_event where workspace_id=%s and tick=%s "
            "and subject_id=%s and event_kind='replanned'",
            (world["workspace"], after["current_tick"], uuid.UUID(person["id"])),
        ).fetchall()
    ]
    assert reasons == ["called_away"]
    consumed = connection.execute(
        "select disposition from world_society_transition_action where workspace_id=%s",
        (world["workspace"],),
    ).fetchall()
    assert [row["disposition"] for row in consumed] == ["applied"]
    scope, _, society = routes(world)
    replay = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replay.status_code == 200 and replay.json()["replay_verified"], replay.text


def test_under_an_input_with_no_routine_a_request_to_somebody_resting_is_refused(app, monkeypatch):
    world, client = app
    _no_routine(monkeypatch)
    snapshot, person = _until_resting(world, client)
    connection = world["connection"]
    profiles = {
        row["document"]["profile"]
        for row in connection.execute(
            "select document from world_society_input where workspace_id=%s", (world["workspace"],)
        ).fetchall()
    }
    # A positive control: every input this society read records no routine.
    assert profiles == {"exulanica.society-input/authored-ground-v2"}
    asked = _ask(world, client, snapshot, person, _other(snapshot, person))
    assert asked.status_code == 409, asked.text
    assert asked.json() == {
        "code": "invalid_society_action",
        "detail": "inhabitant_action_in_progress",
    }
    assert _recorded(world) == 0


def _walking(world, snapshot) -> tuple[dict[str, Any], dict[str, Any]]:
    """The stored society with one person part way to a place, and that person.

    A walk outlasts a minute only where it is longer than a minute's budget of 60 m, which this
    world is too small to hold, so the state records one as a larger world would: a person at a
    node on the way, with a route to the next one. Written as a test-only administrative change,
    with its digest.
    """
    connection = world["connection"]
    stored = connection.execute(
        "select society_id,state from world_society where workspace_id=%s",
        (world["workspace"],),
    ).fetchone()
    state = deepcopy(stored["state"])
    document = connection.execute(
        "select document from world_society_input where workspace_id=%s "
        "order by input_seq desc limit 1",
        (world["workspace"],),
    ).fetchone()["document"]
    edges = document["navigation"]["edges"]
    target = next(t for t in document["targets"] if t["enabled"])
    person = next(p for p in state["inhabitants"] if p["location"]["edge"] is None)
    here = person["location"]["node_id"]
    edge = next(e for e in edges if here in (e["from_node_id"], e["to_node_id"]))
    there = edge["to_node_id"] if edge["from_node_id"] == here else edge["from_node_id"]
    person.update(
        goal={
            "kind": target["affordance"],
            "target_id": target["target_id"],
            "reason": "restore_need",
        },
        target=deepcopy(target),
        route={
            "node_ids": [here, there],
            "edge_index": 0,
            "edge_progress_mm": 0,
            "destination_node_id": there,
            "input_sha256": document["document_sha256"],
        },
        action={
            "kind": "move",
            "status": "active",
            "target_id": target["target_id"],
            "remaining_ticks": 0,
            "reason": "following_reachable_route",
        },
    )
    connection.execute(
        "update world_society set state=%s,state_sha256=%s where workspace_id=%s and society_id=%s",
        (Jsonb(state), society_state_sha256(state), world["workspace"], stored["society_id"]),
    )
    connection.commit()
    return person, {
        **snapshot,
        "state": state,
        "state_sha256": society_state_sha256(state),
    }


@pytest.mark.parametrize("routine", ["newest", "none"])
def test_a_walker_is_left_to_arrive_under_either_input(app, monkeypatch, routine):
    world, client = app
    if routine == "none":
        _no_routine(monkeypatch)
    snapshot = _step(world, client, _inhabited(world, client))
    person, walking = _walking(world, snapshot)
    scope, _, society = routes(world)
    held = client.get(society, headers=OWNER, params=scope).json()
    assert held["state_sha256"] == walking["state_sha256"]
    asked = _ask(world, client, walking, person, _other(snapshot, person))
    assert asked.status_code == 409, asked.text
    assert asked.json() == {
        "code": "invalid_society_action",
        "detail": "inhabitant_action_in_progress",
    }
    assert _recorded(world) == 0
