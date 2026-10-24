"""A placing's preview gives the verdict the placing then gives, and writes nothing
(``POST .../things/preview``).

On the farm of ``tests/test_thing_landing_postgres.py`` (the fixture kind under a fixed identity,
its duck pond and barn read from its own records), through the routes as a deployment serves them:

*   a well placed in the pond, inside the barn, past the edge or in the air: the preview is
    blocked with the placing's code, sentence and ``where``, and neither writes anything;
*   a well on open ground: the preview is ready, says where it stood was checked, and its ``after``
    is the document the placing then records;
*   a creature made from words: ready, its spot unchecked, as the placing checks nothing there;
*   the placing's own checks: an id already placed, a stale base, a digest the workspace holds no
    kind at and a version holding as many things as it may are blocked by the codes the placing
    answers.

In a small town whose traffic reads placed things (``tests/test_world_traffic_route.py``'s), a
bench's place and move previews state what it would close there (``closes``): a lane, or the turns
into a named street; ``read: false`` when the traffic's worker refuses or answers late; nothing in
a town made under traffic rules 1, nor on the farm.
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from types import MappingProxyType
from typing import Any

import pytest
from exulanica.world import object_repository, traffic_host
from exulanica.world import world_recipes as recipe_catalog
from exulanica.world.composers import city_grammar_town
from exulanica.world.thing_store import ThingStore
from exulanica.world.world_recipes import CANDIDATES_MAXIMUM, world_recipes

from test_society_made_kinds import canary_creature
from test_society_made_world import made as imported_made  # noqa: F401
from test_thing_landing_postgres import (
    WELL,
    _farm,
    _open_ground,
    _place,
    _pond,
    _pose,
    _recorded_after,
    _refused_cases,
    _root,
    _scope,
    _the_same_farm_on_every_run,  # noqa: F401
    _version,
)
from test_world_traffic_route import (
    BENCH,
    _driven,
    _identity,
    _junction_middle,
    _lane_middle,
    _made,
)

pytestmark = pytest.mark.postgres

CASES = ["into the duck pond", "inside the barn", "past the farm's edge", "a metre into the air"]


@pytest.fixture(name="made")
def _made_alias(request):  # type: ignore[no-untyped-def]
    return request.getfixturevalue("imported_made")


def _preview(  # type: ignore[no-untyped-def]
    api, entry: dict, thing_id: str, kind: dict, pose: dict, base: str | None = None
):
    return api.post(
        _root(entry) + "/things/preview" + _scope(entry),
        {
            "base_state_sha256": base or _version(api, entry)["state_sha256"],
            "thing_id": thing_id,
            "kind": kind,
            "region_id": "region:generated",
            "pose": pose,
            "origin_role": "fictional",
        },
    )


def _verdict(response) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.mark.parametrize("case", CASES)
def test_a_refused_placing_s_preview_names_the_same_refusal_and_neither_writes(made, case):
    api = made
    entry, records = _farm(api)
    before = _version(api, entry)
    pose, _expected = _refused_cases(entry, records)[case]

    verdict = _verdict(_preview(api, entry, "well", WELL, pose))
    assert _version(api, entry) == before
    placed = _place(api, entry, "well", WELL, pose)

    assert placed.status_code == 422, placed.text
    assert verdict["availability"] == "blocked"
    assert verdict["blocked_reason"] == placed.json()["code"]
    assert verdict["blocked_detail"] == placed.json()["detail"]
    assert verdict["landing"] == {"checked": True, "where": placed.json()["where"]}
    assert verdict["would_change"]["kind"] == "add_thing"
    assert verdict["would_change"]["after"] is None
    assert _version(api, entry) == before


def test_a_well_on_open_ground_is_placed_as_its_preview_said(made):
    api = made
    entry, _records = _farm(api)
    before = _version(api, entry)
    pose = _pose(*_open_ground(entry))

    verdict = _verdict(_preview(api, entry, "well", WELL, pose))
    # Ready, checked, and the height the well rests at there: the farm's level floor.
    assert (verdict["availability"], verdict["landing"]) == (
        "ready",
        {"checked": True, "rest_y_mm": 0},
    )
    assert verdict["would_change"]["subject_id"] == "well"
    assert verdict["would_change"]["before"] is None
    assert "closes" not in verdict, "the farm has no traffic to close"
    assert _version(api, entry) == before

    placed = _place(api, entry, "well", WELL, pose)
    assert placed.status_code == 201, placed.text
    assert placed.json()["edits"][-1]["kind"] == "add_thing"
    assert verdict["would_change"]["after"] == _recorded_after(api, placed.json()["edits"][-1])


def test_a_creature_made_from_words_previews_ready_where_its_maker_puts_it_unchecked(made):
    api = made
    entry, records = _farm(api)
    creature = canary_creature("crocodile", hands=True)
    with api.database.session(api.repository.workspace_id) as session:
        ThingStore(session, api.repository.workspace_id, api.store).keep_creature(
            creature, created_by=api.actor
        )
    kind = {"source": "workspace", "sha256": creature.kind.sha256}

    verdict = _verdict(_preview(api, entry, "creature:0000aaaa", kind, _pose(*_pond(records))))

    assert (verdict["availability"], verdict["landing"]) == ("ready", {"checked": False})


def test_the_placing_s_own_checks_block_its_preview_by_the_placing_s_codes(made, monkeypatch):
    api = made
    entry, _records = _farm(api)
    x, z = _open_ground(entry)
    placed = _place(api, entry, "well", WELL, _pose(x, z))
    assert placed.status_code == 201, placed.text
    elsewhere = _pose(x + 4_000, z)

    taken = _verdict(_preview(api, entry, "well", WELL, elsewhere))
    assert taken["blocked_reason"] == "invalid_object_state"
    assert _place(api, entry, "well", WELL, elsewhere).json()["code"] == "invalid_object_state"

    stale = _verdict(_preview(api, entry, "second-well", WELL, elsewhere, "0" * 64))
    assert stale["blocked_reason"] == "stale_object_base"

    unknown = {"source": "workspace", "sha256": "1" * 64}
    unheld = _verdict(_preview(api, entry, "creature:0000bbbb", unknown, elsewhere))
    assert unheld["blocked_reason"] == "invalid_thing_placement"
    assert _place(api, entry, "creature:0000bbbb", unknown, elsewhere).json()["code"] == (
        "invalid_thing_placement"
    )

    monkeypatch.setattr(object_repository, "PLACED_THINGS_MAXIMUM", 1)
    full = _verdict(_preview(api, entry, "second-well", WELL, elsewhere))
    assert full["blocked_reason"] == "thing_limit_reached"
    refused = _place(api, entry, "second-well", WELL, elsewhere)
    assert (refused.status_code, refused.json()["code"]) == (409, "thing_limit_reached")


# -- what a bench would close of a town's traffic --------------------------------------------------


@pytest.fixture(name="town")
def _town(made, monkeypatch):  # type: ignore[no-untyped-def]
    """Making a small town whose roads the traffic drives, its traffic's worker in this process."""
    worker = traffic_host.TrafficEpisodes(lambda: ThreadPoolExecutor(max_workers=1))
    monkeypatch.setattr(traffic_host, "_episodes", worker)
    generous = {
        recipe.key: dataclasses.replace(recipe, candidates=CANDIDATES_MAXIMUM)
        for recipe in world_recipes()
    }
    monkeypatch.setattr(recipe_catalog, "_by_key", lambda: MappingProxyType(generous))
    _identity(monkeypatch, _driven()[0])
    yield made, worker
    worker.close()


