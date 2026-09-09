"""Durable Companion memory: append-only history, correction lineage, withdrawal, isolation.

The four properties here are the ones migration 0043 exists to make unavoidable, and each is
tested against the real schema rather than against the repository's own intentions. A repository
that simply never issues an UPDATE would pass an append-only test that only called the
repository; these go around it and issue the UPDATE directly, because the guarantee is that the
database refuses, not that this module is polite.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.errors import TombstonedError
from exulanica.world.companion_memory import (
    AnswerCitation,
    AnswerOrigin,
    CompanionMemoryRepository,
    EscapeKind,
    InvalidCompanionMemory,
    MemoryStatus,
    RecordedAnswer,
    RecordedEscape,
    UnknownCompanionMemory,
)

from conftest import ingest_observed, write_photo
from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres


def _answer(**over) -> RecordedAnswer:
    fields = {
        "question": "When were these photographs taken?",
        "answer_text": "These photographs were taken on 2026-02-01.",
        "abstained": None,
        "deterministic": False,
        "repaired": False,
        "served_model": "nvidia/Nemotron-3_5-Lightning",
        "planned_by": "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "prompt_version": "selection-3",
        "latency_ms": 40208,
        "citations": (),
    }
    fields.update(over)
    return RecordedAnswer(**fields)


@pytest.fixture
def memory(repository):
    """A repository for one person, on a connection whose workspace context is set.

    ``assert_workspace_context`` fires in the insert guards, and the ingest fixture's connection
    does not carry the setting, so it is set here rather than assumed.
    """
    set_workspace(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    return CompanionMemoryRepository(repository.connection, repository.workspace_id, actor)


@pytest.fixture
def photograph(repository, photo_dir, tmp_path):
    """One ingested photograph, and the (span, capture) pair a citation names."""
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import CountingVisionModel

    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "a.jpg"))
    assert outcome.error is None, outcome.error
    row = repository.connection.execute(
        "select s.span_id, c.capture_id from evidence_span s "
        "join capture c on c.workspace_id = s.workspace_id and c.blob_sha256 = s.blob_sha256 "
        "where s.workspace_id = %s and s.modality = 'still_image' limit 1",
        (repository.workspace_id,),
    ).fetchone()
    assert row is not None, "the ingest produced no still-image span to cite"
    return row["span_id"], row["capture_id"]


# -- append-only history ------------------------------------------------------------------


def test_a_recorded_answer_cannot_be_rewritten_in_place(memory):
    """The whole point of storing a correction. 5.4: nothing is ever silently rewritten."""
    answer = memory.record_answer(_answer())
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation) as raised:
        memory.connection.execute(
            "update companion_answer set answer_text = %s where answer_id = %s",
            ("something else entirely", answer.answer_id),
        )
    assert "not editable" in str(raised.value)
    assert "answer_text" in str(raised.value)


def test_a_recorded_answer_cannot_be_deleted(memory):
    answer = memory.record_answer(_answer())
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute(
            "delete from companion_answer where answer_id = %s", (answer.answer_id,)
        )


def test_a_citation_is_append_only_so_an_update_cannot_undo_a_withdrawal(memory, photograph):
    """0024's argument, one table over: a membership an UPDATE can re-point is a deletion an
    UPDATE can undo. Re-aiming a citation at a live photograph would un-withdraw an answer a
    tombstone had already reached.
    """
    span_id, capture_id = photograph
    answer = memory.record_answer(
        _answer(citations=(AnswerCitation(span_id=span_id, capture_id=capture_id, ordinal=0),))
    )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute(
            "update companion_answer_citation set ordinal = 5 where answer_id = %s",
            (answer.answer_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute(
            "delete from companion_answer_citation where answer_id = %s", (answer.answer_id,)
        )


def test_an_escape_is_append_only(memory):
    memory.record_escape(
        RecordedEscape(
            escape=EscapeKind.SKIP, intent="confirm_continuity", entity_id=None, turn_id="turn-1"
        )
    )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute("update companion_escape set escape = 'later'")


def test_a_withdrawn_answer_does_not_come_back(memory):
    """Deletion is monotonic (del-1). An UPDATE that revived it would be a deletion undone."""
    answer = memory.record_answer(_answer())
    memory.withdraw(answer.answer_id)
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation) as raised:
        memory.connection.execute(
            "update companion_answer set status = 'active' where answer_id = %s",
            (answer.answer_id,),
        )
    assert "does not come back" in str(raised.value)


# -- correction lineage -------------------------------------------------------------------


def test_a_correction_supersedes_and_leaves_the_original_readable(memory):
    original = memory.record_answer(_answer())
    correction = memory.correct(
        original.answer_id,
        answer_text="They were taken on 2026-03-04.",
        correction_note="The first one was the wrong roll of film.",
    )

    assert correction.origin is AnswerOrigin.CORRECTION
    assert correction.supersedes == original.answer_id
    assert correction.answer_id != original.answer_id
    # The correction is the person's sentence, so no model may be named as having written it.
    assert correction.served_model is None
    # And it is not an abstention: they supplied the content the system could not.
    assert correction.abstained is None

    # The original is still there, still saying what it said, marked as superseded.
    stored = memory.answer(original.answer_id)
    assert stored.answer_text == original.answer_text
    assert stored.status is MemoryStatus.SUPERSEDED

    # But the memory a session opens with shows the correction, not what it replaced.
    recent = memory.recent()
    assert [a.answer_id for a in recent.answers] == [correction.answer_id]


def test_a_correction_inherits_the_citations_of_what_it_corrects(memory, photograph):
    """Otherwise a correction would be a stored sentence about somebody's library that no
    withdrawal could reach, which is the failure this whole plane is built against.
    """
    span_id, capture_id = photograph
    original = memory.record_answer(
        _answer(citations=(AnswerCitation(span_id=span_id, capture_id=capture_id, ordinal=0),))
    )
    correction = memory.correct(
        original.answer_id, answer_text="Actually 2026-03-04.", correction_note=None
    )
    assert [c.span_id for c in correction.citations] == [span_id]
    assert [c.capture_id for c in correction.citations] == [capture_id]


def test_correcting_an_already_corrected_answer_is_refused_rather_than_forking_the_chain(memory):
    original = memory.record_answer(_answer())
    memory.correct(original.answer_id, answer_text="First correction.", correction_note=None)
    with pytest.raises(InvalidCompanionMemory) as raised:
        memory.correct(original.answer_id, answer_text="Second.", correction_note=None)
    assert "already corrected" in str(raised.value)


def test_a_correction_can_itself_be_corrected(memory):
    original = memory.record_answer(_answer())
    first = memory.correct(original.answer_id, answer_text="Once.", correction_note=None)
    second = memory.correct(first.answer_id, answer_text="Twice.", correction_note=None)
    assert second.supersedes == first.answer_id
    assert [a.answer_id for a in memory.recent().answers] == [second.answer_id]


def test_deleting_one_memory_takes_its_whole_lineage(memory):
    """Both directions. A correction quotes what it corrects, so leaving the correction behind
    would leave the deleted thing on the screen inside its own replacement; and the superseded
    original is still about the photographs they asked about.
    """
    original = memory.record_answer(_answer())
    first = memory.correct(original.answer_id, answer_text="Once.", correction_note=None)
    second = memory.correct(first.answer_id, answer_text="Twice.", correction_note=None)

    memory.withdraw(first.answer_id)

    for answer_id in (original.answer_id, first.answer_id, second.answer_id):
        with pytest.raises(UnknownCompanionMemory):
            memory.answer(answer_id)
    assert memory.recent().answers == ()


def test_a_withdrawn_answer_cannot_be_corrected(memory):
    """A correction of a deleted answer would put its subject back on the screen."""
    answer = memory.record_answer(_answer())
    memory.withdraw(answer.answer_id)
    with pytest.raises(UnknownCompanionMemory):
        memory.correct(answer.answer_id, answer_text="Too late.", correction_note=None)


# -- tombstone reach ----------------------------------------------------------------------


def test_withdrawing_a_capture_withdraws_every_answer_that_cited_it(
    memory, repository, photograph
):
    """The acceptance criterion, and the reason the citation table exists.

    `domain-and-evidence-model.md` 6.4: without the recorded set, "the name survives its own
    deletion inside a caption". An answer is a caption with a longer sentence.
    """
    span_id, capture_id = photograph
    cited = memory.record_answer(
        _answer(citations=(AnswerCitation(span_id=span_id, capture_id=capture_id, ordinal=0),))
    )
    uncited = memory.record_answer(_answer(question="How many photographs are there?"))

    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )

    with pytest.raises(UnknownCompanionMemory):
        memory.answer(cited.answer_id)
    row = memory.connection.execute(
        "select status, withdrawn_by from companion_answer where answer_id = %s",
        (cited.answer_id,),
    ).fetchone()
    assert row["status"] == MemoryStatus.WITHDRAWN
    # Named, because a withdrawal a tombstone caused and one the person asked for are different
    # facts and only one of them has a tombstone behind it.
    assert row["withdrawn_by"] is not None

    # An answer that quoted nothing is untouched by a capture withdrawal.
    assert memory.answer(uncited.answer_id).status is MemoryStatus.ACTIVE


def test_a_workspace_tombstone_withdraws_even_the_answers_that_cited_nothing(memory, repository):
    """An abstention cites nothing by construction and is still a record of what was asked."""
    abstained = memory.record_answer(
        _answer(
            abstained="UNANSWERABLE_NOT_CAPTURED",
            answer_text="I have no evidence for that.",
            served_model=None,
        )
    )
    repository.insert_tombstone(scope="workspace", requested_by=uuid.uuid4())
    with pytest.raises(UnknownCompanionMemory):
        memory.answer(abstained.answer_id)


def test_a_withdrawal_reaches_a_correction_as_well_as_what_it_corrected(
    memory, repository, photograph
):
    """The correction inherits the citations, so the same tombstone must reach both."""
    span_id, capture_id = photograph
    original = memory.record_answer(
        _answer(citations=(AnswerCitation(span_id=span_id, capture_id=capture_id, ordinal=0),))
    )
    correction = memory.correct(
        original.answer_id, answer_text="Actually 2026-03-04.", correction_note=None
    )
    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )
    statuses = memory.connection.execute(
        "select answer_id, status from companion_answer where answer_id = any(%s)",
        ([original.answer_id, correction.answer_id],),
    ).fetchall()
    assert {row["status"] for row in statuses} == {MemoryStatus.WITHDRAWN}


def test_an_answer_may_not_be_recorded_citing_evidence_already_withdrawn(
    memory, repository, photograph
):
    """0035's forward half, refusing rather than marking stale.

    Refusing costs one unstored answer the person can ask for again. 0035 marks stale instead
    because refusing an ingest "turns exercising a right into an outage"; one composed answer is
    not an ingest and has no legitimate remainder to preserve.

    It raises `TombstonedError` rather than leaking a psycopg exception, because `create_app`
    already answers that with 410 `tombstoned`. An unhandled database error here would reach the
    person as a 500: told the server broke, when what happened is that they cited a photograph
    somebody withdrew.
    """
    span_id, capture_id = photograph
    repository.insert_tombstone(
        scope="capture", capture_id=capture_id, requested_by=uuid.uuid4()
    )
    with pytest.raises(TombstonedError) as raised:
        memory.record_answer(
            _answer(citations=(AnswerCitation(span_id=span_id, capture_id=capture_id, ordinal=0),))
        )
    assert "deleted" in str(raised.value)


def test_citing_a_photograph_from_another_library_is_unknown_rather_than_tombstoned(memory):
    """The two halves of the split the trigger draws, and they are different facts."""
    with pytest.raises(UnknownCompanionMemory):
        memory.record_answer(
            _answer(
                citations=(
                    AnswerCitation(span_id=uuid.uuid4(), capture_id=uuid.uuid4(), ordinal=0),
                )
            )
        )


def test_a_citation_may_not_name_a_photograph_its_span_does_not_belong_to(
    memory, repository, photograph
):
    """Otherwise the wrong withdrawal reaches the answer: it would quote one photograph, be
    withdrawn by the deletion of another, and survive the deletion of the one it quoted.
    """
    span_id, _capture_id = photograph
    repository.connection.execute(
        "insert into blob(blob_sha256, byte_size, media_type) "
        "values (sha256('a different photograph'::bytea), 1, 'image/jpeg') "
        "on conflict do nothing"
    )
    other_capture = repository.connection.execute(
        "insert into capture(workspace_id, blob_sha256) "
        "values (%s, sha256('a different photograph'::bytea)) returning capture_id",
        (repository.workspace_id,),
    ).fetchone()["capture_id"]
    with pytest.raises(InvalidCompanionMemory) as raised:
        memory.record_answer(
            _answer(
                citations=(
                    AnswerCitation(span_id=span_id, capture_id=other_capture, ordinal=0),
                )
            )
        )
    assert "does not belong" in str(raised.value)


# -- workspace and actor isolation --------------------------------------------------------


def test_one_workspace_never_reads_another_workspace_memory(memory, repository, spine_schema):
    """Row-level security is what makes this automatic, and this proves the policy is on.

    A second connection, a second workspace context, and the same table: the row simply is not
    there, which is why the route can answer 404 without writing a workspace check that would
    turn the surface into an existence oracle.
    """
    mine = memory.record_answer(_answer())
    psycopg_module, scratch = spine_schema
    stranger_workspace = uuid.uuid4()
    connection = open_scratch_connection(psycopg_module, scratch)
    try:
        set_workspace(connection, stranger_workspace)
        stranger = CompanionMemoryRepository(connection, stranger_workspace, memory.actor_id)
        assert stranger.recent().answers == ()
        with pytest.raises(UnknownCompanionMemory):
            stranger.answer(mine.answer_id)
    finally:
        connection.close()


def test_one_person_never_reads_another_person_memory_in_the_same_workspace(memory):
    """Row-level security scopes to the workspace and cannot see the actor, so this clause is
    the whole of the separation. That is why the actor is a constructor argument here and not a
    keyword a call site can forget.
    """
    mine = memory.record_answer(_answer())
    other_person = CompanionMemoryRepository(
        memory.connection, memory.workspace_id, uuid.uuid4()
    )
    assert other_person.recent().answers == ()
    with pytest.raises(UnknownCompanionMemory):
        other_person.answer(mine.answer_id)
    with pytest.raises(UnknownCompanionMemory):
        other_person.correct(mine.answer_id, answer_text="not yours", correction_note=None)
    with pytest.raises(UnknownCompanionMemory):
        other_person.withdraw(mine.answer_id)


# -- the ordinary reads -------------------------------------------------------------------


def test_recent_returns_the_newest_first_and_respects_its_bound(memory):
    for index in range(5):
        memory.record_answer(_answer(question=f"question {index}?"))
    recent = memory.recent(limit=3)
    assert len(recent.answers) == 3
    assert [a.question for a in recent.answers] == ["question 4?", "question 3?", "question 2?"]


def test_recent_refuses_an_unbounded_read(memory):
    with pytest.raises(InvalidCompanionMemory):
        memory.recent(limit=0)
    with pytest.raises(InvalidCompanionMemory):
        memory.recent(limit=10_000)


def test_escapes_come_back_with_what_a_cooldown_needs_to_be_rebuilt(memory):
    """Session open reads these and folds them back into the suppression windows, which is what
    makes 4.3's "never within 7 days of a Skip" enforceable past a reload for the first time.
    """
    entity = uuid.uuid4()
    memory.connection.execute(
        "insert into entity(workspace_id, entity_id, class) values (%s, %s, 'person')",
        (memory.workspace_id, entity),
    )
    memory.record_escape(
        RecordedEscape(
            escape=EscapeKind.NOT_SURE,
            intent="confirm_continuity",
            entity_id=entity,
            turn_id="turn-7",
        )
    )
    escapes = memory.recent().escapes
    assert len(escapes) == 1
    assert escapes[0].escape is EscapeKind.NOT_SURE
    assert escapes[0].entity_id == entity
    assert escapes[0].intent == "confirm_continuity"


def test_an_invented_abstention_code_is_refused(memory):
    with pytest.raises(InvalidCompanionMemory):
        memory.record_answer(_answer(abstained="UNANSWERABLE_BECAUSE_I_SAID_SO"))
