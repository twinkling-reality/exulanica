"""Explicitly hosted playback, bounded and fair across current authorised workspaces.

Before a claimed minute, a host that asks models (``before_minute``) asks the model each chosen
person's world owner picked, with no connection held; a world that runs people by models then
advances one minute per claim, so no person's choice point is passed without being asked.

**Where it runs.** In the API process, in a thread, or in a process of its own
(``exulanica-playback-worker``, :mod:`exulanica.orchestration.playback_worker`) beside an API set
to leave playback to it (``EXULANICA_PLAYBACK_WORKER=process``). Claims and leases decide which
host advances a society, so a host in either place, or several, never advances one twice. A process
of its own says it is alive the one way an API process can see without a table of its own: while it
runs it holds a shared session advisory lock keyed by its playback configuration
(:class:`PlaybackHostLock`), and the API reads ``pg_locks`` for that key
(:class:`PlaybackProcess`). A process that died, or one started with another configuration, holds
no such lock; a process whose loop hangs still holds it, so it reads as running.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import threading
import time
import uuid
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import Final

import psycopg

from exulanica.api.society_runtime import SocietyRuntime
from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.selection.validation import Session
from exulanica.world.society_control_repository import SocietyControlRepository
from exulanica.world.society_controls import (
    DEFAULT_BASE_TICK_INTERVAL_MS,
    LEASE_SECONDS,
    ControlClaim,
    LeaseLost,
    validate_settings,
)

_LOG = logging.getLogger(__name__)

#: Why this host does not advance a workspace's playing societies on its own, by code, in the
#: words a person reads beside the playback control.
HOST_PLAYBACK_REFUSALS = {
    "no_playback_worker": (
        "This server does not advance worlds on their own. Advance one simulated minute at a time."
    ),
    "playback_worker_stopped": (
        "This server's playback has stopped, so this world does not advance on its own until "
        "the server is restarted. Advance one simulated minute at a time."
    ),
    "workspace_not_played": (
        "This server advances other worlds on their own, not this one. Advance one simulated "
        "minute at a time."
    ),
    "guest_towns_full": (
        "Many visitors' worlds are playing on this server right now, so yours waits until one of "
        "them stops. Advance one simulated minute at a time meanwhile."
    ),
}


def host_playback_refusal(
    worker: SocietyControlWorker | None,
    thread: threading.Thread | None,
    workspace: uuid.UUID,
    process: PlaybackProcess | None = None,
) -> str | None:
    """Why this host does not play ``workspace``, by a code of ``HOST_PLAYBACK_REFUSALS``, or None.

    It plays a workspace when its worker thread is alive and the worker's last authority snapshot
    names the workspace. The snapshot is the one the worker's own rounds use, so a workspace that
    account discovery drops stops being played here in the same round it stops being claimed.
    Where a process of its own plays them (``process``), that process is asked instead.
    """
    if process is not None:
        return process.refusal(workspace)
    if worker is None:
        return "no_playback_worker"
    if thread is None or not thread.is_alive():
        return "playback_worker_stopped"
    if workspace not in worker.workspaces:
        return "guest_towns_full" if workspace in worker.waiting else "workspace_not_played"
    return None


#: The profile of the document a playback host's configuration digest is taken over.
PLAYBACK_CONFIGURATION_PROFILE: Final = "exulanica.playback-configuration/v1"
#: How long an API process trusts what it last read of a playback process before reading again.
PRESENCE_SECONDS: Final = 5.0
#: Whether a session holds the shared playback host lock for a key text, as any role reads it.
_PRESENCE: Final = (
    "with host as (select hashtextextended(%s, 0) as k) "
    "select exists(select 1 from pg_locks, host where locktype = 'advisory' and granted "
    "and mode = 'ShareLock' and objsubid = 1 "
    "and classid = ((k >> 32) & 4294967295)::text::oid "
    "and objid = (k & 4294967295)::text::oid) as alive"
)


def playback_configuration_sha256(
    workspaces: Iterable[uuid.UUID],
    *,
    account_discovery: bool,
    base_tick_interval_ms: int,
    guests: tuple[int, int] | None = None,
) -> str:
    """The digest of what a playback host plays: the workspaces it lists, whether it also plays
    the active account workspaces, and its base wait; with guests, how long after a visit their
    towns play and how many at once (``guests``, seconds and the maximum). A playback process and
    the API that leaves playback to it compute it from the same settings."""
    document: dict[str, object] = {
        "profile": PLAYBACK_CONFIGURATION_PROFILE,
        "workspaces": sorted(str(workspace) for workspace in workspaces),
        "account_discovery": account_discovery,
        "base_tick_interval_ms": base_tick_interval_ms,
    }
    if guests is not None:
        document["guests"] = {"play_seconds": guests[0], "playing_maximum": guests[1]}
    return hashlib.sha256(canonical_json(document)).hexdigest()


def playback_host_key(configuration_sha256: str) -> str:
    """The text whose ``hashtextextended`` is a playback host's advisory lock key."""
    return f"{PLAYBACK_CONFIGURATION_PROFILE}:{configuration_sha256}"


