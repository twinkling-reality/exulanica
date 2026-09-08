"""Replay labelled saved fixtures with no database environment in isolated child processes."""

import json
import os
import subprocess
import sys
from pathlib import Path

from exulanica.canonical import canonical_json

DIRECTORY = Path(__file__).resolve().parent
ROOT = DIRECTORY.parents[3]
CASES = [
    "route-bundle",
    "consent-before-expiry",
    "consent-after-expiry",
    "masked-route-bundle",
    "trained-route-bundle",
    "place-bundle",
    "unresolved-place-bundle",
    "withdrawn-recorded-bundle",
    "legacy-protocol-fixture",
    "stale-mask-recorded-bundle",
]
CASES += [
    f"unsupported-{case}-{state}-route"
    for case in ("array", "null", "unsupported", "nested")
    for state in ("with-valid", "without-valid")
]
REPORT = []
for name in CASES:
    path = DIRECTORY / (name + ".json")
    envelope = json.loads(path.read_bytes())
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/verify_world_read_recipient_evidence.py"),
            str(path),
            "--at",
            "2026-09-08T00:00:00Z",
            "--expected-bundle-sha256",
            envelope["bundle_sha256"],
        ],
        cwd="/tmp",
        env={k: v for k, v in os.environ.items() if "DATABASE" not in k},
        capture_output=True,
        text=True,
    )
    if name == "stale-mask-recorded-bundle":
        assert result.returncode == 1 and "stale_derivative_lineage" in result.stderr
        outcome = {"rejected": "stale_derivative_lineage"}
    else:
        assert result.returncode == 0, result.stderr
        outcome = json.loads(result.stdout)
    output = DIRECTORY / ("replay-" + name + ".json")
    assert not output.exists(), "replay results are append-only"
    output.write_bytes(canonical_json(outcome))
    REPORT.append(
        {
            "fixture": name,
            "exit_code": result.returncode,
            "expected_bundle_sha256": envelope["bundle_sha256"],
            "evaluation": output.name,
        }
    )
REPORT_PATH = DIRECTORY / "clean-process-replay.json"
assert not REPORT_PATH.exists()
REPORT_PATH.write_bytes(
    canonical_json(
        {
            "database_environment": "removed",
            "working_directory": "outside_repository",
            "cases": REPORT,
        }
    )
)
print("Verified 18 saved fixtures in isolated child processes")
