"""The detector finds the traces that the bowl photographs actually contain.

This is the failure the whole design note is about, tested directly. The retained bowl collection
contains the arms, hands and clothing of diners at the frame edge, no faces, and the reviewer's
one available answer was "no visible people". Two separate things made that the only answer:

*   The observation schema told the model **not** to list people in ``objects``, and ``objects``
    was the only array a person could appear in.
*   ``person_objects`` filtered that array against an exact-match whitelist of sixteen singular
    nouns. "arms", "hands", "diners", "elbow" and "shoulder" match none of them.

Schema version 2 gives people their own field and asks for partial traces by name. These tests
pin that a hand at the edge of a frame is now found, that an observation stored under version 1
still reads, and that the new field carries no description of anybody.
"""

from __future__ import annotations

import pytest
from exulanica.ingest.person_detectors import RecordedObservationDetector
from exulanica.ingest.stages.person_regions import located_people, unlocated_people
from exulanica.ingest.vision import (
    OBSERVATION_SCHEMA,
    ObservationError,
    PersonTrace,
    validate_observation,
)
from PIL import Image


def _v2(people, objects=()):
    return {
        "scene_description": "A table with a bowl on it.",
        "people": list(people),
        "objects": list(objects),
        "legible_text": [],
        "proposed_place": None,
    }


def _document(observation):
    return {"header": {"schema_version": 2}, "observation": observation}


def _trace(part, x=0.8, y=0.5, w=0.15, h=0.2, confidence="low"):
    return {"part": part, "confidence": confidence, "box": {"x": x, "y": y, "w": w, "h": h}}


# -- the case that motivated the design ---------------------------------------------------


@pytest.mark.parametrize("part", ["hand", "arm", "leg", "foot", "partial_body", "torso"])
def test_every_partial_trace_the_schema_names_is_accepted(part):
    assert len(validate_observation(_v2([_trace(part)])).person_traces) == 1


def test_a_part_outside_the_vocabulary_is_refused_rather_than_dropped():
    """A silently ignored entry is a person the reviewer is never shown."""
    with pytest.raises(ObservationError):
        validate_observation(_v2([_trace("shoulder")]))


def test_a_hand_at_the_edge_of_the_frame_is_found():
    """The bowl case in one assertion. Under version 1 this photograph contained nobody."""
    document = _document(_v2([_trace("hand", x=0.88, y=0.55, w=0.10, h=0.12)]))
    found = located_people(document)
    assert len(found) == 1
    trace = found[0]
    assert (trace.x, trace.y, trace.w, trace.h) == (0.88, 0.55, 0.10, 0.12)
    assert trace.confidence == "low"
    assert trace.part == "hand", "the reviewer is told which trace this is"


def test_several_partial_traces_of_different_diners_are_separate_regions():
    document = _document(_v2([_trace("arm", x=0.02, y=0.4), _trace("hand", x=0.85, y=0.6)]))
    assert len(located_people(document)) == 2


def test_a_reflection_and_somebody_on_a_screen_both_count():
    """The design note lists both explicitly, and both were unreachable before."""
    document = _document(_v2([_trace("reflection", x=0.1), _trace("on_screen", x=0.5)]))
    assert len(located_people(document)) == 2


def test_a_low_confidence_trace_is_still_a_region():
    """Confidence sorts a reviewer's queue; it never decides whether somebody is hidden."""
    document = _document(_v2([_trace("partial_body", confidence="low")]))
    assert len(located_people(document)) == 1


def test_a_trace_with_no_box_is_unlocated_and_masks_the_whole_photograph():
    document = _document(_v2([{"part": "hand", "confidence": "low", "box": None}]))
    assert located_people(document) == []
    assert unlocated_people(document) == 1


# -- what the old path could and could not see --------------------------------------------


def test_the_old_whitelist_would_have_missed_every_one_of_these():
    """Kept as the record of why this changed, not as a thing anybody should rely on."""
    from exulanica.ingest.vision import _PERSON_LABELS

    for missed in ("arms", "hands", "diners", "elbow", "shoulder", "arm", "hand"):
        assert missed not in _PERSON_LABELS


