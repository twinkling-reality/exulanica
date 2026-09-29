"""The recipes a person may make a world from, as one versioned catalog.

``assets/catalogs/world-recipes/world-recipe.v<N>.json`` states each kind of world the server can
generate for a person: its words, the composer that builds it (a module of
:mod:`exulanica.world.composers`, named by the key a structural snapshot records, and the version
of it the recipe was reviewed under), the specification it is generated from and how many seed
candidates a world may try. A specification is a file beside the catalog, under
``specifications/``, in the shape ``POST /world-generation/worlds`` accepts, so the grammar's own
cascade checks it and a recipe carries no parameter the grammar does not declare; the catalog
entry pins the file's SHA-256, so an edited specification is a new file and a new entry rather
than a change under an old name.

The person chooses a recipe and nothing else. Everything a world of it holds, from its seed to its
people, is derived by the server (:mod:`exulanica.world.generated_worlds`). A recipe key the
catalog does not state is refused by name. Pure: no connection and no store.
"""

from __future__ import annotations

import functools
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.grammar.catalogs import (
    CatalogSchema,
    ReferenceField,
    integer_field,
    load_catalog,
    text_field,
)
from exulanica.grammar.documents import read_json
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.specified import Specification, specification

__all__ = [
    "CANDIDATES_MAXIMUM",
    "CATALOG_DIRECTORY",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "TILES_MAXIMUM",
    "UnknownWorldRecipe",
    "WorldRecipe",
    "load_world_recipes",
    "read_specification",
    "specification_tiles",
    "world_recipe",
    "world_recipes",
]

CATALOG_ID: Final = "world-recipe"
CATALOG_VERSION: Final = 1
CATALOG_DIRECTORY: Final = (
    Path(__file__).resolve().parents[2].joinpath("assets", "catalogs", "world-recipes")
)
SPECIFICATIONS: Final = "specifications"
#: How a specification file is named, without its ``.json``: a key and a version.
_SPECIFICATION_NAME: Final = re.compile(r"[a-z][a-z0-9-]*\.v[1-9][0-9]*")
#: How a composer is named: the key a snapshot records, which names its module with ``-`` read as
#: ``_``.
_COMPOSER_NAME: Final = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*")
#: The most tiles a recipe may state. A workspace holds at most the world-count policy's limit of
#: generated worlds and no route deletes one, so that limit times this figure bounds every tile
#: bake a workspace can cause (``world-count-policy.v2.json`` says so beside the limit). Four is a
#: town of two tiles by two: one bake of the one-tile town took 13.3 s on the development machine,
#: so four keep one world's bakes near a minute of one worker's time.
TILES_MAXIMUM: Final = 4
#: The most seed candidates one world may try. Generation runs in the request that makes a
#: world, so each recipe states its own count and why its worst case fits a request; this bound
#: only keeps a mistaken entry from turning one request into an unbounded search.
CANDIDATES_MAXIMUM: Final = 16


class UnknownWorldRecipe(CatalogError):
    """A recipe key the catalog does not state."""

    code: Final = "unknown_world_recipe"


@dataclass(frozen=True, slots=True)
class WorldRecipe:
    """One kind of world a person may make, and what the server makes it from."""

    key: str
    label: str
    #: The structural composer that builds a world of this recipe: the key its snapshot records.
    composer_key: str
    composer_version: int
    #: The specification's file name, without ``.json``, and its SHA-256.
    specification_name: str
    specification_sha256: str
    #: The specification, in the shape ``POST /world-generation/worlds`` accepts.
    specification: Any
    #: How many seed candidates a world of this recipe tries, in order, before it is refused.
    candidates: int
    #: The tiles a world of this recipe covers, as its specification's coverage rule counts them.
    tiles: tuple[tuple[int, int], ...]
    #: The catalog version the recipe was read from; a world records it.
    catalog_version: int

    def reference(self) -> dict[str, object]:
        """What a world made from this recipe records of it."""
        return {
            "catalog_id": CATALOG_ID,
            "catalog_version": self.catalog_version,
            "key": self.key,
            "specification": self.specification_name,
            "specification_sha256": self.specification_sha256,
        }


