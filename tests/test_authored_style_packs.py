"""The authored style packs, held to the script that writes them and to the product's own rules.

``assets/style-packs/packs/`` holds three packs written by
``scripts/style_packs/authored_packs.py``. These tests build every pack again in memory and require
the committed bytes to be exactly what the script writes, so a piece changed by hand, or a script
changed without its files, fails here. Each manifest is read by the product's reader against the
catalogs in this tree, each piece is held to its family's budget, and each frame that stretches is
held to the smallest opening the grammars cut, read from the grammars themselves. Every earlier
version stays published as it was, and a version bump retires the committed pack by itself.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import struct
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from exulanica.grammar.grammars.city.facade import OPENING_SHAPE
from exulanica.grammar.grammars.site.layout import DOOR_HEIGHT_MM, INNER_WALL_MM
from exulanica.world import style_packs

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "assets" / "style-packs" / "packs"
BUILDER = ROOT / "scripts" / "style_packs" / "authored_packs.py"


def _builder() -> ModuleType:
    # The script builds meshes with numpy, which only the reconstruction extra installs.
    pytest.importorskip(
        "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
    )
    spec = importlib.util.spec_from_file_location("exulanica_authored_packs", BUILDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Its dataclasses find their module by name while the class is made.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _manifests() -> dict[str, dict[str, Any]]:
    return {
        folder.name: json.loads((folder / "manifest.json").read_text(encoding="ascii"))
        for folder in sorted(PACKS.iterdir())
    }


def _triangles(glb: bytes) -> int:
    """Triangles of a binary glTF's one primitive, from its JSON chunk's index accessor."""
    length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + length])
    (primitive,) = [p for mesh in document["meshes"] for p in mesh["primitives"]]
    return int(document["accessors"][primitive["indices"]]["count"]) // 3


def test_the_committed_packs_are_exactly_what_the_script_writes() -> None:
    builder = _builder()
    table, _digest = builder.read_table(ROOT)
    expected: dict[str, bytes] = {}
    for spec in builder.SPECS:
        for name, data in builder.build(spec, table).items():
            expected[f"{spec.pack_id}/{name}"] = data
    committed = {
        str(path.relative_to(PACKS)): path.read_bytes()
        for path in sorted(PACKS.rglob("*"))
        if path.is_file()
    }
    assert sorted(committed) == sorted(expected)
    for path, data in expected.items():
        assert committed[path] == data, path


def test_every_pack_is_read_by_the_products_reader_against_this_trees_catalogs() -> None:
    context = style_packs.load_context(ROOT)
    for folder, manifest in _manifests().items():
        read = style_packs.read_manifest(manifest, context)
        assert read["pack_id"] == folder
        assert read["origin"] == "authored"
        assert read["licence"] == {"id": "CC0-1.0", "attribution": None}
        # Every file a manifest lists is the bytes beside it.
        for file in read["files"]:
            data = (PACKS / folder / file["path"]).read_bytes()
            assert len(data) == file["bytes"]
            assert hashlib.sha256(data).hexdigest() == file["sha256"]


def test_every_piece_is_within_its_familys_budget() -> None:
    budgets = style_packs.read_piece_budgets(ROOT)
    for folder, manifest in _manifests().items():
        for role, module in manifest["modules"].items():
            budget = budgets[role.split(".")[0]]
            for variant in module["variants"]:
                data = (PACKS / folder / variant["file"]).read_bytes()
                assert len(data) <= budget.glb_bytes, (folder, variant["file"])
                limit = budget.triangle_limit(variant["size_mm"][0])
                assert 0 < _triangles(data) <= limit, (folder, variant["file"])


@pytest.mark.parametrize("family", ["window", "door"])
def test_every_stretching_frame_fits_the_smallest_opening_the_grammars_cut(family: str) -> None:
    fields = {shape.name: shape for shape in OPENING_SHAPE.fields}
    kinds = json.loads((ROOT / "assets/catalogs/world-kinds/kind-bound.v1.json").read_text("utf-8"))
    door_width = next(e["minimum"] for e in kinds["entries"] if e["key"] == "door_width_mm")
    smallest = {
        "window": (
            fields["width_mm"].minimum,
            fields["reveal_depth_mm"].minimum,
            fields["height_mm"].minimum,
        ),
        "door": (door_width, INNER_WALL_MM, DOOR_HEIGHT_MM),
    }[family]
    seen = 0
    for manifest in _manifests().values():
        for role, module in manifest["modules"].items():
            if not role.startswith(f"{family}."):
                continue
            for variant in module["variants"]:
                for axis, zone in enumerate(variant["stretch_mm"]):
                    assert zone is not None, (role, variant["file"], axis)
                    fixed = variant["size_mm"][axis] - (zone[1] - zone[0])
                    assert fixed < smallest[axis], (role, variant["file"], axis)
                    seen += 1
    assert seen > 0


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """A baseline or progressive JPEG's width and height, read from its frame header."""
    assert data[:2] == b"\xff\xd8", "not a JPEG"
    at = 2
    while at < len(data):
        assert data[at] == 0xFF
        marker = data[at + 1]
        length = struct.unpack(">H", data[at + 2 : at + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[at + 5 : at + 9])
            return width, height
        at += 2 + length
    raise AssertionError("no frame header")


def test_every_pack_shows_itself_in_one_listed_picture_of_one_size() -> None:
    for folder, manifest in _manifests().items():
        preview = manifest["preview"]
        listed = {file["path"]: file for file in manifest["files"]}
        assert listed[preview]["media_type"] == "image/jpeg", folder
        data = (PACKS / folder / preview).read_bytes()
        assert len(data) <= style_packs.PREVIEW_MAX_BYTES, folder
        assert _jpeg_size(data) == (1600, 1000), folder


def _style_packs_copy(tmp_path: Path) -> Path:
    """A root holding a copy of the committed style pack folder, for the builder to change."""
    shutil.copytree(ROOT / "assets" / "style-packs", tmp_path / "assets" / "style-packs")
    return tmp_path


def _ledger(root: Path) -> list[dict[str, Any]]:
    return json.loads((root / "assets" / "style-packs" / "published.v1.json").read_text())[
        "versions"
    ]


def test_every_earlier_version_is_published_exactly_as_its_ledger_and_manifest_state() -> None:
    builder = _builder()
    assert builder.published_problems(ROOT, sorted(_manifests())) == []


def test_a_version_bump_retires_the_committed_pack_whole_and_appends_the_ledger(
    tmp_path: Path,
) -> None:
    builder = _builder()
    root = _style_packs_copy(tmp_path)
    before = _ledger(root)
    current = _manifests()["exulanica.toon-town"]["version"]
    builder.retire(root, "exulanica.toon-town", current)
    committed = PACKS / "exulanica.toon-town"
    folder = root / "assets" / "style-packs" / "published" / "exulanica.toon-town" / str(current)
    text = (committed / "manifest.json").read_bytes()
    assert (folder / "manifest.json").read_bytes() == text
    for file in json.loads(text)["files"]:
        assert (folder / file["path"]).read_bytes() == (committed / file["path"]).read_bytes()
    entry = {
        "pack_id": "exulanica.toon-town",
        "version": current,
        "manifest_sha256": hashlib.sha256(text[:-1]).hexdigest(),
    }
    after = _ledger(root)
    assert after == sorted([*before, entry], key=lambda e: (e["pack_id"], e["version"]))
    # Retiring it again changes nothing; a published folder holding other bytes is refused.
    builder.retire(root, "exulanica.toon-town", current)
    assert _ledger(root) == after
    (folder / "preview.jpg").write_bytes(b"other")
    with pytest.raises(ValueError, match="is published with other bytes"):
        builder.retire(root, "exulanica.toon-town", current)


@pytest.mark.parametrize("breakage", ["published_file", "ledger_entry"])
def test_check_refuses_an_edited_published_file_or_a_version_the_ledger_misses(
    tmp_path: Path, breakage: str
) -> None:
    builder = _builder()
    root = _style_packs_copy(tmp_path)
    ids = sorted(_manifests())
    # The positive control: the unbroken copy holds every version as published.
    assert builder.published_problems(root, ids) == []
    if breakage == "published_file":
        picture = root / "assets/style-packs/published/exulanica.toon-town/2/preview.jpg"
        picture.write_bytes(picture.read_bytes() + b"x")
        expected = "exulanica.toon-town version 2: preview.jpg is not the bytes its manifest states"
    else:
        ledger = root / "assets" / "style-packs" / "published.v1.json"
        document = json.loads(ledger.read_text())
        document["versions"] = [
            e
            for e in document["versions"]
            if (e["pack_id"], e["version"]) != ("exulanica.cozy-town", 1)
        ]
        ledger.write_text(json.dumps(document))
        expected = "does not list exulanica.cozy-town version 1"
    assert any(expected in problem for problem in builder.published_problems(root, ids))
