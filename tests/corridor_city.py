"""The corridor city, generated once per test process, and the tile documents it is cut into."""

from __future__ import annotations

from functools import cache

from exulanica.grammar.catalogs import Catalog
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

__all__ = ["catalogs", "documents", "records"]


@cache
def catalogs() -> tuple[Catalog, ...]:
    return tuple(load_city_catalogs())


@cache
def records() -> tuple[object, ...]:
    return city_records(
        generate_city(
            seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
        )
    )


@cache
def documents() -> dict[tuple[int, int], TileDocument]:
    return {
        (tile_x, tile_y): tile_document(
            records(),
            seed=CORRIDOR_SEED,
            subject_identity=CORRIDOR_CITY_IDENTITY,
            catalogs=catalogs(),
            tile_x=tile_x,
            tile_y=tile_y,
            lod=CORRIDOR_LOD,
        )
        for tile_x, tile_y in CORRIDOR_TILES
    }
