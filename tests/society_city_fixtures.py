"""The city v2 fixture tile as the society reads it, and one busier variant of the same records.

The tile is the grammar's own hand-written fixture (``tests/fixtures/city-v2``): Market Street
running west to east through a signalised T-junction with Mill Lane, a crossing on each of two
arms, and on the north-west corner a shophouse with a bakery, a bookshop and flats above. Nothing
here generates a record.

The fixture's flats house two people, too few for a simulated day to mean much, so
:func:`busier_document` adds five more flats upstairs behind the same front door and selects the
tile again through the grammar's own rules. Its document is checked like any other.
"""

from __future__ import annotations

import dataclasses
from functools import cache
from typing import Any

from exulanica.grammar.catalogs import Catalog
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.document import TileDocument, select_tile
from exulanica.grammar.grammars.city.premises import PremisesRecord

from city_v2_fixture import builder


@cache
def city_catalogs() -> tuple[Catalog, ...]:
    return load_city_catalogs()


def fixture_document() -> TileDocument:
    return builder().build_document()


def owned_records(document: TileDocument | None = None) -> list[Any]:
    return list((document or fixture_document()).grammars[0].owned)


def of_kind(records: list[Any], kind: type) -> list[Any]:
    return [record for record in records if isinstance(record, kind)]


def busier_document(extra_flats: int = 5) -> TileDocument:
    fixture = builder()
    records = fixture_document().grammars[0].records()
    [flats] = [r for r in of_kind(list(records), PremisesRecord) if r.use_class == "residential"]
    more = [
        dataclasses.replace(
            flats,
            identity=fixture.identity("premises", flats.building_identity, flats.unit_ordinal + n),
            unit_ordinal=flats.unit_ordinal + n,
            bay_identities=(),
            floor_area_mm2=70_000_000,
        )
        for n in range(1, extra_flats + 1)
    ]
    return select_tile(fixture.tile, (*records, *more), subject_identity=fixture.CITY)
