"""Write the evaluation record of the second creature rig trial (route C v2) on Nebius AI Cloud.

Reads only tracked evidence under ``ml/appearance/evidence/creature-rig-trial-2/``:
- the job record and the requests;
- ``bodies.json``: each body the job was built from, with its role (held-out or development),
  its words and the digests of its drafted recipe and plan, as the staging step wrote it;
- the job's results and every receipt it wrote;
- ``standin/``: the stand-in run of the same staged job, made before the trial's pre-registration
  was frozen, with its results and receipts;
- the per-job file (the Serverless AI job's id, container start and finish, staged digests and
  outcome);
- the job's ``exulanica.appearance-gpu-run/v1`` record.

Writes ``docs/evaluation/2026-10-07-creature-rig-trial-2.json`` as an
``exulanica.digest-bound-record/v1``. Every figure is computed here from that evidence; nothing is
typed in but the rule the trial was pre-registered with (its document's digest is in the record),
which this script applies:
- a creature counts when at least one of its two items passed every check;
- the plan-guided rig (R2) becomes the default sculpted route at 5 held-out creatures of 8 or more;
- the development rows are reported beside the held-out ones and never counted.

It also gives the second reading the pre-registration names, which never decides the rule: for each
item, the trial's outcome beside the stand-in's for the same request.

Run: ``.venv/bin/python scripts/record_creature_rig_trial_2.py``
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "ml/appearance/evidence"
TRIAL = EVIDENCE / "creature-rig-trial-2"
OUTPUT = ROOT / "docs/evaluation/2026-10-07-creature-rig-trial-2.json"
#: The pre-registration's own digest (deliveries, kept out of the repository with the trial's
#: working notes); the rule below is the one it states.
PREREGISTRATION_SHA256 = "564c019ae45a22e9bcf517da3562be4859d1a34f4e1381231ee636485798d2a1"
DEFAULT_AT = 5


def _instant(text: str) -> datetime:
    """A UTC instant to the millisecond, as the job status states it."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _microdollars(rate_cents_per_hour: int, milliseconds: int) -> int:
    """Rate times milliseconds, in millionths of a dollar, rounded up."""
    return -(-rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)


def _outcomes(folder: Path) -> list[dict[str, Any]]:
    """Every item of the one results file in ``folder``, each with its receipt's measures."""
    [results_path] = sorted(folder.glob("results-*.json"))
    results = json.loads(results_path.read_bytes())
    items = []
    for item in results["items"]:
        receipt = json.loads((folder / "receipts" / f"{item['receipt']}.json").read_bytes())
        rig = receipt.get("rig", {})
        registration = receipt.get("registration", {})
        scales = registration.get("scale_per_mille")
        items.append(
            {
                "creature": receipt["plan"]["key"],
                "joint_moved_mm_largest": max(rig.get("joint_moved_mm", {}).values(), default=None),
                "leaked_per_mille_largest": max(
                    rig.get("leaked_per_mille", {}).values(), default=None
                ),
                "look_sha256": item.get("look"),
                "outcome": item["outcome"],
                "receipt": item["receipt"],
                "refusal": item.get("refusal"),
                # The refusal's own sentence, which names the measure it broke on.
                "refusal_detail": receipt.get("refusal", {}).get("detail"),
                "registration_overlap_per_mille": registration.get("overlap_per_mille"),
                # The largest of the three axis scales over the smallest, in thousandths.
                "registration_scale_ratio_per_mille": (
                    None if not scales else max(scales) * 1000 // min(scales)
                ),
                "registration_yaw_degrees": registration.get("yaw_degrees"),
                "request_sha256": item["request_sha256"],
                "seconds": receipt.get("seconds", {}),
                "stage": receipt.get("stage"),
                "triangles": receipt.get("output", {}).get("triangles"),
                "variant": item["variant"],
            }
        )
    return items


def _counted(items: list[dict[str, Any]], creatures: list[str]) -> dict[str, dict[str, Any]]:
    outcomes: dict[str, list[str]] = {name: [] for name in creatures}
    for item in items:
        if item["creature"] in outcomes:
            outcomes[item["creature"]].append(item["outcome"])
    return {
        name: {"counted": "passed" in found, "outcomes": found}
        for name, found in sorted(outcomes.items())
    }


