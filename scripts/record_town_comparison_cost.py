#!/usr/bin/env python3
"""Record what a town's people cost under each model, from one comparison's stored receipts.

    EXULANICA_DATABASE_URL=<owner url> uv run python scripts/record_town_comparison_cost.py \\
        --workspace <uuid> --world <world id> --comparison <uuid> [--stopped <uuid>] \\
        --tree <launcher state.json> --out docs/evaluation/<name>.json

Reads, and writes nothing to the database. For the comparison ``--comparison`` of a generated
town, every model arm run that completed, and every request and receipt it stored, it states per
model: the runs, the asks, how many the engine applied, what they cost by the provider's recorded
cost, the person-hours the runs decided for (the group's people times the protocol's window), the
cost per person-hour, the asks per person-minute and the answer times. The plan reads the cost per
person-hour and the 95th percentile answer time as its typical figures for a society on the same
kind of ground (``exulanica/api/society_comparison_start.py``). ``--stopped`` names a comparison
of the same town its bound stopped part way, whose asks per person-minute are recorded beside it,
since they show how much more often a town's people are asked than the small square's. The record
is a digest-bound envelope, and it names the tree the comparison ran on from the launcher's state.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import statistics
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.models.usage import USD_QUANTUM

#: The record this measurement's comparison is compared with: the judged group comparison, on the
#: starter world's small square.
SQUARE_RECORD = "docs/evaluation/2026-09-26-society-group-comparison.json"


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-95 * len(ordered) // 100) - 1)]


def _asks(connection: psycopg.Connection, workspace: str, comparison: str) -> list[dict[str, Any]]:
    return connection.execute(
        "select r.run_id, r.arm, d.request->>'base_tick' as tick, d.receipt->>'status' as status, "
        "d.receipt->'provider' as provider from society_comparison_decision d "
        "join society_comparison_run r on r.workspace_id=d.workspace_id and r.world_id=d.world_id "
        "and r.run_id=d.run_id where d.workspace_id=%s and d.comparison_id=%s "
        "order by r.arm, d.decision_seq",
        (workspace, comparison),
    ).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--comparison", required=True)
    parser.add_argument("--stopped", default=None)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with psycopg.connect(os.environ["EXULANICA_DATABASE_URL"], row_factory=dict_row) as connection:
        connection.execute("set transaction read only")
        found = connection.execute(
            "select document, created_at from society_comparison where workspace_id=%s "
            "and world_id=%s and comparison_id=%s",
            (args.workspace, args.world, args.comparison),
        ).fetchone()
        if found is None:
            raise SystemExit("no such comparison in that workspace and world")
        definition = found["document"]
        frozen = connection.execute(
            "select i.document from world_society s join world_society_input i "
            "on i.workspace_id=s.workspace_id and i.society_id=s.society_id "
            "where s.workspace_id=%s and s.world_id=%s and s.society_id=%s and i.input_seq=%s",
            (
                args.workspace,
                args.world,
                definition["society_id"],
                definition["input"]["input_seq"],
            ),
        ).fetchone()["document"]
        outcomes = {
            row["run_id"]: row
            for row in connection.execute(
                "select o.run_id, o.status, r.arm from society_comparison_outcome o "
                "join society_comparison_run r on r.workspace_id=o.workspace_id "
                "and r.world_id=o.world_id and r.run_id=o.run_id "
                "where o.workspace_id=%s and o.world_id=%s and o.comparison_id=%s",
                (args.workspace, args.world, args.comparison),
            ).fetchall()
        }
        asks = _asks(connection, args.workspace, args.comparison)
        stopped = [] if args.stopped is None else _asks(connection, args.workspace, args.stopped)
    group = len(definition["group"]["people"])
    window = int(definition["window_ticks"])
    completed = {run_id for run_id, row in outcomes.items() if row["status"] == "completed"}
    by_model: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"runs": set(), "asks": 0, "applied": 0, "cost": Decimal(0), "latency": []}
    )
    for ask in asks:
        if ask["run_id"] not in completed or ask["provider"] is None:
            continue
        held = by_model[ask["provider"]["model_id"]]
        held["runs"].add(ask["run_id"])
        held["asks"] += 1
        held["applied"] += ask["status"] == "accepted"
        held["cost"] += Decimal(str(ask["provider"]["cost_usd"]))
        if ask["provider"].get("latency_ms") is not None:
            held["latency"].append(int(ask["provider"]["latency_ms"]))
    models = {}
    for model_id, held in sorted(by_model.items()):
        person_minutes = group * window * len(held["runs"])
        models[model_id] = {
            "runs": len(held["runs"]),
            "asks": held["asks"],
            "applied": held["applied"],
            "cost_usd": format(held["cost"], "f"),
            "person_hours": format(Decimal(person_minutes) / 60, "f"),
            "typical_usd_per_person_hour": format(
                (held["cost"] * 60 / person_minutes).quantize(USD_QUANTUM), "f"
            ),
            "asks_per_person_minute": format(
                (Decimal(held["asks"]) / person_minutes).quantize(Decimal("0.0001")), "f"
            ),
            "latency_ms": {
                "p50": int(statistics.median(held["latency"])) if held["latency"] else None,
                "p95": _p95(held["latency"]),
            },
        }
    stopped_models: dict[str, dict[str, Any]] = defaultdict(lambda: {"asks": 0, "last_tick": 0})
    for ask in stopped:
        if ask["provider"] is None:
            continue
        held = stopped_models[f"{ask['arm']}:{ask['provider']['model_id']}"]
        held["asks"] += 1
        held["last_tick"] = max(held["last_tick"], int(ask["tick"]) + 1)
    square = json.loads((root / SQUARE_RECORD).read_text(encoding="utf-8"))["record"]
    tree = json.loads(args.tree.read_text(encoding="utf-8"))["tree"]
    record = {
        "profile": "exulanica.town-comparison-cost/v1",
        "what": (
            "What one person of a generated small town cost for a simulated hour under each model, "
            "and how often they were asked, from the stored receipts of one development comparison "
            "started from the application's Compare view on a server with no file of seeds."
        ),
        "navigation_profile": frozen["navigation"]["profile"],
        "world": {
            "world_id_kind": "generated",
            "input_profile": frozen["profile"],
            "population": int(definition["population"]),
            "nodes": len(frozen["navigation"]["nodes"]),
            "targets": len(frozen["targets"]),
        },
        "comparison": {
            "comparison_id": args.comparison,
            "created_at": found["created_at"].astimezone(dt.UTC).isoformat(),
            "phase": definition["phase"],
            "seeds": len(definition["seeds"]),
            "window_ticks": window,
            "group_size": group,
            "group_source": definition["group"]["source"]["kind"],
            "arms": {
                key: None if arm["provider_config"] is None else arm["provider_config"]["model_id"]
                for key, arm in sorted(definition["arms"].items())
            },
            "runs": {
                row["arm"]: row["status"]
                for row in sorted(outcomes.values(), key=lambda r: r["arm"])
            },
        },
        "models": models,
        "stopped_comparison": None
        if args.stopped is None
        else {
            "comparison_id": args.stopped,
            "why": "its bound stopped every model run part way; its asks up to the minute each stopped",
            "asks": {key: dict(value) for key, value in sorted(stopped_models.items())},
        },
        "square": {
            "record": SQUARE_RECORD,
            "group_size": square["group"]["size"],
            "turns_per_model_arm_over_its_seeds": {
                arm["key"]: square["summaries"][arm["key"]]["reliability"]["turns"]
                for arm in square["arms"]
                if arm["decider"]["kind"] == "model"
            },
            "seeds_scored": len(square["seeds"]),
        },
        "tree": tree,
        "what_this_does_not_show": [
            "One town, one development seed and one comparison: a figure for planning a bound, "
            "not a judged result and not a spread over towns or seeds.",
            "Provider answer times vary within an evening (finding #44); the figures are this "
            "run's.",
            "Models this comparison did not run have no town figure here.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    args.out.write_text(json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "models": models}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
