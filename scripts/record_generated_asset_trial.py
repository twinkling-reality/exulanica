"""Write the evaluation record of the generated 3D pieces trial on Nebius AI Cloud.

Reads only tracked evidence under ``ml/appearance/evidence/``: the trial's per-job file (each
Serverless AI job's id, container start and finish, staged digests and outcome), each job's
``exulanica.appearance-gpu-run/v1`` record, and every request, job and receipt the jobs that ran
wrote. Writes ``docs/evaluation/2026-10-07-nebius-generated-assets-trial.json`` as an
``exulanica.digest-bound-record/v1``. Every figure is computed here from that evidence; nothing is
typed in.

Two costs per job, both at the rate the run records name. The computed cost is the container's
own seconds from start to finish; the upper bound is the run record's interval, from the first
STARTING state seen to the job's deletion, because a failed container's instance stayed up
until the job was deleted. The provider's billing page, read by the operator, is the only
authoritative total.

Run: ``.venv/bin/python scripts/record_generated_asset_trial.py``
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
TRIAL = EVIDENCE / "generated-assets-trial-1"
OUTPUT = ROOT / "docs/evaluation/2026-10-07-nebius-generated-assets-trial.json"
#: Where each route's records sit; a folder absent from the tree is simply not reported.
RUNS = {
    "trial route A": TRIAL,
    "trial route B": TRIAL / "route-b",
    "demo route A": EVIDENCE / "generated-assets-demo-1",
}


def _instant(text: str) -> datetime:
    """A UTC instant to the millisecond, as the job status states it."""
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _microdollars(rate_cents_per_hour: int, milliseconds: int) -> int:
    """Rate times milliseconds, in millionths of a dollar, rounded up."""
    return -(-rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)


def _pieces(folder: Path) -> list[dict[str, Any]]:
    requests = {
        hashlib.sha256(path.read_bytes()).hexdigest(): json.loads(path.read_bytes())
        for path in sorted((folder / "requests").glob("*.json"))
    }
    pieces = []
    for path in sorted((folder / "receipts").glob("*.json")):
        receipt = json.loads(path.read_bytes())
        request = requests[receipt["request_sha256"]]
        measured = receipt["measured"]
        piece: dict[str, Any] = {
            "glb_bytes": measured["glb_bytes"],
            "glb_sha256": receipt["output"]["sha256"],
            "look_role": request["look_role"],
            "over": receipt["verdict"]["over"],
            "receipt_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "request_sha256": receipt["request_sha256"],
            "route": request["route"],
            "size_mm": measured["size_mm"],
            "triangles": measured["triangles"],
            "variant": receipt["variant"],
            "within": receipt["verdict"]["within"],
        }
        if "thing_kind" in request:
            piece["thing_kind"] = request["thing_kind"]
        pieces.append(piece)
    return pieces


def build() -> dict[str, Any]:
    trial_jobs = json.loads((TRIAL / "jobs.json").read_bytes())
    jobs = []
    computed_total = upper_total = 0
    for job in trial_jobs["jobs"] + _demo_jobs():
        run = json.loads((EVIDENCE / f"gpu-run-{job['job_id']}.json").read_bytes())
        started = _instant(job["container_started_at"])
        finished = _instant(job["container_finished_at"])
        milliseconds = (finished - started) // datetime.resolution // 1000
        computed = _microdollars(run["rate_cents_per_hour"], milliseconds)
        computed_total += computed
        upper_total += run["cost_microdollars"]
        jobs.append(
            {
                "attempt": job["attempt"],
                "code_sha256": job["code_sha256"],
                "computed_cost_microdollars": computed,
                "container_finished_at": job["container_finished_at"],
                "container_milliseconds": milliseconds,
                "container_started_at": job["container_started_at"],
                "job_id": job["job_id"],
                "job_sha256": job["job_sha256"],
                "outcome": job["outcome"],
                "pieces": len(run["generations"]),
                "route": job["route"],
                "upper_bound_cost_microdollars": run["cost_microdollars"],
                "upper_bound_from": run["started_at"],
                "upper_bound_to": run["deleted_at"],
            }
        )
    runs = {name: _pieces(folder) for name, folder in RUNS.items() if folder.is_dir()}
    any_run = json.loads((EVIDENCE / f"gpu-run-{jobs[0]['job_id']}.json").read_bytes())
    return {
        "authoritative_total": "the provider's billing page, read by the operator",
        "compute": {
            "gpu": any_run["gpu"],
            "instance_type": any_run["instance_type"],
            "provider": any_run["provider"],
            "rate_cents_per_hour": any_run["rate_cents_per_hour"],
            "rate_source": any_run["rate_source"],
        },
        "jobs": jobs,
        "kind": "exulanica.generated-assets-trial/v1",
        "pieces": runs,
        "script": "scripts/record_generated_asset_trial.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "totals": {
            "computed_cost_microdollars": computed_total,
            "jobs": len(jobs),
            "pieces_within_every_check": sum(p["within"] for ps in runs.values() for p in ps),
            "pieces_with_receipts": sum(len(ps) for ps in runs.values()),
            "upper_bound_cost_microdollars": upper_total,
        },
    }


def _demo_jobs() -> list[dict[str, Any]]:
    path = EVIDENCE / "generated-assets-demo-1" / "jobs.json"
    return json.loads(path.read_bytes())["jobs"] if path.is_file() else []


def main() -> int:
    record = build()
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    totals = record["totals"]
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {totals}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
