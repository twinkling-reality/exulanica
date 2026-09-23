"""The packet states where the account holder confirmed a photograph was taken.

A Selection filtered by a place holds a photograph because of a confirmed link from the
photograph's place to that place, and only a person's decision writes a confirmed link
(``confirmed_needs_a_human`` in ``exulanica/migrations/0001_spine.sql``). Without the link on its
line, such a photograph reaches the composer as a bare line with no description, which its prompt
says tells it nothing about the picture. The packet carries the link on the photograph's line, as
the place's id; the placeholder the composer reads is assigned with the request's other
placeholders, so a packet as built holds no saved name.

These tests confirm a place through the product's own naming path, run the Selection a person's
question plans, and read the packet ``build_packet`` makes of it.
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
from exulanica.identity import IdentityRepository, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.executor import execute
from exulanica.selection.packet import MAX_PACKET_ITEMS, ConfirmedPlace, build_packet
from exulanica.selection.plan import (
    EntitySelector,
    Intent,
    PlaceSelector,
    SelectionPlan,
)
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

PLACE = "Lantern House"
PERSON = "Maria Estrada"


def _occurrence(repository, capture_id: uuid.UUID, occurrence_class: str) -> uuid.UUID:
    row = repository.connection.execute(
        "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
        "and class=%s order by occurrence_id limit 1",
        (repository.workspace_id, capture_id, occurrence_class),
    ).fetchone()
    assert row is not None, f"the fixture photograph has no {occurrence_class} occurrence"
    return row["occurrence_id"]


@pytest.fixture
def confirmed(tmp_path, photo_dir, repository):
    """Two photographs of one sign; the account holder confirmed the place and a person on one.

    Both photographs carry the same proposed place, so the second is the control: a place a model
    proposed and nobody confirmed selects nothing and is stated nowhere.
    """
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    payload["legible_text"] = [
        {"text": PLACE.upper(), "is_signage": True, "confidence": "high", "box": None}
    ]
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    captures = []
    for name, when in (("hall.jpg", "2026:08:14 11:20:00"), ("street.jpg", "2026:08:16 15:05:00")):
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
        for occurrence_class, name in (("place", PLACE), ("person", PERSON))
    }
    session = Session(workspace_id=repository.workspace_id, actor=actor)
    return repository, store, session, captures, entities


def _packet(repository, store, session, plan: SelectionPlan):
    validated = validate(repository.connection, plan, session)
    result = execute(repository.connection, validated, store=store)
    return result, build_packet(repository.connection, result, workspace_id=repository.workspace_id)


def test_the_confirmed_place_is_on_its_photographs_line(confirmed):
    repository, store, session, captures, entities = confirmed
    plan = SelectionPlan(intent=Intent.CAPTURES, place=PlaceSelector(ids=[entities["place"]]))
    result, packet = _packet(repository, store, session, plan)

    # Only the photograph the account holder confirmed: the control's proposed place selects none.
    assert [capture.capture_id for capture in result.captures] == [captures[0]]
    stated = [item for item in packet.items if item.confirmed_places]
    assert len(stated) == 1
    (line,) = stated
    assert line.capture_id == captures[0]
    assert line.assertion_id is None, "the link belongs on the photograph's own line"
    # By id only. The placeholder is the request's to assign, so a packet as built names nothing.
    assert line.confirmed_places == (ConfirmedPlace(entity_id=entities["place"]),)


def test_stating_the_link_adds_no_line(confirmed):
    """The packet's size rule: one line per supporting span and claim, a link included in one."""
    repository, store, session, _, entities = confirmed
    plan = SelectionPlan(
        intent=Intent.CAPTURES,
        place=PlaceSelector(ids=[entities["place"]]),
        semantic_query="lantern house",
    )
    result, packet = _packet(repository, store, session, plan)

    supported = {
        (support.span_id, support.assertion_id)
        for capture in result.captures
        for support in capture.support
    }
    assert {(item.span_id, item.assertion_id) for item in packet.items} == supported
    assert len(packet.items) <= MAX_PACKET_ITEMS
    # A search for the sign's words selected claim lines as well, and none of them carries a link.
    assert any(item.text is not None for item in packet.items)
    assert all(not item.confirmed_places for item in packet.items if item.assertion_id is not None)


def test_a_confirmed_person_is_not_stated(confirmed):
    """Telling a model who is in a photograph is a decision about people; the packet makes none."""
    repository, store, session, captures, entities = confirmed
    plan = SelectionPlan(intent=Intent.CAPTURES, entities=EntitySelector(ids=[entities["person"]]))
    result, packet = _packet(repository, store, session, plan)

    assert [capture.capture_id for capture in result.captures] == [captures[0]], (
        "the person question selected nothing, so the absence below would prove nothing"
    )
    assert packet.items, "the person question built an empty packet"
    assert all(not item.confirmed_places for item in packet.items)


