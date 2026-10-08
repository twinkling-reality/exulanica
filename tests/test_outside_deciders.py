"""An outside program deciding for a subject, through the one decision path, replayed without it.

A decider is the routine, a model, the world's owner or an outside program deciding under a grant
the owner issued (:mod:`exulanica.world.deciders`). What is shown here, with no database:

*   a descriptor is exactly one of the four shapes, and a first choice's ``model`` reads as the
    routine or the model it names;
*   a request records an outside program in its one shape and a receipt its answer in its own,
    with no cost and no free text, and an answer is bound to the program and grant it was asked;
*   a run whose subject an outside program decides for plays through the same request, receipt and
    minute loop as a model's, and replays from what it stored without the program;
*   the registry reads a role's choices at the profile a new choice records and every earlier
    version of it, and nothing later;
*   a request an outside program did not answer ends for an outside reason, and an accepted
    answer always carries the program's record;
*   the host holds every door to its time and its checks: a late, failing or malformed statement
    or answer costs its own subject alone, a door that hangs is not waited for, and no text of a
    request that would carry a saved name is sent.
"""

from __future__ import annotations

import copy
import hashlib
import threading
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from exulanica.api.decision_host import (
    DecisionHost,
    OutsideAsk,
    outside_context_sendable,
    without_named_lines,
)
from exulanica.canonical import canonical_json
from exulanica.epistemics.saved_names import SavedName
from exulanica.world.deciders import (
    EXTERNAL_REASONS,
    DeciderRefused,
    check_external_config,
    check_external_record,
    decided_from_outside,
    decider,
    model_of,
    of_model,
    receipt_from_outside,
)
from exulanica.world.decision_roles import GENERIC_REASONS, decision_roles, load_decision_roles
from exulanica.world.role_decisions import (
    PROVIDER_RECORD,
    play_minutes,
    replay_minutes,
    role_receipt,
    role_request,
    validate_role_receipt,
)

from test_decision_roles import BRANCH, FIXTURES, PACKAGE, SEED

GRANT = uuid.UUID("3a2b1c0d-9e8f-4a7b-8c6d-5e4f3a2b1c0d")
MAPPING = "b" * 64
MINUTES = 40


def _config(contract: Any) -> dict[str, Any]:
    return {
        "kind": "external",
        "bridge": "luanti",
        "grant_id": str(GRANT),
        "grant_seq": 3,
        "mapping_sha256": MAPPING,
        "contract": contract.binding(),
        "deadline_ms": 2500,
    }


def _record(answer: bytes) -> dict[str, Any]:
    return {
        "kind": "external",
        "bridge": "luanti",
        "adapter_version": "0.1.0",
        "grant_id": str(GRANT),
        "grant_seq": 3,
        "mapping_sha256": MAPPING,
        "answer_sha256": hashlib.sha256(answer).hexdigest(),
        "latency_ms": 12,
        "source_ref_sha256": None,
    }


