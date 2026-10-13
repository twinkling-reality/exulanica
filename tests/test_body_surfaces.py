"""Authored original body assets bind to exact plans and stay within declared mesh bounds."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from exulanica.things.bodies import build_body, read_body_recipe
from exulanica.things.body_surfaces import BodySurfaceRefused, author_surface_look
from exulanica.things.run_forms import run_form
from exulanica.world.static_glb import inspect_static_glb
from scripts.things.author_surfaces import assemble_authored

ASSETS = Path(__file__).resolve().parents[1] / "assets/things/canopy-strider"


def _source():
    return json.loads((ASSETS / "authoring.json").read_text())


@pytest.mark.parametrize(
    ("source", "folder"),
    [("authoring.json", "porcelain-v3"), ("variant-authoring.json", "celadon-v3")],
)
def test_original_variants_rebuild_exact_assets_and_carry_authored_provenance(source, folder):
    creature, receipt = assemble_authored(json.loads((ASSETS / source).read_text()))
    assert creature.sketch_container == (ASSETS / folder / "body.glb").read_bytes()
    assert receipt == json.loads((ASSETS / folder / "receipt.json").read_text())
    inspect_static_glb(creature.sketch_container)
    assert receipt["container_sha256"] == hashlib.sha256(creature.sketch_container).hexdigest()
    assert receipt["rest_bounds_mm"][0][2] >= 0
    assert receipt["triangles"] <= 20_000
    assert creature.sketch.document["origin"]["class"] == "authored"
    assert creature.sketch.document["origin"]["lineage"]["receipts"] == []
    assert receipt["surface_sha256"] in creature.sketch.document["origin"]["lineage"]["ingredients"]
    assert creature.kind.document["body"]["plan_sha256"] == creature.plan.sha256
    assert creature.kind.looks[0] == creature.sketch.reference()
    form = run_form(creature.kind, creature.plan, read_body_recipe(dict(creature.recipe)))
    assert form["moves"] == []
    assert {a["key"] for a in form["abilities"]} == {"wait", "say"}


@pytest.mark.parametrize("field", ["plan_sha256", "recipe_sha256"])
def test_another_body_or_recipe_cannot_use_the_surface(field):
    source = _source()
    source["surface"][field] = "f" * 64
    with pytest.raises(BodySurfaceRefused, match="pins"):
        assemble_authored(source)


def test_unknown_attachment_and_surface_fields_refuse():
    source = _source()
    source["surface"]["parts"][0]["bone"] = "absent"
    with pytest.raises(BodySurfaceRefused, match="attachment"):
        assemble_authored(source)
    source = _source()
    source["surface"]["parts"][0]["shape"]["animation"] = "swimming"
    with pytest.raises(BodySurfaceRefused, match="exactly"):
        assemble_authored(source)


def test_mesh_cannot_extend_outside_footprint_or_under_ground():
    for centre in ([50_000, 0, 0], [0, 0, -10_000]):
        source = _source()
        source["surface"]["parts"][0]["shape"]["centre_mm"] = centre
        with pytest.raises(BodySurfaceRefused, match="extent"):
            assemble_authored(source)


def test_mesh_budget_refuses_before_container_allocation():
    source = _source()
    large = copy.deepcopy(source["surface"]["parts"][1])
    source["surface"]["parts"] = [large] * 20
    with pytest.raises(BodySurfaceRefused, match="triangles"):
        assemble_authored(source)


def test_degenerate_tube_and_boolean_shape_figures_refuse():
    source = _source()
    tube = next(p for p in source["surface"]["parts"] if p["shape"]["kind"] == "tube")
    tube["shape"]["sections"][1]["centre_mm"] = tube["shape"]["sections"][0]["centre_mm"]
    with pytest.raises(BodySurfaceRefused, match="zero direction"):
        assemble_authored(source)
    source = _source()
    source["surface"]["parts"][0]["shape"]["segments"] = True
    with pytest.raises(BodySurfaceRefused, match="whole number"):
        assemble_authored(source)


def test_surface_cannot_use_forged_rest_joints_with_a_valid_plan():
    source = _source()
    creature, _ = assemble_authored(source)
    recipe = read_body_recipe(source["recipe"])
    built = build_body(recipe, **source["body"], origin=creature.plan_document["origin"])
    joints = dict(built.joints)
    first = next(iter(joints))
    joints[first] = (joints[first][0] + 1, *joints[first][1:])
    forged = dataclasses.replace(built, joints=joints)
    with pytest.raises(BodySurfaceRefused, match="rest joints"):
        author_surface_look(
            source["surface"], forged, recipe, **source["look"], origin=source["origin"]
        )
