"""A creature's made look, asked as a row, made by the operator's run and worn by its kind
(migration 0220, :mod:`exulanica.world.creature_look_jobs`).

What is shown, against PostgreSQL, as the deployed writer (the runtime role) unless said:

*   asking queues one look job for a creature the workspace keeps, and asking again while it waits
    answers that one; a kind the workspace does not keep, or one that is no creature, is refused,
    and so is a requester at their limit; a workspace being erased asks nothing more;
*   any member of the workspace reads a job, as anyone asking again for that creature is answered
    with it;
*   a run stages a queued job with its request's digest and ends it once: made, naming a look the
    workspace keeps, which the kind then wears; refused by code; a run other than the one that
    staged it ends nothing; the kind's newest kept look is the one worn, and look choices name it;
*   the rows change only forward: a job is inserted queued and nothing else, a staged job never goes
    back to queued, an ended one never changes, who asked and for which creature never change, a
    staged job keeps its run, and a kind look is never updated;
*   a kind look is appended under the workspace's lock, so a creature's erasure asked meanwhile
    waits for it and then deletes it: no kind look names an erased creature; a run ending a job and
    wearing its look in one transaction takes that lock before the job's row, as an erasure does,
    so the two wait for each other in turn and never in a cycle;
*   a job is dated by the statement that asks it, whatever the row says;
*   the rows go only through an erasure: the runtime holds no delete, the table owner is refused by
    the guards, and only the definer owner deletes; row-level security is forced on both tables;
*   a creature's erasure deletes its look jobs and kind looks and nothing of another creature; a
    workspace tombstone deletes every look job and kind look of its workspace.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.db.session import set_workspace
from exulanica.errors import TombstonedError
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world import creature_look_jobs as look_jobs
from exulanica.world.thing_store import ThingStore

from conftest import scratch_role_database
from test_thing_store_postgres import ACTOR, _creature

pytestmark = pytest.mark.postgres

OTHER = uuid.UUID("00000000-0000-4000-8000-00000000c5a3")
RUN = uuid.UUID("00000000-0000-4000-8000-0000000052e0")
REQUEST = "1" * 64


def _runtime(spine_schema, workspace_id):
    return scratch_role_database(spine_schema[1], RUNTIME_ROLE).session(workspace_id)


@pytest.fixture
def provisioned(repository):
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return repository


def _kept(connection, workspace_id, root: Path, *creatures):
    store = ThingStore(connection, workspace_id, LocalContentAddressedStore(root))
    for creature in creatures:
        store.keep_creature(creature, created_by=ACTOR)
    return store


def _count(connection, table: str) -> int:
    return connection.execute(f"select count(*) as n from {table}").fetchone()["n"]


def test_a_look_is_asked_once_for_a_kept_creature(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
        asked = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        assert (asked.status, asked.kind_sha256, asked.requested_by) == (
            "queued",
            creature.kind.sha256,
            ACTOR,
        )
        assert asked.run_id is None and asked.finished_at is None
        again = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=OTHER
        )
        assert again.look_id == asked.look_id and _count(connection, "creature_look") == 1
        # Any member reads it: the second asker was answered with it.
        assert look_jobs.read_look(connection, workspace_id, asked.look_id) == again
        with pytest.raises(look_jobs.LookNotAsked):
            look_jobs.ask_look(connection, workspace_id, kind_sha256="2" * 64, requested_by=ACTOR)
        # A digest that names something else the workspace keeps (its sketch look) is no creature.
        with pytest.raises(look_jobs.LookNotAsked):
            look_jobs.ask_look(
                connection, workspace_id, kind_sha256=creature.sketch.sha256, requested_by=ACTOR
            )


def test_a_requester_at_their_limit_asks_no_more(provisioned, spine_schema, tmp_path, monkeypatch):
    first, second = _creature(), _creature("store dragon", "dragon")
    workspace_id = provisioned.workspace_id
    monkeypatch.setattr(look_jobs, "MAX_OPEN_PER_ACTOR", 1)
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, first, second)
        look_jobs.ask_look(
            connection, workspace_id, kind_sha256=first.kind.sha256, requested_by=ACTOR
        )
        with pytest.raises(look_jobs.LookLimitReached):
            look_jobs.ask_look(
                connection, workspace_id, kind_sha256=second.kind.sha256, requested_by=ACTOR
            )
        # Another requester is counted alone.
        look_jobs.ask_look(
            connection, workspace_id, kind_sha256=second.kind.sha256, requested_by=OTHER
        )


def test_a_run_stages_a_look_and_ends_it_once_and_the_kind_wears_it(
    provisioned, spine_schema, tmp_path
):
    creature, refused_one = _creature(), _creature("store dragon", "dragon")
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature, refused_one)
        made = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        refused = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=refused_one.kind.sha256, requested_by=ACTOR
        )
        assert [
            look.look_id for look in look_jobs.queued_looks(connection, workspace_id, limit=8)
        ] == [
            made.look_id,
            refused.look_id,
        ]
        for look in (made, refused):
            assert look_jobs.stage_look(
                connection, workspace_id, look.look_id, run_id=RUN, request_sha256=REQUEST
            )
        # Staged once: a second staging changes nothing.
        assert not look_jobs.stage_look(
            connection, workspace_id, made.look_id, run_id=uuid.uuid4(), request_sha256=REQUEST
        )
        assert look_jobs.queued_looks(connection, workspace_id, limit=8) == []
        # A run other than the one that staged it ends nothing.
        assert (
            look_jobs.end_look(
                connection,
                workspace_id,
                made.look_id,
                run_id=uuid.uuid4(),
                status="failed",
                failure="job_failed",
            )
            is None
        )
        # The sketch stands for the made look: a look this workspace keeps, on the creature's plan.
        with connection.transaction():
            ended = look_jobs.end_look(
                connection,
                workspace_id,
                made.look_id,
                run_id=RUN,
                status="made",
                look_sha256=creature.sketch.sha256,
                cost_usd=Decimal("0.0375"),
            )
            assert ended is not None
            look_jobs.wear_by_kind(
                connection,
                workspace_id,
                kind_sha256=creature.kind.sha256,
                look_sha256=creature.sketch.sha256,
                chosen_by=ACTOR,
                look_id=made.look_id,
            )
        assert (ended.status, ended.look_sha256, ended.cost_usd) == (
            "made",
            creature.sketch.sha256,
            Decimal("0.03750000"),
        )
        with connection.transaction():
            look_jobs.end_look(
                connection,
                workspace_id,
                refused.look_id,
                run_id=RUN,
                status="refused",
                refusal_code="rig_chain_not_found",
            )
        # Ended once.
        assert (
            look_jobs.end_look(
                connection,
                workspace_id,
                made.look_id,
                run_id=RUN,
                status="cancelled",
                failure="cancelled_by_operator",
            )
            is None
        )
        worn = look_jobs.kind_looks(connection, workspace_id)
        assert {kind: look.sha256 for kind, look in worn.items()} == {
            creature.kind.sha256: creature.sketch.sha256
        }
        # A look the workspace does not keep is never worn.
        with pytest.raises(look_jobs.LookNotAsked):
            look_jobs.wear_by_kind(
                connection,
                workspace_id,
                kind_sha256=creature.kind.sha256,
                look_sha256="3" * 64,
                chosen_by=ACTOR,
            )


def test_the_newest_kind_look_still_kept_is_worn(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _kept(connection, workspace_id, tmp_path, creature)
        look_jobs.wear_by_kind(
            connection,
            workspace_id,
            kind_sha256=creature.kind.sha256,
            look_sha256=creature.sketch.sha256,
            chosen_by=ACTOR,
        )
        assert set(look_jobs.kind_looks(connection, workspace_id)) == {creature.kind.sha256}
        # Withdrawn, it is worn no more, and nothing older stands in for it.
        store.withdraw_look(creature.sketch.look, 1, "no longer worn", withdrawn_by=ACTOR)
        assert look_jobs.kind_looks(connection, workspace_id) == {}


def test_the_rows_change_only_forward(provisioned, spine_schema, tmp_path):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
        asked = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        refusals = (
            # Queued straight to an end other than cancelled.
            "update creature_look set status='failed', failure='x', finished_at=now()",
            # Who asked, and for which creature.
            "update creature_look set requested_by=gen_random_uuid()",
            "update creature_look set kind_sha256=repeat('4', 64)",
        )
        for statement in refusals:
            with (
                pytest.raises(psycopg.errors.IntegrityConstraintViolation),
                connection.transaction(),
            ):
                connection.execute(statement)
        look_jobs.stage_look(
            connection, workspace_id, asked.look_id, run_id=RUN, request_sha256=REQUEST
        )
        for statement in (
            "update creature_look set status='queued', run_id=null, request_sha256=null, "
            "staged_at=null",
            "update creature_look set run_id=gen_random_uuid()",
        ):
            with (
                pytest.raises(psycopg.errors.IntegrityConstraintViolation),
                connection.transaction(),
            ):
                connection.execute(statement)
        with connection.transaction():
            look_jobs.end_look(
                connection,
                workspace_id,
                asked.look_id,
                run_id=RUN,
                status="failed",
                failure="job_failed",
            )
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation), connection.transaction():
            connection.execute("update creature_look set failure='other'")
        # A job is inserted queued, and nothing else: not made, refused or staged.
        for status, columns, values in (
            (
                "made",
                "run_id, request_sha256, staged_at, look_sha256, finished_at, cost_usd",
                f"gen_random_uuid(), '{REQUEST}', now(), '{'7' * 64}', now(), 0",
            ),
            (
                "refused",
                "run_id, request_sha256, staged_at, refusal_code, finished_at",
                f"gen_random_uuid(), '{REQUEST}', now(), 'rig_chain_not_found', now()",
            ),
            (
                "staged",
                "run_id, request_sha256, staged_at",
                f"gen_random_uuid(), '{REQUEST}', now()",
            ),
        ):
            with (
                pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="asked queued"),
                connection.transaction(),
            ):
                connection.execute(
                    "insert into creature_look (workspace_id, look_id, requested_by, kind_sha256, "
                    f"status, {columns}) values (%s, gen_random_uuid(), %s, %s, %s, {values})",
                    (workspace_id, ACTOR, "8" * 64, status),
                )
        # A row dated back is dated by the statement that asks it: the limits count these dates.
        with connection.transaction():
            connection.execute(
                "insert into creature_look (workspace_id, look_id, requested_by, kind_sha256, "
                "created_at) values (%s, gen_random_uuid(), %s, %s, '2000-01-01')",
                (workspace_id, ACTOR, "a" * 64),
            )
            dated = connection.execute(
                "select created_at > now() - interval '1 hour' as now from creature_look "
                "where kind_sha256 = %s",
                ("a" * 64,),
            ).fetchone()
            assert dated["now"]
            raise psycopg.Rollback()
        # A cost belongs to a run's end.
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "insert into creature_look (workspace_id, look_id, requested_by, kind_sha256, "
                "cost_usd) values (%s, gen_random_uuid(), %s, %s, 1)",
                (workspace_id, ACTOR, "5" * 64),
            )


def test_the_rows_go_only_through_an_erasure_and_stay_in_their_workspace(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
        look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        look_jobs.wear_by_kind(
            connection,
            workspace_id,
            kind_sha256=creature.kind.sha256,
            look_sha256=creature.sketch.sha256,
            chosen_by=ACTOR,
        )
        for table in ("creature_look", "kind_look"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(f"delete from {table}")
        # The runtime may append a kind look and never update one.
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute("update kind_look set look_id = null")
    # Another workspace's session reads none of them.
    with _runtime(spine_schema, uuid.uuid4()) as connection:
        assert [_count(connection, table) for table in ("creature_look", "kind_look")] == [0, 0]
    owner = provisioned.connection
    set_workspace(owner, workspace_id)
    owner.commit()
    for statement, said in (
        ("delete from creature_look", "never alone"),
        ("delete from kind_look", "append-only"),
        ("update kind_look set look_id = null", "append-only"),
    ):
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match=said):
            owner.execute(statement)
        owner.rollback()
    # Row-level security is forced, so it holds the tables' owner too, keyed on the workspace.
    for table in ("creature_look", "kind_look"):
        row = owner.execute(
            "select c.relrowsecurity, c.relforcerowsecurity, p.policyname, p.qual "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "left join pg_policies p on p.schemaname = n.nspname and p.tablename = c.relname "
            "where n.nspname = current_schema() and c.relname = %s",
            (table,),
        ).fetchone()
        assert (row["relrowsecurity"], row["relforcerowsecurity"]) == (True, True), table
        assert row["policyname"] == "ws_isolation" and "current_workspace()" in row["qual"]
    owner.rollback()
    # The one exception: the definer owner, whose two erasing bodies alone run as it.
    set_workspace(owner, workspace_id)
    with owner.transaction():
        owner.execute("set local role exulanica_definer")
        assert owner.execute("delete from creature_look").rowcount == 1
        assert owner.execute("delete from kind_look").rowcount == 1
        raise psycopg.Rollback()
    owner.commit()


def test_a_creature_s_erasure_takes_its_look_jobs_and_kind_looks_only(
    provisioned, spine_schema, tmp_path
):
    erased, kept = _creature(), _creature("store dragon", "dragon")
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        store = _kept(connection, workspace_id, tmp_path, erased, kept)
        for creature in (erased, kept):
            look_jobs.ask_look(
                connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
            )
            look_jobs.wear_by_kind(
                connection,
                workspace_id,
                kind_sha256=creature.kind.sha256,
                look_sha256=creature.sketch.sha256,
                chosen_by=ACTOR,
            )
        store.erase_creature(erased.kind.sha256, erased_by=ACTOR)
        for table in ("creature_look", "kind_look"):
            rows = connection.execute(f"select kind_sha256 from {table}").fetchall()
            assert [row["kind_sha256"] for row in rows] == [kept.kind.sha256], table


def test_a_workspace_tombstone_takes_every_look_job_and_kind_look(
    provisioned, spine_schema, tmp_path
):
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
        look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        look_jobs.wear_by_kind(
            connection,
            workspace_id,
            kind_sha256=creature.kind.sha256,
            look_sha256=creature.sketch.sha256,
            chosen_by=ACTOR,
        )
    provisioned.insert_tombstone(
        scope="workspace", requested_by=uuid.uuid4(), reason="the person left"
    )
    with _runtime(spine_schema, workspace_id) as connection:
        assert [_count(connection, table) for table in ("creature_look", "kind_look")] == [0, 0]
        # Erased, the workspace asks nothing more.
        with pytest.raises(TombstonedError):
            look_jobs.ask_look(
                connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
            )


def test_a_kind_look_and_its_creature_s_erasure_never_interleave(
    provisioned, spine_schema, tmp_path, monkeypatch
):
    """The look is worn under the workspace's lock, which a creature's erasure takes too. An erasure
    asked after the wearing checked the creature, and before it appended the row, waits for it and
    then deletes the row; without the lock it would commit first and leave a kind look naming an
    erased creature."""
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
    checked, proceed = threading.Event(), threading.Event()
    kept = look_jobs.admitted_look_by_digest

    def held_open(connection, workspace, sha256):
        found = kept(connection, workspace, sha256)
        checked.set()
        proceed.wait(10)
        return found

    monkeypatch.setattr(look_jobs, "admitted_look_by_digest", held_open)
    failures: list[BaseException] = []

    def wear() -> None:
        try:
            with _runtime(spine_schema, workspace_id) as connection:
                look_jobs.wear_by_kind(
                    connection,
                    workspace_id,
                    kind_sha256=creature.kind.sha256,
                    look_sha256=creature.sketch.sha256,
                    chosen_by=ACTOR,
                )
        except BaseException as error:  # reported below
            failures.append(error)

    def erase() -> None:
        try:
            with _runtime(spine_schema, workspace_id) as connection:
                ThingStore(connection, workspace_id, None).erase_creature(
                    creature.kind.sha256, erased_by=ACTOR
                )
        except BaseException as error:  # reported below
            failures.append(error)

    wearer = threading.Thread(target=wear)
    wearer.start()
    assert checked.wait(10), "the wearing reached its check"
    eraser = threading.Thread(target=erase)
    eraser.start()
    # Without the lock the erasure commits here; with it, it waits for the wearing to commit.
    eraser.join(2)
    proceed.set()
    wearer.join(10)
    eraser.join(10)
    assert not wearer.is_alive() and not eraser.is_alive()
    assert failures == []
    with _runtime(spine_schema, workspace_id) as connection:
        assert _count(connection, "kind_look") == 0
        assert (
            ThingStore(connection, workspace_id, None).kind_by_digest(creature.kind.sha256) is None
        )


def test_a_run_s_end_and_wear_and_a_creature_s_erasure_never_close_a_cycle(
    provisioned, spine_schema, tmp_path
):
    """A run ends a job and wears its look in one transaction; a creature's erasure takes the
    workspace's lock and then its trigger deletes the job's row. The end takes the workspace's lock
    before the job's row, so an erasure asked between the end and the wear waits for the run's
    commit and then deletes what it made; were the end to lock the row first, the two would wait
    on each other and the database would end one of them."""
    creature = _creature()
    workspace_id = provisioned.workspace_id
    with _runtime(spine_schema, workspace_id) as connection:
        _kept(connection, workspace_id, tmp_path, creature)
        asked = look_jobs.ask_look(
            connection, workspace_id, kind_sha256=creature.kind.sha256, requested_by=ACTOR
        )
        look_jobs.stage_look(
            connection, workspace_id, asked.look_id, run_id=RUN, request_sha256=REQUEST
        )
    ended, proceed = threading.Event(), threading.Event()
    failures: list[BaseException] = []

    def end_and_wear() -> None:
        try:
            with _runtime(spine_schema, workspace_id) as connection, connection.transaction():
                look_jobs.end_look(
                    connection,
                    workspace_id,
                    asked.look_id,
                    run_id=RUN,
                    status="made",
                    look_sha256=creature.sketch.sha256,
                )
                ended.set()
                proceed.wait(10)
                look_jobs.wear_by_kind(
                    connection,
                    workspace_id,
                    kind_sha256=creature.kind.sha256,
                    look_sha256=creature.sketch.sha256,
                    chosen_by=ACTOR,
                    look_id=asked.look_id,
                )
        except BaseException as error:  # reported below
            failures.append(error)

    def erase() -> None:
        try:
            with _runtime(spine_schema, workspace_id) as connection:
                ThingStore(connection, workspace_id, None).erase_creature(
                    creature.kind.sha256, erased_by=ACTOR
                )
        except BaseException as error:  # reported below
            failures.append(error)

    run = threading.Thread(target=end_and_wear)
    run.start()
    assert ended.wait(10), "the run ended its job"
    eraser = threading.Thread(target=erase)
    eraser.start()
    # The erasure now waits for the run's lock; were the run holding the row alone, the erasure
    # would take the lock, wait on the row, and the run's wear would close the cycle.
    eraser.join(2)
    proceed.set()
    run.join(15)
    eraser.join(15)
    assert not run.is_alive() and not eraser.is_alive()
    assert failures == []
    with _runtime(spine_schema, workspace_id) as connection:
        assert [_count(connection, table) for table in ("creature_look", "kind_look")] == [0, 0]
