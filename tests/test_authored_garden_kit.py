"""Authored reusable module envelopes and reproducibility, independent of a world identity."""

import hashlib
import json
from pathlib import Path

import pytest

np = pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
from scripts.style_packs.garden_kit import RECIPES, build, validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "assets/style-packs/authoring/water-garden-kit.v1.json"


def test_authored_modules_fit_declared_geometry_and_roof_clearance():
    document = json.loads(DOCUMENT.read_text())
    validate_document(document)
    for row in document["pieces"]:
        piece = RECIPES[row["recipe"]](row)
        points = np.asarray(piece.corners)
        width, depth, height = [n / 1000 for n in row["size_mm"]]
        assert np.all(points.min(0) >= np.asarray([-width / 2, 0, -depth / 2]) - 0.0001)
        assert np.all(points.max(0) <= np.asarray([width / 2, height, depth / 2]) + 0.0001)
        if row["recipe"] == "vault_shell":
            assert np.all(
                points[:, 1] <= height * (1 - np.abs(points[:, 2]) / (depth / 2)) + 0.0001
            )
        if row["recipe"] == "rounded_seat":
            assert points[:, 1].min() == 0
            assert points[:, 1].max() == height


def test_rebuilding_both_palette_variants_preserves_admitted_bytes(tmp_path):
    build(json.loads(DOCUMENT.read_text()), tmp_path)
    for folder in tmp_path.iterdir():
        for file in folder.rglob("*"):
            if file.is_file():
                expected = ROOT / "assets/style-packs/kits" / file.relative_to(tmp_path)
                assert (
                    hashlib.sha256(file.read_bytes()).digest()
                    == hashlib.sha256(expected.read_bytes()).digest()
                )


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["pieces"][0].update(size_mm=[0, 12000, 4200]),
        lambda d: d["pieces"][0].update(segments=True),
        lambda d: d["pieces"][0].update(file="../escaped.glb"),
    ],
)
def test_unsafe_authoring_parameters_refuse_before_output(change):
    document = json.loads(DOCUMENT.read_text())
    change(document)
    with pytest.raises(ValueError):
        validate_document(document)
