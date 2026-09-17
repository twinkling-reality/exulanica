"""The measurements measure what they say, on pictures whose answers are known."""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import quad_scene

from exulanica_appearance.canonical import Refused
from exulanica_appearance.capture.raster import rasterize
from exulanica_appearance.containers import read_container
from exulanica_appearance.metrics.edges import edge_agreement, image_edges
from exulanica_appearance.metrics.stability import reprojection_error
from exulanica_appearance.metrics.textures import (
    decoded_bytes,
    dominant_cycles,
    low_frequency_share_ppm,
    seam_ratio_ppm,
    texel_pitch_um,
)


def _record(camera):
    return {
        "camera": {
            "height": camera.height,
            "near_um": camera.near_um,
            "position_um": list(camera.position_um),
            "target_um": list(camera.target_um),
            "vertical_fov_degrees": camera.vertical_fov_degrees,
            "width": camera.width,
        }
    }


def _layers(layers):
    return {"depth": layers.depth, "identity": layers.identity, "edges": layers.edges}


def test_a_picture_of_the_structure_itself_agrees_with_its_edges():
    triangles, camera = quad_scene()
    layers = rasterize(triangles, camera)
    picture = np.where(layers.identity[..., None] > 0, 200, 20).astype(np.uint8).repeat(3, axis=-1)
    agreement = edge_agreement(image_edges(picture), layers.edges)
    assert agreement["recall_ppm"] == 1_000_000
    assert agreement["precision_ppm"] == 1_000_000
    blank = np.full_like(picture, 120)
    assert edge_agreement(image_edges(blank), layers.edges)["recall_ppm"] == 0


def test_the_same_frame_at_the_same_camera_does_not_flicker():
    triangles, camera = quad_scene()
    layers = rasterize(triangles, camera)
    rng = np.random.default_rng(7)
    picture = rng.integers(0, 256, (camera.height, camera.width, 3), dtype=np.uint8)
    error = reprojection_error(
        picture, picture, _record(camera), _record(camera), _layers(layers), _layers(layers)
    )
    assert error["covisible_pixels"] > 0
    assert error["p95_milli_levels"] == 0
    noise = rng.integers(0, 256, picture.shape, dtype=np.uint8)
    assert (
        reprojection_error(
            picture, noise, _record(camera), _record(camera), _layers(layers), _layers(layers)
        )["p50_milli_levels"]
        > 20_000
    )


def test_seams_repetition_and_modules_on_known_patterns():
    size = 256
    u = np.arange(size)
    courses = (np.sin(2 * np.pi * 24 * u / size)[:, None] * 100 + 128).repeat(size, axis=1)
    tiling = np.repeat(courses[..., None], 3, axis=-1).astype(np.uint8)
    assert dominant_cycles(tiling)["v"] == 24
    smooth = (np.sin(2 * np.pi * 3 * u / size)[:, None] * 100 + 128).repeat(size, axis=1)
    # Byte rounding moves a 7-level neighbour step by a level either way, hence the 15 per cent band.
    assert (
        850_000
        < seam_ratio_ppm(np.repeat(np.rint(smooth)[..., None], 3, axis=-1).astype(np.uint8))["v"]
        < 1_150_000
    )
    ramp = np.repeat(np.repeat((u // 1)[:, None], size, axis=1)[..., None], 3, axis=-1).astype(
        np.uint8
    )
    assert seam_ratio_ppm(ramp)["v"] > 100_000_000
    blotch = (np.sin(2 * np.pi * 2 * u / size)[:, None] * 100 + 128).repeat(size, axis=1)
    assert (
        low_frequency_share_ppm(np.repeat(blotch[..., None], 3, axis=-1).astype(np.uint8)) > 990_000
    )
    assert low_frequency_share_ppm(tiling) < 10_000


def test_decoded_bytes_match_lane_16s_binding_and_pitch_rounds():
    assert decoded_bytes(1024, 1024, 3) == 16_777_212
    assert decoded_bytes(1024, 1024, 2) == 11_184_808
    assert texel_pitch_um(2000, 1024) == 1953
    assert texel_pitch_um(1800, 1024) == 1758


def test_a_published_container_reads_and_a_changed_byte_is_refused(repository):
    manifest = json.loads((repository / "assets" / "textures" / "manifest.json").read_bytes())
    entry = manifest["sets"][0]
    raw = (
        repository / "assets" / "textures" / "blobs" / f"{entry['content_sha256']}.ltex"
    ).read_bytes()
    header, maps = read_container(raw, entry)
    assert header["set_id"] == entry["set_id"]
    assert maps["base_color"].shape == (1024, 1024, 3)
    changed = bytearray(raw)
    changed[-1] ^= 1
    with pytest.raises(Refused, match="size and sha256"):
        read_container(bytes(changed), entry)
