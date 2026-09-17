"""The draft makers and their draft sets, held to the backend's checks before anything publishes.

A draft maker (``DRAFT_MAKERS`` in ``web/packages/loom-texture/src/makers/index.ts``) is checked by
the package's suite against ``src/recipe.ts``, but its manifest reaches the backend only when its
first set is published, inside the commit that pins it. A manifest or a recipe the two languages
read differently would surface there, where it is expensive. So the package writes each draft
manifest as canonical JSON under ``test/draft-makers/``, holding those files to its makers byte
for byte, and this runs the backend's checks over them and over every draft entry in
``library-drafts/``, before publication.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from exulanica.materials import canonical_bytes, manifest_problems, parse_strict, recipe_problems

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "web" / "packages" / "loom-texture"
MANIFEST_DIRECTORY = PACKAGE / "test" / "draft-makers"
MANIFESTS = sorted(MANIFEST_DIRECTORY.glob("*.json"))
ENTRIES = sorted((PACKAGE / "library-drafts").glob("*.json"))


def test_there_are_drafts_to_check():
    """An empty glob would pass every parametrised test by running none of them."""
    assert MANIFESTS
    assert ENTRIES


@pytest.mark.parametrize("path", MANIFESTS, ids=lambda path: path.name)
def test_a_draft_maker_manifest_is_well_formed_here_too(path):
    raw = path.read_bytes()
    manifest = parse_strict(raw)
    assert manifest_problems(manifest) == []
    assert canonical_bytes(manifest) == raw
    assert path.name == f"{manifest['maker_id']}.v{manifest['version']}.json"


@pytest.mark.parametrize("path", ENTRIES, ids=lambda path: path.name)
def test_a_draft_recipe_is_valid_here_too(path):
    recipe = parse_strict(path.read_bytes())["recipe"]
    maker = recipe["maker"]
    manifest = parse_strict(
        (MANIFEST_DIRECTORY / f"{maker['id']}.v{maker['version']}.json").read_bytes()
    )
    assert recipe_problems(recipe, manifest) == []
