"""World projects at the repository and the database: concurrency, retries and the guards.

The HTTP behaviour is in ``tests/test_project_context_api.py``. These hold what only two
connections can show (a retry that waited for the request it repeats, the same key committed
first elsewhere, a creation racing its workspace's deletion), what a database that ends a write
to break a lock cycle gets back, and the rules migration 0127 enforces whatever the caller.
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.world.companion_memory import (
    AnswerComposed,
    CompanionMemoryRepository,
    RecordedAnswer,
)
from exulanica.world.project_context import (
    IdempotencyKeyReused,
    ItemBasis,
    ItemKind,
    ProjectContextBusy,
    ProjectContextRepository,
    ReferenceRefused,
)
from exulanica.world.starter import create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "exulanica"
    / "migrations"
    / "0127_a_world_project_keeps_what_its_person_chose.sql"
)


def _connection(spine_schema, workspace_id):
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.row_factory = dict_row
    set_workspace(connection, workspace_id)
    return connection


def _world(connection, workspace, actor) -> tuple[str, uuid.UUID]:
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection, workspace_id=workspace, actor=actor, title="Projects", world_id=world_id
        )
    return world_id, version_id


@pytest.fixture
def made(repository):
    """One person's project in a starter world, committed."""
    connection = repository.connection
    workspace, actor = repository.workspace_id, uuid.uuid4()
    set_workspace(connection, workspace)
    world_id, version_id = _world(connection, workspace, actor)
    projects = ProjectContextRepository(connection, workspace, actor, world_id)
    project, _ = projects.create_project(title="Concurrency", version_id=version_id)
    return {
        "workspace": workspace,
        "actor": actor,
        "world": world_id,
        "version": version_id,
        "project": project.project_id,
        "revision": project.revision,
        "projects": projects,
    }


def _waiting(observer, pid: int, seconds: float = 10.0) -> None:
    """Wait until backend ``pid`` is waiting for a lock, or fail."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        row = observer.execute(
            "select wait_event_type from pg_stat_activity where pid=%s", (pid,)
        ).fetchone()
        if row is not None and row["wait_event_type"] == "Lock":
            return
        time.sleep(0.02)
    raise AssertionError(f"backend {pid} never waited for a lock")


def _in_threads(calls) -> tuple[list[threading.Thread], list]:
    """Start each call on its own thread; the threads, and what each returned or raised."""
    outcomes: list = [None] * len(calls)

    def run(index, call) -> None:
        try:
            outcomes[index] = call()
        except BaseException as exc:  # reported to the test thread
            outcomes[index] = exc

    threads = [threading.Thread(target=run, args=pair) for pair in enumerate(calls)]
    for thread in threads:
        thread.start()
    return threads, outcomes


def _joined(threads) -> None:
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive(), "a request never finished"


# -- two connections ------------------------------------------------------------------------


def test_a_retry_that_waited_for_the_request_it_repeats_is_answered_with_it(spine_schema, made):
    """Both requests pass the key check before either holds the project; the one that waits is
    answered with what the first made, not refused as stale by the revision the first moved."""
    holder = _connection(spine_schema, made["workspace"])
    observer = _connection(spine_schema, made["workspace"])
    retries = [_connection(spine_schema, made["workspace"]) for _ in range(2)]
    key = uuid.uuid4()

    def add(connection):
        return lambda: ProjectContextRepository(
            connection, made["workspace"], made["actor"], made["world"]
        ).add_item(
            made["project"],
            base_revision=made["revision"],
            kind=ItemKind.GOAL,
            basis=ItemBasis.USER_STATEMENT,
            text="kept once",
            idempotency_key=key,
        )

    try:
        holder.execute("begin")
        holder.execute(
            "select 1 from world_project where workspace_id=%s and project_id=%s for update",
            (made["workspace"], made["project"]),
        )
        threads, outcomes = _in_threads([add(connection) for connection in retries])
        for connection in retries:
            _waiting(observer, connection.info.backend_pid)
        holder.execute("commit")
        _joined(threads)
    finally:
        for connection in (holder, observer, *retries):
            connection.close()
    assert not any(isinstance(o, BaseException) for o in outcomes), outcomes
    assert sorted(created for _item, created in outcomes) == [False, True]
    assert len({item.item_id for item, _created in outcomes}) == 1
    [row] = (
        made["projects"]
        .connection.execute(
            "select count(*) as n from world_project_item where workspace_id=%s and request_id=%s",
            (made["workspace"], key),
        )
        .fetchall()
    )
    assert row["n"] == 1


def test_a_key_committed_first_in_another_world_is_refused_by_name(spine_schema, made):
    """The second creation passes the key check while the first is uncommitted, then meets the
    first's key in the unique index: it answers the reused key, not a server error."""
    other_world, other_version = _world(
        made["projects"].connection, made["workspace"], made["actor"]
    )
    first = _connection(spine_schema, made["workspace"])
    second = _connection(spine_schema, made["workspace"])
    observer = _connection(spine_schema, made["workspace"])
    key = uuid.uuid4()
    try:
        first.execute("begin")
        ProjectContextRepository(
            first, made["workspace"], made["actor"], made["world"]
        ).create_project(title="Same key", version_id=made["version"], idempotency_key=key)
        threads, outcomes = _in_threads(
            [
                lambda: ProjectContextRepository(
                    second, made["workspace"], made["actor"], other_world
                ).create_project(title="Same key", version_id=other_version, idempotency_key=key)
            ]
        )
        _waiting(observer, second.info.backend_pid)
        first.execute("commit")
        _joined(threads)
    finally:
        for connection in (first, second, observer):
            connection.close()
    [refused] = outcomes
    assert isinstance(refused, IdempotencyKeyReused), refused
    assert (refused.status, refused.code) == (409, "idempotency_key_reused")


