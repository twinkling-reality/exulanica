"""The flight route over a saved world, as the deployed runtime role reads it.

A person's starter world gets the small square through the arrangement route, and the flight route
then serves the square's tree's birds: the same steps the flight module computes in process from
the same version, every one inside its bounds and out of every solid cell, the bird's reviewed
body and wing named with their registry rows, and the module's bounds refused by name.
"""

from __future__ import annotations

import gc
import os
import signal
from collections import OrderedDict

import pytest
from exulanica.api.routes import world_flight as route
from exulanica.movement import flight as flight_module
from exulanica.movement.flight import FLIGHT_MODULE, flight_window
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world import flight_input as composer
from exulanica.world.flight_checks import check_windows, checked_world
from exulanica.world.flight_input import saved_world_flight
from exulanica.world.flight_kinds import flight_assets
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.reviewed_catalog import ReviewedCatalog
from exulanica.world.society_authored_ground import read_authored_ground
from fastapi.testclient import TestClient

import test_society_saved_world_api as saved_api
import test_world_arrangements as arrangements
from flight_support import homes

pytestmark = pytest.mark.postgres
saved_world = arrangements.saved_world
runtime_app = arrangements.runtime_app
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")
EPISODE = FLIGHT_MODULE.value("episode_steps")
REACH = FLIGHT_MODULE.value("clock_reach_steps")
#: Shared real time for these tests: the flight's clock reads step 0, so the tests' windows are
#: the flight's first ones. A test that needs the clock elsewhere pins it itself.
_now = {"ms": 0}


@pytest.fixture(autouse=True)
def _pinned_clock(monkeypatch):
    _now["ms"] = 0
    monkeypatch.setattr(composer, "_now_ms", lambda: _now["ms"])


def _square(client, world) -> None:
    scope, version, body = arrangements._body(client, world)
    applied = client.post(
        version + "/arrangements/apply", headers=saved_api.OWNER, params=scope, json=body
    )
    assert applied.status_code == 201, applied.text


def _flight(client, world, **params):
    scope, version, _ = saved_api.routes(world)
    return client.get(version + "/flight", headers=saved_api.OWNER, params={**scope, **params})


def _in_process(world):
    """The same version's flight, composed in this process from the database the route read."""
    connection = world["connection"]
    repository = WorldObjectRepository(
        connection, world["workspace"], world_id=world["world_id"], store=world["store"]
    )
    keys = {row.content_sha256: row.asset_key for row in ReviewedCatalog(connection).assets()}
    flight = saved_world_flight(repository, world["binding"].version_id, keys).flight
    connection.commit()
    return flight


def _checked(world):
    """The same version as the independent checker derives it, from the database's own rows."""
    connection = world["connection"]
    repository = WorldObjectRepository(
        connection, world["workspace"], world_id=world["world_id"], store=world["store"]
    )
    version = repository.version(world["binding"].version_id, with_availability=False)
    ground = read_authored_ground(
        connection, world["workspace"], world["world_id"], version.source_snapshot_id
    )
    keys = {row.content_sha256: row.asset_key for row in ReviewedCatalog(connection).assets()}
    connection.commit()
    return checked_world(objects=version.objects, asset_keys=keys, ground=ground)