class _Program:
    """An outside program behind its door: it answers every request with the last option it was
    offered, and keeps what it was sent."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            self.sent.append(request)
            option = request["context"]["options"][-1]
            frame = canonical_json({"request_id": request["request_id"], "label": option["label"]})
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": _record(frame),
                }
            )
        return results


def _run() -> dict[str, Any]:
    import decision_role_fixtures.junction_signal as adapter

    registry = load_decision_roles(FIXTURES, adapters=PACKAGE)
    role = registry.role("junction_signal")
    contract = role.contract()
    config = _config(contract)

    def play(asking):
        return play_minutes(
            [role],
            role,
            start=adapter.genesis(BRANCH, 3),
            sources=[adapter.source(BRANCH)],
            seed=SEED,
            ticks=MINUTES,
            step=adapter.step,
            config_for=lambda _subject: config,
            request_id_for=lambda subject, tick: uuid.uuid5(
                BRANCH, f"{role.subject}-decision:{subject}:{tick}"
            ),
            asking=asking,
            seam=lambda _state, _due: {},
        )

    program = _Program()
    played = play(program)
    return {"role": role, "played": played, "program": program, "play": play}


def test_an_outside_program_decides_through_the_one_path_and_its_run_replays_without_it():
    run = _run()
    role, played, program = run["role"], run["played"], run["program"]
    assert played.requests and len(played.receipts) == len(played.requests)
    for request, receipt in zip(played.requests, played.receipts, strict=True):
        assert request["provider_config"]["kind"] == "external"
        assert receipt["provider"]["kind"] == "external"
        assert receipt["status"] == "accepted"
        validate_role_receipt(role, receipt, request)
    # What the program was sent is what a model reads: the sealed request, its context with it.
    assert program.sent == played.requests
    # Its answers changed the world: the minute applied them as it applies a model's.
    assert any(event["disposition"] == "applied" for event in played.events)
    # Replay rebuilds every request, receipt and minute from what was stored, with no program.
    asked = len(program.sent)
    stored = list(zip(played.requests, played.receipts, strict=True))
    replayed = replay_minutes(stored, minute_digests=played.minute_digests, play=run["play"])
    assert replayed.receipts == played.receipts
    assert replayed.minute_digests == played.minute_digests
    assert len(program.sent) == asked


def _stored_pair() -> tuple[Any, dict[str, Any], dict[str, Any]]:
    run = _run()
    return run["role"], run["played"].requests[0], run["played"].receipts[0]


def _resealed(role, request, receipt, provider):
    """``receipt`` with another ``provider``, sealed as a receipt is, so only the checks of what
    it records can refuse it, never its digest."""
    result = {key: receipt[key] for key in ("status", "reason", "proposal")}
    return role_receipt(role, request, receipt["decision_seq"], {**result, "provider": provider})


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"grant_id": str(uuid.UUID(int=7))}, id="another-grant"),
        pytest.param({"grant_seq": 4}, id="another-grant-revision"),
        pytest.param({"bridge": "zero_ad"}, id="another-bridge"),
        pytest.param({"mapping_sha256": "c" * 64}, id="another-mapping"),
        pytest.param({"source_ref_sha256": "player-name"}, id="free-text-correlation"),
        pytest.param({"adapter_version": "1.0 build by Someone"}, id="text-as-version"),
        pytest.param({"adapter_version": "alex.smith"}, id="a-name-as-version"),
        pytest.param({"adapter_version": "0.1.0-alex"}, id="a-name-after-a-version"),
        pytest.param({"latency_ms": -1}, id="negative-latency"),
        pytest.param({"answer_sha256": "d" * 63}, id="short-answer-digest"),
        pytest.param({"cost_usd": "0"}, id="a-cost-field"),
        pytest.param({"kind": None}, id="no-kind"),
    ],
)
def test_an_outside_answer_names_the_program_it_was_asked_in_its_own_fields_or_is_refused(change):
    role, request, receipt = _stored_pair()
    # The positive control: the stored receipt, and the same receipt sealed again, are read.
    validate_role_receipt(role, receipt, request)
    validate_role_receipt(role, _resealed(role, request, receipt, receipt["provider"]), request)
    provider = {**copy.deepcopy(receipt["provider"]), **change}
    if change == {"kind": None}:
        del provider["kind"]
    with pytest.raises(ValueError):
        validate_role_receipt(role, _resealed(role, request, receipt, provider), request)


def test_a_model_s_call_record_never_answers_an_outside_request():
    role, request, receipt = _stored_pair()
    as_model = {key: None for key in PROVIDER_RECORD}
    with pytest.raises(ValueError):
        validate_role_receipt(role, _resealed(role, request, receipt, as_model), request)


@pytest.mark.parametrize(
    "change",
    [
        pytest.param({"deadline_ms": 0}, id="no-time"),
        pytest.param({"deadline_ms": 30_001}, id="past-the-lease"),
        pytest.param({"grant_id": str(GRANT).upper()}, id="grant-not-canonical"),
        pytest.param({"bridge": "Luanti"}, id="bridge-not-a-key"),
        pytest.param({"note": "hello"}, id="an-extra-field"),
        pytest.param({"contract": {"sha256": "e" * 64}}, id="contract-half-named"),
    ],
)
def test_a_request_names_an_outside_program_in_its_one_shape_or_is_refused(change):
    import decision_role_fixtures.junction_signal as adapter

    registry = load_decision_roles(FIXTURES, adapters=PACKAGE)
    role = registry.role("junction_signal")
    contract = role.contract()
    state, source = adapter.genesis(BRANCH, 3), adapter.source(BRANCH)
    subject = next(iter(role.adapter.subjects(state)))

    def requested(config: dict[str, Any]):
        return role_request(
            role,
            state,
            source,
            subject,
            request_id=uuid.uuid4(),
            contract=contract,
            seed=SEED,
            provider_config=config,
        )

    good, _status = requested(_config(contract))
    assert good is not None and good["provider_config"]["kind"] == "external"
    with pytest.raises(ValueError):
        requested({**_config(contract), **change})


def test_a_descriptor_is_exactly_one_of_four_shapes():
    assert decider({"kind": "routine"}) == {"kind": "routine"}
    assert decider({"kind": "person"}) == {"kind": "person"}
    model = {"kind": "model", "provider": "nebius_token_factory", "model_id": "a/b"}
    assert decider(model) == model
    external = {"kind": "external", "bridge": "luanti", "grant_id": str(GRANT)}
    assert decider(external) == external
    for refused in (
        {},
        {"kind": "wait"},
        {"kind": "routine", "model_id": "a/b"},
        {"kind": "model", "provider": "nebius_token_factory"},
        {"kind": "model", "provider": "", "model_id": "a/b"},
        {"kind": "external", "bridge": "luanti"},
        {"kind": "external", "bridge": "luanti", "grant_id": "not-a-uuid"},
        {"kind": "external", "bridge": "luanti", "grant_id": str(GRANT), "name": "Alex"},
        {"kind": "person", "account": str(GRANT)},
    ):
        with pytest.raises(DeciderRefused):
            decider(refused)


def test_a_first_choice_s_model_reads_as_the_routine_or_the_model_it_names():
    assert of_model(None) == {"kind": "routine"}
    named = {"provider": "nebius_token_factory", "model_id": "a/b"}
    assert of_model(named) == {"kind": "model", **named}
    assert model_of(of_model(named)) == named
    assert model_of({"kind": "routine"}) is None
    assert model_of({"kind": "external", "bridge": "luanti", "grant_id": str(GRANT)}) is None


def test_a_receipt_says_an_outside_program_was_asked_by_its_record_or_its_reason():
    frame = canonical_json({"label": "x"})
    assert receipt_from_outside({"provider": _record(frame), "reason": "validated_choice"})
    model_call = {key: None for key in PROVIDER_RECORD}
    assert not receipt_from_outside({"provider": model_call, "reason": "validated_choice"})
    for reason in sorted(EXTERNAL_REASONS):
        assert receipt_from_outside({"provider": None, "reason": reason})
    assert not receipt_from_outside({"provider": None, "reason": "model_timed_out"})
    # Every reason only an outside ask gives is one every role records.
    assert EXTERNAL_REASONS <= GENERIC_REASONS


def test_the_one_shapes_refuse_what_they_do_not_state():
    contract = decision_roles().role("society_decision").contract()
    check_external_config(_config(contract))
    check_external_record(_record(b"{}"))
    with pytest.raises(DeciderRefused):
        check_external_config({**_config(contract), "provider": "nebius_token_factory"})
    with pytest.raises(DeciderRefused):
        check_external_record({**_record(b"{}"), "prompt_tokens": 0})


def test_somebody_who_came_from_outside_is_named_by_the_state_alone():
    crossing = {"arrival_id": "x", "bridge": "luanti", "grant_id": "g"}
    state = {
        "inhabitants": [
            {"id": "a", "came_by": "crossed", "crossing": crossing},
            {"id": "b", "came_by": "placed"},
            {"id": "c"},
            {"id": "d", "came_by": "crossed", "crossing": {**crossing, "decided_by": "program"}},
            # A visitor whose arrival said the world decides for it is decided for here.
            {"id": "e", "came_by": "crossed", "crossing": {**crossing, "decided_by": "world"}},
        ]
    }
    assert decided_from_outside(state, "a")
    assert not decided_from_outside(state, "b")
    assert not decided_from_outside(state, "c")
    assert decided_from_outside(state, "d")
    assert not decided_from_outside(state, "e")
    assert not decided_from_outside(state, "nobody")


def test_a_role_reads_its_choices_at_its_profile_and_every_earlier_version_of_it():
    registry = decision_roles()
    person = registry.role("society_decision")
    assert person.choice_profile == "exulanica.society-model-choice/v2"
    assert person.reads_choice("exulanica.society-model-choice/v1")
    assert person.reads_choice("exulanica.society-model-choice/v2")
    assert not person.reads_choice("exulanica.society-model-choice/v3")
    assert not person.reads_choice("exulanica.society-model-choice/v01")
    assert not person.reads_choice("exulanica.junction-signal-model-choice/v1")
    assert registry.for_choice("exulanica.society-model-choice/v1") is person
    assert registry.for_choice("exulanica.society-model-choice/v2") is person
    assert registry.for_choice("exulanica.society-model-choice/v3") is None


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            {"status": "unavailable", "reason": "unanswered_in_its_minute"}, id="a-model-s-reason"
        ),
        pytest.param({"status": "unavailable", "reason": "model_timed_out"}, id="a-model-timeout"),
        pytest.param({"status": "stale", "reason": "decision_context_changed"}, id="stale-unasked"),
        pytest.param({"status": "accepted", "reason": "validated_choice"}, id="accepted-no-record"),
    ],
)
def test_an_outside_request_never_answered_ends_for_an_outside_reason(result):
    role, request, receipt = _stored_pair()
    proposal = receipt["proposal"] if result["status"] == "accepted" else None

    def sealed(reason: str, status: str = "unavailable", offered: Any = None) -> dict[str, Any]:
        unanswered = {"status": status, "reason": reason, "proposal": offered, "provider": None}
        return role_receipt(role, request, receipt["decision_seq"], unanswered)

    # The positive control: no answer, for a reason only an outside ask gives.
    for reason in sorted(EXTERNAL_REASONS):
        validate_role_receipt(role, sealed(reason), request)
    with pytest.raises(ValueError):
        validate_role_receipt(role, sealed(result["reason"], result["status"], proposal), request)


def test_no_text_of_a_context_carrying_a_saved_name_is_sent_outside():
    ana = SavedName(uuid.UUID(int=1), "person", "Ana Lopez")
    context = {
        "options": [{"kind": "target", "label": "going to the well, 20 m away"}],
        "situation": {"last_activity": "talking with Ana Lopez by the gate", "role": "baker"},
    }
    # The positive control: nothing saved, or another name, sends the context as it is.
    assert outside_context_sendable((), context)
    assert outside_context_sendable((SavedName(uuid.UUID(int=2), "person", "Bo"),), context)
    assert not outside_context_sendable((ana,), context)
    for where in (
        {"options": [{"kind": "target", "label": "going to Ana Lopez's house"}]},
        {"notes": ["first", {"deep": ["Ana Lopez"]}]},
        {"Ana Lopez": 1},
    ):
        assert not outside_context_sendable((ana,), where)


class _Door:
    """A door the host asks with no database: each subject's statement and answer is scripted."""

    def __init__(self, answers=None, statements=None) -> None:
        self.answers = answers or {}
        self.statements = statements or {}
        self.released = threading.Event()

    def configuration(self, workspace_id, world_id, subject_id, decider):
        stated = self.statements[subject_id]
        if stated == "raise":
            raise RuntimeError("no record of the grant")
        if stated == "hang":
            self.released.wait(5)
        told = {
            "kind": "external",
            "bridge": decider["bridge"],
            "grant_id": decider["grant_id"],
            "grant_seq": 3,
            "mapping_sha256": MAPPING,
            "deadline_ms": 2500,
        }
        if stated == "malformed":
            del told["grant_seq"]
        return told, None

    def answer(self, workspace_id, world_id, request, ends_at):
        script = self.answers[request["request_id"]]
        if script == "raise":
            raise RuntimeError("the program went away")
        if script == "hang":
            self.released.wait(5)
            script = "good"
        options = request["context"]["options"]
        option = options[-1]
        frame = canonical_json({"label": option["label"]})
        good = {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": _record(frame),
        }
        broken = {
            "good": good,
            "extra-key": {**good, "note": "hello"},
            "not-offered": {
                **good,
                "proposal": {"label": "fly away", "option": {**option, "label": "fly away"}},
            },
            "another-grant": {
                **good,
                "provider": {**good["provider"], "grant_id": str(uuid.UUID(int=7))},
            },
            "accepted-no-record": {**good, "provider": None},
            "stale": {**good, "status": "stale", "proposal": None},
            "a-model-s-reason": {
                "status": "unavailable",
                "reason": "model_timed_out",
                "proposal": None,
                "provider": None,
            },
        }
        return copy.deepcopy(broken[script])


