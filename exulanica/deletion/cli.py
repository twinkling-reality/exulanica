"""``exulanica-purge``: destroy the bytes the tombstones asked for, and say what it did.

**A command rather than something the API does by itself, by default.** Erasure is the one
irreversible thing this system performs, and a demonstration instance that quietly destroyed
files on a timer would be the wrong default to arrive at by saying nothing. The
:class:`~exulanica.deletion.worker.PurgeWorker` can run on a thread, and an operator turns it on
with a credential; this is the way to run it once, watch what it did, and run it again.

**It connects as its own role.** ``EXULANICA_PURGE_DATABASE_URL`` names ``exulanica_purge``
(or the ``exulanica_purge`` alias), and its
absence is refused rather than defaulted to the writer. That is not ceremony: the purge role has
a cross-workspace read the runtime role must never have, and the runtime role has writes the
purger must never need. Running as the wrong one either destroys another tenant's photograph or
cannot tell that it would.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from typing import Any, Final

from exulanica.db.session import Database
from exulanica.deletion.worker import PurgeWorker
from exulanica.env import env_get, env_name, resolve_data_dir
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.namespaces import BLOB_NAMESPACE, material_stores

__all__ = ["PURGE_DATABASE_URL_ENV", "main"]

#: The connection string for the purge role. No default and no fallback to the writer.
PURGE_DATABASE_URL_ENV: Final = env_name("PURGE_DATABASE_URL")


def main(argv: list[str] | None = None, stream: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-purge",
        description=(
            "Destroy the object-store bytes that committed tombstones asked to have destroyed. "
            "Idempotent, and safe to run repeatedly."
        ),
    )
    parser.add_argument(
        "--workspace",
        action="append",
        required=True,
        metavar="UUID",
        help="A workspace to drain. Repeatable. Named rather than discovered, because "
        "discovering them would mean a query this role has no business running.",
    )
    parser.add_argument("--data-dir", default=None)
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="How many jobs one pass may examine. Not how many objects it destroys: a job "
        "that defers because something still holds its bytes consumes one too. The rest stay "
        "queued.",
    )
    args = parser.parse_args(argv)
    out = stream or sys.stdout

    url = env_get("PURGE_DATABASE_URL")
    if not url:
        print(
            f"{PURGE_DATABASE_URL_ENV} is not set (EXULANICA_PURGE_DATABASE_URL is accepted as "
            "an alias). It names the connection for the `exulanica_purge` role (or the "
            "`exulanica_purge` alias), which `exulanica-db` provisions. There is no default and "
            "no fallback to the write role: the purge role holds a cross-workspace read the "
            "runtime role must never have, and running as the writer would destroy bytes "
            "another workspace still holds without being able to tell.",
            file=out,
        )
        return 2

    workspaces = frozenset(uuid.UUID(value) for value in args.workspace)
    data_dir = resolve_data_dir(explicit=args.data_dir)
    worker = PurgeWorker(
        Database(url=url),
        LocalContentAddressedStore(data_dir / BLOB_NAMESPACE),
        workspaces,
        limit_per_pass=args.limit,
        material_stores=material_stores(data_dir),
    )
    outcome = worker.drain()

    if outcome.blocked is not None:
        print(f"refusing to destroy anything: {outcome.blocked}", file=out)
        return 2

    print(f"purge over {len(workspaces)} workspace(s) as {outcome.role}", file=out)
    print(f"  destroyed        {outcome.destroyed}", file=out)
    # Not folded into `destroyed`. "The bytes were removed by this pass" and "the bytes were
    # already gone" are different facts, and the second is the ordinary shape of a resumed job.
    print(f"  already absent   {outcome.already_absent}", file=out)
    # Not a failure. Something live still holds these exact bytes, in this workspace or another,
    # and the job comes back rather than being closed over a photograph that is still there.
    print(f"  deferred         {outcome.skipped}", file=out)
    print(f"  failed           {outcome.failed}", file=out)
    print(f"  tombstones now complete  {len(outcome.completed_tombstones)}", file=out)
    if outcome.exhausted:
        # A target that has been claimed MAX_ATTEMPTS times and never succeeded. Reported rather
        # than retried for ever, because a queue that hides a broken job behind its own noise is
        # a deletion nobody knows did not happen.
        print(
            f"  ! {outcome.exhausted} job(s) have used every attempt and will not be retried",
            file=out,
        )
    for error in outcome.errors[:10]:
        print(f"  ! {error}", file=out)
    return 1 if outcome.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
