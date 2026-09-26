"""The flight route over a saved world, as the deployed runtime role reads it.

A person's starter world gets the small square through the arrangement route, and the flight route
then serves the square's tree's birds: the same steps the flight module computes in process from
the same version, every one inside its bounds and out of every solid cell, the bird's reviewed
body and wing named with their registry rows, and the module's bounds refused by name.
"""

from __future__ import annotations

from collections import OrderedDict

import pytest
from exulanica.api.routes import world_flight as route
from exulanica.movement import flight as flight_module
from exulanica.movement.flight import FLIGHT_MODULE, flight_window
from exulanica.movement.flight_checks import check_windows
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world import flight_input as composer
from exulanica.world.flight_input import saved_world_flight
from exulanica.world.flight_kinds import flight_assets
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.reviewed_catalog import ReviewedCatalog
from fastapi.testclient import TestClient

import test_society_saved_world_api as saved_api
import test_world_arrangements as arrangements

pytestmark = pytest.mark.postgres
saved_world = arrangements.saved_world
runtime_app = arrangements.runtime_app
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")


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
    flight = saved_world_flight(repository, world["binding"].version_id, keys)
    connection.commit()
    return flight


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
    beside = ("world_id", "version_id", "kinds", "unplaced")
    steps_served = {key: value for key, value in window.items() if key not in beside}
    assert steps_served == flight_window(flight, 0, WINDOW)
    assert following.json()["flyers"] == flight_window(flight, WINDOW, WINDOW)["flyers"]
    beside_following = {k: v for k, v in following.json().items() if k not in beside}
    check = check_windows(flight, [steps_served, beside_following])
    assert (check.violations, check.late_home) == ([], 0)
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
        ({"from_step": FLIGHT_MODULE.value("max_from_step") + 1}, "flight_step_out_of_range"),
    ],
    ids=["too_many_steps", "no_steps", "before_the_start", "past_the_last_step"],
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