def test_a_saved_world_with_a_square_serves_its_tree_birds(runtime_app):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        empty = _flight(client, world)
        assert empty.status_code == 200, empty.text
        assert (empty.json()["flyers"], empty.json()["unplaced"]) == ([], [])
        _square(client, world)
        served = _flight(client, world)
        assert served.status_code == 200, served.text
        window = served.json()
        following = _flight(client, world, from_step=WINDOW)
        assert following.status_code == 200, following.text
    assert (window["profile"], window["module"]) == (
        "exulanica.flight-window/v1",
        "exulanica-movement/flight/v1",
    )
    assert (window["from_step"], window["steps"], window["step_ms"]) == (0, WINDOW, 100)
    assert [row["kind"] for row in window["flyers"]] == ["small_bird"] * 3
    flight = _in_process(world)
    assert window["input_sha256"] == flight.sha256
    beside = ("clock_step", "world_id", "version_id", "kinds", "unplaced")
    steps_served = {key: value for key, value in window.items() if key not in beside}
    assert steps_served == flight_window(flight, 0, WINDOW)
    assert following.json()["flyers"] == flight_window(flight, WINDOW, WINDOW)["flyers"]
    beside_following = {k: v for k, v in following.json().items() if k not in beside}
    found = check_windows(_checked(world), homes(flight), [steps_served, beside_following])
    assert (found.violations, found.late_home) == ([], 0)
    (kind,) = window["kinds"]
    generated = {asset.asset_key: asset for asset in flight_assets()}
    for part in ("body", "wing"):
        asset = kind[part]
        assert asset["availability"] == "available", asset
        assert asset["content_sha256"] == generated[asset["asset_key"]].content_sha256


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"steps": WINDOW + 1}, "flight_window_too_long"),
        ({"steps": 0}, "flight_window_too_long"),
        ({"from_step": -1}, "flight_step_out_of_range"),
        ({"from_step": REACH + 1}, "flight_step_out_of_range"),
    ],
    ids=["too_many_steps", "no_steps", "before_the_start", "beyond_the_clock_s_reach"],
)
def test_a_window_beyond_the_module_bounds_is_refused_by_name(runtime_app, params, code):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        refused = _flight(client, world, **params)
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == code


def test_an_unknown_version_is_an_unknown_reference(runtime_app):
    world, make_app = runtime_app
    scope, _, _ = saved_api.routes(world)
    with TestClient(make_app()) as client:
        missing = client.get(
            "/world/versions/00000000-0000-4000-8000-000000000000/flight",
            headers=saved_api.OWNER,
            params=scope,
        )
    assert missing.status_code == 404, missing.text


def test_a_window_beyond_the_bounds_is_refused_before_any_air_is_composed(runtime_app, monkeypatch):
    world, make_app = runtime_app
    composed = []

    def composing(*arguments, **keywords):
        composed.append(arguments)
        raise AssertionError("a refused window composed the flight")

    monkeypatch.setattr(route, "saved_world_flight", composing)
    with TestClient(make_app()) as client:
        refused = _flight(client, world, steps=WINDOW + 1)
    assert (refused.status_code, refused.json()["code"]) == (422, "flight_window_too_long")
    assert composed == []


def test_a_version_s_air_is_composed_once_for_every_window_read_of_it(runtime_app, monkeypatch):
    world, make_app = runtime_app
    monkeypatch.setattr(composer, "_inputs", OrderedDict())
    made = []
    compose = composer.compose_flight_input

    def counted(**keywords):
        made.append(keywords["version"].state_sha256)
        return compose(**keywords)

    monkeypatch.setattr(composer, "compose_flight_input", counted)
    with TestClient(make_app()) as client:
        _square(client, world)
        for start in (0, WINDOW, 2 * WINDOW):
            assert _flight(client, world, from_step=start).status_code == 200
    assert len(made) == 1


def test_a_switched_off_flight_answers_with_its_own_refusal(runtime_app, monkeypatch):
    world, make_app = runtime_app

    def switched_off(name):
        raise MovementModuleNotConnected(name, "flight_not_connected")

    monkeypatch.setattr(flight_module, "built_module", switched_off)
    with TestClient(make_app()) as client:
        refused = _flight(client, world)
    assert (refused.status_code, refused.json()["code"]) == (409, "flight_not_connected")


def test_a_killed_worker_is_refused_by_name_and_the_next_read_starts_another(runtime_app):
    """The server's own worker process, killed: the read that needs it answers 503
    flight_worker_unavailable, which a page tries again, and a new worker serves the next read."""
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _square(client, world)
        assert _flight(client, world).status_code == 200
        killed = composer.flight_episodes().report()["pid"]
        os.kill(killed, signal.SIGKILL)
        # An episode nobody has read, so the read needs the worker: the clock's is episode 0,
        # and the one after it is queued.
        _now["ms"] = EPISODE * FLIGHT_MODULE.step_ms * 3
        refused = _flight(client, world)
        assert refused.status_code == 503, refused.text
        assert refused.json()["code"] == "flight_worker_unavailable"
        again = _flight(client, world)
        assert again.status_code == 200, again.text
        assert composer.flight_episodes().report()["pid"] not in {killed, os.getpid()}
    flight = _in_process(world)
    assert again.json()["flyers"] == flight_window(flight, 3 * EPISODE, WINDOW)["flyers"]


