"""Execute isolated training negative controls: run directly, never mutate the working tree."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exulanica.env import env_get, env_name

CONTROLS = (
    (
        "empty-log-default-deny",
        "exulanica/consent/training.py",
        "    if not exact:\n        return False",
        "    if not exact:\n        return True",
        "tests/test_training_consent.py::test_an_empty_log_and_a_different_licensee_never_grant_training",
    ),
    (
        "withdrawal-dominates-regrant",
        "exulanica/consent/training.py",
        '    if any(r.decision == "withdrawn" for r in relevant):',
        "    if False:",
        "tests/test_training_consent.py::test_withdrawal_dominates_later_grants_and_a_new_term",
    ),
    (
        "owner-grant-required",
        "exulanica/world_package/dataset.py",
        '        if not training_is_granted(receipts, subject_id="package-owner", '
        "terms=terms, at=at):",
        "        if False:",
        "tests/test_world_package_dataset.py::test_training_export_requires_opt_in_even_without_people",
    ),
    (
        "unmasked-person-refused",
        "exulanica/world_package/dataset.py",
        "                if not granted:",
        "                if False:",
        "tests/test_world_package_dataset.py::test_training_export_refuses_unconsented_unmasked_person",
    ),
    (
        "screening-digest-bound",
        "exulanica/world_package/training_inputs.py",
        "s.receipt_digest=%s",
        "%s is not null",
        "tests/test_training_inputs.py::test_invented_screening_cannot_authorize_an_export",
    ),
    (
        "source-mutations-serialize-with-export",
        "exulanica/migrations/0039_training_is_a_separate_permission.sql",
        "    perform pg_advisory_xact_lock_shared(hashtextextended('training-source:' "
        "|| target_workspace::text, 0));",
        "    perform 1;",
        "tests/test_training_consent.py::"
        "test_a_source_mutation_waits_for_an_export_in_its_workspace_only",
    ),
    (
        "recovered-calibration-is-exact",
        "exulanica/world_package/training_inputs.py",
        '            if material["camera"] != decimal_projection(expected_camera) or material[\n'
        '                "calibration"\n'
        '            ] != decimal_projection(camera["calibration"]):',
        "            if False:",
        "tests/test_training_inputs.py::"
        "test_retained_scene_exports_exact_cameras_and_refuses_invented_calibration",
    ),
)


def run_controls(output: Path) -> dict:
    # Read before the environment is scrubbed below, so the isolated suite migrates into the
    # database the operator configured rather than a fixed one.
    database = env_get("TEST_DATABASE_URL")
    if database is None:
        raise RuntimeError(f"set {env_name('TEST_DATABASE_URL')} to a scratch PostgreSQL database")
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="exulanica-training-controls-") as directory:
        work = Path(directory)
        for name in ("exulanica", "tests", "docs"):
            shutil.copytree(root / name, work / name, ignore=shutil.ignore_patterns("__pycache__"))
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copy(root / name, work / name)
        env = {key: value for key, value in os.environ.items() if not key.startswith("EXULANICA_")}
        env.update(
            PYTHONPATH=str(work),
            PYTHONDONTWRITEBYTECODE="1",
            EXULANICA_TEST_DATABASE_URL=database,
            EXULANICA_REQUIRE_POSTGRES="1",
        )
        imported = subprocess.run(
            [sys.executable, "-c", "import exulanica; print(exulanica.__file__)"],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if Path(imported).resolve().parent != (work / "exulanica").resolve():
            raise RuntimeError("negative controls did not import the isolated package")

        def execute(selectors):
            return subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=short", *selectors],
                cwd=work,
                env=env,
                capture_output=True,
                text=True,
            )

        baseline = execute([control[4] for control in CONTROLS])
        if baseline.returncode:
            raise RuntimeError("isolated baseline failed:\n" + baseline.stdout + baseline.stderr)
        print("isolated baseline passed", flush=True)
        records = []
        for name, relative, old, new, selector in CONTROLS:
            path = work / relative
            original = path.read_text()
            if original.count(old) != 1:
                raise RuntimeError(f"{name}: mutation must match exactly once")
            try:
                path.write_text(original.replace(old, new, 1))
                result = execute([selector])
            finally:
                path.write_text(original)
            combined = result.stdout + result.stderr
            test_name = selector.split("::")[-1]
            killed = result.returncode != 0 and any(
                line.startswith("FAILED ") and test_name in line for line in combined.splitlines()
            )
            records.append(
                {
                    "name": name,
                    "selector": selector,
                    "killed": killed,
                    "returncode": result.returncode,
                    "output": combined,
                }
            )
            print(f"{name}: {'killed' if killed else 'SURVIVED'}", flush=True)
        restored = execute([control[4] for control in CONTROLS])
        report = {
            "baseline_passed": True,
            "restored_passed": restored.returncode == 0,
            "controls": records,
            "all_killed": all(r["killed"] for r in records),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n")
        if not report["all_killed"] or not report["restored_passed"]:
            raise RuntimeError(f"negative controls did not pass; see {output}")
        return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run_controls(parser.parse_args().output)
