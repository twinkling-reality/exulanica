"""Run with python -m exulanica.ingest.personal_admission_command."""

from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

from psycopg.conninfo import make_conninfo

from exulanica.db import Database, applied_migrations, provision_workspace
from exulanica.ingest.personal_admission import execute, load_manifest, read_source
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.migrations import migrations, verify_applied
from exulanica.store.local import LocalContentAddressedStore

DATABASE_URL = "postgresql://localhost:5433/exulanica_spine_test"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--photo-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--schema", required=True)
    args = parser.parse_args(argv)
    try:
        if not re.fullmatch(r"exulanica_personal_[a-z0-9_]+", args.schema):
            raise ValueError(
                "use an existing isolated exulanica_personal_* schema; public is refused"
            )
        manifest = load_manifest(args.manifest)
        data = read_source(manifest, args.photo_dir)
        source_root, store_root = args.photo_dir.resolve(), args.data_dir.resolve()
        if (
            source_root == store_root
            or source_root in store_root.parents
            or store_root in source_root.parents
        ):
            raise ValueError("photo and data directories must be separate and non-nested")
        if any(p.is_symlink() for p in [args.data_dir, *args.data_dir.parents]):
            raise ValueError("data directory symbolic links are refused")
        if args.data_dir.exists() and any(p.is_symlink() for p in args.data_dir.rglob("*")):
            raise ValueError("nested data directory symbolic links are refused")
        database = Database(
            make_conninfo(
                DATABASE_URL, hostaddr="127.0.0.1", options=f"-csearch_path={args.schema},public"
            )
        )
        with database.unscoped() as connection:
            actual = connection.execute("select current_schema() name").fetchone()["name"]
            if actual != args.schema:
                raise ValueError(
                    "have the operator create and migrate the isolated schema explicitly"
                )
            known = applied_migrations(connection)
            verify_applied(known)
            pending = [m.version for m in migrations() if m.version not in known]
            if pending:
                raise ValueError("pending migrations: " + ", ".join(pending))

        workspace = uuid.UUID(manifest.workspace_id)
        with database.session(workspace) as connection:
            provision_workspace(connection, workspace)
            pipeline = PhotoIngestPipeline(
                IngestRepository(connection, workspace),
                LocalContentAddressedStore(args.data_dir / "blobs"),
            )
            result = execute(manifest, data, pipeline)
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "action": "Correct the named input or obtain current review/authority; "
                    "pending migrations require explicit operator application "
                    "to the isolated schema. This command never migrates.",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
