"""The tree maker: a species of the committed catalog grown to its box as a textured piece.

The scans the catalog names are not in this repository, so each test writes synthetic ones (leaves
on an opacity mask, a bark and its normal map) at the catalog's paths and states their digests in a
copy of the catalog. The species' own figures are the committed ones.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)
from exulanica.world.style_pack_pieces import (  # noqa: E402
    PieceOutOfBounds,
    check_piece_profile,
    hold_pieces,
    read_textured_piece,
)
from exulanica.world.style_packs import load_context, read_manifest  # noqa: E402
from exulanica_pieces.budgets import read_budgets  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scripts.style_packs import tree_maker  # noqa: E402
from scripts.style_packs.garden_kit import build  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / tree_maker.CATALOG).read_text())
BUDGETS = read_budgets(ROOT)


def _jpeg(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def _leaf_scan(points_deg: int) -> tuple[bytes, bytes]:
    """Four leaves in a 2 by 2 grid on nothing, pointing up (90) or right (0)."""
    colour = Image.new("RGB", (256, 256), (40, 40, 40))
    opacity = Image.new("L", (256, 256), 0)
    paint, mask = ImageDraw.Draw(colour), ImageDraw.Draw(opacity)
    for k in range(4):
        x, y = (k % 2) * 128, (k // 2) * 128
        box = (
            [x + 44, y + 12, x + 84, y + 116]
            if points_deg == 90
            else [x + 12, y + 44, x + 116, y + 84]
        )
        paint.ellipse(box, fill=(60 + 20 * k, 130, 50))
        mask.ellipse(box, fill=255)
    return _jpeg(colour), _jpeg(opacity.convert("RGB"))


def _bark() -> tuple[bytes, bytes]:
    rng = np.random.default_rng(7)
    noise = rng.integers(60, 140, size=(256, 128, 3), dtype=np.uint8)
    return _jpeg(Image.fromarray(noise, "RGB")), _jpeg(
        Image.new("RGB", (128, 256), (128, 128, 255))
    )


@pytest.fixture(scope="module")
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    """The committed catalog with synthetic scans written at its paths, and their folder."""
    folder = tmp_path_factory.mktemp("scans")
    catalog = copy.deepcopy(CATALOG)
    for leaf in catalog["sources"]["leaves"].values():
        colour, opacity = _leaf_scan(leaf["points_deg"])
        for stated, data in ((leaf["colour"], colour), (leaf["opacity"], opacity)):
            (folder / stated["path"]).parent.mkdir(parents=True, exist_ok=True)
            (folder / stated["path"]).write_bytes(data)
            stated["sha256"] = hashlib.sha256(data).hexdigest()
    for bark in catalog["sources"]["barks"].values():
        for stated, data in zip((bark["colour"], bark["normal"]), _bark(), strict=True):
            (folder / stated["path"]).parent.mkdir(parents=True, exist_ok=True)
            (folder / stated["path"]).write_bytes(data)
            stated["sha256"] = hashlib.sha256(data).hexdigest()
    return tree_maker.read_catalog(catalog), folder


def _tree(
    made: tuple[dict[str, Any], Path],
    species: str,
    height: int,
    seed: int,
    width: int | None = None,
):
    catalog, folder = made
    return tree_maker.make_tree(
        catalog, species, height, seed, tree_maker.Sources(catalog, folder), width
    )


def test_the_committed_catalog_reads_and_names_every_species():
    catalog = tree_maker.read_catalog(copy.deepcopy(CATALOG))
    assert set(catalog["species"]) == {
        "broad_canopy", "stone_pine", "italian_cypress", "olive",
        "fan_palm", "round_shrub", "oleander", "flower_bed",
    }  # fmt: skip


def test_the_same_row_makes_the_same_bytes(made):
    first = _tree(made, "olive", 6000, 41)
    again = _tree(made, "olive", 6000, 41)
    assert (first.lod0, first.lod1, first.receipt) == (again.lod0, again.lod1, again.receipt)
    assert _tree(made, "olive", 6000, 42).lod0 != first.lod0


def _pictures(data: bytes) -> tuple[str, ...]:
    """The digests of the pictures a piece embeds, as the pack's count reads them."""
    return check_piece_profile(data).image_sha256


