"""End-to-end FastAPI HTTP + WebSocket + PostgreSQL checkpoint persistence tests for Pillar 3."""

from __future__ import annotations

import json
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.routes.realtime_world import get_realtime_room, register_realtime_room
from exulanica.api.services import Services
from exulanica.canonical import canonical_json
from exulanica.store.local import LocalContentAddressedStore
from exulanica.world.realtime_persistence import (
    RealtimeCheckpointRepository,
    clear_in_memory_checkpoints,
    hydrate_room_from_postgres,
    hydrate_room_from_society_state,
)
from exulanica.world.realtime_runtime import (
    EPOCH_CHECKPOINT_PROFILE,
    REALTIME_DECISION_RECEIPT_PROFILE,
    REALTIME_DELTA_FRAME_PROFILE,
    REALTIME_ROOM_STATE_PROFILE,
    AffordancePlace,
)
from exulanica.world.society_sessions import SESSION_OPENED
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

TOKEN = "realtime-test-owner-token-0123456789abcdef"


class _FakeCursor:
    def fetchone(self) -> None:
        return None

    def fetchall(self) -> list[Any]:
        return []


class _FakeConnection:
    @contextmanager
    def transaction(self):
        yield

    def execute(self, *_args: Any, **_kwargs: Any) -> _FakeCursor:
        return _FakeCursor()

    def cursor(self, **_kwargs: Any) -> _FakeConnection:
        return self


class _FakeDatabase:
    """Minimal database session stand-in so FastAPI route tests run fast with or without PG."""

    @contextmanager
    def session(self, _workspace_id: uuid.UUID):
        yield _FakeConnection()

    @contextmanager
    def unscoped(self):
        yield _FakeConnection()


def _build_test_app(tmp_path: Path, workspace_id: uuid.UUID) -> tuple[Any, dict[str, str]]:
    actor_id = uuid.uuid4()
    tokens = load_token_directory(
        {
            "EXULANICA_API_TOKENS": json.dumps(
                {
                    TOKEN: {
                        "actor": str(actor_id),
                        "permissions": ["world.read", "world.write", "model.invoke"],
                        "workspace_id": str(workspace_id),
                    }
                }
            )
        }
    )
    fake_db = _FakeDatabase()
    services = Services(
        database=fake_db,  # type: ignore[arg-type]
        readonly_database=fake_db,  # type: ignore[arg-type]
        store=LocalContentAddressedStore(tmp_path / "blobs"),
        tokens=tokens,
        executor_shares_the_write_role=True,
        model_client=None,
    )
    app = create_app(services, verify=False)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    return app, headers


