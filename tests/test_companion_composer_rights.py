"""Photograph-derived text reaches the Companion's composer only under a personal model right.

The account holder's standing decision is that text derived from a personal photograph goes to a
hosted model only under a current right naming that model chain and its destination, the same as
the photograph's bytes. The composer is sent exactly such text: a packet of the claims stored
about each photograph it cites, the vision pass's transcription of a sign among them. Measured on
an isolated runtime, a question in words sent that packet to the reasoning model when the only
rights in the workspace named the vision and embedding roles. These tests hold the rule at the
composer, against the real right check and a real database.

Two halves. The first asks the gate directly, including the exact set of rights that run had.
The second asks through ``answer_question``, so the gate is shown to be reached rather than only
to work, and pairs the refusal with a positive control: the same packet, with the right granted,
does reach the composer. A gate that refused everything would pass the first test of the pair and
fail the second.
"""

from __future__ import annotations

import json

import pytest
from exulanica.api.composer_rights import composer_rights_check
from exulanica.db.roles import provision_runtime_role
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.personal_admission import role_handoff
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.models.client import ModelClient
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection import Session
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.question import answer_question
from exulanica.store.local import LocalContentAddressedStore

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS, photo_bytes, scratch_role_database
from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_personal_admission_route import HostedVisionDouble
from test_personal_model_right import ACCOUNT, admit_personal, grant, grant_all

COMPOSER = ModelHandoff.hosted(load_manifest(), Role.REASONING_CHEAP)
VISION = role_handoff("vision")
EMBEDDING = role_handoff("embedding")


@pytest.fixture
def store(tmp_path) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(tmp_path / "blobs")


@pytest.fixture
def observed(repository, store):
    """A personal photograph the vision pass has described, under a right for the vision role.

    The vision double's fixture observation transcribes a sign, so the capture carries exactly
    the kind of derived text the composer would be sent.
    """
    subject = admit_personal(repository, store, photo_bytes(), "mine.jpg")
    grant_all(subject, VISION)
    vision = HostedVisionDouble()
    outcome = PhotoIngestPipeline(repository, store, vision=vision).ingest_derivatives(
        subject.capture_id, privacy_screening_id=subject.detection_id
    )
    assert outcome.error is None, outcome.error
    assert vision.calls == 1
    return subject


# -- the gate, asked directly ---------------------------------------------------------------------


def _refusal(connection, workspace_id, capture_ids) -> str | None:
    """The check's refusal as text, or None when it permits the hand-over."""
    try:
        composer_rights_check(connection, workspace_id)(capture_ids, COMPOSER)
    except PrivacyAdmissionError as refused:
        return str(refused)
    return None


def test_the_rights_a_measured_run_had_do_not_admit_the_composer(observed):
    """Vision and embedding rights, and nothing for the composer: the isolated runtime's set."""
    grant_all(observed, EMBEDDING)
    refused = _refusal(observed.repository.connection, observed.repository.workspace_id,
                       [observed.capture_id])
    assert refused is not None
    assert str(observed.capture_id) in refused


def test_a_right_for_every_model_the_composer_can_reach_admits_it(observed):
    grant_all(observed, COMPOSER)
    assert _refusal(observed.repository.connection, observed.repository.workspace_id,
                    [observed.capture_id]) is None


def test_a_right_for_the_primary_alone_does_not_admit_it(observed):
    """The fallback can receive the same packet, so it needs a right of its own."""
    primary, *rest = COMPOSER.identities
    assert rest, "the composer role declares a fallback; this test needs one to leave out"
    grant(observed, primary, COMPOSER.destination)
    assert _refusal(observed.repository.connection, observed.repository.workspace_id,
                    [observed.capture_id]) is not None


def test_a_capture_nobody_screened_is_refused(repository, store):
    intake = PhotoIngestPipeline(repository, store).ingest_intake(photo_bytes(), filename="u.jpg")
    refused = _refusal(repository.connection, repository.workspace_id, [intake.capture_id])
    assert refused is not None and "no privacy screening" in refused


