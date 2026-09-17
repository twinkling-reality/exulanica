"""The city: the first and largest grammar, and one registered implementation among others.

Version 2. Eleven stages, in the order they run: terrain, districts, streets, parcels, massing,
facade, material, streetlife, vitrine, premises, tile. Each has a version and record shapes whose
validators hold every field, and ``city.v2.json`` states all of it as data: the frame, the stages
and the record kinds each validates, 72 declared parameters and the representation contract of
each admitted projection. **No stage has a generator**, so a city generated today is a receipt
and eleven emissions that each say ``not_implemented`` with a reason, and nothing else.

The cascade is city, district, block, lot, building, face. Every parameter states the level it
belongs to and the one stage that reads it; nearly all are derived per subject by that stage, and
``driving_side`` is required, because the side of the road is a convention a world states and
nothing should choose it silently.

Version 1 is retired: its descriptor stays beside this one as the source schema of the version 1
to 2 parameter migration, ``city-migration.v2.json``, and nothing registers it.

Vocabulary comes from the versioned catalogs under ``assets/catalogs``; see
:mod:`exulanica.grammar.grammars.city.catalogs`. The record shapes and the rules every record
shares are in :mod:`exulanica.grammar.grammars.city.common`; a whole tile's records are checked
together by :mod:`exulanica.grammar.grammars.city.document`.
"""

from __future__ import annotations

from typing import Final

from exulanica.grammar.contract import Grammar
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
from exulanica.grammar.grammars.city.descriptor import CITY_DESCRIPTOR_PATH
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

__all__ = ["CITY_GRAMMAR", "CITY_SHAPES", "CITY_SHAPES_BY_TYPE", "CITY_STAGES"]

CITY_STAGES: Final = (
    terrain_generator.STAGE,
    districts_generator.STAGE,
    streets_generator.STAGE,
    parcels_generator.STAGE,
    massing_generator.STAGE,
    facade_generator.STAGE,
    material_generator.STAGE,
    streetlife_generator.STAGE,
    vitrine_generator.STAGE,
    premises_generator.STAGE,
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
    premises.SHAPE,
    tile.SHAPE,
)
CITY_SHAPES_BY_TYPE: Final = {shape.record_type: shape for shape in CITY_SHAPES}

CITY_GRAMMAR: Final = Grammar.from_descriptor(CITY_DESCRIPTOR_PATH, stages=CITY_STAGES)
