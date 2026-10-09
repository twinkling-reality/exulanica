"""A person asks one being of a society of things for a hands act, in memory.

A v2 request (``exulanica.society-action-request/v2``) is built by the function the actions route
builds requests with, checked against the hands acts the being is offered on the state the minute
starts from, and applied by the minute as a decider's chosen act is: the being waits within reach
or walks to the open node within reach, and the hands step does the act, recorded as asked. The
wait and the walk record a request's reasons (``validated_user_wait``,
``remembered_target_selected``), never a model's, and a stay or a blocked goal gives way to the
walk as it does to a request for a place. The tests drive the minute as the repository runs it
(requests, planner, request events, things phase) and read what the state and the events say.
"""

from __future__ import annotations

import copy
import math
import uuid

import pytest
from exulanica.abilities.registry import HANDS_FROM_OWN_SIDE
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import (
    ACTION_REQUEST_PROFILE,
    HANDS_REQUEST_PROFILE,
    ActionIntent,
    action_goal_policies,
    append_action_events,
    applied_hands,
    build_action_request,
    validate_action_request,
)
from exulanica.world.society_decision_contract import (
    DecisionOption,
    choice_options,
    decision_context,
    person_role,
)
from exulanica.world.society_decisions import receipt_for, seal, validate_decision_receipt
from exulanica.world.society_hands import hand_over_mm, walk_minutes_maximum
from exulanica.world.society_model_decisions import (
    DECISION_EVENT_KIND,
    append_decision_events,
    hands_goal_policy,
    model_goal_policies,
)
from exulanica.world.society_planner import (
    advance_purposeful_society,
    ends_on_request,
    routine_of,
)
from exulanica.world.society_things import (
    THING_REASONS,
    advance_things,
    initial_things_society,
    validate_things_state,
)

from things_society_support import SEED, SOCIETY, arrival, compose, reference, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: Within reach of the knight's standing node, as tests/test_society_hands.py places it.
SWORD = thing("sword", "sword", 2, 2_400, 2_600)
#: Far enough that the knight walks to an open node within reach first.
FAR_SWORD = thing("sword", "sword", 2, -3_000, 2_600)
POPULATION = 6
ASKER = uuid.UUID(int=0xA5)


def _society(*placed):
    document = compose(placed)
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    assert HANDS_FROM_OWN_SIDE in state["modules"]
    return state, document


def _knight(state):
    return next(p for p in state["inhabitants"] if p["placed_id"] == "knight")


def _thing(state, placed_id):
    return next(t for t in state["things"] if t["placed_id"] == placed_id)


def _ask(state, document, being, ability, thing_id, with_id=None):
    return build_action_request(
        state,
        document,
        request_id=uuid.uuid4(),
        requested_by=ASKER,
        subject_id=uuid.UUID(being["id"]),
        intent=ActionIntent(kind="hands", target_id=thing_id, ability=ability, with_id=with_id),
    )


def _minute(state, document, requests=()):
    """One minute as the repository runs a society of things with requests and no receipts."""
    requests = list(requests)
    policies, dispositions = action_goal_policies(state, document, requests)
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    events = append_action_events(state, planned, document, requests, dispositions, events)
    after, events, _ = advance_things(
        state, planned, SEED, document, events, (), asked=applied_hands(requests, dispositions)
    )
    return after, events, dispositions, policies


def test_a_person_asks_a_being_beside_a_thing_to_pick_it_up():
    state, document = _society(GATE, KNIGHT, SWORD)
    knight, sword = _knight(state), _thing(state, "sword")
    request = _ask(state, document, knight, "pick_up", sword["id"])

    assert request["profile"] == HANDS_REQUEST_PROFILE
    assert "target" not in request
    assert request["intent"] == {
        "kind": "hands",
        "ability": "pick_up",
        "thing_id": sword["id"],
        "with_id": None,
    }
    validate_action_request(request)
    after, events, dispositions, policies = _minute(state, document, [request])

    assert [(d.disposition, d.reason) for d in dispositions] == [("applied", "validated_user_act")]
    # Directed, so the being's decider's answer for this minute is set aside
    # (model_goal_policies' existing branch, person_asked_directly).
    assert knight["id"] in policies
    [asked] = [e for e in events if e.kind == "user_action_requested"]
    assert asked.document["target"] is None
    assert asked.document["act"] == {"ability": "pick_up", "thing_id": sword["id"], "with_id": None}
    [picked] = [e for e in events if e.kind == "picked_up"]
    assert picked.document["reason"] == "asked_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]
    # The being waits within reach that minute because the world's owner asked, never because a
    # model chose to wait (``validated_model_wait``).
    assert _knight(after)["action"]["reason"] == "validated_user_wait"
    assert _reasons(events, knight) == {"validated_user_wait"}
    validate_things_state(after)


