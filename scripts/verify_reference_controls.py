"""Run isolated reference-workflow mutation controls serially in the permitted test DB."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from exulanica.evaluation.reference_inputs import envelope

ROOT = Path(__file__).resolve().parents[1]
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
ADMISSION = "exulanica/ingest/reference_admission.py"
INPUTS = "exulanica/evaluation/reference_inputs.py"
CONTROLS = [
    ("manifest_digest", INPUTS, "value != envelope(record)", "False", "test_changed_source"),
    ("source_bytes", INPUTS, 'digest_file(path) != item["sha256"]', "False", "test_changed_source"),
    (
        "frozen_split",
        INPUTS,
        "if manifest.exists() and manifest.read_bytes() != payload:",
        "if False:",
        "test_preparation",
    ),
    (
        "human_attestation",
        ADMISSION,
        "attestation != HUMAN_ATTESTATION",
        "False",
        "test_review_refuses",
    ),
    ("named_human", ADMISSION, "not reviewed_by_name.strip()", "False", "test_review_refuses"),
    (
        "review_time",
        ADMISSION,
        "if reviewed_at > dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5):",
        "if False:",
        "test_review_refuses",
    ),
    (
        "client_actor_refusal",
        "exulanica/api/routes/reconstruction_admission.py",
        'class BenchmarkReview(BaseModel):\n    model_config = ConfigDict(extra="forbid")',
        'class BenchmarkReview(BaseModel):\n    model_config = ConfigDict(extra="ignore")',
        "test_review_needs_session",
    ),
    (
        "benchmark_class",
        ADMISSION,
        'source_manifest.get("corpus_class") == "benchmark"',
        "True",
        "test_review_refuses",
    ),
    (
        "retrieval_date",
        ADMISSION,
        'source_manifest["retrieval_date"] == retrieval_date',
        "True",
        "test_review_refuses",
    ),
    ("complete_manifest", ADMISSION, "if not valid_manifest:", "if False:", "test_review_refuses"),
    (
        "disjoint_heldout",
        ADMISSION,
        "and not set(train) & set(heldout)",
        "and True",
        "test_review_refuses",
    ),
    ("capture_bytes", ADMISSION, "or capture.blob_id.hex != expected", "", "test_review_refuses"),
    (
        "authenticated_actor",
        ADMISSION,
        "reviewed_by=actor,",
        "reviewed_by=uuid.UUID(int=1),",
        "test_exact_review",
    ),
    (
        "retained_split",
        ADMISSION,
        '"source_manifest": source_manifest,',
        '"source_manifest": {},',
        "test_exact_review",
    ),
    (
        "source_composition_bytes",
        "exulanica/orchestration/reference_world.py",
        "or capture.blob_id.hex != expected_sha256",
        "",
        "test_reference_source_topology",
    ),
]


def main() -> int:
    env = {k: v for k, v in os.environ.items() if not k.startswith("EXULANICA_")}
    env.update(EXULANICA_TEST_DATABASE_URL=DATABASE, PYTHONDONTWRITEBYTECODE="1")
    # Created before the baseline subprocess, not merely before the write. .exulanica is gitignored
    # and no tracked file recreates it, so a fresh clone has no such directory, and the baseline log
    # is only written after the isolated suite has run: a mkdir any later would discard minutes of
    # pytest work to a FileNotFoundError. (MEASURED 2026-09-07: the unguarded write raised
    # FileNotFoundError on a fresh-clone-shaped ROOT and left no baseline log at all.)
    output_root = ROOT / ".exulanica/reference-baseline"
    output_root.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix="exulanica-reference-controls-") as temporary:
        work = Path(temporary)
        for directory in ("exulanica", "tests"):
            shutil.copytree(
                ROOT / directory, work / directory, ignore=shutil.ignore_patterns("__pycache__")
            )
        shutil.copy(ROOT / "pyproject.toml", work / "pyproject.toml")
        env["PYTHONPATH"] = str(work)
        command = [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_reference_inputs.py",
            "tests/test_reference_admission.py",
            "tests/test_reference_world.py",
        ]
        baseline = subprocess.run(
            command, cwd=work, env=env, capture_output=True, text=True, check=False
        )
        baseline_output = baseline.stdout + baseline.stderr
        (output_root / "control-baseline.log").write_text(baseline_output)
        if baseline.returncode:
            raise RuntimeError("unmodified isolated baseline failed; no mutant result is valid")
        for name, filename, old, new, selector in CONTROLS:
            path = work / filename
            original = path.read_text()
            if old not in original:
                raise ValueError(f"mutation target missing: {name}")
            path.write_text(original.replace(old, new, 1))
            try:
                result = subprocess.run(
                    [*command, "-k", selector],
                    cwd=work,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            finally:
                path.write_text(original)
            output = result.stdout + result.stderr
            (output_root / f"control-{name}.log").write_text(output)
            records.append(
                {
                    "mutation": name,
                    "production_file": filename,
                    "replace": old,
                    "with": new,
                    "test_selector": selector,
                    "returncode": result.returncode,
                    "killed": result.returncode == 1
                    and "FAILED tests/" in output
                    and "ERROR tests/" not in output,
                    "observed_output_sha256": hashlib.sha256(output.encode()).hexdigest(),
                }
            )
            print(name, result.returncode, flush=True)
    record = {
        "profile": "exulanica.reference-workflow-negative-controls/v1",
        "date": "2026-09-05",
        "isolated_source_copy": True,
        "database": DATABASE,
        "database_creation_allowed": False,
        "baseline_returncode": baseline.returncode,
        "baseline_output_sha256": hashlib.sha256(baseline_output.encode()).hexdigest(),
        "records": records,
    }
    destination = ROOT / "docs/evaluation/2026-09-05-reference-workflow-negative-controls.json"
    destination.write_text(json.dumps(envelope(record), indent=2) + "\n")
    return 0 if all(row["killed"] for row in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
