"""A creature its workspace keeps, placed in an authored version by its kind's digest alone (0188).

What is shown, against PostgreSQL, through the routes a person's page calls:

*   a thing is placed by the digest of a kind its workspace keeps: its row names no key and no
    version (``kind_source`` 'workspace'), and the version's document names the kind as
    ``{"sha256", "source": "workspace"}``;
*   a digest the workspace does not hold is refused alike, another workspace's kind and an
    invented digest, with nothing written;
*   the table holds where a thing's kind comes from: a workspace kind with a key, a shipped kind
    without one, and a change of source are each refused;
*   once its workspace erases the creature, the thing is gone: the version's document says so, a
    move is refused by name (410 ``thing_kind_erased``) and a removal still stands; keeping the same
    creature again does not bring that thing back, while a thing placed after it was kept again is
    there;
*   a thing is gone by its kind's row alone, with no erasure recorded; undoing a gone thing's
    removal keeps it gone, and undoing its placing takes it out; a branch holds a gone thing gone
    after its creature is kept again;
*   a world holding only a creature is not made a world of things;
*   ``GET /things/plans/{plan_sha256}`` answers the drafted plan its workspace holds as the bytes
    of that digest, and another workspace's plan and an invented digest 404 alike;
*   a shipped thing stored before the migration reads after it as the document it always was.
"""

from __future__ import annotations

import hashlib
import json
import uuid

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.migrations import migrations
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import WorldObjectRepository
from exulanica.world.object_repository import version_holds_things
from exulanica.world.placed_things import ThingKindReference, placed_thing_document
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID, create_starter_authorities
from psycopg.conninfo import make_conninfo

import pg_harness
from conftest import scratch_role_database
from test_thing_store_postgres import ACTOR, _creature, _store
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401
from thing_fixtures import kind_body, placeable_kind

pytestmark = pytest.mark.postgres

POSE = {"x_mm": 2_000, "y_mm": 0, "z_mm": 1_000, "yaw_microradians": 0}
#: A placed creature's id, opaque as the page makes it (``creature:`` and the first eight of its
#: draft's id): never made from the creature's label, whose words would outlive its erasure.
WALKER = "creature:5d1e9a07"
AGAIN = "creature:c03b7f21"
#: The migration this file holds, by its title: its number is assigned at landing.
TITLE = "_a_placed_thing_may_name_its_workspace_s_own_kind.sql"


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture
def writer(objects_api, repository, spine_schema):
    """The deployed writer (the runtime role), which keeps and erases creatures."""
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE)


def _kept(writer, workspace_id: uuid.UUID, root, label: str):
    """A creature drafted in the fixtures and kept in ``workspace_id``'s own store."""
    creature = _creature(label=label)
    with writer.session(workspace_id) as connection:
        _store(connection, workspace_id, root).keep_creature(creature, created_by=ACTOR)
    return creature


def _erase(writer, workspace_id: uuid.UUID, creature, root) -> None:
    with writer.session(workspace_id) as connection:
        _store(connection, workspace_id, root).erase_creature(creature.kind.sha256, erased_by=ACTOR)


def _place(objects_api, version, thing_id: str, kind):
    return objects_api.post(
        objects_api.in_world(f"/world/versions/{version['version_id']}/things"),
        {
            "base_state_sha256": version["state_sha256"],
            "thing_id": thing_id,
            "kind": kind,
            "region_id": "region-a",
            "pose": POSE,
            "origin_role": "fictional",
        },
    )


def _read(objects_api, version):
    answer = objects_api.get(objects_api.in_world(f"/world/versions/{version['version_id']}"))
    assert answer.status_code == 200, answer.text
    return answer.json()


def test_a_thing_is_placed_by_the_digest_of_a_kind_its_workspace_keeps(
    objects_api, repository, writer, tmp_path
):
    creature = _kept(writer, repository.workspace_id, tmp_path / "looks", "placed walker")
    version = objects_api.version("A creature")
    placed = _place(
        objects_api,
        version,
        WALKER,
        {"source": "workspace", "sha256": creature.kind.sha256},
    )
    assert placed.status_code == 201, placed.text
    [thing] = placed.json()["things"]
    assert thing["kind"] == {"sha256": creature.kind.sha256, "source": "workspace"}
    assert "gone" not in thing
    row = repository.connection.execute(
        "select kind_source,kind,kind_version,encode(kind_sha256,'hex') as sha256 "
        "from world_alternate_thing where workspace_id=%s and thing_id=%s",
        (repository.workspace_id, WALKER),
    ).fetchone()
    assert row == {
        "kind_source": "workspace",
        "kind": None,
        "kind_version": None,
        "sha256": creature.kind.sha256,
    }


