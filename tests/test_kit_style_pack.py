"""The kit places pack, held to the catalog it is made from and to the product's own rules.

``assets/style-packs/packs/exulanica.kit-places/`` holds pieces converted from open kits by
``scripts/style_packs/kit_pack.py``. A kit's archive is not in this repository, so these tests do
not convert anything: they hold what is committed. The manifest is exactly what the script writes
from the catalog, the built record and the committed pieces; the pack is drawn on the library's
current cozy town; each piece is a palette piece in the pack's own swatches, inside its family's
budget, standing on its base centre at the size its module states; its preview is a picture the
size the authored packs' are; and each piece's record names
the kit model it came from, what was left out of it and the licence file read with it, under a kit
the catalog states with its archive's digest and a licence the pack may carry.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import struct
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from exulanica.world import style_packs
from exulanica.world.style_pack_library import load_style_pack_library
from exulanica.world.style_pack_pieces import check_piece_profile, read_palette_piece

from test_authored_style_packs import _jpeg_size

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "scripts" / "style_packs" / "kit_pack.py"
CATALOG = ROOT / "assets" / "style-packs" / "kits" / "kit-places.v1.json"
BUILT = ROOT / "assets" / "style-packs" / "kits" / "kit-places.built.v1.json"
SHA256 = re.compile(r"[0-9a-f]{64}")


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location("exulanica_kit_pack", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _catalog() -> dict[str, Any]:
    return dict(json.loads(CATALOG.read_text(encoding="utf-8")))


def _built() -> dict[str, Any]:
    return dict(json.loads(BUILT.read_text(encoding="ascii")))


def _folder() -> Path:
    return ROOT / "assets" / "style-packs" / "packs" / _catalog()["pack"]["pack_id"]


def _manifest() -> dict[str, Any]:
    return dict(json.loads((_folder() / "manifest.json").read_text(encoding="ascii")))


def _table() -> list[int]:
    document = json.loads((ROOT / "assets/colour/srgb8-linear16.v1.json").read_text())
    return list(document["values"])


def _position_bounds(glb: bytes) -> tuple[list[float], list[float]]:
    """The least and greatest position a piece states, from its JSON chunk."""
    length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + length])
    (primitive,) = [p for mesh in document["meshes"] for p in mesh["primitives"]]
    accessor = document["accessors"][primitive["attributes"]["POSITION"]]
    return list(accessor["min"]), list(accessor["max"])


def test_the_committed_manifest_is_exactly_what_the_script_writes() -> None:
    builder = _builder()
    written = builder.manifest(ROOT)
    assert list(written) == [str(_folder().relative_to(ROOT) / "manifest.json")]
    for name, data in written.items():
        assert (ROOT / name).read_bytes() == data, name
    assert builder.main(["--check"]) == 0
    # Nothing else is in the folder: the manifest and the pieces it lists.
    listed = {"manifest.json", *(file["path"] for file in _manifest()["files"])}
    found = {str(p.relative_to(_folder())) for p in _folder().rglob("*") if p.is_file()}
    assert found == listed


def test_the_library_serves_it_drawn_on_its_current_cozy_town() -> None:
    library = load_style_pack_library()
    pack_id = _catalog()["pack"]["pack_id"]
    listed = library.pack(pack_id)
    base = library.pack(_catalog()["pack"]["base"])
    assert listed is not None and base is not None
    manifest = _manifest()
    # A pack drawn on a base names it exactly. When the cozy town moves, the script is run again
    # (it needs no kit), and this fails until it is.
    assert manifest["base"] == {
        "pack_id": base.pack_id,
        "version": base.version,
        "manifest_sha256": base.manifest_sha256,
    }
    # It states only what it adds: the look, the ground and the town's own pieces are its base's.
    assert (manifest["light"], manifest["shading"], manifest["edge"]) == (None, None, None)
    assert manifest["surfaces"] == {}
    assert library.default != pack_id


def test_its_preview_is_one_listed_picture_the_size_of_the_authored_packs() -> None:
    manifest = _manifest()
    assert manifest["preview"] == "preview.jpg"
    listed = {file["path"]: file for file in manifest["files"]}
    assert listed["preview.jpg"]["media_type"] == "image/jpeg"
    data = (_folder() / "preview.jpg").read_bytes()
    assert len(data) <= style_packs.PREVIEW_MAX_BYTES
    assert _jpeg_size(data) == (1600, 1000)


def test_it_says_whose_work_it_is_and_under_what_licence() -> None:
    catalog, manifest = _catalog(), _manifest()
    read = style_packs.read_manifest(manifest, style_packs.load_context(ROOT))
    assert read["origin"] == "imported"
    assert read["licence"] == {"id": "CC0-1.0", "attribution": None}
    used = {piece["kit"] for piece in catalog["pieces"]}
    assert used == set(catalog["kits"]), "a kit the catalog states and no piece uses"
    for name, kit in catalog["kits"].items():
        # Only a public-domain dedication is carried without an attribution line.
        assert kit["licence"] == "CC0-1.0", name
        assert SHA256.fullmatch(kit["archive_sha256"]) and kit["archive_bytes"] > 0, name
        assert kit["address"].startswith("https://") and kit["licence_file"], name
        assert kit["author"] in read["authors"], name
        assert kit["author"] in read["provenance"]["source_reference"], name
    assert read["authors"][0] == "Exulanica"


def test_every_piece_is_a_palette_piece_in_the_packs_own_swatches_within_its_budget() -> None:
    manifest, table = _manifest(), _table()
    budgets = style_packs.read_piece_budgets(ROOT)
    own = {tuple(swatch["srgb8"]) for swatch in manifest["palette"]["swatches"]}
    assert all(swatch["key"].startswith("kit_") for swatch in manifest["palette"]["swatches"])
    used: set[tuple[int, int, int]] = set()
    for role, module in manifest["modules"].items():
        # A piece stands in for the slots that name its leaf and no others: no family default.
        assert not role.endswith(".default"), role
        budget = budgets[role.split(".")[0]]
        for variant in module["variants"]:
            data = (_folder() / variant["file"]).read_bytes()
            profile = check_piece_profile(data)
            piece = read_palette_piece(data, table)
            assert piece.colours <= own, variant["file"]
            used |= piece.colours
            assert len(data) <= budget.glb_bytes, variant["file"]
            assert 0 < profile.triangles <= budget.triangle_limit(variant["size_mm"][0])
            assert profile.materials <= budget.materials
            assert variant["stretch_mm"] == [None, None, None] and variant["lod1"] is None
    assert used == own, "a swatch no piece is coloured in"


def test_every_piece_stands_on_its_base_centre_at_the_size_its_module_states() -> None:
    for module in _manifest()["modules"].values():
        for variant in module["variants"]:
            low, high = _position_bounds((_folder() / variant["file"]).read_bytes())
            width, depth, height = variant["size_mm"]
            # glTF metres, +Y up: the base on the ground, centred in plan, to a millimetre.
            assert abs(low[1]) < 0.001, variant["file"]
            assert abs(low[0] + high[0]) < 0.001 and abs(low[2] + high[2]) < 0.001
            for stated, axis in ((width, 0), (height, 1), (depth, 2)):
                assert abs((high[axis] - low[axis]) * 1000 - stated) <= 1, variant["file"]


def test_every_piece_has_a_record_of_the_kit_model_it_came_from() -> None:
    catalog, built, manifest = _catalog(), _built(), _manifest()
    assert built["catalog_sha256"] == hashlib.sha256(CATALOG.read_bytes()).hexdigest()
    assert built["swatches"] == manifest["palette"]["swatches"]
    stated = {piece["file"]: piece for piece in catalog["pieces"]}
    records = {record["file"]: record for record in built["pieces"]}
    listed = {
        file["path"]: file
        for file in manifest["files"]
        if file["media_type"] == "model/gltf-binary"
    }
    assert set(stated) == set(records) == set(listed)
    for file, record in records.items():
        piece = stated[file]
        data = (_folder() / file).read_bytes()
        assert (record["sha256"], record["bytes"]) == (hashlib.sha256(data).hexdigest(), len(data))
        assert (listed[file]["sha256"], listed[file]["bytes"]) == (
            record["sha256"],
            record["bytes"],
        )
        assert record["model"]["path"] == piece["model"] and record["role"] == piece["role"]
        assert SHA256.fullmatch(record["model"]["sha256"]) and record["model"]["bytes"] > 0
        assert SHA256.fullmatch(record["licence_file_sha256"])
        # What was left out of a model is said, with why, or nothing was.
        assert record["left_out"] == piece["leave_out"]
        assert bool(piece["leave_out"]) == ("left_out_reason" in piece)
        assert piece["words"].strip() and piece["reason"].strip()
        # The longest side is the one the catalog names, at the length it names.
        axis = {"width": 0, "depth": 1, "height": 2}[piece["longest_is"]]
        assert record["size_mm"][axis] == piece["longest_mm"] == max(record["size_mm"])
        assert record["triangles"] == record["triangles_read"] - record["triangles_without_area"]
