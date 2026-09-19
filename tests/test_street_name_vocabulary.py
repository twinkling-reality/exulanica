"""The street-name vocabulary: how it is composed, and that it covers what a city can ask for.

Six local street names were a cap on how much city could exist, and NO DECLARED PARAMETER
MENTIONED IT. The cap is gone in the only sense that matters: the vocabulary covers every street
the declared parameter space can lay out, and the check below DERIVES BOTH SIDES, so widening an
extent or narrowing a block fails here by name rather than failing a bake.
"""

from __future__ import annotations

import json
from collections import Counter

from exulanica.grammar.grammars.city.catalogs import CATALOG_DIRECTORY
from exulanica.grammar.grammars.city.descriptor import CITY_SURFACE
from exulanica.grammar.grammars.city.generation import streets as generation_streets
from exulanica.grammar.grammars.city.generation.corridor import (
    CORRIDOR_BINDINGS,
    CORRIDOR_CITY_IDENTITY,
    CORRIDOR_SEED,
)
from exulanica.grammar.grammars.city.generation.tiles import city_records, generate_city
from scripts.generate_street_names import catalog_document, hierarchy_ranks, written_bytes

CATALOG_PATH = CATALOG_DIRECTORY / "street-name.v1.json"
PARTS_PATH = CATALOG_DIRECTORY / "sources" / "street-name-parts.json"


def _parts() -> dict:
    return json.loads(PARTS_PATH.read_text(encoding="utf-8"))


def _catalog() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def _widest_declared_district() -> tuple[int, int, int, int]:
    """The district and blocks that lay the MOST streets: the largest city, the smallest blocks."""
    parameters = {spec.name: spec for spec in CITY_SURFACE.parameters.parameters}
    return (
        parameters["city_extent_x_mm"].maximum,
        parameters["city_extent_y_mm"].maximum,
        parameters["block_length_mm"].minimum,
        parameters["block_depth_mm"].minimum,
    )


def test_the_committed_catalog_is_what_the_generator_writes():
    """The catalog has a producer, so it is not a second source of truth.

    Run ``uv run python scripts/generate_street_names.py`` when this fails.
    """
    document = catalog_document(_parts(), hierarchy_ranks())
    assert written_bytes(document) == CATALOG_PATH.read_bytes()


def test_every_entry_is_its_two_parts_and_the_hierarchies_they_share():
    """The BYTES matching is not enough: this holds the composition rule itself.

    A generator and a file can agree while both say something else than the rule does, so the
    rule is stated here over the committed file rather than over the generator's output.
    """
    parts = _parts()
    elements = {item["word"]: set(item["hierarchies"]) for item in parts["elements"]}
    types = {item["word"]: set(item["hierarchies"]) for item in parts["types"]}
    entries = _catalog()["entries"]
    assert entries, "an empty catalog would satisfy every statement below by having none"
    seen = set()
    for entry in entries:
        element, _, kind = entry["text"].rpartition(" ")
        assert element in elements, entry["key"]
        assert kind in types, entry["key"]
        assert entry["key"] == f"{element.lower()}_{kind.lower()}"
        assert set(entry["hierarchies"]) == elements[element] & types[kind], entry["key"]
        seen.add((element, kind))
    admissible = {
        (element, kind)
        for element, one in elements.items()
        for kind, other in types.items()
        if one & other
    }
    assert seen == admissible, "the catalog is not exactly the admissible compositions"


def test_the_twelve_names_this_catalog_began_as_are_unchanged():
    """The composition was chosen so it is purely additive, and this is what holds it so.

    Every one of the twelve keeps its key, its text and its hierarchies. A composition rule that
    quietly moved `market_street` from high street to local street would be a different vocabulary
    wearing the same name, and two of these keys are named by other tests.

    THIS IS A FACT ABOUT THE CATALOG AND NOT ABOUT ANY WORLD GENERATED FROM IT. "Purely additive"
    reads as the stronger claim and the stronger claim is FALSE: a street's name is
    ``options[draw(..., 0, len(options) - 1)]``, so a longer options list moves the index without
    moving how many streets there are. Measured 2026-09-19 on the corridor's own specification:
    the record count held at 6,566 either side and ALL SEVEN OF ITS STREET NAMES CHANGED,
    linden_terrace and harbour_way and five others becoming hawthorn_street and harbour_road and
    five others. Every street record's digest therefore moves, and because ``tessellate`` sorts by
    (kind, sha256) their order and their triangles move with them. A record COUNT could not have
    seen any of that, and it was quoted as though it had.
    """
    began_as = {
        "bridge_street": ("Bridge Street", ["high_street", "local_street"]),
        "church_walk": ("Church Walk", ["narrow_street"]),
        "foundry_street": ("Foundry Street", ["high_street", "local_street"]),
        "harbour_way": ("Harbour Way", ["avenue", "high_street"]),
        "linden_terrace": ("Linden Terrace", ["local_street"]),
        "maple_row": ("Maple Row", ["local_street", "narrow_street"]),
        "market_street": ("Market Street", ["high_street"]),
        "mill_lane": ("Mill Lane", ["local_street", "narrow_street"]),
        "orchard_place": ("Orchard Place", ["local_street"]),
        "quarry_lane": ("Quarry Lane", ["narrow_street"]),
        "river_avenue": ("River Avenue", ["avenue"]),
        "station_road": ("Station Road", ["avenue", "high_street"]),
    }
    by_key = {entry["key"]: entry for entry in _catalog()["entries"]}
    assert began_as.keys() <= by_key.keys()
    for key, (text, hierarchies) in began_as.items():
        assert (by_key[key]["text"], by_key[key]["hierarchies"]) == (text, hierarchies), key


def test_the_vocabulary_covers_every_street_the_declared_space_can_ask_for():
    """BOTH SIDES ARE DERIVED, which is what makes this a check rather than a remembered cap.

    The demand comes from the descriptor's own parameter maxima through the layout rule and the
    hierarchy rule; the supply comes from the catalog. Widening `city_extent_x_mm`, narrowing
    `block_depth_mm`, or dropping a type from a hierarchy fails HERE, by name, instead of failing
    a bake months later with `the street-name catalog has no more local_street names`.
    """
    span_x, span_y, length, depth = _widest_declared_district()
    demand = generation_streets.street_name_demand(
        span_x, span_y, length, depth, generation_streets.narrowest_reach("local_street")
    )
    assert sum(demand.values()) > 1, "a layout laying no streets would pass this vacuously"
    supply = generation_streets.street_names_by_hierarchy()
    for hierarchy, wanted in sorted(demand.items()):
        assert wanted <= len(supply[hierarchy]), (
            f"a {span_x} by {span_y} mm city with block_length_mm {length} and block_depth_mm "
            f"{depth} lays {wanted} streets needing {hierarchy} names and the catalog holds "
            f"{len(supply[hierarchy])}"
        )


def test_the_corridor_is_no_longer_at_the_edge_of_its_vocabulary():
    """The specification that made this lane: it used all six local names and had none spare."""
    generation = generate_city(
        seed=CORRIDOR_SEED, subject_identity=CORRIDOR_CITY_IDENTITY, bindings=CORRIDOR_BINDINGS
    )
    streets = [r for r in city_records(generation) if r.RECORD_KIND == "city.street"]
    used = Counter(r.name for r in streets)
    assert max(used.values()) == 1, "a street name was used twice"
    supply = generation_streets.street_names_by_hierarchy()
    assert len(streets) < len(supply["local_street"])
