"""A generated world's specification: the served schema, its presets, and the one gate.

``GET /worlds/specification`` is the one document a page, an open model drafting for a person and
an API client read of what a world may be made from, and ``POST /worlds/generated`` passes every
request through one gate (``town_recipe``), which refuses a value the schema does not offer by name
with its key, the value and the range, before anything is generated or written. A preset is a point
in the schema. The composer generates at the grammar version a specification names, and reads a
world made under version 3 again under version 3; it keeps a candidate only when a society can
start on it.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import uuid
from types import MappingProxyType

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.grammar.grammars.city.descriptor import CITY_DESCRIPTOR_PATHS
from exulanica.grammar.grammars.city.document import descriptor_sha256
from exulanica.grammar.grammars.specified import REGISTRY
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.composers import GeneratedWorldRefused, composer_module
from exulanica.world.composers import city_grammar_town as town_composer
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import (
    compose_generated_world,
    compose_specified_world,
    generation_receipt,
)
from exulanica.world.society_controls import DEFAULT_BASE_TICK_INTERVAL_MS, SPEEDS
from exulanica.world.society_grounds import society_ground_for_composer
from exulanica.world.world_recipes import (
    CANDIDATES_MAXIMUM,
    CATALOG_DIRECTORY,
    SpecificationRefused,
    load_specification_schemas,
    load_world_recipes,
    specification_document,
    town_recipe,
    world_recipe,
    world_recipes,
)
from exulanica.world.worlds import workspace_worlds

from test_society_made_world import made as imported_made  # noqa: F401
from test_world_objects_api import objects_api as imported_objects_api  # noqa: F401

pytestmark = pytest.mark.postgres


@pytest.fixture(name="objects_api")
def _objects_api_alias(request):
    return request.getfixturevalue("imported_objects_api")


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    """Towns are tried with the catalog's most candidates, as tests/test_generated_worlds.py's are,
    so a rare identity no preset candidate generates is not a refusal a test did not ask for."""
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def test_the_served_specification_states_every_value_its_range_its_reason_and_the_presets(
    objects_api,
):
    """One document states what may be asked for: every value with its words, kind, unit, range
    and reason, fixed ones with their value, every preset as a point inside the ranges, the
    bounds and every refusal by name."""
    answer = objects_api.get("/worlds/specification")
    assert answer.status_code == 200, answer.text
    document = answer.json()
    assert document == json.loads(json.dumps(specification_document()))
    assert document["profile"] == "exulanica.world-specification/v1"
    assert document["grammar"] == {"grammar_id": "city", "grammar_version": 5}
    assert document["schema"]["catalog_version"] == 2
    grammar = REGISTRY.get("city", 5)
    values = {value["key"]: value for value in document["values"]}
    for key, value in values.items():
        assert value["label"] and len(value["reason"].split()) >= 5, key
        for requirement in value["requires"]:
            other = values[requirement["when"]]
            assert other["adjustable"] and other["key"] != key
            assert other["minimum"] <= requirement["from"] <= requirement["to"] <= other["maximum"]
            assert value["minimum"] <= requirement["minimum"] <= requirement["maximum"]
            assert requirement["maximum"] <= value["maximum"]
            assert len(requirement["reason"].split()) >= 5
        if key in ("grammar_id", "grammar_version"):
            assert value["adjustable"] is False
            continue
        declared = grammar.parameters.get(key)
        assert (value["kind"], value["unit"]) == (declared.kind, declared.unit), key
        if value["kind"] == "integer":
            assert declared.minimum <= value["minimum"] <= value["maximum"] <= declared.maximum
            assert (value["maximum"] - value["minimum"]) % value["step"] == 0
        else:
            assert set(value["choices"]) <= set(declared.options)
        assert value["adjustable"] == ("value" not in value), key
    adjustable = {key for key, value in values.items() if value["adjustable"]}
    shares = {
        spec.name
        for spec in grammar.parameters.parameters
        if spec.unit == "permille" and spec.when_unset == "draw"
    }
    assert len(shares) == 13
    assert adjustable == {
        "city_extent_x_mm",
        "block_length_mm",
        "storey_band_low",
        "storey_band_high",
        "high_street_count",
        "cross_street_hierarchy",
        *shares,
    }
    # A choice is served with each key's words from the catalog its vocabulary names.
    cross = values["cross_street_hierarchy"]
    assert cross["choices"] == ["local_street", "narrow_street"]
    assert cross["choice_labels"] == ["Local street", "Narrow street"]
    assert "choice_labels" not in values["driving_side"]
    # One corner radius for the whole town, fixed with its measurement.
    assert (values["corner_radius_mm"]["adjustable"], values["corner_radius_mm"]["value"]) == (
        False,
        4000,
    )
    assert [preset["key"] for preset in document["presets"]] == ["small_town", "market_town"]
    for preset in document["presets"]:
        assert set(preset["values"]) == adjustable
        for key, chosen in preset["values"].items():
            value = values[key]
            if value["kind"] == "choice":
                assert chosen in value["choices"]
                continue
            assert value["minimum"] <= chosen <= value["maximum"]
            assert (chosen - value["minimum"]) % value["step"] == 0
    assert {row["code"] for row in document["refusals"]} == {
        "unknown_world_recipe",
        "specification_value_unknown",
        "specification_value_out_of_range",
        "specification_values_disagree",
        "generated_world_refused",
        "tile_budget_reached",
        "world_limit_reached",
    }
    # A town three tiles long takes cross streets at least 130 m apart; a town two tiles long takes
    # every distance offered, the rule version 1 of the schema states for it being gone.
    [three_tiles] = values["block_length_mm"]["requires"]
    assert (three_tiles["when"], three_tiles["from"], three_tiles["minimum"]) == (
        "city_extent_x_mm",
        384_000,
        130_000,
    )
    [people] = document["bounds"]["people"]
    assert people["most"] == society_ground_for_composer("city-grammar-town").population
    # The count policy's own figures, a person's and a guest's, whatever a deployment states.
    bounds = document["bounds"]
    assert (
        bounds["generated_worlds_per_workspace"],
        bounds["generated_worlds_per_guest_workspace"],
        bounds["generated_tiles_a_day"],
        bounds["generated_tiles_a_day_for_a_guest"],
    ) == (24, 6, 48, 12)
    # The tick budget is a share of the fastest wait between ticks at play, with its measurement.
    tick = document["bounds"]["tick"]
    assert tick["budget_ms_p95"] == tick["fastest_interval_ms"] // tick["share_divisor"]
    assert tick["fastest_interval_ms"] == DEFAULT_BASE_TICK_INTERVAL_MS // max(SPEEDS)
    assert "95th percentile" in tick["reason"]


def test_a_value_the_schema_does_not_offer_is_refused_by_name_and_nothing_is_written(
    objects_api, repository
):
    before = workspace_worlds(repository.connection, repository.workspace_id)
    cases = [
        ({"block_length_mm": 150_000}, "specification_value_out_of_range", "90000 to 140000"),
        ({"block_length_mm": 95_000}, "specification_value_out_of_range", "in steps of 10000"),
        ({"block_length_mm": "90000"}, "specification_value_out_of_range", 'is "90000"'),
        ({"storey_band_high": 4.5}, "specification_value_out_of_range", "4 to 5"),
        ({"city_extent_x_mm": 512_000}, "specification_value_out_of_range", "256000 to 384000"),
        ({"block_depth_mm": 52_000}, "specification_value_unknown", "fixes it at 56000"),
        ({"driving_side": "left"}, "specification_value_unknown", 'fixes it at "right"'),
        ({"grammar_version": 3}, "specification_value_unknown", "states no value"),
        ({"lamp_spacing_mm": 20_000}, "specification_value_unknown", "states no value"),
        ({"high_street_count": 4}, "specification_value_out_of_range", "1 to 3 count"),
        ({"typology_weight_rowhouse_permille": 1_025}, "specification_value_out_of_range", "0 to"),
        (
            {"typology_weight_rowhouse_permille": 25},
            "specification_value_out_of_range",
            "steps of 50",
        ),
        (
            {"cross_street_hierarchy": "avenue"},
            "specification_value_out_of_range",
            "one of local_street, narrow_street",
        ),
        ({"corner_radius_mm": 6_000}, "specification_value_unknown", "fixes it at 4000"),
    ]
    for values, code, words in cases:
        answer = objects_api.post(
            "/worlds/generated", {"recipe": "small_town", "title": "Refused", "values": values}
        )
        assert answer.status_code == 422, (values, answer.text)
        body = answer.json()
        [key] = values
        assert (body["code"], body["key"], body["value"]) == (code, key, values[key]), values
        assert words in body["detail"], (values, body["detail"])
        if code == "specification_value_out_of_range":
            assert set(body["range"]) in ({"minimum", "maximum", "step"}, {"choices"})
    # Two values the schema does not admit together: the small town's 90 m blocks with a town three
    # tiles long. Named by both keys, before anything is generated.
    answer = objects_api.post(
        "/worlds/generated",
        {"recipe": "small_town", "title": "Refused", "values": {"city_extent_x_mm": 384_000}},
    )
    assert answer.status_code == 422, answer.text
    body = answer.json()
    assert (body["code"], body["key"], body["value"]) == (
        "specification_values_disagree",
        "block_length_mm",
        90_000,
    )
    assert body["with"] == {"key": "city_extent_x_mm", "value": 384_000}
    assert body["range"] == {"minimum": 130_000, "maximum": 140_000, "step": 10_000}
    assert "with that value this schema admits 130000 to 140000 mm" in body["detail"]
    assert workspace_worlds(repository.connection, repository.workspace_id) == before


def test_a_preset_with_values_makes_a_town_of_those_values_and_its_own_seed(
    objects_api, repository
):
    answer = objects_api.post(
        "/worlds/generated",
        {"recipe": "small_town", "title": "Longer blocks", "values": {"block_length_mm": 120_000}},
    )
    assert answer.status_code == 201, answer.text
    entry = answer.json()
    _, receipt = generation_receipt(
        repository.connection,
        repository.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["source_snapshot_id"]),
    )
    bound = receipt["specification"]["bindings"][0]["values"]
    assert bound["block_length_mm"] == 120_000
    assert bound["city_extent_x_mm"] == world_recipe("small_town").values["city_extent_x_mm"]
    assert receipt["grammar"]["grammar_version"] == 5
    assert receipt["recipe"]["values"]["block_length_mm"] == 120_000
    # The values are part of what the seed is drawn from: the same identity with the preset's own
    # values is another world.
    asked = compose_specified_world("small_town", {"block_length_mm": 120_000}, "world:generated:v")
    plain = compose_specified_world("small_town", None, "world:generated:v")
    assert asked.receipt["seed"] != plain.receipt["seed"]


def test_the_gate_and_the_composition_entry_are_pure_and_refuse_as_the_route_does():
    recipe = town_recipe("market_town", {"storey_band_low": 3})
    assert dict(recipe.values or {})["storey_band_low"] == 3
    assert recipe.tiles == ((0, 0), (1, 0), (2, 0))
    with pytest.raises(SpecificationRefused) as refused:
        town_recipe("market_town", {"storey_band_low": 4})
    assert (refused.value.code, refused.value.key, refused.value.value) == (
        "specification_value_out_of_range",
        "storey_band_low",
        4,
    )
    assert refused.value.document()["range"] == {"minimum": 2, "maximum": 3, "step": 1}
    with pytest.raises(recipe_catalog.UnknownWorldRecipe):
        town_recipe("a_preset_nobody_states")
    with pytest.raises(SpecificationRefused) as together:
        town_recipe("market_town", {"block_length_mm": 120_000})
    assert (together.value.code, together.value.other) == (
        "specification_values_disagree",
        ("city_extent_x_mm", 384_000),
    )
    assert town_recipe("small_town", {"city_extent_x_mm": 384_000, "block_length_mm": 130_000})
    # Two tiles with blocks 130 or 140 m apart: version 2 of the schema admits them, since the
    # tessellator draws a straight join without the kerb it runs on into; version 1 still refuses.
    for length in (130_000, 140_000):
        assert (
            town_recipe("small_town", {"block_length_mm": length}).specification["grammar_version"]
            == 5
        )
    version_1 = load_specification_schemas()["world-specification.v1"]
    with pytest.raises(SpecificationRefused) as two_tiles:
        version_1.check_together(
            {"city_extent_x_mm": 256_000, "block_length_mm": 130_000, "storey_band_low": 2}
        )
    assert (two_tiles.value.code, two_tiles.value.other) == (
        "specification_values_disagree",
        ("city_extent_x_mm", 256_000),
    )
    assert two_tiles.value.document()["range"] == {
        "minimum": 90_000,
        "maximum": 120_000,
        "step": 10_000,
    }


def test_a_town_is_read_again_at_the_grammar_version_its_receipt_records():
    """Each receipt is read at the grammar version it records, with that version's catalogs and
    descriptor, so a version 3 or version 4 town regenerates the records it recorded after version
    5 is the one offered; a receipt naming a version this server does not generate is refused by
    name."""
    [version_1] = [r for r in load_world_recipes(catalog_version=1) if r.key == "small_town"]
    [version_2] = [r for r in load_world_recipes(catalog_version=2) if r.key == "small_town"]
    old = compose_generated_world(
        dataclasses.replace(version_1, candidates=CANDIDATES_MAXIMUM), "world:generated:old"
    )
    middle = compose_generated_world(
        dataclasses.replace(version_2, candidates=CANDIDATES_MAXIMUM), "world:generated:middle"
    )
    new = compose_generated_world(world_recipe("small_town"), "world:generated:new")
    module = composer_module(town_composer.COMPOSER_KEY, 1)
    for composed, version in ((old, 3), (middle, 4), (new, 5)):
        grammar = composed.receipt["grammar"]
        assert grammar["grammar_version"] == version
        assert grammar["descriptor_sha256"] == descriptor_sha256(CITY_DESCRIPTOR_PATHS[version])
        # Generated again and held to the receipt's output digest inside records().
        assert module.records(composed.receipt) == composed.records
        documents = module.tile_documents(composed.receipt, composed.records)
        stated = {one.grammar_version for document in documents for one in document.grammars}
        assert stated == {version}
    elsewhere = {
        **new.receipt,
        "grammar": {**new.receipt["grammar"], "grammar_version": 6},
    }
    with pytest.raises(InvalidStructuralData, match="generated_world_grammar_changed"):
        module.records(elsewhere)


def test_a_candidate_whose_homes_no_society_can_hold_is_not_kept(monkeypatch):
    """A town is made only if a society can start on it: its homes hold someone and no more people
    than its ground holds. A candidate whose homes hold more is refused by that name, and a world
    none of whose candidates fits is refused with every candidate's refusal."""
    stated = society_ground_for_composer("city-grammar-town")
    monkeypatch.setattr(
        town_composer,
        "society_ground_for_composer",
        lambda key: dataclasses.replace(stated, population=3),
    )
    with pytest.raises(GeneratedWorldRefused) as refused:
        compose_specified_world("small_town", None, "world:generated:crowded")
    assert len(refused.value.refusals) == CANDIDATES_MAXIMUM
    # Every candidate the grammar generated is refused for its people; any other was refused by
    # the grammar itself first.
    crowded = [
        str(r["refusal"])
        for r in refused.value.refusals
        if str(r["refusal"]).startswith("population_over_tick_budget:")
    ]
    assert crowded and all("at most 3" in refusal for refusal in crowded)
    assert all(
        str(r["refusal"]).startswith(("population_over_tick_budget:", "InvalidRecordError:"))
        for r in refused.value.refusals
    )
    monkeypatch.setattr(town_composer, "place_residents", lambda place: 0)
    with pytest.raises(GeneratedWorldRefused) as empty:
        compose_specified_world("small_town", None, "world:generated:empty")
    assert any(
        str(r["refusal"]).startswith("world_holds_no_residents:") for r in empty.value.refusals
    )
    assert all(
        str(r["refusal"]).startswith(("world_holds_no_residents:", "InvalidRecordError:"))
        for r in empty.value.refusals
    )


