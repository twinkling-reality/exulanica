"""How the model client asks the durable spending authority, with no database in the way.

The client learns about durable spending through one injected protocol
(:mod:`exulanica.models.spending`). These tests hold its order and its conservative side with a
scripted gate: every attempt is admitted and dispatched before anything reaches the transport, a
refusal sends nothing, what came back settles it, and an attempt that may have left without an
answer keeps its whole reservation.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from decimal import Decimal

import pytest
from exulanica.models.budget import BoundedBudget, BudgetGuard
from exulanica.models.chain import ModelChain
from exulanica.models.client import ModelClient
from exulanica.models.egress import EgressRefused
from exulanica.models.errors import BudgetExceededError, ProviderRefused, TransportError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.spending import (
    SPENDING_REFUSALS,
    SpendingRefused,
    SpendingRequest,
    SpendingTicket,
    next_request_key,
    spending_request_key,
)
from exulanica.models.transport import HttpResponse

from model_fakes import FakeTransport, RecordingPolicy, chat_body, model_not_found

ROLE = Role.REASONING_CHEAP
MESSAGES = [{"role": "user", "content": "hello"}]
AUTHORITY = uuid.uuid4()


class Journal(list):
    """Every step of every attempt, gate and transport alike, in the order it happened."""


class ScriptedGate:
    def __init__(
        self,
        journal: Journal,
        workspace_id: uuid.UUID,
        *,
        refuse_admit: str | None = None,
        refuse_dispatch: str | None = None,
        fail_settle: bool = False,
    ) -> None:
        self.journal = journal
        self.workspace_id = workspace_id
        self.refuse_admit = refuse_admit
        self.refuse_dispatch = refuse_dispatch
        self.fail_settle = fail_settle
        self.requests: list[SpendingRequest] = []

    def admit(self, request: SpendingRequest) -> SpendingTicket:
        self.requests.append(request)
        self.journal.append(("admit", request.model_id))
        if self.refuse_admit is not None:
            raise SpendingRefused(self.refuse_admit, scope="workspace")
        return SpendingTicket(
            reservation_id=uuid.uuid4(),
            authority_id=AUTHORITY,
            workspace_id=self.workspace_id,
            usd=request.usd,
            key=request.key,
        )

    def dispatch(self, ticket: SpendingTicket) -> None:
        self.journal.append(("dispatch", ticket.key))
        if self.refuse_dispatch is not None:
            raise SpendingRefused(self.refuse_dispatch, scope="workspace")

    def settle(self, ticket, usage) -> None:
        self.journal.append(("settle", str(usage.cost_basis), usage.usd))
        if self.fail_settle:
            raise RuntimeError("the authority did not answer")

    def release(self, ticket) -> None:
        self.journal.append(("release", ticket.key))


class ScriptedSource:
    def __init__(self, journal: Journal, **options) -> None:
        self.journal = journal
        self.options = options
        self.gates: dict[uuid.UUID, ScriptedGate] = {}

    def for_workspace(self, workspace_id: uuid.UUID) -> ScriptedGate:
        gate = ScriptedGate(self.journal, workspace_id, **self.options)
        self.gates[workspace_id] = gate
        return gate


class JournalTransport(FakeTransport):
    def __init__(self, journal: Journal, responses=None) -> None:
        super().__init__(responses)
        self.journal = journal

    def post_json(self, url, *, headers, payload, timeout):
        self.journal.append(("send", payload.get("model")))
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


class WorkspacePolicy:
    """What the client reads of a workspace's policy: its workspace and its admit."""

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id

    def admit(self, request):
        return request.texts


def _client(journal, *, responses=None, max_attempts=1, **options):
    transport = JournalTransport(journal, responses)
    source = ScriptedSource(journal, **options)
    guard = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=guard,
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
        spending=source,
    )
    return client, transport, source, guard


def _chat(client):
    return client.chat(ROLE, MESSAGES, prompt_version="spending-test", use_cache=False)


def _kinds(journal):
    return [entry[0] for entry in journal]


