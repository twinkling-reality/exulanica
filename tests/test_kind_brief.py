"""The kind brief: what a model fills in, with no keys, and the compiler that makes a kind of it.

The kinds are the hand-written test fixtures in ``tests/fixtures/world-kinds``, turned into the
brief a model would fill by the converter in ``tests/kind_briefs.py``; each brief is held to the
form, compiled, and the kind it makes is held to both stages of the checks. Random briefs drawn
from the form itself show that what the compiler makes always reads (stage A) whatever the brief
says. No test here sends a request anywhere.
"""

from __future__ import annotations

import copy
import json
import random
import re
from collections.abc import Mapping
from typing import Any

import pytest
from exulanica.grammar.grammars.site import layout
from exulanica.selection.kind_brief import brief_form, brief_where, compile_brief
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.samples import check_samples

from kind_briefs import PROVENANCE, brief_of, fixture_kind, held_to_form


def _passes(document: Mapping[str, Any]) -> dict[str, Any]:
    return check_samples(read_kind(dict(document)))


@pytest.mark.parametrize("name", ["farm", "cafe", "site"])
def test_each_fixture_kind_as_a_brief_compiles_into_a_kind_both_stages_pass(name: str) -> None:
    fixture = fixture_kind(name)
    brief = held_to_form(brief_of(fixture))
    compiled = compile_brief(brief, provenance=PROVENANCE)
    report = _passes(compiled.document)
    assert report["verdict"] == "passed"
    # A kind whose samples lay out as stated is not resized.
    assert compiled.sizing == ()
    stated = brief_of(fixture)
    assert compiled.document["site"]["width_mm"] == stated["site_width_mm"]
    assert compiled.document["site"]["depth_mm"] == stated["site_depth_mm"]
    # Every part and zone the fixture states, as many and of the same forms, with the one
    # boundary a brief states.
    forms = [part["form"] for part in compiled.document["parts"]]
    assert forms.count("boundary") == 1
    assert sorted(form for form in forms if form != "boundary") == sorted(
        part["form"] for part in fixture["parts"] if part["form"] != "boundary"
    )
    assert len(compiled.document["zones"]) == len(fixture["zones"])


def test_the_compiled_farm_says_what_the_fixture_says() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    compiled = compile_brief(brief, size=False, provenance=PROVENANCE).document
    by_label = {part["label"]: part for part in compiled["parts"]}
    uses = {use["key"]: use for use in compiled["use_classes"]}
    barn = by_label["barn"]
    assert barn["roles"] == ["workplace"]
    assert uses[barn["use_class"]]["role_label"] == "dairy hand"
    assert uses[barn["use_class"]]["shifts"] == ["early"]
    # The farmhouse's beds say who lives there, so it names the society's own home.
    assert by_label["farmhouse"]["use_class"] == ""
    assert {room["part"] for room in by_label["farmhouse"]["rooms"]} == {"kitchen", "bedroom"}
    assert by_label["kitchen"]["roles"] == ["home"]
    # The pond rail is a gathering spot: furniture people visit, as many as stand at it.
    rail = by_label["pond rail"]
    assert uses[rail["use_class"]]["kind"] == "furniture"
    assert uses[rail["use_class"]]["visitor_affordances"] == ["visit"]
    assert uses[rail["use_class"]]["visitor_capacity"] == rail["stands"] == 3
    fields = next(zone for zone in compiled["zones"] if zone["label"] == "fields")
    assert fields["boundary"] == compiled["site"]["boundary"] == "fence"


# -- random briefs always read -------------------------------------------------------------------

#: Labels a model might give, among them ones that clash once made keys, are no words at all, or
#: are the keys of the society's own uses.
_LABELS = (
    "shed",
    "Shed",
    "shed!",
    "Café",
    "cafe",
    "1st room",
    "!!",
    "bakery",
    "residential",
    "bench",
    "a long label that keeps going and going past forty characters",
    "",
)


