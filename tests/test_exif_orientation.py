"""Orientation, which is where a naive photograph pipeline quietly goes wrong.

A phone writes the sensor readout unrotated and records how to display it in one tag. Ignore
the tag and every portrait photograph is processed sideways: the model describes a rotated
scene and every box it returns lands on the wrong axis. Four of the eight values also include
a mirror, which no amount of rotation can express.

These tests pin the decision recorded in ``orimera/ingest/exif.py``: normalise pixels at
ingest, record that it happened, and put every region in upright display space.
"""

from __future__ import annotations

import io
import random

import pytest
from exulanica.evidence.region import MIRRORED_EXIF_ORIENTATIONS, rotation_for_exif_orientation
from exulanica.ingest.derivatives import render
from exulanica.ingest.exif import _ORIENTATION_TRANSFORM, extract_exif_facts
from exulanica.ingest.stages import stage
from PIL import Image, ImageOps

from conftest import photo_bytes, upright_pixels

ALL_ORIENTATIONS = list(range(1, 9))


def _open(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return image.copy()


@pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
def test_every_orientation_normalises_to_the_same_upright_image(orientation):
    """All eight tags describe the same picture. After ingest they must all *be* it.

    This is the test that fails when a pipeline processes photographs sideways, and it fails
    for the mirrored values too, which a rotation-only fix silently gets wrong.
    """
    with Image.open(io.BytesIO(photo_bytes(orientation=orientation))) as opened:
        opened.load()
        upright, facts = extract_exif_facts(opened)

    expected = upright_pixels()
    assert upright.size == expected.size
    # JPEG is lossy, so compare the colour of a few known regions rather than exact bytes.
    assert _dominant(upright, 4, 4) == "red"
    assert _dominant(upright, upright.width - 5, 4) == "white"
    assert _dominant(upright, upright.width // 2, upright.height - 3) == "blue"
    assert facts.orientation.exif_value == orientation
    assert facts.display_width == 160 and facts.display_height == 100


@pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
def test_the_recorded_transform_matches_what_was_actually_applied(orientation):
    """The table used for the record and the transform used on the pixels must agree.

    ``normalise_orientation`` applies ``ImageOps.exif_transpose`` and records
    ``_ORIENTATION_TRANSFORM``. If those two ever diverge, the pixels are right and the record
    is wrong, and every region normalised afterwards is placed against a lie.
    """
    mirrored, rotation = _ORIENTATION_TRANSFORM[orientation]
    stored = _open(photo_bytes(orientation=orientation))

    reference = ImageOps.exif_transpose(stored)
    manual = stored
    if mirrored:
        manual = manual.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if rotation:
        # PIL rotates counter-clockwise; the table is in clockwise degrees.
        manual = manual.rotate(-rotation, expand=True)

    assert manual.size == reference.size
    assert manual.convert("RGB").tobytes() == reference.convert("RGB").tobytes()


@pytest.mark.parametrize("orientation", sorted(set(ALL_ORIENTATIONS) - MIRRORED_EXIF_ORIENTATIONS))
def test_rotation_agrees_with_the_evidence_layer_for_unmirrored_values(orientation):
    """``exulanica.evidence.region`` refuses mirrored values; where it answers, we must match.

    That module refuses because it describes the branch ADR-0004 rejected, in which pixels are
    NOT normalised and a flip cannot be expressed in the ``rotation`` column. Ingest takes the
    other branch. The two must still agree wherever both have an opinion, so a change to the
    ingest table cannot drift away from the evidence layer unnoticed.
    """
    _, rotation = _ORIENTATION_TRANSFORM[orientation]
    assert rotation == rotation_for_exif_orientation(orientation)


@pytest.mark.parametrize("orientation", sorted(MIRRORED_EXIF_ORIENTATIONS))
def test_mirrored_originals_are_recorded_as_mirrored_and_not_silently_rotated(orientation):
    """A mirror is recorded as a mirror. Treating it as its unmirrored rotation is the bug."""
    with Image.open(io.BytesIO(photo_bytes(orientation=orientation))) as opened:
        opened.load()
        _, facts = extract_exif_facts(opened)
    probe = facts.as_probe_json()["orientation"]
    assert probe["mirrored"] is True
    assert probe["normalised_at_ingest"] is True
    assert probe["exif_orientation"] == orientation
    # The rotation column can hold this value; the mirror lives outside the digest, in the
    # probe, which is exactly why pixels were normalised instead.
    assert probe["rotation_degrees_clockwise"] in (0, 90, 180, 270)


@pytest.mark.parametrize("orientation", ALL_ORIENTATIONS)
def test_the_rendition_a_model_sees_is_upright(orientation):
    """The rendition is the only thing the model looks at, so this is where it must be right."""
    with Image.open(io.BytesIO(photo_bytes(orientation=orientation))) as opened:
        opened.load()
        upright, _ = extract_exif_facts(opened)
    rendition = render(upright, stage("rendition"))
    with Image.open(io.BytesIO(rendition.data)) as encoded:
        encoded.load()
        assert encoded.size == (160, 100)
        assert _dominant(encoded, 4, 4) == "red"
        assert _dominant(encoded, encoded.width // 2, encoded.height - 3) == "blue"


def test_the_rendition_carries_no_exif_at_all():
    """No orientation tag to apply twice, and no GPS leaving the machine with the pixels."""
    with Image.open(io.BytesIO(photo_bytes(orientation=6, gps=(64.3271, -20.1199)))) as opened:
        opened.load()
        upright, facts = extract_exif_facts(opened)
    assert facts.gps is not None  # the original really did carry a position
    rendition = render(upright, stage("rendition"))
    with Image.open(io.BytesIO(rendition.data)) as encoded:
        assert dict(encoded.getexif()) == {}


def test_rendition_encodes_high_entropy_pixels_without_libjpeg_buffer_failure():
    """A valid photograph must not be refused because optional JPEG optimisation overflows.

    Version 1 failed deterministically for these bytes with Pillow's ``broken data stream when
    writing image file`` error. Keeping the generator here makes the regression independent of
    the campaign fixture and ensures it passes through the real downscale and encoder path.
    """
    rng = random.Random(0xE771A)
    image = Image.frombytes("RGB", (800, 600), rng.randbytes(800 * 600 * 3))

    spec = stage("rendition")
    assert spec.version == 2
    assert spec.params["optimize"] is False

    first = render(image, spec)
    second = render(image, spec)
    assert first.data == second.data
    with Image.open(io.BytesIO(first.data)) as encoded:
        encoded.load()
        assert encoded.size == (768, 576)


def test_an_image_with_no_exif_is_treated_as_upright():
    image = upright_pixels()
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    with Image.open(io.BytesIO(buffer.getvalue())) as opened:
        opened.load()
        upright, facts = extract_exif_facts(opened)
    assert facts.orientation.exif_value == 1
    assert facts.orientation.mirrored is False
    assert upright.size == image.size


def _dominant(image: Image.Image, x: int, y: int) -> str:
    r, g, b = image.convert("RGB").getpixel((x, y))[:3]
    if r > 150 and g < 110 and b < 110:
        return "red"
    if b > 150 and r < 110:
        return "blue"
    if r > 200 and g > 200 and b > 200:
        return "white"
    return f"other({r},{g},{b})"
