"""Execute asset-read route evidence and exact-selector controls without replacing history."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "postgresql://localhost:5433/exulanica_spine_test"
SELECTOR = "tests/test_asset_read_currency.py::"


def canonical(value: object) -> bytes:
    if isinstance(value, float):
        raise ValueError("floats are not permitted")
    if isinstance(value, dict):
        for item in value.values():
            canonical(item)
    elif isinstance(value, list):
        for item in value:
            canonical(item)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def binding(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": hashlib.sha256(content).hexdigest(),
        "byte_size": len(content),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--full-gates", action="store_true")
    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    artifacts = (ROOT / args.artifacts).resolve()
    output.relative_to(ROOT / "docs/evaluation")
    artifacts.relative_to(ROOT / "docs/evaluation")
    if output.exists() or artifacts.exists():
        raise FileExistsError("choose fresh paths; accepted and intermediate evidence is retained")
    artifacts.mkdir(parents=True)
    predecessor = ROOT / "docs/evaluation/2026-09-08-screening-currency-integration.json"
    prior = json.loads(predecessor.read_bytes())
    assert set(prior) == {"profile", "record", "record_sha256"}
    assert hashlib.sha256(canonical(prior["record"])).hexdigest() == prior["record_sha256"]
    env = dict(os.environ, EXULANICA_TEST_DATABASE_URL=URL, PYTHONPATH=str(ROOT))
    env.pop("EXULANICA_ASSET_EVIDENCE_DIR", None)
    commands = []

    def run(
        name: str,
        argv: list[str],
        *,
        expected: int = 0,
        failed: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> None:
        print(name, flush=True)
        result = subprocess.run(
            argv, cwd=ROOT, env=env | (extra or {}), capture_output=True, text=True, check=False
        )
        log = (result.stdout + result.stderr).replace(str(ROOT), "<worktree>")
        (artifacts / f"{name}.log").write_text(log)
        commands.append(
            {
                "name": name,
                "argv": argv,
                "exit_code": result.returncode,
                "expected_exit_code": expected,
            }
        )
        if result.returncode != expected:
            raise RuntimeError(f"{name} returned {result.returncode}; inspect retained log")
        if failed:
            assert any(
                line == "FAILED " + failed or line.startswith("FAILED " + failed + " ")
                for line in log.splitlines()
            ), "own exact selector FAILED line missing"

    run(
        "acceptance",
        [sys.executable, "-m", "pytest", "tests/test_asset_read_currency.py", "-q", "-ra"],
        extra={"EXULANICA_ASSET_EVIDENCE_DIR": str(artifacts / "generated-routes")},
    )
    run(
        "training-order",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_training_export_postgres.py::test_training_export_and_presentation_writer_share_a_lock_order",
            "-q",
            "-ra",
        ],
    )
    mutants = [
        (
            "mask-lineage",
            "test_changed_outline_rebuild_does_not_revive_geometry",
            "sql",
            "and privacy_mask_matches(p_workspace,c.capture_id,m.artifact_id,inputs)",
            "and true",
        ),
        (
            "point-lineage",
            "test_changed_outline_rebuild_does_not_revive_geometry",
            "sql",
            "if not found or not asset_screening_allows(p_workspace,s.capture_id,s.screening_id,p_at)",
            "return true;\n if not found or not asset_screening_allows(p_workspace,s.capture_id,s.screening_id,p_at)",
        ),
        (
            "delivery-lock",
            "test_reader_waits_for_prior_writer_and_later_writer_retries",
            "sql",
            "perform pg_advisory_xact_lock(119622341);",
            "null;",
        ),
        (
            "original-policy",
            "test_original_saved_urls_refuse_required_mask_and_ranges",
            "python",
            "",
            "",
        ),
        ("final-buffer-check", "test_final_check_sees_edit_during_buffer_read", "python", "", ""),
    ]
    mutants.append(
        (
            "training-lock-order",
            "tests/test_training_export_postgres.py::test_training_export_and_presentation_writer_share_a_lock_order",
            "sql",
            "perform pg_advisory_xact_lock_shared(\n    hashtextextended('training-source:' || p_workspace::text, 0));\n  perform pg_advisory_xact_lock(hashtextextended('privacy-currency:' || p_workspace::text, 0));",
            "perform pg_advisory_xact_lock(hashtextextended('privacy-currency:' || p_workspace::text, 0));\n  perform pg_advisory_xact_lock_shared(\n    hashtextextended('training-source:' || p_workspace::text, 0));",
        )
    )
    controls = []
    for name, selector, kind, before, after in mutants:
        exact_selector = selector if selector.startswith("tests/") else SELECTOR + selector
        if kind == "sql":
            before_literal = (
                "(\n"
                + "\n".join(repr(before[i : i + 60]) for i in range(0, len(before), 60))
                + "\n)"
            )
            after_literal = (
                "(\n" + "\n".join(repr(after[i : i + 60]) for i in range(0, len(after), 60)) + "\n)"
            )
            program = f"""import pytest
