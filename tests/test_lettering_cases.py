"""The shared lettering cases, run against the backend's reader and layout rule.

``web/packages/loom-lettering/test/lettering-cases.json`` is one set of cases two readers run: the
TypeScript one beside it, which tess's expander will use, and this one. Every case is accepted by
both or refused by both for the same one reason, and each refused case has exactly one defect, so
the order a reader checks in cannot change the reason it gives. The file is generated; this test
holds it to its generator, so a rule change that moves a letter has to be regenerated and reviewed
rather than discovered later by the other language.
"""

from __future__ import annotations

import importlib.util
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from exulanica.lettering import (
    CATALOG_REASONS,
    LAYOUT_REASONS,
    LetteringRefused,
    glyph_parts_mm,
    layout_sign,
    read_glyph_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
CASE_DIRECTORY = ROOT / "web" / "packages" / "loom-lettering" / "test"
CASES = json.loads((CASE_DIRECTORY / "lettering-cases.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _generator():
    spec = importlib.util.spec_from_file_location(
        "generate_lettering_cases", ROOT / "scripts" / "generate_lettering_cases.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@lru_cache(maxsize=8)
def _catalog(name: str):
    return read_glyph_catalog((CASE_DIRECTORY / CASES["catalogs"][name]).read_bytes())


@pytest.mark.parametrize("case", CASES["catalog_cases"], ids=lambda case: case["name"])
def test_a_catalog_case(case: dict[str, Any]):
    raw = _generator().catalog_bytes(case, CASES["catalogs"])
    reason = None
    try:
        read_glyph_catalog(raw)
    except LetteringRefused as refused:
        reason = refused.reason
    assert reason == case["reason"]


@pytest.mark.parametrize("case", CASES["layout_cases"], ids=lambda case: case["name"])
def test_a_layout_case(case: dict[str, Any]):
    try:
        layout = layout_sign(
            _catalog(case["catalog"]),
            case["text"],
            cap_height_mm=case["cap_height_mm"],
            tracking_mm=case["tracking_mm"],
            alignment=case["alignment"],
            box_width_mm=case["box_width_mm"],
            box_height_mm=case["box_height_mm"],
        )
    except LetteringRefused as refused:
        assert refused.reason == case["reason"]
        return
    assert case["reason"] is None
    assert [
        [placement.index, placement.character, placement.x_mm, placement.baseline_mm]
        for placement in layout.placements
    ] == case["layout"]["placements"]
    assert [
        layout.ink.left_mm,
        layout.ink.bottom_mm,
        layout.ink.right_mm,
        layout.ink.top_mm,
    ] == case["layout"]["ink"]


@pytest.mark.parametrize("case", CASES["glyph_cases"], ids=lambda case: case["name"])
def test_a_glyph_case(case: dict[str, Any]):
    parts = glyph_parts_mm(_catalog(case["catalog"]), case["character"], case["cap_height_mm"])
    flat = [
        {
            "outer": [value for point in outer for value in point],
            "holes": [[value for point in hole for value in point] for hole in holes],
        }
        for outer, holes in parts
    ]
    assert flat == case["parts"]


def test_the_cases_reach_every_refusal_reason_and_accept_something():
    catalog_reasons = {case["reason"] for case in CASES["catalog_cases"]}
    layout_reasons = {case["reason"] for case in CASES["layout_cases"]}
    assert catalog_reasons == {None, *CATALOG_REASONS}
    assert layout_reasons == {None, *LAYOUT_REASONS}


def test_the_case_file_and_its_test_catalog_are_what_the_generator_writes():
    text, boxes = _generator().render()
    committed = (CASE_DIRECTORY / "lettering-cases.json").read_text(encoding="utf-8")
    assert committed == text, (
        "the shared cases are out of date. Run: uv run python scripts/generate_lettering_cases.py"
    )
    assert (CASE_DIRECTORY / "cases" / "boxes.v1.json").read_bytes() == boxes
