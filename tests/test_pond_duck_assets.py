"""Yellow/pink authored duck looks share one admitted body without inventing model provenance, and
the duck walks about by its own routine."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.things.bodies import read_body_recipe
from exulanica.things.run_forms import run_form
from exulanica.world.thing_store import read_admission
from scripts.things.author_surfaces import assemble_authored

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets/things/pond-duck"


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


def test_the_duck_s_routine_walks_it_about_more_than_it_waits():
    yellow, _ = assemble_authored(json.loads((ASSETS / "authoring.json").read_text()))
    pink, _ = assemble_authored(json.loads((ASSETS / "pink-authoring.json").read_text()))
    held = (ASSETS / "yellow-v1/kind.json").read_bytes()
    provenance = json.loads((ASSETS / "provenance.json").read_text())["kind"]
    # The pink authoring states the same kind but for its look; the yellow kind is held at the
    # digest its provenance names, and earlier versions are kept.
    assert {**pink.kind.document, "looks": None} == {**yellow.kind.document, "looks": None}
    assert yellow.kind.sha256 == hashlib.sha256(held).hexdigest()
    assert (provenance["version"], provenance["sha256"]) == (
        yellow.kind.version,
        yellow.kind.sha256,
    )
    assert [old["version"] for old in provenance["superseded"]] == list(
        range(yellow.kind.version - 1, 0, -1)
    )
    abilities = json.loads((ROOT / "assets/catalogs/things/abilities.v1.json").read_text())
    moving = {entry["key"] for entry in abilities["entries"] if entry["needs"]["moves"]}
    weights = json.loads(held)["routine"]["weights"]
    # The routine draws walks (to an open spot, a place to visit or rest, another being) more often
    # than it waits.
    assert sum(weight for key, weight in weights.items() if key in moving) > weights["wait"] > 0
