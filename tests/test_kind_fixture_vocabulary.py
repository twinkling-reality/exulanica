"""Fixture defaults are declared content, with stated dimensions and old replay authoritative."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from exulanica.grammar.errors import CatalogError
from exulanica.selection.kind_brief import compile_brief
from exulanica.world.composers import site_plan
from exulanica.world.kinds import thing_leaves
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.thing_leaves import CATALOG_PATH, load_thing_leaves

from kind_briefs import PROVENANCE, brief_of, fixture_kind, held_to_form


def _with_fixture(role: str, source: str) -> dict:
    brief = held_to_form(brief_of(fixture_kind("cafe")))
    fixture = copy.deepcopy(brief["zones"][0]["fixtures"][0])
    fixture.update(
        label="requested thing",
        look=role,
        size_source=source,
        width_mm=3000,
        depth_mm=1500,
        height_mm=1500,
        roles=["decoration"],
        use_role="",
        work=[],
        visit=[],
    )
    brief["zones"][0]["fixtures"] = [fixture]
    return brief


@pytest.mark.parametrize("role", ["fixture.bench", "fixture.well", "vehicle.fishing_boat"])
def test_catalog_defaults_resolve_to_saved_figures_and_are_not_assets(role):
    compiled = compile_brief(_with_fixture(role, "catalog"), provenance=PROVENANCE, size=False)
    part = next(p for p in compiled.document["parts"] if p["label"] == "requested thing")
    assert tuple(part[k] for k in ("width_mm", "depth_mm", "height_mm")) == (
        load_thing_leaves().entries[role].box_mm
    )
    assert part["key"] in compiled.fixture_vocabulary["defaulted_parts"]
    assert "size_source" not in part
    # Saved dimensions are not resolved again against the drafting vocabulary.
    read_kind(compiled.document)


def test_stated_size_and_unknown_leaf_remain_authoritative_and_unlisted_is_counted():
    for role in ("fixture.bench", "fixture.unlisted_instrument"):
        compiled = compile_brief(_with_fixture(role, "stated"), provenance=PROVENANCE, size=False)
        part = next(p for p in compiled.document["parts"] if p["label"] == "requested thing")
        assert (part["width_mm"], part["depth_mm"], part["height_mm"]) == (3000, 1500, 1500)
        assert (part["key"] in compiled.fixture_vocabulary["unlisted_parts"]) == (
            role == "fixture.unlisted_instrument"
        )
        read_kind(compiled.document)


def test_unknown_leaf_cannot_claim_catalog_dimensions():
    with pytest.raises(KindRefused, match="catalog sizing requires") as error:
        compile_brief(
            _with_fixture("fixture.unlisted_instrument", "catalog"),
            provenance=PROVENANCE,
            size=False,
        )
    assert error.value.where.endswith(".size_source")


def test_stated_dimensions_outside_the_profile_are_refused_without_clamping():
    brief = _with_fixture("fixture.bench", "stated")
    brief["zones"][0]["fixtures"][0]["height_mm"] = 50
    compiled = compile_brief(brief, provenance=PROVENANCE, size=False)
    with pytest.raises(KindRefused, match="kind_out_of_bounds"):
        read_kind(compiled.document)


def test_a_saved_kind_replays_without_the_drafting_vocabulary(monkeypatch):
    kind = read_kind(fixture_kind("cafe"))
    world = site_plan.compose_kind(kind, kind.values(kind.presets[0][0]), "world:generated:test")

    def unavailable(*_args, **_kwargs):
        raise AssertionError("saved world consulted the drafting vocabulary")

    monkeypatch.setattr(thing_leaves, "load_thing_leaves", unavailable)
    assert site_plan.records(json.loads(json.dumps(world.receipt))) == world.records
    assert read_kind(dict(kind.document)).sha256 == kind.sha256


@pytest.mark.parametrize(
    "field,value", [("height_mm", 50), ("width_mm", True), ("family", "water")]
)
def test_catalog_cannot_extend_fixture_bounds_or_forms(tmp_path: Path, field, value):
    document = json.loads(CATALOG_PATH.read_text())
    document["entries"][0][field] = value
    path = tmp_path / "thing-leaf.v1.json"
    path.write_text(json.dumps(document))
    with pytest.raises(CatalogError):
        load_thing_leaves(path)
