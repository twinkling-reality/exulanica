#!/usr/bin/env python3
"""Run a serialized fixture campaign and retain an append-only, digest-bound record."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from exulanica.canonical import canonical_json, sha256_of_canonical

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_world_read_evidence.py"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--name", required=True, help="Unique dated basename ending world-read-recipient-evidence"
    )
    parser.add_argument("--previous-attempt", type=Path)
    parser.add_argument(
        "--predecessor",
        type=Path,
        default=Path("docs/evaluation/2026-09-08-verification-world-read-recipient-evidence.json"),
    )
    args = parser.parse_args()
    if not re.fullmatch(
        r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9-]*world-read-recipient-evidence", args.name
    ):
        parser.error("use a unique dated evidence basename")
    destination = ROOT / "docs/evaluation" / (args.name + ".json")
    artifacts = ROOT / "docs/evaluation/artifacts" / args.name
    if destination.exists() or artifacts.exists():
        parser.error("evidence paths already exist; choose a new name")
    artifacts.mkdir(parents=True)
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "EXULANICA_TEST_DATABASE_URL": "postgresql://localhost:5433/exulanica_spine_test",
    }
    commands = []

    def run(label: str, argv: list[str], extra: dict[str, str] | None = None) -> tuple[int, str]:
        print(label, flush=True)
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env={**env, **(extra or {})},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        output = result.stdout.replace(str(ROOT), "<worktree>")
        output = re.sub(r"/Users/[^\s'\"]+", "<local-path>", output)
        output = re.sub(r"/private/var/folders/[^\s'\"]+", "<fixture-path>", output)
        output = output.replace("pytest-of-" + Path.home().name, "pytest-of-fixture")
        (artifacts / (label + ".log")).write_text(output)
        commands.append(
            {
                "label": label,
                "argv": ["<python>" if a == sys.executable else a for a in argv],
                "exit_code": result.returncode,
            }
        )
        return result.returncode, output

    status, _ = run(
        "recipient-path",
        [sys.executable, "-m", "pytest", TEST, "-q"],
        {"WORLD_READ_RECIPIENT_ARTIFACTS": str(artifacts)},
    )
    if status:
        raise SystemExit("recipient fixture failed; logs retained, no acceptance record")
    controls = [
        ("consent", "consent_digest_mismatch", "test_recipient_consent_expiry_and_record_movement"),
        (
            "lineage",
            "geometry_output_mismatch",
            "test_recipient_rejects_omission_and_output_mismatch",
        ),
        ("mask", "stale_derivative_lineage", "test_recipient_masked_sources_and_stale_lineage"),
        (
            "mask-input",
            "mask_input_commitment_mismatch",
            "test_recipient_masked_sources_and_stale_lineage",
        ),
        (
            "trained",
            "trained_output_mismatch",
            "test_recipient_trained_publication_and_source_controls",
        ),
    ]
    results = []
    for name, reason, test in controls:
        plugin = artifacts / ("mutant_" + name.replace("-", "_") + ".py")
        plugin.write_text(
            '"""Executed negative control: disable one exact recipient check."""\n'
            "def pytest_sessionstart(session: object) -> None:\n"
            "    import exulanica.graph.world_read_verification as verifier\n"
            "    original = verifier.require\n"
            "    def broken(condition: bool, reason: str) -> None:\n"
            f"        if reason != {reason!r}:\n"
            "            original(condition, reason)\n"
            "    verifier.require = broken\n"
        )
        selector = TEST + "::" + test
        status, output = run(
            "control-" + name,
            [sys.executable, "-m", "pytest", "-q", "-p", plugin.stem, selector],
            {"PYTHONPATH": str(ROOT) + os.pathsep + str(artifacts)},
        )
        if status != 1 or ("FAILED " + selector) not in output or "DID NOT RAISE" not in output:
            raise SystemExit("control did not fail its named selector; logs retained")
        results.append(
            {
                "name": name,
                "disabled_check": reason,
                "selector": selector,
                "exact_failed_line": "FAILED " + selector,
            }
        )
    plugin = artifacts / "mutant_unsupported_receipt.py"
    plugin.write_text(
        '"""Executed control: restore unchecked receipt projection."""\n'
        "def pytest_sessionstart(session: object) -> None:\n"
        "    import exulanica.graph.world_read_evidence as evidence\n"
        "    def unchecked(value: object, expected_profile: str) -> None:\n"
        "        return None\n"
        "    evidence.receipt_problem = unchecked\n"
    )
    selector = TEST + "::test_recipient_route_handles_unsupported_manifest_candidates[array]"
    status, output = run(
        "control-unsupported-receipt",
        [sys.executable, "-m", "pytest", "-q", "-p", plugin.stem, selector],
        {"PYTHONPATH": str(ROOT) + os.pathsep + str(artifacts)},
    )
    if status != 1 or ("FAILED " + selector) not in output or "AttributeError" not in output:
        raise SystemExit("unsupported-receipt control did not reproduce its named route failure")
    results.append(
        {
            "name": "unsupported-receipt",
            "disabled_check": "supported_receipt_validation",
            "selector": selector,
            "exact_failed_line": "FAILED " + selector,
            "failure_discriminator": "AttributeError",
        }
    )
    gates = [
        ("backend", [sys.executable, "-m", "pytest", "-q"]),
        ("ruff", [sys.executable, "-m", "ruff", "check", "."]),
        ("imports", [str(Path(sys.executable).parent / "lint-imports"), "--no-cache"]),
        ("web-typecheck", ["pnpm", "--dir", "web", "run", "typecheck"]),
        ("web-boundaries", ["pnpm", "--dir", "web", "run", "boundaries"]),
        ("web-tests", ["pnpm", "--dir", "web", "run", "test"]),
    ]
    for label, argv in gates:
        status, _ = run(label, argv)
        if status:
            raise SystemExit(label + " gate failed; logs retained, no acceptance record")
    predecessor = (ROOT / args.predecessor).resolve()
    if not predecessor.is_relative_to(ROOT / "docs/evaluation"):
        parser.error("predecessor must be a retained evaluation record")
    previous = json.loads(predecessor.read_bytes())
    assert sha256_of_canonical(previous["record"]).hex() == previous["record_sha256"]
    files = []
    for path in sorted(artifacts.iterdir()):
        if not path.is_file():
            continue
        data = path.read_bytes()
        files.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": hashlib.sha256(data).hexdigest(),
                "byte_size": len(data),
            }
        )
    if args.previous_attempt:
        previous_root = (ROOT / args.previous_attempt).resolve()
        if not previous_root.is_relative_to(ROOT / "docs/evaluation/artifacts"):
            parser.error("previous attempt must be a retained artifact directory")
        for path in sorted(previous_root.iterdir()):
            if path.is_file():
                data = path.read_bytes()
                files.append(
                    {
                        "path": str(path.relative_to(ROOT)),
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "byte_size": len(data),
                    }
                )
    for command in commands:
        command["argv"] = [
            "<venv>/lint-imports" if a.endswith("/lint-imports") else a for a in command["argv"]
        ]
    record = {
        "profile": "exulanica.world-read-recipient-campaign/v1",
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "predecessor_record": {
            "path": str(predecessor.relative_to(ROOT)),
            "record_sha256": previous["record_sha256"],
        },
        "fixture": "Generated photos and scripted point/pose/training fixtures; no personal media or GPU",
        "commands": commands,
        "controls": results,
        "artifacts": files,
        "limits": [
            "internal_only; no redistribution authority or training permission",
            "offline recipients cannot discover later withdrawals",
            "legacy missing mask snapshots need separate producer retention; no inferred backfill",
            "retained public is not migrated; no real-data activation",
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
    # The newly generated envelope must itself pass retained-record checks.
    status, _ = run(
        "post-generation-records",
        [sys.executable, "-m", "pytest", "-q", "tests/test_retained_evaluation_records.py"],
    )
    if status:
        raise SystemExit("post-generation validation failed; immutable record and log retained")
    print(str(destination.relative_to(ROOT)), flush=True)


if __name__ == "__main__":
    main()
