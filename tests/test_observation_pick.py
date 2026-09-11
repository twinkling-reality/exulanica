"""The click-to-evidence pick, now that it runs on the server: geometry, and what it refuses.

These are the browser's own cases, ported number for number from what was
``web/packages/atlas-core/test/observation-pick.test.ts`` when the pick moved into
``exulanica/graph/observations.py``. They are pure: an index built by hand and a camera, no
database and no receipt, so a change to the projection fails here before anything slower runs.
"""

from __future__ import annotations

from array import array

from exulanica.graph.observations import (
    DEFAULT_OCCLUSION_BAND_PX,
    DEFAULT_TOLERANCE_PX,
    _Camera,
    _ObservationIndex,
    _pick,
)

#: A 640x480 photograph with a 500 pixel focal length and a centred principal point.
_INTRINSICS = {"fx": 500.0, "fy": 500.0, "cx": 320.0, "cy": 240.0}

#: A camera at the origin looking down -Z, which is the renderer convention the graph delivers.
AT_ORIGIN = _Camera(
    scene_from_camera=(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1),
    projection="pinhole",
    **_INTRINSICS,
)

#: The same camera moved to (10, 2, 0) and yawed so it looks along -X, with world +Y still up.
#: Columns of the rotation block are the camera's axes in scene space: +X right is (0, 0, -1), +Y
#: up is (0, 1, 0), and +Z is (1, 0, 0), so forward, which is -Z, is (-1, 0, 0).
MOVED = _Camera(
    scene_from_camera=(0, 0, 1, 10, 0, 1, 0, 2, -1, 0, 0, 0, 0, 0, 0, 1),
    projection="pinhole",
    **_INTRINSICS,
)


def _index(
    *points: tuple[int, tuple[float, float, float]], observers: int = 1
) -> _ObservationIndex:
    """Points in the order given, each observed by the first ``observers`` of two photographs."""
    starts = array("q", [0])
    observed = array("H")
    for _ in points:
        observed.extend(range(observers))
        starts.append(len(observed))
    return _ObservationIndex(
        retained_per_image=4096,
        captures=("photograph-a", "photograph-b"),
        point_ids=array("q", [point_id for point_id, _ in points]),
        xs=array("d", [world[0] for _, world in points]),
        ys=array("d", [world[1] for _, world in points]),
        zs=array("d", [world[2] for _, world in points]),
        track_lengths=array("q", [observers] * len(points)),
        starts=starts,
        observers=observed,
        x=array("d", [0.0] * len(observed)),
        y=array("d", [0.0] * len(observed)),
        errors=array("d", [0.4] * len(observed)),
        cameras={},
    )


def pick(
    camera: _Camera,
    index: _ObservationIndex,
    u: float,
    v: float,
    *,
    tolerance: float = DEFAULT_TOLERANCE_PX,
    band: float = DEFAULT_OCCLUSION_BAND_PX,
    live: tuple[bool, bool] = (True, True),
) -> tuple[int, float, float] | None:
    """``(point id, pixel distance, depth)`` of the pick, or None, so a case reads as one line."""
    picked = _pick(index, camera, u, v, tolerance, band, list(live))
    if picked is None:
        return None
    distance, depth, position = picked
    return index.point_ids[position], distance, depth


def test_the_defaults_are_the_browsers():
    """A caller that omits them gets the answer the inspector always got."""
    assert (DEFAULT_TOLERANCE_PX, DEFAULT_OCCLUSION_BAND_PX) == (24.0, 4.0)


def test_a_point_straight_ahead_lands_on_the_principal_point():
    assert pick(AT_ORIGIN, _index((1, (0, 0, -5))), 320, 240, tolerance=1e-9) == (1, 0.0, 5.0)


