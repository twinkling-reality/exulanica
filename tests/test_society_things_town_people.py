"""A society of things over a town is the town's own people: the baker of its bakery.

A town's first things input carries what its people are made from (a seed-free frame), and the
society's genesis completes it with its seed. What holds each claim:

* the living town's own genesis, the released engine: for the same place and seed, person for
  person, a villager's home, job, shift, role and reason are the living resident's;
* digests read from a clean checkout of f676d996, a tree whose society of things reads no people:
  an input without a frame, its genesis and an hour of it are the bytes they were;
* the input's and the state's own checks, each broken and the break named.
"""

from __future__ import annotations

import copy
import dataclasses
import functools
import hashlib
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.authored_delta import version_delta_sha256
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    initial_living_society,
    input_routine,
    living_places,
    town_routine,
)
from exulanica.world.society_planner import (
    advance_purposeful_society,
    input_sha256,
    validate_society_input,
)
from exulanica.world.society_things import (
    advance_things,
    initial_things_society,
    validate_things_state,
)
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.town_people import people_frame, resident_of, town_people

import test_walking_surfaces_v3 as town

SEED = town.SEED
SOCIETY = town.SOCIETY
#: Read from a clean checkout of f676d996 (its society of things reads no people) with
#: tests/test_walking_surfaces_v3.py's own town, seed and society: the first input with nothing
#: placed and with the town scene's things, a genesis over each, and sixty minutes of each.
UNCHANGED = {
    "bare": {
        "input": "7beea53987c1b70c00160f96c3d2a66712fc6d6e541609b360cfc0db6a2e426e",
        "genesis": "e10b280dd50f30a6ac2fbd513d26cf0c3a9504b0ff756532a909eeb6327a26a1",
        "hour": "899228363c4f49a7a759c4aff25a1ca5950b8de20a258c187dc3ab00b3b0fc15",
        "events": "0b10ea19acfa4874be80d88ac94a0fdb52246c69f1e9fb74923ccda9eb23c2e2",
    },
    "scene": {
        "input": "0c7a07eb1c9d8c56a35a128570149d841db82fff9f72775a6999e85699d4bc10",
        "genesis": "f21912a3cef59e5e2979cd09a40fc883062b8be1a071cfda1cdf9d934a7ba596",
        "hour": "9254c249c603ecf3960ff83f81c8acfed21bf1eef19e10862b109957e32861f4",
        "events": "092308ed87b46975647c1cb5df0b776d4a784baab7c94f75d09dfa415f3b2945",
    },
}


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


@functools.cache
def _living_place() -> dict[str, Any]:
    """The town's place under the routine a living town is made under."""
    ground = town._town()[0]
    return walking_surfaces_place(ground.place_id, town._composed().records, town_routine())


def _frame() -> dict[str, Any]:
    return people_frame(_living_place(), town_routine())


def _housed(*things: Any, people: dict[str, Any] | None = None, input_seq: int = 1) -> dict:
    """The town's things input carrying its people's frame, as the runtime composes a first one."""
    ground, place, base, standing = town._town()
    version = dataclasses.replace(base, things=tuple(things))
    version = dataclasses.replace(version, state_sha256=version_delta_sha256(version))
    return build_walking_surfaces_input(
        ground=ground,
        version=version,
        place=place,
        input_seq=input_seq,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=standing,
        things=True,
        segment_blocked=segment_blocked,
        obstructions=town._obstructions(),
        people=_frame() if people is None else people,
    )


def _genesis(document: dict[str, Any], seed: str = SEED) -> dict[str, Any]:
    return initial_things_society(
        SOCIETY, seed, document, population=document["population"]["size"]
    )


def _living_genesis(seed: str = SEED) -> tuple[Any, dict[str, Any]]:
    """The living town's genesis over the same town, seed and society."""
    ground, _place, base, standing = town._town()
    document = build_walking_surfaces_input(
        ground=ground,
        version=base,
        place=_living_place(),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=standing,
        living=town_routine(),
    )
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        seed,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    return place, state


def _resealed(document: dict[str, Any]) -> dict[str, Any]:
    document["document_sha256"] = input_sha256(document)
    return document


def test_a_town_s_first_things_input_carries_its_people_s_frame_and_holds_no_seed():
    document = _housed()
    validate_society_input(document)
    assert document["people"] == _frame()
    assert document["people"]["population"] == document["population"]["size"]
    # A frame is what the people are made from before any draw: the same for every seed.
    assert SEED not in canonical_json(document).decode("utf-8")
    # A later input states none, and the same things compose the input a society reads on.
    later = _housed(input_seq=2)
    assert "people" not in later and "modules" not in later
    validate_society_input(later)


