"""The execution record lists every attempt a request paid for, or may have, and only its own.

A request's model client is its own copy (``ModelClient.with_attempts``), which hands the request's
call log each attempt as the process ledger records it: a completed reply, an attempt that timed
out or failed, and a reply the client refused as truncated or outside the schema. The log lists
each with its outcome and whether its cost is known, never the provider's words about a failure,
and never by reading the process ledger. A request a policy or the budget refused before it left
is not an attempt. When a model error ends the request, the error carries the record to the
problem body, whose ``execution`` member is the block a completed request returns.

The model is scripted throughout. Nothing here spends credits.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import threading
from collections.abc import Mapping
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.composer_rights import composer_rights_check, photograph_text_right
from exulanica.api.services import Services
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import BudgetExceededError, TransportError
from exulanica.models.lens_budget import LensBudget, LensBudgetGuard
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.policy import HostedRequestRefused, NoHostedRequestPolicy
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.calls import noted_calls
from exulanica.selection.plan import Intent, SelectionPlan
from exulanica.selection.question import answer_question
from fastapi.testclient import TestClient

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body, model_not_found
from test_companion_saved_names import named
from tests_support_api import EVERY_PERMISSION, scratch_database
from world_support import FIXTURE_WORLD_ID, registered_world

pytestmark = pytest.mark.postgres

__all__ = ["named"]

MANIFEST = load_manifest()
COMPOSER = MANIFEST.roles[Role.REASONING_CHEAP.value]
PLANNER = MANIFEST.roles[Role.STRUCTURED_EXTRACTION.value]
#: Words a provider might put in a failure, which no execution record may repeat.
PROVIDER_WORDS = "upstream-shard-7 overloaded, quota bucket 991"
PLAN = SelectionPlan(intent=Intent.CAPTURES, semantic_query="running club")
ANSWER = Answer(
    clauses=[AnswerClause(text="Your photographs show a running club.", type=ClauseType.META)]
)
TOKEN = "every-attempt-owner-token-long-enough-for-tests"


def _reply(body: str, **kwargs: Any) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(chat_body(body, **kwargs)))


def _timed_out() -> TransportError:
    return TransportError(
        f"the read timed out: {PROVIDER_WORDS}", timed_out=True, reached_provider=None
    )


def _client(repository, transport, *, max_attempts: int = 1) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
    ).with_policy(
        WorkspaceRequestPolicy(
            repository.workspace_id,
            connection=borrowing(repository.connection),
            photograph_right=photograph_text_right,
            released_places=no_place_released,
        )
    )


def _ask(named, client, *, plan: SelectionPlan | None = PLAN):
    repository, store, session, _ = named
    return answer_question(
        repository.connection,
        client,
        "What do my photographs of the running club show?",
        session,
        world_id=None,
        plan=plan,
        store=store,
        before_compose=composer_rights_check(repository.connection, repository.workspace_id),
    )


def _shape(calls) -> list[tuple[str, str, str, str]]:
    return [(c.role, c.requested_model, c.outcome.value, c.cost_basis.value) for c in calls]


def _no_provider_words(calls) -> None:
    assert PROVIDER_WORDS not in json.dumps([dataclasses.asdict(c) for c in calls])


# -- one question ------------------------------------------------------------------------------


def test_a_timed_out_composer_is_carried_on_the_error_with_its_cost_unknown(named):
    transport = FakeTransport([_timed_out()])
    client = _client(named[0], transport)

    with pytest.raises(TransportError) as raised:
        _ask(named, client)

    noted = noted_calls(raised.value)
    assert noted is not None, "the error that ended the question carries no execution record"
    assert noted.prompt_version
    assert _shape(noted.calls) == [
        ("reasoning_cheap", COMPOSER.primary.model_id, "timed_out", "unknown")
    ]
    (call,) = noted.calls
    assert call.usd is None and call.served_model is None and call.attempts == 1
    _no_provider_words(noted.calls)
    # The process ledger still charges it, at the most it can have cost.
    assert client.ledger.unknown_cost_calls == 1


def test_a_failed_attempt_then_a_retry_that_succeeded_are_both_listed(named):
    transport = FakeTransport(
        [
            HttpResponse(status_code=503, text=json.dumps({"error": PROVIDER_WORDS})),
            _reply(ANSWER.model_dump_json(), model=COMPOSER.primary.model_id),
        ]
    )
    outcome = _ask(named, _client(named[0], transport, max_attempts=2))

    assert _shape(outcome.calls) == [
        ("reasoning_cheap", COMPOSER.primary.model_id, "failed", "unknown"),
        ("reasoning_cheap", COMPOSER.primary.model_id, "completed", "known"),
    ]
    assert outcome.calls[1].attempts == 2
    assert outcome.calls[1].served_model == COMPOSER.primary.model_id
    _no_provider_words(outcome.calls)


def test_a_reply_refused_as_truncated_is_listed_with_its_reported_cost(named):
    transport = FakeTransport([_reply("", finish_reason="length", model=COMPOSER.primary.model_id)])
    outcome = _ask(named, _client(named[0], transport))

    assert outcome.deterministic
    assert _shape(outcome.calls) == [
        ("reasoning_cheap", COMPOSER.primary.model_id, "reply_refused", "known")
    ]
    (call,) = outcome.calls
    assert (call.prompt_tokens, call.completion_tokens) == (100, 200)
    assert call.usd is not None and call.served_model is None


def test_a_withdrawn_primary_is_listed_before_the_fallback_that_answered(named):
    transport = FakeTransport()
    transport.by_model[PLANNER.primary.model_id] = model_not_found(PLANNER.primary.model_id)
    transport.by_model[PLANNER.fallback.model_id] = _reply(
        PLAN.model_dump_json(), model=PLANNER.fallback.model_id
    )
    transport.by_model[COMPOSER.primary.model_id] = _reply(
        ANSWER.model_dump_json(), model=COMPOSER.primary.model_id
    )
    outcome = _ask(named, _client(named[0], transport), plan=None)

    assert _shape(outcome.calls)[:2] == [
        ("structured_extraction", PLANNER.primary.model_id, "failed", "unknown"),
        ("structured_extraction", PLANNER.fallback.model_id, "completed", "known"),
    ]
    assert outcome.calls[1].used_fallback and outcome.calls[1].attempts == 2
    assert _shape(outcome.calls)[-1][:3] == (
        "reasoning_cheap",
        COMPOSER.primary.model_id,
        "completed",
    )


# -- what is never an attempt ------------------------------------------------------------------


def test_a_copy_with_no_policy_still_refuses_to_send_and_hears_nothing():
    heard: list[object] = []
    transport = FakeTransport([_reply("{}")])
    bare = ModelClient(api_key="test-key-not-real", transport=transport)

    with pytest.raises(NoHostedRequestPolicy):
        bare.with_attempts(heard.append).chat(
            Role.REASONING_CHEAP, [{"role": "user", "content": "hello"}], prompt_version="t"
        )
    assert heard == [] and transport.call_count == 0


def test_a_budget_refusal_sent_nothing_and_is_not_an_attempt():
    heard: list[object] = []
    transport = FakeTransport([_reply("{}")])
    client = ModelClient(
        api_key="test-key-not-real",
        transport=transport,
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=0),
        policy=RecordingPolicy(),
    )

    with pytest.raises(BudgetExceededError):
        client.with_attempts(heard.append).chat(
            Role.REASONING_CHEAP, [{"role": "user", "content": "hello"}], prompt_version="t"
        )
    assert heard == [] and transport.call_count == 0


def test_a_lens_budget_client_is_copied_with_its_own_guard_and_counters():
    """A lens guard keeps counters outside its ledger; the copy reserves and records through it."""
    heard: list[object] = []
    guard = LensBudgetGuard(
        "facade-proposer",
        LensBudget(
            max_tokens=1_000_000,
            max_calls=10,
            max_wall_clock_ms=3_600_000,
            max_cost_usd=Decimal("1.00"),
        ),
        per_call_timeout_ms=1_000,
    )
    transport = FakeTransport([_reply("{}"), _reply("{}")])
    client = guard.model_client(
        api_key="test-key-not-real", transport=transport, policy=RecordingPolicy()
    )

    observed = client.with_attempts(heard.append)
    for _ in range(2):
        observed.chat(
            Role.REASONING_CHEAP, [{"role": "user", "content": "hello"}], prompt_version="t"
        )

    assert len(heard) == 2
    assert guard.calls_committed == 2 and guard.billed_calls == 2
    # The guard's own record settled each reservation to what was reported, none left open.
    assert guard.usd_committed == sum((usage.usd for usage in heard), Decimal(0))
    assert guard.ledger.calls == heard
    assert observed.budget is guard and observed.ledger is guard.ledger


# -- two questions at once, through the route --------------------------------------------------


class _TwoAtOnce:
    """A transport that holds each composer request until both questions have sent theirs.

    Then it times out the one that asks ``slow`` and answers the other, so both questions are
    in flight in the same process, through the same process client and ledger, at once.
    """

    def __init__(self, slow: str) -> None:
        self._slow = slow
        self._both = threading.Barrier(2, timeout=20)
        self._lock = threading.Lock()
        self.requests: list[Mapping[str, Any]] = []

    def post_json(self, url, *, headers, payload, timeout) -> HttpResponse:
        with self._lock:
            self.requests.append(payload)
        self._both.wait()
        asked = "\n".join(
            m["content"] for m in payload["messages"] if isinstance(m.get("content"), str)
        )
        if self._slow in asked:
            raise _timed_out()
        return _reply(ANSWER.model_dump_json(), model=str(payload["model"]))

    def get_json(self, url, *, headers, timeout) -> HttpResponse:
        raise AssertionError("no catalogue read in this test")


@pytest.fixture
def app_for(named, spine_schema, monkeypatch):
    """Build the API over the named world, with the process model client over ``transport``."""
    repository, store, session, _ = named
    _psycopg, scratch = spine_schema
    registered_world(repository.connection, repository.workspace_id, FIXTURE_WORLD_ID)
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(repository.workspace_id),
                    "actor": str(session.actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
    )
    with contextlib.ExitStack() as stack:

        def build(transport):
            model = ModelClient(
                api_key="test-key-not-real",
                transport=transport,
                budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
            )
            database = scratch_database(scratch)
            services = Services(
                database=database,
                readonly_database=database,
                store=store,
                tokens=load_token_directory(),
                executor_shares_the_write_role=True,
                model_client=model,
            )
            http = stack.enter_context(TestClient(create_app(services, verify=False)))
            return http, model

        yield build


@pytest.fixture
def ask_api(app_for):
    transport = _TwoAtOnce(slow="Which shirt")
    http, model = app_for(transport)
    return http, model, transport


def _ask_route(http, question: str, *, plan: SelectionPlan | None = PLAN):
    body: dict[str, Any] = {"question": question}
    if plan is not None:
        body["plan"] = plan.model_dump(mode="json")
    return http.post(
        "/selection/ask",
        headers={"Authorization": f"Bearer {TOKEN}"},
        params={"world_id": FIXTURE_WORLD_ID},
        json=body,
    )


def test_two_questions_in_flight_at_once_each_list_only_their_own_attempts(ask_api):
    http, model, transport = ask_api
    responses: dict[str, Any] = {}

    def ask(question: str) -> None:
        responses[question] = http.post(
            "/selection/ask",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"world_id": FIXTURE_WORLD_ID},
            json={"question": question, "plan": PLAN.model_dump(mode="json")},
        )

    questions = ("Which shirt is the runner wearing?", "Where did the running club meet?")
    threads = [threading.Thread(target=ask, args=(q,)) for q in questions]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(transport.requests) == 2, "both questions reached the composer"
    slow, fast = (responses[q] for q in questions)
    assert slow.status_code == 502, slow.text
    problem = slow.json()
    # An extension member beside the problem's own two, which keep their meaning.
    assert set(problem) == {"code", "detail", "execution"}
    assert problem["code"] == "model_refused"
    assert problem["detail"] == "a model request timed out before its reply arrived"
    assert PROVIDER_WORDS not in json.dumps(problem)
    assert [
        (c["role"], c["outcome"], c["cost_basis"], c["usd"]) for c in problem["execution"]["calls"]
    ] == [("reasoning_cheap", "timed_out", "unknown", None)]
    assert PROVIDER_WORDS not in json.dumps(problem["execution"])

    assert fast.status_code == 200, fast.text
    assert [
        (c["role"], c["outcome"], c["cost_basis"]) for c in fast.json()["execution"]["calls"]
    ] == [("reasoning_cheap", "completed", "known")]
    # The process ledger holds both, which is exactly why it is not read for either.
    assert len(model.ledger.calls) == 2


# -- what a failure carries, and in whose words ------------------------------------------------


def test_the_problem_detail_says_what_happened_in_product_words(app_for):
    """The provider's answer to a failed request never reaches the problem body."""
    http, _ = app_for(
        FakeTransport([HttpResponse(status_code=503, text=json.dumps({"error": PROVIDER_WORDS}))])
    )

    response = _ask_route(http, "What do my photographs show?")

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["detail"] == "the model endpoint could not answer a request"
    assert PROVIDER_WORDS not in json.dumps(body)
    assert [c["outcome"] for c in body["execution"]["calls"]] == ["failed"]


