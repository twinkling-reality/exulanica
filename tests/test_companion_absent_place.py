"""A question about a place nobody saved is not answered from another place's photographs.

The planner is sent every named entity as an id and a class, and a name only for an entity the
question names (``_catalogue_line`` in ``exulanica/selection/planner.py``), so an id it chooses for
anything else is one it could only have guessed. A rehearsal of the running product saw it guess:
asked "What does the sign say at Harbour Station?" with one place saved, Mireland Hall, the planner
put Mireland Hall's id in the place dimension, and the composer answered about Harbour Station over
Mireland Hall's photographs. Once it wrote a historical clause citing one of them, once a false
statement about the search that carried a citation, and once an uncited statement about the search.

These tests save a place and a person through the product's own identity decisions, on photographs
whose sign names the place, and ask questions through a client that carries the workspace's policy
as a route builds it, with the planner's and the composer's replies scripted at the transport.
Packet tokens are drawn from a counter so that a scripted reply can cite one.
"""

from __future__ import annotations

import copy
import datetime as dt
import itertools
import json
import uuid

import pytest
from exulanica.api.composer_rights import composer_rights_check
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.identity import IdentityRepository, confirm_link, name_occurrence
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection import answer as answer_module
from exulanica.selection import packet as packet_module
from exulanica.selection.answer import (
    Abstention,
    Answer,
    AnswerClause,
    AnswerRejected,
    ClauseType,
    render_deterministic_answer,
    validate_answer,
)
from exulanica.selection.executor import execute
from exulanica.selection.packet import build_packet
from exulanica.selection.plan import EntitySelector, Intent, PlaceSelector, SelectionPlan
from exulanica.selection.question import AnsweredQuestion, answer_question
from exulanica.selection.validation import validate
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo
from model_fakes import chat_body
from test_companion_saved_names import _client

PLACE = "Mireland Hall"
PERSON = "Maria Estrada"
#: A place no photograph shows and nobody saved.
ABSENT = "Harbour Station"
#: What the vision stage writes for each photograph. It says "sign", so the query the live planner
#: wrote for these questions, "sign", selects both photographs.
CAPTION = "A painted sign reading MIRELAND HALL above the door of a brick building."
NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.UTC)
SIGN_AT_ABSENT = f"What does the sign say at {ABSENT}?"
SIGN_AT_PLACE = f"What does the sign say at {PLACE}?"
#: The first token a packet draws from the counter this module installs.
FIRST_TOKEN = "TOKEN00001"


@pytest.fixture
def saved(tmp_path, photo_dir, repository, monkeypatch):
    """Two photographs of Mireland Hall's sign, the place saved from one and confirmed on the other.

    A person in the first photograph is saved too, so a plan has somebody the question does not
    name to stand in for "me".
    """
    counter = itertools.count(1)
    monkeypatch.setattr(packet_module, "_token", lambda taken: f"TOKEN{next(counter):05d}")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = copy.deepcopy(DEFAULT_PAYLOAD)
    payload["scene_description"] = CAPTION
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
    payload["proposed_place"] = {
        "label": PLACE,
        "basis": "signage",
        "supporting_evidence": f"A sign reading {PLACE.upper()}.",
        "confidence": "high",
    }
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel(payload=payload))
    captures = []
    for name, when in (
        ("nameplate.jpg", "2026:08:14 11:20:00"),
        ("nameplate-tree.jpg", "2026:08:16 15:05:00"),
    ):
        outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, name, when=when))
        assert outcome.error is None, outcome.error
        captures.append(outcome.capture_id)

    def occurrence(capture_id: uuid.UUID, occurrence_class: str) -> uuid.UUID:
        row = repository.connection.execute(
            "select occurrence_id from occurrence where workspace_id=%s and capture_id=%s "
            "and class=%s order by occurrence_id limit 1",
            (repository.workspace_id, capture_id, occurrence_class),
        ).fetchone()
        assert row is not None, f"the fixture photograph has no {occurrence_class} occurrence"
        return row["occurrence_id"]

    actor = uuid.uuid4()
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    entities = {
        occurrence_class: name_occurrence(
            identity,
            assertions,
            occurrence_id=occurrence(captures[0], occurrence_class),
            display_name=name,
            actor=actor,
        ).entity_id
        for occurrence_class, name in (("place", PLACE), ("person", PERSON))
    }
    confirm_link(
        identity,
        occurrence_id=occurrence(captures[1], "place"),
        entity_id=entities["place"],
        actor=actor,
    )
    session = Session(workspace_id=repository.workspace_id, actor=actor)
    return repository, store, session, entities


def _reply(value: SelectionPlan | Answer) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(value.model_dump_json())))


def _answer(*clauses: AnswerClause) -> Answer:
    return Answer(clauses=list(clauses))


def _ask(saved, question: str, *replies: SelectionPlan | Answer, plan=None):
    repository, store, session, _ = saved
    client, transport = _client(repository, [_reply(value) for value in replies])
    outcome = answer_question(
        repository.connection,
        client,
        question,
        session,
        plan=plan,
        now=NOW,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )
    return outcome, transport