class PlaybackHostLock:
    """Held by a playback process while it runs: a shared session advisory lock on one idle
    connection, keyed by its configuration. Shared, so several processes with one configuration
    each hold it; released when the connection closes, so a process that dies holds nothing."""

    def __init__(self, database: Database, configuration_sha256: str) -> None:
        self._database = database
        self._key = playback_host_key(configuration_sha256)
        self._held = contextlib.ExitStack()

    def __enter__(self) -> PlaybackHostLock:
        with contextlib.ExitStack() as unless_held:
            connection = unless_held.enter_context(self._database.unscoped())
            connection.execute(
                "select pg_advisory_lock_shared(hashtextextended(%s, 0))", (self._key,)
            )
            # A session lock outlives the transaction its statement opened. Ending it leaves the
            # connection idle, holding no snapshot for as long as the process runs.
            connection.commit()
            self._held = unless_held.pop_all()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._held.close()


class PlaybackProcess:
    """What an API process that leaves playback to a process of its own says of that process.

    It plays a workspace when a process holds the playback host lock for this host's own
    configuration (:class:`PlaybackHostLock`) and the workspace is one that configuration plays:
    listed, or, with account discovery, an active account-owned workspace. Both are read again at
    most every :data:`PRESENCE_SECONDS`.
    """

    def __init__(
        self,
        database: Database,
        *,
        workspaces: Iterable[uuid.UUID],
        account_discovery: bool,
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None,
        base_tick_interval_ms: int,
        guests: tuple[int, int] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._database = database
        self._listed = frozenset(workspaces)
        self._workspace_source = workspace_source
        self.configuration_sha256 = playback_configuration_sha256(
            self._listed,
            account_discovery=account_discovery,
            base_tick_interval_ms=base_tick_interval_ms,
            guests=guests,
        )
        self._clock = clock
        self._lock = threading.Lock()
        self._read: tuple[float, bool, frozenset[uuid.UUID], frozenset[uuid.UUID]] | None = None

    def refusal(self, workspace: uuid.UUID) -> str | None:
        """``playback_worker_stopped``, ``guest_towns_full``, ``workspace_not_played`` or None, as
        a thread's host answers (:func:`host_playback_refusal`)."""
        alive, played, waiting = self._state()
        if not alive:
            return "playback_worker_stopped"
        if workspace not in played:
            return "guest_towns_full" if workspace in waiting else "workspace_not_played"
        return None

    @property
    def alive(self) -> bool:
        return self._state()[0]

    def _state(self) -> tuple[bool, frozenset[uuid.UUID], frozenset[uuid.UUID]]:
        now = self._clock()
        with self._lock:
            if self._read is not None and now - self._read[0] < PRESENCE_SECONDS:
                return self._read[1], self._read[2], self._read[3]
        with self._database.unscoped() as connection:
            alive = bool(
                connection.execute(
                    _PRESENCE, (playback_host_key(self.configuration_sha256),)
                ).fetchone()["alive"]
            )
        discovered = () if self._workspace_source is None else self._workspace_source()
        played = self._listed | frozenset(discovered)
        waiting = frozenset(getattr(discovered, "waiting", ())) - played
        with self._lock:
            self._read = (now, alive, played, waiting)
        return alive, played, waiting


class SocietyControlWorker:
    def __init__(
        self,
        database: Database,
        *,
        runtime: SocietyRuntime,
        workspaces: Iterable[uuid.UUID],
        workspace_source: Callable[[], Iterable[uuid.UUID]] | None = None,
        base_tick_interval_ms: int = DEFAULT_BASE_TICK_INTERVAL_MS,
        before_minute: Callable[[ControlClaim, float], bool] | None = None,
        workers: int = 1,
    ) -> None:
        validate_settings("paused", 1, base_tick_interval_ms)
        if not 1 <= workers <= 8:
            raise ValueError("a playback round runs 1 to 8 workspaces' claims at once")
        #: How many workspaces' claims a round runs at once. 1 plays them in turn on the calling
        #: thread, as before the setting existed; more, on a pool of that many threads, each claim
        #: still its own lease and session, so a slow model answer in one workspace does not hold
        #: another's minute.
        self.workers = workers
        self._pool: ThreadPoolExecutor | None = None
        self.database, self.runtime = database, runtime
        #: Asks the chosen models before a claimed minute, given the claim and the monotonic time
        #: its lease runs out; says whether the world runs people by models.
        self._before_minute = before_minute
        self._configured_workspaces = frozenset(workspaces)
        self._workspace_source = workspace_source
        self._workspace_lock = threading.Lock()
        self._current_workspaces = self._configured_workspaces
        self._waiting_workspaces: frozenset[uuid.UUID] = frozenset()
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

    @property
    def waiting(self) -> frozenset[uuid.UUID]:
        """The workspaces the last snapshot found there but left unplayed: guests' towns past the
        playing maximum (:class:`~exulanica.db.account_workspaces.WatchedWorkspaces`)."""
        with self._workspace_lock:
            return self._waiting_workspaces

    def _workspace_snapshot(self) -> tuple[uuid.UUID, ...]:
        discovered = () if self._workspace_source is None else self._workspace_source()
        resolved = self._configured_workspaces | frozenset(discovered)
        if any(type(workspace) is not uuid.UUID for workspace in resolved):
            raise TypeError("society workspace discovery must return UUIDs")
        waiting = frozenset(getattr(discovered, "waiting", ())) - resolved
        with self._workspace_lock:
            self._current_workspaces = resolved
            self._waiting_workspaces = waiting
        return tuple(sorted(resolved, key=str))

    def _authorizer(
        self, connection: psycopg.Connection, workspace: uuid.UUID
    ) -> Callable[[uuid.UUID, dict], None]:
        return lambda actor, doc: self.runtime.authorize(
            connection, Session(workspace_id=workspace, actor=actor), doc
        )

    def _repository(
        self,
        connection: psycopg.Connection,
        workspace: uuid.UUID,
        world_id: str,
    ) -> SocietyControlRepository:
        return SocietyControlRepository(
            connection,
            workspace,
            world_id=world_id,
            base_tick_interval_ms=self.base_tick_interval_ms,
            input_authorizer=self._authorizer(connection, workspace),
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
        # The claim considers every world the workspace holds and names the world it was taken
        # in. It runs only in that world.
        with self.database.session(workspace) as connection:
            claim = SocietyControlRepository.claim_in_workspace(
                connection,
                workspace,
                input_authorizer=self._authorizer(connection, workspace),
                base_tick_interval_ms=self.base_tick_interval_ms,
            )
        if claim is None:
            return None
        lease_ends = time.monotonic() + LEASE_SECONDS
        one_minute = False
        if self._before_minute is not None:
            try:
                one_minute = self._before_minute(claim, lease_ends)
            except Exception:
                # The routine decides this minute; never the exception's text, which may carry
                # request bytes or a credential.
                _LOG.error("Society model decisions failed before a minute; the routine decides")
                one_minute = True
        # Committed lease survives process death. No connection is retained between phases.
        try:
            with self.database.session(workspace) as connection:
                return self._repository(connection, workspace, claim.world_id).execute(
                    claim, max_ticks=1 if one_minute else None
                )
        except LeaseLost:
            return {"status": "lease_lost"}

    def _pooled_round(
        self, workspaces: Iterable[uuid.UUID], stop: threading.Event
    ) -> tuple[bool, bool]:
        """One round's claims, :attr:`workers` at once; whether one failed, and whether every one
        was run (a stop skips those not yet started, as it ends the turn-by-turn round). Each pool
        thread holds the round's snapshot as its own authority."""
        snapshot = frozenset(workspaces)

        def one(workspace: uuid.UUID) -> str:
            if stop.is_set():
                return "skipped"
            self._round_authority.workspaces = snapshot
            try:
                self.run_once(workspace)
            except Exception:
                # As the turn-by-turn round: the lease expires; no bytes or provider text logged.
                _LOG.error("Society playback round failed; its lease remains recoverable")
                return "failed"
            finally:
                del self._round_authority.workspaces
            return "ran"

        # One pool for the run (run() shuts it down), so idle rounds start no threads.
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=self.workers, thread_name_prefix="society-playback"
            )
        outcomes = list(self._pool.map(one, sorted(snapshot, key=str)))
        return "failed" in outcomes, "skipped" not in outcomes

    def _close_pool(self) -> None:
        """Shut the round pool down once its claims under way end, as the round's own pool was:
        run() calls it as it ends, and a failed round to start the next with a new pool."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def run(self, stop: threading.Event, *, poll_seconds: float = 0.25) -> None:
        if not 0.05 <= poll_seconds <= 5:
            raise ValueError("playback polling must be between 0.05 and 5 seconds")
        try:
            self._rounds(stop, poll_seconds)
        finally:
            self._close_pool()

    def _rounds(self, stop: threading.Event, poll_seconds: float) -> None:
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
            if self.workers > 1:
                try:
                    failed, complete = self._pooled_round(workspaces, stop)
                except Exception as exc:
                    # The pool itself failed (no thread to start, for one): a failed round, as a
                    # claim's failure is, and the next round goes on with a new pool.
                    _LOG.error("Society playback round failed: %s", type(exc).__qualname__)
                    self._close_pool()
                    failed, complete = True, True
            else:
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
                            # Leave the committed lease to expire, rather than claiming false
                            # success. Do not log request/source bytes or provider exception text.
                            _LOG.error(
                                "Society playback round failed; its lease remains recoverable"
                            )
                finally:
                    del self._round_authority.workspaces
            if complete:
                if failed:
                    self._record_failed_round()
                else:
                    self._record_successful_round()
            stop.wait(poll_seconds)
