"""A signal choice and its one bounded answer stay in their world and version."""

from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import seal
from exulanica.world.traffic_signal_repository import (
    SignalChoiceRefused,
    TrafficSignalRepository,
)

import test_society_stay_requests_api as stays

app = stays.app
saved_world = stays.saved_world
pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_choice_reservation_and_receipt_are_idempotent_and_bound_to_the_point(app):
    world, client = app
    services = client.app.state.services
    role = decision_roles().role("junction_signal")
    manifest = load_manifest()
    spec = next(
        spec
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    )
    mechanism = role.contract().mechanism_for(spec)
    assert mechanism is not None
    signal_id = "signal:fixture-junction"
    version_id = world["binding"].version_id
    with services.database.session(world["workspace"]) as connection:
        repository = TrafficSignalRepository(
            connection, world["workspace"], world["binding"].world_id, version_id
        )
        key = uuid.uuid4()
        choice = repository.record_choice(
            role,
            manifest,
            request_id=key,
            signal_id=signal_id,
            known_signals=[signal_id],
            model={"provider": spec.provider, "model_id": spec.model_id},
            chosen_by=world["session"].actor,
        )
        assert choice["effective_second"] % 60 == 0
        assert (
            repository.record_choice(
                role,
                manifest,
                request_id=key,
                signal_id=signal_id,
                known_signals=[signal_id],
                model={"provider": spec.provider, "model_id": spec.model_id},
                chosen_by=world["session"].actor,
            )["document_sha256"]
            == choice["document_sha256"]
        )
        held = repository.current_choices()[signal_id]
        assert held["choice_seq"] == choice["choice_seq"]
        point = choice["effective_second"] + 24
        reservation = repository.reserve_point(
            role,
            roads_version="a" * 64,
            episode=point // 1200,
            segment=(point % 1200) // 60,
            choice=held,
            choice_second=point,
            state_sha256="b" * 64,
            observation={
                "active_near": 1,
                "other_near": 0,
                "active_queue": 0,
                "other_queue": 0,
                "active_wait_seconds": 0,
                "other_wait_seconds": 0,
                "near_vehicle_count": 1,
                "green_elapsed_seconds": 24,
            },
            manifest_sha256="c" * 64,
            mechanism=mechanism.value,
        )
        assert reservation is not None
        assert (
            repository.reserve_point(
                role,
                roads_version="a" * 64,
                episode=point // 1200,
                segment=(point % 1200) // 60,
                choice=held,
                choice_second=point,
                state_sha256="b" * 64,
                observation={"near_vehicle_count": 1},
                manifest_sha256="c" * 64,
                mechanism=mechanism.value,
            )["request"]
            == reservation["request"]
        )
        with pytest.raises(SignalChoiceRefused, match="point_changed_after_reservation"):
            repository.reserve_point(
                role,
                roads_version="a" * 64,
                episode=point // 1200,
                segment=(point % 1200) // 60,
                choice=held,
                choice_second=point,
                state_sha256="d" * 64,
                observation={"near_vehicle_count": 1},
                manifest_sha256="c" * 64,
                mechanism=mechanism.value,
            )
        receipt = repository.record_result(
            role,
            uuid.UUID(reservation["request"]["request_id"]),
            {
                "status": "unavailable",
                "reason": "provider_credential_absent",
                "proposal": None,
                "provider": None,
            },
        )
        assert receipt["request_sha256"] == reservation["request"]["document_sha256"]
        with pytest.raises(SignalChoiceRefused, match="duplicate_answer"):
            repository.record_result(
                role,
                uuid.UUID(reservation["request"]["request_id"]),
                {
                    "status": "unavailable",
                    "reason": "provider_credential_absent",
                    "proposal": None,
                    "provider": None,
                },
            )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_world_hour_reservations_are_shared_across_versions_and_concurrent(app):
    world, client = app
    services = client.app.state.services
    role = decision_roles().deciding_for("signal")
    manifest = load_manifest()
    spec = next(
        spec
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    )
    mechanism = role.contract().mechanism_for(spec)
    assert mechanism is not None
    first = world["binding"].version_id
    second = uuid.uuid4()
    world_id = world["binding"].world_id
    workspace = world["workspace"]
    owner = world["connection"]
    owner.execute(
        "insert into world_alternate_version(version_id,workspace_id,world_id,"
        "source_snapshot_id,parent_version_id,title,origin,style_version_id,"
        "state_sha256,edit_seq,created_by) select %s,workspace_id,world_id,"
        "source_snapshot_id,version_id,%s,origin,style_version_id,state_sha256,"
        "edit_seq,created_by from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (second, "Budget sibling", workspace, world_id, first),
    )
    owner.commit()
    choices = {}
    for version in (first, second):
        with services.database.session(workspace) as connection:
            repository = TrafficSignalRepository(connection, workspace, world_id, version)
            choice = repository.record_choice(
                role,
                manifest,
                request_id=uuid.uuid4(),
                signal_id="signal:budget",
                known_signals=["signal:budget"],
                model={"provider": spec.provider, "model_id": spec.model_id},
                chosen_by=world["session"].actor,
            )
            choices[version] = (
                repository.current_choices()["signal:budget"],
                choice["effective_second"] + 24,
            )

    barrier = Barrier(2)

    def reserve(version):
        choice, point = choices[version]
        barrier.wait(5)
        with services.database.session(workspace) as connection:
            repository = TrafficSignalRepository(connection, workspace, world_id, version)
            return repository.reserve_point(
                role,
                roads_version="a" * 64,
                episode=point // 1200,
                segment=(point % 1200) // 60,
                choice=choice,
                choice_second=point,
                state_sha256="b" * 64,
                observation={
                    "active_near": 1,
                    "other_near": 0,
                    "active_queue": 0,
                    "other_queue": 0,
                    "active_wait_seconds": 0,
                    "other_wait_seconds": 0,
                    "near_vehicle_count": 1,
                    "green_elapsed_seconds": 24,
                },
                manifest_sha256="c" * 64,
                mechanism=mechanism.value,
                budget_bound_usd=Decimal("0.06"),
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result()
            for future in (pool.submit(reserve, first), pool.submit(reserve, second))
        ]
    assert sorted(row["budget_refusal"] or "admitted" for row in results) == [
        "admitted",
        "world_hour_spend_spent",
    ]
    with services.database.session(workspace) as connection:
        assert TrafficSignalRepository(connection, workspace, world_id, first).world_hour() == (
            1,
            Decimal("0.06"),
        )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("superseded", [False, True])
