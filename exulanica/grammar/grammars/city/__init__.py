"""The city: the first and largest grammar, and one registered implementation among others.

Ten stages, in the order they run: terrain, streets, parcels, massing, facade, material,
streetlife, vitrine, premises, tile. Each has a version, a record shape and a validator. **None
has a generator yet**, so a city generated today is a receipt and ten emissions that each say
``not_implemented`` with a reason, and nothing else. That is the honest output of a skeleton.

The cascade is city, district, block, lot, building, face. The parameter schema is empty,
because no implemented stage reads a parameter; a parameter is declared by the change that first
reads it. The declared semantics admit the output to no projection yet.

Vocabulary comes from the versioned catalogs under ``assets/catalogs``; see
:mod:`exulanica.grammar.grammars.city.catalogs`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from exulanica.grammar.contract import Grammar
from exulanica.grammar.grammars.city import (
    facade,
    massing,
    material,
    parcels,
    premises,
    streetlife,
    streets,
    terrain,
    tile,
    vitrine,
)

__all__ = ["CITY_GRAMMAR", "CITY_STAGES"]

CITY_STAGES: Final = (
    terrain.STAGE,
    streets.STAGE,
    parcels.STAGE,
    massing.STAGE,
    facade.STAGE,
    material.STAGE,
    streetlife.STAGE,
    vitrine.STAGE,
    premises.STAGE,
    tile.STAGE,
)

CITY_GRAMMAR: Final = Grammar.from_descriptor(
    Path(__file__).with_name("city.v1.json"), stages=CITY_STAGES
)
