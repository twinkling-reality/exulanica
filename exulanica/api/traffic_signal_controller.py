"""Prepare and seal a saved world's traffic minutes before any viewer asks for them.

One controller thread rotates the worlds with recorded signal choices and the worlds whose clock
is coupled. At most the catalog's pending bound of world preparations run together; one spawned
traffic process computes pure segments and is released between choice points. The API process
alone reserves, asks through the shared model client and budget, records, and seals. A viewer may
replay sealed minutes through the same pure process, but it never reaches the ask path. No model
is asked while a connection, a transaction or a lock is held: a point is reserved and closed, the
model is asked with no connection, and the answer is recorded in a transaction of its own.

**Legacy traffic** keeps the wall clock: minutes are prepared up to two ahead of it. A world that
fell more than the legacy profile's episodes behind (after downtime, say) starts a fresh chain at
the current episode rather than sealing every minute it missed, and records the skipped span as a
``legacy_signal_gap`` clock receipt; minutes already sealed are never touched.

**Coupled traffic** follows its world's society (:mod:`exulanica.world.world_clock`): it seals
traffic minute ``k`` once the society has committed minute ``k + 1``, feeding the minute's steps the
crossing occupancy the society recorded, at most the profile's minutes a turn. It keeps no
continuation in the database: the process keeps them, and after a restart one episode is computed
again and every sealed digest checked. A fault in what it reads blocks the world's traffic by name
and the society waits; a lasting refusal of its roads makes traffic unavailable for the era and
the society goes on without it.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import suppress
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from exulanica.api.decision_host import (
    RoleAsk,
    ask,
    ask_bound_usd,
    host_refusal,
    model_refusal,
    question_refusal,
    share_kept,
)
from exulanica.db.session import Database
from exulanica.models.client import ModelClient
from exulanica.models.errors import ManifestError
from exulanica.models.manifest import MANIFEST_PATH, Manifest, load_manifest
from exulanica.movement.flight_episodes import watch_parent
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.episode_worker import worker_pool
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import unreadable_reason
from exulanica.world.traffic_episodes import (
    EPISODE,
    TrafficInput,
    TrafficRefused,
    compute_band_identities,
    compute_coupled_segments,
    compute_signal_catalog,
    compute_signal_probe,
    compute_signal_replay,
    coupled_frames_sha256,
    feeds_wire,
    window_of_segments,
    wire,
)
from exulanica.world.traffic_host import saved_world_roads
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository
from exulanica.world.world_clock import (
    COUPLED,
    LEGACY,
    ClockRefused,
    clock_profile,
    crossing_feeds,
    feed_projection_sha256,
    occupancy_intervals,
)
from exulanica.world.world_clock_repository import WorldClockRepository, era_of

__all__ = ["TrafficSignalController"]

_LOG = logging.getLogger(__name__)
_PROBE_SECONDS = 30.0
_SEGMENTS_PER_TURN = EPISODE // 60
# Cover the entire effective minute: selection is at least one minute ahead and rounds upward.
_PREPARED_MINUTES_AHEAD = 2
#: Continuations of coupled minutes this process keeps, by version, era, episode and segment.
_CONTINUATIONS_KEPT = 64
#: Faults in what a coupled world's traffic reads: its traffic is blocked and its society waits.
_BLOCKING = frozenset(
    {
        "crossing_occupancy_missing",
        "crossing_occupancy_mismatch",
        "crossing_occupancy_unmapped",
        "crossing_edge_ambiguous",
        "traffic_replay_mismatch",
        "traffic_minute_sealed_differently",
        "coupled_roads_changed",
    }
)
#: Lasting refusals of a coupled world's roads: its traffic is unavailable for the era.
_LASTING = frozenset({"roads_unavailable", "roads_world_too_large", "roads_not_stated"})


def _fallback(reason: str, provider: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {"status": "unavailable", "reason": reason, "proposal": None, "provider": provider}


class TrafficSignalController:
    """Time-driven preparation and read-only replay of durable traffic segments."""

    def __init__(
        self,
        database: Database,
        client: ModelClient | None,
        workspaces: tuple[uuid.UUID, ...],
        policy_for: Callable[[uuid.UUID], Any],
        *,
        manifest: Manifest | None = None,
        clock: Callable[[], float] = time.time,
        probe_pool: ProcessPoolExecutor | None = None,
    ) -> None:
        self.database = database
        self.client = client
        self.workspaces = workspaces
        self.policy_for = policy_for
        self.manifest = manifest or load_manifest()
        self.manifest_sha256 = hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest()
        self.clock = clock
        self.role: DecisionRole = decision_roles().deciding_for("signal")
        self._pool = probe_pool
        self._owns_pool = probe_pool is None
        self._pool_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._turn = 0
        self._cache_lock = threading.Lock()
        self._bands: OrderedDict[str, dict[str, str]] = OrderedDict()
        self._continuations: OrderedDict[tuple[Any, ...], dict[str, Any]] = OrderedDict()

    def _process(self) -> ProcessPoolExecutor:
        with self._pool_lock:
            if self._stop.is_set():
                raise SignalChoiceRefused("traffic_worker_unavailable")
            if self._pool is None:
                self._pool = worker_pool(watch_parent)
            return self._pool

    def _retire_pool(self, pool: ProcessPoolExecutor) -> None:
        """Stop and reap an owned worker, including Python versions without terminate_workers."""
        with self._pool_lock:
            if self._pool is pool:
                self._pool = None
        if not self._owns_pool:
            return
        if hasattr(pool, "terminate_workers"):
            with suppress(BrokenProcessPool, OSError, RuntimeError):
                pool.terminate_workers()
            return
        # ProcessPoolExecutor.shutdown(wait=False) cancels queued jobs but leaves a running
        # child alive on Python 3.11. Its process map is the only bounded kill path there.
        processes = tuple((getattr(pool, "_processes", None) or {}).values())
        # The pool's manager thread joins these same children, and shutdown() drops its
        # reference, so it is taken first. Two threads waiting on one child race: the one whose
        # waitpid loses records no exit code, and a reaped child then still reads as running.
        manager = getattr(pool, "_executor_manager_thread", None)
        for process in processes:
            try:
                if process.is_alive():
                    process.terminate()
            except (AssertionError, OSError):
                pass
        pool.shutdown(wait=False, cancel_futures=True)
        if manager is not None:
            with suppress(RuntimeError):
                manager.join(timeout=1.0)
        for process in processes:
            try:
                if process.pid is not None:
                    process.join(timeout=0.5)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=0.5)
            except (AssertionError, OSError):
                pass

    def _worker(self, function: Callable[..., Any], *args: Any) -> Any:
        """One pure job; a dead owned process is discarded once, never reused by a viewer."""
        for attempt in range(2):
            if self._stop.is_set():
                raise SignalChoiceRefused("traffic_worker_unavailable")
            try:
                pool = self._process()
            except (OSError, RuntimeError):
                raise SignalChoiceRefused("traffic_worker_unavailable") from None
            future = None
            try:
                future = pool.submit(function, *args)
                return future.result(timeout=_PROBE_SECONDS)
            except (BrokenProcessPool, CancelledError, TimeoutError):
                if future is not None:
                    future.cancel()
                if not self._owns_pool:
                    raise SignalChoiceRefused("traffic_worker_unavailable") from None
                self._retire_pool(pool)
                if attempt:
                    raise SignalChoiceRefused("traffic_worker_unavailable") from None
        raise SignalChoiceRefused("traffic_worker_unavailable")

    def start(self) -> None:
        if not self.workspaces or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="traffic-signal-controller", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        with self._pool_lock:
            pool = self._pool
        if pool is not None:
            self._retire_pool(pool)
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.run_cycle()
            except Exception as exc:
                _LOG.exception("Traffic signal preparation cycle failed: %s", type(exc).__name__)
            self._stop.wait(1)

    def _worlds(self) -> list[tuple[uuid.UUID, str, uuid.UUID]]:
        worlds = []
        for workspace_id in self.workspaces:
            with self.database.session(workspace_id) as connection:
                rows = connection.execute(
                    "select world_id,version_id from world_traffic_signal_choice "
                    "where workspace_id=%s union select world_id,version_id from world_clock "
                    "where workspace_id=%s and traffic_state='running' "
                    "order by world_id,version_id",
                    (workspace_id, workspace_id),
                ).fetchall()
            worlds.extend((workspace_id, row["world_id"], row["version_id"]) for row in rows)
        return sorted(worlds)

    def run_cycle(self) -> None:
        """One fair batch; each world gets at most one trip episode per turn."""
        worlds = self._worlds()
        if not worlds:
            return
        limit = signal_actuation().pending_handoffs_maximum
        first = self._turn % len(worlds)
        selected = (worlds[first:] + worlds[:first])[:limit]
        self._turn = (first + len(selected)) % len(worlds)
        with ThreadPoolExecutor(max_workers=limit) as threads:
            futures = [(world, threads.submit(self.prepare_world, *world)) for world in selected]
            for world, future in futures:
                try:
                    future.result()
                except Exception as exc:
                    _LOG.exception(
                        "Traffic signal preparation failed for %s: %s",
                        world[1],
                        type(exc).__name__,
                    )

    def prepare_world(self, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID) -> int:
        """Prepare one episode's minutes, including fixed prefixes before activation; a coupled
        world's minutes are sealed as its society commits them instead."""
        if self._stop.is_set():
            return 0
        with self.database.session(workspace_id) as connection:
            coupled = WorldClockRepository(connection, workspace_id, world_id).row(version_id)
            if coupled is None:
                repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
                row = connection.execute(
                    "select source_snapshot_id from world_alternate_version where workspace_id=%s "
                    "and world_id=%s and version_id=%s",
                    (workspace_id, world_id, version_id),
                ).fetchone()
                if row is None:
                    return 0
                value = saved_world_roads(
                    connection, workspace_id, world_id, row["source_snapshot_id"]
                )
                latest = repository.latest_any_segment()
                earliest = min(choice["effective_second"] for choice in repository._choices())
        if coupled is not None:
            if coupled["traffic_state"] != "running":
                return 0
            return self._follow(workspace_id, world_id, version_id)
        current_episode = int(self.clock()) // EPISODE
        if latest is None:
            episode = min(current_episode, earliest // EPISODE)
            segment = 0
        else:
            episode, segment = latest["episode"], latest["segment"] + 1
            if segment == EPISODE // signal_actuation().segment_seconds:
                episode, segment = episode + 1, 0
        reach = clock_profile(LEGACY).legacy_signal_catchup_episodes
        if episode < current_episode - reach:
            # Further behind than the profile lets a legacy signal catch up: the minutes it missed
            # are left unsealed and said so, and the chain starts again at the current episode.
            self._legacy_gap(
                workspace_id,
                world_id,
                version_id,
                episode * EPISODE + segment * signal_actuation().segment_seconds,
                current_episode * EPISODE,
            )
            episode, segment = current_episode, 0
        target_end = (int(self.clock()) // 60 + _PREPARED_MINUTES_AHEAD) * 60
        prepared = 0
        while prepared < _SEGMENTS_PER_TURN and not self._stop.is_set():
            start = episode * EPISODE + segment * 60
            if start >= target_end:
                break
            for attempt in range(2):
                try:
                    self._prepare_segment(
                        workspace_id, world_id, version_id, value, episode, segment
                    )
                    break
                except SignalChoiceRefused as exc:
                    if exc.code != "segment_choice_changed" or attempt:
                        raise
            prepared += 1
            segment += 1
            if segment == EPISODE // 60:
                episode, segment = episode + 1, 0
        return prepared

    def _legacy_gap(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        from_second: int,
        to_second: int,
    ) -> None:
        """Record, once, that a legacy signal's minutes from ``from_second`` up to ``to_second``
        were skipped rather than sealed."""
        with self.database.session(workspace_id) as connection, connection.transaction():
            TrafficSignalRepository(connection, workspace_id, world_id, version_id)._lock_version()
            clocks = WorldClockRepository(connection, workspace_id, world_id)
            if clocks.row(version_id) is not None:
                # Coupled since this turn read it: its traffic keeps the clock now, and no legacy
                # minute is skipped.
                return
            recorded = connection.execute(
                "select 1 from world_clock_event where workspace_id=%s and world_id=%s "
                "and version_id=%s and kind='legacy_signal_gap' "
                "and document->>'from_second'=%s and document->>'to_second'=%s",
                (workspace_id, world_id, version_id, str(from_second), str(to_second)),
            ).fetchone()
            if recorded is None:
                clocks.record_event(
                    version_id,
                    "legacy_signal_gap",
                    {
                        "from_second": from_second,
                        "to_second": to_second,
                        "skipped_seconds": to_second - from_second,
                        "episodes_allowed": clock_profile(LEGACY).legacy_signal_catchup_episodes,
                    },
                )

    def _prepare_segment(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        episode: int,
        segment: int,
    ) -> None:
        end_local = (segment + 1) * 60
        with self.database.session(workspace_id) as connection:
            repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            previous = repository.segment(episode, segment - 1) if segment else None
            prior_episode = repository.segment(episode - 1, 19) if not segment and episode else None
            if segment and previous is None:
                raise SignalChoiceRefused("previous_segment_missing")
            continuation = None if previous is None else previous["continuation"]
            initial_cursors = (
                continuation["initial_signal_cursors"]
                if continuation is not None
                else prior_episode["continuation"]["signal_cursors"]
                if prior_episode is not None
                else {}
            )
            choices = {
                signal: {int(second): action for second, action in row.items()}
                for signal, row in (continuation or {}).get("signal_choices", {}).items()
            }
            active_choices = repository.choices_at(episode * EPISODE + segment * 60)
            selected_generations = {
                signal: row["choice_seq"] for signal, row in active_choices.items()
            }
            selected = tuple(
                sorted(signal for signal, row in active_choices.items() if row["model"] is not None)
            )
        states: list[dict[str, Any]] = []
        while not self._stop.is_set():
            answer = self._worker(
                compute_signal_probe,
                wire(value),
                episode,
                end_local,
                continuation,
                choices,
                initial_cursors,
                selected,
            )
            states.extend(answer["states"])
            continuation = answer["continuation"]
            point = answer["point"]
            if point is None:
                break
            action = self._answer_point(
                workspace_id, world_id, version_id, value, episode, segment, point
            )
            choices.setdefault(point["signal_id"], {})[point["choice_second"]] = action
        if self._stop.is_set():
            return
        assert continuation is not None
        with self.database.session(workspace_id) as connection:
            repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            repository.seal_segment(
                role=self.role,
                roads_version=value.version_id,
                input_sha256=value.sha256,
                episode=episode,
                segment=segment,
                states=states,
                continuation=continuation,
                selected_generations=selected_generations,
            )

    # -- a coupled world's traffic ---------------------------------------------------------------

    def bands(self, value: TrafficInput) -> dict[str, str]:
        """Each band's ``society_crossing_id`` by its crossing record identity, from the pure
        worker, kept by the roads' input digest."""
        with self._cache_lock:
            found = self._bands.get(value.sha256)
            if found is not None:
                self._bands.move_to_end(value.sha256)
                return found
        found = self._worker(compute_band_identities, wire(value))
        with self._cache_lock:
            self._bands[value.sha256] = found
            while len(self._bands) > 8:
                self._bands.popitem(last=False)
        return found

    def _follow(self, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID) -> int:
        """Seal what the society lets a coupled world's traffic seal, at most the profile's
        minutes this turn; hold its traffic by name when what it reads is wrong."""
        sealed = 0
        era = 0
        while sealed < clock_profile(COUPLED).follower_minutes_per_turn:
            if self._stop.is_set():
                break
            try:
                era = self._seal_next_minute(workspace_id, world_id, version_id)
            except ClockRefused as error:
                if error.code in _BLOCKING:
                    self._hold(workspace_id, world_id, version_id, "blocked", error.code)
                    break
                raise
            except TrafficRefused as error:
                if error.code in _BLOCKING:
                    self._hold(workspace_id, world_id, version_id, "blocked", error.code)
                    break
                if error.code in _LASTING:
                    self._hold(workspace_id, world_id, version_id, "unavailable", error.code)
                    break
                raise
            except UnsupportedNetworkError:
                self._hold(workspace_id, world_id, version_id, "unavailable", "roads_unavailable")
                break
            except InvalidStructuralData as error:
                self._hold(
                    workspace_id, world_id, version_id, "unavailable", unreadable_reason(error)
                )
                break
            if not era:
                break
            sealed += 1
        return sealed

    def _hold(
        self, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID, state: str, code: str
    ) -> None:
        with self.database.session(workspace_id) as connection:
            clocks = WorldClockRepository(connection, workspace_id, world_id)
            clock = clocks.row(version_id)
            if clock is not None:
                clocks.hold_traffic(version_id, era=clock["era"], state=state, code=code)
        _LOG.error("Coupled traffic of %s held %s: %s", world_id, state, code)

    def _seal_next_minute(
        self, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
    ) -> int:
        """Seal the next traffic minute a coupled world's society lets through; answer the era
        sealed in, or 0 when there is nothing to seal yet."""
        with self.database.session(workspace_id) as connection:
            clocks = WorldClockRepository(connection, workspace_id, world_id)
            clock = clocks.row(version_id)
            if clock is None or clock["traffic_state"] != "running":
                return 0
            world_tick = clock["traffic_sealed_through_tick"] + 1
            # Traffic's minute needs the society's minute after it: its admissions look sixty
            # seconds ahead for walkers.
            if world_tick + 1 > clock["society_tick"]:
                return 0
            row = connection.execute(
                "select source_snapshot_id from world_alternate_version where workspace_id=%s "
                "and world_id=%s and version_id=%s",
                (workspace_id, world_id, version_id),
            ).fetchone()
            if row is None:
                return 0
            value = saved_world_roads(connection, workspace_id, world_id, row["source_snapshot_id"])
            if value.version_id != clock["roads_version"] or value.sha256 != clock["input_sha256"]:
                raise ClockRefused("coupled_roads_changed", "the roads are not those coupled")
            era = era_of(clock)
            start = era.traffic_second(era.world_second_of_tick(world_tick - 1))
            episode, local = divmod(start, EPISODE)
            segment = local // 60
            documents, sealed, initial_cursors = self._episode_facts(
                clocks, clock, episode, segment, through_tick=world_tick + 1
            )
            signals = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            active_choices = signals.choices_at(start)
            selected_generations = {
                signal: row["choice_seq"] for signal, row in active_choices.items()
            }
            selected = tuple(
                sorted(signal for signal, row in active_choices.items() if row["model"] is not None)
            )
        feeds = crossing_feeds(
            occupancy_intervals(documents),
            era=era,
            episode_first_second=episode * EPISODE,
            covers_through_local_second=60 * (segment + 1) + 59,
            bands=self.bands(value),
        )
        continuation = (
            None
            if segment == 0
            else self._continuation_at(
                version_id, clock["era"], value, episode, sealed, feeds, initial_cursors
            )
        )
        choices = {
            signal: {int(second): action for second, action in made.items()}
            for signal, made in (continuation or {}).get("signal_choices", {}).items()
        }
        digests: list[str] = []
        while not self._stop.is_set():
            answer = self._worker(
                compute_signal_probe,
                wire(value),
                episode,
                60 * (segment + 1),
                continuation,
                choices,
                initial_cursors,
                selected,
                feeds_wire(feeds),
                True,
            )
            digests.extend(answer["state_sha256s"])
            continuation = answer["continuation"]
            point = answer["point"]
            if point is None:
                break
            action = self._answer_point(
                workspace_id, world_id, version_id, value, episode, segment, point, coupled=True
            )
            choices.setdefault(point["signal_id"], {})[point["choice_second"]] = action
        if self._stop.is_set():
            return 0
        assert continuation is not None
        with self.database.session(workspace_id) as connection:
            WorldClockRepository(connection, workspace_id, world_id).seal_minute(
                version_id,
                era=clock["era"],
                world_tick=world_tick,
                occupancy_through_tick=world_tick + 1,
                feed_sha256=feed_projection_sha256(feeds),
                frames_sha256=coupled_frames_sha256(
                    digests, continuation["signal_choices"], continuation["initial_signal_cursors"]
                ),
                continuation=continuation,
                selected_generations=selected_generations,
                role=self.role,
            )
        self._remember((version_id, clock["era"], episode, segment + 1), continuation)
        return clock["era"]

    def _episode_facts(
        self,
        clocks: WorldClockRepository,
        clock: Mapping[str, Any],
        episode: int,
        segment: int,
        *,
        through_tick: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
        """What rebuilding a coupled episode through ``segment`` reads: the occupancy it feeds on,
        its minutes sealed before ``segment``, and the phase cursors it began with."""
        era = era_of(clock)
        first_tick = era.world_second(episode * EPISODE) // era.seconds_per_tick + 1
        # A walker who stepped onto a crossing up to two minutes before the episode may still be
        # on it; the projection clips what it reads to the episode.
        documents = clocks.occupancy(
            clock,
            first_tick=max(clock["era_start_tick"] + 1, first_tick - 2),
            through_tick=through_tick,
        )
        sealed = [dict(row["document"]) for row in clocks.minutes(clock, episode)][:segment]
        if [row["segment"] for row in sealed] != list(range(segment)):
            raise ClockRefused(
                "crossing_occupancy_missing", f"minutes before {segment} of episode {episode}"
            )
        before = clocks.minute(clock, first_tick - 1)
        initial = {} if before is None else dict(before["document"]["signal_cursors"])
        return documents, sealed, initial

    def _remember(self, key: tuple[Any, ...], continuation: dict[str, Any]) -> None:
        with self._cache_lock:
            self._continuations[key] = continuation
            self._continuations.move_to_end(key)
            while len(self._continuations) > _CONTINUATIONS_KEPT:
                self._continuations.popitem(last=False)

    def _continuation_at(
        self,
        version_id: uuid.UUID,
        era: int,
        value: TrafficInput,
        episode: int,
        sealed: list[dict[str, Any]],
        feeds: Any,
        initial_cursors: Mapping[str, Any],
    ) -> dict[str, Any]:
        """The continuation a coupled episode's next minute starts from: kept by this process,
        else computed again from the episode's genesis and checked against every sealed digest."""
        segment = len(sealed)
        with self._cache_lock:
            kept = self._continuations.get((version_id, era, episode, segment))
        if kept is not None and kept["document_sha256"] == sealed[-1]["continuation_sha256"]:
            return kept
        self._check_feeds(sealed, feeds)
        answer = self._worker(
            compute_coupled_segments,
            wire(value),
            episode,
            sealed,
            feeds_wire(feeds),
            initial_cursors,
            segment - 1,
        )
        self._remember((version_id, era, episode, segment), answer["continuation"])
        return answer["continuation"]

    @staticmethod
    def _check_feeds(sealed: list[dict[str, Any]], feeds: Any) -> None:
        """Each sealed minute bound the feeds it consumed: minute ``j`` consumed feeds 1 to
        ``j + 1``, projected again here from the stored occupancy."""
        for minute in sealed:
            if feed_projection_sha256(feeds[: minute["segment"] + 1]) != minute["feed_sha256"]:
                raise ClockRefused(
                    "crossing_occupancy_mismatch",
                    f"minute {minute['world_tick']} consumed feeds the occupancy no longer makes",
                )

    def replay_coupled_window(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        from_second: int,
        seconds: int,
    ) -> dict[str, Any]:
        """A coupled world's window, read only from sealed minutes, each rebuilt in the pure
        worker and held to what was sealed; a second not yet sealed is refused."""
        with self.database.session(workspace_id) as connection:
            clocks = WorldClockRepository(connection, workspace_id, world_id)
            clock = clocks.row(version_id)
            if clock is None or clock["roads_version"] is None:
                raise ClockRefused("traffic_not_coupled", "this version's traffic is not coupled")
            era = era_of(clock)
            sealed_end = era.traffic_second(
                era.world_second_of_tick(clock["traffic_sealed_through_tick"])
            )
            if from_second < era.timeline_origin_second:
                raise ClockRefused("traffic_second_out_of_range", "a second before the era")
            if from_second + seconds > sealed_end:
                raise ClockRefused(
                    "traffic_not_yet_sealed", f"traffic is sealed up to second {sealed_end}"
                )
            wanted: dict[int, list[int]] = {}
            for first in range((from_second // 60) * 60, from_second + seconds, 60):
                episode, local = divmod(first, EPISODE)
                wanted.setdefault(episode, []).append(local // 60)
            reads = {}
            for episode, segments in wanted.items():
                last = max(segments)
                through = era.world_second(episode * EPISODE + 60 * (last + 1)) // 60 + 1
                documents, sealed, initial = self._episode_facts(
                    clocks, clock, episode, last + 1, through_tick=through
                )
                reads[episode] = (min(segments), last, documents, sealed, initial)
        packed = {}
        facts = []
        for episode, (first, last, documents, sealed, initial) in reads.items():
            feeds = crossing_feeds(
                occupancy_intervals(documents),
                era=era,
                episode_first_second=episode * EPISODE,
                covers_through_local_second=60 * (last + 1) + 59,
                bands=self.bands(value),
            )
            self._check_feeds(sealed, feeds)
            answer = self._worker(
                compute_coupled_segments,
                wire(value),
                episode,
                sealed,
                feeds_wire(feeds),
                initial,
                first,
            )
            for segment, section in answer["packed"].items():
                packed[(episode, segment)] = section
            for minute in sealed[first : last + 1]:
                facts.append(
                    {
                        key: minute[key]
                        for key in (
                            "profile",
                            "era",
                            "world_tick",
                            "start_second",
                            "occupancy_through_tick",
                            "feed_sha256",
                            "decisions_sha256",
                            "frames_sha256",
                            "continuation_sha256",
                            "choice_seq",
                            "active_second",
                            "document_sha256",
                        )
                    }
                )
        return {
            **window_of_segments(value, packed, from_second, seconds, coupled=True),
            "sealed_minutes": facts,
        }

    def verify_coupled_minutes(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        first_tick: int,
        last_tick: int,
    ) -> dict[str, Any]:
        """Rebuild sealed coupled minutes ``first_tick`` to ``last_tick`` from each episode's
        genesis, whatever the worker keeps, and hold every feed, frame and continuation digest to
        what was sealed. The worker holds no model client, so nothing is asked."""
        with self.database.session(workspace_id) as connection:
            clocks = WorldClockRepository(connection, workspace_id, world_id)
            clock = clocks.row(version_id)
            if clock is None or clock["roads_version"] is None:
                raise ClockRefused("traffic_not_coupled", "this version's traffic is not coupled")
            era = era_of(clock)
            if not (
                clock["era_start_tick"] < first_tick <= last_tick
                and last_tick <= clock["traffic_sealed_through_tick"]
            ):
                raise ClockRefused(
                    "traffic_not_yet_sealed",
                    f"traffic minutes are sealed from {clock['era_start_tick'] + 1} "
                    f"to {clock['traffic_sealed_through_tick']}",
                )
            wanted: dict[int, list[int]] = {}
            for tick in range(first_tick, last_tick + 1):
                episode, local = divmod(
                    era.traffic_second(era.world_second_of_tick(tick - 1)), EPISODE
                )
                wanted.setdefault(episode, []).append(local // 60)
            reads = {}
            for episode, segments in wanted.items():
                last = max(segments)
                through = era.world_second(episode * EPISODE + 60 * (last + 1)) // 60 + 1
                reads[episode] = (
                    min(segments),
                    last,
                    *self._episode_facts(clocks, clock, episode, last + 1, through_tick=through),
                )
        rebuilt = 0
        for episode, (first, last, documents, sealed, initial) in reads.items():
            feeds = crossing_feeds(
                occupancy_intervals(documents),
                era=era,
                episode_first_second=episode * EPISODE,
                covers_through_local_second=60 * (last + 1) + 59,
                bands=self.bands(value),
            )
            self._check_feeds(sealed, feeds)
            answer = self._worker(
                compute_coupled_segments,
                wire(value),
                episode,
                sealed,
                feeds_wire(feeds),
                initial,
                first,
                True,
            )
            rebuilt += last + 1
            if sorted(answer["packed"]) != list(range(first, last + 1)):
                raise ClockRefused("traffic_replay_mismatch", "a verified minute was not rebuilt")
        return {
            "minutes_checked": last_tick - first_tick + 1,
            "episodes_rebuilt": len(reads),
            "minutes_rebuilt": rebuilt,
        }

    def _answer_point(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        episode: int,
        segment: int,
        point: Mapping[str, Any],
        *,
        coupled: bool = False,
    ) -> str:
        """The action at a choice point: a recorded answer, a fresh ask, or fixed timing.

        A legacy world's point already passed by the wall clock is too late to ask. A coupled
        world's minute is shown only once sealed, so its point is never late that way; the ask's
        own deadline and the world's hourly caps still bound it.
        """
        absolute = episode * EPISODE + point["choice_second"]
        with self.database.session(workspace_id) as connection:
            repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            choice = repository.choices_at(absolute).get(point["signal_id"])
            if choice is None or choice["model"] is None:
                return "switch"
            prior = repository.point_receipt(
                episode, point["signal_id"], absolute, choice["choice_seq"]
            )
            if prior is not None and prior["decision"] is not None:
                return self._action(prior["decision"])
            if not coupled and absolute <= self.clock():
                if prior is not None:
                    repository.record_result(
                        self.role, prior["request_id"], _fallback("point_stale")
                    )
                return "switch"
            try:
                spec = self.manifest.offered(self.role.chosen, choice["model"]["model_id"])
            except ManifestError:
                return "switch"
            mechanism = self.role.contract().mechanism_for(spec)
            if mechanism is None or spec.provider != choice["model"]["provider"]:
                return "switch"
            contract = self.role.contract()
            bound = (
                ask_bound_usd(self.role, self.client.budget, spec, contract)
                if self.client is not None
                else Decimal(0)
            )
            reserved = repository.reserve_point(
                self.role,
                roads_version=value.version_id,
                episode=episode,
                segment=segment,
                choice=choice,
                choice_second=absolute,
                state_sha256=point["state_sha256"],
                observation=point["observation"],
                manifest_sha256=self.manifest_sha256,
                mechanism=mechanism.value,
                budget_bound_usd=bound,
            )
            if reserved is None:
                return "switch"
        request = reserved["request"]
        deadline = reserved["deadline_at"]
        request_id = uuid.UUID(request["request_id"])
        if deadline <= datetime.now(UTC):
            with self.database.session(workspace_id) as connection:
                TrafficSignalRepository(
                    connection, workspace_id, world_id, version_id
                ).record_result(self.role, request_id, _fallback("no_time_to_ask"))
            return "switch"
        reason = reserved["budget_refusal"] or host_refusal(
            self.role, self.client, self.manifest, contract
        )
        if reason is None:
            reason = model_refusal(self.role, self.client, self.manifest, contract, choice["model"])
        if reason is not None or self.client is None:
            result = _fallback(reason or "provider_credential_absent")
        else:
            asking = self.client.with_policy(self.policy_for(workspace_id))
            if question_refusal(self.role, asking, spec.model_id) is not None:
                result = _fallback("request_refused")
            else:
                keep_usd, keep_calls = share_kept(self.client.budget, contract)
                ends_at = time.monotonic() + max(0, (deadline - datetime.now(UTC)).total_seconds())
                result = ask(
                    asking,
                    RoleAsk(self.role, request, spec, mechanism),
                    contract,
                    ends_at,
                    keep_usd=keep_usd,
                    keep_calls=keep_calls,
                )
        with self.database.session(workspace_id) as connection:
            repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            try:
                receipt = repository.record_result(self.role, request_id, result)
            except SignalChoiceRefused as exc:
                if exc.code in {"answer_after_deadline", "choice_generation_changed"}:
                    receipt = repository.record_result(
                        self.role, request_id, _fallback("point_stale", result["provider"])
                    )
                else:
                    held = repository.decision_for(request_id)
                    if held is None:
                        return "switch"
                    receipt = held
        return self._action(receipt)

    @staticmethod
    def _action(receipt: Mapping[str, Any]) -> str:
        if receipt["status"] != "accepted":
            return "switch"
        return receipt["proposal"]["option"]["kind"]

    def replay_window(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        from_second: int,
        seconds: int,
    ) -> dict[str, Any]:
        """Read only sealed frames; worker replay verifies both state and display digests."""
        first = from_second // 60
        last = (from_second + seconds - 1) // 60
        packed = {}
        segment_facts = []
        for minute in range(first, last + 1):
            episode, local = divmod(minute * 60, EPISODE)
            segment = local // 60
            with self.database.session(workspace_id) as connection:
                repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
                sealed = repository.segment(episode, segment)
                previous = repository.segment(episode, segment - 1) if segment else None
            if sealed is None or sealed["input_sha256"] != value.sha256:
                raise SignalChoiceRefused("segment_not_sealed")
            choices = {
                signal: {int(second): action for second, action in row.items()}
                for signal, row in sealed["continuation"]["signal_choices"].items()
            }
            for signal in sealed["continuation"]["signal_cursors"]:
                choices.setdefault(signal, {})
            initial_cursors = sealed["continuation"]["initial_signal_cursors"]
            section, following, frames_sha = self._worker(
                compute_signal_replay,
                wire(value),
                episode,
                segment,
                None if previous is None else previous["continuation"],
                choices,
                initial_cursors,
            )
            if following["document_sha256"] != sealed["continuation_sha256"]:
                raise SignalChoiceRefused("segment_continuation_changed")
            if frames_sha != sealed["frames_sha256"]:
                raise SignalChoiceRefused("segment_frames_changed")
            packed[(episode, segment)] = section
            segment_facts.append(
                {
                    "profile": "exulanica.traffic-sealed-segment/v1",
                    "world_id": world_id,
                    "version_id": str(version_id),
                    "roads_version": sealed["roads_version"],
                    "start_second": sealed["start_second"],
                    "end_second": sealed["end_second"],
                    "choice_seq": sealed["choice_seq"],
                    "active_second": sealed["active_second"],
                    "decisions_sha256": sealed["decisions_sha256"],
                    "frames_sha256": sealed["frames_sha256"],
                    "continuation_sha256": sealed["continuation_sha256"],
                }
            )
        return {
            **window_of_segments(value, packed, from_second, seconds),
            "sealed_segments": segment_facts,
        }

    def signals(self, value: TrafficInput) -> list[dict[str, str]]:
        """Compiled signal identities from the pure worker, without a model call."""
        return self._worker(compute_signal_catalog, wire(value))
