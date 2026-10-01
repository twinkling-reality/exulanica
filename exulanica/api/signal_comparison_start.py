"""A signal comparison's start from the application: what it can cost, and every refusal by name.

A world's owner starts a signal comparison of a saved town (``POST /world/versions/{version_id}/
traffic/comparisons``): the route defines it over the version's roads as they are, reserves every
run and records its start with the bound its owner stated (migration 0132's start, claimed and
played by a host's comparison worker as a society comparison's is). What it can cost at most is
derived, never stated (:func:`signal_comparison_cost`): a run of a model arm asks at every choice
point of its group's signals, and the traffic step offers a signal at most one choice point at the
end of each green's minimum and one at each extension the plan allows, so a signal has at most
(extensions + 1) choice points for each of the plan's greens in an episode, each ask at most the
role's bound (:func:`~exulanica.api.decision_host.ask_bound_usd`). No measurement of what a signal
comparison typically costs exists, so none is served; the bound the owner states is held to the
most and to this server's budget, and a run the bound no longer fits stops by name.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from typing import Any, Final

from exulanica.api.decision_host import ask_bound_usd
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import Manifest
from exulanica.models.usage import USD_QUANTUM
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.traffic_episodes import EPISODE

__all__ = [
    "START_REFUSALS",
    "SignalComparisonCost",
    "SignalStartRefused",
    "points_most",
    "signal_comparison_cost",
    "stopped_signal_host_usd",
]

_MILLISECONDS_PER_SECOND: Final = 1000

#: Every way a signal comparison's start is refused, by the code it is answered with and its
#: status. The plan route answers the same codes in its body.
START_REFUSALS: Final = {
    # This server.
    "comparisons_not_set_up": 409,
    "comparisons_not_played": 409,
    "comparisons_not_run_here": 409,
    "provider_credential_absent": 409,
    # The world: it plays another signal comparison started from the application, or the id
    # already names another comparison of the workspace.
    "comparison_running": 409,
    "comparison_conflict": 409,
    # The roads: none stated, none traffic can drive, too many vehicles for traffic, no signal.
    "roads_not_stated": 404,
    "roads_unavailable": 409,
    "roads_world_too_large": 409,
    "signals_absent": 409,
    # The selection.
    "signal_not_in_world": 422,
    "group_empty": 422,
    "model_not_offered": 422,
    "model_named_twice": 422,
    "model_not_askable_here": 409,
    "seeds_out_of_range": 422,
    # The bound.
    "bound_out_of_range": 422,
    "bound_over_budget": 409,
    "calls_over_budget": 409,
}


class SignalStartRefused(ValueError):
    """A signal comparison that cannot be started, by a code of :data:`START_REFUSALS`."""

    def __init__(self, code: str, detail: str) -> None:
        if code not in START_REFUSALS:
            raise ValueError(f"a start is refused only by a stated code, not {code!r}")
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail

    @property
    def status(self) -> int:
        return START_REFUSALS[self.code]


def points_most() -> int:
    """The most choice points one signal can have in one episode: the plan's greens, two in each
    of its cycles, times the point at each green's minimum and one at each extension it allows."""
    plan = load_traffic_catalogs().plan(signal_actuation().plan)
    cycles = EPISODE * _MILLISECONDS_PER_SECOND // plan.cycle_ms
    return 2 * cycles * (signal_actuation().green_extension_seconds_maximum + 1)


@dataclass(frozen=True, slots=True)
class SignalComparisonCost:
    """What a signal comparison can cost at most."""

    runs: int
    #: The most asks its model runs can make, and the calls they can take.
    asks: int
    calls: int
    #: The most they can cost: every ask at its bound.
    most_usd: Decimal
    #: The most one ask of any of its runs can cost: what a host that stopped part way may have
    #: spent and never recorded, since a signal run asks one point at a time.
    point_usd: Decimal
    #: The most its runs played at once can hold reserved together: one ask at a time.
    held_usd: Decimal

    def document(self) -> dict[str, Any]:
        return {
            "runs": self.runs,
            "asks_most": self.asks,
            "calls_most": self.calls,
            "most_usd": format(self.most_usd, "f"),
            "held_usd": format(self.held_usd, "f"),
            "typical_usd": None,
            "typical_record": None,
        }


def signal_comparison_cost(
    body: Mapping[str, Any],
    group_size: int,
    role: DecisionRole,
    budget: BudgetGuard,
    manifest: Manifest,
    *,
    runs_left: list[tuple[str, str]] | None = None,
) -> SignalComparisonCost:
    """What the signal comparison ``body`` states can cost at most, every ask of its model runs at
    its model's bound; ``runs_left`` names the runs to count by arm and seed digest, else every
    run the body plans."""
    contract = role.contract()
    runs = (
        [(key, digest) for digest in body["seeds"] for key in body["arms"]]
        if runs_left is None
        else list(runs_left)
    )
    offered = {
        spec.model_id: ask_bound_usd(role, budget, spec, contract)
        for spec in manifest.offered_models(role.chosen)
    }
    dearest = max(offered.values(), default=Decimal(0))
    per_run = points_most() * group_size
    asks = 0
    most = Decimal(0)
    point = Decimal(0)
    for key, _digest in runs:
        config = body["arms"][key]["provider_config"]
        if config is None:
            continue
        bound = offered.get(config["model_id"], dearest)
        asks += per_run
        most += per_run * bound
        point = max(point, bound)
    return SignalComparisonCost(
        runs=len(runs),
        asks=asks,
        calls=asks * contract.value("answer_attempts_maximum"),
        most_usd=most,
        point_usd=point,
        held_usd=point.quantize(USD_QUANTUM, rounding=ROUND_CEILING),
    )


def stopped_signal_host_usd(
    definition: Mapping[str, Any],
    role: DecisionRole,
    budget: BudgetGuard,
    manifest: Manifest,
    open_runs: Sequence[Mapping[str, Any]],
) -> Decimal:
    """What a host whose lease ran out may have spent on a signal comparison and never recorded:
    one ask of the dearest of its open model runs, since a host plays one run at a time and a run
    asks one choice point at a time; nothing where no run is open. A takeover and a cancellation
    presume it alike."""
    if not open_runs:
        return Decimal(0)
    cost = signal_comparison_cost(
        definition,
        len(definition["group"]),
        role,
        budget,
        manifest,
        runs_left=[(run["arm"], run["seed_digest"]) for run in open_runs],
    )
    return cost.held_usd if cost.point_usd > 0 else Decimal(0)
