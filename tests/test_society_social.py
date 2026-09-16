import json
from copy import deepcopy

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import ordered_events_document
from exulanica.world.society_social import (
    advance_social_society,
    decision_context,
    initial_social_society,
    validate_proposal,
)

from social_society_fixtures import add_social_marker, recorded_choice, social_input
from society_fixtures import SEED, SOCIETY, edited, seal


def learned_state():
    initial = social_input()
    changed = add_social_marker(initial)
    state = initial_social_society(SOCIETY, SEED, initial)
    states = [state]
    events = []
    for tick in range(1, 5):
        state, produced, _ = advance_social_society(
            state, SEED, [initial, changed] if tick == 1 else [changed]
        )
        states.append(state)
        events.extend(produced)
    return initial, changed, states, events


def test_local_observation_communication_then_valid_remembered_choice_and_replay():
    initial, changed, states, earlier = learned_state()
    state = states[-1]
    observer, receiver, distant = state["social"]["cast_ids"]
    key = "authored:new-marker:visit"
    assert key in states[1]["social"]["agents"][observer]["beliefs"]
    assert key not in states[1]["social"]["agents"][receiver]["beliefs"]
    learned = states[2]["social"]["agents"][receiver]["beliefs"][key]
    assert learned["origin"] == "communication" and learned["source_subject_id"] == observer
    assert states[2]["social"]["agents"][receiver]["observations"] == []
    assert key not in states[2]["social"]["agents"][distant]["beliefs"]
    assert any(e.kind == "communicated" and e.document["dialogue"] is None for e in earlier)
    context = decision_context(state, changed, receiver)
    assert context["can_choose_goal"]
    decision = recorded_choice(state, changed, receiver)
    chosen, events, processed = advance_social_society(state, SEED, [changed], [decision])
    person = next(p for p in chosen["inhabitants"] if p["id"] == receiver)
    assert person["goal"]["reason"] == "remembered_target_selected"
    assert person["target"]["target_id"] == key
    assert person["position_mm"] == [0, 0]
    assert processed == [(1, "applied")]
    completed, completion_events, _ = advance_social_society(chosen, SEED, [changed])
    assert any(
        e.kind == "action_completed" and str(e.subject_id) == receiver for e in completion_events
    )
    # Reload serialized original states and exact receipts, never consult a provider.
    reloaded = json.loads(json.dumps(state))
    replayed, replay_events, replay_processed = advance_social_society(
        reloaded, SEED, [changed], [json.loads(json.dumps(decision))]
    )
    assert replayed == chosen and replay_processed == processed
    assert ordered_events_document(replay_events) == ordered_events_document(events)
    assert len(completed["inhabitants"]) == 128
    assert society_state_sha256(
        initial_social_society(SOCIETY, SEED, initial)
    ) == society_state_sha256(states[0])


def test_agent_context_does_not_expose_another_agents_beliefs_or_allow_unknown_target():
    _, changed, states, _ = learned_state()
    state = states[1]
    _, receiver, _ = state["social"]["cast_ids"]
    context = decision_context(state, changed, receiver)
    assert context["own_beliefs"] == [] and context["own_observations"] == []
    assert "authored:new-marker" not in json.dumps(context)
    context["can_choose_goal"] = True
    assert (
        validate_proposal(
            context, changed, {"kind": "choose_goal", "target_id": "authored:new-marker:visit"}
        )
        == "target_not_known_to_agent"
    )
    with pytest.raises(ValueError, match="bounded social cast"):
        decision_context(state, changed, state["inhabitants"][20]["id"])


def test_edit_invalidates_stored_decision_without_learning_global_truth_or_acting():
    _, changed, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    decision = recorded_choice(state, changed, receiver)
    removed = edited(changed)
    removed["targets"] = [t for t in removed["targets"] if t["origin"] == "district"]
    seal(removed)
    next_state, events, processed = advance_social_society(
        state, SEED, [changed, removed], [decision]
    )
    assert processed == [(1, "stale")]
    assert any(e.document["reason"] == "decision_context_changed" for e in events)
    person = next(p for p in next_state["inhabitants"] if p["id"] == receiver)
    assert (person["target"] or {}).get("origin") != "authored"
    with pytest.raises(ValueError, match="sequence gap"):
        advance_social_society(next_state, SEED, [removed], [decision])


def test_receipt_tampering_rejected_and_missing_provider_receipt_cannot_act():
    _, changed, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    receipt = recorded_choice(state, changed, receiver)
    bad = deepcopy(receipt)
    bad["proposal"]["target_id"] = "unknown"
    with pytest.raises(ValueError, match="digest"):
        advance_social_society(state, SEED, [changed], [bad])
    receipt.update(
        status="unavailable", reason="provider_not_configured", proposal=None, provider=None
    )
    seal(receipt)
    _, events, processed = advance_social_society(state, SEED, [changed], [receipt])
    assert processed == [(1, "unavailable")]
    assert any(e.document["reason"] == "provider_not_configured" for e in events)


