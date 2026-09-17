"""The capture's copy of the bench's poses and camera is still exactly what bench.ts says."""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

from exulanica_appearance.capture.bench import (
    BENCH_MODULE,
    BENCH_POSES_FROM,
    FOOTWAY_WALK,
    POSE_NAMES,
    walk_cameras,
)

EXPORTER = Path(__file__).resolve().parents[1] / "capture" / "export-bench.ts"


def _copied_lines(text: str) -> list[str]:
    start = text.index("// Copied verbatim from bench.ts")
    end = text.index("// End of the verbatim copy.")
    return [
        line
        for line in text[start:end].splitlines()[1:]
        if re.search(r"case '|EYE_M = |const eye = |: 'cc0\.", line)
    ]


def test_every_copied_line_appears_verbatim_in_bench_ts(repository):
    bench = (repository / BENCH_POSES_FROM).read_text()
    lines = _copied_lines(EXPORTER.read_text())
    assert len(lines) == 6 + 1 + 1 + 7
    for line in lines:
        assert line in bench, f"bench.ts no longer says: {line.strip()}"
    assert {re.search(r"case '(\w+)'", line).group(1) for line in lines if "case '" in line} == set(
        POSE_NAMES
    )


def test_the_bench_camera_is_still_seventy_degrees_at_1440_by_900(repository):
    bench = (repository / BENCH_POSES_FROM).read_text()
    assert "camera.addComponent('camera', { fov: 70, nearClip: 0.08, farClip: 1200 });" in bench
    assert "app.setCanvasResolution(pc.RESOLUTION_FIXED, 1440, 900);" in bench
    exporter = EXPORTER.read_text()
    assert (
        "far_um: um(1200), height: 900, near_um: um(0.08), vertical_fov_degrees: 70, width: 1440"
        in exporter
    )
    assert (repository / BENCH_MODULE).is_file()


def test_the_walk_is_seven_metres_in_121_frames():
    cameras = walk_cameras(80_000)
    assert len(cameras) == FOOTWAY_WALK["frames"] == 121
    assert cameras[0].position_um[0] == -5_000_000 and cameras[-1].position_um[0] == 2_000_000
    steps = {b.position_um[0] - a.position_um[0] for a, b in pairwise(cameras)}
    assert steps <= {58_333, 58_334}
    assert all(c.width == 1280 and c.height == 720 for c in cameras)
