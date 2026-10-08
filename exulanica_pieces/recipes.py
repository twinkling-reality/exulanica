"""Piece recipes: what to ask a model for when a kind of thing needs a generated look.

A recipe comes from the kind's own document, so a kind nobody has written anything for (a creature
a model drafted, a kind added next week) generates with no catalog edit:

- the subject is the kind's label, or its appearance words where it has them (a drafted creature's
  body recipe states them);
- the look role is ``prop.<kind>`` for a thing a hand holds and ``fixture.<kind>`` for any other
  object; a being has none, since packs dress look roles and a creature carries its own colours;
- the slot is the kind's box (an object's ``box_mm``; a drafted body's ``extent_mm``, its length
  along the depth), never restated anywhere else;
- the hold is the kind's holdable offer, its grip point and axis, with the widest section a hand
  closes around, which the caller reads from the body plan catalog;
- an object's piece is made by route A, the production route; a being's look by route C, the
  creature route, which reads the recipe's words and box.

The catalog ``assets/catalogs/generation/piece-recipes.v<N>.json`` holds only what was measured to
do better than that for one kind version: plain words for the concept picture, how many variants
to make, and a box fill bar other than :data:`~exulanica_pieces.records.BOX_FILL_MINIMUM_PER_MILLE`,
each entry with the reason that measured it. An entry applies to exactly the kind version it
names. A request built with an entry names it (the catalog's version and the entry's sha256), so a
cached piece leads to the recipe that wrote its words. Every published version stays in the
repository unchanged and readable by its number, so a request naming an older version still finds
its words there; new recipes come from the newest version.

Plain Python: the product reads this module, and a kind document reaches it as the mapping the
product's own reader already checked.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica_pieces.canonical import (
    Refused,
    canonical_bytes,
    exact_keys,
    is_count,
    is_sha256,
    parse_strict,
    sha256_hex,
)

__all__ = [
    "BEING_ROUTE",
    "DEFAULT_VARIANTS",
    "OBJECT_ROUTE",
    "RECIPES_CATALOG_ID",
    "RECIPES_DIRECTORY",
    "PieceRecipes",
    "Recipe",
    "RecipeEntry",
    "load_recipe_versions",
    "load_recipes",
    "read_recipes",
    "recipe_for_kind",
    "recipe_words",
    "recipes_path",
]

#: Relative to the repository root; version N is ``piece-recipes.v<N>.json`` there.
RECIPES_DIRECTORY: Final = "assets/catalogs/generation"
RECIPES_CATALOG_ID: Final = "piece-recipes"
_RECIPES_FILE: Final = re.compile(r"piece-recipes\.v([1-9][0-9]*)\.json")
#: Variants a request asks for when its recipe states none: four, as every demo job made.
DEFAULT_VARIANTS: Final = 4
#: Route A (concept picture, TRELLIS-image-large) is the route the trial chose for pieces.
OBJECT_ROUTE: Final = "A"
#: Route C is the creature route: a plan-guided concept picture, route A's mesh, then a rig.
BEING_ROUTE: Final = "C"
#: A request's description holds at most this many characters (the request's own limit).
_MAX_WORDS: Final = 80
#: A drafted creature's appearance words hold at most this many (the body grammar's bound).
_MAX_BEING_WORDS: Final = 200
_MAX_VARIANTS: Final = 16
_KIND_KEY: Final = re.compile(r"[a-z][a-z0-9_]{0,47}")
_CATALOG_KEYS: Final = ("catalog_id", "catalog_version", "entries", "schema_version")
_ENTRY_KEYS: Final = ("kind", "licence", "reason")
_ENTRY_OPTIONAL: Final = ("box_fill_minimum_permille", "description", "variants")
_LICENCE_KEYS: Final = ("content_source", "licence_source", "origin", "spdx", "verdict")
_REASON_WORDS: Final = 5


@dataclass(frozen=True, slots=True)
class RecipeEntry:
    """One catalog entry: what was measured to do better for one kind version."""

    kind_key: str
    kind_version: int
    description: str | None
    variants: int | None
    box_fill_minimum_permille: int | None
    sha256: str


@dataclass(frozen=True, slots=True)
class PieceRecipes:
    """The read catalog: its version, its digest and its entries by kind key and version."""

    catalog_version: int
    sha256: str
    entries: Mapping[tuple[str, int], RecipeEntry]

    def words_of(self, recipe: Mapping[str, Any]) -> str | None:
        """The words of the entry a request's ``recipe`` names, when this catalog holds it."""
        if recipe.get("catalog_version") != self.catalog_version:
            return None
        for entry in self.entries.values():
            if entry.sha256 == recipe.get("sha256"):
                return entry.description
        return None


