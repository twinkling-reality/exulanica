"""Cross-language and safety contracts for the reviewed world-style registry."""

from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest
from exulanica.world import STYLE_REGISTRY, InvalidStyleData, StyleReference, StyleRegistry

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "exulanica" / "world" / "style-registry.v1.json"
RECIPES_TS = ROOT / "web" / "packages" / "presentation" / "src" / "world-style-recipes.ts"
FRONTEND_RECIPE_COMMIT = "55b123627314d328fba3850eb607d8a7682a8cad"
FRONTEND_CAPABILITIES = {
    "world.vitality",
    "material.transmission",
    "relationships.energy",
    "detail.ecology",
    "atmosphere.softness",
    "detail.contours",
    "material.technical-contrast",
    "surface.finish",
    "motion.tempo",
    "interface.hue",
    "interface.warmth",
    "interface.depth",
    "interface.light",
}
FRONTEND_MODULES = {
    "source-light-v1": {"interface.hue", "interface.warmth", "interface.depth", "interface.light"},
    "aeroheart-optics-v1": {
        "world.vitality",
        "material.transmission",
        "relationships.energy",
        "detail.ecology",
        "atmosphere.softness",
    },
    "registered-surface-v1": {"surface.finish"},
    "bounded-tempo-v1": {"motion.tempo"},
    "survey-relief-response-v1": {"detail.contours", "material.technical-contrast"},
}


def registry_document():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def test_the_backend_adapter_is_pinned_to_the_reviewed_frontend_recipe_contract():
    # These exact identities are the renderer-neutral contract pinned to
    # FRONTEND_RECIPE_COMMIT, not copied renderer code.
    assert len(FRONTEND_RECIPE_COMMIT) == 40
    assert STYLE_REGISTRY.frontend_contract_commit == FRONTEND_RECIPE_COMMIT
    assert set(STYLE_REGISTRY.capabilities) == FRONTEND_CAPABILITIES
    assert {
        module_id: set(definition.capabilities)
        for module_id, definition in STYLE_REGISTRY.modules.items()
    } == FRONTEND_MODULES

    catalog = STYLE_REGISTRY.catalog()
    assert catalog["schemaVersion"] == 1
    assert catalog["contractSource"] == {"frontendCommit": FRONTEND_RECIPE_COMMIT}
    assert catalog["defaultProfile"]["profileId"] == "origin-landscape"
    aeroheart = next(
        value for value in catalog["profiles"] if value["profileId"] == "origin-landscape"
    )
    assert aeroheart["recipeBinding"] == {
        "schemaVersion": 1,
        "frontendCommit": FRONTEND_RECIPE_COMMIT,
        "availability": "product",
        "origin": "authored",
        "profileId": "origin-landscape",
        "profileVersion": 1,
        "modules": [
            "aeroheart-optics-v1",
            "registered-surface-v1",
            "bounded-tempo-v1",
            "source-light-v1",
        ],
        "capabilityMapping": {
            "source-hue": "interface.hue",
            "source-warmth": "interface.warmth",
            "source-depth": "interface.depth",
            "source-light": "interface.light",
            "vitality": "world.vitality",
            "glass": "material.transmission",
            "relationship-energy": "relationships.energy",
            "garden-density": "detail.ecology",
            "horizon-softness": "atmosphere.softness",
            "surface-finish": "surface.finish",
            "world-tempo": "motion.tempo",
        },
    }
    finish = next(value for value in aeroheart["controls"] if value["key"] == "surface-finish")
    assert finish["options"] == [
        {"value": "source-paper", "label": "Source paper"},
        {"value": "clear-lens", "label": "Clear lens"},
    ]


def test_the_backend_registry_matches_the_committed_world_profile_versions():
    source = RECIPES_TS.read_text(encoding="utf-8")
    declared_ids = set(re.findall(r"profileId: '([^']+)'", source))
    assert declared_ids == {profile_id for profile_id, _version in STYLE_REGISTRY.profiles}
    assert {version for _profile_id, version in STYLE_REGISTRY.profiles} == {1}