def _bench_preview(api, entry: dict, point: tuple[int, int]) -> dict[str, Any]:  # type: ignore[no-untyped-def]
    """A bench's place preview at a plan point (east and north), at the height it rests at there."""
    pose = {"x_mm": point[0], "y_mm": 0, "z_mm": -point[1], "yaw_microradians": 0}
    first = _verdict(_preview(api, entry, "bench", BENCH, pose))
    rest = first["landing"]["rest_y_mm"]
    return _verdict(_preview(api, entry, "bench", BENCH, {**pose, "y_mm": rest}))


def test_a_bench_s_preview_states_the_lane_or_the_turns_it_would_close_in_a_town(
    town, monkeypatch, caplog
):
    api, worker = town
    entry = _made(api, "A bench's preview")
    _, lane_point = _lane_middle(api, entry)
    on_lane = _bench_preview(api, entry, lane_point)
    assert on_lane["availability"] == "ready"
    assert on_lane["closes"] == {
        "rules": 3,
        "read": True,
        "lanes": 1,
        "streets": [],
        "turns": [],
        "widest": "lane",
    }
    _, junction_point = _junction_middle(api, entry)
    junction_verdict = _bench_preview(api, entry, junction_point)
    in_junction = junction_verdict["closes"]
    in_junction_rest = junction_verdict["landing"]["rest_y_mm"]
    assert (in_junction["read"], in_junction["lanes"], in_junction["widest"]) == (True, 0, "turn")
    assert in_junction["turns"] and in_junction["streets"] == []
    assert all(isinstance(turn["street"], str) and turn["street"] for turn in in_junction["turns"])
    # A worker that refuses, or answers later than the preview waits, leaves it unread.
    ask, wait = worker.ask, traffic_host.CLOSING_SECONDS

    def refused(function):  # type: ignore[no-untyped-def]
        raise traffic_host.TrafficWorkerUnavailable("stopped")

    def late(function):  # type: ignore[no-untyped-def]
        time.sleep(0.5)
        return function()

    monkeypatch.setattr(worker, "ask", refused)
    with caplog.at_level(logging.WARNING, logger=traffic_host.__name__):
        assert _bench_preview(api, entry, lane_point)["closes"] == {"rules": 3, "read": False}
    assert "not read" not in caplog.text, "a refusal is expected, not logged as a fault"
    monkeypatch.setattr(worker, "ask", late)
    monkeypatch.setattr(traffic_host, "CLOSING_SECONDS", 0.1)
    assert _bench_preview(api, entry, lane_point)["closes"] == {"rules": 3, "read": False}
    monkeypatch.setattr(worker, "ask", ask)
    monkeypatch.setattr(traffic_host, "CLOSING_SECONDS", wait)
    # With as many asks waiting as may, the next is unread at once rather than queued behind them.
    full = threading.BoundedSemaphore(1)
    full.acquire()
    monkeypatch.setattr(traffic_host, "_closing_room", full)
    assert _bench_preview(api, entry, lane_point)["closes"] == {"rules": 3, "read": False}
    monkeypatch.setattr(traffic_host, "_closing_room", threading.BoundedSemaphore(2))
    # A move's preview states it as a placing's does: a bench placed on the lane, moved into the
    # junction, would close the turns there, read from the open roads whatever already stands.
    pose = {"x_mm": lane_point[0], "y_mm": 0, "z_mm": -lane_point[1], "yaw_microradians": 0}
    pose["y_mm"] = on_lane["landing"]["rest_y_mm"]
    placed = _place(api, entry, "bench", BENCH, pose)
    assert placed.status_code == 201, placed.text
    junction_pose = {"x_mm": junction_point[0], "z_mm": -junction_point[1], "yaw_microradians": 0}
    moved = _verdict(
        api.post(
            _root(entry) + "/things/bench/move/preview" + _scope(entry),
            {
                "base_state_sha256": _version(api, entry)["state_sha256"],
                "pose": {**junction_pose, "y_mm": in_junction_rest},
            },
        )
    )
    assert moved["availability"] == "ready" and moved["closes"] == in_junction