def _reasons(events, being):
    """The reasons the planner's events for ``being`` record in a minute."""
    return {
        e.document["reason"]
        for e in events
        if str(e.subject_id) == being["id"] and e.kind not in NOT_THE_PLANNERS
    }


#: Events with reasons of their own: the hands step's, the request's and a decision's.
NOT_THE_PLANNERS = frozenset(
    {"picked_up", "put_down", "gave", "took", "hands_missed", "user_action_requested"}
    | {DECISION_EVENT_KIND}
)


def test_a_thing_farther_off_is_walked_to_and_picked_up_as_asked():
    state, document = _society(GATE, KNIGHT, FAR_SWORD)
    knight, sword = _knight(state), _thing(state, "sword")
    after, events, dispositions, policies = _minute(
        state, document, [_ask(state, document, knight, "pick_up", sword["id"])]
    )
    assert dispositions[0].disposition == "applied"
    assert "place_node_id" in policies[knight["id"]]
    # The walk records a request's reason, never the one a model's choice records: the question
    # path reads chosen_by_their_model events as a model's decisions.
    assert "remembered_target_selected" in _reasons(events, knight)
    assert "chosen_by_their_model" not in _reasons(events, knight)
    picked = [e for e in events if e.kind == "picked_up"]
    for _minutes in range(walk_minutes_maximum()):
        if picked:
            break
        # The asked act is kept, marked as asked, until the being stands within reach.
        assert _knight(after)["hands"]["asked"] is True
        after, events, _, _ = _minute(after, document)
        picked = [e for e in events if e.kind == "picked_up"]
    [done] = picked
    assert done.document["reason"] == "asked_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]


def test_a_being_asked_gives_what_it_holds_to_the_being_beside_it():
    other_knight = thing("knight-2", "knight", 1, 9_000, 3_000)
    state, document = _society(GATE, KNIGHT, other_knight, SWORD)
    knight, sword = _knight(state), _thing(state, "sword")
    held, _, _, _ = _minute(
        state, document, [_ask(state, document, knight, "pick_up", sword["id"])]
    )
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    here = _knight(held)["position_mm"]
    there = next(
        nodes[b]
        for e in document["navigation"]["edges"]
        for a, b in ((e["from_node_id"], e["to_node_id"]), (e["to_node_id"], e["from_node_id"]))
        if nodes[a] == here and math.dist(nodes[a], nodes[b]) == hand_over_mm(document)
    )
    beside = copy.deepcopy(held)
    other = next(p for p in beside["inhabitants"] if p["placed_id"] == "knight-2")
    other["position_mm"] = list(there)
    request = _ask(beside, document, _knight(beside), "give", sword["id"], with_id=other["id"])
    after, events, dispositions, _ = _minute(beside, document, [request])
    assert dispositions[0].disposition == "applied"
    [gave] = [e for e in events if e.kind == "gave"]
    assert gave.document["reason"] == "asked_to_give"
    assert _thing(after, "sword")["held_by"] == other["id"]


@pytest.mark.parametrize(
    ("ability", "placed", "reason"),
    [
        # Nothing in hand to put down.
        ("put_down", "sword", "act_not_offered"),
        # A well is not holdable.
        ("pick_up", "well", "act_not_offered"),
        # No such thing in the society.
        ("pick_up", None, "thing_gone"),
    ],
)
def test_an_act_the_being_is_not_offered_is_refused_by_name(ability, placed, reason):
    well = thing("well", "well", 2, -4_000, 2_000)
    state, document = _society(GATE, KNIGHT, SWORD, well)
    thing_id = str(uuid.UUID(int=77)) if placed is None else _thing(state, placed)["id"]
    with pytest.raises(ValueError, match=rf"^{reason}$"):
        _ask(state, document, _knight(state), ability, thing_id)