def test_every_attempt_is_admitted_and_dispatched_before_it_is_sent_and_settled_after():
    journal = Journal()
    client, _transport, source, guard = _client(journal)
    workspace = uuid.uuid4()
    result = _chat(client.with_policy(WorkspacePolicy(workspace)))
    assert result.answer == "OK"
    assert _kinds(journal) == ["admit", "dispatch", "send", "settle"]
    assert journal[-1][1] == "reported"
    assert journal[-1][2] == result.usage.usd
    gate = source.gates[workspace]
    (request,) = gate.requests
    # The durable reservation is the worst case the process's fuse holds for the same attempt.
    spec = load_manifest()[ROLE].primary
    assert request.usd == guard.estimate_usd(
        spec,
        prompt_chars=sum(len(str(m)) for m in MESSAGES),
        max_tokens=load_manifest()[ROLE].default_max_tokens,
    )
    assert (request.provider, request.model_id, request.role) == (
        spec.provider,
        spec.model_id,
        str(ROLE),
    )
    assert guard.held_usd == 0


def test_a_client_with_a_source_sends_nothing_without_a_workspace():
    journal = Journal()
    client, transport, _source, guard = _client(journal)
    with pytest.raises(SpendingRefused) as refused:
        _chat(client.with_policy(RecordingPolicy()))
    assert refused.value.reason == "spending_scope_missing"
    assert isinstance(refused.value, BudgetExceededError)
    assert transport.call_count == 0 and journal == []
    assert (guard.held_usd, guard.held_calls, guard.billed_calls) == (0, 0, 0)


def test_a_refused_admission_sends_nothing_and_gives_the_fuse_back():
    journal = Journal()
    client, transport, _source, guard = _client(journal, refuse_admit="spending_not_granted")
    with pytest.raises(SpendingRefused) as refused:
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert refused.value.reason == "spending_not_granted"
    assert transport.call_count == 0
    assert _kinds(journal) == ["admit"]
    assert (guard.held_usd, guard.held_calls, guard.billed_calls) == (0, 0, 0)


def test_a_refused_dispatch_releases_the_admission_and_sends_nothing():
    journal = Journal()
    client, transport, _source, guard = _client(journal, refuse_dispatch="spending_revoked")
    with pytest.raises(SpendingRefused) as refused:
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert refused.value.reason == "spending_revoked"
    assert transport.call_count == 0
    assert _kinds(journal) == ["admit", "dispatch", "release"]
    assert guard.held_usd == 0


def test_a_timeout_after_dispatch_keeps_the_whole_reservation():
    journal = Journal()
    timeout = TransportError("timed out", timed_out=True, reached_provider=None)
    client, _transport, source, _guard = _client(journal, responses=[timeout])
    workspace = uuid.uuid4()
    with pytest.raises(TransportError):
        _chat(client.with_policy(WorkspacePolicy(workspace)))
    assert _kinds(journal) == ["admit", "dispatch", "send", "settle"]
    (request,) = source.gates[workspace].requests
    assert journal[-1][1:] == ("unknown", request.usd)


def test_a_connection_never_made_is_released():
    journal = Journal()
    refused = TransportError("connect failed", reached_provider=False, retryable=False)
    client, _transport, _source, _guard = _client(journal, responses=[refused])
    with pytest.raises(TransportError):
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert _kinds(journal) == ["admit", "dispatch", "send", "release"]


def test_a_missing_credential_is_refused_before_the_authority_is_asked(monkeypatch):
    journal = Journal()
    client, transport, _source, guard = _client(journal)

    def no_credential(self, spec):
        raise ProviderRefused(
            "no credential", provider=spec.provider, reason="provider_credential_absent"
        )

    monkeypatch.setattr(ModelChain, "_headers", no_credential)
    with pytest.raises(ProviderRefused):
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert journal == [] and transport.call_count == 0
    assert guard.held_usd == 0


def test_an_allowlist_refusal_at_the_transport_is_released():
    journal = Journal()
    client, _transport, _source, guard = _client(journal, responses=[EgressRefused("undeclared")])
    with pytest.raises(EgressRefused):
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert _kinds(journal) == ["admit", "dispatch", "send", "release"]
    assert guard.held_usd == 0


class InterruptedTransport(JournalTransport):
    """Sends, then stops the process's wait the way an interruption does."""

    def post_json(self, url, *, headers, payload, timeout):
        self.journal.append(("send", payload.get("model")))
        raise KeyboardInterrupt


