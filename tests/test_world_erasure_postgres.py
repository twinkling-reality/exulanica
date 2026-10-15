"""A world's rows are erased whole, and a workspace's erasure erases every world it holds.

``world_erase_rows`` deletes every row of one world, children first, and a workspace tombstone
runs it for each world of the workspace and then deletes the kinds the workspace kept. What
that has to reach is read from the migrated schema and never from a list typed here: the tables
that hang from ``world_identity`` by a foreign key, however far down, and which of a table's
rows are a given world's, by following those same keys. The rows come from
``tests/existence_builders.py``, which makes one real object of every kind a route addresses, so
the workspace under test holds a composed world, a starter and a generated town, with societies,
edits, projects, a door grant, piece requests and comparisons among them.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import re
import uuid
from decimal import Decimal

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.generation import batches
from exulanica.migrations import migrations
from exulanica.world.companion_memory import (
    CompanionMemoryRepository,
    SimulatedInhabitant,
    SimulationCitation,
)
from exulanica.world.minds_budget import MindsBudgetRepository
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_erasure import erase_society
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

import pg_harness
from conftest import scratch_role_database
from route_probes import EXISTENCE_BUILDERS
from test_companion_memory import _answer
from test_existence_oracle import _RUNTIME_ROLE
from test_existence_oracle import existence as existence
from test_piece_batch_tombstone_order_postgres import _queued
from test_society_erasure_postgres import _tables_holding
from world_support import historical_world_fixture_schema

pytestmark = pytest.mark.postgres

#: The registration every world table hangs from.
REGISTRATION = "world_identity"
#: An erasure's own record names the world it erased a society of, by id, and is kept.
ERASURE_RECORD = "society_erasure"
#: The one table whose rows are a world's with no key to it (0127), so no foreign key leads from
#: it to the registration: the name or the spot a placeholder stood for in a Companion answer
#: that cites the world.
NAMING_NO_KEY = "companion_answer_simulation_label"
#: A workspace's kept kinds are no one world's: its tombstone deletes them after its worlds.
KEPT_KINDS = "world_kind_version"
#: The society tables a workspace or a world reaches through ``society_erase_rows`` alone: their
#: rows name a society and never the world.
ERASED_WITH_ITS_SOCIETY = "society_erase_rows(uuid,uuid)"
ERASED_WITH_ITS_WORLD = "world_erase_rows(uuid,text)"
ERASED_WITH_PARTICIPATION = "participation_erase(uuid,text)"
#: A saved world's picture hangs from its entry alone (0218): the entry's own BEFORE DELETE trigger
#: runs this definer, which deletes the picture as world_erase_rows deletes the entry.
ERASED_WITH_ITS_ENTRY = "saved_world_entry_picture_erase()"
PARTICIPATION_GUARD = "tg_participation_record_guard"
#: The guard 0182 put on a society's tables, and the one this erasure puts on a world's.
SOCIETY_GUARD = "tg_society_record_erased_whole"
WORLD_GUARD = "tg_world_record_erased_whole"

# ---------------------------------------------------------------------------------------------
# Reading the schema
# ---------------------------------------------------------------------------------------------


def _admin(existence):
    """The harness's own connection: the schema's owner, which row-level security does not bind."""
    return existence.repository.connection


def _links(admin) -> list[tuple[str, str, tuple[str, ...], tuple[str, ...]]]:
    """Every foreign key of the schema: child, parent, and the columns on each side, in order."""
    rows = admin.execute(
        "select c.conrelid::regclass::text as child, c.confrelid::regclass::text as parent, "
        "(select array_agg(a.attname order by k.ord) "
        " from unnest(c.conkey) with ordinality k(n, ord) "
        " join pg_attribute a on a.attrelid = c.conrelid and a.attnum = k.n) as child_columns, "
        "(select array_agg(a.attname order by k.ord) "
        " from unnest(c.confkey) with ordinality k(n, ord) "
        " join pg_attribute a on a.attrelid = c.confrelid and a.attnum = k.n) as parent_columns "
        "from pg_constraint c where c.contype = 'f' "
        "and c.connamespace = current_schema()::regnamespace"
    ).fetchall()
    return [
        (row["child"], row["parent"], tuple(row["child_columns"]), tuple(row["parent_columns"]))
        for row in rows
    ]


def _hanging_from_a_world(links) -> set[str]:
    """Every table a foreign key leads from to the registration, however far down."""
    records = {REGISTRATION}
    grown = True
    while grown:
        reached = {child for child, parent, _, _ in links if parent in records}
        grown = not reached <= records
        records |= reached
    return records


def _with_column(admin, column: str) -> set[str]:
    return {
        row["table_name"]
        for row in admin.execute(
            "select c.table_name from information_schema.columns c "
            "join information_schema.tables t on t.table_schema = c.table_schema "
            "and t.table_name = c.table_name and t.table_type = 'BASE TABLE' "
            "where c.table_schema = current_schema() and c.column_name = %s",
            (column,),
        ).fetchall()
    }


def _deleted_by(admin, signature: str) -> set[str]:
    """Every table a function deletes from, read from its own body."""
    body = admin.execute(
        "select pg_get_functiondef(%s::regprocedure) as body", (signature,)
    ).fetchone()["body"]
    return set(re.findall(r"delete from (\w+)", body))


def _of_the_world(table: str, alias: str, links, keyed: set[str], depth: int = 0) -> sql.Composable:
    """A condition on ``alias``, a row of ``table``: it is the world's, by the schema's own keys.

    A table that carries ``world_id`` says so itself. Any other is the world's where a row it
    references is, through any of its foreign keys into the tables that hang from a world.
    """
    name = sql.Identifier(alias)
    if table in keyed:
        return sql.SQL("{}.world_id = %(world)s").format(name)
    hanging = _hanging_from_a_world(links)
    through = []
    for child, parent, child_columns, parent_columns in links:
        if child != table or parent not in hanging or parent == table:
            continue
        inner = f"p{depth}"
        joined = sql.SQL(" and ").join(
            sql.SQL("{}.{} = {}.{}").format(
                sql.Identifier(inner), sql.Identifier(theirs), name, sql.Identifier(ours)
            )
            for ours, theirs in zip(child_columns, parent_columns, strict=True)
        )
        through.append(
            sql.SQL("exists (select 1 from {} {} where {} and {})").format(
                sql.Identifier(parent),
                sql.Identifier(inner),
                joined,
                _of_the_world(parent, inner, links, keyed, depth + 1),
            )
        )
    assert through, f"{table} hangs from a world by no key the schema declares"
    return sql.SQL("(") + sql.SQL(" or ").join(through) + sql.SQL(")")


def _world_rows(admin, workspace: uuid.UUID, world: str) -> dict[str, int]:
    """How many rows of each table that hangs from a world are this world's, but its erasure
    records; and of the one table that names its versions with no key."""
    links = _links(admin)
    keyed = _with_column(admin, "world_id")
    counts = {}
    for table in sorted(_hanging_from_a_world(links) - {ERASURE_RECORD}):
        counts[table] = admin.execute(
            sql.SQL(
                "select count(*) as n from {} x where x.workspace_id = %(workspace)s and "
            ).format(sql.Identifier(table))
            + _of_the_world(table, "x", links, keyed),
            {"workspace": workspace, "world": world},
        ).fetchone()["n"]
    counts[NAMING_NO_KEY] = admin.execute(
        sql.SQL(
            "select count(*) as n from {} x where x.workspace_id = %(workspace)s "
            "and (x.version_id in (select v.version_id from world_alternate_version v "
            "where v.workspace_id = %(workspace)s and v.world_id = %(world)s) "
            "or x.answer_id in (select c.answer_id from companion_answer_simulation_citation c "
            "where c.workspace_id = %(workspace)s and c.world_id = %(world)s))"
        ).format(sql.Identifier(NAMING_NO_KEY)),
        {"workspace": workspace, "world": world},
    ).fetchone()["n"]
    return counts


def _workspace_rows(admin, workspace: uuid.UUID) -> dict[str, int]:
    """How many rows of each table that hangs from a world, and of the two beside them, a
    workspace holds."""
    tables = _hanging_from_a_world(_links(admin)) | {NAMING_NO_KEY, KEPT_KINDS}
    return {
        table: admin.execute(
            sql.SQL("select count(*) as n from {} where workspace_id = %s").format(
                sql.Identifier(table)
            ),
            (workspace,),
        ).fetchone()["n"]
        for table in sorted(tables)
    }


def _worlds(admin, workspace: uuid.UUID) -> list[str]:
    return [
        row["world_id"]
        for row in admin.execute(
            "select world_id from world_identity where workspace_id = %s order by world_id",
            (workspace,),
        ).fetchall()
    ]


#: The addresses whose objects live in a world, or are made beside one: every kind a world route,
#: the door or the Companion addresses, and a saved entry.
_OF_A_WORLD = ("/world/", "/worlds/", "/door/", "/companion/")


def _one_of_everything(existence) -> None:
    """One real object of every kind a world's routes address, in the owner's workspace.

    Each kind is built by itself, as the sweep builds it for one route: what a builder remembers
    of the ids it named is forgotten between kinds, since two kinds may each make a version of
    their own, and the objects several builders share (the world itself) are kept.
    """
    made = 0
    for address in sorted(EXISTENCE_BUILDERS):
        if address.startswith(_OF_A_WORLD) or address == "/world-entries/{entry_id}":
            existence._made.clear()
            existence.real(address)
            made += 1
    assert made >= 30, made


#: A kept kind's label, in words nothing else in a test database holds.
KEPT_LABEL = "Quillon harbour, 7731"
#: Where a Companion answer's spot placeholder pointed: a label that names no version.
SPOT = "the veridian well, 5512"


def _keep_a_kind(admin, workspace: uuid.UUID, actor: uuid.UUID) -> None:
    """A kind the workspace kept, as the library's draft route writes one."""
    digest = "c" * 64
    admin.execute(
        "insert into world_kind_version (workspace_id, kind, version, document_sha256, document, "
        "origin, validation, created_by) values (%s, 'harbour', 1, %s, %s, 'drafted', %s, %s)",
        (
            workspace,
            digest,
            Jsonb(
                {
                    "profile": "exulanica.world-kind/v1",
                    "kind": "harbour",
                    "version": 1,
                    "origin": "drafted",
                    "label": KEPT_LABEL,
                }
            ),
            Jsonb(
                {
                    "profile": "exulanica.world-kind-validation/v1",
                    "verdict": "passed",
                    "kind": {"sha256": digest},
                }
            ),
            actor,
        ),
    )


