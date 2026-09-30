"""A saved world's traffic, through the real application: served to its world, refused by name.

``GET /world/versions/{version_id}/traffic?world_id=`` reads the roads a world's own records state,
generated again from its receipt, and serves windows of the roads module's episodes, which the
traffic's worker computes (here a thread of this process: the spawned worker is
tests/test_traffic_episodes.py's). A world is made through ``POST /worlds/generated`` as the
runtime role, under row-level security. Its identity is fixed to the first of a numbered few whose
small town's roads the traffic drives: about one two-tile town in fifteen has roads the compiler
refuses, which this route names, and a town's identity decides which.
"""

from __future__ import annotations

import dataclasses
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType

import pytest
from exulanica.api.permissions import ROUTE_RULES, SELF_CHARGING_TILE_ROUTES, Permission
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world import saved_entries as saved_entries_module
from exulanica.world import traffic_host
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.generated_worlds import compose_specified_world, generation_receipt
from exulanica.world.traffic_episodes import EPISODE, prepared, traffic_input
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM, load_world_recipes, world_recipes
from exulanica.world.worlds import GENERATED

from personal_world_support import STRANGER_TOKEN
from test_society_made_world import made as imported_made  # noqa: F401

pytestmark = pytest.mark.postgres

ROUTE = ("GET", "/world/versions/{version_id}/traffic")


def _driven() -> tuple[str, int]:
    """The first of a numbered few identities whose small town's roads the traffic drives, and how
    many vehicles its fleet holds, read as the route's host prepares a network."""
    for index in range(8):
        world_id = f"world:generated:traffic-route-{index}"
        composed = compose_specified_world("small_town", None, world_id)
        value = traffic_input(
            world_id=world_id,
            version_id=composed.receipt_sha256,
            city_identity=composed.receipt["subject_identity"],
            grammar_version=composed.receipt["grammar"]["grammar_version"],
            records=composed.records,
        )
        try:
            fleet = prepared(value).fleet
        except UnsupportedNetworkError:
            continue
        if sum(fleet.values()):
            return world_id, sum(fleet.values())
    raise AssertionError("none of eight small towns has roads the traffic drives")


@pytest.fixture(name="made")
def _made_alias(request):
    return request.getfixturevalue("imported_made")


@pytest.fixture(autouse=True)
def in_this_process(monkeypatch):
    """The route's worker, in this process."""
    worker = traffic_host.TrafficEpisodes(lambda: ThreadPoolExecutor(max_workers=1))
    monkeypatch.setattr(traffic_host, "_episodes", worker)
    yield
    worker.close()


@pytest.fixture(autouse=True)
def _presets_try_every_candidate(monkeypatch):
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))


def _identity(monkeypatch, world_id: str) -> None:
    """The next generated world is made for ``world_id``."""
    minted = saved_entries_module.new_world_id
    monkeypatch.setattr(
        saved_entries_module,
        "new_world_id",
        lambda kind: world_id if kind == GENERATED else minted(kind),
    )


def _traffic(api, entry, query: str = "seconds=5", *, token=None):
    path = (
        f"/world/versions/{entry['authored_version_id']}/traffic"
        f"?world_id={entry['world_id']}&{query}"
    )
    return api.get(path) if token is None else api.get(path, token=token)


def _made(api, title: str) -> dict:
    response = api.post("/worlds/generated", {"recipe": "small_town", "title": title})
    assert response.status_code == 201, response.text
    return response.json()


def test_the_route_is_read_with_world_read_and_charges_no_tile():
    rule = ROUTE_RULES[ROUTE]
    assert rule.permissions == frozenset({Permission.WORLD_READ})
    assert ROUTE not in SELF_CHARGING_TILE_ROUTES


def test_a_saved_towns_traffic_is_served_to_its_world_from_its_own_records(made, monkeypatch):
    api = made
    driven, fleet = _driven()
    _identity(monkeypatch, driven)
    entry = _made(api, "Driven")
    answer = _traffic(api, entry)
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert (body["profile"], body["seconds"], body["crossings_fed"]) == (
        "exulanica.traffic-window/v1",
        5,
        False,
    )
    assert (body["world_id"], body["version_id"]) == (
        entry["world_id"],
        entry["authored_version_id"],
    )
    # The roads' version is the receipt the world's records come from.
    digest, receipt = generation_receipt(
        api.repository.connection,
        api.repository.workspace_id,
        entry["world_id"],
        uuid.UUID(entry["source_snapshot_id"]),
    )
    assert body["roads_version"] == digest
    assert receipt["grammar"]["grammar_version"] == 4
    assert len(body["vehicles"]) == fleet
    assert all(len(row["mode"]) == 5 for row in body["vehicles"])
    assert 0 <= body["clock_second"] - body["from_second"] <= 30
    # A stranger is told the world does not exist.
    assert _traffic(api, entry, token=STRANGER_TOKEN).status_code == 404


def test_refusals_name_what_is_wrong(made, monkeypatch):
    api = made
    _identity(monkeypatch, _driven()[0])
    entry = _made(api, "Asked wrongly")
    clock = traffic_host.traffic_clock()
    cases = [
        ("seconds=61", 422, "traffic_window_too_long"),
        (f"from_second={clock - 3 * EPISODE}", 422, "traffic_second_out_of_range"),
    ]
    for query, status, code in cases:
        answer = _traffic(api, entry, query)
        assert (answer.status_code, answer.json()["code"]) == (status, code), query
    unknown = {**entry, "authored_version_id": str(uuid.uuid4())}
    answer = _traffic(api, unknown)
    assert (answer.status_code, answer.json()["code"]) == (404, "unknown_reference")


def test_a_world_whose_records_state_no_roads_is_refused_by_name(made):
    api = made
    starter = api.post("/world-entries/starter", {"title": "My world"})
    assert starter.status_code == 200, starter.text
    answer = _traffic(api, starter.json())
    assert answer.status_code == 404, answer.text
    assert answer.json()["code"] == "roads_not_stated"


def test_roads_the_traffic_cannot_drive_are_refused_with_the_compilers_reason(made, monkeypatch):
    """Version 1's small town is one tile of city grammar version 3, whose lanes end at the far
    side of each crossing, so a turn passes another approach's stop line and the compiler refuses
    the network: the town is still made and drawn, and its traffic is refused by name."""
    [version_1] = [r for r in load_world_recipes(catalog_version=1) if r.key == "small_town"]
    monkeypatch.setattr(
        recipe_catalog,
        "town_recipe",
        lambda key, values=None: dataclasses.replace(version_1, candidates=CANDIDATES_MAXIMUM),
    )
    api = made
    _identity(monkeypatch, "world:generated:traffic-route-0")
    entry = _made(api, "Version 3")
    answer = _traffic(api, entry)
    assert answer.status_code == 409, answer.text
    assert answer.json()["code"] == "roads_unavailable"
    assert "stop line" in answer.json()["detail"]
