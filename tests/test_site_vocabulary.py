"""A site plan's closed words are read from the world kinds catalogs and are site plan v1's words.

A word is part of the record format: a record names it, and a list of words in a record follows the
order its catalog states. So each list the site grammar reads is held here to the v1 words, written
out once. A catalog that adds, drops or reorders a word fails here; such a change is a later
catalog version and a later plan version, read beside these.
"""

from __future__ import annotations

import pytest
from exulanica.grammar.grammars.site import plan
from exulanica.grammar.grammars.site.layout import LOT_ORDER, PATTERN_REALIZERS

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


def test_every_pattern_a_fixture_may_take_has_one_realizer_and_every_realizer_a_word():
    """``fill`` lays out areas; every other pattern word lays out fixtures by its realizer."""
    assert set(PATTERN_REALIZERS) == set(plan.PATTERNS) - {"fill"}


def test_every_placement_on_the_spine_has_its_place_in_the_order_lots_are_cut():
    """``edge_back`` takes the strip across the far edge instead of a lot."""
    assert set(LOT_ORDER) == set(plan.PLACEMENTS) - {"edge_back"}
