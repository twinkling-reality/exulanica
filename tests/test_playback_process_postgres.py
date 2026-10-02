"""The playback process, run as its command, against the application's database as deployed.

A town made through the API plays in ``exulanica-playback-worker``: its minutes advance while the
command runs and the API, which plays nothing itself, reads the process as alive through the lock
it holds (``PlaybackHostLock``); the command stops on a signal with no round left open, and the
lock goes with it. The API reads the lock as the runtime role, which owns nothing and bypasses no
row-level security.
"""

from __future__ import annotations

import dataclasses
import io
import json
import threading
import time
import uuid
from types import MappingProxyType

import pytest
from exulanica.api.installation import installation_facts
from exulanica.api.society_control_worker import (
    PlaybackHostLock,
    PlaybackProcess,
    playback_configuration_sha256,
)
from exulanica.orchestration import playback_worker
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.society_engines import CREATES
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM

import personal_world_support as personal
from test_purge import purged as purged
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

TOWN = CREATES["town"]


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def _every_town_a_test_makes_is_made(monkeypatch):
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in recipe_catalog.world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


class Clock:
    """A monotonic clock a test moves past the API's reading interval."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def later(self) -> None:
        self.now += 60.0


def _presence(database, listed: uuid.UUID, clock: Clock) -> PlaybackProcess:
    return PlaybackProcess(
        database,
        workspaces=(listed,),
        account_discovery=False,
        workspace_source=None,
        base_tick_interval_ms=8000,
        clock=clock,
    )


def test_the_api_reads_a_playback_process_alive_while_it_holds_its_configurations_lock(made):
    api = made
    listed = api.repository.workspace_id
    clock = Clock()
    presence = _presence(api.database, listed, clock)
    assert presence.refusal(listed) == "playback_worker_stopped"
    other = playback_configuration_sha256(
        [listed], account_discovery=False, base_tick_interval_ms=4000
    )
    with PlaybackHostLock(api.database, other):
        clock.later()
        # A process with another configuration plays other things: not this host's playback.
        assert presence.refusal(listed) == "playback_worker_stopped"
    with PlaybackHostLock(api.database, presence.configuration_sha256):
        clock.later()
        assert presence.refusal(listed) is None
        assert presence.refusal(uuid.uuid4()) == "workspace_not_played"
        # Read again only after the interval: what it read stands until then.
    clock.later()
    assert presence.refusal(listed) == "playback_worker_stopped"


def _playing_town(api) -> tuple[dict, str]:
    made = api.post("/worlds/generated", {"recipe": "small_town", "title": "A played town"})
    assert made.status_code == 201, made.text
    entry = made.json()
    scope = f"?world_id={entry['world_id']}"
    society = f"/world/versions/{entry['authored_version_id']}/society"
    created = api.post(society + scope, {"region_id": "region:generated", "profile": TOWN})
    assert created.status_code in (200, 201), created.text
    control = api.get(society + "/control" + scope).json()
    played = api.put(
        society + "/control" + scope,
        {"base_revision": control["revision"], "mode": "playing", "speed": 4},
    )
    assert played.status_code == 200, played.text
    return entry, society + "/control" + scope


def _tick(api, control: str) -> int:
    return api.get(control).json()["current_tick"]


def test_the_playback_command_plays_a_listed_town_and_stops_on_a_signal(
    made, tmp_path, monkeypatch
):
    api = made
    entry, control = _playing_town(api)
    before = _tick(api, control)
    listed = api.repository.workspace_id
    environ = {
        "EXULANICA_DATABASE_URL": api.database.url,
        "EXULANICA_DATA_DIR": str(tmp_path),
        "EXULANICA_API_TOKENS": json.dumps(
            {
                personal.OWNER_TOKEN: {
                    "workspace_id": str(listed),
                    "actor": str(api.actor),
                    "permissions": ["world.read"],
                }
            }
        ),
        "EXULANICA_SOCIETY_CONTROL_WORKSPACES": json.dumps([str(listed)]),
        "EXULANICA_PLAYBACK_WORKER": "process",
    }
    # The throwaway schema keeps no migration ledger, as the API's tests build it unverified.
    monkeypatch.setattr(playback_worker, "verify_schema", lambda _database: None)
    handlers: dict[int, object] = {}
    monkeypatch.setattr(
        playback_worker.signal,
        "signal",
        lambda signum, handler: handlers.setdefault(signum, handler) and None,
    )
    output = io.StringIO()
    exit_codes: list[int] = []
    command = threading.Thread(
        target=lambda: exit_codes.append(playback_worker.main(environ=environ, stream=output))
    )
    command.start()
    clock = Clock()
    presence = _presence(api.database, listed, clock)
    try:
        deadline = time.monotonic() + 60
        while _tick(api, control) == before and time.monotonic() < deadline:
            time.sleep(0.5)
        assert _tick(api, control) > before, output.getvalue()
        clock.later()
        assert presence.refusal(listed) is None
    finally:
        handlers[playback_worker.signal.SIGTERM](playback_worker.signal.SIGTERM, None)
        command.join(60)
    assert exit_codes == [0], output.getvalue()
    events = [json.loads(line)["event"] for line in output.getvalue().splitlines()]
    assert events[0] == "startup" and events[-2:] == ["shutdown_requested", "stopped"]
    clock.later()
    assert presence.refusal(listed) == "playback_worker_stopped"
    stopped_at = _tick(api, control)
    time.sleep(3)
    assert _tick(api, control) == stopped_at
    assert entry["world_id"]


def test_the_playback_command_refuses_an_environment_that_plays_nothing(
    made, tmp_path, monkeypatch
):
    monkeypatch.setattr(playback_worker, "verify_schema", lambda _database: None)
    environ = {
        "EXULANICA_DATABASE_URL": made.database.url,
        "EXULANICA_DATA_DIR": str(tmp_path),
        "EXULANICA_API_TOKENS": json.dumps(
            {
                personal.OWNER_TOKEN: {
                    "workspace_id": str(made.repository.workspace_id),
                    "actor": str(made.actor),
                    "permissions": ["world.read"],
                }
            }
        ),
    }
    for extra, words in (
        ({}, "plays no society"),
        ({"EXULANICA_PLAYBACK_WORKER": "off"}, "EXULANICA_PLAYBACK_WORKER is off"),
    ):
        output = io.StringIO()
        assert playback_worker.main(environ={**environ, **extra}, stream=output) == 1
        refused = json.loads(output.getvalue().splitlines()[-1])
        assert refused["event"] == "startup_failed" and words in refused["message"]


def test_installation_facts_take_simulation_from_the_profile_where_a_process_plays(purged):
    """Played here, simulation is ready; left to a process, it is what the installation's profile
    declares, as a comparison worker of its own is; played by nobody, it advances on request."""
    from test_installation_facts import _by_name, _installation, _services

    def simulation(player: str) -> dict:
        services = _services(
            purged,
            _installation(),
            society_control_workspaces=(uuid.uuid4(),),
            society_runtime=object(),
            playback_player=player,
        )
        return _by_name(installation_facts(services))["simulation"]

    assert simulation("here") == {"component": "simulation", "state": "ready"}
    assert simulation("process")["state"] == "configured"
    assert simulation("none") == {
        "component": "simulation",
        "state": "configured",
        "reason": "advanced_on_request",
    }
