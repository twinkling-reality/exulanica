"""What a being of a society of things notices, built by rule from its society's state.

The expected values come from elsewhere than the module under test: names from the say options
the decision contract builds, offer words from the offers catalog file itself, distances from
positions this file sets, and what a being is doing from actions this file writes.
"""

from __future__ import annotations

import copy
import json

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.errors import CatalogError
from exulanica.things.catalogs import CATALOG_DIRECTORY
from exulanica.world.society_decision_contract import choice_options, person_role
from exulanica.world.society_surroundings import (
    MORE_MAXIMUM,
    NoticeTerms,
    surroundings,
    surroundings_lines,
    withhold,
)
from exulanica.world.society_things import THINGS_PROFILE, initial_things_society

from things_society_support import SEED, SOCIETY, compose, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 2, -2_000, 3_000)
SPIRIT = thing("spirit", "lantern_spirit", 1, 1_000, 3_000)
LANTERN = thing("lantern", "lantern", 1, 1_200, 3_000)
SWORD = thing("sword", "sword", 3, -2_500, 2_000)
TERMS = NoticeTerms(
    reach_mm=20_000,
    beings_maximum=6,
    things_maximum=6,
    bytes_maximum=2_400,
    hearing_reach_mm=8_000,
    offers_version=1,
)


def _offer_words() -> dict[str, str]:
    """Each offer's words as the offers catalog file states them, read here as plain JSON."""
    raw = json.loads((CATALOG_DIRECTORY / "offers.v1.json").read_text(encoding="utf-8"))
    return {entry["key"]: entry["words"] for entry in raw["entries"]}


def _square(population: int = 3):
    """The knight with the lantern spirit 2 m east holding its lantern, the sword at the knight's
    feet, the gate 7 m north, and the square's villagers: the first 3 m east of the knight, the
    next 11 m east, the rest 30 m east. Every position is set here."""
    document = compose((GATE, KNIGHT, SPIRIT, LANTERN, SWORD))
    state = copy.deepcopy(initial_things_society(SOCIETY, SEED, document, population=population))
    people = {p["placed_id"]: p for p in state["inhabitants"] if p["came_by"] == "placed"}
    knight, spirit = people["knight"], people["spirit"]
    x, y = knight["position_mm"]
    spirit["position_mm"] = [x + 2_000, y]
    things = {t["placed_id"]: t for t in state["things"]}
    things["lantern"]["held_by"], things["lantern"]["position_mm"] = spirit["id"], None
    things["sword"]["position_mm"] = [x + 300, y]
    things["gate"]["position_mm"] = [x, y + 7_000]
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    for index, villager in enumerate(villagers):
        villager["position_mm"] = [x + ((3_000, 11_000)[index] if index < 2 else 30_000), y]
    return state, document, knight, spirit, villagers


def test_a_being_notices_who_is_near_named_as_its_say_options_name_them():
    state, document, knight, _spirit, villagers = _square()
    block = surroundings(state, document, knight["id"], TERMS)
    role = person_role()
    contract = role.contract(role.terms(THINGS_PROFILE).versions)
    options = choice_options(state, document, knight["id"], contract, seed=SEED)
    # The say options name each being who hears, and the block must name it the same way.
    said_to = {o.addressee_id: o.label for o in options if o.kind == "say_to" and o.addressee_id}
    by_name = {being["who"]: being for being in block["beings"]}
    for being_id, label in said_to.items():
        named = next(name for name in by_name if f" {name}, " in f" {label}")
        assert by_name[named]["hears_you"] is True, being_id
    near, eleven = villagers[0], villagers[1]
    assert [being["metres"] for being in block["beings"]] == [2, 3, 11]
    assert block["beings"][0] == {
        "who": "the lantern spirit",
        "kind": "lantern spirit",
        "metres": 2,
        "doing": "waiting",
        "holding": ["lantern"],
        "from_elsewhere": False,
        "hears_you": True,
    }
    # 11 m is within notice but beyond the 8 m a line carries.
    assert block["beings"][2]["hears_you"] is False
    assert near["id"] in said_to and eleven["id"] not in said_to
    # The third villager stands 30 m off: beyond notice, neither listed nor counted.
    assert block["more_beings"] == 0
    assert all("30" not in str(being["metres"]) for being in block["beings"])