class _RefusesTheComposer:
    """The account holder's rules refusing the composer's request as it leaves."""

    def admit(self, request):
        if request.role is Role.REASONING_CHEAP:
            raise HostedRequestRefused("a photograph's model right ended as the request left")
        return request.texts


def test_a_policy_refusal_after_a_paid_planner_carries_the_record(app_for, monkeypatch):
    planned = _reply(PLAN.model_dump_json(), model=PLANNER.primary.model_id)
    http, _ = app_for(FakeTransport([planned]))
    attach = Services.hosted_model

    def refusing(self, connection, workspace_id):
        return attach(self, connection, workspace_id).with_policy(_RefusesTheComposer())

    monkeypatch.setattr(Services, "hosted_model", refusing)

    response = _ask_route(http, "What do my photographs of the running club show?", plan=None)

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "hosted_request_refused"
    assert [(c["role"], c["outcome"]) for c in body["execution"]["calls"]] == [
        ("structured_extraction", "completed")
    ]


def test_a_reply_with_no_choices_is_recorded_as_refused(named):
    empty = chat_body("", model=COMPOSER.primary.model_id)
    empty["choices"] = []
    transport = FakeTransport([HttpResponse(status_code=200, text=json.dumps(empty))])
    client = _client(named[0], transport)

    with pytest.raises(TransportError) as raised:
        _ask(named, client)

    noted = noted_calls(raised.value)
    assert noted is not None
    assert _shape(noted.calls) == [
        ("reasoning_cheap", COMPOSER.primary.model_id, "reply_refused", "known")
    ]
    assert len(client.ledger.calls) == 1


