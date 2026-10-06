"""``exulanica-generated-tile-worker``: the process that bakes generated worlds' tiles.

It owns no HTTP surface. Its workspaces are ``EXULANICA_WORKSPACE_IDS`` and ``--workspace``, and,
when ``EXULANICA_ACCOUNT_DATABASE_URL`` is set, the workspaces active accounts own, read again on
every pass, as the derivative and preparation workers read them. It claims and reads each job as
the runtime role (``EXULANICA_DATABASE_URL``, refused if it is an owner or a superuser) and
publishes each baked tile through ``EXULANICA_TILE_PUBLISHER_DATABASE_URL``.

The publisher is ``exulanica_tiles`` (migration 0138), which may execute the publish function and
nothing else, and :func:`~exulanica.db.tiles_role.assert_tiles_role` checks it at startup. A wider
role, the owner included, is refused wherever the installation's profile installs generated tiles,
and accepted with a ``publisher_not_narrow`` warning elsewhere, so a development checkout that has
not provisioned the role keeps baking. Baked tiles go to the tile store
under ``EXULANICA_DATA_DIR``.

Nothing here downloads anything. The tessellator runs either compiled (``EXULANICA_TESS_CLI``, a
``cli.js`` built by ``tsc``, run by ``EXULANICA_NODE`` or the ``node`` on ``PATH``), as the tile
worker's image carries it, or from the checkout's TypeScript through ``tsx``
(``EXULANICA_WEB_DIRECTORY``, or the checkout's ``web/``), whose dependencies must already be
installed.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.account_workspaces import ACCOUNT_DATABASE_URL_ENV, AccountWorkspaceSource
from exulanica.db.migrate import verify_schema
from exulanica.db.roles import assert_runtime_role
from exulanica.db.session import Database
from exulanica.db.tiles_role import TilesRoleUnsafe, assert_tiles_role
from exulanica.env import env_get, env_name
from exulanica.ingest.generated_tiles import GeneratedTileBaker
from exulanica.store.configured import content_stores

__all__ = ["PUBLISHER_ENV", "check_publisher", "main"]

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


def check_publisher(url: str, environ: Mapping[str, str]) -> str | None:
    """Why the publisher is wider than the tile role, as a warning, or None when it is that role.

    Refused, by raising :class:`~exulanica.db.tiles_role.TilesRoleUnsafe`, wherever the
    installation's profile installs generated tiles (``public`` among the shipped ones): an
    installation that bakes towns publishes only as the tile role. Elsewhere, where the profile
    installs none or no profile is named, the warning lets a development checkout keep baking.
    """
    with psycopg.connect(url, autocommit=True, row_factory=dict_row) as connection:
        try:
            assert_tiles_role(connection)
        except TilesRoleUnsafe as refusal:
            if _installs_generated_tiles(environ):
                raise TilesRoleUnsafe(
                    "this installation's profile installs generated tiles, which are published "
                    f"only as the tile role: {refusal}"
                ) from refusal
            return str(refusal)
    return None


def _installs_generated_tiles(environ: Mapping[str, str]) -> bool:
    """Whether the installation profile ``EXULANICA_INSTALLATION_PROFILE`` names installs
    ``generated_tiles``.

    Read here rather than through the API's loader, which this layer does not import; the API
    validates the whole profile at its own startup, and an unreadable one stops it there."""
    named = env_get("INSTALLATION_PROFILE", environ)
    if not named:
        return False
    document = json.loads(Path(named).read_text(encoding="utf-8"))
    component = (document.get("components") or {}).get("generated_tiles") or {}
    return component.get("installed") is True


def _compiled(environ: Mapping[str, str]) -> tuple[Path, Path] | None:
    """The compiled tessellator and the Node that runs it, when ``EXULANICA_TESS_CLI`` names one."""
    cli = env_get("TESS_CLI", environ)
    if not cli:
        return None
    node = env_get("NODE", environ) or shutil.which("node")
    if not node:
        raise ValueError("EXULANICA_TESS_CLI is set and no node was found; set EXULANICA_NODE")
    return Path(node), Path(cli)


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
            raise ValueError(f"set {PUBLISHER_ENV}: the role a baked tile is published as")
        narrow = check_publisher(publisher_url, environment)
        if narrow is not None:
            _emit(output, "publisher_not_narrow", message=narrow)
        account_url = environment.get(ACCOUNT_DATABASE_URL_ENV)
        source = AccountWorkspaceSource(account_url, database.url).verify() if account_url else None
        workspaces = _workspaces(args.workspace, environment)
        if not workspaces and source is None:
            raise ValueError(
                "no workspace was configured and no account source is set; a worker that bakes "
                "nothing is not well"
            )

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
            compiled=_compiled(environment),
        )
    except Exception as error:
        _emit(output, "startup_failed", failure_class=type(error).__name__, message=str(error))
        return 1
    _emit(output, "startup", workspaces=len(workspaces), mode="once" if args.once else "daemon")
    while True:
        failed = 0
        for outcome in baker.drain(workspaces | (source() if source is not None else frozenset())):
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
