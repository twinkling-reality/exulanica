"""FastAPI HTTP and WebSocket surface for the 20 Hz real-time spatial room and 3-tier minds.

Mounts under ``/world/versions/{version_id}/realtime``:

*   ``GET /world/versions/{version_id}/realtime/state``: returns the current 20 Hz room snapshot
    and AOI delta frame (``?observer_x_mm=...&observer_z_mm=...&since_tick=...``) with canonical
    ``state_sha256`` and active Tier 0/1/2/Door statuses.
*   ``POST /world/versions/{version_id}/realtime/step``: advances the room by ``1..100`` 20 Hz
    ticks, applies player/agent movement or speech actions and async Tier 2 model/Door proposals,
    persists any flushed epoch checkpoint, and returns the AOI delta frame plus receipts and
    checkpoint.
*   ``WebSocket /world/versions/{version_id}/realtime/stream``: streams 20 Hz AOI delta frames
    (``exulanica.realtime-delta-frame/v1``) and accepts non-blocking inbound player actions,
    Tier 2 proposals, AOI subscriptions, and step/checkpoint commands.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.authorisation import TokenNotAccepted
from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.realtime_persistence import (
    RealtimeCheckpointRepository,
    hydrate_room_from_postgres,
    hydrate_room_from_society_state,
)
from exulanica.world.realtime_runtime import (
    DEFAULT_AOI_RADIUS_MM,
    REALTIME_DELTA_FRAME_PROFILE,
    REALTIME_ROOM_STATE_PROFILE,
    EpochCheckpoint,
    RealtimeDecisionReceipt,
    RealtimeDecisionRequest,
    RealtimeWorldRoom,
    Tier2Proposal,
)

__all__ = [
    "PlayerActionInput",
    "StepRealtimeBody",
    "Tier2ProposalInput",
    "get_realtime_room",
    "register_realtime_room",
    "router",
]

router = APIRouter(prefix="/world/versions/{version_id}/realtime", tags=["realtime"])

_ROOMS_STATE_ATTR = "realtime_world_rooms"


class PlayerActionInput(BaseModel):
    """Direct player or agent movement/speech command submitted to the 20 Hz loop."""

    model_config = ConfigDict(extra="forbid")
    being_id: Annotated[str, Field(min_length=1, max_length=200)]
    target_x_mm: StrictInt | None = None
    target_y_mm: StrictInt | None = None
    target_z_mm: StrictInt | None = None
    goal_kind: Annotated[str, Field(min_length=1, max_length=64)] = "walk_to_point"
    line: Annotated[str, Field(min_length=1, max_length=200)] | None = None


class Tier2ProposalInput(BaseModel):
    """Asynchronous Tier 2 model or external Door bridge proposal arriving at tick T + k."""

    model_config = ConfigDict(extra="forbid")
    request_id: Annotated[str, Field(min_length=1, max_length=300)]
    chosen_label: Annotated[str, Field(min_length=1, max_length=300)]
    line: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    latency_ms: Annotated[StrictInt, Field(ge=0, le=3_600_000)] = 0
    model_id: Annotated[str, Field(min_length=1, max_length=200)] | None = None
    bridge: Annotated[str, Field(min_length=1, max_length=64)] | None = None
    grant_id: Annotated[str, Field(min_length=1, max_length=64)] | None = None


class StepRealtimeBody(BaseModel):
    """Request body for advancing a 20 Hz real-time room by 1..100 ticks."""

    model_config = ConfigDict(extra="forbid")
    ticks: Annotated[StrictInt, Field(ge=1, le=100)] = 1
    tier2_dispatch_limit: Annotated[StrictInt, Field(ge=0, le=256)] = 8
    observer_x_mm: StrictInt = 0
    observer_y_mm: StrictInt | None = None
    observer_z_mm: StrictInt = 0
    radius_mm: Annotated[StrictInt, Field(ge=1_000, le=500_000)] = DEFAULT_AOI_RADIUS_MM
    player_actions: list[PlayerActionInput] = Field(default_factory=list)
    tier2_proposals: list[Tier2ProposalInput] = Field(default_factory=list)
    flush_checkpoint: bool = False
    bootstrap: bool = False


def _rooms_map(app: FastAPI) -> dict[tuple[str, str], RealtimeWorldRoom]:
    rooms = getattr(app.state, _ROOMS_STATE_ATTR, None)
    if rooms is None:
        rooms = {}
        setattr(app.state, _ROOMS_STATE_ATTR, rooms)
    return rooms


def register_realtime_room(
    app: FastAPI,
    workspace_id: uuid.UUID,
    room: RealtimeWorldRoom,
) -> None:
    """Register or replace an active ``RealtimeWorldRoom`` for ``(workspace_id, version_id)``."""
    _rooms_map(app)[(str(workspace_id), str(room.version_id))] = room


def get_realtime_room(
    app: FastAPI,
    workspace_id: uuid.UUID,
    version_id: uuid.UUID | str,
) -> RealtimeWorldRoom | None:
    """Return the active in-memory ``RealtimeWorldRoom`` for ``(workspace_id, version_id)``."""
    return _rooms_map(app).get((str(workspace_id), str(version_id)))


def _resolve_or_hydrate_room(
    app: FastAPI,
    connection: Any,
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    *,
    world_id: str | None = None,
    bootstrap: bool = False,
) -> RealtimeWorldRoom:
    rooms = _rooms_map(app)
    key = (str(workspace_id), str(version_id))
    existing = rooms.get(key)
    if existing is not None:
        if world_id is not None and existing.world_id != world_id:
            raise UnknownWorldResource(str(version_id))
        return existing

    try:
        room = hydrate_room_from_postgres(
            connection,
            workspace_id,
            version_id=version_id,
            world_id=world_id,
            prefer_checkpoint=True,
        )
    except UnknownWorldResource:
        if not bootstrap:
            raise
        room = hydrate_room_from_society_state(
            world_id=world_id or "realtime-world",
            version_id=str(version_id),
            seed=f"exulanica-bootstrap-{version_id}",
        )

    rooms[key] = room
    return room


def _build_aoi_snapshot_frame(
    room: RealtimeWorldRoom,
    *,
    observer_x_mm: int,
    observer_y_mm: int,
    radius_mm: int,
    since_tick: int | None = None,
) -> dict[str, Any]:
    """Build an AOI delta frame directly from the room's current spatial grid."""
    cell_mm = room.grid.cell_mm
    nearby = room.grid.nearby_beings(observer_x_mm, observer_y_mm, radius_mm)
    deltas: list[list[Any]] = []
    entities: list[dict[str, Any]] = []
    for being in nearby:
        deltas.append(
            [
                being.u16_id,
                being.x_mm,
                being.y_mm,
                being.z_mm,
                being.yaw_urad,
                being.motion_state,
                being.active_tier,
            ]
        )
        entities.append(
            {
                "active_tier": being.active_tier,
                "being_id": being.being_id,
                "label": being.label,
                "last_line": being.last_line,
                "mind_tier": being.mind_tier_label(),
                "motion_state": being.motion_state,
                "u16_id": being.u16_id,
                "x_mm": being.x_mm,
                "y_mm": being.y_mm,
                "yaw_urad": being.yaw_urad,
                "z_mm": being.z_mm,
            }
        )
    return {
        "deltas": deltas,
        "entities": entities,
        "observer_cell": [observer_x_mm // cell_mm, observer_y_mm // cell_mm],
        "profile": REALTIME_DELTA_FRAME_PROFILE,
        "radius_mm": radius_mm,
        "since_tick": since_tick,
        "state_sha256": room.state_sha256(),
        "tick": room.tick,
        "world_minute": room.world_minute,
    }


def _execute_room_steps(
    room: RealtimeWorldRoom,
    repo: RealtimeCheckpointRepository,
    *,
    ticks: int,
    tier2_dispatch_limit: int,
    observer_x_mm: int,
    observer_y_mm: int,
    radius_mm: int,
    player_actions: list[PlayerActionInput],
    tier2_proposals: list[Tier2ProposalInput],
    flush_checkpoint: bool,
) -> dict[str, Any]:
    start_tick = room.tick

    for action in player_actions:
        if action.being_id not in room.beings:
            room.add_being(
                being_id=action.being_id,
                label=action.being_id,
                came_by="placed",
                decider={"kind": "person"},
                x_mm=action.target_x_mm or 0,
                y_mm=(
                    action.target_y_mm
                    if action.target_y_mm is not None
                    else (action.target_z_mm or 0)
                ),
                z_mm=action.target_z_mm or 0,
            )
        room.apply_player_action(
            being_id=action.being_id,
            target_x_mm=action.target_x_mm,
            target_y_mm=(
                action.target_y_mm if action.target_y_mm is not None else action.target_z_mm
            ),
            target_z_mm=action.target_z_mm,
            goal_kind=action.goal_kind,
            line=action.line,
        )

    for prop in tier2_proposals:
        room.coordinator.queue_proposal(
            Tier2Proposal(
                request_id=prop.request_id,
                chosen_label=prop.chosen_label,
                line=prop.line,
                latency_ms=prop.latency_ms,
                model_id=prop.model_id,
                bridge=prop.bridge,
                grant_id=prop.grant_id,
            )
        )

    dispatched_all: list[RealtimeDecisionRequest] = []
    committed_all: list[RealtimeDecisionReceipt] = []
    events_all: list[dict[str, Any]] = []
    flushed_ckpt: EpochCheckpoint | None = None
    last_tick_res = None

    for _ in range(ticks):
        res = room.step_tick(tier2_dispatch_limit=tier2_dispatch_limit)
        last_tick_res = res
        dispatched_all.extend(res.dispatched_requests)
        committed_all.extend(res.committed_receipts)
        events_all.extend(res.events)
        if res.checkpoint is not None:
            flushed_ckpt = res.checkpoint
            repo.save_checkpoint(room, flushed_ckpt)

    if flush_checkpoint and (flushed_ckpt is None or flushed_ckpt.end_tick != room.tick):
        flushed_ckpt = room.flush_epoch_checkpoint()
        repo.save_checkpoint(room, flushed_ckpt)

    assert last_tick_res is not None
    aoi_frame = _build_aoi_snapshot_frame(
        room,
        observer_x_mm=observer_x_mm,
        observer_y_mm=observer_y_mm,
        radius_mm=radius_mm,
        since_tick=start_tick,
    )

    return {
        "checkpoint": None if flushed_ckpt is None else flushed_ckpt.canonical_dict(),
        "committed_receipts": [r.canonical_dict() for r in committed_all],
        "delta_frame": aoi_frame,
        "dispatched_requests": [req.canonical_dict() for req in dispatched_all],
        "events": events_all,
        "profile": "exulanica.realtime-step-result/v1",
        "start_tick": start_tick,
        "state_sha256": aoi_frame["state_sha256"],
        "tick": room.tick,
        "ticks_advanced": room.tick - start_tick,
        "tier_summary": room.tier_summary(),
        "version_id": room.version_id,
        "world_id": room.world_id,
        "world_minute": room.world_minute,
    }


@router.get("/state")
def get_realtime_state(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    request: Request,
    world_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    observer_x_mm: int = 0,
    observer_y_mm: int | None = None,
    observer_z_mm: int = 0,
    radius_mm: Annotated[int, Field(ge=1_000, le=500_000)] = DEFAULT_AOI_RADIUS_MM,
    since_tick: Annotated[int | None, Field(ge=0)] = None,
) -> dict[str, Any]:
    """Return the current 20 Hz room state snapshot, AOI delta frame, and active tier summary."""
    room = _resolve_or_hydrate_room(
        request.app,
        connection,
        session.workspace_id,
        version_id,
        world_id=world_id,
        bootstrap=False,
    )
    resolved_y_mm = observer_y_mm if observer_y_mm is not None else observer_z_mm
    aoi_frame = _build_aoi_snapshot_frame(
        room,
        observer_x_mm=observer_x_mm,
        observer_y_mm=resolved_y_mm,
        radius_mm=radius_mm,
        since_tick=since_tick,
    )
    return {
        "aoi_frame": aoi_frame,
        "beings": [
            {
                **room.beings[bid].canonical_dict(),
                "mind_tier": room.beings[bid].mind_tier_label(),
            }
            for bid in sorted(room.beings)
        ],
        "epoch_seq": room.epoch_seq,
        "in_flight_requests": [
            room.coordinator.in_flight_requests[rid].canonical_dict()
            for rid in sorted(room.coordinator.in_flight_requests)
        ],
        "latest_checkpoint": (room.checkpoints[-1].canonical_dict() if room.checkpoints else None),
        "profile": REALTIME_ROOM_STATE_PROFILE,
        "since_tick": since_tick,
        "state_sha256": aoi_frame["state_sha256"],
        "tick": room.tick,
        "tier_summary": room.tier_summary(),
        "version_id": room.version_id,
        "world_id": room.world_id,
        "world_minute": room.world_minute,
    }


@router.post("/step")
def post_realtime_step(
    version_id: uuid.UUID,
    body: StepRealtimeBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> dict[str, Any]:
    """Advance the 20 Hz room by 1..100 ticks and apply player actions / Tier 2 proposals."""
    room = _resolve_or_hydrate_room(
        request.app,
        connection,
        session.workspace_id,
        version_id,
        world_id=world_id,
        bootstrap=body.bootstrap,
    )
    resolved_y_mm = body.observer_y_mm if body.observer_y_mm is not None else body.observer_z_mm
    repo = RealtimeCheckpointRepository(connection, session.workspace_id)
    return _execute_room_steps(
        room,
        repo,
        ticks=body.ticks,
        tier2_dispatch_limit=body.tier2_dispatch_limit,
        observer_x_mm=body.observer_x_mm,
        observer_y_mm=resolved_y_mm,
        radius_mm=body.radius_mm,
        player_actions=body.player_actions,
        tier2_proposals=body.tier2_proposals,
        flush_checkpoint=body.flush_checkpoint,
    )


def _authenticate_websocket(websocket: WebSocket) -> uuid.UUID | None:
    """Resolve the caller's workspace_id for a WebSocket stream connection."""
    services = getattr(websocket.app.state, "services", None)
    auth_header = websocket.headers.get("authorization")
    if auth_header and services is not None and getattr(services, "tokens", None) is not None:
        scheme, _, token = auth_header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise TokenNotAccepted("invalid bearer header")
        session, _held = services.tokens.grant_for(token.strip())
        return session.workspace_id

    ws_param = websocket.query_params.get("workspace_id")
    if ws_param:
        try:
            return uuid.UUID(ws_param)
        except ValueError:
            pass

    rooms = _rooms_map(websocket.app)
    version_str = str(websocket.path_params.get("version_id", ""))
    for (ws_id_str, ver_str), _room in rooms.items():
        if ver_str == version_str:
            return uuid.UUID(ws_id_str)

    return uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.websocket("/stream")
async def websocket_realtime_stream(
    websocket: WebSocket,
    version_id: uuid.UUID,
) -> None:
    """Stream 20 Hz AOI delta frames and process non-blocking player / Tier 2 messages."""
    try:
        workspace_id = _authenticate_websocket(websocket)
    except TokenNotAccepted:
        await websocket.close(code=1008)
        return

    assert workspace_id is not None
    await websocket.accept()

    observer_x_mm = int(websocket.query_params.get("observer_x_mm", "0"))
    observer_z_mm = int(
        websocket.query_params.get(
            "observer_y_mm", websocket.query_params.get("observer_z_mm", "0")
        )
    )
    radius_mm = int(websocket.query_params.get("radius_mm", str(DEFAULT_AOI_RADIUS_MM)))
    world_id = websocket.query_params.get("world_id")

    rooms = _rooms_map(websocket.app)
    key = (str(workspace_id), str(version_id))
    room = rooms.get(key)
    if room is None:
        room = hydrate_room_from_society_state(
            world_id=world_id or "realtime-world",
            version_id=str(version_id),
            seed=f"exulanica-ws-{version_id}",
        )
        rooms[key] = room

    repo = RealtimeCheckpointRepository(None, workspace_id)

    # Emit initial 20 Hz AOI delta frame immediately on connection
    initial_frame = _build_aoi_snapshot_frame(
        room,
        observer_x_mm=observer_x_mm,
        observer_y_mm=observer_z_mm,
        radius_mm=radius_mm,
    )
    await websocket.send_json(
        {
            **initial_frame,
            "committed_receipts": [],
            "dispatched_requests": [
                room.coordinator.in_flight_requests[rid].canonical_dict()
                for rid in sorted(room.coordinator.in_flight_requests)
            ],
            "tier_summary": room.tier_summary(),
            "type": "delta_frame",
        }
    )

    try:
        while True:
            msg = await websocket.receive_json()
            if not isinstance(msg, Mapping):
                continue
            msg_type = str(msg.get("type", "step"))

            if "observer_x_mm" in msg:
                observer_x_mm = int(msg["observer_x_mm"])
            if "observer_y_mm" in msg or "observer_z_mm" in msg:
                observer_z_mm = int(msg.get("observer_y_mm", msg.get("observer_z_mm", 0)))
            if "radius_mm" in msg:
                radius_mm = int(msg["radius_mm"])

            if msg_type == "subscribe_aoi":
                frame = _build_aoi_snapshot_frame(
                    room,
                    observer_x_mm=observer_x_mm,
                    observer_y_mm=observer_z_mm,
                    radius_mm=radius_mm,
                )
                await websocket.send_json(
                    {
                        **frame,
                        "tier_summary": room.tier_summary(),
                        "type": "delta_frame",
                    }
                )
                continue

            if msg_type == "checkpoint":
                ckpt = room.flush_epoch_checkpoint()
                saved = repo.save_checkpoint(room, ckpt)
                await websocket.send_json(
                    {
                        "checkpoint": ckpt.canonical_dict(),
                        "profile": saved["profile"],
                        "state_sha256": ckpt.state_sha256,
                        "tick": room.tick,
                        "type": "checkpoint_flushed",
                    }
                )
                continue

            player_actions: list[PlayerActionInput] = []
            tier2_proposals: list[Tier2ProposalInput] = []

            if msg_type in ("player_move", "player_action"):
                player_actions.append(
                    PlayerActionInput(
                        being_id=str(msg["being_id"]),
                        target_x_mm=(
                            None if msg.get("target_x_mm") is None else int(msg["target_x_mm"])
                        ),
                        target_y_mm=(
                            None if msg.get("target_y_mm") is None else int(msg["target_y_mm"])
                        ),
                        target_z_mm=(
                            None if msg.get("target_z_mm") is None else int(msg["target_z_mm"])
                        ),
                        goal_kind=str(msg.get("goal_kind", "walk_to_point")),
                        line=None if msg.get("line") is None else str(msg["line"]),
                    )
                )
            elif msg_type == "tier2_proposal":
                tier2_proposals.append(
                    Tier2ProposalInput(
                        request_id=str(msg["request_id"]),
                        chosen_label=str(msg["chosen_label"]),
                        line=None if msg.get("line") is None else str(msg["line"]),
                        latency_ms=int(msg.get("latency_ms", 0)),
                        model_id=None if msg.get("model_id") is None else str(msg["model_id"]),
                        bridge=None if msg.get("bridge") is None else str(msg["bridge"]),
                        grant_id=None if msg.get("grant_id") is None else str(msg["grant_id"]),
                    )
                )
            else:
                for raw_act in msg.get("player_actions", ()):
                    if isinstance(raw_act, Mapping):
                        player_actions.append(PlayerActionInput(**raw_act))
                for raw_prop in msg.get("tier2_proposals", ()):
                    if isinstance(raw_prop, Mapping):
                        tier2_proposals.append(Tier2ProposalInput(**raw_prop))

            ticks_to_step = int(msg.get("ticks", 1))
            step_res = _execute_room_steps(
                room,
                repo,
                ticks=max(1, min(100, ticks_to_step)),
                tier2_dispatch_limit=int(msg.get("tier2_dispatch_limit", 8)),
                observer_x_mm=observer_x_mm,
                observer_y_mm=observer_z_mm,
                radius_mm=radius_mm,
                player_actions=player_actions,
                tier2_proposals=tier2_proposals,
                flush_checkpoint=bool(msg.get("flush_checkpoint", False)),
            )
            delta_frame = step_res["delta_frame"]
            await websocket.send_json(
                {
                    **delta_frame,
                    "checkpoint": step_res["checkpoint"],
                    "committed_receipts": step_res["committed_receipts"],
                    "dispatched_requests": step_res["dispatched_requests"],
                    "events": step_res["events"],
                    "tier_summary": step_res["tier_summary"],
                    "type": "delta_frame",
                }
            )
    except WebSocketDisconnect:
        return