@dataclass(frozen=True, slots=True)
class Recipe:
    """What to ask for one kind: the request's fields, before a pack and budgets are chosen."""

    route: str
    look_role: str | None
    slot_mm: Mapping[str, int]
    words: str | None
    variants: int
    hold: Mapping[str, Any] | None
    thing_kind: Mapping[str, Any]
    entry: RecipeEntry | None
    catalog_version: int

    def request_arguments(self) -> dict[str, Any]:
        """Keyword arguments for :func:`exulanica_pieces.records.build_request`, less the pack, the
        budgets and the route a caller may choose; a being's look is not a piece request."""
        if self.look_role is None:
            raise Refused(
                "a being's look is made by the creature route from these words and this box, "
                "not as a piece"
            )
        arguments: dict[str, Any] = {
            "look_role": self.look_role,
            "slot_mm": dict(self.slot_mm),
            "thing_kind": dict(self.thing_kind),
            "variants": self.variants,
        }
        if self.words is not None:
            arguments["description"] = self.words
        if self.hold is not None:
            arguments["hold"] = {**self.hold, "grip": dict(self.hold["grip"])}
        if self.entry is not None:
            arguments["recipe"] = {
                "catalog_version": self.catalog_version,
                "sha256": self.entry.sha256,
            }
            if self.entry.box_fill_minimum_permille is not None:
                arguments["box_fill_minimum_permille"] = self.entry.box_fill_minimum_permille
        return arguments


_PLAIN: Final = re.compile(r"[a-z](?:[a-z ,:;'-]*[a-z])?")


