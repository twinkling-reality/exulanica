"""A remembered Companion answer keeps what kind of answer it was (migration 0112).

The page draws the line under an answer from its kind: a model answered, the search answered, a
model drew a change to the world, the world refused it, and so on. A row that kept only the model
identifiers was redrawn from them, so a proposal came back after a reload as an answer. What is
here: the route stores the kind with the two facts the same line states (a fallback model, and the
requests that returned no answer) and serves them back; it refuses a kind it does not know, a
missing one, and a correction posted as an answer; a correction records its own kind; the database
holds the column to exactly the repository's kinds; and none of the four new columns can be
rewritten in place.
"""

from __future__ import annotations

import re
import uuid

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.world.companion_memory import (
    AnswerComposed,
    CompanionMemoryRepository,
    InvalidCompanionMemory,
    RecordedAnswer,
)

from pg_harness import migrated_schema
from test_api import deployment as deployment

pytestmark = pytest.mark.postgres

_BODY = {
    "question": "Could the horizon be softer in here?",
    "answer_text": "The horizon will sit softer. Nothing has changed yet.",
    "prompt_version": "proposal-3",
    "latency_ms": 3500,
    "served_model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "planned_by": "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "composed": "proposed",
    "used_fallback": True,
    "unanswered_attempts": 2,
    "unanswered_cost_unknown": True,
}
_KIND_FIELDS = ("composed", "used_fallback", "unanswered_attempts", "unanswered_cost_unknown")


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
        "latency_ms": 900,
        "citations": (),
        "composed": AnswerComposed.MODEL,
        "used_fallback": False,
        "unanswered_attempts": 0,
        "unanswered_cost_unknown": False,
    }
    fields.update(over)
    return RecordedAnswer(**fields)


@pytest.fixture
def memory(repository):
    set_workspace(repository.connection, repository.workspace_id)
    return CompanionMemoryRepository(repository.connection, repository.workspace_id, uuid.uuid4())


# -- through the route ----------------------------------------------------------------------------


def test_the_route_keeps_the_kind_and_the_attempts_and_serves_them_on_the_next_read(deployment):
    response = deployment.as_owner("POST", "/companion/memory/answers", json=_BODY)
    assert response.status_code == 201, response.text
    kept = {key: response.json()[key] for key in _KIND_FIELDS}
    assert kept == {key: _BODY[key] for key in _KIND_FIELDS}

    answers = deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]
    assert [{key: answer[key] for key in _KIND_FIELDS} for answer in answers] == [kept]


@pytest.mark.parametrize("field", _KIND_FIELDS)
def test_the_route_refuses_an_answer_that_does_not_say_its_kind_and_attempts(deployment, field):
    body = {key: value for key, value in _BODY.items() if key != field}
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 422, response.text
    assert deployment.as_owner("GET", "/companion/memory/recent").json()["answers"] == []


def test_the_route_refuses_a_kind_it_does_not_know(deployment):
    body = dict(_BODY, composed="answered_somehow")
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 422, response.text
    assert deployment.as_owner("GET", "/companion/memory/recent").json()["answers"] == []


def test_the_route_refuses_a_correction_posted_as_an_answer(deployment):
    body = dict(_BODY, composed="corrected")
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_companion_memory"


def test_the_route_refuses_an_unknown_cost_with_no_unanswered_request(deployment):
    body = dict(_BODY, unanswered_attempts=0, unanswered_cost_unknown=True)
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 422, response.text


def test_a_correction_is_kept_as_the_kind_that_says_the_person_wrote_it(deployment):
    recorded = deployment.as_owner("POST", "/companion/memory/answers", json=_BODY).json()
    response = deployment.as_owner(
        "POST",
        f"/companion/memory/answers/{recorded['answer_id']}/corrections",
        json={"answer_text": "The horizon was fine as it was."},
    )
    assert response.status_code == 201, response.text
    corrected = response.json()
    # No model wrote it and nothing went unanswered: none of the answer's own attempts carry over.
    assert {key: corrected[key] for key in _KIND_FIELDS} == {
        "composed": "corrected",
        "used_fallback": False,
        "unanswered_attempts": 0,
        "unanswered_cost_unknown": False,
    }


# -- in the database ------------------------------------------------------------------------------


def test_the_column_holds_exactly_the_kinds_the_repository_states(memory):
    definition = memory.connection.execute(
        "select pg_get_constraintdef(oid) as definition from pg_constraint "
        "where conrelid='companion_answer'::regclass and conname='companion_answer_composed_known'"
    ).fetchone()
    assert definition is not None, "migration 0112's check on companion_answer.composed"
    stated = set(re.findall(r"'([a-z]+)'::text", definition["definition"]))
    # A positive control: kinds the page is known to draw are found by the same reading.
    assert {"proposed", "unshown", "outcome", "corrected"} <= stated
    assert stated == {kind.value for kind in AnswerComposed}