def _draw(node: Mapping[str, Any], defs: Mapping[str, Any], rng: random.Random, name: str) -> Any:
    """A value the form's JSON schema admits, small enough to stay inside the count bounds."""
    if "$ref" in node:
        return _draw(defs[node["$ref"].rsplit("/", 1)[-1]], defs, rng, name)
    if "anyOf" in node:
        return _draw(rng.choice(node["anyOf"]), defs, rng, name)
    if "enum" in node:
        return rng.choice(node["enum"])
    if "const" in node:
        return node["const"]
    kind = node.get("type")
    if kind == "object":
        return {key: _draw(value, defs, rng, key) for key, value in node["properties"].items()}
    if kind == "array":
        least = node.get("minItems", 0)
        most = {"zones": 2, "fixtures": 2}.get(name, 1)
        return [_draw(node["items"], defs, rng, name) for _ in range(rng.randint(least, most))]
    if kind == "integer":
        low, high = node.get("minimum", 0), node.get("maximum", 1000)
        if name in ("from", "to") and high <= 64:
            high = min(high, 4)  # counts and storeys: few, so the things placed stay in bounds
        if name in ("site_width_mm", "site_depth_mm"):
            high = min(high, 48000)  # an indoor site's grid points stay in bounds
        return rng.randint(low, high)
    if kind == "boolean":
        return rng.random() < 0.5
    pattern = node.get("pattern", "")
    families = re.match(r"^\^\(([^)]*)\)", pattern)
    if families is not None:
        return f"{rng.choice(families.group(1).split('|'))}.{rng.choice(('stone', 'a1', 'x_y'))}"
    if pattern:
        return f"kind_{rng.randint(0, 999)}"
    low, high = node.get("minLength", 0), node.get("maxLength", 60)
    text = rng.choice(_LABELS)[:high]
    return text if len(text) >= low else "x" * low


def test_whatever_a_brief_says_its_kind_reads() -> None:
    schema = brief_form().model_json_schema()
    rng = random.Random(20261007)
    read = 0
    for _ in range(300):
        brief = held_to_form(_draw(schema, schema.get("$defs", {}), rng, ""))
        document = compile_brief(brief, size=False, provenance=PROVENANCE).document
        if not any(z["structures"] or z["areas"] or z["fixtures"] for z in brief["zones"]):
            # A place that holds nothing at all is no kind, and is refused by name.
            with pytest.raises(KindRefused, match=r"zones\[0\]\.holds: holds 0"):
                read_kind(document)
            continue
        try:
            read_kind(document)
        except KindRefused as refused:
            pytest.fail(f"{refused}\n{json.dumps(brief)[:2000]}")
        read += 1
    assert read > 250


# -- sizing ---------------------------------------------------------------------------------------


def test_a_site_too_small_for_what_it_holds_is_grown_until_its_samples_lay_out() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    brief["site_width_mm"] = brief["site_depth_mm"] = 8000
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert compiled.sizing, "nothing was grown"
    site = compiled.document["site"]
    assert site["width_mm"] > 8000 and site["depth_mm"] > 8000
    assert _passes(compiled.document)["verdict"] == "passed"


