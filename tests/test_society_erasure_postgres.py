"""A world's society is erased whole, by its route or with its workspace, against PostgreSQL as the
runtime role a deployment runs as (migration "a society is erased whole").

What is shown:

*   a person plays a knight and types a line it says, which reaches the answer, the receipt, the
    said event, the society's state and the next minute's request; nobody but the erasure deletes
    one of those rows; ``DELETE .../society`` erases the society, and afterwards the line's words
    are in no text or jsonb column of any table the catalog names, no row names the society, its
    tombstone and erasure are kept, the society reads 404, and the world makes a new one;
*   every table that records a society, by its id or by a foreign key from one, and the clock's
    and comparisons' records that name its world version or comparison, is erased with it, and
    only by the erasure (read from the catalog, not from a list);
*   a workspace tombstone erases every society of its workspace;
*   an erasure names a society tombstone of its own workspace, or one not held while a restore's
    replay carries it;
*   the Companion's answers that cited the society's world version are withdrawn, their text kept;
*   a society of another version of the same world, and another workspace's, keep every row at
    both entry points, and an erasure written in another workspace's name is refused.
"""

from __future__ import annotations

import re
import time
import uuid

import psycopg
import pytest
from exulanica.api.society_runtime import AuthoredWorldSocietyBinding, SocietyRuntime
from exulanica.db.session import set_workspace
from exulanica.selection.validation import Session
from exulanica.world.companion_memory import CompanionMemoryRepository, SimulationCitation
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.society_controls import LEASE_SECONDS
from exulanica.world.starter import AUTHORED_STARTER_REGION_ID
from psycopg import sql

import test_outside_deciders_postgres as outside
import test_society_authored_world_postgres as authored
import test_society_play_postgres as play
import test_society_stay_requests_api as stays
import test_society_things_postgres as things_api
from test_companion_memory import _answer
from test_society_person_decisions_postgres import _claim, _services
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

#: A line a person types, with words nothing else in a test database holds.
LINE = "Remember the zephyr quartz, 4417 paces north."
NEEDLE = "zephyr quartz, 4417"
#: The records a society's erasure deletes that name no society: its clock's receipts and sealed
#: traffic by its world version, and its comparisons' run starts and cancellation by comparison.
NAMING_NO_SOCIETY = frozenset(
    {
        "comparison_cancellation",
        "comparison_run_start",
        "world_clock_event",
        "world_clock_traffic_minute",
    }
)


def _tables_holding(connection, needle: str) -> set[str]:
    """Every table one of whose text or jsonb columns holds ``needle``, the catalog's columns."""
    columns = connection.execute(
        "select c.table_name, c.column_name from information_schema.columns c "
        "join information_schema.tables t on t.table_schema = c.table_schema "
        "and t.table_name = c.table_name and t.table_type = 'BASE TABLE' "
        "where c.table_schema = current_schema() "
        "and c.data_type in ('text', 'jsonb', 'json', 'character varying')"
    ).fetchall()
    assert len(columns) > 500, "the positive control: the catalog names the schema's columns"
    found = set()
    for row in columns:
        table, column = row["table_name"], row["column_name"]
        held = connection.execute(
            sql.SQL("select 1 from {} where {}::text like %s limit 1").format(
                sql.Identifier(table), sql.Identifier(column)
            ),
            (f"%{needle}%",),
        ).fetchone()
        if held is not None:
            found.add(table)
    connection.commit()
    return found


#: The erasure's own record names the society it erased by its id, and is kept, as a creature's is.
ERASURE_RECORD = "society_erasure"


def _society_rows(connection, society_id) -> dict[str, int]:
    """How many rows of each table with a society id name ``society_id``, but the erasure's own."""
    tables = [
        row["table_name"]
        for row in connection.execute(
            "select c.table_name from information_schema.columns c "
            "join information_schema.tables t on t.table_schema = c.table_schema "
            "and t.table_name = c.table_name and t.table_type = 'BASE TABLE' "
            "where c.table_schema = current_schema() and c.column_name = 'society_id' "
            "order by 1"
        ).fetchall()
        if row["table_name"] != ERASURE_RECORD
    ]
    counts = {
        table: connection.execute(
            sql.SQL("select count(*) as n from {} where society_id = %s").format(
                sql.Identifier(table)
            ),
            (society_id,),
        ).fetchone()["n"]
        for table in tables
    }
    connection.commit()
    return counts


