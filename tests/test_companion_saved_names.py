"""No name the account holder saved is in any request the Companion sends to a hosted model.

The account holder's rules: a person's name never goes to a hosted model, with or without a right,
and a confirmed place name goes only under a place-name right for that place and that model. No
test here grants one, so no saved name of any kind may go. A name exists in this product only
because the account holder saved it, so these tests save real ones through the product's own
naming path, a person and a place, ask a question that uses both, put both in the photograph's
text as well, and read every byte the transport was handed. The clients carry the workspace's
policy as the API attaches it, so what is read is what would leave.

The positive controls are what make an absence mean something. The planner request must still
carry each entity by id and placeholder, or the redaction has simply dropped the question; and
the composer request must still carry the rest of the photograph's text, or the packet never
reached it and the absence of the names proves nothing.
"""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest
from exulanica.api.composer_rights import composer_rights_check, photograph_text_right
from exulanica.db.migrate import provision_workspace
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.caption_embeddings import CaptionEmbeddingPass
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.identity import IdentityRepository, merge_entities, name_occurrence
from exulanica.identity.subjects import IdentityError
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.proposal import propose_appearance
from exulanica.selection.question import answer_question, entity_catalogue, propose_plan
from exulanica.selection.request_names import RequestNames
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
from world_support import FIXTURE_WORLD_ID

PERSON = "Maria Estrada"
PLACE = "Lantern House"
TEXT = ["MARIA ESTRADA RUNNING CLUB", "LANTERN HOUSE"]


def _leaks(body: str) -> list[str]:
    """Every saved name, or part of a person's name, that appears in a request body."""
    lowered = " ".join(body.lower().split())
    found = [part for part in PERSON.lower().split() if part in lowered]
    if PLACE.lower() in lowered:
        found.append(PLACE)
    return found


@pytest.fixture
def named(tmp_path, photo_dir, repository):
    """One photograph: a person in a shirt carrying their name, in front of a named building."""
    store = LocalContentAddressedStore(tmp_path / "blobs")
    payload = json.loads(json.dumps(DEFAULT_PAYLOAD))
    payload["scene_description"] = "A person in a running shirt in front of a building."
    # A located person, as the answer fixture in test_selection_answer draws one: a person object
    # without a box yields no occurrence to name. DEFAULT_PAYLOAD's proposed place gives a place
    # occurrence to name.
    payload["objects"] = [
        {
            "label": "person",
            "salience": "primary",
            "confidence": "high",
            "box": {"x": 0.5, "y": 0.1, "w": 0.2, "h": 0.6},
        }
    ]
    payload["legible_text"] = [
        {"text": text, "is_signage": True, "confidence": "high", "box": None} for text in TEXT
    ]
    vision = CountingVisionModel(payload=payload)
    pipeline = PhotoIngestPipeline(repository, store, vision=vision)
    outcome = ingest_observed(pipeline, repository, write_photo(photo_dir, "run.jpg"))
    assert outcome.error is None, outcome.error

    identity = IdentityRepository(repository.connection, repository.workspace_id)
    assertions = AssertionWriter(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    entities = {}
    for occurrence_class, name in (("person", PERSON), ("place", PLACE)):
        occurrence = repository.connection.execute(
            "select occurrence_id from occurrence where class = %s order by occurrence_id limit 1",
            (occurrence_class,),
        ).fetchone()
        assert occurrence is not None, f"the fixture photograph has no {occurrence_class} to name"
        entities[occurrence_class] = name_occurrence(
            identity,
            assertions,
            occurrence_id=occurrence["occurrence_id"],
            display_name=name,
            actor=actor,
        ).entity_id
    session = Session(workspace_id=repository.workspace_id, actor=actor)
    return repository, store, session, entities


def _bare(responses: list[HttpResponse]) -> tuple[ModelClient, FakeTransport]:
    """The process's client: no policy, so it sends nothing until one is attached."""
    transport = FakeTransport(responses)
    return (
        ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        ),
        transport,
    )


def _client(repository, responses: list[HttpResponse]) -> tuple[ModelClient, FakeTransport]:
    """The client a route sends through: the workspace's policy attached, as the API builds it."""
    client, transport = _bare(responses)
    policy = WorkspaceRequestPolicy(
        repository.workspace_id,
        connection=borrowing(repository.connection),
        photograph_right=photograph_text_right,
        released_places=no_place_released,
    )
    return client.with_policy(policy), transport


