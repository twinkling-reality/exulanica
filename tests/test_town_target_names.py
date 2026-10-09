"""What a town's place calls a premises or a bench, on a society of things' input
(walking-surfaces-v3): each town target says its use class, label and address number as the
place's destination states them; an input composed before the field (stored since the town
ground landed) still reads; a name never moves anybody's destination; v1 and v2 say no names.
Composed without a database."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from exulanica.world.society_planner import (
    advance_purposeful_society,
    input_sha256,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_things import advance_things, initial_things_society

from test_walking_surfaces_v3 import SEED, SOCIETY, _compose, _scene_things, _town


def _sealed(document: dict[str, Any]) -> dict[str, Any]:
    held = {k: v for k, v in document.items() if k != "document_sha256"}
    held["document_sha256"] = input_sha256(held)
    return held


def _without_names(document: dict[str, Any]) -> dict[str, Any]:
    """The same input as code before the field composed it: no target says a name."""
    old = copy.deepcopy(document)
    for target in old["targets"]:
        target.pop("place", None)
    return _sealed(old)


def test_each_town_target_says_what_the_town_s_place_calls_it_and_a_thing_says_nothing():
    document = _compose(*_scene_things())
    destinations = {
        destination["destination_id"].split(":", 1)[1]: destination
        for destination in _town()[1]["destinations"]
    }
    town = [t for t in document["targets"] if t["origin"] in ("premises", "furniture")]
    assert {t["origin"] for t in town} == {"premises", "furniture"}
    for target in town:
        destination = destinations[target["object_id"]]
        assert target["place"] == {
            "use_class": destination["use_class"],
            "label": destination["label"],
            "address_number": destination["address_number"],
        }
    assert any(t["place"]["address_number"] is not None for t in town if t["origin"] == "premises")
    things = [t for t in document["targets"] if t["origin"] == "thing"]
    assert things and all("place" not in t for t in things)


def test_v1_and_v2_targets_say_no_names():
    for living in (False, True):
        document = _compose(as_things=False, living=living)
        assert all("place" not in target for target in document["targets"])


def test_an_input_composed_before_the_names_still_reads_and_a_wrong_name_is_refused():
    named = _compose(*_scene_things())
    validate_society_input(_without_names(named))
    town = next(i for i, t in enumerate(named["targets"]) if t["origin"] == "premises")
    thing = next(i for i, t in enumerate(named["targets"]) if t["origin"] == "thing")
    extra = copy.deepcopy(named)
    extra["targets"][town]["place"]["street"] = "High Street"
    on_a_thing = copy.deepcopy(named)
    on_a_thing["targets"][thing]["place"] = dict(named["targets"][town]["place"])
    unlabelled = copy.deepcopy(named)
    unlabelled["targets"][town]["place"]["use_class"] = ""
    for broken in (extra, on_a_thing, unlabelled):
        with pytest.raises(ValueError, match="invalid target"):
            validate_society_input(_sealed(broken))
    v1 = copy.deepcopy(_compose(as_things=False))
    v1["targets"][0]["place"] = dict(named["targets"][town]["place"])
    with pytest.raises(ValueError, match="invalid target fields"):
        validate_society_input(_sealed(v1))


def test_someone_heading_to_a_premises_keeps_going_when_the_first_named_input_arrives():
    """A society made from an input without names (as one stored since the town ground landed)
    consumes the first input that names its places: a person on the way to a premises keeps their
    target and route; only the name is new."""
    named = _compose(*_scene_things())
    old = _without_names(named)
    later = {k: v for k, v in copy.deepcopy(named).items() if k != "modules"}
    later["input_seq"] = 2
    later = _sealed(later)
    validate_input_successor(old, later)
    state = initial_things_society(SOCIETY, SEED, old, population=old["population"]["size"])
    heading = None
    for _ in range(60):
        planned, events = advance_purposeful_society(state, SEED, [old])
        state, _events, _crossings = advance_things(state, planned, SEED, old, events)
        heading = next(
            (
                person
                for person in state["inhabitants"]
                if person["target"] is not None
                and person["target"]["origin"] == "premises"
                and person["location"]["node_id"] is None
            ),
            None,
        )
        if heading is not None:
            break
    assert heading is not None, "nobody walked to a premises within the hour"
    planned, events = advance_purposeful_society(state, SEED, [old, later])
    state, events, _crossings = advance_things(state, planned, SEED, later, events)
    now = next(person for person in state["inhabitants"] if person["id"] == heading["id"])
    assert now["target"] is not None
    assert now["target"]["target_id"] == heading["target"]["target_id"]
    assert "place" in now["target"]
    assert not [e for e in events if "target_changed" in json.dumps(e.document)]


def test_every_label_a_town_can_say_is_a_lowercase_common_noun():
    """The card says "the {label} at number {n}": a town's labels come from the routine catalog's
    closed list of use classes, never from a record's own name, and each is lower case."""
    from exulanica.world.society_living import current_routine

    labels = {use.label for use in current_routine().use_classes.values()}
    assert labels and all(label == label.lower() and label.strip() == label for label in labels)
