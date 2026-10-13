"""Admitted kind preferences govern ordinary choices only in recorded purposeful/v3."""

from __future__ import annotations

import copy

import pytest
from exulanica.abilities.registry import PURPOSEFUL_BY_KIND_WEIGHTS
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar, read_body_recipe
from exulanica.things.creatures import assemble_creature
from exulanica.things.run_forms import run_form
from exulanica.world.society_actions import ActionIntent, action_goal_policies, build_action_request
from exulanica.world.society_catalogs import UNRECORDED_ROUTINE_VERSIONS, purposeful_routine
from exulanica.world.society_decision_contract import (
    TalkPromise,
    choice_options,
    option_goal_policy,
    person_role,
    recheck_talk,
)
from exulanica.world.society_planner import (
    advance_purposeful_society,
    input_sha256,
    validate_society_input,
)
from exulanica.world.society_routine_weights import routine_weights
from exulanica.world.society_things import (
    advance_things,
    initial_things_society,
    validate_things_state,
)

from creature_support import form_of
from test_society_made_kinds import BY, WELL, _placed
from things_society_support import SEED, SOCIETY, compose


def scenario(*preferences, resting=True, walking=True):
    kinds, placed = {}, [WELL]
    for number, weights in enumerate(preferences):
        form = form_of(
            "horse", label="routine creature " + chr(97 + number), moves=None if walking else []
        )
        for key in ("wait", "stand", "talk", "rest", "visit"):
            form[f"can_{key}"] = key == "wait" or (walking and (key != "rest" or resting))
            form[f"weight_{key}"] = weights.get(key, 0) if form[f"can_{key}"] else 0
        form["can_follow"] = walking
        form["weight_follow"] = 0
        creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
        kinds[creature.kind.sha256] = run_form(
            creature.kind, creature.plan, read_body_recipe(dict(creature.recipe))
        )
        placed.append(
            _placed(f"weighted:{number}", creature.kind.sha256, -2000 + number * 4000, 4000)
        )
    document = compose(tuple(placed), made_kinds=kinds)
    assert PURPOSEFUL_BY_KIND_WEIGHTS in document["modules"]
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    for person in state["inhabitants"]:
        person["need_milli"] = 0
    return state, document


def being(state, number=0):
    return next(p for p in state["inhabitants"] if p.get("placed_id") == f"weighted:{number}")


def minute(state, document, policies=None):
    planned, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    after, events, _ = advance_things(state, planned, SEED, document, events)
    validate_things_state(after)
    return after, events


@pytest.mark.parametrize(
    "weights, reason", [({"wait": 1000}, "routine_wait"), ({}, "no_weighted_activity")]
)
def test_wait_preference_or_zero_total_waits_honestly_without_event_flood(weights, reason):
    state, document = scenario(weights)
    initial = copy.deepcopy(state)
    position = being(state)["position_mm"]
    events = []
    for _ in range(12):
        state, recorded = minute(state, document)
        events.extend(e for e in recorded if str(e.subject_id) == being(state)["id"])
        person = being(state)
        assert person["position_mm"] == position and person["motion_path_mm"] == [position]
        assert person["goal"] is None and person["route"] is None
        assert (
            person["action"]["kind"],
            person["action"]["status"],
            person["action"]["reason"],
        ) == ("idle", "active", reason)
    assert [e.document["reason"] for e in events] == [reason]
    replay = initial
    replay_events = []
    for _ in range(12):
        replay, recorded = minute(replay, document)
        replay_events.extend(e for e in recorded if str(e.subject_id) == being(replay)["id"])
    assert (state, events) == (replay, replay_events)


@pytest.mark.parametrize("preference", ["stand", "visit"])
def test_positive_preference_produces_real_routes_and_activity(preference):
    state, document = scenario({preference: 1000})
    positions = {tuple(being(state)["position_mm"])}
    goals = set()
    for _ in range(18):
        state, _ = minute(state, document)
        person = being(state)
        positions.add(tuple(person["position_mm"]))
        if person["goal"] is not None:
            goals.add(person["goal"]["kind"])
    assert len(positions) > 1
    assert goals == {preference}


def test_missing_and_explicit_zero_are_same_and_other_ability_weights_do_not_leak():
    state, _ = scenario({"wait": 1000})
    own = being(state)
    before = routine_weights(state)
    form = state["kinds"][own["kind"]["sha256"]]
    assert "rest" not in form["routine"]["weights"]
    form["routine"]["weights"].update(rest=0, follow=10000)
    assert routine_weights(state) == before
    assert before[own["id"]] == {"wait": 1000, "stand": 0, "talk": 0, "rest": 0, "visit": 0}
    untyped = copy.deepcopy(state)
    del being(untyped)["kind"]
    assert own["id"] not in routine_weights(untyped)


