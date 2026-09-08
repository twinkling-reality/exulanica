"""Execute labelled generated admission commands and retain an append-only evidence envelope."""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

import psycopg
from PIL import Image, ImageDraw
from psycopg import sql
from psycopg.conninfo import make_conninfo

from exulanica.canonical import canonical_json
from exulanica.db import Database, apply_pending
from exulanica.ingest.personal_admission_command import DATABASE_URL
from exulanica.models.manifest import MANIFEST_PATH
from exulanica.orchestration.manifest import load_build_manifest
from exulanica.orchestration.preflight import inspect_database

ROOT = Path(__file__).resolve().parents[1]
INVARIANT = "changed_region_requires_current_mask_before_geometry"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rehearse(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    photos = root / "photos"
    photos.mkdir()
    now = dt.datetime.now(dt.UTC)
    workspace, actor = str(uuid.uuid4()), str(uuid.uuid4())
    schema = "exulanica_personal_evidence_" + uuid.uuid4().hex
    url = make_conninfo(
        DATABASE_URL, hostaddr="127.0.0.1", options=f"-csearch_path={schema},public"
    )
    database = Database(url)
    commands: list[dict[str, Any]] = []
    for index in range(2):
        image = Image.new("RGB", (240, 160), (240, 220, 190 + index * 20))
        draw = ImageDraw.Draw(image)
        draw.text((8, 8), "GENERATED TEST IMAGE - NO REAL PEOPLE", fill="black")
        if index:
            draw.rectangle((20, 40, 90, 150), fill="red")
        image.save(photos / f"{index}.png")

    def command(name: str, document: dict[str, Any], expected: int = 0) -> dict[str, Any]:
        manifest_path = root / f"{name}.json"
        manifest_path.write_bytes(canonical_json(document))
        argv = [
            "uv",
            "run",
            "python",
            "-m",
            "exulanica.ingest.personal_admission_command",
            "--schema",
            schema,
            "--manifest",
            str(manifest_path.relative_to(ROOT)),
            "--photo-dir",
            str(photos.relative_to(ROOT)),
            "--data-dir",
            str((root / "data").relative_to(ROOT)),
        ]
        completed = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
        (root / f"{name}.log").write_text(completed.stdout + completed.stderr)
        commands.append(
            {
                "name": name,
                "command": shlex.join(argv),
                "exit_code": completed.returncode,
                "expected_exit_code": expected,
            }
        )
        assert completed.returncode == expected, (name, completed.stdout, completed.stderr)
        return json.loads(completed.stdout)

    with psycopg.connect(DATABASE_URL, autocommit=True) as owner:
        extensions = {r[0] for r in owner.execute("select extname from pg_extension")}
        assert {"vector", "pgcrypto", "pg_trgm", "btree_gist"} <= extensions
        owner.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
        try:
            doc = {
                "profile": "exulanica.personal-admission/v1",
                "actor_id": actor,
                "workspace_id": workspace,
                "purpose": "labelled generated admission rehearsal",
                "source": {
                    "path": "0.png",
                    "sha256": digest(photos / "0.png"),
                    "bytes": (photos / "0.png").stat().st_size,
                    "capture_id": None,
                },
                "authority": {
                    "account_authority_basis": "I generated these labelled pixels",
                    "authorized_at": (now - dt.timedelta(minutes=1)).isoformat(),
                    "valid_until": (now + dt.timedelta(hours=2)).isoformat(),
                },
                "operation": "admit",
                "authorization_id": None,
                "screening_id": None,
                "recorded_at": now.isoformat(),
                "review": "not-reviewed",
                "edits": [],
            }
            command("pending-migrations", doc, 1)
            apply_pending(database)
            for name, changes in [
                ("missing-authority", {"authority": None}),
                (
                    "expired-authority",
                    {"authority": {**doc["authority"], "valid_until": "2000-01-01T00:00:00Z"}},
                ),
                ("wrong-source-bytes", {"source": {**doc["source"], "sha256": "0" * 64}}),
            ]:
                command(name, {**doc, **changes}, 1)
            admitted = command("admit", doc)["result"]
            assert (
                command("admit-repeat", doc)["result"]["authorization_id"]
                == admitted["authorization_id"]
            )
            doc["source"]["capture_id"] = admitted["capture_id"]
            doc["authorization_id"] = admitted["authorization_id"]

            def run(name: str, operation: str, expected: int = 0, **changes: Any) -> dict[str, Any]:
                doc.update(
                    operation=operation,
                    recorded_at=dt.datetime.now(dt.UTC).isoformat(),
                    review="not-reviewed",
                    edits=[],
                )
                doc.update(changes)
                return command(name, doc, expected)

            detected = run("detection-permission", "detect")["result"]
            doc["screening_id"] = detected["screening_id"]
            run("detection-only-geometry-refusal", "geometry-check", 1)
            foreign = copy.deepcopy(doc)
            foreign["workspace_id"] = str(uuid.uuid4())
            command("cross-workspace-refusal", foreign, 1)
            empty = run("manual-no-person", "review", review="no-person")["result"]
            assert empty["eligibility_state"] == "eligible"
            doc["screening_id"] = empty["screening_id"]
            run("manual-no-person-geometry", "geometry-check")
            # The second generated image is admitted separately for frontier's two-source manifest.
            other = copy.deepcopy(doc)
            other.update(operation="admit", authorization_id=None, screening_id=None)
            other["source"] = {
                "path": "1.png",
                "sha256": digest(photos / "1.png"),
                "bytes": (photos / "1.png").stat().st_size,
                "capture_id": None,
            }
            second = command("second-admit", other)["result"]
            other["source"]["capture_id"] = second["capture_id"]
            other.update(
                operation="review", review="no-person", authorization_id=second["authorization_id"]
            )
            command("second-manual-review", other)
            edit = {
                "action": "add",
                "region_key": "a" * 64,
                "silhouette": {
                    "kind": "polygon",
                    "points": [[0, 0], [500000, 0], [500000, 500000], [0, 500000]],
                },
            }
            blocked = run("person-needs-mask", "review", review="confirmed-regions", edits=[edit])[
                "result"
            ]
            assert blocked["eligibility_state"] == "blocked"
            doc["screening_id"] = blocked["screening_id"]
            run("unmasked-person-geometry-refusal", "geometry-check", 1)
            doc["screening_id"] = detected["screening_id"]
            masked = run("build-mask", "mask")["result"]
            assert "masked_source" in masked["stages_run"]
            screened = run("rescreen", "rescreen", review="confirmed-regions")["result"]
            assert screened["eligibility_state"] == "eligible"
            doc["screening_id"] = screened["screening_id"]
            run("masked-geometry-permission", "geometry-check")
            assert not run("retry-idempotent", "retry")["result"]["stages_run"]
            edit["action"] = "confirm"
            edit["silhouette"]["points"][1][0] = 750000
            assert (
                run("changed-region", "review", review="confirmed-regions", edits=[edit])["result"][
                    "eligibility_state"
                ]
                == "blocked"
            )
            run("stale-mask-geometry-refusal", "geometry-check", 1)
            # Executed negative control: the original database-only permission accepts the stale
            # receipt. It deliberately fails the SAME invariant checked by the command above.
            control = subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    "-c",
                    "import psycopg,sys; "
                    "c=psycopg.connect(sys.argv[1]); "
                    "allowed=c.execute('select privacy_screening_allows_capture(%s,%s,%s)', "
                    "tuple(sys.argv[2:])).fetchone()[0]; "
                    f"assert not allowed, '{INVARIANT}'",
                    url,
                    workspace,
                    admitted["capture_id"],
                    screened["screening_id"],
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            (root / "negative-control.log").write_text(control.stdout + control.stderr)
            assert control.returncode != 0 and INVARIANT in control.stderr
            doc["screening_id"] = detected["screening_id"]
            assert "masked_source" in run("retry-changed-mask", "retry")["result"]["stages_run"]
            final = run("rescreen-changed-mask", "rescreen", review="confirmed-regions")["result"]
            assert final["eligibility_state"] == "eligible"
            doc["screening_id"] = final["screening_id"]
            run("final-geometry-permission", "geometry-check")
            frontier = {
                "profile": "exulanica-frontier-build/v1",
                "workspace_id": workspace,
                "actor_id": actor,
                "world_id": "atlas:default",
                "sources": [
                    {"path": p.name, "sha256": digest(p), "bytes": p.stat().st_size}
                    for p in sorted(photos.iterdir())
                ],
                "pipeline": {
                    "vision": "unavailable",
                    "depth": "moge",
                    "model_manifest_sha256": digest(MANIFEST_PATH),
                },
                "precomputed_artifacts": [],
                "adaptation": {
                    "profile_id": "origin-landscape",
                    "profile_version": 1,
                    "parameters": {"vitality": 1},
                    "proposal_provenance": {
                        "origin": "companion",
                        "origin_reference": "generated-rehearsal",
                        "model_id": "scripted-fixture-no-model-call",
                        "prompt_version": "fixture/v1",
                        "reference_ids": ["generated"],
                    },
                },
                "deletion_demo": {"path": "0.png"},
            }
            path = root / "frontier-manifest.json"
            path.write_bytes(canonical_json(frontier))
            preflight = inspect_database(url, load_build_manifest(path))
            assert preflight["screened_sources"] == 2
            (root / "frontier-database-preflight.json").write_bytes(canonical_json(preflight))
            preflight_argv = [
                "uv",
                "run",
                "python",
                "-m",
                "exulanica.orchestration.cli",
                "preflight",
                "--manifest",
                str(path.relative_to(ROOT)),
                "--photo-dir",
                str(photos.relative_to(ROOT)),
                "--data-dir",
                str((root / "data").relative_to(ROOT)),
                "--output",
                str((root / "frontier-output").relative_to(ROOT)),
                "--private-key",
                str((root / "not-supplied.pem").relative_to(ROOT)),
            ]
            preflight_run = subprocess.run(
                preflight_argv,
                env={**os.environ, "EXULANICA_DATABASE_URL": url},
                capture_output=True,
                text=True,
                check=False,
            )
            (root / "frontier-preflight.log").write_text(
                preflight_run.stdout + preflight_run.stderr
            )
            preflight_report = json.loads(preflight_run.stdout)
            assert preflight_run.returncode == 1
            checks = {c["check"]: c for c in preflight_report["checks"]}
            assert checks["database_schema_and_screening"]["status"] == "passed"
            assert checks["signing_key"]["status"] == "failed"
            commands.append(
                {
                    "name": "frontier-preflight",
                    "command": "EXULANICA_DATABASE_URL="
                    + shlex.quote(url)
                    + " "
                    + shlex.join(preflight_argv),
                    "exit_code": preflight_run.returncode,
                    "expected_exit_code": 1,
                }
            )
            return {
                "commands": commands,
                "schema": schema,
                "schema_removed": True,
                "frontier_database_preflight": preflight,
                "known_failing_sql_baseline": {
                    "invariant": INVARIANT,
                    "exit_code": control.returncode,
                    "kind": "existing SQL-only historical-receipt path",
                },
                "model_calls": 0,
                "detector": "unavailable; human review of generated fixtures",
            }
        finally:
            owner.execute(sql.SQL("drop schema {} cascade").format(sql.Identifier(schema)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--predecessor", type=Path, required=True)
    parser.add_argument("--gate-logs", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("records are append-only; choose a new output")
    result = rehearse(args.artifacts.resolve())
    selector = (
        "tests/test_personal_admission_flow.py::"
        "test_changed_region_requires_current_mask_before_geometry"
    )
    program = (
        "import inspect\n\n"
        "import exulanica.ingest.privacy as privacy\n"
        "import pytest\n\n"
        "lines = inspect.getsource(privacy).splitlines(keepends=True)\n"
        'needle = "    if not capture_mask_is_current(repository, capture_id):\\n"\n'
        "assert lines.count(needle) == 1\n"
        "start = lines.index(needle)\n"
        'assert "privacy screening is stale:" in lines[start + 2]\n'
        'assert lines[start + 4].strip() == "return screening"\n'
        'source = "".join(lines[:start] + lines[start + 4:])\n'
        'exec(compile(source, privacy.__file__, "exec"), privacy.__dict__)\n'
        "selector = (\n"
        '    "tests/test_personal_admission_flow.py::"\n'
        '    "test_changed_region_requires_current_mask_before_geometry"\n'
        ")\n"
        'raise SystemExit(pytest.main([selector, "-q"]))\n'
    )
    (args.artifacts / "command-guard-mutant.py").write_text(program)
    mutant = subprocess.run(
        ["uv", "run", "python", "-c", program],
        cwd=ROOT,
        env={**os.environ, "EXULANICA_TEST_DATABASE_URL": DATABASE_URL},
        text=True,
        capture_output=True,
        check=False,
    )
    (args.artifacts / "command-guard-mutant.log").write_text(mutant.stdout + mutant.stderr)
    assert mutant.returncode == 1 and f"FAILED {selector}" in mutant.stdout
    assert "DID NOT RAISE" in mutant.stdout
    result["command_local_negative_control"] = {
        "selector": selector,
        "exit_code": mutant.returncode,
        "mutation": "remove only require_privacy_screening mask-currency guard in subprocess memory",
        "required_failure_line": f"FAILED {selector}",
    }
    predecessor = json.loads(args.predecessor.read_bytes())
    assert (
        hashlib.sha256(canonical_json(predecessor["record"])).hexdigest()
        == predecessor["record_sha256"]
    )
    if args.gate_logs:
        shutil.copytree(args.gate_logs, args.artifacts / "gates")
    record = {
        "code_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_files": [
            {"path": str(p.relative_to(ROOT)), "sha256": digest(p)}
            for p in [
                ROOT / "exulanica/ingest/personal_admission.py",
                ROOT / "exulanica/ingest/personal_admission_command.py",
                ROOT / "exulanica/ingest/privacy.py",
                ROOT / "tests/test_personal_admission_command.py",
                ROOT / "tests/test_personal_admission_flow.py",
                ROOT / "scripts/record_personal_admission_evidence.py",
            ]
        ],
        "profile": "exulanica.personal-admission-flow/v1",
        "recorded_at": dt.datetime.now(dt.UTC).isoformat(),
        "predecessor_record": {
            "path": str(args.predecessor),
            "record_sha256": predecessor["record_sha256"],
        },
        "execution": result,
        "artifacts": [
            {"path": str(p.relative_to(ROOT)), "sha256": digest(p), "byte_size": p.stat().st_size}
            for p in sorted(args.artifacts.resolve().rglob("*"))
            if p.is_file()
        ],
        "limitations": [
            "Generated pixels only; no real people, detector, depth or GPU run.",
            "Full frontier preflight executed: exact-source database screening passed; "
            "overall preflight refused because no signing key was supplied.",
            "Existing SQL predicate accepts historical eligible receipts after edits; "
            "the known-failing SQL baseline reproduces this unresolved policy gap, not a mutant kill.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    encoded = canonical_json(envelope)
    if b"/Users/" in encoded or b"Bearer " in encoded or b"api-token" in encoded:
        raise ValueError("retained record contains a personal path or credential marker")
    with args.output.open("xb") as stream:
        stream.write(encoded)
    print(args.output)


if __name__ == "__main__":
    main()
