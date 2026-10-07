"""A saved world's air for flight for beings, composed with no database.

The worlds are flight v1's bounds worlds (``scripts/measure_flight_bounds.py``), composed from the
reviewed assets' own digests. What each column's top should be is read here from the independent
flight checker's own derivation of the same world's parts (:mod:`exulanica.world.flight_checks`),
never from the composer's.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.movement.flight_v2 import FlightMinuteRefused, column_mm_for
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.flight_air import compose_air_columns
from scripts.measure_flight_bounds import (
    SNAPSHOT_ID,
    VERSION_ID,
    WORLD_ID,
    WORLDS,
    _assets,
    checked,
    ground,
    world_objects,
)

#: A large flyer's span: columns of 4 m.
SPAN_MM = 8_000


def _version(objects) -> AlternateVersion:
    return AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=SNAPSHOT_ID,
        parent_version_id=None,
        title="air",
        style_version_id=None,
        state_sha256="0" * 64,
        edit_seq=len(objects),
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-25T00:00:00+00:00",
        objects=tuple(objects),
    )


def _keys() -> dict[str, str]:
    return {digest: key for key, digest in _assets().items()}


@pytest.mark.parametrize("name", WORLDS)
def test_each_column_stands_as_tall_as_the_tallest_part_reaching_into_it(name):
    air = compose_air_columns(
        world_id=WORLD_ID,
        version=_version(world_objects(name)),
        ground=ground(),
        asset_keys=_keys(),
        span_mm=SPAN_MM,
    )
    side = column_mm_for(SPAN_MM)
    assert air.column_mm == side == 4_000
    world = checked(name)
    expected = [0] * (air.columns_x * air.columns_y)
    for _object, ((x0, _y0, z0), (x1, y1, z1)) in world.parts:
        top = y1 - world.ground_mm
        if top <= 0:
            continue
        for iy in range(air.columns_y):
            south = air.origin_y_mm + iy * side
            if z1 < south or z0 >= south + side:
                continue
            for ix in range(air.columns_x):
                east = air.origin_x_mm + ix * side
                if x1 < east or x0 >= east + side:
                    continue
                expected[iy * air.columns_x + ix] = max(expected[iy * air.columns_x + ix], top)
    assert list(air.tops_mm) == expected
    # The comparison held where the world stands, and, but in the cluttered world, whose objects
    # reach into every 4 m column of its 24 m square, where it is open.
    assert max(expected) > 0
    assert expected.count(0) > 0 or name == "cluttered"


def test_the_same_version_gives_the_same_air():
    first, second = (
        compose_air_columns(
            world_id=WORLD_ID,
            version=_version(world_objects("small_square")),
            ground=ground(),
            asset_keys=_keys(),
            span_mm=SPAN_MM,
        )
        for _ in range(2)
    )
    assert first == second and len(first.sha256) == 64


def test_an_object_the_air_cannot_place_makes_it_unavailable_by_name():
    objects = list(world_objects("small_square"))
    objects[0] = dataclasses.replace(objects[0], asset_sha256="f" * 64)
    with pytest.raises(FlightMinuteRefused, match="unknown_object_geometry") as refused:
        compose_air_columns(
            world_id=WORLD_ID,
            version=_version(objects),
            ground=ground(),
            asset_keys=_keys(),
            span_mm=SPAN_MM,
        )
    assert refused.value.code == "flight_unavailable"


def test_a_ground_wider_than_the_module_flies_is_refused_before_any_object_is_read():
    vast = dataclasses.replace(
        ground(),
        area=dataclasses.replace(ground().area, half_width_mm=5_000_000, half_depth_mm=5_000_000),
    )
    with pytest.raises(FlightMinuteRefused) as refused:
        compose_air_columns(
            world_id=WORLD_ID,
            version=_version(world_objects("small_square")),
            ground=vast,
            asset_keys={},
            span_mm=SPAN_MM,
        )
    assert refused.value.code == "flight_world_too_large"