def test_a_schema_is_read_only_when_its_ranges_lie_inside_the_grammar_and_presets_inside_it(
    tmp_path,
):
    """A range wider than the grammar declares, a key the grammar does not declare, and a preset
    value outside its schema's range are each refused when the catalog is read."""

    def directory(change) -> object:
        target = tmp_path / str(uuid.uuid4())
        shutil.copytree(CATALOG_DIRECTORY, target)
        change(target)
        return target

    def edit(name: str, key: str, field: str, value: object):
        def change(target):
            path = target / name
            document = json.loads(path.read_text())
            for entry in document["entries"]:
                if entry["key"] == key:
                    entry[field] = value
            path.write_text(json.dumps(document))

        return change

    assert load_specification_schemas(directory(lambda target: None))
    with pytest.raises(CatalogError, match="is a number from 60000 to 250000"):
        load_specification_schemas(
            directory(edit("world-specification.v1.json", "block_length_mm", "maximum", 300_000))
        )
    with pytest.raises(CatalogError, match="is a choice of"):
        load_specification_schemas(
            directory(edit("world-specification.v1.json", "driving_side", "choices", ["middle"]))
        )
    with pytest.raises(CatalogError, match="not a declared parameter"):
        load_specification_schemas(
            directory(edit("world-specification.v1.json", "block_length_mm", "key", "block_mm"))
        )
    requirement = {
        "when": "city_extent_x_mm",
        "from": 384_000,
        "to": 384_000,
        "minimum": 130_000,
        "maximum": 140_000,
        "reason": "Measured: three tiles need long blocks.",
    }
    for changed, words in (
        ({"when": "block_depth_mm"}, "which is no other adjustable value"),
        ({"from": 300_000, "to": 300_000}, "spans city_extent_x_mm outside its range or step"),
        ({"minimum": 125_000}, "narrows block_length_mm outside its range or step"),
    ):
        with pytest.raises(CatalogError, match=words):
            load_specification_schemas(
                directory(
                    edit(
                        "world-specification.v1.json",
                        "block_length_mm",
                        "requires",
                        [{**requirement, **changed}],
                    )
                )
            )
    with pytest.raises(CatalogError, match=r"two requirements in force together when .* 384000"):
        load_specification_schemas(
            directory(
                edit(
                    "world-specification.v1.json",
                    "block_length_mm",
                    "requires",
                    [requirement, {**requirement, "minimum": 140_000}],
                )
            )
        )
    with pytest.raises(CatalogError, match="preset small_town: block_length_mm"):
        load_world_recipes(
            directory(
                edit(
                    f"world-recipe.v{recipe_catalog.CATALOG_VERSION}.json",
                    "small_town",
                    "values",
                    {
                        "city_extent_x_mm": 256_000,
                        "block_length_mm": 150_000,
                        "storey_band_low": 2,
                        "storey_band_high": 4,
                    },
                )
            )
        )
