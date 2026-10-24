"""A town's premises told by name from action catalog v12 (``places_named``): where a being stands
at a premises' door or inside one, and a premises it remembers, in the told place catalog's words,
named as the day page names it ("the restaurant at number 6").

A request asked under the eleventh catalog tells them as it always did, so a stored request
rebuilds to the byte; its digest was read on the code before the twelfth catalog. A person playing
is asked under the thirteenth, past every rule, and is told them as a model is. Composed without a
database: the town and its society of things are tests/test_society_things_town_people.py's.
"""

from __future__ import annotations

import copy
import dataclasses
import json
import uuid
from typing import Any

import pytest
from exulanica.world import society_catalogs, society_surroundings
from exulanica.world.decision_roles import LABEL_RULES
from exulanica.world.role_decisions import role_request
from exulanica.world.society_decision_contract import at_choice_point, person_role, situation
from exulanica.world.society_play import play_contract
from exulanica.world.society_recollection import RecollectionBounds, _place_words, remembered
from exulanica.world.society_surroundings import (
    NoticeTerms,
    _inside,
    premises_name,
    surroundings,
    told_places,
)

import test_society_things_town_people as town_people
from living_town_support import before_floor_area

pytestmark = pytest.mark.usefixtures(before_floor_area.__name__)

ELEVENTH = {"society-decision-action": 11, "society-decision-policy": 8}
TWELFTH = {"society-decision-action": 12, "society-decision-policy": 8}
#: The prompt each catalog's requests record.
PROMPTS = {11: "society-person-choice/v9", 12: "society-person-choice/v10"}
#: The eleventh catalog's request for the villager of :func:`_at_the_restaurant`, as the code
#: before the twelfth catalog sealed it.
ELEVENTH_REQUEST_SHA256 = "3c4406f88d82ed68b8849d8c658ca5f007a2d3ed71d54857baf89348ab41f272"
#: A people's first minute of the day: 18:00.
DUSK = 18 * 60
TERMS = NoticeTerms(
    reach_mm=12_000,
    beings_maximum=6,
    things_maximum=6,
    bytes_maximum=4_096,
    hearing_reach_mm=6_000,
    offers_version=1,
    names_as_written=True,
    activity_names_as_written=True,
)


