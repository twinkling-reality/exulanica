"""A drafted body's pace is read from its own standing height, by the gaits catalog's rule.

``exulanica/things/gaits.py`` gives a body its pace in thousandths of a society's own: the
reference pace times the square root of the ratio of standing heights (the dynamic similarity rule
of animal walking), in integer arithmetic. What each of the thirteen hand-written bodies should
stand at is read here from the sketch the page draws (the plan fixtures' joints), not from the
function under test, and what its pace should be is stated here as the rule itself: the largest
whole number whose square is at most a million times the height over the reference.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.things.bodies import read_body_recipe, stance_mm
from exulanica.things.catalogs import ThingCatalogError
from exulanica.things.gaits import PACE_PERMILLE, Gaits, gaits, load_gaits, pace_permille
from exulanica.things.run_forms import RunFormRefused, read_run_form

from test_creature_bodies import CREATURES
from test_thing_kind_run_forms import _run_form

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "assets/catalogs/things/gaits.v1.json"
PLANS = ROOT / "web/packages/atlas-react/test/fixtures/creature-plans"
WALKING = "exulanica-movement/walking/v1"
NAMES = sorted(CREATURES)
#: The pace of four bodies, by hand: the height of the hips over 900 mm, its square root, in
#: thousandths, rounded down. 1,235 / 900 = 1.37222, root 1.17142; 57 / 900 = 0.06333, root
#: 0.25166; 270 / 900 = 0.3, root 0.54772; 975 / 900 = 1.08333, root 1.04083.
BY_HAND = {"dragon": (1235, 1171), "bat": (57, 251), "spider": (270, 547), "horse": (975, 1040)}


def _entries() -> dict[str, dict[str, Any]]:
    return {entry["key"]: entry for entry in json.loads(CATALOG.read_text())["entries"]}


def _recipe(name: str) -> Any:
    return read_body_recipe(copy.deepcopy(CREATURES[name]["recipe"]))


def _drawn_stance_mm(name: str, role: str) -> int | None:
    """Where the sketch stands the first joint of each chain of ``role``, millimetres above the
    ground (a container's +Y, metres), the lowest of them: read from the fixture the page draws."""
    fixture = json.loads((PLANS / f"{name}.json").read_text())
    heights = [
        fixture["joints_m"][limb["bones"][0]][1]
        for limb in fixture["plan"]["limbs"]
        if limb["role"] == role
    ]
    return round(min(heights) * 1000) if heights else None


def test_the_catalog_states_the_rule_its_source_and_each_figure_with_a_reason():
    entries = _entries()
    assert set(entries) == {
        "stance_similarity",
        "reference_stance_mm",
        "legs",
        "tentacles",
        "lying",
        "limits",
    }
    # The rule names its published source; the reference is the things contract's own figure.
    assert "Alexander and Jayes (1983)" in entries["stance_similarity"]["reason"]
    assert "Froude" in entries["stance_similarity"]["reason"]
    assert entries["reference_stance_mm"]["spec"] == {"value": 900}
    # What is a chosen default says so in its own reason.
    for key in ("tentacles", "lying"):
        assert "chosen" in entries[key]["reason"], key
    table = gaits()
    assert isinstance(table, Gaits)
    assert (table.reference_stance_mm, table.minimum, table.maximum) == (900, 100, 3000)
    assert table.standing == (("leg", True), ("tentacle", True))


def test_the_reference_is_where_the_things_contract_stands_a_person_s_hips():
    # The contract's 1,700 mm figure has its hips 900 mm above the ground; the pose tests' blocky
    # figure is that body, written there in the slot frame as (x, y, z up).
    contract = (ROOT / "docs/things-contract.md").read_text()
    assert "1,700 mm" in contract
    skeleton_test = (ROOT / "web/packages/atlas-react/test/things-skeleton.test.ts").read_text()
    assert "hips: [0, 0, 900]" in skeleton_test
    assert gaits().reference_stance_mm == 900


@pytest.mark.parametrize("name", NAMES)
def test_a_body_stands_where_its_sketch_draws_its_hips(name):
    recipe = _recipe(name)
    for role in ("leg", "tentacle"):
        assert stance_mm(recipe, role) == _drawn_stance_mm(name, role), role
    # A role the body has none of has no standing height.
    assert stance_mm(recipe, "fin") is None


@pytest.mark.parametrize("name", NAMES)
def test_a_body_s_pace_is_the_root_of_its_standing_height_over_the_reference(name):
    recipe = _recipe(name)
    pace = pace_permille(recipe)
    stance = _drawn_stance_mm(name, "leg") or _drawn_stance_mm(name, "tentacle")
    if stance is None:
        # Neither leg nor tentacle: a body lying along the ground keeps the society's pace.
        assert CREATURES[name]["recipe"]["posture"] == "serpentine"
        assert pace == 1000
        return
    # The rule, stated here: the largest whole pace whose square is at most a million times the
    # height over the reference's 900 mm (whole division first, as a recorded figure must be).
    quotient = 1_000_000 * stance // 900
    assert pace * pace <= quotient < (pace + 1) * (pace + 1)
    assert 100 <= pace <= 3000
    if name in BY_HAND:
        assert (stance, pace) == BY_HAND[name]


def test_a_taller_body_walks_faster_and_legs_are_read_before_tentacles():
    paces = {name: pace_permille(_recipe(name)) for name in NAMES}
    assert paces["bat"] < paces["spider"] < paces["horse"] < paces["dragon"] < paces["four_arms"]
    # A body whose hips stand at the reference walks at the society's own pace, to the thousandth.
    table = gaits()
    horse = _recipe("horse")
    at_reference = Gaits(975, table.standing, table.minimum, table.maximum, table.version)
    assert pace_permille(horse, at_reference) == 1000
    # A body with legs is read at its legs whatever else it has.
    legged = Gaits(900, (("tentacle", True), ("leg", True)), 100, 3000, 1)
    assert pace_permille(horse, legged) == pace_permille(horse)


def test_a_pace_is_held_to_the_catalog_s_limits():
    table = gaits()
    dragon = _recipe("dragon")
    # Against a reference a hundred metres high the dragon's hips give 111, and against one a
    # millimetre high far more than three times: each is held.
    low = Gaits(100_000, table.standing, 200, 3000, 1)
    assert pace_permille(dragon, low) == 200
    assert pace_permille(dragon, Gaits(100_000, table.standing, 100, 3000, 1)) == 111
    assert pace_permille(dragon, Gaits(1, table.standing, 100, 3000, 1)) == 3000


def _catalog(tmp_path: Path, change: Any) -> Path:
    document = json.loads(CATALOG.read_text())
    change({entry["key"]: entry for entry in document["entries"]}, document)
    (tmp_path / "gaits.v1.json").write_text(json.dumps(document))
    return tmp_path


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda e, d: e["stance_similarity"]["spec"].update(root=3), "the one rule"),
        (lambda e, d: e["reference_stance_mm"]["spec"].update(value=0), "millimetres"),
        (lambda e, d: e["legs"]["spec"].update(reads="wing"), "reads one of"),
        (lambda e, d: e["tentacles"]["spec"].update(reads="leg"), "reads one of"),
        (lambda e, d: e["lying"]["spec"].update(pace="stance_similarity"), "keeps the pace"),
        (lambda e, d: e["legs"]["spec"].update(pace="gallop"), "how its pace follows"),
        (lambda e, d: e["limits"]["spec"].update(pace_permille_minimum=2000), "least and a most"),
        (lambda e, d: d["entries"].remove(e["tentacles"]), "a gait for each"),
        (lambda e, d: d["entries"].remove(e["lying"]), "one gait that"),
    ],
)
def test_a_catalog_that_does_not_state_the_rule_this_code_computes_is_refused(
    tmp_path, change, said
):
    with pytest.raises(ThingCatalogError, match=said):
        load_gaits(1, _catalog(tmp_path, change))


