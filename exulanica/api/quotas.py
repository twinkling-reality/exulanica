"""Per-workspace tile quotas: a ceiling on the tiles one workspace may have materialised on demand.

**Why this exists before anything it meters.** Tiles are baked offline and no on-demand tile
route ships. The first such route is a compute amplifier: one request turns into a
tessellation, and a loop of requests turns into a bill and a full disk. So the ceiling lands
first, and the route that needs it inherits it by declaration rather than by remembering to call
it. :func:`exulanica.api.dependencies.authorise_route` charges one tile against this table for
every request to a route whose declaration in :mod:`exulanica.api.permissions` requires
``tiles.materialise``, before the route runs, as the non-owner runtime role under row-level
security. A tile route cannot opt out, because the charge happens in the dependency every route
already runs.

**No declared quota is no quota.** A workspace with no row here materialises nothing. There is no
default ceiling, because a default ceiling is a number nobody chose, and the answer names the
missing declaration rather than pretending the workspace used its allowance.

**A ceiling, not a rate.** ``tiles_used`` only ever rises, and the operator raises
``tiles_limit`` deliberately, the way ``exulanica.models.budget`` asks for its own ceiling to be
raised. A rate needs a clock and a window, which is a policy the tile route will own; nothing
here reads the time.

**The charge is pessimistic.** It is taken before the tile is materialised and not refunded when
materialisation fails, for the reason the model budget reserves before a call: charging less
than a request can cost lets the last request cross the ceiling, which is the one thing the
ceiling exists to prevent. A refused charge is never retried; retrying is the loop being stopped.

**Integers only.** Both counters are ``bigint`` in the table and ``int`` here, and
:meth:`TileQuota.document` passes through :func:`exulanica.canonical.canonical_json`, which
refuses a float outright. The audit timestamps are in the table and never in the document.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from exulanica.canonical import canonical_json
from exulanica.errors import ExulanicaError

if TYPE_CHECKING:
    import psycopg

__all__ = [
    "TILE_QUOTA_TABLE",
    "TileQuota",
    "TileQuotaError",
    "TileQuotaExceeded",
    "TileQuotaUndeclared",
    "charge_tiles",
    "declare_tile_quota",
    "read_tile_quota",
]

TILE_QUOTA_TABLE: Final = "workspace_tile_quota"


class TileQuotaError(ExulanicaError):
    """A tile charge was refused, so nothing was materialised. Never retry it."""


class TileQuotaExceeded(TileQuotaError):
    """The charge would take the workspace past its declared ceiling."""


class TileQuotaUndeclared(TileQuotaError):
    """The workspace has no declared tile quota, so it may materialise nothing."""


def _whole(value: object, name: str, *, minimum: int) -> int:
    # bool is an int in Python and a quota of True tiles is a bug, not a quota.
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


@dataclass(frozen=True, slots=True)
class TileQuota:
    """One workspace's ceiling and what it has used, as integers."""

    workspace_id: uuid.UUID
    tiles_limit: int
    tiles_used: int

    def __post_init__(self) -> None:
        _whole(self.tiles_limit, "tiles_limit", minimum=0)
        _whole(self.tiles_used, "tiles_used", minimum=0)
        if self.tiles_used > self.tiles_limit:
            raise ValueError("tiles_used cannot exceed tiles_limit")

    @property
    def tiles_remaining(self) -> int:
        return self.tiles_limit - self.tiles_used

    def document(self) -> dict[str, object]:
        """The wire shape, checked by the canonical serialiser so a float cannot reach it."""
        document: dict[str, object] = {
            "workspace_id": str(self.workspace_id),
            "tiles_limit": self.tiles_limit,
            "tiles_used": self.tiles_used,
            "tiles_remaining": self.tiles_remaining,
        }
        canonical_json(document)
        return document


def _quota(row: object) -> TileQuota:
    return TileQuota(
        workspace_id=row["workspace_id"],  # type: ignore[index]
        tiles_limit=int(row["tiles_limit"]),  # type: ignore[index]
        tiles_used=int(row["tiles_used"]),  # type: ignore[index]
    )


def read_tile_quota(connection: psycopg.Connection, workspace_id: uuid.UUID) -> TileQuota | None:
    """The workspace's quota, or None when none is declared."""
    row = connection.execute(
        "select workspace_id, tiles_limit, tiles_used from workspace_tile_quota "
        "where workspace_id = %s",
        (workspace_id,),
    ).fetchone()
    return None if row is None else _quota(row)


def declare_tile_quota(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    tiles_limit: int,
    declared_by: uuid.UUID,
) -> TileQuota:
    """Declare or change a workspace's ceiling. An operator act, never a request's.

    A ceiling below what has already been used is refused by the table's check constraint
    rather than silently raised to meet it: lowering a ceiling past its usage is a decision
    somebody has to make out loud.
    """
    _whole(tiles_limit, "tiles_limit", minimum=0)
    row = connection.execute(
        "insert into workspace_tile_quota (workspace_id, tiles_limit, declared_by) "
        "values (%s, %s, %s) "
        "on conflict (workspace_id) do update set tiles_limit = excluded.tiles_limit, "
        "declared_by = excluded.declared_by, declared_at = statement_timestamp() "
        "returning workspace_id, tiles_limit, tiles_used",
        (workspace_id, tiles_limit, declared_by),
    ).fetchone()
    assert row is not None
    return _quota(row)


def charge_tiles(connection: psycopg.Connection, workspace_id: uuid.UUID, tiles: int) -> TileQuota:
    """Take ``tiles`` from the workspace's quota in one statement, or refuse and take nothing.

    The update carries the ceiling in its own predicate, so two requests racing for the last
    tile are serialised by the row lock and exactly one of them matches. The table's check
    constraint says the same thing a second time, so a charge that bypassed this function
    still could not cross the ceiling.
    """
    _whole(tiles, "tiles", minimum=1)
    row = connection.execute(
        "update workspace_tile_quota set tiles_used = tiles_used + %(tiles)s "
        "where workspace_id = %(workspace)s and tiles_used + %(tiles)s <= tiles_limit "
        "returning workspace_id, tiles_limit, tiles_used",
        {"tiles": tiles, "workspace": workspace_id},
    ).fetchone()
    if row is not None:
        return _quota(row)
    current = read_tile_quota(connection, workspace_id)
    if current is None:
        raise TileQuotaUndeclared(
            "this workspace has no declared tile quota, so it may materialise no tiles. There is "
            "no default ceiling; an operator declares one."
        )
    raise TileQuotaExceeded(
        f"this request needs {tiles} tile(s) and the workspace has {current.tiles_remaining} of "
        f"{current.tiles_limit} left. Nothing was materialised. Do not retry: the ceiling is "
        "raised deliberately or not at all."
    )
