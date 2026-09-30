"""A started comparison stops between seeds, keeping every seed it played, where its bound would not
let the next one finish.

Every ask is held at its model's most until its usage is recorded, so a bound near what a comparison
typically spends stops its runs part way and keeps nothing of them. The host that plays a start
admits each seed's model runs only while what is left of the bound holds what runs like them
typically cost and what they can hold reserved at once; otherwise it closes that seed's and every
later seed's model runs, and the start, as ``comparison_bound_before_seed``, and the served result
says so. The bound itself is unchanged: no ask is admitted past it.
"""

from __future__ import annotations

import dataclasses
from decimal import Decimal

import pytest
from exulanica.api import society_comparison_start as start_module
from exulanica.api.society_comparison_start import TypicalFigures
from exulanica.db.session import set_workspace
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient

import test_society_comparison_start_postgres as starts
import test_society_stay_requests_api as stays

pytestmark = pytest.mark.postgres
saved_world = starts.saved_world
started = starts.started
#: What one of the group's people is taken to cost for the hour under the scripted model: far more
#: than its scripted asks cost, so a seed's typical figure is what decides whether it is admitted.
PER_PERSON_HOUR = Decimal("0.01")


def _plan(held: dict, seeds: int) -> dict:
    world = held["world"]
    answered = held["client"].get(
        starts._comparisons(world) + "/plan",
        headers=starts.OWNER,
        params={
            **starts._scope(world),
            "role": "society_decision",
            "group": "everyone",
            "model": f"{starts.MODEL.provider}/{starts.MODEL.model_id}",
            "seeds": seeds,
        },
    )
    assert answered.status_code == 200, answered.text
    return answered.json()["plan"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_bound_between_one_and_two_seeds_typical_cost_stops_between_them(started, monkeypatch):
    world = started["world"]
    stays._inhabited(world, started["client"])
    figures = TypicalFigures("measured here", {starts.MODEL.model_id: PER_PERSON_HOUR}, {})
    monkeypatch.setattr(start_module, "figures_for", lambda *_args: (figures, True))
    one, two = _plan(started, 1), _plan(started, 2)
    # One seed's least bound that lets it finish, and a hundred-millionth of a dollar more, which
    # its own asks spend: the second seed's typical figure does not fit what is left.
    bound = Decimal(one["suggested_usd"]) + Decimal("0.00000001")
    assert bound < Decimal(two["typical_usd"]) + Decimal(one["held_usd"])
    body = starts._body(seeds=2, bound_usd=format(bound, "f"))
    assert starts._start(started, body).status_code == 201, body
    assert starts._worker(started).run_once(world["workspace"]) is True
    result = (
        started["client"]
        .get(
            starts._comparisons(world) + f"/{body['comparison_id']}",
            headers=starts.OWNER,
            params=starts._scope(world),
        )
        .json()
    )
    first, second = result["seeds"]
    # The first seed was admitted and played to its end; its runs are kept and scored.
    assert {run["status"] for run in first["runs"].values()} == {"completed"}
    assert first["runs"]["model_a"]["score"] is not None
    # The second seed was not admitted: its anchors and its model run were closed, asking nothing.
    assert {run["failure"] for run in second["runs"].values()} == {"comparison_bound_before_seed"}
    # The served start says why it stopped, and it spent within its bound.
    assert (result["start"]["state"], result["start"]["closed_reason"]) == (
        "closed",
        "comparison_bound_before_seed",
    )
    assert Decimal(0) < Decimal(result["start"]["spent_usd"]) <= bound


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_bound_that_holds_both_seeds_plays_both(started, monkeypatch):
    # The positive control: the same comparison under a bound that holds the second seed's
    # typical figure beside the first's plays both.
    world = started["world"]
    stays._inhabited(world, started["client"])
    figures = TypicalFigures("measured here", {starts.MODEL.model_id: PER_PERSON_HOUR}, {})
    monkeypatch.setattr(start_module, "figures_for", lambda *_args: (figures, True))
    two = _plan(started, 2)
    body = starts._body(seeds=2, bound_usd=two["suggested_usd"])
    assert starts._start(started, body).status_code == 201, body
    assert starts._worker(started).run_once(world["workspace"]) is True
    (listed,) = starts._listing(started)
    assert listed["runs_completed"] == listed["runs"] == 6
    assert (listed["start"]["state"], listed["start"]["closed_reason"]) == ("finished", None)
    # Once the start is finished, the host has drawn every completed run for its reads.
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    drawn = connection.execute(
        "select count(*) as n from society_comparison_replay "
        "where world_id=%s and comparison_id=%s",
        (world["binding"].world_id, body["comparison_id"]),
    ).fetchone()["n"]
    connection.commit()
    assert drawn == 6


def _with_budget(held: dict, *, max_calls: int, plays_here: bool) -> None:
    """The server's model client under a process budget of ``max_calls`` calls."""
    services = held["client"].app.state.services
    held["client"].app.state.services = dataclasses.replace(
        services,
        runs_comparison_worker=plays_here,
        model_client=ModelClient(
            api_key="test-key-not-real",
            manifest=starts.MANIFEST,
            transport=held["transport"],
            budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=max_calls),
        ),
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_whose_calls_this_process_cannot_hold_is_refused(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    calls = _plan(started, 1)["calls_most"]
    _with_budget(started, max_calls=calls, plays_here=True)
    refused = starts._start(started, starts._body())
    assert (refused.status_code, refused.json()["code"]) == (409, "calls_over_budget")
    # Positive control: with room for every call it can make, the same start is taken.
    _with_budget(started, max_calls=10 * calls, plays_here=True)
    assert starts._start(started, starts._body()).status_code == 201


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_seed_whose_calls_this_process_cannot_hold_is_not_admitted(started):
    world = started["world"]
    stays._inhabited(world, started["client"])
    calls = _plan(started, 1)["calls_most"]
    body = starts._body()
    assert starts._start(started, body).status_code == 201, body
    # The process that plays it has fewer calls left than the seed's runs can make.
    _with_budget(started, max_calls=calls - 1, plays_here=False)
    assert starts._worker(started).run_once(world["workspace"]) is True
    run, result = starts._model_run(started, body["comparison_id"])
    assert (run["status"], run["failure"]) == ("failed", "comparison_bound_before_seed")
    assert result["start"]["closed_reason"] == "comparison_bound_before_seed"
    assert not started["transport"].requests, "nothing was asked"