def test_society_hydration_and_checkpoint_roundtrip_restores_exact_state_sha256() -> None:
    """Hydrating from society state + sessions, flushing a checkpoint, and restoring matches."""
    clear_in_memory_checkpoints()
    workspace_id = uuid.uuid4()
    version_id = str(uuid.uuid4())
    world_id = "sunlit-harbor-world"

    society_state = {
        "branch_id": version_id,
        "inhabitants": [
            {
                "came_by": "populated",
                "id": "person-teo",
                "location": {"node_id": "node-dock", "position_mm": [4_000, 5_000, 0]},
                "name": "Teo (a fisherman)",
            },
            {
                "came_by": "populated",
                "id": "person-ines",
                "location": {"node_id": "node-bench", "position_mm": [5_500, 5_000, 0]},
                "name": "Ines (a baker)",
            },
            {
                "came_by": "crossed",
                "decider": {
                    "bridge": "starlight_bridge",
                    "grant_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "grant-kael")),
                    "kind": "external",
                },
                "id": "visitor-kael",
                "location": {"position_mm": [6_000, 5_200, 0]},
                "name": "Kael (a traveller)",
            },
        ],
        "tick": 3,
    }
    society_input = {
        "navigation": {
            "nodes": [
                {"node_id": "node-dock", "position_mm": [4_000, 5_000, 0]},
                {"node_id": "node-bench", "position_mm": [10_000, 5_000, 0]},
            ]
        },
        "targets": [
            {
                "activity": "resting",
                "capacity": 4,
                "label": "harbor stone bench",
                "place_node_id": "node-bench",
                "target_id": "place-harbor-bench",
            },
            {
                "activity": "watching",
                "capacity": 6,
                "label": "fishing quay",
                "place_node_id": "node-dock",
                "target_id": "place-fishing-quay",
            },
        ],
        "world": {"title": "Sunlit Harbor"},
    }
    assigned_models = {
        "person-teo": {
            "kind": "model",
            "model_id": "nvidia/Nemotron-3-Super-120B",
            "provider": "nebius",
        }
    }
    control_receipts = [
        {
            "ends_by": "2026-10-28T15:00:00+00:00",
            "event_seq": 1,
            "kind": SESSION_OPENED,
            "limits": {
                "calls": 100,
                "decisions": 100,
                "minutes": 60,
                "usd": "5.00000000",
                "wall_seconds": 3600,
            },
            "opened_at": "2026-10-28T14:00:00+00:00",
            "opened_by": str(uuid.uuid4()),
            "reason": "started",
            "request_id": str(uuid.uuid4()),
            "session_id": "sess-001",
            "start_state_sha256": "a" * 64,
            "start_tick": 0,
        }
    ]

    room = hydrate_room_from_society_state(
        world_id=world_id,
        version_id=version_id,
        society_state=society_state,
        society_input=society_input,
        assigned_models=assigned_models,
        control_receipts=control_receipts,
        seed="harbor-seed-01",
        checkpoint_interval_ticks=10,
    )

    assert room.world_title == "Sunlit Harbor"
    assert room.world_minute == 3
    assert set(room.beings) == {"person-teo", "person-ines", "visitor-kael"}
    assert room.beings["person-teo"].decider["kind"] == "model"
    assert room.beings["visitor-kael"].mind_tier_label() == "door_visitor"

    # Step 10 ticks at 20 Hz so an epoch checkpoint is automatically flushed
    for _ in range(10):
        room.step_tick(tier2_dispatch_limit=4)

    assert len(room.checkpoints) == 1
    expected_sha256 = room.state_sha256()

    repo = RealtimeCheckpointRepository(workspace_id)
    saved_record = repo.save_checkpoint(room, room.checkpoints[-1])
    assert saved_record["profile"] == EPOCH_CHECKPOINT_PROFILE
    assert saved_record["state_sha256"] == expected_sha256
    assert len(canonical_json(saved_record)) > 0

    # Restore from the saved checkpoint and verify exact state_sha256 & continuation parity
    restored = repo.restore_room(world_id=world_id, version_id=version_id)
    assert restored is not None
    assert restored.state_sha256() == expected_sha256
    assert restored.tick == room.tick
    assert restored.epoch_seq == room.epoch_seq

    # Stepping both rooms one more tick produces the exact same canonical state_sha256
    room.step_tick(tier2_dispatch_limit=4)
    restored.step_tick(tier2_dispatch_limit=4)
    assert restored.state_sha256() == room.state_sha256()


