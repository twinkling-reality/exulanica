"""How fast a drafted body swims: a share of its own walking pace, by what it swims with.

The gaits catalog's second version (``assets/catalogs/things/gaits.v2.json``) keeps the first's
walking entries and adds one swim entry for each way the body grammar's third version lets a body
swim: fins, legs that paddle, four or more tentacles, a long body. A body's pace in water is its own
walking pace times the largest share among those it meets (``gaits.swim_pace_permille``). A creature
drafted under that grammar states the pace in its kind, its run form carries it, and a society swims
it at that pace; a kind kept before states none and swims at the swimming module's reference pace.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.movement.registry import SWIMMING, built_module
from exulanica.things.bodies import load_body_grammar, read_body_recipe
from exulanica.things.catalogs import ThingCatalogError
from exulanica.things.gaits import (
    PACE_PERMILLE,
    SWIM_MOVEMENT,
    SWIM_VERSION,
    gaits,
    load_gaits,
    pace_permille,
    swim_pace_permille,
)
from exulanica.things.run_forms import RunFormRefused, read_run_form

from test_creature_bodies import CREATURES
from water_society_support import finned_walker

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "assets/catalogs/things/gaits.v2.json"
NAMES = sorted(CREATURES)
#: Paces in water by hand, from the walking paces tests/test_creature_gaits.py works for four bodies
#: (their legs paddle, at four tenths: 1,171 x 0.4 = 468.4, 251 x 0.4 = 100.4, 547 x 0.4 = 218.8,
#: 1,040 x 0.4 = 416, each rounded down) and a long body with no leg, which keeps the society's
#: walking pace and swims at six tenths of it.
BY_HAND = {"dragon": 468, "bat": 100, "spider": 218, "horse": 416, "serpent": 600}


def _recipe(name: str) -> Any:
    return read_body_recipe(copy.deepcopy(CREATURES[name]["recipe"]))


def test_each_way_the_grammar_lets_a_body_swim_has_a_share_with_its_reason():
    table = gaits(SWIM_VERSION)
    assert table.version == 2
    assert table.swimming == (
        ("fin", 1, 700),
        ("leg", 1, 400),
        ("serpentine", None, 600),
        ("tentacle", 4, 600),
    )
    # The same ways, at the same counts, as the body grammar's third version enables swimming by.
    third = load_body_grammar(version=3)
    swimming = third.movements[SWIM_MOVEMENT]
    assert swimming["pace"] == {"catalog": "gaits", "version": SWIM_VERSION}
    enabled = {(part, least) for part, least in swimming["enabled_by"]["parts"].items()}
    enabled |= {(posture, None) for posture in swimming["enabled_by"]["postures"]}
    assert enabled == {(reads, least) for reads, least, _share in table.swimming}
    entries = [e for e in json.loads(CATALOG.read_text())["entries"] if e["group"] == "swim"]
    assert len(entries) == 4 and all(len(entry["reason"].split()) > 20 for entry in entries)
    # The share every swimmer whose kind states none swims at is the module's reference pace.
    assert built_module(SWIMMING).value("reference_pace_permille") == 400


@pytest.mark.parametrize("name", NAMES)
def test_walking_reads_the_same_under_both_versions(name):
    recipe = _recipe(name)
    assert (
        pace_permille(recipe, gaits(1)) == pace_permille(recipe, gaits(2)) == pace_permille(recipe)
    )
    assert gaits(1).swimming == ()


@pytest.mark.parametrize("name", NAMES)
def test_a_body_swims_at_the_best_share_of_its_walk_it_has_a_way_to(name):
    recipe = _recipe(name)
    pace = swim_pace_permille(recipe)
    shares = [
        share
        for reads, least, share in gaits(SWIM_VERSION).swimming
        if (recipe.posture == reads if least is None else recipe.pairs(reads) >= least)
    ]
    assert shares, name
    assert pace == pace_permille(recipe) * max(shares) // 1000
    if name in BY_HAND:
        assert pace == BY_HAND[name]


def test_a_body_with_no_way_to_swim_has_no_pace_in_water():
    document = copy.deepcopy(CREATURES["floating_eight"]["recipe"])
    document["limbs"] = [
        {**limb, "count": 2} for limb in document["limbs"] if limb["role"] == "tentacle"
    ]
    assert swim_pace_permille(read_body_recipe(document)) is None


def _catalog(tmp_path: Path, change: Any) -> Path:
    document = json.loads(CATALOG.read_text())
    change({entry["key"]: entry for entry in document["entries"]}, document)
    (tmp_path / "gaits.v2.json").write_text(json.dumps(document))
    return tmp_path


@pytest.mark.parametrize(
    "change",
    [
        lambda e, d: e["swims_with_fins"]["spec"].update(share_permille=1001),
        lambda e, d: e["swims_with_fins"]["spec"].update(share_permille=0),
        lambda e, d: e["swims_with_fins"]["spec"].update(reads="wing"),
        lambda e, d: e["swims_with_fins"]["spec"].update(least=None),
        lambda e, d: e["swims_on_its_length"]["spec"].update(least=1),
        lambda e, d: e["paddles_with_legs"]["spec"].update(reads="fin"),
        lambda e, d: e["swims_with_tentacles"]["spec"].update(speed=3),
    ],
)
def test_a_swim_entry_out_of_shape_is_refused_by_name(tmp_path, change):
    with pytest.raises(ThingCatalogError, match="swims at"):
        load_gaits(2, _catalog(tmp_path, change))


def test_a_drafted_swimmer_s_run_form_carries_its_pace_and_one_out_of_range_is_refused():
    _sha256, form = finned_walker(3)
    [swimming] = [move for move in form["moves"] if move["module"] == SWIMMING]
    assert swimming["parameters"] == {PACE_PERMILLE: 592}
    read_run_form(form)
    for pace in (0, 10_001, True, "592"):
        changed = copy.deepcopy(form)
        changed["moves"][form["moves"].index(swimming)]["parameters"][PACE_PERMILLE] = pace
        with pytest.raises(RunFormRefused):
            read_run_form(changed)


def test_a_kind_kept_before_states_no_pace_in_water_and_its_run_form_reads_as_before():
    _sha256, form = finned_walker(2)
    [swimming] = [move for move in form["moves"] if move["module"] == SWIMMING]
    assert swimming["parameters"] == {}
    read_run_form(form)
