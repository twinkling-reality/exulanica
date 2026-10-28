"""Tests and 256-agent benchmark for the 20 Hz real-time spatial room & 3-tier mind runtime."""

from __future__ import annotations

import statistics
import time
import uuid

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.world.crossings import ARRIVAL_PROFILE, Crossing
from exulanica.world.realtime_runtime import (
    DEFAULT_AOI_RADIUS_MM,
    EPOCH_CHECKPOINT_PROFILE,
    MAX_CONCURRENT_BEINGS,
    REALTIME_DECISION_RECEIPT_PROFILE,
    REALTIME_DELTA_FRAME_PROFILE,
    TICK_DURATION_MS,
    TICK_HZ,
    AffordancePlace,
    RealtimeWorldRoom,
    Tier2Proposal,
)


def _populate_256_agent_room(
    *,
    seed: str = "exulanica-256-benchmark",
    checkpoint_interval_ticks: int = 100,
) -> RealtimeWorldRoom:
    room = RealtimeWorldRoom(
        world_id="world-256-town",
        version_id="ver-256-001",
        world_title="Sunlit Bazaar",
        seed=seed,
        checkpoint_interval_ticks=checkpoint_interval_ticks,
    )

    # Create 32 town places spread across a 128m x 128m town grid
    for idx in range(32):
        gx = (idx % 8) * 16_000 + 4_000
        gy = (idx // 8) * 16_000 + 4_000
        room.add_place(
            AffordancePlace(
                place_id=f"place-{idx:02d}",
                label=f"market stall {idx + 1}",
                kind="stall",
                x_mm=gx,
                y_mm=gy,
                z_mm=0,
                capacity=12,
            )
        )

    # Populate 256 concurrent beings across human players, open models, Door bridges, and routines
    for i in range(MAX_CONCURRENT_BEINGS):
        row = i // 16
        col = i % 16
        x_mm = col * 8_000 + (i % 5) * 250
        y_mm = row * 8_000 + (i % 7) * 250
        if i < 64:
            decider = {
                "kind": "model",
                "model_id": "nvidia/Nemotron-3-Super-120B",
                "provider": "nebius",
            }
            came_by = "populated"
        elif i < 96:
            grant_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"grant-{i}"))
            decider = {
                "bridge": "open_arena_bridge",
                "grant_id": grant_uuid,
                "kind": "external",
            }
            came_by = "crossed"
        elif i < 128:
            account_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"player-{i}"))
            decider = {
                "account_id": account_uuid,
                "kind": "person",
            }
            came_by = "placed"
        else:
            decider = {"kind": "routine"}
            came_by = "populated"

        room.add_being(
            being_id=f"being-{i:03d}",
            label=f"inhabitant {i + 1}",
            came_by=came_by,
            decider=decider,
            x_mm=x_mm,
            y_mm=y_mm,
            z_mm=0,
        )

    return room