def test_giving_to_a_being_not_here_is_refused_as_gone():
    state, document = _society(GATE, KNIGHT, SWORD)
    held, _, _, _ = _minute(
        state,
        document,
        [_ask(state, document, _knight(state), "pick_up", _thing(state, "sword")["id"])],
    )
    with pytest.raises(ValueError, match=r"^thing_gone$"):
        _ask(
            held,
            document,
            _knight(held),
            "give",
            _thing(held, "sword")["id"],
            with_id=str(uuid.UUID(int=78)),
        )


def test_a_being_an_outside_program_decides_for_is_refused_by_name():
    state, document = _society(GATE, KNIGHT, SWORD)
    crossed = copy.deepcopy(state)
    being = _knight(crossed)
    being.update(
        came_by="crossed",
        placed_id=None,
        placed_at_mm=None,
        crossing={"arrival_id": "a", "bridge": "b", "grant_id": str(uuid.UUID(int=1))},
    )
    with pytest.raises(ValueError, match=r"^decided_from_outside$"):
        _ask(crossed, document, being, "pick_up", _thing(crossed, "sword")["id"])


def test_a_request_for_a_target_keeps_its_v1_shape():
    state, document = _society(GATE, KNIGHT, SWORD)
    target = next(t for t in document["targets"] if t["enabled"])
    request = build_action_request(
        state,
        document,
        request_id=uuid.UUID(int=5),
        requested_by=ASKER,
        subject_id=uuid.UUID(_knight(state)["id"]),
        intent=ActionIntent(kind="go_to", target_id=target["target_id"]),
    )
    expected = {
        "profile": ACTION_REQUEST_PROFILE,
        "request_id": str(uuid.UUID(int=5)),
        "requested_by": str(ASKER),
        "subject_id": _knight(state)["id"],
        "branch_id": state["branch_id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "intent": {"kind": "go_to", "target_id": target["target_id"]},
        "target": target,
    }
    assert {key: value for key, value in request.items() if key != "document_sha256"} == expected
    assert request["document_sha256"] == society_state_sha256(expected)


@pytest.mark.parametrize(
    "intent",
    [
        {"ability": "pick_up", "thing": "t", "with": None, "since": 0, "asked": False},
        {"ability": "pick_up", "thing": "t", "with": None, "since": 0, "by": "person"},
    ],
    ids=["asked-false", "another-key"],
)
def test_the_state_check_admits_asked_only_as_true(intent):
    state, _ = _society(GATE, KNIGHT, SWORD)
    good = copy.deepcopy(state)
    _knight(good)["hands"] = {
        "ability": "pick_up",
        "thing": "t",
        "with": None,
        "since": 0,
        "asked": True,
    }
    validate_things_state(good)
    _knight(state)["hands"] = intent
    with pytest.raises(ValueError, match="hands act"):
        validate_things_state(state)


def test_a_minute_with_a_hands_request_replays_to_the_same_bytes():
    state, document = _society(GATE, KNIGHT, FAR_SWORD)
    request = _ask(state, document, _knight(state), "pick_up", _thing(state, "sword")["id"])
    first, events_1, _, _ = _minute(copy.deepcopy(state), document, [request])
    again, events_2, _, _ = _minute(copy.deepcopy(state), document, [request])
    assert society_state_sha256(first) == society_state_sha256(again)
    assert [e.event_id for e in events_1] == [e.event_id for e in events_2]


def test_every_asked_reason_is_one_the_browser_has_words_for():
    assert {f"asked_to_{ability}" for ability in ("pick_up", "put_down", "give", "take")} <= (
        THING_REASONS
    )


def test_of_two_requests_for_one_being_in_a_minute_only_the_first_is_done():
    other_sword = thing("sword-2", "sword", 2, 2_400, 3_400)
    state, document = _society(GATE, KNIGHT, SWORD, other_sword)
    knight = _knight(state)
    first = _ask(state, document, knight, "pick_up", _thing(state, "sword")["id"])
    second = _ask(state, document, knight, "pick_up", _thing(state, "sword-2")["id"])
    after, _events, dispositions, _ = _minute(state, document, [first, second])
    assert [(d.disposition, d.reason) for d in dispositions] == [
        ("applied", "validated_user_act"),
        ("superseded", "subject_already_directed"),
    ]
    assert _thing(after, "sword")["held_by"] == knight["id"]
    assert _thing(after, "sword-2")["held_by"] is None


#: Swords about the square, so that where the knight stands one is likely a walk away.
WEST_SWORD = thing("sword-west", "sword", 2, -3_000, 2_600)
EAST_SWORD = thing("sword-east", "sword", 2, 9_000, 2_600)
SOUTH_SWORD = thing("sword-south", "sword", 2, -2_000, -6_000)
SWORDS = ("sword-west", "sword-east", "sword-south")


def _walked_to(state, document, being):
    """A request for a sword the being must walk to, and the minute that applies it."""
    for placed in SWORDS:
        try:
            request = _ask(state, document, being, "pick_up", _thing(state, placed)["id"])
        except ValueError:
            continue
        after, events, dispositions, policies = _minute(state, document, [request])
        if "place_node_id" in policies.get(being["id"], {}):
            return after, events, dispositions
    raise AssertionError("neither sword is a walk away from where the being stands")


def test_a_blocked_being_asked_for_an_act_walks_to_reach_it():
    """A blocked goal gives way to the asked walk, as it does to a request for a place."""
    state, document = _society(GATE, KNIGHT, WEST_SWORD, EAST_SWORD, SOUTH_SWORD)
    blocked = copy.deepcopy(state)
    knight = _knight(blocked)
    knight["goal"] = {"kind": "stand", "target_id": None, "reason": "standing_a_while"}
    knight["action"] = {
        "kind": "idle",
        "status": "blocked",
        "target_id": None,
        "remaining_ticks": 0,
        "reason": "no_room_to_wait",
    }
    after, events, dispositions = _walked_to(blocked, document, knight)
    assert [(d.disposition, d.reason) for d in dispositions] == [("applied", "validated_user_act")]
    assert _knight(after)["goal"]["reason"] == "remembered_target_selected"
    assert "remembered_target_selected" in _reasons(events, knight)


def test_a_being_standing_a_while_is_called_away_to_reach_what_it_is_asked_for():
    """A stay a request ends gives way to the asked walk in the minute it is applied."""
    state, document = _society(GATE, KNIGHT, WEST_SWORD, EAST_SWORD, SOUTH_SWORD)
    routine = routine_of(document)
    for _minutes in range(480):
        knight = _knight(state)
        if knight["action"]["kind"] == "stand" and ends_on_request(routine, knight):
            try:
                after, events, dispositions = _walked_to(state, document, knight)
                break
            except AssertionError:
                pass
        state, _events, _, _ = _minute(state, document)
    else:
        raise AssertionError("the knight never stood a while a walk from a sword in 480 minutes")
    assert dispositions[0].disposition == "applied"
    assert "called_away" in _reasons(events, knight)
    assert _knight(after)["goal"]["reason"] == "remembered_target_selected"


def _decision_receipt(state, document, being):
    """The receipt of the being's own model, which chose the first option it was offered."""
    terms = person_role().terms(state["profile"])
    contract = person_role().contract(terms.versions)
    options = choice_options(state, document, being["id"], contract, seed=SEED)
    context = decision_context(state, document, being["id"], options)
    request = seal(
        {
            "profile": person_role().request_profile,
            "request_id": str(uuid.uuid5(uuid.UUID(being["id"]), f"tick:{state['tick']}")),
            "subject_id": being["id"],
            "branch_id": state["branch_id"],
            "base_tick": state["tick"],
            "base_state_sha256": society_state_sha256(state),
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "context": context,
            "context_sha256": society_state_sha256(context),
            "provider_config": {
                "provider": "example_provider",
                "model_id": "example/model",
                "mechanism": "tool_call",
                "choice_seq": 1,
                "manifest_sha256": "a" * 64,
                "prompt_version": terms.prompt_version,
                "contract": contract.binding(),
                "deadline_ms": 20000,
            },
        }
    )
    option = context["options"][0]
    receipt = receipt_for(
        request,
        1,
        {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": {
                "provider": "example_provider",
                "model_id": "example/model",
                "served_model_id": "example/model",
                "mechanism": "tool_call",
                "prompt_version": terms.prompt_version,
                "messages_sha256": "b" * 64,
                "answers_asked": 1,
                "calls": [],
                "prompt_tokens": 300,
                "completion_tokens": 40,
                "cost_usd": "0.00002760",
                "cost_known": True,
                "latency_ms": 900,
            },
        },
    )
    validate_decision_receipt(receipt, request)
    return receipt


