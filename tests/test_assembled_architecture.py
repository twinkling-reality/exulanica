"""Architecture modules for kits pinned to appearance catalog version 3: an arcade block, a tower
and a hall made as one bay and one storey that repeat to meet a building's box.

Each module stays inside its own size, cuts every face at its zones' edges so the server's check
passes it, holds the structure family's budget, and gives back its row's own size when drawn with
the row's bays and storeys. A version 3 kit states each module's zones; a version 1 or 2 kit makes
the same rows whole, at their size, as before.
"""

import copy
import json
from pathlib import Path

import pytest

np = pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
from exulanica.world.style_pack_checks import colour_table  # noqa: E402
from exulanica.world.style_pack_pieces import check_piece_profile, check_repeat_zones  # noqa: E402
from exulanica_pieces.budgets import read_budgets  # noqa: E402
from scripts.style_packs.architecture import ARCHITECTURE_SWATCHES  # noqa: E402
from scripts.style_packs.assembled_architecture import (  # noqa: E402
    ASSEMBLED_RECIPES,
    split_at,
)
from scripts.style_packs.authored_packs import Piece  # noqa: E402
from scripts.style_packs.garden_kit import build, validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GARDEN = ROOT / "assets/style-packs/authoring/water-garden-kit.v1.json"
TABLE = colour_table(ROOT)
BUDGET = read_budgets(ROOT).families["structure"]
PALETTE = [
    {"key": key, "srgb8": list(rgb), "roughness_permille": rough, "metalness_permille": metal}
    for key, rgb, rough, metal in ARCHITECTURE_SWATCHES
]

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
    "arcade-tall-pointed": {
        "recipe": "arcade_block",
        "size_mm": [15000, 24000, 36000],
        "segments": 12,
        "bays": 4,
        "storeys": 6,
        "arch": "pointed",
        "ground_share_permille": 250,
        "pier_share_permille": 300,
        "loggia_depth_mm": 4000,
        "roof_balustrade": False,
    },
    "arcade-no-storeys": {
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
        "size_mm": [9000, 10000, 30000],
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
    "hall": {
        "recipe": "hall",
        "size_mm": [50000, 22000, 24000],
        "segments": 10,
        "bays": 9,
        "arch": "round",
    },
}


def _zone_length(zone):
    return 0 if zone is None else zone[1] - zone[0]


@pytest.mark.parametrize("name", sorted(ROWS))
def test_a_module_stays_inside_its_size_and_no_triangle_crosses_a_zone(name):
    row = ROWS[name]
    module = ASSEMBLED_RECIPES[row["recipe"]](row)
    width, depth, height = [n / 1000 for n in module.size_mm]
    points = np.asarray(module.piece.corners)
    assert set(module.piece.keys) <= {swatch["key"] for swatch in PALETTE}
    assert np.all(points.min(0) >= np.asarray([-width / 2, 0, -depth / 2]) - 0.0001)
    assert np.all(points.max(0) <= np.asarray([width / 2, height, depth / 2]) + 0.0001)
    for zones in (module.stretch_mm, module.repeat_mm):
        for axis, zone in enumerate(zones):
            assert zone is None or 0 <= zone[0] < zone[1] <= module.size_mm[axis]
    # An axis stretches or repeats, not both.
    assert all(
        s is None or r is None for s, r in zip(module.stretch_mm, module.repeat_mm, strict=True)
    )
    data = module.piece.bytes(PALETTE, TABLE)
    variant = {
        "size_mm": list(module.size_mm),
        "repeat_mm": [None if z is None else list(z) for z in module.repeat_mm],
    }
    check_repeat_zones(data, variant)
    profile = check_piece_profile(data)
    assert profile.triangles <= BUDGET.triangles and len(data) <= BUDGET.glb_bytes


