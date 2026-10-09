"""The reference worker end to end on a migrated database, with every outside party scripted.

The planner and reader answer through the real model client over a scripted transport, Tavily
answers through the real adapter over another, the spending gate records what it was asked, and
the policy is the product's WorkspaceRequestPolicy with one saved person's name. A planted excerpt
and a planted address are in Tavily's answer, a planted name in a planned subject, and none may be
found afterwards in any outgoing query, any row the work wrote, or the bundle.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from decimal import Decimal

import pytest
from exulanica.epistemics import hosted_requests
from exulanica.epistemics.hosted_requests import (
    WorkspaceRequestPolicy,
    borrowing,
    no_place_released,
)
from exulanica.epistemics.saved_names import SavedName
from exulanica.errors import PrivacyAdmissionError
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused, SpendingTicket
from exulanica.models.transport import HttpResponse
from exulanica.references import store
from exulanica.references.adapters.base import ReferenceSourceUnavailable
from exulanica.references.adapters.tavily import TavilySearch
from exulanica.references.bundle import read_bundle
from exulanica.references.worker import PROCESS_RESERVE_PERCENT, ReferenceWorker, stage_seconds
from psycopg.rows import tuple_row

from model_fakes import FakeTransport, RecordingPolicy, chat_body

pytestmark = pytest.mark.postgres

ACTOR = uuid.UUID("7c1a2b3c-4d5e-4f60-8a71-92b3c4d5e6f7")
PERSON = SavedName(
    uuid.UUID("0b1f3c52-2c55-4a50-8e0a-2f6f1d9c4e01"), "person", "Marguerite Okonkwo"
)
PLANTED_EXCERPT = "Wrenfield almanac says the lime wash is renewed every spring by hand"
PLANTED_ADDRESS = "https://planted-result.example/page-4471"
DRAFTER = "Qwen/Qwen3-235B-A22B-Instruct-2507"


class _Database:
    def __init__(self, repository) -> None:
        self._repository = repository

    @contextlib.contextmanager
    def session(self, workspace_id):
        assert workspace_id == self._repository.workspace_id
        yield self._repository.connection


class _Gate:
    """A spending gate that records what it is asked and, as the authority does, refuses a key it
    has already admitted."""

    def __init__(
        self, refuse: str | None = None, *, refuse_dispatch: bool = False, fail_settle: bool = False
    ) -> None:
        self.admitted, self.settled, self.released = [], [], []
        self._refuse = refuse
        self._refuse_dispatch = refuse_dispatch
        self._fail_settle = fail_settle

    def admit(self, request):
        if self._refuse:
            raise SpendingRefused(self._refuse)
        if request.key in {earlier.key for earlier in self.admitted}:
            raise SpendingRefused("duplicate_request_settled")
        self.admitted.append(request)
        return SpendingTicket(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), request.usd, request.key)

    def dispatch(self, ticket):
        if self._refuse_dispatch:
            raise SpendingRefused("spending_suspended")

    def settle(self, ticket, usage):
        if self._fail_settle:
            raise RuntimeError("the ledger did not answer")
        self.settled.append(usage)

    def release(self, ticket):
        self.released.append(ticket)


class _Spending:
    def __init__(self, gate: _Gate) -> None:
        self.gate = gate

    def for_workspace(self, workspace_id):
        return self.gate


def _structured(value: dict) -> HttpResponse:
    return HttpResponse(200, json.dumps(chat_body(json.dumps(value), model=DRAFTER)))


PLAN = {
    "subjects": [
        {"aspect": "buildings", "text": "whitewashed island houses"},
        {"aspect": "buildings", "text": "harbour houses Marguerite Okonkwo painted"},
        {"aspect": "materials_and_colour", "text": "blue painted wooden doors"},
    ]
}
READING = {
    "notes": [
        {"aspect": "buildings", "text": "white cube houses with flat roofs"},
        # Six running words of the planted excerpt: dropped.
        {"aspect": "materials_and_colour", "text": "lime wash is renewed every spring"},
        {"aspect": "materials_and_colour", "text": "doors and shutters in bright blue"},
    ]
}


def _tavily_answer() -> HttpResponse:
    return HttpResponse(
        200,
        json.dumps(
            {
                "results": [
                    {"title": "Wrenfield", "url": PLANTED_ADDRESS, "content": PLANTED_EXCERPT}
                ],
                "images": [
                    {"url": PLANTED_ADDRESS + ".jpg", "description": "White walls, blue doors"}
                ],
                "usage": {"credits": 1},
                "request_id": "123e4567-e89b-12d3-a456-426614174111",
            }
        ),
    )


@pytest.fixture
def scene(repository, monkeypatch):
    monkeypatch.setattr(hosted_requests, "saved_names", lambda connection, workspace: (PERSON,))
    connection, workspace_id = repository.connection, repository.workspace_id
    models = FakeTransport()
    tavily = FakeTransport()
    gate = _Gate()

    def refuse_photographs(*args):
        raise PrivacyAdmissionError("no photograph is read here")

    def policy_for(workspace):
        return WorkspaceRequestPolicy(
            workspace,
            connection=borrowing(connection),
            photograph_right=refuse_photographs,
            released_places=no_place_released,
        )

    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=models,
        budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=20),
        policy=RecordingPolicy(),
    )

    def worker(**changes):
        arguments = dict(
            client=client,
            policy_for=policy_for,
            spending=_Spending(gate),
            adapter_for=lambda source: TavilySearch(
                source, transport=tavily, credential="tvly-test"
            ),
            workspaces=lambda: (workspace_id,),
        )
        arguments.update(changes)
        return ReferenceWorker(_Database(repository), **arguments)

    def request(web: bool = True, purpose: str = "kind"):
        made, _ = store.create_request(
            connection,
            workspace_id,
            offered_to=(workspace_id,),
            owner_actor_id=ACTOR,
            purpose=purpose,
            web=web,
            description="a harbour town with whitewashed houses and blue doors",
            withheld_words=["Rosalind", "Teague"],
            prompts_sha256="e" * 64,
        )
        return made

    return connection, workspace_id, models, tavily, gate, worker, request


def _every_row_as_text(connection) -> str:
    cursor = connection.cursor(row_factory=tuple_row)
    rows = [
        *cursor.execute("select * from reference_request").fetchall(),
        *cursor.execute("select * from reference_lookup").fetchall(),
        *cursor.execute("select * from job").fetchall(),
    ]
    return json.dumps(rows, default=str)


def test_a_web_request_becomes_a_bundle_of_notes_and_keeps_nothing_it_found(scene) -> None:
    connection, workspace_id, models, tavily, gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN), _structured(READING)]
    tavily.responses = [_tavily_answer(), _tavily_answer()]

    assert worker().run_once(workspace_id) == "complete"

    finished = store.read_request(connection, workspace_id, made.reference_id)
    bundle = read_bundle(finished.bundle)
    assert finished.bundle_sha256 == bundle.digest
    assert [(note.aspect, note.text) for note in bundle.notes] == [
        ("buildings", "white cube houses with flat roofs"),
        ("materials_and_colour", "doors and shutters in bright blue"),
    ]
    assert {note.basis for note in bundle.notes} == {"web_description"}
    assert [(call.provider, call.role, call.model_id) for call in bundle.model_calls] == [
        ("nebius_token_factory", "reference_drafting", DRAFTER)
    ] * 2
    # Two subjects passed the boundary; the one naming a saved person never left.
    sent = [request_["payload"]["query"] for request_ in tavily.requests]
    assert sent == ["whitewashed island houses", "blue painted wooden doors"]
    assert len(bundle.lookups) == 2
    assert [(r.provider, r.role, r.usd) for r in gate.admitted] == [
        ("tavily_search", "reference_search", Decimal(0))
    ] * 2
    assert len(gate.settled) == 2 and gate.released == []
    written = _every_row_as_text(connection)
    for planted in (PLANTED_EXCERPT, "Wrenfield", PLANTED_ADDRESS, "Okonkwo", "Rosalind"):
        assert planted not in written
        assert planted not in json.dumps(finished.bundle)
    # The reader was shown the excerpt, in memory only, and that is all it was.
    assert PLANTED_EXCERPT in json.dumps(models.requests[1]["payload"])
    assert [step["state"] for step in finished.steps] == ["done", "done", "done", "done"]


@pytest.mark.parametrize(("purpose", "shown"), [("world_draft", False), ("kind", True)])
def test_a_town_draft_s_reader_is_shown_no_description_of_a_web_picture(scene, purpose, shown):
    """For a town draft the reader is shown the pages' excerpts alone: the source's description of
    a picture it found ("White walls, blue doors") never reaches the model; for a kind it does."""
    _connection, workspace_id, models, tavily, _gate, worker, request = scene
    request(purpose=purpose)
    models.responses = [_structured(PLAN), _structured(READING)]
    tavily.responses = [_tavily_answer(), _tavily_answer()]
    assert worker().run_once(workspace_id) == "complete"
    reading = json.dumps(models.requests[1]["payload"])
    assert PLANTED_EXCERPT in reading
    assert ("White walls, blue doors" in reading) is shown
    assert ("Picture:" in reading) is shown


def test_a_request_without_web_notes_asks_nobody(scene) -> None:
    connection, workspace_id, models, tavily, gate, worker, request = scene
    made = request(web=False)
    assert worker().run_once(workspace_id) == "complete"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert read_bundle(finished.bundle).notes == ()
    assert models.requests == [] and tavily.requests == [] and gate.admitted == []
    assert [step["state"] for step in finished.steps] == ["skipped", "skipped", "skipped", "done"]


def test_a_source_not_configured_is_known_before_any_model_is_asked(scene) -> None:
    connection, workspace_id, models, _tavily, _gate, worker, request = scene
    made = request()

    def not_configured(source):
        raise ReferenceSourceUnavailable("references_not_configured", "no key", charged=False)

    assert worker(adapter_for=not_configured).run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert read_bundle(finished.bundle).missed == ("plan", "search", "read")
    assert finished.steps[1]["reason"] == "references_not_configured"
    assert models.requests == []
    count = connection.cursor(row_factory=tuple_row).execute(
        "select count(*) from reference_lookup"
    )
    assert count.fetchone()[0] == 0


def test_spent_credits_stop_the_searches_before_any_is_sent(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN)]
    spent = _Gate(refuse="spending_limit_reached")
    assert worker(spending=_Spending(spent)).run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert finished.steps[1]["reason"] == "spending_limit_reached"
    assert tavily.requests == []


def test_a_planner_that_answers_outside_its_form_leaves_the_plan_missed(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured({"subjects": [{"aspect": "weather", "text": "sunny"}]})]
    assert worker().run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert read_bundle(finished.bundle).missed == ("plan", "search", "read")
    assert finished.steps[0]["reason"] == "plan_refused"
    assert tavily.requests == []


def test_past_the_deadline_the_request_ends_partial_with_what_it_has(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN)]
    tavily.responses = [_tavily_answer()]
    past = stage_seconds(load_manifest()).total(pictures=0, web=True) + 1.0
    ticks = iter([0.0, 0.0, 0.0, 0.0, past, past, past, past])
    late = worker(clock=lambda: next(ticks, past))
    assert late.run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert "deadline" in json.dumps(finished.steps)


def test_a_request_the_person_stopped_ends_cancelled_without_a_bundle(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN)]

    def stop_then_adapt(source):
        store.request_cancel(connection, workspace_id, made.reference_id)
        return TavilySearch(source, transport=tavily, credential="tvly-test")

    assert worker(adapter_for=stop_then_adapt).run_once(workspace_id) == "cancelled"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert finished.status == "cancelled" and finished.bundle is None
    assert tavily.requests == []


def test_a_cost_change_is_recorded_as_reported_and_stops_the_source_in_this_process(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    first, second = request(), request()
    models.responses = [_structured(PLAN)]
    costly = json.loads(_tavily_answer().text)
    costly["usage"]["credits"] = 3
    tavily.responses = [
        HttpResponse(200, json.dumps(costly)),
        HttpResponse(200, json.dumps(costly)),
    ]
    playing = worker()
    assert playing.run_once(workspace_id) == "partial"
    credits = connection.cursor(row_factory=tuple_row).execute(
        "select outcome, credits from reference_lookup where reference_id=%s",
        (first.reference_id,),
    )
    # The request's two searches were in flight together, and each is recorded as reported.
    assert credits.fetchall() == [("reference_cost_changed", 3)] * 2
    # The next request sends nothing and asks no model: the source is stopped here.
    asked = len(models.requests)
    assert playing.run_once(workspace_id) == "partial"
    later = store.read_request(connection, workspace_id, second.reference_id)
    assert later.steps[1]["reason"] == "reference_cost_changed"
    assert len(tavily.requests) == 2 and len(models.requests) == asked


def test_a_job_taken_again_after_a_crash_does_not_search_again(scene) -> None:
    connection, workspace_id, models, _tavily, gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN), _structured(PLAN)]

    class Crashing:
        def __init__(self) -> None:
            self.sent = 0

        def search(self, query):
            self.sent += 1
            raise RuntimeError("the process died after the search left")

        def close(self) -> None:
            return None

    crashing = Crashing()
    with pytest.raises(RuntimeError):
        worker(adapter_for=lambda source: crashing).run_once(workspace_id)
    connection.execute(
        "update job set lease_expires_at = now() - interval '1 second' where job_id=%s",
        (made.job_id,),
    )
    assert worker(adapter_for=lambda source: crashing).run_once(workspace_id) == "partial"
    # Both of the request's searches had left together before the crash; neither leaves again.
    assert crashing.sent == 2
    keys = sorted(admitted.key for admitted in gate.admitted)
    assert keys == [f"reference:{made.job_id}:search:{index}" for index in (0, 1)]
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert finished.steps[1]["reason"] == "duplicate_request_settled"


def test_a_refused_dispatch_releases_its_ticket_and_sends_nothing(scene) -> None:
    _connection, workspace_id, models, tavily, _gate, worker, request = scene
    request()
    models.responses = [_structured(PLAN)]
    gate = _Gate(refuse_dispatch=True)
    assert worker(spending=_Spending(gate)).run_once(workspace_id) == "partial"
    # Each admitted search's ticket is released, and nothing is sent.
    assert len(gate.released) == 2 and tavily.requests == []


def test_a_settlement_the_ledger_cannot_take_never_ends_the_job(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN), _structured(READING)]
    tavily.responses = [_tavily_answer(), _tavily_answer()]
    gate = _Gate(fail_settle=True)
    assert worker(spending=_Spending(gate)).run_once(workspace_id) == "complete"
    assert store.read_request(connection, workspace_id, made.reference_id).status == "complete"


def test_a_shutdown_ends_a_running_request_partial_at_its_next_step(scene) -> None:
    import threading

    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    stop = threading.Event()
    stop.set()
    assert worker(stop=stop).run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert {step.get("reason") for step in finished.steps[:3]} == {"shutdown"}
    assert models.requests == [] and tavily.requests == []


def test_the_catalog_s_calls_per_minute_holds_in_this_process(scene, monkeypatch) -> None:
    import dataclasses

    from exulanica.references import worker as worker_module
    from exulanica.references.catalogs import load_reference_catalogs

    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    slow = dataclasses.replace(
        load_reference_catalogs().sources["tavily_search"], calls_per_minute=1
    )
    monkeypatch.setattr(worker_module, "web_source", lambda: slow)
    models.responses = [_structured(PLAN), _structured(READING)]
    tavily.responses = [_tavily_answer(), _tavily_answer()]
    assert worker().run_once(workspace_id) == "complete"
    assert len(tavily.requests) == 1
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert len(read_bundle(finished.bundle).lookups) == 1


def test_spent_credits_are_known_before_the_planner_is_paid(scene) -> None:
    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    spent = _Gate(refuse="spending_not_granted")
    assert worker(spending=_Spending(spent)).run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert finished.steps[0]["reason"] == "source_unavailable"
    assert finished.steps[1]["reason"] == "spending_not_granted"
    assert models.requests == [] and tavily.requests == []


def test_reference_jobs_leave_half_the_process_budget_for_other_work(scene) -> None:
    connection, workspace_id, models, _tavily, gate, worker, request = scene
    made = request()
    # Two calls in all: half is kept for other work, so the planner and reader cannot both fit.
    small = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=models,
        budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=2),
        policy=RecordingPolicy(),
    )
    assert PROCESS_RESERVE_PERCENT == 50
    assert worker(client=small).run_once(workspace_id) == "partial"
    finished = store.read_request(connection, workspace_id, made.reference_id)
    assert finished.steps[0]["reason"] == "process_budget_spent"
    assert models.requests == [] and gate.admitted == []


def test_a_spent_rate_is_known_before_the_planner_is_paid(scene, monkeypatch) -> None:
    import dataclasses

    from exulanica.references import worker as worker_module
    from exulanica.references.catalogs import load_reference_catalogs

    connection, workspace_id, models, tavily, _gate, worker, request = scene
    request()
    second = request()
    slow = dataclasses.replace(
        load_reference_catalogs().sources["tavily_search"], calls_per_minute=1
    )
    monkeypatch.setattr(worker_module, "web_source", lambda: slow)
    models.responses = [_structured(PLAN), _structured(READING)]
    tavily.responses = [_tavily_answer()]
    playing = worker()
    playing.run_once(workspace_id)
    asked = len(models.requests)
    assert playing.run_once(workspace_id) == "partial"
    later = store.read_request(connection, workspace_id, second.reference_id)
    assert later.steps[1]["reason"] == "reference_source_rate_limited_here"
    assert len(models.requests) == asked


# -- each step's share of the job's time, searches at once, and a cut call named as one ------------


def test_each_step_has_its_measured_share_and_the_job_their_sum() -> None:
    """The drafting role's timeout for the planner and the reader (25 s, from its manifest basis),
    and the nine searches measured on 2026-10-09 (longest 9,657 ms, times 2, up to 5 s: 20 s)."""
    stages = stage_seconds(load_manifest())
    assert (stages.plan, stages.search, stages.read) == (25.0, 20.0, 25.0)
    assert stages.total(pictures=0, web=True) == 70.0
    assert stages.total(pictures=2, web=False) == 2 * stages.picture


def test_one_request_s_searches_are_sent_at_once(scene) -> None:
    """Both searches the plan admits are in flight together: each waits at a barrier for the
    other, which only a concurrent sending passes."""
    import threading

    _connection, workspace_id, models, _tavily, _gate, worker, request = scene
    request()
    models.responses = [_structured(PLAN), _structured(READING)]
    barrier = threading.Barrier(2, timeout=10)

    class Together(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):
            barrier.wait()
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    together = Together([_tavily_answer(), _tavily_answer()])
    playing = worker(
        adapter_for=lambda source: TavilySearch(source, transport=together, credential="tvly-test")
    )
    assert playing.run_once(workspace_id) == "complete"
    assert len(together.requests) == 2 and not barrier.broken


def test_the_reader_keeps_its_share_after_slow_searches(scene, monkeypatch) -> None:
    """Searches that take their whole share leave the reader its own: it is handed the read
    share, not what a single deadline would have left."""
    from exulanica.references import drafting

    _connection, workspace_id, models, _tavily, _gate, worker, request = scene
    request()
    stages = stage_seconds(load_manifest())
    models.responses = [_structured(PLAN), _structured(READING)]
    now = [0.0]

    class Slow(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):
            now[0] = stages.plan + stages.search
            return super().post_json(url, headers=headers, payload=payload, timeout=timeout)

    slow = Slow([_tavily_answer(), _tavily_answer()])
    handed: list[float] = []
    real = drafting.read_notes

    def reading(client, leads, **keywords):
        handed.append(keywords["deadline_s"])
        return real(client, leads, **keywords)

    monkeypatch.setattr(drafting, "read_notes", reading)
    playing = worker(
        clock=lambda: now[0],
        adapter_for=lambda source: TavilySearch(source, transport=slow, credential="tvly-test"),
    )
    assert playing.run_once(workspace_id) == "complete"
    assert handed == [stages.read]


def test_a_call_cut_by_its_deadline_is_recorded_as_deadline(scene, monkeypatch) -> None:
    from exulanica.models.errors import TransportError
    from exulanica.references import drafting

    connection, workspace_id, models, tavily, _gate, worker, request = scene
    made = request()
    models.responses = [_structured(PLAN)]
    tavily.responses = [_tavily_answer(), _tavily_answer()]

    def cut(client, leads, **keywords):
        raise TransportError("the deadline ended the wait", deadline_ended=True)

    monkeypatch.setattr(drafting, "read_notes", cut)
    assert worker().run_once(workspace_id) == "partial"
    steps = store.read_request(connection, workspace_id, made.reference_id).steps
    (read,) = [step for step in steps if step["step"] == "read"]
    assert (read["state"], read["reason"]) == ("missed", "deadline")