def test_an_interruption_while_under_way_leaves_the_reservation_held():
    journal = Journal()
    client, _transport, _source, guard = _client(journal)
    client._chain._transport = InterruptedTransport(journal)
    with pytest.raises(KeyboardInterrupt):
        _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    # Nothing settles or releases it: the request may have reached the provider.
    assert _kinds(journal) == ["admit", "dispatch", "send"]
    assert guard.held_usd == 0


def test_each_retry_is_admitted_on_its_own():
    journal = Journal()
    busy = HttpResponse(status_code=503, text='{"error": {"message": "busy"}}')
    client, _transport, _source, _guard = _client(journal, responses=[busy], max_attempts=2)
    _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert _kinds(journal) == [
        "admit",
        "dispatch",
        "send",
        "settle",
        "admit",
        "dispatch",
        "send",
        "settle",
    ]
    assert [journal[3][1], journal[7][1]] == ["unknown", "reported"]


def test_a_withdrawn_model_is_settled_unknown_and_the_fallback_admitted_on_its_own():
    manifest = load_manifest()
    role = next(role for role, binding in manifest.roles.items() if binding.fallback is not None)
    primary = manifest[role].primary.model_id
    journal = Journal()
    client, transport, source, _guard = _client(journal)
    transport.by_model[primary] = model_not_found(primary)
    transport.default = HttpResponse(status_code=200, text=chat_body_json())
    workspace = uuid.uuid4()
    client.with_policy(WorkspacePolicy(workspace)).chat(
        role, MESSAGES, prompt_version="spending-test", use_cache=False
    )
    admitted = [request.model_id for request in source.gates[workspace].requests]
    assert admitted == [primary, manifest[role].fallback.model_id]
    assert [entry[1] for entry in journal if entry[0] == "settle"] == ["unknown", "reported"]


def chat_body_json() -> str:
    import json

    return json.dumps(chat_body())


def test_a_cache_hit_asks_the_authority_nothing(tmp_path):
    from exulanica.models.cache import FileResponseCache

    journal = Journal()
    source = ScriptedSource(journal)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=JournalTransport(journal),
        budget=BudgetGuard(ceiling_usd=Decimal(1), max_calls=100),
        cache=FileResponseCache(tmp_path / "cache"),
        spending=source,
    ).with_policy(WorkspacePolicy(uuid.uuid4()))
    client.chat(ROLE, MESSAGES, prompt_version="spending-test")
    journal.clear()
    cached = client.chat(ROLE, MESSAGES, prompt_version="spending-test")
    assert cached.cache_hit and journal == []


def test_attempt_keys_count_within_a_request_and_are_fresh_outside_one():
    journal = Journal()
    busy = HttpResponse(status_code=503, text='{"error": {"message": "busy"}}')
    client, _transport, source, _guard = _client(journal, responses=[busy], max_attempts=2)
    workspace = uuid.uuid4()
    with spending_request_key("society-decision:request-7"):
        _chat(client.with_policy(WorkspacePolicy(workspace)))
    keys = [request.key for request in source.gates[workspace].requests]
    assert keys == ["society-decision:request-7#1", "society-decision:request-7#2"]
    outside = next_request_key()
    assert outside.startswith("auto:") and outside != next_request_key()
    # The same request replayed is admitted as the same attempts.
    journal.clear()
    replay, _transport, replayed, _guard = _client(journal, responses=[busy], max_attempts=2)
    with spending_request_key("society-decision:request-7"):
        _chat(replay.with_policy(WorkspacePolicy(workspace)))
    assert [request.key for request in replayed.gates[workspace].requests] == keys


@pytest.mark.parametrize("key", ["", "has space", "a" * 181, "@person", "é"])
def test_a_request_key_is_a_plain_bounded_label(key):
    with pytest.raises(ValueError), spending_request_key(key):
        pass


def test_attempt_observers_and_bounds_keep_the_workspace_spending():
    journal = Journal()
    client, _transport, source, guard = _client(journal)
    workspace = uuid.uuid4()
    scoped = client.with_policy(WorkspacePolicy(workspace))
    heard = []
    _chat(scoped.with_attempts(heard.append))
    bound = BoundedBudget(guard, ceiling_usd=Decimal("0.5"), max_calls=5)
    _chat(scoped.with_bound(bound))
    assert len(heard) == 1
    assert len(source.gates[workspace].requests) == 2


