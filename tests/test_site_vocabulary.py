"""A site plan's closed words are read from the world kinds catalogs and are site plan v1's words.

A word is part of the record format: a record names it, and a list of words in a record follows the
order its catalog states. So each list the site grammar reads is held here to the v1 words, written
out once. A catalog that adds, drops or reorders a word fails here; such a change is a later
catalog version and a later plan version, read beside these.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.grammars.site import plan

V1_WORDS = {
    "ENCLOSURES": ("open", "indoor"),
    "FORMS": ("path", "area", "structure", "room", "fixture", "boundary"),
    "PLACEMENTS": ("front", "middle", "back", "left", "right", "edge_back"),
    "PATTERNS": (
        "fill",
        "row",
        "grid",
        "scatter",
        "perimeter",
        "cluster",
        "centre",
        "back_wall",
    ),
    "ACCESS": ("open", "closed"),
    "ROOF_FORMS": ("flat", "gable"),
    "ROLES": (
        "bed",
        "boundary",
        "decoration",
        "field",
        "gathering",
        "ground",
        "home",
        "no_go",
        "obstruction",
        "parking",
        "path",
        "road",
        "seat",
        "shop",
        "water",
        "workplace",
    ),
    "LOOK_FAMILIES": (
        "animal",
        "boundary",
        "character",
        "door",
        "fixture",
        "ground",
        "path",
        "plant",
        "prop",
        "road",
        "roof",
        "structure",
        "vehicle",
        "wall",
        "water",
        "window",
    ),
}


@pytest.mark.parametrize("name", sorted(V1_WORDS))
def test_each_list_of_words_is_site_plan_v1s_in_its_order(name):
    assert getattr(plan, name) == V1_WORDS[name]
