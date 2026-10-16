"""Landscapes: everything a world stands on, as data. Its land, and the volumes placed on it.

The land states one height per point; a landscape adds what it cannot: rock that overhangs, sea
stacks and arches (volumes), and in later versions sky islands, spans, landmark flora and far
layers. The land and volume documents inside never change for it.

* :mod:`.catalog`: the bound of every value a landscape and its placements state
  (``assets/catalogs/landscape``).
* :mod:`.document`: ``exulanica.landscape/v1``, read against the catalog and the land's and the
  volumes' own readers.
* :mod:`.compose`: each placed volume realized under its own seed: chunks at each level and tops.
* :mod:`.rules`: the landscape rules a world's receipt names, so its landscape rebuilds the same.
* :mod:`.spacing`: placed volumes stand apart, no two placements' rock meeting where their reaches
  meet.

Nothing here opens a database, a store or evidence, and nothing reads a landscape yet.
"""

from exulanica.grammar.landscape.catalog import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    LandscapeCatalog,
    landscape_catalog,
    load_landscape_catalog,
)
from exulanica.grammar.landscape.compose import (
    PlacedVolume,
    compose_volumes,
    placement_seed,
    volume_bodies,
    volumes_section,
)
from exulanica.grammar.landscape.document import (
    PROFILE,
    LandscapeDocument,
    LandscapeRefused,
    Placement,
    read_landscape_document,
)
from exulanica.grammar.landscape.rules import (
    LANDSCAPE_RULES_VERSION,
    SERVED_LANDSCAPE_RULES,
    check_landscape_rules,
    landscape_rules,
)
from exulanica.grammar.landscape.spacing import check_volumes_apart, placement_reach

__all__ = [
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "LANDSCAPE_RULES_VERSION",
    "PROFILE",
    "SERVED_LANDSCAPE_RULES",
    "LandscapeCatalog",
    "LandscapeDocument",
    "LandscapeRefused",
    "PlacedVolume",
    "Placement",
    "check_landscape_rules",
    "check_volumes_apart",
    "compose_volumes",
    "landscape_catalog",
    "landscape_rules",
    "load_landscape_catalog",
    "placement_reach",
    "placement_seed",
    "read_landscape_document",
    "volume_bodies",
    "volumes_section",
]
