"""Explicitly hosted playback, bounded and fair across current authorised workspaces."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable, Iterable

import psycopg

from exulanica.api.society_runtime import SocietyRuntime
from exulanica.db.session import Database
from exulanica.selection.validation import Session
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import LeaseLost, validate_settings

_LOG = logging.getLogger(__name__)


class SocietyControlWorker:
    def __init__(
        self,
        database: Database,
        *,
        runtime: SocietyRuntime,
        workspaces: Iterable[uuid.UUID],
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        base_tick_interval_ms: int = 1000,
    ) -> None:
        validate_settings("paused", 1, base_tick_interval_ms)
        self.database, self.runtime = database, runtime
        self._configured_workspaces = frozenset(workspaces)
        self._workspace_source = workspace_source
        self._workspace_lock = threading.Lock()
        self._current_workspaces = self._configured_workspaces
        self._round_authority = threading.local()
        self.base_tick_interval_ms = base_tick_interval_ms
        self._health_lock = threading.Lock()
        self._failed_rounds = 0
        self._last_round_failed = False

    @property
    def health(self) -> dict[str, int | bool]:
        """Return a coherent, secret-free snapshot for host readiness reporting."""
        with self._health_lock:
            return {
                "failed_rounds": self._failed_rounds,
                "last_round_failed": self._last_round_failed,
            }

    def _record_failed_round(self) -> None:
        with self._health_lock:
            self._failed_rounds += 1
            self._last_round_failed = True

    def _record_successful_round(self) -> None:
        with self._health_lock:
            self._last_round_failed = False

    @property
    def workspaces(self) -> tuple[uuid.UUID, ...]:
        """The last successful authority snapshot, exposed without mutable worker state."""
        with self._workspace_lock:
            return tuple(sorted(self._current_workspaces, key=str))

    def _workspace_snapshot(self) -> tuple[uuid.UUID, ...]:
        discovered = () if self._workspace_source is None else self._workspace_source()
        resolved = self._configured_workspaces | frozenset(discovered)
        if any(type(workspace) is not uuid.UUID for workspace in resolved):
            raise TypeError("society workspace discovery must return UUIDs")
        with self._workspace_lock:
            self._current_workspaces = resolved
        return tuple(sorted(resolved, key=str))

    def _repository(
        self, connection: psycopg.Connection, workspace: uuid.UUID
    ) -> SocietyControlRepository:
        return SocietyControlRepository(
            connection,
            workspace,
            base_tick_interval_ms=self.base_tick_interval_ms,
            input_authorizer=lambda actor, doc: self.runtime.authorize(
                connection, Session(workspace_id=workspace, actor=actor), doc
            ),
        )

    def run_once(self, workspace: uuid.UUID) -> dict | None:
        """Use this round's authority, or refresh it for a direct call outside the loop."""
        workspaces = getattr(self._round_authority, "workspaces", None)
        if workspaces is None:
            workspaces = self._workspace_snapshot()
        if workspace not in workspaces:
            raise ValueError("workspace is not configured for this playback worker")
        return self._run_authorized_once(workspace)

    def _run_authorized_once(self, workspace: uuid.UUID) -> dict | None:
        """Run after the caller captured one fresh, immutable round snapshot."""
        with self.database.session(workspace) as connection:
            claim = self._repository(connection, workspace).claim()
        if claim is None:
            return None
        # Committed lease survives process death. No connection is retained between phases.
        try:
            with self.database.session(workspace) as connection:
                return self._repository(connection, workspace).execute(claim)
        except LeaseLost:
            return {"status": "lease_lost"}

    def run(self, stop: threading.Event, *, poll_seconds: float = 0.25) -> None:
        if not 0.05 <= poll_seconds <= 5:
            raise ValueError("playback polling must be between 0.05 and 5 seconds")
        while not stop.is_set():
            failed = False
            complete = True
            try:
                workspaces = self._workspace_snapshot()
            except Exception:
                self._record_failed_round()
                _LOG.error("Society playback workspace discovery failed")
                stop.wait(poll_seconds)
                continue
            # One claim per workspace per round, at most 3 ticks per claim. A busy workspace
            # cannot drain its entire backlog before another workspace is considered. The
            # thread-local snapshot lets run_once preserve its public test/direct-call seam
            # without turning a cached readiness value into authority for another thread.
            self._round_authority.workspaces = frozenset(workspaces)
            try:
                for workspace in workspaces:
                    if stop.is_set():
                        complete = False
                        break
                    try:
                        self.run_once(workspace)
                    except Exception:
                        failed = True
                        # Leave the committed lease to expire, rather than claiming false success.
                        # Do not log request/source bytes or provider exception text.
                        _LOG.error("Society playback round failed; its lease remains recoverable")
            finally:
                del self._round_authority.workspaces
            if complete:
                if failed:
                    self._record_failed_round()
                else:
                    self._record_successful_round()
            stop.wait(poll_seconds)
