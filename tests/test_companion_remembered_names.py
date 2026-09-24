"""A remembered answer keeps which entity each of its placeholders stood for, and never a name.

The Companion's answer names a person, or a place the account holder did not allow for the model,
only by placeholder, and the answer's ``names`` maps each placeholder to its entity so the browser
can draw the name from the account holder's own library. A remembered answer keeps that map, as
entity ids, so it is drawn again with the names as they are when it is drawn: a rename, a deletion
and a withdrawn consent carry through because the name is read from the library, not from here.

These tests hold the map against the real schema: stored and served, inherited by a correction,
append-only, of the entity's own class, refused for an entity a tombstone already covers, and
holding no name text.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.session import set_workspace
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.errors import TombstonedError
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.world.companion_memory import (
    CompanionMemoryRepository,
    InvalidCompanionMemory,
    RecordedAnswer,
    UnknownCompanionMemory,
)

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo

pytestmark = pytest.mark.postgres

PERSON = "Maria Estrada"


def _answer(**over) -> RecordedAnswer:
    fields = {
        "question": "Who is in the photographs from the harbour?",
        "answer_text": "[person A] is in two photographs from the harbour.",
        "abstained": None,
        "deterministic": False,
        "repaired": False,
        "served_model": "nvidia/Nemotron-3_5-Lightning",
        "planned_by": "Qwen/Qwen3-235B-A22B-Instruct-2507",
        "prompt_version": "selection-7",
        "latency_ms": 1200,
        "citations": (),
    }
    fields.update(over)
    return RecordedAnswer(**fields)


@pytest.fixture
def person(repository, photo_dir, tmp_path):
    """A person the account holder named, on one ingested photograph; returns the entity id."""
    import copy

    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "harbour.jpg"))
    assert outcome.error is None, outcome.error
    occurrence = repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and class='person' limit 1",
        (repository.workspace_id,),
    ).fetchone()
    assert occurrence is not None, "the fixture photograph has no person occurrence"
    named = name_occurrence(
        IdentityRepository(repository.connection, repository.workspace_id),
        AssertionWriter(repository.connection, repository.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name=PERSON,
        actor=uuid.uuid4(),
    )
    return named.entity_id


@pytest.fixture
def memory(repository):
    set_workspace(repository.connection, repository.workspace_id)
    return CompanionMemoryRepository(repository.connection, repository.workspace_id, uuid.uuid4())


def test_a_remembered_answer_keeps_which_entity_each_placeholder_stood_for(memory, person):
    recorded = memory.record_answer(_answer(names={"[person A]": person}))
    assert dict(recorded.names) == {"[person A]": person}

    again = memory.recent().answers
    assert [dict(answer.names) for answer in again] == [{"[person A]": person}]
    assert dict(memory.answer(recorded.answer_id).names) == {"[person A]": person}


def test_an_answer_that_names_nothing_is_remembered_with_an_empty_map(memory):
    recorded = memory.record_answer(_answer(answer_text="Two photographs.", names={}))
    assert dict(recorded.names) == {}
    assert dict(memory.recent().answers[0].names) == {}


def test_the_map_holds_the_entity_id_and_never_the_name(memory, person):
    """The name stays in the library, where a rename, a deletion or a withdrawal reaches it."""
    recorded = memory.record_answer(_answer(names={"[person A]": person}))
    rows = memory.connection.execute(
        "select * from companion_answer_name where answer_id=%s", (recorded.answer_id,)
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["entity_id"] == person
    for value in rows[0].values():
        assert "Maria" not in str(value) and "Estrada" not in str(value)
    columns = {
        row["column_name"]
        for row in memory.connection.execute(
            "select column_name from information_schema.columns "
            "where table_name='companion_answer_name'"
        ).fetchall()
    }
    assert columns == {"workspace_id", "answer_id", "label", "entity_id"}


def test_a_correction_keeps_the_names_of_the_answer_it_replaces(memory, person):
    """It is the same question about the same people, so it is drawn with the same names."""
    recorded = memory.record_answer(_answer(names={"[person A]": person}))
    correction = memory.correct(
        recorded.answer_id,
        answer_text="[person A] is in three of them.",
        correction_note=None,
    )
    assert dict(correction.names) == {"[person A]": person}
    assert dict(memory.recent().answers[0].names) == {"[person A]": person}


def test_the_map_is_append_only(memory, person):
    recorded = memory.record_answer(_answer(names={"[person A]": person}))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute(
            "update companion_answer_name set label='[person B]' where answer_id=%s",
            (recorded.answer_id,),
        )
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        memory.connection.execute(
            "delete from companion_answer_name where answer_id=%s", (recorded.answer_id,)
        )


def test_a_label_that_is_not_a_placeholder_is_refused(memory, person):
    """A label that is not a placeholder may be a name, which this plane never holds."""
    with pytest.raises(InvalidCompanionMemory):
        memory.record_answer(_answer(names={PERSON: person}))
    assert memory.recent().answers == ()


def test_the_database_refuses_a_placeholder_of_another_class(memory, person):
    """A person drawn where the text says a place would put a name in the wrong sentence."""
    recorded = memory.record_answer(_answer(names={}))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation) as raised:
        memory.connection.execute(
            "insert into companion_answer_name (workspace_id,answer_id,label,entity_id) "
            "values (%s,%s,'[place A]',%s)",
            (memory.workspace_id, recorded.answer_id, person),
        )
    assert "not a person placeholder" in str(raised.value)


def test_the_database_refuses_a_label_that_is_not_a_placeholder(memory, person):
    recorded = memory.record_answer(_answer(names={}))
    for label in (PERSON, "[person a]", "person A"):
        with pytest.raises(psycopg.IntegrityError) as raised:
            memory.connection.execute(
                "insert into companion_answer_name (workspace_id,answer_id,label,entity_id) "
                "values (%s,%s,%s,%s)",
                (memory.workspace_id, recorded.answer_id, label, person),
            )
        assert "Maria" not in str(raised.value)


def test_an_entity_in_another_workspace_is_not_in_this_library(memory):
    with pytest.raises(UnknownCompanionMemory):
        memory.record_answer(_answer(names={"[person A]": uuid.uuid4()}))
    assert memory.recent().answers == ()


def test_a_deleted_person_is_not_recorded_as_a_placeholder_again(memory, repository, person):
    """The forward half, as for an escape: a new row naming a deleted entity is refused.

    An answer stored before the deletion keeps its map and is drawn with the words the browser
    says for a deleted entity, because the name is read from the library, where the deletion is.
    """
    kept = memory.record_answer(_answer(names={"[person A]": person}))
    repository.insert_tombstone(scope="entity", entity_id=person, requested_by=uuid.uuid4())
    with pytest.raises(TombstonedError):
        memory.record_answer(_answer(names={"[person A]": person}))
    assert [answer.answer_id for answer in memory.recent().answers] == [kept.answer_id]


# -- through the route ------------------------------------------------------------------------

from test_api import deployment as deployment  # noqa: E402

_BODY = {
    "question": "Who is in this photograph?",
    "answer_text": "[person A] is in this photograph.",
    "prompt_version": "selection-7",
    "latency_ms": 900,
}


def test_the_route_keeps_the_map_and_serves_it_on_the_next_read(deployment):
    """The browser posts the answer's ``names`` back, and a reload reads them with the answer."""
    body = dict(_BODY, names={"[person A]": str(deployment.entity_id)})
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 201, response.text
    assert response.json()["names"] == {"[person A]": str(deployment.entity_id)}

    answers = deployment.as_owner("GET", "/companion/memory/recent").json()["answers"]
    assert [answer["names"] for answer in answers] == [{"[person A]": str(deployment.entity_id)}]


def test_the_route_serves_an_empty_map_for_an_answer_recorded_without_one(deployment):
    response = deployment.as_owner("POST", "/companion/memory/answers", json=_BODY)
    assert response.status_code == 201, response.text
    assert response.json()["names"] == {}


def test_the_route_refuses_a_name_where_a_placeholder_belongs(deployment):
    body = dict(_BODY, names={"Julie": str(deployment.entity_id)})
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 422, response.text
    assert "Julie" not in response.text.replace('"Julie"', "")
    assert deployment.as_owner("GET", "/companion/memory/recent").json()["answers"] == []


def test_the_route_answers_an_entity_it_does_not_hold_as_an_unknown_reference(deployment):
    body = dict(_BODY, names={"[person A]": str(uuid.uuid4())})
    response = deployment.as_owner("POST", "/companion/memory/answers", json=body)
    assert response.status_code == 404, response.text
    assert response.json()["code"] == "unknown_reference"
