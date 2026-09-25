"""A person brings inhabitants into their own saved world with one request, and nothing else does.

No host registration takes part: the runtime here is built with none, the way every instance now
builds one. The world's own starter snapshot says where inhabitants walk, the society binds a
place derived from the authored version, and the place, the first input and the society are made
together or not at all. Every step is an authenticated request against the real application.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.api.society_runtime import (
    SAVED_WORLD_BINDING_PREFIX,
    SocietyRuntime,
    saved_world_place_id,
)
from exulanica.selection.validation import Session
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import LeaseLost
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.starter import AUTHORED_GROUND_MODULE_VERSION
from fastapi.testclient import TestClient

import test_society_authored_world_postgres as helpers
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import registered_world

saved_world = helpers.saved_world
pytestmark = pytest.mark.postgres
TOKEN = "saved-world-inhabitants-owner-token-long-enough"
STRANGER_TOKEN = "saved-world-inhabitants-stranger-token-long-enough"
OWNER = {"Authorization": f"Bearer {TOKEN}"}
STRANGER = {"Authorization": f"Bearer {STRANGER_TOKEN}"}
V2 = "exulanica-society/v2"
#: What placing an object in front of yourself stores: it turns to face you. Every placement in
#: this file is turned, because every fixture at yaw zero is how a turned object once went unseen.
FACING_THE_PERSON = 3_141_593


@pytest.fixture
def world_app(saved_world, spine_schema, monkeypatch):
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
    # No registration of any kind: what the person asks for is all there is.
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    database = scratch_database(spine_schema[1])

    def make_app():
        return create_app(
            Services(
                database=database,
                readonly_database=database,
                store=world["store"],
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=None,
                society_runtime=runtime,
            ),
            verify=False,
        )

    return world, make_app, runtime, database


def routes(world):
    binding = world["binding"]
    version = f"/world/versions/{binding.version_id}"
    return {"world_id": binding.world_id}, version, version + "/society"


def place(client, world, object_id, x_mm, z_mm, asset="plate", yaw=FACING_THE_PERSON):
    scope, version, _ = routes(world)
    base = client.get(version, headers=OWNER, params=scope).json()["state_sha256"]
    response = client.post(
        version + "/objects",
        headers=OWNER,
        params=scope,
        json={
            "base_state_sha256": base,
            "object_id": object_id,
            "asset_sha256": world[asset].content_sha256,
            "region_id": world["binding"].region_id,
            "transform": {
                "x_mm": x_mm,
                "y_mm": 0,
                "z_mm": z_mm,
                "yaw_microradians": yaw,
                "scale_milli": 1000,
            },
            "origin_role": "fictional",
        },
    )
    assert response.status_code == 201, response.text


def bring_inhabitants(client, world, profile=V2):
    """The person's one explicit action: a society for this world, with no place named."""
    scope, _, society = routes(world)
    return client.post(
        society,
        headers=OWNER,
        params=scope,
        json={"region_id": world["binding"].region_id, "seed": "7a" * 32, "profile": profile},
    )


def held(world):
    """Every row the action can create, counted in this workspace."""
    connection = world["connection"]
    counts = {}
    for table, where in (
        ("place", "place_id=%(place)s"),
        ("world_society", "true"),
        ("world_society_input", "true"),
    ):
        counts[table] = connection.execute(
            f"select count(*) as n from {table} where workspace_id=%(ws)s and {where}",
            {"ws": world["workspace"], "place": saved_world_place_id(world["binding"].version_id)},
        ).fetchone()["n"]
    connection.commit()
    return counts


NOTHING = {"place": 0, "world_society": 0, "world_society_input": 0}


