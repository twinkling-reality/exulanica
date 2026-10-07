"""Things placed in an authored version by their kind, as the database and the routes hold them.

What is shown, against PostgreSQL:

*   the deployed writer (the runtime role, which may not DELETE) places, moves, removes and undoes a
    thing; an undone addition is a retained, removed row, and the same id may be placed again;
*   what a placed thing is never changes after it is placed: migration 0152's trigger refuses a
    change to its kind or origin, and lets its pose change;
*   a placed thing is its workspace's alone: another workspace's session sees none of its rows,
    under row-level security (every key also includes the workspace, from its first migration);
*   a version branched from another keeps its placed things, and carrying one plans to carry them;
*   the routes place a thing by its kind (the digest filled from the shipped library), answer with
    the whole version, and refuse by name a kind that is not shipped, a digest that is not its own,
    and an id already placed;
*   a version holds a bounded number of things, removed ones included, and refuses one more by
    name; undoing a placement makes room again.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.world import WorldObjectRepository, object_repository
from exulanica.world.object_repository import CarryOutcome
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import ThingPlacement, placed_thing_document

from conftest import scratch_role_database
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_objects_postgres import world as imported_world  # noqa: F401
from thing_fixtures import kind_body, kind_reference, placeable_kind, placeable_kinds

pytestmark = pytest.mark.postgres

POSE = {"x_mm": 2_000, "y_mm": 500, "z_mm": 0, "yaw_microradians": 0}


@pytest.fixture(name="world")
def _world_alias(request):
    return request.getfixturevalue("imported_world")


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _placement(thing_id: str = "thing:placed") -> ThingPlacement:
    return ThingPlacement(
        thing_id=thing_id,
        kind=kind_reference(placeable_kind()),
        region_id="region-a",
        transform=Transform(2_000, 500, 0, 0, 1_000),
        origin=ObjectOrigin("authored", "fictional"),
    )


def _runtime(spine_schema, workspace_id):
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(workspace_id)


def test_the_deployed_writer_places_moves_removes_and_undoes_a_thing(
    world, repository, spine_schema
):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Well", created_by=uuid.uuid4()
    )
    empty = version.state_sha256
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    with _runtime(spine_schema, repository.workspace_id) as connection:
        runtime = WorldObjectRepository(
            connection, repository.workspace_id, world_id=objects.world_id, store=objects.store
        )
        assert (
            connection.execute(
                "select has_table_privilege(current_user,'world_alternate_thing','DELETE') "
                "as allowed"
            ).fetchone()["allowed"]
            is False
        )
        placed = runtime.add_thing(
            version.version_id, _placement(), base_state_sha256=empty, actor=uuid.uuid4()
        )
        [thing] = placed.things
        assert thing.kind.sha256 == placeable_kind().sha256
        assert placed.state_sha256 != empty
        moved = runtime.move_thing(
            version.version_id,
            "thing:placed",
            Transform(-1_000, 0, 0, 1_570_796, 1_000),
            base_state_sha256=placed.state_sha256,
            actor=uuid.uuid4(),
        )
        assert moved.things[0].transform.x_mm == -1_000
        removed = runtime.remove_thing(
            version.version_id,
            "thing:placed",
            base_state_sha256=moved.state_sha256,
            actor=uuid.uuid4(),
        )
        assert removed.things[0].removed is True
        state = removed.state_sha256
        for expected in (moved.state_sha256, placed.state_sha256, empty):
            state = runtime.undo(
                version.version_id, base_state_sha256=state, actor=uuid.uuid4()
            ).state_sha256
            assert state == expected
        assert runtime.version(version.version_id).things == ()
        retained = connection.execute(
            "select removed,addition_undone from world_alternate_thing where workspace_id=%s "
            "and world_id=%s and version_id=%s and thing_id='thing:placed'",
            (repository.workspace_id, objects.world_id, version.version_id),
        ).fetchone()
        assert retained == {"removed": True, "addition_undone": True}
        again = runtime.add_thing(
            version.version_id, _placement(), base_state_sha256=empty, actor=uuid.uuid4()
        )
        assert [thing.thing_id for thing in again.things] == ["thing:placed"]
        assert again.state_sha256 == placed.state_sha256


def test_what_a_placed_thing_is_never_changes_after_it_is_placed(world, repository, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Fixed", created_by=uuid.uuid4()
    )
    objects.add_thing(
        version.version_id,
        _placement("thing:fixed"),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    key = (repository.workspace_id, objects.world_id, version.version_id)
    where = "where workspace_id=%s and world_id=%s and version_id=%s and thing_id='thing:fixed'"
    placed = placeable_kind()
    other = next(kind for kind in placeable_kinds() if kind.kind != placed.kind)
    with _runtime(spine_schema, repository.workspace_id) as connection:
        # The positive control: the pose may change.
        connection.execute(f"update world_alternate_thing set x_mm=x_mm+1 {where}", key)
        for change in (
            f"kind='{other.kind}'",
            f"kind_version={placed.version + 1}",
            "origin_role='personal'",
        ):
            with (
                pytest.raises(psycopg.errors.CheckViolation, match="keeps the kind and origin"),
                connection.transaction(),
            ):
                connection.execute(f"update world_alternate_thing set {change} {where}", key)


def test_a_thing_s_id_is_its_author_s_within_their_own_workspace(world, repository, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Owner", created_by=uuid.uuid4()
    )
    objects.add_thing(
        version.version_id,
        _placement("thing:shared"),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    stranger = uuid.uuid4()
    with _runtime(spine_schema, stranger) as connection:
        # The stranger's own rows only: the owner's thing is invisible under row-level security.
        assert (
            connection.execute("select count(*) as n from world_alternate_thing").fetchone()["n"]
            == 0
        )
    with _runtime(spine_schema, repository.workspace_id) as connection:
        assert (
            connection.execute("select count(*) as n from world_alternate_thing").fetchone()["n"]
            == 1
        )


def test_a_branch_keeps_its_parent_s_things_and_a_carry_plans_to_carry_them(world):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Parent", created_by=uuid.uuid4()
    )
    placed = objects.add_thing(
        version.version_id,
        _placement("thing:carried"),
        base_state_sha256=version.state_sha256,
        actor=uuid.uuid4(),
    )
    branched = objects.branch_version(
        parent_version_id=version.version_id, title="Branch", created_by=uuid.uuid4()
    ).version
    assert [placed_thing_document(thing) for thing in branched.things] == [
        placed_thing_document(thing) for thing in placed.things
    ]
    assert branched.state_sha256 == placed.state_sha256
    plan = objects.carry_plan(version.version_id)
    assert [(part.subject_id, part.outcome) for part in plan.parts] == [
        ("thing:carried", CarryOutcome.CARRIED)
    ]


def test_the_routes_place_a_thing_by_its_kind_and_refuse_by_name(objects_api):
    version = objects_api.version("Things")
    path = objects_api.in_world(f"/world/versions/{version['version_id']}/things")

    kind = placeable_kind()

    def body(**changes):
        sent = {
            "base_state_sha256": version["state_sha256"],
            "thing_id": "thing:placed",
            "kind": kind_body(kind),
            "region_id": "region-a",
            "pose": POSE,
            "origin_role": "fictional",
        }
        sent.update(changes)
        return sent

    for refused, code in (
        (body(kind={"kind": "no_such_kind", "version": 1}), "invalid_thing_placement"),
        (body(kind={**kind_body(kind), "sha256": "a" * 64}), "invalid_thing_placement"),
        (body(region_id="region-z"), "invalid_thing_placement"),
    ):
        answer = objects_api.post(path, refused)
        assert (answer.status_code, answer.json()["code"]) == (422, code), answer.text
    # A pose states no scale: a thing stands at its kind's own size.
    assert objects_api.post(path, body(pose={**POSE, "scale_milli": 2_000})).status_code == 422
    placed = objects_api.post(path, body())
    assert placed.status_code == 201, placed.text
    document = placed.json()
    assert document["schema_version"] == 5
    [placed] = document["things"]
    assert placed["kind"] == {"kind": kind.kind, "sha256": kind.sha256, "version": kind.version}
    assert document["edits"][-1]["kind"] == "add_thing"
    assert document["edits"][-1]["thing_id"] == "thing:placed"
    again = objects_api.post(path, body(base_state_sha256=document["state_sha256"]))
    assert (again.status_code, again.json()["code"]) == (409, "invalid_object_state")
    moved = objects_api.post(
        objects_api.in_world(f"/world/versions/{version['version_id']}/things/thing:placed/move"),
        {"base_state_sha256": document["state_sha256"], "pose": {**POSE, "x_mm": 0}},
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["things"][0]["transform"]["x_mm"] == 0


def test_a_version_holds_a_bounded_number_of_things_and_refuses_one_more_by_name(
    objects_api, monkeypatch
):
    # The bound is the module's declared figure; two keeps the version small and shows the rule.
    monkeypatch.setattr(object_repository, "PLACED_THINGS_MAXIMUM", 2)
    version = objects_api.version("Full")
    root = f"/world/versions/{version['version_id']}"
    state = version["state_sha256"]

    def place(thing_id: str):
        return objects_api.post(
            objects_api.in_world(f"{root}/things"),
            {
                "base_state_sha256": state,
                "thing_id": thing_id,
                "kind": kind_body(placeable_kind()),
                "region_id": "region-a",
                "pose": POSE,
                "origin_role": "fictional",
            },
        )

    for thing_id in ("thing:first", "thing:second"):
        placed = place(thing_id)
        assert placed.status_code == 201, placed.text
        state = placed.json()["state_sha256"]
    removed = objects_api.post(
        objects_api.in_world(f"{root}/things/thing:first/remove"), {"base_state_sha256": state}
    )
    assert removed.status_code == 200, removed.text
    state = removed.json()["state_sha256"]
    # A removed thing stays in the version's delta, so it still counts.
    refused = place("thing:third")
    assert (refused.status_code, refused.json()["code"]) == (409, "thing_limit_reached")
    for _ in range(2):
        undone = objects_api.post(
            objects_api.in_world(f"{root}/things/undo"), {"base_state_sha256": state}
        )
        assert undone.status_code == 200, undone.text
        state = undone.json()["state_sha256"]
    # Undoing the second placement made room again.
    assert place("thing:third").status_code == 201