def test_the_being_s_own_model_is_set_aside_in_the_minute_it_is_asked():
    """Spec section 5: a model's answer for the asked being in that minute is superseded, its
    decision event says so (person_asked_directly), and the asked act is what the minute does."""
    state, document = _society(GATE, KNIGHT, SWORD)
    knight, sword = _knight(state), _thing(state, "sword")
    request = _ask(state, document, knight, "pick_up", sword["id"])
    receipt = _decision_receipt(state, document, knight)
    directed, dispositions = action_goal_policies(state, document, [request])
    policies, decided = model_goal_policies(state, document, [receipt], directed)
    assert [(d.disposition, d.reason) for d in decided] == [("superseded", "person_asked_directly")]
    assert policies[knight["id"]] == directed[knight["id"]]
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    events = append_action_events(state, planned, document, [request], dispositions, events)
    events = append_decision_events(state, planned, document, [receipt], decided, events)
    after, events, _ = advance_things(
        state,
        planned,
        SEED,
        document,
        events,
        (),
        decisions=[(receipt, decided[0])],
        asked=applied_hands([request], dispositions),
    )
    [decision] = [e for e in events if e.kind == DECISION_EVENT_KIND]
    assert (decision.document["outcome"], decision.document["reason"]) == (
        "decision_superseded",
        "person_asked_directly",
    )
    [picked] = [e for e in events if e.kind == "picked_up"]
    assert picked.document["reason"] == "asked_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]


