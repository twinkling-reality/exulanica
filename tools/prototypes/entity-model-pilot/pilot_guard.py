"""Offline-tested private pilot guard. No CLI, service construction or live authorization.

A later clone adapter must supply truthful target/read records from actual resources. These
validators prove relationships between supplied records; they cannot prove a clone exists.
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import math
import threading
import time
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from exulanica.models.usage import CallUsage, CostBasis


class PilotStop(BaseException):
    """Escape the production worker's Exception-to-routine fallback without another tick."""

    def __init__(self: Any, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class Identity:
    workspace_id: uuid.UUID
    world_id: str
    version_id: uuid.UUID
    society_id: uuid.UUID
    subject_id: str
    provider: str
    model_id: str
    source_sha256: str
    modules_sha256: str
    choice_seq: int


@dataclass(frozen=True)
class RequestRow:
    request_id: uuid.UUID
    subject_id: str
    status: str | None  # None means pending; terminal means a durable decision exists.
    provider: str
    model_id: str
    consumed: bool = False
    applied: bool = False


@dataclass(frozen=True)
class Snapshot:
    identity: Identity
    tick: int
    state_sha256: str
    requests: tuple[RequestRow, ...]
    # All model/external/player assignments, across all hosted roles, encoded by subject.
    eligible_subjects: tuple[str, ...]
    playing_versions: tuple[uuid.UUID, ...]
    pending_background_jobs: int = 0
    refusal: str | None = None


@dataclass(frozen=True)
class TargetBinding:
    """Externally collected clone records and actual configured values, not an approval flag."""

    run_root: Path
    recorded_data: Path
    configured_data: Path
    recorded_store: Path
    configured_store: Path
    primary_paths: tuple[Path, ...]
    database_url: str
    api_url: str
    app_url: str
    source_inputs_sha256: str
    schema_version: int
    spending_mode: str
    authority_id: uuid.UUID
    workspace_allowance_usd: Decimal
    workspace_allowance_calls: int
    witness_path: Path
    recorded_witness_path: Path

    def validate(self: Any) -> dict:
        root = self.run_root.resolve()
        if not self.primary_paths:
            raise PilotStop("primary_paths_missing")
        paths = tuple(p.resolve() for p in (self.configured_data, self.configured_store))
        if paths != (self.recorded_data.resolve(), self.recorded_store.resolve()):
            raise PilotStop("configured_target_differs")
        for candidate in (root, *paths, self.witness_path.resolve()):
            for primary in self.primary_paths:
                actual = primary.resolve()
                if (
                    candidate == actual
                    or candidate.is_relative_to(actual)
                    or actual.is_relative_to(candidate)
                ):
                    raise PilotStop("primary_path_overlap")
        if any(p == root or not p.is_relative_to(root) for p in paths):
            raise PilotStop("clone_path_outside_run")
        witness = self.witness_path.resolve()
        if witness != self.recorded_witness_path.resolve():
            raise PilotStop("witness_target_differs")
        if any(
            witness == p or witness.is_relative_to(p) or p.is_relative_to(witness) for p in paths
        ):
            raise PilotStop("witness_in_backup_domain")
        for url, port, schemes in (
            (self.database_url, 20030, {"postgres", "postgresql"}),
            (self.api_url, 20031, {"http"}),
            (self.app_url, 20032, {"http"}),
        ):
            try:
                parsed = urlsplit(url)
                safe = (
                    parsed.hostname in {"localhost", "127.0.0.1", "::1"}
                    and parsed.port == port
                    and parsed.scheme in schemes
                )
            except ValueError:
                safe = False
            if not safe:
                raise PilotStop("target_endpoint_not_isolated")
        if (
            self.schema_version != 212
            or len(self.source_inputs_sha256) != 64
            or any(c not in "0123456789abcdef" for c in self.source_inputs_sha256)
        ):
            raise PilotStop("source_preflight_missing")
        if (
            self.spending_mode != "durable"
            or self.workspace_allowance_usd != Decimal("0.25")
            or self.workspace_allowance_calls != 100
        ):
            raise PilotStop("durable_allowance_not_bound")
        if not isinstance(self.authority_id, uuid.UUID):
            raise PilotStop("authority_identity_missing")
        # Do not log URL credentials or paths from a primary environment.
        return {
            "source_inputs_sha256": self.source_inputs_sha256,
            "schema_version": self.schema_version,
            "spending_mode": self.spending_mode,
            "authority_id": str(self.authority_id),
            "target_descriptor_sha256": hashlib.sha256(
                json.dumps(
                    {
                        "root": str(root),
                        "data": str(paths[0]),
                        "store": str(paths[1]),
                        "witness": str(witness),
                    },
                    sort_keys=True,
                ).encode()
            ).hexdigest(),
        }


class AttemptAudit:
    """Observe the existing client's ledger after recording; never throw from this callback."""

    def __init__(self: Any, identity: Identity, budget: Any, sink: Callable[[dict], None]) -> None:
        self.identity, self.budget, self.sink = identity, budget, sink
        self.rows: list[dict] = []
        self.failure: str | None = None
        self._lock = threading.Lock()
        self.start_calls = len(budget.ledger.calls)
        if budget.ceiling_usd != Decimal("0.25") or budget.max_calls != 100:
            raise PilotStop("process_fuse_differs")
        if self.start_calls or budget.held_calls or budget.spent_usd:
            raise PilotStop("process_fuse_not_fresh")

    def observe(self: Any, usage: CallUsage) -> None:
        try:
            row = {
                **usage.as_cost_json(),
                "provider": usage.provider,
                "used_fallback": usage.used_fallback,
                "latency_s": usage.latency_s,
            }
            with self._lock:
                self.rows.append(row)
                if (
                    usage.provider != self.identity.provider
                    or usage.model_id != self.identity.model_id
                    or usage.used_fallback
                ):
                    self.failure = "unexpected_provider_attempt"
                elif usage.cost_basis == CostBasis.UNKNOWN:
                    self.failure = "unknown_provider_liability"
                self.sink({"kind": "attempt", **row})
        except BaseException:
            with self._lock:
                self.failure = "attempt_receipt_failed"

    def check(self: Any, *, allow_cap: bool = False) -> dict:
        with self._lock:
            if self.failure:
                raise PilotStop(self.failure)
            if len(self.budget.ledger.calls) - self.start_calls != len(self.rows):
                raise PilotStop("unobserved_provider_attempt")
            if self.budget.held_calls or self.budget.held_usd:
                raise PilotStop("unsettled_provider_liability")
            if not allow_cap and (
                self.budget.billed_calls >= 100 or self.budget.spent_usd >= Decimal("0.25")
            ):
                raise PilotStop("admission_cap_reached")
            return {
                "attempts": len(self.rows),
                "billed_calls": self.budget.billed_calls,
                "spent_usd": str(self.budget.spent_usd),
                "held_calls": self.budget.held_calls,
                "held_usd": str(self.budget.held_usd),
                "ledger": self.budget.ledger.as_cost_json(),
            }

    def bind(self: Any, client: Any) -> Any:
        if client.budget is not self.budget:
            raise PilotStop("client_guard_differs")
        observed = client.with_attempts(self.observe)
        if observed.budget is not self.budget:
            raise PilotStop("observer_replaced_guard")
        return observed


class PilotGuard:
    def __init__(
        self: Any,
        *,
        identity: Identity,
        binding: TargetBinding,
        read: Callable[[], Snapshot],
        audit: AttemptAudit,
        sink: Callable[[dict], None],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.identity, self.read, self.audit, self.sink, self.monotonic = (
            identity,
            read,
            audit,
            sink,
            monotonic,
        )
        self.binding = binding
        self.started: float | None = None
        self.deadline: float | None = None
        self.baseline: frozenset[uuid.UUID] | None = None
        self.seen: dict[uuid.UUID, RequestRow] = {}
        self.last_tick: int | None = None
        self.stopped = False
        self.dispatch_failure: str | None = None
        self.last_time: float | None = None
        self._lock = threading.Lock()

    def emit(self: Any, row: dict) -> None:
        try:
            self.sink(row)
        except BaseException:
            raise PilotStop("guard_receipt_failed") from None

    def _time(self: Any) -> float:
        now = self.monotonic()
        if not math.isfinite(now):
            raise PilotStop("invalid_monotonic_clock")
        if self.last_time is not None and now < self.last_time:
            raise PilotStop("monotonic_clock_reversed")
        self.last_time = now
        return now

    def _snapshot(self: Any) -> Snapshot:
        try:
            snapshot = self.read()
        except BaseException as exc:
            if isinstance(exc, PilotStop):
                raise
            raise PilotStop("state_read_failed") from None
        if snapshot.identity != self.identity:
            raise PilotStop("source_or_choice_identity_changed")
        if snapshot.eligible_subjects != (self.identity.subject_id,):
            raise PilotStop("unexpected_decider")
        if snapshot.playing_versions != (self.identity.version_id,):
            raise PilotStop("unexpected_playback_scope")
        if snapshot.pending_background_jobs != 0:
            raise PilotStop("background_jobs_present")
        if snapshot.refusal is not None:
            raise PilotStop("model_or_source_refused")
        if type(snapshot.tick) is not int or snapshot.tick < 0:
            raise PilotStop("invalid_tick")
        if self.last_tick is not None and not self.last_tick <= snapshot.tick <= self.last_tick + 1:
            raise PilotStop("unexpected_tick_advance")
        if len(snapshot.state_sha256) != 64 or any(
            c not in "0123456789abcdef" for c in snapshot.state_sha256
        ):
            raise PilotStop("invalid_state_digest")
        if len({r.request_id for r in snapshot.requests}) != len(snapshot.requests):
            raise PilotStop("duplicate_request_identity")
        return snapshot

    def start(self: Any) -> None:
        if self.started is not None or self.stopped:
            raise PilotStop("pilot_cannot_restart")
        pins = self.binding.validate()
        snapshot = self._snapshot()
        if any(r.status is None for r in snapshot.requests):
            raise PilotStop("pending_request_at_start")
        self.audit.check()
        self.started = self._time()
        self.deadline = self.started + 600.0
        self.baseline = frozenset(r.request_id for r in snapshot.requests)
        self.last_tick = snapshot.tick
        self.emit(
            {
                "kind": "started",
                **pins,
                "tick": snapshot.tick,
                "state_sha256": snapshot.state_sha256,
                "baseline_requests": sorted(str(r) for r in self.baseline),
            }
        )

    def check(self: Any, *, claim: Any=None, before_new_ask: bool = True) -> Snapshot:
        if self.stopped or self.baseline is None or self.deadline is None:
            raise PilotStop("pilot_not_active")
        if self._time() >= self.deadline:
            raise PilotStop("wall_deadline")
        if claim is not None and (
            claim.workspace_id,
            claim.world_id,
            claim.version_id,
            claim.society_id,
        ) != (
            self.identity.workspace_id,
            self.identity.world_id,
            self.identity.version_id,
            self.identity.society_id,
        ):
            raise PilotStop("unexpected_claim")
        snapshot = self._snapshot()
        if self._time() >= self.deadline:
            raise PilotStop("wall_deadline")
        if self.dispatch_failure:
            raise PilotStop(self.dispatch_failure)
        current = {r.request_id: r for r in snapshot.requests if r.request_id not in self.baseline}
        if (
            not self.baseline.issubset({r.request_id for r in snapshot.requests})
            or not self.seen.keys() <= current.keys()
        ):
            raise PilotStop("request_history_disappeared")
        for key, row in current.items():
            if (
                row.subject_id != self.identity.subject_id
                or row.provider != self.identity.provider
                or row.model_id != self.identity.model_id
            ):
                raise PilotStop("unexpected_request")
            if row.status not in {None, "accepted", "rejected", "unavailable", "stale"}:
                raise PilotStop("unknown_decision_status")
            old = self.seen.get(key)
            if (
                old is not None
                and old.status is not None
                and (
                    old.status != row.status
                    or old.provider != row.provider
                    or old.model_id != row.model_id
                )
            ):
                raise PilotStop("decision_rewritten")
        self.seen = current
        finalized = sum(r.status is not None for r in current.values())
        if finalized > 10 or len(current) > 10:
            raise PilotStop("decision_limit_exceeded")
        if before_new_ask and finalized >= 10:
            raise PilotStop("decision_limit_reached")
        if before_new_ask and any(r.status is None for r in current.values()):
            raise PilotStop("unanswered_request")
        self.audit.check(allow_cap=not before_new_ask)
        self.last_tick = snapshot.tick
        return snapshot

    def summary(self: Any) -> dict:
        return {
            "requests": len(self.seen),
            "finalized": sum(r.status is not None for r in self.seen.values()),
            "accepted": sum(r.status == "accepted" for r in self.seen.values()),
            "consumed": sum(r.consumed for r in self.seen.values()),
            "applied": sum(r.applied for r in self.seen.values()),
            "attempts": len(self.audit.rows),
        }


@contextmanager
def install_worker_guards(worker: Any, guard: PilotGuard) -> Any:
    """Wrap actual claim/tell/callback/execute seams without changing production worker code."""
    names = ("_tell_of_erased_kinds", "_before_minute", "_repository")
    originals = {name: getattr(worker, name) for name in names}
    instance_values = {name: (name in vars(worker), vars(worker).get(name)) for name in names}
    if originals["_before_minute"] is None:
        raise PilotStop("decision_host_absent")

    def tell(workspace: Any, claim: Any) -> Any:
        guard.check(claim=claim)
        value = originals["_tell_of_erased_kinds"](workspace, claim)
        guard.check(claim=claim)
        if value != "clear":
            raise PilotStop("erasure_not_clear")
        return value

    def before(claim: Any, lease_ends: Any) -> Any:
        guard.check(claim=claim)
        try:
            originals["_before_minute"](claim, min(lease_ends, guard.deadline))
        except Exception:
            raise PilotStop("decision_host_failed") from None
        guard.check(claim=claim, before_new_ask=False)
        return True

    class Execution:
        def __init__(self: Any, repository: Any) -> None:
            self.repository = repository

        def execute(self: Any, claim: Any, *, max_ticks: Any=None, untold: Any=False) -> Any:
            guard.check(claim=claim, before_new_ask=False)
            if untold:
                raise PilotStop("erasure_not_clear")
            result = self.repository.execute(claim, max_ticks=1, untold=False)
            guard.check(claim=claim, before_new_ask=False)
            return result

    def repository(*args: Any, **kwargs: Any) -> Any:
        return Execution(originals["_repository"](*args, **kwargs))

    worker._tell_of_erased_kinds, worker._before_minute, worker._repository = (
        tell,
        before,
        repository,
    )
    try:
        yield
    finally:
        for name, (present, value) in instance_values.items():
            if present:
                setattr(worker, name, value)
            else:
                delattr(worker, name)


def pause_with_fresh_revision(
    repository: Any, identity: Identity, actor: uuid.UUID, *, retries: int = 3
) -> dict:
    """Request a transaction-local pause; caller must commit and verify in a fresh session.

    This result deliberately cannot satisfy run_guarded cleanup confirmation.
    """
    from exulanica.world.society import StaleSocietyState

    if repository.workspace_id != identity.workspace_id or repository.world_id != identity.world_id:
        raise PilotStop("pause_scope_differs")
    for attempt in range(retries):
        prior = repository.read(identity.version_id)
        if prior["society_id"] != str(identity.society_id):
            raise PilotStop("pause_society_differs")
        try:
            repository.configure(
                identity.version_id,
                actor=actor,
                base_revision=prior["revision"],
                mode="paused",
                speed=1,
            )
        except StaleSocietyState:
            if attempt + 1 == retries:
                raise
            continue
        after = repository.read(identity.version_id)
        if (
            after["society_id"] != str(identity.society_id)
            or after["mode"] != "paused"
            or after["lease_expires_at"] is not None
        ):
            raise PilotStop("pause_not_verified")
        return {"requested_mode": "paused", "revision": after["revision"], "commit_verified": False}
    raise PilotStop("pause_not_attempted")


def run_guarded(
    worker: Any,
    guard: PilotGuard,
    *,
    pause: Callable[[], dict],
    revoke: Callable[[], dict],
    close: Callable[[], None],
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Serial private pump; cleanup attempts every independent fence even if another fails."""
    result = {"reason": "not_started", "cleanup": {}, "failures": []}
    if not guard._lock.acquire(blocking=False):
        raise PilotStop("concurrent_pilot")
    cleanup_bound = False
    try:
        if guard.started is not None or guard.stopped:
            raise PilotStop("pilot_cannot_restart")
        guard.binding.validate()
        if getattr(getattr(worker, "database", None), "url", None) != guard.binding.database_url:
            raise PilotStop("worker_target_differs")
        cleanup_bound = True
        guard.start()
        with install_worker_guards(worker, guard):
            while True:
                guard.check()
                answer = worker.run_once(guard.identity.workspace_id)
                guard.check(before_new_ask=False)
                guard.emit(
                    {
                        "kind": "pump",
                        **guard.summary(),
                        "accounting": guard.audit.check(allow_cap=True),
                    }
                )
                guard.check()  # tenth result may be consumed, but an eleventh round cannot start.
                if answer is None:
                    sleep(min(0.1, max(0, guard.deadline - guard._time())))
    except PilotStop as exc:
        result["reason"] = exc.reason
    except BaseException as exc:
        result["reason"] = (
            "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "driver_failed"
        )
        result["failures"].append({"phase": "run", "type": type(exc).__name__})
    finally:
        guard.stopped = True
        for name, operation in (("pause", pause), ("revoke", revoke), ("close", close)):
            if not cleanup_bound:
                result["cleanup"][name] = "skipped_unverified_target"
                continue
            try:
                response = operation()
                if name == "pause" and (
                    not isinstance(response, dict)
                    or response.get("mode") != "paused"
                    or response.get("lease_expires_at", "missing") is not None
                ):
                    raise ValueError("pause_not_confirmed")
                if name == "revoke" and (
                    not isinstance(response, dict)
                    or response.get("revoked") is not True
                    or response.get("authority_id") != str(guard.binding.authority_id)
                    or response.get("workspace_id") != str(guard.identity.workspace_id)
                ):
                    raise ValueError("revocation_not_confirmed")
                result["cleanup"][name] = "confirmed"
            except BaseException as exc:
                result["cleanup"][name] = "failed"
                result["failures"].append({"phase": name, "type": type(exc).__name__})
        result.update(guard.summary())
        result["counts_scope"] = "last_observed_not_final_readback"
        result["final_readback_required"] = True
        result["liability_reconciliation_required"] = bool(
            guard.audit.failure or guard.audit.budget.held_calls or guard.audit.budget.held_usd
        )
        result["safe_stopped"] = not result["failures"] and all(
            v == "confirmed" for v in result["cleanup"].values()
        )
        try:
            guard.emit({"kind": "stopped", **result})
        except BaseException:
            result["safe_stopped"] = False
            result["failures"].append({"phase": "receipt", "type": "ReceiptFailure"})
        guard._lock.release()
    return result


class DispatchFence:
    """Local pre-dispatch fence, including repair attempts; never inspect held reservations."""

    def __init__(self: Any, transport: Any, guard: PilotGuard, *, url: str) -> None:
        self.transport, self.guard, self.url = transport, guard, url

    def post_json(self: Any, url: Any, *, headers: Any, payload: Any, timeout: Any) -> Any:
        from exulanica.models.errors import TransportError

        guard = self.guard
        reason = None
        try:
            now = guard._time()
            if guard.stopped or guard.deadline is None or guard.baseline is None:
                reason = "pilot_not_active"
            elif now >= guard.deadline:
                reason = "dispatch_deadline"
            elif guard.dispatch_failure or guard.audit.failure:
                reason = guard.dispatch_failure or guard.audit.failure
            elif url != self.url or payload.get("model") != guard.identity.model_id:
                reason = "unexpected_dispatch"
            elif not math.isfinite(timeout) or timeout <= 0:
                reason = "invalid_dispatch_timeout"
        except PilotStop as exc:
            reason = exc.reason
        if reason:
            guard.dispatch_failure = reason
            raise TransportError(reason, retryable=False, reached_provider=False)
        return self.transport.post_json(
            url, headers=headers, payload=payload, timeout=min(timeout, guard.deadline - now)
        )

    def get_json(self: Any, *args: Any, **kwargs: Any) -> Any:
        from exulanica.models.errors import TransportError

        self.guard.dispatch_failure = "unexpected_readiness_dispatch"
        raise TransportError(
            "unexpected_readiness_dispatch", retryable=False, reached_provider=False
        )


def guarded_client(client: Any, guard: PilotGuard) -> Any:
    """Copy existing client/chain, preserving budget and durable spending gate."""
    observed = guard.audit.bind(client)
    observed._chain = copy.copy(observed._chain)
    url = client.manifest.provider(guard.identity.provider).base_url + "/chat/completions"
    observed._chain._transport = DispatchFence(observed._chain._transport, guard, url=url)
    return observed


def observed_worker(services: Any, guard: PilotGuard) -> Any:
    """Adapter for existing Services, callable only by a separately reviewed clone launcher."""
    if (
        services.spending_mode != "durable"
        or services.spending is None
        or services.playback_player != "none"
        or services.runs_society_control_worker
        or services.society_control_workspaces != (guard.identity.workspace_id,)
    ):
        raise PilotStop("services_scope_differs")
    guard.binding.validate()
    if services.model_client is None:
        raise PilotStop("model_client_absent")
    readonly = urlsplit(services.readonly_database.url)
    writable = urlsplit(guard.binding.database_url)
    if (readonly.scheme, readonly.hostname, readonly.port, readonly.path, readonly.query) != (
        writable.scheme,
        writable.hostname,
        writable.port,
        writable.path,
        writable.query,
    ):
        raise PilotStop("readonly_target_differs")
    if (
        services.database.url != guard.binding.database_url
        or services.spending.database.url != guard.binding.database_url
        or Path(services.store.root).resolve() != guard.binding.configured_store.resolve()
        or Path(services.spending.witness.directory).resolve()
        != guard.binding.witness_path.resolve()
    ):
        raise PilotStop("services_target_differs")
    observed = guarded_client(services.model_client, guard)
    wrapped = dataclasses.replace(services, model_client=observed)
    worker = wrapped.build_society_control_worker()
    if worker is None or worker.workers != 1 or worker.workspaces != (guard.identity.workspace_id,):
        raise PilotStop("worker_scope_differs")
    return worker


if __name__ == "__main__":
    raise SystemExit(
        "Offline private library only; no live CLI or clone authorization is provided."
    )
