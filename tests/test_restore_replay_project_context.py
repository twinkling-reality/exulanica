"""A restore keeps every project deletion a person made, erased again, through a real restore.

Each test keeps something in a project, takes an actual ``pg_dump`` backup, deletes it the way the
product does, seals the checkpoint, restores the dump with ``psql`` and replays with the restore
command (``tests/test_restore_replay_withdrawals.py``'s round trip). The backup holds the words;
after the replay the row is withdrawn again and its words are cleared again, because the carried
update runs migration 0127's triggers as the person's deletion did.

The two-step tests delete two related things in turn, the earlier one first, and hold every
project row to the status, instant, reason and erasure it ended with at the source. They fail if
the replay reaches the later deletion's cascade before the earlier deletion it already found
ended: the shares, items and projects are replayed earliest first, ahead of Companion memory.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.session import set_workspace
from exulanica.world.companion_memory import AnswerCitation, CompanionMemoryRepository
from exulanica.world.project_context import (
    ItemBasis,
    ItemKind,
    ProjectContextRepository,
    Reuse,
)
from exulanica.world.starter import create_starter_authorities
from exulanica.world.worlds import AUTHORED_STARTER, new_world_id

from test_companion_memory import _answer
from test_purge import purged as purged
from test_restore_replay_search_entries import commands as commands
from test_restore_replay_withdrawals import _through_a_restore
from test_search_entries_on_stop import ACCOUNT

pytestmark = pytest.mark.postgres


def _projects(fixture) -> tuple[ProjectContextRepository, uuid.UUID, int]:
    connection = fixture.repository.connection
    set_workspace(connection, fixture.workspace_id)
    world_id = new_world_id(AUTHORED_STARTER)
    with connection.transaction():
        _snapshot, _style, version_id = create_starter_authorities(
            connection,
            workspace_id=fixture.workspace_id,
            actor=ACCOUNT,
            title="Restored",
            world_id=world_id,
        )
    projects = ProjectContextRepository(connection, fixture.workspace_id, ACCOUNT, world_id)
    project, _ = projects.create_project(title="kept title", version_id=version_id)
    return projects, project.project_id, project.revision


def _revision(projects, project_id) -> int:
    return projects.project(project_id).revision


def _item_current(fixture, item_id) -> bool:
    [row] = fixture.rows(
        "select status::text <> 'withdrawn' as current from world_project_item where item_id=%s",
        item_id,
    )
    return bool(row["current"])


def _erased(fixture, item_id) -> None:
    rows = fixture.rows(
        "select r.text, r.note, r.refs, r.erased_at, i.request_sha256 from "
        "world_project_item_revision r join world_project_item i using (workspace_id, item_id) "
        "where r.item_id=%s",
        item_id,
    )
    assert rows
    for row in rows:
        assert (row["text"], row["note"], row["refs"], row["request_sha256"]) == (
            None,
            None,
            None,
            None,
        )
        assert row["erased_at"] is not None


def _goal(projects, project_id, base, text, **extra):
    item, _ = projects.add_item(
        project_id,
        base_revision=base,
        kind=extra.pop("kind", ItemKind.GOAL),
        basis=extra.pop("basis", ItemBasis.USER_STATEMENT),
        text=text,
        idempotency_key=uuid.uuid4(),
        **extra,
    )
    return item


def test_an_item_deleted_after_the_backup_stays_deleted_and_erased(purged, commands, tmp_path):
    projects, project_id, base = _projects(purged)
    item = _goal(projects, project_id, base, "restored secret goal")
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: projects.delete_item(project_id, item.item_id),
        current=lambda: _item_current(purged, item.item_id),
    )
    _erased(purged, item.item_id)
    [row] = purged.rows(
        "select withdrawn_reason::text as reason, withdrawn_by from world_project_item "
        "where item_id=%s",
        item.item_id,
    )
    assert row == {"reason": "deleted", "withdrawn_by": None}


def test_a_suggestion_rejected_after_the_backup_stays_rejected(purged, commands, tmp_path):
    projects, project_id, base = _projects(purged)
    memory = CompanionMemoryRepository(purged.repository.connection, purged.workspace_id, ACCOUNT)
    answer = memory.record_answer(_answer())
    item = _goal(
        projects,
        project_id,
        base,
        "restored secret suggestion",
        basis=ItemBasis.INFERRED_SUGGESTION,
        references=[{"kind": "companion_answer", "answer_id": str(answer.answer_id)}],
    )
    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: projects.review_item(
            project_id, item.item_id, base_revision=_revision(projects, project_id), accept=False
        ),
        current=lambda: _item_current(purged, item.item_id),
    )
    _erased(purged, item.item_id)


def test_a_project_deleted_after_the_backup_stays_deleted_with_its_words(
    purged, commands, tmp_path
):
    projects, project_id, base = _projects(purged)
    item = _goal(projects, project_id, base, "restored secret in a project")

    def current() -> bool:
        [row] = purged.rows(
            "select withdrawn_at is null as current from world_project where project_id=%s",
            project_id,
        )
        return bool(row["current"])

    assert not _through_a_restore(
        purged, tmp_path, withdraw=lambda: projects.delete_project(project_id), current=current
    )
    [row] = purged.rows(
        "select title, request_sha256 from world_project where project_id=%s", project_id
    )
    assert row == {"title": None, "request_sha256": None}
    _erased(purged, item.item_id)


def test_a_share_stopped_after_the_backup_stays_stopped(purged, commands, tmp_path):
    projects, project_id, base = _projects(purged)
    item = _goal(projects, project_id, base, "a shared goal")
    _revision_after, shares = projects.share(
        project_id,
        base_revision=_revision(projects, project_id),
        project=True,
        item_ids=[item.item_id],
    )
    stopped = next(s for s in shares if s.item_id == item.item_id)

    def current() -> bool:
        [row] = purged.rows(
            "select withdrawn_at is null as current from world_project_share where share_id=%s",
            stopped.share_id,
        )
        return bool(row["current"])

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=lambda: projects.stop_share(project_id, stopped.share_id),
        current=current,
    )
    assert _item_current(purged, item.item_id), "stopping a share deletes nothing"


def test_an_item_drawn_from_an_answer_a_deletion_reached_is_withdrawn_by_it_again(
    purged, commands, tmp_path
):
    """A tombstone's withdrawal is not carried; the replayed tombstone writes it again, by name."""
    [cited] = purged.rows(
        "select s.span_id, c.capture_id from evidence_span s join capture c "
        "on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256 "
        "where s.workspace_id = %s and s.modality = 'still_image' limit 1",
        purged.workspace_id,
    )
    memory = CompanionMemoryRepository(purged.repository.connection, purged.workspace_id, ACCOUNT)
    answer = memory.record_answer(
        _answer(
            citations=(
                AnswerCitation(span_id=cited["span_id"], capture_id=cited["capture_id"], ordinal=0),
            )
        )
    )
    projects, project_id, base = _projects(purged)
    item = _goal(
        projects,
        project_id,
        base,
        "drawn from a photograph's answer",
        references=[{"kind": "companion_answer", "answer_id": str(answer.answer_id)}],
    )

    def withdraw() -> None:
        purged.tombstone_the_capture(cited["capture_id"])
        _erased(purged, item.item_id)

    assert not _through_a_restore(
        purged,
        tmp_path,
        withdraw=withdraw,
        current=lambda: _item_current(purged, item.item_id),
    )
    _erased(purged, item.item_id)
    [row] = purged.rows(
        "select i.withdrawn_reason::text as reason, t.scope::text as scope "
        "from world_project_item i join tombstone t on t.tombstone_id = i.withdrawn_by "
        "where i.item_id=%s",
        item.item_id,
    )
    assert row == {"reason": "source_withdrawn", "scope": "capture"}


