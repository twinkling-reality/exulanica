"""A host makes a person's world advance on its own, from settings in its environment.

The settings are read by ``build_services`` and refused by name when malformed. The application
built from them runs the real playback worker against private PostgreSQL as a runtime role, and
the control read says whether this host plays the world, how often, and in words why not.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.services import (
    SOCIETY_CONTROL_WORKSPACES_ENV,
    SOCIETY_SETTING_REFUSALS,
    SOCIETY_TICK_INTERVAL_MS_ENV,
    SocietySettingRefused,
    build_services,
)
from exulanica.api.society_control_worker import HOST_PLAYBACK_REFUSALS
from exulanica.db.roles import provision_runtime_role
from exulanica.world.society_controls import (
    BASE_TICK_INTERVAL_MAX_MS,
    BASE_TICK_INTERVAL_MIN_MS,
    DEFAULT_BASE_TICK_INTERVAL_MS,
    SPEEDS,
)
from exulanica.world.starter import AUTHORED_GROUND_MODULE_VERSION
from fastapi.testclient import TestClient

from conftest import scratch_role_database
from test_society_authored_world_postgres import saved_world
from test_society_saved_world_api import OWNER, TOKEN, bring_inhabitants, place, routes
from tests_support_api import EVERY_PERMISSION

# Imported fixtures are deliberately registered in this module; the owner's token is the one the
# imported helpers send.
__all__ = ["saved_world"]

_RUNTIME_ROLE = "exulanica_host_playback_suite"
#: How long a test waits for the worker to commit ticks nobody asked for. A bound on waiting,
#: not a timing claim: at the fastest pace a tick is due every quarter second.
_ADVANCE_DEADLINE_SECONDS = 60
#: A base other than the default, so a paused control's interval visibly follows the host's.
_OTHER_BASE_MS = BASE_TICK_INTERVAL_MAX_MS
assert _OTHER_BASE_MS != DEFAULT_BASE_TICK_INTERVAL_MS
#: The fastest base a host may state, so the tests that wait on the worker wait least.
_FAST_BASE_MS = BASE_TICK_INTERVAL_MIN_MS


def _environment(database_url: str, data_dir, workspace, actor, **settings) -> dict[str, str]:
    return {
        "EXULANICA_DATABASE_URL": database_url,
        "EXULANICA_DATA_DIR": str(data_dir),
        "EXULANICA_DERIVATIVE_WORKER": "off",
        "EXULANICA_API_TOKENS": json.dumps(
            {
                TOKEN: {
                    "workspace_id": str(workspace),
                    "actor": str(actor),
                    "permissions": EVERY_PERMISSION,
                }
            }
        ),
        **settings,
    }


# -- the settings, read and refused by name -------------------------------------------------------


def _settings_only(tmp_path, **settings):
    """build_services over a database it never opens, for what the settings resolve to."""
    return build_services(
        _environment("postgresql://unused", tmp_path, uuid.uuid4(), uuid.uuid4(), **settings)
    )


def test_absent_settings_play_nothing_at_the_declared_default(tmp_path):
    services = _settings_only(tmp_path)
    assert services.society_control_workspaces == ()
    assert services.society_base_tick_interval_ms == DEFAULT_BASE_TICK_INTERVAL_MS
    assert not services.society_control_enabled
    assert services.build_society_control_worker() is None


def test_listed_workspaces_and_interval_reach_the_worker(tmp_path):
    first, second = uuid.uuid4(), uuid.uuid4()
    services = _settings_only(
        tmp_path,
        **{
            SOCIETY_CONTROL_WORKSPACES_ENV: json.dumps([str(first), str(second)]),
            SOCIETY_TICK_INTERVAL_MS_ENV: str(_OTHER_BASE_MS),
        },
    )
    assert services.society_control_workspaces == (first, second)
    assert services.society_base_tick_interval_ms == _OTHER_BASE_MS
    # No accounts are configured, and a listed workspace needs none.
    assert services.accounts is None and not services.runs_society_control_worker
    worker = services.build_society_control_worker()
    assert worker is not None
    assert set(worker.workspaces) == {first, second}
    assert worker.base_tick_interval_ms == _OTHER_BASE_MS
    # An explicitly empty list is the same as none.
    assert (
        _settings_only(
            tmp_path, **{SOCIETY_CONTROL_WORKSPACES_ENV: "[]"}
        ).society_control_workspaces
        == ()
    )


#: A fixed workspace id, not a random one: parametrize ids must be the same in every xdist worker,
#: or the workers collect different tests and the run stops before any test runs.
_one = "84f363b2-eb09-4699-9711-97cda3022ff6"


@pytest.mark.parametrize(
    ("variable", "value", "code"),
    [
        (SOCIETY_CONTROL_WORKSPACES_ENV, "not json", "society_control_workspaces_not_json"),
        (SOCIETY_CONTROL_WORKSPACES_ENV, json.dumps(_one), "society_control_workspaces_not_array"),
        (
            SOCIETY_CONTROL_WORKSPACES_ENV,
            json.dumps({"a": _one}),
            "society_control_workspaces_not_array",
        ),
        (
            SOCIETY_CONTROL_WORKSPACES_ENV,
            json.dumps(["nope"]),
            "society_control_workspaces_not_uuid",
        ),
        (SOCIETY_CONTROL_WORKSPACES_ENV, json.dumps([7]), "society_control_workspaces_not_uuid"),
        (
            SOCIETY_CONTROL_WORKSPACES_ENV,
            json.dumps([_one, _one]),
            "society_control_workspaces_duplicate",
        ),
        (SOCIETY_TICK_INTERVAL_MS_ENV, "fast", "society_tick_interval_not_integer"),
        (SOCIETY_TICK_INTERVAL_MS_ENV, "2000.0", "society_tick_interval_not_integer"),
        (SOCIETY_TICK_INTERVAL_MS_ENV, "-4000", "society_tick_interval_not_integer"),
        (
            SOCIETY_TICK_INTERVAL_MS_ENV,
            str(BASE_TICK_INTERVAL_MIN_MS - 4),
            "society_tick_interval_out_of_bounds",
        ),
        (
            SOCIETY_TICK_INTERVAL_MS_ENV,
            str(BASE_TICK_INTERVAL_MAX_MS + 4),
            "society_tick_interval_out_of_bounds",
        ),
        (
            SOCIETY_TICK_INTERVAL_MS_ENV,
            str(BASE_TICK_INTERVAL_MIN_MS + 2),
            "society_tick_interval_out_of_bounds",
        ),
        ("EXULANICA_SOCIETY_CONTROL_WORKER", "automatic", "society_control_worker_not_boolean"),
    ],
)
def test_a_malformed_setting_stops_startup_by_name(tmp_path, variable, value, code):
    with pytest.raises(SocietySettingRefused) as refused:
        _settings_only(tmp_path, **{variable: value})
    assert refused.value.code == code and refused.value.variable == variable
    assert str(refused.value).startswith(f"{code}: {variable} ")
    assert code in SOCIETY_SETTING_REFUSALS


def test_every_bound_the_playback_module_accepts_is_accepted(tmp_path):
    """The positive control for the refusals above: the bounds are asked, not restated."""
    for interval in (BASE_TICK_INTERVAL_MIN_MS, BASE_TICK_INTERVAL_MAX_MS):
        services = _settings_only(tmp_path, **{SOCIETY_TICK_INTERVAL_MS_ENV: f" {interval} "})
        assert services.society_base_tick_interval_ms == interval


# -- the running host, against PostgreSQL as a runtime role ---------------------------------------


@pytest.fixture
def host(saved_world, spine_schema, tmp_path):
    """Builds applications from environment settings over the saved world, as a runtime role."""
    world = saved_world
    provision_runtime_role(world["connection"], role=_RUNTIME_ROLE)
    world["connection"].commit()
    database = scratch_role_database(spine_schema[1], _RUNTIME_ROLE)
    with database.session(world["workspace"]) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role

    def make_app(**settings):
        # The saved world's store is ``<tmp_path>/blobs``, which is this data directory's.
        environ = _environment(
            database.url, tmp_path, world["workspace"], world["session"].actor, **settings
        )
        return create_app(build_services(environ), verify=False)

    return world, make_app


def _inhabited(client, world):
    place(client, world, "object:cushion", 3_000, 5_000)
    place(client, world, "object:bench", -3_000, 5_000, asset="pillar")
    response = bring_inhabitants(client, world)
    assert response.status_code == 200, response.text


def _control(client, world):
    scope, _, society = routes(world)
    response = client.get(society + "/control", headers=OWNER, params=scope)
    assert response.status_code == 200, response.text
    return response.json()


def _configure(client, world, control, mode, speed):
    scope, _, society = routes(world)
    response = client.put(
        society + "/control",
        headers=OWNER,
        params=scope,
        json={"base_revision": control["revision"], "mode": mode, "speed": speed},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _tick(client, world):
    scope, _, society = routes(world)
    return client.get(society, headers=OWNER, params=scope).json()["current_tick"]


def _wait_for_tick(client, world, at_least):
    deadline = time.monotonic() + _ADVANCE_DEADLINE_SECONDS
    while (tick := _tick(client, world)) < at_least:
        assert time.monotonic() < deadline, f"tick {tick} after {_ADVANCE_DEADLINE_SECONDS} s"
        time.sleep(0.1)
    return tick


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_a_listed_workspace_advances_with_nobody_asking(host):
    world, make_app = host
    listed = {
        SOCIETY_CONTROL_WORKSPACES_ENV: json.dumps([str(world["workspace"])]),
        SOCIETY_TICK_INTERVAL_MS_ENV: str(_FAST_BASE_MS),
    }
    with TestClient(make_app(**listed)) as client:
        _inhabited(client, world)
        paused = _control(client, world)
        assert paused["mode"] == "paused" and paused["current_tick"] == 0
        assert paused["host_playback"] == {
            "running": True,
            "interval_ms": _FAST_BASE_MS,
            "reason": None,
        }
        playing = _configure(client, world, paused, "playing", max(SPEEDS))
        assert playing["host_playback"] == {
            "running": True,
            "interval_ms": _FAST_BASE_MS // max(SPEEDS),
            "reason": None,
        }
        # No step, no request: the host's worker alone moves the world on.
        assert _wait_for_tick(client, world, 2) >= 2
        scope, _, society = routes(world)
        events = client.get(society + "/control/events", headers=OWNER, params=scope).json()
        advanced = [e for e in events["events"] if e["kind"] == "advanced"]
        assert advanced and all(e["executed_ticks"] >= 1 for e in advanced)
        assert not [e for e in events["events"] if e["kind"] == "manual_step"]

        ready = client.get("/readyz").json()["checks"]["society_playback"]
        assert ready["ok"] and ready["configured"] and ready["running"]
        assert ready["base_tick_interval_ms"] == _FAST_BASE_MS
        assert ready["listed_workspaces"] == 1 and ready["account_discovery"] is False
        assert str(world["workspace"]) not in json.dumps(ready)

        # Paused, it stays where it is, and the read still says the host would play it.
        now = _control(client, world)
        stopped = _configure(client, world, now, "paused", 1)
        assert stopped["host_playback"]["running"] is True
        held = _tick(client, world)
        time.sleep(3 * _FAST_BASE_MS / 1000)
        assert _tick(client, world) == held


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_a_paused_control_reads_the_hosts_interval_and_a_playing_one_its_own(host):
    world, make_app = host
    listed = json.dumps([str(world["workspace"])])
    with TestClient(make_app(**{SOCIETY_CONTROL_WORKSPACES_ENV: listed})) as client:
        _inhabited(client, world)
        playing = _configure(client, world, _control(client, world), "playing", 2)
        assert playing["base_tick_interval_ms"] == DEFAULT_BASE_TICK_INTERVAL_MS
        paused = _configure(client, world, playing, "paused", 2)
    slower = {
        SOCIETY_CONTROL_WORKSPACES_ENV: listed,
        SOCIETY_TICK_INTERVAL_MS_ENV: str(_OTHER_BASE_MS),
    }
    with TestClient(make_app(**slower)) as client:
        # The saved control keeps the base it was configured under; Play would adopt the host's.
        read = _control(client, world)
        assert read["revision"] == paused["revision"]
        assert read["base_tick_interval_ms"] == DEFAULT_BASE_TICK_INTERVAL_MS
        assert read["host_playback"]["interval_ms"] == _OTHER_BASE_MS // 2
        playing = _configure(client, world, read, "playing", 4)
        assert playing["base_tick_interval_ms"] == _OTHER_BASE_MS
        assert playing["host_playback"]["interval_ms"] == _OTHER_BASE_MS // 4
        _configure(client, world, playing, "paused", 1)


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_a_host_that_does_not_play_the_world_says_why(host):
    world, make_app = host
    # No worker at all.
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        read = _control(client, world)
        assert read["host_playback"] == {
            "running": False,
            "interval_ms": DEFAULT_BASE_TICK_INTERVAL_MS,
            "reason": HOST_PLAYBACK_REFUSALS["no_playback_worker"],
        }
        assert client.get("/readyz").json()["checks"]["society_playback"]["running"] is False
        # Saving "playing" here is allowed and advances nothing, and the read keeps saying so.
        playing = _configure(client, world, read, "playing", 1)
        assert playing["host_playback"]["running"] is False
        # Three of the fastest waits a host may state: no host here would have advanced it.
        time.sleep(3 * _FAST_BASE_MS / 1000)
        assert _tick(client, world) == 0
        _configure(client, world, playing, "paused", 1)

    # A worker that plays somebody else's workspace.
    elsewhere = {SOCIETY_CONTROL_WORKSPACES_ENV: json.dumps([str(uuid.uuid4())])}
    with TestClient(make_app(**elsewhere)) as client:
        read = _control(client, world)
        assert read["host_playback"]["running"] is False
        assert read["host_playback"]["reason"] == HOST_PLAYBACK_REFUSALS["workspace_not_played"]

    # A worker asked for whose thread is no longer running.
    listed = {SOCIETY_CONTROL_WORKSPACES_ENV: json.dumps([str(world["workspace"])])}
    with TestClient(make_app(**listed)) as client:
        assert _control(client, world)["host_playback"]["running"] is True
        finished = threading.Thread(target=lambda: None)
        finished.start()
        finished.join()
        client.app.state.society_control_thread = finished
        read = _control(client, world)
        assert read["host_playback"]["running"] is False
        assert read["host_playback"]["reason"] == HOST_PLAYBACK_REFUSALS["playback_worker_stopped"]


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [AUTHORED_GROUND_MODULE_VERSION], indirect=True)
def test_a_manual_step_carries_host_playback_in_its_control(host):
    world, make_app = host
    with TestClient(make_app()) as client:
        _inhabited(client, world)
        control = _control(client, world)
        scope, _, society = routes(world)
        state = client.get(society, headers=OWNER, params=scope).json()
        response = client.post(
            society + "/control/steps",
            headers=OWNER,
            params=scope,
            json={
                "base_revision": control["revision"],
                "base_tick": state["current_tick"],
                "base_state_sha256": state["state_sha256"],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["control"]["host_playback"]["running"] is False
