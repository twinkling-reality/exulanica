"""The style pack reader: the shared cases, canonical bytes, budgets and the context it reads.

The case file is shared with the browser's reader
(``web/packages/atlas-core/test/style-pack.test.ts``), which must reach the same verdict on every
case: the same refusal reason and path, or the same canonical digest. Each refusal's reason and
path were stated by hand when the case was written.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.world import style_packs

ROOT = Path(__file__).resolve().parents[1]
CASES: dict[str, Any] = json.loads(
    (ROOT / "assets/style-packs/manifest-cases.v1.json").read_text(encoding="utf-8")
)


def _context() -> style_packs.StylePackContext:
    families = {
        key: style_packs.LookFamily(**value) for key, value in CASES["context"]["families"].items()
    }
    return style_packs.StylePackContext(
        families=families, texture_sets=frozenset(CASES["context"]["texture_sets"])
    )


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_every_shared_case_has_its_stated_verdict(case: dict[str, Any]) -> None:
    expected = case["expect"]
    if "sha256" in expected:
        manifest = style_packs.read_manifest(case["manifest"], _context())
        assert style_packs.manifest_sha256(manifest) == expected["sha256"]
        return
    with pytest.raises(style_packs.StylePackRefused) as refused:
        style_packs.read_manifest(case["manifest"], _context())
    assert (refused.value.reason, refused.value.path) == (expected["refusal"], expected["path"])


def test_the_cases_cover_a_valid_pack_and_every_refusal_reason() -> None:
    reasons = {case["expect"].get("refusal", "valid") for case in CASES["cases"]}
    assert reasons == {"valid", "shape", "range", "reference", "duplicate", "licence"}


def test_canonical_bytes_are_the_browsers() -> None:
    # Written out by hand: sorted keys, no whitespace, lowercase escapes past ASCII.
    assert (
        style_packs.canonical_json({"b": 1, "a": "é☃", "c": [True, None]})
        == '{"a":"\\u00e9\\u2603","b":1,"c":[true,null]}'
    )
    with pytest.raises(style_packs.StylePackRefused):
        style_packs.canonical_json(0.5)


def test_reading_returns_the_manifest_it_was_given() -> None:
    manifest = CASES["cases"][0]["manifest"]
    assert style_packs.read_manifest(manifest, _context()) == manifest


def test_the_piece_budgets_state_one_triangle_rule_per_family() -> None:
    budgets = style_packs.read_piece_budgets(ROOT)
    assert set(budgets) == {
        "boundary",
        "door",
        "fixture",
        "plant",
        "prop",
        "roof",
        "structure",
        "vehicle",
        "window",
    }
    # A tiled family's limit scales with the piece's width: 200 per metre over 4.5 m is 900.
    assert budgets["boundary"].triangle_limit(4500) == 900
    assert budgets["window"].triangle_limit(4500) == 400


def test_a_budget_with_both_triangle_rules_is_refused(tmp_path: Path) -> None:
    document = json.loads(
        (ROOT / "assets/style-packs/piece-budgets.v1.json").read_text(encoding="utf-8")
    )
    document["families"]["window"]["triangles_per_metre"] = 10
    (tmp_path / "assets/style-packs").mkdir(parents=True)
    # Written as the committed file is, canonical JSON and one newline, so only the rule is broken.
    (tmp_path / "assets/style-packs/piece-budgets.v1.json").write_text(
        style_packs.canonical_json(document) + "\n"
    )
    with pytest.raises(ValueError, match="window: states triangles or triangles per metre"):
        style_packs.read_piece_budgets(tmp_path)


def test_the_context_comes_from_the_family_catalog_and_the_texture_manifest(
    tmp_path: Path,
) -> None:
    catalog = {
        "schema_version": 1,
        "catalog_id": "look-family",
        "catalog_version": 1,
        "entries": [
            {
                "key": "window",
                "fit": "fill",
                "dressing": "module",
                "fill_minimum_permille": 800,
                "fill_maximum_permille": 1250,
                "reason": "A window fills its opening.",
                "licence": {"spdx": "Apache-2.0"},
            }
        ],
    }
    (tmp_path / "assets/catalogs/world-kinds").mkdir(parents=True)
    (tmp_path / "assets/catalogs/world-kinds/look-family.v1.json").write_text(json.dumps(catalog))
    (tmp_path / "assets/textures").mkdir(parents=True)
    (tmp_path / "assets/textures/manifest.json").write_text(
        json.dumps({"profile": "x", "sets": [{"set_id": "cc0.slate"}]})
    )
    context = style_packs.load_context(tmp_path)
    assert context.families["window"] == style_packs.LookFamily("fill", "module", 800, 1250)
    assert context.texture_sets == frozenset({"cc0.slate"})