def test_a_later_input_that_states_no_people_reads_the_same_as_the_first():
    """An edit that changes nothing the society reads appends no input: the people only a first
    input states are no difference, and a thing placed is."""
    from exulanica.api.society_runtime import _reads_the_same

    first = _housed()
    assert _reads_the_same(first, _housed(input_seq=2))
    assert not _reads_the_same(first, _housed(*town._scene_things(), input_seq=2))


@pytest.mark.parametrize("things", ["bare", "scene"])
def test_an_input_with_no_frame_and_its_society_are_the_bytes_they_were(things: str):
    placed = town._scene_things() if things == "scene" else []
    document = town._compose(*placed)
    assert "people" not in document
    genesis = _genesis(document)
    assert "people" not in genesis
    assert not any("resident" in person for person in genesis["inhabitants"])
    state, events = town._hour(document, 60)
    assert {
        "input": _sha(document),
        "genesis": _sha(genesis),
        "hour": _sha(state),
        "events": _sha([[event.kind, event.document] for event in events]),
    } == UNCHANGED[things]


@pytest.mark.parametrize("seed", [SEED, "a" * 64, hashlib.sha256(b"things-town").hexdigest()])
def test_every_villager_is_the_resident_the_living_town_makes(seed: str):
    place, living = _living_genesis(seed)
    state = _genesis(_housed(*town._scene_things()), seed)
    subject = {key: dest["subject_id"] for key, dest in place.destinations.items()}
    called = {
        dest["subject_id"]: (dest["use_class"], dest["label"], dest["address_number"])
        for dest in place.destinations.values()
    }
    villagers = [p for p in state["inhabitants"] if p["came_by"] == "populated"]
    assert len(villagers) == len(living["inhabitants"]) > 0
    working = 0
    for villager, resident in zip(villagers, living["inhabitants"], strict=True):
        # The same person: one ordinal and one identity in either engine.
        assert (villager["ordinal"], villager["id"]) == (resident["ordinal"], resident["id"])
        stated = villager["resident"]
        premises = state["people"]["premises"]
        home = subject[resident["home"]["destination_id"]]
        at_home = premises[stated["home"]["premises"]]
        assert at_home["subject_id"] == home and stated["home"]["household"] == 0
        assert (at_home["use_class"], at_home["label"], at_home["address_number"]) == called[home]
        assert stated["role"] == {
            "key": resident["role"]["key"],
            "label": resident["role"]["label"],
        }
        assert villager["role"] == resident["role"]["label"]
        assert stated["reason"] == resident["role_reason"]
        if resident["work"] is None:
            assert stated["job"] is None
        else:
            working += 1
            workplace = subject[resident["work"]["destination_id"]]
            at_work = premises[stated["job"]["premises"]]
            assert at_work["subject_id"] == workplace
            assert (at_work["use_class"], at_work["label"], at_work["address_number"]) == (
                called[workplace]
            )
            assert (stated["job"]["shift"]["start_minute"], stated["job"]["shift"]["minutes"]) == (
                resident["work"]["shift_start_minute"],
                resident["work"]["shift_minutes"],
            )
        # One reader says the same of the same person in either engine.
        ours, theirs = resident_of(state, villager), resident_of(living, resident)
        assert ours is not None and theirs is not None
        assert (ours["role"], ours["works"], ours["shift"]) == (
            theirs["role"],
            theirs["works"],
            theirs["shift"],
        )
        # Each engine names the same premises its own way: by subject here, by destination there.
        assert ours["home"]["subject_id"] == subject[theirs["home"]["destination_id"]]
        assert (ours["job"] is None) == (theirs["job"] is None)
        if ours["job"] is not None:
            assert ours["job"]["subject_id"] == subject[theirs["job"]["destination_id"]]
    assert working == len(villagers) * 600 // 1000
    # The document the genesis made is the one the rule makes for this place and seed.
    people = town_people(seed, _living_place(), town_routine())
    assert state["people"] == {
        "profile": "exulanica.town-people/v1",
        "rule": "exulanica.town-people-rule/v1",
        "document_sha256": people["document_sha256"],
        # What each of the document's premises is called, once, in the document's order.
        "premises": [
            {key: row[key] for key in ("subject_id", "use_class", "label", "address_number")}
            for row in people["premises"]
        ],
    }


def test_only_the_town_s_own_people_are_residents_and_a_seed_changes_who_works_where():
    document = _housed(*town._scene_things())
    state = _genesis(document)
    placed = [p for p in state["inhabitants"] if p["came_by"] == "placed"]
    assert {p["placed_id"] for p in placed} == {"knight", "lantern-spirit"}
    assert not any("resident" in p for p in placed)
    assert all(resident_of(state, p) is None for p in placed)
    roles = {p["role"] for p in state["inhabitants"] if p["came_by"] == "populated"}
    # The town's own roles, by its premises, and none of the six words a society with no
    # people draws.
    assert "resident" in roles and len(roles) > 1
    other = _genesis(document, "b" * 64)
    assert other["people"]["document_sha256"] != state["people"]["document_sha256"]
    assert [p["resident"]["home"] for p in other["inhabitants"] if "resident" in p] == [
        p["resident"]["home"] for p in state["inhabitants"] if "resident" in p
    ]


