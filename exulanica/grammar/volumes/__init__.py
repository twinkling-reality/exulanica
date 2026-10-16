"""Volumes: solid masses the land cannot state, as data, realized by one pure integer field.

The land is one height per point, so it cannot say a cliff that overhangs, a sea stack with an
arch through it or a spire. A volume can: a few bounded parts in its own frame, joined, carved,
weathered and capped.

* :mod:`.catalog`: the shapes a part may take and the bound of every value
  (``assets/catalogs/volumes``).
* :mod:`.document`: ``exulanica.volume/v1``, the mass a world states, read against the catalog.
* :mod:`.turns`: sine and cosine in whole millidegrees, and the matrix a part is placed by.
* :mod:`.noise3`: integer value noise in three dimensions, the weathering on its faces.
* :mod:`.field`: the signed distance to its surface at any point, exact near the surface.
* :mod:`.realize`: ``exulanica.volume-chunk/v1``, its surface meshed by chunk at a level of detail.
* :mod:`.sheets`: ``exulanica.volume-sheet/v1``, its walkable tops on the 1 m lattice.
* :mod:`.rules`: the volume rules a world's receipt names, so its volumes rebuild the same.

Nothing here opens a database, a store or evidence, and nothing reads a volume yet: a volume is a
pure function of its document and a seed, as a land is.
"""

from exulanica.grammar.volumes.catalog import (
    CATALOG_VERSION,
    CATALOG_VERSIONS,
    LAND_CATALOGS,
    OPS,
    ShapeKind,
    ValueBound,
    VolumeCatalog,
    load_volume_catalog,
    volume_catalog,
)
from exulanica.grammar.volumes.document import (
    PROFILE,
    TopLand,
    VolumeDocument,
    VolumePart,
    VolumeRefused,
    read_volume_document,
)
from exulanica.grammar.volumes.field import (
    EXACT_MM,
    FAR_MM,
    SHAPES,
    TOP_LAND_CELL_MM,
    TopLandSurface,
    VolumeField,
)
from exulanica.grammar.volumes.noise3 import Noise3
from exulanica.grammar.volumes.realize import (
    CHUNK_MM,
    CHUNK_PROFILE,
    LEVELS,
    VolumeChunk,
    input_sha256,
    read_volume_chunk,
    realize_chunk,
    realize_volume,
    volume_chunks,
)
from exulanica.grammar.volumes.rules import (
    SERVED_VOLUME_RULES,
    VOLUME_RULES_VERSION,
    check_volume_rules,
    volume_rules,
)
from exulanica.grammar.volumes.sheets import (
    SHEET_PROFILE,
    VolumeSheet,
    read_volume_sheet,
    volume_tops,
)
from exulanica.grammar.volumes.turns import TURN_ONE, sin_cos, turn_matrix

__all__ = [
    "CATALOG_VERSION",
    "CATALOG_VERSIONS",
    "CHUNK_MM",
    "CHUNK_PROFILE",
    "EXACT_MM",
    "FAR_MM",
    "LAND_CATALOGS",
    "LEVELS",
    "OPS",
    "PROFILE",
    "SERVED_VOLUME_RULES",
    "SHAPES",
    "SHEET_PROFILE",
    "TOP_LAND_CELL_MM",
    "TURN_ONE",
    "VOLUME_RULES_VERSION",
    "Noise3",
    "ShapeKind",
    "TopLand",
    "TopLandSurface",
    "ValueBound",
    "VolumeCatalog",
    "VolumeChunk",
    "VolumeDocument",
    "VolumeField",
    "VolumePart",
    "VolumeRefused",
    "VolumeSheet",
    "check_volume_rules",
    "input_sha256",
    "load_volume_catalog",
    "read_volume_chunk",
    "read_volume_document",
    "read_volume_sheet",
    "realize_chunk",
    "realize_volume",
    "sin_cos",
    "turn_matrix",
    "volume_catalog",
    "volume_chunks",
    "volume_rules",
    "volume_tops",
]
