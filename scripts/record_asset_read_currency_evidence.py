"""Record the asset-read scope checkpoint; this is not route acceptance evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = (root / args.output).resolve()
    artifacts = (root / args.artifacts).resolve()
    output.relative_to(root / "docs/evaluation")
    artifacts.relative_to(root / "docs/evaluation")
    if output.exists() or artifacts.exists():
        raise FileExistsError("preserve historical records; choose fresh output paths")
    artifacts.mkdir(parents=True)

    def binding(path: Path) -> dict[str, object]:
        content = path.read_bytes()
        return {
            "path": path.relative_to(root).as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "byte_size": len(content),
        }

    predecessor = root / "docs/evaluation/2026-09-08-screening-currency-integration.json"
    previous = json.loads(predecessor.read_bytes())
    assert set(previous) == {"profile", "record", "record_sha256"}
    assert hashlib.sha256(canonical(previous["record"])).hexdigest() == previous["record_sha256"]
    probe = """begin read only;
select current_database(), current_user, current_setting('transaction_isolation');
select rolname, rolsuper, rolbypassrls from pg_roles
where rolname in ('exulanica_ro','exulanica_app') order by rolname;
set local role exulanica_ro;
select current_user, current_setting('transaction_read_only');
select pg_advisory_xact_lock(hashtextextended('asset-read-checkpoint-probe',0));
select mode, granted from pg_locks where pid=pg_backend_pid() and locktype='advisory';
select n.nspname, p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
where p.proname in ('privacy_currency_lock','tg_training_source_mutation_lock');
rollback;
"""
    sql_path = artifacts / "role-probe.sql"
    sql_path.write_text(probe)
    command = [
        "psql",
        "postgresql://localhost:5433/exulanica_spine_test",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-f",
        str(sql_path),
    ]
    result = subprocess.run(command, cwd=root, capture_output=True, text=True, check=False)
    log = artifacts / "role-probe.log"
    log.write_text(result.stdout + result.stderr)
    sources = [
        "docs/asset-read-currency.md",
        "scripts/record_asset_read_currency_evidence.py",
        "exulanica/api/routes/evidence.py",
        "exulanica/api/routes/geometry.py",
        "exulanica/api/routes/graph.py",
        "exulanica/api/routes/world_read.py",
        "exulanica/api/dependencies.py",
        "exulanica/api/services.py",
        "exulanica/db/session.py",
        "exulanica/db/roles.py",
        "exulanica/graph/geometry.py",
        "exulanica/graph/scene_geometry.py",
        "exulanica/world/repository.py",
        "exulanica/ingest/scene_selection.py",
        "exulanica/ingest/scene_reconstruction.py",
        "exulanica/ingest/scene_splat.py",
        "exulanica/ingest/masked_inputs.py",
    ]
    sources.extend(
        str(path.relative_to(root))
        for path in sorted((root / "exulanica/migrations").glob("*.sql"))
        if path.name[:4] in {"0013", "0030", "0035", "0036", "0037", "0038", "0039", "0040"}
    )
    record = {
        "profile": "exulanica.asset-read-currency-checkpoint/v1",
        "status": "scope_checkpoint_pending",
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "source_binding_basis": "exact working-tree bytes; documentation and recorder are new",
        "predecessor_record": {
            "path": predecessor.relative_to(root).as_posix(),
            "record_sha256": previous["record_sha256"],
        },
        "sources": [binding(root / source) for source in sources],
        "artifacts": [binding(sql_path), binding(log)],
        "probe_exit_code": result.returncode,
        "executed_route_criteria": [],
        "killed_controls": [],
        "full_gates_executed": False,
        "serialized_suite_slot_reserved": False,
        "limits": [
            "Read-only role/catalog probe only; no currency route or interleaving proof.",
            "No runtime changes, migrations or producer lineage changes.",
            "Original/crop/by-URI authorization and snapshot/locking need scope decisions.",
            "Masked splat production is refused by the existing producer.",
            "All generated-media acceptance criteria and full gates remain pending.",
        ],
    }
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical(record)).hexdigest(),
    }
    with output.open("xb") as stream:
        stream.write(canonical(envelope) + b"\n")
    print(output.relative_to(root))
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