def _hold(grown: list[tree_maker.MadeTree], textures: int) -> dict[str, int]:
    """Trees as one role's variants, each with its second level, held as a pack holds them beside
    ``textures`` texture pictures of their own."""
    pieces, files = {}, {}
    for index, tree in enumerate(grown):
        first, far = f"pieces/tree-{index}.glb", f"pieces/tree-{index}-far.glb"
        variant = {
            "file": first,
            "lod1": far,
            "size_mm": list(tree.size_mm),
            "stretch_mm": [None, None, None],
        }
        pieces |= {first: ("plant", variant, False), far: ("plant", variant, True)}
        files |= {first: tree.lod0, far: tree.lod1}
    return hold_pieces(
        pieces,
        files.__getitem__,
        BUDGETS.families,
        BUDGETS.lod1_share_permille,
        [f"{k:064x}" for k in range(textures)],
    )


def test_a_species_variants_carry_its_pictures_and_their_own_branches(made):
    first, second = (_tree(made, "olive", 6000, seed) for seed in (41, 42))
    for level in ("lod0", "lod1"):
        a, b = getattr(first, level), getattr(second, level)
        # Bark, its normal map and the leaf sheet: the same three for every olive.
        assert _pictures(a) == _pictures(b) and len(set(_pictures(a))) == 3
        assert a != b
    assert [lod["pictures_sha256"] for lod in first.receipt["lods"]] == [
        list(_pictures(first.lod0)),
        list(_pictures(first.lod1)),
    ]


def test_two_species_carry_leaves_of_their_own(made):
    olive, pine = (_tree(made, name, 6000, 41) for name in ("olive", "stone_pine"))
    for level in ("lod0", "lod1"):
        # The leaf sheet is each species' own; the tests' scans give every bark one picture.
        assert _pictures(getattr(olive, level))[2] != _pictures(getattr(pine, level))[2]


def test_a_species_several_variants_count_in_a_pack_as_one_variant_does(made):
    one = [_tree(made, "olive", 6000, 51)]
    three = one + [_tree(made, "olive", 6000, seed) for seed in (52, 53)]
    room = 64 - len(set(_pictures(one[0].lod0) + _pictures(one[0].lod1)))
    # One variant's pictures beside textures up to the bound fill the count, and so do three's.
    assert _hold(one, room) and _hold(three, room)
    for grown in (one, three):
        with pytest.raises(PieceOutOfBounds) as over:
            _hold(grown, room + 1)
        assert str(over.value) == "files: draws with 65 pictures; at most 64"


@pytest.mark.parametrize("species", ["broad_canopy", "italian_cypress", "fan_palm", "oleander"])
def test_a_tree_holds_the_plant_budget_and_reads_as_the_product_reads_it(made, species):
    tree = _tree(made, species, 9000 if species != "oleander" else 1200, 11)
    files = {"pieces/tree.glb": tree.lod0, "pieces/tree-far.glb": tree.lod1}
    variant = {
        "file": "pieces/tree.glb",
        "lod1": "pieces/tree-far.glb",
        "size_mm": list(tree.size_mm),
        "stretch_mm": [None, None, None],
    }
    held = hold_pieces(
        {
            "pieces/tree.glb": ("plant", variant, False),
            "pieces/tree-far.glb": ("plant", variant, True),
        },
        files.__getitem__,
        BUDGETS.families,
        BUDGETS.lod1_share_permille,
    )
    assert (
        held["pieces/tree-far.glb"] <= held["pieces/tree.glb"] * BUDGETS.lod1_share_permille // 1000
    )
    for data in files.values():
        assert check_piece_profile(data).textured
        assert read_textured_piece(data).images == 3


def test_a_tree_is_grown_to_its_box_and_its_second_level_stands_inside_it(made):
    tree = _tree(made, "fan_palm", 9000, 51, 3000)
    assert tree.size_mm[2] == 9000
    assert max(tree.size_mm[:2]) <= 3001
    first, second = tree.receipt["lods"]
    assert all(far <= near for far, near in zip(second["size_mm"], first["size_mm"], strict=True))
    assert tree.receipt["width_mm"] == 3000 and tree.receipt["spread"] < 1.0


