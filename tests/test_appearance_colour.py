"""Declared colour facts use admitted active primitive instances, never recipe names or pixels."""

from copy import deepcopy
from pathlib import Path

import pytest
from exulanica.world.appearance_colour import (
    ColourInterval,
    ColourSwatch,
    colour_facts,
    match_colour,
)
from exulanica.world.static_glb import StaticGlbRefused, inspect_static_glb

from static_glb_builder import CUBE_CORNERS, cube, png

ROOT = Path(__file__).resolve().parents[1]


def _constant(factor=(0.5, 0.0, 1.0, 1.0)):
    source = cube()
    material = source.material(
        pbrMetallicRoughness={
            "baseColorFactor": list(factor),
            "metallicFactor": 0,
        }
    )
    source.document["meshes"][0]["primitives"][0]["material"] = material
    return source


def _facts(source, **kwargs):
    return colour_facts(inspect_static_glb(source.build()), **kwargs)


def test_linear_factors_convert_to_srgb_and_numeric_predicates_are_inclusive():
    source = _constant()
    inspected = inspect_static_glb(source.build())
    before = deepcopy(inspected.document)
    facts = colour_facts(inspected)
    assert facts["coverage"]["state"] == "complete"
    assert facts["primitives"][0]["srgb8"] == [188, 0, 255]
    assert match_colour(facts, ColourSwatch((188, 0, 255)))["state"] == "match"
    assert match_colour(facts, ColourSwatch((187, 0, 255)))["state"] == "no_match"
    assert match_colour(facts, ColourInterval((180, 0, 254), (188, 2, 255)))["state"] == "match"
    assert inspected.document == before
    # The default base factor is white; metallic remains explicitly disabled for this subset.
    del source.document["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]
    assert match_colour(_facts(source), ColourSwatch((255, 255, 255)))["state"] == "match"
    low = _facts(_constant((0.0, 0.0031308, 0.04045, 1.0)))
    assert low["primitives"][0]["srgb8"] == [0, 10, 57]


def test_implicit_metallic_material_is_unknown_instead_of_a_white_colour_claim():
    source = cube()
    facts = _facts(source)
    assert facts["primitives"][0]["material"] is None
    assert facts["primitives"][0]["reasons"] == ["metallic_surface"]
    assert match_colour(facts, ColourSwatch((255, 255, 255)))["state"] == "unknown"


@pytest.mark.parametrize(
    "channels", [(True, 0, 0), (-1, 0, 0), (256, 0, 0), (0.0, 0, 0), (0, 0), [0, 0, 0]]
)
def test_predicate_channels_are_strict_and_bounded(channels):
    with pytest.raises(ValueError):
        ColourSwatch(channels)
    with pytest.raises(ValueError):
        ColourInterval((0, 0, 0), channels)


def test_inverted_ranges_wrong_profiles_and_unadmitted_documents_are_not_accepted():
    with pytest.raises(ValueError):
        ColourInterval((10, 0, 0), (9, 255, 255))
    with pytest.raises(TypeError):
        colour_facts(_constant().document)
    with pytest.raises(ValueError):
        match_colour({"profile": "other"}, ColourSwatch((0, 0, 0)))
    with pytest.raises(TypeError):
        match_colour(_facts(_constant()), "yellow")
    for profile, reason in (
        ("other-container/v1", "unsupported_profile"),
        (None, "container_not_inspected"),
    ):
        facts = colour_facts(None, **({"container_profile": profile} if profile else {}))
        assert facts["coverage"]["reason"] == reason
        assert facts["coverage"]["total"] is None
        assert match_colour(facts, ColourSwatch((0, 0, 0)))["state"] == "unknown"
    unsupported = _constant()
    unsupported.document["extensionsRequired"] = ["KHR_materials_variants"]
    with pytest.raises(StaticGlbRefused):
        inspect_static_glb(unsupported.build())


def test_unused_materials_and_detached_nodes_do_not_create_matches():
    source = _constant((0, 0, 1, 1))
    red = source.material(
        pbrMetallicRoughness={"baseColorFactor": [1, 0, 0, 1], "metallicFactor": 0}
    )
    primitive = deepcopy(source.document["meshes"][0]["primitives"][0])
    primitive["material"] = red
    detached_mesh = source.mesh(primitive)
    detached_node = source.node(mesh=detached_mesh)
    facts = _facts(source)
    assert facts["coverage"]["total"] == 1
    assert match_colour(facts, ColourSwatch((255, 0, 0)))["state"] == "no_match"
    source.scene(0, detached_node)
    added = _facts(source)
    answer = match_colour(added, ColourSwatch((255, 0, 0)))
    assert answer["state"] == "match"
    assert [row["node"] for row in answer["matches"]] == [detached_node]


@pytest.mark.parametrize(
    "effect,reason",
    [
        ("base_texture", "base_colour_texture"),
        ("vertex", "vertex_colour"),
        ("blend", "transparency"),
        ("mask", "transparency"),
        ("alpha", "transparency"),
        ("metal", "metallic_surface"),
        ("emission", "emission"),
        ("normalTexture", "material_map"),
        ("occlusionTexture", "material_map"),
        ("emissiveTexture", "material_map"),
        ("metallicRoughnessTexture", "material_map"),
    ],
)
def test_material_effects_are_unknown_not_false_matches_or_known_negatives(effect, reason):
    source = _constant((1, 0, 0, 1))
    primitive = source.document["meshes"][0]["primitives"][0]
    material = source.document["materials"][0]
    pbr = material["pbrMetallicRoughness"]
    if effect == "vertex":
        primitive["attributes"]["COLOR_0"] = source.vectors(
            [(1, 1, 1, 1)] * len(CUBE_CORNERS), "VEC4"
        )
    elif effect in ("blend", "mask"):
        material["alphaMode"] = effect.upper()
    elif effect == "alpha":
        pbr["baseColorFactor"][3] = 0.5
    elif effect == "metal":
        pbr["metallicFactor"] = 0.1
    elif effect == "emission":
        material["emissiveFactor"] = [0.1, 0, 0]
    else:
        primitive["attributes"]["TEXCOORD_0"] = source.vectors([(0, 0)] * len(CUBE_CORNERS), "VEC2")
        texture = {"index": source.texture(source.image(png(2, 2), "image/png"))}
        if effect == "base_texture":
            pbr["baseColorTexture"] = texture
        elif effect == "metallicRoughnessTexture":
            pbr[effect] = texture
        else:
            material[effect] = texture
    facts = _facts(source)
    assert reason in facts["primitives"][0]["reasons"]
    assert facts["primitives"][0]["srgb8"] is None
    for swatch in ((255, 0, 0), (0, 0, 255)):
        assert match_colour(facts, ColourSwatch(swatch))["state"] == "unknown"


def test_positive_partial_match_does_not_claim_complete_coverage_and_budgets_preserve_unknown():
    source = _constant((0, 1, 0, 1))
    second = deepcopy(source.document["meshes"][0]["primitives"][0])
    second["attributes"]["COLOR_0"] = source.vectors([(1, 1, 1)] * len(CUBE_CORNERS), "VEC3")
    source.document["meshes"][0]["primitives"].append(second)
    facts = _facts(source)
    answer = match_colour(facts, ColourSwatch((0, 255, 0)))
    assert answer["state"] == "match"
    assert answer["coverage"] == {
        "state": "partial",
        "reason": "unsupported_surface",
        "total": 2,
        "examined": 2,
        "known": 1,
        "unknown": 1,
        "unexamined": 0,
    }
    assert match_colour(facts, ColourSwatch((255, 0, 0)))["state"] == "unknown"
    budgeted = _facts(source, maximum_primitives=1)
    assert budgeted["coverage"]["unexamined"] == 1
    assert budgeted["coverage"]["reason"] == "primitive_budget"
    assert match_colour(budgeted, ColourSwatch((0, 255, 0)))["state"] == "match"
    assert match_colour(budgeted, ColourSwatch((255, 0, 0)))["state"] == "unknown"
    for limit in (0, -1, 513, True, 1.5):
        with pytest.raises(ValueError):
            _facts(source, maximum_primitives=limit)


def test_two_retained_compatible_looks_change_facts_without_reading_recipe_words():
    base = ROOT / "assets/things/pond-duck"
    before = {str(path): path.read_bytes() for path in base.rglob("*") if path.is_file()}
    first = colour_facts(inspect_static_glb((base / "yellow-v1/body.glb").read_bytes()))
    second = colour_facts(inspect_static_glb((base / "pink-look-v1/body.glb").read_bytes()))
    # Numeric material swatches, not semantic labels or a production rule about this asset.
    a, b = ColourSwatch((242, 200, 74)), ColourSwatch((211, 145, 212))
    assert (match_colour(first, a)["state"], match_colour(second, a)["state"]) == (
        "match",
        "no_match",
    )
    assert (match_colour(first, b)["state"], match_colour(second, b)["state"]) == (
        "no_match",
        "match",
    )
    assert first["coverage"]["state"] == second["coverage"]["state"] == "complete"
    assert before == {str(path): path.read_bytes() for path in base.rglob("*") if path.is_file()}