def _budgets_and_citations(existence, scratch: str) -> None:
    """A budget for the people's minds in every world of the workspace, and a Companion answer
    that cites a version of each world that has one, with the name its placeholder stood for."""
    admin, workspace = _admin(existence), existence.workspace_id
    versions = {
        row["world_id"]: row["version_id"]
        for row in admin.execute(
            "select distinct on (world_id) world_id, version_id from world_alternate_version "
            "where workspace_id = %s order by world_id, version_id",
            (workspace,),
        ).fetchall()
    }
    with scratch_role_database(scratch, _RUNTIME_ROLE).session(workspace) as runtime:
        for world in _worlds(admin, workspace):
            MindsBudgetRepository(runtime, workspace, world_id=world).record(
                person_role(),
                request_id=uuid.uuid4(),
                usd_per_hour="0.25",
                decisions_per_hour=30,
                set_by=existence.actor,
            )
        for world, version_id in versions.items():
            inhabitant = uuid.uuid4()
            CompanionMemoryRepository(runtime, workspace, existence.actor).record_answer(
                _answer(
                    question="Who is by the well?",
                    answer_text="[inhabitant A] is standing by [spot A].",
                    world_id=world,
                    inhabitants={"[inhabitant A]": SimulatedInhabitant(version_id, inhabitant)},
                    spots={"[spot A]": SPOT},
                    simulation_citations=(
                        SimulationCitation(
                            ordinal=0,
                            result_kind="synthetic_inhabitant",
                            version_id=version_id,
                            inhabitant_id=inhabitant,
                            event_id=None,
                            tick=1,
                        ),
                    ),
                )
            )


