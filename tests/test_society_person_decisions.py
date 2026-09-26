"""A person in the small square decides by the model their world's owner chose, or by the routine.

Pure: the small square is composed and advanced in memory exactly as a step advances it
(``living_square_support``), a model is a scripted transport behind the real client, and a
decision is the receipt the host would store. What is shown:

*   the options a person is offered are the routine's own choice, labelled by what they are and
    ordered by a seed, and never carry anything but catalog words and numbers;
*   an applied choice is the planner's goal with the model's own reason code, and a wait is a wait;
*   with no receipt a minute is exactly the minute it always was;
*   a receipt that is stale, superseded or no longer holds changes nothing, by name;
*   an answer that is never one of the options is refused, asked once more, and handed to the
    routine with the reason, and every attempt is on the receipt.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.api.society_person_decisions import PersonAsk, answer_tokens, ask_person
from exulanica.models.budget import BudgetGuard
from exulanica.models.choice import ChoiceRequest
from exulanica.models.client import ModelClient
from exulanica.models.manifest import MANIFEST_PATH, AnsweringMechanism, parse_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_decision_contract import (
    DECISION_REASONS,
    INSTRUCTION,
    at_choice_point,
    choice_options,
    choice_request,
    decision_context,
    decision_contract,
    decision_messages,
)
from exulanica.world.society_decisions import (
    PERSON_REQUEST_PROFILE,
    receipt_for,
    seal,
    validate_decision_receipt,
)
from exulanica.world.society_model_decisions import (
    DECISION_EVENT_KIND,
    append_decision_events,
    model_goal_policies,
)
from exulanica.world.society_planner import (
    advance_purposeful_society,
    held_nodes,
    initial_purposeful_society,
)
from exulanica.world.society_presence import change_presence, presence_request

import living_square_support as square
from model_fakes import FakeTransport, RecordingPolicy, chat_body

SEED = square.DEVELOPMENT_SEEDS[0]
PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"


def _world():
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(
        square.SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    return state, document


def _deciding(state, document, contract):
    """The people who choose in the coming minute and have somewhere to go, with their options."""
    return {
        person["id"]: options
        for person in state["inhabitants"]
        if (options := choice_options(state, document, person["id"], contract, seed=SEED))
    }


def _minute_with_choices(minutes: int = 40):
    """A state of the square at which somebody is choosing, and what each chooser is offered."""
    state, document = _world()
    contract = decision_contract()
    for _ in range(minutes):
        offered = _deciding(state, document, contract)
        if offered:
            return state, document, contract, offered
        state, _ = advance_purposeful_society(state, SEED, [document])
    raise AssertionError("nobody in the small square chose in forty minutes")


def _request(state, document, subject, options, *, model="example/model"):
    context = decision_context(state, document, subject, options)
    return seal(
        {
            "profile": PERSON_REQUEST_PROFILE,
            "request_id": str(uuid.uuid5(square.SOCIETY, f"{subject}:{state['tick']}")),
            "subject_id": subject,
            "branch_id": state["branch_id"],
            "base_tick": state["tick"],
            "base_state_sha256": society_state_sha256(state),
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": {
                "provider": "example_provider",
                "model_id": model,
                "mechanism": "tool_call",
                "choice_seq": 1,
                "manifest_sha256": "a" * 64,
                "prompt_version": "society-person-choice/v1",
                "contract": decision_contract().binding(),
                "deadline_ms": 20000,
            },
        }
    )


def _provider(model="example/model"):
    return {
        "provider": "example_provider",
        "model_id": model,
        "served_model_id": model,
        "mechanism": "tool_call",
        "prompt_version": "society-person-choice/v1",
        "messages_sha256": "b" * 64,
        "answers_asked": 1,
        "calls": [],
        "prompt_tokens": 300,
        "completion_tokens": 40,
        "cost_usd": "0.00002760",
        "cost_known": True,
        "latency_ms": 900,
    }


def _receipt(request, sequence, label):
    option = next(o for o in request["context"]["options"] if o["label"] == label)
    receipt = receipt_for(
        request,
        sequence,
        {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": label, "option": option},
            "provider": _provider(),
        },
    )
    validate_decision_receipt(receipt, request)
    return receipt


def _goal_of(state, subject):
    return next(p for p in state["inhabitants"] if p["id"] == subject)


# -- what a person is offered ---------------------------------------------------------------------


def test_the_offered_options_are_the_routines_own_choice_labelled_by_what_they_are():
    state, document, contract, offered = _minute_with_choices()
    for subject, options in offered.items():
        labels = [option.label for option in options]
        assert len(labels) == len(set(labels))
        assert labels.count(contract.words["wait"]) == 1
        assert 2 <= len(options) <= contract.value("options_maximum")
        # Built as the one choice a model answers: every label is product vocabulary.
        ChoiceRequest(description="x", options=tuple(labels))
        for option in options:
            if option.kind == "target":
                assert option.label.endswith(" m away") or " m away (" in option.label
                assert option.target_id in {t["target_id"] for t in document["targets"]}
        # The same person at the same minute reads the same order; the order is the seed's.
        again = choice_options(state, document, subject, contract, seed=SEED)
        assert [o.label for o in again] == labels
        # A choice point is the planner's own.
        assert at_choice_point(_goal_of(state, subject))


def test_a_person_blocked_on_the_way_keeps_their_goal_and_is_not_asked():
    """The routine chooses at no goal or a completed action. Blocked on the way to a goal, a
    person keeps it, and the routine does not choose for them, so no model is asked there either."""
    state, document = _world()
    for _ in range(40):
        walking = next(
            (p for p in state["inhabitants"] if p["goal"] and p["action"]["status"] == "active"),
            None,
        )
        if walking is not None:
            break
        state, _ = advance_purposeful_society(state, SEED, [document])
    else:
        raise AssertionError("nobody in the small square set off in forty minutes")
    blocked = copy.deepcopy(state)
    person = _goal_of(blocked, walking["id"])
    person["action"] = {
        "kind": "idle",
        "status": "blocked",
        "target_id": person["goal"]["target_id"],
        "remaining_ticks": 0,
        "reason": "known_target_unreachable",
    }
    assert not at_choice_point(person)
    # The positive control: the same person with the action completed is at a choice point.
    assert at_choice_point({**person, "action": {**person["action"], "status": "completed"}})
    after, _ = advance_purposeful_society(blocked, SEED, [document])
    assert _goal_of(after, walking["id"])["goal"] == person["goal"]


def test_the_order_is_shuffled_by_the_seed_not_sorted():
    state, document, contract, offered = _minute_with_choices()
    orders = {
        tuple(o.label for o in choice_options(state, document, subject, contract, seed=seed))
        for subject in offered
        for seed in square.DEVELOPMENT_SEEDS[:8]
    }
    assert len(orders) > len(offered), "the seed never moves the order"


def test_the_messages_carry_the_options_and_nothing_of_anybody_else():
    state, document, _contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    context = decision_context(state, document, subject, options)
    messages = decision_messages(context, AnsweringMechanism.TOOL_CALL)
    text = messages[1]["content"]
    for option in options:
        assert f"- {option.label}" in text
    for person in state["inhabitants"]:
        assert person["display_name"] not in text
    assert choice_request(context).options == tuple(o.label for o in options)


# -- what a receipt does to a minute ---------------------------------------------------------------


def test_with_no_receipt_every_minute_is_the_minute_it_always_was():
    state, document = _world()
    plain = state
    for _ in range(60):
        policies, decided = model_goal_policies(state, document, [], {})
        assert policies == {} and decided == ()
        state, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
        after = append_decision_events(plain, state, document, [], decided, events)
        plain, plain_events = advance_purposeful_society(plain, SEED, [document])
        assert state == plain
        assert after == plain_events


def test_an_applied_choice_is_the_planners_goal_with_the_models_own_reason():
    state, document, _, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    target = next(o for o in options if o.kind == "target")
    request = _request(state, document, subject, options)
    receipt = _receipt(request, 1, target.label)
    policies, decided = model_goal_policies(state, document, [receipt], {})
    assert [(d.disposition, d.reason) for d in decided] == [("applied", "validated_choice")]
    after, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    person = _goal_of(after, subject)
    assert person["goal"]["target_id"] == target.target_id
    assert person["goal"]["reason"] == "chosen_by_their_model"
    events = append_decision_events(state, after, document, [receipt], decided, events)
    (event,) = [e for e in events if e.kind == DECISION_EVENT_KIND]
    assert event.document["disposition"] == "applied"
    assert event.document["chose"] == target.label
    assert event.document["model"] == {"provider": "example_provider", "model_id": "example/model"}
    assert event.document["origin"] == "model"


def test_a_chosen_wait_is_a_wait():
    state, document, contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    receipt = _receipt(_request(state, document, subject, options), 1, contract.words["wait"])
    policies, _decided = model_goal_policies(state, document, [receipt], {})
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    person = _goal_of(after, subject)
    assert person["action"]["status"] == "blocked"
    assert person["action"]["reason"] == "validated_model_wait"


def test_a_receipt_asked_over_another_state_is_stale():
    state, document, _, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    receipt = _receipt(_request(state, document, subject, options), 1, options[0].label)
    later, _ = advance_purposeful_society(state, SEED, [document])
    _, decided = model_goal_policies(later, document, [receipt], {})
    assert [(d.disposition, d.reason) for d in decided] == [("stale", "decision_context_changed")]


def test_a_persons_own_request_comes_before_their_models_choice():
    state, document, _, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    target = next(o for o in options if o.kind == "target")
    receipt = _receipt(_request(state, document, subject, options), 1, target.label)
    directed = {
        subject: {"allowed_target_ids": [target.target_id], "preferred_target_id": target.target_id}
    }
    policies, decided = model_goal_policies(state, document, [receipt], directed)
    assert policies[subject] == directed[subject]
    assert [(d.disposition, d.reason) for d in decided] == [("superseded", "person_asked_directly")]


def _shared_place():
    """A minute at which two choosers are offered one place, and the free spots it has left.

    Searched over the development seeds and their first hundred minutes; the search failing is a
    test failure, never a skip, because the case is what this test is about.
    """
    contract = decision_contract()
    for seed in square.DEVELOPMENT_SEEDS:
        document = square.compose(square.square_objects())
        targets = {t["target_id"]: t for t in document["targets"]}
        state = initial_purposeful_society(
            square.SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
        )
        for _ in range(100):
            offered = {
                person["id"]: options
                for person in state["inhabitants"]
                if (options := choice_options(state, document, person["id"], contract, seed=seed))
            }
            for target_id, target in sorted(targets.items()):
                choosers = sorted(
                    (subject, next(o for o in options if o.target_id == target_id), options)
                    for subject, options in offered.items()
                    if any(o.target_id == target_id for o in options)
                )
                if len(choosers) < 2:
                    continue
                first, second = choosers[:2]
                mover = _goal_of(state, first[0])
                held = held_nodes(list(state["inhabitants"]), mover)
                free = [node for node in target["place_node_ids"] if node not in held]
                others = [
                    p["id"] for p in state["inhabitants"] if p["id"] not in (first[0], second[0])
                ]
                if free and len(free) - 1 <= len(others):
                    return state, document, target_id, free, others, first, second
            state, _ = advance_purposeful_society(state, seed, [document])
    raise AssertionError("no minute offers one place to two people at once")


def test_two_choices_never_share_the_last_free_spot_of_a_place():
    state, document, target_id, free, others, first, second = _shared_place()
    # Every free spot but one is promised first, as direct requests' places are before a minute.
    directed = {
        holder: {
            "allowed_target_ids": [target_id],
            "preferred_target_id": target_id,
            "place_node_id": node,
        }
        for holder, node in zip(others, free[1:], strict=False)
    }
    (subject, option, options), (other, same, theirs) = first, second
    one = _receipt(_request(state, document, subject, options), 1, option.label)
    two = _receipt(_request(state, document, other, theirs), 2, same.label)
    policies, decided = model_goal_policies(state, document, [one, two], directed)
    assert [(d.disposition, d.reason) for d in decided] == [
        ("applied", "validated_choice"),
        ("rejected", "place_taken_this_minute"),
    ]
    assert policies[subject]["place_node_id"] == free[0]
    assert other not in policies


def test_an_unaccepted_receipt_leaves_the_turn_to_the_routine_and_keeps_its_status():
    state, document, _, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    request = _request(state, document, subject, options)
    receipt = receipt_for(
        request,
        1,
        {"status": "unavailable", "reason": "model_timed_out", "proposal": None, "provider": None},
    )
    validate_decision_receipt(receipt, request)
    policies, decided = model_goal_policies(state, document, [receipt], {})
    assert policies == {}
    assert [(d.disposition, d.reason) for d in decided] == [("unavailable", "model_timed_out")]
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    plain, _ = advance_purposeful_society(state, SEED, [document])
    assert after == plain


@pytest.mark.parametrize(
    ("status", "reason", "closed"),
    [
        ("unavailable", "unanswered_in_its_minute", ("unavailable", "unanswered_in_its_minute")),
        ("accepted", "validated_choice", ("stale", "decision_context_changed")),
    ],
    ids=["unanswered", "accepted"],
)
def test_a_receipt_for_someone_sent_away_is_closed_by_their_id_alone(status, reason, closed):
    """A request closed after its minute can outlast its person: the world's owner may send
    everyone away once nothing is waiting. The minute that consumes its receipt closes it by the
    person's id, and moves nobody."""
    state, document, _contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    request = _request(state, document, subject, options)
    if status == "accepted":
        receipt = _receipt(request, 1, options[0].label)
    else:
        receipt = receipt_for(
            request, 1, {"status": status, "reason": reason, "proposal": None, "provider": None}
        )
        validate_decision_receipt(receipt, request)
    away = presence_request(
        state, request_id=uuid.uuid4(), requested_by=uuid.uuid4(), wanted="away"
    )
    gone, _ = change_presence(
        state, state["seed_sha256"], [document], away, population=AUTHORED_GROUND_POPULATION
    )
    assert gone["inhabitants"] == []
    policies, decided = model_goal_policies(gone, document, [receipt], {})
    assert policies == {}
    assert [(d.disposition, d.reason) for d in decided] == [closed]
    after, events = advance_purposeful_society(gone, SEED, [document], goal_policy=policies)
    appended = append_decision_events(gone, after, document, [receipt], decided, events)
    [event] = [e for e in appended if e.kind == DECISION_EVENT_KIND]
    assert event.subject_id == uuid.UUID(subject)
    assert event.document["summary"].startswith("Someone no longer here (simulated)")
    assert (event.document["goal"], event.document["position_mm"]) == (None, None)


