"""A saved world's v2 society recorded before its routine moved to data replays byte for byte.

``tests/fixtures/society-v2-history/recorded.json`` is what the product stored for one society on
the tree it names (``recorded_on``), before any routine was recorded in an input: a starter world
with the small square placed in front of where a person arrives, eight inhabitants brought in with
the browser's seed, and thirty minutes advanced through the routes a browser calls, with a directed
request, an edit that adds an object, and everyone sent away and brought back on the way.
``capture.py.txt`` beside it is the driver that recorded it, as it ran.

The test regenerates that history from its genesis input the way the repository's replay does,
minute by minute, and holds every state digest and every minute's events to what was stored. An
input that records no routine must keep meaning what it meant when it was recorded.
"""

from __future__ import annotations

import json
import uuid
from itertools import pairwise
from pathlib import Path
from typing import Any

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import action_goal_policies, append_action_events
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    ordered_events_document,
    validate_input_successor,
    validate_society_input,
)
from exulanica.world.society_presence import change_presence

HISTORY = Path(__file__).parent / "fixtures" / "society-v2-history" / "recorded.json"


def _history() -> dict[str, Any]:
    return json.loads(HISTORY.read_text(encoding="utf-8"))


def replay(history: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Every minute of a recorded history regenerated, as (final state, per-minute receipts)."""
    society = history["society"]
    documents = [row["document"] for row in history["inputs"]]
    validate_society_input(documents[0])
    for previous, current in pairwise(documents):
        validate_input_successor(previous, current)
    state = initial_purposeful_society(
        uuid.UUID(society["society_id"]),
        society["seed"],
        documents[0],
        population=society["population_size"],
    )
    presences = {row["tick"]: row["document"] for row in history["presences"]}
    receipts = []
    for transition in history["transitions"]:
        previous = state
        inputs = documents[transition["from_input_seq"] - 1 : transition["to_input_seq"]]
        requests = [
            row["document"]
            for row in history["actions"]
            if row["document"]["base_tick"] == state["tick"]
        ]
        if transition["tick"] in presences:
            state, events = change_presence(
                state,
                society["seed"],
                inputs,
                presences[transition["tick"]],
                population=society["population_size"],
            )
        else:
            policies, dispositions = action_goal_policies(state, inputs[-1], requests)
            state, events = advance_purposeful_society(
                state, society["seed"], inputs, goal_policy=policies
            )
            events = append_action_events(
                previous, state, inputs[-1], requests, dispositions, events
            )
        receipts.append(
            {
                "tick": state["tick"],
                "previous_state_sha256": society_state_sha256(previous),
                "state_sha256": society_state_sha256(state),
                "event_ids": [str(event.event_id) for event in events],
                "events_sha256": society_state_sha256(ordered_events_document(events)),
            }
        )
    return state, receipts


def test_the_recorded_history_covers_what_it_says():
    history = _history()
    assert history["society"]["engine_version"] == "exulanica-society/v2"
    assert [row["document"]["profile"] for row in history["inputs"]] == [
        "exulanica.society-input/authored-ground-v2"
    ] * 2
    assert [row["disposition"] for row in history["actions"]] == ["applied"]
    assert [row["document"]["presence"] for row in history["presences"]] == ["away", "here"]
    assert len(history["transitions"]) == history["society"]["current_tick"] == 30


def test_a_v2_society_recorded_before_routines_replays_byte_for_byte():
    history = _history()
    state, receipts = replay(history)
    stored = [{key: row[key] for key in receipts[0]} for row in history["transitions"]]
    for regenerated, recorded in zip(receipts, stored, strict=True):
        assert regenerated == recorded, f"minute {recorded['tick']} does not replay"
    assert sum(len(receipt["event_ids"]) for receipt in receipts) == history["event_count"]
    assert society_state_sha256(state) == history["society"]["state_sha256"]
    assert state == history["society"]["state"]


def test_the_replay_notices_a_changed_minute():
    """A positive control: the comparison above fails when one recorded minute differs."""
    history = _history()
    history["transitions"][7]["state_sha256"] = "0" * 64
    _, receipts = replay(history)
    stored = [{key: row[key] for key in receipts[0]} for row in history["transitions"]]
    with pytest.raises(AssertionError):
        assert receipts == stored
