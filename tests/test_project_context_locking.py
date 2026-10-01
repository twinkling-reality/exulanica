"""A deletion reaching project items and a write holding its project cannot wait on each other.

A writer holds its project and then its item. A workspace tombstone updates answers (0043), whose
cascade locks the projects of the items drawn from them before those items (0127); a person
deleting a Companion answer locks its lineage and does the same. These tests stop a writer between
its two locks, start the deletion, wait until the deletion is waiting, and let the writer take its
item with NOWAIT: with the order held, the waiting deletion holds no item, so the writer gets it at
once and the deletion then completes. NOWAIT rather than a wait, because the answer deletion is
tried again when the database ends it to break a deadlock, and a retry would let a cycle pass as
the expected outcome. The last test plants the cascade as it would be without the project lock and
shows the same interleaving then finds the item held, so the first two are known to be able to
fail.
"""

from __future__ import annotations

import re
import threading
import time
import uuid

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.world.companion_memory import (
    AnswerComposed,
    CompanionMemoryRepository,
    RecordedAnswer,
)
from exulanica.world.project_context import ItemBasis, ItemKind, ProjectContextRepository
from exulanica.world.starter import create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id
from psycopg.rows import dict_row

from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres


def _connection(spine_schema, workspace_id):
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.row_factory = dict_row
    set_workspace(connection, workspace_id)
    return connection


@pytest.fixture
def drawn(repository):
    """A project with one goal drawn from a Companion answer, all committed."""
    connection = repository.connection
    workspace, actor = repository.workspace_id, uuid.uuid4()
    set_workspace(connection, workspace)
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection, workspace_id=workspace, actor=actor, title="Locks", world_id=world_id
        )
    answer = CompanionMemoryRepository(connection, workspace, actor).record_answer(
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
    projects = ProjectContextRepository(connection, workspace, actor, world_id)
    project, _ = projects.create_project(title="Locks", version_id=version_id)
    item, _ = projects.add_item(
        project.project_id,
        base_revision=project.revision,
        kind=ItemKind.GOAL,
        basis=ItemBasis.USER_STATEMENT,
        text="rest spots",
        references=[{"kind": "companion_answer", "answer_id": str(answer.answer_id)}],
    )
    return {
        "workspace": workspace,
        "actor": actor,
        "project": project.project_id,
        "item": item.item_id,
        "answer": answer.answer_id,
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


def _race(spine_schema, drawn, deletion) -> tuple[BaseException | None, BaseException | None]:
    """Hold the project, start ``deletion`` on another connection, wait for it to wait, then
    take the item. Returns what the writer and the deletion raised, if anything."""
    writer = _connection(spine_schema, drawn["workspace"])
    deleter = _connection(spine_schema, drawn["workspace"])
    observer = _connection(spine_schema, drawn["workspace"])
    outcome: dict[str, BaseException | None] = {"writer": None, "deletion": None}

    def run_deletion() -> None:
        try:
            deletion(deleter)
        except BaseException as exc:  # reported to the test thread
            outcome["deletion"] = exc

    try:
        writer.execute("begin")
        writer.execute(
            "select 1 from world_project where workspace_id=%s and project_id=%s for update",
            (drawn["workspace"], drawn["project"]),
        )
        thread = threading.Thread(target=run_deletion)
        thread.start()
        _waiting(observer, deleter.info.backend_pid)
        try:
            writer.execute(
                "select 1 from world_project_item where workspace_id=%s and item_id=%s "
                "for update nowait",
                (drawn["workspace"], drawn["item"]),
            )
            writer.execute("commit")
        except psycopg.Error as exc:
            outcome["writer"] = exc
            writer.execute("rollback")
        thread.join(timeout=30)
        assert not thread.is_alive(), "the deletion never finished"
    finally:
        for connection in (writer, deleter, observer):
            connection.close()
    return outcome["writer"], outcome["deletion"]


def _workspace_tombstone(drawn):
    def delete(connection) -> None:
        connection.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'locking test')",
            (drawn["workspace"], drawn["actor"]),
        )

    return delete


def _answer_deletion(drawn):
    def delete(connection) -> None:
        CompanionMemoryRepository(connection, drawn["workspace"], drawn["actor"]).withdraw(
            drawn["answer"]
        )

    return delete


def _status(repository, item_id) -> str:
    return repository.connection.execute(
        "select status::text as status from world_project_item where item_id=%s", (item_id,)
    ).fetchone()["status"]


def test_a_workspace_tombstone_waits_for_a_writer_holding_its_project(
    repository, spine_schema, drawn
):
    writer, deletion = _race(spine_schema, drawn, _workspace_tombstone(drawn))
    assert (writer, deletion) == (None, None)
    assert _status(repository, drawn["item"]) == "withdrawn"


def test_a_deleted_answer_waits_for_a_writer_holding_its_items_project(
    repository, spine_schema, drawn
):
    writer, deletion = _race(spine_schema, drawn, _answer_deletion(drawn))
    assert (writer, deletion) == (None, None)
    assert _status(repository, drawn["item"]) == "withdrawn"


_CASCADE = "tg_companion_answers_withdraw_project_items()"


def test_without_the_project_lock_the_deletion_holds_the_item_it_waits_behind(
    repository, spine_schema, drawn
):
    """The control: the cascade as it would be without locking projects first holds the item
    while it waits for the project, which a writer that waited would turn into a deadlock."""
    connection = repository.connection
    original = connection.execute(
        "select pg_get_functiondef(%s::regprocedure) as body", (_CASCADE,)
    ).fetchone()["body"]
    planted = re.sub(
        r"perform 1 from world_project p.*?for update of p;", "null;", original, count=1, flags=re.S
    )
    assert planted != original
    connection.execute(planted)
    try:
        writer, deletion = _race(spine_schema, drawn, _workspace_tombstone(drawn))
    finally:
        connection.execute(original)
    assert isinstance(writer, psycopg.errors.LockNotAvailable), (
        "the planted cascade left the item free, so the test proves nothing",
        writer,
    )
    assert deletion is None, deletion