def test_the_site_is_as_deep_as_the_layouts_own_need_function_says(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The depth comes from layout._need itself: a different need is a different depth."""
    brief = held_to_form(brief_of(fixture_kind("site")))
    monkeypatch.setattr(layout, "_need", lambda plan, zone: 100_000)
    compiled = compile_brief(brief, size=False, provenance=PROVENANCE)
    assert compiled.document["site"]["depth_mm"] == brief["site_depth_mm"]
    from exulanica.selection import kind_brief

    said = kind_brief._deep_enough(compiled.document, kind_brief.load_kind_catalogs())
    # Three zones beside the spine (the fourth lies across the far edge), each said to need
    # 100 m: one side holds at least half of the 300 m, with a ring of the hoarding's thickness
    # at each end in whole modules.
    assert said == "site depth_mm 64000 to 151000"


def test_a_site_whose_walking_graph_is_over_budget_is_shrunk_until_it_is_not() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    brief["site_width_mm"] = brief["site_depth_mm"] = 256000
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert any("to" in step and "256000 to" in step for step in compiled.sizing)
    site = compiled.document["site"]
    assert site["width_mm"] < 256000 and site["depth_mm"] < 256000
    assert _passes(compiled.document)["verdict"] == "passed"


def test_a_structure_too_small_for_its_rooms_fixtures_is_grown() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    farmyard = next(zone for zone in brief["zones"] if zone["label"] == "farmyard")
    farmhouse = next(s for s in farmyard["structures"] if s["label"] == "farmhouse")
    kitchen = next(room for room in farmhouse["rooms"] if room["label"] == "kitchen")
    kitchen["fixtures"][0]["count"] = {"from": 12, "to": 12}  # twelve tables in one kitchen
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert any(step.startswith("structure farmhouse") for step in compiled.sizing)
    assert _passes(compiled.document)["verdict"] == "passed"


def _farmhouse_of_tables(brief: dict[str, Any], tables: int) -> dict[str, Any]:
    """The farm's farmhouse stated at the least a structure may be, its kitchen holding a row of
    ``tables`` tables: what a drafted bunk house with its beds in a row asks of sizing."""
    farmyard = next(zone for zone in brief["zones"] if zone["label"] == "farmyard")
    farmhouse = next(s for s in farmyard["structures"] if s["label"] == "farmhouse")
    farmhouse["width_mm"] = farmhouse["depth_mm"] = {"from": 2000, "to": 2000}
    kitchen = next(room for room in farmhouse["rooms"] if room["label"] == "kitchen")
    kitchen["fixtures"][0]["count"] = {"from": tables, "to": tables}
    kitchen["fixtures"][0]["pattern"] = "row"
    return brief


def test_a_structure_grown_a_long_way_on_a_small_site_is_sized_until_its_samples_pass() -> None:
    """Each quarter a structure grows asks the site to be answered again; the drafted bunk houses
    of the v3.2 measurement needed 18 and 26 rounds and were refused after 16."""
    brief = _farmhouse_of_tables(held_to_form(brief_of(fixture_kind("farm"))), 4)
    brief["site_width_mm"] = brief["site_depth_mm"] = 8000
    compiled = compile_brief(brief, provenance=PROVENANCE)
    grown = [step for step in compiled.sizing if step.startswith(("site", "structure farmhouse w"))]
    assert len(grown) > 16
    assert _passes(compiled.document)["verdict"] == "passed"


def test_a_structure_grown_for_its_rooms_is_trimmed_to_the_smallest_that_passes() -> None:
    """Growth goes a quarter each way; a row of six tables lacks room one way only, so the
    farmhouse comes back to a whole module more than the samples refuse, each way."""
    brief = _farmhouse_of_tables(held_to_form(brief_of(fixture_kind("farm"))), 6)
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert any(step.startswith("structure farmhouse depth_mm ") for step in compiled.sizing)
    document = compiled.document
    farmhouse = _farm_part(document, "farmhouse")
    assert farmhouse["depth_mm"] < farmhouse["width_mm"]
    assert _passes(document)["verdict"] == "passed"
    for name in ("width_mm", "depth_mm"):
        smaller = copy.deepcopy(document)
        _farm_part(smaller, "farmhouse")[name] -= 500  # the open-air module
        with pytest.raises(KindRefused):
            _passes(smaller)


def _zone(document: Mapping[str, Any], label: str) -> dict[str, Any]:
    return next(zone for zone in document["zones"] if zone["label"] == label)


def test_a_zone_the_brief_states_closed_stays_closed_and_what_it_holds_is_only_seen() -> None:
    """The words said nobody goes there: the pond corner stays closed, and its rail, stated as a
    gathering spot, is kept to be seen rather than opening the corner to reach it."""
    brief = held_to_form(brief_of(fixture_kind("farm")))
    next(zone for zone in brief["zones"] if zone["label"] == "pond corner")["access"] = "closed"
    compiled = compile_brief(brief, provenance=PROVENANCE)
    document = compiled.document
    assert _zone(document, "pond corner")["access"] == "closed"
    rail = _farm_part(document, "pond rail")
    assert (rail["roles"], rail["use_class"], rail["stands"]) == (["decoration"], "", 0)
    assert _passes(document)["verdict"] == "passed"


def test_a_field_in_a_zone_the_brief_states_closed_is_kept_without_its_work() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    next(zone for zone in brief["zones"] if zone["label"] == "fields")["access"] = "closed"
    document = compile_brief(brief, provenance=PROVENANCE).document
    assert _zone(document, "fields")["access"] == "closed"
    field = _farm_part(document, "field")
    assert (field["roles"], field["use_class"]) == (["field"], "")
    assert _passes(document)["verdict"] == "passed"


def test_a_zone_stated_closed_around_a_structure_is_opened_to_its_door() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    next(zone for zone in brief["zones"] if zone["label"] == "farmyard")["access"] = "closed"
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert _zone(compiled.document, "farmyard")["access"] == "open"
    assert _farm_part(compiled.document, "bench")["roles"] == ["seat"]  # still sat on
    assert _passes(compiled.document)["verdict"] == "passed"


def test_people_come_in_where_nobody_lives_and_the_brief_says_nobody_comes() -> None:
    brief = held_to_form(brief_of(fixture_kind("site")))
    brief["offsite_residents"] = 0
    compiled = compile_brief(brief, provenance=PROVENANCE)
    # Twelve builders, two site managers and a cook work there; all of them come in.
    assert compiled.document["society"]["offsite_residents"] == 15
    assert _passes(compiled.document)["verdict"] == "passed"


def test_more_people_than_a_world_houses_are_cut_to_the_bound() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    brief["offsite_residents"] = 128
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert any(step.startswith("offsite_residents 128 to") for step in compiled.sizing)
    assert _passes(compiled.document)["verdict"] == "passed"


# -- what the compiler makes of what a model gets wrong -------------------------------------------


def _farm_part(document: Mapping[str, Any], label: str) -> dict[str, Any]:
    return next(part for part in document["parts"] if part["label"] == label)


def test_what_a_model_gets_wrong_is_made_what_the_checks_need() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    farmyard = next(zone for zone in brief["zones"] if zone["label"] == "farmyard")
    bench = next(f for f in farmyard["fixtures"] if f["label"] == "bench")
    bench["seats"] = 12  # more than fit along 1800 mm
    bench["sleepers"] = 2  # a bench sleeps nobody
    barn = next(s for s in farmyard["structures"] if s["label"] == "barn")
    barn["work"][0]["closing_minute"] = barn["work"][0]["opening_minute"]  # open no minute
    barn["width_mm"] = {"from": 16100, "to": 12000}  # largest first, off the module
    hay = next(f for f in farmyard["fixtures"] if f["label"] == "hay bale")
    # Deck chairs drafted as a shop are seats people gather at, even with work stated for them.
    hay["roles"], hay["use_role"] = ["seat", "gathering"], "shop"
    hay["work"] = copy.deepcopy(barn["work"])
    # A stall stated as no seat and as a shop with work is a shop.
    stall = {**copy.deepcopy(hay), "label": "farm_stall", "roles": []}
    farmyard["fixtures"].append(stall)
    pond = next(zone for zone in brief["zones"] if zone["label"] == "pond corner")
    pond["access"] = "closed"  # the words close it; its rail is only seen
    pond["placement"] = "edge_back"
    farmyard["placement"] = "edge_back"  # a second zone across the far edge
    brief["zones"].append({**pond, "label": "empty", "structures": [], "areas": [], "fixtures": []})
    document = compile_brief(brief, size=False, provenance=PROVENANCE).document
    read_kind(document)
    assert _farm_part(document, "bench")["seats"] == 4
    assert _farm_part(document, "bench")["sleepers"] == 0
    uses = {use["key"]: use for use in document["use_classes"]}
    barn_use = uses[_farm_part(document, "barn")["use_class"]]
    assert (barn_use["opening_minute"], barn_use["closing_minute"]) == (0, 1440)
    assert _farm_part(document, "barn")["width_mm"] == {"from": 12000, "to": 16500}
    hay_part = _farm_part(document, "hay bale")
    assert hay_part["roles"] == ["gathering", "seat"]
    assert uses[hay_part["use_class"]]["kind"] == "furniture"
    assert uses[hay_part["use_class"]]["visitor_affordances"] == ["rest", "visit"]
    stall_part = _farm_part(document, "farm stall")  # a label's underscores read as spaces
    assert (stall_part["key"], stall_part["roles"]) == ("farm_stall", ["shop"])
    assert uses[stall_part["use_class"]]["visitor_capacity"] == 4
    zones = {zone["label"]: zone for zone in document["zones"]}
    assert zones["pond corner"]["access"] == "closed"
    assert _farm_part(document, "pond rail")["roles"] == ["decoration"]
    assert [zone["placement"] for zone in document["zones"]].count("edge_back") == 1
    assert "empty" not in zones


def test_one_use_stated_twice_in_the_same_words_is_one_class() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    farmyard = next(zone for zone in brief["zones"] if zone["label"] == "farmyard")
    barn = next(s for s in farmyard["structures"] if s["label"] == "barn")
    farmyard["structures"].append(copy.deepcopy(barn))
    document = compile_brief(brief, size=False, provenance=PROVENANCE).document
    barns = [part for part in document["parts"] if part["label"] == "barn"]
    assert [part["key"] for part in barns] == ["barn", "barn_2"]
    assert barns[0]["use_class"] == barns[1]["use_class"]
    assert sum(1 for use in document["use_classes"] if use["label"] == "barn") == 1


def test_a_use_named_like_one_of_the_societys_is_named_apart() -> None:
    brief = held_to_form(brief_of(fixture_kind("cafe")))
    zone = next(zone for zone in brief["zones"] if zone["fixtures"])
    counter = next(f for f in zone["fixtures"] if f["use_role"] == "shop")
    counter["label"] = "bakery"
    document = compile_brief(brief, size=False, provenance=PROVENANCE).document
    assert _farm_part(document, "bakery")["use_class"] == "bakery_2"
    read_kind(document)


def test_where_a_check_refused_a_kind_is_said_in_the_brief() -> None:
    brief = held_to_form(brief_of(fixture_kind("farm")))
    compiled = compile_brief(brief, size=False, provenance=PROVENANCE)
    keys = [part["key"] for part in compiled.document["parts"]]
    bedroom = keys.index("bedroom")
    assert brief_where(f"parts[{bedroom}].holds[0].count", compiled) == (
        "zones[0].structures[0].rooms[1].fixtures[0].count"
    )
    barn_use = next(
        i for i, use in enumerate(compiled.document["use_classes"]) if use["label"] == "barn"
    )
    assert brief_where(f"use_classes[{barn_use}].shifts", compiled) == (
        "zones[0].structures[1].work[0].shifts"
    )
    assert brief_where("zones[1].holds[0].count", compiled) == "zones[1].areas[0].count"
    assert brief_where("zones[2].holds", compiled) == (
        "zones[2] (its structures, areas and fixtures together)"
    )
    assert brief_where("part farmhouse", compiled) == "zones[0].structures[0]"
    assert brief_where("site.entry_width_mm", compiled) == "spine.width_mm"
    assert brief_where("sample preset as_described", compiled) == "a sample world of the kind"


def test_an_indoor_zone_its_own_walls_close_is_given_a_thinner_inner_wall(monkeypatch):
    """Indoors a zone's walks run in a narrow verge inside its walls, which thick walls close: a
    kind its samples refuse as unreached there gets an inner wall of its own, half as thick, until
    the samples pass; the outer walls stay as stated."""
    from exulanica.selection import kind_brief

    brief = held_to_form(brief_of(fixture_kind("cafe")))
    brief["boundary"]["thickness_mm"] = 300
    brief["spine"]["width_mm"] = 1500
    for zone in brief["zones"]:
        zone["fenced"] = True
    # The control: without the answer, the samples refuse the kind as unreached.
    with monkeypatch.context() as patched:
        patched.setattr(kind_brief._Sizing, "inner_walls", lambda self: None)
        unanswered = compile_brief(brief, provenance=PROVENANCE).document
        with pytest.raises(KindRefused, match="kind_unreachable"):
            check_samples(read_kind(unanswered))
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert "inner wall inner_wall thickness_mm 300 to 150" in compiled.sizing
    walls = {part["key"]: part for part in compiled.document["parts"] if part["form"] == "boundary"}
    outer = compiled.document["site"]["boundary"]
    assert (walls[outer]["thickness_mm"], walls["inner_wall"]["thickness_mm"]) == (300, 150)
    assert {zone["boundary"] for zone in compiled.document["zones"]} == {"inner_wall"}
    assert _passes(compiled.document)["verdict"] == "passed"


def test_a_site_holding_no_area_is_trimmed_to_room_to_spare_round_its_smallest():
    from exulanica.selection import kind_brief

    brief = held_to_form(brief_of(fixture_kind("cafe")))
    brief["site_depth_mm"] = 60000  # a small cafe on a long empty floor
    compiled = compile_brief(brief, provenance=PROVENANCE)
    trimmed = [step for step in compiled.sizing if step.startswith("site depth_mm 60000 to ")]
    assert len(trimmed) == 1
    depth = compiled.document["site"]["depth_mm"]
    assert depth < 60000 and _passes(compiled.document)["verdict"] == "passed"
    # No more than twice the smallest depth whose samples pass, found apart from the compiler a
    # module at a time, within the last step of the compiler's six halvings (52 m / 64).
    smallest = copy.deepcopy(compiled.document)
    module = 100
    while True:
        smallest["site"]["depth_mm"] -= module
        if not kind_brief._passes(smallest):
            break
    assert depth <= 2 * (smallest["site"]["depth_mm"] + module + 52000 // 64)
    # A site holding areas keeps its size: they fill it.
    farm = compile_brief(held_to_form(brief_of(fixture_kind("farm"))), provenance=PROVENANCE)
    assert farm.document["site"]["depth_mm"] == 128000


def test_a_side_of_the_spine_too_short_for_its_zones_grows_by_the_shortfall_the_layout_states():
    """Every zone on one side: the depth floor (half of what they all need) is too short, and the
    layout's own sentence says by how much; the site grows by that and its samples lay out."""
    brief = held_to_form(brief_of(fixture_kind("farm")))
    for zone in brief["zones"]:
        zone["placement"] = "left"
    brief["site_depth_mm"] = 8000
    compiled = compile_brief(brief, provenance=PROVENANCE)
    depth_steps = [step for step in compiled.sizing if "site depth_mm" in step]
    assert len(depth_steps) >= 2  # the floor from the need function, then the stated shortfall
    assert _passes(compiled.document)["verdict"] == "passed"


def test_a_zone_across_the_far_edge_with_a_share_too_small_is_given_more_of_the_depth():
    """A model states shares as small weights; the zone across the far edge takes its share per
    thousand of the site's depth, so a share of 1 takes nothing: its share is raised, never the
    depth grown for it, and the samples lay out."""
    brief = held_to_form(brief_of(fixture_kind("farm")))
    pond = next(zone for zone in brief["zones"] if zone["label"] == "pond corner")
    pond.update(placement="edge_back", share=1)
    compiled = compile_brief(brief, provenance=PROVENANCE)
    assert compiled.sizing[0] == "zone pond_corner share 1 to 100"
    assert _passes(compiled.document)["verdict"] == "passed"


def test_a_zone_across_the_far_edge_too_shallow_for_its_areas_is_given_more_of_the_depth():
    """Its lot is as deep as its share of the site's depth, so the width is not what grows."""
    brief = held_to_form(brief_of(fixture_kind("farm")))
    fields = next(zone for zone in brief["zones"] if zone["label"] == "fields")
    fields.update(placement="edge_back", share=50)
    compiled = compile_brief(brief, provenance=PROVENANCE)
    raised = [step for step in compiled.sizing if step.startswith("zone fields share 50 to ")]
    assert raised and not any(
        "width_mm" in step for step in compiled.sizing[: compiled.sizing.index(raised[0])]
    )
    assert _passes(compiled.document)["verdict"] == "passed"
