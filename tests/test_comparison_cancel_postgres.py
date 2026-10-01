"""A comparison started from the application is cancelled once, stops before its next dispatch,
keeps what it paid for, and is never played again; its runs say whether a host is playing them.

Through the application as deployed, as the runtime role, with a scripted model: a start nobody
holds closes at the cancellation itself, asking nothing; a start a host is playing stops at the
host's next dispatch, its minute in flight answered and recorded; a start whose host's lease ran
out closes with what that host may have spent presumed, as a takeover presumes it. A repeated
cancel changes nothing, a finished start keeps its own closing, only whoever may start one cancels
it, and another workspace learns nothing.
"""

from __future__ import annotations

import threading
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.db.session import set_workspace
from exulanica.orchestration.compare import comparison_body
from exulanica.world.comparison_facts import ComparisonFacts
from exulanica.world.society_comparison_start_repository import SocietyComparisonStarts

import test_society_comparison_postgres as compared
import test_society_comparison_start_postgres as start_tests
import test_society_stay_requests_api as stays
from comparison_support import SEEDS
from test_society_saved_world_api import OWNER

saved_world = start_tests.saved_world
started = start_tests.started
pytestmark = pytest.mark.postgres


def _cancel(held: dict[str, Any], comparison_id: str, headers=OWNER, world=None):
    world = world or held["world"]
    return held["client"].post(
        f"{start_tests._comparisons(world)}/{comparison_id}/cancel",
        headers=headers,
        params=start_tests._scope(held["world"]),
    )


def _result(held: dict[str, Any], comparison_id: str) -> dict[str, Any]:
    world = held["world"]
    read = held["client"].get(
        f"{start_tests._comparisons(world)}/{comparison_id}",
        headers=OWNER,
        params=start_tests._scope(world),
    )
    assert read.status_code == 200, read.text
    return read.json()


