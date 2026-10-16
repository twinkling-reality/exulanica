"""The creeper maker: a climbing plant of the committed catalog grown over a wall patch as a
textured piece, held to the plant budget, and the kit rows that make a look's climbing plants.

The scans the tree species catalog names are not in this repository, so each test writes synthetic
ones (leaves on an opacity mask, a bark and its normal map) at the catalog's paths and states their
digests in a copy of that catalog. The creeper species' own figures are the committed ones.
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
from exulanica_pieces.budgets import read_budgets  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402
from scripts.style_packs import creeper_maker, tree_maker  # noqa: E402
from scripts.style_packs.garden_kit import build, validate_document  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TREES = json.loads((ROOT / tree_maker.CATALOG).read_text())
CREEPERS = json.loads((ROOT / creeper_maker.CATALOG).read_text())
BUDGETS = read_budgets(ROOT)
PLANT = BUDGETS.families["plant"]
GARDEN = ROOT / "assets/style-packs/authoring/water-garden-kit.v1.json"


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
def made(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """The committed creeper catalog read against the tree catalog with synthetic scans written
    at its paths, the tree catalog, and the scans' folder."""
    folder = tmp_path_factory.mktemp("scans")
    trees = copy.deepcopy(TREES)
    for leaf in trees["sources"]["leaves"].values():
        for stated, data in zip(
            (leaf["colour"], leaf["opacity"]), _leaf_scan(leaf["points_deg"]), strict=True
        ):
            (folder / stated["path"]).parent.mkdir(parents=True, exist_ok=True)
            (folder / stated["path"]).write_bytes(data)
            stated["sha256"] = hashlib.sha256(data).hexdigest()
    for bark in trees["sources"]["barks"].values():
        for stated, data in zip((bark["colour"], bark["normal"]), _bark(), strict=True):
            (folder / stated["path"]).parent.mkdir(parents=True, exist_ok=True)
            (folder / stated["path"]).write_bytes(data)
            stated["sha256"] = hashlib.sha256(data).hexdigest()
    trees = tree_maker.read_catalog(trees)
    return creeper_maker.read_catalog(copy.deepcopy(CREEPERS), trees), trees, folder


def _creeper(made, species: str, width: int, height: int, seed: int, most: int = PLANT.triangles):
    catalog, trees, folder = made
    return creeper_maker.make_creeper(
        catalog,
        species,
        width,
        height,
        seed,
        tree_maker.Sources(trees, folder),
        most,
        BUDGETS.lod1_share_permille,
    )


def test_the_committed_catalog_reads_and_names_its_species():
    catalog = creeper_maker.read_catalog(
        copy.deepcopy(CREEPERS), tree_maker.read_catalog(copy.deepcopy(TREES))
    )
    assert set(catalog["species"]) == {"ivy", "bougainvillea"}
    assert catalog["sources"] in creeper_maker.SOURCES


@pytest.mark.parametrize("species", ["ivy", "bougainvillea"])
def test_a_patch_holds_the_plant_budget_and_reads_as_the_product_reads_it(made, species):
    grown = _creeper(made, species, 4000, 7000, 11)
    variant = {
        "file": "pieces/creeper.glb",
        "lod1": "pieces/creeper-far.glb",
        "size_mm": list(grown.size_mm),
        "stretch_mm": [None, None, None],
    }
    files = {"pieces/creeper.glb": grown.lod0, "pieces/creeper-far.glb": grown.lod1}
    measured = hold_pieces(
        {
            "pieces/creeper.glb": ("plant", variant, False),
            "pieces/creeper-far.glb": ("plant", variant, True),
        },
        files.__getitem__,
        BUDGETS.families,
        BUDGETS.lod1_share_permille,
    )
    assert measured["pieces/creeper.glb"] <= PLANT.triangles
    for data in files.values():
        assert check_piece_profile(data).textured and len(data) <= PLANT.glb_bytes
        read_textured_piece(data)
    assert grown.sway_permille == CREEPERS["species"][species]["sway_permille"]