@pytest.mark.parametrize(
    ("placed", "reason"),
    [(SWORD, "validated_model_wait"), (FAR_SWORD, "chosen_by_their_model")],
    ids=["within-reach-waits", "farther-off-walks"],
)
def test_a_decider_s_own_act_keeps_the_model_s_reasons(placed, reason):
    """The positive control on the request's reasons: an act the being's decider chose waits or
    walks with the model's own codes, as it did before requests could ask for one."""
    state, document = _society(GATE, KNIGHT, placed)
    knight, sword = _knight(state), _thing(state, "sword")
    option = next(
        o
        for o in choice_options(
            state,
            document,
            knight["id"],
            person_role().contract(person_role().terms(state["profile"]).versions),
            seed=SEED,
        )
        if o.kind == "pick_up" and o.target_id == sword["id"]
    )
    policy = hands_goal_policy(state, document, knight["id"], option, set())
    _planned, events = advance_purposeful_society(
        state, SEED, [document], goal_policy={knight["id"]: policy}
    )
    assert reason in _reasons(events, knight)
    assert not {"validated_user_wait", "remembered_target_selected"} & _reasons(events, knight)


def _choice(state, document, being, kind, thing_id):
    """The option a decider is offered for ``kind`` of ``thing_id``, as its receipt records it."""
    contract = person_role().contract(person_role().terms(state["profile"]).versions)
    return next(
        o
        for o in choice_options(state, document, being["id"], contract, seed=SEED)
        if o.kind == kind and o.target_id == thing_id
    )


def _decided(being, option):
    """A decider's applied choice, as the things phase reads a consumed receipt."""
    from exulanica.world.role_decisions import DecisionDisposition

    receipt = {
        "subject_id": being["id"],
        "request_id": f"r-{being['id']}-{option.kind}",
        "status": "accepted",
        "reason": "validated_choice",
        "proposal": {"label": option.label, "option": option.as_record()},
        "provider": {"provider": "test", "model_id": "m"},
    }
    return receipt, DecisionDisposition(
        decision_seq=1,
        request_id=receipt["request_id"],
        subject_id=being["id"],
        disposition="applied",
        reason="validated_choice",
        decision_sha256="0" * 64,
    )


def _things_minute(state, document, *, requests=(), decisions=(), crossings=()):
    """One minute as the repository runs it, with a person's requests, deciders' applied choices
    and a door's crossings: each policy, the planner, the requests' events, the things phase."""
    requests = list(requests)
    policies, dispositions = action_goal_policies(state, document, requests)
    for receipt, _disposition in decisions:
        option = DecisionOption.from_record(receipt["proposal"]["option"])
        policy = hands_goal_policy(state, document, receipt["subject_id"], option, set())
        assert not isinstance(policy, str), policy
        policies[receipt["subject_id"]] = policy
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    events = append_action_events(state, planned, document, requests, dispositions, events)
    after, events, _ = advance_things(
        state,
        planned,
        SEED,
        document,
        events,
        crossings,
        decisions=list(decisions),
        asked=applied_hands(requests, dispositions),
    )
    return after, events, dispositions