# -- an answer that is not an option ---------------------------------------------------------------


def _offered_manifest():
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )
    document["models"][model_id]["answering"] = {"tool_call": PROBE_RECORD}
    return parse_manifest(document), model_id


def _tool_reply(action: str, model: str) -> HttpResponse:
    body = chat_body("", model=model, finish_reason="tool_calls")
    body["choices"][0]["message"]["content"] = None
    body["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "c",
            "type": "function",
            "function": {"name": "act", "arguments": json.dumps({"action": action})},
        }
    ]
    return HttpResponse(200, json.dumps(body))


def test_an_answer_never_offered_is_asked_once_more_then_left_to_the_routine_by_name():
    state, document, contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    manifest, model_id = _offered_manifest()
    request = _request(state, document, subject, options, model=model_id)
    transport = FakeTransport([_tool_reply("fly away", model_id), _tool_reply("sing", model_id)])
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    spec = manifest.spec(model_id)
    result = ask_person(
        client,
        PersonAsk(request, spec, AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + 20.0,
    )
    assert (result["status"], result["reason"]) == ("rejected", "answer_not_offered")
    assert result["proposal"] is None
    assert transport.call_count == contract.value("answer_attempts_maximum")
    provider = result["provider"]
    assert provider["answers_asked"] == contract.value("answer_attempts_maximum")
    assert [call["outcome"] for call in provider["calls"]] == ["reply_refused", "reply_refused"]
    assert provider["provider"] == spec.provider and provider["model_id"] == model_id
    # The retry tells the model why, in product words, and carries the same options.
    second = transport.requests[1]["payload"]["messages"]
    assert "not one of the offered actions" in second[-1]["content"]
    receipt = receipt_for(request, 1, result)
    validate_decision_receipt(receipt, request)
    policies, decided = model_goal_policies(state, document, [receipt], {})
    assert policies == {}
    assert [(d.disposition, d.reason) for d in decided] == [("rejected", "answer_not_offered")]
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    assert _goal_of(after, subject)["goal"] is None or (
        _goal_of(after, subject)["goal"]["reason"] != "chosen_by_their_model"
    )


def test_an_offered_answer_is_accepted_with_its_option_and_its_call():
    state, document, contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    manifest, model_id = _offered_manifest()
    request = _request(state, document, subject, options, model=model_id)
    label = options[-1].label
    transport = FakeTransport([_tool_reply(label, model_id)])
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    result = ask_person(
        client,
        PersonAsk(request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + 20.0,
    )
    assert (result["status"], result["reason"]) == ("accepted", "validated_choice")
    assert result["proposal"]["label"] == label
    assert [call["outcome"] for call in result["provider"]["calls"]] == ["completed"]
    assert result["provider"]["cost_known"] is True
    validate_decision_receipt(receipt_for(request, 1, result), request)
    # Asked with the model's own default bound, room for a reasoning model to reason first.
    spec = manifest.spec(model_id)
    sent = transport.requests[0]["payload"]["max_tokens"]
    assert sent == answer_tokens(spec) == max(spec.default_max_tokens, spec.min_max_tokens)


@pytest.mark.parametrize("left", [0.0, -1.0], ids=["now", "past"])
def test_an_ask_whose_time_has_run_out_sends_nothing_and_says_so(left):
    state, document, contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    manifest, model_id = _offered_manifest()
    request = _request(state, document, subject, options, model=model_id)
    transport = FakeTransport([_tool_reply(options[0].label, model_id)])
    guard = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=guard,
        policy=RecordingPolicy(),
    )
    result = ask_person(
        client,
        PersonAsk(request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + left,
    )
    assert (result["status"], result["reason"]) == ("unavailable", "no_time_to_ask")
    assert (result["proposal"], result["provider"]) == (None, None)
    assert transport.call_count == 0 and (guard.billed_calls, guard.held_calls) == (0, 0)
    validate_decision_receipt(receipt_for(request, 1, result), request)


def test_an_asks_bound_covers_every_ask_the_square_makes():
    """What the host decides a model's ask needs is at least what its calls reserve: both answers,
    the second carrying the retry's note, for every choice the square offers in its first hour."""
    from exulanica.api.society_person_decisions import _NOT_OFFERED, ask_bound_usd

    manifest, model_id = _offered_manifest()
    spec = manifest.spec(model_id)
    contract = decision_contract()
    budget = BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10)
    bound = ask_bound_usd(budget, spec, contract)
    state, document = _world()
    asked = 0
    for _ in range(60):
        for subject, options in _deciding(state, document, contract).items():
            context = decision_context(state, document, subject, options)
            for mechanism in (AnsweringMechanism.TOOL_CALL, AnsweringMechanism.JSON_SCHEMA):
                first = decision_messages(context, mechanism)
                second = [*first, {"role": "user", "content": _NOT_OFFERED}]
                reserved = sum(
                    budget.estimate_usd(
                        spec,
                        prompt_chars=sum(len(str(message)) for message in messages),
                        max_tokens=answer_tokens(spec) or 0,
                    )
                    for messages in (first, second)
                )
                assert reserved <= bound
                asked += 1
        state, _ = advance_purposeful_society(state, SEED, [document])
    # The positive control: asks were weighed, and the sizing this bound replaced, the
    # instruction alone with the answer's bound, falls short of a real ask.
    assert asked > 20
    instruction_alone = contract.value("answer_attempts_maximum") * budget.estimate_usd(
        spec, prompt_chars=len(INSTRUCTION), max_tokens=answer_tokens(spec) or 0
    )
    assert instruction_alone < reserved


class _AnswersLate(FakeTransport):
    """A model that answers off the offer, after the ask's time is up."""

    def post_json(self, url, *, headers, payload, timeout):
        time.sleep(0.2)
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


def test_an_answer_asked_once_more_with_no_time_left_sends_nothing_more_and_says_so():
    state, document, contract, offered = _minute_with_choices()
    subject, options = next(iter(offered.items()))
    manifest, model_id = _offered_manifest()
    request = _request(state, document, subject, options, model=model_id)
    transport = _AnswersLate([_tool_reply("fly away", model_id), _tool_reply("sing", model_id)])
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    result = ask_person(
        client,
        PersonAsk(request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + 0.1,
    )
    assert (result["status"], result["reason"]) == ("unavailable", "no_time_to_ask")
    assert transport.call_count == 1
    assert [call["outcome"] for call in result["provider"]["calls"]] == ["reply_refused"]
    validate_decision_receipt(receipt_for(request, 1, result), request)


def test_a_refusal_is_decided_on_money_spent_never_on_calls_under_way():
    """A call under way, the Companion's say, holds part of the budget until it is recorded. The
    host neither refuses for it nor lets a refusal come and go with it: once spending leaves too
    little, the refusal holds until the process restarts."""
    from exulanica.api.society_person_decisions import host_refusal, smallest_ask_usd
    from exulanica.models.manifest import Role, load_manifest
    from exulanica.models.usage import CallUsage

    manifest = load_manifest()
    contract = decision_contract()
    smallest = smallest_ask_usd(
        BudgetGuard(ceiling_usd=Decimal(1), max_calls=10), manifest, contract
    )
    assert smallest is not None
    spec = manifest[Role.REASONING_CHEAP].primary
    probe = BudgetGuard(ceiling_usd=Decimal(1), max_calls=10)
    chars = 3000
    while probe.estimate_usd(spec, prompt_chars=chars, max_tokens=2048) < 2 * smallest:
        chars *= 2
    guard = BudgetGuard(
        ceiling_usd=probe.estimate_usd(spec, prompt_chars=chars, max_tokens=2048) + smallest / 2,
        max_calls=10,
    )
    client = ModelClient(
        api_key="test-key-not-real", manifest=manifest, transport=FakeTransport([]), budget=guard
    )
    held = guard.reserve(spec, role=Role.REASONING_CHEAP, prompt_chars=chars, max_tokens=2048)
    # What calls under way hold leaves less than the smallest ask, and nothing is spent.
    assert guard.available_usd < smallest and guard.spent_usd == 0
    assert host_refusal(client, manifest, contract) is None
    guard.record(
        CallUsage.failed(
            role=Role.REASONING_CHEAP,
            spec=spec,
            reached_provider=True,
            timed_out=True,
            failure="charged at its reservation",
            usd_bound=held,
        ),
        released=held,
    )
    assert (guard.held_usd, guard.spent_usd) == (Decimal(0), held)
    assert host_refusal(client, manifest, contract) == "process_budget_spent"


def test_every_reason_a_person_decision_records_is_in_the_stated_set():
    from exulanica.api.society_person_decisions import _failure_reason
    from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT, PROVIDER_NOT_ADMITTED
    from exulanica.models.errors import (
        BudgetExceededError,
        ManifestError,
        ModelError,
        ModelUnavailableError,
        TransportError,
    )

    # Each failure names its own reason, not merely one the set holds: a spent process budget is
    # not a failed call, and a timeout is not an unavailable model.
    raised = {
        "process_budget_spent": BudgetExceededError("x", spent_usd=0, ceiling_usd=0),
        "model_no_longer_offered": ManifestError("x"),
        "model_call_failed": ModelError("x"),
        "model_unavailable": ModelUnavailableError("x", model_id="m", status_code=404),
        "model_timed_out": TransportError("x", timed_out=True),
    }
    assert {reason: _failure_reason(exc) for reason, exc in raised.items()} == {
        reason: reason for reason in raised
    }
    assert _failure_reason(TransportError("x")) == "model_call_failed"
    assert set(raised) <= DECISION_REASONS
    assert {PROVIDER_NOT_ADMITTED, PROVIDER_CREDENTIAL_ABSENT} <= DECISION_REASONS