def _plain(value: object, limit: int, where: str) -> str:
    """Plain words: 1 to ``limit`` characters of lower case letters, single spaces and simple
    punctuation, so no markup or instruction reaches a prompt, and no numeral, which a picture
    model paints into the picture."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or _PLAIN.fullmatch(value) is None
        or "  " in value
    ):
        raise Refused(
            f"{where} is 1 to {limit} characters of lower case words, single spaces, commas, "
            "colons, semicolons, apostrophes and hyphens, with no numeral"
        )
    return value


def _line(value: object, limit: int, where: str) -> str:
    """A drafted creature's appearance words, as its body recipe's reader admits them: one trimmed
    line of 1 to ``limit`` characters with no control character and no numeral."""
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= limit
        or value != value.strip()
        or any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 or ord(c) in (0x2028, 0x2029) for c in value)
        or any(c.isdigit() for c in value)
    ):
        raise Refused(f"{where} is one line of 1 to {limit} characters with no numeral")
    return value


def recipes_path(version: int) -> str:
    """Where version ``version`` of the catalog lives, relative to the repository root."""
    if not is_count(version, 1):
        raise Refused("a recipe catalog version is a whole number from 1")
    return f"{RECIPES_DIRECTORY}/{RECIPES_CATALOG_ID}.v{version}.json"


def read_recipes(raw: bytes, where: str = "the piece recipe catalog") -> PieceRecipes:
    """The catalog, strictly: the house envelope, exact keys, each kind version once, every value
    in its bounds, and each entry improving on the derived recipe in at least one way."""
    document = exact_keys(parse_strict(raw, where), _CATALOG_KEYS, where)
    if document["schema_version"] != 1 or document["catalog_id"] != RECIPES_CATALOG_ID:
        raise Refused(f"{where} is schema version 1 of catalog {RECIPES_CATALOG_ID!r}")
    version = document["catalog_version"]
    if not is_count(version, 1):
        raise Refused(f"{where}: catalog_version is a whole number from 1")
    entries = document["entries"]
    if not isinstance(entries, list):
        raise Refused(f"{where}: entries is a list")
    found: dict[tuple[str, int], RecipeEntry] = {}
    for index, value in enumerate(entries):
        at = f"{where}: entries[{index}]"
        if not isinstance(value, dict):
            raise Refused(f"{at} is an object")
        keys = set(value)
        if not set(_ENTRY_KEYS) <= keys or not keys <= set(_ENTRY_KEYS) | set(_ENTRY_OPTIONAL):
            raise Refused(
                f"{at} has {', '.join(_ENTRY_KEYS)} and optionally {', '.join(_ENTRY_OPTIONAL)}"
            )
        if not keys & set(_ENTRY_OPTIONAL):
            raise Refused(f"{at} states nothing the kind's own document does not")
        kind = exact_keys(value["kind"], ("key", "version"), f"{at}.kind")
        if (
            not isinstance(kind["key"], str)
            or _KIND_KEY.fullmatch(kind["key"]) is None
            or not is_count(kind["version"], 1)
        ):
            raise Refused(f"{at}.kind names a thing kind's key and its version from 1")
        reference = (kind["key"], kind["version"])
        if reference in found:
            raise Refused(f"{at}.kind names {reference[0]} version {reference[1]} a second time")
        reason = value["reason"]
        if not isinstance(reason, str) or len(reason.split()) < _REASON_WORDS:
            raise Refused(f"{at}.reason says, in a sentence, what was measured")
        licence = exact_keys(value["licence"], _LICENCE_KEYS, f"{at}.licence")
        if licence["origin"] != "original" or licence["verdict"] != "SHIP":
            raise Refused(f"{at}.licence is original content that ships")
        description = value.get("description")
        if description is not None:
            _plain(description, _MAX_WORDS, f"{at}.description")
        variants = value.get("variants")
        if variants is not None and (not is_count(variants, 1) or variants > _MAX_VARIANTS):
            raise Refused(f"{at}.variants is 1 to {_MAX_VARIANTS}")
        bar = value.get("box_fill_minimum_permille")
        if bar is not None and (not is_count(bar, 1) or bar > 1000):
            raise Refused(f"{at}.box_fill_minimum_permille is 1 to 1,000")
        found[reference] = RecipeEntry(
            kind_key=kind["key"],
            kind_version=kind["version"],
            description=description,
            variants=variants,
            box_fill_minimum_permille=bar,
            sha256=sha256_hex(canonical_bytes(value)),
        )
    return PieceRecipes(
        catalog_version=version,
        sha256=sha256_hex(canonical_bytes(document)),
        entries=MappingProxyType(found),
    )


def load_recipe_versions(repository: Path) -> Mapping[int, PieceRecipes]:
    """Every committed version of the catalog by its number, each held to its file's name."""
    versions: dict[int, PieceRecipes] = {}
    for path in sorted((repository / RECIPES_DIRECTORY).glob(f"{RECIPES_CATALOG_ID}.v*.json")):
        match = _RECIPES_FILE.fullmatch(path.name)
        if match is None:
            raise Refused(f"{path.name} is not named {RECIPES_CATALOG_ID}.v<N>.json")
        where = recipes_path(int(match.group(1)))
        catalog = read_recipes(path.read_bytes(), where)
        if catalog.catalog_version != int(match.group(1)):
            raise Refused(f"{where} holds catalog_version {catalog.catalog_version}")
        versions[catalog.catalog_version] = catalog
    if not versions:
        raise Refused(f"no {RECIPES_CATALOG_ID} catalog under {RECIPES_DIRECTORY}")
    return MappingProxyType(versions)