def _pictures(admin) -> None:
    """A picture for every saved world of every workspace, written by the schema's owner (0218)."""
    data = b"a picture"
    admin.execute(
        "insert into saved_world_entry_picture (workspace_id,entry_id,media_type,bytes,byte_size,"
        "sha256,width,height,authored_version_id,authored_state_sha256,style_version_id,taken_by) "
        "select e.workspace_id,e.entry_id,'image/jpeg',%s,%s,%s,640,360,e.authored_version_id,"
        "e.authored_state_sha256,e.style_version_id,e.created_by from saved_world_entry e",
        (data, len(data), hashlib.sha256(data).hexdigest()),
    )


def _erase_one_world(admin, workspace: uuid.UUID, world: str) -> None:
    """``world_erase_rows`` as its owner runs it, in the workspace's own session."""
    with admin.transaction():
        admin.execute("set local role exulanica_definer")
        admin.execute("select set_config('exulanica.workspace_id', %s, true)", (str(workspace),))
        # The world erasure trigger invokes participation first, then world rows.
        admin.execute("select participation_erase(%s, %s)", (workspace, world))
        admin.execute("select world_erase_rows(%s, %s)", (workspace, world))


# ---------------------------------------------------------------------------------------------
# What the erasure reaches, from the schema
# ---------------------------------------------------------------------------------------------