def _host(door: _Door) -> DecisionHost:
    """The host with nothing but a door: what these tests ask of it reads nothing else."""
    return DecisionHost(
        database=None,  # type: ignore[arg-type]
        runtime=None,  # type: ignore[arg-type]
        client=None,
        workspaces=frozenset(),
        policy_for=lambda _workspace: pytest.fail("no model is asked here"),
        manifest=None,  # type: ignore[arg-type]
        manifest_sha256="a" * 64,
        external=door,
    )


_CLAIM = SimpleNamespace(workspace_id=uuid.UUID(int=4), world_id="w")


def _outside_asks(count: int, deadline_ms: int = 300) -> tuple[Any, list[OutsideAsk]]:
    run = _run()
    role = run["role"]
    asks = [
        OutsideAsk(role, request, deadline_ms, time.monotonic() + 10)
        for request in run["played"].requests[:count]
    ]
    assert len(asks) == count
    return role, asks


@pytest.mark.parametrize(
    "script",
    [
        "extra-key",
        "not-offered",
        "another-grant",
        "accepted-no-record",
        "stale",
        "a-model-s-reason",
    ],
)
def test_an_outside_answer_a_receipt_may_not_record_costs_its_own_subject_alone(script):
    _role, (first, second) = _outside_asks(2)
    door = _Door(
        answers={first.request["request_id"]: script, second.request["request_id"]: "good"}
    )
    [group] = _host(door)._asked_by_every_role(None, [], _CLAIM, [([first, second], [])])
    by_request = {str(request_id): result for request_id, result in group}
    assert by_request[first.request["request_id"]] == {
        "status": "unavailable",
        "reason": "decider_disconnected",
        "proposal": None,
        "provider": None,
    }
    # The positive control: the other subject's answer, in the same minute, is kept as given.
    kept = by_request[second.request["request_id"]]
    assert (kept["status"], kept["provider"]["kind"]) == ("accepted", "external")


