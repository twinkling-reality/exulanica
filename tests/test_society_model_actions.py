"""A model-run person may stand a while or stop to talk, as the routine itself could let them.

Pure: the small square is composed and advanced in memory exactly as a step advances it
(``living_square_support``), and a decision is the receipt the host would store. What is shown:

*   the second contract offers standing and talking, and the first offers what it always did;
*   a conversation is offered only with somebody the routine itself could pair the person with
    then, and standing only where the routine finds an open spot;
*   a choice to talk is checked when the minute runs: the other person still free and nobody,
    their own model included, deciding for them in that minute, with room for the two of them,
    and each failure has a name;
*   an applied conversation is the routine's own talk, with the model's own reason code, and two
    people whose models chose each other talk together;
*   a played hour of such choices replays byte for byte with nothing asked, and a society with no
    model choices, or with the first contract's, is the one it was before the second existed.
"""

from __future__ import annotations

import copy
import json
import random
import re
import time
import uuid
from decimal import Decimal
from pathlib import Path

import exulanica.api.decision_host as host_module
import pytest
from exulanica.api.decision_host import DecisionHost, RoleAsk
from exulanica.api.society_person_decisions import PersonAsk, ask_person
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import (
    MANIFEST_PATH,
    AnsweringMechanism,
    load_manifest,
    parse_manifest,
)
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground import AUTHORED_GROUND_POPULATION
from exulanica.world.society_decision_contract import (
    CHOSEN_BY_MODEL,
    DecisionOption,
    TalkPromise,
    choice_options,
    decision_contract,
    option_goal_policy,
    person_role,
    recheck_option,
    recheck_talk,
)
from exulanica.world.society_decisions import person_request, receipt_for, validate_decision_receipt
from exulanica.world.society_model_decisions import append_decision_events, model_goal_policies
from exulanica.world.society_planner import (
    REASON_CODES,
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
    routine_of,
    standing_exclusions,
)

import living_square_support as square
import test_society_person_decisions as asks
from model_fakes import FakeTransport, RecordingPolicy

SEED = square.DEVELOPMENT_SEEDS[0]
V1 = {"society-decision-action": 1, "society-decision-policy": 1}
#: Where the tests stand the square's eight people: open ground south of its places, on the
#: society's two-metre lattice. Person 2 has one neighbour four metres away on each side, and
#: everybody else at ten metres or more, beyond the talk's reach of eight.
SPOTS = {
    0: (-10000, 10000),
    1: (-4000, 10000),
    2: (0, 10000),
    3: (4000, 10000),
    4: (10000, 10000),
    5: (-8000, 2000),
    6: (0, 0),
    7: (8000, 2000),
}
#: A person's need well below the routine's rest threshold, so nobody prefers a rest first.
RESTED = 300


def _node(x: int, z: int) -> str:
    """The lattice node at a point, as the authored ground names its nodes."""
    return f"ground:{x:+09d}:{z:+09d}"


def _square(spots=SPOTS, *, need=RESTED, document=None):
    """The square's genesis with its people moved to ``spots`` and given ``need``, all free."""
    document = square.compose(square.square_objects()) if document is None else document
    state = initial_purposeful_society(
        square.SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    nodes = {node["node_id"] for node in document["navigation"]["nodes"]}
    for person in state["inhabitants"]:
        x, z = spots[person["ordinal"]]
        assert _node(x, z) in nodes, (x, z)
        person["location"] = {"node_id": _node(x, z), "edge": None}
        person["position_mm"] = [x, z]
        person["motion_path_mm"] = [[x, z]]
        person["need_milli"] = need
    return state, document


def _person(state, ordinal):
    return next(p for p in state["inhabitants"] if p["ordinal"] == ordinal)


def _standing(state, document, ordinal):
    """Make a person stand a while where they are, as the routine leaves somebody standing."""
    person = _person(state, ordinal)
    here = person["location"]["node_id"]
    person["goal"] = {"kind": "stand", "target_id": None, "reason": "stopping_a_while"}
    person["route"] = {
        "node_ids": [here],
        "edge_index": 0,
        "edge_progress_mm": 0,
        "destination_node_id": here,
        "input_sha256": document["document_sha256"],
    }
    person["action"] = {
        "kind": "stand",
        "status": "active",
        "target_id": None,
        "remaining_ticks": 3,
        "reason": "standing_a_while",
        "relief_milli": 0,
    }


def _walking(state, document, ordinal, to):
    """Make a person be on their way to ``to``, as a goal the routine chose leaves them."""
    person = _person(state, ordinal)
    here = person["location"]["node_id"]
    person["goal"] = {"kind": "stand", "target_id": None, "reason": "stopping_a_while"}
    person["route"] = {
        "node_ids": [here, to],
        "edge_index": 0,
        "edge_progress_mm": 0,
        "destination_node_id": to,
        "input_sha256": document["document_sha256"],
    }
    person["action"] = {
        "kind": "move",
        "status": "active",
        "target_id": None,
        "remaining_ticks": 0,
        "reason": "following_reachable_route",
    }


def _talks(options):
    return {option.partner_id: option for option in options if option.kind == "talk"}


def _config(contract):
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": "society-person-choice/v1",
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }


def _provider():
    return {
        "provider": "example_provider",
        "model_id": "example/model",
        "served_model_id": "example/model",
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


def _request(state, document, subject, contract=None, seed=SEED):
    contract = decision_contract() if contract is None else contract
    request, status = person_request(
        state,
        document,
        subject,
        request_id=uuid.uuid5(square.SOCIETY, f"{subject}:{state['tick']}"),
        contract=contract,
        seed=seed,
        provider_config=_config(contract),
    )
    assert request is not None, status
    return request


def _receipt(request, sequence, choose):
    """The receipt of a model that chose the first offered option ``choose`` accepts."""
    option = next(o for o in request["context"]["options"] if choose(o))
    receipt = receipt_for(
        request,
        sequence,
        {
            "status": "accepted",
            "reason": "validated_choice",
            "proposal": {"label": option["label"], "option": option},
            "provider": _provider(),
        },
    )
    validate_decision_receipt(receipt, request)
    return receipt


def _talk_with(partner):
    return lambda option: option["kind"] == "talk" and option["partner_id"] == partner["id"]


def _minute(state, document, receipts, directed=None):
    """One minute consuming ``receipts``: the policies, dispositions, next state and events."""
    policies, decided = model_goal_policies(state, document, receipts, directed or {})
    after, events = advance_purposeful_society(state, SEED, [document], goal_policy=policies)
    events = append_decision_events(state, after, document, receipts, decided, events)
    return policies, decided, after, events


# -- the contract ---------------------------------------------------------------------------------


def test_the_second_contract_states_standing_and_talking_and_the_first_stays_as_it_was():
    second, first = decision_contract(), decision_contract(V1)
    assert (
        second.versions
        == person_role().contract_versions
        == {
            "society-decision-action": 2,
            "society-decision-policy": 2,
        }
    )
    assert set(second.words) == {"target", "wait", "stand", "talk"}
    assert set(first.words) == {"target", "wait"}
    # A person to talk with is named by a number and a walk, never by any name.
    assert set(re.findall(r"\{([a-z_]+)\}", second.words["talk"])) == {"number", "metres"}
    assert second.words["stand"] == second.words["stand"].lower()
    # The first contract's words and bounds are what every stored request recorded.
    assert first.words["target"] == second.words["target"]
    assert first.words["wait"] == second.words["wait"]
    assert dict(first.policy) == dict(second.policy)
    assert first.sha256 != second.sha256


def test_a_conversation_is_recorded_with_who_it_is_with_and_every_other_option_as_it_was():
    base = {
        "label": "stand a while nearby",
        "kind": "stand",
        "action": "stand",
        "target_id": None,
        "activity": "stand",
        "walk_mm": None,
    }
    assert DecisionOption.from_record(base).as_record() == base
    talk = {
        **base,
        "label": "talk with person 2, 4 m away",
        "kind": "talk",
        "action": "talk",
        "activity": "talk",
        "walk_mm": 4000,
        "partner_id": "someone",
    }
    assert DecisionOption.from_record(talk).as_record() == talk
    assert set(DecisionOption.from_record(base).as_record()) == set(base)
    with pytest.raises(ValueError, match="exactly its fields"):
        DecisionOption.from_record({**base, "partner_id": "someone"})
    with pytest.raises(ValueError, match="exactly its fields"):
        DecisionOption.from_record({k: v for k, v in talk.items() if k != "partner_id"})
    with pytest.raises(ValueError, match="who it is with"):
        DecisionOption.from_record({**talk, "partner_id": ""})


# -- what a person is offered ---------------------------------------------------------------------


def test_a_conversation_is_offered_with_everybody_the_routine_could_pair_them_with():
    state, document = _square()
    me = _person(state, 2)
    talks = _talks(choice_options(state, document, me["id"], decision_contract(), seed=SEED))
    # Within the talk's eight metres of (0, 10000): the two four metres along the row, and nobody
    # at ten metres or more, so exactly two.
    near = {_person(state, 1)["id"], _person(state, 3)["id"]}
    assert set(talks) == near
    for partner_id, option in talks.items():
        partner = next(p for p in state["inhabitants"] if p["id"] == partner_id)
        assert option.label == f"talk with person {partner['ordinal'] + 1}, 4 m away"
        assert option.walk_mm == 4000
        assert option.activity == routine_of(document).in_setting("pair").key
        # No name of anybody is in what a model reads: only the number their name ends with.
        for part in partner["display_name"].split():
            if part.isalpha():
                assert part.lower() not in re.findall(r"[a-z]+", option.label)


def test_nobody_on_their_way_somewhere_or_tired_and_sitting_nothing_out_is_offered_to_talk_with():
    state, document = _square()
    me = _person(state, 2)
    # One neighbour is on their way somewhere; the other is tired enough to want a rest first.
    _walking(state, document, 1, _node(-4000, 8000))
    _person(state, 3)["need_milli"] = 900
    assert _talks(choice_options(state, document, me["id"], decision_contract(), seed=SEED)) == {}
    # The positive control: tired but standing a while, the routine may still join them there.
    _standing(state, document, 3)
    talks = _talks(choice_options(state, document, me["id"], decision_contract(), seed=SEED))
    assert set(talks) == {_person(state, 3)["id"]}


def test_a_person_tired_enough_to_rest_may_still_be_offered_to_talk_and_to_stand():
    """The model replaces the routine's preference that a tired person rests first, as it does for
    places, and is shown how tired they are; what can be done stays the routine's."""
    state, document = _square()
    me = _person(state, 2)
    me["need_milli"] = 900
    kinds = {
        option.kind
        for option in choice_options(state, document, me["id"], decision_contract(), seed=SEED)
    }
    assert {"talk", "stand", "wait"} <= kinds


def test_standing_is_offered_where_the_routine_finds_room_and_the_first_routine_has_none():
    state, document = _square()
    me = _person(state, 2)
    options = choice_options(state, document, me["id"], decision_contract(), seed=SEED)
    (stand,) = [option for option in options if option.kind == "stand"]
    assert stand.label == decision_contract().words["stand"]
    assert stand.activity == routine_of(document).in_setting("open").key
    # Over an input read under the routine first released, nobody stands or talks, and so no model
    # is offered either: that routine chooses the nearest place.
    older = square.compose(square.square_objects(), v2=True)
    assert routine_of(older).in_setting("open") is None
    state, older = _square(document=older)
    kinds = {
        option.kind
        for option in choice_options(state, older, me["id"], decision_contract(), seed=SEED)
    }
    assert kinds and kinds <= {"target", "wait"}


def test_the_first_contract_never_offers_standing_or_talking():
    state, document = _square()
    for person in state["inhabitants"]:
        kinds = {
            option.kind
            for option in choice_options(
                state, document, person["id"], decision_contract(V1), seed=SEED
            )
        }
        assert kinds <= {"target", "wait"}


def test_a_person_with_nothing_but_waiting_to_do_is_not_asked():
    state, document = _square()
    me = _person(state, 2)
    contract = decision_contract()
    request, status = person_request(
        state,
        document,
        me["id"],
        request_id=uuid.uuid4(),
        contract=contract,
        seed=SEED,
        provider_config=_config(contract),
        offer=lambda options: [o for o in options if o.kind == "wait"],
    )
    assert (request, status) == (None, "nothing_to_choose")
    # The positive control: standing and waiting are a choice.
    request, status = person_request(
        state,
        document,
        me["id"],
        request_id=uuid.uuid4(),
        contract=contract,
        seed=SEED,
        provider_config=_config(contract),
        offer=lambda options: [o for o in options if o.kind in ("wait", "stand")],
    )
    assert status == "in_progress" and len(request["context"]["options"]) == 2


def test_the_nearest_actions_are_kept_to_the_bound_with_standing_and_waiting_always_among_them():
    state, document = _square()
    me = _person(state, 2)
    contract = decision_contract()
    everything = choice_options(state, document, me["id"], contract, seed=SEED)
    bounded = dict(contract.policy, options_maximum=4)
    narrow = type(contract)(
        words=contract.words,
        action_keys=contract.action_keys,
        policy=bounded,
        versions=contract.versions,
        sha256=contract.sha256,
    )
    kept = choice_options(state, document, me["id"], narrow, seed=SEED)
    assert len(everything) > 4 and len(kept) == 4
    assert {"stand", "wait"} <= {option.kind for option in kept}
    walks = sorted(o.walk_mm for o in everything if o.kind in ("target", "talk"))
    assert sorted(o.walk_mm for o in kept if o.kind in ("target", "talk")) == walks[:2]


# -- what the minute does with a choice -----------------------------------------------------------


def test_a_chosen_conversation_is_the_routines_own_talk_with_the_models_reason():
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    receipt = _receipt(_request(state, document, me["id"]), 1, _talk_with(partner))
    policies, decided, after, events = _minute(state, document, [receipt])
    assert [(d.disposition, d.reason) for d in decided] == [("applied", "validated_choice")]
    policy = policies[me["id"]]
    assert (policy["partner_id"], policy["chosen_by"]) == (partner["id"], CHOSEN_BY_MODEL)
    assert partner["id"] not in policies, "the other person is not decided for by the model"
    mine, theirs = _person(after, 2), _person(after, 3)
    assert mine["goal"]["kind"] == "talk" and mine["goal"]["partner_id"] == partner["id"]
    assert mine["goal"]["reason"] == "chosen_by_their_model"
    assert theirs["goal"]["kind"] == "talk" and theirs["goal"]["partner_id"] == me["id"]
    assert theirs["goal"]["reason"] == "stopped_to_talk"
    assert mine["goal"]["duration_ticks"] == theirs["goal"]["duration_ticks"]
    assert mine["route"]["destination_node_id"] == policy["place_node_id"]
    assert theirs["route"]["destination_node_id"] == policy["partner_node_id"]
    (applied,) = [e for e in events if e.kind == "decision_applied"]
    assert applied.document["chose"] == receipt["proposal"]["label"]
    # They meet and talk, as the routine's own talkers do.
    state = after
    for _ in range(6):
        state, _ = advance_purposeful_society(state, SEED, [document])
        if all(_person(state, o)["action"]["reason"] == "talking" for o in (2, 3)):
            break
    assert all(_person(state, o)["action"]["kind"] == "talk" for o in (2, 3))
    assert all(_person(state, o)["action"]["reason"] == "talking" for o in (2, 3))


def test_a_partner_somebody_decided_for_that_minute_is_busy_whoever_asked_first():
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    talk = _receipt(_request(state, document, me["id"]), 1, _talk_with(partner))
    # Their owner asked them to go somewhere themselves.
    directed = {partner["id"]: {"allowed_target_ids": [], "wait": True}}
    _, decided, _, _ = _minute(state, document, [talk], directed)
    assert [(d.disposition, d.reason) for d in decided] == [("rejected", "partner_busy")]
    # Their own model chose to stand, in a receipt recorded after the choice to talk with them:
    # a person's own choice comes before another's choice to talk with them.
    own = _receipt(_request(state, document, partner["id"]), 2, lambda o: o["kind"] == "stand")
    policies, decided, _, _ = _minute(state, document, [talk, own])
    assert [(d.disposition, d.reason) for d in decided] == [
        ("rejected", "partner_busy"),
        ("applied", "validated_choice"),
    ]
    assert policies[partner["id"]]["activity"] == "stand"
    assert me["id"] not in policies


def test_a_partner_who_can_no_longer_stop_to_talk_is_refused_by_name():
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    option = DecisionOption.from_record(
        next(
            o
            for o in _request(state, document, me["id"])["context"]["options"]
            if o["kind"] == "talk" and o["partner_id"] == partner["id"]
        )
    )
    assert isinstance(recheck_talk(state, document, me["id"], option, set(), ()), TalkPromise)
    moved = copy.deepcopy(state)
    far = _person(moved, 3)
    far["location"] = {"node_id": _node(10000, 2000), "edge": None}
    far["position_mm"] = [10000, 2000]
    assert recheck_talk(moved, document, me["id"], option, set(), ()) == "partner_not_free"
    walking = copy.deepcopy(state)
    _walking(walking, document, 3, _node(4000, 8000))
    assert recheck_talk(walking, document, me["id"], option, set(), ()) == "partner_not_free"
    gone = copy.deepcopy(state)
    gone["inhabitants"] = [p for p in gone["inhabitants"] if p["ordinal"] != 3]
    assert recheck_talk(gone, document, me["id"], option, set(), ()) == "partner_not_free"
    assert recheck_talk(state, document, me["id"], option, set(), {partner["id"]}) == "partner_busy"


def test_no_room_to_talk_or_to_stand_is_refused_by_name():
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    options = {
        o["kind"]: DecisionOption.from_record(o)
        for o in _request(state, document, me["id"])["context"]["options"]
        if o["kind"] in ("stand", "talk") and o.get("partner_id") in (None, partner["id"])
    }
    everywhere = {node["node_id"] for node in document["navigation"]["nodes"]}
    assert (
        recheck_talk(state, document, me["id"], options["talk"], everywhere, ())
        == "no_room_to_talk"
    )
    assert recheck_option(state, document, me["id"], options["stand"], everywhere) == (
        "no_room_to_stand",
        None,
    )
    # The positive control: with nothing promised, both hold.
    refused, spot = recheck_option(state, document, me["id"], options["stand"], set())
    assert refused is None and spot not in standing_exclusions(document)


def test_two_people_whose_models_chose_each_other_talk_together():
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    mine = _receipt(_request(state, document, me["id"]), 1, _talk_with(partner))
    theirs = _receipt(_request(state, document, partner["id"]), 2, _talk_with(me))
    policies, decided, after, _ = _minute(state, document, [mine, theirs])
    assert [(d.disposition, d.reason) for d in decided] == [("applied", "validated_choice")] * 2
    assert policies[partner["id"]]["partner_id"] == me["id"]
    assert policies[partner["id"]]["place_node_id"] == policies[me["id"]]["partner_node_id"]
    for ordinal, other in ((2, partner), (3, me)):
        person = _person(after, ordinal)
        assert person["goal"]["partner_id"] == other["id"]
        assert person["goal"]["reason"] == "chosen_by_their_model"


def test_a_partner_whose_own_model_chose_to_talk_with_somebody_else_is_busy_whoever_asked_first():
    state, document = _square()
    first, partner, third = _person(state, 2), _person(state, 3), _person(state, 4)
    for order in ((1, 2), (2, 1)):
        asked = _receipt(_request(state, document, first["id"]), order[0], _talk_with(partner))
        own = _receipt(_request(state, document, partner["id"]), order[1], _talk_with(third))
        receipts = sorted([asked, own], key=lambda receipt: receipt["decision_seq"])
        policies, decided, after, _ = _minute(state, document, receipts)
        outcome = {d.subject_id: (d.disposition, d.reason) for d in decided}
        assert outcome[first["id"]] == ("rejected", "partner_busy"), order
        assert outcome[partner["id"]] == ("applied", "validated_choice"), order
        assert policies[partner["id"]]["partner_id"] == third["id"]
        assert _person(after, 3)["goal"]["partner_id"] == third["id"]
        assert first["id"] not in policies


def test_a_chosen_stand_is_taken_at_the_routines_own_spot_and_the_person_stands():
    state, document = _square()
    me = _person(state, 2)
    receipt = _receipt(_request(state, document, me["id"]), 1, lambda o: o["kind"] == "stand")
    policies, decided, after, _ = _minute(state, document, [receipt])
    assert [(d.disposition, d.reason) for d in decided] == [("applied", "validated_choice")]
    spot = policies[me["id"]]["place_node_id"]
    # Within the routine's standing reach of where they were, and clear of every place.
    x, z = (int(part) for part in spot.split(":")[1:])
    reach = routine_of(document).in_setting("open").reach_mm
    assert (x - me["position_mm"][0]) ** 2 + (z - me["position_mm"][1]) ** 2 <= reach**2
    assert spot not in standing_exclusions(document)
    person = _person(after, 2)
    assert person["goal"] == {"kind": "stand", "target_id": None, "reason": "chosen_by_their_model"}
    state = after
    for _ in range(4):
        if _person(state, 2)["action"]["kind"] == "stand":
            break
        state, _ = advance_purposeful_society(state, SEED, [document])
    assert _person(state, 2)["action"]["reason"] == "standing_a_while"
    assert _person(state, 2)["location"]["node_id"] == spot


def test_a_promise_the_minute_no_longer_has_room_for_stops_the_chooser_by_name():
    """An edit and its undo inside one minute can move somebody before anybody chooses. A spot
    promised before the minute that somebody else then holds is never shared: the one whose
    model chose it is stopped by name, and the other person is left to their routine."""
    state, document = _square()
    me, partner, other = _person(state, 2), _person(state, 3), _person(state, 1)
    # Somebody standing a while keeps their spot through the minute.
    _standing(state, document, 1)
    held = other["location"]["node_id"]
    stand = {"allowed_target_ids": [], "activity": "stand", "place_node_id": held}
    stand["chosen_by"] = CHOSEN_BY_MODEL
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy={me["id"]: stand})
    assert _person(after, 2)["action"]["reason"] == "route_invalidated"
    talk = option_goal_policy(
        DecisionOption("x", "talk", "talk", None, "talk", None, partner["id"]),
        TalkPromise(partner["id"], held, partner["location"]["node_id"], 3),
    )
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy={me["id"]: talk})
    assert _person(after, 2)["action"]["reason"] == "route_invalidated"
    assert (_person(after, 3)["goal"] or {}).get("partner_id") != me["id"]
    # The positive control: promised a spot nobody holds, the same conversation starts.
    free = TalkPromise(partner["id"], _node(2000, 10000), partner["location"]["node_id"], 3)
    talk = option_goal_policy(
        DecisionOption("x", "talk", "talk", None, "talk", None, partner["id"]), free
    )
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy={me["id"]: talk})
    assert _person(after, 2)["goal"]["partner_id"] == partner["id"]