# -- two deletions, the earlier one first ------------------------------------------------------


def _endings(fixture) -> dict[str, list]:
    """How every project row of the workspace ended: what a replay has to reproduce."""
    return {
        table: fixture.rows(statement, fixture.workspace_id)
        for table, statement in {
            "projects": "select project_id, withdrawn_at, withdrawn_by, title, request_sha256 "
            "from world_project where workspace_id=%s order by project_id",
            "items": "select item_id, status::text as status, withdrawn_at, withdrawn_by, "
            "withdrawn_reason::text as reason, request_sha256 from world_project_item "
            "where workspace_id=%s order by item_id",
            "revisions": "select item_id, revision, text, note, refs, erased_at "
            "from world_project_item_revision where workspace_id=%s order by item_id, revision",
            "shares": "select share_id, withdrawn_at from world_project_share "
            "where workspace_id=%s order by share_id",
        }.items()
    }


def _in_turn(fixture, tmp_path, *, first, then, current) -> dict[str, list]:
    """Both deletions after the backup, then a restore: every row ends as it did at the source."""
    ended: dict[str, dict[str, list]] = {}

    def withdraw() -> None:
        first()
        then()
        ended["source"] = _endings(fixture)

    assert not _through_a_restore(fixture, tmp_path, withdraw=withdraw, current=current)
    assert _endings(fixture) == ended["source"]
    return ended["source"]


