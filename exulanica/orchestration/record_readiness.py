"""Execute and retain a dated, predecessor-bound frontier readiness observation.

Run with ``python -m exulanica.orchestration.record_readiness --date YYYY-MM-DD
--label NAME --predecessor docs/evaluation/PRIOR.json``. Existing records are never replaced.
Synthetic inputs and keys live only in an owned temporary directory. Retained geometry is read
under the application role in a read-only transaction; its source store is never populated here.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.graph.observations import scene_observations
from exulanica.ingest.stages import pipeline_digest
from exulanica.orchestration.dry_run import PERMITTED_DATABASE_URL, run_dry_run
from exulanica.orchestration.preflight import permitted_database_url, run_frontier_preflight
from exulanica.store.local import LocalContentAddressedStore

ROOT = Path(__file__).resolve().parents[2]
_BOWL_WORKSPACE = uuid.UUID("bdba4f95-07e3-4ff6-8c5b-eb8989ab63cb")
_BOWL_SCENE = uuid.UUID("851ca35b-31c3-560c-84f9-4e142962755b")


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _observations() -> dict[str, Any]:
    store_path = ROOT / ".exulanica/reference-baseline/runtime/blobs"
    if not store_path.is_dir():
        raise ValueError("Restore the retained reference blob store before recording readiness.")
    store = LocalContentAddressedStore(store_path)
    url = permitted_database_url(PERMITTED_DATABASE_URL)
    measured = {}
    with psycopg.connect(url, row_factory=dict_row) as connection:
        connection.execute("set transaction isolation level repeatable read read only")
        connection.execute("set local role exulanica_app")
        connection.execute(
            "select set_config('exulanica.workspace_id',%s,true)", (str(_BOWL_WORKSPACE),)
        )
        for name, limit in (("whole", None), ("first_page", 500)):
            graph = scene_observations(connection, _BOWL_WORKSPACE, _BOWL_SCENE, store, limit=limit)
            if graph is None:
                raise ValueError("The retained bowl observation graph is not readable.")
            payload = canonical_json(graph)
            measured[name] = {
                "canonical_bytes": len(payload),
                "canonical_sha256": _digest(payload),
                "bounds": graph["bounds"],
            }
            del graph, payload
    return {
        "workspace_id": str(_BOWL_WORKSPACE),
        "scene_id": str(_BOWL_SCENE),
        "database_role": "exulanica_app",
        "read_only_transaction": True,
        "measurement": measured,
        "answer_bytes_saved": measured["whole"]["canonical_bytes"]
        - measured["first_page"]["canonical_bytes"],
        "server_work_bounded": False,
    }


def _rehearsal() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="exulanica-readiness-") as temporary:
        root = Path(temporary) / "rehearsal"
        result = run_dry_run(root)
        old_database = os.environ.get("EXULANICA_DATABASE_URL")
        os.environ["EXULANICA_DATABASE_URL"] = PERMITTED_DATABASE_URL
        try:
            report = run_frontier_preflight(
                manifest_path=root / "frontier-build.json",
                photo_dir=root / "photos",
                data_dir=root / "data",
                output=root / "unused-preflight-output",
                private_key=root / "throwaway-key.pem",
            )
        finally:
            if old_database is None:
                os.environ.pop("EXULANICA_DATABASE_URL", None)
            else:
                os.environ["EXULANICA_DATABASE_URL"] = old_database
        if report["status"] != "passed":
            failed = [item["check"] for item in report["checks"] if item["status"] != "passed"]
            raise ValueError("Generated-input preflight failed: " + ", ".join(failed))
        receipt = json.loads((root / "run/frontier-receipt.json").read_bytes())
        names = ["frontier-build.json", "run/frontier-receipt.json"] + [
            f"run/evaluation-{stage}.json" for stage in ("initial", "repeat", "after-deletion")
        ]
        digests = {name: _digest((root / name).read_bytes()) for name in names}
        # Keep outcomes, not machine-specific temporary paths or the private key. Each ordinary
        # package already passed clean-process verification inside the executed demonstration.
        return {
            "status": result["status"],
            "synthetic": True,
            "hosted_model_calls": receipt["formation"]["model_calls"],
            "repeat_model_calls": receipt["repeat"]["ingest"]["model_calls"],
            "repeat_stages_run": receipt["repeat"]["ingest"]["stages_run"],
            "isolated_schema_removed": result["isolated_schema_removed"],
            "source_file_deleted": receipt["deletion"]["original_photo_file_deleted"],
            "remaining_regions": receipt["deletion"]["remaining_regions"],
            "artifact_sha256": digests,
            "packages": {
                name: {"clean_process_verification": package["clean_process_verification"]}
                for name, package in receipt["packages"].items()
            },
            "preflight": {
                "status": report["status"],
                "read_only": report["read_only"],
                "checks": [
                    {"check": item["check"], "status": item["status"]} for item in report["checks"]
                ],
            },
            "key": {
                "algorithm": "Ed25519",
                "throwaway": True,
                "mode": format((root / "throwaway-key.pem").stat().st_mode & 0o777, "04o"),
                "material_emitted": False,
            },
            "temporary_artifacts_removed_after_measurement": True,
        }


def _controls(path: Path) -> dict[str, Any]:
    """Retain separately executed evidence only after its logs and kill outcomes verify."""
    data = path.read_bytes()
    document = json.loads(data)
    runs = document["runs"]
    baselines = {run["run"]: run for run in runs if run["run"] in {"baseline", "restored-baseline"}}
    if set(baselines) != {"baseline", "restored-baseline"} or any(
        run["returncode"] != 0 for run in baselines.values()
    ):
        raise ValueError("Control evidence needs successful original and restored baselines.")
    mutants = [run for run in runs if run["run"] not in baselines]
    if not mutants or any(
        run["returncode"] != 1
        or run.get("named_test_failed", document.get("named_test_failed")) is not True
        for run in mutants
    ):
        raise ValueError("Every control must fail its named test with return code 1.")
    for run in runs:
        if _digest(Path(run["output_path"]).read_bytes()) != run["output_sha256"]:
            raise ValueError("Control output no longer matches its recorded digest.")
    for run in mutants:
        output = Path(run["output_path"]).read_text()
        selectors = run.get("selectors", [document.get("selector", "")])
        for selector in selectors:
            name = selector.split("::")[-1]
            if not name or not any(
                line.lstrip().startswith(("FAILED", "FAIL ")) and name in line
                for line in output.splitlines()
            ):
                raise ValueError("The control log does not show its named test failing.")
        mutation = run.get("mutation", document.get("mutation"))
        if not mutation or mutation.get("occurrences") != 1:
            raise ValueError("Every mutation must name one exact source occurrence.")

    def sanitized(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: sanitized(item)
                for key, item in value.items()
                if key not in {"directory", "output_path"}
            }
        if isinstance(value, list):
            return [sanitized(item) for item in value]
        if isinstance(value, str) and Path(value).is_absolute():
            return "external absolute path omitted"
        return value

    return {
        "results_file_sha256": _digest(data),
        "logs_digest_verified": True,
        "all_named_mutants_killed": True,
        "evidence": sanitized(document),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument(
        "--controls",
        type=Path,
        action="append",
        default=[],
        help="Previously executed controls result JSON; repeat for multiple runs",
    )
    args = parser.parse_args()
    if dt.date.fromisoformat(args.date).isoformat() != args.date:
        parser.error("--date must be YYYY-MM-DD")
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", args.label) is None:
        parser.error("--label must contain lowercase words or digits separated by hyphens")
    target = ROOT / "docs/evaluation" / f"{args.date}-{args.label}.json"
    if target.exists() or target.is_symlink():
        parser.error("Choose a new date/label; an existing observation cannot be overwritten")
    predecessor_path = (ROOT / args.predecessor).resolve()
    predecessor_relative = predecessor_path.relative_to(ROOT).as_posix()
    if not predecessor_relative.startswith("docs/evaluation/"):
        parser.error("--predecessor must name a record under docs/evaluation")
    predecessor = json.loads(predecessor_path.read_bytes())
    if set(predecessor) != {"profile", "record", "record_sha256"}:
        parser.error("The predecessor is not a three-field digest-bound record")
    predecessor_digest = _digest(canonical_json(predecessor["record"]))
    if predecessor_digest != predecessor["record_sha256"]:
        parser.error("The predecessor record digest does not verify")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()
    files = [
        *sorted((ROOT / "exulanica/orchestration").glob("*.py")),
        ROOT / "exulanica/graph/observations.py",
        ROOT / "exulanica/api/routes/world_read.py",
        ROOT / "web/packages/app/src/observations-api.ts",
    ]
    controls = [_controls(path) for path in args.controls]
    record = {
        "profile": "exulanica.frontier-readiness/v1",
        "date": args.date,
        "head": head,
        "pipeline_digest": pipeline_digest(),
        "database": PERMITTED_DATABASE_URL,
        "implementation_files_sha256": {
            path.relative_to(ROOT).as_posix(): _digest(path.read_bytes()) for path in files
        },
        "predecessor_record": {"path": predecessor_relative, "record_sha256": predecessor_digest},
        "milestone_inputs": {
            "authorized_personal_corpus_supplied_to_this_run": False,
            "production_signing_key_supplied_to_this_run": False,
            "existence_elsewhere": "unknown",
        },
        "synthetic_rehearsal": _rehearsal(),
        "retained_observations": _observations(),
        "executed_controls": controls,
        "limitations": [
            "No personal corpus was ingested and no production signing key was used.",
            "No hosted vision, real COLMAP, CUDA training, or depth inference was executed.",
            "Observation paging bounds the answer; the server still groups the full receipt.",
            "This command runs no suite; optional controls are separately executed evidence "
            "whose outcome and retained log digests are verified during this run.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": _digest(canonical_json(record)),
    }
    with target.open("xb") as stream:
        stream.write(canonical_json(envelope) + b"\n")
    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
