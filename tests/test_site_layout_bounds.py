"""The work a site's layout and walking graph do is bounded by what they hold, not by the site.

A world kind comes from a person or a model, so the work it can ask of the generator is bounded:
a scattered holding draws only the cells it tries, a holding of none costs nothing, a layout past
its budget is refused by name, a kind's whole check shares one budget, and the walking graph asks
only the obstacles near each way. The kinds are built here from the hand-written fixture farm (a
test fixture, not a kind a person or a model made); each expected value comes from another run (a
smaller site, a kind without the holding, an index that asks every obstacle), not from the code
under test.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars.site import generate_site, site_records
from exulanica.grammar.grammars.site import layout as site_layout
from exulanica.grammar.grammars.site.layout import LayoutBudget, LayoutOverBudget
from exulanica.grammar.grammars.site.records import SiteFixtureRecord
from exulanica.world import society_site_place
from exulanica.world.kinds import samples as kind_samples
from exulanica.world.kinds.document import KindRefused, read_kind
from exulanica.world.kinds.routine import kind_routine
from exulanica.world.kinds.samples import check_samples, sample_values, site_seed

FIXTURES = Path(__file__).parent / "fixtures" / "world-kinds"
SEED = "7" * 64
ROOT = "0b6f3a1e-2c4d-5e6f-8a9b-0c1d2e3f4a5b"


def _farm() -> dict[str, Any]:
    return json.loads((FIXTURES / "fixture-farm.json").read_text(encoding="utf-8"))


def _prop(key: str, size: int) -> dict[str, Any]:
    return {
        "key": key,
        "label": key,
        "description": "",
        "form": "fixture",
        "roles": ["obstruction"],
        "look": f"prop.{key}",
        "use_class": "",
        "width_mm": size,
        "depth_mm": size,
        "height_mm": 500,
        "seats": 0,
        "stands": 0,
        "sleepers": 0,
        "blocks": 1,
    }


def _zone(index: int, holds: list[dict[str, Any]], access: str = "open") -> dict[str, Any]:
    return {
        "key": f"z{index}",
        "label": f"zone {index}",
        "placement": "middle",
        "share": 100,
        "ground": "ground.grass",
        "access": access,
        "boundary": "",
        "holds": holds,
    }


def _site(width: int, depth: int, zones: list[dict[str, Any]], *parts: dict[str, Any]) -> Any:
    """The farm's parts on a site of its own size with its own zones, one preset and no values."""
    document = _farm()
    document["kind"] = "bounds_test"
    document["parameters"] = []
    document["presets"] = [{"key": "only", "label": "Only", "values": {}}]
    document["site"]["width_mm"] = width
    document["site"]["depth_mm"] = depth
    document["parts"].extend(parts)
    document["zones"] = [
        {**zones[0], "holds": [{"part": "farmhouse", "count": 1, "pattern": "row"}]},
        *zones[1:],
    ]
    return read_kind(document)


def _laid_out(kind: Any, budget: LayoutBudget | None) -> tuple[object, ...]:
    plan = kind.plan(kind.values("only"))
    return site_records(generate_site(plan, seed=SEED, subject_identity=ROOT, budget=budget))