def test_the_town_s_people_live_an_hour_and_the_same_hour_again_and_stay_who_they_are():
    document = _housed(*town._scene_things())
    genesis = _genesis(document)

    def hour() -> tuple[dict[str, Any], list[Any]]:
        state, every = _genesis(document), []
        for _ in range(60):
            planned, events = advance_purposeful_society(state, SEED, [document])
            state, events, _crossings = advance_things(state, planned, SEED, document, events)
            every.extend(events)
        return state, every

    state, events = hour()
    again, repeated = hour()
    assert again == state
    assert [(e.kind, e.document) for e in repeated] == [(e.kind, e.document) for e in events]
    assert state["people"] == genesis["people"]
    assert {p["id"]: p["resident"] for p in state["inhabitants"] if "resident" in p} == {
        p["id"]: p["resident"] for p in genesis["inhabitants"] if "resident" in p
    }
    assert any(e.kind == "goal_selected" for e in events)


def _on_a_later_input(document: dict[str, Any]) -> None:
    document["input_seq"] = 2
    del document["modules"]


def _fewer_than_the_population(document: dict[str, Any]) -> None:
    document["people"]["population"] -= 1


def _an_unknown_rule(document: dict[str, Any]) -> None:
    document["people"]["rule"] = "exulanica.town-people-rule/v0"


def _a_seed_beside_the_frame(document: dict[str, Any]) -> None:
    document["people"]["seed"] = SEED


def _premises_out_of_order(document: dict[str, Any]) -> None:
    document["people"]["premises"].reverse()


@pytest.mark.parametrize(
    ("broken", "named"),
    [
        (_on_a_later_input, "first input"),
        (_fewer_than_the_population, "as many as its population"),
        (_an_unknown_rule, "unknown people rule"),
        (_a_seed_beside_the_frame, "exactly its profile's keys"),
        (_premises_out_of_order, "in destination order"),
    ],
)
def test_an_input_whose_people_break_their_frame_is_refused_and_the_break_named(broken, named):
    document = copy.deepcopy(_housed())
    validate_society_input(document)
    broken(document)
    with pytest.raises(ValueError, match=named):
        validate_society_input(_resealed(document))


def test_a_lattice_ground_s_things_input_carries_no_people():
    import things_society_support as lattice

    document = copy.deepcopy(lattice.compose([]))
    validate_society_input(document)
    document["people"] = _frame()
    with pytest.raises(ValueError, match="world of homes"):
        validate_society_input(_resealed(document))


def _a_resident_on_a_placed_being(state: dict[str, Any]) -> None:
    donor = next(p for p in state["inhabitants"] if "resident" in p)
    placed = next(p for p in state["inhabitants"] if p["came_by"] == "placed")
    placed["resident"] = copy.deepcopy(donor["resident"])


def _a_villager_who_is_nobody(state: dict[str, Any]) -> None:
    del next(p for p in state["inhabitants"] if "resident" in p)["resident"]


def _a_role_word_that_is_not_the_role(state: dict[str, Any]) -> None:
    next(p for p in state["inhabitants"] if "resident" in p)["role"] = "knight"


def _a_job_the_reason_denies(state: dict[str, Any]) -> None:
    worker = next(p for p in state["inhabitants"] if p.get("resident", {}).get("job"))
    worker["resident"]["reason"] = "keeps_no_job"


def _a_record_that_is_no_digest(state: dict[str, Any]) -> None:
    state["people"]["document_sha256"] = "people"


def _a_home_the_state_does_not_state(state: dict[str, Any]) -> None:
    resident = next(p for p in state["inhabitants"] if "resident" in p)["resident"]
    resident["home"]["premises"] = len(state["people"]["premises"])


def _a_premises_with_no_name_for_it(state: dict[str, Any]) -> None:
    del state["people"]["premises"][0]["label"]


@pytest.mark.parametrize(
    ("broken", "named"),
    [
        (_a_resident_on_a_placed_being, "nobody else does"),
        (_a_villager_who_is_nobody, "nobody else does"),
        (_a_role_word_that_is_not_the_role, "called by their role"),
        (_a_job_the_reason_denies, "called by their role"),
        (_a_record_that_is_no_digest, "by profile, rule and digest"),
        (_a_home_the_state_does_not_state, "a premises the state states"),
        (_a_premises_with_no_name_for_it, "what each premises of its people is called"),
    ],
)
def test_a_state_whose_people_are_out_of_shape_is_refused_and_the_break_named(broken, named):
    state = _genesis(_housed(*town._scene_things()))
    validate_things_state(state)
    broken(state)
    with pytest.raises(ValueError, match=named):
        validate_things_state(state)