def test_every_table_that_hangs_from_a_world_is_erased_with_it_and_guarded(existence):
    admin = _admin(existence)
    links = _links(admin)
    hanging = _hanging_from_a_world(links)
    # A positive control: a society's answers, a door's secrets and an edit are among them.
    assert {"world_society_person_answer", "door_secret", "world_alternate_version_edit"} <= hanging
    by_world = _deleted_by(admin, ERASED_WITH_ITS_WORLD)
    by_society = _deleted_by(admin, ERASED_WITH_ITS_SOCIETY)
    by_participation = _deleted_by(admin, ERASED_WITH_PARTICIPATION) - {
        "participation_redemption_refusal"  # This workspace-wide audit is no single world's.
    }
    by_entry = _deleted_by(admin, ERASED_WITH_ITS_ENTRY)
    # What the entry's trigger deletes is reached only because the trigger runs on the entry's own
    # delete, which world_erase_rows makes: before each row's delete, as the definers' owner.
    assert "saved_world_entry" in by_world
    assert (
        admin.execute(
            "select count(*) as n from pg_trigger where tgrelid = 'saved_world_entry'::regclass "
            "and tgfoid = %s::regprocedure and not tgisinternal "
            "and (tgtype & 1) = 1 and (tgtype & 2) = 2 and (tgtype & 8) = 8",
            (ERASED_WITH_ITS_ENTRY,),
        ).fetchone()["n"]
        == 1
    )
    assert admin.execute(
        "select p.prosecdef and pg_get_userbyid(p.proowner) = 'exulanica_definer' as definer "
        "from pg_proc p where p.oid = %s::regprocedure",
        (ERASED_WITH_ITS_ENTRY,),
    ).fetchone()["definer"]
    assert by_world | by_society | by_participation | by_entry == (hanging - {ERASURE_RECORD}) | {
        NAMING_NO_KEY
    }
    # What its societies' erasure leaves is the world's own to delete: every table that carries
    # the world's id, and every table no society's erasure deletes from.
    assert (hanging & _with_column(admin, "world_id")) - {
        ERASURE_RECORD
    } <= by_world | by_participation
    assert hanging - by_society - {ERASURE_RECORD} <= by_world | by_participation | by_entry
    assert REGISTRATION in by_world and KEPT_KINDS not in by_world

    guards = {
        (row["tab"], row["name"])
        for row in admin.execute(
            "select tgrelid::regclass::text as tab, tgname as name from pg_trigger "
            "where tgname in (%s, %s, %s)",
            (WORLD_GUARD, SOCIETY_GUARD, PARTICIPATION_GUARD),
        ).fetchall()
    }
    by_society_s_guard = {table for table, name in guards if name == SOCIETY_GUARD}
    by_world_s_guard = {table for table, name in guards if name == WORLD_GUARD}
    # piece_output never had a delete guard (0175), and world_minds_budget's is its own.
    own = {"piece_output", "world_minds_budget"}
    assert by_world_s_guard == ((by_world | by_entry | {KEPT_KINDS}) - by_society_s_guard - own)
    assert not by_world_s_guard & by_society_s_guard
    assert {table for table, name in guards if name == PARTICIPATION_GUARD} == (
        by_participation | {"participation_redemption_refusal"}
    )

    may_delete = {
        row["table_name"]
        for row in admin.execute(
            "select table_name from information_schema.role_table_grants "
            "where table_schema = current_schema() and grantee = 'exulanica_definer' "
            "and privilege_type = 'DELETE'"
        ).fetchall()
    }
    required_delete = by_world | by_participation | by_entry | {KEPT_KINDS}
    assert required_delete <= may_delete, sorted(required_delete - may_delete)


