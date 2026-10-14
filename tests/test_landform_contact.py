"""A land chunk read as exact heightfield geometry, so the existing contact predicates apply."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

from exulanica.grammar.landform import (
    CELL_MM,
    CHUNK_MM,
    NEAR_BOUND_MM,
    PROFILE,
    SAMPLES_PER_SIDE,
    WorldFrame,
    read_land_document,
    realize_backdrop,
    realize_chunk,
)
from exulanica.world.heightfield_geometry import point_contact, read_heightfield_geometry
from exulanica.world.landform_contact import chunk_geometry, chunk_height_at, chunk_local

FRAME = WorldFrame(width_mm=80_000, depth_mm=70_000, seed="f" * 64)
ROLLING = read_land_document(
    {
        "profile": PROFILE,
        "ground_mm": 5000,
        "features": [
            {
                "id": "hill",
                "kind": "rise",
                "side": "north",
                "distance_mm": -20000,
                "height_mm": 15000,
            },
            {"id": "swell", "kind": "undulation", "amplitude_mm": 1500, "wavelength_mm": 20000},
        ],
    }
)


def rational(value: dict) -> Fraction:
    return Fraction(int(value["numerator"]), int(value["denominator"]))


def test_the_near_bound_is_the_exact_sheet_bound():
    level = {
        "profile": "exulanica.heightfield-geometry/v1",
        "component_id": "landform:bound",
        "frame": "region-local-east-up-south-mm",
        "east_mm": [0, 1000],
        "south_mm": [0, 1000],
        "height_mm": [NEAR_BOUND_MM, -NEAR_BOUND_MM, NEAR_BOUND_MM, 0],
        "diagonal": "a-c-b,b-c-d",
        "provenance": {
            "kind": "generated",
            "source_sha256": "a" * 64,
            "generator_id": "exulanica.landform",
            "generator_version": 1,
            "input_sha256": "b" * 64,
        },
    }
    read_heightfield_geometry(level)
    assert CHUNK_MM <= 256_000 and CELL_MM >= 250


def test_a_chunk_reads_as_heightfield_geometry_in_its_own_frame():
    chunk = realize_chunk(ROLLING, FRAME, 0, 0)
    document = chunk_geometry(chunk)
    geometry = read_heightfield_geometry(document)
    assert len(geometry.east_mm) == len(geometry.south_mm) == SAMPLES_PER_SIDE
    assert document["provenance"]["kind"] == "generated"
    assert document["provenance"]["input_sha256"] == chunk.sha256
    assert document["component_id"] == "landform:chunk:0:0"


def test_exact_contact_and_the_land_agree_on_every_height():
    chunk = realize_chunk(ROLLING, FRAME, 1, -1)
    geometry = read_heightfield_geometry(chunk_geometry(chunk))
    x0, y0 = CHUNK_MM, -CHUNK_MM
    points = [
        (x0, y0),
        (x0 + 128_000, y0 + 128_000),
        (x0 + 3_250, y0 + 7_750),
        (x0 + 90_500, y0 + 12_125),
        (x0 + 64_000, y0 + 999),
        (x0 + 127_999, y0 + 1),
    ]
    for x, y in points:
        contact = point_contact(geometry, chunk_local(chunk, x, y))
        assert contact is not None, (x, y)
        assert rational(contact["height_mm"]) == chunk_height_at(chunk, x, y), (x, y)


FIXTURE = Path(__file__).parent / "fixtures" / "landform" / "conformance.json"
VECTOR_FRAME = WorldFrame(width_mm=80_000, depth_mm=70_000, seed="9" * 64)
VECTOR_LAND = {
    "profile": PROFILE,
    "ground_mm": 7000,
    "features": [
        {"id": "tilt", "kind": "tilt", "side": "north_east", "grade_permille": 40},
        {"id": "knoll", "kind": "rise", "side": "south_west", "distance_mm": 10000,
         "width_mm": 150000, "depth_mm": 120000, "height_mm": 14000},
        {"id": "swell", "kind": "undulation", "amplitude_mm": 1200, "wavelength_mm": 25000},
        {"id": "skyline", "kind": "range", "side": "north", "distance_mm": 900000,
         "band_mm": 400000, "height_mm": 200000},
    ],
}  # fmt: skip


def conformance() -> dict:
    """The cross-language vectors: one chunk at the near land's south-west corner, a small
    backdrop, and exact heights at points the browser's reader is held to."""
    land = read_land_document(VECTOR_LAND)
    chunk = realize_chunk(land, VECTOR_FRAME, -1, -1)
    backdrop = realize_backdrop(land, VECTOR_FRAME, reach_mm=600_000)
    x0, y0 = -CHUNK_MM, -CHUNK_MM
    points = [(x0, y0), (0, 0), (x0 + 1, y0 + 2), (x0 + 64_500, y0 + 64_250),
              (x0 + 64_250, y0 + 64_500), (x0 + 100_333, y0 + 7_777), (-1, -1),
              (x0 + 12_000, y0 + 127_999), (x0 + 127_000, y0 + 500), (x0 + 3, y0 + 3)]  # fmt: skip
    return {
        "profile": "exulanica.landform-conformance/v1",
        "note": "Made by conformance() in tests/test_landform_contact.py; that test holds this "
        "file to what the realizer makes, and the browser's reader is held to it in "
        "web/packages/atlas-core/test/landform.test.ts.",
        "land": land.canonical(),
        "frame": {
            "width_mm": VECTOR_FRAME.width_mm,
            "depth_mm": VECTOR_FRAME.depth_mm,
            "seed": VECTOR_FRAME.seed,
        },
        "chunk": chunk.document(),
        "chunk_sha256": chunk.sha256,
        "backdrop": backdrop.document(),
        "backdrop_sha256": backdrop.sha256,
        "points": [
            {"east_mm": x, "north_mm": y, "height_mm": _wire(chunk_height_at(chunk, x, y))}
            for x, y in points
        ],
    }


def _wire(value: Fraction | None) -> dict:
    assert value is not None
    return {"numerator": str(value.numerator), "denominator": str(value.denominator)}


def test_the_cross_language_vectors_are_what_the_realizer_makes():
    assert json.loads(FIXTURE.read_text(encoding="utf-8")) == conformance()