def test_a_synthetic_capture_needs_no_right(repository, store):
    """The exemption is the right module's decision, and the gate defers to it."""
    intake = PhotoIngestPipeline(repository, store).ingest_intake(photo_bytes(), filename="s.jpg")
    authorization = authorize_synthetic_capture(
        repository,
        capture_id=intake.capture_id,
        actor=ACCOUNT,
        generator_manifest={"profile": "exulanica.synthetic-test-corpus/v1"},
        authorization_scope={"purpose": "composer right test"},
    )
    record_synthetic_exemption(repository, authorization_id=authorization.authorization_id)
    assert _refusal(repository.connection, repository.workspace_id, [intake.capture_id]) is None


def test_the_check_runs_on_the_executors_read_only_role(observed, spine_schema):
    """The route runs the check on the read-only executor connection, so run it there.

    The check takes the global asset read lock inside a read-only transaction. If that role could
    not take it, the check would crash on every personal photograph instead of deciding, and a
    check that crashes has decided nothing. Refusal and permission are both asked on that role.
    """
    _, schema = spine_schema
    provision_runtime_role(observed.repository.connection, role="exulanica_ro", read_only=True)
    readonly = scratch_role_database(schema, "exulanica_ro")
    workspace = observed.repository.workspace_id
    with readonly.session(workspace) as connection:
        assert connection.execute("select current_user as who").fetchone()["who"] == "exulanica_ro"
        refused = _refusal(connection, workspace, [observed.capture_id])
    assert refused is not None and str(observed.capture_id) in refused

    grant_all(observed, COMPOSER)
    with readonly.session(workspace) as connection:
        assert _refusal(connection, workspace, [observed.capture_id]) is None


# -- the gate, reached through answer_question ----------------------------------------------------


def _client(responses: list[HttpResponse]) -> tuple[ModelClient, FakeTransport]:
    from exulanica.models.budget import BudgetGuard

    transport = FakeTransport(responses)
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        policy=RecordingPolicy(),
    )
    return client, transport


def _ask(observed, client: ModelClient):
    # A supplied plan, so the planner makes no call and the only model call possible is the
    # composer's. The query matches the transcribed sign, so the packet is not empty.
    return answer_question(
        observed.repository.connection,
        client,
        "What does the sign say?",
        Session(workspace_id=observed.repository.workspace_id, actor=ACCOUNT),
        world_id=None,
        plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="gullfoss"),
        store=observed.store,
        before_compose=composer_rights_check(
            observed.repository.connection, observed.repository.workspace_id
        ),
    )


def test_without_a_composer_right_the_packet_is_answered_locally_and_nothing_is_sent(observed):
    client, transport = _client([RuntimeError("the composer was called with no right")])
    answered = _ask(observed, client)

    assert answered.packet is not None and not answered.packet.is_empty
    assert transport.call_count == 0, "the composer received a packet no right permits"
    assert answered.deterministic is True
    assert answered.rejections and answered.rejections[0].startswith("model_right_refused")
    assert answered.calls == ()


def test_with_a_composer_right_the_same_packet_does_reach_the_composer(observed):
    """The positive control for the test above: the gate is a gate, not a wall."""
    grant_all(observed, COMPOSER)
    reply = Answer(clauses=[AnswerClause(text="I have no evidence for that.",
                                         type=ClauseType.META)])
    client, transport = _client(
        [HttpResponse(status_code=200,
                      text=json.dumps(chat_body(reply.model_dump_json())))]
    )
    answered = _ask(observed, client)

    assert transport.call_count >= 1
    assert not any(r.startswith("model_right_refused") for r in answered.rejections)


def test_answering_without_a_right_check_is_refused_outright(observed):
    """No caller can compose by forgetting the check: it is required and must be callable."""
    client, _ = _client([RuntimeError("no model call is expected")])
    with pytest.raises(TypeError, match="before_compose"):
        answer_question(
            observed.repository.connection,
            client,
            "What does the sign say?",
            Session(workspace_id=observed.repository.workspace_id, actor=ACCOUNT),
            world_id=None,
            plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="gullfoss"),
            before_compose=None,
        )