def _user_message(request: dict) -> str:
    """The first user message: the planner's catalogue and question, or the composer's packet."""
    return next(m["content"] for m in request["payload"]["messages"] if m["role"] == "user")


def _catalogue_lines(planner_request: dict) -> list[str]:
    """The catalogue the planner was sent, one entry per line, read from its user message."""
    message = _user_message(planner_request)
    catalogue = message.split("Catalogue:\n", 1)[1].split("\n\nQuestion:", 1)[0]
    return catalogue.splitlines()


def _cited(outcome: AnsweredQuestion) -> list[list[str]]:
    return [clause.citations for clause in outcome.answer.clauses if clause.citations]


def _stood_in(entities: dict[str, uuid.UUID]) -> SelectionPlan:
    """The plan the live planner returned for the absent place: the saved place, and "sign"."""
    return SelectionPlan(
        intent=Intent.CAPTURES,
        place=PlaceSelector(ids=[entities["place"]]),
        semantic_query="sign",
    )


#: What the composer wrote over Mireland Hall's photographs when asked about Harbour Station, in
#: three runs of the rehearsal, each as a scripted reply citing the packet's first token.
OBSERVED = {
    "a historical clause citing another place's photograph": _answer(
        AnswerClause(
            text=f"You have not seen a sign that says anything about {ABSENT} in your photographs.",
            type=ClauseType.HISTORICAL,
            citations=[FIRST_TOKEN],
        )
    ),
    "a false statement about the search carrying a citation": _answer(
        AnswerClause(
            text="Your collection does not contain a sign that mentions a location.",
            type=ClauseType.META,
            citations=[FIRST_TOKEN],
        )
    ),
    "an uncited statement about the search": _answer(
        AnswerClause(
            text=f"The information does not mention a sign at {ABSENT}.", type=ClauseType.META
        )
    ),
}


# -- a Selection the planner guessed -------------------------------------------------------------


@pytest.mark.parametrize("shape", sorted(OBSERVED))
def test_a_place_the_question_does_not_name_is_not_searched(saved, shape):
    """Each observed answer came from asking about one place over another place's photographs.

    The planner's plan is refused before anything is searched, so none of them can be written.
    """
    _, _, _, entities = saved
    outcome, transport = _ask(saved, SIGN_AT_ABSENT, _stood_in(entities), OBSERVED[shape])

    # The premise: the planner was sent the saved place as an id and a class and nothing more,
    # so the id it chose is one it could only have guessed.
    planner = transport.requests[0]
    assert f"- {entities['place']} (place)" in _catalogue_lines(planner)
    assert PLACE.lower() not in _user_message(planner).lower()

    assert not _cited(outcome), (
        f"the answer cites a photograph of another place: {outcome.answer.model_dump_json()}"
    )
    assert len(transport.requests) == 1, (
        f"the composer was asked about {ABSENT} over {PLACE}'s photographs and answered "
        f"{outcome.answer.model_dump_json()}"
    )
    assert outcome.abstention is Abstention.NOT_UNDERSTOOD
    assert outcome.answer == answer_module.abstain_from_a_guess()[0]
    # Kept, as the plan the lookup refuses is kept: it is how somebody sees what was guessed.
    assert outcome.plan == _stood_in(entities)
    assert outcome.result is None and outcome.packet is None, "something was searched"
    assert not outcome.deterministic and not outcome.repaired
    assert [rejection.split(":", 1)[0] for rejection in outcome.rejections] == ["unnamed_reference"]
    assert outcome.names == ()
    assert [call.role for call in outcome.calls] == ["structured_extraction"]


def test_somebody_the_question_does_not_name_is_not_searched_beside_a_place_it_does(saved):
    """A guess in the entity dimension is refused as one in the place dimension is.

    "Who was with me at" a place once filtered by a person nobody named, in five draws of five
    (``selection-6`` in ``exulanica/selection/prompts.py``). The place here is named, the person
    is not.
    """
    _, _, _, entities = saved
    plan = SelectionPlan(
        intent=Intent.ENTITIES,
        place=PlaceSelector(ids=[entities["place"]]),
        entities=EntitySelector(ids=[entities["person"]]),
    )
    uncited = OBSERVED["an uncited statement about the search"]
    outcome, transport = _ask(saved, f"Who was with me at {PLACE}?", plan, uncited)

    assert len(transport.requests) == 1, "the composer was asked from a guessed Selection"
    assert outcome.abstention is Abstention.NOT_UNDERSTOOD
    assert outcome.result is None


def test_what_the_question_names_is_searched_in_either_dimension(saved):
    """The control: a person and a place the question names by their saved names are searched."""
    _, _, _, entities = saved
    plan = SelectionPlan(
        intent=Intent.CAPTURES,
        place=PlaceSelector(ids=[entities["place"]]),
        entities=EntitySelector(ids=[entities["person"]]),
    )
    answered = _answer(
        AnswerClause(
            text="This photograph was taken at [place A].",
            type=ClauseType.HISTORICAL,
            citations=[FIRST_TOKEN],
        )
    )
    outcome, transport = _ask(saved, f"Was {PERSON} at {PLACE}?", plan, answered)

    assert outcome.abstention is None, outcome.answer.model_dump_json()
    assert len(transport.requests) == 2
    assert outcome.result is not None and outcome.result.captures
    assert _cited(outcome) == [[FIRST_TOKEN]]


