"""Where the city's descriptors are, and what record validators need from the current one.

The descriptor file is the data object that states the grammar version: its frame, stages,
parameters and projection contracts. Record validators need its parameter schema and cascade
before the grammar itself exists (the grammar is built from the stages that hold those
validators), so this module reads that part alone, with
:class:`exulanica.grammar.contract.ParameterSurface`. The grammar built in
:mod:`exulanica.grammar.grammars.city` reads the same file, and a test holds the two readings
equal.

``city.v1.json`` and ``city.v2.json`` stay beside it, unchanged: each is the source schema of one
parameter migration, and a descriptor's bytes are what every document written against it pins by
digest, so a superseded one is never edited.

``city-shapes.v2.json`` is here for the same reason, and is worth its own sentence because it is
the one file in this package with no live producer. A descriptor states parameters; RECORD SHAPES
come from :func:`exulanica.grammar.shapes.describe_shapes` over the current code, and the current
code describes one version. Version 2's shape table is therefore frozen data, kept so the
tessellator can go on reading documents written before version 3 (ADR-0024). It is not an
unchecked copy: ``tests/test_grammar_descriptor.py`` holds it against the live table and admits
exactly one difference, ``city.tile`` gaining ``coordinate_unit`` and a record version.
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
    "CITY_V2_DESCRIPTOR_PATH",
    "CITY_V2_SHAPES_PATH",
    "CITY_V2_SURFACE",
]

CITY_GRAMMAR_ID: Final = "city"
CITY_GRAMMAR_VERSION: Final = 3
_HERE: Final = Path(__file__).resolve().parent
CITY_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v3.json")
CITY_V1_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v1.json")
CITY_V2_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v2.json")
#: Version 2's record shape table, frozen. The module docstring says why it has no producer.
CITY_V2_SHAPES_PATH: Final = _HERE.joinpath("city-shapes.v2.json")
#: Every migration the city ships, by the version it migrates to.
CITY_MIGRATION_PATHS: Final = {
    2: _HERE.joinpath("city-migration.v2.json"),
    3: _HERE.joinpath("city-migration.v3.json"),
}

CITY_SURFACE: Final = ParameterSurface.read(CITY_DESCRIPTOR_PATH)
CITY_V1_SURFACE: Final = ParameterSurface.read(CITY_V1_DESCRIPTOR_PATH)
CITY_V2_SURFACE: Final = ParameterSurface.read(CITY_V2_DESCRIPTOR_PATH)
CITY_ADMISSIBLE_USES: Final = tuple(read_json(CITY_DESCRIPTOR_PATH)["admissible_uses"])