def test_a_digest_the_workspace_does_not_hold_is_refused_alike_with_nothing_written(
    objects_api, writer, tmp_path
):
    elsewhere = _kept(
        writer, objects_api.stranger_workspace_id, tmp_path / "theirs", "their walker"
    )
    version = objects_api.version("Not ours")
    answers = [
        _place(objects_api, version, WALKER, {"source": "workspace", "sha256": digest})
        for digest in (elsewhere.kind.sha256, uuid.uuid4().hex * 2)
    ]
    assert {(answer.status_code, json.dumps(answer.json())) for answer in answers} == {
        (
            422,
            json.dumps(
                {
                    "code": "invalid_thing_placement",
                    "detail": "this workspace holds no thing kind at that digest",
                }
            ),
        )
    }
    assert _read(objects_api, version)["things"] == []


def test_the_table_holds_where_a_thing_s_kind_comes_from(objects_api, repository, writer, tmp_path):
    creature = _kept(writer, repository.workspace_id, tmp_path / "looks", "held walker")
    version = objects_api.version("Sources")
    assert _place(
        objects_api, version, "thing:shipped", kind_body(placeable_kind())
    ).status_code == (201)
    connection = repository.connection
    columns = (
        "workspace_id,world_id,version_id,thing_id,kind_source,kind,kind_version,kind_sha256,"
        "region_id,x_mm,y_mm,z_mm,yaw_microradians,origin_kind,origin_role,removed,"
        "created_edit_id,last_edit_id"
    )

    def insert(thing_id: str, source: str, key: str | None, version_number: int | None) -> None:
        connection.execute(
            f"insert into world_alternate_thing({columns}) values "
            "(%s,%s,%s,%s,%s,%s,%s,decode(%s,'hex'),'region-a',0,0,0,0,'authored','fictional',"
            "false,%s,%s)",
            (
                repository.workspace_id,
                objects_api.world_id,
                uuid.UUID(version["version_id"]),
                thing_id,
                source,
                key,
                version_number,
                creature.kind.sha256,
                uuid.uuid4(),
                uuid.uuid4(),
            ),
        )

    for thing_id, source, key, version_number in (
        ("thing:keyed", "workspace", "held_walker", 1),
        ("thing:unkeyed", "shipped", None, None),
    ):
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(thing_id, source, key, version_number)
        connection.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "update world_alternate_thing set kind_source='workspace',kind=null,kind_version=null "
            "where workspace_id=%s and thing_id='thing:shipped'",
            (repository.workspace_id,),
        )
    connection.rollback()