def test_unknown_parameters_and_executable_payload_channels_are_not_style_data():
    for parameters in (
        {"css": "body { display: none }"},
        {"markup": "<script>alert(1)</script>"},
        {"shader": "void main() {}"},
        {"texture-url": "https://example.invalid/texture.png"},
        {"vitality": "url(https://example.invalid/a.png)"},
    ):
        with pytest.raises(InvalidStyleData):
            STYLE_REGISTRY.validate_reference(StyleReference("origin-landscape", 1, parameters))


def test_only_registered_capabilities_can_enter_a_profile_manifest():
    document = registry_document()
    document["profiles"][0]["controls"].append(
        {
            "key": "future-magic",
            "capability": "future.unknown",
            "kind": "range",
            "group": "world",
            "label": "Future magic",
            "description": "Not reviewed.",
            "min": 0,
            "max": 1,
            "step": 0.1,
            "default_value": 0.5,
        }
    )
    with pytest.raises(ValueError, match="unregistered"):
        StyleRegistry(document)


def test_unknown_modules_and_unmatched_module_capabilities_fail_closed():
    document = registry_document()
    document["profiles"][0]["recipe"]["modules"].append("not-reviewed-v1")
    with pytest.raises(ValueError, match="unknown world style module"):
        StyleRegistry(document)

    document = registry_document()
    document["profiles"][0]["recipe"]["modules"].remove("bounded-tempo-v1")
    with pytest.raises(ValueError, match="capability binding mismatch"):
        StyleRegistry(document)

    document = registry_document()
    duplicate = copy.deepcopy(document["profiles"][0]["controls"][0])
    duplicate["key"] = "second-vitality"
    document["profiles"][0]["controls"].append(duplicate)
    with pytest.raises(ValueError, match="invalid or unregistered"):
        StyleRegistry(document)


def test_unknown_profile_versions_never_reinterpret_parameters_against_version_one():
    with pytest.raises(InvalidStyleData, match="unknown world profile"):
        STYLE_REGISTRY.validate_reference(StyleReference("origin-landscape", 2, {"vitality": 0.5}))


@pytest.mark.parametrize("status", ["removed", "unsupported"])
def test_removed_and_unsupported_profiles_have_one_deterministic_fallback(status):
    document = registry_document()
    retired = copy.deepcopy(document["profiles"][1])
    retired.update(
        {
            "profile_id": "retired-study",
            "display_name": "Retired study",
            "description": "A profile retained only so history resolves.",
            "status": status,
            "fallback": {"profile_id": "origin-landscape", "profile_version": 1},
        }
    )
    document["profiles"].append(retired)
    registry = StyleRegistry(document)
    resolved, warnings = registry.resolve_reference(StyleReference("retired-study", 1, {}))
    assert resolved == registry.default_reference
    assert len(warnings) == 1
    assert status in warnings[0]


def test_an_unknown_historical_profile_falls_back_without_mutating_the_requested_value():
    requested = StyleReference("not-installed-anymore", 7, {"unknown": True})
    resolved, warnings = STYLE_REGISTRY.resolve_reference(requested)
    assert requested.profile_id == "not-installed-anymore"
    assert resolved == STYLE_REGISTRY.default_reference
    assert warnings == ("Unknown world profile not-installed-anymore@7; using origin-landscape@1.",)


def test_the_registry_is_metadata_not_interface_layout_or_renderer_programs():
    document = registry_document()
    serialized = json.dumps(document, sort_keys=True).lower()
    for forbidden in (
        '"css"',
        '"html"',
        '"markup"',
        '"javascript"',
        '"shader"',
        '"layout"',
        '"remote_url"',
        '"texture_url"',
    ):
        assert forbidden not in serialized


def test_a_profile_definition_cannot_widen_its_reviewed_capability_bounds():
    document = copy.deepcopy(registry_document())
    document["profiles"][0]["controls"][0]["max"] = 2
    with pytest.raises(ValueError, match="range definition"):
        StyleRegistry(document)

    document = copy.deepcopy(registry_document())
    document["profiles"][0]["controls"][0]["min"] = -1
    with pytest.raises(ValueError, match="range definition"):
        StyleRegistry(document)