def test_routine_talk_cannot_recruit_a_zero_preference_partner():
    state, document = scenario({"talk": 1000}, {"wait": 1000})
    other = being(state, 1)["id"]
    start = being(state, 1)["position_mm"]
    for _ in range(18):
        state, _ = minute(state, document)
        assert being(state, 1)["position_mm"] == start
        assert being(state, 1)["action"]["reason"] == "routine_wait"
        assert not any(
            p.get("goal", {}).get("partner_id") == other
            for p in state["inhabitants"]
            if p.get("goal")
        )


def test_tiredness_overrides_zero_rest_preference_and_waiting_releases_its_seat():
    state, document = scenario({"wait": 1000})
    being(state)["need_milli"] = 800
    state, _ = minute(state, document)
    assert being(state)["goal"]["kind"] == "rest"
    assert being(state)["goal"]["reason"] == "needs_a_rest"
    seen_room = False
    for _ in range(25):
        state, events = minute(state, document)
        seen_room |= any(
            str(e.subject_id) == being(state)["id"] and e.document["reason"] == "making_room"
            for e in events
        )
    assert seen_room
    assert being(state)["action"]["reason"] == "routine_wait"
    assert being(state)["need_milli"] < 750
    no_rest, no_rest_document = scenario({"wait": 1000}, resting=False)
    being(no_rest)["need_milli"] = 800
    no_rest, _ = minute(no_rest, no_rest_document)
    assert being(no_rest)["need_milli"] == 0
    assert being(no_rest)["action"]["reason"] == "routine_wait"


def test_zero_preferences_do_not_remove_explicit_choices_or_capability_checks():
    state, document = scenario({"wait": 1000})
    person = being(state)
    contract = person_role().contract_for(state["profile"])
    options = choice_options(state, document, person["id"], contract, seed=SEED)
    assert {"stand", "target", "talk"} <= {option.kind for option in options}
    target = next(t for t in document["targets"] if t["enabled"] and t["affordance"] == "visit")
    import uuid

    request = build_action_request(
        state,
        document,
        request_id=uuid.uuid5(SOCIETY, "weighted-owner"),
        requested_by=uuid.UUID(int=17),
        subject_id=uuid.UUID(person["id"]),
        intent=ActionIntent("go_to", target["target_id"]),
    )
    policies, dispositions = action_goal_policies(state, document, [request])
    assert dispositions[0].disposition == "applied"
    state, _ = minute(state, document, policies)
    assert being(state)["goal"]["kind"] == "visit"
    still, still_document = scenario({"wait": 1000}, walking=False)
    position = being(still)["position_mm"]
    for _ in range(3):
        still, _ = minute(still, still_document)
    assert being(still)["position_mm"] == position
    assert not {"stand", "target", "talk"} & {
        o.kind
        for o in choice_options(still, still_document, being(still)["id"], contract, seed=SEED)
    }


def test_nearest_with_activity_targets_remains_refused_and_no_targets_waits():
    state, document = scenario({"wait": 1000})
    prior = copy.deepcopy(document)
    document["routine"] = purposeful_routine(UNRECORDED_ROUTINE_VERSIONS).binding()
    for target in document["targets"]:
        target["activity"] = target["affordance"]
    document["document_sha256"] = input_sha256(document)
    with pytest.raises(ValueError, match="does not state every target"):
        validate_society_input(document)
    document["targets"] = []
    document["input_seq"] += 1
    document.pop("modules", None)
    document.pop("movement_modules", None)
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    planned, events = advance_purposeful_society(state, SEED, [prior, document])
    state, _, _ = advance_things(state, planned, SEED, document, events)
    assert being(state)["action"]["reason"] == "routine_wait"


def test_explicit_talk_with_zero_preference_partner_keeps_its_validated_promise():
    state, document = scenario({"wait": 1000}, {"wait": 1000})
    subject, partner = being(state), being(state, 1)
    contract = person_role().contract_for(state["profile"])
    offered = choice_options(state, document, subject["id"], contract, seed=SEED)
    option = next(o for o in offered if o.kind == "talk" and o.partner_id == partner["id"])
    promise = recheck_talk(state, document, subject["id"], option, set(), set())
    assert isinstance(promise, TalkPromise)
    policy = option_goal_policy(option, promise)
    after, _ = minute(state, document, {subject["id"]: policy})
    assert being(after)["goal"]["partner_id"] == partner["id"]
    assert being(after, 1)["goal"]["partner_id"] == subject["id"]
    assert being(after)["goal"]["reason"] == "chosen_by_their_model"
    # A positive control for the autonomous branch: actual talk preferences still pair.
    state, document = scenario({"talk": 1000}, {"talk": 1000})
    after, _ = minute(state, document)
    assert being(after)["goal"]["kind"] == "talk"