def test_an_observation_stored_under_schema_version_1_still_reads():
    """An existing corpus must not silently become a corpus with nobody in it."""
    legacy = {
        "scene_description": "Two people by a waterfall.",
        "objects": [
            {
                "label": "person",
                "salience": "primary",
                "confidence": "high",
                "box": {"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.5},
            },
            {"label": "waterfall", "salience": "secondary", "confidence": "high", "box": None},
        ],
        "legible_text": [],
        "proposed_place": None,
    }
    found = located_people({"header": {"schema_version": 1}, "observation": legacy})
    assert len(found) == 1
    assert validate_observation(legacy).person_traces[0].part == "full_body"


def test_a_model_that_ignores_the_instruction_is_still_caught():
    """The defensive filter stays: a model putting a person in `objects` does not get through."""
    payload = _v2(
        [],
        objects=[
            {
                "label": "person",
                "salience": "primary",
                "confidence": "high",
                "box": {"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.4},
            }
        ],
    )
    assert len(validate_observation(payload).person_traces) == 1


# -- what the field may not carry ----------------------------------------------------------


def test_a_person_trace_carries_no_description_of_anybody():
    """Routing people through `objects` meant the model wrote free text about them."""
    fields = set(PersonTrace.model_fields)
    assert fields == {"part", "confidence", "box"}
    assert "label" not in fields
    assert "salience" not in fields


def test_the_people_schema_asks_for_location_and_forbids_description():
    people = OBSERVATION_SCHEMA["properties"]["people"]
    assert "Do not describe anybody" in people["description"]
    assert "do not name anybody" in people["description"]
    assert set(people["items"]["properties"]) == {"part", "confidence", "box"}


def test_the_schema_asks_for_the_partial_traces_by_name():
    parts = OBSERVATION_SCHEMA["properties"]["people"]["items"]["properties"]["part"]["enum"]
    for part in ("hand", "arm", "leg", "partial_body", "reflection", "on_screen"):
        assert part in parts


def test_the_schema_tells_the_model_a_miss_is_worse_than_a_false_positive():
    """Under default deny a false positive costs a click; a miss reconstructs somebody."""
    description = OBSERVATION_SCHEMA["properties"]["people"]["description"]
    assert "worse error" in description


def test_objects_now_points_at_the_field_people_belong_in():
    """The old wording said people were handled elsewhere and there was no elsewhere."""
    assert "people array above" in OBSERVATION_SCHEMA["properties"]["objects"]["description"]


# -- the fact that keeps an unlocated person from colliding with a located one -------------


def test_a_located_trace_stays_located_through_the_adapter():
    """The ordinary case, pinned so the flag below cannot be set by defaulting it the wrong way."""
    document = _document(_v2([_trace("full_body", x=0.4, y=0.4, w=0.2, h=0.2)]))
    found = RecordedObservationDetector().detect(
        Image.new("RGB", (8, 8)),
        {"person_boxes": tuple(located_people(document)), "unlocated_people": 0},
    )
    assert len(found) == 1
    assert found[0].located is True


def test_a_trace_with_no_box_is_marked_unlocated_rather_than_placed_at_the_centre():
    """A boxless trace must say nobody could place it, because the key derivation reads that.

    This is the file that owns "a person the detector must not lose", so this is where a revert
    of that one line gets caught. Without it the whole-frame outline's centre is the middle of
    the photograph, which is an ordinary body's grid cell, and the two regions become one row.
    """
    document = _document(
        _v2(
            [
                _trace("full_body", x=0.4, y=0.4, w=0.2, h=0.2),
                {"part": "hand", "confidence": "low", "box": None},
            ]
        )
    )
    found = RecordedObservationDetector().detect(
        Image.new("RGB", (8, 8)),
        {
            "person_boxes": tuple(located_people(document)),
            "unlocated_people": unlocated_people(document),
        },
    )
    assert len(found) == 2
    assert [person.located for person in found] == [True, False]
