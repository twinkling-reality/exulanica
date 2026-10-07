"""The looks this repository authors, as recipe documents, and the containers they write.

Each look here is original geometry authored for this repository and dedicated to the public domain
under CC0 1.0, like the world object catalog's furniture: a blocky figure in two palettes (a
traveller and a knight in plate), and a sword, a lantern, a well and a gate. Their recipes are
data, ``exulanica.look-recipe/v1`` documents under ``assets/catalogs/things/recipes``, one file per
recipe version, and this module is their one reader: no code here names a look. A recipe states
named nodes, each at a point in the slot frame and holding parts (boxes and upright cylinders in
whole millimetres, each in one colour, some glowing), or it builds on another recipe (``base``) and
colours it with its ``palette``. A colour is an sRGB ``#rrggbb`` in lowercase or the name of a
palette role, so the two blocky figures are one figure in two palettes and its joints are stated
once. A recipe is a look's when every colour it reaches resolves; the blocky figure itself names its
colours by role and is only built on.

Their containers are written by :mod:`exulanica.things.pieces` and never committed: the bytes are
reproducible, and the look documents under ``assets/catalogs/things/looks`` pin each one's digest,
held to these recipes by a test that writes them again.

A blocky figure is rigid parts on the humanoid plan's named bones (look kind ``rigid_on_bones``):
the joint nodes stand where a 1,700 mm figure's joints stand in the T-pose, the character facing +y
with its left at -x, and every part is a box on the joint it moves with. An upper arm, a lower arm
and a hand are three boxes, so the elbow bends; a blocky figure from a game with one box per limb
would map its arm onto the upper arm alone and say so in its translation manifest.

Pure: no connection, no store.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.things.origin import OriginRefused, read_origin
from exulanica.things.pieces import Node, Part, write_container

__all__ = [
    "AUTHORED_LOOKS",
    "RECIPE_DIRECTORY",
    "RECIPE_PROFILE",
    "Recipe",
    "RecipeRefused",
    "container_of",
    "load_recipes",
    "nodes_of",
    "read_recipe",
]

RECIPE_PROFILE: Final = "exulanica.look-recipe/v1"
RECIPE_DIRECTORY: Final = Path(__file__).resolve().parents[2] / "assets/catalogs/things/recipes"
_KEY: Final = re.compile(r"[a-z][a-z0-9-]{0,47}")
_COLOUR: Final = re.compile(r"#[0-9a-f]{6}")
_ROLE: Final = re.compile(r"[a-z][a-z0-9_]{0,31}")
_NAME: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9:_.-]{0,63}")
_FILE: Final = re.compile(r"([a-z][a-z0-9-]{0,47})\.v([1-9][0-9]{0,3})\.json")
_TOP: Final = frozenset(
    {"profile", "recipe", "version", "summary", "base", "palette", "nodes", "origin"}
)
_NODE: Final = frozenset({"name", "at_mm", "parts"})
_PART: Final = frozenset({"name", "shape", "size_mm", "centre_mm", "colour"})
_SHAPES: Final = ("box", "cylinder")
#: The most nodes, parts in a node and bases followed: a recipe is a few dozen solids, not a mesh.
_NODES_MAXIMUM: Final = 64
_PARTS_MAXIMUM: Final = 64
_BASES_MAXIMUM: Final = 4


class RecipeRefused(ValueError):
    """A recipe this code will not read or write, by the field at fault."""

    code: Final = "look_recipe_invalid"


def _fail(where: str, message: str) -> RecipeRefused:
    return RecipeRefused(f"{where}: {message}")


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _fail(where, f"states exactly {sorted(keys)}")
    return value


def _whole_triple(where: str, value: object, *, positive: bool) -> tuple[int, int, int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or any(type(v) is not int or (positive and v <= 0) for v in value)
    ):
        kind = "positive whole millimetres" if positive else "whole millimetres"
        raise _fail(where, f"is three {kind}")
    return (value[0], value[1], value[2])


def _colour(where: str, value: object) -> str:
    if type(value) is not str or (
        _COLOUR.fullmatch(value) is None and _ROLE.fullmatch(value) is None
    ):
        raise _fail(where, "is #rrggbb in lowercase or the name of a palette role")
    return value


@dataclass(frozen=True, slots=True)
class Recipe:
    """A read recipe: identity, the document, and its digest."""

    recipe: str
    version: int
    document: Mapping[str, Any]
    sha256: str


def read_recipe(raw: object) -> Recipe:
    """``raw`` as a recipe, every field checked, or :class:`RecipeRefused`."""
    document = _closed("recipe", raw, _TOP)
    if document["profile"] != RECIPE_PROFILE:
        raise _fail("profile", f"is {RECIPE_PROFILE}")
    if type(document["recipe"]) is not str or _KEY.fullmatch(document["recipe"]) is None:
        raise _fail("recipe", "is a lowercase key")
    version = document["version"]
    if type(version) is not int or not 1 <= version <= 9999:
        raise _fail("version", "is a whole number from 1")
    summary = document["summary"]
    if type(summary) is not str or not 1 <= len(summary) <= 200 or summary != summary.strip():
        raise _fail("summary", "is one line of at most 200 characters")
    base, nodes, palette = document["base"], document["nodes"], document["palette"]
    if (base is None) == (nodes is None):
        raise _fail("recipe", "states its own nodes or builds on a base, one of the two")
    if base is not None:
        held = _closed("base", base, frozenset({"recipe", "version"}))
        if type(held["recipe"]) is not str or _KEY.fullmatch(held["recipe"]) is None:
            raise _fail("base.recipe", "is a lowercase key")
        if type(held["version"]) is not int or held["version"] < 1:
            raise _fail("base.version", "is a whole number from 1")
    if palette is not None:
        if not isinstance(palette, Mapping) or not palette:
            raise _fail("palette", "maps palette roles to colours")
        for role, colour in palette.items():
            if type(role) is not str or _ROLE.fullmatch(role) is None:
                raise _fail(f"palette.{role}", "is a palette role's name")
            if type(colour) is not str or _COLOUR.fullmatch(colour) is None:
                raise _fail(f"palette.{role}", "is #rrggbb in lowercase")
    if nodes is not None:
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= _NODES_MAXIMUM:
            raise _fail("nodes", f"is a list of 1 to {_NODES_MAXIMUM} nodes")
        names = set()
        for index, raw_node in enumerate(nodes):
            at = f"nodes[{index}]"
            node = _closed(at, raw_node, _NODE)
            if type(node["name"]) is not str or _NAME.fullmatch(node["name"]) is None:
                raise _fail(f"{at}.name", "is a node's name")
            if node["name"] in names:
                raise _fail(f"{at}.name", "names each node once")
            names.add(node["name"])
            _whole_triple(f"{at}.at_mm", node["at_mm"], positive=False)
            parts = node["parts"]
            if not isinstance(parts, list) or len(parts) > _PARTS_MAXIMUM:
                raise _fail(f"{at}.parts", f"is a list of at most {_PARTS_MAXIMUM} parts")
            for number, raw_part in enumerate(parts):
                where = f"{at}.parts[{number}]"
                keys = _PART | (
                    {"glow"} if isinstance(raw_part, Mapping) and "glow" in raw_part else set()
                )
                part = _closed(where, raw_part, frozenset(keys))
                if type(part["name"]) is not str or _NAME.fullmatch(part["name"]) is None:
                    raise _fail(f"{where}.name", "is a part's name")
                if part["shape"] not in _SHAPES:
                    raise _fail(f"{where}.shape", f"is one of {list(_SHAPES)}")
                _whole_triple(f"{where}.size_mm", part["size_mm"], positive=True)
                _whole_triple(f"{where}.centre_mm", part["centre_mm"], positive=False)
                _colour(f"{where}.colour", part["colour"])
                if "glow" in part:
                    _colour(f"{where}.glow", part["glow"])
    try:
        read_origin(document["origin"], where="origin")
    except OriginRefused as exc:
        raise _fail("origin", str(exc)) from exc
    return Recipe(
        recipe=str(document["recipe"]),
        version=version,
        document=MappingProxyType(dict(document)),
        sha256=sha256_of_canonical(dict(document)).hex(),
    )


def load_recipes(directory: Path = RECIPE_DIRECTORY) -> Mapping[tuple[str, int], Recipe]:
    """Every recipe in ``directory`` by key and version, each file named for what it states."""
    found: dict[tuple[str, int], Recipe] = {}
    for path in sorted(directory.glob("*.json")):
        named = _FILE.fullmatch(path.name)
        if named is None:
            raise _fail(path.name, "is named <recipe>.v<version>.json")
        recipe = read_recipe(json.loads(path.read_text(encoding="utf-8")))
        if (recipe.recipe, recipe.version) != (named[1], int(named[2])):
            raise _fail(path.name, "states the recipe and version its name says")
        found[(recipe.recipe, recipe.version)] = recipe
    return MappingProxyType(found)


@cache
def _recipes() -> Mapping[tuple[str, int], Recipe]:
    return load_recipes(RECIPE_DIRECTORY)


def _nodes_and_palette(
    recipes: Mapping[tuple[str, int], Recipe], key: tuple[str, int]
) -> tuple[list[Mapping[str, Any]], dict[str, str]]:
    """A recipe's nodes, followed through its bases, and its palette, the nearer recipe's role
    colour winning over a base's."""
    palette: dict[str, str] = {}
    for _ in range(_BASES_MAXIMUM + 1):
        recipe = recipes.get(key)
        if recipe is None:
            raise _fail(f"{key[0]} v{key[1]}", "is a recipe this directory holds")
        for role, colour in (recipe.document["palette"] or {}).items():
            palette.setdefault(role, colour)
        if recipe.document["nodes"] is not None:
            return list(recipe.document["nodes"]), palette
        base = recipe.document["base"]
        key = (base["recipe"], base["version"])
    raise _fail(f"{key[0]} v{key[1]}", f"builds on at most {_BASES_MAXIMUM} bases")