def _society_id(world) -> uuid.UUID | None:
    row = (
        world["connection"]
        .execute(
            "select society_id from world_society where workspace_id = %s and version_id = %s",
            (world["workspace"], world["binding"].version_id),
        )
        .fetchone()
    )
    world["connection"].commit()
    return None if row is None else row["society_id"]


def _played_line(world, client, services):
    """A knight beside another, played, saying :data:`LINE` and carrying on a minute after."""
    snapshot, knight = play._knight_society(world, client, beside=True)
    assert play._start(client, world, knight).status_code == 201
    scope, _, society = routes(world)
    path = f"{society}/play/{knight}"
    turn = client.get(path + "/turn", headers=OWNER, params=scope).json()
    say = next(option for option in turn["options"] if option["takes_line"])
    body = {"base_tick": turn["base_tick"], "label": say["label"], "line": LINE}
    assert play._post(client, path + "/answer", scope, body).status_code == 202
    host = outside._doorkeeping_host(world, services, None)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    snapshot = stays._step(world, client, snapshot)
    # The knight's next request shows its decider what it said.
    snapshot = stays._step(world, client, snapshot)
    return snapshot, knight


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_is_erased_whole_with_every_word_its_people_said(app):
    world, client = app
    services = _services(client)
    _played_line(world, client, services)
    connection = world["connection"]
    society_id = _society_id(world)
    held = _tables_holding(connection, NEEDLE)
    # The positive control: the line reached the answer, the receipt, the said event, the state
    # and the next minute's request.
    assert {
        "world_society_person_answer",
        "world_society_decision",
        "world_society_event",
        "world_society",
        "world_society_decision_request",
    } <= held, held
    # Nobody else deletes a society's record: not the runtime, and not the tables' owner.
    with (
        services.database.session(world["workspace"]) as runtime,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        runtime.execute("delete from world_society_event where society_id = %s", (society_id,))
    with pytest.raises(psycopg.errors.CheckViolation, match="erased whole"):
        connection.execute("delete from world_society_event where society_id = %s", (society_id,))
    connection.rollback()

    scope, _, society = routes(world)
    erased = client.delete(society, headers=OWNER, params=scope)
    assert erased.status_code == 204, erased.text
    assert _tables_holding(connection, NEEDLE) == set()
    assert not any(_society_rows(connection, society_id).values())
    [kept] = connection.execute(
        "select t.scope::text as scope, e.society_id from society_erasure e "
        "join tombstone t on t.tombstone_id = e.tombstone_id where e.workspace_id = %s",
        (world["workspace"],),
    ).fetchall()
    connection.commit()
    assert (kept["scope"], kept["society_id"]) == ("society", society_id)
    gone = client.get(society, headers=OWNER, params=scope)
    assert gone.status_code == 404, gone.text
    again = client.delete(society, headers=OWNER, params=scope)
    assert (again.status_code, again.json()["code"]) == (404, "society_unavailable")
    # The world stays: it makes a new society (its id is the world's, so the same one), which
    # starts at its first minute with none of the erased one's history.
    remade = things_api._make_society(client, world)
    assert remade["current_tick"] == 0
    assert _society_rows(connection, society_id)["world_society_transition"] == 0


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_every_table_that_records_a_society_is_erased_with_it_and_only_by_it(app):
    world, _client = app
    connection = world["connection"]
    keyed = {
        row["table_name"]
        for row in connection.execute(
            "select table_name from information_schema.columns "
            "where table_schema = current_schema() and column_name = 'society_id'"
        ).fetchall()
    }
    links = connection.execute(
        "select c.conrelid::regclass::text as child, c.confrelid::regclass::text as parent "
        "from pg_constraint c where c.contype = 'f' "
        "and c.connamespace = current_schema()::regnamespace"
    ).fetchall()
    records = {"world_society"} | (keyed - {ERASURE_RECORD})
    grown = True
    while grown:
        reached = {link["child"] for link in links if link["parent"] in records}
        grown = not reached <= records
        records |= reached
    # A positive control: the play's answers and the door's asks are among them.
    assert {"world_society_person_answer", "door_ask", "society_comparison_hour"} <= records
    body = connection.execute(
        "select pg_get_functiondef('society_erase_rows(uuid,uuid)'::regprocedure) as body"
    ).fetchone()["body"]
    erased = set(re.findall(r"delete from (\w+)", body))
    assert erased == records | NAMING_NO_SOCIETY
    guarded = {
        row["tab"]
        for row in connection.execute(
            "select tgrelid::regclass::text as tab from pg_trigger "
            "where tgname = 'tg_society_record_erased_whole'"
        ).fetchall()
    }
    connection.commit()
    assert guarded == erased


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_workspace_tombstone_erases_every_society_of_its_workspace(app):
    world, client = app
    services = _services(client)
    snapshot, _knight = play._knight_society(world, client)
    stays._step(world, client, snapshot)
    society_id = _society_id(world)
    assert sum(_society_rows(world["connection"], society_id).values()) > 1
    with services.database.session(world["workspace"]) as runtime:
        runtime.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the workspace is erased')",
            (world["workspace"], world["session"].actor),
        )
    assert not any(_society_rows(world["connection"], society_id).values())


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_erasure_names_a_society_tombstone_of_its_own_or_none_while_a_restore_replays(app):
    """The erasure's trigger reads the tombstone it names: another scope's tombstone of this
    workspace is refused by name, and so is a tombstone not held while no restore replays, with
    nothing deleted. One not held while a restore's replay is under way, as when it carries an
    erasure before it replays the tombstone, deletes the society."""
    world, client = app
    services = _services(client)
    play._knight_society(world, client)
    society_id = _society_id(world)
    before = _society_rows(world["connection"], society_id)
    assert any(before.values()), "the positive control: the society is there"

    def write(tombstone_id) -> None:
        with services.database.session(world["workspace"]) as runtime:
            runtime.execute(
                "insert into society_erasure (workspace_id, world_id, version_id, society_id, "
                "tombstone_id, erased_by) values (%s, %s, %s, %s, %s, %s)",
                (
                    world["workspace"],
                    world["binding"].world_id,
                    world["binding"].version_id,
                    society_id,
                    tombstone_id,
                    world["session"].actor,
                ),
            )

    with services.database.session(world["workspace"]) as runtime:
        creature = runtime.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'creature', %s, 'another scope') returning tombstone_id",
            (world["workspace"], world["session"].actor),
        ).fetchone()["tombstone_id"]
    with pytest.raises(psycopg.errors.CheckViolation, match="a society tombstone of its own"):
        write(creature)
    with pytest.raises(psycopg.errors.CheckViolation, match="unless a restore's replay carries it"):
        write(uuid.uuid4())
    assert _society_rows(world["connection"], society_id) == before

    owner = world["connection"]
    owner.execute(
        "insert into restore_control (checkpoint_id, checkpoint_sha256, state, restore_id) "
        "values (%s, %s, 'replaying', %s)",
        (uuid.uuid4(), "a" * 64, uuid.uuid4()),
    )
    owner.commit()
    try:
        write(uuid.uuid4())
    finally:
        owner.execute("delete from restore_control")
        owner.commit()
    assert not any(_society_rows(world["connection"], society_id).values())


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_companion_s_answers_that_cited_the_society_are_withdrawn_with_their_text(app):
    world, client = app
    services = _services(client)
    snapshot, knight = play._knight_society(world, client)
    text = "Knight is standing by the well."
    with services.database.session(world["workspace"]) as runtime:
        kept = CompanionMemoryRepository(
            runtime, world["workspace"], world["session"].actor
        ).record_answer(
            _answer(
                question="What is the knight doing?",
                answer_text=text,
                world_id=world["binding"].world_id,
                simulation_citations=(
                    SimulationCitation(
                        ordinal=0,
                        result_kind="synthetic_inhabitant",
                        version_id=world["binding"].version_id,
                        inhabitant_id=uuid.UUID(knight),
                        event_id=None,
                        tick=snapshot["current_tick"],
                    ),
                ),
            )
        )
    scope, _, society = routes(world)
    assert client.delete(society, headers=OWNER, params=scope).status_code == 204
    row = (
        world["connection"]
        .execute(
            "select a.status::text as status, a.answer_text, t.scope::text as scope "
            "from companion_answer a join tombstone t on t.tombstone_id = a.withdrawn_by "
            "where a.answer_id = %s",
            (kept.answer_id,),
        )
        .fetchone()
    )
    world["connection"].commit()
    assert (row["status"], row["answer_text"], row["scope"]) == ("withdrawn", text, "society")


