"""Execute generated-media shared-policy acceptance and isolated SQL negative controls."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from exulanica.canonical import canonical_json  # noqa: E402

URL = "postgresql://localhost:5433/exulanica_spine_test"
SELECTOR = "tests/test_screening_currency.py::"


def file_record(path):
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "byte_size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main():
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    artifacts = args.artifacts.resolve()
    predecessor = args.predecessor.resolve()
    for path in (output, artifacts, predecessor):
        path.relative_to(ROOT)
    if output.exists() or artifacts.exists():
        raise SystemExit("Use new output and artifact paths; accepted evidence is immutable")
    prior = json.loads(predecessor.read_bytes())
    assert set(prior) == {"profile", "record", "record_sha256"}
    assert hashlib.sha256(canonical_json(prior["record"])).hexdigest() == prior["record_sha256"]
    artifacts.mkdir(parents=True)
    env = dict(os.environ, EXULANICA_TEST_DATABASE_URL=URL)
    env.pop("EXULANICA_SCREENING_EVIDENCE_DIR", None)
    commands = []

    def run(name, argv, *, extra_env=None, expected=0, failed_selector=None):
        result = subprocess.run(
            argv, cwd=ROOT, env=env | (extra_env or {}), capture_output=True, text=True, check=False
        )
        log = result.stdout + result.stderr
        log = log.replace(str(ROOT), "<worktree>")
        log = re.sub(r"/private/var/folders/[^\s\"\'\)]+", "<temporary>", log)
        log = re.sub(r"/Users/[^/\s]+", "<user>", log)
        (artifacts / f"{name}.log").write_text(log)
        commands.append(
            {
                "name": name,
                "argv": [v.replace(str(ROOT), "<worktree>") for v in argv],
                "exit_code": result.returncode,
                "expected_exit_code": expected,
            }
        )
        if result.returncode != expected:
            raise RuntimeError(f"{name}: unexpected exit {result.returncode}; inspect retained log")
        if failed_selector:
            assert any(
                line.startswith("FAILED " + failed_selector + " ")
                or line == "FAILED " + failed_selector
                for line in log.splitlines()
            ), "exact selector FAILED line absent"
        return result

    scenario = artifacts / "generated-rehearsal"
    run(
        "acceptance",
        [sys.executable, "-m", "pytest", "tests/test_screening_currency.py", "-q", "-ra"],
        extra_env={"EXULANICA_SCREENING_EVIDENCE_DIR": str(scenario)},
    )
    mutants = [
        (
            "review-binding",
            "test_receipt_input_binding_guard",
            """assert "and s.receipt_record->'privacy_inputs'=inputs" in sql
sql = sql.replace("and s.receipt_record->'privacy_inputs'=inputs", "and true")""",
        ),
        (
            "mask-input-digest",
            "test_input_digest_guard",
            """sql, count = re.subn(r"and m.input_digest=\\(select digest.*?x\\(h\\)\\)", "and true", sql, flags=re.S)
assert count == 1""",
        ),
        (
            "consent-expiry",
            "test_producer_consent_currency[expired]",
            """needle = "and c.effective_at<=p_at and (c.valid_until is null or c.valid_until>p_at)"
assert needle in sql
sql = sql.replace(needle, "and c.effective_at<=p_at")""",
        ),
    ]
    mutants.extend([
        ("claimed-outline", "test_stale_or_missing_claimed_review_inputs_do_not_authorize",
         """needle = "and sr->'silhouette'=r->'silhouette'"
assert needle in sql
sql = sql.replace(needle, "and true")"""),
        ("consent-allocation", "test_concurrent_subject_writers_refuse_duplicate_allocation",
         """needle = "and c.consent_id<>new.consent_id)"
assert needle in sql
sql = sql.replace(needle, "and false)")"""),
    ])
    controls = []
    for name, selector, mutation in mutants:
        program = (
            """import re
import pytest
from exulanica.migrations import Migration
original = Migration.sql.fget
def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0040":
"""
            + "\n".join("        " + line for line in mutation.splitlines())
            + """
    return sql
Migration.sql = property(mutated)
raise SystemExit(pytest.main(["SELECTOR", "-q", "-ra"]))
""".replace("SELECTOR", SELECTOR + selector)
        )
        program_path = artifacts / f"{name}-mutant.py"
        program_path.write_text(program)
        # These programs are retained source artifacts, so apply the project's normal checks.
        subprocess.run([sys.executable, "-m", "ruff", "check", "--fix", str(program_path)],
                       cwd=ROOT, check=False, capture_output=True)
        subprocess.run([sys.executable, "-m", "ruff", "format", str(program_path)],
                       cwd=ROOT, check=True, capture_output=True)
        subprocess.run([sys.executable, "-m", "ruff", "check", str(program_path)],
                       cwd=ROOT, check=True, capture_output=True)
        run(
            name,
            [sys.executable, str(program_path)],
            expected=1,
            failed_selector=SELECTOR + selector,
        )
        controls.append(
            {
                "name": name,
                "selector": SELECTOR + selector,
                "result": "killed; exact selector FAILED line required",
                "mutation": "subprocess-only migration property; retained SQL unchanged",
            }
        )
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    record = {
        "profile": "exulanica.screening-currency/v1",
        "tested_head": head,
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "predecessor_record": {
            "path": predecessor.relative_to(ROOT).as_posix(),
            "record_sha256": prior["record_sha256"],
        },
        "commands": commands,
        "negative_controls": controls,
        "scenario": json.loads((scenario / "scenario.json").read_bytes()),
        "artifacts": [file_record(p) for p in sorted(artifacts.rglob("*")) if p.is_file()],
        "source_files": [
            file_record(ROOT / p)
            for p in [
                "exulanica/migrations/0040_bind_geometry_admission_to_current_privacy_inputs.sql",
                "exulanica/ingest/person_state.py",
                "exulanica/ingest/personal_admission.py",
                "exulanica/ingest/privacy.py",
                "exulanica/ingest/masked_inputs.py",
                "exulanica/ingest/spine/privacy.py",
                "tests/test_screening_currency.py",
                "scripts/record_screening_currency_evidence.py",
            ]
        ],
        "limits": [
            "Isolated generated-media database rehearsal; schemas removed by test harness.",
            "Point-map writes use labelled placeholder content; no depth inference or disclosure demonstrated.",
            "No personal media, hosted models, credentials, GPU or public migration.",
            "Asset-read currency and read-versus-withdrawal races remain separate activation dependencies.",
            "Full backend/web gates are recorded separately; this record covers focused executed acceptance.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
            }
        )
    )
    print(output.relative_to(ROOT))


if __name__ == "__main__":
    main()
