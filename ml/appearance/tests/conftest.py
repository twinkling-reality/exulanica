"""Shared helpers for the appearance tests: a one-quad scene the rasteriser can be checked against."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from exulanica_appearance.capture.raster import Camera, Triangles

REPOSITORY = Path(__file__).resolve().parents[3]


@pytest.fixture
def repository() -> Path:
    return REPOSITORY


def quad_scene() -> tuple[Triangles, Camera]:
    """A 2 m square wall at z = 5 m facing the camera (-Z), identity 1, surface mm = x, -y in mm;
    the camera at the origin looks down +Z, 64 by 48 pixels, 70 degrees vertical."""
    corners = np.array([[-1.0, -1.0, 5.0], [1.0, -1.0, 5.0], [1.0, 1.0, 5.0], [-1.0, 1.0, 5.0]])
    st = np.array([[-1000.0, 1000.0], [1000.0, 1000.0], [1000.0, -1000.0], [-1000.0, -1000.0]])
    triangles = Triangles(
        a=np.array([corners[0], corners[0]]),
        b=np.array([corners[1], corners[2]]),
        c=np.array([corners[2], corners[3]]),
        normal=np.array([[0.0, 0.0, -1.0], [0.0, 0.0, -1.0]]),
        identity=np.array([1, 1]),
        st_a=np.array([st[0], st[0]]),
        st_b=np.array([st[1], st[2]]),
        st_c=np.array([st[2], st[3]]),
    )
    camera = Camera(
        position_um=(0, 0, 0),
        target_um=(0, 0, 1_000_000),
        width=64,
        height=48,
        vertical_fov_degrees=70,
        near_um=80_000,
    )
    return triangles, camera


#: The published set the lane's own dry run dresses. Named, because the catalog grows: it held eight
#: sets when this package was written and seventeen by 2026-09-18, so a test that took the first one
#: was testing whichever set sorted first that week.
BRICK_SET_ID = "cc0.brick-running-bond"


@pytest.fixture
def brick_set(repository: Path) -> dict[str, Any]:
    """The manifest entry for that set, or a clear failure if the texture lane withdraws it."""
    manifest = json.loads((repository / "assets" / "textures" / "manifest.json").read_bytes())
    for entry in manifest["sets"]:
        if entry["set_id"] == BRICK_SET_ID:
            return entry
    raise AssertionError(
        f"{BRICK_SET_ID} is no longer published; this lane's dry run and jobs name it"
    )
