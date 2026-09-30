"""The versioned comparison drawing for a living town."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from exulanica.world.society_comparison import PlayedRun, RunPlan
from exulanica.world.society_living import input_routine, living_places
from exulanica.world.society_person_label import person_label
from exulanica.world.society_score import DECISION_EVENT

REPLAY_PROFILE = "exulanica.society-comparison-run-replay/v3"


def replay_document(
    plan: RunPlan,
    arm: str,
    digest: str,
    played: PlayedRun,
    *,
    model_name: Callable[[str], str],
) -> dict[str, Any]:
    """Draw recorded living positions, destinations, actions and all supported needs."""
    source = plan.inputs[-1]
    routine = input_routine(source)
    [place] = living_places([source], routine)
    nodes = place.document["nodes"]
    positions = {node["node_id"]: node["position_mm"] for node in nodes}
    destinations = [d for d in place.document["destinations"] if d["enabled"]]
    thresholds = {
        key: routine.needs[key].threshold for key in played.start["population"]["supported_needs"]
    }

    def person(value: Mapping[str, Any]) -> dict[str, Any]:
        path = value["motion_path_mm"] or [value["position_mm"]]
        goal = value["goal"]
        needs = value["needs"]
        return {
            "id": value["id"],
            "x": value["position_mm"][0],
            "z": value["position_mm"][1],
            "path": [list(point) for point in path],
            "action": value["action"]["kind"],
            "status": value["action"]["status"],
            "reason": value["action"]["reason"],
            "goal": None
            if goal is None
            else {
                "kind": goal["activity"],
                "target_id": goal["destination_id"],
                "reason": goal["reason"],
            },
            "need_milli": sum(
                max(0, needs[key] - threshold) for key, threshold in thresholds.items()
            ),
            "needs": dict(needs),
        }

    minutes = [
        {"tick": state["tick"], "people": [person(p) for p in state["inhabitants"]]}
        for state in (played.start, *played.states)
    ]
    dispositions = {
        event.document["decision_seq"]: event.document
        for event in played.events
        if event.kind == DECISION_EVENT
    }
    decisions = []
    for receipt in played.receipts:
        applied = dispositions.get(receipt["decision_seq"])
        call = receipt["provider"] or {}
        decisions.append(
            {
                "decision_seq": receipt["decision_seq"],
                "subject_id": receipt["subject_id"],
                "tick": receipt["base_tick"] + 1,
                "status": receipt["status"],
                "reason": receipt["reason"],
                "disposition": None if applied is None else applied["disposition"],
                "disposition_reason": None if applied is None else applied["reason"],
                "chose": None if receipt["proposal"] is None else receipt["proposal"]["label"],
                "latency_ms": call.get("latency_ms"),
                "cost_usd": call.get("cost_usd"),
            }
        )
    events = [
        {
            "tick": event.tick,
            "subject_id": str(event.subject_id),
            "kind": event.kind,
            "reason": str(event.document.get("reason", "")),
            "summary": str(event.document.get("summary", "")),
        }
        for event in played.events
        if event.subject_id is not None
    ]
    people = []
    for value in played.start["inhabitants"]:
        decider, _config = plan.decider_for(value["id"])
        described = {"kind": decider["kind"]}
        if decider["kind"] == "model":
            described.update(
                provider=decider["provider"],
                model_id=decider["model_id"],
                name=model_name(decider["model_id"]),
            )
        people.append(
            {
                "id": value["id"],
                "name": person_label(value),
                "in_group": plan.group is None or value["id"] in plan.group,
                "decider": described,
            }
        )
    return {
        "profile": REPLAY_PROFILE,
        "replay_verified": True,
        "run_id": str(plan.run_id),
        "arm": arm,
        "seed_digest": digest,
        "threshold": 0,
        "need_thresholds": thresholds,
        "place": {
            "nodes": [
                {"id": node["node_id"], "x": node["position_mm"][0], "z": node["position_mm"][1]}
                for node in nodes
            ],
            "edges": [
                [edge["from_node_id"], edge["to_node_id"]] for edge in place.document["edges"]
            ],
            "targets": [
                {
                    "target_id": dest["destination_id"],
                    "affordance": dest["affordances"][0] if dest["affordances"] else "place",
                    "activity": dest["use_class"] or "place",
                    "label": dest["label"] or (dest["use_class"] or "place").replace("_", " "),
                    "x": positions[dest["node_id"]][0],
                    "z": positions[dest["node_id"]][1],
                    "places": [list(positions[dest["node_id"]])],
                }
                for dest in destinations
            ],
        },
        "activities": [
            {"kind": activity.key, "label": activity.label}
            for activity in routine.activities.values()
        ],
        "people": people,
        "minutes": minutes,
        "decisions": decisions,
        "events": events,
    }
