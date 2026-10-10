"""A town's people document: who lives where and who works where, whichever engine reads it.

Three sources hold the document, none of them the module under test:

* the living town's own genesis (``initial_living_society``), the released engine whose
  assignment rule v1 states: every person of the document is the person that engine makes, over
  shipped towns, seeds and populations;
* a town of six worked from the catalogs' own JSON and SHA-256, with no engine and none of the
  module's helpers;
* the profile's rules, each broken on a sound document and the break named.
"""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.routine import kind_routine
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    initial_living_society,
    input_routine,
    living_places,
    town_routine,
)
from exulanica.world.town_people import (
    PROFILE,
    RULE_V1,
    TownPeopleRefused,
    town_people,
    town_people_sha256,
    validate_town_people,
)

from living_town_support import SEED, town_input

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "assets" / "catalogs" / "society"
CAFE = Path(__file__).parent / "fixtures" / "world-kinds" / "fixture-cafe.json"
SOCIETY = uuid.UUID("5a5a5a5a-0000-4000-8000-000000000005")
SEEDS = (SEED, "a" * 64, hashlib.sha256(b"town-people").hexdigest())


def _engine(document: dict[str, Any], seed: str, population: int) -> tuple[Any, dict[str, Any]]:
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        seed,
        place,
        routine,
        branch_id=document["version_id"],
        population=population,
        profile=LIVING_TOWN_PROFILE,
    )
    return place, state


def _as_the_engine_made_them(place: Any, state: dict[str, Any]) -> list[dict[str, Any]]:
    """Each person of a living town's genesis, in the words a people document uses."""
    subject = {key: dest["subject_id"] for key, dest in place.destinations.items()}
    rows = []
    for person in state["inhabitants"]:
        work = person["work"]
        rows.append(
            {
                "ordinal": person["ordinal"],
                "home": subject[person["home"]["destination_id"]],
                "work": None if work is None else subject[work["destination_id"]],
                "shift": None
                if work is None
                else (work["shift_start_minute"], work["shift_minutes"]),
                "role": (person["role"]["key"], person["role"]["label"]),
                "reason": person["role_reason"],
            }
        )
    return rows