def _reply(body: str) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(body)))


def _ask(repository, store, session, question: str, search: str) -> tuple[object, list[str]]:
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=search)
    answer = Answer(
        clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)]
    )
    client, transport = _client(
        repository, [_reply(plan.model_dump_json()), _reply(answer.model_dump_json())]
    )
    outcome = answer_question(
        repository.connection,
        client,
        question,
        session,
        world_id=None,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )
    return outcome, [json.dumps(request["payload"]) for request in transport.requests]


def test_no_saved_name_reaches_the_planner_or_the_composer(named):
    repository, store, session, entities = named
    outcome, sent = _ask(
        repository,
        store,
        session,
        f"Is {PERSON} wearing the running club shirt outside {PLACE}?",
        "running club",
    )

    assert len(sent) == 2, f"expected the planner and the composer, got {len(sent)} requests"
    planner, composer = sent
    for body in sent:
        assert not _leaks(body), f"sent to a hosted model: {_leaks(body)}"

    # Positive controls: each entity is still referable, and the packet did reach the composer.
    assert f"- {entities['person']} (person): [person A]" in planner
    assert f"- {entities['place']} (place): [place A]" in planner
    assert "Is [person A] wearing the running club shirt outside [place A]?" in planner
    assert "[person A]" in composer and "RUNNING CLUB" in composer
    assert dict(outcome.names)["[person A]"] == entities["person"]
    assert dict(outcome.names)["[place A]"] == entities["place"]


def test_the_catalogue_names_nothing_even_on_an_unrelated_question(named):
    """Every question sends the catalogue, so no saved name may ride along on any of them."""
    repository, store, session, entities = named
    _, sent = _ask(repository, store, session, "Which photographs show a building?", "building")

    planner = sent[0]
    # Listed by id and class, and with no placeholder, because this question named neither.
    assert f"- {entities['person']} (person)" in planner
    assert f"- {entities['place']} (place)" in planner
    assert "[person A]" not in planner and "[place A]" not in planner
    assert not _leaks(planner)


def test_the_planner_redacts_a_raw_question_on_its_own(named):
    """``POST /selection/plan`` hands the planner the question as typed, with no earlier pass.

    Inside ``answer_question`` the question is already redacted when the planner sees it, so that
    path cannot show the planner's own redaction works. This asks the planner directly, the way
    the plan route does.
    """
    repository, _, _, entities = named
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
    client, transport = _client(repository, [_reply(plan.model_dump_json())])

    propose_plan(
        client,
        f"Show me {PERSON} at {PLACE}",
        entity_catalogue(repository.connection, repository.workspace_id),
        names=RequestNames.read(repository.connection, repository.workspace_id),
    )

    (planner,) = [json.dumps(request["payload"]) for request in transport.requests]
    assert not _leaks(planner), f"sent to the planner: {_leaks(planner)}"
    assert "Show me [person A] at [place A]" in planner
    assert f"- {entities['place']} (place): [place A]" in planner


def test_no_saved_name_is_sent_to_the_request_classifier(named):
    """The classifier reads every utterance before the answer path does, so it is redacted too.

    Its call site replaces the person and leaves the place to the boundary, which withholds it:
    no right was granted.
    """
    repository, _, session, _ = named
    utterance = f"make the light warmer where {PERSON} stands outside {PLACE}"
    client, transport = _client(repository, [reply({"kind": "question"})])

    propose_appearance(
        repository.connection,
        client,
        utterance,
        session,
        current=current_reference(),
        world_id=FIXTURE_WORLD_ID,
        store=None,
    )

    (classifier,) = [json.dumps(request["payload"]) for request in transport.requests]
    assert not _leaks(classifier), f"sent to the classifier: {_leaks(classifier)}"
    assert "where [person A] stands outside [place A]" in classifier
    # The call site's half, read before any boundary: the person replaced, the place as saved.
    recorded, recording = scripted(reply({"kind": "question"}))
    propose_appearance(
        repository.connection,
        recorded,
        utterance,
        session,
        current=current_reference(),
        world_id=FIXTURE_WORLD_ID,
        store=None,
    )
    (built,) = [json.dumps(request["payload"]) for request in recording.requests]
    assert "where [person A] stands outside Lantern House" in built
    assert not [part for part in PERSON.lower().split() if part in built.lower()]