def test_fastapi_realtime_state_and_step_routes_with_tier2_continuation(tmp_path: Path) -> None:
    """GET /realtime/state and POST /realtime/step step 20 Hz ticks and validate proposals."""
    clear_in_memory_checkpoints()
    workspace_id = uuid.uuid4()
    version_id = uuid.uuid4()
    world_id = "bazaar-world"

    app, headers = _build_test_app(tmp_path, workspace_id)

    room = hydrate_room_from_society_state(
        world_id=world_id,
        version_id=str(version_id),
        generated_places=[
            AffordancePlace(
                place_id="place-fountain",
                label="courtyard fountain",
                kind="fountain",
                x_mm=6_000,
                y_mm=2_000,
                capacity=4,
            ),
            AffordancePlace(
                place_id="place-tea-stall",
                label="tea stall",
                kind="stall",
                x_mm=2_000,
                y_mm=6_000,
                capacity=2,
            ),
        ],
        society_state={
            "inhabitants": [
                {
                    "came_by": "populated",
                    "id": "being-mara",
                    "location": {"position_mm": [1_000, 1_000, 0]},
                    "name": "Mara (a merchant)",
                },
                {
                    "came_by": "populated",
                    "id": "being-sol",
                    "location": {"position_mm": [2_000, 1_000, 0]},
                    "name": "Sol (a scholar)",
                },
            ],
            "tick": 0,
        },
        assigned_models={
            "being-mara": {
                "kind": "model",
                "model_id": "nvidia/Nemotron-3-Super-120B",
                "provider": "nebius",
            },
            "being-sol": {
                "kind": "model",
                "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507",
                "provider": "nebius",
            },
        },
        seed="api-realtime-seed",
        checkpoint_interval_ticks=20,
    )
    register_realtime_room(app, workspace_id, room)

    with TestClient(app) as client:
        # 1. GET /world/versions/{version_id}/realtime/state
        state_res = client.get(
            f"/world/versions/{version_id}/realtime/state",
            params={
                "observer_x_mm": 1_000,
                "observer_z_mm": 1_000,
                "since_tick": 0,
                "world_id": world_id,
            },
            headers=headers,
        )
        assert state_res.status_code == 200, state_res.text
        state_json = state_res.json()
        assert state_json["profile"] == REALTIME_ROOM_STATE_PROFILE
        assert state_json["aoi_frame"]["profile"] == REALTIME_DELTA_FRAME_PROFILE
        assert len(state_json["beings"]) == 2
        assert state_json["state_sha256"] == room.state_sha256()

        # 2. POST /world/versions/{version_id}/realtime/step (advance 5 ticks, dispatch Tier 2 asks)
        step1_res = client.post(
            f"/world/versions/{version_id}/realtime/step",
            params={"world_id": world_id},
            headers=headers,
            json={
                "observer_x_mm": 1_000,
                "observer_z_mm": 1_000,
                "ticks": 5,
                "tier2_dispatch_limit": 8,
            },
        )
        assert step1_res.status_code == 200, step1_res.text
        step1_json = step1_res.json()
        assert step1_json["tick"] == 5
        assert step1_json["ticks_advanced"] == 5
        assert len(step1_json["dispatched_requests"]) == 2

        reqs_by_being = {r["being_id"]: r for r in step1_json["dispatched_requests"]}
        mara_req = reqs_by_being["being-mara"]
        sol_req = reqs_by_being["being-sol"]

        # Mara chooses a valid dialogue option to Sol
        mara_say = next(
            c
            for c in mara_req["offered_choices"]
            if c["kind"] == "say_to" and c["target_id"] == "being-sol"
        )
        # Sol chooses to go to `place-tea-stall`, which we disable to trigger stale_precondition
        sol_go = next(
            c
            for c in sol_req["offered_choices"]
            if c["kind"] == "go_place" and c["target_id"] == "place-tea-stall"
        )
        room.places["place-tea-stall"].enabled = False

        # 3. Submit both Tier 2 proposals + a player action and flush checkpoint at tick 20
        step2_res = client.post(
            f"/world/versions/{version_id}/realtime/step",
            params={"world_id": world_id},
            headers=headers,
            json={
                "flush_checkpoint": True,
                "observer_x_mm": 1_000,
                "observer_z_mm": 1_000,
                "player_actions": [
                    {
                        "being_id": "player-avatar-1",
                        "goal_kind": "walk_to_point",
                        "line": "Hello from the plaza!",
                        "target_x_mm": 3_000,
                        "target_z_mm": 3_000,
                    }
                ],
                "ticks": 15,
                "tier2_proposals": [
                    {
                        "chosen_label": mara_say["label"],
                        "latency_ms": 480,
                        "line": "Good morning Sol, care for some spiced tea?",
                        "model_id": "nvidia/Nemotron-3-Super-120B",
                        "request_id": mara_req["request_id"],
                    },
                    {
                        "chosen_label": sol_go["label"],
                        "latency_ms": 590,
                        "line": None,
                        "model_id": "Qwen/Qwen3-235B-A22B-Instruct-2507",
                        "request_id": sol_req["request_id"],
                    },
                ],
            },
        )
        assert step2_res.status_code == 200, step2_res.text
        step2_json = step2_res.json()
        assert step2_json["tick"] == 20
        assert step2_json["checkpoint"] is not None
        assert step2_json["checkpoint"]["profile"] == EPOCH_CHECKPOINT_PROFILE
        assert step2_json["checkpoint"]["end_tick"] == 20

        receipts = {r["being_id"]: r for r in step2_json["committed_receipts"]}
        assert receipts["being-mara"]["profile"] == REALTIME_DECISION_RECEIPT_PROFILE
        assert receipts["being-mara"]["status"] == "accepted"
        assert receipts["being-mara"]["disposition"] == "applied"
        assert receipts["being-mara"]["reason"] == "validated_choice"

        assert receipts["being-sol"]["status"] == "stale"
        assert receipts["being-sol"]["disposition"] == "stale"
        assert receipts["being-sol"]["reason"] == "stale_precondition"

        # Verify checkpoint round-trip restoration after evicting in-memory room
        saved_sha = step2_json["state_sha256"]
        app.state.realtime_world_rooms.clear()
        assert get_realtime_room(app, workspace_id, version_id) is None

        restored_res = client.get(
            f"/world/versions/{version_id}/realtime/state",
            params={"world_id": world_id},
            headers=headers,
        )
        assert restored_res.status_code == 200, restored_res.text
        assert restored_res.json()["state_sha256"] == saved_sha
        assert restored_res.json()["tick"] == 20