from exulanica.migrations import Migration
original = Migration.sql.fget
BEFORE = {before_literal}
AFTER = {after_literal}

def mutated(self: Migration) -> str:
    sql = original(self)
    if self.version == "0041":
        assert BEFORE in sql
        sql = sql.replace(BEFORE, AFTER)
    return sql

Migration.sql = property(mutated)
SELECTOR = {exact_selector!r}  # noqa: E501
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
"""
        else:
            program = f"""import pytest
from exulanica.api.routes import evidence

def bypass(*args: object, **kwargs: object) -> None:
    pass

evidence._authorize_original = bypass
SELECTOR = {exact_selector!r}  # noqa: E501
raise SystemExit(pytest.main([SELECTOR, "-q", "-ra"]))
"""
        path = artifacts / f"{name}-mutant.py"
        path.write_text(program)
        for argv in (
            [sys.executable, "-m", "ruff", "check", "--fix", str(path)],
            [sys.executable, "-m", "ruff", "format", str(path)],
            [sys.executable, "-m", "ruff", "check", str(path)],
        ):
            subprocess.run(argv, cwd=ROOT, check="--fix" not in argv, capture_output=True)
        run(name, [sys.executable, str(path)], expected=1, failed=exact_selector)
        controls.append(
            {
                "name": name,
                "selector": exact_selector,
                "result": "killed",
                "scope": "subprocess memory only; original files unchanged",
            }
        )
    if args.full_gates:
        for name, argv in [
            (
                "environment",
                ["uv", "sync", "--locked", "--extra", "pose", "--extra", "reconstruction"],
            ),
            ("backend", ["uv", "run", "pytest"]),
            ("ruff", ["uv", "run", "ruff", "check", "."]),
            ("imports", ["uv", "run", "lint-imports"]),
            ("typecheck", ["pnpm", "--dir", "web", "run", "typecheck"]),
            ("boundaries", ["pnpm", "--dir", "web", "run", "boundaries"]),
            ("web", ["pnpm", "--dir", "web", "run", "test"]),
        ]:
            run(name, argv)
    source_files = [
        "exulanica/api/routes/evidence.py",
        "exulanica/api/routes/graph.py",
        "exulanica/api/routes/world_read.py",
        "exulanica/graph/asset_read_policy.py",
        "exulanica/graph/geometry.py",
        "exulanica/graph/scene_geometry.py",
        "exulanica/world/repository.py",
        "exulanica/migrations/0041_guard_asset_reads_with_current_permission.sql",
        "tests/test_asset_read_currency.py",
        "tests/test_training_export_postgres.py",
        "tests/test_world_style_postgres.py",
        "docs/asset-read-currency.md",
        "scripts/record_asset_read_currency_evidence.py",
    ]
    record = {
        "profile": "exulanica.asset-read-currency/v1",
        "status": "executed",
        "tested_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "predecessor_record": {
            "path": predecessor.relative_to(ROOT).as_posix(),
            "record_sha256": prior["record_sha256"],
        },
        "checkpoint_record": binding(
            ROOT / "docs/evaluation/2026-09-08-checkpoint-asset-read-currency.json"
        ),
        "approval_commit": "6270115",
        "fixture_assertion_approval_commit": "6d12621",
        "serialized_suite_slot_reserved": True,
        "commands": commands,
        "negative_controls": controls,
        "full_gates_executed": args.full_gates,
        "recorder_intermediate_artifacts": [
            binding(p)
            for p in sorted(
                (
                    ROOT / "docs/evaluation/artifacts/2026-09-08-asset-read-currency-executed-01"
                ).rglob("*")
            )
            if p.is_file()
        ],
        "development_artifacts": [
            binding(p)
            for p in sorted(
                (
                    ROOT / "docs/evaluation/artifacts/2026-09-08-asset-read-currency-development-01"
                ).rglob("*")
            )
            if p.is_file()
        ],
        "sources": [binding(ROOT / source) for source in source_files],
        "artifacts": [binding(p) for p in sorted(artifacts.rglob("*")) if p.is_file()],
        "limits": [
            "Generated media only; scripted geometry payloads do not prove inference quality.",
            "Masked splat production remains unsupported; missing lineage refuses.",
            "Snapshot metadata is not permission for a later request.",
            "Final authorization precedes network delivery; later expiry/withdrawal is not retroactive.",
            "No public migration, runtime activation, personal media, hosted models, GPU spend or push.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical(record)).hexdigest(),
    }
    with output.open("xb") as stream:
        stream.write(canonical(envelope) + b"\n")
    print(output.relative_to(ROOT), flush=True)


if __name__ == "__main__":
    main()
