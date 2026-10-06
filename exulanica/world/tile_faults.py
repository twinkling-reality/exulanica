"""``exulanica-tile-fault``: the owner's decision to serve a faulted tile's stored first bake.

A tile whose second bake differed from its first is marked ``nondeterminism_detected``
(migration 0072) and never served. A baked tile is shared by every world whose tiles it is, so on
an arrival world one fault fails that tile for every visitor's copy. Making the bake deterministic
again is the fix; until then the owner may decide to serve the bytes the first bake stored, which
are held to their digest on every delivery like any other tile.

``clear`` records that decision in ``baked_tile_fault_clearance`` (migration 0144): which tile, who
decided, why and when. It never changes or deletes the stored tile, whose guard trigger refuses
both, and a clearance is itself never changed. Readers then serve the tile, and its failed bake
jobs no longer fail the world (:mod:`exulanica.world.generated_worlds`). ``list`` names every
faulted tile and whether it is cleared. Both run as the owner (``EXULANICA_DATABASE_URL``); no
runtime role may write a clearance.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from exulanica.db.session import Database

__all__ = ["clear_fault", "faulted_tiles", "main"]

_OPERATOR = re.compile(r"[a-z0-9][a-z0-9:._-]{0,95}")


def faulted_tiles(connection: psycopg.Connection) -> list[dict[str, Any]]:
    """Every tile whose bakes disagreed, with whether its fault is cleared, newest first.

    Each names what a clearance would serve and what disagreed with it: the stored first bake's
    container digest, when it was baked and its receipt, and the digest the later bake produced,
    so the owner decides with both in front of them."""
    rows = connection.execute(
        "select b.baked_tile_id, b.tile_x, b.tile_y, b.lod, b.baked_at, b.receipt, "
        "b.container_sha256, b.fault_container_sha256, b.fault_detected_at, "
        "c.cleared_by, c.reason, c.cleared_at from baked_tile b "
        "left join baked_tile_fault_clearance c using (baked_tile_id) "
        "where b.state = 'nondeterminism_detected' order by b.fault_detected_at desc"
    ).fetchall()
    return [
        {
            "baked_tile_id": str(row["baked_tile_id"]),
            "tile": [row["tile_x"], row["tile_y"]],
            "lod": row["lod"],
            "baked_at": row["baked_at"].isoformat(),
            "receipt": row["receipt"],
            "container_sha256": bytes(row["container_sha256"]).hex(),
            "fault_container_sha256": bytes(row["fault_container_sha256"]).hex(),
            "fault_detected_at": row["fault_detected_at"].isoformat(),
            "cleared": row["cleared_at"] is not None,
            "cleared_by": row["cleared_by"],
            "reason": row["reason"],
        }
        for row in rows
    ]


def clear_fault(
    connection: psycopg.Connection, baked_tile_id: uuid.UUID, *, operator: str, reason: str
) -> bool:
    """Record the decision to serve ``baked_tile_id``'s stored first bake. True when this recorded
    it, False when it was already cleared. Refused by the database for a tile with no fault."""
    if _OPERATOR.fullmatch(operator) is None:
        raise ValueError("an operator label is lower case letters, digits and :._-")
    if not 1 <= len(reason) <= 500:
        raise ValueError("a reason is 1 to 500 characters")
    row = connection.execute(
        "insert into baked_tile_fault_clearance (baked_tile_id, cleared_by, reason) "
        "values (%s, %s, %s) on conflict (baked_tile_id) do nothing returning baked_tile_id",
        (baked_tile_id, operator, reason),
    ).fetchone()
    return row is not None


def main(argv: Sequence[str] | None = None, *, stream: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-tile-fault",
        description="List faulted baked tiles, or record the decision to serve one's first bake.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="every faulted tile and whether it is cleared")
    clear = commands.add_parser("clear", help="serve a faulted tile's stored first bake")
    clear.add_argument("--baked-tile", type=uuid.UUID, required=True)
    clear.add_argument("--operator", required=True)
    clear.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    output = stream or sys.stdout
    with Database.from_env().unscoped() as connection:
        if args.command == "list":
            document: Any = {"faulted": faulted_tiles(connection)}
        else:
            recorded = clear_fault(
                connection, args.baked_tile, operator=args.operator, reason=args.reason
            )
            document = {"baked_tile_id": str(args.baked_tile), "recorded": recorded}
    print(json.dumps(document, sort_keys=True), file=output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