def test_websocket_realtime_stream_20hz_deltas_and_nonblocking_proposals(tmp_path: Path) -> None:
    """WebSocket /realtime/stream emits 20 Hz AOI frames and processes player/Tier 2 inputs."""
    clear_in_memory_checkpoints()
    workspace_id = uuid.uuid4()
    version_id = uuid.uuid4()
    world_id = "ws-stream-world"

    app, headers = _build_test_app(tmp_path, workspace_id)
    room = hydrate_room_from_society_state(
        world_id=world_id,
        version_id=str(version_id),
        society_state={
            "inhabitants": [
                {
                    "came_by": "populated",
                    "id": "being-ws-1",
                    "location": {"position_mm": [2_000, 2_000, 0]},
                    "name": "Aria (a villager)",
                }
            ],
            "tick": 0,
        },
        assigned_models={
            "being-ws-1": {
                "kind": "model",
                "model_id": "nvidia/Nemotron-3-Super-120B",
                "provider": "nebius",
            }
        },
        seed="ws-seed-01",
    )
    register_realtime_room(app, workspace_id, room)

    with (
        TestClient(app) as client,
        client.websocket_connect(
            f"/world/versions/{version_id}/realtime/stream?world_id={world_id}&observer_x_mm=2000&observer_z_mm=2000",
            headers=headers,
        ) as ws,
    ):
        # 1. Initial frame received immediately on connect
        init_msg = ws.receive_json()
        assert init_msg["type"] == "delta_frame"
        assert init_msg["profile"] == REALTIME_DELTA_FRAME_PROFILE
        assert init_msg["tick"] == 0
        assert len(init_msg["entities"]) == 1

        # 2. Step 2 ticks over WebSocket to trigger Tier 2 request dispatch
        ws.send_json({"ticks": 2, "type": "step"})
        step_msg = ws.receive_json()
        assert step_msg["tick"] == 2
        assert len(step_msg["dispatched_requests"]) == 1
        dispatched_req = step_msg["dispatched_requests"][0]

        # 3. Send non-blocking player movement command over WebSocket
        ws.send_json(
            {
                "being_id": "player-ws-hero",
                "line": "Stepping into the stream!",
                "target_x_mm": 2_500,
                "target_z_mm": 2_500,
                "ticks": 3,
                "type": "player_move",
            }
        )
        move_msg = ws.receive_json()
        assert move_msg["tick"] == 5
        entity_ids = {e["being_id"] for e in move_msg["entities"]}
        assert "player-ws-hero" in entity_ids

        # 4. Submit async Tier 2 proposal over WebSocket
        chosen_opt = dispatched_req["offered_choices"][0]
        ws.send_json(
            {
                "chosen_label": chosen_opt["label"],
                "latency_ms": 310,
                "line": "Good to see you!" if chosen_opt["takes_line"] else None,
                "model_id": "nvidia/Nemotron-3-Super-120B",
                "request_id": dispatched_req["request_id"],
                "ticks": 1,
                "type": "tier2_proposal",
            }
        )
        prop_msg = ws.receive_json()
        assert prop_msg["tick"] == 6
        assert len(prop_msg["committed_receipts"]) == 1
        assert prop_msg["committed_receipts"][0]["disposition"] == "applied"

        # 5. Request explicit checkpoint flush over WebSocket
        ws.send_json({"type": "checkpoint"})
        ckpt_msg = ws.receive_json()
        assert ckpt_msg["type"] == "checkpoint_flushed"
        assert ckpt_msg["profile"] == EPOCH_CHECKPOINT_PROFILE
        assert ckpt_msg["tick"] == 6