def specification_tiles(document: Any) -> tuple[tuple[int, int], ...]:
    """The tiles a specification covers, counted by its grammar's coverage rule from the values its
    bindings state, before anything is generated; one that leaves a counted value unbound is
    refused by name."""
    if not isinstance(document, dict) or set(document) != {
        "grammar_id",
        "grammar_version",
        "bindings",
    }:
        raise CatalogError("a specification states grammar_id, grammar_version and bindings only")
    spec = read_specification(document)
    values: dict[str, object] = {}
    for binding in spec.bindings:
        values.update(binding.values)
    unbound = [name for name in spec.coverage.reads if name not in values]
    if unbound:
        raise CatalogError(f"a recipe's specification binds {', '.join(unbound)} itself")
    return tuple(spec.coverage.tiles(values))  # type: ignore[arg-type]


def read_specification(document: Any) -> Specification:
    """A specification file read against the registered grammar it names."""
    try:
        return specification(
            document["grammar_id"],
            document["grammar_version"],
            [(binding["level"], binding["values"]) for binding in document["bindings"]],
        )
    except (KeyError, TypeError) as exc:
        raise CatalogError(f"a specification is malformed: {exc}") from exc


def _specifications(directory: Path) -> dict[str, dict[str, str]]:
    """Every specification file beside the catalog, pinned by its bytes' SHA-256."""
    pins: dict[str, dict[str, str]] = {}
    for path in sorted(directory.joinpath(SPECIFICATIONS).glob("*.json")):
        name = path.name.removesuffix(".json")
        if _SPECIFICATION_NAME.fullmatch(name) is None:
            raise CatalogError(f"{path.name} is not named <key>.v<N>.json")
        pins[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    return pins


def _composer(where: str, value: object) -> str:
    name = str(text_field(where, value))
    if _COMPOSER_NAME.fullmatch(name) is None:
        raise CatalogError(
            f"{where} names a composer by its lowercase hyphenated key, not {name!r}"
        )
    return name


def _schema(pins: dict[str, dict[str, str]]) -> CatalogSchema:
    return CatalogSchema(
        CATALOG_ID,
        CATALOG_VERSION,
        (
            ("label", text_field),
            ("composer", _composer),
            ("composer_version", integer_field(1, 1_000)),
            (
                "specification",
                ReferenceField("a world specification", _SPECIFICATION_NAME, pins),
            ),
            ("candidates", integer_field(1, CANDIDATES_MAXIMUM)),
            ("candidates_reason", text_field),
            ("tiles", integer_field(1, TILES_MAXIMUM)),
            ("reason", text_field),
        ),
    )


def load_world_recipes(directory: Path = CATALOG_DIRECTORY) -> tuple[WorldRecipe, ...]:
    """Read the catalog and every specification it names, each held to its pinned digest."""
    present = {path.name for path in directory.glob("*.json")}
    claimed = {f"{CATALOG_ID}.v{CATALOG_VERSION}.json"}
    if present != claimed:
        raise CatalogError(
            f"{directory}: files with no schema {sorted(present - claimed)}, "
            f"schemas with no file {sorted(claimed - present)}"
        )
    pins = _specifications(directory)
    catalog = load_catalog(
        directory.joinpath(f"{CATALOG_ID}.v{CATALOG_VERSION}.json"), _schema(pins)
    )
    recipes = []
    for entry in catalog.entries:
        values = dict(entry.values)
        name = str(values["specification"])
        path = directory.joinpath(SPECIFICATIONS, f"{name}.json")
        document = read_json(path)
        tiles = specification_tiles(document)
        if len(tiles) != values["tiles"]:
            raise CatalogError(
                f"recipe {entry.key} states {values['tiles']} tiles and its specification "
                f"{name} covers {len(tiles)}"
            )
        recipes.append(
            WorldRecipe(
                key=entry.key,
                label=str(values["label"]),
                composer_key=str(values["composer"]),
                composer_version=int(values["composer_version"]),
                specification_name=name,
                specification_sha256=pins[name]["sha256"],
                specification=document,
                candidates=int(values["candidates"]),
                tiles=tiles,
                catalog_version=catalog.catalog_version,
            )
        )
    return tuple(recipes)


@functools.cache
def _by_key() -> MappingProxyType[str, WorldRecipe]:
    return MappingProxyType({recipe.key: recipe for recipe in load_world_recipes()})


def world_recipes() -> tuple[WorldRecipe, ...]:
    """The recipes a running server offers, read once."""
    return tuple(_by_key().values())


def world_recipe(key: str) -> WorldRecipe:
    """The recipe of that key, or a refusal naming it."""
    recipe = _by_key().get(key)
    if recipe is None:
        raise UnknownWorldRecipe(f"no world recipe is named {key!r}")
    return recipe
