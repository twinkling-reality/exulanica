"""A world serves decision roles and distinguishes a pending signal choice from active control."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.decision_roles import decision_roles
from exulanica.world.generated_worlds import compose_specified_world
from exulanica.world.traffic_episodes import EPISODE, prepared, traffic_input
from exulanica.world.traffic_signal_repository import TrafficSignalRepository

import test_world_traffic_route as traffic
from test_society_made_world import made as imported_made  # noqa: F401

_presets_try_every_candidate = traffic._presets_try_every_candidate
pytestmark = pytest.mark.postgres


def _signalled() -> str:
    for index in range(16):
        world_id = f"world:generated:signal-models-{index}"
        composed = compose_specified_world("small_town", None, world_id)
        value = traffic_input(
            world_id=world_id,
            version_id=composed.receipt_sha256,
            city_identity=composed.receipt["subject_identity"],
            grammar_version=composed.receipt["grammar"]["grammar_version"],
            records=composed.records,
        )
        try:
            ready = prepared(value)
        except UnsupportedNetworkError:
            continue
        if any(junction.signal is not None for junction in ready.network.junctions.values()):
            return world_id
    raise AssertionError("no small town with a drivable signal")


def test_roles_are_served_and_a_choice_stays_pending_until_a_sealed_decision(request, monkeypatch):
    api = request.getfixturevalue("imported_made")
    traffic._identity(monkeypatch, _signalled())
    entry = traffic._made(api, "Signal roles")
    path = f"/world/versions/{entry['authored_version_id']}/models?world_id={entry['world_id']}"
    first = api.get(path)
    assert first.status_code == 200, first.text
    view = first.json()
    assert view["profile"] == "exulanica.world-models/v1"
    roles = {role["key"]: role for role in view["roles"]}
    assert {"society_decision", "junction_signal"} <= roles.keys()
    signal = roles["junction_signal"]
    assert signal["available"] and signal["subjects"]
    assert signal["models"]
    subject = signal["subjects"][0]["signal_id"]
    model = signal["models"][0]
    chosen = api.post(
        path.replace("/models?", "/models/junction_signal?"),
        {
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [subject],
            "model": {"provider": model["provider"], "model_id": model["model_id"]},
        },
    )
    assert chosen.status_code == 200, chosen.text
    after = api.get(path)
    assert after.status_code == 200, after.text
    choice = next(row for row in after.json()["roles"] if row["key"] == "junction_signal")[
        "choices"
    ][0]
    assert choice["subject_id"] == subject
    assert choice["status"] == "pending"
    assert choice["timebase"] == "unix"
    assert choice["active_second"] is None
    assert choice["effective_second"] == chosen.json()["effective_second"]
    controller = api.client.app.state.traffic_signal_controller
    with ThreadPoolExecutor(max_workers=1) as worker:
        controller._pool = worker
        controller._owns_pool = False
        prepared = controller.prepare_world(
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["authored_version_id"]),
        )
        assert prepared > 0
        controller.clock = lambda: choice["effective_second"] + 1
        controller.prepare_world(
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["authored_version_id"]),
        )
        traffic_view = api.get(
            f"/world/versions/{entry['authored_version_id']}/traffic"
            f"?world_id={entry['world_id']}&from_second={choice['effective_second']}&seconds=5"
        )
        assert traffic_view.status_code == 200, traffic_view.text
        [sealed] = traffic_view.json()["sealed_segments"]
        assert sealed["world_id"] == entry["world_id"]
        assert sealed["version_id"] == entry["authored_version_id"]
        assert sealed["start_second"] == choice["effective_second"]
        assert len(sealed["decisions_sha256"]) == 64
        removed = api.post(
            path.replace("/models?", "/models/junction_signal?"),
            {"idempotency_key": str(uuid.uuid4()), "subjects": [subject], "model": None},
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["effective_second"] >= sealed["end_second"]
        replayed = api.get(
            f"/world/versions/{entry['authored_version_id']}/traffic"
            f"?world_id={entry['world_id']}&from_second={choice['effective_second']}&seconds=5"
        )
        assert replayed.status_code == 200, replayed.text
        assert replayed.json()["sealed_segments"] == traffic_view.json()["sealed_segments"]
        assert replayed.json()["vehicles"] == traffic_view.json()["vehicles"]
        final = api.get(path)
        choice = next(row for row in final.json()["roles"] if row["key"] == "junction_signal")[
            "choices"
        ][0]
        assert choice["model"] is None and choice["status"] == "pending"
        assert choice["running_model"] is None


def test_a_choice_interleaved_before_seal_recomputes_that_minute(request, monkeypatch):
    api = request.getfixturevalue("imported_made")
    traffic._identity(monkeypatch, _signalled())
    entry = traffic._made(api, "Interleaved signal")
    version_id = uuid.UUID(entry["authored_version_id"])
    workspace = api.repository.workspace_id
    world_id = entry["world_id"]
    path = f"/world/versions/{version_id}/models?world_id={world_id}"
    # Both choices read one wall second, so a minute boundary passing between them (as on a slow
    # serial run) cannot move the second choice a minute later than the segment it interleaves.
    with api.client.app.state.services.database.session(workspace) as connection:
        now = TrafficSignalRepository(connection, workspace, world_id, version_id).wall_second()
    monkeypatch.setattr(TrafficSignalRepository, "wall_second", lambda _self: now)
    signal = next(role for role in api.get(path).json()["roles"] if role["subject"] == "signal")
    subject = signal["subjects"][0]["signal_id"]
    model = signal["models"][0]
    chosen = api.post(
        path.replace("/models?", "/models/junction_signal?"),
        {
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [subject],
            "model": {"provider": model["provider"], "model_id": model["model_id"]},
        },
    )
    assert chosen.status_code == 200
    effective = chosen.json()["effective_second"]
    controller = api.client.app.state.traffic_signal_controller
    with ThreadPoolExecutor(max_workers=1) as worker:
        controller._pool = worker
        controller._owns_pool = False
        controller.clock = lambda: effective - 61
        controller.prepare_world(workspace, world_id, version_id)
        controller.clock = lambda: effective + 1
        original = TrafficSignalRepository.seal_segment
        interrupted = []

        def interleave(repository, **kwargs):
            start = kwargs["episode"] * EPISODE + kwargs["segment"] * 60
            if start == effective and not interrupted:
                interrupted.append(start)
                with api.client.app.state.services.database.session(workspace) as connection:
                    other = TrafficSignalRepository(connection, workspace, world_id, version_id)
                    removal = other.record_choice(
                        decision_roles().deciding_for("signal"),
                        load_manifest(),
                        request_id=uuid.uuid4(),
                        signal_id=subject,
                        known_signals=[subject],
                        model=None,
                        chosen_by=api.actor,
                    )
                    assert removal["effective_second"] == effective
            return original(repository, **kwargs)

        monkeypatch.setattr(TrafficSignalRepository, "seal_segment", interleave)
        controller.prepare_world(workspace, world_id, version_id)
        assert interrupted == [effective]
        served = api.get(
            f"/world/versions/{version_id}/traffic?world_id={world_id}"
            f"&from_second={effective}&seconds=5"
        )
        assert served.status_code == 200, served.text
        [sealed] = served.json()["sealed_segments"]
        assert sealed["choice_seq"] is None
        assert sealed["start_second"] == effective
