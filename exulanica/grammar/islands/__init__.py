"""Sky islands: islands that float, as data, made into volumes by rule.

An island states the outline of its top, its rim, how deep and in what form its underside hangs,
the rock limbs hanging from it, and its looks and weathering; a maker turns it and a seed into an
unchanged volume, so everything a volume is (its field, chunks and walkable tops) holds of it.

* :mod:`.catalog`: the bound of every value an island states (``assets/catalogs/islands``).
* :mod:`.document`: ``exulanica.sky-island/v1``, read against the catalog.
* :mod:`.maker`: the island and a seed made into an ``exulanica.volume/v1`` document.

Nothing here opens a database, a store or evidence, and nothing reads a sky island yet.
"""

from exulanica.grammar.islands.catalog import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    VOLUME_CATALOGS,
    IslandCatalog,
    island_catalog,
    load_island_catalog,
)
from exulanica.grammar.islands.document import (
    LATER,
    PROFILE,
    IslandDocument,
    IslandRefused,
    read_island_document,
)
from exulanica.grammar.islands.maker import make_island_volume

__all__ = [
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "LATER",
    "PROFILE",
    "VOLUME_CATALOGS",
    "IslandCatalog",
    "IslandDocument",
    "IslandRefused",
    "island_catalog",
    "load_island_catalog",
    "make_island_volume",
    "read_island_document",
]