def _resolve(colour: str | None, palette: Mapping[str, str], where: str) -> str | None:
    if colour is None or _COLOUR.fullmatch(colour):
        return colour
    if colour not in palette:
        raise _fail(where, f"names the role {colour!r}, which no palette colours")
    return palette[colour]


def nodes_from(
    recipes: Mapping[tuple[str, int], Recipe], recipe: str, version: int
) -> tuple[Node, ...]:
    """The nodes and parts ``recipe`` at ``version`` writes, every colour resolved."""
    nodes, palette = _nodes_and_palette(recipes, (recipe, version))
    return tuple(
        Node(
            node["name"],
            tuple(node["at_mm"]),
            tuple(
                Part(
                    part["name"],
                    part["shape"],
                    tuple(part["size_mm"]),
                    tuple(part["centre_mm"]),
                    _resolve(part["colour"], palette, f"{recipe} {part['name']}"),
                    _resolve(part.get("glow"), palette, f"{recipe} {part['name']}"),
                )
                for part in node["parts"]
            ),
        )
        for node in nodes
    )


def _writable(recipes: Mapping[tuple[str, int], Recipe], key: tuple[str, int]) -> bool:
    try:
        nodes_from(recipes, *key)
    except RecipeRefused:
        return False
    return True


class _AuthoredLooks(Mapping[str, Callable[[], tuple[Node, ...]]]):
    """Every look this repository authors, by look key, with what writes its nodes: each recipe
    whose colours all resolve, at its newest version. Read from the recipes when first asked."""

    def _keys(self) -> dict[str, int]:
        recipes = _recipes()
        newest: dict[str, int] = {}
        for recipe, version in sorted(recipes):
            if _writable(recipes, (recipe, version)):
                newest[recipe] = version
        return newest

    def __getitem__(self, look: str) -> Callable[[], tuple[Node, ...]]:
        version = self._keys()[look]
        return lambda: nodes_from(_recipes(), look, version)

    def __iter__(self) -> Iterator[str]:
        return iter(sorted(self._keys()))

    def __len__(self) -> int:
        return len(self._keys())


#: Every look this repository authors, by look key, with what writes its nodes.
AUTHORED_LOOKS: Final[Mapping[str, Callable[[], tuple[Node, ...]]]] = _AuthoredLooks()


def nodes_of(look: str) -> tuple[Node, ...]:
    return AUTHORED_LOOKS[look]()


@cache
def container_of(look: str) -> bytes:
    """The container an authored look draws: the same bytes on every machine."""
    return write_container(nodes_of(look))
