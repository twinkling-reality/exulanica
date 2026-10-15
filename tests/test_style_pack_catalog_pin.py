"""Appearance catalog opt-in preserves old identities and cannot reinterpret a base pack."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from exulanica.world import style_packs
from exulanica.world.style_pack_admission import StylePackAdmissionRefused, admit
from exulanica.world.world_settings import resolve_chain
from exulanica_pieces.budgets import read_budgets

from style_pack_upload_support import upload

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = style_packs.load_context(ROOT)
BUDGETS = read_budgets(ROOT)
CASES = json.loads((ROOT / "assets/style-packs/manifest-cases.v1.json").read_bytes())
PIN = {"version": 2, "sha256": CONTEXT.family_catalogs[2].sha256}
SHARED = json.loads((ROOT / "assets/style-packs/catalog-pin-cases.v1.json").read_bytes())


@pytest.mark.parametrize("case", SHARED["cases"], ids=lambda case: case["name"])
def test_shared_pin_cases_have_the_same_browser_verdict(case):
    raw = SHARED["context"]
    context = style_packs.StylePackContext(
        families={key: style_packs.LookFamily(**value) for key, value in raw["families"].items()},
        texture_sets=frozenset(raw["texture_sets"]),
        family_catalogs={
            int(version): style_packs.LookFamilyCatalog(
                catalog["sha256"],
                {
                    key: style_packs.LookFamily(**value)
                    for key, value in catalog["families"].items()
                },
            )
            for version, catalog in raw["family_catalogs"].items()
        },
    )
    if "sha256" in case["expect"]:
        read = style_packs.read_manifest(case["manifest"], context)
        assert style_packs.manifest_sha256(read) == case["expect"]["sha256"]
    else:
        with pytest.raises(style_packs.StylePackRefused) as refused:
            style_packs.read_manifest(case["manifest"], context)
        assert (refused.value.reason, refused.value.path) == (
            case["expect"]["refusal"],
            case["expect"]["path"],
        )


def test_legacy_manifest_identity_and_catalog_do_not_follow_selected_appearance():
    legacy = copy.deepcopy(CASES["cases"][0]["manifest"])
    pinned = {**legacy, "look_family_catalog": PIN}
    selected = style_packs.context_for_manifest(pinned, CONTEXT)
    assert CONTEXT.families["roof"].fit == "surface"
    assert selected.families["roof"].fit == "contain"
    # Passing a selected context back cannot accidentally opt an old manifest into v2.
    restored = style_packs.context_for_manifest(legacy, selected)
    assert restored.families == CONTEXT.families
    read = style_packs.read_manifest(legacy, selected)
    assert read == legacy
    assert style_packs.manifest_sha256(read) == CASES["cases"][0]["expect"]["sha256"]
    assert style_packs.read_manifest(pinned, CONTEXT) == pinned
    assert style_packs.manifest_sha256(pinned) != style_packs.manifest_sha256(legacy)


def test_retained_v2_pin_is_exact_file_bytes_and_only_changes_roof_fit():
    raw = (ROOT / "assets/catalogs/world-kinds/look-family.v2.json").read_bytes()
    assert PIN["sha256"] == hashlib.sha256(raw).hexdigest()
    first = json.loads((ROOT / "assets/catalogs/world-kinds/look-family.v1.json").read_bytes())
    second = json.loads(raw)
    second["catalog_version"] = 1
    roof = next(entry for entry in first["entries"] if entry["key"] == "roof")
    for entry in second["entries"]:
        if entry["key"] == "roof":
            assert entry["fit"] == "contain"
            entry.update(fit=roof["fit"], reason=roof["reason"])
    assert second == first


def test_retained_v3_is_exact_file_bytes_and_only_lets_a_structure_meet_its_box():
    raw = (ROOT / "assets/catalogs/world-kinds/look-family.v3.json").read_bytes()
    assert CONTEXT.family_catalogs[3].sha256 == hashlib.sha256(raw).hexdigest()
    second = json.loads((ROOT / "assets/catalogs/world-kinds/look-family.v2.json").read_bytes())
    third = json.loads(raw)
    third["catalog_version"] = 2
    structure = next(entry for entry in second["entries"] if entry["key"] == "structure")
    for entry in third["entries"]:
        if entry["key"] == "structure":
            assert (
                entry["fit"],
                entry["fill_minimum_permille"],
                entry["fill_maximum_permille"],
            ) == (
                "fill",
                800,
                1250,
            )
            entry.update(
                {
                    key: structure[key]
                    for key in ("fit", "fill_minimum_permille", "fill_maximum_permille", "reason")
                }
            )
    assert third == second


@pytest.mark.parametrize(
    ("pin", "reason", "path"),
    [
        (None, "shape", "look_family_catalog"),
        ({**PIN, "url": "https://example.test/catalog"}, "shape", "look_family_catalog"),
        ({**PIN, "version": True}, "shape", "look_family_catalog.version"),
        ({**PIN, "version": 999}, "reference", "look_family_catalog.version"),
        ({**PIN, "sha256": "0" * 64}, "reference", "look_family_catalog.sha256"),
        ({"version": 999, "sha256": "invalid"}, "shape", "look_family_catalog.sha256"),
    ],
)
def test_pin_refusal_is_deterministic_and_precedes_role_reading(pin, reason, path):
    manifest = copy.deepcopy(CASES["cases"][0]["manifest"])
    manifest.update(look_family_catalog=pin, surfaces={"unknown.role": {}})
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(manifest, CONTEXT)
    assert (refused.value.reason, refused.value.path) == (reason, path)


@pytest.mark.parametrize("child_pinned,base_pinned", [(True, False), (False, True)])
def test_chain_cannot_reinterpret_inherited_modules(child_pinned, base_pinned):
    base = copy.deepcopy(CASES["cases"][0]["manifest"])
    child = copy.deepcopy(base)
    child["pack_id"] = "maker.child"
    child["base"] = {
        "pack_id": base["pack_id"],
        "version": base["version"],
        "manifest_sha256": "a" * 64,
    }
    if child_pinned:
        child["look_family_catalog"] = PIN
    if base_pinned:
        base["look_family_catalog"] = PIN
    for reader in (
        resolve_chain,
        lambda chain: style_packs.role_offer(chain, "roof.default", CONTEXT),
    ):
        with pytest.raises(style_packs.StylePackRefused) as refused:
            reader([child, base])
        assert (refused.value.reason, refused.value.path) == ("reference", "base")
    child["look_family_catalog"] = base["look_family_catalog"] = PIN
    assert resolve_chain([child, base]).light == base["light"]


@pytest.mark.parametrize("with_resolver", [False, True])
def test_upload_refuses_unchecked_or_mismatched_pinned_base_before_files(with_resolver):
    made = upload()
    base = copy.deepcopy(made.manifest)
    made.manifest["look_family_catalog"] = PIN
    made.manifest["base"] = {
        "pack_id": base["pack_id"],
        "version": base["version"],
        "manifest_sha256": "a" * 64,
    }
    calls = []

    def identity(named):
        calls.append(named)
        return "workspace"

    with pytest.raises(StylePackAdmissionRefused) as refused:
        admit(
            made.declaration_bytes(),
            made.manifest_bytes,
            {},
            context=CONTEXT,
            budgets=BUDGETS.families,
            lod1_share_permille=BUDGETS.lod1_share_permille,
            resolve_base=identity,
            resolve_base_manifest=(lambda _: base) if with_resolver else None,
        )
    assert calls == [made.manifest["base"]]
    assert (refused.value.code, refused.value.path) == ("invalid_style_data", "base")