def test_the_erasure_locks_every_parent_before_its_first_delete(existence):
    """Read from the erasure's own body: every parent a writer without the workspace lock adds to
    or changes is locked, in one order, before the first delete, with the world's societies
    erased between the comparisons' runs and the door's grants, and the registration last."""
    admin = _admin(existence)
    body = admin.execute(
        "select pg_get_functiondef(%s::regprocedure) as body", (ERASED_WITH_ITS_WORLD,)
    ).fetchone()["body"]
    first = body.index("delete from")
    locked = re.findall(r"perform 1 from (\w+) \w+\s+where[^;]*for update", body)
    assert locked == [
        "world_project",
        "world_project_item",
        "saved_world_entry",
        "world_alternate_version",
        "world_style_state",
        "world_style_preview",
        "world_structure_state",
        "world_structure_preview",
        "world_interaction_policy_state",
        "world_interaction_policy_preview",
        "piece_request",
        "signal_comparison_start",
        "signal_comparison_run",
        "door_grant",
        REGISTRATION,
    ]
    assert all(body.index(f"perform 1 from {table} ") < first for table in locked)
    project_plane = body.index("pg_advisory_xact_lock(hashtextextended('world_project:'")
    societies = body.index("perform society_erase_rows(")
    assert project_plane < body.index("perform 1 from world_project ")
    assert body.index("perform 1 from signal_comparison_run ") < societies
    assert societies < body.index("perform 1 from door_grant ") < first


def test_the_erasure_deletes_every_child_before_its_parent(existence):
    """The order of the erasure's deletes against the schema's foreign keys: wherever one table it
    deletes from references another, the child's last delete comes before the parent's first.
    That holds for the tables no test here gives a row to as well."""
    admin = _admin(existence)
    body = admin.execute(
        "select pg_get_functiondef(%s::regprocedure) as body", (ERASED_WITH_ITS_WORLD,)
    ).fetchone()["body"]
    order = re.findall(r"delete from (\w+)", body)
    first = {table: order.index(table) for table in set(order)}
    last = {table: len(order) - 1 - order[::-1].index(table) for table in set(order)}
    checked = 0
    for child, parent, _, _ in _links(admin):
        if child != parent and child in first and parent in first:
            assert last[child] < first[parent], (child, parent)
            checked += 1
    assert checked > 150, checked
    assert order[-1] == REGISTRATION


# ---------------------------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------------------------


def test_one_world_is_erased_whole_and_every_other_world_keeps_every_row(existence, spine_schema):
    """The data-loss control. A workspace holding one of everything loses one world: every row
    that is that world's by the schema's keys, in every table that hangs from a world; each other
    world of the workspace keeps every row it had, the kind the workspace kept is kept, and
    another workspace keeps every row."""
    _one_of_everything(existence)
    _psycopg, scratch = spine_schema
    _budgets_and_citations(existence, scratch)
    admin = _admin(existence)
    workspace = existence.workspace_id
    _keep_a_kind(admin, workspace, existence.actor)
    _pictures(admin)
    worlds = _worlds(admin, workspace)
    assert len(worlds) >= 3, worlds
    before = {world: _world_rows(admin, workspace, world) for world in worlds}
    # The world with the most to lose is the one erased.
    erased = max(worlds, key=lambda world: sum(before[world].values()))
    held = {table for table, count in before[erased].items() if count}
    assert len(held) >= 40, sorted(held)
    # Each other world holds what the erased one holds of these, so a delete too wide would show.
    # Saved worlds' pictures (0218): some world keeps one, so a delete too wide would show; the
    # erasure of a world that has one is test_saved_entry_pictures_postgres.py's.
    assert sum(1 for world in worlds if before[world]["saved_world_entry_picture"]) >= 1
    for table, count in (
        ("world_minds_budget", 1),
        ("companion_answer_simulation_citation", 1),
        (NAMING_NO_KEY, 2),
    ):
        assert before[erased][table] == count, table
        assert sum(1 for world in worlds if before[world][table]) >= 2, table
    [stranger] = [
        row["workspace_id"]
        for row in admin.execute(
            "select distinct workspace_id from world_identity where workspace_id <> %s",
            (workspace,),
        ).fetchall()
    ]
    elsewhere = _workspace_rows(admin, stranger)
    assert elsewhere[REGISTRATION] == 1 and sum(elsewhere.values()) > 1
    cited_answers = [
        row["answer_id"]
        for row in admin.execute(
            "select answer_id from companion_answer_simulation_citation "
            "where workspace_id = %s and world_id = %s",
            (workspace, erased),
        ).fetchall()
    ]
    assert cited_answers

    _erase_one_world(admin, workspace, erased)

    after = _world_rows(admin, workspace, erased)
    assert not any(after.values()), {table: count for table, count in after.items() if count}
    # Check the known answer ids directly: after citations and versions are gone, a join through
    # them would miss orphaned spot labels, whose rows carry no world or version key.
    assert not admin.execute(
        "select 1 from companion_answer_simulation_label where workspace_id = %s "
        "and answer_id = any(%s)",
        (workspace, cited_answers),
    ).fetchall()
    assert _worlds(admin, workspace) == [world for world in worlds if world != erased]
    assert _tables_holding(admin, KEPT_LABEL) == {KEPT_KINDS}
    for world in worlds:
        if world != erased:
            assert _world_rows(admin, workspace, world) == before[world], world
    assert _workspace_rows(admin, stranger) == elsewhere


