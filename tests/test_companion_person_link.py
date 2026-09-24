"""The packet states who the account holder confirmed is in a photograph, by placeholder only.

A Selection filtered by a person holds a photograph because of a confirmed link from one of the
photograph's person occurrences to that person, and only a person's decision writes a confirmed
link. The packet carries the link on the photograph's line as the person's id, and the composer
is told it as ``user_confirmed_person: [person A]``: the account holder's statement of who is in
the photograph, never something a model saw. A person's saved name never reaches a hosted model,
with or without a right, so the line names them by the request's placeholder and the browser
restores the name.

A person who is deleted, merged into another or whose consent was withdrawn is not stated, and a
person with no saved name has no placeholder and is not stated. These tests confirm a person
through the product's own naming path, run the Selection a question plans and read what the
composer is sent, with the transport as the witness.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest
from exulanica.api.composer_rights import composer_rights_check, photograph_text_right
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.identity import IdentityRepository, name_occurrence, rename_entity
from exulanica.identity.decisions import merge_entities
from exulanica.ingest import person_review
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.executor import execute
from exulanica.selection.packet import ConfirmedPerson, build_packet
from exulanica.selection.plan import EntitySelector, Intent, PlaceSelector, SelectionPlan
from exulanica.selection.question import answer_question
from exulanica.selection.validation import validate
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

pytestmark = pytest.mark.postgres

PERSON = "Maria Estrada"
#: Every form of the person's saved name the boundary recognises: whole, and each part of three
#: letters or more.
PERSON_FORMS = ("maria estrada", "maria", "estrada")
PLACE = "Lantern House"


def _occurrence(repository, capture_id, occurrence_class):
    row = repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
        "and class=%s order by occurrence_id limit 1",
        (repository.workspace_id, capture_id, occurrence_class),
    ).fetchone()
    assert row is not None, f"the fixture photograph has no {occurrence_class} occurrence"
    return row["occurrence_id"]


@pytest.fixture
def linked(tmp_path, photo_dir, repository):
    """Two photographs with a person in each; the account holder named the person on the first.

    The person's saved name is also written on the first photograph, where a vision stage would
    read it, so a line of packet text carries it too. The second photograph's person is nobody the
    account holder named, the control a person question must not select.
    """
    import copy

    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    payload["legible_text"] = [
        {"text": PLACE.upper(), "is_signage": True, "confidence": "high", "box": None},
        {"text": PERSON.upper(), "is_signage": False, "confidence": "high", "box": None},
    ]
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    captures = []
    for name, when in (("pier.jpg", "2026:08:14 11:20:00"), ("quay.jpg", "2026:08:16 15:05:00")):
        outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, name, when=when))
        assert outcome.error is None, outcome.error
        captures.append(outcome.capture_id)

    actor = uuid.uuid4()
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    entities = {
        occurrence_class: name_occurrence(
            identity,
            assertions,
            occurrence_id=_occurrence(repository, captures[0], occurrence_class),
            display_name=name,
            actor=actor,
        ).entity_id
        for occurrence_class, name in (("person", PERSON), ("place", PLACE))
    }
    session = Session(workspace_id=repository.workspace_id, actor=actor)
    return repository, store, session, captures, entities


def _person_plan(entities, *, place=False) -> SelectionPlan:
    return SelectionPlan(
        intent=Intent.CAPTURES,
        entities=EntitySelector(ids=[entities["person"]]),
        place=PlaceSelector(ids=[entities["place"]]) if place else None,
    )


def _result(repository, store, session, plan):
    validated = validate(repository.connection, plan, session)
    return execute(repository.connection, validated, world_id=None, store=store)


def _packet(repository, store, session, plan):
    result = _result(repository, store, session, plan)
    return result, build_packet(repository.connection, result, workspace_id=repository.workspace_id)


def _every_entity(repository):
    """A place-name resolver that releases every entity the workspace holds, people included."""

    def released(connection, workspace_id, handoff):
        return frozenset(
            row["entity_id"]
            for row in connection.execute(
                "select entity_id from entity where workspace_id=%s", (workspace_id,)
            ).fetchall()
        )

    return released


def _answered(repository, store, session, question, replies, *, plan=None, released=None):
    transport = FakeTransport(
        [HttpResponse(status_code=200, text=json.dumps(chat_body(body))) for body in replies]
    )
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
    )
    policy = WorkspaceRequestPolicy(
        repository.workspace_id,
        connection=borrowing(repository.connection),
        photograph_right=photograph_text_right,
        released_places=no_place_released if released is None else released,
    )
    outcome = answer_question(
        repository.connection,
        client.with_policy(policy),
        question,
        session,
        world_id=None,
        plan=plan,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )
    return outcome, [request["payload"] for request in transport.requests]


_NOTHING = Answer(clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)])
_LINE = re.compile(r"^  \[([A-Z0-9]+)\]  provenance=")
_PERSON_LINE = re.compile(r"^      user_confirmed_person: (.+)$")
_PLACE_LINE = re.compile(r"^      user_confirmed_place: (.+)$")


def _stated(composer: dict, line: re.Pattern[str]) -> dict[str, list[str]]:
    """Each photograph line of the packet the composer was sent, and what ``line`` states under it.

    Read from the user message alone, because the system message describes the line with an
    example of its own.
    """
    (packet,) = [m["content"] for m in composer["messages"] if m["role"] == "user"]
    stated: dict[str, list[str]] = {}
    token = None
    for text in packet.splitlines():
        if (head := _LINE.match(text)) is not None:
            token = head.group(1)
            stated[token] = []
        elif (found := line.match(text)) is not None:
            assert token is not None, "a stated link came before any photograph's line"
            stated[token].append(found.group(1))
    assert stated, "the composer was sent no photograph line, so nothing below means anything"
    return stated


def _no_saved_name(bodies) -> None:
    for body in bodies:
        sent = json.dumps(body, ensure_ascii=False).lower()
        for form in PERSON_FORMS:
            assert form not in sent, f"a form of a person's saved name was sent: {form!r}"


# -- the packet ------------------------------------------------------------------------------


def test_the_confirmed_person_is_on_its_photographs_line(linked):
    repository, store, session, captures, entities = linked
    result, packet = _packet(repository, store, session, _person_plan(entities))

    # Only the photograph the account holder confirmed: the second photograph's person is nobody.
    assert [capture.capture_id for capture in result.captures] == [captures[0]]
    stated = [item for item in packet.items if item.confirmed_people]
    assert len(stated) == 1
    (line,) = stated
    assert line.capture_id == captures[0]
    # By id only. The placeholder is the request's to assign, so a packet as built names nobody.
    assert line.confirmed_people == (ConfirmedPerson(entity_id=entities["person"]),)
    assert not line.confirmed_places, "a person link is not a place link"


# -- what the composer is sent ---------------------------------------------------------------


def test_the_composer_reads_the_confirmed_person_by_placeholder_only(linked):
    repository, store, session, _, entities = linked
    plan = _person_plan(entities)
    outcome, (planner, composer) = _answered(
        repository,
        store,
        session,
        f"Which of my photographs is {PERSON} in?",
        [plan.model_dump_json(), _NOTHING.model_dump_json()],
    )

    assert [people for people in _stated(composer, _PERSON_LINE).values() if people] == [
        ["[person A]"]
    ]
    assert dict(outcome.names)["[person A]"] == entities["person"]
    # Positive control: the question named the person, and the planner saw them replaced.
    assert "is [person A] in?" in json.dumps(planner)
    _no_saved_name([planner, composer])


def test_no_saved_name_of_a_person_leaves_with_every_right_granted(linked):
    """Every entity released, as though a right existed for each: the person's name still stays.

    The positive control is the place: released, its saved name is written on its line, so the
    resolver did release what it was given and the person's placeholder is not an accident.
    """
    repository, store, session, _, entities = linked
    plan = _person_plan(entities, place=True)
    outcome, bodies = _answered(
        repository,
        store,
        session,
        f"Which photographs of {PERSON} were taken at {PLACE}?",
        [plan.model_dump_json(), _NOTHING.model_dump_json()],
        released=_every_entity(repository),
    )
    composer = bodies[-1]
    assert [people for people in _stated(composer, _PERSON_LINE).values() if people] == [
        ["[person A]"]
    ]
    assert [places for places in _stated(composer, _PLACE_LINE).values() if places] == [[PLACE]]
    assert dict(outcome.names)["[person A]"] == entities["person"]
    _no_saved_name(bodies)


def test_no_saved_name_of_a_person_leaves_with_no_right_granted(linked):
    repository, store, session, _, entities = linked
    plan = _person_plan(entities, place=True)
    _, bodies = _answered(
        repository,
        store,
        session,
        f"Which photographs of {PERSON} were taken at {PLACE}?",
        [plan.model_dump_json(), _NOTHING.model_dump_json()],
    )
    composer = bodies[-1]
    assert [people for people in _stated(composer, _PERSON_LINE).values() if people] == [
        ["[person A]"]
    ]
    assert [places for places in _stated(composer, _PLACE_LINE).values() if places] == [
        ["[place A]"]
    ]
    _no_saved_name(bodies)
    assert PLACE.lower() not in json.dumps(bodies).lower()


# -- the people who are not stated ---------------------------------------------------------------


def _stated_people_in_answer(repository, store, session, plan):
    _, (composer,) = _answered(
        repository,
        store,
        session,
        "Which of these photographs are they in?",
        [_NOTHING.model_dump_json()],
        plan=plan,
    )
    return [people for people in _stated(composer, _PERSON_LINE).values() if people]


def test_a_person_whose_consent_was_withdrawn_is_not_stated(linked):
    repository, store, session, captures, entities = linked
    subject = person_review.create_subject(
        repository, actor=session.actor, entity_id=entities["person"]
    )
    # The control: a subject with no withdrawal is still stated.
    assert _stated_people_in_answer(repository, store, session, _person_plan(entities)) == [
        ["[person A]"]
    ]
    person_review.record_consent(
        repository,
        subject_id=subject,
        actor=session.actor,
        consent_scope="likeness",
        decision="withdrawn",
    )
    result, packet = _packet(repository, store, session, _person_plan(entities))
    assert [capture.capture_id for capture in result.captures] == [captures[0]], (
        "the withdrawn person's photograph was not selected, so the absence below proves nothing"
    )
    assert all(not item.confirmed_people for item in packet.items)
    assert _stated_people_in_answer(repository, store, session, _person_plan(entities)) == []


def test_a_merged_person_is_not_stated(linked):
    repository, store, session, captures, entities = linked
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    survivor = identity.entities.create(entity_class="person")
    # The survivor keeps its own name, so it must have one to merge into.
    rename_entity(
        identity,
        AssertionWriter(repository.connection, repository.workspace_id),
        entity_id=survivor,
        display_name="Mia Estrada",
        actor=session.actor,
    )
    merge_entities(identity, sources=[entities["person"]], target=survivor, actor=session.actor)
    result, packet = _packet(repository, store, session, _person_plan(entities))
    assert [capture.capture_id for capture in result.captures] == [captures[0]], (
        "the merged person's link selected nothing, so the absence below proves nothing"
    )
    assert all(not item.confirmed_people for item in packet.items)


def test_a_person_deleted_after_the_search_is_not_stated(linked):
    repository, store, session, captures, entities = linked
    result = _result(repository, store, session, _person_plan(entities))
    assert [capture.capture_id for capture in result.captures] == [captures[0]]
    repository.insert_tombstone(
        scope="entity", entity_id=entities["person"], requested_by=session.actor
    )
    packet = build_packet(repository.connection, result, workspace_id=repository.workspace_id)
    assert packet.items, "the photograph itself survives a person's deletion"
    assert all(not item.confirmed_people for item in packet.items)


def test_a_person_whose_name_was_taken_back_is_carried_and_never_stated(linked):
    repository, store, session, _, entities = linked
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    naming = assertions.active_naming_assertion(entities["person"], PERSON)
    assert naming is not None
    assertions.retract(naming, retracted_by=session.actor, reason="the name was taken back")

    _, packet = _packet(repository, store, session, _person_plan(entities))
    assert [item.confirmed_people for item in packet.items if item.confirmed_people] == [
        (ConfirmedPerson(entity_id=entities["person"]),)
    ]
    outcome, (composer,) = _answered(
        repository,
        store,
        session,
        "Which of these photographs are they in?",
        [_NOTHING.model_dump_json()],
        plan=_person_plan(entities),
    )
    assert not any(_stated(composer, _PERSON_LINE).values()), "an unnamed person was stated"
    assert entities["person"] not in dict(outcome.names).values()


def test_the_composer_is_told_what_the_line_means_and_what_it_does_not():
    from exulanica.selection.prompts import _COMPOSER_SYSTEM

    assert "`user_confirmed_person: [person A]`" in _COMPOSER_SYSTEM
    assert "not something anybody saw" in _COMPOSER_SYSTEM
    assert "never write that a person is visible or can be seen" in _COMPOSER_SYSTEM
