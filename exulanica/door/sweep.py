"""The door's sweep: grants that ran out with nobody reading them, settled by the maintenance pass.

A visitor the world decides for is never asked through the door, so nothing the decision host does
sends it home when its grant runs out; the door settles a grant whenever it reads one that ran out
(:meth:`exulanica.door.grants.GrantRepository.settle`), and this settles the rest. The
installation's maintenance pass calls :func:`sweep` once a pass: it reads, across every workspace
and as the role that reads for backups, the grants that ran out unrevoked and still have a visitor
present or a traveller mind naming a model, oldest end first, at most :data:`SWEPT_PER_PASS`; then
settles each in its own workspace, in a transaction of its own, as the runtime role: a departure for
each visitor still present, then its traveller mind handed back, chosen by the grant's own actor.
So a visitor leaves within one maintenance pass of its grant's end, sooner when the door reads the
grant first. Settling is idempotent. Only grants that ran out within
:data:`~exulanica.door.grants.SETTLE_WINDOW` are looked at. A grant a pass could not settle, or
whose settling left it as it was, is held back: every later pass takes it after every other grant,
so it never holds the place of a newer one, and names it until it is settled or leaves the window;
one that leaves the window unsettled is logged by its id once, as no pass looks at it again.

Only this module of the door is reached from the maintenance pass (the import contract "Only the
HTTP surface reaches the door" names the one edge), and it reaches only what settling needs.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Collection
from typing import Any, Final

from psycopg.rows import dict_row

from exulanica.db.session import Database
from exulanica.door.grants import SETTLE_WINDOW, UNSETTLED, GrantRepository, grant_actor

__all__ = ["SWEPT_PER_PASS", "sweep"]

#: The most grants one maintenance pass settles; any more wait for the next pass, oldest first.
SWEPT_PER_PASS: Final = 32
#: How far past the window a held-back grant this pass no longer finds is looked for, to say that it
#: left unsettled: the passes run every few seconds, so one that left did so moments ago.
_LEFT_WITHIN: Final = dt.timedelta(days=1)

_LOG = logging.getLogger(__name__)


def sweep(
    finder: Database,
    runtime: Database,
    *,
    limit: int = SWEPT_PER_PASS,
    deferred: Collection[uuid.UUID] = (),
) -> dict[str, Any]:
    """Settle the grants that ran out with something left to settle, oldest end first, at most
    ``limit``, those in ``deferred`` (held back: a pass before could not settle them, or settling
    left them as they were) after every other: found across workspaces through ``finder`` (a role
    that reads every workspace's rows and writes none), each settled through ``runtime`` in its
    own workspace. Returns how many grants were settled, how many departures were written, how
    many grants failed, and ``stuck``, sorted: the grants held back from now on, each one that
    failed or is still unsettled after settling and each held-back one still unsettled that this
    pass did not reach, which the next pass is given as ``deferred``."""
    held_back = sorted(set(deferred))
    with finder.unscoped() as raw:
        cursor = raw.cursor(row_factory=dict_row)
        # The rest first, at most ``limit``; then the held-back grants by id, wherever their ends
        # fall, so none of them leaves the reckoning while it is still unsettled.
        ordered = cursor.execute(
            UNSETTLED.format(scope="not (g.grant_id = any(%(held)s::uuid[]))"),
            {"held": held_back, "limit": limit, "window": SETTLE_WINDOW},
        ).fetchall()
        if held_back:
            ordered += cursor.execute(
                UNSETTLED.format(scope="g.grant_id = any(%(held)s::uuid[])"),
                {"held": held_back, "limit": len(held_back), "window": SETTLE_WINDOW},
            ).fetchall()
            found = {row["grant_id"] for row in ordered}
            gone = [grant_id for grant_id in held_back if grant_id not in found]
            # A held-back grant no longer found was settled meanwhile, or has just left the window
            # unsettled: its visitor then stays, run by the routine, until its owner sends it away.
            left = (
                cursor.execute(
                    UNSETTLED.format(scope="g.grant_id = any(%(held)s::uuid[])"),
                    {"held": gone, "limit": len(gone), "window": SETTLE_WINDOW + _LEFT_WITHIN},
                ).fetchall()
                if gone
                else []
            )
            for row in left:
                _LOG.warning("A door grant left the sweep's window unsettled: %s", row["grant_id"])
    settled = departures = failed = 0
    stuck = [row["grant_id"] for row in ordered[limit:]]
    for row in ordered[:limit]:
        try:
            with runtime.session(row["workspace_id"]) as connection:
                grants = GrantRepository(
                    connection, row["workspace_id"], grant_actor(row["grant_id"])
                )
                departures += grants.settle(row["grant_id"])
                left = grants.unsettled([row["grant_id"]], limit=1)
        except Exception:  # one grant that cannot be settled waits for the next pass, not the rest
            failed += 1
            stuck.append(row["grant_id"])
            continue
        if left:
            stuck.append(row["grant_id"])  # settling left it as it was
        else:
            settled += 1
    return {
        "grants": settled,
        "departures": departures,
        "failed": failed,
        "stuck": sorted(stuck),
    }
