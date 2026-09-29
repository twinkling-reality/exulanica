"""A world specification, resolved and generated: the one path every generated world takes.

A specification names a grammar, its version and the values its cascade levels bind; it is the body
``POST /world-generation/worlds`` accepts and the file a world recipe names
(:mod:`exulanica.world.world_recipes`). This module is what both do with one: read it against the
registered grammar (:func:`specification`), resolve its cascade under a seed and count the
tiles the world covers (:func:`covered_tiles`), and generate it (:func:`generate_specified`). The
route and a recipe differ in who may ask and how the asking is metered, and in how the seed is
derived, never in how a specification becomes a world. Pure: no database, store or evidence.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias

from exulanica.canonical import canonical_json
from exulanica.grammar import Grammar, generate
from exulanica.grammar.contract import Generation
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars import builtin_registry
from exulanica.grammar.grammars.city.generation.terrain import city_tiles
from exulanica.grammar.parameters import CascadeBinding, ParameterValue, ResolvedParameters

__all__ = [
    "GENERATED_LOD",
    "REGISTRY",
    "WORLD_COVERAGE",
    "Specification",
    "WorldCoverage",
    "covered_tiles",
    "derived_identity",
    "derived_seed",
    "generate_specified",
    "specification",
    "specification_payload",
]

#: Every grammar this instance can generate from. Built once: registration is the grammars'
#: business and a request never adds to it.
REGISTRY: Final = builtin_registry()

#: The one level of detail any stage produces. Nothing reduces detail by level (see
#: :mod:`exulanica.api.routes.world_generation`), so this is a statement about what is made rather
#: than a default standing in for a choice.
GENERATED_LOD: Final = 0


#: How many tiles a resolved parameter set covers, for one grammar's own coverage rule.
_Tiles: TypeAlias = Callable[[Mapping[str, ParameterValue]], list[tuple[int, int]]]


class WorldCoverage:
    """How many tiles one grammar's world covers, and which parameters say so.

    ``reads`` is the point of this being data. The route must know a request's tile count BEFORE
    it generates, because that count is what the quota charges, and a parameter whose
    ``when_unset`` is ``derive`` has no single value until a stage derives one per subject. So the
    route refuses a specification that leaves any of ``reads`` unbound, naming each one, rather
    than guessing a count, charging the maximum, or re-deriving what the stage will draw. The last
    of those would be a second implementation of the stage's own rule, free to drift from it.
    """

    __slots__ = ("_tiles", "reads")

    def __init__(self, *reads: str, tiles: _Tiles) -> None:
        self.reads = reads
        self._tiles = tiles

    def tiles(self, values: Mapping[str, ParameterValue]) -> list[tuple[int, int]]:
        return self._tiles(values)


#: A grammar with no entry here is refused rather than generated, because a world whose tiles
#: cannot be counted cannot be metered. ``exulanica.api.quotas`` meters this route. ``box`` has
#: no entry and no tiles: it makes one box to prove the contract is generic, and it is not a
#: world anybody walks.
WORLD_COVERAGE: Final[Mapping[str, WorldCoverage]] = {
    "city": WorldCoverage(
        "city_extent_x_mm",
        "city_extent_y_mm",
        tiles=lambda values: city_tiles(
            int(values["city_extent_x_mm"]), int(values["city_extent_y_mm"])
        ),
    ),
}


def specification_payload(
    grammar_id: str, grammar_version: int, bindings: Sequence[CascadeBinding]
) -> dict[str, object]:
    """The canonical form of a specification: what the seed is taken over.

    Bindings are sorted by level and their values are already sorted by name by
    :meth:`CascadeBinding.of`, so two requests stating the same specification in a different order
    produce the same payload and therefore the same world.

    The level of detail is NOT in here. Two levels of detail of one world are one world, and a
    tile's level is a property of the tile record, so folding it in would make two seeds for one
    thing.
    """
    return {
        "profile": "exulanica.world-specification/v1",
        "grammar_id": grammar_id,
        "grammar_version": grammar_version,
        "bindings": [
            {"level": binding.level, "values": dict(binding.values)}
            for binding in sorted(bindings, key=lambda binding: binding.level)
        ],
    }


def derived_seed(payload: Mapping[str, object]) -> str:
    """The seed a specification makes: SHA-256 over its canonical JSON, as lowercase hex.

    Over canonical JSON rather than a concatenation of the fields, because
    ``exulanica.ingest.stages`` records what an unframed concatenation cost: version 1 of its
    idempotency key joined variable-length fields with no framing, so ``("vision", 11)`` and
    ``("vision1", 1)`` hashed identically and two stages could share one row. Canonical JSON
    frames every field by construction and refuses a float outright.
    """
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def derived_identity(seed: str) -> str:
    """The world identity a specification admits: uuid5 of its seed, under the URL namespace.

    From the SEED rather than from the payload again, and that is the whole reason this is one
    line. The seed is already a SHA-256 over the specification and is a fixed-length hex string,
    so there is no variable-length field to frame and nothing to get wrong. Under the invalid
    documentation domain, as the corridor's own identity is, because no such URL is ever fetched.

    ``require_identity`` says a subject identity is "supplied by whoever admitted it". This route
    is what admits one, and it admits exactly one per specification, which is the same property
    the derived seed carries: ask twice, get the same world.
    """
    return str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"https://exulanica.invalid/world-generation/1/{seed}")
    )


@dataclass(frozen=True, slots=True)
class Specification:
    """A specification read against the registered grammar it names, with its coverage rule."""

    grammar: Grammar
    bindings: tuple[CascadeBinding, ...]
    coverage: WorldCoverage

    def payload(self) -> dict[str, object]:
        """Its canonical form (:func:`specification_payload`)."""
        return specification_payload(
            self.grammar.key.grammar_id, self.grammar.key.grammar_version, self.bindings
        )


def specification(
    grammar_id: str,
    grammar_version: int,
    bindings: Sequence[tuple[str, Mapping[str, ParameterValue]]],
) -> Specification:
    """Read a specification: its grammar from the registry, its bindings by the cascade's own rules.

    An unregistered grammar is refused by the registry, and a grammar with no coverage rule is
    refused by name, because the tiles a world of it covers cannot be counted and so cannot be
    metered. Each binding is checked by :meth:`CascadeBinding.of`, which refuses an unknown level
    or parameter by name.
    """
    grammar = REGISTRY.get(grammar_id, grammar_version)
    coverage = WORLD_COVERAGE.get(grammar.key.grammar_id)
    if coverage is None:
        raise InvalidParameterError(
            f"{grammar.key.grammar_id} declares no world coverage rule, so the tiles a request "
            "for it would materialise cannot be counted and cannot be metered"
        )
    return Specification(
        grammar,
        tuple(CascadeBinding.of(level, values) for level, values in bindings),
        coverage,
    )


def covered_tiles(
    spec: Specification, seed: str
) -> tuple[ResolvedParameters, list[tuple[int, int]]]:
    """Resolve the cascade under ``seed`` and count the tiles the world covers, before generating.

    A parameter the coverage rule reads that no level binds is refused by name: the tiles are
    counted from it before anything is generated, and a parameter a stage derives per subject has
    no single value to count.
    """
    grammar = spec.grammar
    resolved = grammar.cascade.resolve(
        grammar.parameters, spec.bindings, seed=seed, domain_prefix=grammar.key.grammar_id
    )
    values = dict(resolved.values)
    unbound = [name for name in spec.coverage.reads if name not in values]
    if unbound:
        raise InvalidParameterError(
            f"{', '.join(unbound)} must be bound by some level: the tiles this request would "
            "materialise are counted from them before anything is generated, and a parameter a "
            "stage derives per subject has no single value to count"
        )
    return resolved, spec.coverage.tiles(values)


def generate_specified(spec: Specification, *, seed: str, subject_identity: str) -> Generation:
    """Generate the world a specification makes under ``seed``, for ``subject_identity``."""
    return generate(
        spec.grammar, seed=seed, subject_identity=subject_identity, bindings=spec.bindings
    )