def _missed(events):
    return [(e.document["reason"], e.document["thing"]) for e in events if e.kind == "hands_missed"]


def test_an_asked_act_its_decider_replaces_is_recorded_as_left_undone():
    """Root's L1, THINGS's words: a decider's own hands act replacing a pending asked act records
    the asked one as missed, chose_otherwise, marked asked; the decider's act is then done."""
    state, document = _society(GATE, KNIGHT, SWORD, thing("sword-far", "sword", 2, -3_000, 2_600))
    knight, near, far = _knight(state), _thing(state, "sword"), _thing(state, "sword-far")
    pending = copy.deepcopy(state)
    _knight(pending)["hands"] = {
        "ability": "pick_up",
        "thing": far["id"],
        "with": None,
        "since": pending["tick"],
        "asked": True,
    }
    validate_things_state(pending)
    pick = _choice(state, document, knight, "pick_up", near["id"])
    after, events, _ = _things_minute(pending, document, decisions=[_decided(knight, pick)])
    [missed] = [e for e in events if e.kind == "hands_missed"]
    assert missed.document["reason"] == "chose_otherwise"
    assert missed.document["thing"] == {
        "ability": "pick_up",
        "thing": far["id"],
        "with": None,
        "asked": True,
    }
    [picked] = [e for e in events if e.kind == "picked_up"]
    assert picked.document["reason"] == "chose_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]


def test_a_decider_s_pending_act_a_request_replaces_is_recorded_as_left_undone():
    """Root's L1, THINGS's words: a request replacing a decider's pending act records that act as
    missed, asked_otherwise, with no asked mark (it was the decider's); the asked act is done."""
    state, document = _society(GATE, KNIGHT, SWORD, thing("sword-far", "sword", 2, -3_000, 2_600))
    knight, near, far = _knight(state), _thing(state, "sword"), _thing(state, "sword-far")
    pending = copy.deepcopy(state)
    _knight(pending)["hands"] = {
        "ability": "pick_up",
        "thing": far["id"],
        "with": None,
        "since": pending["tick"],
    }
    request = _ask(pending, document, _knight(pending), "pick_up", near["id"])
    after, events, dispositions = _things_minute(pending, document, requests=[request])
    assert dispositions[0].disposition == "applied"
    [missed] = [e for e in events if e.kind == "hands_missed"]
    assert missed.document["reason"] == "asked_otherwise"
    assert missed.document["thing"] == {"ability": "pick_up", "thing": far["id"], "with": None}
    [picked] = [e for e in events if e.kind == "picked_up"]
    assert picked.document["reason"] == "asked_to_pick_up"
    assert _thing(after, "sword")["held_by"] == knight["id"]


def test_an_asked_act_dropped_by_the_hands_step_is_marked_asked():
    """N3: a hands_missed for an asked act states asked; one for a decider's act does not (the
    positive control, as every stored minute recorded it)."""
    state, document = _society(GATE, KNIGHT, SWORD)
    gone = str(uuid.UUID(int=79))
    for asked, details in ((True, {"asked": True}), (False, {})):
        pending = copy.deepcopy(state)
        _knight(pending)["hands"] = {
            "ability": "pick_up",
            "thing": gone,
            "with": None,
            "since": pending["tick"],
            **({"asked": True} if asked else {}),
        }
        _after, events, _ = _things_minute(pending, document)
        [missed] = [e for e in events if e.kind == "hands_missed"]
        assert missed.document["reason"] == "thing_gone"
        assert missed.document["thing"] == {
            "ability": "pick_up",
            "thing": gone,
            "with": None,
            **details,
        }


