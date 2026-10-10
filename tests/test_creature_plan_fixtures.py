"""The drafted bodies the page's tests pose are exactly what this server builds.

``scripts/things/creature_plan_fixtures.py`` writes one file a hand-written creature under
``web/packages/atlas-react/test/fixtures/creature-plans/``: its plan, its sketch look, its kind and
where the sketch's container stands each bone. The page's pose tests read them. This module fails
when a committed file is no longer what the script writes (write them again with the script), and
holds the joints to the body builder's own figures, carried into the container's frame by the
things contract's rule and not by the script.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from test_creature_bodies import CREATURES, _built

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/things/creature_plan_fixtures.py"


def _script() -> Any:
    spec = importlib.util.spec_from_file_location("creature_plan_fixtures", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((_script().FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_the_committed_fixtures_are_what_the_script_writes(capsys):
    script = _script()
    # Positive control: there is a file for every hand-written creature, and no other.
    assert sorted(path.stem for path in script.FIXTURES.glob("*.json")) == sorted(CREATURES)
    assert len(CREATURES) == 13
    assert script.main(["--check"]) == 0, capsys.readouterr().out


def test_the_check_fails_on_a_changed_file_a_missing_one_and_a_stray_one(
    tmp_path, monkeypatch, capsys
):
    script = _script()
    copy = tmp_path / "creature-plans"
    shutil.copytree(script.FIXTURES, copy)
    monkeypatch.setattr(script, "FIXTURES", copy)
    monkeypatch.setattr(script, "ROOT", tmp_path)
    assert script.main(["--check"]) == 0
    # One figure moved by a millimetre.
    name = sorted(CREATURES)[0]
    document = json.loads((copy / f"{name}.json").read_text(encoding="utf-8"))
    bone = sorted(document["joints_m"])[0]
    document["joints_m"][bone][1] += 0.001
    (copy / f"{name}.json").write_text(script._text(document), encoding="utf-8")
    capsys.readouterr()
    assert script.main(["--check"]) == 1
    assert f"creature-plans/{name}.json" in capsys.readouterr().out
    # Written again, it passes; then one file gone, and one nobody's recipe writes.
    assert script.main([]) == 0 and script.main(["--check"]) == 0
    (copy / f"{name}.json").unlink()
    assert script.main(["--check"]) == 1
    assert script.main([]) == 0
    (copy / "nobody.json").write_text("{}\n", encoding="utf-8")
    capsys.readouterr()
    assert script.main(["--check"]) == 1
    assert "no recipe writes this file: creature-plans/nobody.json" in capsys.readouterr().out
    # Writing refuses to go on beside a file it did not write, and leaves it there.
    assert script.main([]) == 1 and (copy / "nobody.json").exists()


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_a_fixture_s_joints_are_the_builder_s_in_the_container_s_frame(name):
    """The builder places joints in the slot frame (millimetres, facing +y, left at -x, up +z); a
    container is glTF (metres, +Y up, facing +Z), so a joint at (x, y, z) stands at
    (-x, z, y) / 1000 (docs/things-contract.md). A container stores 32-bit figures, hence the
    tolerance of a hundredth of a millimetre."""
    _recipe, built = _built(name)
    fixture = _fixture(name)
    assert set(fixture["joints_m"]) == set(built.joints)
    assert [bone["name"] for bone in fixture["plan"]["bones"]] == [
        bone["name"] for bone in built.plan["bones"]
    ]
    for bone, (x, y, z) in built.joints.items():
        assert fixture["joints_m"][bone] == pytest.approx(
            [-x / 1000, z / 1000, y / 1000], abs=1e-5
        ), bone


@pytest.mark.parametrize("name", sorted(CREATURES))
def test_a_fixture_s_documents_agree_with_each_other_and_its_recipe(name):
    fixture = _fixture(name)
    recipe = CREATURES[name]["recipe"]
    plan, look, kind = fixture["plan"], fixture["look"], fixture["kind"]
    assert fixture["profile"] == "exulanica.creature-plan-fixture/v1"
    assert kind["body"]["extent_mm"] == recipe["extent_mm"]
    assert kind["body"]["plan"] == f"{plan['key']}/v{plan['version']}"
    assert look["body_plan"] == kind["body"]["plan"]
    assert [ref["look"] for ref in kind["looks"]] == [look["look"]]
    # Every chain names bones of the plan, each bone in at most one chain.
    bones = {bone["name"] for bone in plan["bones"]}
    chained = [bone for limb in plan["limbs"] for bone in limb["bones"]]
    assert set(chained) <= bones and len(chained) == len(set(chained))