def test_a_failure_on_the_closing_path_leaves_the_preview_ready_and_its_closing_unread(
    town, monkeypatch, caplog
):
    api, worker = town
    entry = _made(api, "A closing that fails")
    _, point = _lane_middle(api, entry)
    ask = worker.ask

    def faulty(function):  # type: ignore[no-untyped-def]
        raise ValueError("a fault in the worker's job")

    monkeypatch.setattr(worker, "ask", faulty)
    with caplog.at_level(logging.WARNING, logger=traffic_host.__name__):
        verdict = _bench_preview(api, entry, point)
    assert verdict["availability"] == "ready"
    assert verdict["closes"] == {"rules": 3, "read": False}
    assert "ValueError" in caplog.text
    monkeypatch.setattr(worker, "ask", ask)

    # A read that fails in the database is rolled back to the closing's savepoint: the preview's own
    # transaction goes on, and it answers as it would.
    def failing(connection, *_arguments):  # type: ignore[no-untyped-def]
        connection.execute("select * from a_table_no_one_made")

    monkeypatch.setattr(traffic_host, "saved_world_roads", failing)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=traffic_host.__name__):
        verdict = _bench_preview(api, entry, point)
    assert verdict["availability"] == "ready"
    assert verdict["closes"] == {"rules": 3, "read": False}
    assert "UndefinedTable" in caplog.text
    # Asked inside a transaction of the caller's, the transaction still takes its next statement.
    connection = api.repository.connection
    x, y = point
    square = [(x - 300, -y - 300), (x + 300, -y - 300), (x + 300, -y + 300), (x - 300, -y + 300)]
    with connection.transaction():
        found = traffic_host.footprint_closing(
            connection,
            api.repository.workspace_id,
            entry["world_id"],
            uuid.UUID(entry["source_snapshot_id"]),
            [square],
        )
        assert found == {"rules": 3, "read": False}
        assert connection.execute("select 1 as one").fetchone() == {"one": 1}


def test_a_town_made_under_traffic_rules_1_previews_no_closing(town, monkeypatch):
    api, _worker = town
    monkeypatch.setattr(city_grammar_town, "TRAFFIC_RULES", 1)
    entry = _made(api, "An older town")
    _, point = _lane_middle(api, entry)
    verdict = _bench_preview(api, entry, point)
    assert verdict["availability"] == "ready" and "closes" not in verdict