def _visitor_with_a_lantern(document):
    """A traveller crossed in carrying a lantern, standing beside the knight."""
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    brought = str(uuid.uuid5(SOCIETY, "brought lantern"))
    state, _, _ = _things_minute(
        state,
        document,
        crossings=[
            arrival(
                1,
                kind=reference("traveller", 1),
                carried=[{"thing_id": brought, "kind": reference("lantern", 1)}],
            )
        ],
    )
    visitor = next(p for p in state["inhabitants"] if p["came_by"] == "crossed")
    beside = copy.deepcopy(state)
    moved = next(p for p in beside["inhabitants"] if p["id"] == visitor["id"])
    moved["position_mm"] = list(_knight(beside)["position_mm"])
    return beside, visitor, brought


def test_a_thing_a_visitor_here_brought_is_not_the_owner_s_to_hand_over():
    """Root's L2, THINGS's name and words: picking up or taking a thing whose bringer is still
    here is refused belongs_to_visitor, at the request and again at the minute."""
    document = compose((GATE, KNIGHT, SWORD))
    state, visitor, brought = _visitor_with_a_lantern(document)
    assert next(t for t in state["things"] if t["id"] == brought)["brought_by"] == visitor["id"]
    knight = _knight(state)
    with pytest.raises(ValueError, match=r"^belongs_to_visitor$"):
        _ask(state, document, knight, "take", brought, with_id=visitor["id"])
    # Lying on the ground beside the knight, as its bringer would put it down, it is still the
    # visitor's.
    down = copy.deepcopy(state)
    lying = next(t for t in down["things"] if t["id"] == brought)
    lying.update(held_by=None, position_mm=list(_knight(down)["position_mm"]))
    del lying["socket"]
    # The world's own sword lies there too, for the positive control below.
    next(t for t in down["things"] if t["placed_id"] == "sword")["position_mm"] = list(
        _knight(down)["position_mm"]
    )
    validate_things_state(down)
    with pytest.raises(ValueError, match=r"^belongs_to_visitor$"):
        _ask(down, document, _knight(down), "pick_up", brought)
    # The positive control: the world's own sword lying beside it may be picked up.
    _ask(down, document, _knight(down), "pick_up", _thing(down, "sword")["id"])
    # The minute reads the act again: a request for the visitor's lantern, held as the table
    # would hold one built without the request's own check, is refused by the same name.
    unchecked = _unchecked_request(down, document, _knight(down), "pick_up", brought)
    _policies, dispositions = action_goal_policies(down, document, [unchecked])
    assert [(d.disposition, d.reason) for d in dispositions] == [("rejected", "belongs_to_visitor")]


def _unchecked_request(state, document, being, ability, thing_id, with_id=None):
    """A v2 request with the envelope build_action_request writes, built without its check."""
    body = {
        "profile": HANDS_REQUEST_PROFILE,
        "request_id": str(uuid.UUID(int=0x51)),
        "requested_by": str(ASKER),
        "subject_id": being["id"],
        "branch_id": state["branch_id"],
        "base_tick": state["tick"],
        "base_state_sha256": society_state_sha256(state),
        "input_seq": document["input_seq"],
        "input_sha256": document["document_sha256"],
        "intent": {"kind": "hands", "ability": ability, "thing_id": thing_id, "with_id": with_id},
    }
    return {**body, "document_sha256": society_state_sha256(body)}


def test_a_society_without_the_hands_module_refuses_by_the_module_first():
    """N1: a society not running the hands module answers act_not_offered, never thing_gone,
    whatever thing the request names."""
    document = compose((GATE, KNIGHT, SWORD))
    document.pop("modules", None)
    from exulanica.world.society_planner import input_sha256

    document.pop("document_sha256")
    document["document_sha256"] = input_sha256(document)
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    assert "modules" not in state
    for named in (str(uuid.UUID(int=77)), next(t["id"] for t in state["things"])):
        with pytest.raises(ValueError, match=r"^act_not_offered$"):
            _ask(state, document, _knight(state), "pick_up", named)


def test_no_shipped_kind_can_be_asked_to_take():
    """Take needs a being whose kind offers let_take, and no shipped kind does, so a person's
    take is refused by name (the offers catalog is the expectation's source)."""
    from pathlib import Path

    kinds = Path(__file__).resolve().parents[1] / "assets" / "catalogs" / "things" / "kinds"
    assert sorted(kinds.glob("*.json")), kinds
    assert not [path.name for path in kinds.glob("*.json") if "let_take" in path.read_text()]
    other = thing("knight-2", "knight", 1, 3_000, 5_000)
    state, document = _society(GATE, KNIGHT, other, SWORD)
    held, _, _, _ = _minute(
        state,
        document,
        [_ask(state, document, _knight(state), "pick_up", _thing(state, "sword")["id"])],
    )
    second = next(p for p in held["inhabitants"] if p["placed_id"] == "knight-2")
    with pytest.raises(ValueError, match=r"^act_not_offered$"):
        _ask(
            held, document, second, "take", _thing(held, "sword")["id"], with_id=_knight(held)["id"]
        )