def test_the_committed_catalog_reads():
    assert load_gaits(1).version == 1


@pytest.mark.parametrize("name", NAMES)
def test_a_run_form_states_its_body_s_pace_with_the_walking_it_moves_by(name):
    form = _run_form(name)
    walking = [move for move in form["moves"] if move["module"] == WALKING]
    if not walking:
        # A body that cannot move from where it is states no pace: nothing walks it.
        assert form["moves"] == [] and CREATURES[name]["recipe"]["posture"] == "floating"
        return
    assert walking == [
        {"module": WALKING, "parameters": {PACE_PERMILLE: pace_permille(_recipe(name))}}
    ]
    if name in BY_HAND:
        assert walking[0]["parameters"] == {"pace_permille": BY_HAND[name][1]}


def test_a_form_without_a_pace_reads_as_before_and_a_pace_out_of_range_is_refused():
    form = _run_form("dragon")
    assert form["moves"][0]["parameters"] == {"pace_permille": 1171}
    # A form written before the pace was declared states none, and reads.
    earlier = copy.deepcopy(form)
    earlier["moves"][0]["parameters"] = {}
    read_run_form(earlier)
    for pace in (0, -5, 10_001, True, "1171", 1171.0):
        changed = copy.deepcopy(form)
        changed["moves"][0]["parameters"]["pace_permille"] = pace
        with pytest.raises(RunFormRefused):
            read_run_form(changed)
    # The widest a reader takes: a thousandth of the society's pace to ten times it.
    for pace in (1, 10_000):
        changed = copy.deepcopy(form)
        changed["moves"][0]["parameters"]["pace_permille"] = pace
        read_run_form(changed)
    # No other name is a move's figure.
    changed = copy.deepcopy(form)
    changed["moves"][0]["parameters"]["stride_mm"] = 400
    with pytest.raises(RunFormRefused):
        read_run_form(changed)