def test_loose_things_are_noticed_with_what_their_offers_say_and_a_held_thing_only_in_hands():
    state, document, knight, _spirit, _villagers = _square()
    block = surroundings(state, document, knight["id"], TERMS)
    words = _offer_words()
    assert block["things"] == [
        {"what": "sword", "metres": 0, "good_for": [words["holdable"]]},
        {
            "what": "gate",
            "metres": 7,
            "good_for": [words["arrive_through"], words["leave_through"]],
        },
    ]
    assert "lantern" not in [entry["what"] for entry in block["things"]]
    assert block["more_things"] == 0


@pytest.mark.parametrize(
    ("action", "goal", "doing"),
    [
        ({"kind": "move", "status": "active", "target_id": None}, None, "walking"),
        ({"kind": "idle", "status": "blocked", "target_id": None}, None, "waiting"),
        ({"kind": "stand", "status": "active", "target_id": None}, {"kind": "stand"}, "standing"),
        ({"kind": "talk", "status": "active", "target_id": None}, "partner", "talking with"),
        ({"kind": "rest", "status": "active", "target_id": "bench"}, None, "resting on a bench"),
    ],
    ids=["walking", "waiting", "standing", "talking", "resting"],
)
def test_what_a_being_is_doing_is_read_in_its_routine_s_words(action, goal, doing):
    state, document, knight, spirit, villagers = _square()
    near = next(p for p in state["inhabitants"] if p["id"] == villagers[0]["id"])
    if action["target_id"] == "bench":
        bench = next(t for t in document["targets"] if t["activity"] == "rest_bench")
        action = {**action, "target_id": bench["target_id"]}
    if goal == "partner":
        goal = {"kind": "talk", "partner_id": spirit["id"]}
    near["action"] = {**near["action"], **action, "remaining_ticks": 3, "reason": "test"}
    near["goal"] = goal
    block = surroundings(state, document, knight["id"], TERMS)
    found = next(b for b in block["beings"] if b["metres"] == 3)
    if doing == "talking with":
        assert found["doing"] == "talking with the lantern spirit"
    else:
        assert found["doing"] == doing


def test_where_a_being_stands_is_the_place_whose_access_point_is_within_two_metres():
    state, document, knight, _spirit, _villagers = _square()
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    bench = next(t for t in document["targets"] if t["activity"] == "rest_bench")
    me = next(p for p in state["inhabitants"] if p["id"] == knight["id"])
    me["position_mm"] = list(nodes[bench["node_id"]])
    at = surroundings(state, document, knight["id"], TERMS)["at"]
    assert at == {"words": "resting on a bench", "good_for": _offer_words()["rest_at"]}
    # Moved 30 m from every place, it stands at none.
    me["position_mm"] = [me["position_mm"][0] + 30_000, me["position_mm"][1] + 30_000]
    assert surroundings(state, document, knight["id"], TERMS)["at"] is None


def test_beings_past_the_bound_are_counted_nearest_first_ties_by_identifier():
    state, document, knight, _spirit, villagers = _square(population=6)
    x, y = knight["position_mm"]
    for villager in villagers:
        villager["position_mm"] = [x + 4_000, y]
    few = NoticeTerms(**{**_terms(), "beings_maximum": 2})
    block = surroundings(state, document, knight["id"], few)
    # The spirit at 2 m first; then the six villagers all at 4 m, the lowest identifier first.
    lowest = min(v["id"] for v in villagers)
    assert block["beings"][0]["who"] == "the lantern spirit"
    assert block["beings"][1]["metres"] == 4
    named = {v["id"]: v for v in villagers}[lowest]
    assert block["beings"][1]["who"].startswith(named["display_name"].lower())
    assert block["more_beings"] == len(villagers) - 1


def _terms() -> dict[str, int]:
    return {
        "reach_mm": TERMS.reach_mm,
        "beings_maximum": TERMS.beings_maximum,
        "things_maximum": TERMS.things_maximum,
        "bytes_maximum": TERMS.bytes_maximum,
        "hearing_reach_mm": TERMS.hearing_reach_mm,
        "offers_version": TERMS.offers_version,
    }


