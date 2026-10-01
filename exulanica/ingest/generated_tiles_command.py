"""``exulanica-generated-tile-worker``: the process that bakes generated worlds' tiles.

It owns no HTTP surface. Workspaces are deployment configuration, as for the derivative worker:
``EXULANICA_WORKSPACE_IDS`` and ``--workspace``. It claims and reads each job as the runtime role
(``EXULANICA_DATABASE_URL``, refused if it is an owner or a superuser) and publishes each baked tile
through ``EXULANICA_TILE_PUBLISHER_DATABASE_URL``, the owner connection migration 0072 requires for
that write and for nothing else. Baked tiles go to the tile store under ``EXULANICA_DATA_DIR``.

Nothing here downloads anything. Node and the web package's dependencies must already be installed
(``EXULANICA_WEB_DIRECTORY``, or the checkout's ``web/``).
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.env import env_get, env_name
from exulanica.ingest.generated_tiles import GeneratedTileBaker
from exulanica.store.configured import content_stores

__all__ = ["PUBLISHER_ENV", "main"]

PUBLISHER_ENV: Final = env_name("TILE_PUBLISHER_DATABASE_URL")
_CHECKOUT_WEB: Final = Path(__file__).resolve().parents[2] / "web"


def _emit(stream: Any, event: str, **fields: Any) -> None:
    print(
        json.dumps({"component": "generated-tile-worker", "event": event, **fields}, default=str),
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


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    stream: Any = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-generated-tile-worker",
        description="Bake the tiles generated worlds are waiting for, off the request.",
    )
    parser.add_argument("--workspace", action="append", default=[], help="workspace UUID")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--once", action="store_true", help="bake what is waiting and exit")
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    environment = os.environ if environ is None else environ
    try:
        database = Database.from_env(environment)
        verify_schema(database)
        with database.unscoped() as connection:
            assert_runtime_role(connection)
        publisher_url = environment.get(PUBLISHER_ENV)
        if not publisher_url:
            raise ValueError(f"set {PUBLISHER_ENV}: a baked tile is published by the owner")
        workspaces = _workspaces(args.workspace, environment)
        if not workspaces:
            raise ValueError("no workspace was configured; a worker that bakes nothing is not well")

        @contextmanager
        def publisher() -> Iterator[psycopg.Connection]:
            with psycopg.connect(publisher_url, autocommit=True, row_factory=dict_row) as owner:
                yield owner

        web = env_get("WEB_DIRECTORY", environment)
        baker = GeneratedTileBaker(
            session=database.session,
            publisher=publisher,
            store=content_stores(environment).tiles,
            web_directory=Path(web) if web else _CHECKOUT_WEB,
            worker=f"{platform.node() or 'unknown'}:{os.getpid()}:{uuid.uuid4().hex[:8]}",
        )
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    _emit(output, "startup", workspaces=len(workspaces), mode="once" if args.once else "daemon")
    while True:
        failed = 0
        for outcome in baker.drain(workspaces):
            failed += outcome.status != "baked"
            _emit(
                output,
                "bake",
                job_id=outcome.job_id,
                world_id=outcome.world_id,
                tile=list(outcome.tile),
                status=outcome.status,
                detail=outcome.detail,
                baked_tile_id=outcome.baked_tile_id,
            )
        if args.once:
            return 1 if failed else 0
        time.sleep(args.poll_seconds)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
