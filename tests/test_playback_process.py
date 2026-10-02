"""A host's societies played in a process of its own (``EXULANICA_PLAYBACK_WORKER=process``).

The API that leaves playback to a process starts neither the playback worker nor the traffic
signal controller's loop, says in readiness where playback runs, and answers each world's
playback from what it reads of that process. No database: the process's lock is read by the
PostgreSQL tests (``tests/test_playback_process_postgres.py``).
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from types import SimpleNamespace

import pytest
from exulanica.api.app import _lifespan
from exulanica.api.routes.health import _society_check
from exulanica.api.services import Services, SocietySettingRefused, _playback_player
from exulanica.api.society_control_worker import (
    PlaybackProcess,
    host_playback_refusal,
    playback_configuration_sha256,
)
from exulanica.api.traffic_signal_controller import TrafficSignalController
from starlette.requests import Request

from test_account_control_integration import services


def test_who_plays_societies_is_named_or_startup_refuses():
    spelled = (None, "", " on ", "TRUE", "process", " Process ", "OFF", "0", "no")
    assert [_playback_player(value) for value in spelled] == [
        "here",
        "here",
        "here",
        "here",
        "process",
        "process",
        "none",
        "none",
        "none",
    ]
    with pytest.raises(SocietySettingRefused) as refused:
        _playback_player("elsewhere")
    assert refused.value.code == "playback_worker_not_recognised"


@pytest.mark.parametrize(
    ("player", "plays_here", "seals_traffic_here"),
    [("here", True, True), ("process", False, False), ("none", False, True)],
)
def test_the_api_plays_and_seals_only_where_the_setting_says(
    monkeypatch, tmp_path, player, plays_here, seals_traffic_here
):
    """``process`` leaves the playback worker and the traffic loop to the playback process;
    ``none`` plays nothing and still seals the traffic a society advanced by hand needs."""
    ran, sealed = threading.Event(), threading.Event()

    class Worker:
        def run(self, stop):
            ran.set()
            stop.wait()

    monkeypatch.setattr(Services, "build_society_control_worker", lambda _: Worker())
    monkeypatch.setattr(TrafficSignalController, "start", lambda _self: sealed.set())
    monkeypatch.setattr(TrafficSignalController, "close", lambda _self: None)
    monkeypatch.setattr("exulanica.api.app.verify_restore", lambda *_: None)
    monkeypatch.setattr("exulanica.api.app.seed_reviewed_assets", lambda *_: None)
    configured = services(
        tmp_path, society_control_workspaces=(uuid.uuid4(),), playback_player=player
    )
    app = SimpleNamespace(state=SimpleNamespace(services=configured, verify_schema_at_boot=False))

    async def scenario():
        context = _lifespan(app)
        await context.__aenter__()
        await asyncio.to_thread(ran.wait, 0.5)
        await context.__aexit__(None, None, None)

    asyncio.run(scenario())
    assert ran.is_set() is plays_here
    assert sealed.is_set() is seals_traffic_here
    assert (app.state.society_control_thread is not None) is plays_here
    assert (app.state.playback_process is not None) is (player == "process")


def test_readiness_says_where_playback_runs_and_whether_its_process_lives(tmp_path):
    configured = services(
        tmp_path, society_control_workspaces=(uuid.uuid4(),), playback_player="process"
    )
    process = SimpleNamespace(alive=False)
    state = SimpleNamespace(
        playback_process=process, society_control_worker=None, society_control_thread=None
    )
    request = Request({"type": "http", "app": SimpleNamespace(state=state)})
    report = _society_check(request, configured)
    assert (report["ok"], report["running"], report["played_by"]) == (True, False, "process")
    assert report["process_alive"] is False
    process.alive = True
    assert _society_check(request, configured)["process_alive"] is True
    unplayed = services(
        tmp_path, society_control_workspaces=(uuid.uuid4(),), playback_player="none"
    )
    nobody = _society_check(request, unplayed)
    assert (nobody["ok"], nobody["running"], nobody["played_by"]) == (True, False, "none")
    assert "process_alive" not in nobody


def test_a_world_is_played_when_the_process_that_plays_it_says_so():
    listed, other = uuid.uuid4(), uuid.uuid4()
    stopped = SimpleNamespace(refusal=lambda workspace: "playback_worker_stopped")
    assert host_playback_refusal(None, None, listed, stopped) == "playback_worker_stopped"
    playing = SimpleNamespace(
        refusal=lambda workspace: None if workspace == listed else "workspace_not_played"
    )
    assert host_playback_refusal(None, None, listed, playing) is None
    assert host_playback_refusal(None, None, other, playing) == "workspace_not_played"
    assert host_playback_refusal(None, None, listed) == "no_playback_worker"


def test_a_playback_configuration_is_named_by_what_it_plays():
    first, second = uuid.uuid4(), uuid.uuid4()
    named = playback_configuration_sha256(
        [first, second], account_discovery=False, base_tick_interval_ms=8000
    )
    assert named == playback_configuration_sha256(
        [second, first], account_discovery=False, base_tick_interval_ms=8000
    )
    for changed in (
        playback_configuration_sha256([first], account_discovery=False, base_tick_interval_ms=8000),
        playback_configuration_sha256(
            [first, second], account_discovery=True, base_tick_interval_ms=8000
        ),
        playback_configuration_sha256(
            [first, second], account_discovery=False, base_tick_interval_ms=4000
        ),
    ):
        assert changed != named


def test_the_api_reads_the_process_it_leaves_playback_to_by_its_own_configuration(tmp_path):
    listed = uuid.uuid4()
    configured = services(
        tmp_path,
        society_control_workspaces=(listed,),
        playback_player="process",
        society_base_tick_interval_ms=4000,
    )
    process = configured.playback_process()
    assert isinstance(process, PlaybackProcess)
    assert process.configuration_sha256 == configured.playback_configuration_sha256()
    assert process.configuration_sha256 == playback_configuration_sha256(
        [listed], account_discovery=False, base_tick_interval_ms=4000
    )
    assert services(tmp_path, society_control_workspaces=(listed,)).playback_process() is None
    assert services(tmp_path, playback_player="process").playback_process() is None