def test_the_block_keeps_within_its_bytes_dropping_and_counting_the_farthest_first():
    state, document, knight, _spirit, _villagers = _square()
    full = surroundings(state, document, knight["id"], TERMS)
    # The positive control: unbounded, the block lists three beings and two things.
    assert (len(full["beings"]), len(full["things"])) == (3, 2)
    size = len(canonical_json(full))
    tight = NoticeTerms(**{**_terms(), "bytes_maximum": size - 1})
    block = surroundings(state, document, knight["id"], tight)
    assert len(canonical_json(block)) <= size - 1
    # The farthest entry was the villager 11 m off, dropped and counted; the gate at 7 m stays.
    assert [b["metres"] for b in block["beings"]] == [2, 3]
    assert block["more_beings"] == 1
    assert [t["what"] for t in block["things"]] == ["sword", "gate"]


def test_the_block_is_read_again_to_the_byte_and_changes_nothing_it_reads():
    state, document, knight, _spirit, _villagers = _square()
    before = copy.deepcopy(state)
    first = surroundings(state, document, knight["id"], TERMS)
    assert state == before
    assert canonical_json(surroundings(state, document, knight["id"], TERMS)) == canonical_json(
        first
    )


def test_the_block_holds_words_alone_never_a_look_an_identifier_a_position_or_a_decider():
    state, document, knight, _spirit, _villagers = _square()
    block = surroundings(state, document, knight["id"], TERMS)
    text = json.dumps(block)
    for person in state["inhabitants"]:
        assert person["id"] not in text
    for held in state["things"]:
        assert held["id"] not in text
    assert set(block) == {"at", "beings", "more_beings", "things", "more_things"}
    for being in block["beings"]:
        assert set(being) == {
            "who",
            "kind",
            "metres",
            "doing",
            "holding",
            "from_elsewhere",
            "hears_you",
        }
    for word in ("look", "model", "position", "sha256", "decider"):
        assert word not in text


def test_an_entry_carrying_what_may_not_be_shown_is_withheld_and_counted():
    state, document, knight, _spirit, _villagers = _square()
    block = surroundings(state, document, knight["id"], TERMS)
    first = block["beings"][1]["who"].split(" (")[0]
    kept = withhold(block, lambda text: first in text)
    assert [b["who"] for b in kept["beings"]] == [
        b["who"] for b in block["beings"] if first not in b["who"]
    ]
    assert kept["more_beings"] == block["more_beings"] + 1
    # A rule that carries nothing keeps the block as it was.
    assert withhold(block, lambda text: False) == block


def test_a_model_reads_the_block_as_lines_in_its_own_words():
    state, document, knight, _spirit, villagers = _square()
    block = surroundings(state, document, knight["id"], TERMS)
    near = villagers[0]["display_name"].lower()
    words = _offer_words()
    assert surroundings_lines(block) == [
        "Around you now:",
        "- the lantern spirit, 2 m away; waiting; holding the lantern; hears you",
        f"- {near} (a villager), 3 m away; waiting; hears you",
        f"- {villagers[1]['display_name'].lower()} (a villager), 11 m away; waiting",
        "Things near you:",
        f"- the sword, beside you ({words['holdable']})",
        f"- the gate, 7 m away ({words['arrive_through']}; {words['leave_through']})",
    ]


def test_terms_refuse_a_bound_that_is_not_a_whole_number_of_at_least_one():
    for name in ("reach_mm", "beings_maximum", "things_maximum", "bytes_maximum"):
        with pytest.raises(ValueError, match=name):
            NoticeTerms(**{**_terms(), name: 0})
    assert MORE_MAXIMUM == 99


def test_the_offer_words_are_read_from_the_version_the_terms_name():
    state, document, knight, _spirit, _villagers = _square()
    # The positive control: version 1 is read and its words are the file's.
    block = surroundings(state, document, knight["id"], TERMS)
    assert block["things"][0]["good_for"] == [_offer_words()["holdable"]]
    # A version the catalog does not hold is refused rather than read from another.
    unknown = NoticeTerms(**{**_terms(), "offers_version": 999})
    with pytest.raises(CatalogError, match=r"offers\.v999"):
        surroundings(state, document, knight["id"], unknown)