def test_a_failure_after_a_refused_answer_carries_the_validator_s_reasons(named):
    uncited = Answer(
        clauses=[AnswerClause(text="You were at the running club.", type=ClauseType.HISTORICAL)]
    )
    transport = FakeTransport(
        [_reply(uncited.model_dump_json(), model=COMPOSER.primary.model_id), _timed_out()]
    )

    with pytest.raises(TransportError) as raised:
        _ask(named, _client(named[0], transport))

    noted = noted_calls(raised.value)
    assert noted is not None and noted.rejections
    assert [c.outcome.value for c in noted.calls] == ["completed", "timed_out"]


def test_an_environment_proposal_lists_every_attempt_and_carries_it_on_failure(named):
    from exulanica.selection.environment_proposal import (
        EnvironmentOperation,
        propose_environment_operation,
    )

    repository, _, session, _ = named
    offered = [EnvironmentOperation.PLACE_SELECTED_FEATURE]
    refused_then_drafted = FakeTransport(
        [
            _reply(json.dumps({"operation": "not an offered one"})),
            _reply(json.dumps({"operation": offered[0].value})),
        ]
    )
    client = _client(repository, refused_then_drafted)
    decision = propose_environment_operation(
        repository.connection, client, "put it here", session, offered
    )
    assert [c.outcome.value for c in decision.calls] == ["reply_refused", "completed"]

    with pytest.raises(TransportError) as raised:
        propose_environment_operation(
            repository.connection,
            _client(repository, FakeTransport([_timed_out()])),
            "put it here",
            session,
            offered,
        )
    noted = noted_calls(raised.value)
    assert noted is not None and [c.outcome.value for c in noted.calls] == ["timed_out"]


