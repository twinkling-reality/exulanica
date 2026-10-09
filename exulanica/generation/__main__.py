"""The operator's commands for generation sessions.

    python -m exulanica.generation session open --session session.json --manifest manifest.json \\
        --compute-key nebius-ai-cloud-rtx-pro-6000 --job-id aijob-... --window-hours 2 --by ops
    python -m exulanica.generation session close --id <generation session id> --reason idle \\
        [--gpu-run gpu-run-aijob-....json]
    python -m exulanica.generation session status

The operator starts a session on their own Nebius AI Cloud account with the generation tooling
(``ml/appearance``: ``assets session record --manifest``, ``stage``, ``start``) and registers it
here, so the generation worker serves it until its window ends or it is closed. Run with the
administrative database URL (``EXULANICA_DATABASE_URL``): the register is written only by a member
of its owner, never by the runtime. ``--by`` is a label for the record, never a name, an address or
a key. Nothing here starts, stops or creates a cloud resource. Every command prints one JSON
document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from exulanica_pieces.canonical import Refused, sha256_hex
from exulanica_pieces.queue import read_session, read_session_manifest
from exulanica_pieces.recipes import OBJECT_ROUTE

from exulanica.db.session import Database
from exulanica.generation.requests import generation_catalogs

__all__ = ["main"]

_LABEL = re.compile(r"[a-z0-9][a-z0-9:._-]{0,63}")
_REASON = re.compile(r"[a-z][a-z0-9_]{0,63}")
#: The longest window a registration states: the register refuses one past a day.
MAX_WINDOW_HOURS = 24


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m exulanica.generation")
    commands = parser.add_subparsers(dest="command", required=True)
    session = commands.add_parser("session").add_subparsers(dest="step", required=True)
    opened = session.add_parser("open")
    for name in ("--session", "--manifest", "--compute-key", "--job-id", "--by"):
        opened.add_argument(name, required=True)
    opened.add_argument("--window-hours", type=float, required=True)
    closed = session.add_parser("close")
    closed.add_argument("--id", required=True)
    closed.add_argument("--reason", required=True)
    closed.add_argument("--gpu-run")
    session.add_parser("status")
    return parser


def _open(database: Database, arguments: argparse.Namespace) -> dict[str, Any]:
    session_raw = Path(arguments.session).read_bytes()
    session = read_session(session_raw)
    manifest = read_session_manifest(Path(arguments.manifest).read_bytes(), session_raw)
    if "nonce" not in session:
        raise Refused(
            "the session record carries no nonce; record it with the tooling, which draws one, so "
            "no two sessions share a digest or its markers"
        )
    if session["route"] != OBJECT_ROUTE:
        # Piece requests take route A; a session of another route could build no job of them.
        raise Refused(
            f"the session serves route {session['route']}; piece requests take route {OBJECT_ROUTE}"
        )
    if arguments.compute_key not in generation_catalogs().compute.entries:
        raise Refused(f"{arguments.compute_key} is not a GPU the piece compute catalog names")
    if not _LABEL.fullmatch(arguments.by):
        raise Refused("--by is a label: lower case letters, digits and :._-")
    if not 0 < arguments.window_hours <= MAX_WINDOW_HOURS:
        raise Refused(f"a session's window is more than 0 and at most {MAX_WINDOW_HOURS} hours")
    with database.unscoped() as connection:
        held = connection.execute(
            "select 1 from generation_session where session_sha256 = %s",
            (sha256_hex(session_raw),),
        ).fetchone()
        if held is not None:
            raise Refused(
                "that session record is registered already; a session is registered once, since "
                "its markers and heartbeats are named by its digest"
            )
        row = connection.execute(
            "insert into generation_session (session_canonical, session_sha256, route, "
            "code_sha256, components_sha256, container, compute_key, provider_job_id, opened_by, "
            "window_ends_at) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, "
            "statement_timestamp() + make_interval(secs => %s)) "
            "returning generation_session_id, opened_at, window_ends_at",
            (
                session_raw.decode("ascii"),
                sha256_hex(session_raw),
                session["route"],
                session["code_sha256"],
                manifest["components_sha256"],
                manifest["container"],
                arguments.compute_key,
                arguments.job_id,
                arguments.by,
                arguments.window_hours * 3600,
            ),
        ).fetchone()
    assert row is not None
    return {
        "generation_session_id": str(row["generation_session_id"]),
        "session_sha256": sha256_hex(session_raw),
        "opened_at": row["opened_at"].isoformat(),
        "window_ends_at": row["window_ends_at"].isoformat(),
    }


def _close(database: Database, arguments: argparse.Namespace) -> dict[str, Any]:
    if not _REASON.fullmatch(arguments.reason):
        raise Refused("--reason is lower case words joined by _")
    gpu_run = (
        None
        if arguments.gpu_run is None
        else hashlib.sha256(Path(arguments.gpu_run).read_bytes()).hexdigest()
    )
    with database.unscoped() as connection:
        row = connection.execute(
            "update generation_session set closed_at = statement_timestamp(), close_reason = %s, "
            "gpu_run_sha256 = %s where generation_session_id = %s and closed_at is null "
            "returning closed_at",
            (arguments.reason, gpu_run, uuid.UUID(arguments.id)),
        ).fetchone()
    if row is None:
        raise Refused("no open session has that id")
    return {"generation_session_id": arguments.id, "closed_at": row["closed_at"].isoformat()}


def _status(database: Database) -> dict[str, Any]:
    with database.unscoped() as connection:
        rows = connection.execute(
            "select generation_session_id, session_sha256, compute_key, provider_job_id, "
            "opened_at, window_ends_at from generation_session where closed_at is null "
            "and window_ends_at > statement_timestamp() order by opened_at desc"
        ).fetchall()
    return {
        "open": [
            {
                "generation_session_id": str(row["generation_session_id"]),
                "session_sha256": row["session_sha256"],
                "compute_key": row["compute_key"],
                "provider_job_id": row["provider_job_id"],
                "opened_at": row["opened_at"].isoformat(),
                "window_ends_at": row["window_ends_at"].isoformat(),
            }
            for row in rows
        ]
    }


def main(argv: Sequence[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    database = Database.from_env(os.environ if environ is None else environ)
    try:
        if arguments.step == "open":
            document = _open(database, arguments)
        elif arguments.step == "close":
            document = _close(database, arguments)
        else:
            document = _status(database)
    except (Refused, OSError, ValueError) as refused:
        print(json.dumps({"refused": str(refused)}, sort_keys=True), file=sys.stderr)
        return 2
    print(json.dumps(document, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