def test_a_patch_stays_inside_its_wall_patch_and_stands_out_from_its_wall(made):
    grown = _creeper(made, "ivy", 3000, 5000, 5)
    width, depth, height = grown.size_mm
    assert (width, height) == (3000, 5000) and depth > 0
    document = json.loads(grown.lod0[20 : 20 + int.from_bytes(grown.lod0[12:16], "little")])
    bounded = [a for a in document["accessors"] if a["type"] == "VEC3" and "min" in a]
    assert len(bounded) == 2  # the stems' positions and the leaves'
    for accessor in bounded:
        low, high = accessor["min"], accessor["max"]
        assert low[0] >= -1.5001 and high[0] <= 1.5001
        assert low[1] >= -0.0001 and high[1] <= 5.0001
        assert low[2] >= -0.0001 and high[2] <= depth / 2000 + 0.0001


def test_the_same_row_makes_the_same_bytes_and_another_seed_another_patch(made):
    first = _creeper(made, "ivy", 2000, 6000, 41)
    assert _creeper(made, "ivy", 2000, 6000, 41).lod0 == first.lod0
    assert _creeper(made, "ivy", 2000, 6000, 42).lod0 != first.lod0
    assert first.receipt["species"] == "ivy" and first.receipt["seed"] == 41


def _pictures(data: bytes) -> tuple[str, ...]:
    """The digests of the pictures a piece embeds, as the pack's count reads them."""
    return check_piece_profile(data).image_sha256


def _positions(data: bytes) -> list[bytes]:
    """Each primitive's vertex positions, as the piece's binary chunk holds them."""
    length = int.from_bytes(data[12:16], "little")
    document = json.loads(data[20 : 20 + length])
    binary = data[20 + length + 8 :]
    views = [
        document["bufferViews"][document["accessors"][p["attributes"]["POSITION"]]["bufferView"]]
        for p in document["meshes"][0]["primitives"]
    ]
    return [binary[v["byteOffset"] : v["byteOffset"] + v["byteLength"]] for v in views]


def _hold(grown: list[creeper_maker.MadeCreeper], textures: int) -> dict[str, int]:
    """Patches as one role's variants, each with its second level, held as a pack holds them beside
    ``textures`` texture pictures of their own."""
    pieces, files = {}, {}
    for index, patch in enumerate(grown):
        first, far = f"pieces/creeper-{index}.glb", f"pieces/creeper-{index}-far.glb"
        variant = {
            "file": first,
            "lod1": far,
            "size_mm": list(patch.size_mm),
            "stretch_mm": [None, None, None],
        }
        pieces |= {first: ("plant", variant, False), far: ("plant", variant, True)}
        files |= {first: patch.lod0, far: patch.lod1}
    return hold_pieces(
        pieces,
        files.__getitem__,
        BUDGETS.families,
        BUDGETS.lod1_share_permille,
        [f"{k:064x}" for k in range(textures)],
    )


def test_a_species_variants_carry_its_pictures_and_their_own_geometry(made):
    first, second = (_creeper(made, "ivy", 2000, 3000, seed) for seed in (21, 22))
    for level in ("lod0", "lod1"):
        a, b = getattr(first, level), getattr(second, level)
        assert _pictures(a) == _pictures(b) and len(set(_pictures(a))) == 2
        assert _positions(a) != _positions(b)
    assert [lod["pictures_sha256"] for lod in first.receipt["lods"]] == [
        list(_pictures(first.lod0)),
        list(_pictures(first.lod1)),
    ]


def test_two_species_carry_pictures_of_their_own(made):
    ivy, bougainvillea = (_creeper(made, name, 2000, 3000, 21) for name in ("ivy", "bougainvillea"))
    for level in ("lod0", "lod1"):
        # The leaf sheet is each species' own; the tests' scans give every bark one picture.
        assert _pictures(getattr(ivy, level))[1] != _pictures(getattr(bougainvillea, level))[1]


def test_a_species_several_variants_count_in_a_pack_as_one_variant_does(made):
    one = [_creeper(made, "ivy", 2000, 3000, 31)]
    three = one + [_creeper(made, "ivy", 2000, 3000, seed) for seed in (32, 33)]
    # One variant's four pictures beside 60 of the textures' fill the count, and so do three's.
    assert _hold(one, 60) and _hold(three, 60)
    for grown in (one, three):
        with pytest.raises(PieceOutOfBounds) as over:
            _hold(grown, 61)
        assert str(over.value) == "files: draws with 65 pictures; at most 64"