def test_a_project_created_while_its_workspace_is_deleted_does_not_outlive_it(spine_schema, made):
    """The tombstone holds the project plane's key; a creation waits for it and is then refused,
    rather than committing a live project the tombstone's cascade never saw."""
    deleter = _connection(spine_schema, made["workspace"])
    creator = _connection(spine_schema, made["workspace"])
    observer = _connection(spine_schema, made["workspace"])
    try:
        deleter.execute("begin")
        deleter.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'creation race')",
            (made["workspace"], made["actor"]),
        )
        threads, outcomes = _in_threads(
            [
                lambda: ProjectContextRepository(
                    creator, made["workspace"], made["actor"], made["world"]
                ).create_project(title="Too late", version_id=made["version"])
            ]
        )
        _waiting(observer, creator.info.backend_pid)
        deleter.execute("commit")
        _joined(threads)
    finally:
        for connection in (deleter, creator, observer):
            connection.close()
    [refused] = outcomes
    # The tombstone invalidated the version's source; the database's guard stands behind that.
    assert isinstance(refused, ReferenceRefused), refused
    assert (refused.status, refused.code) == (409, "invalidated_source_version")
    live = made["projects"].connection.execute(
        "select count(*) as n from world_project where workspace_id=%s and withdrawn_at is null",
        (made["workspace"],),
    )
    assert live.fetchone()["n"] == 0


# -- a write the database ended to break a lock cycle ---------------------------------------


def _goal(made, **extra):
    return made["projects"].add_item(
        made["project"],
        base_revision=made["projects"].project(made["project"]).revision,
        kind=ItemKind.GOAL,
        basis=ItemBasis.USER_STATEMENT,
        text="tried again",
        **extra,
    )


def test_a_write_ended_by_a_deadlock_is_tried_again_in_a_new_transaction(made):
    projects = made["projects"]
    real = projects._add_item
    ended: list[int] = []

    def once(*args, **kwargs):
        if not ended:
            ended.append(1)
            raise psycopg.errors.DeadlockDetected("deadlock detected")
        return real(*args, **kwargs)

    projects._add_item = once
    item, created = _goal(made)
    assert created and ended == [1]
    assert projects.item(made["project"], item.item_id).text == "tried again"


def test_a_write_ended_by_a_deadlock_every_time_answers_busy(made):
    projects = made["projects"]
    tries: list[int] = []

    def always(*_args, **_kwargs):
        tries.append(1)
        raise psycopg.errors.DeadlockDetected("deadlock detected")

    projects._add_item = always
    with pytest.raises(ProjectContextBusy) as busy:
        _goal(made)
    assert len(tries) == 3
    assert (busy.value.status, busy.value.code) == (503, "project_context_busy")


# -- the rules the database holds, whatever the caller --------------------------------------


def _refused(connection, statement, params, message):
    with (
        pytest.raises(psycopg.errors.IntegrityConstraintViolation, match=message),
        connection.transaction(),
    ):
        connection.execute(statement, params)


def test_the_database_holds_ownership_acceptance_and_finality(made):
    connection = made["projects"].connection
    item, _ = _goal(made)
    workspace = made["workspace"]
    _refused(
        connection,
        "insert into world_project_item (workspace_id, world_id, project_id, author_actor_id, "
        "kind, status) values (%s, %s, %s, %s, 'goal', 'active')",
        (workspace, made["world"], made["project"], uuid.uuid4()),
        "only a live project's owner adds to it",
    )
    _refused(
        connection,
        "update world_project_item_revision set text='rewritten' where workspace_id=%s "
        "and item_id=%s",
        (workspace, item.item_id),
        "never rewritten",
    )
    answer = CompanionMemoryRepository(connection, workspace, made["actor"]).record_answer(
        RecordedAnswer(
            question="Where do people rest?",
            answer_text="Nobody rests here yet.",
            abstained=None,
            deterministic=True,
            repaired=False,
            served_model=None,
            planned_by=None,
            prompt_version="selection-3",
            latency_ms=1,
            citations=(),
            composed=AnswerComposed.NONE,
            used_fallback=False,
            unanswered_attempts=0,
            unanswered_cost_unknown=False,
        )
    )
    proposal, _ = _goal_suggestion(made, answer.answer_id)
    _refused(
        connection,
        "insert into world_project_share (workspace_id, project_id, item_id, shared_by) "
        "values (%s, %s, %s, %s)",
        (workspace, made["project"], proposal.item_id, made["actor"]),
        "only an accepted item is shared",
    )
    made["projects"].delete_project(made["project"])
    _refused(
        connection,
        "update world_project set withdrawn_at=null, title='back' where workspace_id=%s "
        "and project_id=%s",
        (workspace, made["project"]),
        "does not come back",
    )


def _goal_suggestion(made, answer_id):
    return made["projects"].add_item(
        made["project"],
        base_revision=made["projects"].project(made["project"]).revision,
        kind=ItemKind.PREFERENCE,
        basis=ItemBasis.INFERRED_SUGGESTION,
        text="a suggestion",
        references=[{"kind": "companion_answer", "answer_id": str(answer_id)}],
    )


def test_the_migration_keeps_nothing_it_was_not_given():
    """No backfill: a remembered question is not a stated goal, so 0127 inserts no row at all."""
    text = _MIGRATION.read_text()
    assert re.search(r"\binsert\s+into\b", text, re.IGNORECASE) is None
