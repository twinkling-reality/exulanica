"""Architecture pieces in authored kits: they hold their declared size, the product reads them, the
same document builds the same bytes, and numbers that would break a piece refuse before output."""

import copy
import hashlib
import json
from pathlib import Path

import pytest

np = pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
from scripts.style_packs.architecture import (  # noqa: E402
    ARCHITECTURE_RECIPES,
    ARCHITECTURE_SWATCHES,
    MINIMUM_MM,
)
from scripts.style_packs.garden_kit import build, validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GARDEN = ROOT / "assets/style-packs/authoring/water-garden-kit.v1.json"
KEYS = {key for key, *_ in ARCHITECTURE_SWATCHES}

ROWS = {
    "arcade": {
        "recipe": "arcade_block",
        "size_mm": [36000, 14000, 18000],
        "segments": 12,
        "bays": 7,
        "storeys": 2,
        "arch": "round",
        "ground_share_permille": 380,
        "pier_share_permille": 260,
        "loggia_depth_mm": 4500,
        "roof_balustrade": True,
    },
    "arcade-pointed-low": {
        "recipe": "arcade_block",
        "size_mm": [24000, 12000, 9000],
        "segments": 12,
        "bays": 5,
        "storeys": 0,
        "arch": "pointed",
        "ground_share_permille": 600,
        "pier_share_permille": 200,
        "loggia_depth_mm": 3000,
        "roof_balustrade": False,
    },
    "colonnade": {
        "recipe": "colonnade",
        "size_mm": [30000, 6000, 7000],
        "segments": 16,
        "columns": 9,
    },
    "colonnade-single": {
        "recipe": "colonnade",
        "size_mm": [12000, 3000, 5000],
        "segments": 16,
        "columns": 5,
    },
    "tower-pyramid": {
        "recipe": "tower",
        "size_mm": [8000, 8000, 36000],
        "segments": 10,
        "stages": 4,
        "roof": "pyramid",
        "arch": "round",
    },
    "tower-dome": {
        "recipe": "tower",
        "size_mm": [9000, 9000, 30000],
        "segments": 10,
        "stages": 3,
        "roof": "dome",
        "arch": "round",
    },
    "tower-terrace": {
        "recipe": "tower",
        "size_mm": [7000, 7000, 24000],
        "segments": 10,
        "stages": 3,
        "roof": "terrace",
        "arch": "pointed",
    },
    "stair": {
        "recipe": "stair_flight",
        "size_mm": [6000, 12000, 7000],
        "segments": 8,
        "riser_mm": 160,
        "cheek_mm": 400,
    },
    "pavilion": {
        "recipe": "pavilion",
        "size_mm": [16000, 10000, 7000],
        "segments": 8,
        "columns": 6,
    },
    "hall": {
        "recipe": "hall",
        "size_mm": [50000, 22000, 24000],
        "segments": 10,
        "bays": 9,
        "arch": "round",
    },
    "balustrade": {"recipe": "balustrade", "size_mm": [3000, 320, 1050], "segments": 8},
}


def _at_minimum(row: dict) -> dict:
    smallest = dict(row)
    smallest["size_mm"] = list(MINIMUM_MM[row["recipe"]])
    if row["recipe"] == "stair_flight":
        smallest["cheek_mm"] = 200
    return smallest


CASES = {**ROWS, **{f"{name}-at-minimum": _at_minimum(row) for name, row in ROWS.items()}}


@pytest.mark.parametrize("name", sorted(CASES))
def test_every_recipe_stays_inside_its_declared_size(name):
    row = CASES[name]
    piece = ARCHITECTURE_RECIPES[row["recipe"]](row)
    points = np.asarray(piece.corners)
    width, depth, height = [n / 1000 for n in row["size_mm"]]
    assert len(piece.keys) > 0 and set(piece.keys) <= KEYS
    assert np.all(points.min(0) >= np.asarray([-width / 2, 0, -depth / 2]) - 0.0001)
    assert np.all(points.max(0) <= np.asarray([width / 2, height, depth / 2]) + 0.0001)


def _document() -> dict:
    garden = json.loads(GARDEN.read_text())
    variant = copy.deepcopy(garden["variants"][0])
    variant.update(
        pack_id="original.arcade-test",
        title="Arcade test",
        architecture_srgb8={"stone": [200, 190, 170]},
    )
    roles = {
        "arcade": "structure.bathhouse",
        "tower-pyramid": "structure.lantern_tower",
        "pavilion": "structure.cafe",
        "hall": "structure.great_hall",
        "balustrade": "boundary.balustrade",
    }
    pieces = [
        {**ROWS[name], "role": role, "file": f"pieces/{name}.glb"} for name, role in roles.items()
    ]
    return {**garden, "pieces": pieces, "variants": [variant]}


def test_a_kit_with_architecture_builds_pieces_the_product_reads(tmp_path):
    # build() reads every piece back with the product's own palette piece reader and the manifest
    # with the style pack reader, so a returned build is one the product accepts.
    build(_document(), tmp_path)
    manifest = json.loads((tmp_path / "original.arcade-test/manifest.json").read_text())
    assert {"structure.bathhouse", "structure.great_hall", "boundary.balustrade"} <= set(
        manifest["modules"]
    )
    swatches = {s["key"]: s["srgb8"] for s in manifest["palette"]["swatches"]}
    assert set(swatches) >= KEYS
    assert swatches["stone"] == [200, 190, 170]
    assert swatches["trim"] == [240, 232, 214]


def test_the_same_document_builds_the_same_bytes(tmp_path):
    build(_document(), tmp_path / "a")
    build(_document(), tmp_path / "b")
    first = sorted((tmp_path / "a").rglob("*"))
    for path in first:
        if path.is_file():
            twin = tmp_path / "b" / path.relative_to(tmp_path / "a")
            assert (
                hashlib.sha256(path.read_bytes()).digest()
                == hashlib.sha256(twin.read_bytes()).digest()
            )


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d["pieces"][0].update(bays=0),
        lambda d: d["pieces"][0].update(arch="ogee"),
        lambda d: d["pieces"][0].update(roof_balustrade="yes"),
        lambda d: d["pieces"][0].update(size_mm=[5000, 14000, 18000]),
        lambda d: d["pieces"][1].update(roof="onion"),
        lambda d: d["pieces"][1].update(stages=9),
        lambda d: d["pieces"][2].update(columns=1),
        lambda d: d["pieces"][3].update(bays=25),
        lambda d: d["variants"][0].update(architecture_srgb8={"marble": [1, 2, 3]}),
        lambda d: d["variants"][0].update(architecture_srgb8={"stone": [1, 2, 300]}),
    ],
)
def test_numbers_that_would_break_a_piece_refuse_before_output(change):
    document = _document()
    change(document)
    with pytest.raises(ValueError):
        validate_document(document)


def test_a_stair_with_a_riser_too_tall_to_climb_refuses():
    document = _document()
    document["pieces"].append(
        {**ROWS["stair"], "riser_mm": 300, "role": "prop.stair", "file": "pieces/stair.glb"}
    )
    with pytest.raises(ValueError):
        validate_document(document)
