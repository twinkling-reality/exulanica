"""The two stages, at the points where a mistake would reveal somebody.

Both stages are mostly plumbing over parts tested elsewhere. What is tested here is the handful of
decisions that are theirs alone, and every one of them is a place where the safe answer and the
convenient answer differ:

*   A detection is read from the schema that produced it, not re-parsed by hand, so the clamping
    the vision module already documents cannot drift.
*   A person with no usable box is counted as unlocated rather than skipped, and an unlocated
    person masks the whole photograph.
*   A region whose state nobody recorded is masked. A dictionary lookup that fell through to
    "not masked" would reveal exactly the person nobody had decided about.
*   A photograph where everybody consented produces no derivative at all, so reconstruction reads
    the original and the store does not fill with re-encoded copies.
"""

from __future__ import annotations

import pytest
from exulanica.consent.regions import Silhouette
from exulanica.consent.states import ResolvedPresentation
from exulanica.evidence.region import Rect
from exulanica.ingest.stages import stage
from exulanica.ingest.stages.masked_source import hidden_outlines
from exulanica.ingest.stages.person_regions import located_people, unlocated_people

KEY_A = b"\xaa" * 32
KEY_B = b"\xbb" * 32
OUTLINE_A = Silhouette.from_rect(Rect.from_normalised(0.1, 0.1, 0.2, 0.2))
OUTLINE_B = Silhouette.from_rect(Rect.from_normalised(0.6, 0.6, 0.2, 0.2))


def _document(objects):
    return {
        "observation": {
            "scene_description": "a room",
            "objects": objects,
            "legible_text": [],
            "proposed_place": None,
        }
    }


def _person(box, label="person", confidence="high"):
    entry = {"label": label, "salience": "primary", "confidence": confidence}
    entry["box"] = box
    return entry


def test_a_located_person_becomes_a_clamped_box():
    found = located_people(_document([_person({"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4})]))
    assert found == [(0.1, 0.2, 0.3, 0.4, "high")]


def test_a_box_running_off_the_frame_is_clamped_rather_than_refused():
    """Models routinely emit 1.02 for an edge; refusing would unmask the person."""
    found = located_people(_document([_person({"x": 0.8, "y": 0.8, "w": 0.5, "h": 0.5})]))
    assert len(found) == 1
    x, y, w, h, _ = found[0]
    assert x + w <= 1.0 and y + h <= 1.0


def test_a_person_with_no_box_is_counted_as_unlocated():
    document = _document([_person(None)])
    assert located_people(document) == []
    assert unlocated_people(document) == 1


def test_a_degenerate_box_is_unlocated_rather_than_a_zero_area_mask():
    """Masking an empty rectangle would leave the person beside it visible."""
    document = _document([_person({"x": 0.5, "y": 0.5, "w": 0.0, "h": 0.0})])
    assert located_people(document) == []
    assert unlocated_people(document) == 1


def test_a_non_person_object_is_not_a_person():
    document = _document([_person({"x": 0.1, "y": 0.1, "w": 0.2, "h": 0.2}, label="bicycle")])
    assert located_people(document) == []
    assert unlocated_people(document) == 0


def test_several_person_labels_all_count_as_people():
    document = _document(
        [
            _person({"x": 0.1, "y": 0.1, "w": 0.1, "h": 0.1}, label="woman"),
            _person({"x": 0.3, "y": 0.1, "w": 0.1, "h": 0.1}, label="man"),
        ]
    )
    assert len(located_people(document)) == 2


def test_a_region_with_no_resolved_state_is_masked():
    """Default deny at the one place a lookup miss would reveal somebody."""
    assert hidden_outlines({KEY_A: OUTLINE_A}, {}) == (OUTLINE_A,)


def test_a_shown_person_is_not_masked():
    resolved = {KEY_A: ResolvedPresentation("shown", False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == ()


def test_a_temporarily_hidden_person_is_not_masked_in_the_derivative():
    resolved = {KEY_A: ResolvedPresentation("hidden", False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == ()


@pytest.mark.parametrize("state", ["unknown", "present", "withdrawn"])
def test_every_unconsented_state_is_masked(state):
    resolved = {KEY_A: ResolvedPresentation(state, False)}
    assert hidden_outlines({KEY_A: OUTLINE_A}, resolved) == (OUTLINE_A,)


def test_one_hidden_person_beside_one_shown_person_masks_only_the_hidden_one():
    resolved = {
        KEY_A: ResolvedPresentation("shown", False),
        KEY_B: ResolvedPresentation("present", False),
    }
    assert hidden_outlines({KEY_A: OUTLINE_A, KEY_B: OUTLINE_B}, resolved) == (OUTLINE_B,)


def test_outlines_are_ordered_by_region_key_not_by_dictionary_order():
    regions = {KEY_B: OUTLINE_B, KEY_A: OUTLINE_A}
    assert hidden_outlines(regions, {}) == (OUTLINE_A, OUTLINE_B)


def test_the_region_stage_pins_its_detector_in_its_parameters():
    """A detector swapped without editing this would leave the corpus keyed as before."""
    spec = stage("person_regions")
    assert spec.params["detector"] == "recorded-vision-observation/v1"
    assert spec.model_role is None
    assert spec.deterministic is True


def test_the_region_stage_declares_that_it_stores_no_template():
    assert stage("person_regions").params["biometric_template"] == "never"
    assert stage("person_regions").params["scope"] == "whole-silhouette-not-face"


def test_an_unlocated_person_masks_the_whole_image_by_policy():
    assert stage("person_regions").params["unlocated_person_policy"] == "mask-whole-image"


def test_the_masked_stage_declares_a_neutral_non_generative_fill():
    spec = stage("masked_source")
    assert spec.params["fill"] == "neutral-flat"
    assert spec.params["fill_srgb"] == [128, 128, 128]
    assert spec.deterministic is True
    assert spec.model_role is None


def test_the_masked_stage_grows_the_mask_before_filling():
    assert stage("masked_source").params["dilation_millionths"] > 0
