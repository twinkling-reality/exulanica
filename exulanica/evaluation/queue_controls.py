"""Execute queue dispatch negative controls against an isolated source copy."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
CONTROLS = (
    (
        "inherited_scope",
        "scripts/queue_reference_reconstruction.py",
        'environment["EXULANICA_SCENE_JOB_IDS"] = str(selected.job_id)',
        'environment.setdefault("EXULANICA_SCENE_JOB_IDS", str(selected.job_id))',
        "test_queue_dispatch_preserves_an_older_jobs_final_attempt",
    ),
    (
        "unscoped_launcher",
        "deploy/gsplat/run-scene-worker.sh",
        'if [[ -z "${SCOPE_CHECK//[[:space:],]/}" ]]; then',
        "if false; then",
        "test_unscoped_gpu_pass_is_refused_before_docker",
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if not k.startswith("EXULANICA_")}
    environment["EXULANICA_TEST_DATABASE_URL"] = DATABASE
    records = []
    with tempfile.TemporaryDirectory(prefix="exulanica-queue-controls-") as directory:
        work = Path(directory)
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        files.append("tests/test_reference_queue_dispatch.py")
        for relative in sorted(set(files) - {""}):
            source = ROOT / relative
            if source.is_file():
                target = work / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        environment["PYTHONPATH"] = str(work)

        def run(name: str, selector: str | None = None) -> tuple[int, str]:
            command = [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_reference_queue_dispatch.py",
            ]
            if selector:
                command.extend(["-k", selector])
            result = subprocess.run(
                command, cwd=work, env=environment, capture_output=True, text=True
            )
            output = result.stdout + result.stderr
            (args.output / f"{name}.log").write_text(output)
            return result.returncode, output

        baseline, _ = run("baseline")
        if baseline:
            raise RuntimeError(f"unmutated baseline failed; inspect {args.output / 'baseline.log'}")
        for name, relative, old, new, selector in CONTROLS:
            path = work / relative
            original = path.read_text()
            if original.count(old) != 1:
                raise ValueError(f"{name} must match exactly one production occurrence")
            path.write_text(original.replace(old, new, 1))
            try:
                code, output = run(name, selector)
            finally:
                path.write_text(original)
            killed = code == 1 and any(
                line.startswith("FAILED") and selector in line for line in output.splitlines()
            )
            records.append(
                {
                    "name": name,
                    "production_file": relative,
                    "replace": old,
                    "with": new,
                    "test": selector,
                    "returncode": code,
                    "killed": killed,
                    "output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                }
            )
        result = {
            "profile": "exulanica.queue-negative-controls/v1",
            "database": DATABASE,
            "isolated_source_copy": True,
            "baseline_passed": True,
            "controls": records,
        }
        (args.output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if all(record["killed"] for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