def _runs(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {run["run_id"]: run for seed in result["seeds"] for run in seed["runs"].values()}


def _cancellations(world: dict[str, Any]) -> int:
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    return connection.execute(
        "select count(*) as n from comparison_cancellation where workspace_id=%s",
        (world["workspace"],),
    ).fetchone()["n"]


def _receipts(world: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    return connection.execute(
        "select base_tick, receipt from society_comparison_decision where workspace_id=%s "
        "and run_id=%s order by decision_seq",
        (world["workspace"], uuid.UUID(run_id)),
    ).fetchall()


def _start_row(world: dict[str, Any], comparison_id: str) -> dict[str, Any]:
    connection = world["connection"]
    starts = SocietyComparisonStarts(connection, world["workspace"])
    row = starts.read(world["binding"].world_id, [uuid.UUID(comparison_id)])[
        uuid.UUID(comparison_id)
    ]
    connection.commit()
    return row


def _begun(held: dict[str, Any], *, inhabit: bool = True, **changes: Any) -> str:
    if inhabit:
        stays._inhabited(held["world"], held["client"])
    body = start_tests._body(**changes)
    answered = start_tests._start(held, body)
    assert answered.status_code == 201, answered.text
    return body["comparison_id"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_waiting_start_is_closed_by_its_cancellation_and_asks_nothing(started):
    """The cancel route never calls a model: its operation is described as spending nothing,
    though it takes the grants a start takes."""
    comparison_id = _begun(started)
    answered = _cancel(started, comparison_id)
    assert answered.status_code == 200, answered.text
    (listed,) = answered.json()["comparisons"]
    assert listed["start"]["state"] == "closed"
    assert listed["start"]["closed_reason"] == "comparison_cancelled"
    assert listed["start"]["cancel"]["requested_at"]
    assert Decimal(listed["start"]["presumed_usd"]) == 0
    result = _result(started, comparison_id)
    assert {run["status"] for run in _runs(result).values()} == {"failed"}
    assert {run["failure"] for run in _runs(result).values()} == {"comparison_cancelled"}
    assert all(run["progress"] is None for run in _runs(result).values())
    # Nothing is played again: no host claims a closed start, and no model was ever asked.
    assert start_tests._worker(started).run_once(started["world"]["workspace"]) is False
    assert started["transport"].requests == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_repeated_cancel_changes_nothing_and_a_finished_start_keeps_its_closing(started):
    comparison_id = _begun(started)
    first = _cancel(started, comparison_id).json()
    again = _cancel(started, comparison_id)
    assert again.status_code == 200, again.text
    assert again.json() == first
    assert _cancellations(started["world"]) == 1
    # A start that finished on its own is not cancelled after the fact.
    finished = _begun(started, inhabit=False)
    assert start_tests._worker(started).run_once(started["world"]["workspace"]) is True
    before = _result(started, finished)
    assert before["start"]["state"] == "finished" and before["start"]["closed_reason"] is None
    late = _cancel(started, finished)
    assert late.status_code == 200, late.text
    (listed,) = late.json()["comparisons"]
    assert listed["start"]["state"] == "finished"
    assert listed["start"]["closed_reason"] is None
    assert listed["start"]["cancel"] is None
    assert _cancellations(started["world"]) == 1


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_host_stops_before_its_next_dispatch_and_keeps_the_minute_it_paid_for(started):
    comparison_id = _begun(started)
    world, transport = started["world"], started["transport"]
    cancelled_at: list[int] = []
    once = threading.Lock()
    post = transport.post_json

    def cancelling(url, *, headers, payload, timeout):
        # The model's first ask: the comparison is cancelled while this minute is in flight. A
        # minute's asks run at once, so only the first thread to arrive cancels.
        with once:
            if not cancelled_at:
                cancelled_at.append(len(transport.requests))
                facts = ComparisonFacts(
                    world["connection"], world["workspace"], world["binding"].world_id, "society"
                )
                facts.cancel(uuid.UUID(comparison_id), world["session"].actor)
                world["connection"].commit()
        return post(url, headers=headers, payload=payload, timeout=timeout)

    transport.post_json = cancelling
    assert start_tests._worker(started).run_once(world["workspace"]) is True
    result = _runs(_result(started, comparison_id))
    stopped = [run for run in result.values() if run["failure"] is not None]
    assert {run["failure"] for run in stopped} == {"comparison_cancelled"}
    asked = [run for run in stopped if _receipts(world, run["run_id"])]
    assert len(asked) == 1, "one model run was asking when the comparison was cancelled"
    receipts = _receipts(world, asked[0]["run_id"])
    # Everything it sent is recorded, and all of it belongs to the one minute in flight.
    assert len({row["base_tick"] for row in receipts}) == 1
    assert len(transport.requests) == sum(
        len(row["receipt"]["provider"]["calls"]) for row in receipts if row["receipt"]["provider"]
    )
    start = _result(started, comparison_id)["start"]
    assert (start["state"], start["closed_reason"]) == ("closed", "comparison_cancelled")
    assert start_tests._worker(started).run_once(world["workspace"]) is False


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_whose_host_lease_ran_out_is_cancelled_with_its_presumed_spend(started):
    comparison_id = _begun(started)
    world = started["world"]
    connection = world["connection"]
    starts = SocietyComparisonStarts(connection, world["workspace"])
    claim = starts.claim()
    assert claim is not None and str(claim.comparison_id) == comparison_id
    connection.execute(
        "update society_comparison_start "
        "set lease_expires_at=clock_timestamp()-interval '1 second' "
        "where workspace_id=%s and comparison_id=%s",
        (world["workspace"], uuid.UUID(comparison_id)),
    )
    connection.commit()
    answered = _cancel(started, comparison_id)
    assert answered.status_code == 200, answered.text
    (listed,) = answered.json()["comparisons"]
    assert (listed["start"]["state"], listed["start"]["closed_reason"]) == (
        "closed",
        "comparison_cancelled",
    )
    # The host whose lease ran out may have been asking a minute of its runs, never recorded.
    assert Decimal(listed["start"]["presumed_usd"]) > 0
    assert _start_row(world, comparison_id)["lease_token"] is None


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_whoever_may_start_one_cancels_and_another_workspace_learns_nothing(started):
    comparison_id = _begun(started)
    for headers in (start_tests.WRITER, start_tests.READER):
        # Addressed by an id, the route answers a credential that may not use it as it answers
        # an unknown id, as the start route does, so it is no existence oracle.
        refused = _cancel(started, comparison_id, headers=headers)
        assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    other = _cancel(started, comparison_id, headers=start_tests.OTHER)
    invented = _cancel(started, str(uuid.uuid4()), headers=start_tests.OTHER)
    assert other.status_code == invented.status_code == 404
    assert other.json() == invented.json()
    assert _cancellations(started["world"]) == 0
    assert _result(started, comparison_id)["start"]["state"] == "waiting"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_comparison_the_local_command_ran_is_not_cancelled_here(started):
    world, client = started["world"], started["client"]
    comparison_id, _transport = compared._compared(world, client)
    answered = _cancel(started, str(comparison_id))
    assert (answered.status_code, answered.json()["code"]) == (409, "comparison_not_started")
    assert _cancellations(world) == 0


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_run_not_yet_reserved_states_no_progress(started):
    """A comparison the local command defined and has not reserved runs for: it is read, and its
    runs, which have no id yet, state no progress."""
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    runner = compared._runner(world, client.app.state.services, compared._Chooser())
    comparison_id = uuid.uuid4()
    runner.define(
        world["binding"].version_id,
        comparison_id=comparison_id,
        body=comparison_body(runner, compared._models(), SEEDS, control=False),
    )
    runs = [
        run
        for seed in _result(started, str(comparison_id))["seeds"]
        for run in seed["runs"].values()
    ]
    assert runs and all(run["run_id"] is None and run["progress"] is None for run in runs)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_run_being_played_reads_running_and_one_waiting_its_turn_reads_queued(started):
    comparison_id = _begun(started)
    world, transport = started["world"], started["transport"]
    seen: list[dict[str, Any]] = []
    once = threading.Lock()
    post = transport.post_json

    def reading(url, *, headers, payload, timeout):
        # Read once, by the first of a minute's asks to arrive, while the run is being played.
        with once:
            if not seen:
                seen.append(_runs(_result(started, comparison_id)))
        return post(url, headers=headers, payload=payload, timeout=timeout)

    transport.post_json = reading
    waiting = _runs(_result(started, comparison_id))
    assert {run["progress"]["state"] for run in waiting.values()} == {"queued"}
    assert start_tests._worker(started).run_once(world["workspace"]) is True
    (during,) = seen
    running = [run for run in during.values() if (run["progress"] or {}).get("state") == "running"]
    assert running and all(run["progress"]["started_at"] for run in running)
    assert all(run["status"] == "incomplete" for run in running)
    after = _runs(_result(started, comparison_id))
    assert all(run["progress"] is None for run in after.values())


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_cancelled_start_whose_host_stopped_is_closed_by_the_next_claim_with_its_spend(started):
    comparison_id = _begun(started)
    world = started["world"]
    connection = world["connection"]
    claim = SocietyComparisonStarts(connection, world["workspace"]).claim()
    assert claim is not None and str(claim.comparison_id) == comparison_id
    connection.commit()
    # A host holds the start: the cancellation is recorded, and that host is the one to close it.
    answered = _cancel(started, comparison_id)
    assert answered.status_code == 200, answered.text
    (listed,) = answered.json()["comparisons"]
    assert listed["start"]["state"] == "running"
    assert listed["start"]["cancel"]["requested_at"]
    assert listed["start"]["closed_reason"] is None
    # It stops without closing it, and its lease runs out.
    connection.execute(
        "update society_comparison_start "
        "set lease_expires_at=clock_timestamp()-interval '1 second' "
        "where workspace_id=%s and comparison_id=%s",
        (world["workspace"], uuid.UUID(comparison_id)),
    )
    connection.commit()
    assert start_tests._worker(started).run_once(world["workspace"]) is True
    start = _result(started, comparison_id)["start"]
    assert (start["state"], start["closed_reason"]) == ("closed", "comparison_cancelled")
    # What the stopped host may have been asking is presumed, and nobody was asked again.
    assert Decimal(start["presumed_usd"]) > 0
    assert started["transport"].requests == []
    runs = _runs(_result(started, comparison_id))
    assert {run["failure"] for run in runs.values()} == {"comparison_cancelled"}
