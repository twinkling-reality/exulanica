"""Prepare and seal a saved world's traffic minutes before any viewer asks for them.

One controller thread rotates the worlds with recorded signal choices. At most the catalog's
pending bound of world preparations run together; one spawned traffic process computes pure
segments and is released between choice points. The API process alone reserves, asks through the
shared model client and budget, records, and seals. A viewer may replay sealed minutes through the
same pure process, but it never reaches the ask path.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
import uuid
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
from exulanica.traffic.signal_actuation import signal_actuation
from exulanica.world.decision_roles import DecisionRole, decision_roles
from exulanica.world.episode_worker import worker_pool
from exulanica.world.traffic_episodes import (
    EPISODE,
    TrafficInput,
    compute_signal_catalog,
    compute_signal_probe,
    compute_signal_replay,
    window_of_segments,
    wire,
)
from exulanica.world.traffic_host import saved_world_roads
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository

__all__ = ["TrafficSignalController"]

_LOG = logging.getLogger(__name__)
_PROBE_SECONDS = 30.0
_SEGMENTS_PER_TURN = EPISODE // 60
# Cover the entire effective minute: selection is at least one minute ahead and rounds upward.
_PREPARED_MINUTES_AHEAD = 2


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
        for process in processes:
            try:
                if process.is_alive():
                    process.terminate()
            except (AssertionError, OSError):
                pass
        pool.shutdown(wait=False, cancel_futures=True)
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
                    "select distinct world_id,version_id from world_traffic_signal_choice "
                    "where workspace_id=%s order by world_id,version_id",
                    (workspace_id,),
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
        """Prepare one episode's minutes, including fixed prefixes before activation."""
        if self._stop.is_set():
            return 0
        with self.database.session(workspace_id) as connection:
            repository = TrafficSignalRepository(connection, workspace_id, world_id, version_id)
            row = connection.execute(
                "select source_snapshot_id from world_alternate_version where workspace_id=%s "
                "and world_id=%s and version_id=%s",
                (workspace_id, world_id, version_id),
            ).fetchone()
            if row is None:
                return 0
            value = saved_world_roads(connection, workspace_id, world_id, row["source_snapshot_id"])
            latest = repository.latest_any_segment()
            earliest = min(choice["effective_second"] for choice in repository._choices())
        current_episode = int(self.clock()) // EPISODE
        if latest is None:
            episode = min(current_episode, earliest // EPISODE)
            segment = 0
        else:
            episode, segment = latest["episode"], latest["segment"] + 1
            if segment == EPISODE // signal_actuation().segment_seconds:
                episode, segment = episode + 1, 0
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

    def _answer_point(
        self,
        workspace_id: uuid.UUID,
        world_id: str,
        version_id: uuid.UUID,
        value: TrafficInput,
        episode: int,
        segment: int,
        point: Mapping[str, Any],
    ) -> str:
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
            if absolute <= self.clock():
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
