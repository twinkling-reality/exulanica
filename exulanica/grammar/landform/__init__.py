"""Landform: a world's land as data, realized by one pure integer function and graded by layouts.

* :mod:`.catalog`: the feature kinds and the bound of every value (``assets/catalogs/landform``).
* :mod:`.document`: ``exulanica.landform/v1``, the land a world states, read against the catalog.
* :mod:`.noise`: integer value noise on axis grids.
* :mod:`.realize`: ``H(x, y)``; near land in 128 m chunks on the city's tile grid; the backdrop
  drawn to the horizon; water bodies.
* :mod:`.grading`: pads, corridors, banks and walls, ponds, and the checks a graded land meets.
* :mod:`.rules`: the land rules a world's receipt names, so its land rebuilds the same.
* :mod:`.recipes`: the land a world made from a sentence stands on, as data.

Nothing here opens a database, a store or evidence: a land is a pure function of its document
and the world's seed, as every generated subject is.
"""

from exulanica.grammar.landform.catalog import (
    FeatureKind,
    LandformCatalog,
    ValueBound,
    landform_catalog,
    load_landform_catalog,
)
from exulanica.grammar.landform.document import (
    PROFILE,
    LandDocument,
    LandFeature,
    LandformRefused,
    level_land,
    read_land_document,
)
from exulanica.grammar.landform.grading import (
    BANK_GRADE_PERMILLE,
    CUT_FILL_MOST_MM,
    DRY_ABOVE_WATER_MM,
    WALK_GRADE_PERMILLE,
    Basin,
    Corridor,
    GradedLand,
    GradingPlan,
    Pad,
    Wall,
    grade_land,
)
from exulanica.grammar.landform.realize import (
    BACKDROP_PROFILE,
    BACKDROP_REACH_MM,
    CELL_MM,
    CHUNK_MM,
    CHUNK_PROFILE,
    NEAR_BOUND_MM,
    SAMPLES_PER_SIDE,
    Backdrop,
    LandChunk,
    NearLand,
    WaterBody,
    WorldFrame,
    height_at,
    land_heights,
    near_chunks,
    near_domain,
    read_land_chunk,
    realize_backdrop,
    realize_chunk,
    realize_near,
    realize_region,
    water_bodies,
)
from exulanica.grammar.landform.recipes import LandRecipe, land_recipes, load_land_recipes
from exulanica.grammar.landform.rules import LAND_RULES_VERSION, check_land_rules, land_rules

__all__ = [
    "BACKDROP_PROFILE",
    "BACKDROP_REACH_MM",
    "BANK_GRADE_PERMILLE",
    "CELL_MM",
    "CHUNK_MM",
    "CHUNK_PROFILE",
    "CUT_FILL_MOST_MM",
    "DRY_ABOVE_WATER_MM",
    "LAND_RULES_VERSION",
    "NEAR_BOUND_MM",
    "PROFILE",
    "SAMPLES_PER_SIDE",
    "WALK_GRADE_PERMILLE",
    "Backdrop",
    "Basin",
    "Corridor",
    "FeatureKind",
    "GradedLand",
    "GradingPlan",
    "LandChunk",
    "LandDocument",
    "LandFeature",
    "LandRecipe",
    "LandformCatalog",
    "LandformRefused",
    "NearLand",
    "Pad",
    "ValueBound",
    "Wall",
    "WaterBody",
    "WorldFrame",
    "check_land_rules",
    "grade_land",
    "height_at",
    "land_heights",
    "land_recipes",
    "land_rules",
    "landform_catalog",
    "level_land",
    "load_land_recipes",
    "load_landform_catalog",
    "near_chunks",
    "near_domain",
    "read_land_chunk",
    "read_land_document",
    "realize_backdrop",
    "realize_chunk",
    "realize_near",
    "realize_region",
    "water_bodies",
]