def _at_the_restaurant() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The town's society of things, its first villager free to choose standing at the access
    point of the first restaurant the input names, remembering it and a place the input does not
    name."""
    document = town_people._housed()
    state = copy.deepcopy(town_people._genesis(document))
    restaurant = next(t for t in document["targets"] if t["place"]["label"] == "restaurant")
    nodes = {node["node_id"]: node["position_mm"] for node in document["navigation"]["nodes"]}
    villager = next(
        p for p in state["inhabitants"] if p["came_by"] == "populated" and at_choice_point(p)
    )
    villager["position_mm"] = list(nodes[restaurant["node_id"]])
    villager["location"] = {"node_id": restaurant["node_id"], "edge": None}
    villager["recollection"] = {
        "met": [],
        "places": [
            {
                "target_id": restaurant["target_id"],
                "words": "visiting",
                "first_tick": 0,
                "last_tick": 0,
                "times": 1,
            },
            {
                "target_id": "gone:rest",
                "words": "resting",
                "first_tick": 0,
                "last_tick": 0,
                "times": 1,
            },
        ],
        "handed": [],
        "choices": [],
    }
    return state, document, villager, restaurant


def _request(
    versions: dict[str, int], *, kind: str = "model", day_start: int | None = None
) -> dict:
    state, document, villager, _restaurant = _at_the_restaurant()
    role = person_role()
    contract = (
        play_contract(role, state["profile"]) if kind == "person" else role.contract(versions)
    )
    config = (
        {"kind": "person", "contract": contract.binding()}
        if kind == "person"
        else {
            "provider": "test",
            "model_id": "test",
            "mechanism": "tool_call",
            "choice_seq": 1,
            "manifest_sha256": "0" * 64,
            "prompt_version": PROMPTS[versions[role.action_catalog]],
            "contract": contract.binding(),
            "deadline_ms": contract.value("decision_deadline_ms"),
        }
    )
    request, status = role_request(
        role,
        state,
        document,
        villager["id"],
        request_id=uuid.UUID(int=12),
        contract=contract,
        seed=town_people.SEED,
        provider_config=config,
        day_start=day_start,
    )
    assert status == "in_progress"
    return request


def test_the_premises_a_being_stands_at_is_told_by_its_name_from_the_twelfth_catalog():
    state, document, villager, restaurant = _at_the_restaurant()
    name = premises_name(restaurant)
    assert name == f"restaurant at number {restaurant['place']['address_number']}"
    named = surroundings(
        state, document, villager["id"], dataclasses.replace(TERMS, places_named=True)
    )
    plain = surroundings(state, document, villager["id"], TERMS)
    assert named["at"] == {"words": f"at the {name}", "good_for": "others can visit it"}
    assert plain["at"] == {"words": "visiting", "good_for": "others can visit it"}
    # Everything else the being notices reads as before.
    assert {k: v for k, v in named.items() if k != "at"} == {
        k: v for k, v in plain.items() if k != "at"
    }


def test_a_new_request_tells_the_premises_and_a_stored_eleventh_rebuilds_to_the_byte():
    _state, _document, _villager, restaurant = _at_the_restaurant()
    name = premises_name(restaurant)
    twelfth, eleventh = _request(TWELFTH), _request(ELEVENTH)
    assert twelfth["context"]["surroundings"]["at"]["words"] == f"at the {name}"
    assert [p["words"] for p in twelfth["context"]["remembers"]["places"]] == [
        f"visited the {name}",
        "resting",
    ]
    told = situation(twelfth["context"])
    assert f"Where you stand: at the {name} (others can visit it)." in told
    assert any(f"visited the {name} (" in line for line in told)
    assert eleventh["context"]["surroundings"]["at"]["words"] == "visiting"
    assert [p["words"] for p in eleventh["context"]["remembers"]["places"]] == [
        "visiting",
        "resting",
    ]
    assert eleventh["document_sha256"] == ELEVENTH_REQUEST_SHA256


def test_a_person_playing_is_told_the_town_as_a_model_is():
    role = person_role()
    played = play_contract(role, "exulanica-society/v7")
    assert played.label_rules == set(LABEL_RULES)
    asked = _request(TWELFTH, kind="person", day_start=DUSK)
    model = _request(TWELFTH, day_start=DUSK)
    for key in ("surroundings", "remembers", "world_clock"):
        assert asked["context"][key] == model["context"][key], key
    assert asked["context"]["world_clock"]["day"] == 0


def test_a_remembered_premises_is_told_by_what_the_being_did_there():
    _state, _document, _villager, restaurant = _at_the_restaurant()
    name = premises_name(restaurant)
    state = {
        "day_context": {
            "destinations": [
                {"destination_id": "premises:home", "subject_id": "city.premises:home"}
            ]
        }
    }
    person = {"day_home": "premises:home"}

    def told(activity: str | None, subject: str | None = None) -> str:
        target = {
            **restaurant,
            "activity": activity,
            "subject_id": subject or restaurant["subject_id"],
        }
        entry = {"target_id": target["target_id"], "words": "noted"}
        return _place_words(state, person, entry, {target["target_id"]: target})

    assert told("visit") == f"visited the {name}"
    assert told("eat_out") == f"ate at the {name}"
    assert told("shop") == f"shopped at the {name}"
    assert told("work") == f"worked at the {name}"
    assert told("rest") == f"rested at the {name}"
    assert told("stay_home") == f"was at the {name}"
    assert told("sleep") == f"went to the {name}"
    assert (
        told("stay_home", "city.premises:home")
        == told("eat_at_home", "city.premises:home")
        == "was at home"
    )
    # A place the input names no premises for keeps the words it was noted with.
    unnamed = {k: v for k, v in restaurant.items() if k != "place"}
    entry = {"target_id": unnamed["target_id"], "words": "resting"}
    assert _place_words(state, person, entry, {unnamed["target_id"]: unnamed}) == "resting"
    assert _place_words(state, person, entry, {}) == "resting"


def test_remembering_a_place_by_name_needs_the_input_the_minute_consumed():
    state, document, villager, _restaurant = _at_the_restaurant()
    bounds = RecollectionBounds(
        beings_maximum=8,
        places_maximum=8,
        handed_maximum=8,
        bytes_maximum=4_096,
        choices_maximum=8,
        places_named=True,
    )
    with pytest.raises(ValueError, match="input its minute consumed"):
        remembered(state, villager, bounds)
    assert remembered(state, villager, bounds, document=document)["places"][0]["words"].startswith(
        "visited the "
    )


def test_places_told_in_the_same_words_are_told_once_their_times_added():
    state, document, villager, restaurant = _at_the_restaurant()
    state["tick"] = 10
    twin = {**restaurant, "target_id": restaurant["target_id"] + ":twin"}
    document = {**document, "targets": [*document["targets"], twin]}
    noted = {"first_tick": 0, "words": "visiting", "times": 1}
    villager["recollection"]["places"] = [
        {**noted, "target_id": twin["target_id"], "last_tick": 9, "times": 2},
        {**noted, "target_id": "gone:rest", "last_tick": 8, "words": "resting"},
        {**noted, "target_id": restaurant["target_id"], "last_tick": 7},
    ]
    bounds = RecollectionBounds(
        beings_maximum=8,
        places_maximum=8,
        handed_maximum=8,
        bytes_maximum=4_096,
        choices_maximum=8,
        places_named=True,
    )
    told = remembered(state, villager, bounds, document=document)["places"]
    name = premises_name(restaurant)
    assert [(p["words"], p["times"], p["last_minutes_ago"]) for p in told] == [
        (f"visited the {name}", 3, 1),
        ("resting", 1, 2),
    ]
    # Told as stored, each apart, where the request holds no such rule.
    plain = remembered(state, villager, dataclasses.replace(bounds, places_named=False))
    assert [p["words"] for p in plain["places"]] == ["visiting", "resting", "visiting"]


def test_inside_a_premises_is_told_by_its_name_and_one_s_own_home_as_home():
    _state, _document, _villager, restaurant = _at_the_restaurant()
    name = premises_name(restaurant)
    destinations = [
        {
            "destination_id": "premises:r",
            "subject_id": restaurant["subject_id"],
            "label": "restaurant",
        },
        {"destination_id": "premises:home", "subject_id": "city.premises:home", "label": "home"},
    ]
    state = {"day_context": {"destinations": destinations}}
    targets = {restaurant["target_id"]: restaurant}
    me = {"location": {"destination_id": "premises:r"}, "day_home": "premises:home"}
    assert _inside(state, me, targets, True) == {"words": f"in the {name}"}
    assert _inside(state, me, targets, False) == {"words": "restaurant"}
    home = {**me, "location": {"destination_id": "premises:home"}}
    assert _inside(state, home, targets, True) == {"words": "at home"}
    assert _inside(state, home, targets, False) == {"words": "home"}


def test_the_told_place_catalog_words_every_told_place_once(tmp_path, monkeypatch):
    words = told_places()
    assert words["here_at"] == "at the {place}" and words["remembered_any"] == "went to the {place}"
    source = society_catalogs.ROUTINE_DIRECTORY / "society-told-place.v1.json"
    broken = json.loads(source.read_text())
    broken["entries"] = [e for e in broken["entries"] if e["key"] != "remembered_work"]
    (tmp_path / source.name).write_text(json.dumps(broken))
    monkeypatch.setattr(society_catalogs, "ROUTINE_DIRECTORY", tmp_path)
    society_surroundings.told_places.cache_clear()
    try:
        with pytest.raises(ValueError, match="every told place"):
            society_surroundings.told_places()
    finally:
        society_surroundings.told_places.cache_clear()
