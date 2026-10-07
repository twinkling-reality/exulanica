"""The composers that build a generated world, one module each, named by the key a snapshot records.

A world recipe (:mod:`exulanica.world.world_recipes`) names the composer that builds a world of it
and the version it was reviewed under. The composer is ``exulanica.world.composers.<key>`` with the
key's ``-`` read as ``_``, and nothing else; it holds what the generic path calls, each by the name
:data:`COMPOSER_NAMES` lists:

* ``COMPOSER_KEY`` and ``COMPOSER_VERSIONS``: the key its snapshots record and the versions it
  reads;
* ``compose(recipe, world_id)``: the world a recipe makes for one identity, as a
  :class:`ComposedWorld` (its receipt, its structural candidate and the records it generated), or
  :class:`GeneratedWorldRefused` naming why no seed candidate generated;
* ``records(receipt)``: the records a stored receipt generates again, held to its output digest;
* ``stated_extent(topology, placement)``: the region a world of it holds, the rectangle it covers
  in that region's frame and where a person arrives, read from its snapshot
  (:class:`StatedExtent`);
* ``tile_inputs(receipt)``: each tile it covers with the digest over the inputs its bake is keyed
  by, so a reader finds a baked tile without regenerating anything.

Another kind of generated world is a recipe entry and, only where no composer builds it yet, a
module here. A recipe naming a composer that does not exist, or one that does not define every
name, or one that states another key or no such version, is refused by name.

The seed is the one fact every composer derives alike (:func:`seed_candidate`): drawn from the
recipe and the world's own identity, so each world of a recipe is its own, and numbered, so a
recipe's candidates are tried in a stated order and the one kept is recorded.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.world.structure import SpatialCandidate
from exulanica.world.world_recipes import WorldRecipe

__all__ = [
    "COMPOSER_NAMES",
    "PACKAGE",
    "RECEIPT_PROFILE",
    "SEED_PROFILE",
    "ComposedWorld",
    "GeneratedWorldIdentitiesRefused",
    "GeneratedWorldRefused",
    "StatedExtent",
    "UnknownWorldComposer",
    "composer_module",
    "receipt_sha256",
    "seed_candidate",
]

PACKAGE: Final = "exulanica.world.composers"
#: What a composer module must define, each by the name the generic path calls it by.
COMPOSER_NAMES: Final = (
    "COMPOSER_KEY",
    "COMPOSER_VERSIONS",
    "compose",
    "records",
    "stated_extent",
    "tile_inputs",
)
#: The profile of the canonical document a world's seed is the SHA-256 of.
SEED_PROFILE: Final = "exulanica.generated-world-seed/v1"
#: The profile of a generated world's receipt (migration 0118's world_generation_receipt).
RECEIPT_PROFILE: Final = "exulanica.generated-world/v1"


class UnknownWorldComposer(ValueError):
    """A composer a recipe names that this package does not hold, or holds incompletely."""

    code: Final = "unknown_world_composer"


class GeneratedWorldRefused(Exception):
    """A recipe that generated no world for this identity, with every candidate's refusal."""

    code: Final = "generated_world_refused"

    def __init__(self, recipe_key: str, refusals: Sequence[Mapping[str, object]]) -> None:
        self.recipe_key = recipe_key
        self.refusals = tuple(dict(refusal) for refusal in refusals)
        stated = "; ".join(f"candidate {r['candidate']}: {r['refusal']}" for r in self.refusals)
        super().__init__(
            f"recipe {recipe_key} generated no world from any of its {len(self.refusals)} "
            f"seed candidates ({stated})"
        )


class GeneratedWorldIdentitiesRefused(GeneratedWorldRefused):
    """A recipe that generated no world for any identity one request drew, under the same code,
    with each identity's candidates' refusals (each refusal also names its ``identity``)."""

    def __init__(self, recipe_key: str, drawn: Mapping[str, GeneratedWorldRefused]) -> None:
        super().__init__(
            recipe_key,
            [
                {"identity": world_id, **r}
                for world_id, refused in drawn.items()
                for r in refused.refusals
            ],
        )
        self.identities = tuple(drawn)
        stated = "; ".join(
            f"{world_id}: "
            + ", ".join(f"candidate {r['candidate']}: {r['refusal']}" for r in refused.refusals)
            for world_id, refused in drawn.items()
        )
        Exception.__init__(
            self,
            f"recipe {recipe_key} generated no world for any of the {len(drawn)} identities "
            f"drawn for it ({stated})",
        )


@dataclass(frozen=True, slots=True)
class ComposedWorld:
    """What a composer made for one world: how, the structure it states, and its records."""

    receipt: Mapping[str, Any]
    receipt_sha256: str
    candidate: SpatialCandidate
    records: tuple[object, ...]
    #: For a world made from a world kind and asked for with its society's place, that place, the
    #: one its checks built; None otherwise.
    place: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class StatedExtent:
    """What a generated world's snapshot states of where its people are: its region, the
    rectangle its tiles cover in that region's frame (east and south millimetres, each as its
    least and greatest), and its spawn (east, height and south)."""

    region_id: str
    region_ids: tuple[str, ...]
    east_mm: tuple[int, int]
    south_mm: tuple[int, int]
    arrival_mm: tuple[int, int, int]


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """The SHA-256 of a receipt's canonical JSON, the digest its world's snapshot names."""
    return sha256_of_canonical(dict(receipt)).hex()


def seed_candidate(recipe: WorldRecipe, world_id: str, candidate: int) -> str:
    """The seed of one candidate: SHA-256 over the recipe, the world's identity and the number.

    Over canonical JSON, as :func:`exulanica.grammar.grammars.specified.derived_seed` is, so every
    field is framed. The recipe is named by its catalog version, key and specification digest, so an
    edited specification seeds another world.
    """
    if type(candidate) is not int or not 0 <= candidate < recipe.candidates:
        raise ValueError(f"recipe {recipe.key} tries candidates 0 to {recipe.candidates - 1}")
    return sha256_of_canonical(
        {
            "profile": SEED_PROFILE,
            "recipe": recipe.reference(),
            "world_id": world_id,
            "candidate": candidate,
        }
    ).hex()


def composer_module(key: str, version: int) -> ModuleType:
    """The module that builds worlds of this composer key at this version, or a refusal."""
    name = f"{PACKAGE}.{key.replace('-', '_')}"
    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        raise UnknownWorldComposer(f"no composer module builds {key!r}") from exc
    missing = [attribute for attribute in COMPOSER_NAMES if not hasattr(module, attribute)]
    if missing:
        raise UnknownWorldComposer(f"composer {name} does not define {', '.join(missing)}")
    if key != module.COMPOSER_KEY:
        raise UnknownWorldComposer(f"composer {name} builds {module.COMPOSER_KEY!r}, not {key!r}")
    if version not in module.COMPOSER_VERSIONS:
        raise UnknownWorldComposer(f"composer {key} reads no version {version}")
    return module
