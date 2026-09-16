"""Materials as data: maker manifests, recipes, library entries, bake receipts, and the catalog.

A surface's appearance is a maker applied to a recipe. Makers are code, versioned, and live in
``web/packages/loom-texture``; everything else is an object with a profile, named by the sha256 of
its canonical bytes, and this package is where the backend reads those objects and checks them.
It holds no pixels, opens no database, writes no store, and imports no numeric or learning
stack: the import-linter contracts in ``pyproject.toml`` keep it that way, so the checks here run
anywhere and a recipe can be judged before anything expensive happens to it.

What is here: the strict reader and the profiles (:mod:`~exulanica.materials.objects`), the
manifest and recipe checks the TypeScript baker shares case for case
(:mod:`~exulanica.materials.recipes`), and verification of the published catalog
(:mod:`~exulanica.materials.catalog`). Every object here is invented, never observed, and nothing
here can say otherwise.
"""

from exulanica.materials.catalog import (
    LibraryRecord,
    MakerRecord,
    MaterialCatalog,
    ObjectReader,
    verify_material_catalog,
)
from exulanica.materials.objects import (
    BAKE_PIPELINE,
    BAKE_RECEIPT_PROFILE,
    CATALOG_PROFILE,
    LIBRARY_ENTRY_PROFILE,
    MAKER_PROFILE,
    RECIPE_PROFILE,
    STRICT_JSON_PROBLEMS,
    MaterialObjectError,
    canonical_bytes,
    freeze,
    parse_strict,
    read_document,
    read_object,
    sha256_hex,
    thaw,
)
from exulanica.materials.recipes import (
    COMMON_CONTROLS,
    check_recipe,
    evaluate,
    manifest_problems,
    recipe_problems,
)

__all__ = [
    "BAKE_PIPELINE",
    "BAKE_RECEIPT_PROFILE",
    "CATALOG_PROFILE",
    "COMMON_CONTROLS",
    "LIBRARY_ENTRY_PROFILE",
    "MAKER_PROFILE",
    "RECIPE_PROFILE",
    "STRICT_JSON_PROBLEMS",
    "LibraryRecord",
    "MakerRecord",
    "MaterialCatalog",
    "MaterialObjectError",
    "ObjectReader",
    "canonical_bytes",
    "check_recipe",
    "evaluate",
    "freeze",
    "manifest_problems",
    "parse_strict",
    "read_document",
    "read_object",
    "recipe_problems",
    "sha256_hex",
    "thaw",
    "verify_material_catalog",
]