def test_the_server_s_lifespan_stops_the_flight_worker(runtime_app):
    world, make_app = runtime_app
    with TestClient(make_app()) as client:
        _square(client, world)
        assert _flight(client, world).status_code == 200
        worker = composer.flight_episodes().report()["pid"]
        os.kill(worker, 0)
    with pytest.raises(ProcessLookupError):
        os.kill(worker, 0)


def test_a_read_naming_no_step_starts_at_the_shared_clock_and_says_where_it_is(runtime_app):
    """Shared real time: two reads at the same moment are the same window of the flight, from the
    clock's step, and each answer carries the clock's step as it was answered."""
    world, make_app = runtime_app
    moment = 1_790_445_600_000
    _now["ms"] = moment
    clock = moment // FLIGHT_MODULE.step_ms
    with TestClient(make_app()) as client:
        _square(client, world)
        first = _flight(client, world)
        second = _flight(client, world)
        _now["ms"] = moment + 250
        later = _flight(client, world)
    assert first.status_code == second.status_code == later.status_code == 200, first.text
    assert first.json() == second.json()
    assert (first.json()["from_step"], first.json()["clock_step"]) == (clock, clock)
    assert (later.json()["from_step"], later.json()["clock_step"]) == (clock + 2, clock + 2)
    flight = _in_process(world)
    assert first.json()["flyers"] == flight_window(flight, clock, WINDOW)["flyers"]


@pytest.mark.parametrize("side", [-1, 1], ids=["behind", "ahead"])
def test_a_window_more_than_the_clock_s_reach_away_is_refused_by_name(runtime_app, side):
    world, make_app = runtime_app
    _now["ms"] = 1_790_445_600_000
    clock = _now["ms"] // FLIGHT_MODULE.step_ms
    with TestClient(make_app()) as client:
        within = _flight(client, world, from_step=clock + side * REACH, steps=1)
        beyond = _flight(client, world, from_step=clock + side * (REACH + 1), steps=1)
    assert within.status_code == 200, within.text
    assert (beyond.status_code, beyond.json()["code"]) == (422, "flight_step_out_of_range")


def test_the_answer_is_encoded_one_flyer_to_an_encoder_call(runtime_app, monkeypatch):
    """The standard library's encoder holds the interpreter's lock for a whole call, so no call
    encodes more than one flyer's samples; the bytes still read as the window served."""
    world, make_app = runtime_app
    calls: list[str] = []
    real = route.json.dumps

    def recorded(value, **keywords):
        text = real(value, **keywords)
        calls.append(text)
        return text

    with TestClient(make_app()) as client:
        _square(client, world)
        assert _flight(client, world).status_code == 200
        monkeypatch.setattr(route.json, "dumps", recorded)
        served = _flight(client, world, from_step=WINDOW)
        monkeypatch.setattr(route.json, "dumps", real)
    assert served.status_code == 200, served.text
    samples = [text.count('"position_mm"') for text in calls]
    assert max(samples) == 1 and sum(samples) == len(served.json()["flyers"]) == 3
    flight = _in_process(world)
    assert served.json()["flyers"] == flight_window(flight, WINDOW, WINDOW)["flyers"]


def test_the_server_freezes_what_startup_made_and_lets_it_go_when_it_stops(runtime_app):
    """A full collection over what startup made would stall every request the server answers, so
    the lifespan collects once and freezes it for the server's life, and unfreezes it at the end."""
    world, make_app = runtime_app
    assert gc.get_freeze_count() == 0
    with TestClient(make_app()) as client:
        assert gc.get_freeze_count() > 0
        assert gc.isenabled()
        assert _flight(client, world).status_code == 200
    assert gc.get_freeze_count() == 0