def test_a_workspace_tombstone_erases_every_world_it_holds_and_the_kinds_it_kept(
    existence, spine_schema
):
    """A workspace holding one of everything, and a kind it kept, is erased: no table that hangs
    from a world keeps a row of it, a title a person typed is in no table, and another workspace
    keeps every row."""
    _one_of_everything(existence)
    _psycopg, scratch = spine_schema
    _budgets_and_citations(existence, scratch)
    admin = _admin(existence)
    workspace = existence.workspace_id
    _keep_a_kind(admin, workspace, existence.actor)
    _pictures(admin)
    held = _workspace_rows(admin, workspace)
    assert held[REGISTRATION] >= 3 and sum(1 for count in held.values() if count) >= 50, held
    assert "saved_world_entry" in _tables_holding(admin, "A town")
    assert _tables_holding(admin, KEPT_LABEL) == {KEPT_KINDS}
    [stranger] = [
        row["workspace_id"]
        for row in admin.execute(
            "select distinct workspace_id from world_identity where workspace_id <> %s",
            (workspace,),
        ).fetchall()
    ]
    elsewhere = _workspace_rows(admin, stranger)

    with scratch_role_database(scratch, _RUNTIME_ROLE).session(workspace) as runtime:
        runtime.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the workspace is erased')",
            (workspace, existence.actor),
        )

    after = _workspace_rows(admin, workspace)
    kept = {table: count for table, count in after.items() if count}
    assert set(kept) <= {ERASURE_RECORD}, kept
    assert not _tables_holding(admin, "A town") and not _tables_holding(admin, KEPT_LABEL)
    assert _workspace_rows(admin, stranger) == elsewhere


def test_nobody_but_the_erasure_deletes_a_world_s_record(existence):
    """The schema's owner, which row-level security does not bind, is refused by name."""
    existence.real("/world-entries/{entry_id}")
    admin = _admin(existence)
    for table in ("saved_world_entry", "world_alternate_version", REGISTRATION):
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="erased whole"),
            admin.transaction(),
        ):
            admin.execute(
                sql.SQL("delete from {} where workspace_id = %s").format(sql.Identifier(table)),
                (existence.workspace_id,),
            )
    set_workspace(admin, existence.workspace_id)


def test_world_erasure_preserves_prior_society_erasure_records(existence):
    _one_of_everything(existence)
    admin, workspace = _admin(existence), existence.workspace_id
    society = admin.execute(
        "select world_id, version_id from world_society where workspace_id = %s limit 1",
        (workspace,),
    ).fetchone()
    assert society is not None
    erasure = erase_society(
        admin, workspace, society["world_id"], society["version_id"], erased_by=existence.actor
    )
    before = admin.execute(
        "select to_jsonb(e) as record from society_erasure e where erasure_id = %s", (erasure,)
    ).fetchone()
    _erase_one_world(admin, workspace, society["world_id"])
    assert (
        admin.execute(
            "select to_jsonb(e) as record from society_erasure e where erasure_id = %s", (erasure,)
        ).fetchone()
        == before
    )
    assert (
        admin.execute(
            "select 1 from world_identity where workspace_id = %s and world_id = %s",
            (workspace, society["world_id"]),
        ).fetchone()
        is None
    )