def test_postgres_hydration_restores_the_process_checkpoint(spine_schema) -> None:
    """A room hydrated from PostgreSQL restores this process's checkpoint, and nothing makes a
    checkpoint table at run time: a table comes from a migration, with grants and an erasure."""
    from pg_harness import open_scratch_connection

    clear_in_memory_checkpoints()
    psycopg_mod, scratch = spine_schema
    workspace_id = uuid.uuid4()
    version_id = uuid.uuid4()
    world_id = "pg-realtime-world"

    conn = open_scratch_connection(psycopg_mod, scratch)
    try:
        conn.execute("select set_config('exulanica.workspace_id', %s, false)", (str(workspace_id),))
        room = hydrate_room_from_society_state(
            world_id=world_id,
            version_id=str(version_id),
            seed="pg-persistence-seed",
            checkpoint_interval_ticks=10,
        )
        for _ in range(10):
            room.step_tick(tier2_dispatch_limit=4)

        expected_sha = room.state_sha256()
        repo = RealtimeCheckpointRepository(workspace_id)
        repo.save_checkpoint(room, room.checkpoints[-1])

        restored = hydrate_room_from_postgres(
            conn,
            workspace_id,
            version_id=version_id,
            world_id=world_id,
            prefer_checkpoint=True,
        )
        assert restored.state_sha256() == expected_sha
        assert restored.tick == 10
        assert restored.epoch_seq == 1
        table = conn.execute("select to_regclass('world_realtime_checkpoint')").fetchone()
        assert table is not None and table[0] is None
    finally:
        conn.close()


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer not-a-configured-token"}])
def test_websocket_realtime_stream_refuses_a_caller_without_a_held_token(
    tmp_path: Path, headers: dict[str, str]
) -> None:
    """The stream answers only a bearer token the installation holds: never a workspace named in the
    address, nor the workspace of a room already open at the version."""
    clear_in_memory_checkpoints()
    workspace_id = uuid.uuid4()
    version_id = uuid.uuid4()
    world_id = "ws-refused-world"
    app, _held = _build_test_app(tmp_path, workspace_id)
    room = hydrate_room_from_society_state(
        world_id=world_id, version_id=str(version_id), seed="ws-refused-seed"
    )
    register_realtime_room(app, workspace_id, room)

    with TestClient(app) as client:
        with (
            pytest.raises(WebSocketDisconnect) as refused,
            client.websocket_connect(
                f"/world/versions/{version_id}/realtime/stream"
                f"?world_id={world_id}&workspace_id={workspace_id}",
                headers=headers,
            ) as ws,
        ):
            ws.receive_json()
        assert refused.value.code == 1008
