"""Continuous real-time 20 Hz spatial tick loop and 3-tier hierarchical mind runtime.

Decouples the authoritative spatial tick loop (20 Hz, 50 ms sub-ticks) from asynchronous
deliberative cognition (Tier 2 open models and Door bridges) and durable persistence
(periodic zero-float epoch checkpoints):

1. :class:`RealtimeWorldRoom` maintains deterministic integer-millimeter and integer-microradian
   poses (``x_mm``, ``y_mm``, ``z_mm``, ``yaw_urad``) for up to 256+ concurrent beings (human
   players, external Door visitors, and open-model inhabitants).
2. Area-of-Interest (AOI) spatial hashing partitions the world into integer grid cells so nearby
   queries, swept collision avoidance, and delta-compressed frame emission stay under 2 ms/tick
   at 256 concurrent beings.
3. :class:`HierarchicalMindCoordinator` coordinates three non-blocking tiers:
   - **Tier 0 (20 Hz Reflex & Steering)**: waypoint advancement, collision avoidance, and
     continuous motion every 50 ms tick.
   - **Tier 1 (Reactive Local Policy / Routine Fallback)**: instant deterministic local action
     selection when a being reaches a waypoint or faces an immediate local event while a Tier 2
     deliberation is in flight or unconfigured.
   - **Tier 2 (Async Open-Model / Door Planner)**: dispatches non-blocking requests pinned to
     a ``context_epoch`` and ``context_sha256``. When a proposal arrives across later ticks,
     :class:`ContinuationValidator` checks whether its preconditions still hold at the current
     tick and commits either an ``applied`` receipt or an exact refusal receipt (such as
     ``stale_precondition``) without ever stalling the 20 Hz spatial clock.

Pure: no database connection, no store, no floats in canonical state or digests.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.things.lines import LINE_CHARACTERS_MAXIMUM, LineRefused, check_line, repeats_line
from exulanica.things.manifests import TranslationManifest, check_accounting, read_manifest
from exulanica.world.crossings import ARRIVAL_PROFILE, Crossing, check_arrival
from exulanica.world.deciders import decider as validate_decider

__all__ = [
    "AOI_CELL_MM",
    "COLLISION_RADIUS_MM",
    "CONTINUATION_REASONS",
    "DEFAULT_AOI_RADIUS_MM",
    "DEFAULT_CHECKPOINT_INTERVAL_TICKS",
    "DEFAULT_SPEED_MM_PER_TICK",
    "EPOCH_CHECKPOINT_PROFILE",
    "FULL_CIRCLE_URAD",
    "HEARING_REACH_MM",
    "MAX_CONCURRENT_BEINGS",
    "REALTIME_DECISION_RECEIPT_PROFILE",
    "REALTIME_DECISION_REQUEST_PROFILE",
    "REALTIME_DELTA_FRAME_PROFILE",
    "REALTIME_ROOM_STATE_PROFILE",
    "SUBTICKS_PER_WORLD_MINUTE",
    "TICK_DURATION_MS",
    "TICK_HZ",
    "AOISpatialGrid",
    "AffordancePlace",
    "ContinuationValidator",
    "ContinuationVerdict",
    "EpochCheckpoint",
    "HierarchicalMindCoordinator",
    "OfferedChoice",
    "RealtimeBeing",
    "RealtimeDecisionReceipt",
    "RealtimeDecisionRequest",
    "RealtimeTickResult",
    "RealtimeWorldRoom",
    "Tier2Proposal",
]

TICK_HZ: Final = 20
TICK_DURATION_MS: Final = 50
SUBTICKS_PER_WORLD_MINUTE: Final = 160
MAX_CONCURRENT_BEINGS: Final = 256

AOI_CELL_MM: Final = 16_000
DEFAULT_AOI_RADIUS_MM: Final = 24_000
HEARING_REACH_MM: Final = 8_000
COLLISION_RADIUS_MM: Final = 340
DEFAULT_SPEED_MM_PER_TICK: Final = 70
FULL_CIRCLE_URAD: Final = 6_283_185
DEFAULT_CHECKPOINT_INTERVAL_TICKS: Final = 100

REALTIME_ROOM_STATE_PROFILE: Final = "exulanica.realtime-room-state/v1"
REALTIME_DELTA_FRAME_PROFILE: Final = "exulanica.realtime-delta-frame/v1"
REALTIME_DECISION_REQUEST_PROFILE: Final = "exulanica.realtime-decision-request/v1"
REALTIME_DECISION_RECEIPT_PROFILE: Final = "exulanica.realtime-decision-receipt/v1"
EPOCH_CHECKPOINT_PROFILE: Final = "exulanica.realtime-epoch-checkpoint/v1"

CONTINUATION_REASONS: Final = frozenset(
    {
        "validated_choice",
        "stale_precondition",
        "place_occupied",
        "partner_out_of_reach",
        "partner_busy",
        "target_missing",
        "label_not_offered",
        "line_where_none",
        "no_line_where_one",
        "line_breaks_rule",
        "line_said_before",
        "request_superseded",
        "unknown_request",
    }
)


def _deterministic_int(seed: str, domain: str, key: str, tick: int) -> int:
    digest = hashlib.sha256(f"{seed}:{domain}:{key}:{tick}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _yaw_urad_from_delta(dx_mm: int, dy_mm: int) -> int:
    """Quantize heading from integer millimeter deltas into integer microradians [0, 6_283_185)."""
    if dx_mm == 0 and dy_mm == 0:
        return 0
    rad = math.atan2(dy_mm, dx_mm)
    if rad < 0:
        rad += 2.0 * math.pi
    return int(rad * 1_000_000) % FULL_CIRCLE_URAD


@dataclass(slots=True)
class AffordancePlace:
    """An interactive place or waypoint in the world room."""

    place_id: str
    label: str
    kind: str
    x_mm: int
    y_mm: int
    z_mm: int = 0
    capacity: int = 4
    enabled: bool = True
    occupants: set[str] = field(default_factory=set)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "capacity": self.capacity,
            "enabled": self.enabled,
            "kind": self.kind,
            "label": self.label,
            "occupants": sorted(self.occupants),
            "place_id": self.place_id,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "z_mm": self.z_mm,
        }


@dataclass(frozen=True, slots=True)
class OfferedChoice:
    """One deterministic affordance offered to a Tier 2 mind at a choice point."""

    label: str
    kind: str
    target_id: str | None = None
    target_x_mm: int | None = None
    target_y_mm: int | None = None
    takes_line: bool = False

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "label": self.label,
            "takes_line": self.takes_line,
            "target_id": self.target_id,
            "target_x_mm": self.target_x_mm,
            "target_y_mm": self.target_y_mm,
        }


@dataclass(slots=True)
class RealtimeBeing:
    """One inhabitant, human player, or crossed Door visitor in the 20 Hz spatial room."""

    being_id: str
    u16_id: int
    label: str
    came_by: str
    decider: dict[str, Any]
    x_mm: int
    y_mm: int
    z_mm: int = 0
    yaw_urad: int = 0
    speed_mm_per_tick: int = DEFAULT_SPEED_MM_PER_TICK
    goal_kind: str = "idle"
    goal_target_id: str | None = None
    target_x_mm: int = 0
    target_y_mm: int = 0
    active_tier: int = 0
    motion_state: str = "idle"
    active_request_id: str | None = None
    last_line: str | None = None
    said_lines: list[str] = field(default_factory=list)
    heard_lines: list[str] = field(default_factory=list)
    carried_ids: list[str] = field(default_factory=list)
    arrival_id: str | None = None
    translation_manifest_sha256: str | None = None
    last_Snapshot_pose: tuple[int, int, int, int, str, int, str | None] = field(
        default=(0, 0, 0, 0, "", 0, None), repr=False
    )

    def __post_init__(self) -> None:
        self.decider = validate_decider(self.decider)
        if self.came_by not in ("populated", "placed", "crossed"):
            raise ValueError(f"invalid came_by {self.came_by!r}")
        for name, val in (
            ("x_mm", self.x_mm),
            ("y_mm", self.y_mm),
            ("z_mm", self.z_mm),
            ("yaw_urad", self.yaw_urad),
            ("speed_mm_per_tick", self.speed_mm_per_tick),
        ):
            if type(val) is not int:
                raise TypeError(f"{name} must be an integer, got {type(val).__name__}")

    def pose_tuple(self) -> tuple[int, int, int, int, str, int, str | None]:
        return (
            self.x_mm,
            self.y_mm,
            self.z_mm,
            self.yaw_urad,
            self.motion_state,
            self.active_tier,
            self.goal_target_id,
        )

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "active_request_id": self.active_request_id,
            "active_tier": self.active_tier,
            "arrival_id": self.arrival_id,
            "being_id": self.being_id,
            "came_by": self.came_by,
            "carried_ids": list(self.carried_ids),
            "decider": dict(self.decider),
            "goal_kind": self.goal_kind,
            "goal_target_id": self.goal_target_id,
            "heard_lines": list(self.heard_lines[-8:]),
            "label": self.label,
            "last_line": self.last_line,
            "motion_state": self.motion_state,
            "said_lines": list(self.said_lines[-8:]),
            "speed_mm_per_tick": self.speed_mm_per_tick,
            "target_x_mm": self.target_x_mm,
            "target_y_mm": self.target_y_mm,
            "translation_manifest_sha256": self.translation_manifest_sha256,
            "u16_id": self.u16_id,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "yaw_urad": self.yaw_urad,
            "z_mm": self.z_mm,
        }


class AOISpatialGrid:
    """Integer spatial hash grid for fast Area-of-Interest (AOI) queries and collision checks."""

    __slots__ = ("_beings_by_cell", "_cell_mm", "_coords_by_being")

    def __init__(self, cell_mm: int = AOI_CELL_MM) -> None:
        if type(cell_mm) is not int or cell_mm <= 0:
            raise ValueError("cell_mm must be a positive integer")
        self._cell_mm = cell_mm
        self._beings_by_cell: dict[tuple[int, int], list[RealtimeBeing]] = defaultdict(list)
        self._coords_by_being: dict[str, tuple[int, int]] = {}

    @property
    def cell_mm(self) -> int:
        return self._cell_mm

    def rebuild(self, beings: Iterable[RealtimeBeing]) -> None:
        self._beings_by_cell.clear()
        self._coords_by_being.clear()
        cell_mm = self._cell_mm
        by_cell = self._beings_by_cell
        coords = self._coords_by_being
        for being in beings:
            cell = (being.x_mm // cell_mm, being.y_mm // cell_mm)
            by_cell[cell].append(being)
            coords[being.being_id] = cell

    def cell_of(self, x_mm: int, y_mm: int) -> tuple[int, int]:
        return (x_mm // self._cell_mm, y_mm // self._cell_mm)

    def nearby_beings(
        self,
        x_mm: int,
        y_mm: int,
        radius_mm: int,
        *,
        exclude_id: str | None = None,
    ) -> list[RealtimeBeing]:
        """Return beings within ``radius_mm`` of ``(x_mm, y_mm)``, ordered by ``u16_id``."""
        cell_mm = self._cell_mm
        min_cx = (x_mm - radius_mm) // cell_mm
        max_cx = (x_mm + radius_mm) // cell_mm
        min_cy = (y_mm - radius_mm) // cell_mm
        max_cy = (y_mm + radius_mm) // cell_mm
        r_sq = radius_mm * radius_mm
        by_cell = self._beings_by_cell
        found: list[RealtimeBeing] = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = by_cell.get((cx, cy))
                if not bucket:
                    continue
                for candidate in bucket:
                    if candidate.being_id == exclude_id:
                        continue
                    dx = candidate.x_mm - x_mm
                    dy = candidate.y_mm - y_mm
                    if dx * dx + dy * dy <= r_sq:
                        found.append(candidate)
        found.sort(key=lambda b: b.u16_id)
        return found

    def cells_in_radius(self, x_mm: int, y_mm: int, radius_mm: int) -> list[tuple[int, int]]:
        cell_mm = self._cell_mm
        min_cx = (x_mm - radius_mm) // cell_mm
        max_cx = (x_mm + radius_mm) // cell_mm
        min_cy = (y_mm - radius_mm) // cell_mm
        max_cy = (y_mm + radius_mm) // cell_mm
        return [
            (cx, cy)
            for cx in range(min_cx, max_cx + 1)
            for cy in range(min_cy, max_cy + 1)
            if (cx, cy) in self._beings_by_cell
        ]

    def beings_in_cell(self, cell: tuple[int, int]) -> list[RealtimeBeing]:
        return self._beings_by_cell.get(cell, [])


@dataclass(frozen=True, slots=True)
class RealtimeDecisionRequest:
    """An asynchronous Tier 2 deliberation request pinned to a specific ``context_epoch``."""

    request_id: str
    being_id: str
    base_tick: int
    context_epoch: int
    decider: dict[str, Any]
    offered_choices: tuple[OfferedChoice, ...]
    line_characters_maximum: int
    context: dict[str, Any]
    context_sha256: str
    document_sha256: str

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "base_tick": self.base_tick,
            "being_id": self.being_id,
            "context": self.context,
            "context_epoch": self.context_epoch,
            "context_sha256": self.context_sha256,
            "decider": self.decider,
            "document_sha256": self.document_sha256,
            "line_characters_maximum": self.line_characters_maximum,
            "offered_choices": [c.canonical_dict() for c in self.offered_choices],
            "profile": REALTIME_DECISION_REQUEST_PROFILE,
            "request_id": self.request_id,
        }


@dataclass(frozen=True, slots=True)
class Tier2Proposal:
    """An asynchronous proposal arriving from an open model or external Door bridge."""

    request_id: str
    chosen_label: str
    line: str | None = None
    latency_ms: int = 0
    model_id: str | None = None
    bridge: str | None = None
    grant_id: str | None = None


@dataclass(frozen=True, slots=True)
class ContinuationVerdict:
    """Verdict from the deterministic Continuation Validator at arrival tick ``T + k``."""

    status: str
    disposition: str
    reason: str
    chosen_choice: OfferedChoice | None = None
    checked_line: str | None = None


@dataclass(frozen=True, slots=True)
class RealtimeDecisionReceipt:
    """Sealed receipt binding an async Tier 2 proposal to its request and arrival tick verdict."""

    decision_seq: int
    request_id: str
    request_sha256: str
    being_id: str
    base_tick: int
    consumed_tick: int
    context_epoch: int
    context_sha256: str
    status: str
    disposition: str
    reason: str
    proposal: dict[str, Any] | None
    decider: dict[str, Any]
    latency_ms: int
    document_sha256: str

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "base_tick": self.base_tick,
            "being_id": self.being_id,
            "consumed_tick": self.consumed_tick,
            "context_epoch": self.context_epoch,
            "context_sha256": self.context_sha256,
            "decider": self.decider,
            "decision_seq": self.decision_seq,
            "disposition": self.disposition,
            "document_sha256": self.document_sha256,
            "latency_ms": self.latency_ms,
            "profile": REALTIME_DECISION_RECEIPT_PROFILE,
            "proposal": self.proposal,
            "reason": self.reason,
            "request_id": self.request_id,
            "request_sha256": self.request_sha256,
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class EpochCheckpoint:
    """Periodic zero-float checkpoint and receipt batch ready for PostgreSQL persistence."""

    epoch_seq: int
    start_tick: int
    end_tick: int
    world_minute: int
    state_sha256: str
    receipt_batch: tuple[dict[str, Any], ...]
    crossings_bound: tuple[dict[str, Any], ...]
    checkpoint_sha256: str

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "checkpoint_sha256": self.checkpoint_sha256,
            "crossings_bound": list(self.crossings_bound),
            "end_tick": self.end_tick,
            "epoch_seq": self.epoch_seq,
            "profile": EPOCH_CHECKPOINT_PROFILE,
            "receipt_batch": list(self.receipt_batch),
            "start_tick": self.start_tick,
            "state_sha256": self.state_sha256,
            "world_minute": self.world_minute,
        }


@dataclass(frozen=True, slots=True)
class RealtimeTickResult:
    """Output of a single 50 ms (20 Hz) authoritative tick."""

    tick: int
    world_minute: int
    changed_entity_count: int
    cell_deltas: Mapping[tuple[int, int], tuple[tuple[int, int, int, int, int, str, int], ...]]
    dispatched_requests: tuple[RealtimeDecisionRequest, ...]
    committed_receipts: tuple[RealtimeDecisionReceipt, ...]
    events: tuple[dict[str, Any], ...]
    checkpoint: EpochCheckpoint | None = None


class ContinuationValidator:
    """Validates async Tier 2 proposals against the live room state at arrival tick ``T + k``."""

    @staticmethod
    def validate(
        room: RealtimeWorldRoom,
        request: RealtimeDecisionRequest,
        proposal: Tier2Proposal,
    ) -> ContinuationVerdict:
        being = room.beings.get(request.being_id)
        if being is None:
            return ContinuationVerdict(
                status="stale",
                disposition="stale",
                reason="target_missing",
            )
        if being.active_request_id != request.request_id:
            return ContinuationVerdict(
                status="stale",
                disposition="superseded",
                reason="request_superseded",
            )

        choice = next(
            (c for c in request.offered_choices if c.label == proposal.chosen_label),
            None,
        )
        if choice is None:
            return ContinuationVerdict(
                status="rejected",
                disposition="rejected",
                reason="label_not_offered",
            )

        has_line = proposal.line is not None and proposal.line != ""
        if choice.takes_line != has_line:
            return ContinuationVerdict(
                status="rejected",
                disposition="rejected",
                reason="line_where_none" if has_line else "no_line_where_one",
            )

        checked_line: str | None = None
        if choice.takes_line and proposal.line is not None:
            try:
                checked_line = check_line(
                    proposal.line, maximum=request.line_characters_maximum
                )
            except LineRefused:
                return ContinuationVerdict(
                    status="rejected",
                    disposition="rejected",
                    reason="line_breaks_rule",
                )
            recent = (*being.said_lines, *being.heard_lines)
            if repeats_line(checked_line, recent):
                return ContinuationVerdict(
                    status="rejected",
                    disposition="rejected",
                    reason="line_said_before",
                )

        # Now check spatial and world preconditions at the current tick (T + k)
        if choice.kind == "go_place":
            place = room.places.get(choice.target_id or "")
            if place is None or not place.enabled:
                return ContinuationVerdict(
                    status="stale",
                    disposition="stale",
                    reason="stale_precondition",
                )
            if (
                len(place.occupants) >= place.capacity
                and being.being_id not in place.occupants
            ):
                return ContinuationVerdict(
                    status="stale",
                    disposition="stale",
                    reason="place_occupied",
                )
        elif choice.kind == "say_to":
            partner = room.beings.get(choice.target_id or "")
            if partner is None:
                return ContinuationVerdict(
                    status="stale",
                    disposition="stale",
                    reason="stale_precondition",
                )
            dx = partner.x_mm - being.x_mm
            dy = partner.y_mm - being.y_mm
            if dx * dx + dy * dy > HEARING_REACH_MM * HEARING_REACH_MM:
                return ContinuationVerdict(
                    status="stale",
                    disposition="stale",
                    reason="partner_out_of_reach",
                )
        elif choice.kind == "follow":
            leader = room.beings.get(choice.target_id or "")
            if leader is None:
                return ContinuationVerdict(
                    status="stale",
                    disposition="stale",
                    reason="stale_precondition",
                )

        return ContinuationVerdict(
            status="accepted",
            disposition="applied",
            reason="validated_choice",
            chosen_choice=choice,
            checked_line=checked_line,
        )


class HierarchicalMindCoordinator:
    """Coordinates Tier 0 (20 Hz reflex), Tier 1 (reactive fallback), and Tier 2 (async planner)."""

    def __init__(self, seed: str = "exulanica-realtime-v1") -> None:
        self.seed = seed
        self.in_flight_requests: dict[str, RealtimeDecisionRequest] = {}
        self.pending_proposals: list[Tier2Proposal] = []
        self.decision_seq: int = 0

    def queue_proposal(self, proposal: Tier2Proposal) -> None:
        """Enqueue an async Tier 2 model or Door bridge answer to be resolved on the next tick."""
        self.pending_proposals.append(proposal)

    def build_offered_choices(
        self, room: RealtimeWorldRoom, being: RealtimeBeing
    ) -> tuple[OfferedChoice, ...]:
        """Build deterministic offered choices from nearby places and nearby beings in AOI."""
        choices: list[OfferedChoice] = []

        # 1. Nearby beings within hearing reach for dialogue or following
        nearby = room.grid.nearby_beings(
            being.x_mm, being.y_mm, HEARING_REACH_MM, exclude_id=being.being_id
        )
        for other in nearby[:3]:
            dist_m = max(
                1,
                math.isqrt((other.x_mm - being.x_mm) ** 2 + (other.y_mm - being.y_mm) ** 2)
                // 1000,
            )
            choices.append(
                OfferedChoice(
                    label=f"say something to {other.label}, {dist_m} m away",
                    kind="say_to",
                    target_id=other.being_id,
                    target_x_mm=other.x_mm,
                    target_y_mm=other.y_mm,
                    takes_line=True,
                )
            )
            choices.append(
                OfferedChoice(
                    label=f"walk with {other.label}, {dist_m} m away",
                    kind="follow",
                    target_id=other.being_id,
                    target_x_mm=other.x_mm,
                    target_y_mm=other.y_mm,
                    takes_line=False,
                )
            )

        # 2. Available places in the room ordered deterministically
        for place_id in sorted(room.places):
            place = room.places[place_id]
            if not place.enabled:
                continue
            if len(place.occupants) >= place.capacity and being.being_id not in place.occupants:
                continue
            dist_m = max(
                1,
                math.isqrt((place.x_mm - being.x_mm) ** 2 + (place.y_mm - being.y_mm) ** 2)
                // 1000,
            )
            choices.append(
                OfferedChoice(
                    label=f"go to {place.label}, {dist_m} m away",
                    kind="go_place",
                    target_id=place.place_id,
                    target_x_mm=place.x_mm,
                    target_y_mm=place.y_mm,
                    takes_line=False,
                )
            )
            if len(choices) >= 8:
                break

        choices.append(
            OfferedChoice(
                label="carry on here",
                kind="wait",
                target_id=None,
                target_x_mm=being.x_mm,
                target_y_mm=being.y_mm,
                takes_line=False,
            )
        )
        return tuple(choices)

    def tier1_select_fallback(
        self,
        room: RealtimeWorldRoom,
        being: RealtimeBeing,
        tick: int,
    ) -> None:
        """Tier 1 local reactive policy: selects a valid local waypoint immediately."""
        place_ids = [
            pid
            for pid, p in sorted(room.places.items())
            if p.enabled and (len(p.occupants) < p.capacity or being.being_id in p.occupants)
        ]
        if not place_ids:
            being.goal_kind = "wait"
            being.goal_target_id = None
            being.target_x_mm = being.x_mm
            being.target_y_mm = being.y_mm
            being.active_tier = 1
            being.motion_state = "idle"
            return

        draw = _deterministic_int(self.seed, "tier1", being.being_id, tick)
        chosen_pid = place_ids[draw % len(place_ids)]
        place = room.places[chosen_pid]

        # Release previous place occupancy if switching places
        if being.goal_target_id and being.goal_target_id in room.places:
            room.places[being.goal_target_id].occupants.discard(being.being_id)

        being.goal_kind = "go_place"
        being.goal_target_id = place.place_id
        being.target_x_mm = place.x_mm
        being.target_y_mm = place.y_mm
        being.active_tier = 1
        being.motion_state = "walking"

    def dispatch_tier2_request(
        self,
        room: RealtimeWorldRoom,
        being: RealtimeBeing,
    ) -> RealtimeDecisionRequest | None:
        """Create and register a non-blocking Tier 2 request while Tier 0/1 keeps moving."""
        if being.decider["kind"] not in ("model", "external"):
            return None
        if being.active_request_id is not None:
            return None

        offered = self.build_offered_choices(room, being)
        if len(offered) < 2:
            return None

        request_id = (
            f"req:{room.world_id}:{being.being_id}:{room.tick}:{room.epoch_seq}"
        )
        context: dict[str, Any] = {
            "being_id": being.being_id,
            "context_epoch": room.epoch_seq,
            "heard_lines": list(being.heard_lines[-4:]),
            "label": being.label,
            "offered_choices": [c.canonical_dict() for c in offered],
            "position_mm": [being.x_mm, being.y_mm, being.z_mm],
            "tick": room.tick,
            "world_title": room.world_title,
        }
        context_sha256 = sha256_of_canonical(context).hex()
        unsigned = {
            "base_tick": room.tick,
            "being_id": being.being_id,
            "context": context,
            "context_epoch": room.epoch_seq,
            "context_sha256": context_sha256,
            "decider": dict(being.decider),
            "line_characters_maximum": LINE_CHARACTERS_MAXIMUM,
            "offered_choices": [c.canonical_dict() for c in offered],
            "profile": REALTIME_DECISION_REQUEST_PROFILE,
            "request_id": request_id,
        }
        doc_sha256 = sha256_of_canonical(unsigned).hex()
        request = RealtimeDecisionRequest(
            request_id=request_id,
            being_id=being.being_id,
            base_tick=room.tick,
            context_epoch=room.epoch_seq,
            decider=dict(being.decider),
            offered_choices=offered,
            line_characters_maximum=LINE_CHARACTERS_MAXIMUM,
            context=context,
            context_sha256=context_sha256,
            document_sha256=doc_sha256,
        )
        being.active_request_id = request_id
        self.in_flight_requests[request_id] = request
        return request

    def resolve_pending_proposals(
        self, room: RealtimeWorldRoom
    ) -> tuple[list[RealtimeDecisionReceipt], list[dict[str, Any]]]:
        """Validate and commit queued Tier 2 proposals at the current tick without blocking."""
        if not self.pending_proposals:
            return [], []

        batch = list(self.pending_proposals)
        self.pending_proposals.clear()
        receipts: list[RealtimeDecisionReceipt] = []
        events: list[dict[str, Any]] = []

        for proposal in batch:
            request = self.in_flight_requests.pop(proposal.request_id, None)
            if request is None:
                continue

            verdict = ContinuationValidator.validate(room, request, proposal)
            being = room.beings.get(request.being_id)
            if being is not None and being.active_request_id == request.request_id:
                being.active_request_id = None

            proposal_record: dict[str, Any] | None = None
            if verdict.status == "accepted" and verdict.chosen_choice is not None:
                proposal_record = {
                    "chosen_label": verdict.chosen_choice.label,
                    "kind": verdict.chosen_choice.kind,
                    "line": verdict.checked_line,
                    "target_id": verdict.chosen_choice.target_id,
                }
                if being is not None:
                    self._apply_accepted_choice(
                        room, being, verdict.chosen_choice, verdict.checked_line, events
                    )

            self.decision_seq += 1
            unsigned_receipt = {
                "base_tick": request.base_tick,
                "being_id": request.being_id,
                "consumed_tick": room.tick,
                "context_epoch": request.context_epoch,
                "context_sha256": request.context_sha256,
                "decider": request.decider,
                "decision_seq": self.decision_seq,
                "disposition": verdict.disposition,
                "latency_ms": int(proposal.latency_ms),
                "profile": REALTIME_DECISION_RECEIPT_PROFILE,
                "proposal": proposal_record,
                "reason": verdict.reason,
                "request_id": request.request_id,
                "request_sha256": request.document_sha256,
                "status": verdict.status,
            }
            receipt_sha256 = sha256_of_canonical(unsigned_receipt).hex()
            receipt = RealtimeDecisionReceipt(
                decision_seq=self.decision_seq,
                request_id=request.request_id,
                request_sha256=request.document_sha256,
                being_id=request.being_id,
                base_tick=request.base_tick,
                consumed_tick=room.tick,
                context_epoch=request.context_epoch,
                context_sha256=request.context_sha256,
                status=verdict.status,
                disposition=verdict.disposition,
                reason=verdict.reason,
                proposal=proposal_record,
                decider=request.decider,
                latency_ms=int(proposal.latency_ms),
                document_sha256=receipt_sha256,
            )
            receipts.append(receipt)
            events.append(
                {
                    "being_id": request.being_id,
                    "decision_seq": receipt.decision_seq,
                    "disposition": receipt.disposition,
                    "kind": "decision_applied",
                    "reason": receipt.reason,
                    "request_id": receipt.request_id,
                    "tick": room.tick,
                }
            )

        return receipts, events

    def _apply_accepted_choice(
        self,
        room: RealtimeWorldRoom,
        being: RealtimeBeing,
        choice: OfferedChoice,
        checked_line: str | None,
        events: list[dict[str, Any]],
    ) -> None:
        if (
            being.goal_target_id
            and being.goal_target_id in room.places
            and choice.target_id != being.goal_target_id
        ):
            room.places[being.goal_target_id].occupants.discard(being.being_id)

        being.active_tier = 2
        being.goal_kind = choice.kind
        being.goal_target_id = choice.target_id

        if choice.kind == "go_place" and choice.target_id in room.places:
            place = room.places[choice.target_id]
            place.occupants.add(being.being_id)
            being.target_x_mm = place.x_mm
            being.target_y_mm = place.y_mm
            being.motion_state = "walking"
        elif choice.kind == "follow" and choice.target_id in room.beings:
            leader = room.beings[choice.target_id]
            being.target_x_mm = leader.x_mm
            being.target_y_mm = leader.y_mm
            being.motion_state = "walking"
        elif choice.kind == "say_to" and choice.target_id in room.beings:
            partner = room.beings[choice.target_id]
            being.yaw_urad = _yaw_urad_from_delta(
                partner.x_mm - being.x_mm, partner.y_mm - being.y_mm
            )
            being.motion_state = "talking"
            if checked_line is not None:
                being.last_line = checked_line
                being.said_lines.append(checked_line)
                partner.heard_lines.append(checked_line)
                for bystander in room.grid.nearby_beings(
                    being.x_mm, being.y_mm, HEARING_REACH_MM, exclude_id=being.being_id
                ):
                    if bystander.being_id != partner.being_id:
                        bystander.heard_lines.append(checked_line)
                events.append(
                    {
                        "kind": "said",
                        "line": checked_line,
                        "speaker_id": being.being_id,
                        "tick": room.tick,
                        "to_id": partner.being_id,
                    }
                )
        else:
            being.target_x_mm = being.x_mm
            being.target_y_mm = being.y_mm
            being.motion_state = "idle"


class RealtimeWorldRoom:
    """Authoritative 20 Hz spatial tick room for up to 256+ concurrent beings."""

    def __init__(
        self,
        *,
        world_id: str,
        version_id: str,
        world_title: str = "A Living Town",
        seed: str = "exulanica-realtime-v1",
        checkpoint_interval_ticks: int = DEFAULT_CHECKPOINT_INTERVAL_TICKS,
        aoi_cell_mm: int = AOI_CELL_MM,
    ) -> None:
        self.world_id = world_id
        self.version_id = version_id
        self.world_title = world_title
        self.seed = seed
        self.checkpoint_interval_ticks = checkpoint_interval_ticks
        self.tick: int = 0
        self.epoch_seq: int = 0
        self.epoch_start_tick: int = 0

        self.beings: dict[str, RealtimeBeing] = {}
        self.places: dict[str, AffordancePlace] = {}
        self.manifests: dict[str, TranslationManifest] = {}
        self.grid = AOISpatialGrid(cell_mm=aoi_cell_mm)
        self.coordinator = HierarchicalMindCoordinator(seed=seed)

        self._next_u16_id: int = 1
        self._epoch_receipts: list[RealtimeDecisionReceipt] = []
        self._epoch_crossings: list[dict[str, Any]] = []
        self.checkpoints: list[EpochCheckpoint] = []

    @property
    def world_minute(self) -> int:
        return self.tick // SUBTICKS_PER_WORLD_MINUTE

    def add_place(self, place: AffordancePlace) -> None:
        self.places[place.place_id] = place

    def add_being(
        self,
        *,
        being_id: str,
        label: str,
        came_by: str = "populated",
        decider: Mapping[str, Any] | None = None,
        x_mm: int = 0,
        y_mm: int = 0,
        z_mm: int = 0,
        yaw_urad: int = 0,
        speed_mm_per_tick: int = DEFAULT_SPEED_MM_PER_TICK,
    ) -> RealtimeBeing:
        if being_id in self.beings:
            raise ValueError(f"being {being_id!r} already exists in room")
        u16_id = self._next_u16_id
        self._next_u16_id += 1
        being = RealtimeBeing(
            being_id=being_id,
            u16_id=u16_id,
            label=label,
            came_by=came_by,
            decider=dict(decider or {"kind": "routine"}),
            x_mm=x_mm,
            y_mm=y_mm,
            z_mm=z_mm,
            yaw_urad=yaw_urad,
            speed_mm_per_tick=speed_mm_per_tick,
            target_x_mm=x_mm,
            target_y_mm=y_mm,
        )
        self.beings[being_id] = being
        self.grid.rebuild(self.beings.values())
        return being

    def admit_door_arrival(
        self,
        crossing: Crossing,
        *,
        manifest_raw: Mapping[str, Any],
        source_payload: Mapping[str, Any],
        spawn_x_mm: int = 0,
        spawn_y_mm: int = 0,
        label: str | None = None,
    ) -> RealtimeBeing:
        """Validate and admit a cross-world Door visitor into the live 20 Hz room."""
        checked = check_arrival(dict(crossing.document))
        if str(crossing.crossing_id) != checked["arrival_id"]:
            raise ValueError("crossing_id does not match arrival_id")

        manifest = read_manifest(manifest_raw)
        check_accounting(manifest, source_payload)
        manifest_sha = sha256_of_canonical(dict(manifest_raw)).hex()
        if manifest_sha != checked["translation_manifest_sha256"]:
            raise ValueError("translation_manifest_sha256 mismatch")

        thing_id = str(checked["thing_id"])
        if thing_id in self.beings:
            raise ValueError("already_here")

        by = checked["origin"]["by"]
        decided_by = checked.get("decided_by", "program")
        if decided_by == "world":
            visitor_decider: dict[str, Any] = {"kind": "routine"}
        else:
            visitor_decider = {
                "bridge": str(by["bridge"]),
                "grant_id": str(checked["grant_id"]),
                "kind": "external",
            }

        carried_ids = [str(item["thing_id"]) for item in checked["carried"]]
        visitor_label = label or f"the {checked['kind']['kind']}"
        u16_id = self._next_u16_id
        self._next_u16_id += 1

        visitor = RealtimeBeing(
            being_id=thing_id,
            u16_id=u16_id,
            label=visitor_label,
            came_by="crossed",
            decider=visitor_decider,
            x_mm=spawn_x_mm,
            y_mm=spawn_y_mm,
            z_mm=0,
            yaw_urad=0,
            target_x_mm=spawn_x_mm,
            target_y_mm=spawn_y_mm,
            carried_ids=carried_ids,
            arrival_id=str(checked["arrival_id"]),
            translation_manifest_sha256=manifest_sha,
        )
        self.beings[thing_id] = visitor
        self.manifests[str(checked["arrival_id"])] = manifest
        self._epoch_crossings.append(
            {
                "arrival_id": str(checked["arrival_id"]),
                "disposition": "arrived",
                "profile": ARRIVAL_PROFILE,
                "thing_id": thing_id,
                "tick": self.tick,
                "translation_manifest_sha256": manifest_sha,
            }
        )
        self.grid.rebuild(self.beings.values())
        return visitor

    def canonical_state(self) -> dict[str, Any]:
        """Return the strict zero-float canonical dictionary of the authoritative room state."""
        return {
            "beings": [
                self.beings[bid].canonical_dict() for bid in sorted(self.beings)
            ],
            "epoch_seq": self.epoch_seq,
            "places": [
                self.places[pid].canonical_dict() for pid in sorted(self.places)
            ],
            "profile": REALTIME_ROOM_STATE_PROFILE,
            "seed": self.seed,
            "tick": self.tick,
            "version_id": self.version_id,
            "world_id": self.world_id,
            "world_minute": self.world_minute,
            "world_title": self.world_title,
        }

    def state_sha256(self) -> str:
        """Compute the canonical SHA-256 hex digest of the room state (rejects any float)."""
        return hashlib.sha256(canonical_json(self.canonical_state())).hexdigest()

    def _step_tier0_and_tier1(
        self,
        *,
        tier2_dispatch_limit: int,
    ) -> list[RealtimeDecisionRequest]:
        """Advance all beings by one 50 ms spatial tick using Tier 0 steering & Tier 1 fallback."""
        dispatched: list[RealtimeDecisionRequest] = []
        tick = self.tick
        places = self.places
        beings_map = self.beings
        coordinator = self.coordinator
        by_cell = self.grid._beings_by_cell
        cell_mm = self.grid._cell_mm
        min_sep = COLLISION_RADIUS_MM * 2
        min_sep_sq = min_sep * min_sep

        for being in beings_map.values():
            # Update dynamic follow target if following another being
            if being.goal_kind == "follow" and being.goal_target_id in beings_map:
                leader = beings_map[being.goal_target_id]
                being.target_x_mm = leader.x_mm
                being.target_y_mm = leader.y_mm

            dx = being.target_x_mm - being.x_mm
            dy = being.target_y_mm - being.y_mm
            dist_sq = dx * dx + dy * dy

            if dist_sq == 0:
                # Reached waypoint / idle: Tier 1 immediately picks a continuation if not talking
                if being.motion_state != "talking":
                    coordinator.tier1_select_fallback(self, being, tick)
                    dx = being.target_x_mm - being.x_mm
                    dy = being.target_y_mm - being.y_mm
                    dist_sq = dx * dx + dy * dy

                # If configured for Tier 2 (model or external Door), dispatch non-blocking ask
                if (
                    len(dispatched) < tier2_dispatch_limit
                    and being.decider["kind"] in ("model", "external")
                    and being.active_request_id is None
                ):
                    req = coordinator.dispatch_tier2_request(self, being)
                    if req is not None:
                        dispatched.append(req)

            if dist_sq > 0:
                step = being.speed_mm_per_tick
                if dist_sq <= step * step:
                    nx = being.target_x_mm
                    ny = being.target_y_mm
                    being.motion_state = "arrived"
                    if being.goal_kind == "go_place" and being.goal_target_id in places:
                        places[being.goal_target_id].occupants.add(being.being_id)
                else:
                    dist = math.isqrt(dist_sq)
                    nx = being.x_mm + (dx * step) // dist
                    ny = being.y_mm + (dy * step) // dist
                    being.motion_state = "walking"

                # Tier 0 local collision avoidance against same-cell neighbors
                cx = nx // cell_mm
                cy = ny // cell_mm
                bucket = by_cell.get((cx, cy))
                if bucket and len(bucket) > 1:
                    uid = being.u16_id
                    for other in bucket:
                        if other.u16_id >= uid:
                            continue
                        odx = nx - other.x_mm
                        ody = ny - other.y_mm
                        odist_sq = odx * odx + ody * ody
                        if 0 < odist_sq < min_sep_sq:
                            odist = math.isqrt(odist_sq)
                            push = (min_sep - odist) // 2 + 1
                            nx += (odx * push) // odist
                            ny += (ody * push) // odist
                        elif odist_sq == 0:
                            nx += (uid & 7) + 1
                            ny -= ((uid >> 3) & 7) + 1

                being.yaw_urad = _yaw_urad_from_delta(nx - being.x_mm, ny - being.y_mm)
                being.x_mm = nx
                being.y_mm = ny

        return dispatched

    def step_tick(self, *, tier2_dispatch_limit: int = 8) -> RealtimeTickResult:
        """Advance the authoritative room by one 50 ms (20 Hz) tick."""
        self.tick += 1

        # 1. Resolve any asynchronous Tier 2 model/Door proposals that arrived before this tick
        committed_receipts, events = self.coordinator.resolve_pending_proposals(self)
        if committed_receipts:
            self._epoch_receipts.extend(committed_receipts)

        # 2. Step Tier 0 (20 Hz steering/collision) & Tier 1 (reactive fallback) + dispatch Tier 2
        dispatched_requests = self._step_tier0_and_tier1(
            tier2_dispatch_limit=tier2_dispatch_limit
        )

        # 3. Rebuild spatial hash grid and compute delta-compressed frames by AOI cell
        self.grid.rebuild(self.beings.values())
        cell_deltas: dict[
            tuple[int, int], tuple[tuple[int, int, int, int, int, str, int], ...]
        ] = {}
        changed_count = 0
        cell_mm = self.grid._cell_mm
        temp_cells: dict[
            tuple[int, int], list[tuple[int, int, int, int, int, str, int]]
        ] = defaultdict(list)

        for being in self.beings.values():
            pose = being.pose_tuple()
            if pose != being.last_Snapshot_pose:
                being.last_Snapshot_pose = pose
                changed_count += 1
                cell = (being.x_mm // cell_mm, being.y_mm // cell_mm)
                temp_cells[cell].append(
                    (
                        being.u16_id,
                        being.x_mm,
                        being.y_mm,
                        being.z_mm,
                        being.yaw_urad,
                        being.motion_state,
                        being.active_tier,
                    )
                )

        for cell, entries in temp_cells.items():
            entries.sort(key=lambda item: item[0])
            cell_deltas[cell] = tuple(entries)

        # 4. Periodic epoch checkpointing
        checkpoint: EpochCheckpoint | None = None
        if (
            self.checkpoint_interval_ticks > 0
            and self.tick % self.checkpoint_interval_ticks == 0
        ):
            checkpoint = self.flush_epoch_checkpoint()

        return RealtimeTickResult(
            tick=self.tick,
            world_minute=self.world_minute,
            changed_entity_count=changed_count,
            cell_deltas=cell_deltas,
            dispatched_requests=tuple(dispatched_requests),
            committed_receipts=tuple(committed_receipts),
            events=tuple(events),
            checkpoint=checkpoint,
        )

    def aoi_delta_frame(
        self,
        tick_result: RealtimeTickResult,
        *,
        observer_x_mm: int,
        observer_y_mm: int,
        radius_mm: int = DEFAULT_AOI_RADIUS_MM,
    ) -> dict[str, Any]:
        """Return the AOI-filtered delta-compressed frame for a client or Door bridge."""
        cell_mm = self.grid.cell_mm
        min_cx = (observer_x_mm - radius_mm) // cell_mm
        max_cx = (observer_x_mm + radius_mm) // cell_mm
        min_cy = (observer_y_mm - radius_mm) // cell_mm
        max_cy = (observer_y_mm + radius_mm) // cell_mm

        deltas: list[list[Any]] = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                cell_entries = tick_result.cell_deltas.get((cx, cy))
                if not cell_entries:
                    continue
                for entry in cell_entries:
                    deltas.append(list(entry))

        deltas.sort(key=lambda row: row[0])
        return {
            "deltas": deltas,
            "observer_cell": [observer_x_mm // cell_mm, observer_y_mm // cell_mm],
            "profile": REALTIME_DELTA_FRAME_PROFILE,
            "radius_mm": radius_mm,
            "tick": tick_result.tick,
            "world_minute": tick_result.world_minute,
        }

    def flush_epoch_checkpoint(self) -> EpochCheckpoint:
        """Compute canonical zero-float ``state_sha256`` and flush the epoch checkpoint batch."""
        self.epoch_seq += 1
        state_digest = self.state_sha256()
        receipt_dicts = tuple(r.canonical_dict() for r in self._epoch_receipts)
        crossing_dicts = tuple(dict(c) for c in self._epoch_crossings)
        unsigned = {
            "crossings_bound": list(crossing_dicts),
            "end_tick": self.tick,
            "epoch_seq": self.epoch_seq,
            "profile": EPOCH_CHECKPOINT_PROFILE,
            "receipt_batch": list(receipt_dicts),
            "start_tick": self.epoch_start_tick,
            "state_sha256": state_digest,
            "world_minute": self.world_minute,
        }
        checkpoint_digest = sha256_of_canonical(unsigned).hex()
        checkpoint = EpochCheckpoint(
            epoch_seq=self.epoch_seq,
            start_tick=self.epoch_start_tick,
            end_tick=self.tick,
            world_minute=self.world_minute,
            state_sha256=state_digest,
            receipt_batch=receipt_dicts,
            crossings_bound=crossing_dicts,
            checkpoint_sha256=checkpoint_digest,
        )
        self.checkpoints.append(checkpoint)
        self._epoch_receipts.clear()
        self._epoch_crossings.clear()
        self.epoch_start_tick = self.tick
        return checkpoint
