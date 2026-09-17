"""The rasteriser records exact geometry, and a structure record holds its layers and its reasons."""

from __future__ import annotations

import math

import numpy as np
import pytest
from conftest import quad_scene

from exulanica_appearance.canonical import Refused, canonical_bytes, parse_canonical
from exulanica_appearance.capture.raster import NORMAL_SCALE, rasterize
from exulanica_appearance.structure import (
    REASON_KEYS,
    LayerStore,
    build_structure,
    load_layers,
    read_structure,
)

SOURCE = {
    "geometry_sha256": "1" * 64,
    "kind": "bench",
    "module": "web/packages/atlas-react/test/generated-tile-bench/test-street.ts",
    "module_sha256": "2" * 64,
    "poses_from": "web/packages/atlas-react/test/generated-tile-bench/bench.ts",
    "poses_from_sha256": "3" * 64,
}
LEGEND = [{"identity": 1, "surface": "wall", "texture_set": "cc0.brick-running-bond"}]
REASONS = {key: f"the reason for {key}" for key in REASON_KEYS}


def test_a_wall_facing_the_camera_is_recorded_exactly():
    triangles, camera = quad_scene()
    layers = rasterize(triangles, camera)
    # The wall spans 2 m at 5 m: half-height angle atan(0.2) against a 35 degree half field.
    assert layers.identity[24, 32] == 1
    assert layers.depth[24, 32] == 5_000_000
    assert tuple(layers.normal[24, 32]) == (0, 0, -NORMAL_SCALE)
    half = math.tan(math.radians(35))
    # Looking down +Z with +Y up, the camera's right is world -X (PlayCanvas's lookAt), so pixel
    # (row 24, column 32) looks at x = -(32.5 / 64 * 2 - 1) * half * 64/48 * 5 m.
    x = -(32.5 / 64 * 2 - 1) * half * (64 / 48) * 5
    y = (1 - 24.5 / 48 * 2) * half * 5
    assert layers.surface_s[24, 32] == round(x * 1_000_000)
    assert abs(layers.surface_t[24, 32] - round(-y * 1_000_000)) <= 1
    assert layers.identity[0, 0] == 0 and layers.depth[0, 0] == 0
    rows, _columns = np.nonzero(layers.identity)
    # The wall's edge pixels carry the step bit (hit next to nothing); its interior carries none.
    assert layers.edges[24, 32] == 0
    assert layers.edges[rows.min(), 32] & 4 or layers.edges[rows.min() - 1, 32] & 4


def test_the_near_plane_and_the_nearest_hit_win():
    triangles, camera = quad_scene()
    far = rasterize(triangles, camera)
    moved = type(camera)(
        camera.position_um, camera.target_um, camera.width, camera.height, 70, 5_000_001
    )
    assert int(rasterize(triangles, moved).identity.max()) == 0
    assert far.depth.max() == 5_000_000


def test_rasterising_twice_gives_the_same_bytes():
    triangles, camera = quad_scene()
    one, two = rasterize(triangles, camera), rasterize(triangles, camera)
    for name in ("depth", "normal", "identity", "surface_s", "surface_t", "edges"):
        assert one.layer_bytes(name) == two.layer_bytes(name)


def _record(tmp_path):
    triangles, camera = quad_scene()
    store = LayerStore(tmp_path / "layers")
    raw = build_structure(
        source=SOURCE,
        camera=camera,
        name="quad",
        legend=LEGEND,
        layers=rasterize(triangles, camera),
        code_sha256="4" * 64,
        reasons=REASONS,
        store=store,
    )
    return raw, store


def test_a_structure_record_round_trips_through_its_store(tmp_path):
    raw, store = _record(tmp_path)
    document = read_structure(raw)
    layers = load_layers(document, store)
    assert layers["depth"][24, 32] == 5_000_000
    assert layers["normal"].shape == (48, 64, 3)


def test_a_tampered_layer_is_refused(tmp_path):
    raw, store = _record(tmp_path)
    document = read_structure(raw)
    entry = document["layers"][0]
    path = store.directory / f"{entry['sha256']}.bin.z"
    import zlib

    path.write_bytes(zlib.compress(b"\0" * entry["byte_length"]))
    with pytest.raises(Refused, match="recorded digest"):
        load_layers(document, store)


@pytest.mark.parametrize(
    "change, words",
    [
        (lambda d: d["reasons"].pop("plane_tolerance_um"), "reasons"),
        (lambda d: d["reasons"].update(prompt="not a structure choice"), "reasons"),
        (lambda d: d.update(truth="observed"), "truth is invented"),
        (lambda d: d["layers"].reverse(), "in that order"),
        (lambda d: d["layers"][0].update(byte_length=12), "over the camera's pixels"),
        (lambda d: d["parameters"].update(plane_tolerance_um=1), "parameters"),
        (lambda d: d["legend"][0].update(identity=2), "legend identities"),
        (lambda d: d["source"].update(kind="tile"), "only source"),
        (lambda d: d["camera"].update(up=[0, 0, 1]), "up is"),
    ],
)
def test_the_structure_reader_refuses_a_record_out_of_shape(tmp_path, change, words):
    raw, _ = _record(tmp_path)
    document = parse_canonical(raw, "test")
    change(document)
    with pytest.raises(Refused, match=words):
        read_structure(canonical_bytes(document))
