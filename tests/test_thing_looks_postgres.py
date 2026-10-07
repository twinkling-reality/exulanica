"""The look each thing of a version wears, as the database and the route hold it.

What is shown, against PostgreSQL:

*   the deployed writer (the runtime role) records a crossing's look once however often the
    crossing is handed over, writes nothing for a look the thing may not wear, may neither change
    nor remove a choice, and reads the latest choice per thing, in thing id order;
*   migration 0156's table holds its shape: a crossing's choice names its crossing and an owner's
    its actor, a placed thing's id names a thing placed in the version, and the append-only trigger
    refuses every change, even the table owner's;
*   a choice is its workspace's alone: another workspace's session sees none of its rows;
*   the route answers ``exulanica.thing-look-choices/v1``, never cached, and an absent version 404.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.world.thing_looks import (
    LOOK_CHOICES_PROFILE,
    ThingLookRefused,
    look_choices,
    record_crossing_look,
)

from conftest import scratch_role_database
from test_thing_looks import _kind, _look
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from test_world_objects_postgres import world as imported_world  # noqa: F401

pytestmark = pytest.mark.postgres

VISITOR = _kind("visitor")
TRAVELLER = _look("blocky-traveller")
KNIGHT = _look("blocky-knight")


@pytest.fixture(name="world")
def _world_alias(request):
    return request.getfixturevalue("imported_world")


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


def _runtime(spine_schema, workspace_id):
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(workspace_id)


def _record(connection, workspace_id, world_id, version_id, thing_id, crossing_id, look):
    return record_crossing_look(
        connection,
        workspace_id=workspace_id,
        world_id=world_id,
        version_id=version_id,
        thing_id=thing_id,
        crossing_id=crossing_id,
        kind=VISITOR,
        look=look,
    )


def test_the_deployed_writer_records_a_crossing_s_look_once_and_reads_the_latest_per_thing(
    world, repository, spine_schema
):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Gate", created_by=uuid.uuid4()
    )
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    first, second = sorted((uuid.uuid4(), uuid.uuid4()), key=str)
    arrival = uuid.uuid4()
    where = (repository.workspace_id, objects.world_id, version.version_id)
    with _runtime(spine_schema, repository.workspace_id) as connection:
        for privilege in ("UPDATE", "DELETE"):
            allowed = connection.execute(
                "select has_table_privilege(current_user,'world_thing_look',%s) as allowed",
                (privilege,),
            ).fetchone()["allowed"]
            assert allowed is False, privilege
        # A look the thing may not wear is refused before anything is written.
        with pytest.raises(ThingLookRefused) as refused:
            _record(connection, *where, second, uuid.uuid4(), _look("primitive-well"))
        assert refused.value.code == "look_unfit"
        assert look_choices(connection, *where)["looks"] == []
        # The same crossing handed over twice records one look; the first stands.
        _record(connection, *where, second, arrival, TRAVELLER)
        _record(connection, *where, second, arrival, KNIGHT)
        _record(connection, *where, first, uuid.uuid4(), KNIGHT)
        read = look_choices(connection, *where)
        assert read["profile"] == LOOK_CHOICES_PROFILE
        assert [(entry["thing_id"], entry["look"]) for entry in read["looks"]] == [
            (str(first), KNIGHT),
            (str(second), TRAVELLER),
        ]
        assert {entry["chosen_by"] for entry in read["looks"]} == {"crossing"}
        assert all(entry["placed_id"] is None for entry in read["looks"])
        assert all(entry["chosen_at"].endswith("Z") for entry in read["looks"])
        # A later choice for the same thing is the one worn, and the earlier one stays.
        connection.execute(
            "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,look,"
            "look_version,look_sha256,chosen_by,actor) values (%s,%s,%s,%s,%s,%s,%s,'owner',%s)",
            (*where, second, KNIGHT["look"], 1, bytes.fromhex(KNIGHT["sha256"]), uuid.uuid4()),
        )
        [_, later] = look_choices(connection, *where)["looks"]
        assert (later["look"], later["chosen_by"]) == (KNIGHT, "owner")
        assert (
            connection.execute(
                "select count(*) as n from world_thing_look where thing_id=%s", (second,)
            ).fetchone()["n"]
            == 2
        )


def test_the_table_holds_its_shape_and_refuses_every_change(world, repository):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Shape", created_by=uuid.uuid4()
    )
    where = (repository.workspace_id, objects.world_id, version.version_id)
    connection = repository.connection
    _record(connection, *where, uuid.uuid4(), uuid.uuid4(), TRAVELLER)
    connection.commit()
    insert = (
        "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,placed_id,look,"
        "look_version,look_sha256,chosen_by,crossing_id,actor) "
        "values (%s,%s,%s,%s,%s,%s,1,%s,%s,%s,%s)"
    )
    digest = bytes.fromhex(TRAVELLER["sha256"])
    refused = [
        # A crossing's choice without its crossing, and an owner's without its actor.
        (None, "crossing", None, None, psycopg.errors.CheckViolation),
        (None, "owner", None, None, psycopg.errors.CheckViolation),
        (None, "owner", uuid.uuid4(), uuid.uuid4(), psycopg.errors.CheckViolation),
        # A placed thing's id must name a thing placed in this version.
        ("thing:absent", "owner", None, uuid.uuid4(), psycopg.errors.ForeignKeyViolation),
    ]
    for placed_id, chosen_by, crossing_id, actor, error in refused:
        with pytest.raises(error):
            connection.execute(
                insert,
                (
                    *where,
                    uuid.uuid4(),
                    placed_id,
                    TRAVELLER["look"],
                    digest,
                    chosen_by,
                    crossing_id,
                    actor,
                ),
            )
        connection.rollback()
    for change in (
        "update world_thing_look set look='blocky-knight'",
        "delete from world_thing_look",
    ):
        with pytest.raises(psycopg.errors.CheckViolation, match="appended and never changed"):
            connection.execute(change)
        connection.rollback()


def test_a_choice_is_its_workspace_s_alone(world, repository, spine_schema):
    objects, snapshot, _ = world
    version = objects.create_version(
        source_snapshot_id=snapshot.snapshot_id, title="Mine", created_by=uuid.uuid4()
    )
    _record(
        repository.connection,
        repository.workspace_id,
        objects.world_id,
        version.version_id,
        uuid.uuid4(),
        uuid.uuid4(),
        TRAVELLER,
    )
    repository.connection.commit()
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    with _runtime(spine_schema, repository.workspace_id) as mine:
        # The positive control: the owner's own session sees the row.
        assert mine.execute("select count(*) as n from world_thing_look").fetchone()["n"] == 1
    with _runtime(spine_schema, uuid.uuid4()) as theirs:
        assert theirs.execute("select count(*) as n from world_thing_look").fetchone()["n"] == 0


def test_the_route_answers_the_latest_look_per_thing_and_404s_an_absent_version(
    objects_api, repository
):
    version = objects_api.version("Looks")
    thing, arrival = uuid.uuid4(), uuid.uuid4()
    _record(
        repository.connection,
        repository.workspace_id,
        objects_api.world_id,
        uuid.UUID(version["version_id"]),
        thing,
        arrival,
        TRAVELLER,
    )
    repository.connection.commit()
    path = objects_api.in_world(f"/world/versions/{version['version_id']}/thing-looks")
    response = objects_api.get(path)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert (body["profile"], body["version_id"]) == (LOOK_CHOICES_PROFILE, version["version_id"])
    [entry] = body["looks"]
    assert entry["thing_id"] == str(thing) and entry["look"] == TRAVELLER
    assert entry["chosen_by"] == "crossing" and entry["placed_id"] is None
    absent = objects_api.get(objects_api.in_world(f"/world/versions/{uuid.uuid4()}/thing-looks"))
    assert absent.status_code == 404