def test_a_being_asked_puts_down_what_it_holds_where_it_stands():
    state, document = _society(GATE, KNIGHT, SWORD)
    knight = _knight(state)
    held, _, _, _ = _minute(
        state, document, [_ask(state, document, knight, "pick_up", _thing(state, "sword")["id"])]
    )
    assert _thing(held, "sword")["held_by"] == knight["id"]
    request = _ask(held, document, _knight(held), "put_down", _thing(held, "sword")["id"])
    after, events, dispositions, _ = _minute(held, document, [request])
    assert dispositions[0].disposition == "applied"
    [down] = [e for e in events if e.kind == "put_down"]
    assert down.document["reason"] == "asked_to_put_down"
    sword = _thing(after, "sword")
    assert sword["held_by"] is None
    assert sword["position_mm"] == _knight(after)["position_mm"]


def test_a_second_being_asked_for_the_same_far_thing_finds_its_place_taken():
    """At the minute the first applied request holds the one open node within reach of the
    sword, so the second is refused out_of_reach there, though both were offered when made."""
    second = thing("knight-2", "knight", 1, 3_000, 5_000)
    state, document = _society(GATE, KNIGHT, second, FAR_SWORD)
    knight = _knight(state)
    other = next(p for p in state["inhabitants"] if p["placed_id"] == "knight-2")
    sword = _thing(state, "sword")
    first = _ask(state, document, knight, "pick_up", sword["id"])
    then = _ask(state, document, other, "pick_up", sword["id"])
    _after, _events, dispositions, policies = _minute(state, document, [first, then])
    assert [(d.disposition, d.reason) for d in dispositions] == [
        ("applied", "validated_user_act"),
        ("rejected", "out_of_reach"),
    ]
    assert "place_node_id" in policies[knight["id"]] and other["id"] not in policies


#: A v2 minute pinned: the knight asked (request 0x61) to pick up the sword it must walk to, the
#: minute as _minute composes it, over the modules of the history test's record. The digests were
#: recorded from this package's code; the knight's events and their reasons are the spec's,
#: written out by hand.
PINNED_V2_MINUTE = {
    "tick": 1,
    "state_sha256": "b4c4a29df1372f1f3bc3baeab324360f05ab50cd76f6a6545e4bb2cd8df53d06",
    "events_sha256": "4271460d41e6088b847faf7f07ce2721cde3dd20b9dc13484e63a7dd4a51d755",
    "knight": [
        ("goal_selected", "remembered_target_selected"),
        ("route_progressed", "standing_a_while"),
        ("user_action_requested", "validated_user_act"),
        ("picked_up", "asked_to_pick_up"),
    ],
}


def test_a_minute_with_a_walking_hands_request_keeps_its_pinned_bytes():
    from test_society_hands_history_before_requests import recorded
    from test_society_things_before_modules import _events_sha256

    # The modules the pin was recorded with, so a module added since leaves the minute as it was.
    document = recorded(compose((GATE, KNIGHT, FAR_SWORD)))
    state = initial_things_society(SOCIETY, SEED, document, population=POPULATION)
    knight, sword = _knight(state), _thing(state, "sword")
    request = build_action_request(
        state,
        document,
        request_id=uuid.UUID(int=0x61),
        requested_by=ASKER,
        subject_id=uuid.UUID(knight["id"]),
        intent=ActionIntent(kind="hands", target_id=sword["id"], ability="pick_up"),
    )
    after, events, _, _ = _minute(state, document, [request])
    assert [
        (e.kind, e.document["reason"]) for e in events if str(e.subject_id) == knight["id"]
    ] == PINNED_V2_MINUTE["knight"]
    assert (after["tick"], society_state_sha256(after), _events_sha256(events)) == (
        PINNED_V2_MINUTE["tick"],
        PINNED_V2_MINUTE["state_sha256"],
        PINNED_V2_MINUTE["events_sha256"],
    )
