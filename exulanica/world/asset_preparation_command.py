"""``exulanica-asset-preparation``: the process that prepares workspace assets.

It owns no HTTP surface and takes no bytes from anyone: admissions arrive through the API, and this
process reads them back from each workspace's own namespace in the configured content store
(:func:`exulanica.store.configured.content_stores`: the data directory, or the shared object store).
Workspaces are deployment configuration, as for the material bake worker:
``EXULANICA_WORKSPACE_IDS`` and ``--workspace``, and, when ``EXULANICA_ACCOUNT_DATABASE_URL`` is
set, the workspaces active accounts own, read fresh on every pass. It connects as the runtime role,
refuses an owner or a superuser, and refuses a schema it does not recognise. It runs the preparers
registered in :data:`exulanica.world.asset_preparation.PREPARERS` and nothing else, each under the
timeout and lease its registration declares.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import signal
import sys
import threading
import uuid
from collections.abc import Mapping
from typing import Any, Final

from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV, AccountWorkspaceSource
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name
from exulanica.store.configured import content_stores
from exulanica.world.asset_preparation import AssetPreparationWorker
from exulanica.world.workspace_preparations import retained_bytes_limit

__all__ = ["WORKSPACES_ENV", "main"]

WORKSPACES_ENV: Final = env_name("WORKSPACE_IDS")


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "asset-preparation", "event": event, **fields}, sort_keys=True),
        file=stream,
        flush=True,
    )


def _workspaces(values: list[str], environ: Mapping[str, str]) -> frozenset[uuid.UUID]:
    raw = list(values)
    raw.extend(
        part.strip()
        for part in (env_get("WORKSPACE_IDS", environ) or "").split(",")
        if part.strip()
    )
    return frozenset(uuid.UUID(value) for value in raw)


def _build(args: argparse.Namespace, environ: Mapping[str, str]) -> AssetPreparationWorker:
    database = Database.from_env(environ)
    verify_schema(database)
    with database.unscoped() as connection:
        assert_runtime_role(connection)
    account_url = environ.get(ACCOUNT_DATABASE_URL_ENV)
    source = AccountWorkspaceSource(account_url, database.url).verify() if account_url else None
    workspaces = _workspaces(args.workspace, environ)
    if not workspaces and source is None:
        raise ValueError(
            f"no workspace was configured. Set {WORKSPACES_ENV}, pass --workspace, or set "
            f"{ACCOUNT_DATABASE_URL_ENV}; a worker that silently prepares nothing is not healthy."
        )
    return AssetPreparationWorker(
        database,
        content_stores(environ).workspace_assets,
        workspaces,
        name=args.name or f"{platform.node() or 'unknown'}:{os.getpid()}:{uuid.uuid4().hex[:8]}",
        poll_seconds=args.poll_seconds,
        workspace_source=source,
        retained_bytes_limit=retained_bytes_limit(environ),
    )


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-asset-preparation",
        description="Prepare admitted workspace assets, one preparation at a time.",
    )
    parser.add_argument("--workspace", action="append", default=[], help="workspace UUID")
    parser.add_argument("--name", help="stable worker identifier; generated when omitted")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--grace-seconds", type=float, default=120.0)
    parser.add_argument("--once", action="store_true", help="prepare what is waiting and exit")
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ

    try:
        worker = _build(args, environment)
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    _emit(
        output,
        "startup",
        worker=worker.name,
        mode="once" if args.once else "daemon",
        preparers=list(worker.preparers),
    )

    if args.once:
        try:
            outcome = worker.drain()
        except Exception as error:
            _emit(output, "pass_failed", failure_class=type(error).__name__, message=str(error))
            return 1
        _emit(
            output,
            "stopped",
            prepared=outcome.prepared,
            failed=outcome.failed,
            lost=outcome.lost,
            exhausted=outcome.exhausted,
            failures=outcome.failures[:10],
            errors=outcome.errors[:10],
        )
        return 1 if outcome.errors else 0

    requested = threading.Event()

    def request_shutdown(signum: int, _frame: Any) -> None:
        _emit(output, "shutdown_requested", signal=signal.Signals(signum).name)
        requested.set()

    previous = {
        signum: signal.signal(signum, request_shutdown)
        for signum in (signal.SIGTERM, signal.SIGINT)
    }
    worker.start()
    try:
        while not requested.wait(0.5):
            if not worker.alive:
                _emit(output, "worker_stopped_unexpectedly", last_error=worker.last_error)
                return 1
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    worker.stop(timeout=args.grace_seconds)
    _emit(output, "stopped", last_error=worker.last_error)
    return 0