def test_a_place_the_question_names_is_answered_as_it_always_was(saved):
    """The present place: its plan is searched, composed and cited, with nothing refused."""
    _, _, _, entities = saved
    answered = _answer(
        AnswerClause(
            text="The sign reads [place A].", type=ClauseType.HISTORICAL, citations=[FIRST_TOKEN]
        )
    )
    outcome, transport = _ask(saved, SIGN_AT_PLACE, _stood_in(entities), answered)

    # Positive control for the premise above: the question named the place, so its catalogue
    # line carries the placeholder the question was given.
    assert f"- {entities['place']} (place): [place A]" in _catalogue_lines(transport.requests[0])
    assert outcome.abstention is None
    assert not outcome.deterministic and not outcome.repaired and not outcome.rejections
    assert len(transport.requests) == 2
    assert outcome.answer == answered
    assert dict(outcome.names)["[place A]"] == entities["place"]


def test_the_guess_is_refused_before_any_photograph_is_read(saved, monkeypatch):
    """Nothing is executed, so no photograph's text reaches any request the question makes."""
    from exulanica.selection import question as question_module

    def never(*args, **kwargs):
        raise AssertionError("a guessed Selection was executed")

    monkeypatch.setattr(question_module, "execute", never)
    _, _, _, entities = saved
    uncited = OBSERVED["an uncited statement about the search"]
    outcome, _ = _ask(saved, SIGN_AT_ABSENT, _stood_in(entities), uncited)
    assert outcome.abstention is Abstention.NOT_UNDERSTOOD


def test_the_answer_to_a_guess_says_nothing_was_searched():
    """Every clause is about the search, cites nothing and holds no number."""
    answer, reason = answer_module.abstain_from_a_guess()
    assert reason is Abstention.NOT_UNDERSTOOD
    assert all(clause.type is ClauseType.META for clause in answer.clauses)
    assert all(not clause.citations and not clause.value_refs for clause in answer.clauses)
    assert not any(character.isdigit() for clause in answer.clauses for character in clause.text)


# -- a statement about the search cites nothing -------------------------------------------------


def _packet(saved):
    repository, store, session, entities = saved
    validated = validate(repository.connection, _stood_in(entities), session)
    result = execute(repository.connection, validated, store=store)
    return build_packet(repository.connection, result, workspace_id=repository.workspace_id)


def test_a_statement_about_the_search_that_cites_a_photograph_is_refused(saved):
    packet = _packet(saved)
    assert packet.resolve(FIRST_TOKEN) is not None, "the citation resolves; only its type is wrong"
    cited_meta = OBSERVED["a false statement about the search carrying a citation"]
    with pytest.raises(AnswerRejected) as refused:
        validate_answer(cited_meta, packet)
    (reason,) = refused.value.reasons
    assert reason.startswith("clause 0 is 'meta'"), reason
    assert FIRST_TOKEN in reason


def test_the_answer_that_exists_regardless_cites_nothing_about_the_search(saved):
    """The deterministic answer still passes the validator by construction."""
    packet = _packet(saved)
    answer = render_deterministic_answer(packet)
    assert validate_answer(answer, packet) == answer
    assert [clause.citations for clause in answer.clauses if clause.type is ClauseType.META] == [[]]


def test_a_cited_statement_about_the_search_is_repaired_once(saved):
    _, _, _, entities = saved
    repaired = _answer(
        AnswerClause(
            text="The sign reads [place A].", type=ClauseType.HISTORICAL, citations=[FIRST_TOKEN]
        )
    )
    outcome, transport = _ask(
        saved,
        SIGN_AT_PLACE,
        _stood_in(entities),
        OBSERVED["a false statement about the search carrying a citation"],
        repaired,
    )

    assert outcome.repaired, (
        f"the cited statement about the search was accepted: {outcome.answer.model_dump_json()}"
    )
    assert outcome.answer == repaired
    assert [rejection[: len("clause 0 is 'meta'")] for rejection in outcome.rejections] == [
        "clause 0 is 'meta'"
    ]
    # The repair is told which rule refused the first answer.
    last = transport.requests[-1]["payload"]["messages"][-1]
    assert last["role"] == "user" and "clause 0 is 'meta'" in last["content"]


def test_a_statement_about_the_search_cited_twice_leaves_the_answer_to_the_renderer(saved):
    _, _, _, entities = saved
    cited_meta = OBSERVED["a false statement about the search carrying a citation"]
    outcome, transport = _ask(saved, SIGN_AT_PLACE, _stood_in(entities), cited_meta, cited_meta)

    assert outcome.deterministic
    assert len(transport.requests) == 3
    assert all(
        not clause.citations for clause in outcome.answer.clauses if clause.type is ClauseType.META
    )
    assert "Your collection does not contain" not in outcome.answer.model_dump_json()