def test_one_request_brings_inhabitants_in_and_asking_again_changes_nothing(world_app):
    world, make_app, _, _ = world_app
    scope, _, society_route = routes(world)
    derived_place = saved_world_place_id(world["binding"].version_id)
    with TestClient(make_app()) as client:
        # An empty world has somewhere to stand and nothing to do. The refusal says so by name,
        # and the place it would have bound is not left behind.
        response = bring_inhabitants(client, world)
        assert response.status_code == 409, response.text
        assert response.json() == {
            "code": "no_reachable_targets",
            "detail": "initial society requires reachable targets",
        }
        assert held(world) == NOTHING

        place(client, world, "object:cushion", 3_000, 5_000)
        response = bring_inhabitants(client, world)
        assert response.status_code == 200, response.text
        society = response.json()
        assert society["profile"] == V2 and society["current_tick"] == 0
        # A handful of people, none where a person arrives in the world.
        assert society["population_size"] == len(society["state"]["inhabitants"]) == 8
        assert all(
            (p["position_mm"][0] - 0) ** 2 + (p["position_mm"][1] - 4_000) ** 2 > 2_000**2
            for p in society["state"]["inhabitants"]
        )
        # The place is derived from the version the way the society's own identity is.
        assert society["place_id"] == str(derived_place)
        assert uuid.UUID(society["society_id"]) == uuid.uuid5(
            world["binding"].version_id, "exulanica-society/v1"
        )
        assert held(world) == {"place": 1, "world_society": 1, "world_society_input": 1}

        again = bring_inhabitants(client, world)
        assert again.status_code == 200, again.text
        assert again.json()["society_id"] == society["society_id"]
        assert again.json()["state_sha256"] == society["state_sha256"]
        assert held(world) == {"place": 1, "world_society": 1, "world_society_input": 1}

        # The input binds the binding derived from the world itself, and nothing a host wrote.
        document = (
            world["connection"]
            .execute(
                "select document from world_society_input where workspace_id=%s",
                (world["workspace"],),
            )
            .fetchone()["document"]
        )
        world["connection"].commit()
        [registration] = [
            ref for ref in document["dependency_refs"] if ref["kind"] == "society_runtime_binding"
        ]
        assert registration["identity"] == (
            f"{SAVED_WORLD_BINDING_PREFIX}{world['binding'].version_id}"
        )

        # A plain read is unchanged; asking for places adds them, from the consumed input.
        assert "places" not in client.get(society_route, headers=OWNER, params=scope).json()
        read = client.get(society_route, headers=OWNER, params={**scope, "places": "true"})
        assert read.status_code == 200, read.text
        places = read.json()["places"]
        assert places["input_seq"] == 1 and places["availability"] == "available"
        [target] = places["targets"]
        assert (target["object_id"], target["affordance"]) == ("object:cushion", "rest")
        assert places["unavailable_affordances"] == []
        expected = {1: "ground", 2: "declared"}[world["ground_module_version"]]
        assert places["walkable_area"]["source"] == expected
        assert places["walkable_area"]["half_width_mm"] == 12_000
        assert places["clearance_mm"] == 450

        assert client.get(society_route, headers=STRANGER, params=scope).status_code == 404
        # Named in another world this workspace holds, the fixture's, the version is not in it: a
        # missing version, and still nothing written.
        elsewhere = {"world_id": registered_world(world["connection"], world["workspace"])}
        world["connection"].commit()
        assert (
            client.post(
                society_route,
                headers=OWNER,
                params=elsewhere,
                json={"region_id": world["binding"].region_id, "seed": "8b" * 32, "profile": V2},
            ).status_code
            == 404
        )
        assert held(world) == {"place": 1, "world_society": 1, "world_society_input": 1}


def test_an_object_placed_facing_the_person_lets_inhabitants_in(world_app):
    """The defect this lane found: every normally placed object used to make the world unusable."""
    world, make_app, _, _ = world_app
    scope, _, society_route = routes(world)
    with TestClient(make_app()) as client:
        # Exactly what the browser stored for "Place before me" at the spawn.
        place(client, world, "object-1-1", 0, 500, yaw=FACING_THE_PERSON)
        response = bring_inhabitants(client, world)
        assert response.status_code == 200, response.text
        places = client.get(
            society_route, headers=OWNER, params={**scope, "places": "true"}
        ).json()["places"]
    assert places["availability"] == "available"
    assert [(t["object_id"], t["affordance"]) for t in places["targets"]] == [
        ("object-1-1", "rest")
    ]