def test_a_settlement_the_authority_cannot_take_keeps_the_answer(caplog):
    journal = Journal()
    client, _transport, _source, _guard = _client(journal, fail_settle=True)
    with caplog.at_level(logging.WARNING, logger="exulanica.models.chain"):
        result = _chat(client.with_policy(WorkspacePolicy(uuid.uuid4())))
    assert result.answer == "OK"
    assert "stays held" in caplog.text


def test_an_embedding_is_admitted_as_a_chat_is():
    journal = Journal()
    client, _transport, source, _guard = _client(journal)
    workspace = uuid.uuid4()
    embedding = {
        "model": "embedder",
        "data": [{"embedding": [0.0] * 4}],
        "usage": {"prompt_tokens": 3},
    }
    import json

    client._chain._transport.default = HttpResponse(status_code=200, text=json.dumps(embedding))
    # The dimensions check may refuse the scripted vector after it is settled; admission came
    # first either way, and that is what this holds.
    with contextlib.suppress(Exception):
        client.with_policy(WorkspacePolicy(workspace)).embed(["a caption"], use_cache=False)
    assert _kinds(journal)[:4] == ["admit", "dispatch", "send", "settle"]
    assert source.gates[workspace].requests[0].role == "embedding"


def test_one_client_copy_spends_for_one_workspace():
    journal = Journal()
    client, _transport, _source, _guard = _client(journal)
    scoped = client.with_policy(WorkspacePolicy(uuid.uuid4()))
    with pytest.raises(ValueError, match="one workspace"):
        scoped.with_policy(WorkspacePolicy(uuid.uuid4()))


def test_a_client_without_a_source_spends_as_it_always_has():
    journal = Journal()
    transport = JournalTransport(journal)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal(1), max_calls=100),
        policy=RecordingPolicy(),
    )
    _chat(client)
    assert _kinds(journal) == ["send"]
    assert client.spending is None and client.spending_source is None


def test_a_source_is_attached_before_any_policy():
    journal = Journal()
    transport = JournalTransport(journal)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal(1), max_calls=100),
    )
    composed = client.with_spending_source(ScriptedSource(journal))
    with pytest.raises(SpendingRefused, match="no workspace"):
        _chat(composed.with_policy(RecordingPolicy()))
    with pytest.raises(ValueError, match="before any policy"):
        client.with_policy(RecordingPolicy()).with_spending_source(ScriptedSource(journal))


def test_an_authority_refusal_states_no_figure_of_other_workspaces():
    shared = SpendingRefused(
        "spending_limit_reached",
        scope="authority",
        detail="usd",
        limit="5.00000000",
        committed="4.99990000",
        requested="0.00120000",
    )
    member = shared.problem_member()
    assert member == {
        "reason": "spending_limit_reached",
        "retry": "never",
        "scope": "authority",
        "detail": "usd",
        "requested": "0.00120000",
    }
    assert "4.9999" not in str(shared) and "5.0000" not in str(shared)
    assert shared.spent_usd is None and shared.ceiling_usd is None
    own = SpendingRefused(
        "spending_limit_reached",
        scope="workspace",
        detail="usd",
        limit="0.50000000",
        committed="0.49990000",
        requested="0.00120000",
    )
    assert own.problem_member()["committed"] == "0.49990000"
    assert "0.49990000" in str(own)


def test_every_refusal_says_whether_asking_again_can_succeed():
    retries = {reason: SpendingRefused(reason).retry for reason in SPENDING_REFUSALS}
    assert retries["spending_unavailable"] == "later"
    assert retries["spending_suspended"] == "after_reauthorization"
    assert {retries[reason] for reason in SPENDING_REFUSALS} <= {
        "never",
        "later",
        "after_reauthorization",
    }
    with pytest.raises(ValueError):
        SpendingRefused("process_budget_spent")


@pytest.mark.parametrize(
    "usd", [Decimal("-0.00000001"), Decimal("0.000000001"), Decimal("NaN"), 0.01]
)
def test_a_reservation_is_a_finite_amount_at_the_ledger_quantum(usd):
    with pytest.raises(ValueError):
        SpendingRequest(provider="p", model_id="m", role="r", usd=usd, key="auto:1")