def test_every_reason_the_planner_records_for_these_choices_is_one_it_states():
    assert {"chosen_by_their_model", "stopped_to_talk", "route_invalidated"} <= REASON_CODES


# -- replay --------------------------------------------------------------------------------------


def _played(seed, minutes, choose):
    """``minutes`` of the square with every person run by a scripted model, receipt by receipt."""
    contract = decision_contract()
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(
        square.SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    start, sequence, minutes_played = state, 0, []
    for _ in range(minutes):
        receipts = []
        for person in sorted(state["inhabitants"], key=lambda held: held["id"]):
            request, _status = person_request(
                state,
                document,
                person["id"],
                request_id=uuid.uuid5(square.SOCIETY, f"{person['id']}:{state['tick']}"),
                contract=contract,
                seed=seed,
                provider_config=_config(contract),
            )
            if request is None:
                continue
            sequence += 1
            options = request["context"]["options"]
            picked = choose(random.Random(f"{seed}:{state['tick']}:{person['id']}"), options)
            receipts.append(_receipt(request, sequence, lambda o, picked=picked: o == picked))
        _p, _d, after, events = _minute(state, document, receipts)
        minutes_played.append(
            (receipts, society_state_sha256(after), ordered_events_document(events))
        )
        state = after
    return start, document, minutes_played


def _prefer_talk(rng, options):
    talks = [o for o in options if o["kind"] == "talk"]
    return rng.choice(talks or options)


def test_a_played_hour_of_standing_and_talking_replays_byte_for_byte_with_nothing_asked():
    start, document, minutes = _played(SEED, 60, _prefer_talk)
    kinds = {
        receipt["proposal"]["option"]["kind"] for receipts, _, _ in minutes for receipt in receipts
    }
    assert {"talk", "stand"} & kinds, "the hour chose neither, so it shows nothing"
    # Replayed from the stored receipts alone: no request is built and no model is asked.
    state = start
    talked = 0
    for receipts, digest, events in minutes:
        _p, _d, state, replayed = _minute(state, document, receipts)
        assert society_state_sha256(state) == digest
        assert ordered_events_document(replayed) == events
        talked += sum(1 for e in replayed if e.document["outcome"] == "talk_started")
    assert talked > 0


# -- what was there before -------------------------------------------------------------------------

#: Digests of the square played by its routine alone over four development seeds for 120 minutes,
#: and with every person run by a scripted model under the first contract over two more for 60,
#: taken on the tree before the second contract existed (fbc735a4, with the capture this file's
#: ``_digests`` repeats). A change that moves the routine, or the first contract's options,
#: policies or events, moves one of them.
BEFORE_THE_SECOND_CONTRACT = {
    "routine": {
        "768df339d126513717b4c381dc44451e7bed1de0f06e4727fbcd02e9afa371a7": (
            "f712a833f81a17bd2b8b473e9d5e3d53d3c74ecb9ea00eb10ffe116697b8886e",
            "9bcd06d5b2dab19ac68b5a180bf9767f9816e1b50890df8541b5dda759281a22",
        ),
        "a3db77e1deb7be778f69bbfbb5603b2f65a92fdf3f5b13a0dc85c4d1618879d9": (
            "edd6f62079dc2a080b71afab096742cd0bb63b3bcb4a07f9da2806910baf70b4",
            "18236b675dc0ffddb1d13f4cfd5fd82106c5d421d4172174d476a86d1ce414f9",
        ),
        "d79b78076211a98006e80c88c81feb9e36232099c2aa63884215fded7f564081": (
            "54672ecf670f427271d6ff4ca13d830418ba8ebc8d2cd273572dd23e12aa8f39",
            "cebf3da726175c53e950e9ad33933ce621a35b3de8ce1fa702f0b0288d7072e3",
        ),
        "f00cd6ccf42a1d2c42141bd5de38cfd45942ee40abce26228034b677c1312d96": (
            "9b4d01ed329dcb0ec3dc65476bc308b0dd0fe79cb3ae7dc7d74517bd7e35f75b",
            "23430c79b4e00ab07c686412b00129f1db861ca716789f9f4313551f7c648462",
        ),
    },
    "first_contract": {
        "6a736404de6c282792195ff30f8cce0360aa2444440f8f7eb5fa0551500294a3": {
            "requests": 72,
            "requests_sha256": "383586a6feeaad0dce08dff1d267026e1d7bef5eb9d276ec2a643509407bc856",
            "dispositions_sha256": (
                "a1ab798d71ad80230dfe1928c3118c07dcaf899c291f1fbe9130f01c0060a4bc"
            ),
            "states_sha256": "ae0aa01d8a29e452ada6bea54320a8100b11d1d013c6f75be01d1553a3e6e1f1",
            "events_sha256": "ca6a2e2cab0269198e9bbe8f45b69d87b16c7323229549166a215e8b2930f655",
        },
        "d7ce9415a7b8628e4ed27bee1a321583a5da01b072e6188e382a5b0f3d99d5b0": {
            "requests": 65,
            "requests_sha256": "96a716ad6899194cbd58726a97e589902362c44c460e42c7f8100103da0db7bb",
            "dispositions_sha256": (
                "fdeb1fae1c3886e96b97db69fe8c2c4ee016e23681cd96207e61dd88d80f9c72"
            ),
            "states_sha256": "01fc8d8b286c4b5076027b9a0aa004e8672fba8c0ecd423173e7ec0860e00f57",
            "events_sha256": "09c495edd5c2edcef083091bdddd1675bc3730774745655e279369898bfa4df9",
        },
    },
}


def _routine_digests(seed, minutes=120):
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(
        square.SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    states, events = [society_state_sha256(state)], []
    for _ in range(minutes):
        state, minute = advance_purposeful_society(state, seed, [document])
        states.append(society_state_sha256(state))
        events.append(society_state_sha256(ordered_events_document(minute)))
    return society_state_sha256(states), society_state_sha256(events)


@pytest.mark.parametrize("seed", sorted(BEFORE_THE_SECOND_CONTRACT["routine"]))
def test_a_society_with_no_model_choices_is_the_one_it_was_before(seed):
    assert _routine_digests(seed) == BEFORE_THE_SECOND_CONTRACT["routine"][seed]


#: What the capture's scripted model records of its calls: nothing a replay reads.
_CAPTURED_CALL = {
    "provider": "nebius_token_factory",
    "model_id": "scripted/model",
    "served_model_id": "scripted/model",
    "mechanism": "tool_call",
    "prompt_version": "society-person-choice/v1",
    "messages_sha256": "0" * 64,
    "answers_asked": 1,
    "calls": [],
    "prompt_tokens": 1,
    "completion_tokens": 1,
    "cost_usd": "0",
    "cost_known": True,
    "latency_ms": 1,
}


def _first_contract_digests(seed, minutes=60):
    """Every person run by a scripted model under the first contract, a receipt each choice, as
    the capture before the second contract ran it."""
    contract = decision_contract(V1)
    document = square.compose(square.square_objects())
    state = initial_purposeful_society(
        square.SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    config = {
        "provider": "nebius_token_factory",
        "model_id": "scripted/model",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "0" * 64,
        "prompt_version": "society-person-choice/v1",
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    sequence = 0
    states, events, dispositions, requests = [society_state_sha256(state)], [], [], []
    for _ in range(minutes):
        receipts = []
        for person in sorted(state["inhabitants"], key=lambda held: held["id"]):
            request, _status = person_request(
                state,
                document,
                person["id"],
                request_id=uuid.uuid5(square.SOCIETY, f"{person['id']}:{state['tick']}"),
                contract=contract,
                seed=seed,
                provider_config=config,
            )
            if request is None:
                continue
            requests.append(request["document_sha256"])
            options = request["context"]["options"]
            chosen = random.Random(f"{seed}:{state['tick']}:{person['id']}").choice(options)
            sequence += 1
            receipts.append(
                receipt_for(
                    request,
                    sequence,
                    {
                        "status": "accepted",
                        "reason": "validated_choice",
                        "proposal": {"label": chosen["label"], "option": chosen},
                        "provider": _CAPTURED_CALL,
                    },
                )
            )
        previous = state
        policies, decided = model_goal_policies(state, document, receipts, {})
        state, minute = advance_purposeful_society(state, seed, [document], goal_policy=policies)
        minute = append_decision_events(previous, state, document, receipts, decided, minute)
        dispositions.extend((d.decision_seq, d.disposition, d.reason) for d in decided)
        states.append(society_state_sha256(state))
        events.append(society_state_sha256(ordered_events_document(minute)))
    return {
        "requests": len(requests),
        "requests_sha256": society_state_sha256(requests),
        "dispositions_sha256": society_state_sha256([list(d) for d in dispositions]),
        "states_sha256": society_state_sha256(states),
        "events_sha256": society_state_sha256(events),
    }


@pytest.mark.parametrize("seed", sorted(BEFORE_THE_SECOND_CONTRACT["first_contract"]))
def test_the_first_contracts_requests_and_decisions_are_the_ones_they_were_before(seed):
    assert _first_contract_digests(seed) == BEFORE_THE_SECOND_CONTRACT["first_contract"][seed]


# -- an ask that ends in an error nothing names ---------------------------------------------------


class _Unnamed(Exception):
    """An error no model error names, as a defect in a client or a library raises."""


#: Text such an error may carry, which a log must never hold: request bytes, or a credential.
_CARRIED = "request bytes and a key-shaped secret"


def _ask_of(model_id):
    state, document, contract, offered = asks._minute_with_choices()
    subject, options = next(iter(offered.items()))
    return asks._request(state, document, subject, options, model=model_id), contract


def _logged(caplog):
    return [record.getMessage() for record in caplog.records]


def test_an_ask_ending_in_an_error_nothing_names_logs_its_class_and_never_its_text(caplog):
    manifest, model_id = asks._offered_manifest()
    request, contract = _ask_of(model_id)
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=FakeTransport([_Unnamed(_CARRIED)]),
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10),
        policy=RecordingPolicy(),
    )
    result = ask_person(
        client,
        PersonAsk(request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL),
        contract,
        time.monotonic() + 20.0,
    )
    assert (result["status"], result["reason"]) == ("unavailable", "model_call_failed")
    logged = _logged(caplog)
    assert any(f"{__name__}._Unnamed" in line for line in logged), logged
    assert not any(_CARRIED in line for line in logged)
    assert all(record.exc_info is None for record in caplog.records)


def test_an_ask_that_raises_past_its_own_record_logs_its_class_and_never_its_text(
    caplog, monkeypatch
):
    manifest, model_id = asks._offered_manifest()
    request, contract = _ask_of(model_id)

    def raises(*_args, **_kwargs):
        raise _Unnamed(_CARRIED)

    monkeypatch.setattr(host_module, "ask", raises)
    ask = RoleAsk(person_role(), request, manifest.spec(model_id), AnsweringMechanism.TOOL_CALL)
    ((request_id, result),) = DecisionHost._ask(
        None, None, [ask], contract, time.monotonic() + 20.0, Decimal("1"), 0
    )
    assert str(request_id) == request["request_id"]
    assert (result["status"], result["reason"]) == ("unavailable", "model_call_failed")
    logged = _logged(caplog)
    assert any(f"{__name__}._Unnamed" in line for line in logged), logged
    assert not any(_CARRIED in line for line in logged)


def test_the_routines_own_pairs_never_take_a_spot_a_policy_promised():
    from exulanica.world.society_planner import _graph, _paths, _talk_pairs

    document = square.compose(square.square_objects())
    routine = routine_of(document)
    talk = routine.in_setting("pair")
    graph = _graph(document)

    def pairs_at(state, policies):
        return _talk_pairs(
            state["inhabitants"],
            routine,
            talk,
            graph,
            standing_exclusions(document),
            policies,
            lambda start: _paths(start, graph[1]),
            SEED,
            state["tick"] + 1,
        )

    state = initial_purposeful_society(
        square.SOCIETY, SEED, document, population=AUTHORED_GROUND_POPULATION
    )
    for _ in range(120):
        found = pairs_at(state, {})
        if found:
            break
        state, _ = advance_purposeful_society(state, SEED, [document])
    else:
        raise AssertionError("the routine paired nobody in two hours")
    # The positive control: with nothing promised, the routine takes this spot.
    _talker, pair = sorted(found.items())[0]
    spot = pair["node_id"]
    bystander = next(p["id"] for p in state["inhabitants"] if p["id"] not in found)
    promised = {bystander: {"allowed_target_ids": [], "place_node_id": spot}}
    assert spot not in {pair["node_id"] for pair in pairs_at(state, promised).values()}


def test_standing_is_not_offered_when_every_spot_within_reach_is_held():
    """A person in the square's corner: the eleven lattice nodes within the six metres standing
    reaches are their own and ten more. Seven people stand on seven of them and four of those are
    on their way to the rest, their own node included, so the routine finds nowhere to stand."""
    corner = {
        0: (-10000, 10000),
        1: (-10000, 8000),
        2: (-10000, 6000),
        3: (-10000, 4000),
        4: (-8000, 10000),
        5: (-8000, 8000),
        6: (-8000, 6000),
        7: (-6000, 10000),
    }
    state, document = _square(corner)
    me = _person(state, 0)
    for ordinal, to in zip(
        (1, 2, 3, 4),
        (_node(-6000, 8000), _node(-6000, 6000), _node(-4000, 10000), _node(-10000, 10000)),
        strict=True,
    ):
        _walking(state, document, ordinal, to)
    kinds = {
        option.kind
        for option in choice_options(state, document, me["id"], decision_contract(), seed=SEED)
    }
    assert "target" in kinds and "stand" not in kinds
    # The positive control: with nobody on their way, four of those spots are open again.
    state, document = _square(corner)
    kinds = {
        option.kind
        for option in choice_options(state, document, me["id"], decision_contract(), seed=SEED)
    }
    assert "stand" in kinds


# -- the answering order a measurement chose for a model -------------------------------------------

PROBE = "docs/evaluation/2026-09-26-society-model-actions-probe.json"


def _manifest_with(order):
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    if order is None:
        document["models"][model_id].pop("answering_order", None)
    else:
        document["models"][model_id]["answering_order"] = order
    return parse_manifest(document), model_id


@pytest.mark.parametrize(
    ("order", "refusal"),
    [
        ({"mechanisms": ["json_schema"], "record": PROBE}, "states exactly"),
        ({"mechanisms": [], "record": PROBE, "reason": "why"}, "at least one mechanism"),
        ({"mechanisms": ["fax"], "record": PROBE, "reason": "why"}, "not a mechanism"),
        (
            {"mechanisms": ["json_schema", "json_schema"], "record": PROBE, "reason": "why"},
            "twice",
        ),
        ({"mechanisms": ["json_schema"], "record": "notes.txt", "reason": "why"}, "record"),
        ({"mechanisms": ["json_schema"], "record": PROBE, "reason": " "}, "says why"),
    ],
    ids=["fields", "empty", "unknown", "twice", "record", "reason"],
)
def test_an_answering_order_is_refused_by_name_unless_it_is_measured_data(order, refusal):
    with pytest.raises(ManifestError, match=refusal):
        _manifest_with(order)


def test_an_answering_order_names_only_mechanisms_the_model_is_verified_for():
    from exulanica.models.errors import ManifestError

    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = "Qwen/Qwen3-235B-A22B-Instruct-2507"
    document["models"][model_id]["answering"] = {"tool_call": PROBE}
    document["models"][model_id]["answering_order"] = {
        "mechanisms": ["json_schema", "tool_call"],
        "record": PROBE,
        "reason": "why",
    }
    with pytest.raises(ManifestError, match="does not verify"):
        parse_manifest(document)


def test_a_model_is_asked_in_its_own_measured_order_and_otherwise_in_the_contracts():
    contract = decision_contract()
    plain, model_id = _manifest_with(None)
    assert str(contract.mechanism_for(plain.spec(model_id))) == "tool_call"
    ordered, _ = _manifest_with(
        {"mechanisms": ["json_schema", "tool_call"], "record": PROBE, "reason": "why"}
    )
    assert str(contract.mechanism_for(ordered.spec(model_id))) == "json_schema"
    # The host asks by the same rule.
    askable = host_module._askable(person_role(), ordered, contract, model_id)
    assert askable is not None and str(askable[1]) == "json_schema"


def test_the_manifests_answering_orders_are_the_ones_the_probes_rules_selected():
    record = json.loads(Path(PROBE).read_text(encoding="utf-8"))["record"]
    manifest = load_manifest()
    offered = {spec.model_id: spec for spec in manifest.offered_models(person_role().chosen)}
    # A positive control: the probe asked every offered model, and selected an order for one.
    assert set(record["models"]) == set(offered)
    assert any(found["answering_order_selected"] for found in record["models"].values())
    for model_id, found in record["models"].items():
        spec = offered[model_id]
        selected = found["answering_order_selected"] or []
        assert [str(m) for m in spec.answering_order] == selected
        if selected:
            assert spec.answering_order_record == PROBE
            # The figures the reason states are the record's.
            for mechanism in selected:
                median = found["figures"][mechanism]["completion_tokens"]["median"]
                assert median in spec.answering_order_reason
        # No attempt bound was selected, so none is built.
        assert found["attempt_bound_ms_selected"] is None


# -- what the Companion says of a conversation a model chose --------------------------------------


def test_the_companion_line_for_a_conversation_a_model_chose_names_the_model_and_the_other():
    from exulanica.selection.inhabitant_words import inhabitant_words_catalog
    from exulanica.selection.society_question import SocietyScene, _Builder

    chooser, partner = str(uuid.uuid4()), str(uuid.uuid4())
    scene = SocietyScene(
        society_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        profile="exulanica-society/v2",
        tick=9,
        people={
            chooser: {"id": chooser, "display_name": "Bela Ash 2"},
            partner: {"id": partner, "display_name": "Emi Ash 5"},
        },
        usable_targets=frozenset(),
        events=(),
        explaining={},
        selected=None,
        deciding_models={(7, chooser): "Model A"},
    )
    catalog = inhabitant_words_catalog()
    goal = {"kind": "talk", "target_id": None, "reason": "chosen_by_their_model"}
    event = {
        "event_id": str(uuid.uuid4()),
        "tick": 7,
        "event_kind": "goal_selected",
        "subject_id": chooser,
        "document": {
            "outcome": "goal_selected",
            "reason": "chosen_by_their_model",
            "goal": {**goal, "partner_id": partner, "duration_ticks": 4},
        },
    }
    line = _Builder(scene, catalog).event(event).line
    named = catalog.words("line", "chosen_model").format(line="", model="Model A").strip()
    with_partner = catalog.words("line", "with_partner").format(
        line="", partner=scene.labels.person(partner)
    )
    assert named in line and line.endswith(with_partner.strip())
    # The positive control: a goal to talk nobody's model chose names no model.
    event["document"] = {**event["document"], "reason": "stopped_to_talk"}
    assert "Model A" not in _Builder(scene, catalog).event(event).line


# -- judged as the minute has it ------------------------------------------------------------------


def _rest_threshold(document):
    """The need at which the routine sends somebody to rest before anything else."""
    return min(
        a.preferred_at_need
        for a in routine_of(document).activities.values()
        if a.preferred_at_need > 0
    )


def test_a_partner_is_judged_by_the_need_the_minute_gives_them_at_the_exact_threshold():
    """The routine grows everybody's need by a minute before it pairs anybody, so somebody one
    short of the rest threshold is already tired when it would pair them."""
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    threshold = _rest_threshold(document)
    contract = decision_contract()
    option = DecisionOption.from_record(
        next(
            o
            for o in _request(state, document, me["id"])["context"]["options"]
            if o["kind"] == "talk" and o["partner_id"] == partner["id"]
        )
    )
    partner["need_milli"] = threshold - 1
    assert partner["id"] not in _talks(
        choice_options(state, document, me["id"], contract, seed=SEED)
    )
    assert recheck_talk(state, document, me["id"], option, set(), ()) == "partner_not_free"
    # The positive control: two short, the minute leaves them one short, and they may talk.
    partner["need_milli"] = threshold - 2
    assert partner["id"] in _talks(choice_options(state, document, me["id"], contract, seed=SEED))
    assert isinstance(recheck_talk(state, document, me["id"], option, set(), ()), TalkPromise)


def test_the_minute_itself_keeps_no_conversation_whose_other_person_is_no_longer_free():
    """Promised before the minute, a conversation is checked again as the minute stands: somebody
    an edit inside the minute set walking is not pulled into it, and the chooser is stopped."""
    state, document = _square()
    me, partner = _person(state, 2), _person(state, 3)
    promise = TalkPromise(partner["id"], _node(2000, 10000), partner["location"]["node_id"], 3)
    talk = option_goal_policy(
        DecisionOption("x", "talk", "talk", None, "talk", None, partner["id"]), promise
    )
    _walking(state, document, 3, _node(4000, 8000))
    after, _ = advance_purposeful_society(state, SEED, [document], goal_policy={me["id"]: talk})
    assert _person(after, 2)["action"]["reason"] == "route_invalidated"
    assert (_person(after, 3)["goal"] or {}).get("partner_id") != me["id"]


def _independent_stand_spots(state, document, person):
    """Where the routine lets ``person`` stand, worked out here from the input and the state by
    identity, not through the contract: open nodes of the lattice within the standing reach that
    they can walk to and that nobody else stands at or is headed to."""
    from exulanica.world.society_planner import _paths

    positions = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    adjacent = {node: [] for node in positions}
    for edge in document["navigation"]["edges"]:
        adjacent[edge["from_node_id"]].append((edge["to_node_id"], edge))
        adjacent[edge["to_node_id"]].append((edge["from_node_id"], edge))
    location = person["location"]
    start = location["node_id"] if location["edge"] is None else location["edge"]["to_node_id"]
    paths = _paths(start, adjacent)
    held = set()
    for other in state["inhabitants"]:
        if other["id"] == person["id"]:
            continue
        if other["goal"] is not None and other["route"] is not None:
            held.add(other["route"]["destination_node_id"])
        if other["location"]["edge"] is None:
            held.add(other["location"]["node_id"])
    reach = routine_of(document).in_setting("open").reach_mm
    x, z = person["position_mm"]
    return sorted(
        node
        for node, (nx, nz) in positions.items()
        if adjacent[node]
        and node not in standing_exclusions(document)
        and node not in held
        and node in paths
        and (nx - x) ** 2 + (nz - z) ** 2 <= reach**2
    )


def test_where_a_person_may_stand_is_the_list_the_routine_draws_from():
    from exulanica.world.society_decision_contract import places_to_stand

    checked = 0
    for seed in square.DEVELOPMENT_SEEDS[:3]:
        document = square.compose(square.square_objects())
        state = initial_purposeful_society(
            square.SOCIETY, seed, document, population=AUTHORED_GROUND_POPULATION
        )
        for _ in range(30):
            for person in state["inhabitants"]:
                if person["goal"] is None or person["action"]["status"] == "completed":
                    expected = _independent_stand_spots(state, document, person)
                    assert places_to_stand(state, document, person["id"]) == expected
                    checked += 1
            state, _ = advance_purposeful_society(state, seed, [document])
    # A positive control: people chose often enough to check, some where they stood was a spot.
    assert checked > 50


def test_a_person_whose_only_open_spot_is_where_they_stand_may_stand_there():
    from exulanica.world.society_decision_contract import places_to_stand

    corner = {
        0: (-10000, 10000),
        1: (-10000, 8000),
        2: (-10000, 6000),
        3: (-10000, 4000),
        4: (-8000, 10000),
        5: (-8000, 8000),
        6: (-8000, 6000),
        7: (-6000, 10000),
    }
    state, document = _square(corner)
    me = _person(state, 0)
    # The three other nodes within reach are where three of them are headed; theirs are taken.
    for ordinal, to in zip(
        (1, 2, 3),
        (_node(-6000, 8000), _node(-6000, 6000), _node(-4000, 10000)),
        strict=True,
    ):
        _walking(state, document, ordinal, to)
    here = me["location"]["node_id"]
    assert places_to_stand(state, document, me["id"]) == [here]
    options = choice_options(state, document, me["id"], decision_contract(), seed=SEED)
    (stand,) = [option for option in options if option.kind == "stand"]
    assert recheck_option(state, document, me["id"], stand, set()) == (None, here)


def test_a_request_or_comparison_asked_under_the_first_contract_keeps_its_mechanism():
    """A model's own answering order applies from the policy's second version: anything asked
    under the first recorded the mechanism the policy's order gave, and is asked by it again."""
    manifest = load_manifest()
    first, second = decision_contract(V1), decision_contract()
    nano = manifest.spec("nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B")
    assert nano.answering_order, "the positive control: this model states an order of its own"
    assert str(first.mechanism_for(nano)) == "tool_call"
    assert str(second.mechanism_for(nano)) == "json_schema"
    # The comparison recorded under the first contract names each arm's mechanism, unchanged.
    record = json.loads(
        Path("docs/evaluation/2026-09-26-society-model-comparison-preregistration.json").read_text(
            encoding="utf-8"
        )
    )["record"]
    recorded = decision_contract(record["contract"]["catalog_versions"])
    assert record["candidates"]
    for arm in record["candidates"]:
        assert str(recorded.mechanism_for(manifest.spec(arm["model_id"]))) == arm["mechanism"]


def test_a_policy_offering_fewer_options_than_a_request_needs_is_refused_by_name(monkeypatch):
    import dataclasses

    import exulanica.world.decision_roles as roles_module

    role = person_role()
    loaded = roles_module._catalog

    def reading(maximum):
        def bounded(read_role, catalog_id, version, schema):
            catalog = loaded(read_role, catalog_id, version, schema)
            if catalog_id != read_role.policy_catalog:
                return catalog
            entries = tuple(
                dataclasses.replace(
                    entry,
                    values=tuple(
                        (
                            name,
                            maximum if (entry.key, name) == ("options_maximum", "value") else value,
                        )
                        for name, value in entry.values
                    ),
                )
                for entry in catalog.entries
            )
            return dataclasses.replace(catalog, entries=entries)

        monkeypatch.setattr(roles_module, "_catalog", bounded)
        return roles_module._contract(role, role.contract_versions)

    with pytest.raises(roles_module.ContractError, match="options_maximum is at least 2"):
        reading(1)
    # The positive control: at the fewest, a person is offered standing and waiting alone.
    narrow = reading(2)
    state, document = _square()
    me = _person(state, 2)
    kinds = sorted(o.kind for o in choice_options(state, document, me["id"], narrow, seed=SEED))
    assert kinds == ["stand", "wait"]


def test_two_choices_to_talk_with_one_free_person_never_share_them():
    """Two people's models choose the same person, whom nobody decides for: the first choice
    takes them, and the second finds them busy."""
    state, document = _square()
    left, wanted, right = _person(state, 1), _person(state, 2), _person(state, 3)
    receipts = [
        _receipt(_request(state, document, left["id"]), 1, _talk_with(wanted)),
        _receipt(_request(state, document, right["id"]), 2, _talk_with(wanted)),
    ]
    policies, decided, after, _ = _minute(state, document, receipts)
    assert [(d.disposition, d.reason) for d in decided] == [
        ("applied", "validated_choice"),
        ("rejected", "partner_busy"),
    ]
    assert _person(after, 2)["goal"]["partner_id"] == left["id"]
    assert right["id"] not in policies
