"""The server's v1 local pose agrees with the browser's display-frame equations."""

from __future__ import annotations

import pytest
from exulanica.world.arrival_display_frame import CameraSample, scene_display_frame


@pytest.mark.parametrize(
    ("cameras", "corners", "expected"),
    [
        (
            [CameraSample((2, 1.6, 3), (0, 0, -1), (0, 1, 0))],
            [(-2, -1, -2), (2, 2, 2)],
            (0.6153846153846154, (-1.2307692307692308, 0.6153846153846154, -1.8461538461538463)),
        ),
        (
            [
                CameraSample((4, 2, 0), (-1, -0.1, 0), (0, 1, 0)),
                CameraSample((0, 2, 4), (0, -0.1, -1), (0, 1, 0)),
            ],
            [(-1, -2, -1), (1, 2, 1)],
            (0.4, (3.5102129536390695e-16, 0.8, 3.552713678800501e-16)),
        ),
        (
            [
                CameraSample((0, 2, 2), (0, 0, -1), (0, 1, 0)),
                CameraSample((0, 2, -2), (0, 0, 1), (0, -1, 0)),
            ],
            [],
            (1, (0, -2, 0)),
        ),
        (
            [
                CameraSample((3, 2, 4), (-0.5, -0.2, -0.8), (0.2, 0.9, -0.1)),
                CameraSample((-2, 3, 1), (0.6, -0.1, -0.7), (0.1, 0.95, -0.2)),
            ],
            [(-3, -2, -4), (3, 2, 4)],
            (0.4443001948457013, (0.15719881199339408, 0.8, 0.3114484346478816)),
        ),
    ],
)
def test_v1_similarity_matches_browser_samples(cameras, corners, expected):
    frame = scene_display_frame(cameras, corners)
    assert frame.scale == pytest.approx(expected[0], abs=1e-12)
    assert frame.translation == pytest.approx(expected[1], abs=1e-12)
    if len(cameras) == 2 and corners and corners[0] == (-3, -2, -4):
        assert frame.rotation == pytest.approx(
            (
                0.987115,
                -0.159510,
                0.012668,
                0.159510,
                0.974661,
                -0.156816,
                0.012668,
                0.156816,
                0.987546,
            ),
            abs=1e-5,
        )