def test_a_door_that_hangs_or_fails_is_not_waited_for_and_costs_its_own_subject_alone():
    _role, (hung, failed, good) = _outside_asks(3, deadline_ms=200)
    door = _Door(
        answers={
            hung.request["request_id"]: "hang",
            failed.request["request_id"]: "raise",
            good.request["request_id"]: "good",
        }
    )
    started = time.monotonic()
    try:
        [group] = _host(door)._asked_by_every_role(None, [], _CLAIM, [([hung, failed, good], [])])
    finally:
        elapsed = time.monotonic() - started
        door.released.set()
    by_request = {str(request_id): result for request_id, result in group}
    assert by_request[hung.request["request_id"]]["reason"] == "no_answer_in_time"
    assert by_request[failed.request["request_id"]]["reason"] == "decider_disconnected"
    assert by_request[good.request["request_id"]]["status"] == "accepted"
    # The host stopped waiting at the door's deadline, not when the door let go.
    assert elapsed < 2, elapsed


def test_an_answer_that_comes_after_its_end_is_no_answer_in_time():
    _role, (asked,) = _outside_asks(1)
    door = _Door(answers={asked.request["request_id"]: "good"})
    host = _host(door)
    assert host._outside_answer(_CLAIM, asked, time.monotonic() + 5)["status"] == "accepted"
    assert host._outside_answer(_CLAIM, asked, time.monotonic() - 1)["reason"] == (
        "no_answer_in_time"
    )

    class _Slow(_Door):
        def answer(self, workspace_id, world_id, request, ends_at):
            time.sleep(0.15)
            return super().answer(workspace_id, world_id, request, ends_at)

    slow = _Slow(answers={asked.request["request_id"]: "good"})
    late = _host(slow)._outside_answer(_CLAIM, asked, time.monotonic() + 0.05)
    assert late["reason"] == "no_answer_in_time" and late["provider"] is None


