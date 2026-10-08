"""The drafts of kinds of world a process holds: a draft's job runs on its own thread, so the route
that starts it answers at once; a workspace runs one draft at a time, a person starts a few an
hour and the process runs a few; a draft ends once, as its job leaves it, forgets its words when it
ends, is read only by the person who started it, and is forgotten an hour after it ended. No test
here sends a request anywhere or reads a database."""

from __future__ import annotations

import re
import threading
import uuid

import pytest
from exulanica.api.kind_drafts import (
    KIND_DRAFT_CODES,
    KindDraft,
    KindDraftBusy,
    KindDraftCapacity,
    KindDraftLimit,
    KindDrafts,
    draft_deadline_seconds,
)
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection.kind_drafting import DRAFT_ATTEMPTS
from exulanica.world.kinds.worker import CHECK_SECONDS

HERE, THERE, ELSEWHERE = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
ACTOR, SOMEBODY = uuid.uuid4(), uuid.uuid4()


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _held(release: threading.Event, ready: threading.Event | None = None):
    """A job that waits for ``release``, then finishes ready: a model still reasoning."""

    def job(draft: KindDraft, drafts: KindDrafts) -> None:
        if ready is not None:
            ready.set()
        release.wait(10)
        drafts.finish(draft, state="ready", kind="farm", version=1)

    return job


def _settled(drafts: KindDrafts, workspace: uuid.UUID, draft_id: uuid.UUID) -> KindDraft:
    for _ in range(200):
        draft = drafts.read(workspace, ACTOR, draft_id)
        assert draft is not None
        if draft.state != "drafting":
            return draft
        threading.Event().wait(0.01)
    raise AssertionError("the draft never ended")


def test_a_draft_is_answered_while_its_job_still_runs_and_ends_as_the_job_leaves_it():
    drafts = KindDrafts()
    release, started = threading.Event(), threading.Event()
    draft = drafts.start(HERE, ACTOR, "a farm", _held(release, started))
    assert started.wait(5)
    assert draft.state == "drafting"
    running = drafts.read(HERE, ACTOR, draft.draft_id)
    assert (running.state, running.description) == ("drafting", "a farm")
    release.set()
    ended = _settled(drafts, HERE, draft.draft_id)
    assert (ended.state, ended.kind, ended.version) == ("ready", "farm", 1)
    # A draft that ended keeps nothing the person typed.
    assert ended.description == ""


def test_a_workspace_runs_one_draft_and_the_process_no_more_than_its_share():
    drafts = KindDrafts(per_server=2)
    release = threading.Event()
    first = drafts.start(HERE, ACTOR, "a farm", _held(release))
    with pytest.raises(KindDraftBusy) as busy:
        drafts.start(HERE, ACTOR, "a harbour", _held(release))
    assert (busy.value.draft_id, busy.value.actor) == (first.draft_id, ACTOR)
    drafts.start(THERE, ACTOR, "a cafe", _held(release))
    with pytest.raises(KindDraftCapacity):
        drafts.start(ELSEWHERE, ACTOR, "a school", _held(release))
    release.set()
    _settled(drafts, HERE, first.draft_id)
    # Once one ends, the workspace and the process may start again.
    _settled_next = drafts.start(HERE, ACTOR, "a harbour", _held(release))
    assert _settled(drafts, HERE, _settled_next.draft_id).state == "ready"


def test_a_job_that_fails_or_says_nothing_leaves_its_draft_refused_by_name():
    drafts = KindDrafts()

    def failing(draft: KindDraft, drafts: KindDrafts) -> None:
        raise RuntimeError("the worker went away")

    def silent(draft: KindDraft, drafts: KindDrafts) -> None:
        return None

    failed = _settled(drafts, HERE, drafts.start(HERE, ACTOR, "a farm", failing).draft_id)
    assert (failed.state, failed.refusal["code"]) == ("refused", "kind_draft_failed")
    quiet = _settled(drafts, THERE, drafts.start(THERE, ACTOR, "a farm", silent).draft_id)
    assert (quiet.state, quiet.refusal["code"]) == ("refused", "kind_draft_failed")


def test_a_draft_ends_once():
    drafts = KindDrafts()

    def twice(draft: KindDraft, drafts: KindDrafts) -> None:
        drafts.finish(draft, state="ready", kind="farm", version=1)
        drafts.finish(draft, state="refused", refusal={"code": "late", "detail": ""})

    ended = _settled(drafts, HERE, drafts.start(HERE, ACTOR, "a farm", twice).draft_id)
    assert (ended.state, ended.refusal) == ("ready", None)


