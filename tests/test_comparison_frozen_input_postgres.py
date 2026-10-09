"""A comparison started from the application may freeze an earlier stored input of its society.

Through the application as deployed, as the runtime role, with a scripted model: a world's people
are brought in (the society's first input) and an object is placed after them (its second). A
comparison frozen at the first input plays runs that consume exactly that input, and one frozen at
the newest consumes both, so the two compare the same people, models and seeds with and without the
edit. Every run starts at the society's genesis: neither is a branch of the live society at the
edit's tick, and the live history is never written. An input the society does not hold is refused
by name, and one that lost its rights is answered as every society read answers it.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from exulanica.api.society_runtime import SocietyRuntime
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_repository import SocietyRepository

import test_society_comparison_start_postgres as start_tests
import test_society_stay_requests_api as stays
from test_society_saved_world_api import OWNER, place

saved_world = start_tests.saved_world
started = start_tests.started
pytestmark = pytest.mark.postgres


def _two_inputs(held: dict[str, Any]) -> int:
    """The world's people brought in, then an object placed in front of them: the society's newest
    input, its second."""
    world, client = held["world"], held["client"]
    stays._inhabited(world, client)
    place(client, world, "object:bench", 0, 4_000)
    connection = world["connection"]
    newest = connection.execute(
        "select max(input_seq) as newest from world_society_input where workspace_id=%s",
        (world["workspace"],),
    ).fetchone()["newest"]
    connection.commit()
    return int(newest)


def _read(held: dict[str, Any], comparison_id: str) -> dict[str, Any]:
    world = held["world"]
    answered = held["client"].get(
        f"{start_tests._comparisons(world)}/{comparison_id}",
        headers=OWNER,
        params=start_tests._scope(world),
    )
    assert answered.status_code == 200, answered.text
    return answered.json()


def _consumed(held: dict[str, Any], comparison_id: str, run_id: str) -> list[int]:
    """The society inputs a run's plan consumes, by sequence."""
    world = held["world"]
    comparisons = SocietyComparisonRepository(
        SocietyRepository(
            world["connection"],
            world["workspace"],
            world_id=world["binding"].world_id,
            input_authorizer=lambda _document: None,
        )
    )
    plan, _definition = comparisons.read_plan(uuid.UUID(comparison_id), uuid.UUID(run_id))
    world["connection"].commit()
    return [int(document["input_seq"]) for document in plan.inputs]


def _played(held: dict[str, Any], **changes: Any) -> dict[str, Any]:
    body = start_tests._body(**changes)
    answered = start_tests._start(held, body)
    assert answered.status_code == 201, answered.text
    assert start_tests._worker(held).run_once(held["world"]["workspace"]) is True
    return _read(held, body["comparison_id"])


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_frozen_at_an_earlier_input_plays_exactly_the_inputs_up_to_it(started):
    newest = _two_inputs(started)
    assert newest == 2, "placing an object after the people came records the second input"
    before = _played(started, input_seq=1)
    after = _played(started)
    assert before["input"]["input_seq"] == 1
    assert after["input"]["input_seq"] == newest
    assert before["input"]["document_sha256"] != after["input"]["document_sha256"]
    for result, inputs in ((before, [1]), (after, [1, 2])):
        runs = [run for seed in result["seeds"] for run in seed["runs"].values()]
        assert {run["status"] for run in runs} == {"completed"}
        for run in runs:
            assert _consumed(started, result["comparison_id"], run["run_id"]) == inputs
    # Both compare the same arms on the same seeds: only the frozen input differs.
    assert [arm["key"] for arm in before["arms"]] == [arm["key"] for arm in after["arms"]]
    assert [seed["seed_digest"] for seed in before["seeds"]] == [
        seed["seed_digest"] for seed in after["seeds"]
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_input_the_society_does_not_hold_is_refused_by_name(started):
    newest = _two_inputs(started)
    world, client = started["world"], started["client"]
    before = start_tests._counts(world)
    planned = client.get(
        start_tests._comparisons(world) + "/plan",
        headers=OWNER,
        params={
            **start_tests._scope(world),
            "role": start_tests._body()["role"],
            "group": "everyone",
            "model": f"{start_tests.MODEL.provider}/{start_tests.MODEL.model_id}",
            "input_seq": newest + 1,
        },
    )
    assert planned.status_code == 200, planned.text
    assert planned.json()["plan_refusal"]["code"] == "input_not_in_society"
    refused = start_tests._start(started, start_tests._body(input_seq=newest + 1))
    assert (refused.status_code, refused.json()["code"]) == (422, "input_not_in_society")
    assert start_tests._counts(world) == before


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_input_that_lost_its_rights_is_answered_unavailable(started, monkeypatch):
    _two_inputs(started)
    granted = SocietyRuntime.authorize

    def first_withdrawn(self, connection, session, document):
        if int(document["input_seq"]) == 1:
            raise UnavailableSocietyInput("the first input's source was withdrawn")
        return granted(self, connection, session, document)

    monkeypatch.setattr(SocietyRuntime, "authorize", first_withdrawn)
    world = started["world"]
    before = start_tests._counts(world)
    refused = start_tests._start(started, start_tests._body(input_seq=1))
    assert (refused.status_code, refused.json()["code"]) == (424, "unavailable_society_input")
    assert start_tests._counts(world) == before
    # Every run's genesis is built over the first input, so a start frozen at the newest input,
    # which keeps its rights, is refused too: none of its runs could play.
    refused = start_tests._start(started, start_tests._body())
    assert (refused.status_code, refused.json()["code"]) == (424, "unavailable_society_input")
    assert start_tests._counts(world) == before
    # The positive control: with the first input's rights back, the same start is made.
    monkeypatch.setattr(SocietyRuntime, "authorize", granted)
    assert start_tests._start(started, start_tests._body()).status_code == 201