@pytest.mark.parametrize("name", sorted(ROWS))
def test_drawn_with_its_rows_bays_and_storeys_a_module_is_its_rows_size(name):
    row = ROWS[name]
    module = ASSEMBLED_RECIPES[row["recipe"]](row)
    # How many bays across and storeys (or stages) up the row states.
    width_copies, height_copies = {
        "arcade_block": lambda: (row["bays"], row["storeys"]),
        "tower": lambda: (1, row["stages"]),
        "hall": lambda: (row["bays"], 1),
    }[row["recipe"]]()
    width = module.size_mm[0] + (width_copies - 1) * _zone_length(module.repeat_mm[0])
    height = module.size_mm[2] + (height_copies - 1) * _zone_length(module.repeat_mm[2])
    # Each bay and storey is drawn to the whole millimetre: the row's size within one a copy.
    assert abs(width - row["size_mm"][0]) <= width_copies
    if height_copies > 1 or row["recipe"] != "arcade_block":
        assert abs(height - row["size_mm"][2]) <= height_copies
    assert module.size_mm[1] == row["size_mm"][1]


def test_a_cut_keeps_each_parts_winding_and_the_whole_area():
    piece = Piece()
    piece.face([(-1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 2.0, 0.0)], "stone", (0.0, 0.0, 1.0))
    cut = split_at(piece, [[-0.25, 0.5], [1.0], []])
    corners = np.asarray(cut.corners).reshape(-1, 3, 3)
    normals = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    assert len(cut.keys) > 3 and set(cut.keys) == {"stone"}
    assert np.all(normals[:, 2] > 0)
    assert np.isclose(np.linalg.norm(normals, axis=1).sum() / 2, 2.0)
    for lows, highs, cutoff in ((corners[:, :, 0].min(1), corners[:, :, 0].max(1), (-0.25, 0.5)),):
        for edge in cutoff:
            assert not np.any((lows < edge - 1e-9) & (highs > edge + 1e-9))


def _document(version: int) -> dict:
    garden = json.loads(GARDEN.read_text())
    variant = copy.deepcopy(garden["variants"][0])
    variant.update(pack_id=f"original.assembled-v{version}", title="Assembled test")
    roles = {
        "arcade": "structure.bathhouse",
        "tower-dome": "structure.lantern_tower",
        "hall": "structure.great_hall",
    }
    pieces = [
        {**ROWS[name], "role": role, "file": f"pieces/{name}.glb"} for name, role in roles.items()
    ]
    return {
        **garden,
        "look_family_catalog_version": version,
        "pieces": pieces,
        "variants": [variant],
    }


def test_a_version_3_kit_states_each_modules_zones_and_a_version_2_kit_makes_rows_whole(tmp_path):
    # build() reads every piece back with the product's palette reader and the manifest with the
    # style pack reader against the catalog the kit pins.
    build(_document(3), tmp_path)
    folder = tmp_path / "original.assembled-v3"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["look_family_catalog"]["version"] == 3
    for role in ("structure.bathhouse", "structure.lantern_tower", "structure.great_hall"):
        (variant,) = manifest["modules"][role]["variants"]
        assert any(zone is not None for zone in variant["repeat_mm"])
        check_repeat_zones((folder / variant["file"]).read_bytes(), variant)
    bathhouse = manifest["modules"]["structure.bathhouse"]["variants"][0]
    assert (
        bathhouse["stretch_mm"][1] is not None
        and bathhouse["size_mm"][0] < ROWS["arcade"]["size_mm"][0]
    )
    build(_document(2), tmp_path)
    whole = json.loads((tmp_path / "original.assembled-v2/manifest.json").read_text())
    for name, role in (("arcade", "structure.bathhouse"), ("hall", "structure.great_hall")):
        (variant,) = whole["modules"][role]["variants"]
        assert "repeat_mm" not in variant
        assert variant["size_mm"] == ROWS[name]["size_mm"]
        assert variant["stretch_mm"] == [None, None, None]


@pytest.mark.parametrize(
    "change",
    [
        lambda pieces: pieces[0].update(bays=24),
        lambda pieces: pieces[0].update(storeys=8),
        lambda pieces: pieces[2].update(size_mm=[30000, 22000, 24000], bays=15),
    ],
    ids=["arcade bays under 2 m", "storeys under 2.5 m", "hall bays under 2 m"],
)
def test_a_row_whose_module_would_break_refuses_in_a_version_3_kit_only(change):
    for version, refused in ((3, True), (2, False)):
        document = _document(version)
        change(document["pieces"])
        if refused:
            with pytest.raises(ValueError):
                validate_document(document)
        else:
            validate_document(document)
