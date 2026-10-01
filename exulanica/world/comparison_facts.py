"""A started comparison's cancellation, and when a host started playing each of its runs.

A comparison started from the application, a society comparison of who decides for a world's
people or a signal comparison of a town's lights, may be cancelled by whoever may start one. The
cancellation is appended once (migration 0130's ``comparison_cancellation``), so a repeated cancel
finds the first and changes nothing, and it is never changed or removed. A host playing the
comparison reads it before each dispatch and stops asking; a start no host holds is closed by the
cancellation itself (:mod:`exulanica.api.society_comparison_worker`).

A host that starts playing a run under its claim appends that fact (``comparison_run_start``), so a
reader tells a run being played from one waiting for its turn: an unfinished run is running while
it has a start under the start's live lease, and queued otherwise.

Every statement names the workspace, the world and the kind. Nothing here asks a model, plays a
minute or closes a run.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.session import set_workspace

__all__ = ["KINDS", "PROGRESS_STATES", "ComparisonFacts", "run_progress"]

#: The kinds of comparison a cancellation or a run start names.
KINDS: Final = ("society", "signal")
#: Where an unfinished run stands: being played by a host, or waiting for its turn.
PROGRESS_STATES: Final = ("queued", "running")


class ComparisonFacts:
    """Append and read one kind of comparison's cancellations and run starts in one world."""

    def __init__(
        self, connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, kind: str
    ) -> None:
        if kind not in KINDS:
            raise ValueError(f"no kind of comparison {kind!r}")
        self.connection, self.workspace_id, self.world_id, self.kind = (
            connection,
            workspace_id,
            world_id,
            kind,
        )
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)

    # -- cancellation ------------------------------------------------------------------------

    def cancel(self, comparison_id: uuid.UUID, requested_by: uuid.UUID) -> dict[str, Any]:
        """The comparison's cancellation, appended now or found appended before: the first
        request is the one kept, whoever sends another."""
        self.connection.execute(
            "insert into comparison_cancellation(workspace_id,world_id,kind,comparison_id,"
            "requested_by) values(%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,kind,comparison_id) do nothing",
            (self.workspace_id, self.world_id, self.kind, comparison_id, requested_by),
        )
        found = self.cancellation(comparison_id)
        assert found is not None, "a cancellation just appended is read back"
        return found

    def cancellation(self, comparison_id: uuid.UUID) -> dict[str, Any] | None:
        """The comparison's cancellation, or None when nobody cancelled it."""
        return self.cancellations([comparison_id]).get(comparison_id)

    def cancellations(self, comparison_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
        """The cancellations of these comparisons of the world, by comparison id."""
        rows = self.connection.execute(
            "select comparison_id,requested_by,requested_at from comparison_cancellation "
            "where workspace_id=%s and world_id=%s and kind=%s and comparison_id=any(%s)",
            (self.workspace_id, self.world_id, self.kind, list(comparison_ids)),
        ).fetchall()
        return {row["comparison_id"]: dict(row) for row in rows}

    # -- run starts --------------------------------------------------------------------------

    def run_started(
        self, comparison_id: uuid.UUID, run_id: uuid.UUID, lease_token: uuid.UUID
    ) -> None:
        """A host holding ``lease_token`` starts playing the run now; the same start again is
        the one kept."""
        self.connection.execute(
            "insert into comparison_run_start(workspace_id,world_id,kind,comparison_id,run_id,"
            "lease_token) values(%s,%s,%s,%s,%s,%s) "
            "on conflict (workspace_id,kind,run_id,lease_token) do nothing",
            (self.workspace_id, self.world_id, self.kind, comparison_id, run_id, lease_token),
        )

    def run_starts(self, comparison_id: uuid.UUID) -> dict[uuid.UUID, list[dict[str, Any]]]:
        """Every start of the comparison's runs, by run id, oldest first."""
        rows = self.connection.execute(
            "select run_id,lease_token,started_at from comparison_run_start where "
            "workspace_id=%s and world_id=%s and kind=%s and comparison_id=%s "
            "order by started_at, lease_token",
            (self.workspace_id, self.world_id, self.kind, comparison_id),
        ).fetchall()
        starts: dict[uuid.UUID, list[dict[str, Any]]] = {}
        for row in rows:
            starts.setdefault(row["run_id"], []).append(dict(row))
        return starts


def run_progress(
    start: Mapping[str, Any] | None,
    starts: Sequence[Mapping[str, Any]],
    now: dt.datetime,
) -> dict[str, Any]:
    """Where one unfinished run stands, from its comparison's ``start`` row and the run's
    ``starts``: running while a start of it was made under the start's live lease, else queued,
    with when that live start began."""
    live = (
        start is not None
        and start["finished_at"] is None
        and start["lease_token"] is not None
        and start["lease_expires_at"] > now
    )
    held = (
        next((row for row in starts if live and row["lease_token"] == start["lease_token"]), None)
        if start is not None
        else None
    )
    return {
        "state": "running" if held is not None else "queued",
        "started_at": None if held is None else held["started_at"].isoformat(),
    }
