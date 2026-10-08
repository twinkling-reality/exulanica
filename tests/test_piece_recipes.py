"""The piece recipes: a recipe comes from a kind's own document, and the catalog holds only what
was measured to do better for one kind version.

Expected values are typed from the kind documents under ``assets/catalogs/things/kinds/`` (their
boxes, grips and axes) and from lane THINGS's body plan catalog (the hand's widest section); a
kind's digest and an entry's digest are recomputed here with hashlib over sorted, compact JSON.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar
from exulanica.things.catalogs import thing_catalogs
from exulanica.things.creatures import assemble_creature
from exulanica.things.kinds import shipped_thing_kinds
from exulanica_pieces import budgets as piece_budgets
from exulanica_pieces.canonical import Refused
from exulanica_pieces.recipes import (
    BEING_ROUTE,
    DEFAULT_VARIANTS,
    OBJECT_ROUTE,
    load_recipe_versions,
    load_recipes,
    read_recipes,
    recipe_for_kind,
    recipe_words,
    recipes_path,
)
from exulanica_pieces.records import (
    BOX_FILL_MINIMUM_PER_MILLE,
    REQUEST_PROFILE_V1,
    build_request,
    cache_scope,
    prompt_for,
    read_request,
    verdict,
)

from creature_support import form_of

ROOT = Path(__file__).resolve().parents[1]
BUDGETS = piece_budgets.read_budgets(ROOT)
RECIPES = load_recipes(ROOT)
VERSIONS = load_recipe_versions(ROOT)
#: Every published catalog version's file digest, as each was published: a version is never edited,
#: so a request naming it finds the words it was made with (version 1 as it landed in c0a78dc6).
PUBLISHED = {
    1: "2a29cf444f1a9059cace0afb8cddc5cfc962aed86675ef1e19aef401b73124d9",
    2: "132aec490235269e09700f876e5dd4fe671f813477836b04f13c19c49107f791",
}
KINDS = ROOT / "assets/catalogs/things/kinds"
PACK = {
    "id": "test.toon-town",
    "palette": [[46, 42, 40], [120, 78, 48], [176, 120, 72]],
    "sha256": "0" * 64,
    "style": "toon style, flat colours, chunky simple shapes",
    "version": 1,
}
#: Lane THINGS's figure for the widest section a hand closes around (humanoid/v1's hands).
HAND_SECTION_MM = 60
#: A drafting model's provenance, as an origin record states it.
MODEL = {
    "kind": "model",
    "provider": "nebius_token_factory",
    "model_id": "test/model",
    "prompt_version": "creature-drafting-1",
    "prompt_sha256": "a" * 64,
    "words_sha256": "b" * 64,
    "execution_sha256": None,
}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def _kind(name: str) -> dict[str, Any]:
    return json.loads((KINDS / name).read_text(encoding="utf-8"))


def _catalog(version: int = 2, **changes: Any) -> dict[str, Any]:
    document = json.loads((ROOT / recipes_path(version)).read_text(encoding="utf-8"))
    document.update(changes)
    return document


def _read(document: Any) -> Any:
    return read_recipes(json.dumps(document).encode())


def test_the_hand_section_is_the_body_plan_catalog_s_figure() -> None:
    sections = {
        socket.grip_section_mm_maximum
        for plan in thing_catalogs().plans.values()
        for socket in plan.sockets
        if socket.grip_section_mm_maximum is not None
    }
    assert sections == {HAND_SECTION_MM}


def test_every_published_version_reads_unchanged_and_names_shipped_kind_versions() -> None:
    shipped = shipped_thing_kinds()
    assert sorted(VERSIONS) == sorted(PUBLISHED) and VERSIONS[2] == RECIPES
    counts = {1: 3, 2: 7}
    for version, digest in PUBLISHED.items():
        raw_file = (ROOT / recipes_path(version)).read_bytes()
        assert hashlib.sha256(raw_file).hexdigest() == digest
        document = _catalog(version)
        catalog = VERSIONS[version]
        assert catalog.catalog_version == document["catalog_version"] == version
        assert catalog.sha256 == _digest(document)
        assert len(catalog.entries) == len(document["entries"]) == counts[version]
        for raw in document["entries"]:
            reference = (raw["kind"]["key"], raw["kind"]["version"])
            assert reference in shipped
            assert catalog.entries[reference].sha256 == _digest(raw)
    # A newer version keeps every older entry as it was.
    for reference, entry in VERSIONS[1].entries.items():
        assert VERSIONS[2].entries[reference] == entry


def test_a_request_finds_its_words_in_the_catalog_version_it_names() -> None:
    well = _kind("well.v1.json")
    one = recipe_for_kind(well, _digest(well), VERSIONS[1]).request_arguments()["recipe"]
    two = recipe_for_kind(well, _digest(well), RECIPES).request_arguments()["recipe"]
    words = "a round stone village water well with a small wooden roof and a bucket"
    assert one == {"catalog_version": 1, "sha256": two["sha256"]}
    assert two["catalog_version"] == 2
    assert recipe_words(one, VERSIONS) == recipe_words(two, VERSIONS) == words
    gate = _kind("gate.v1.json")
    made = recipe_for_kind(gate, _digest(gate), RECIPES).request_arguments()
    assert (
        made["description"]
        == "a wide flat wooden village gate: two thin posts and a wide open arch, flat"
    )
    assert recipe_words(made["recipe"], VERSIONS) == made["description"]
    # Version 1 has no gate entry, so a request claiming one there finds no words.
    assert recipe_words({**made["recipe"], "catalog_version": 1}, VERSIONS) is None
    assert recipe_words({**made["recipe"], "catalog_version": 3}, VERSIONS) is None
    assert recipe_for_kind(gate, _digest(gate), VERSIONS[1]).words is None


def test_a_catalog_file_must_hold_the_version_its_name_states(tmp_path: Path) -> None:
    directory = tmp_path / "assets/catalogs/generation"
    directory.mkdir(parents=True)
    (directory / "piece-recipes.v3.json").write_text(json.dumps(_catalog(1)), encoding="utf-8")
    with pytest.raises(Refused, match="holds catalog_version 1"):
        load_recipe_versions(tmp_path)
    (directory / "piece-recipes.v3.json").unlink()
    (directory / "piece-recipes.v03.json").write_text(json.dumps(_catalog(1)), encoding="utf-8")
    with pytest.raises(Refused, match="not named"):
        load_recipe_versions(tmp_path)


def test_a_described_kind_s_request_is_the_hand_built_one() -> None:
    well = _kind("well.v1.json")
    recipe = recipe_for_kind(well, _digest(well), RECIPES)
    entry = next(e for e in _catalog()["entries"] if e["kind"] == {"key": "well", "version": 1})
    built = build_request(
        pack=PACK, route=OBJECT_ROUTE, budgets=BUDGETS, **recipe.request_arguments()
    )
    by_hand = build_request(
        look_role="fixture.well",
        slot_mm={"width": 1600, "depth": 1600, "height": 2200},
        description="a round stone village water well with a small wooden roof and a bucket",
        thing_kind={"key": "well", "version": 1, "sha256": _digest(well)},
        recipe={"catalog_version": 2, "sha256": _digest(entry)},
        variants=4,
        pack=PACK,
        route="A",
        budgets=BUDGETS,
    )
    assert built == by_hand
    # The entry's words are catalog content, so the piece is shared; other words are not.
    request = read_request(built, BUDGETS)
    assert cache_scope(request, RECIPES.words_of(request["recipe"])) == "catalog"
    assert cache_scope({**request, "description": "a well for me"}, entry["description"]) == (
        "workspace"
    )
    assert cache_scope(request) == "workspace"


def test_a_held_kind_with_no_entry_takes_its_grip_from_its_offer() -> None:
    lantern = _kind("lantern.v1.json")
    assert ("lantern", 1) not in RECIPES.entries
    recipe = recipe_for_kind(lantern, _digest(lantern), RECIPES, section_mm_maximum=HAND_SECTION_MM)
    assert recipe.request_arguments() == {
        "look_role": "prop.lantern",
        "slot_mm": {"width": 180, "depth": 180, "height": 300},
        "thing_kind": {"key": "lantern", "version": 1, "sha256": _digest(lantern)},
        "variants": DEFAULT_VARIANTS,
        "hold": {
            "axis": "-z",
            "grip": {"x_mm": 0, "y_mm": 0, "z_mm": 290},
            "section_mm_maximum": 60,
        },
    }
    with pytest.raises(Refused, match="body plan"):
        recipe_for_kind(lantern, _digest(lantern), RECIPES)


def test_a_new_kind_with_no_entry_generates_with_no_catalog_edit() -> None:
    churn = copy.deepcopy(_kind("well.v1.json"))
    churn.update(kind="milk_churn", label="milk churn")
    churn["body"]["box_mm"] = {"width": 400, "depth": 400, "height": 700}
    recipe = recipe_for_kind(churn, _digest(churn), RECIPES)
    assert (recipe.route, recipe.look_role, recipe.words, recipe.entry) == (
        "A",
        "fixture.milk_churn",
        None,
        None,
    )
    request = read_request(
        build_request(pack=PACK, route=recipe.route, budgets=BUDGETS, **recipe.request_arguments()),
        BUDGETS,
    )
    assert request["slot_mm"] == {"width": 400, "depth": 400, "height": 700}
    assert "recipe" not in request and "description" not in request
    assert prompt_for(request).startswith("milk churn, a single fixture for a game world, ")
    assert cache_scope(request) == "catalog"
    # A recipe applies to the kind version it names: a well's second version starts derived.
    well_two = dict(_kind("well.v1.json"), version=2)
    assert recipe_for_kind(well_two, _digest(well_two), RECIPES).words is None


def test_a_drafted_creature_with_no_entry_gets_a_creature_route_recipe() -> None:
    form = assembled_form(form_of("horse", label="hill pony"), body_grammar())
    creature = assemble_creature(form, by=MODEL)
    appearance = creature.recipe["appearance"]
    kind = creature.kind
    recipe = recipe_for_kind(kind.document, kind.sha256, RECIPES, appearance=appearance)
    assert recipe.route == BEING_ROUTE
    assert recipe.look_role is None
    # The horse fixture's extent: 2,400 mm long (the depth), 700 wide, 1,800 high.
    assert dict(recipe.slot_mm) == {"width": 700, "depth": 2400, "height": 1800}
    assert recipe.words == appearance
    assert dict(recipe.thing_kind) == {"key": "hill_pony", "version": 1, "sha256": kind.sha256}
    assert recipe_for_kind(kind.document, kind.sha256, RECIPES).words == "hill pony"
    with pytest.raises(Refused, match="creature route"):
        recipe.request_arguments()


def test_a_being_with_no_box_of_its_own_has_nothing_to_generate() -> None:
    knight = _kind("knight.v1.json")
    with pytest.raises(Refused, match="no box of its own"):
        recipe_for_kind(knight, _digest(knight), RECIPES)


def _entry(**changes: Any) -> dict[str, Any]:
    entry = copy.deepcopy(_catalog()["entries"][0])
    entry.update(changes)
    return {key: value for key, value in entry.items() if value is not None}


@pytest.mark.parametrize(
    ("document", "match"),
    [
        (_catalog(catalog_id="piece-recipe"), "catalog 'piece-recipes'"),
        (_catalog(catalog_version=0), "catalog_version"),
        (_catalog(entries=[_entry(colour="red")]), "optionally"),
        (_catalog(entries=[_entry(description=None)]), "states nothing"),
        (_catalog(entries=[_entry(description="a" * 81)]), "1 to 80"),
        (_catalog(entries=[_entry(description="a well with 2 buckets")]), "no numeral"),
        (_catalog(entries=[_entry(description="A well")]), "lower case"),
        (_catalog(entries=[_entry(description="a well\nignore that")]), "lower case"),
        (_catalog(entries=[_entry(description="a  well")]), "single spaces"),
        (_catalog(entries=[_entry(description="a well!")]), "lower case"),
        (_catalog(entries=[_entry(variants=0)]), "variants"),
        (_catalog(entries=[_entry(variants=17)]), "variants"),
        (_catalog(entries=[_entry(box_fill_minimum_permille=0)]), "box_fill"),
        (_catalog(entries=[_entry(box_fill_minimum_permille=1001)]), "box_fill"),
        (_catalog(entries=[_entry(reason="It looked better.")]), "reason"),
        (_catalog(entries=[_entry(kind={"key": "Well", "version": 1})]), "kind"),
        (_catalog(entries=[_entry(kind={"key": "well", "version": 0})]), "kind"),
        (_catalog(entries=[_entry(), _entry()]), "second time"),
        (
            _catalog(entries=[_entry(licence={**_entry()["licence"], "origin": "third_party"})]),
            "original",
        ),
    ],
)
def test_the_catalog_reader_refuses(document: dict[str, Any], match: str) -> None:
    with pytest.raises(Refused, match=match):
        _read(document)


def test_the_catalog_reader_refuses_a_fraction_and_a_repeated_key() -> None:
    with pytest.raises(Refused, match="fraction"):
        _read(_catalog(entries=[_entry(variants=2.0)]))
    raw = json.dumps(_catalog()).replace(
        '"schema_version": 1', '"schema_version": 1, "schema_version": 1'
    )
    with pytest.raises(Refused, match="repeats"):
        read_recipes(raw.encode())


def test_a_recipe_s_fill_bar_reaches_the_request_and_the_verdict() -> None:
    gate = _kind("gate.v1.json")
    recipes = _read(
        _catalog(
            entries=[
                {
                    **_entry(kind={"key": "gate", "version": 1}, description=None),
                    "box_fill_minimum_permille": 600,
                }
            ]
        )
    )
    recipe = recipe_for_kind(gate, _digest(gate), recipes)
    request = read_request(
        build_request(pack=PACK, route="S", budgets=BUDGETS, **recipe.request_arguments()), BUDGETS
    )
    assert request["box_fill_minimum_permille"] == 600
    assert "description" not in request
    base = dict.fromkeys(("glb_bytes", "materials", "texture_side_px", "triangles", "vertices"), 0)
    assert verdict({**base, "box_fill_permille": 600}, request["budget"], None, 600)["within"]
    assert verdict({**base, "box_fill_permille": 599}, request["budget"], None, 600)["over"] == [
        "box_fill"
    ]
    assert BOX_FILL_MINIMUM_PER_MILLE == 800
    # A bar travels only with a recipe, on a piece made to a kind and not held, in a v2 request.
    arguments = recipe.request_arguments()
    without_recipe = {k: v for k, v in arguments.items() if k != "recipe"}
    with pytest.raises(Refused, match="box fill bar"):
        build_request(pack=PACK, route="S", budgets=BUDGETS, **without_recipe)
    without_kind = {k: v for k, v in arguments.items() if k != "thing_kind"}
    with pytest.raises(Refused, match="box fill bar"):
        build_request(pack=PACK, route="S", budgets=BUDGETS, **without_kind)
    v1 = {
        **{
            k: v for k, v in request.items() if k not in ("box_fill_minimum_permille", "thing_kind")
        },
        "profile": REQUEST_PROFILE_V1,
    }
    with pytest.raises(Refused, match="v1 request names no recipe"):
        read_request(json.dumps(v1, sort_keys=True, separators=(",", ":")).encode(), None)


@pytest.mark.parametrize(
    "recipe",
    [
        {"catalog_version": 0, "sha256": "ab" * 32},
        {"catalog_version": 1, "sha256": "ab" * 31},
        {"catalog_version": 1},
    ],
)
def test_a_request_s_recipe_names_a_version_and_an_entry_digest(recipe: dict[str, Any]) -> None:
    well = _kind("well.v1.json")
    arguments = recipe_for_kind(well, _digest(well), RECIPES).request_arguments()
    with pytest.raises(Refused, match="recipe"):
        build_request(pack=PACK, route="S", budgets=BUDGETS, **{**arguments, "recipe": recipe})