def test_the_living_society_is_refused_in_a_saved_world_and_leaves_nothing(world_app):
    world, make_app, _, _ = world_app
    with TestClient(make_app()) as client:
        place(client, world, "object:cushion", 3_000, 5_000)
        response = bring_inhabitants(client, world, "exulanica-society/v4")
        assert response.status_code == 422, response.text
        assert "no place contract for an authored ground" in response.json()["detail"]
        assert held(world) == NOTHING


def test_an_object_outside_the_walkable_area_is_named_as_one_nobody_can_reach(world_app):
    world, make_app, _, _ = world_app
    scope, _, society_route = routes(world)
    with TestClient(make_app()) as client:
        place(client, world, "object:cushion", 3_000, 5_000)
        # 11,550 mm is the area's half extent less the clearance, on either axis. One plate just
        # inside it on the east axis and one just past it on the south axis.
        place(client, world, "object:near-edge", 11_000, 0)
        place(client, world, "object:far", 0, 12_000)
        assert bring_inhabitants(client, world).status_code == 200
        places = client.get(
            society_route, headers=OWNER, params={**scope, "places": "true"}
        ).json()["places"]
    assert sorted(t["object_id"] for t in places["targets"]) == [
        "object:cushion",
        "object:near-edge",
    ]
    [far] = places["unavailable_affordances"]
    assert far["object_id"] == "object:far"
    assert far["reason"] == "authored_affordance_unreachable"
    assert far["affordance"] == "rest"


