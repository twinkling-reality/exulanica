"""World kinds: a kind of world as one data object, refused by name until people can live in it.

The kinds here are the hand-written fixtures in ``tests/fixtures/world-kinds`` (test fixtures, not
kinds a person or a model made). Each refusal test changes one thing in a fixture that passes, so
the refusal is that change's and no other's; expected figures are counted here from the kind
document and the records, never read back from the code under test.
"""

from __future__ import annotations

import contextlib
import copy
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.site.records import (
    SiteFixtureRecord,
    SiteRoomRecord,
    SiteStructureRecord,
)
from exulanica.world.kinds.catalogs import CATALOG_DIRECTORY, load_kind_catalogs
from exulanica.world.kinds.document import KindRefused, KindValueRefused, read_kind
from exulanica.world.kinds.routine import kind_overlay, kind_routine, overlay_routine
from exulanica.world.kinds.samples import SiteRefused, check_samples, compose_site
from exulanica.world.society_living import town_routine
from exulanica.world.society_place import validate_place

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"


def _document(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8"))


def _refused(document: dict[str, Any]) -> KindRefused:
    with pytest.raises(KindRefused) as caught:
        read_kind(document)
    return caught.value


def _part(document: dict[str, Any], key: str) -> dict[str, Any]:
    return next(part for part in document["parts"] if part["key"] == key)


@pytest.mark.parametrize("name", ["farm", "cafe", "site"])
def test_each_fixture_kind_passes_both_stages(name: str) -> None:
    kind = read_kind(_document(name))
    report = check_samples(kind)
    assert report["verdict"] == "passed"
    expected_samples = 2 * len(kind.presets) + sum(
        1
        for parameter in kind.parameters
        for value in (parameter.minimum, parameter.maximum)
        if value != kind.presets[0][2][parameter.key]
    )
    assert len(report["samples"]) == expected_samples


def _mutated(name: str, change) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    document = copy.deepcopy(_document(name))
    change(document)
    return document


MUTANTS = {
    "an unknown top-level key": (
        lambda d: d.update(colour="red"),
        "kind_document_invalid",
    ),
    "a float figure": (
        lambda d: d["site"].update(depth_mm=128000.5),
        "kind_document_invalid",
    ),
    "an engine role nobody has": (
        lambda d: _part(d, "bench")["roles"].append("teleporter"),
        "kind_role_unknown",
    ),
    "a role the part's form may not take": (
        lambda d: _part(d, "barn")["roles"].append("bed"),
        "kind_role_unknown",
    ),
    "a look family that does not exist": (
        lambda d: _part(d, "bench").update(look="spaceship.bench"),
        "kind_role_unknown",
    ),
    "a seat that seats nobody": (
        lambda d: _part(d, "bench").update(seats=0),
        "kind_role_unmet",
    ),
    "a workplace with no workplace use class": (
        lambda d: _part(d, "barn").update(use_class=""),
        "kind_role_unmet",
    ),
    "a use class nobody states": (
        lambda d: _part(d, "barn").update(use_class="spaceport"),
        "kind_reference_unknown",
    ),
    "a zone holding a part nobody states": (
        lambda d: d["zones"][0]["holds"].append({"part": "windmill", "count": 1, "pattern": "row"}),
        "kind_reference_unknown",
    ),
    "a length off the site's module": (
        lambda d: d["site"].update(depth_mm=128100),
        "kind_out_of_bounds",
    ),
    "a site past the largest": (
        lambda d: d["site"].update(depth_mm=512000),
        "kind_out_of_bounds",
    ),
    "a preset value off its parameter's step": (
        lambda d: d["presets"][0]["values"].update(width_mm=100000),
        "kind_out_of_bounds",
    ),
    "a parameter no figure uses": (
        lambda d: (
            d["parameters"].append(
                {
                    "key": "unused",
                    "label": "Unused",
                    "minimum": 1,
                    "maximum": 2,
                    "step": 1,
                    "reason": "x",
                }
            )
            or [preset["values"].update(unused=1) for preset in d["presets"]]
        ),
        "kind_reference_unknown",
    ),
    "a use class naming a shift the society lacks": (
        lambda d: d["use_classes"][0].update(shifts=["graveyard"]),
        "kind_reference_unknown",
    ),
    "a use class repeating one of the society's": (
        lambda d: d["use_classes"][0].update(key="cafe"),
        "kind_document_invalid",
    ),
    "a licence the matrix does not ship": (
        lambda d: d["licence"].update(spdx="CC-BY-NC-4.0"),
        "kind_document_invalid",
    ),
    "a generator nobody builds": (
        lambda d: d["generator"].update(key="dream-engine"),
        "kind_reference_unknown",
    ),
}


@pytest.mark.parametrize("case", sorted(MUTANTS))
def test_stage_a_refuses_each_fault_by_its_own_code(case: str) -> None:
    change, code = MUTANTS[case]
    assert read_kind(_document("farm"))  # the fixture itself passes: each refusal is the change's
    refusal = _refused(_mutated("farm", change))
    assert refusal.code == code, (case, refusal)


def test_a_closed_zone_that_holds_a_workplace_is_refused_as_unreachable():
    def close_the_farmyard(document: dict[str, Any]) -> None:
        document["zones"][0]["access"] = "closed"

    kind = read_kind(_mutated("farm", close_the_farmyard))
    with pytest.raises(KindRefused) as caught:
        check_samples(kind)
    assert caught.value.code == "kind_unreachable"


def test_a_kind_that_houses_nobody_is_refused():
    def nobody(document: dict[str, Any]) -> None:
        document["society"]["offsite_residents"] = 0
        document["parameters"] = []
        document["presets"][0]["values"] = {}

    kind = read_kind(_mutated("cafe", nobody))
    with pytest.raises(KindRefused) as caught:
        check_samples(kind)
    assert caught.value.code == "kind_population_out_of_bounds"


@pytest.mark.parametrize("character", ["\u0000", "\r", "\u202e", "\u200b", "\ufeff", "\ue000"])
def test_text_holding_a_control_or_format_character_is_refused(character: str) -> None:
    def marked(document: dict[str, Any]) -> None:
        document["label"] = f"A {character}cafe"

    refused = _refused(_mutated("cafe", marked))
    assert (refused.code, refused.where) == ("kind_document_invalid", "label")


def test_a_kind_too_big_to_generate_is_refused_before_anything_is_generated():
    # An indoor site of 60 m by 60 m is 600 by 600 points on its 100 mm module, past the 512 by
    # 512 the bounds catalog allows (grid_points); the same cafe holding ten times 64 tables
    # places 640 things, past 512 (placed_things).
    def wide(document: dict[str, Any]) -> None:
        document["site"]["width_mm"] = 60_000
        document["site"]["depth_mm"] = 60_000

    def crowded(document: dict[str, Any]) -> None:
        document["zones"][0]["holds"].extend(
            {"part": "table", "count": 64, "pattern": "grid"} for _ in range(10)
        )
        document["zones"][0]["holds"] = document["zones"][0]["holds"][:12]

    refused = _refused(_mutated("cafe", wide))
    assert (refused.code, refused.where) == ("kind_out_of_bounds", "site")
    assert "360000 grid points" in refused.detail
    refused = _refused(_mutated("cafe", crowded))
    assert (refused.code, refused.where) == ("kind_out_of_bounds", "zones")
    assert "outside 1 to 512" in refused.detail


def test_a_site_too_large_to_walk_is_refused_while_its_graph_is_built():
    # The farm stretched to the largest site the bounds allow: its open ground needs more walking
    # places than the 962 a living society's tick was measured on (the bounds catalog).
    def huge(document: dict[str, Any]) -> None:
        document["site"]["depth_mm"] = 256_000
        width = document["parameters"][0]
        width["minimum"], width["maximum"], width["step"] = 224_000, 256_000, 32_000
        document["presets"][0]["values"]["width_mm"] = 256_000

    kind = read_kind(_mutated("farm", huge))
    with pytest.raises(KindRefused) as caught:
        check_samples(kind)
    assert caught.value.code == "kind_graph_over_budget"
    # Refused from the budget held while the graph was built, not from counting it afterwards.
    assert "grew past 962 places" in caught.value.detail


def test_a_side_that_cannot_hold_its_zones_is_refused_with_every_figure():
    def crowd(document: dict[str, Any]) -> None:
        document["site"]["depth_mm"] = 24000

    kind = read_kind(_mutated("site", crowd))
    with pytest.raises(KindRefused) as caught:
        check_samples(kind)
    assert caught.value.code == "kind_generation_refused"
    assert "zones need" in caught.value.detail and " mm (" in caught.value.detail


def test_the_values_gate_refuses_by_name_and_never_clamps():
    kind = read_kind(_document("farm"))
    assert kind.values("small_farm") == {"barns": 1, "width_mm": 96000}
    assert kind.values("small_farm", {"barns": 2})["barns"] == 2
    with pytest.raises(KindValueRefused) as unknown:
        kind.values("small_farm", {"silos": 3})
    assert unknown.value.code == "specification_value_unknown"
    for value in (3, 0, 1.5, "2", 96500):
        key = "width_mm" if value == 96500 else "barns"
        with pytest.raises(KindValueRefused) as outside:
            kind.values("small_farm", {key: value})
        assert outside.value.code == "specification_value_out_of_range"


def test_the_overlay_adds_the_kinds_use_classes_and_leaves_the_base_routine_as_it_was():
    base = town_routine()
    before = (base.sha256, dict(base.use_classes), dict(base.policy))
    kind = read_kind(_document("farm"))
    routine = kind_routine(kind, base)
    assert (base.sha256, dict(base.use_classes), dict(base.policy)) == before
    stated = {entry["key"] for entry in _document("farm")["use_classes"]}
    assert set(routine.use_classes) == set(base.use_classes) | stated
    assert routine.policy["employment_share_milli"] == 1000
    assert routine.sha256 != base.sha256
    broken = kind_overlay(kind)
    broken["use_classes"][0]["shifts"] = ["graveyard"]
    with pytest.raises(CatalogError):
        overlay_routine(base, broken)


def test_a_world_houses_the_sleepers_of_its_beds_and_reaches_every_destination():
    kind = read_kind(_document("farm"))
    values = kind.values("small_farm")
    world = compose_site(kind, values, "world:test-farm")
    validate_place(world.place, world.routine)
    # Residents counted here from the records: the sleepers of the beds in each home's rooms.
    homes = {
        r.identity
        for r in world.records
        if isinstance(r, SiteStructureRecord) and "home" in r.roles
    }
    rooms = {
        r.identity
        for r in world.records
        if isinstance(r, SiteRoomRecord) and r.structure_identity in homes
    }
    sleepers = sum(
        r.sleepers
        for r in world.records
        if isinstance(r, SiteFixtureRecord) and r.owner_identity in rooms
    )
    residents = sum(d["resident_capacity"] for d in world.place["destinations"])
    assert residents == sleepers > 0
    # Every destination is reached from the entry, by a search written here.
    adjacent: dict[str, set[str]] = {}
    for edge in world.place["edges"]:
        adjacent.setdefault(edge["from_node_id"], set()).add(edge["to_node_id"])
        adjacent.setdefault(edge["to_node_id"], set()).add(edge["from_node_id"])
    seen, frontier = {"entry"}, ["entry"]
    while frontier:
        for other in adjacent.get(frontier.pop(), ()):
            if other not in seen:
                seen.add(other)
                frontier.append(other)
    assert {d["node_id"] for d in world.place["destinations"]} <= seen


def test_a_kind_whose_people_come_from_off_the_site_houses_them_at_its_entry():
    kind = read_kind(_document("site"))
    values = kind.values("small_job")
    world = compose_site(kind, values, "world:test-site")
    offsite = [d for d in world.place["destinations"] if d["destination_id"] == "home:offsite"]
    assert [d["resident_capacity"] for d in offsite] == [values["workers"]]
    assert [d["node_id"] for d in offsite] == ["entry"]


def test_two_worlds_of_one_kind_differ_and_one_world_is_the_same_each_time():
    kind = read_kind(_document("farm"))
    values = kind.values("small_farm")
    first = compose_site(kind, values, "world:a")
    again = compose_site(kind, values, "world:a")
    other = compose_site(kind, values, "world:b")
    assert first.output_digest == again.output_digest and first.place == again.place
    assert other.output_digest != first.output_digest


def test_compose_refuses_with_every_candidate_when_none_fits():
    def impossible(document: dict[str, Any]) -> None:
        _part(document, "barn")["width_mm"] = 60000
        document["zones"][0]["holds"][1]["count"] = 3
        document["parameters"] = [p for p in document["parameters"] if p["key"] != "barns"]
        for preset in document["presets"]:
            preset["values"].pop("barns")

    kind = read_kind(_mutated("farm", impossible))
    with pytest.raises(SiteRefused) as caught:
        compose_site(kind, kind.values("small_farm"), "world:x")
    assert caught.value.code == "kind_generation_refused"
    assert [r["candidate"] for r in caught.value.refusals] == [0, 1, 2, 3]


def test_the_kind_catalogs_state_the_site_grammars_words(tmp_path: Path) -> None:
    catalogs = load_kind_catalogs()
    assert len(catalogs.families) == 16 and len(catalogs.role_forms) == 16
    # A catalog that drops a family the grammar knows is refused: the check can fail.
    copied = tmp_path / "world-kinds"
    shutil.copytree(CATALOG_DIRECTORY, copied)
    families = json.loads((copied / "look-family.v1.json").read_text(encoding="utf-8"))
    families["entries"] = [e for e in families["entries"] if e["key"] != "water"]
    (copied / "look-family.v1.json").write_text(json.dumps(families), encoding="utf-8")
    with pytest.raises(CatalogError, match="look-family catalog states"):
        load_kind_catalogs.__wrapped__(copied)  # type: ignore[attr-defined]


#: Values a kind's JSON may hold in the wrong place: each lookup a value names must refuse it by
#: name, never fail with another error (a list or an object where a key is read was once a 500).
_WRONG: tuple[object, ...] = (None, True, [], {}, ["a"], {"a": 1}, "", "x" * 300, -1, 2**40)
#: Text no kind may hold anywhere: a NUL (which the database's JSON cannot keep) and a zero-width
#: space (a format character).
_NEVER_KEPT: tuple[str, ...] = ("a\u0000b", "a​b")


def _leaves(node: object, at: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    found: list[tuple[object, ...]] = [at]
    if isinstance(node, dict):
        for key, value in node.items():
            found.extend(_leaves(value, (*at, key)))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            found.extend(_leaves(value, (*at, index)))
    return found


def _put(document: dict[str, Any], at: tuple[object, ...], value: object) -> object:
    if not at:
        return value
    changed = copy.deepcopy(document)
    node: Any = changed
    for step in at[:-1]:
        node = node[step]
    node[at[-1]] = value
    return changed


def test_every_value_of_a_kind_in_the_wrong_shape_is_refused_by_name_and_odd_text_never_kept():
    farm = _document("farm")
    for at in _leaves(farm):
        for value in _WRONG:
            with contextlib.suppress(KindRefused):
                read_kind(_put(farm, at, value))
        # Every place a value stands, a key's or a word's alike, refuses this text.
        for text in _NEVER_KEPT:
            with pytest.raises(KindRefused):
                read_kind(_put(farm, at, text))


def test_a_use_class_s_words_are_held_as_every_text_of_a_kind_is():
    def zero_width(document: dict[str, Any]) -> None:
        document["use_classes"][0]["role_label"] = "dairy​hand"

    def long_label(document: dict[str, Any]) -> None:
        document["use_classes"][0]["label"] = "a" * 61

    refused = _refused(_mutated("farm", zero_width))
    assert (refused.code, refused.where) == ("kind_document_invalid", "use_classes[0].role_label")
    refused = _refused(_mutated("farm", long_label))
    assert (refused.code, refused.where) == ("kind_out_of_bounds", "use_classes[0].label")
