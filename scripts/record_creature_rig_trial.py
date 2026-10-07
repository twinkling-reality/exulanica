"""Write the evaluation record of the creature rig trial on Nebius AI Cloud.

Reads only tracked evidence under ``ml/appearance/evidence/creature-rig-trial-1/``:
- the job record;
- the requests;
- the job's results and every receipt it wrote;
- the per-job file (the Serverless AI job's id, container start and finish, staged digests and
  outcome);
- the job's ``exulanica.appearance-gpu-run/v1`` record.

Writes ``docs/evaluation/2026-10-07-creature-rig-trial.json`` as an
``exulanica.digest-bound-record/v1``. Every figure is computed here from that evidence; nothing is
typed in but the rule the trial was pre-registered with (its document's digest is in the record),
which this script applies:
- a creature counts when at least one of its two items passed every check;
- the plan-guided rig (R2) becomes the default sculpted route at 5 creatures of 8 or more.

Run: ``.venv/bin/python scripts/record_creature_rig_trial.py``
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
TRIAL = EVIDENCE / "creature-rig-trial-1"
OUTPUT = ROOT / "docs/evaluation/2026-10-07-creature-rig-trial.json"
#: The pre-registration's own digest (deliveries, kept out of the repository with the trial's
#: working notes); the rule below is the one it states.
PREREGISTRATION_SHA256 = "9b1390682569cafd02ad0fa0700f11e8eee2e2810b0d8ef3c87be724159c646f"
DEFAULT_AT = 5


def _instant(text: str) -> datetime:
    """A UTC instant to the millisecond, as the job status states it."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _microdollars(rate_cents_per_hour: int, milliseconds: int) -> int:
    """Rate times milliseconds, in millionths of a dollar, rounded up."""
    return -(-rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)


def _items() -> list[dict[str, Any]]:
    [results_path] = sorted(TRIAL.glob("results-*.json"))
    results = json.loads(results_path.read_bytes())
    items = []
    for item in results["items"]:
        receipt = json.loads((TRIAL / "receipts" / f"{item['receipt']}.json").read_bytes())
        rig = receipt.get("rig", {})
        registration = receipt.get("registration", {})
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
                "registration_yaw_degrees": registration.get("yaw_degrees"),
                "seconds": receipt.get("seconds", {}),
                "triangles": receipt.get("output", {}).get("triangles"),
                "variant": item["variant"],
            }
        )
    return items


def build() -> dict[str, Any]:
    job_raw = (TRIAL / "job.json").read_bytes()
    [job] = json.loads((TRIAL / "jobs.json").read_bytes())["jobs"]
    run = json.loads((EVIDENCE / f"gpu-run-{job['job_id']}.json").read_bytes())
    started = _instant(job["container_started_at"])
    finished = _instant(job["container_finished_at"])
    milliseconds = (finished - started) // datetime.resolution // 1000
    items = _items()
    creatures: dict[str, list[str]] = {}
    for item in items:
        creatures.setdefault(item["creature"], []).append(item["outcome"])
    counted = sorted(name for name, outcomes in creatures.items() if "passed" in outcomes)
    return {
        "authoritative_total": "the provider's billing page, read by the operator",
        "compute": {
            "gpu": run["gpu"],
            "instance_type": run["instance_type"],
            "provider": run["provider"],
            "rate_cents_per_hour": run["rate_cents_per_hour"],
            "rate_source": run["rate_source"],
        },
        "creatures": {
            name: {"counted": name in counted, "outcomes": outcomes}
            for name, outcomes in sorted(creatures.items())
        },
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
        "kind": "exulanica.creature-rig-trial/v1",
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
        "script": "scripts/record_creature_rig_trial.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "totals": {
            "creatures": len(creatures),
            "creatures_counted": len(counted),
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
