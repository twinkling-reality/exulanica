"""The corridor specification at city version 4, as traffic reads it, made once per test process.

The corridor is the one generated world a development preview draws whose streets traffic drives,
so the traffic host's tests read it: its records, its tile documents, its traffic input and the
network, derivation and fleet the worker would prepare for it.
"""

from __future__ import annotations

import json
import struct
from functools import cache

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.document import TileDocument
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_LOD,
    CORRIDOR_SEED,
    CORRIDOR_TILES,
)
from exulanica.grammar.grammars.city.generation.tiles import (
    city_records,
    generate_city,
    tile_document,
)
from exulanica.grammar.records import record_payload
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.city_derivation import DerivedRoads, derive_road_records
from exulanica.world import traffic_episodes

__all__ = [
    "VERSION",
    "container_of",
    "derived",
    "documents",
    "prepared",
    "records",
    "value",
]

#: The city grammar version whose streets traffic drives: stop lines before crossings, parking.
VERSION = 4


@cache
def records() -> tuple[object, ...]:
    return city_records(
        generate_city(
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            bindings=CORRIDOR_BINDINGS,
            grammar_version=VERSION,
        )
    )


@cache
def documents() -> dict[tuple[int, int], TileDocument]:
    catalogs = load_city_catalogs(grammar_version=VERSION)
    return {
        (tile_x, tile_y): tile_document(
            records(),
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            catalogs=catalogs,
            tile_x=tile_x,
            tile_y=tile_y,
            lod=CORRIDOR_LOD,
            grammar_version=VERSION,
        )
        for tile_x, tile_y in CORRIDOR_TILES
    }


@cache
def derived() -> DerivedRoads:
    return derive_road_records(
        records(),
        load_traffic_catalogs(),
        load_city_catalogs(grammar_version=VERSION),
        city_identity=CORRIDOR_CITY_IDENTITY,
    )


@cache
def value() -> traffic_episodes.TrafficInput:
    return traffic_episodes.traffic_input(
        world_id=CORRIDOR_SEED,
        version_id="the corridor at city version 4",
        city_identity=CORRIDOR_CITY_IDENTITY,
        grammar_version=VERSION,
        records=records(),
    )


def prepared() -> traffic_episodes.Prepared:
    return traffic_episodes.prepared(value())


def container_of(document: TileDocument) -> bytes:
    """A container whose header states what a tessellator's does of a tile's records, in its
    layout: magic, the header's length, the header. There is no geometry after it, which a reader
    of records does not read; ``test_tile_traffic_route.py`` checks a real bake's header reads the
    same records."""
    [grammar] = document.grammars
    rows = []
    for membership, carried in (("owned", grammar.owned), ("halo", grammar.halo)):
        for record in carried:
            payload = record_payload(record)
            rows.append(
                {
                    **payload,
                    "identity": record.identity,  # type: ignore[attr-defined]
                    "membership": membership,
                    "grammar": 0,
                }
            )
    header = canonical_json(
        {
            "profile": "exulanica.owd/v3",
            "grammars": [
                {
                    "grammar_id": grammar.grammar_id,
                    "grammar_version": grammar.grammar_version,
                    "subject_identity": grammar.subject_identity,
                }
            ],
            "records": rows,
        }
    )
    json.loads(header)
    return b"OWD3" + struct.pack("<I", len(header)) + header
