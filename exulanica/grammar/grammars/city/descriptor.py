"""Where the city's descriptors are, and what record validators need from the current one.

The descriptor file is the data object that states the grammar version: its frame, stages,
parameters and projection contracts. Record validators need its parameter schema and cascade
before the grammar itself exists (the grammar is built from the stages that hold those
validators), so this module reads that part alone, with
:class:`exulanica.grammar.contract.ParameterSurface`. The grammar built in
:mod:`exulanica.grammar.grammars.city` reads the same file, and a test holds the two readings
equal.

``city.v1.json`` stays beside it, unchanged: it is the source schema of the version 1 to 2
parameter migration.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from exulanica.grammar.contract import ParameterSurface
from exulanica.grammar.documents import read_json

__all__ = [
    "CITY_ADMISSIBLE_USES",
    "CITY_DESCRIPTOR_PATH",
    "CITY_GRAMMAR_ID",
    "CITY_GRAMMAR_VERSION",
    "CITY_MIGRATION_PATHS",
    "CITY_SURFACE",
    "CITY_V1_DESCRIPTOR_PATH",
    "CITY_V1_SURFACE",
]

CITY_GRAMMAR_ID: Final = "city"
CITY_GRAMMAR_VERSION: Final = 2
_HERE: Final = Path(__file__).resolve().parent
CITY_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v2.json")
CITY_V1_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v1.json")
#: Every migration the city ships, by the version it migrates to.
CITY_MIGRATION_PATHS: Final = {2: _HERE.joinpath("city-migration.v2.json")}

CITY_SURFACE: Final = ParameterSurface.read(CITY_DESCRIPTOR_PATH)
CITY_V1_SURFACE: Final = ParameterSurface.read(CITY_V1_DESCRIPTOR_PATH)
CITY_ADMISSIBLE_USES: Final = tuple(read_json(CITY_DESCRIPTOR_PATH)["admissible_uses"])
