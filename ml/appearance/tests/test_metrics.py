"""The measurements measure what they say, on pictures whose answers are known."""

from __future__ import annotations

import json

import numpy as np
import pytest
from conftest import quad_scene
from PIL import Image

from exulanica_appearance.canonical import (
    Refused,
    canonical_bytes,
    parse_canonical,
    sha256_hex,
)
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


def test_a_session_is_measured_against_the_recipe_and_the_conditioning(tmp_path, repository):
    from exulanica_appearance.metrics.session import MODULES, measure_session
    from exulanica_appearance.runner.dry_run import dry_run

    dry_run(repository, tmp_path / "dry")
    results, staged = tmp_path / "dry" / "run", tmp_path / "dry" / "staged"
    document = parse_canonical(
        measure_session(repository=repository, results=results, staged=staged),
        "the session measurements",
    )
    assert len(document["generations"]) == 4
    row = document["generations"][0]
    # The period comes from the brick recipe's own parameters, not from whatever peak is strongest.
    module = row["published_module"]
    assert module["maker"] == "loom.brick"
    assert module["from"] == {axis: MODULES["loom.brick"][axis] for axis in ("u", "v")}
    assert module["cycles"]["v"] == 24
    assert set(row["retention_permille"]) == {"u", "v"}
    # The stub generates at 256 while the conditioning is 1024, and a resize is not the structure
    # that was given, so the agreement is not measured and the record says why rather than going
    # quiet about it.
    assert row["conditioning_agreement"] == {}
    assert "256" in row["conditioning_not_measured"]
    assert document["summary"]["conditioning_not_measured"]["count"] == 4
    assert "conditioning_recall_ppm" not in document["summary"]
    # Without the staged directory the same run measures, and says nothing about the conditioning.
    without = parse_canonical(
        measure_session(repository=repository, results=results), "the session measurements"
    )
    assert without["generations"][0]["conditioning_agreement"] == {}
    assert without["generations"][0]["conditioning_not_measured"] == ""
    # A conditioning picture changed after the run cannot stand in for the structure that was given.
    picture = next((staged / "conditioning").rglob("*.png"))
    pixels = np.array(Image.open(picture).convert("RGB"), dtype=np.uint8)
    pixels[0, 0] = 255 - pixels[0, 0]
    Image.fromarray(pixels).save(picture)
    with pytest.raises(Refused, match="not the pixels the record pins"):
        measure_session(repository=repository, results=results, staged=staged)


def test_two_runs_of_one_job_are_compared_by_digest(tmp_path, repository):
    from exulanica_appearance.metrics.session import compare_runs
    from exulanica_appearance.runner.dry_run import dry_run

    dry_run(repository, tmp_path / "first")
    dry_run(repository, tmp_path / "second")
    first, second = tmp_path / "first" / "run", tmp_path / "second" / "run"
    document = parse_canonical(compare_runs(first=first, second=second), "the comparison")
    # The stub is a fixed function of its seed, so two runs of one spec agree byte for byte. That is
    # what the comparison is for: on a real model it is the question, here it is a control.
    assert document["compared"] == 4
    assert document["identical"] == 4
    assert document["verdict"] == "every output identical"
    assert all(row["seed"] for row in document["generations"])

    # A changed output is caught, and named by what the job fixes rather than by position.
    row = document["generations"][0]
    stem = row["first_output_sha256"]
    records = sorted((first / "records").glob("*.json"))
    changed = next(path for path in records if stem in path.read_text())
    edited = json.loads(changed.read_bytes())
    edited["outputs"][0]["sha256"] = "f" * 64
    changed.write_bytes(canonical_bytes(edited))
    (first / "records" / f"{sha256_hex(changed.read_bytes())}.json").write_bytes(
        changed.read_bytes()
    )
    document = parse_canonical(compare_runs(first=first, second=second), "the comparison")
    assert document["identical"] == 3
    assert "1 of 4 outputs differ" == document["verdict"]

    # Comparing runs that did not generate the same set measures the difference between the jobs
    # rather than between the machines, so it is refused.
    import shutil

    short = tmp_path / "short"
    shutil.copytree(second, short)
    summary = parse_canonical((short / "results.json").read_bytes(), "the results")
    summary["generations"] = summary["generations"][:-1]
    (short / "results.json").write_bytes(canonical_bytes(summary))
    with pytest.raises(Refused, match="did not generate the same set"):
        compare_runs(first=first, second=short)


def test_the_module_amplitude_is_read_at_a_stated_period_not_the_strongest():
    from exulanica_appearance.metrics.textures import (
        dominant_cycles,
        module_amplitude_milli,
    )

    size = 256
    x = np.arange(size)
    # 8 cycles across the tile at 20 grey levels, plus a stronger 3-cycle wave the model might add.
    courses = 128 + 20 * np.sin(2 * np.pi * 8 * x / size) + 40 * np.sin(2 * np.pi * 3 * x / size)
    tile = np.repeat(courses.reshape(1, size), size, axis=0)
    pixels = np.repeat(np.round(tile).astype(np.uint8)[..., None], 3, axis=-1)
    # The strongest period is the invented one; the module's own period is still read at 8 cycles.
    assert dominant_cycles(pixels)["u"] == 3
    amplitude = module_amplitude_milli(pixels, {"u": 8, "v": 1})
    assert 19_500 <= amplitude["u"] <= 20_500
    assert amplitude["v"] <= 100
    flat = np.full((size, size, 3), 128, dtype=np.uint8)
    assert module_amplitude_milli(flat, {"u": 8, "v": 8}) == {"u": 0, "v": 0}
    with pytest.raises(Refused, match="not inside a profile"):
        module_amplitude_milli(pixels, {"u": size, "v": 8})


def test_decoded_bytes_match_lane_16s_binding_and_pitch_rounds():
    assert decoded_bytes(1024, 1024, 3) == 16_777_212
    assert decoded_bytes(1024, 1024, 2) == 11_184_808
    assert texel_pitch_um(2000, 1024) == 1953
    assert texel_pitch_um(1800, 1024) == 1758


def test_a_published_container_reads_and_a_changed_byte_is_refused(repository, brick_set):
    entry = brick_set
    raw = (
        repository / "assets" / "textures" / "blobs" / f"{entry['content_sha256']}.ltex"
    ).read_bytes()
    header, maps = read_container(raw, entry)
    assert header["set_id"] == entry["set_id"]
    # The decoded map is the size the container declares, whatever that size is: the catalog now
    # publishes 512 px sets beside 1024 px ones, and a hard-coded size tested the catalog's fashion.
    size = header["resolution"]
    assert size == entry["resolution"]
    assert maps["base_color"].shape == (size["height"], size["width"], 3)
    changed = bytearray(raw)
    changed[-1] ^= 1
    with pytest.raises(Refused, match="size and sha256"):
        read_container(bytes(changed), entry)
