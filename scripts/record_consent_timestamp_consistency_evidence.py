#!/usr/bin/env python3
"""Retain generated-fixture timestamp evidence without rewriting accepted records."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from exulanica.canonical import canonical_json, sha256_of_canonical

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_consent_timestamp_consistency.py"
SELECTOR = TEST + "::test_default_time_sql_receipt_uses_one_instant"
BASE = "802f902c3cacb631ab80bf43f4348ddbe67734a2"
PREDECESSOR = "docs/evaluation/2026-09-08-world-read-recipient-integration.json"


def normalize(text):
    text = text.replace(str(ROOT), "<worktree>").replace(sys.executable, "<python>")
    text = re.sub(r"/Users/[^\s'\"]+", "<local-path>", text)
    text = re.sub(r"/(?:private/)?var/folders/[^\s'\"]+", "<fixture-path>", text)
    return text.replace("pytest-of-" + Path.home().name, "pytest-of-fixture")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True)
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--previous-attempt", action="append", default=[])
    parser.add_argument("--slot-confirmed", action="store_true", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"2026-09-[0-9]{2}-[a-z0-9-]+consent-timestamp-consistency", args.name):
        parser.error("use a unique dated consent-timestamp-consistency name")
    artifacts = ROOT / "docs/evaluation/artifacts" / args.name
    destination = ROOT / "docs/evaluation" / (args.name + ".json")
    if artifacts.exists() or destination.exists():
        parser.error("choose fresh paths; previous attempts are immutable")
    artifacts.mkdir(parents=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "EXULANICA_TEST_DATABASE_URL": "postgresql://localhost:5433/exulanica_spine_test",
    }
    commands = []

    def run(label, argv, extra=None):
        print(label, flush=True)
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env={**env, **(extra or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = normalize(result.stdout)
        (artifacts / (label + ".log")).write_text(output)
        commands.append(
            {"label": label, "argv": [normalize(a) for a in argv], "exit_code": result.returncode}
        )
        (artifacts / "commands.json").write_bytes(canonical_json(commands))
        return result.returncode, output

    if args.baseline:
        status, output = run(
            "baseline",
            [sys.executable, "-m", "pytest", "-q", SELECTOR],
            {"CONSENT_TIMESTAMP_ARTIFACTS": str(artifacts)},
        )
        assert status == 1 and "FAILED " + SELECTOR in output
        assert "two-clock effective_at mismatch" in output
        print("Expected baseline mismatch retained", flush=True)
        return

    for label, argv in [
        (
            "locked-environment",
            ["uv", "sync", "--locked", "--extra", "pose", "--extra", "reconstruction"],
        ),
        ("targeted", [sys.executable, "-m", "pytest", "-q", TEST]),
    ]:
        status, _ = run(label, argv, {"CONSENT_TIMESTAMP_ARTIFACTS": str(artifacts)})
        if status:
            raise SystemExit(label + " failed; attempt retained")
    plugin = artifacts / "mutant_two_clocks.py"
    plugin.write_text(
        '"""Restore exactly the baseline record_consent writer in this child process."""\n'
        "def pytest_sessionstart(session):\n"
        "    import ast\n"
        "    import subprocess\n"
        "    from exulanica.ingest import person_review\n"
        f"    source = subprocess.check_output(['git', 'show', '{BASE}:exulanica/ingest/person_review.py'], text=True)\n"
        "    tree = ast.parse(source)\n"
        "    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'record_consent')\n"
        "    exec(compile(ast.Module(body=[function], type_ignores=[]), '<baseline-writer>', 'exec'), person_review.__dict__)\n"
    )
    status, output = run(
        "negative-control",
        [sys.executable, "-m", "pytest", "-q", "-p", plugin.stem, SELECTOR],
        {"PYTHONPATH": str(ROOT) + os.pathsep + str(artifacts)},
    )
    assert status == 1 and "FAILED " + SELECTOR in output
    assert "two-clock effective_at mismatch" in output
    for label, argv in [
        ("backend", [sys.executable, "-m", "pytest", "-q"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("imports", [str(Path(sys.executable).parent / "lint-imports"), "--no-cache"]),
        ("web-typecheck", ["pnpm", "--dir", "web", "run", "typecheck"]),
        ("web-boundaries", ["pnpm", "--dir", "web", "run", "boundaries"]),
        ("web-tests", ["pnpm", "--dir", "web", "run", "test"]),
    ]:
        status, _ = run(label, argv)
        if status:
            raise SystemExit(label + " failed; attempt retained")
    previous = json.loads((ROOT / PREDECESSOR).read_bytes())
    assert sha256_of_canonical(previous["record"]).hex() == previous["record_sha256"]
    files = []
    for folder in [artifacts, *(ROOT / p for p in args.previous_attempt)]:
        if not folder.resolve().is_relative_to(ROOT / "docs/evaluation/artifacts"):
            parser.error("previous attempt must be under evaluation artifacts")
        for path in sorted(folder.iterdir()):
            if path.is_file():
                data = path.read_bytes()
                files.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "byte_size": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
    record = {
        "profile": "exulanica.consent-timestamp-consistency/v1",
        "source_base": BASE,
        "tested_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "predecessor_record": {"path": PREDECESSOR, "record_sha256": previous["record_sha256"]},
        "serialized_slot": "Orchestrator confirmed exclusive ownership before database mutation",
        "commands": commands,
        "artifacts": files,
        "negative_control": {
            "selector": SELECTOR,
            "exact_failed_line": "FAILED " + SELECTOR,
            "reason": "two-clock effective_at mismatch",
        },
        "limits": [
            "Generated photographs; scripted point maps and pose publication, no GPU or hosted models",
            "Legacy disagreement wire fixture is not a database repair or backfill",
            "Any unavailable historical receipt still rejects its supplied chain",
            "No migration, retained-public activation, real personal rows, merge or push",
        ],
    }
    destination.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": sha256_of_canonical(record).hex(),
            }
        )
    )
    # Do not mutate the now-bound command inventory or logs while checking the final envelope.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_retained_evaluation_records.py"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    (artifacts / "post-final-envelope-check.log").write_text(normalize(result.stdout))
    if result.returncode:
        raise SystemExit("Post-generation checks failed; envelope and failure retained")
    print(str(destination.relative_to(ROOT)), flush=True)


if __name__ == "__main__":
    main()