def test_runtime_cannot_invoke_erasure_without_an_authorized_trigger(existence, spine_schema):
    existence.real("/world-entries/{entry_id}")
    _, scratch = spine_schema
    workspace = existence.workspace_id
    before = _workspace_rows(_admin(existence), workspace)
    with (
        scratch_role_database(scratch, _RUNTIME_ROLE).session(workspace) as runtime,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        runtime.transaction(),
    ):
        runtime.execute("select world_erase_rows(%s, %s)", (workspace, "any-world"))
    assert _workspace_rows(_admin(existence), workspace) == before


# ---------------------------------------------------------------------------------------------
# The migration
# ---------------------------------------------------------------------------------------------

#: The erasure's migration, found by its title, so renumbering it at landing changes nothing here.
ERASURE_TITLE = "_a_workspace_s_erasure_takes_its_worlds.sql"
#: pg_trigger.tgtype's bits (PostgreSQL's trigger.h): a row trigger, before, and delete.
ROW, BEFORE, DELETE = 1, 2, 8


def _triggers(admin) -> dict[tuple[str, str], tuple[int, str, str]]:
    return {
        (row[0], row[1]): (row[2], row[3], row[4])
        for row in admin.execute(
            "select c.relname, t.tgname, t.tgtype, t.tgfoid::regproc::text, t.tgenabled::text "
            "from pg_trigger t join pg_class c on c.oid = t.tgrelid "
            "where c.relnamespace = current_schema()::regnamespace and not t.tgisinternal"
        ).fetchall()
    }


def _forced(admin) -> dict[str, bool]:
    return {
        row[0]: row[1]
        for row in admin.execute(
            "select c.relname, c.relforcerowsecurity from pg_class c "
            "where c.relnamespace = current_schema()::regnamespace and c.relkind = 'r'"
        ).fetchall()
    }


def test_every_guard_the_erasure_rebuilt_keeps_every_event_but_delete(monkeypatch):
    """The erasure rebuilds 47 guards without delete and drops 5 that guarded delete alone, from a
    list written out of the schema. Read from pg_trigger on a schema of this test's own, before
    the migration and after it: every trigger of a table that takes the new guard keeps its
    function, its timing and every event it had but delete; 52 lost delete, 5 of them whole; 69
    tables take the new guard, before each row; no other table's trigger changed; and the
    migration leaves every trigger enabled and every table's row-level security forced as it
    was."""
    everything = list(migrations())
    [erasure] = [m for m in everything if m.path.name.endswith(ERASURE_TITLE)]
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness,
            "migrations",
            lambda: iter(m for m in everything if m.version < erasure.version),
        )
        with pg_harness.migrated_schema() as (_psycopg, admin):
            before, forced = _triggers(admin), _forced(admin)
            admin.execute(erasure.sql)
            admin.commit()
            after, forced_after = _triggers(admin), _forced(admin)
    guarded = {table for table, name in after if name == WORLD_GUARD}
    assert len(guarded) == 69, sorted(guarded)
    for table in guarded:
        assert after[(table, WORLD_GUARD)] == (ROW | BEFORE | DELETE, WORLD_GUARD, "O"), table
    rebuilt, dropped = set(), set()
    for (table, name), (events, function, enabled) in before.items():
        if table not in guarded:
            assert after.get((table, name)) == (events, function, enabled), (table, name)
            continue
        if (table, name) not in after:
            assert events & ~(ROW | BEFORE) == DELETE, (table, name, events)
            dropped.add((table, name))
            continue
        kept, kept_function, kept_enabled = after[(table, name)]
        assert (kept_function, kept_enabled) == (function, enabled), (table, name)
        assert kept & ~DELETE == events & ~DELETE, (table, name, events, kept)
        if events & DELETE and not kept & DELETE:
            rebuilt.add((table, name))
    assert (len(rebuilt), len(dropped)) == (47, 5), (sorted(rebuilt), sorted(dropped))
    added = {key for key in after if key not in before}
    assert added == {(table, WORLD_GUARD) for table in guarded} | {
        ("tombstone", "tg_world_erases_on_tombstone"),
        ("piece_erasure_settlement", "tg_piece_erasure_settlement_append_only"),
        ("piece_erasure_settlement_event", "tg_piece_erasure_settlement_event"),
        ("piece_erasure_settlement", "tg_sealed_checkpoint_refuses_withdrawals"),
        ("piece_erasure_settlement_event", "tg_sealed_checkpoint_refuses_withdrawals"),
    }
    assert all(enabled == "O" for _events, _function, enabled in after.values())
    assert forced_after == {
        **forced,
        "piece_erasure_settlement": True,
        "piece_erasure_settlement_event": True,
    }