def _said(item: dict[str, Any]) -> str:
    return "passed" if item["outcome"] == "passed" else f"{item['outcome']}: {item['refusal']}"


def build() -> dict[str, Any]:
    job_raw = (TRIAL / "job.json").read_bytes()
    bodies = json.loads((TRIAL / "bodies.json").read_bytes())["bodies"]
    [job] = json.loads((TRIAL / "jobs.json").read_bytes())["jobs"]
    run = json.loads((EVIDENCE / f"gpu-run-{job['job_id']}.json").read_bytes())
    started = _instant(job["container_started_at"])
    finished = _instant(job["container_finished_at"])
    milliseconds = (finished - started) // datetime.resolution // 1000
    role = {body["key"]: body["role"] for body in bodies}
    items = [dict(item, role=role[item["creature"]]) for item in _outcomes(TRIAL)]
    held_out = sorted(body["key"] for body in bodies if body["role"] == "held_out")
    development = sorted(body["key"] for body in bodies if body["role"] == "development")
    creatures = _counted(items, held_out)
    counted = sorted(name for name, creature in creatures.items() if creature["counted"])
    stand_in = {
        (item["request_sha256"], item["variant"]): item for item in _outcomes(TRIAL / "standin")
    }
    pairs = [
        {
            "creature": item["creature"],
            "role": item["role"],
            "stand_in": _said(stand_in[(item["request_sha256"], item["variant"])]),
            "trial": _said(item),
            "variant": item["variant"],
        }
        for item in items
    ]
    stand_in_counted = _counted(list(stand_in.values()), held_out)
    return {
        "authoritative_total": "the provider's billing page, read by the operator",
        "bodies": [
            {
                "bones": body["bones"],
                "description": body["description"],
                "key": body["key"],
                "plan_sha256": body["plan_sha256"],
                "request_sha256": body["request_sha256"],
                "role": body["role"],
            }
            for body in bodies
        ],
        "compute": {
            "gpu": run["gpu"],
            "instance_type": run["instance_type"],
            "provider": run["provider"],
            "rate_cents_per_hour": run["rate_cents_per_hour"],
            "rate_source": run["rate_source"],
        },
        "creatures": creatures,
        "development": _counted(items, development),
        "items": items,
        "job": {
            "code_sha256": job["code_sha256"],
            "computed_cost_microdollars": _microdollars(run["rate_cents_per_hour"], milliseconds),
            "container_finished_at": job["container_finished_at"],
            "container_milliseconds": milliseconds,
            "container_started_at": job["container_started_at"],
            "job_id": job["job_id"],
            "job_sha256": hashlib.sha256(job_raw).hexdigest(),
            "outcome": job["outcome"],
            "upper_bound_cost_microdollars": run["cost_microdollars"],
            "upper_bound_from": run["started_at"],
            "upper_bound_to": run["deleted_at"],
        },
        "kind": "exulanica.creature-rig-trial/v2",
        "preregistration_sha256": PREREGISTRATION_SHA256,
        "rule": {
            "counted": "a creature counts when at least one of its two items passed every check",
            "default_at": DEFAULT_AT,
            "verdict": (
                "the plan-guided rig is the default sculpted route"
                if len(counted) >= DEFAULT_AT
                else "the sketch stays the default; a sculpted look is offered only where an "
                "item passed"
            ),
        },
        "script": "scripts/record_creature_rig_trial_2.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "second_reading": {
            "note": (
                "reported, never deciding the rule: each item's outcome beside the stand-in's for "
                "the same request, the stand-in run made before the pre-registration was frozen"
            ),
            "items": pairs,
            "items_agreeing": sum(pair["trial"] == pair["stand_in"] for pair in pairs),
            "counted_by_the_trial_only": sorted(
                name for name in counted if not stand_in_counted[name]["counted"]
            ),
            "counted_by_the_stand_in_only": sorted(
                name
                for name, creature in stand_in_counted.items()
                if creature["counted"] and name not in counted
            ),
        },
        "totals": {
            "creatures": len(creatures),
            "creatures_counted": len(counted),
            "development_bodies": len(development),
            "development_counted": sum(
                creature["counted"] for creature in _counted(items, development).values()
            ),
            "items": len(items),
            "items_passed": sum(item["outcome"] == "passed" for item in items),
        },
    }


def main() -> int:
    record = build()
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {record['totals']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
