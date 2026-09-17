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


def _cases(paths: list[Path], what: str) -> list:
    """The paths as parameters, or one named skip when there is no draft of that kind at all.

    Pytest skips a test parametrised over an empty list with no reason given, and that is how these
    checks would leave quietly: the run after a batch publishes its last draft reports two bare
    skips and looks like any other green run. Between batches the skip is right, so it stays, but
    it says why, and the anchor above still holds the directories themselves.
    """
    if not paths:
        reason = f"no {what} are written just now, so there is nothing here to check"
        return [pytest.param(None, marks=pytest.mark.skip(reason=reason), id="none")]
    return [pytest.param(path, id=path.name) for path in paths]


def test_the_drafts_and_their_manifests_are_where_this_test_looks():
    """Between batches there may be no drafts, so the paths themselves are anchored instead.

    A mistyped path would glob nothing and pass every parametrised test by running none of them.
    The published library beside the drafts must be found, and every draft entry must have its
    maker's manifest and every manifest a draft entry.
    """
    assert (PACKAGE / "library" / "cc0.brick-running-bond.json").is_file()
    makers = {path.name for path in MANIFESTS}
    named = set()
    for path in ENTRIES:
        maker = parse_strict(path.read_bytes())["recipe"]["maker"]
        named.add(f"{maker['id']}.v{maker['version']}.json")
    assert named == makers


@pytest.mark.parametrize("path", _cases(MANIFESTS, "draft maker manifests"))
def test_a_draft_maker_manifest_is_well_formed_here_too(path):
    raw = path.read_bytes()
    manifest = parse_strict(raw)
    assert manifest_problems(manifest) == []
    assert canonical_bytes(manifest) == raw
    assert path.name == f"{manifest['maker_id']}.v{manifest['version']}.json"


@pytest.mark.parametrize("path", _cases(ENTRIES, "draft sets"))
def test_a_draft_recipe_is_valid_here_too(path):
    recipe = parse_strict(path.read_bytes())["recipe"]
    maker = recipe["maker"]
    manifest = parse_strict(
        (MANIFEST_DIRECTORY / f"{maker['id']}.v{maker['version']}.json").read_bytes()
    )
    assert recipe_problems(recipe, manifest) == []