def _as_the_document_states_them(people: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for person in people["people"]:
        job = person["job"]
        rows.append(
            {
                "ordinal": person["ordinal"],
                "home": person["home"]["subject_id"],
                "work": None if job is None else job["subject_id"],
                "shift": None
                if job is None
                else (job["shift"]["start_minute"], job["shift"]["minutes"]),
                "role": (person["role"]["key"], person["role"]["label"]),
                "reason": person["reason"],
            }
        )
    return rows


@pytest.mark.parametrize(
    ("recipe", "index"),
    [("small_town", 0), ("small_town", 1), ("market_town", 0)],
)
def test_every_person_is_the_person_the_living_town_makes(recipe: str, index: int):
    document = town_input(recipe, (), index)
    routine = input_routine(document)
    full = document["population"]["size"]
    compared = 0
    for seed in SEEDS:
        # Every place in a home lived in, and a town with some of its last homes empty.
        for population in (full, full - 5, 1):
            place, state = _engine(document, seed, population)
            people = town_people(seed, document["living"]["place"], routine, population=population)
            assert _as_the_document_states_them(people) == _as_the_engine_made_them(place, state)
            # The living town records a household as a chain of pairs in a home.
            together = {
                frozenset((left["ordinal"], right["ordinal"]))
                for left in people["people"]
                for right in people["people"]
                if left["ordinal"] < right["ordinal"] and left["home"] == right["home"]
            }
            ordinal = {person["id"]: person["ordinal"] for person in state["inhabitants"]}
            chained = {
                frozenset((ordinal[row["left"]], ordinal[row["right"]]))
                for row in state["relationships"]
            }
            # A home of two is one pair either way; the engine chains a larger home's pairs.
            assert chained <= together and {o for pair in chained for o in pair} == {
                o for pair in together for o in pair
            }
            assert people["day"]["start_minute_of_day"] == state["clock"]["start_minute_of_day"]
            assert people["routine"] == state["routine"]
            compared += len(people["people"])
    assert compared > 3 * full


def test_a_town_s_people_are_the_same_in_either_frame_and_name_the_place_they_were_made_over():
    document = town_input()
    routine = input_routine(document)
    [framed] = living_places([document], routine, {})
    carried = document["living"]["place"]
    over_carried = town_people(SEED, carried, routine)
    over_framed = town_people(SEED, framed.document, routine)
    assert over_carried["people"] == over_framed["people"]
    assert over_carried["premises"] == over_framed["premises"]
    assert over_carried["place"] == {
        "place_id": carried["place_id"],
        "document_sha256": carried["document_sha256"],
    }
    # The place the input names among its dependencies, by the same digest.
    assert {"kind": "city_place", "sha256": carried["document_sha256"]} in [
        {"kind": ref["kind"], "sha256": ref["sha256"]} for ref in document["dependency_refs"]
    ]


# A town of six, worked from the catalogs' JSON and SHA-256 alone.


def _premises(
    key: str, use: dict[str, Any], *, number: int, enabled: bool = True
) -> dict[str, Any]:
    workplace = use["kind"] == "workplace"
    return {
        "destination_id": f"premises:{key}",
        "subject_id": f"city.premises:{key}",
        "node_id": f"door:{key}",
        "enabled": enabled,
        "use_class": use["key"],
        "label": use["label"],
        "address_number": number,
        "staff_capacity": use["staff_per_unit"],
        "resident_capacity": use["resident_capacity"],
        "role": {"key": use["role_key"], "label": use["role_label"]},
        "shift": {"start_minute": 0, "minutes": 1} if workplace else None,
    }


def _catalog(name: str) -> dict[str, dict[str, Any]]:
    stated = json.loads((CATALOGS / name).read_text(encoding="utf-8"))
    return {entry["key"]: entry for entry in stated["entries"]}


def _draw(seed: str, domain: str, ordinal: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{domain}:{ordinal}".encode()).digest()[:8], "big")


def _six() -> dict[str, Any]:
    uses = _catalog("society-use-class.v2.json")
    return {
        "place_id": "place:six",
        "document_sha256": "6" * 64,
        "destinations": [
            _premises("h1", uses["residential"], number=1),
            _premises("h2", uses["residential"], number=3),
            _premises("h3", uses["residential"], number=5),
            # A home the place does not offer houses nobody.
            _premises("h0", uses["residential"], number=7, enabled=False),
            _premises("bakery", uses["bakery"], number=2),
            _premises("bookshop", uses["bookshop"], number=4),
            _premises("cafe", uses["cafe"], number=6),
        ],
    }


def test_a_town_of_six_worked_from_the_catalogs_and_the_draws():
    uses = _catalog("society-use-class.v2.json")
    shifts = _catalog("society-shift.v1.json")
    policy = {entry["key"]: entry["value"] for entry in _catalog("society-policy.v2.json").values()}
    people = town_people(SEED, _six(), town_routine())
    assert people["profile"] == PROFILE and people["rule"] == RULE_V1
    assert people["origin"] == {"kind": "derived"}
    assert people["day"] == {"start_minute_of_day": policy["start_minute_of_day"]}

    # Six places in three homes of two, in premises order; the home not offered is not stated.
    assert [person["home"] for person in people["people"]] == [
        {"subject_id": f"city.premises:{home}", "household": 0}
        for home in ("h1", "h1", "h2", "h2", "h3", "h3")
    ]
    assert [row["subject_id"] for row in people["premises"]] == sorted(
        f"city.premises:{key}" for key in ("h1", "h2", "h3", "bakery", "bookshop", "cafe")
    )
    by_subject = {row["subject_id"]: row for row in people["premises"]}
    assert by_subject["city.premises:h2"] == {
        "subject_id": "city.premises:h2",
        "use_class": "residential",
        "label": "home",
        "address_number": 3,
        "node_id": "door:h2",
        "homes": 2,
        "positions": [],
    }
    # A cafe's two positions work the early and the late shift in turn.
    assert by_subject["city.premises:cafe"]["positions"] == [
        {"key": key, "start_minute": shifts[key]["start_minute"], "minutes": shifts[key]["minutes"]}
        for key in uses["cafe"]["shifts"]
    ]

    # Six in ten of six work: three, the three the seed's work draw puts first.
    assert policy["employment_share_milli"] == 600
    workers = sorted(range(6), key=lambda i: (_draw(SEED, "work", i), i))[:3]
    assert sorted(p["ordinal"] for p in people["people"] if p["job"]) == sorted(workers)
    # Workplace-first: the first position of each of the three workplaces, in the seed's order of
    # workplaces, before any second position.
    workplaces = sorted(
        ("bakery", "bookshop", "cafe"), key=lambda k: (_draw(SEED, f"workplace:premises:{k}", 0), k)
    )
    jitter = policy["shift_jitter_minutes"]
    for worker, key in zip(workers, workplaces, strict=True):
        shift = shifts[uses[key]["shifts"][0]]
        start = shift["start_minute"] - jitter + _draw(SEED, "shift", worker) % (2 * jitter + 1)
        assert people["people"][worker] == {
            "ordinal": worker,
            "home": people["people"][worker]["home"],
            "job": {
                "subject_id": f"city.premises:{key}",
                "position": 0,
                "shift": {
                    "key": shift["key"],
                    "start_minute": start % 1440,
                    "minutes": shift["minutes"],
                },
            },
            "role": {"key": uses[key]["role_key"], "label": uses[key]["role_label"]},
            "reason": "works_at_premises",
        }
    for person in people["people"]:
        if person["ordinal"] not in workers:
            assert person["job"] is None
            assert person["role"] == {"key": "resident", "label": "resident"}
            assert person["reason"] == "keeps_no_job"


def test_four_of_six_live_in_the_first_homes_and_two_of_them_work():
    people = town_people(SEED, _six(), town_routine(), population=4)
    assert [person["home"]["subject_id"] for person in people["people"]] == [
        "city.premises:h1",
        "city.premises:h1",
        "city.premises:h2",
        "city.premises:h2",
    ]
    assert sum(person["job"] is not None for person in people["people"]) == 4 * 600 // 1000


def test_a_town_with_more_workers_than_positions_says_who_found_none():
    uses = _catalog("society-use-class.v2.json")
    place = _six()
    # Only the bookshop is left to work at: one position for the three who would work.
    place["destinations"] = [
        row for row in place["destinations"] if row["use_class"] in ("residential", "bookshop")
    ]
    people = town_people(SEED, place, town_routine())
    reasons = [person["reason"] for person in people["people"]]
    assert reasons.count("works_at_premises") == uses["bookshop"]["staff_per_unit"] == 1
    assert reasons.count("no_open_position") == 2
    assert reasons.count("keeps_no_job") == 3


def test_a_town_with_no_workplace_houses_its_people_and_gives_no_reason_about_work():
    place = _six()
    place["destinations"] = [
        row for row in place["destinations"] if row["use_class"] == "residential"
    ]
    people = town_people(SEED, place, town_routine())
    assert {person["reason"] for person in people["people"]} == {"lives_at_premises"}
    assert all(row["positions"] == [] for row in people["premises"])


def test_a_kind_s_overlay_sets_the_share_who_work_and_is_named_in_the_document():
    stated = json.loads(CAFE.read_text(encoding="utf-8"))
    routine = kind_routine(read_kind(stated))
    people = town_people(SEED, _six(), routine)
    share = stated["society"]["employment_permille"]
    assert share != 600
    assert sum(person["job"] is not None for person in people["people"]) == 6 * share // 1000
    assert people["routine"]["overlay"]["employment_share_milli"] == share
    validate_town_people(people)


def test_the_document_is_named_by_its_digest_and_another_seed_is_another_town_s_people():
    first = town_people(SEED, _six(), town_routine())
    again = town_people(SEED, _six(), town_routine())
    assert canonical_json(first) == canonical_json(again)
    body = {key: value for key, value in first.items() if key != "document_sha256"}
    assert first["document_sha256"] == hashlib.sha256(canonical_json(body)).hexdigest()
    assert SEED not in canonical_json(first).decode("utf-8")
    others = {
        town_people(seed, _six(), town_routine())["document_sha256"]
        for seed in (hashlib.sha256(bytes([n])).hexdigest() for n in range(8))
    }
    assert len(others | {first["document_sha256"]}) > 1


@pytest.mark.parametrize(
    ("place", "population", "code"),
    [
        ({"destinations": []}, None, "place_offers_no_homes"),
        (None, 0, "population_outside_homes"),
        (None, 7, "population_outside_homes"),
        (None, True, "population_outside_homes"),
    ],
)
def test_a_place_or_a_population_no_people_are_made_over_is_refused_by_name(
    place: dict[str, Any] | None, population: Any, code: str
):
    with pytest.raises(TownPeopleRefused) as refused:
        town_people(SEED, _six() if place is None else place, town_routine(), population=population)
    assert refused.value.code == code


def test_a_seed_that_is_no_digest_is_refused():
    with pytest.raises(TownPeopleRefused) as refused:
        town_people("5" * 63, _six(), town_routine())
    assert refused.value.code == "seed_not_a_digest"


def _first(people: dict[str, Any], *, working: bool) -> dict[str, Any]:
    return next(p for p in people["people"] if (p["job"] is not None) == working)


def _extra_key(people: dict[str, Any]) -> None:
    people["name"] = "Ari"


def _out_of_order(people: dict[str, Any]) -> None:
    people["people"].reverse()


def _a_third_in_a_home_of_two(people: dict[str, Any]) -> None:
    people["people"][2]["home"] = dict(people["people"][0]["home"])


def _a_home_nobody_stated(people: dict[str, Any]) -> None:
    people["people"][0]["home"]["subject_id"] = "city.premises:nowhere"


def _a_position_the_workplace_has_not(people: dict[str, Any]) -> None:
    _first(people, working=True)["job"]["position"] = 9


def _two_in_one_position(people: dict[str, Any]) -> None:
    idle = _first(people, working=False)
    worker = _first(people, working=True)
    idle["job"] = copy.deepcopy(worker["job"])
    idle["role"] = dict(worker["role"])
    idle["reason"] = "works_at_premises"


def _another_position_s_shift(people: dict[str, Any]) -> None:
    _first(people, working=True)["job"]["shift"]["minutes"] += 1


def _a_reason_that_denies_the_job(people: dict[str, Any]) -> None:
    _first(people, working=True)["reason"] = "keeps_no_job"


def _premises_out_of_order(people: dict[str, Any]) -> None:
    people["premises"].reverse()


def _a_premises_that_offers_nothing(people: dict[str, Any]) -> None:
    people["premises"].append(
        {**people["premises"][-1], "subject_id": "city.premises:zz", "homes": 0, "positions": []}
    )


def _a_start_past_midnight(people: dict[str, Any]) -> None:
    _first(people, working=True)["job"]["shift"]["start_minute"] = 1440


@pytest.mark.parametrize(
    ("broken", "named"),
    [
        (_extra_key, "exactly its profile's keys"),
        (_out_of_order, "ordinal order"),
        (_a_third_in_a_home_of_two, "houses more people"),
        (_a_home_nobody_stated, "lives at a premises the document states"),
        (_a_position_the_workplace_has_not, "works a position their workplace states"),
        (_two_in_one_position, "one position"),
        (_another_position_s_shift, "their position's shift"),
        (_a_reason_that_denies_the_job, "whether they hold a job"),
        (_premises_out_of_order, "in subject order"),
        (_a_premises_that_offers_nothing, "at least one of the two"),
        (_a_start_past_midnight, "states a shift"),
    ],
)
def test_a_document_that_breaks_its_profile_is_refused_and_the_break_named(broken, named: str):
    people = town_people(SEED, _six(), town_routine())
    validate_town_people(people)
    broken(people)
    # Sealed again, so the rule broken is what refuses it and not its digest.
    people["document_sha256"] = town_people_sha256(people)
    with pytest.raises(TownPeopleRefused, match=named) as refused:
        validate_town_people(people)
    assert refused.value.code == "malformed_people"


def test_a_document_changed_after_it_was_sealed_is_refused_by_its_digest():
    people = town_people(SEED, _six(), town_routine())
    people["premises"][0]["address_number"] = 99
    with pytest.raises(TownPeopleRefused, match="digest mismatch"):
        validate_town_people(people)
