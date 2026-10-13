"""Yellow/pink authored duck looks share one admitted body without inventing model provenance."""

from __future__ import annotations

import json
from pathlib import Path

from exulanica.things.bodies import read_body_recipe
from exulanica.things.run_forms import run_form
from exulanica.world.thing_store import read_admission
from scripts.things.author_surfaces import assemble_authored

ASSETS = Path(__file__).resolve().parents[1] / "assets/things/pond-duck"


def test_duck_looks_rebuild_same_body_and_pass_existing_admission():
    yellow, first = assemble_authored(json.loads((ASSETS / "authoring.json").read_text()))
    pink, second = assemble_authored(json.loads((ASSETS / "pink-authoring.json").read_text()))
    assert pink.plan.sha256 == yellow.plan.sha256
    assert pink.recipe_sha256 == yellow.recipe_sha256
    assert pink.sketch.sha256 != yellow.sketch.sha256
    for creature, receipt, folder in [(yellow, first, "yellow-v1"), (pink, second, "pink-look-v1")]:
        assert creature.sketch_container == (ASSETS / folder / "body.glb").read_bytes()
        assert receipt == json.loads((ASSETS / folder / "receipt.json").read_text())
        admission = read_admission(
            dict(creature.sketch.document),
            creature.sketch_container,
            plan_of=lambda name: yellow.plan if name == yellow.plan.name else None,
        )
        assert admission.container_profile == "exulanica.static-glb/v1"
        assert creature.sketch.document["origin"]["class"] == "authored"
        assert creature.sketch.document["origin"]["distribution"] == "private"
        assert receipt["model_receipts"] == [] and receipt["rest_bounds_mm"][0][2] == 0
    form = run_form(yellow.kind, yellow.plan, read_body_recipe(dict(yellow.recipe)))
    assert [m["module"] for m in form["moves"]] == ["exulanica-movement/walking/v1"]
    assert 0 < form["moves"][0]["parameters"]["pace_permille"] <= 1000
    assert {a["key"] for a in form["abilities"]} == {
        "wait",
        "stand",
        "talk",
        "rest",
        "visit",
        "follow",
        "say",
    }