def test_256_concurrent_beings_20hz_aoi_and_deterministic_checkpoints() -> None:
    """256 concurrent beings step at 20 Hz (< 2 ms/tick) with identical deterministic digests."""
    assert TICK_HZ == 20
    assert TICK_DURATION_MS == 50

    room_a = _populate_256_agent_room(
        seed="deterministic-seed-alpha", checkpoint_interval_ticks=100
    )
    room_b = _populate_256_agent_room(
        seed="deterministic-seed-alpha", checkpoint_interval_ticks=100
    )

    assert len(room_a.beings) == 256
    assert room_a.state_sha256() == room_b.state_sha256()

    tick_durations_ms: list[float] = []
    last_result_a = None

    for _ in range(100):
        t0 = time.perf_counter()
        res_a = room_a.step_tick(tier2_dispatch_limit=8)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        tick_durations_ms.append(elapsed_ms)
        last_result_a = res_a

        res_b = room_b.step_tick(tier2_dispatch_limit=8)
        assert res_a.changed_entity_count == res_b.changed_entity_count

    assert last_result_a is not None
    assert last_result_a.checkpoint is not None
    assert last_result_a.checkpoint.canonical_dict()["profile"] == EPOCH_CHECKPOINT_PROFILE
    assert last_result_a.checkpoint.epoch_seq == 1
    assert last_result_a.checkpoint.start_tick == 0
    assert last_result_a.checkpoint.end_tick == 100

    # Verify zero-float canonical digest parity across both independent runs
    assert room_a.state_sha256() == room_b.state_sha256()
    assert room_a.checkpoints[-1].checkpoint_sha256 == room_b.checkpoints[-1].checkpoint_sha256

    # Verify AOI delta frame filtering returns only nearby entities in canonical format
    aoi_frame = room_a.aoi_delta_frame(
        last_result_a,
        observer_x_mm=16_000,
        observer_y_mm=16_000,
        radius_mm=DEFAULT_AOI_RADIUS_MM,
    )
    assert aoi_frame["profile"] == REALTIME_DELTA_FRAME_PROFILE
    assert aoi_frame["tick"] == 100
    assert 0 < len(aoi_frame["deltas"]) < 256
    # Ensure canonical_json accepts the AOI frame and checkpoint without any float errors
    assert len(canonical_json(aoi_frame)) > 0
    assert len(canonical_json(last_result_a.checkpoint.canonical_dict())) > 0

    median_ms = statistics.median(tick_durations_ms)
    mean_ms = statistics.mean(tick_durations_ms)
    assert median_ms < 2.0, f"Expected < 2.0 ms/tick median, measured {median_ms:.3f} ms"
    assert mean_ms < 2.0, f"Expected < 2.0 ms/tick mean, measured {mean_ms:.3f} ms"


def test_async_tier2_proposals_accepted_and_stale_precondition_without_stalling() -> None:
    """Async Tier 2 proposals resolve across ticks with applied and stale_precondition receipts."""
    room = RealtimeWorldRoom(
        world_id="world-async-test",
        version_id="ver-async-001",
        world_title="Harbor Square",
        seed="tier2-async-seed",
        checkpoint_interval_ticks=50,
    )

    bench = AffordancePlace(
        place_id="place-bench-1",
        label="stone bench",
        kind="bench",
        x_mm=5_000,
        y_mm=0,
        capacity=1,
    )
    well = AffordancePlace(
        place_id="place-well-1",
        label="town well",
        kind="well",
        x_mm=0,
        y_mm=6_000,
        capacity=4,
    )
    room.add_place(bench)
    room.add_place(well)

    alice = room.add_being(
        being_id="being-alice",
        label="Alice (a villager)",
        came_by="populated",
        decider={
            "kind": "model",
            "model_id": "nvidia/Nemotron-3-Super-120B",
            "provider": "nebius",
        },
        x_mm=0,
        y_mm=0,
    )
    bob = room.add_being(
        being_id="being-bob",
        label="Bob (a villager)",
        came_by="populated",
        decider={
            "kind": "model",
            "model_id": "nvidia/Nemotron-3-Super-120B",
            "provider": "nebius",
        },
        x_mm=1_000,
        y_mm=0,
    )

    # Tick 1: Both Alice and Bob dispatch non-blocking Tier 2 requests while Tier 1 moves them
    tick1 = room.step_tick(tier2_dispatch_limit=8)
    assert len(tick1.dispatched_requests) == 2
    req_by_being = {req.being_id: req for req in tick1.dispatched_requests}
    alice_req = req_by_being["being-alice"]
    bob_req = req_by_being["being-bob"]

    # Simulate 10 spatial ticks (500 ms) passing while the 120B open model is thinking.
    # Verify Tier 0/1 keeps Alice and Bob moving smoothly at 20 Hz without stalling!
    alice_pos_tick1 = (alice.x_mm, alice.y_mm)
    for _ in range(10):
        step_res = room.step_tick(tier2_dispatch_limit=8)
        assert step_res.changed_entity_count >= 1
    assert (alice.x_mm, alice.y_mm) != alice_pos_tick1

    # Find Alice's offered choice to speak to Bob (which is still valid because Bob is within 8m)
    say_choice = next(
        c for c in alice_req.offered_choices if c.kind == "say_to" and c.target_id == "being-bob"
    )
    room.coordinator.queue_proposal(
        Tier2Proposal(
            request_id=alice_req.request_id,
            chosen_label=say_choice.label,
            line="Morning! The harbor wind is brisk today.",
            latency_ms=550,
            model_id="nvidia/Nemotron-3-Super-120B",
        )
    )

    # For Bob, find his offered choice to go to `place-bench-1`, but disable the bench before commit
    # so the world moves on and triggers `stale_precondition`!
    bench_choice = next(
        c
        for c in bob_req.offered_choices
        if c.kind == "go_place" and c.target_id == "place-bench-1"
    )
    bench.enabled = False
    room.coordinator.queue_proposal(
        Tier2Proposal(
            request_id=bob_req.request_id,
            chosen_label=bench_choice.label,
            line=None,
            latency_ms=620,
            model_id="nvidia/Nemotron-3-Super-120B",
        )
    )

    # Next tick resolves both proposals without blocking the 20 Hz loop
    tick12 = room.step_tick(tier2_dispatch_limit=8)
    assert len(tick12.committed_receipts) == 2
    receipts_by_being = {r.being_id: r for r in tick12.committed_receipts}

    alice_receipt = receipts_by_being["being-alice"]
    assert alice_receipt.profile if hasattr(alice_receipt, "profile") else True
    assert alice_receipt.canonical_dict()["profile"] == REALTIME_DECISION_RECEIPT_PROFILE
    assert alice_receipt.status == "accepted"
    assert alice_receipt.disposition == "applied"
    assert alice_receipt.reason == "validated_choice"
    assert alice_receipt.base_tick == 1
    assert alice_receipt.consumed_tick == 12
    assert alice.last_line == "Morning! The harbor wind is brisk today."
    assert "Morning! The harbor wind is brisk today." in bob.heard_lines

    bob_receipt = receipts_by_being["being-bob"]
    assert bob_receipt.status == "stale"
    assert bob_receipt.disposition == "stale"
    assert bob_receipt.reason == "stale_precondition"
    assert bob_receipt.proposal is None