def load_recipes(repository: Path, version: int | None = None) -> PieceRecipes:
    """One committed version of the catalog: ``version``, or the newest, which new requests use."""
    versions = load_recipe_versions(repository)
    chosen = max(versions) if version is None else version
    if chosen not in versions:
        raise Refused(f"no committed {recipes_path(chosen)}")
    return versions[chosen]


def recipe_words(recipe: Mapping[str, Any], versions: Mapping[int, PieceRecipes]) -> str | None:
    """The words of the entry a request's ``recipe`` names, read in the catalog version it names,
    or None when no committed version holds that entry."""
    version = recipe.get("catalog_version")
    catalog = versions.get(version) if isinstance(version, int) else None
    return None if catalog is None else catalog.words_of(recipe)


def _holdable(document: Mapping[str, Any]) -> Mapping[str, Any] | None:
    for offer in document.get("offers") or ():
        if offer.get("key") == "holdable":
            return offer["parameters"]
    return None


def recipe_for_kind(
    document: Mapping[str, Any],
    sha256: str,
    recipes: PieceRecipes,
    *,
    section_mm_maximum: int | None = None,
    appearance: str | None = None,
) -> Recipe:
    """The recipe for the thing kind ``document`` (as its reader checked it, named by ``sha256``):
    derived from the document, improved by the catalog entry for its key and version when there
    is one.

    ``section_mm_maximum`` is the widest section a hand closes around, from the body plan catalog;
    a holdable kind needs it. ``appearance`` is a drafted kind's appearance words, which its body
    recipe states; a kind without them is asked for by its label."""
    key, version = document["kind"], document["version"]
    if not isinstance(key, str) or _KIND_KEY.fullmatch(key) is None or not is_count(version, 1):
        raise Refused("a thing kind names its key and its version from 1")
    if not is_sha256(sha256):
        raise Refused("a thing kind is named by its sha256")
    body = document["body"]
    holdable = _holdable(document)
    hold = None
    if "box_mm" in body:
        box = body["box_mm"]
        slot = {"width": box["width"], "depth": box["depth"], "height": box["height"]}
        route, role = OBJECT_ROUTE, f"{'prop' if holdable else 'fixture'}.{key}"
        if holdable is not None:
            if section_mm_maximum is None:
                raise Refused(f"{key} is held: the hand's widest section comes from its body plan")
            hold = {
                "axis": holdable["axis"],
                "grip": dict(holdable["grip"]),
                "section_mm_maximum": section_mm_maximum,
            }
    elif "extent_mm" in body:
        extent = body["extent_mm"]
        slot = {"width": extent["width"], "depth": extent["length"], "height": extent["height"]}
        route, role = BEING_ROUTE, None
    else:
        raise Refused(
            f"{key} has no box of its own (it wears the people catalog, a rigged figure or a "
            "light), so there is nothing to generate for it"
        )
    entry = recipes.entries.get((key, version))
    # An object with no words of its own is asked for by its look role's leaf, which is its key;
    # a being, which has no look role, by its label.
    words = appearance if appearance is not None else (None if role else document["label"])
    if entry is not None and entry.description is not None:
        words = entry.description
    elif words is not None and role is None:
        _line(words, _MAX_BEING_WORDS, f"{key}'s words")
    elif words is not None:
        _plain(words, _MAX_WORDS, f"{key}'s words")
    return Recipe(
        route=route,
        look_role=role,
        slot_mm=MappingProxyType(slot),
        words=words,
        variants=(entry.variants if entry and entry.variants else DEFAULT_VARIANTS),
        hold=MappingProxyType(hold) if hold is not None else None,
        thing_kind=MappingProxyType({"key": key, "sha256": sha256, "version": version}),
        entry=entry,
        catalog_version=recipes.catalog_version,
    )