def test_a_door_s_statement_that_fails_or_comes_late_leaves_its_own_subject_unasked():
    role = decision_roles().role("society_decision")
    contract = role.contract()
    described = {"kind": "external", "bridge": "luanti", "grant_id": str(GRANT)}
    subjects = ["a", "b", "c", "d"]
    door = _Door(statements={"a": "raise", "b": "malformed", "c": "hang", "d": "good"})
    started = time.monotonic()
    try:
        stated = _host(door)._stated(
            _CLAIM,
            role,
            contract,
            subjects,
            {subject: {"decider": described} for subject in subjects},
            time.monotonic() + 0.3,
        )
    finally:
        elapsed = time.monotonic() - started
        door.released.set()
    assert sorted(stated) == ["d"]
    config, refusal = stated["d"]
    assert refusal is None and config["contract"] == contract.binding()
    assert elapsed < 2, elapsed


def test_an_outside_program_is_never_shown_a_heard_line_carrying_a_saved_name():
    heard = [
        {"from": "the villager (person 1)", "to_you": True, "line": "Good morning.", "tick": 3},
        {"from": "the villager (person 2)", "to_you": False, "line": "Ask Hazel.", "tick": 4},
        {"from": "the knight (person 9)", "to_you": False, "line": "Hello.", "tick": 5},
    ]
    context = {"options": [], "heard": heard}
    hazel = SavedName(uuid.UUID(int=3), "person", "Hazel Moss")
    knight = SavedName(uuid.UUID(int=4), "person", "Knight Errant")
    kept = without_named_lines((hazel,))(dict(context))
    assert [line["line"] for line in kept["heard"]] == ["Good morning.", "Hello."]
    # Who said it is screened too: a saved name matching a speaker's words leaves that line out.
    kept = without_named_lines((knight,))(dict(context))
    assert [line["line"] for line in kept["heard"]] == ["Good morning.", "Ask Hazel."]
    # The positive control: with nothing saved that any of it carries, everything is shown.
    assert without_named_lines((SavedName(uuid.UUID(int=5), "person", "Bo"),))(context) == context
