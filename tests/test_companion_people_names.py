"""A person's saved name is in no request the Companion sends to a hosted model.

The account holder's rule: people's names never go to a hosted model, with or without a right.
A name exists in this product only because the account holder saved it, so the test saves a real
one through the product's own naming path, asks a question that uses it, photographs it on a
shirt so it is in the evidence too, and then reads every byte the client double was handed. The
planner and the composer are both asked, in one real ``answer_question`` flow.

The positive controls are what make the absence mean something. The planner request must still
carry the person, by id and placeholder, or the redaction has simply dropped the question; and
the composer request must still carry the rest of the shirt's text, or the packet never reached
it and the absence of the name proves nothing.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.api.composer_rights import composer_rights_check
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.people import saved_person_names
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.proposal import propose_appearance
from exulanica.selection.question import answer_question, entity_catalogue, propose_plan
from exulanica.store.local import LocalContentAddressedStore

from conftest import (
    DEFAULT_PAYLOAD,
    TEST_CEILING_USD,
    TEST_MAX_CALLS,
    CountingVisionModel,
    ingest_observed,
    write_photo,
)
from model_fakes import FakeTransport, chat_body
from test_selection_proposal import current_reference, reply, scripted

NAME = "Maria Estrada"
SHIRT = "MARIA ESTRADA RUNNING CLUB"


@pytest.fixture
def named(tmp_path, photo_dir, repository):
    """One photograph of a person in a shirt carrying their name, and that person saved by name."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
    payload["scene_description"] = "A person in a running shirt beside a lake."
    # A located person, as the answer fixture in test_selection_answer draws one: a person object
    # without a box yields no occurrence to name.
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    payload["legible_text"] = [
        {"text": SHIRT, "is_signage": False, "confidence": "high", "box": None}
    ]
    vision = CountingVisionModel(payload=payload)
    pipeline = PhotoIngestPipeline(repository, store, vision=vision)
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "run.jpg"))
    assert outcome.error is None, outcome.error

    occurrence = repository.connection.execute(
        "select occurrence_id from occurrence where class = 'person' order by occurrence_id limit 1"
    ).fetchone()
    assert occurrence is not None, "the fixture photograph has no person to name"
    actor = uuid.uuid4()
    person = name_occurrence(
        IdentityRepository(repository.connection, repository.workspace_id),
        AssertionWriter(repository.connection, repository.workspace_id),
        occurrence_id=occurrence["occurrence_id"],
        display_name=NAME,
        actor=actor,
    )
    return repository, store, Session(workspace_id=repository.workspace_id, actor=actor), person


def _client(responses: list[HttpResponse]) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(responses)
    return (
        ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
        transport,
    )


def _reply(body: str) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(body)))


def test_a_saved_name_reaches_neither_the_planner_nor_the_composer(named):
    repository, store, session, person = named
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
    answer = Answer(
        clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)]
    )
    client, transport = _client([_reply(plan.model_dump_json()), _reply(answer.model_dump_json())])

    outcome = answer_question(
        repository.connection,
        client,
        f"Is {NAME} wearing the running club shirt in my photographs?",
        session,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )

    sent = [json.dumps(request["payload"]) for request in transport.requests]
    assert len(sent) == 2, f"expected the planner and the composer, got {len(sent)} requests"
    planner, composer = sent
    for body in sent:
        for word in NAME.split():
            assert word.lower() not in body.lower(), f"{word!r} was sent to a hosted model"

    # Positive controls: the person is still referable, and the packet did reach the composer.
    assert str(person.entity_id) in planner and "[person A]" in planner
    assert "Is [person A] wearing" in planner
    assert "[person A]" in composer and "RUNNING CLUB" in composer
    assert dict(outcome.people) == {"[person A]": person.entity_id}


def test_a_catalogued_person_is_an_id_and_a_class_even_when_not_asked_about(named):
    """Every question sends the catalogue, so a saved name must not ride along on any of them."""
    repository, store, session, person = named
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="lake")
    answer = Answer(
        clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)]
    )
    client, transport = _client([_reply(plan.model_dump_json()), _reply(answer.model_dump_json())])

    answer_question(
        repository.connection,
        client,
        "Which photographs show a lake?",
        session,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )

    planner = json.dumps(transport.requests[0]["payload"])
    assert f"- {person.entity_id} (person)" in planner
    for word in NAME.split():
        assert word.lower() not in planner.lower()


def test_the_planner_redacts_a_raw_question_on_its_own(named):
    """``POST /selection/plan`` hands the planner the question as typed, with no earlier pass.

    Inside ``answer_question`` the question is already redacted when the planner sees it, so that
    path cannot show the planner's own redaction works. This asks the planner directly, the way
    the plan route does.
    """
    repository, _, _, person = named
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
    client, transport = _client([_reply(plan.model_dump_json())])

    propose_plan(
        client,
        f"Show me {NAME} at the lake",
        entity_catalogue(repository.connection, repository.workspace_id),
        people=saved_person_names(repository.connection, repository.workspace_id),
    )

    (planner,) = [json.dumps(request["payload"]) for request in transport.requests]
    for word in NAME.split():
        assert word.lower() not in planner.lower(), f"{word!r} was sent to the planner"
    assert "Show me [person A] at the lake" in planner
    assert f"- {person.entity_id} (person): [person A]" in planner


def test_a_saved_name_is_not_sent_to_the_request_classifier(named):
    """The classifier reads every utterance before the answer path does, so it is redacted too."""
    repository, _, session, _ = named
    client, transport = scripted(reply({"kind": "question"}))

    propose_appearance(
        repository.connection,
        client,
        f"make the light warmer where {NAME} is standing",
        session,
        current=current_reference(),
    )

    (classifier,) = [json.dumps(request["payload"]) for request in transport.requests]
    for word in NAME.split():
        assert word.lower() not in classifier.lower(), f"{word!r} was sent to the classifier"
    assert "where [person A] is standing" in classifier