def test_up_in_the_world_is_up_in_the_photograph_not_down():
    """The renderer camera has +Y up and COLMAP image axes have +v down, so the sign flips.

    Getting this wrong gives a vertically mirrored pick that looks plausible on a symmetric
    subject, which is why it is asserted rather than reasoned about.
    """
    above = _index((1, (0, 1, -5)))
    assert pick(AT_ORIGIN, above, 320, 140, tolerance=1e-9) is not None
    assert pick(AT_ORIGIN, above, 320, 340) is None
    below = _index((1, (0, -1, -5)))
    assert pick(AT_ORIGIN, below, 320, 340, tolerance=1e-9) is not None


def test_right_in_the_world_is_right_in_the_photograph():
    assert pick(AT_ORIGIN, _index((1, (1, 0, -5))), 420, 240, tolerance=1e-9) is not None
    assert pick(AT_ORIGIN, _index((1, (1, 0, -5))), 220, 240) is None


def test_a_point_behind_the_camera_is_never_projected_through_the_lens():
    assert pick(AT_ORIGIN, _index((1, (0, 0, 5))), 320, 240) is None
    assert pick(AT_ORIGIN, _index((1, (0, 0, 0))), 320, 240) is None


def test_a_camera_off_the_origin_and_off_the_axes_is_honoured():
    """Standing at (10, 2, 0) looking along -X, a point at (5, 2, 0) is five units ahead."""
    point_id, distance, depth = pick(MOVED, _index((1, (5, 2, 0))), 320, 240)
    assert point_id == 1
    assert abs(depth - 5) < 1e-9
    assert distance < 1e-9


def test_the_point_under_the_cursor_is_selected():
    point_id, distance, depth = pick(AT_ORIGIN, _index((1, (0, 0, -5)), (2, (2, 0, -5))), 322, 241)
    assert point_id == 1
    assert distance < 4
    assert abs(depth - 5) < 1e-9


def test_nothing_recorded_near_the_cursor_is_a_miss():
    """A real answer: the honest state for a plain surface with few matched features."""
    assert pick(AT_ORIGIN, _index((1, (0, 0, -5))), 10, 10) is None


def test_an_explicit_tolerance_is_respected():
    points = _index((1, (0, 0, -5)))
    assert pick(AT_ORIGIN, points, 350, 240) is None
    assert pick(AT_ORIGIN, points, 350, 240, tolerance=40)[0] == 1


def test_the_nearer_point_wins_when_two_lie_on_one_ray():
    """A background point a fraction of a pixel closer to the cursor must not beat the foreground.

    The near point carries the HIGHER id and the far point is nearer the cursor in pixels, so
    neither the id tie-break nor the pixel-distance order can produce this answer. Only depth can.
    """
    near, far = (9, (0.002, 0, -5)), (2, (0, 0, -50))
    point_id, _distance, depth = pick(AT_ORIGIN, _index(far, near), 320, 240)
    assert point_id == 9
    assert abs(depth - 5) < 1e-9


def test_the_occlusion_band_does_not_swallow_a_genuinely_distant_point():
    """The band resolves one ray. A near point away from the cursor loses to a far one on it."""
    near, far = (1, (0.06, 0, -5)), (2, (0, 0, -50))
    assert pick(AT_ORIGIN, _index(near, far), 320, 240)[0] == 2


def test_points_behind_the_camera_are_ignored_entirely():
    assert pick(AT_ORIGIN, _index((1, (0, 0, 5)), (2, (0, 0, -5))), 320, 240)[0] == 2


def test_two_coincident_points_resolve_the_same_way_every_time():
    assert pick(AT_ORIGIN, _index((9, (0, 0, -5)), (3, (0, 0, -5))), 320, 240)[0] == 3


def test_a_point_whose_photographs_all_left_the_scene_cannot_be_picked():
    """The graph read drops it, so the pick must not find it and report the point behind it."""
    front, behind = (1, (0, 0, -5)), (2, (0, 0, -50))
    index = _index(front, behind, observers=1)
    assert pick(AT_ORIGIN, index, 320, 240)[0] == 1
    assert pick(AT_ORIGIN, index, 320, 240, live=(False, True)) is None
    both = _index(front, behind, observers=2)
    assert pick(AT_ORIGIN, both, 320, 240, live=(False, True))[0] == 1