@pytest.mark.parametrize("direction", ["person_into_place", "place_into_person"])
def test_a_merge_across_classes_leaks_no_name_whether_or_not_it_is_allowed(named, direction):
    """Merging a person and a place is an identity defect of its own, fixed separately.

    Written to hold either way. If the merge is refused, the refusal is asserted; if it is
    allowed, the merged record's name is still a saved name. In both cases no name is sent.
    """
    repository, store, session, entities = named
    source, target = (
        (entities["person"], entities["place"])
        if direction == "person_into_place"
        else (entities["place"], entities["person"])
    )
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    try:
        merge_entities(identity, sources=[source], target=target, actor=session.actor)
        merged = True
    except (IdentityError, psycopg.Error):
        merged = False
    if not merged:
        row = repository.connection.execute(
            "select merged_into from entity where workspace_id=%s and entity_id=%s",
            (repository.workspace_id, source),
        ).fetchone()
        assert row["merged_into"] is None, "a refused merge left the record merged"

    _, sent = _ask(
        repository,
        store,
        session,
        f"Where was {PERSON} photographed outside {PLACE}?",
        "running club",
    )
    for body in sent:
        assert not _leaks(body), f"after a {direction} merge, sent: {_leaks(body)}"


# -- the embedding role ---------------------------------------------------------------------------


def _vector_reply() -> HttpResponse:
    """One finite, non-zero vector of the size the manifest declares for the embedding role."""
    vector = [1.0] + [0.0] * 4095
    return HttpResponse(
        status_code=200,
        text=json.dumps({"data": [{"embedding": vector}], "usage": {"prompt_tokens": 20}}),
    )


def _allow(handoff) -> None:
    """Stands for a granted right. The fixture photograph is synthetic test media."""


def _photograph(repository) -> uuid.UUID:
    (row,) = repository.connection.execute(
        "select capture_id from capture where workspace_id=%s", (repository.workspace_id,)
    ).fetchall()
    return row["capture_id"]


def _embed(repository, capture: uuid.UUID) -> tuple[object, FakeTransport]:
    """The derivative worker's pass over the process's client, which attaches the policy itself."""
    client, transport = _bare([_vector_reply()])
    embedded = CaptionEmbeddingPass(client)(
        repository.connection, repository.workspace_id, capture, before_send=_allow
    )
    return embedded, transport


def test_no_saved_name_reaches_the_caption_embedding(named):
    """The caption pass sends a photograph's stored text, and a sign can carry a saved name.

    Measured before the pass replaced them: the request held the sign's text as stored, the
    person's name and the place's name included.
    """
    repository, _, _, _ = named
    provision_workspace(repository.connection, repository.workspace_id)

    embedded, transport = _embed(repository, _photograph(repository))

    assert embedded is not None
    (request,) = transport.requests
    (sent,) = request["payload"]["input"]
    assert not _leaks(sent), f"sent to the embedding model: {_leaks(sent)}"
    # Positive controls: the photograph's text reached the request, and each name was replaced by
    # its placeholder rather than dropped along with the words around it.
    assert "RUNNING CLUB" in sent
    assert "[person A]" in sent and "[place A]" in sent


def test_no_saved_name_reaches_the_query_embedding_of_a_supplied_plan(named):
    """A plan the caller supplies is embedded as the caller wrote it, and it can name anybody."""
    repository, store, session, _ = named
    provision_workspace(repository.connection, repository.workspace_id)
    embedded, _ = _embed(repository, _photograph(repository))
    assert embedded is not None, "no caption vector exists, so no query would be embedded"

    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=f"{PERSON} running club at {PLACE}")
    answer = Answer(
        clauses=[AnswerClause(text="I have no evidence for that.", type=ClauseType.META)]
    )
    client, transport = _client(repository, [_vector_reply(), _reply(answer.model_dump_json())])
    answer_question(
        repository.connection,
        client,
        "Where does the running club meet?",
        session,
        world_id=None,
        plan=plan,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )

    queries = [r["payload"]["input"] for r in transport.requests if "input" in r["payload"]]
    assert len(queries) == 1, "the supplied plan's query was not embedded, so this shows nothing"
    (query,) = queries[0]
    assert not _leaks(query), f"sent to the embedding model: {_leaks(query)}"
    # Positive controls: the query's other words went, and each name went as its placeholder.
    assert "running club" in query
    assert "[person A]" in query and "[place A]" in query