def test_only_the_person_who_started_a_draft_reads_it_and_an_ended_one_is_forgotten_in_an_hour():
    clock = _Clock()
    drafts = KindDrafts(clock=clock)
    release = threading.Event()
    held = drafts.start(HERE, ACTOR, "a farm", _held(release))
    assert drafts.read(THERE, ACTOR, held.draft_id) is None
    assert drafts.read(HERE, SOMEBODY, held.draft_id) is None
    assert drafts.read(HERE, ACTOR, uuid.uuid4()) is None
    clock.now += 60  # a draft still running within its deadline is never forgotten
    assert drafts.read(HERE, ACTOR, held.draft_id).state == "drafting"
    release.set()
    ended = _settled(drafts, HERE, held.draft_id)
    clock.now = ended.changed + 3599
    assert drafts.read(HERE, ACTOR, held.draft_id) is not None
    clock.now += 2
    assert drafts.read(HERE, ACTOR, held.draft_id) is None


def test_a_draft_still_drafting_past_its_deadline_ends_as_failed_and_frees_its_workspace():
    """A job that can no longer finish (its thread gone) would hold the workspace and one of the
    process's places until a restart; past the deadline and a margin it ends instead."""
    clock = _Clock()
    drafts = KindDrafts(clock=clock, deadline_seconds=lambda: 100.0)
    release = threading.Event()
    held = drafts.start(HERE, ACTOR, "a farm", _held(release))
    clock.now += 100 + 120
    assert drafts.read(HERE, ACTOR, held.draft_id).state == "drafting"
    clock.now += 1
    stuck = drafts.read(HERE, ACTOR, held.draft_id)
    assert (stuck.state, stuck.refusal["code"], stuck.description) == (
        "refused",
        "kind_draft_failed",
        "",
    )
    assert drafts.refusal(HERE, ACTOR) is None
    release.set()
    # The job finishing late changes nothing: a draft ends once.
    threading.Event().wait(0.05)
    assert drafts.read(HERE, ACTOR, held.draft_id).state == "refused"


def test_a_person_starts_as_many_drafts_an_hour_as_they_may_and_then_waits():
    clock = _Clock()
    drafts = KindDrafts(clock=clock, starts_per_hour=3)
    release = threading.Event()
    release.set()
    for _ in range(3):
        _settled(drafts, HERE, drafts.start(HERE, ACTOR, "a farm", _held(release)).draft_id)
        clock.now += 10
    assert drafts.refusal(HERE, ACTOR) == "kind_draft_limit"
    with pytest.raises(KindDraftLimit) as limited:
        drafts.start(HERE, ACTOR, "a farm", _held(release))
    # The first start leaves the hour 3600 - 30 seconds from now.
    assert limited.value.retry_seconds == 3570
    # Somebody else in the workspace is not counted with them.
    assert drafts.refusal(HERE, SOMEBODY) is None
    clock.now += 3569
    assert drafts.refusal(HERE, ACTOR) == "kind_draft_limit"
    clock.now += 1
    assert drafts.refusal(HERE, ACTOR) is None


def test_a_draft_whose_thread_cannot_start_holds_no_place(monkeypatch):
    drafts = KindDrafts()

    def no_thread(self) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading.Thread, "start", no_thread)
    with pytest.raises(KindDraftCapacity):
        drafts.start(HERE, ACTOR, "a farm", _held(threading.Event()))
    monkeypatch.undo()
    assert drafts.listing(HERE, ACTOR) == ()
    assert drafts.refusal(HERE, ACTOR) is None


def test_a_draft_reaching_its_checks_while_the_server_closes_starts_no_kind_worker(monkeypatch):
    from exulanica.api import kind_drafts

    from kind_briefs import fixture_kind

    class _NoJob:
        checks = None

        def run(self, *args, **kwargs):
            raise AssertionError("a kind job was run while the server closed")

    monkeypatch.setattr(kind_drafts, "kind_worker", _NoJob)
    drafts = KindDrafts()
    check = kind_drafts._checked(HERE, drafts)
    drafts.close()
    with pytest.raises(kind_drafts._ChecksUnavailable):
        check(fixture_kind("farm"))


def test_a_draft_s_deadline_is_its_attempts_at_the_role_s_timeout_and_their_checks():
    timeout = load_manifest()[Role.KIND_DRAFTER].timeout_seconds
    assert draft_deadline_seconds() == DRAFT_ATTEMPTS * (timeout + CHECK_SECONDS)


def test_a_person_s_drafts_are_listed_newest_first_and_nobody_else_s():
    clock = _Clock()
    drafts = KindDrafts(clock=clock)
    release = threading.Event()
    release.set()
    first = drafts.start(HERE, ACTOR, "a farm", _held(release))
    _settled(drafts, HERE, first.draft_id)
    clock.now += 5
    second = drafts.start(HERE, ACTOR, "a harbour", _held(release))
    _settled(drafts, HERE, second.draft_id)
    drafts.start(HERE, SOMEBODY, "a cafe", _held(release))
    listed = [draft.draft_id for draft in drafts.listing(HERE, ACTOR)]
    assert listed == [second.draft_id, first.draft_id]
    assert drafts.listing(THERE, ACTOR) == ()


