"""The things composition: a saved world's input with the things its author placed.

What is shown here, with no database:

*   a placed object whose kind blocks walking takes away the lattice under its box and a walker's
    clearance around it, and one that offers a visit offers it at its kind's places, as a target of
    origin ``thing``;
*   a thing off the ground states its height and offers no activity, and still blocks;
*   a gate's arrival point is its kind's, turned with it;
*   every placed thing is bound by reference, removed ones included, and each kind by digest; a
    thing whose kind is not shipped at its digest makes the input unavailable by name;
*   the input's list of things is held to its shape, and a things input may move on to a later
    things input keeping its arrival, never back to another composition.
"""

from __future__ import annotations

import copy
import dataclasses

import pytest
from exulanica.world.placed_things import ThingKindReference
from exulanica.world.society_input_policy import AUTHORED_GROUND_INPUT_V5
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_thing_inputs import validate_input_things

from things_society_support import compose, pinned_arrival, thing

WELL = thing("well", "well", 2, -4_000, 2_000)


def _within(point, centre, half_x, half_z):
    return abs(point[0] - centre[0]) <= half_x and abs(point[1] - centre[1]) <= half_z


def test_a_blocking_object_takes_its_ground_and_offers_its_visit_at_its_kind_s_places():
    bare = compose(())
    document = compose((WELL,))
    assert document["profile"] == AUTHORED_GROUND_INPUT_V5
    validate_society_input(document)
    # The positive control: the bare square has lattice nodes where the well will stand.
    reach = 800 + CLEARANCE_MM
    assert any(
        _within(n["position_mm"], (-4_000, 2_000), reach, reach)
        for n in bare["navigation"]["nodes"]
    )
    lattice = [n for n in document["navigation"]["nodes"] if not n["node_id"].startswith("place:")]
    assert not any(
        _within(n["position_mm"], (-4_000, 2_000), reach - 1, reach - 1) for n in lattice
    )
    [target] = [t for t in document["targets"] if t["origin"] == "thing"]
    assert (
        target["target_id"],
        target["subject_id"],
        target["object_id"],
        target["affordance"],
    ) == (
        "thing:well:visit",
        "thing:well",
        "well",
        "visit",
    )
    assert target["place_node_ids"] and all(
        node.startswith("place:thing:well:") for node in target["place_node_ids"]
    )
    [entry] = document["things"]
    assert set(entry) == {"placed_id", "kind", "position_mm", "yaw_microradians", "arrival_mm"}
    assert "looks" not in entry["kind"] and entry["kind"]["reference"]["kind"] == "well"


def test_a_thing_off_the_ground_states_its_height_and_offers_nothing_but_still_blocks():
    lifted = thing("well", "well", 2, -4_000, 2_000, y_mm=600)
    document = compose((lifted,))
    [entry] = document["things"]
    assert entry["height_mm"] == 600
    assert not [t for t in document["targets"] if t["origin"] == "thing"]
    [record] = [r for r in document["unavailable_affordances"] if r["subject_id"] == "thing:well"]
    assert record["reason"] == "authored_object_off_ground"
    reach = 800 + CLEARANCE_MM - 1
    assert not any(
        _within(n["position_mm"], (-4_000, 2_000), reach, reach)
        for n in document["navigation"]["nodes"]
    )


@pytest.mark.parametrize(
    ("yaw", "expected"), [(0, [0, 8_000]), (3_141_593, [1, 10_000])], ids=["facing", "turned"]
)
def test_a_gate_s_arrival_point_is_its_kind_s_turned_with_it(yaw, expected):
    gate = thing("gate", "gate", 1, 0, 9_000, yaw=yaw)
    [entry] = compose((gate,))["things"]
    # The kind's point is 1,000 mm in front of the gate (+y in its slot frame, -z in the region's).
    assert entry["arrival_mm"] == expected


def test_every_placed_thing_is_bound_by_reference_and_an_unshipped_kind_is_refused_by_name():
    removed = thing("sword", "sword", 2, 3_500, 3_000, removed=True)
    document = compose((WELL, removed))
    refs = {(r["kind"], r["identity"]) for r in document["dependency_refs"]}
    version = document["version_id"]
    assert {("placed_thing", f"{version}:well"), ("placed_thing", f"{version}:sword")} <= refs
    assert ("thing_kind", "well.v2") in refs and ("thing_kind", "sword.v2") not in refs
    assert [entry["placed_id"] for entry in document["things"]] == ["well"]
    forged = dataclasses.replace(WELL, kind=ThingKindReference("well", 2, "a" * 64))
    unavailable = compose((forged,))
    assert (unavailable["availability"], unavailable["unavailable_reason"]) == (
        "unavailable",
        "unknown_thing_kind:well",
    )
    assert unavailable["things"] == []


@pytest.mark.parametrize(
    "change",
    [
        lambda things: things.append(copy.deepcopy(things[0])),
        lambda things: things.reverse(),
        lambda things: things[0].update(arrival_mm=[0, 0]),
        lambda things: things[1].update(arrival_mm=None),
        lambda things: things[0].update(height_mm=0),
        lambda things: things[0].update(placed_id="Well"),
        lambda things: things[0]["kind"].pop("label"),
        lambda things: things[0]["kind"]["reference"].update(version=9),
    ],
    ids=[
        "twice",
        "unsorted",
        "a-well-with-an-arrival",
        "a-gate-without-one",
        "on-the-ground-with-a-height",
        "an-id-of-the-wrong-shape",
        "a-kind-without-its-label",
        "a-reference-to-another-version",
    ],
)
def test_the_things_an_input_states_are_held_to_their_shape(change):
    document = compose((WELL, thing("zz-gate", "gate", 1, 0, 9_000)))
    validate_input_things(document)  # the positive control
    broken = copy.deepcopy(document)
    change(broken["things"])
    with pytest.raises(ValueError):
        validate_input_things(broken)


def test_a_things_input_keeps_the_arrival_its_society_was_made_with():
    pinned = pinned_arrival()
    first = compose((WELL,), arrival=pinned)
    assert first["arrival"] == pinned.model_dump(mode="json")
    assert first["navigation"]["arrival_mm"] == [0, 2_000]
    edits = first["authored_state"]["edit_seq"]
    validate_input_successor(
        first, compose((WELL,), input_seq=2, edit_seq=edits + 1, arrival=pinned)
    )
    for unpinned in (compose((WELL,), input_seq=2, edit_seq=edits + 1),):
        with pytest.raises(ValueError, match="arrival"):
            validate_input_successor(first, unpinned)