def test_a_scan_that_is_not_the_catalogs_is_refused_by_its_path(made):
    catalog, folder = made
    changed = copy.deepcopy(catalog)
    changed["sources"]["barks"]["fissured"]["colour"]["sha256"] = "0" * 64
    with pytest.raises(tree_maker.TreeCatalogRefused) as refused:
        tree_maker.make_tree(changed, "olive", 6000, 41, tree_maker.Sources(changed, folder))
    assert refused.value.path == changed["sources"]["barks"]["fissured"]["colour"]["path"]


@pytest.mark.parametrize(
    ("edit", "path"),
    [
        (
            lambda c: c["species"]["stone_pine"]["branch"].update(levels=5),
            "$.species.stone_pine.branch.levels",
        ),
        (
            lambda c: c["species"]["olive"]["card"].update(form="wreath"),
            "$.species.olive.card.form",
        ),
        (lambda c: c["species"]["olive"].update(bark="cork"), "$.species.olive.bark"),
        (
            lambda c: c["species"]["olive"]["leaves"].update(colour=[1, 2, 3]),
            "$.species.olive.leaves",
        ),
        (
            lambda c: c["species"]["fan_palm"]["lod1"].update(leaf_scale=9),
            "$.species.fan_palm.lod1.leaf_scale",
        ),
        (lambda c: c["textures"]["lod0"].update(sheet_px=4096), "$.textures.lod0.sheet_px"),
        (
            lambda c: c["sources"]["leaves"]["oval"]["colour"].update(path="../x.jpg"),
            "$.sources.leaves.oval.colour.path",
        ),
        (
            lambda c: c["species"]["olive"].update(sway_permille=4001),
            "$.species.olive.sway_permille",
        ),
        (
            lambda c: c["species"]["olive"].update(sway_permille=1.5),
            "$.species.olive.sway_permille",
        ),
    ],
    ids=[
        "levels",
        "card form",
        "bark",
        "unknown field",
        "far leaf scale",
        "sheet side",
        "path outside",
        "sway past its range",
        "sway a fraction",
    ],
)
def test_a_catalog_out_of_its_ranges_is_refused_by_the_path_that_broke_it(edit: Any, path: str):
    catalog = copy.deepcopy(CATALOG)
    edit(catalog)
    with pytest.raises(tree_maker.TreeCatalogRefused) as refused:
        tree_maker.read_catalog(catalog)
    assert refused.value.path == path


def test_tree_rows_of_one_role_become_its_variants_each_with_its_second_level(
    made, tmp_path, monkeypatch
):
    catalog, folder = made
    monkeypatch.setattr(tree_maker, "read_catalog", lambda _document: catalog)
    document = json.loads(
        (ROOT / "assets/style-packs/authoring/water-garden-kit.v1.json").read_text()
    )
    document["variants"] = document["variants"][:1]
    document["pieces"] += [
        {
            "recipe": "tree",
            "role": "plant.pine_wood",
            "file": "pieces/pine.glb",
            "species": "stone_pine",
            "height_mm": 9000,
            "seed": 21,
            "width_mm": 5000,
        },
        {
            "recipe": "tree",
            "role": "plant.pine_wood",
            "file": "pieces/cypress.glb",
            "species": "italian_cypress",
            "height_mm": 9000,
            "seed": 31,
        },
    ]
    build(document, tmp_path, folder)
    pack = document["variants"][0]["pack_id"]
    manifest = json.loads((tmp_path / pack / "manifest.json").read_text())
    read_manifest(manifest, load_context(ROOT))
    variants = manifest["modules"]["plant.pine_wood"]["variants"]
    assert [(v["file"], v["lod1"]) for v in variants] == [
        ("pieces/pine.glb", "pieces/pine-far.glb"),
        ("pieces/cypress.glb", "pieces/cypress-far.glb"),
    ]
    # Each variant takes its species' share of the look's wind: a stiff cypress less than a pine.
    assert [v["sway_permille"] for v in variants] == [
        CATALOG["species"]["stone_pine"]["sway_permille"],
        CATALOG["species"]["italian_cypress"]["sway_permille"],
    ]
    assert variants[1]["sway_permille"] < variants[0]["sway_permille"]
    receipts = json.loads((tmp_path / f"{pack}.trees.json").read_text())
    assert [r["species"] for r in receipts] == ["stone_pine", "italian_cypress"]
    with pytest.raises(ValueError, match="names the folder of its scans"):
        build(document, tmp_path / "again")
