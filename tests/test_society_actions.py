"""Typed user directions at the deterministic society-planner boundary."""

from __future__ import annotations

import uuid
from copy import deepcopy

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import (
    ActionIntent,
    action_goal_policies,
    advance_directed_purposeful_society,
    build_action_request,
    validate_action_request,
)
from exulanica.world.society_planner import initial_purposeful_society
from exulanica.world.society_social import advance_social_society, initial_social_society

from society_fixtures import SEED, SOCIETY, VERSION, edited, seal, society_input

ACTOR = uuid.UUID("8de45374-8fab-41d5-9344-388c7c5c9fe6")


def request(state, document, *, target="authored:bench:rest", kind="go_to", affordance=None):
    return build_action_request(
        state,
        document,
        request_id=uuid.uuid5(VERSION, f"{state['tick']}:{state['inhabitants'][0]['id']}:{target}"),
        requested_by=ACTOR,
        subject_id=uuid.UUID(state["inhabitants"][0]["id"]),
        intent=ActionIntent(kind, target, affordance),
    )


@pytest.mark.parametrize("initializer", [initial_purposeful_society, initial_social_society])
def test_canonical_target_ids_produce_the_same_v2_v3_goal_policy(initializer):
    document = society_input()
    state = initializer(SOCIETY, SEED, document)
    action = request(state, document)
    policies, dispositions = action_goal_policies(state, document, [action])
    subject = state["inhabitants"][0]["id"]
    assert policies == {
        subject: {
            "allowed_target_ids": ["authored:bench:rest"],
            "preferred_target_id": "authored:bench:rest",
        }
    }
    assert [(value.disposition, value.reason) for value in dispositions] == [
        ("applied", "validated_user_target")
    ]
    assert action["target"] == document["targets"][0]
    assert "position_mm" not in action["intent"] and "text" not in action["intent"]


def test_directed_v2_advance_uses_the_reviewed_graph_and_replays_exactly():
    document = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, document)
    action = request(state, document)
    original = deepcopy(state)
    advanced, events, dispositions = advance_directed_purposeful_society(
        state, SEED, [document], [action]
    )
    replayed, replay_events, replay_dispositions = advance_directed_purposeful_society(
        original, SEED, [document], [action]
    )
    person = advanced["inhabitants"][0]
    assert person["goal"]["target_id"] == "authored:bench:rest"
    assert person["position_mm"] == [40000, 20000]
    assert person["motion_path_mm"] == [[0, 0], [40000, 0], [40000, 20000]]
    assert events[-1].kind == "user_action_requested"
    assert events[-1].document["action_request_sha256"] == action["document_sha256"]
    assert events[-1].document["disposition"] == "applied"
    assert (advanced, events, dispositions) == (replayed, replay_events, replay_dispositions)
    assert state == original


def test_v3_external_policy_uses_the_normal_planner_without_weakening_preconditions():
    document = society_input()
    state = initial_social_society(SOCIETY, SEED, document)
    action = request(state, document)
    policies, _dispositions = action_goal_policies(state, document, [action])
    advanced, _events, _processed = advance_social_society(
        state, SEED, [document], external_goal_policy=policies
    )
    person = advanced["inhabitants"][0]
    assert person["goal"]["target_id"] == "authored:bench:rest"
    disconnected = deepcopy(document)
    disconnected["navigation"]["edges"] = []
    seal(disconnected)
    stale = deepcopy(state)
    stale.update(
        input_seq=disconnected["input_seq"],
        input_sha256=disconnected["document_sha256"],
    )
    unreachable, _events, _processed = advance_social_society(
        stale, SEED, [disconnected], external_goal_policy=policies
    )
    unreachable_person = unreachable["inhabitants"][0]
    assert (unreachable_person["goal"] or {}).get("target_id") != "authored:bench:rest"
    with pytest.raises(ValueError, match="select one enabled current target"):
        advance_social_society(
            stale,
            SEED,
            [disconnected],
            external_goal_policy={
                person["id"]: {
                    "allowed_target_ids": ["invented"],
                    "preferred_target_id": "invented",
                }
            },
        )


def test_action_request_rejects_coordinates_prose_and_unreviewed_affordances():
    document = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, document)
    action = request(state, document, kind="perform", affordance="rest")
    for mutation in (
        lambda value: value["intent"].update(position_mm=[40000, 40000]),
        lambda value: value["intent"].update(text="walk over there"),
        lambda value: value["intent"].update(affordance="teleport"),
    ):
        malformed = deepcopy(action)
        mutation(malformed)
        malformed["document_sha256"] = society_state_sha256(
            {key: value for key, value in malformed.items() if key != "document_sha256"}
        )
        with pytest.raises(ValueError):
            validate_action_request(malformed)
    with pytest.raises(ValueError, match="unknown canonical target"):
        request(state, document, target="browser:pixel:20,40")


def test_stale_state_changed_target_and_withdrawal_fail_closed():
    document = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, document)
    action = request(state, document)
    later = deepcopy(state)
    later["tick"] += 1
    policies, dispositions = action_goal_policies(later, document, [action])
    assert not policies and dispositions[0].disposition == "stale"

    moved = edited(document)
    moved["targets"][0]["node_id"] = "a"
    seal(moved)
    changed = deepcopy(state)
    changed.update(input_seq=moved["input_seq"], input_sha256=moved["document_sha256"])
    policies, dispositions = action_goal_policies(changed, moved, [action])
    assert not policies and dispositions[0].reason == "action_context_changed"

    withdrawn = deepcopy(document)
    withdrawn.update(availability="unavailable", unavailable_reason="source_withdrawn")
    seal(withdrawn)
    paused = deepcopy(state)
    paused.update(input_seq=withdrawn["input_seq"], input_sha256=withdrawn["document_sha256"])
    # Building a new request against unavailable authority is refused before persistence.
    with pytest.raises(ValueError, match="source_withdrawn"):
        request(paused, withdrawn)