def test_past_its_budget_a_patch_keeps_fewer_larger_cards(made):
    plenty = _creeper(made, "ivy", 4000, 7000, 3)
    held = _creeper(made, "ivy", 4000, 7000, 3, most=400)
    assert held.receipt["lods"][0]["triangles"] <= 400
    assert held.receipt["cards"]["kept"] < plenty.receipt["cards"]["kept"]
    assert held.receipt["cards"]["size_m"] > plenty.receipt["cards"]["size_m"]


@pytest.mark.parametrize(
    ("edit", "path"),
    [
        (lambda c: c["species"]["ivy"]["card"].update(source="fern"), "$.species.ivy.card.source"),
        (lambda c: c["species"]["ivy"]["stem"].update(bark="cork"), "$.species.ivy.stem.bark"),
        (lambda c: c["species"]["ivy"]["growth"].update(depth=4), "$.species.ivy.growth.depth"),
        (
            lambda c: c["species"]["ivy"]["cards"].update(tilt_deg=[40, 10]),
            "$.species.ivy.cards.tilt_deg",
        ),
        (lambda c: c["species"]["ivy"].update(sway_permille=5000), "$.species.ivy.sway_permille"),
        (lambda c: c.update(sources="tree-species.v9"), "$.sources"),
    ],
)
def test_a_catalog_out_of_its_ranges_is_refused_by_the_path_that_broke_it(edit, path):
    catalog = copy.deepcopy(CREEPERS)
    edit(catalog)
    with pytest.raises(creeper_maker.CreeperCatalogRefused) as refused:
        creeper_maker.read_catalog(catalog, tree_maker.read_catalog(copy.deepcopy(TREES)))
    assert refused.value.path == path


def _document() -> dict[str, Any]:
    garden = json.loads(GARDEN.read_text())
    variant = copy.deepcopy(garden["variants"][0])
    variant.update(
        pack_id="original.climbing-test",
        title="Climbing test",
        climb={
            "structure.default": {
                "pieces": ["plant.climber"],
                "walls": ["back", "left", "right"],
                "share_permille": 400,
                "height_permille": [400, 800],
                "seed": 9,
            }
        },
    )
    rows = [
        {
            "recipe": "creeper",
            "role": "plant.climber",
            "file": f"pieces/{name}.glb",
            "species": species,
            "width_mm": 3000,
            "height_mm": 6000,
            "seed": seed,
        }
        for name, species, seed in (("ivy", "ivy", 1), ("bougainvillea", "bougainvillea", 2))
    ]
    return {**garden, "pieces": garden["pieces"] + rows, "variants": [variant]}


def test_creeper_rows_become_a_roles_variants_and_the_variant_states_what_climbs(
    made, tmp_path, monkeypatch
):
    _catalog, trees, folder = made
    monkeypatch.setattr(tree_maker, "read_catalog", lambda _document: trees)
    build(_document(), tmp_path, folder)
    manifest = json.loads((tmp_path / "original.climbing-test/manifest.json").read_text())
    variants = manifest["modules"]["plant.climber"]["variants"]
    assert [v["file"] for v in variants] == ["pieces/ivy.glb", "pieces/bougainvillea.glb"]
    assert all(v["lod1"] == v["file"][: -len(".glb")] + "-far.glb" for v in variants)
    assert [v["sway_permille"] for v in variants] == [
        CREEPERS["species"]["ivy"]["sway_permille"],
        CREEPERS["species"]["bougainvillea"]["sway_permille"],
    ]
    assert manifest["climb"]["structure.default"]["pieces"] == ["plant.climber"]
    receipts = json.loads((tmp_path / "original.climbing-test.creepers.json").read_text())
    assert [r["species"] for r in receipts] == ["ivy", "bougainvillea"]


@pytest.mark.parametrize(
    "change",
    [
        lambda row: row.pop("width_mm"),
        lambda row: row.update(height_mm=6000.5),
        lambda row: row.update(file="../out.glb"),
        lambda row: row.update(extra=1),
    ],
)
def test_a_creeper_row_that_states_too_little_or_too_much_refuses(change):
    document = _document()
    change(document["pieces"][-1])
    with pytest.raises(ValueError):
        validate_document(document)
