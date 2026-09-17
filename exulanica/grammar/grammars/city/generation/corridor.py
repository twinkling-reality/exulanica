"""The corridor specification, as integers: the one generated street the visual gate will judge.

**What it asks for.** A city 640 m by 128 m, five tiles in a row, one district, on level ground,
driving on the right. The streets generator lays a high street along its middle, 64 m north of the
south edge, and cross streets 140 m apart placed so the district's middle falls half way between
two of them: at x 110 m, 250 m, 390 m and 530 m. The corridor is the high street's segment between
250 m and 390 m. Its two frontages then run from about 256 m to about 384 m, inside tile ``(2, 0)``,
so the tile that owns the corridor's blocks, lots and buildings is one tile, and the route of about
125 m the gate walks lies on its footway. A block on either side of it gives the view along the
street depth to about 270 m.

**Why each bound value is bound, not derived.**

* ``driving_side``: required; the corridor states right.
* ``city_extent_x_mm``, ``city_extent_y_mm``: five whole tiles by one, so a corridor tile has a
  full block on each side along the street and nothing is generated a walk cannot see.
* ``terrain_relief_mm``: 0, because this terrain stage version generates level ground only.
* ``block_length_mm``: 140 m between cross street centrelines, which leaves a frontage of about
  126 m, the length of the Melbourne route the visual gate compares with.
* ``block_depth_mm``: 56 m between streets along x, so each block holds two rows of lots about
  20 m deep, one facing the high street and one the street behind.
* ``gutter_width_mm``: 300 mm, one value for the district, because a street keeps one carriageway
  width along its length and the streets stage reads this block parameter bound.
* ``front_setback_mm``: 0, because a high street builds to its frontage line, the unbroken street
  edge the rubric asks for, and the parcels stage reads no other value.
* ``memory_precinct_lots``: 1, the one reserved lot the target architecture requires.

Everything else is derived by the stage that reads it, per subject, from the seed.

**The seed and the city.** The seed is the SHA-256 of a sentence naming this specification; the
admitted city identity is a uuid5 under the invalid documentation domain. Neither is evidence of
anything, and a new specification states a new sentence.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Final

from exulanica.grammar.grammars.city.tile import HALO_RADIUS_MM
from exulanica.grammar.parameters import CascadeBinding

__all__ = [
    "CORRIDOR_BINDINGS",
    "CORRIDOR_CITY_IDENTITY",
    "CORRIDOR_LOD",
    "CORRIDOR_SEED",
    "CORRIDOR_TILE",
    "CORRIDOR_TILES",
    "HALO_RADIUS_MM",
]

CORRIDOR_SEED: Final = hashlib.sha256(
    b"exulanica corridor lane 07: the first generated street, specification 1"
).hexdigest()
CORRIDOR_CITY_IDENTITY: Final = str(
    uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/corridor/07/city/1")
)
CORRIDOR_BINDINGS: Final = (
    CascadeBinding.of(
        "city",
        {
            "driving_side": "right",
            "city_extent_x_mm": 640_000,
            "city_extent_y_mm": 128_000,
            "terrain_relief_mm": 0,
            "block_length_mm": 140_000,
            "block_depth_mm": 56_000,
            "gutter_width_mm": 300,
            "front_setback_mm": 0,
            "memory_precinct_lots": 1,
        },
    ),
)
#: The tile that owns the corridor's blocks, lots and buildings.
CORRIDOR_TILE: Final = (2, 0)
#: Every tile the city covers, west to east.
CORRIDOR_TILES: Final = tuple((tile_x, 0) for tile_x in range(5))
CORRIDOR_LOD: Final = 0