def _erased_tables(connection) -> list[str]:
    """Every table the erasure deletes from, read from its own body."""
    body = connection.execute(
        "select pg_get_functiondef('society_erase_rows(uuid,uuid)'::regprocedure) as body"
    ).fetchone()["body"]
    connection.commit()
    return sorted(set(re.findall(r"delete from (\w+)", body)))


def _workspace_rows(connection, workspace) -> dict[str, int]:
    """How many rows of each table the erasure deletes from ``workspace`` holds."""
    counts = {
        table: connection.execute(
            sql.SQL("select count(*) as n from {} where workspace_id = %s").format(
                sql.Identifier(table)
            ),
            (workspace,),
        ).fetchone()["n"]
        for table in _erased_tables(connection)
    }
    connection.commit()
    return counts


def _version_rows(connection, workspace, society_id, version_id) -> dict[str, int]:
    """How many rows of each table the erasure deletes from name one society of ``workspace``,
    by its id, or, for its clock's records, by its world version."""
    counts = dict(_society_rows(connection, society_id))
    for table in ("world_clock_event", "world_clock_traffic_minute"):
        counts[table] = connection.execute(
            sql.SQL(
                "select count(*) as n from {} where workspace_id = %s and version_id = %s"
            ).format(sql.Identifier(table)),
            (workspace, version_id),
        ).fetchone()["n"]
    connection.commit()
    return counts