# -- what the composer is sent ---------------------------------------------------------------


def _client(repository, replies: list[str]) -> tuple[ModelClient, FakeTransport]:
    """The client a route sends through: the workspace's policy attached, as the API builds it."""
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
        released_places=no_place_released,
    )
    return client.with_policy(policy), transport


_NOTHING = Answer(clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)])


def _answered(repository, store, session, question, replies, plan=None):
    client, transport = _client(repository, replies)
    outcome = answer_question(
        repository.connection,
        client,
        question,
        session,
        plan=plan,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )
    return outcome, [request["payload"] for request in transport.requests]


_LINE = re.compile(r"^  \[([A-Z0-9]+)\]  provenance=")
_STATED = re.compile(r"^      user_confirmed_place: (.+)$")


def _stated(composer: dict) -> dict[str, list[str]]:
    """Each photograph line of the packet the composer was sent, and the places stated under it.

    Read from the user message alone. The system message describes the line with an example of
    its own, so a search of the whole request would find that example whether or not the packet
    carried a single line.
    """
    (packet,) = [m["content"] for m in composer["messages"] if m["role"] == "user"]
    stated: dict[str, list[str]] = {}
    token = None
    for line in packet.splitlines():
        if (head := _LINE.match(line)) is not None:
            token = head.group(1)
            stated[token] = []
        elif (place := _STATED.match(line)) is not None:
            assert token is not None, "a stated place came before any photograph's line"
            stated[token].append(place.group(1))
    assert stated, "the composer was sent no photograph line, so nothing below means anything"
    return stated


def test_the_composer_reads_the_confirmed_place_by_its_placeholder_only(confirmed):
    repository, store, session, _, entities = confirmed
    plan = SelectionPlan(intent=Intent.CAPTURES, place=PlaceSelector(ids=[entities["place"]]))
    outcome, (planner, composer) = _answered(
        repository,
        store,
        session,
        f"Which of my photographs were taken at {PLACE}?",
        [plan.model_dump_json(), _NOTHING.model_dump_json()],
    )

    # One photograph was confirmed there, and its line states the place by the placeholder the
    # question's own redaction gave it.
    assert [places for places in _stated(composer).values() if places] == [["[place A]"]]
    assert dict(outcome.names)["[place A]"] == entities["place"]
    # Positive control: the question named the place, and the planner saw it replaced.
    assert "taken at [place A]?" in json.dumps(planner)
    for body in (planner, composer):
        assert PLACE.lower() not in json.dumps(body).lower(), "a saved place name was sent"


def test_a_place_the_question_did_not_name_is_given_its_own_placeholder(confirmed):
    """A supplied plan can select a place the words never name; its line still names it safely."""
    repository, store, session, _, entities = confirmed
    plan = SelectionPlan(intent=Intent.CAPTURES, place=PlaceSelector(ids=[entities["place"]]))
    outcome, (composer,) = _answered(
        repository,
        store,
        session,
        "Which of these photographs were taken there?",
        [_NOTHING.model_dump_json()],
        plan=plan,
    )

    assert [places for places in _stated(composer).values() if places] == [["[place A]"]]
    assert dict(outcome.names) == {"[place A]": entities["place"]}
    assert PLACE.lower() not in json.dumps(composer).lower()


def test_the_placeholder_is_given_by_the_places_id_not_by_its_words(confirmed):
    """Names are not unique, so a placeholder found by matching words can belong to another entity.

    Here the fixture's place, a person, and a second place are all saved as the same words, in that
    order. Matching the second place's name against every saved name finds the first place's
    pattern first, and the second place would be stated under nobody's placeholder, or someone
    else's.
    """
    repository, store, session, captures, _ = confirmed
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    named = {}
    for occurrence_class in ("person", "place"):
        named[occurrence_class] = name_occurrence(
            identity,
            assertions,
            occurrence_id=_occurrence(repository, captures[1], occurrence_class),
            display_name=PLACE,
            actor=session.actor,
        ).entity_id
    plan = SelectionPlan(intent=Intent.CAPTURES, place=PlaceSelector(ids=[named["place"]]))
    outcome, (composer,) = _answered(
        repository,
        store,
        session,
        "Which of these photographs were taken there?",
        [_NOTHING.model_dump_json()],
        plan=plan,
    )

    (stated,) = [places for places in _stated(composer).values() if places]
    (label,) = stated
    assert dict(outcome.names)[label] == named["place"]
    assert label.startswith("[place ")
