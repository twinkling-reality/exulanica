"""``exulanica-material-bake``: the process that bakes workspace recipes.

It owns no HTTP surface and takes no bytes from anyone. Workspaces are deployment configuration,
as for the derivative worker: ``EXULANICA_WORKSPACE_IDS`` and ``--workspace``, and, when
``EXULANICA_ACCOUNT_DATABASE_URL`` is set, the workspaces active accounts own, read fresh on every
pass. It connects as the runtime role, refuses an owner or a superuser, refuses a schema it does
not recognise, and refuses to start without Node, the TypeScript loader, the baker, the published
material catalog, and a way to measure a child's memory. Bytes go to each workspace's own
namespace under ``EXULANICA_DATA_DIR``.

Nothing here downloads anything. Node and the web package's dependencies must already be on the
host or in the image (``deploy/material-bake/``), and the operator installs them.
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
from pathlib import Path
from typing import Any, Final

from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV, AccountWorkspaceSource
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.store.namespaces import material_stores
from exulanica.world.material_bakes import BakeLimits, BakeRuntime, MaterialBakeWorker
from exulanica.world.texture_assets import TEXTURE_DIRECTORY, load_material_catalog

__all__ = ["TEXTURE_DIRECTORY_ENV", "WEB_DIRECTORY_ENV", "WORKSPACES_ENV", "main"]

WORKSPACES_ENV: Final = env_name("WORKSPACE_IDS")
#: Where ``manifest.json``, ``catalog.json`` and ``objects/`` are, when not in a checkout.
TEXTURE_DIRECTORY_ENV: Final = env_name("TEXTURE_DIRECTORY")
#: Where ``node_modules`` and ``packages/loom-texture`` are, when not in a checkout.
WEB_DIRECTORY_ENV: Final = env_name("WEB_DIRECTORY")


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "material-bake", "event": event, **fields}, sort_keys=True),
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


def _build(args: argparse.Namespace, environ: Mapping[str, str]) -> MaterialBakeWorker:
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
            f"{ACCOUNT_DATABASE_URL_ENV}; a worker that silently bakes nothing is not healthy."
        )
    textures = env_get("TEXTURE_DIRECTORY", environ)
    web = env_get("WEB_DIRECTORY", environ)
    runtime = (
        BakeRuntime.from_checkout(node=environ.get("EXULANICA_NODE"), web=Path(web))
        if web
        else BakeRuntime.from_checkout(node=environ.get("EXULANICA_NODE"))
    )
    return MaterialBakeWorker(
        database,
        material_stores(resolve_data_dir(environ)),
        workspaces,
        runtime=runtime,
        catalog=load_material_catalog(Path(textures) if textures else TEXTURE_DIRECTORY),
        limits=BakeLimits(timeout_seconds=args.timeout_seconds, memory_bytes=args.memory_mib << 20),
        name=args.name or f"{platform.node() or 'unknown'}:{os.getpid()}:{uuid.uuid4().hex[:8]}",
        poll_seconds=args.poll_seconds,
        workspace_source=source,
    )


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-material-bake",
        description="Bake requested workspace material recipes, one process per bake.",
    )
    parser.add_argument("--workspace", action="append", default=[], help="workspace UUID")
    parser.add_argument("--name", help="stable worker identifier; generated when omitted")
    parser.add_argument("--poll-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    parser.add_argument("--memory-mib", type=int, default=768)
    parser.add_argument("--grace-seconds", type=float, default=120.0)
    parser.add_argument("--once", action="store_true", help="bake what is waiting and exit")
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ

    try:
        worker = _build(args, environment)
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    _emit(output, "startup", worker=worker.name, mode="once" if args.once else "daemon")

    if args.once:
        try:
            outcome = worker.drain()
        except Exception as error:
            _emit(output, "pass_failed", failure_class=type(error).__name__, message=str(error))
            return 1
        _emit(
            output,
            "stopped",
            baked=outcome.baked,
            failed=outcome.failed,
            lost=outcome.lost,
            exhausted=outcome.exhausted,
            failures=outcome.failures[:10],
        )
        return 1 if outcome.failed else 0

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