def test_the_playback_worker_advances_a_society_in_a_saved_world(world_app):
    world, make_app, runtime, database = world_app
    scope, _, society_route = routes(world)
    with TestClient(make_app()) as client:
        place(client, world, "object:cushion", 3_000, 5_000)
        assert bring_inhabitants(client, world).status_code == 200
        control = client.get(society_route + "/control", headers=OWNER, params=scope).json()
        response = client.put(
            society_route + "/control",
            headers=OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert response.status_code == 200, response.text
        world["connection"].execute(
            "update world_society_control set next_due_at=clock_timestamp()-interval '5 seconds' "
            "where workspace_id=%s",
            (world["workspace"],),
        )
        world["connection"].commit()
        worker = SocietyControlWorker(database, runtime=runtime, workspaces=[world["workspace"]])
        # Before the claim spanned worlds this returned None: the society is not in the default
        # world, and the worker only ever looked there.
        result = worker.run_once(world["workspace"])
        assert result is not None and result["receipt"]["kind"] == "advanced"
        assert result["receipt"]["executed_ticks"] >= 1
        after = client.get(society_route, headers=OWNER, params=scope).json()
        assert after["current_tick"] == result["receipt"]["tick_to"] >= 1


@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_one_claim_per_round_across_worlds_and_it_runs_only_in_its_own(saved_world):
    """Two saved worlds in one workspace compete for claims by due time, not by world."""
    world = saved_world
    connection = world["connection"]
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    second_id = f"world:authored:{uuid.uuid4()}"
    with connection.transaction():
        _, second_version = helpers.make_starter(
            connection, world["workspace"], world["session"].actor, second_id, 2
        )
    worlds = {world["world_id"]: world["binding"].version_id, second_id: second_version}
    for world_id, version_id in worlds.items():
        objects = helpers.objects_repository({**world, "world_id": world_id}, runtime)
        version = objects.version(version_id)
        objects.add_object(
            version_id,
            helpers.AuthoredObject(
                object_id="object:cushion",
                asset_sha256=world["plate"].content_sha256,
                region_id=world["binding"].region_id,
                transform=helpers.Transform(
                    x_mm=3_000,
                    y_mm=0,
                    z_mm=5_000,
                    yaw_microradians=FACING_THE_PERSON,
                    scale_milli=1000,
                ),
                origin=helpers.ObjectOrigin("authored", "fictional"),
            ),
            base_state_sha256=version.state_sha256,
            actor=world["session"].actor,
        )
        society = SocietyRepository(
            connection,
            world["workspace"],
            world_id=world_id,
            input_authorizer=lambda doc: runtime.authorize(connection, world["session"], doc),
        )
        with connection.transaction():
            place_id = runtime.saved_world_place(connection, world["session"], version_id)
            society.create(
                version_id,
                place_id=place_id,
                region_id=world["binding"].region_id,
                seed="7a" * 32,
                actor=world["session"].actor,
                profile=V2,
                initial_input=runtime.initial_input(
                    connection, world["session"], version_id, None, world["binding"].region_id
                ),
            )
        controls(connection, world, runtime, world_id).configure(
            version_id, actor=world["session"].actor, base_revision=0, mode="playing", speed=1
        )
    # The second world has waited longer, so it is claimed first. The claim is the workspace's,
    # not any one world's, and names the world it was taken in.
    for world_id, seconds in ((world["world_id"], 5), (second_id, 50)):
        connection.execute(
            "update world_society_control c set next_due_at=clock_timestamp()"
            "-make_interval(secs=>%s) from world_society s where s.workspace_id=c.workspace_id "
            "and s.society_id=c.society_id and s.world_id=%s and c.workspace_id=%s",
            (seconds, world_id, world["workspace"]),
        )
    connection.commit()
    claiming = controls(connection, world, runtime, world["world_id"])
    first = SocietyControlRepository.claim_in_workspace(
        connection, world["workspace"], input_authorizer=claiming.input_authorizer
    )
    assert (first.world_id, first.version_id) == (second_id, second_version)
    with pytest.raises(LeaseLost, match="another world"):
        claiming.execute(first)
    executed = controls(connection, world, runtime, second_id).execute(first)
    assert executed["receipt"]["kind"] == "advanced"
    second = SocietyControlRepository.claim_in_workspace(
        connection, world["workspace"], input_authorizer=claiming.input_authorizer
    )
    assert (second.world_id, second.version_id) == (world["world_id"], world["binding"].version_id)
    assert claiming.execute(second)["receipt"]["kind"] == "advanced"


def controls(connection, world, runtime, world_id):
    return SocietyControlRepository(
        connection,
        world["workspace"],
        world_id=world_id,
        input_authorizer=lambda actor, doc: runtime.authorize(
            connection, Session(workspace_id=world["workspace"], actor=actor), doc
        ),
    )


@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_an_edit_in_a_world_holding_no_society_takes_no_global_lock(saved_world):
    """Every instance now observes every accepted edit, in every workspace.

    The asset read lock is one exclusive lock for the whole database. Taken on each edit it would
    queue every workspace's edits behind each other, so the observer takes it only for a version
    that holds a society which reads assets.
    """
    world = saved_world
    connection = world["connection"]
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    held_lock = (
        "select count(*) as n from pg_locks where locktype='advisory' and pid=pg_backend_pid() "
        "and classid=0 and objid=119622341 and objsubid=1 and mode='ExclusiveLock'"
    )
    with connection.transaction():
        runtime.authored_edit(connection, world["session"], world["binding"].version_id)
        assert connection.execute(held_lock).fetchone()["n"] == 0
    add_turned(world, runtime, "object:cushion", 3_000, 5_000, FACING_THE_PERSON)
    with connection.transaction():
        place_id = runtime.saved_world_place(
            connection, world["session"], world["binding"].version_id
        )
        helpers.society_repository(world, runtime).create(
            world["binding"].version_id,
            place_id=place_id,
            region_id=world["binding"].region_id,
            seed="7a" * 32,
            actor=world["session"].actor,
            profile=V2,
            initial_input=runtime.initial_input(
                connection,
                world["session"],
                world["binding"].version_id,
                None,
                world["binding"].region_id,
            ),
        )
    # A positive control: the same probe does see the lock once there is a society to feed.
    with connection.transaction():
        runtime.authored_edit(connection, world["session"], world["binding"].version_id)
        assert connection.execute(held_lock).fetchone()["n"] == 1


def add_turned(world, runtime, object_id, x_mm, z_mm, yaw):
    """Place a plate at a yaw, through the repository and the society's own edit hook."""
    objects = helpers.objects_repository(world, runtime)
    version = objects.version(world["binding"].version_id)
    return objects.add_object(
        version.version_id,
        helpers.AuthoredObject(
            object_id=object_id,
            asset_sha256=world["plate"].content_sha256,
            region_id=world["binding"].region_id,
            transform=helpers.Transform(
                x_mm=x_mm, y_mm=0, z_mm=z_mm, yaw_microradians=yaw, scale_milli=1000
            ),
            origin=helpers.ObjectOrigin("authored", "fictional"),
        ),
        base_state_sha256=version.state_sha256,
        actor=world["session"].actor,
    )


def test_a_society_recorded_under_the_old_rule_still_reads_and_moves_on(saved_world, monkeypatch):
    """Inputs stored while a turned object made the world unusable stay exactly as they were.

    The first saved-world composition, with the rule that refused any turn, is put back for the
    first part, so the society records what it recorded then. With today's composition restored,
    every stored input still authorises (they are matched by their stored bytes, never composed
    again), the society still reads and replays, and the next edit composes a usable world again
    under the newest profile, with nobody stranded.
    """
    import exulanica.api.society_runtime as runtime_module
    import exulanica.world.society_composition as composition
    from exulanica.world.society_authored_ground import build_authored_ground_society_input
    from exulanica.world.society_input_policy import (
        AUTHORED_GROUND_INPUT,
        AUTHORED_GROUND_INPUT_V3,
    )

    def first_composition(*, standing, **arguments):
        # What the runtime composed a saved world with before objects were decided one by one.
        return build_authored_ground_society_input(**arguments)

    world = saved_world
    connection = world["connection"]
    session = world["session"]
    version_id = world["binding"].version_id
    region = world["binding"].region_id
    runtime = SocietyRuntime(
        store=world["store"], authored_bindings=[], reviewed_affordances=world["registry"]
    )
    society = helpers.society_repository(world, runtime)
    monkeypatch.setattr(composition, "AUTHORED_GROUND_COMPOSITION", "the rule before turns")
    monkeypatch.setattr(runtime_module, "build_authored_ground_society_input_v3", first_composition)

    add_turned(world, runtime, "object:cushion", 3_000, 5_000, 0)
    with connection.transaction():
        place_id = runtime.saved_world_place(connection, session, version_id)
        created = society.create(
            version_id,
            place_id=place_id,
            region_id=region,
            seed="7a" * 32,
            actor=session.actor,
            profile=V2,
            initial_input=runtime.initial_input(connection, session, version_id, None, region),
        )
    add_turned(world, runtime, "object:turned", -3_000, 5_000, FACING_THE_PERSON)
    stepped = society.advance(
        version_id, base_tick=created["current_tick"], base_state_sha256=created["state_sha256"]
    )
    monkeypatch.undo()

    stored = [
        row["document"]
        for row in connection.execute(
            "select document from world_society_input where workspace_id=%s order by input_seq",
            (world["workspace"],),
        ).fetchall()
    ]
    assert [d["availability"] for d in stored] == ["available", "unavailable"]
    assert [d["profile"] for d in stored] == [AUTHORED_GROUND_INPUT] * 2
    assert stored[1]["unavailable_reason"] == "unsupported_object_transform:object:turned"
    for document in stored:
        runtime.authorize(connection, session, document)
    assert society.snapshot(version_id)["state_sha256"] == stepped["state_sha256"]
    assert society.replay(version_id)["replay_verified"]

    add_turned(world, runtime, "object:facing", 0, 2_000, 1_570_796)
    latest = connection.execute(
        "select document from world_society_input where workspace_id=%s "
        "order by input_seq desc limit 1",
        (world["workspace"],),
    ).fetchone()["document"]
    assert latest["input_seq"] == 3 and latest["availability"] == "available"
    assert latest["profile"] == AUTHORED_GROUND_INPUT_V3
    assert sorted(t["object_id"] for t in latest["targets"]) == [
        "object:cushion",
        "object:facing",
        "object:turned",
    ]
    moved = society.advance(
        version_id, base_tick=stepped["current_tick"], base_state_sha256=stepped["state_sha256"]
    )
    assert moved["input_seq"] == 3
    assert society.replay(version_id)["replay_verified"]