def test_a_row_kept_before_the_kind_was_kept_is_read_with_no_kind(memory):
    """What 0112 leaves on the rows it found: no kind, no fallback, nothing unanswered."""
    row = memory.connection.execute(
        "insert into companion_answer (workspace_id,actor_id,question,answer_text,prompt_version,"
        "latency_ms) values (%s,%s,'When?','Then.','selection-3',10) returning answer_id",
        (memory.workspace_id, memory.actor_id),
    ).fetchone()
    assert row is not None
    kept = memory.answer(row["answer_id"])
    assert (
        kept.composed,
        kept.used_fallback,
        kept.unanswered_attempts,
        kept.unanswered_cost_unknown,
    ) == (None, False, 0, False)


def test_the_repository_records_the_kind_and_attempts_it_was_given(memory):
    kept = memory.record_answer(
        _answer(
            composed=AnswerComposed.DISCARDED,
            used_fallback=True,
            unanswered_attempts=1,
            unanswered_cost_unknown=False,
        )
    )
    again = memory.answer(kept.answer_id)
    assert (again.composed, again.used_fallback, again.unanswered_attempts) == (
        AnswerComposed.DISCARDED,
        True,
        1,
    )
    assert again == kept


def test_the_repository_refuses_a_correction_recorded_as_an_answer(memory):
    with pytest.raises(InvalidCompanionMemory):
        memory.record_answer(_answer(composed=AnswerComposed.CORRECTED))
    assert memory.recent().answers == ()


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("composed", "search"),
        ("used_fallback", True),
        ("unanswered_attempts", 3),
        ("unanswered_cost_unknown", True),
    ],
)
def test_none_of_the_new_columns_is_rewritten_in_place(memory, column, value):
    answer = memory.record_answer(_answer(unanswered_attempts=1, unanswered_cost_unknown=False))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation) as raised:
        memory.connection.execute(
            f"update companion_answer set {column} = %s where answer_id = %s",
            (value, answer.answer_id),
        )
    assert "not editable" in str(raised.value)
    assert column in str(raised.value)


def test_the_database_refuses_an_asked_answer_of_the_corrected_kind(memory):
    """The repository refuses it first; the column refuses it for any other writer."""
    with pytest.raises(psycopg.errors.CheckViolation) as raised:
        memory.connection.execute(
            "insert into companion_answer (workspace_id,actor_id,question,answer_text,"
            "prompt_version,latency_ms,composed) "
            "values (%s,%s,'When?','Then.','selection-3',10,'corrected')",
            (memory.workspace_id, memory.actor_id),
        )
    assert raised.value.diag.constraint_name == "only_a_correction_is_corrected"


def test_the_database_refuses_an_unknown_cost_with_nothing_unanswered(memory):
    with pytest.raises(psycopg.errors.CheckViolation) as raised:
        memory.connection.execute(
            "insert into companion_answer (workspace_id,actor_id,question,answer_text,"
            "prompt_version,latency_ms,composed,unanswered_cost_unknown) "
            "values (%s,%s,'When?','Then.','selection-3',10,'model',true)",
            (memory.workspace_id, memory.actor_id),
        )
    assert raised.value.diag.constraint_name == "an_unknown_cost_needs_an_unanswered_attempt"


def test_a_column_a_later_migration_adds_cannot_be_rewritten_in_place():
    """0112's guard names the columns that may change, so a column added after it is frozen too.

    In a throwaway schema with every migration applied, as a later migration would add one.
    """
    with migrated_schema() as (_psycopg, connection):
        connection.execute("alter table companion_answer add column added_later text")
        workspace = uuid.uuid4()
        set_workspace(connection, workspace)
        row = connection.execute(
            "insert into companion_answer (workspace_id,actor_id,question,answer_text,"
            "prompt_version,latency_ms,composed,added_later) "
            "values (%s,%s,'When?','Then.','selection-3',10,'none','as kept') returning answer_id",
            (workspace, uuid.uuid4()),
        ).fetchone()
        assert row is not None
        answer_id = row[0]
        with (
            pytest.raises(psycopg.errors.IntegrityConstraintViolation) as raised,
            connection.transaction(),
        ):
            connection.execute(
                "update companion_answer set added_later='rewritten' where answer_id=%s",
                (answer_id,),
            )
        assert "added_later may not be rewritten in place" in str(raised.value)
        # A positive control: what has happened to the answer since still moves on the same row.
        connection.execute(
            "update companion_answer set status='withdrawn', withdrawn_at=now() where answer_id=%s",
            (answer_id,),
        )
        status = connection.execute(
            "select status::text from companion_answer where answer_id=%s", (answer_id,)
        ).fetchone()
        assert status == ("withdrawn",)
