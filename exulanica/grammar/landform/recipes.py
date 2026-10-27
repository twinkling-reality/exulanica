"""Land recipes: the land a world made from a sentence stands on, as data.

``assets/catalogs/landform/landform-recipe.vN.json`` (``exulanica.landform-recipe``) lists each
recipe with a whole land document (``exulanica.landform/v1``), read by the landform reader as the
catalog is read; the words a made world's card says it is set with, its preposition included
(``title``: "on a coast, ...", "in a valley ..."); the whole words that
name it in a person's sentence (``words``); the setting ground parts that bring it
(``for_ground``, keys of ``assets/style-packs/settings/setting-parts.v5.json``); whether it is
the land a place stands on when nothing names another (``default``, exactly one); a reason and a
licence. Entries are in the order a sentence that names two is read in: the first wins.

A recipe is chosen for a world before it is made, and the world's receipt keeps the land document
itself, so a later version of a recipe never moves a world already made. The catalog changes by a
new version, never by an edit of a shipped one; new worlds read the newest. Version 2's coast pours
a cascade from the site's sea-facing edge into the sea; version 3's coast brings the sea nearer, its
shore 25 m from the place rather than 70 m, so a town or a site by the sea stands by it, and its
cascade ends where the sea now begins. Version 4 adds the lakeside, read after the coast: the
default's land with a filled lake to the south, its near shore 25 m from the place. Versions 1 to 3
stay readable.
"""

from __future__ import annotations

import functools
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from exulanica.grammar.catalogs import Licence
from exulanica.grammar.documents import read_json
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.landform.catalog import CATALOG_DIRECTORY
from exulanica.grammar.landform.document import LandformRefused, read_land_document
from exulanica.grammar.records import KEY_PATTERN

__all__ = [
    "RECIPE_CATALOG_ID",
    "RECIPE_VERSION",
    "RECIPE_VERSIONS",
    "LandRecipe",
    "land_recipes",
    "load_land_recipes",
]

RECIPE_CATALOG_ID: Final = "exulanica.landform-recipe"
#: Every version of the recipe catalog this code reads, and the newest, which new worlds read.
RECIPE_VERSIONS: Final = (1, 2, 3, 4)
RECIPE_VERSION: Final = 4
_ENVELOPE: Final = frozenset({"schema_version", "catalog_id", "catalog_version", "entries"})
_FIELDS: Final = frozenset(
    {"key", "title", "words", "for_ground", "default", "land", "reason", "licence"}
)
_WORD: Final = re.compile(r"[a-z]+")


@dataclass(frozen=True, slots=True)
class LandRecipe:
    key: str
    title: str
    words: tuple[str, ...]
    for_ground: tuple[str, ...]
    default: bool
    #: The canonical land document and its digest.
    land: Mapping[str, Any]
    land_sha256: str


def _text(where: str, value: object) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise CatalogError(f"{where} is non-empty text with no surrounding space")
    return value


def _keys(where: str, value: object, pattern: re.Pattern[str]) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        type(item) is not str or pattern.fullmatch(item) is None for item in value
    ):
        raise CatalogError(f"{where} is a list of lowercase words")
    if len(set(value)) != len(value):
        raise CatalogError(f"{where} repeats a word")
    return tuple(value)


def load_land_recipes(
    version: int = RECIPE_VERSION, path: Path | None = None
) -> tuple[LandRecipe, ...]:
    """Every recipe of ``version`` (from ``path``, else the shipped file), in the order a sentence
    is read against them, or a refusal naming the entry."""
    if version not in RECIPE_VERSIONS:
        raise CatalogError(f"land recipes are versions {RECIPE_VERSIONS}, not {version}")
    if path is None:
        path = CATALOG_DIRECTORY.joinpath(f"landform-recipe.v{version}.json")
    document = read_json(path)
    if not isinstance(document, dict) or set(document) != _ENVELOPE:
        raise CatalogError(f"{path.name}: the envelope is exactly {sorted(_ENVELOPE)}")
    if (document["schema_version"], document["catalog_id"], document["catalog_version"]) != (
        1,
        RECIPE_CATALOG_ID,
        version,
    ):
        raise CatalogError(f"{path.name} is {RECIPE_CATALOG_ID} version {version}, schema 1")
    raw_entries = document["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise CatalogError(f"{path.name}: entries is a list of recipes")
    recipes: list[LandRecipe] = []
    for index, raw in enumerate(raw_entries):
        where = f"{path.name} entries[{index}]"
        if not isinstance(raw, dict) or set(raw) != _FIELDS:
            raise CatalogError(f"{where} has exactly the fields {sorted(_FIELDS)}")
        key = raw["key"]
        if type(key) is not str or KEY_PATTERN.fullmatch(key) is None:
            raise CatalogError(f"{where}.key is a lowercase key, got {key!r}")
        if type(raw["default"]) is not bool:
            raise CatalogError(f"{where}.default is true or false")
        _text(f"{where}.reason", raw["reason"])
        Licence.read(f"{where}.licence", raw["licence"])
        try:
            land = read_land_document(raw["land"])
        except LandformRefused as exc:
            raise CatalogError(f"{where}.land: {exc}") from exc
        recipes.append(
            LandRecipe(
                key=key,
                title=_text(f"{where}.title", raw["title"]),
                words=_keys(f"{where}.words", raw["words"], _WORD),
                for_ground=_keys(f"{where}.for_ground", raw["for_ground"], KEY_PATTERN),
                default=raw["default"],
                land=land.canonical(),
                land_sha256=land.sha256,
            )
        )
    for field in ("key", "words", "for_ground"):
        named = [
            one
            for recipe in recipes
            for one in ((getattr(recipe, field),) if field == "key" else getattr(recipe, field))
        ]
        if len(set(named)) != len(named):
            raise CatalogError(f"{path.name}: two recipes share a {field}")
    if sum(recipe.default for recipe in recipes) != 1:
        raise CatalogError(f"{path.name}: exactly one recipe is the default")
    return tuple(recipes)


@functools.cache
def land_recipes(version: int = RECIPE_VERSION) -> tuple[LandRecipe, ...]:
    """The shipped recipes at ``version`` (the newest unless one is named), read once."""
    return load_land_recipes(version)