def _draws(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    counted = [0]
    original = site_layout.DomainCursor.number

    def number(self: Any) -> int:
        counted[0] += 1
        return original(self)

    monkeypatch.setattr(site_layout.DomainCursor, "number", number)
    return counted


def test_a_scattered_holding_draws_for_what_it_tries_not_for_the_size_of_its_zone(monkeypatch):
    scattered = [{"part": "pebble", "count": 2, "pattern": "scatter"}] * 4
    draws = _draws(monkeypatch)
    counts = {}
    for side in (64_000, 256_000):
        zones = [_zone(i, scattered) for i in range(6)]
        kind = _site(side, side, zones, _prop("pebble", 200))
        draws[0] = 0
        records = _laid_out(kind, None)
        counts[side] = draws[0]
        placed = sum(
            1 for r in records if isinstance(r, SiteFixtureRecord) and r.part_key == "pebble"
        )
        assert placed == 5 * 4 * 2
    # Sixteen times the ground, about the same draws: each tried cell is drawn when it is tried.
    assert counts[256_000] <= 2 * counts[64_000]


def test_a_layout_past_its_budget_is_refused_by_name_and_within_it_lays_out():
    # Small fixtures sent to the centre of yards their larger neighbours already fill search far
    # for room, the work a nearest-free search does.
    holds = [
        {"part": "block", "count": 12, "pattern": "grid"},
        {"part": "pebble", "count": 30, "pattern": "centre"},
    ]
    zones = [_zone(i, holds, "closed" if i else "open") for i in range(12)]
    kind = _site(256_000, 256_000, zones, _prop("block", 12_000), _prop("pebble", 200))
    tight = LayoutBudget(5_000)
    with pytest.raises(LayoutOverBudget) as caught:
        _laid_out(kind, tight)
    assert "more than 5000 placements" in str(caught.value)
    roomy = LayoutBudget(10**9)
    records = _laid_out(kind, roomy)
    assert roomy.spent > 5_000
    assert sum(1 for r in records if isinstance(r, SiteFixtureRecord)) >= 11 * 42


def test_a_holding_of_none_places_nothing_and_costs_nothing():
    def farm(extra: bool) -> Any:
        document = _farm()
        if extra:
            document["parts"].append(_prop("crate", 400))
            document["parameters"].append(
                {
                    "key": "crates",
                    "label": "Crates",
                    "minimum": 0,
                    "maximum": 4,
                    "step": 1,
                    "reason": "test",
                }
            )
            for preset in document["presets"]:
                preset["values"]["crates"] = 0
            kitchen = next(part for part in document["parts"] if part["key"] == "kitchen")
            kitchen["holds"].append(
                {"part": "crate", "count": {"parameter": "crates"}, "pattern": "scatter"}
            )
        return read_kind(document)

    plain, with_none = farm(False), farm(True)
    preset = plain.presets[0][0]
    budgets = [LayoutBudget(10**9), LayoutBudget(10**9)]
    laid = [
        site_records(
            generate_site(
                kind.plan(kind.values(preset)), seed=SEED, subject_identity=ROOT, budget=budget
            )
        )
        for kind, budget in zip((plain, with_none), budgets, strict=True)
    ]
    assert not any(
        isinstance(record, SiteFixtureRecord) and record.part_key == "crate" for record in laid[1]
    )
    assert laid[0] == laid[1]
    assert budgets[0].spent == budgets[1].spent


def test_a_kind_s_whole_check_shares_one_layout_budget(monkeypatch):
    kind = read_kind(_farm())
    assert check_samples(kind)["verdict"] == "passed"
    monkeypatch.setattr(
        kind_samples,
        "layout_budget",
        lambda in_all=False: LayoutBudget(100_000, 50 if in_all else None),
    )
    with pytest.raises(KindRefused) as caught:
        check_samples(kind)
    assert caught.value.code == "kind_layout_over_budget"
    assert "50 placements in all" in caught.value.detail


class _EveryBox(society_site_place._Cells):
    """The obstacles of every way and point asked of all of them, as before they were indexed."""

    def holding(self, point: Any) -> list[Any]:
        return list(self.boxes)

    def near(self, a: Any, b: Any) -> list[Any]:
        return list(self.boxes)


def _places(kind: Any) -> list[str]:
    routine = kind_routine(kind)
    found = []
    for _label, values, seed in sample_values(kind):
        plan, society = kind.plan(values), kind.society(values)
        for candidate in range(2):
            drawn = site_seed(kind.reference(), values, f"index-test:{seed}", candidate)
            try:
                records = site_records(generate_site(plan, seed=drawn, subject_identity=ROOT))
            except InvalidParameterError:
                continue
            place = society_site_place.place_from_site_records(
                place_id="p", records=records, society=society, routine=routine
            )
            found.append(sha256_of_canonical(place).hex())
    return found


@pytest.mark.parametrize("name", ["farm", "cafe", "site"])
def test_the_walking_graph_asks_the_obstacles_near_a_way_and_finds_what_asking_all_finds(
    name, monkeypatch
):
    kind = read_kind(json.loads((FIXTURES / f"fixture-{name}.json").read_text(encoding="utf-8")))
    indexed = _places(kind)
    monkeypatch.setattr(society_site_place, "_Cells", _EveryBox)
    assert _places(kind) == indexed


def test_a_crowded_site_s_walking_graph_is_the_one_asking_every_obstacle_gives(monkeypatch):
    holds = [{"part": "stone", "count": 40, "pattern": "scatter"}]
    zones = [_zone(i, copy.deepcopy(holds)) for i in range(12)]
    kind = _site(128_000, 128_000, zones, _prop("stone", 600))
    indexed = _places(kind)
    monkeypatch.setattr(society_site_place, "_Cells", _EveryBox)
    assert _places(kind) == indexed


def test_a_world_is_laid_out_again_within_the_budget_it_was_made_under(monkeypatch):
    from exulanica.world.composers import site_plan
    from exulanica.world.errors import InvalidStructuralData

    kind = read_kind(_farm())
    made = site_plan.compose_kind(kind, kind.values("small_farm"), "world:generated:budget-test")
    assert site_plan.records(made.receipt) == made.records
    # A bound lowered under a stored world refuses it by name; nothing is laid out past it.
    monkeypatch.setattr(site_plan, "layout_budget", lambda: LayoutBudget(5))
    with pytest.raises(InvalidStructuralData, match="generated_world_catalogs_changed"):
        site_plan.records(made.receipt)
