"""The city grammar this package registers.

Eleven stages, in the order they run: terrain, districts, streets, parcels, massing, facade,
streetlife, vitrine, premises, material, tile; version 5 runs premises before vitrine. Material
runs last but one, so every record whose surfaces it dresses already exists. Each has a version
and record shapes whose validators hold every field. Three versions are registered.
``city.v3.json`` states the frame, the stages and the record kinds each validates, 91 declared
parameters and the representation contract of each admitted projection; ``city.v4.json`` states
the same with the streets stage at its version 3 (stop lines set back before crossings, kerbside
parking lanes) and the two parameters it adds, 93 in all; ``city.v5.json`` reads a district's
street mix and use mix (streets stage version 4, massing, premises and vitrine version 3) and
dresses every ground band and the bare ground (material version 3), with the fifteen parameters
it adds, 108 in all. A caller names the version it generates (:func:`city_grammar`).
Ten stages have generators under :mod:`exulanica.grammar.grammars.city.generation`. The
registered ``tile`` stage remains a record-shape and ownership contract
(:data:`~exulanica.grammar.grammars.city.tile.STAGE` is an
:class:`~exulanica.grammar.contract.UnimplementedStage`); tile documents are assembled after
generation by :mod:`exulanica.grammar.grammars.city.generation.tiles`.

The cascade is city, district, block, lot, building, face. Every parameter states the level it
belongs to and the one stage that reads it; nearly all are derived per subject by that stage, and
``driving_side`` is required, because the side of the road is a convention a world states and
nothing should choose it silently.

``city.v1.json`` and ``city.v2.json`` are the source schemas of the parameter migrations in
:data:`~exulanica.grammar.grammars.city.descriptor.CITY_MIGRATION_PATHS`. Nothing registers them.
A descriptor's bytes are what every document written against it pins by digest, so a superseded
file is never edited.

Vocabulary comes from the versioned catalogs under ``assets/catalogs``; see
:mod:`exulanica.grammar.grammars.city.catalogs`. The record shapes and the rules every record
shares are in :mod:`exulanica.grammar.grammars.city.common`; a whole tile's records are checked
together by :mod:`exulanica.grammar.grammars.city.document`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from exulanica.grammar.contract import Grammar
from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city import (
    districts,
    facade,
    massing,
    material,
    parcels,
    premises,
    roads,
    streetlife,
    streets,
    terrain,
    tile,
    vitrine,
)
from exulanica.grammar.grammars.city.descriptor import (
    CITY_DESCRIPTOR_PATH,
    CITY_GENERATING_VERSIONS,
    CITY_V4_DESCRIPTOR_PATH,
    CITY_V5_DESCRIPTOR_PATH,
)
from exulanica.grammar.grammars.city.generation import districts as districts_generator
from exulanica.grammar.grammars.city.generation import facade as facade_generator
from exulanica.grammar.grammars.city.generation import massing as massing_generator
from exulanica.grammar.grammars.city.generation import material as material_generator
from exulanica.grammar.grammars.city.generation import parcels as parcels_generator
from exulanica.grammar.grammars.city.generation import premises as premises_generator
from exulanica.grammar.grammars.city.generation import streetlife as streetlife_generator
from exulanica.grammar.grammars.city.generation import streets as streets_generator
from exulanica.grammar.grammars.city.generation import terrain as terrain_generator
from exulanica.grammar.grammars.city.generation import vitrine as vitrine_generator
from exulanica.grammar.shapes import RecordShape

__all__ = [
    "CITY_GRAMMAR",
    "CITY_GRAMMARS",
    "CITY_GRAMMAR_V4",
    "CITY_GRAMMAR_V5",
    "CITY_SHAPES",
    "CITY_SHAPES_BY_TYPE",
    "CITY_STAGES",
    "CITY_V4_STAGES",
    "CITY_V5_STAGES",
    "city_grammar",
]

CITY_STAGES: Final = (
    terrain_generator.STAGE,
    districts_generator.STAGE,
    streets_generator.STAGE,
    parcels_generator.STAGE,
    massing_generator.STAGE,
    facade_generator.STAGE,
    streetlife_generator.STAGE,
    vitrine_generator.STAGE,
    premises_generator.STAGE,
    material_generator.STAGE,
    tile.STAGE,
)

#: Every top-level record shape of the city, in stage order.
CITY_SHAPES: Final[tuple[RecordShape, ...]] = (
    terrain.SHAPE,
    districts.SHAPE,
    streets.NODE_SHAPE,
    streets.STREET_SHAPE,
    streets.SEGMENT_SHAPE,
    streets.BLOCK_SHAPE,
    streets.CURB_SHAPE,
    streets.CROSSING_SHAPE,
    *roads.SHAPES,
    parcels.SHAPE,
    massing.MASSING_SHAPE,
    massing.ROOFTOP_SHAPE,
    facade.FACADE_SHAPE,
    facade.BAY_SHAPE,
    facade.ENTRANCE_SHAPE,
    material.SHAPE,
    streetlife.FURNITURE_SHAPE,
    streetlife.TREE_SHAPE,
    vitrine.SHAPE,
    vitrine.BACKING_SHAPE,
    premises.SHAPE,
    tile.SHAPE,
)
CITY_SHAPES_BY_TYPE: Final = {shape.record_type: shape for shape in CITY_SHAPES}

CITY_GRAMMAR: Final = Grammar.from_descriptor(CITY_DESCRIPTOR_PATH, stages=CITY_STAGES)

#: Version 4's stages: version 3's, with the streets stage at its version 3.
CITY_V4_STAGES: Final = tuple(
    streets_generator.STAGE_V3 if stage is streets_generator.STAGE else stage
    for stage in CITY_STAGES
)
CITY_GRAMMAR_V4: Final = Grammar.from_descriptor(CITY_V4_DESCRIPTOR_PATH, stages=CITY_V4_STAGES)
#: Version 5's stages: the street mix (streets at its version 4), the use mix (massing, premises and
#: vitrine at their version 3, premises before vitrine so a shop's use chooses its window) and every
#: surface dressed (material at its version 3).
CITY_V5_STAGES: Final = (
    terrain_generator.STAGE,
    districts_generator.STAGE,
    streets_generator.STAGE_V4,
    parcels_generator.STAGE,
    massing_generator.STAGE_V3,
    facade_generator.STAGE,
    streetlife_generator.STAGE,
    premises_generator.STAGE_V3,
    vitrine_generator.STAGE_V3,
    material_generator.STAGE_V3,
    tile.STAGE,
)
CITY_GRAMMAR_V5: Final = Grammar.from_descriptor(CITY_V5_DESCRIPTOR_PATH, stages=CITY_V5_STAGES)
#: Every city grammar version this package generates, by version.
CITY_GRAMMARS: Final = MappingProxyType({3: CITY_GRAMMAR, 4: CITY_GRAMMAR_V4, 5: CITY_GRAMMAR_V5})
if tuple(CITY_GRAMMARS) != CITY_GENERATING_VERSIONS:
    raise GrammarError(
        f"the city generates versions {tuple(CITY_GRAMMARS)} and states {CITY_GENERATING_VERSIONS}"
    )


def city_grammar(grammar_version: int) -> Grammar:
    """The city grammar at ``grammar_version``; a version this package does not generate is
    refused by name."""
    grammar = CITY_GRAMMARS.get(grammar_version)
    if grammar is None:
        raise GrammarError(
            f"city grammar version {grammar_version} is not one this package generates, "
            f"which are {CITY_GENERATING_VERSIONS}"
        )
    return grammar
