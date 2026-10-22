"""Baked bytes move only with the tessellator's source version.

A bake is stored once under its stage and served as that stage's bake for as long as the stage is
current (migration 0144), so a tessellator change that moves the bytes it bakes but keeps
``TESSELLATOR_SOURCE_VERSION`` leaves every tile stored before it served as it was, never baked
again. That happened: the lot steps' crossing cut changed a hillside tile whose two faces cancelled
at a shared corner, under version 20, and the stored tile stayed refused by the browser.

``tests/fixtures/baked-tile-goldens.json`` holds, for each source version, the triangle digests of
three tiles: tess's conformance tile; tile (1, 0) of a small town on hillside land, whose lot steps
cross a footway's grade; and tile (0, 0) of a level small town, which carries a street its
neighbour owns across the seam. A change that moves any of them under the version it states fails
here, and the fix is to move the version (with the migration that states the new stage) and add
the new version's digests, keeping every older entry.

Each tile is baked from a document held fixed by every version that makes it: the hillside town
names the land rules it is made by (a later land rules version makes a different town), and each
entry states its document's SHA-256, so a document that moved anyway (a grammar, recipe or land
change, not the tessellator) is said as that rather than as bytes the tessellator moved.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Final

import pytest
from exulanica.grammar.grammars.city.document import document_bytes
from exulanica.grammar.landform import land_recipes, land_rules
from exulanica.ingest.stages import STAGES
from exulanica.world.composers import city_grammar_town as town
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.world_recipes import town_recipe

ROOT: Final = Path(__file__).resolve().parents[1]
WEB: Final = ROOT / "web"
PACKAGE: Final = WEB / "packages" / "loom-tess"
EXPAND: Final = PACKAGE / "src" / "core" / "expand.ts"
CLI: Final = PACKAGE / "src" / "node" / "cli.ts"
TSX: Final = WEB / "node_modules" / ".bin" / "tsx"
CONFORMANCE: Final = PACKAGE / "test" / "fixtures" / "tile-conformance.json"
GOLDENS: Final = ROOT / "tests" / "fixtures" / "baked-tile-goldens.json"
#: The small town on hillside land whose tile (1, 0) is held: the world names its seed, chosen
#: because a footway there crosses a lot's grade, so the bytes move when the crossing cut does.
HILLSIDE_WORLD: Final = "world:generated:baked-tile-goldens-hillside-1"
HILLSIDE_TILE: Final = (1, 0)
#: The land rules the hillside town is made by, named so a later land rules version never moves it.
HILLSIDE_LAND_RULES: Final = 6
#: The level small town whose tile (0, 0) is held: a street its neighbour tile owns crosses the
#: seam, so the bytes move when a halo record's ground does.
LEVEL_WORLD: Final = "world:generated:brown-0"
LEVEL_TILE: Final = (0, 0)


def source_version() -> int:
    """``TESSELLATOR_SOURCE_VERSION`` as the tessellator's own source states it."""
    found = re.search(r"TESSELLATOR_SOURCE_VERSION = (\d+);", EXPAND.read_text(encoding="utf-8"))
    assert found is not None, f"TESSELLATOR_SOURCE_VERSION is not stated in {EXPAND}"
    return int(found.group(1))


def _goldens() -> dict[str, Any]:
    return json.loads(GOLDENS.read_text(encoding="utf-8"))


def _document(made: Any, tile: tuple[int, int]) -> bytes:
    for document in town.tile_documents(made.receipt, made.records):
        if (document.tile.tile_x, document.tile.tile_y) == tile:
            return document_bytes(document)
    raise LookupError(f"the town has no tile {tile}")


def _hillside_document() -> bytes:
    [hillside] = [recipe for recipe in land_recipes() if recipe.key == "hillside"]
    recipe = dataclasses.replace(
        town.on_land(town_recipe("small_town"), dict(hillside.land)),
        land_rules=land_rules(HILLSIDE_LAND_RULES),
    )
    return _document(compose_generated_world(recipe, HILLSIDE_WORLD), HILLSIDE_TILE)


def _level_document() -> bytes:
    return _document(compose_generated_world(town_recipe("small_town"), LEVEL_WORLD), LEVEL_TILE)


def _digests(document: Path, out: Path) -> dict[str, str]:
    if not TSX.exists():
        pytest.skip(f"the web toolchain is not installed ({TSX} is missing)")
    if shutil.which("node") is None:
        pytest.skip("node is not on PATH")
    printed = subprocess.run(
        [str(TSX), str(CLI), "bake", str(document), str(out)],
        cwd=WEB,
        capture_output=True,
        text=True,
        check=True,
        timeout=300,
    ).stdout
    return {
        "document_sha256": hashlib.sha256(document.read_bytes()).hexdigest(),
        **json.loads(printed)["triangle_digests"],
    }


def test_the_stage_states_the_tessellators_own_source_version() -> None:
    assert STAGES["baked_tile"].params["tessellator"] == source_version()


def test_every_version_keeps_its_goldens_and_the_current_one_has_them() -> None:
    versions = _goldens()["versions"]
    assert str(source_version()) in versions, (
        f"no goldens for tessellator {source_version()}: add its digests to {GOLDENS.name}"
    )
    assert all(
        set(tiles) == {"conformance", "hillside (1,0)", "level (0,0)"}
        for tiles in versions.values()
    )


def test_baked_bytes_move_only_with_the_source_version(tmp_path: Path) -> None:
    hillside = tmp_path / "hillside-1-0.json"
    hillside.write_bytes(_hillside_document())
    level = tmp_path / "level-0-0.json"
    level.write_bytes(_level_document())
    baked = {
        "conformance": _digests(CONFORMANCE, tmp_path / "conformance.owd"),
        "hillside (1,0)": _digests(hillside, tmp_path / "hillside-1-0.owd"),
        "level (0,0)": _digests(level, tmp_path / "level-0-0.owd"),
    }
    stated = _goldens()["versions"].get(str(source_version()))
    assert stated is not None
    for name, tile in baked.items():
        assert tile["document_sha256"] == stated[name]["document_sha256"], (
            f"the document {name} is baked from moved (a grammar, recipe or land change, not the "
            "tessellator): name the versions that make it, or state its new digest"
        )
    assert baked == stated, (
        f"the bytes tessellator {source_version()} bakes moved: move TESSELLATOR_SOURCE_VERSION, "
        f"state the new stage in a migration, and add the new version's digests: {baked}"
    )
