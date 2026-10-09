"""``exulanica-piece-generation``: the process that serves generation sessions.

It owns no HTTP surface. Each pass (:class:`exulanica.generation.worker.PieceGenerationWorker`)
follows every batch in flight, takes each made request's passed pieces into its world's look (and
back on request: :mod:`exulanica.generation.apply`) and, while the operator's session is warm,
queues the served workspaces' waiting piece requests into it. Workspaces are deployment
configuration, as for the asset preparation worker: ``EXULANICA_WORKSPACE_IDS`` and
``--workspace``, and, when ``EXULANICA_ACCOUNT_DATABASE_URL`` is set, the workspaces active accounts
own, read fresh each pass.

It holds two credentials, both from the operator's environment and read in this process only: the
runtime database role (``EXULANICA_DATABASE_URL``; it refuses an owner or a superuser) and the
generation bucket's key file (``EXULANICA_GENERATION_BUCKET_KEY_FILE``), whose requests can put, get
and list objects and delete none. It spends through the durable spending authority
(``EXULANICA_SPENDING=durable``, the witness directory where one is configured). It calls no model,
so the model egress allowlist does not apply to it: its only outbound requests go to the endpoint
its key file names and to the content store. Generated pieces are kept in the shared
``generated-pieces`` namespace of the configured content store, bounded by
``EXULANICA_GENERATED_PIECES_MAX_BYTES``.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Final

from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV, AccountWorkspaceSource
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name
from exulanica.generation.apply import LookStepper
from exulanica.generation.bucket import KEY_FILE_VARIABLE, bucket_from_environment
from exulanica.generation.pieces import max_bytes
from exulanica.generation.requests import generation_catalogs
from exulanica.generation.worker import PieceGenerationWorker
from exulanica.spending.config import durable_spending_from_env
from exulanica.store.configured import content_stores
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.style_packs import load_context
from exulanica.world.workspace_preparations import retained_bytes_limit

__all__ = ["WORKSPACES_ENV", "main"]

WORKSPACES_ENV: Final = env_name("WORKSPACE_IDS")
#: The repository's root, where the look families and texture manifest are committed.
_TREE: Final = Path(__file__).resolve().parents[2]


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "piece-generation", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _configured(values: list[str], environ: Mapping[str, str]) -> frozenset[uuid.UUID]:
    raw = list(values)
    raw.extend(
        part.strip()
        for part in (env_get("WORKSPACE_IDS", environ) or "").split(",")
        if part.strip()
    )
    return frozenset(uuid.UUID(value) for value in raw)


def _workspaces(
    configured: frozenset[uuid.UUID], source: AccountWorkspaceSource | None
) -> Callable[[], Iterable[uuid.UUID]]:
    def read() -> Iterable[uuid.UUID]:
        found = set(configured)
        if source is not None:
            found.update(source())
        return sorted(found)

    return read


def build(args: argparse.Namespace, environ: Mapping[str, str]) -> PieceGenerationWorker:
    database = Database.from_env(environ)
    verify_schema(database)
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    bucket = bucket_from_environment(environ)
    if bucket is None:
        raise ValueError(f"no generation bucket was configured: set {KEY_FILE_VARIABLE}")
    account_url = environ.get(ACCOUNT_DATABASE_URL_ENV)
    source = AccountWorkspaceSource(account_url, database.url).verify() if account_url else None
    configured = _configured(args.workspace, environ)
    if not configured and source is None:
        raise ValueError(
            f"no workspace was configured. Set {WORKSPACES_ENV}, pass --workspace, or set "
            f"{ACCOUNT_DATABASE_URL_ENV}; a worker that silently serves nothing is not healthy."
        )
    stores = content_stores(environ)
    library = style_pack_library()
    return PieceGenerationWorker(
        database=database,
        bucket=bucket,
        pieces_store=stores.generated_pieces,
        spending=durable_spending_from_env(environ, database, label="piece-generation"),
        catalogs=generation_catalogs(),
        library=library,
        shipped=shipped_thing_kinds(),
        workspaces=_workspaces(configured, source),
        store_bound=max_bytes(environ),
        looks=LookStepper(
            library=library,
            context=load_context(_TREE),
            stores=stores.workspace_style_packs,
            generated_pieces=stores.generated_pieces,
            retained_bytes_limit=retained_bytes_limit(environ),
        ),
    )


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-piece-generation",
        description="Serve the operator's generation session with the workspaces' piece requests.",
    )
    parser.add_argument("--workspace", action="append", default=[], help="workspace UUID")
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    args = parser.parse_args(argv)
    output = sys.stdout
    environment = os.environ if environ is None else environ
    try:
        worker = build(args, environment)
    except Exception as error:
        _emit(output, "startup_refused", failure_class=type(error).__name__, message=str(error))
        return 2
    _emit(output, "startup", mode="once" if args.once else "daemon")
    stop = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        stop.set()

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        while True:
            try:
                report = worker.run_once()
                if report["workspaces"]:
                    _emit(output, "pass", **report)
            except Exception as error:
                _emit(output, "pass_failed", failure_class=type(error).__name__, message=str(error))
                if args.once:
                    return 1
            if args.once or stop.wait(args.poll_seconds):
                break
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    _emit(output, "stopped")
    return 0
