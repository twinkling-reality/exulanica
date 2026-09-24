"""The result document of one rehearsal run, assembled from what each step reported.

``assemble`` takes the step list, its gates and the outcome each runner reported, and returns the
document ``result.schema.json`` describes. It is the one place that decides a step's final status:

*   a step the step list declares ``not_available`` is reported as such, with its reason;
*   a step no runner reported is ``not_reachable``, with the reason the orchestrator recorded (its
    page session ended, a step it requires did not pass), never a missing line;
*   a step reported ``passed`` stays passed only when every observable the step list declares for it
    was checked and held, and nothing undeclared was reported. A runner therefore cannot pass a step
    by checking less than the data says, or by checking something the data does not say.

The gate table then gives each gate the owning document states the worst status of its steps
(``GATE_ORDER``) and names the first failed step that serves it, with that step's owner area, so a
failure can be routed without reading the run.
Standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from steplist import STATUSES, Gate

RESULT_PROFILE = "exulanica.rehearsal-result/v1"
#: A gate's status is the first of these that any of its steps has.
GATE_ORDER = ("failed", "not_reachable", "not_available", "passed")


def _declared(step: Mapping[str, Any]) -> list[dict[str, str]]:
    return [
        {"kind": kind, "id": observable["id"], "says": observable["says"]}
        for kind, observables in step["expect"].items()
        for observable in observables
    ]


def _settle(step: Mapping[str, Any], outcome: Mapping[str, Any]) -> dict[str, Any]:
    """The outcome with the declared-versus-observed rule applied to a reported pass."""
    settled = dict(outcome)
    status = settled.get("status")
    if status not in STATUSES or status == "not_available":
        settled["status"] = "failed"
        settled["reason"] = (
            f"the runner reported the status {status!r}, which a runner may not report"
        )
        return settled
    if status != "passed":
        return settled
    declared = {observable["id"] for observable in _declared(step)}
    observations = settled.get("observations", [])
    reported = {observation.get("id") for observation in observations}
    missing = sorted(declared - reported)
    extra = sorted(str(identifier) for identifier in reported - declared)
    broken = sorted(
        str(observation.get("id"))
        for observation in observations
        if observation.get("ok") is not True
    )
    reasons = []
    if missing:
        reasons.append(f"declared but not checked: {', '.join(missing)}")
    if extra:
        reasons.append(f"checked but not declared in the step list: {', '.join(extra)}")
    if broken:
        reasons.append(f"did not hold: {', '.join(broken)}")
    if reasons:
        settled["status"] = "failed"
        settled["reason"] = "; ".join(reasons)
    return settled


def assemble(
    steps: Mapping[str, Any],
    gates: Sequence[Gate],
    outcomes: Mapping[str, Mapping[str, Any]],
    unreached: Mapping[str, str],
    run: Mapping[str, Any],
) -> dict[str, Any]:
    """The run's result document. ``unreached`` gives the reason for a step no runner reported."""
    reported_steps: list[dict[str, Any]] = []
    for step in steps["steps"]:
        base = {
            "id": step["id"],
            "action": step["action"],
            "gates": list(step["gates"]),
            "session": step.get("session"),
            "owner_area": step["owner_area"],
            "expect": _declared(step),
        }
        if step.get("not_available") is not None:
            outcome: dict[str, Any] = {"status": "not_available", "reason": step["not_available"]}
        elif step["id"] in outcomes:
            outcome = _settle(step, outcomes[step["id"]])
        else:
            outcome = {
                "status": "not_reachable",
                "reason": unreached.get(step["id"], "no runner reported this step"),
            }
        outcome.setdefault("observations", [])
        outcome.setdefault("evidence", {})
        reported_steps.append(base | outcome)

    by_id = {step["id"]: step for step in reported_steps}
    table = []
    for gate in gates:
        serving = [step for step in reported_steps if gate.key in step["gates"]]
        statuses = {step["status"] for step in serving}
        first_failure = next((s for s in serving if s["status"] == "failed"), None)
        table.append(
            {
                "gate": gate.key,
                "name": gate.name,
                "document": gate.document,
                "heading": gate.heading,
                # The worst status of the steps that serve it: a failure anywhere is the gate's
                # failure, whatever step list order puts ahead of it.
                "status": next(status for status in GATE_ORDER if status in statuses),
                "steps": [{"id": s["id"], "status": s["status"]} for s in serving],
                "first_failure": None
                if first_failure is None
                else {
                    "step": first_failure["id"],
                    "reason": first_failure.get("reason"),
                    "owner_area": by_id[first_failure["id"]]["owner_area"],
                },
            }
        )
    counts = {
        status: sum(1 for s in reported_steps if s["status"] == status) for status in STATUSES
    }
    return {
        "profile": RESULT_PROFILE,
        "steps_profile": steps["profile"],
        "steps_version": steps["version"],
        "run": dict(run),
        "summary": counts,
        "steps": reported_steps,
        "gates": table,
    }
