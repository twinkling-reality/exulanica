"""Each world's society starts from the world's own seed, derived by the server and never served.

The create route takes no seed. The server derives it from the world's identity, its workspace and
its id (:func:`exulanica.world.society.world_society_seed`), so two worlds start their people
differently where one seed the page sent once started them all alike, and a world's people are
the same people across its versions: a new version brought in again draws the same roles, needs
and first places over the same ground. A society stored before keeps the seed it recorded and
replays byte for byte. No response carries a seed, only its digest.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from types import SimpleNamespace

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.society import (
    SEED_FIELD,
    served_document,
    served_snapshot,
    world_society_seed,
)
from fastapi.testclient import TestClient

import test_society_saved_world_api as saved_api
from society_seed_support import choose_society_seed

saved_world = saved_api.saved_world
world_app = saved_api.world_app
pytestmark = pytest.mark.postgres

#: The seed the page sent for every saved world's society, before the server derived one.
PAGE_SEED = "7a" * 32


def test_the_seed_is_the_worlds_own_and_names_no_version():
    workspace, other_workspace = uuid.uuid4(), uuid.uuid4()
    seed = world_society_seed(workspace, "world:personal:a")
    assert seed == world_society_seed(workspace, "world:personal:a")
    assert len(seed) == 64 and set(seed) <= set("0123456789abcdef")
    assert seed != world_society_seed(workspace, "world:personal:b")
    # A world is its workspace and its id together: the same id elsewhere is another world.
    assert seed != world_society_seed(other_workspace, "world:personal:a")
    # The document the seed is the digest of: the world's identity, and nothing about a version.
    document = {
        "profile": "exulanica.society-seed/v1",
        "workspace_id": str(workspace),
        "world_id": "world:personal:a",
    }
    assert seed == hashlib.sha256(canonical_json(document)).hexdigest()


def test_a_served_society_carries_the_seeds_digest_and_never_the_seed():
    state = {"profile": "exulanica-society/v2", SEED_FIELD: PAGE_SEED, "tick": 3}
    snapshot = {"seed": PAGE_SEED, "state": state, "state_sha256": "a" * 64}
    served = served_snapshot(snapshot)
    digest = hashlib.sha256(PAGE_SEED.encode()).hexdigest()
    assert served["seed_digest"] == digest and served["state"]["seed_digest"] == digest
    assert PAGE_SEED not in json.dumps(served)
    # The stored documents are untouched: their digests still name the bytes that were stored.
    assert snapshot["seed"] == PAGE_SEED and state[SEED_FIELD] == PAGE_SEED
    first = {"profile": "exulanica-society/v1", "tick": 0}
    assert served_document(first) is first


def _furnish(client, world) -> None:
    for index, (x_mm, z_mm) in enumerate(((3_000, 5_000), (-3_000, 5_000))):
        saved_api.place(client, world, f"object:plate-{index}", x_mm, z_mm)


def _bring_in(client, world) -> dict:
    brought = saved_api.bring_inhabitants(client, world)
    assert brought.status_code in (200, 201), brought.text
    return brought.json()


def _starter_world(client, world, title: str) -> dict:
    """Another saved world in the same workspace, made the way the page makes one."""
    made = client.post("/world-entries/starter", headers=saved_api.OWNER, json={"title": title})
    assert made.status_code == 200, made.text
    entry = made.json()
    binding = SimpleNamespace(
        world_id=entry["world_id"],
        version_id=uuid.UUID(entry["authored_version_id"]),
        region_id=entry["authored_scene"]["region"]["region_id"],
    )
    return {**world, "binding": binding}


def _people(snapshot: dict) -> list[tuple]:
    """What the seed decides about each person at genesis, by ordinal."""
    return [
        (
            person["display_name"],
            person["role"],
            person["position_mm"],
            person["need_milli"],
            person["schedule"],
        )
        for person in snapshot["state"]["inhabitants"]
    ]


def _unserved(value: object) -> None:
    text = json.dumps(value)
    assert f'"{SEED_FIELD}"' not in text and '"seed"' not in text


def test_two_worlds_start_differently_and_one_worlds_versions_alike(world_app):
    world, make_app, _runtime, _database = world_app
    with TestClient(make_app()) as client:
        _furnish(client, world)
        first = _bring_in(client, world)
        other = _starter_world(client, world, "Another world")
        _furnish(client, other)
        second = _bring_in(client, other)
        # A new version of the first world, branched with its objects, brought in again.
        branched = client.post(
            "/world/versions",
            headers=saved_api.OWNER,
            params={"world_id": world["binding"].world_id},
            json={"title": "Next", "parent_version_id": str(world["binding"].version_id)},
        )
        assert branched.status_code == 201, branched.text
        version = {
            **world,
            "binding": SimpleNamespace(
                world_id=world["binding"].world_id,
                version_id=uuid.UUID(branched.json()["version_id"]),
                region_id=world["binding"].region_id,
            ),
        }
        again = _bring_in(client, version)
        scope, _, society = saved_api.routes(world)
        events = client.get(society + "/events", headers=saved_api.OWNER, params=scope).json()
    workspace = world["workspace"]
    for snapshot, owner in ((first, world), (second, other)):
        seed = world_society_seed(workspace, owner["binding"].world_id)
        assert snapshot["seed_digest"] == hashlib.sha256(seed.encode()).hexdigest()
        _unserved(snapshot)
    _unserved(events)
    # Two worlds: two seeds, so the same ground and the same objects start different people.
    assert first["seed_digest"] != second["seed_digest"]
    assert _people(first) != _people(second)
    # One world, a second version: another society, the same seed, the same people.
    assert again["society_id"] != first["society_id"]
    assert again["seed_digest"] == first["seed_digest"]
    assert _people(again) == _people(first)


def test_an_edit_keeps_every_person_as_they_were(world_app):
    world, make_app, _runtime, _database = world_app
    with TestClient(make_app()) as client:
        _furnish(client, world)
        before = _bring_in(client, world)
        saved_api.place(client, world, "object:pillar", 6_000, 9_000, asset="pillar")
        scope, _, society = saved_api.routes(world)
        after = client.get(society, headers=saved_api.OWNER, params=scope).json()
    # The edit is an input queued to the same society; nobody is made again.
    assert after["society_id"] == before["society_id"]
    assert after["seed_digest"] == before["seed_digest"]
    assert [p["id"] for p in after["state"]["inhabitants"]] == [
        p["id"] for p in before["state"]["inhabitants"]
    ]
    assert _people(after) == _people(before)


def test_a_society_stored_under_the_page_seed_keeps_it_and_replays(world_app):
    world, make_app, _runtime, _database = world_app
    with TestClient(make_app()) as client:
        _furnish(client, world)
        # Stored as the route stored it when the page sent its seed.
        choose_society_seed(client.app, PAGE_SEED)
        stored = _bring_in(client, world)
        client.app.state.services = dataclasses.replace(
            client.app.state.services, society_seed=world_society_seed
        )
        scope, _, society = saved_api.routes(world)
        for _ in range(3):
            read = client.get(society, headers=saved_api.OWNER, params=scope).json()
            stepped = client.post(
                society + "/steps",
                headers=saved_api.OWNER,
                params=scope,
                json={"base_tick": read["current_tick"], "base_state_sha256": read["state_sha256"]},
            )
            assert stepped.status_code == 200, stepped.text
        replay = client.get(society + "/replay", headers=saved_api.OWNER, params=scope)
        again = client.post(
            society,
            headers=saved_api.OWNER,
            params=scope,
            json={"region_id": world["binding"].region_id, "profile": saved_api.V2},
        )
    page = hashlib.sha256(PAGE_SEED.encode()).hexdigest()
    assert stored["seed_digest"] == page
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"] and replay.json()["seed_digest"] == page
    # Bringing people in again reads back the society stored, with the seed it recorded.
    assert again.status_code == 200, again.text
    assert again.json()["seed_digest"] == page
    row = (
        world["connection"]
        .execute(
            "select seed from world_society where workspace_id=%s and version_id=%s",
            (world["workspace"], world["binding"].version_id),
        )
        .fetchone()
    )
    assert row["seed"] == PAGE_SEED