def test_a_restart_seals_an_unanswered_request_with_a_named_fallback(app, superseded):
    world, client = app
    services = client.app.state.services
    role = decision_roles().deciding_for("signal")
    manifest = load_manifest()
    spec = next(
        spec
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    )
    mechanism = role.contract().mechanism_for(spec)
    assert mechanism is not None
    version = world["binding"].version_id
    workspace = world["workspace"]
    world_id = world["binding"].world_id
    with services.database.session(workspace) as connection:
        repository = TrafficSignalRepository(connection, workspace, world_id, version)
        chosen = repository.record_choice(
            role,
            manifest,
            request_id=uuid.uuid4(),
            signal_id="signal:expired",
            known_signals=["signal:expired"],
            model={"provider": spec.provider, "model_id": spec.model_id},
            chosen_by=world["session"].actor,
        )
        point = chosen["effective_second"] + (144 if superseded else 24)
        episode, local = divmod(point, 1200)
        target_segment = local // 60
        reservation = repository.reserve_point(
            role,
            roads_version="a" * 64,
            episode=episode,
            segment=target_segment,
            choice=repository.current_choices()["signal:expired"],
            choice_second=point,
            state_sha256="b" * 64,
            observation={
                "active_near": 1,
                "other_near": 0,
                "active_queue": 0,
                "other_queue": 0,
                "active_wait_seconds": 0,
                "other_wait_seconds": 0,
                "near_vehicle_count": 1,
                "green_elapsed_seconds": 24,
            },
            manifest_sha256="c" * 64,
            mechanism=mechanism.value,
        )
        assert reservation is not None
        request_id = uuid.UUID(reservation["request"]["request_id"])
        if superseded:
            removed = repository.record_choice(
                role,
                manifest,
                request_id=uuid.uuid4(),
                signal_id="signal:expired",
                known_signals=["signal:expired"],
                model=None,
                chosen_by=world["session"].actor,
            )
            assert removed["effective_second"] <= point - 24
    if not superseded:
        time.sleep(5.1)
    with services.database.session(workspace) as connection:
        repository = TrafficSignalRepository(connection, workspace, world_id, version)
        for segment in range(target_segment + 1):
            local_start = segment * 60
            absolute_start = episode * 1200 + local_start
            generations = {
                signal: row["choice_seq"]
                for signal, row in repository.choices_at(absolute_start).items()
            }
            choices = (
                {"signal:expired": {str(local): "switch"}}
                if segment == target_segment and not superseded
                else {}
            )
            continuation = seal(
                {
                    "profile": "exulanica.traffic-continuation/v1",
                    "input_sha256": "d" * 64,
                    "episode": episode,
                    "next_second": local_start + 60,
                    "state": {"second": local_start + 59},
                    "signal_choices": choices,
                    "initial_signal_cursors": {},
                }
            )
            repository.seal_segment(
                role=role,
                roads_version="a" * 64,
                input_sha256="d" * 64,
                episode=episode,
                segment=segment,
                states=[{"second": second} for second in range(local_start, local_start + 60)],
                continuation=continuation,
                selected_generations=generations,
            )
        receipt = repository.decision_for(request_id)
        assert receipt is not None
        assert receipt["status"] == "unavailable"
        assert receipt["reason"] == ("point_stale" if superseded else "unanswered_in_its_minute")
        assert repository.latest_segment(episode)["segment"] == target_segment