def _reason(endings, item_id) -> str:
    return next(row["reason"] for row in endings["items"] if row["item_id"] == item_id)


def test_an_item_deleted_before_its_project_keeps_its_own_deletion(purged, commands, tmp_path):
    projects, project_id, base = _projects(purged)
    deleted = _goal(projects, project_id, base, "deleted first")
    kept = _goal(projects, project_id, _revision(projects, project_id), "deleted with the project")
    endings = _in_turn(
        purged,
        tmp_path,
        first=lambda: projects.delete_item(project_id, deleted.item_id),
        then=lambda: projects.delete_project(project_id),
        current=lambda: _item_current(purged, deleted.item_id),
    )
    assert _reason(endings, deleted.item_id) == "deleted"
    assert _reason(endings, kept.item_id) == "project_deleted"


def test_a_copy_deleted_before_its_source_keeps_its_own_deletion(purged, commands, tmp_path):
    source_projects, source_project, base = _projects(purged)
    source = _goal(source_projects, source_project, base, "copied, then deleted after its copy")
    copies, copy_project, copy_base = _projects(purged)
    copy, _ = copies.add_item(
        copy_project,
        base_revision=copy_base,
        reuse=Reuse(source_projects.world_id, source_project, source.item_id),
    )
    endings = _in_turn(
        purged,
        tmp_path,
        first=lambda: copies.delete_item(copy_project, copy.item_id),
        then=lambda: source_projects.delete_item(source_project, source.item_id),
        current=lambda: _item_current(purged, copy.item_id),
    )
    assert _reason(endings, copy.item_id) == "deleted"
    assert _reason(endings, source.item_id) == "deleted"


def test_a_share_stopped_before_its_item_was_deleted_keeps_its_instant(purged, commands, tmp_path):
    projects, project_id, base = _projects(purged)
    item = _goal(projects, project_id, base, "shared, then deleted")
    _after, shares = projects.share(
        project_id,
        base_revision=_revision(projects, project_id),
        project=False,
        item_ids=[item.item_id],
    )
    [share] = shares

    def open_share() -> bool:
        [row] = purged.rows(
            "select withdrawn_at is null as current from world_project_share where share_id=%s",
            share.share_id,
        )
        return bool(row["current"])

    endings = _in_turn(
        purged,
        tmp_path,
        first=lambda: projects.stop_share(project_id, share.share_id),
        then=lambda: projects.delete_item(project_id, item.item_id),
        current=open_share,
    )
    [stopped] = endings["shares"]
    [deleted] = endings["items"]
    assert stopped["withdrawn_at"] < deleted["withdrawn_at"]


def test_a_suggestion_rejected_before_its_answer_was_deleted_stays_rejected(
    purged, commands, tmp_path
):
    projects, project_id, base = _projects(purged)
    memory = CompanionMemoryRepository(purged.repository.connection, purged.workspace_id, ACCOUNT)
    answer = memory.record_answer(_answer())
    item = _goal(
        projects,
        project_id,
        base,
        "rejected, then its answer deleted",
        basis=ItemBasis.INFERRED_SUGGESTION,
        references=[{"kind": "companion_answer", "answer_id": str(answer.answer_id)}],
    )
    endings = _in_turn(
        purged,
        tmp_path,
        first=lambda: projects.review_item(
            project_id, item.item_id, base_revision=_revision(projects, project_id), accept=False
        ),
        then=lambda: memory.withdraw(answer.answer_id),
        current=lambda: _item_current(purged, item.item_id),
    )
    assert _reason(endings, item.item_id) == "rejected"