def test_upgrade_erases_existing_workspace_worlds_and_preserves_other_workspaces(monkeypatch):
    """Real saved entries and kept kinds precede the migration: an already-effective erasure
    loses its world rows on upgrade while an unrelated workspace remains byte-for-byte intact.
    Guards and forced row security survive the one-off as they do an empty-schema upgrade.
    """
    everything = list(migrations())
    [erasure] = [m for m in everything if m.path.name.endswith(ERASURE_TITLE)]
    monkeypatch.setattr(
        pg_harness, "migrations", lambda: iter(m for m in everything if m.version < erasure.version)
    )
    with pg_harness.migrated_schema() as (_, admin):
        forced = _forced(admin)
        admin.row_factory = dict_row
        erased, kept, actor = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        # The historical schema holds neither erased ids nor explicit support bindings.
        # Restore that exact schema before applying its erasure migration.
        with historical_world_fixture_schema(admin, support=True):
            for workspace in (erased, kept):
                set_workspace(admin, workspace)
                entry = SavedWorldEntryRepository(admin, workspace).create_starter(
                    title=f"Upgrade world {workspace}", created_by=actor
                )
                _keep_a_kind(admin, workspace, actor)
                if workspace == erased:
                    _queued(admin, workspace, world_id=entry.world_id)
                    [batch] = batches.batches_in_flight(admin, workspace)
                    batches.end_batch(
                        admin,
                        workspace,
                        batch,
                        state="expired",
                        ended_at=dt.datetime.now(dt.UTC),
                        settlements={
                            r.piece_request_id: ("reported", Decimal("0.012345"))
                            for r in batch.requests
                        },
                    )
                    _queued(admin, workspace, world_id=entry.world_id)
        set_workspace(admin, erased)
        obligation_columns = (
            "workspace_id",
            "piece_request_id",
            "reservation_id",
            "reservation_authority_id",
            "reservation_holder",
            "piece_batch_id",
            "worst_case_usd",
            "basis",
            "usd",
        )
        expected_obligations = admin.execute(
            "select p.workspace_id,p.piece_request_id,p.reservation_id,p.reservation_authority_id,"
            "p.reservation_holder,p.piece_batch_id,p.worst_case_usd,s.basis,s.usd "
            "from piece_request p left join piece_settlement s "
            "using(workspace_id,piece_request_id) "
            "where p.workspace_id=%s order by p.piece_request_id",
            (erased,),
        ).fetchall()
        assert {row["basis"] for row in expected_obligations} == {None, "reported"}
        tombstone = admin.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'erased before world erasure migration') "
            "returning tombstone_id",
            (erased, actor),
        ).fetchone()["tombstone_id"]
        before = _workspace_rows(admin, erased)
        assert before[REGISTRATION] and before["saved_world_entry"] and before[KEPT_KINDS]
        tables = sorted(_hanging_from_a_world(_links(admin)) | {NAMING_NO_KEY, KEPT_KINDS})

        def kept_rows():
            return {
                table: admin.execute(
                    sql.SQL(
                        "select to_jsonb(x) as row from {} x where workspace_id = %s "
                        "order by to_jsonb(x)::text"
                    ).format(sql.Identifier(table)),
                    (kept,),
                ).fetchall()
                for table in tables
            }

        elsewhere = kept_rows()
        admin.commit()
        admin.execute(erasure.sql)
        admin.commit()
        remaining = _workspace_rows(admin, erased)
        assert not any(remaining.values()), remaining
        assert kept_rows() == elsewhere
        assert (
            admin.execute(
                "select " + ",".join(obligation_columns) + " from piece_erasure_settlement "
                "where workspace_id=%s order by piece_request_id",
                (erased,),
            ).fetchall()
            == expected_obligations
        )
        assert admin.execute(
            "select 1 from tombstone where tombstone_id = %s", (tombstone,)
        ).fetchone()
        admin.row_factory = psycopg.rows.tuple_row
        assert _forced(admin) == {
            **forced,
            "piece_erasure_settlement": True,
            "piece_erasure_settlement_event": True,
        }
        assert all(enabled == "O" for _, _, enabled in _triggers(admin).values())
