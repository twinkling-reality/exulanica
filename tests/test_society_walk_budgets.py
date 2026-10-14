"""A society response serves each kind-paced inhabitant's walk budget beside its state.

The engine walks a body whose kind states its own pace at the society's budget times that pace
over a thousand (:func:`exulanica.world.society_planner.tick_budgets`). The page draws that figure
as the server serves it (``walk_budgets_mm_per_tick``, from
:func:`~exulanica.world.society.served_snapshot`) instead of working it out again. The states
here are synthetic: a made kind stated at 685 per mille in a society whose budget is 60 m a tick.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from exulanica.world.society import served_snapshot
from exulanica.world.society_planner import own_walk_budgets, tick_budgets

PACED = "exulanica-movement/walking/v2"
UNPACED = "exulanica-movement/walking/v1"
MADE = "a" * 64
SILENT = "b" * 64


def _state(modules: list[str] | None = None) -> dict[str, Any]:
    walk = {"module": "exulanica-movement/walking/v1"}
    return {
        "profile": "exulanica-society/v7",
        "tick": 3,
        "movement_budget_mm_per_tick": 60_000,
        "movement_modules": [PACED] if modules is None else modules,
        "kinds": {
            MADE: {"moves": [walk | {"parameters": {"pace_permille": 685}}]},
            SILENT: {"moves": [walk | {"parameters": {}}]},
        },
        "inhabitants": [
            {"id": "made", "kind": {"source": "workspace", "sha256": MADE}},
            {"id": "silent", "kind": {"source": "workspace", "sha256": SILENT}},
            {"id": "shipped", "kind": {"kind": "knight", "version": 1, "sha256": "c" * 64}},
            {"id": "person"},
        ],
    }


def _snapshot(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "society_id": "society",
        "current_tick": state["tick"],
        "state": state,
        "seed": "seed",
        "state_sha256": "d" * 64,
    }


def test_a_body_whose_kind_states_its_pace_is_served_the_engines_own_budget():
    state = _state()
    budgets = own_walk_budgets(state)
    assert budgets == {"made": 41_100}
    # One authority: the figure is the engine's own for that body.
    made = next(person for person in state["inhabitants"] if person["id"] == "made")
    assert budgets["made"] == tick_budgets(state)(made)


def test_nobody_is_served_a_budget_where_the_walking_paces_nobody_or_no_budget_is_recorded():
    assert own_walk_budgets(_state([UNPACED])) == {}
    assert own_walk_budgets(_state([])) == {}
    no_budget = _state()
    del no_budget["movement_budget_mm_per_tick"]
    assert own_walk_budgets(no_budget) == {}
    assert own_walk_budgets({"tick": 0, "inhabitants": [{"id": "person"}]}) == {}


def test_the_served_snapshot_carries_the_budgets_beside_the_state_and_leaves_the_state_alone():
    state = _state()
    stored = deepcopy(state)
    served = served_snapshot(_snapshot(state))
    assert served["walk_budgets_mm_per_tick"] == {"made": 41_100}
    assert "walk_budgets_mm_per_tick" not in served["state"]
    assert state == stored
    assert served["state_sha256"] == "d" * 64


def test_a_snapshot_with_nobody_paced_by_kind_is_served_as_before():
    served = served_snapshot(_snapshot(_state([UNPACED])))
    assert "walk_budgets_mm_per_tick" not in served