def test_the_problem_body_carries_the_rejections_noted_before_the_failure(app_for):
    uncited = Answer(
        clauses=[AnswerClause(text="You were at the running club.", type=ClauseType.HISTORICAL)]
    )
    http, _ = app_for(
        FakeTransport(
            [_reply(uncited.model_dump_json(), model=COMPOSER.primary.model_id), _timed_out()]
        )
    )

    response = _ask_route(http, "What do my photographs of the running club show?")

    assert response.status_code == 502, response.text
    execution = response.json()["execution"]
    assert execution["rejections"], "the validator's reasons were dropped from the failure"
    assert [c["outcome"] for c in execution["calls"]] == ["completed", "timed_out"]


def test_a_selection_refused_after_composition_carries_what_was_paid_for(app_for, monkeypatch):
    """The evidence re-check can refuse the plan after the composer was paid; the record stays."""
    from exulanica.selection import question as question_module
    from exulanica.selection.validation import RejectionCode, SelectionRejected

    http, _ = app_for(
        FakeTransport([_reply(ANSWER.model_dump_json(), model=COMPOSER.primary.model_id)])
    )
    validated = question_module.validate
    calls = {"n": 0}

    def refuse_the_second(connection, plan, session):
        calls["n"] += 1
        if calls["n"] == 2:
            raise SelectionRejected(RejectionCode.NOT_AUTHORISED, "withdrawn while composing")
        return validated(connection, plan, session)

    monkeypatch.setattr(question_module, "validate", refuse_the_second)

    response = _ask_route(http, "What do my photographs of the running club show?")

    assert response.status_code != 200, response.text
    body = response.json()
    assert body["code"] == "not_authorised"
    assert [(c["role"], c["outcome"]) for c in body["execution"]["calls"]] == [
        ("reasoning_cheap", "completed")
    ]


def test_a_copy_of_the_request_s_budget_view_does_not_recurse():
    """copy, deepcopy and pickle build the instance before its state: nothing to ask then."""
    import copy
    import pickle

    heard: list[object] = []
    client = ModelClient(
        api_key="test-key-not-real",
        transport=FakeTransport([_reply("{}")]),
        policy=RecordingPolicy(),
    ).with_attempts(heard.append)
    recorder = client._recorder

    for twin in (
        copy.copy(recorder),
        copy.deepcopy(recorder),
        pickle.loads(pickle.dumps(recorder)),
    ):
        assert twin.ceiling_usd == recorder.ceiling_usd
    copied = copy.copy(client)
    copied.chat(Role.REASONING_CHEAP, [{"role": "user", "content": "hello"}], prompt_version="t")
    assert len(heard) == 1
