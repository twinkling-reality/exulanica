"""Masking a person out of a photograph, deterministically and before anything reads it.

The design note's second principle is "mask before, not only after": reconstruction reads a masked
derivative, so a hidden person never becomes depth, point maps or Gaussians. Three failures make
that principle false, and each has a test here.

*   **A mask that is not reproducible is not a build input.** The masked derivative's digest enters
    the scene build inputs, so a rasteriser whose edge pixels depend on the installed Pillow would
    silently invalidate builds that had already been accepted. The scanline is this repository's
    own, in exact integer arithmetic.
*   **A mask cut on the detector's boundary outlines the person it hides.** Hence the dilation, and
    hence a test that the grown mask is strictly larger.
*   **A person nobody could locate is the dangerous case, not the harmless one.** An unlocated
    detection masks the whole frame rather than nothing.
"""

from __future__ import annotations

import pytest
from exulanica.consent.regions import DetectedPerson, Silhouette
from exulanica.evidence.region import PPM, Rect
from exulanica.ingest.masking import NEUTRAL_FILL, build_coverage, encode_masked_source, mask_image
from exulanica.ingest.person_detectors import (
    NoRegionDetector,
    RecordedObservationDetector,
    StubRegionDetector,
    whole_image_silhouette,
)
from PIL import Image

ENCODER = {"format": "JPEG", "quality": 95, "subsampling": "4:4:4", "optimize": False}


def _photo(width=48, height=32, colour=(10, 200, 30)):
    return Image.new("RGB", (width, height), colour)


def _covered(mask):
    pixels = mask.load()
    return sum(1 for y in range(mask.height) for x in range(mask.width) if pixels[x, y])


def test_a_masked_region_is_neutral_and_the_rest_is_untouched():
    photo = _photo()
    box = Silhouette.from_rect(Rect.from_normalised(0.25, 0.25, 0.5, 0.5))
    masked = mask_image(photo, (box,), dilation_millionths=0)
    assert masked.load()[24, 16] == NEUTRAL_FILL
    assert masked.load()[0, 0] == (10, 200, 30)


def test_masking_never_modifies_the_source_image():
    photo = _photo()
    mask_image(photo, (whole_image_silhouette(),), dilation_millionths=0)
    assert photo.load()[24, 16] == (10, 200, 30)


def test_no_regions_still_returns_a_copy_rather_than_the_original_object():
    """A caller holding the source and believing it masked is the quiet version of this bug."""
    photo = _photo()
    assert mask_image(photo, (), dilation_millionths=0) is not photo


def test_masking_is_byte_identical_for_identical_inputs():
    photo = _photo()
    box = Silhouette.from_rect(Rect.from_normalised(0.2, 0.3, 0.4, 0.4))
    first = encode_masked_source(mask_image(photo, (box,), dilation_millionths=8000), ENCODER)
    second = encode_masked_source(mask_image(photo, (box,), dilation_millionths=8000), ENCODER)
    assert first == second


def test_a_different_region_produces_different_bytes():
    """If it did not, a consent change could not produce a new build."""
    photo = _photo()
    here = Silhouette.from_rect(Rect.from_normalised(0.1, 0.1, 0.3, 0.3))
    there = Silhouette.from_rect(Rect.from_normalised(0.5, 0.5, 0.3, 0.3))
    assert encode_masked_source(
        mask_image(photo, (here,), dilation_millionths=0), ENCODER
    ) != encode_masked_source(mask_image(photo, (there,), dilation_millionths=0), ENCODER)


def test_coverage_matches_the_outline_area_exactly():
    """A rasteriser that fills the complement passes every centre test and fails this one."""
    triangle = Silhouette(((100_000, 100_000), (900_000, 200_000), (500_000, 900_000)))
    assert _covered(build_coverage((triangle,), 40, 30)) == 360


def test_crossings_order_by_ratio_not_by_numerator():
    """Sorting the exact ratios lexicographically fills the wrong side of a sloped edge."""
    sloped = Silhouette(((0, 0), (PPM, 900_000), (0, PPM)))
    covered = _covered(build_coverage((sloped,), 60, 60))
    assert 0 < covered < 60 * 60


def test_dilation_grows_the_mask_so_no_rim_of_the_person_survives():
    photo = _photo()
    box = Silhouette.from_rect(Rect.from_normalised(0.3, 0.3, 0.2, 0.2))
    tight = _covered(build_coverage((box,), *photo.size, dilation_px=0))
    grown = _covered(build_coverage((box,), *photo.size, dilation_px=2))
    assert grown > tight


def test_a_negative_dilation_is_refused():
    with pytest.raises(ValueError, match="reveals a rim"):
        build_coverage((whole_image_silhouette(),), 8, 8, dilation_px=-1)


def test_two_overlapping_regions_do_not_leave_a_seam():
    left = Silhouette.from_rect(Rect.from_normalised(0.0, 0.0, 0.5, 1.0))
    right = Silhouette.from_rect(Rect.from_normalised(0.5, 0.0, 0.5, 1.0))
    assert _covered(build_coverage((left, right), 40, 10)) == 400


def test_an_unlocated_person_masks_the_whole_photograph():
    """The bowl failure in miniature: nobody could say where they were, so nothing was hidden."""
    detected = RecordedObservationDetector().detect(
        _photo(), {"person_boxes": (), "unlocated_people": 1}
    )
    assert len(detected) == 1
    assert detected[0].silhouette == whole_image_silhouette()
    photo = _photo()
    masked = mask_image(photo, (detected[0].silhouette,), dilation_millionths=0)
    assert masked.load()[0, 0] == NEUTRAL_FILL
    assert masked.load()[47, 31] == NEUTRAL_FILL


def test_a_recorded_box_is_reported_as_a_box_and_never_as_a_silhouette():
    detected = RecordedObservationDetector().detect(
        _photo(), {"person_boxes": ((0.1, 0.2, 0.3, 0.4, "high"),)}
    )
    assert detected[0].shape == "box"
    assert detected[0].confidence == "high"
    assert detected[0].detector == "recorded-vision-observation/v1"


def test_finding_nothing_is_not_the_same_double_as_never_looking():
    assert NoRegionDetector().detect(_photo(), {}) == ()
    assert NoRegionDetector().model_id != StubRegionDetector().model_id


def test_a_stub_detector_ignores_the_pixels_it_is_shown():
    region = DetectedPerson(whole_image_silhouette(), "box", "low", "fixed-region-double")
    detector = StubRegionDetector((region,))
    assert detector.detect(_photo(colour=(0, 0, 0)), {}) == detector.detect(_photo(), {})