def test_vacated_location_does_not_reveal_a_distant_new_location():
    _, changed, states, _ = learned_state()
    state = states[-1]
    observer, receiver, distant = state["social"]["cast_ids"]
    moved = edited(changed)
    target = next(t for t in moved["targets"] if t["origin"] == "authored")
    target["node_id"] = "c"
    seal(moved)
    result, events, _ = advance_social_society(state, SEED, [changed, moved])
    key = target["target_id"]
    belief = result["social"]["agents"][observer]["beliefs"][key]
    assert belief["target"]["node_id"] == "a" and belief["available"] is False
    assert result["social"]["agents"][distant]["beliefs"][key]["target"]["node_id"] == "c"
    context = decision_context(result, moved, observer)
    assert all(b["target"]["node_id"] != "c" for b in context["own_beliefs"])
    assert any(
        e.kind == "observed" and e.document["input_seq"] == moved["input_seq"] for e in events
    )
    assert not any(
        p["id"] == receiver and (p["target"] or {}).get("target_id") == key
        for p in result["inhabitants"]
    )


def test_wait_receipt_is_one_tick_and_old_hearsay_cannot_overwrite_newer_input():
    _, changed, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    decision = recorded_choice(
        state, changed, receiver, proposal={"kind": "wait", "target_id": None}
    )
    waited, _, processed = advance_social_society(state, SEED, [changed], [decision])
    person = next(p for p in waited["inhabitants"] if p["id"] == receiver)
    assert processed == [(1, "applied")]
    assert person["action"]["reason"] == "validated_model_wait"
    resumed, _, _ = advance_social_society(waited, SEED, [changed])
    assert (
        next(p for p in resumed["inhabitants"] if p["id"] == receiver)["action"]["reason"]
        != "validated_model_wait"
    )
    removed = edited(changed)
    removed["targets"] = [t for t in removed["targets"] if t["origin"] == "district"]
    seal(removed)
    current, _, _ = advance_social_society(state, SEED, [changed, removed])
    observer = current["social"]["cast_ids"][0]
    key = "authored:new-marker:visit"
    assert current["social"]["agents"][observer]["beliefs"][key]["available"] is False
    for _ in range(4):
        current, _, _ = advance_social_society(current, SEED, [removed])
        assert (
            current["social"]["agents"][observer]["beliefs"][key]["input_seq"]
            == removed["input_seq"]
        )
        assert current["social"]["agents"][observer]["beliefs"][key]["available"] is False


def test_known_target_requires_current_reachability_and_memory_remains_bounded():
    _, changed, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    context = decision_context(state, changed, receiver)
    disconnected = edited(changed)
    disconnected["navigation"]["edges"] = [
        e for e in disconnected["navigation"]["edges"] if e["edge_id"] == "bc"
    ]
    seal(disconnected)
    assert (
        validate_proposal(
            context, disconnected, {"kind": "choose_goal", "target_id": "authored:new-marker:visit"}
        )
        == "known_target_unreachable"
    )
    numerous = edited(changed)
    prototype = next(t for t in changed["targets"] if t["origin"] == "authored")
    for number in range(24):
        target = deepcopy(prototype)
        target.update(
            target_id=f"authored:fixture-{number:02}:visit",
            subject_id=f"authored:fixture-{number:02}",
            object_id=f"object:fixture-{number:02}",
        )
        numerous["targets"].append(target)
    numerous["targets"].sort(key=lambda t: t["target_id"])
    seal(numerous)
    current, events, _ = advance_social_society(state, SEED, [changed, numerous])
    observer = current["social"]["cast_ids"][0]
    assert len([e for e in events if e.kind == "observed" and str(e.subject_id) == observer]) > 16
    own = current["social"]["agents"][observer]
    assert len(own["observations"]) == len(own["beliefs"]) == 16
    assert len(decision_context(current, numerous, observer)["own_observations"]) == 8


def test_unavailable_pause_does_not_expose_old_targets_in_decision_events():
    _, changed, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    receipt = recorded_choice(state, changed, receiver)
    unavailable = edited(changed)
    unavailable.update(availability="unavailable", unavailable_reason="source_withdrawn")
    seal(unavailable)
    paused, events, dispositions = advance_social_society(
        state, SEED, [changed, unavailable], [receipt]
    )
    assert dispositions == [(1, "stale")]
    event = next(e for e in events if e.kind == "decision_applied")
    assert event.document["goal"] is None
    assert event.document["action"]["target_id"] is None
    assert not paused["social"]["agents"][receiver]["beliefs"]
