"""How long the door keeps its two global tables' rows, and the one way they are removed.

``door_secret`` and ``door_redemption_refusal`` belong to no workspace, so nothing else ever
removes their rows. Migration 0149 keeps a refused redemption for a day, which the lockout's minute
reads, and a secret for thirty days after its end, so an owner's question about a credential that
stopped working can still be answered; its triggers refuse every earlier delete. A revoked secret
is a withdrawal and is kept for good (migration 0157), bounded by the secrets one grant may ever be
given (:data:`exulanica.door.grants.SECRETS_ISSUED_MAXIMUM`). The runtime holds no DELETE:
:func:`prune` calls ``door_prune``, a function with its owner's rights that removes only rows past
those bounds, a bounded batch of each table at a time. The door prunes as it goes, beside
the writes that add rows, so the tables stay bounded with no job of their own.
"""

from __future__ import annotations

from typing import Final

import psycopg

__all__ = ["PRUNE_BATCH", "prune"]

#: The most rows of each table one prune removes: enough to keep up with the rows the door adds
#: between prunes, few enough that a prune never holds a request for long.
PRUNE_BATCH: Final = 100


def prune(connection: psycopg.Connection) -> int:
    """Remove up to :data:`PRUNE_BATCH` rows of each global door table past its retention, and say
    how many went."""
    row = connection.execute("select door_prune(%s) as pruned", (PRUNE_BATCH,)).fetchone()
    assert row is not None
    return int(row["pruned"])
