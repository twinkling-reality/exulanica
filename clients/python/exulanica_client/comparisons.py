"""Independent reading: a comparison of models, its runs and their decisions, read from outside.

    EXULANICA_TOKEN=<token> python -m exulanica_client comparisons \\
        --base-url http://127.0.0.1:8000 [--comparison <uuid>] --transcript comparison.json

It needs only ``world.read``. In order, stopping at the first thing that is not as expected:

1.  Read the saved world and the comparisons of the version it opens at, and take the one named, or
    the newest a world's owner started from the application.
2.  Read that comparison: its start, its arms and every run's outcome.
3.  Read every completed run of a model arm, replayed by the server from what it stored with no
    model call, and the decisions in it.

Then it checks, from those reads alone, that the start finished within the bound its owner stated,
that every run the start planned has an outcome, that each model arm names its model, that every
run it read was replayed from its record, and that each run's replayed decisions are exactly the
asks the comparison counted for it, each for somebody a model decides for in that run. It changes
nothing and reads no seed, which no response carries.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from .client import WorldClient

__all__ = ["read_comparison"]


class ComparisonStop(Exception):
    """The reading cannot go on, with the reason a person can act on."""


def _path(version_id: str, rest: str = "") -> str:
    return f"/world/versions/{version_id}/society/comparisons{rest}"


def _check(checks: list[dict[str, Any]], words: str, holds: bool) -> None:
    checks.append({"check": words, "holds": bool(holds)})


def _chosen(listing: Sequence[Mapping[str, Any]], named: str | None) -> Mapping[str, Any]:
    if named is not None:
        found = [entry for entry in listing if entry["comparison_id"] == named]
        if not found:
            raise ComparisonStop(f"the version lists no comparison {named}")
        return found[0]
    started = [entry for entry in listing if entry.get("start") is not None]
    if not started:
        raise ComparisonStop("the version lists no comparison started from the application")
    return started[0]


def read_comparison(
    client: WorldClient,
    world: Mapping[str, Any],
    args: argparse.Namespace,
    record: dict[str, Any],
    *,
    step: Any,
) -> None:
    """Read one comparison of ``world``'s version and check what it says, into ``record``.

    ``step(name)`` names the part of the reading the exchanges that follow belong to.
    """
    world_id, version_id = world["world_id"], world["authored_version_id"]
    query = {"world_id": world_id}
    step("list")
    listing = client.get(_path(version_id), query=query)["comparisons"]
    entry = _chosen(listing, getattr(args, "comparison", None))
    comparison_id = entry["comparison_id"]
    step("comparison")
    result = client.get(_path(version_id, f"/{comparison_id}"), query=query)
    checks: list[dict[str, Any]] = []
    start = result.get("start")
    _check(
        checks,
        "the comparison was started from the application and finished",
        start is not None and start["state"] == "finished",
    )
    _check(
        checks,
        "its asks spent no more than the bound its owner stated",
        start is not None and Decimal(start["spent_usd"]) <= Decimal(start["bound_usd"]),
    )
    runs = [run for seed in result["seeds"] for run in seed["runs"].values()]
    _check(
        checks,
        "every run the start planned has an outcome",
        start is not None
        and len(runs) == start["runs_planned"]
        and all(run["status"] in ("completed", "failed") for run in runs),
    )
    arms = {arm["key"]: arm for arm in result["arms"]}
    models = [arm for arm in arms.values() if arm["decider"]["kind"] == "model"]
    _check(
        checks,
        "each model arm names the model that decided, by name and id",
        bool(models)
        and all(arm["decider"].get("name") and arm["decider"].get("model_id") for arm in models),
    )
    group = result["group"]["people"]
    others = {other["id"] for other in result["others"] if other["decider"]["kind"] == "model"}
    decided_for = None if group is None else {person["id"] for person in group}
    read: list[dict[str, Any]] = []
    for seed in result["seeds"]:
        for key, run in sorted(seed["runs"].items()):
            if arms[key]["decider"]["kind"] != "model" or run["status"] != "completed":
                continue
            step(f"run {key}")
            replay = client.get(
                _path(version_id, f"/{comparison_id}/runs/{run['run_id']}"), query=query
            )
            decisions = replay["decisions"]
            asked = [decision for decision in decisions if decision["latency_ms"] is not None]
            subjects = {decision["subject_id"] for decision in decisions}
            read.append(
                {
                    "arm": key,
                    "model": arms[key]["decider"]["name"],
                    "run_id": run["run_id"],
                    "seed_digest": seed["seed_digest"],
                    "decisions": len(decisions),
                    "asked": len(asked),
                    "accepted": sum(
                        1 for decision in decisions if decision["status"] == "accepted"
                    ),
                    "chose": sorted(
                        {decision["chose"] for decision in decisions if decision["chose"]}
                    ),
                }
            )
            _check(
                checks,
                f"run {key} was replayed from its record with no model call",
                replay["replay_verified"] is True and replay["run_id"] == run["run_id"],
            )
            counted = (0 if run["calls"] is None else run["calls"]["asked"]) + (
                0 if run["others_calls"] is None else run["others_calls"]["asked"]
            )
            _check(
                checks,
                f"run {key}'s replayed decisions are the asks the comparison counted for it",
                run["calls"] is not None and len(asked) == counted,
            )
            _check(
                checks,
                f"every decision of run {key} is for somebody a model decides for in it",
                decided_for is None or subjects <= (decided_for | others),
            )
    _check(checks, "a completed run of a model arm was read", bool(read))
    record.update(
        {
            "comparison": {
                "comparison_id": comparison_id,
                "phase": result["phase"],
                "group_size": result["group"]["size"],
                "arms": [
                    {
                        "key": arm["key"],
                        "role": arm["role"],
                        "decider": arm["decider"],
                    }
                    for arm in result["arms"]
                ],
                "start": start,
                "verdict": result["verdict"],
                "runs": [
                    {"arm": key, "status": run["status"], "failure": run["failure"]}
                    for seed in result["seeds"]
                    for key, run in sorted(seed["runs"].items())
                ],
            },
            "runs_read": read,
            "checks": checks,
        }
    )
