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

**Three versions generate.** ``city.v3.json``, ``city.v4.json`` and ``city.v5.json`` are
registered, and a caller names the one it generates. Version 4 differs from version 3 in its
streets stage alone (stage version 3: a stop line set back before the crossing it approaches, and
kerbside parking lanes where the street hierarchy catalog gives a street them) and in the two
parameters that stage adds. Version 5 reads a district's street mix and use mix: how many high
streets it lays and what its other cross streets are (streets stage version 4), and weights for
the typologies its lots take (massing stage version 3) and the uses its shops take (premises stage
version 3, which runs before the vitrine stage, version 3, so a shop's use chooses its window); its
material stage, version 3, dresses the bare ground and every ground band. Every name here without
a version in it is version 3's, which is what every specification written before version 4 states:
a caller that names no version generates exactly what it did. :data:`CITY_DESCRIPTOR_PATHS` and
:data:`CITY_SURFACES` hold every version by number.

``city-shapes.v2.json``, ``city-shapes.v3.json`` and ``city-shapes.v4.json`` are here for the
same reason, and are worth their own sentence because they are the files in this package with no
live producer. A descriptor states parameters; RECORD SHAPES come from
:func:`exulanica.grammar.shapes.describe_shapes` over the grammar's code. ``city-shapes.v2.json``
is frozen so the tessellator can read documents written against that descriptor (ADR-0024),
``city-shapes.v3.json`` so its version 3 table stays what it was when version 4 arrived, and
``city-shapes.v4.json`` so version 4's stays what it was when version 5 arrived. None is an
unchecked copy: ``tests/test_grammar_descriptor.py`` holds each against the live table and states
each difference, ``city.tile`` gaining ``coordinate_unit`` and a record version at version 3, and
the facade's own ``grammar_version`` bound, which the live code widens to every version it
generates.
"""

from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica.grammar.contract import ParameterSurface
from exulanica.grammar.documents import read_json

__all__ = [
    "CITY_ADMISSIBLE_USES",
    "CITY_DESCRIPTOR_PATH",
    "CITY_DESCRIPTOR_PATHS",
    "CITY_GENERATING_VERSIONS",
    "CITY_GRAMMAR_ID",
    "CITY_GRAMMAR_VERSION",
    "CITY_MIGRATION_PATHS",
    "CITY_SURFACE",
    "CITY_SURFACES",
    "CITY_V1_DESCRIPTOR_PATH",
    "CITY_V1_SURFACE",
    "CITY_V2_DESCRIPTOR_PATH",
    "CITY_V2_SHAPES_PATH",
    "CITY_V2_SURFACE",
    "CITY_V3_SHAPES_PATH",
    "CITY_V4_DESCRIPTOR_PATH",
    "CITY_V4_SHAPES_PATH",
    "CITY_V4_SURFACE",
    "CITY_V5_DESCRIPTOR_PATH",
    "CITY_V5_SURFACE",
]

CITY_GRAMMAR_ID: Final = "city"
#: Version 3, the version a caller that names none generates.
CITY_GRAMMAR_VERSION: Final = 3
_HERE: Final = Path(__file__).resolve().parent
CITY_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v3.json")
CITY_V1_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v1.json")
CITY_V2_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v2.json")
CITY_V4_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v4.json")
CITY_V5_DESCRIPTOR_PATH: Final = _HERE.joinpath("city.v5.json")
#: Version 2's record shape table, frozen. The module docstring says why it has no producer.
CITY_V2_SHAPES_PATH: Final = _HERE.joinpath("city-shapes.v2.json")
#: Version 3's record shape table, frozen when version 4 arrived, for the same reason.
CITY_V3_SHAPES_PATH: Final = _HERE.joinpath("city-shapes.v3.json")
#: Version 4's record shape table, frozen when version 5 arrived, for the same reason.
CITY_V4_SHAPES_PATH: Final = _HERE.joinpath("city-shapes.v4.json")
#: Every migration the city ships, by the version it migrates to.
CITY_MIGRATION_PATHS: Final = {
    2: _HERE.joinpath("city-migration.v2.json"),
    3: _HERE.joinpath("city-migration.v3.json"),
    4: _HERE.joinpath("city-migration.v4.json"),
    5: _HERE.joinpath("city-migration.v5.json"),
}

CITY_SURFACE: Final = ParameterSurface.read(CITY_DESCRIPTOR_PATH)
CITY_V1_SURFACE: Final = ParameterSurface.read(CITY_V1_DESCRIPTOR_PATH)
CITY_V2_SURFACE: Final = ParameterSurface.read(CITY_V2_DESCRIPTOR_PATH)
CITY_V4_SURFACE: Final = ParameterSurface.read(CITY_V4_DESCRIPTOR_PATH)
CITY_V5_SURFACE: Final = ParameterSurface.read(CITY_V5_DESCRIPTOR_PATH)
#: Every city descriptor this package ships, by version.
CITY_DESCRIPTOR_PATHS: Final = MappingProxyType(
    {
        1: CITY_V1_DESCRIPTOR_PATH,
        2: CITY_V2_DESCRIPTOR_PATH,
        3: CITY_DESCRIPTOR_PATH,
        4: CITY_V4_DESCRIPTOR_PATH,
        5: CITY_V5_DESCRIPTOR_PATH,
    }
)
CITY_SURFACES: Final = MappingProxyType(
    {
        1: CITY_V1_SURFACE,
        2: CITY_V2_SURFACE,
        3: CITY_SURFACE,
        4: CITY_V4_SURFACE,
        5: CITY_V5_SURFACE,
    }
)
#: The versions this package generates and reads records at, oldest first.
CITY_GENERATING_VERSIONS: Final = (3, 4, 5)
CITY_ADMISSIBLE_USES: Final = tuple(read_json(CITY_DESCRIPTOR_PATH)["admissible_uses"])
