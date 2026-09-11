"""``exulanica-seed``: produce a judge seed, restore a stack to it, and return it there.

Six verbs, because the operations genuinely differ in what they may touch and conflating any two
of them would hide which. ``export`` reads. ``verify`` reads a directory and nothing else, so it
runs on a machine with no database. ``restore`` writes a fresh stack. ``reset`` empties a used one
and reloads it. ``role`` and ``token`` provision the two halves of judge access.

**Nothing here prints a bearer token.** ``token`` writes the directory to a file with mode 0600
and reports the path and the token's SHA-256, which is what the API compares against anyway. A
command that echoed the secret would put it in a terminal scrollback, a CI log and a screen
recording, and the operator needs the file rather than the string.

Connection and store come from the environment the deployment already sets:
``EXULANICA_DATABASE_URL`` and ``EXULANICA_DATA_DIR``. ``restore`` and ``reset`` need the
administrative principal that ran the migrations, not the runtime role, and say so when refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
import uuid
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.orchestration.judge_seed import (
    JUDGE_ROLE,
    JUDGE_WRITE_TABLES,
    SeedRefused,
    export_seed,
    judge_grants,
    mint_judge_token,
    provision_judge_role,
    read_manifest,
    reset_to_seed,
    restore_seed,
    verify_seed,
)
from exulanica.store.local import LocalContentAddressedStore

__all__ = ["JUDGE_ROLE_PASSWORD_ENV", "main"]

JUDGE_ROLE_PASSWORD_ENV: Final = env_name("JUDGE_ROLE_PASSWORD")

#: 36 bytes of entropy, url-safe. The same width the reference launcher uses, and comfortably
#: over the 32-character floor ``load_token_directory`` enforces at start-up.
_TOKEN_BYTES: Final = 36


def _store(explicit: str | None) -> LocalContentAddressedStore:
    return LocalContentAddressedStore(resolve_data_dir(explicit=explicit) / "blobs")


def _report(stream: Any, manifest: Any, archive: Path) -> None:
    document = manifest.to_json()
    totals = document["totals"]
    print(f"archive     {archive}", file=stream)
    print(f"workspace   {document['workspace_id']}", file=stream)
    print(f"schema      {document['schema_version']}", file=stream)
    print(f"registries  {document['registry_digest']}", file=stream)
    print(
        f"rows        {totals['rows']} in {totals['row_files']} tables",
        file=stream,
    )
    print(
        f"blobs       {totals['blobs']} objects, {totals['blob_bytes']} bytes",
        file=stream,
    )
    if document["absent"]:
        print(
            f"absent      {totals['absent']} key(s) a row references that the source store did "
            "not hold, recorded in the manifest:",
            file=stream,
        )
        for key, value in sorted(document["absent"].items()):
            print(f"            {value['referenced_by']} {key}", file=stream)


def _export(arguments: argparse.Namespace, stream: Any) -> int:
    database = Database.from_env()
    destination = Path(arguments.into)
    with database.unscoped() as connection:
        manifest = export_seed(
            connection,
            _store(arguments.data_dir),
            workspace_id=uuid.UUID(arguments.workspace),
            destination=destination,
            created_at=arguments.created_at,
            allow_absent=arguments.allow_absent,
        )
    _report(stream, manifest, destination)
    return 0


def _verify(arguments: argparse.Namespace, stream: Any) -> int:
    archive = Path(arguments.archive)
    manifest = verify_seed(archive)
    _report(stream, manifest, archive)
    print("verified    every row file and every blob matches the manifest", file=stream)
    return 0


def _restore(arguments: argparse.Namespace, stream: Any) -> int:
    database = Database.from_env()
    archive = Path(arguments.archive)
    with database.unscoped() as connection:
        manifest = restore_seed(
            connection,
            _store(arguments.data_dir),
            archive=archive,
            verify=not arguments.no_verify,
        )
    _report(stream, manifest, archive)
    print("restored    landed rows and store bytes match the manifest", file=stream)
    return 0


def _reset(arguments: argparse.Namespace, stream: Any) -> int:
    database = Database.from_env()
    archive = Path(arguments.archive)
    with database.unscoped() as connection:
        manifest = reset_to_seed(connection, archive=archive, verify=not arguments.no_verify)
    print(f"reset       workspace {manifest.workspace_id} is back at the seed", file=stream)
    print("store       untouched, because its keys are content addressed", file=stream)
    return 0


def _role(arguments: argparse.Namespace, stream: Any) -> int:
    database = Database.from_env()
    password = env_get("JUDGE_ROLE_PASSWORD")
    if not password and not arguments.no_password:
        print(
            f"{JUDGE_ROLE_PASSWORD_ENV} is not set. Set it, or pass --no-password for a "
            "deployment that authenticates by certificate or by peer.",
            file=sys.stderr,
        )
        return 2
    with database.unscoped() as connection:
        provision_judge_role(connection, role=arguments.role, password=password or None)
        grants = judge_grants(connection, role=arguments.role)
    writable = sorted(name for name, values in grants.items() if values - {"SELECT"})
    deletable = sorted(name for name, values in grants.items() if "DELETE" in values)
    print(f"role        {arguments.role}", file=stream)
    print(f"readable    {len(grants)} tables", file=stream)
    print(f"writable    {len(writable)} tables: {', '.join(writable)}", file=stream)
    print(f"deletable   {len(deletable)} tables", file=stream)
    if deletable or sorted(writable) != sorted(JUDGE_WRITE_TABLES):
        print(
            "the live grants do not match the allowlist; refusing to report success",
            file=sys.stderr,
        )
        return 1
    return 0


def _token(arguments: argparse.Namespace, stream: Any) -> int:
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    directory = mint_judge_token(
        workspace_id=uuid.UUID(arguments.workspace),
        actor=uuid.UUID(arguments.actor) if arguments.actor else uuid.uuid4(),
        token=token,
    )
    path = Path(arguments.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Written through a file descriptor opened 0600 rather than written and then chmodded, so
    # the secret is never on disk world-readable, not even for the width of one syscall.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(canonical_json(directory))
        handle.write(b"\n")
    grant = next(iter(directory.values()))
    print(f"written     {path} (mode 0600)", file=stream)
    print(f"workspace   {grant['workspace_id']}", file=stream)
    print(f"actor       {grant['actor']}", file=stream)
    print(f"digest      {hashlib.sha256(token.encode('utf-8')).hexdigest()}", file=stream)
    print(
        "the token itself is in the file and is not printed. Load it with "
        f'EXULANICA_API_TOKENS="$(cat {path})".',
        file=stream,
    )
    return 0


def _describe(arguments: argparse.Namespace, stream: Any) -> int:
    manifest = read_manifest(Path(arguments.archive))
    json.dump(manifest.to_json(), stream, indent=2, sort_keys=True)
    stream.write("\n")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="exulanica-seed",
        description="Produce a judge seed, restore a stack to it, and return it there.",
    )
    subparsers = parser.add_subparsers(dest="verb", required=True)

    def with_data_dir(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--data-dir",
            default=None,
            help="the content-addressed store's parent; defaults to EXULANICA_DATA_DIR",
        )

    export = subparsers.add_parser("export", help="write one workspace and its bytes to an archive")
    export.add_argument("--workspace", required=True, help="the workspace uuid to export")
    export.add_argument("--into", required=True, help="a new directory to write the archive into")
    export.add_argument(
        "--created-at",
        required=True,
        help="the timestamp recorded in the manifest, supplied so two exports can be diffed",
    )
    export.add_argument(
        "--allow-absent",
        action="store_true",
        help=(
            "export a source whose store is missing bytes a row references, recording each gap "
            "in the manifest instead of failing. Without it, an incomplete source is refused."
        ),
    )
    with_data_dir(export)
    export.set_defaults(handler=_export)

    verify = subparsers.add_parser("verify", help="re-hash an archive against its own manifest")
    verify.add_argument("--archive", required=True)
    verify.set_defaults(handler=_verify)

    restore = subparsers.add_parser("restore", help="bring a fresh migrated stack to an archive")
    restore.add_argument("--archive", required=True)
    restore.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the byte verification. Only for a re-run whose archive was just verified.",
    )
    with_data_dir(restore)
    restore.set_defaults(handler=_restore)

    reset = subparsers.add_parser("reset", help="return a used stack to the archive's rows")
    reset.add_argument("--archive", required=True)
    reset.add_argument("--no-verify", action="store_true")
    reset.set_defaults(handler=_reset)

    role = subparsers.add_parser("role", help="provision the judge database role")
    role.add_argument("--role", default=JUDGE_ROLE)
    role.add_argument(
        "--no-password",
        action="store_true",
        help="for a deployment authenticating by certificate or by peer",
    )
    role.set_defaults(handler=_role)

    token = subparsers.add_parser("token", help="mint the judge token directory into a file")
    token.add_argument("--workspace", required=True)
    token.add_argument("--actor", default=None, help="defaults to a fresh uuid")
    token.add_argument("--out", required=True, help="the file to write, created mode 0600")
    token.set_defaults(handler=_token)

    describe = subparsers.add_parser("describe", help="print an archive's manifest as JSON")
    describe.add_argument("--archive", required=True)
    describe.set_defaults(handler=_describe)
    return parser


def main(argv: list[str] | None = None, stream: Any = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return int(arguments.handler(arguments, stream or sys.stdout))
    except SeedRefused as error:
        print(f"refused: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