def test_an_erased_creature_s_thing_is_gone_and_keeping_it_again_does_not_bring_it_back(
    objects_api, repository, writer, tmp_path
):
    looks = tmp_path / "looks"
    creature = _kept(writer, repository.workspace_id, looks, "erased walker")
    version = objects_api.version("Gone")
    root = f"/world/versions/{version['version_id']}/things"
    placed = _place(
        objects_api,
        version,
        WALKER,
        {"source": "workspace", "sha256": creature.kind.sha256},
    )
    assert placed.status_code == 201, placed.text
    _erase(writer, repository.workspace_id, creature, looks)
    [thing] = _read(objects_api, version)["things"]
    assert thing["gone"] is True
    state = placed.json()["state_sha256"]
    moved = objects_api.post(
        objects_api.in_world(f"{root}/{WALKER}/move"),
        {"base_state_sha256": state, "pose": {**POSE, "x_mm": 0}},
    )
    assert (moved.status_code, moved.json()["code"]) == (410, "thing_kind_erased")
    # The same creature kept again: the thing placed before its erasure stays gone, and one
    # placed now is there.
    _kept(writer, repository.workspace_id, looks, "erased walker")
    again = _place(
        objects_api,
        {**version, "state_sha256": state},
        AGAIN,
        {"source": "workspace", "sha256": creature.kind.sha256},
    )
    assert again.status_code == 201, again.text
    things = {one["thing_id"]: one for one in _read(objects_api, version)["things"]}
    assert things[WALKER]["gone"] is True
    assert "gone" not in things[AGAIN]
    removed = objects_api.post(
        objects_api.in_world(f"{root}/{WALKER}/remove"),
        {"base_state_sha256": again.json()["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    assert {one["thing_id"]: one["removed"] for one in removed.json()["things"]} == {
        WALKER: True,
        AGAIN: False,
    }


def test_a_world_holding_only_a_creature_is_a_world_of_things_while_its_kind_is_held(
    objects_api, repository, writer, tmp_path
):
    # A society of things takes a creature its workspace keeps in as a being, so it decides which
    # society a saved world gets exactly as a shipped being does: one rule for every thing. Once
    # its kind is erased no society reads it, and it decides nothing.
    looks = tmp_path / "looks"
    creature = _kept(writer, repository.workspace_id, looks, "lone walker")
    version = objects_api.version("Only a creature")
    empty = uuid.UUID(version["version_id"])

    def holds(version_id: uuid.UUID) -> bool:
        return version_holds_things(
            repository.connection, repository.workspace_id, objects_api.world_id, version_id
        )

    assert holds(empty) is False
    placed = _place(
        objects_api, version, WALKER, {"source": "workspace", "sha256": creature.kind.sha256}
    )
    assert placed.status_code == 201, placed.text
    held = uuid.UUID(placed.json()["version_id"])
    assert holds(held) is True
    _erase(writer, repository.workspace_id, creature, looks)
    assert holds(held) is False
    # A shipped thing beside it counts as it always did.
    shipped = _place(
        objects_api, _read(objects_api, placed.json()), "thing:shipped", kind_body(placeable_kind())
    )
    assert shipped.status_code == 201, shipped.text
    assert holds(uuid.UUID(shipped.json()["version_id"])) is True


def test_a_thing_whose_kind_its_workspace_no_longer_holds_is_gone_with_no_erasure_recorded(
    objects_api, repository, writer, tmp_path
):
    # The kind row deleted with no erasure recorded, as a workspace's tombstone purge deletes it:
    # the absence alone makes the thing gone.
    creature = _kept(writer, repository.workspace_id, tmp_path / "looks", "purged walker")
    version = objects_api.version("Purged")
    placed = _place(
        objects_api, version, WALKER, {"source": "workspace", "sha256": creature.kind.sha256}
    )
    assert placed.status_code == 201, placed.text
    connection = repository.connection
    # Only the purge's definer deletes from the store (0172's append-only trigger), so the owner
    # deletes as that role, with no erasure written, as a tombstone's purge does.
    connection.commit()
    with connection.transaction():
        connection.execute("set local role exulanica_definer")
        deleted = connection.execute(
            "delete from thing_kind_version where workspace_id=%s and sha256=%s",
            (repository.workspace_id, creature.kind.sha256),
        )
        assert deleted.rowcount == 1
    erasures = connection.execute(
        "select count(*) as count from thing_erasure where workspace_id=%s",
        (repository.workspace_id,),
    ).fetchone()
    assert erasures["count"] == 0
    [thing] = _read(objects_api, version)["things"]
    assert thing["gone"] is True


def test_undoing_a_gone_thing_s_removal_keeps_it_gone_and_undoing_its_placing_takes_it_out(
    objects_api, repository, writer, tmp_path
):
    looks = tmp_path / "looks"
    creature = _kept(writer, repository.workspace_id, looks, "undone walker")
    version = objects_api.version("Undone")
    root = f"/world/versions/{version['version_id']}/things"
    placed = _place(
        objects_api, version, WALKER, {"source": "workspace", "sha256": creature.kind.sha256}
    )
    assert placed.status_code == 201, placed.text
    removed = objects_api.post(
        objects_api.in_world(f"{root}/{WALKER}/remove"),
        {"base_state_sha256": placed.json()["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    _erase(writer, repository.workspace_id, creature, looks)
    back = objects_api.post(
        objects_api.in_world(f"{root}/undo"), {"base_state_sha256": removed.json()["state_sha256"]}
    )
    assert back.status_code == 200, back.text
    [thing] = back.json()["things"]
    assert (thing["removed"], thing["gone"]) == (False, True)
    out = objects_api.post(
        objects_api.in_world(f"{root}/undo"), {"base_state_sha256": back.json()["state_sha256"]}
    )
    assert out.status_code == 200, out.text
    assert out.json()["things"] == []


def test_a_branch_holds_a_gone_thing_gone_after_its_creature_is_kept_again(
    objects_api, repository, writer, tmp_path
):
    # The copy keeps its placing edit's time, so the erasure after it still makes it gone, and
    # keeping the same creature again brings back neither the original nor the copy.
    looks = tmp_path / "looks"
    creature = _kept(writer, repository.workspace_id, looks, "branched walker")
    version = objects_api.version("Before a branch")
    placed = _place(
        objects_api, version, WALKER, {"source": "workspace", "sha256": creature.kind.sha256}
    )
    assert placed.status_code == 201, placed.text
    _erase(writer, repository.workspace_id, creature, looks)
    _kept(writer, repository.workspace_id, looks, "branched walker")
    branch = objects_api.post(
        objects_api.in_world("/world/versions"),
        {"title": "A branch", "parent_version_id": version["version_id"]},
    )
    assert branch.status_code == 201, branch.text
    [thing] = branch.json()["things"]
    assert (thing["thing_id"], thing["gone"]) == (WALKER, True)
    [original] = _read(objects_api, version)["things"]
    assert original["gone"] is True


def test_the_plans_route_serves_a_held_plan_and_answers_404_alike(
    objects_api, repository, writer, tmp_path
):
    ours = _kept(writer, repository.workspace_id, tmp_path / "ours", "planned walker")
    theirs = _kept(writer, objects_api.stranger_workspace_id, tmp_path / "theirs", "their planner")
    answer = objects_api.get(f"/things/plans/{ours.plan.sha256}")
    assert answer.status_code == 200, answer.text
    assert hashlib.sha256(answer.content).hexdigest() == ours.plan.sha256
    assert answer.json()["profile"] == "exulanica.body-plan/v1"
    absent = [
        objects_api.get(f"/things/plans/{digest}")
        for digest in (theirs.plan.sha256, uuid.uuid4().hex * 2)
    ]
    assert {(one.status_code, one.content) for one in absent} == {(404, absent[0].content)}


def test_a_shipped_thing_stored_before_the_migration_reads_as_it_always_was(monkeypatch, tmp_path):
    everything = list(migrations())
    [migration] = [m for m in everything if m.path.name.endswith(TITLE)]
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    kind = placeable_kind()
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness,
            "migrations",
            lambda: iter(m for m in everything if m.version < migration.version),
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            scratch = admin.execute("select current_schema()").fetchone()[0]
            admin.commit()
            base = env_get("TEST_DATABASE_URL")
            assert base is not None
            database = Database(url=make_conninfo(base, options=f"-csearch_path={scratch},public"))
            with monkeypatch.context() as before, database.session(workspace) as connection:
                # Today's thing reader names the migration's column. The version is made holding no
                # thing yet, which is all the reader before the migration ever read of it.
                before.setattr(WorldObjectRepository, "_things", lambda _self, _version_id: ())
                _snapshot, _style, version_id = create_starter_authorities(
                    connection, workspace_id=workspace, actor=actor, title="Kept", world_id=world_id
                )
                # The row as the code before the migration wrote it: no source column yet.
                connection.execute(
                    "insert into world_alternate_thing(workspace_id,world_id,version_id,thing_id,"
                    "kind,kind_version,kind_sha256,region_id,x_mm,y_mm,z_mm,yaw_microradians,"
                    "origin_kind,origin_role,removed,created_edit_id,last_edit_id) values "
                    "(%s,%s,%s,'thing:kept',%s,%s,decode(%s,'hex'),%s,1500,0,-2500,0,'authored',"
                    "'fictional',false,%s,%s)",
                    (
                        workspace,
                        world_id,
                        version_id,
                        kind.kind,
                        kind.version,
                        kind.sha256,
                        AUTHORED_STARTER_REGION_ID,
                        uuid.uuid4(),
                        uuid.uuid4(),
                    ),
                )
            admin.execute(migration.sql)
            admin.commit()
            with database.session(workspace) as connection:
                version = WorldObjectRepository(
                    connection,
                    workspace,
                    world_id=world_id,
                    store=LocalContentAddressedStore(tmp_path / "blobs"),
                ).version(version_id)
            [thing] = version.things
            assert thing.kind == ThingKindReference(kind.kind, kind.version, kind.sha256)
            assert thing.kind_gone is False
            assert placed_thing_document(thing) == {
                "kind": {"kind": kind.kind, "sha256": kind.sha256, "version": kind.version},
                "origin": {"kind": "authored", "role": "fictional"},
                "region_id": AUTHORED_STARTER_REGION_ID,
                "removed": False,
                "thing_id": "thing:kept",
                "transform": {
                    "coordinate_space": "region_local",
                    "coordinate_unit": "millimetre",
                    "scale_milli": 1000,
                    "x_mm": 1500,
                    "y_mm": 0,
                    "yaw_microradians": 0,
                    "z_mm": -2500,
                },
            }