def test_cross_world_door_visitor_admission_into_live_20hz_loop() -> None:
    """A Door visitor crosses with a verified translation manifest and steps in the 20 Hz room."""
    room = RealtimeWorldRoom(
        world_id="world-door-test",
        version_id="ver-door-001",
        world_title="Lantern Crossing",
        seed="door-crossing-seed",
        checkpoint_interval_ticks=10,
    )
    room.add_place(
        AffordancePlace(
            place_id="place-gate-plaza",
            label="gate plaza",
            kind="plaza",
            x_mm=4_000,
            y_mm=4_000,
        )
    )

    arrival_id = str(uuid.uuid4())
    grant_id = str(uuid.uuid4())
    visitor_thing_id = str(
        uuid.uuid5(
            uuid.UUID("8f1d6a52-3c47-5e09-b4a8-1e7c2d90f6b3"),
            f"{grant_id}:arrival:{arrival_id}",
        )
    )
    lantern_thing_id = str(
        uuid.uuid5(
            uuid.UUID("8f1d6a52-3c47-5e09-b4a8-1e7c2d90f6b3"),
            f"{grant_id}:arrival:{arrival_id}:0:0",
        )
    )

    source_payload = {
        "cyber_scout": "character",
        "plasma_torch": 1,
        "combat_shield_hp": 250,
    }
    source_sha = sha256_of_canonical(source_payload).hex()
    kind_ref = {
        "kind": "traveller",
        "sha256": "a" * 64,
        "version": 1,
    }
    manifest_raw = {
        "fields": [
            {
                "disposition": "approximated",
                "path": "/cyber_scout",
                "reason": "Arrives as a wayfaring traveller in this peaceful lantern town.",
                "to": "/kind",
                "words": "A cyber scout, arriving as a traveller",
            },
            {
                "disposition": "approximated",
                "path": "/plasma_torch",
                "reason": "A plasma torch arrives as a warm brass lantern.",
                "to": "/carried/0",
                "words": "A plasma torch, arriving as a lantern",
            },
            {
                "disposition": "dropped",
                "path": "/combat_shield_hp",
                "reason": "This world has no combat shield health.",
                "to": None,
                "words": "Combat shield points stay behind",
            },
        ],
        "profile": "exulanica.translation-manifest/v2",
        "source": {
            "format": "starlight-arena",
            "sha256": source_sha,
            "type": "cyber-scout",
        },
        "target": {
            "kind": kind_ref,
            "look": None,
        },
        "translator": {
            "key": "starlight-arena",
            "sha256": "b" * 64,
            "version": 1,
        },
    }
    manifest_sha = sha256_of_canonical(manifest_raw).hex()

    arrival_doc = {
        "arrival_id": arrival_id,
        "carried": [
            {
                "kind": {
                    "kind": "lantern",
                    "sha256": "c" * 64,
                    "version": 1,
                },
                "thing_id": lantern_thing_id,
            }
        ],
        "decided_by": "program",
        "gate": "north-arch",
        "grant_id": grant_id,
        "kind": kind_ref,
        "may_carry_out": True,
        "origin": {
            "authors": ["Starlight Bridge"],
            "by": {
                "adapter_version": "1.0.0",
                "bridge": "starlight_bridge",
                "grant_id": grant_id,
                "kind": "program",
                "mapping_sha256": "b" * 64,
            },
            "class": "crossed",
            "distribution": "public",
            "licence": {
                "attribution": "Starlight Bridge",
                "licence_text_sha256": None,
                "licence_url": "https://creativecommons.org/licenses/by/4.0/",
                "share_alike": False,
                "spdx": "CC-BY-4.0",
                "verdict": "SHIP-ATTRIB",
            },
            "lineage": {
                "ingredients": [],
                "receipts": [],
                "translation_manifest_sha256": manifest_sha,
            },
            "profile": "exulanica.origin/v1",
            "sources": [],
        },
        "profile": ARRIVAL_PROFILE,
        "thing_id": visitor_thing_id,
        "translation_manifest_sha256": manifest_sha,
    }

    crossing = Crossing(crossing_id=uuid.UUID(arrival_id), document=arrival_doc)
    visitor = room.admit_door_arrival(
        crossing,
        manifest_raw=manifest_raw,
        source_payload=source_payload,
        spawn_x_mm=1_000,
        spawn_y_mm=1_000,
        label="Kael (a traveller)",
    )

    assert visitor.being_id == visitor_thing_id
    assert visitor.came_by == "crossed"
    assert visitor.decider == {
        "bridge": "starlight_bridge",
        "grant_id": grant_id,
        "kind": "external",
    }
    assert visitor.carried_ids == [lantern_thing_id]
    assert visitor.translation_manifest_sha256 == manifest_sha

    # Step 10 ticks at 20 Hz: the Door visitor gets an external Tier 2 ask and walks via Tier 0/1
    first_tick = room.step_tick(tier2_dispatch_limit=4)
    assert len(first_tick.dispatched_requests) == 1
    door_req = first_tick.dispatched_requests[0]
    assert door_req.being_id == visitor_thing_id

    go_plaza = next(c for c in door_req.offered_choices if c.kind == "go_place")
    room.coordinator.queue_proposal(
        Tier2Proposal(
            request_id=door_req.request_id,
            chosen_label=go_plaza.label,
            latency_ms=120,
            bridge="starlight_bridge",
            grant_id=grant_id,
        )
    )

    for _ in range(9):
        room.step_tick(tier2_dispatch_limit=4)

    # At tick 10, an epoch checkpoint is flushed containing both the bound crossing and receipt
    assert len(room.checkpoints) == 1
    ckpt = room.checkpoints[0]
    assert len(ckpt.crossings_bound) == 1
    assert ckpt.crossings_bound[0]["arrival_id"] == arrival_id
    assert len(ckpt.receipt_batch) == 1
    assert ckpt.receipt_batch[0]["being_id"] == visitor_thing_id
    assert ckpt.receipt_batch[0]["disposition"] == "applied"


def test_no_floats_rejected_in_realtime_room() -> None:
    """Attempting to construct a being with float coordinates raises TypeError immediately."""
    room = RealtimeWorldRoom(world_id="w1", version_id="v1")
    with pytest.raises(TypeError):
        room.add_being(
            being_id="float-being",
            label="bad float",
            x_mm=100.5,  # type: ignore[arg-type]
            y_mm=0,
        )
    # Also verify canonical_json rejects floats if someone mutates state
    state = room.canonical_state()
    state["bad_float"] = 0.5
    with pytest.raises(CanonicalisationError):
        canonical_json(state)