def test_every_code_a_draft_answers_with_is_in_the_closed_list():
    """The page keeps one words table for these codes; a code the routes or the job can answer
    with that the list lacks fails here, read from the code itself, the list's own text left out."""
    import inspect

    from exulanica.api import kind_drafts
    from exulanica.api.routes import world_kinds
    from exulanica.api.routes.selection import ModelNotConfigured
    from exulanica.world.kinds.document import KIND_CODES
    from exulanica.world.kinds.repository import KindCapReached, KindVersionExists

    listed = {code for code, _meaning in KIND_DRAFT_CODES}
    module, stripped = re.subn(
        r"KIND_DRAFT_CODES: Final = \(.*?\n\)\n", "", inspect.getsource(kind_drafts), flags=re.S
    )
    assert stripped == 1
    sources = [module] + [
        inspect.getsource(getattr(world_kinds, name))
        for name in ("start_kind_draft", "read_kind_draft", "list_kind_drafts", "_drafting")
    ]
    shapes = (
        r'"code": "([a-z_]+)"',  # a refusal the job leaves
        r'_problem\(\s*\d+,\s*"([a-z_]+)"',  # a route's problem
        r'(?:return|code =) "([a-z_]+)"',  # the offered read's and the registry's own words
    )
    answered = {
        found for source in sources for shape in shapes for found in re.findall(shape, source)
    }
    # The positive control: with the list's text left out, the scan still finds codes of each
    # shape, so a list that lacked them would fail.
    assert {
        "kind_draft_failed",
        "budget_exceeded",
        "kind_draft_busy",
        "kind_draft_limit",
        "kind_draft_unknown",
        "not_authorised",
    } <= answered
    # Codes passed by attribute: the cap and the version's refusals, no model credential, and the
    # permission layer's 404 to a credential without world.read.
    answered |= {KindCapReached.code, KindVersionExists.code, ModelNotConfigured.code}
    answered |= {"unknown_reference"}
    # A kind's own refusals are the kind checks' codes, listed apart (KIND_CODES).
    answered -= {code for code, _meaning in KIND_CODES}
    assert answered <= listed, sorted(answered - listed)


def _client(**options):
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient

    from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
    from model_fakes import FakeTransport

    return ModelClient(
        api_key="test-key-not-real",
        transport=FakeTransport(),
        budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
        **options,
    )


def test_an_allowance_below_one_attempt_admits_no_draft_though_it_is_not_spent():
    """Admission refuses an attempt that would cross the ceiling, so a remainder above zero but
    below what one attempt reserves would start a draft that ends at its first call."""
    from decimal import Decimal

    from exulanica.api.kind_drafts import allowance_refusal, attempt_floor_usd
    from exulanica.models.spending import SpendingRefused
    from exulanica.spending.status import SpendingRefusals

    client = _client()
    [(provider, floor)] = attempt_floor_usd(client).items()
    spec = load_manifest()[Role.KIND_DRAFTER].primary
    # The floor is the answer bound and the instructions at the model's prices, above the answer
    # bound alone.
    answer = load_manifest()[Role.KIND_DRAFTER].max_tokens.value
    assert floor > client.budget.estimate_usd(spec, max_tokens=answer) > 0
    below = SpendingRefusals({provider: None}, {provider: floor - Decimal("0.0001")})
    refused = allowance_refusal(below, client)
    assert (refused.reason, refused.requested) == ("spending_limit_reached", str(floor))
    assert allowance_refusal(SpendingRefusals({provider: None}, {provider: floor}), client) is None
    spent = SpendingRefused("spending_revoked", scope="workspace")
    assert allowance_refusal(SpendingRefusals({provider: spent}), client) is spent
    assert allowance_refusal(None, client) is None


def test_a_draft_s_deadline_is_its_client_s_longest_call_and_ends_it_when_passed():
    # A client that retries takes longer than the role's one timeout, and its draft is given it.
    client = _client(max_attempts=3)
    longest = client.worst_case_seconds(Role.KIND_DRAFTER)
    assert longest > load_manifest()[Role.KIND_DRAFTER].timeout_seconds
    assert draft_deadline_seconds(client) == DRAFT_ATTEMPTS * (longest + CHECK_SECONDS)
    clock = _Clock()
    drafts = KindDrafts(clock=clock, deadline_seconds=lambda: 10_000.0)
    release = threading.Event()
    held = drafts.start(HERE, ACTOR, "a farm", _held(release), deadline=100.0)
    clock.now += 100 + 120
    assert drafts.read(HERE, ACTOR, held.draft_id).state == "drafting"
    clock.now += 1
    assert drafts.read(HERE, ACTOR, held.draft_id).state == "refused"
    release.set()