def _another_workspace_s_society(world) -> tuple[uuid.UUID, uuid.UUID]:
    """A society of a saved world of another workspace, made as the fixture makes its own, through
    the same connection under that workspace's name. Answers the workspace and the society."""
    connection, actor = world["connection"], world["session"].actor
    workspace = uuid.uuid4()
    world_id = f"world:authored:{uuid.uuid4()}"
    set_workspace(connection, workspace)
    try:
        with connection.transaction():
            snapshot_id, version_id = authored.make_starter(
                connection, workspace, actor, world_id, world["ground_module_version"]
            )
        place_id = uuid.uuid4()
        connection.execute(
            "insert into place(workspace_id,place_id) values(%s,%s)", (workspace, place_id)
        )
        connection.commit()
        binding = AuthoredWorldSocietyBinding(
            binding_id="society-erasure-another-workspace",
            workspace_id=workspace,
            world_id=world_id,
            version_id=version_id,
            source_snapshot_id=snapshot_id,
            place_id=place_id,
            region_id=AUTHORED_STARTER_REGION_ID,
        )
        runtime = SocietyRuntime(
            store=world["store"],
            authored_bindings=[binding],
            reviewed_affordances=world["registry"],
        )
        elsewhere = {
            **world,
            "workspace": workspace,
            "world_id": world_id,
            "session": Session(workspace_id=workspace, actor=actor),
            "binding": binding,
            "runtime": runtime,
        }
        elsewhere["objects"] = authored.objects_repository(elsewhere, runtime)
        authored.place_object(elsewhere, world["plate"], "object:cushion", 3_000, 5_000)
        society, _document = authored.create_society(elsewhere)
        connection.commit()
    finally:
        set_workspace(connection, world["workspace"])
    return workspace, society["society_id"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_erasure_keeps_every_row_of_another_version_s_society_and_another_workspace_s(app):
    """The data-loss control, at both entry points: the route erases this version's society and
    leaves a society of another version of the same world, and another workspace's, row for row
    over every table it deletes from; this workspace's tombstone erases both of its own and leaves
    the other workspace's; and an erasure written in the other workspace's name from a session of
    this one is refused, rather than recorded with nothing erased."""
    world, client = app
    snapshot, _knight = play._knight_society(world, client)
    stays._step(world, client, snapshot)
    connection = world["connection"]
    society_id = _society_id(world)
    # Another version of the same world, with a society of its own that has lived a minute.
    with connection.transaction():
        style = WorldStyleRepository(connection, world["workspace"], world_id=world["world_id"])
        other_version = world["objects"].create_version(
            source_snapshot_id=world["binding"].source_snapshot_id,
            title="Another version",
            style_version_id=style.current().version_id,
            created_by=world["session"].actor,
        )
    versioned = {
        **world,
        "binding": world["binding"].model_copy(update={"version_id": other_version.version_id}),
    }
    things_api._place(client, versioned, "well", "well", 2, -4_000, 2_000)
    things_api._place(client, versioned, "knight", "knight", 1, 3_000, 3_000)
    stays._step(versioned, client, things_api._make_society(client, versioned))
    # Both versions' clocks coupled, so each society's clock holds receipts named by its version.
    for held in (world, versioned):
        held_scope, held_version, _ = routes(held)
        coupled = client.put(
            held_version + "/clock",
            headers=OWNER,
            params=held_scope,
            json={"base_revision": 0, "profile": "coupled"},
        )
        assert coupled.status_code == 200, coupled.text
    other_society = _society_id(versioned)
    assert other_society is not None and other_society != society_id
    workspace, foreign = _another_workspace_s_society(world)
    kept_version = _version_rows(
        connection, world["workspace"], other_society, other_version.version_id
    )
    kept_workspace = _workspace_rows(connection, workspace)
    # The positive controls: each holds rows the erasure would delete were it theirs.
    assert kept_version["world_society_transition"] > 0 and kept_version["world_society"] == 1
    assert kept_version["world_clock_event"] > 0 and kept_version["world_clock"] == 1
    assert kept_workspace["world_society"] == 1 and sum(kept_workspace.values()) > 1

    scope, _, society = routes(world)
    assert client.delete(society, headers=OWNER, params=scope).status_code == 204
    assert not any(_society_rows(connection, society_id).values())
    assert (
        _version_rows(connection, world["workspace"], other_society, other_version.version_id)
        == kept_version
    )
    assert _workspace_rows(connection, workspace) == kept_workspace

    services = _services(client)
    with services.database.session(world["workspace"]) as runtime:
        runtime.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the workspace is erased')",
            (world["workspace"], world["session"].actor),
        )
    assert not any(_society_rows(connection, other_society).values())
    assert _workspace_rows(connection, workspace) == kept_workspace

    # The other workspace's own society tombstone, then its erasure written from a session of
    # this workspace: refused by name, and nothing of it erased.
    set_workspace(connection, workspace)
    tombstone = connection.execute(
        "insert into tombstone (workspace_id, scope, requested_by, reason) "
        "values (%s, 'society', %s, 'another workspace') returning tombstone_id",
        (workspace, world["session"].actor),
    ).fetchone()["tombstone_id"]
    connection.commit()
    set_workspace(connection, world["workspace"])
    [held] = connection.execute(
        "select world_id, version_id from world_society where workspace_id = %s", (workspace,)
    ).fetchall()
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
        connection.execute(
            "insert into society_erasure (workspace_id, world_id, version_id, society_id, "
            "tombstone_id, erased_by) values (%s, %s, %s, %s, %s, %s)",
            (
                workspace,
                held["world_id"],
                held["version_id"],
                foreign,
                tombstone,
                world["session"].actor,
            ),
        )
    connection.rollback()
    assert _workspace_rows(connection, workspace) == kept_workspace
