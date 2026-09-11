"""Build a judge seed from the retained reference database, without touching the retained one.

The provenance chain this walks, and the reason each hop exists:

    postgresql://localhost:5433/exulanica_spine_test      the RETAINED database, migrations
                                                          0001 to 0038. Never read by this
                                                          script and never migrated by it.
    postgresql://localhost:5433/exulanica_inspect_test    a pg_dump copy an operator migrated to
                                                          HEAD by hand. Read only here.
    postgresql://localhost:5433/exulanica_judgeseed_test  this script's own copy. The structural
                                                          plane is composed HERE, so the copy
                                                          somebody else is inspecting is not
                                                          changed underneath them.

**Applying a migration to the retained database is an operator-authorised step after a backup,
and nothing in this file does it.** The copy is made with ``pg_dump`` from a database that is
already at HEAD, so no migration runs at all.

Two verbs. ``prepare`` makes the copy and composes the structural plane a sandbox version
branches from; ``export`` writes the archive. They are separate because ``prepare`` writes and
``export`` does not, and an operator re-running the export should not silently recompose a world.

The archive itself, its verification, its restore and its reset are ``exulanica-seed``, which
ships inside the image. This script is the host-side half that only ever runs on the machine
holding the reference baseline.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

from exulanica.orchestration.judge_seed import export_seed, prepare_sandbox_world
from exulanica.store.local import LocalContentAddressedStore

ROOT = Path(__file__).resolve().parents[1]

#: The operator-migrated copy this reads. Not the retained database, which stays at 0038.
SOURCE = "postgresql://localhost:5433/exulanica_inspect_test"
#: This script's own copy, which is the only database it writes to.
SEED_SOURCE = "postgresql://localhost:5433/exulanica_judgeseed_test"
#: PostgreSQL 18's own binaries. The Homebrew default on this machine is 14, and its `pg_dump`
#: refuses an 18 server with a version-mismatch error rather than producing a partial dump.
PG_BIN = Path("/opt/homebrew/opt/postgresql@18/bin")
STORE_PARENT = ROOT / ".exulanica/reference-baseline/runtime"

#: The Montserrat volcanic sample. `docs/retained-reference-workflow.md` records how it was
#: admitted, screened and published; this script neither re-screens nor re-derives anything.
VOLCANIC = uuid.UUID("79004d44-ca24-4d17-9eef-56786415e233")

#: The actor recorded against the composed structural plane and the opened sandbox version. A
#: stable uuid rather than a fresh one per run, so re-running `prepare` is idempotent in the
#: audit trail rather than adding a new author every time.
SEED_ACTOR = uuid.UUID("6f9b1c34-2a5d-4e71-8f0a-3c2b7d915e46")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(command, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"{command[0]} failed: {result.stderr.strip()[:2000]}")
    return result


def _copy_database(source: str, target: str, *, force: bool) -> None:
    """Replace ``target`` with a fresh dump of ``source``.

    `create database ... template` would be faster and is not used: it refuses while any session
    holds the template, and on this machine another session usually does.
    """
    admin = "postgresql://localhost:5433/postgres"
    with psycopg.connect(admin, autocommit=True) as connection:
        name = target.rsplit("/", 1)[-1]
        exists = connection.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone()
        if exists and not force:
            raise SystemExit(
                f"{name} already exists. Pass --force to replace it, which drops every row in it."
            )
        if exists:
            connection.execute(f'drop database "{name}"')
        connection.execute(f'create database "{name}"')

    dump = subprocess.Popen(
        [str(PG_BIN / "pg_dump"), source], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    load = subprocess.Popen(
        [str(PG_BIN / "psql"), "--quiet", "--output=/dev/null", target],
        stdin=dump.stdout,
        stderr=subprocess.PIPE,
    )
    assert dump.stdout is not None
    dump.stdout.close()
    _, load_error = load.communicate()
    dump.wait()
    if dump.returncode != 0 or load.returncode != 0:
        raise SystemExit(f"copying {source} failed: {load_error.decode()[:2000]}")


def prepare(arguments: argparse.Namespace) -> int:
    _copy_database(arguments.source, arguments.seed_source, force=arguments.force)
    with psycopg.connect(arguments.seed_source, row_factory=dict_row) as connection:
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(arguments.workspace),)
        )
        result = prepare_sandbox_world(
            connection, workspace_id=arguments.workspace, actor=SEED_ACTOR
        )
        connection.commit()
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def export(arguments: argparse.Namespace) -> int:
    store = LocalContentAddressedStore(Path(arguments.store_parent) / "blobs")
    with psycopg.connect(arguments.seed_source, row_factory=dict_row) as connection:
        manifest = export_seed(
            connection,
            store,
            workspace_id=arguments.workspace,
            destination=Path(arguments.into),
            created_at=arguments.created_at,
            allow_absent=arguments.allow_absent,
        )
    document = manifest.to_json()
    json.dump(document["totals"], sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    for key, value in sorted(document["absent"].items()):
        print(f"absent  {value['referenced_by']}  {key}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="seed_workspace.py",
        description="Prepare a judge seed source and export a seed archive from it.",
    )
    parser.add_argument("--source", default=SOURCE, help="the operator-migrated copy to read")
    parser.add_argument("--seed-source", default=SEED_SOURCE, help="this script's own copy")
    parser.add_argument("--workspace", type=uuid.UUID, default=VOLCANIC)
    subparsers = parser.add_subparsers(dest="verb", required=True)

    prepared = subparsers.add_parser(
        "prepare", help="copy the source and compose the structural plane and one sandbox version"
    )
    prepared.add_argument("--force", action="store_true", help="replace an existing seed source")
    prepared.set_defaults(handler=prepare)

    exported = subparsers.add_parser("export", help="write the archive from the prepared copy")
    exported.add_argument("--into", required=True)
    exported.add_argument("--created-at", required=True)
    exported.add_argument("--store-parent", default=str(STORE_PARENT))
    exported.add_argument("--allow-absent", action="store_true")
    exported.set_defaults(handler=export)

    arguments = parser.parse_args(argv)
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
