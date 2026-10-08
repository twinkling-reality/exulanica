"""A society of things made before societies recorded their ability modules replays as it ran.

``fixtures/society-things-before-modules.json`` was recorded by the code before the modules (THINGS
3a3.2): a knight beside a gate whose model says a line every minute and a visitor crossing in, with
each minute's receipts and crossings as stored and the digest of each minute's state and events.
Every later change must recompute those minutes byte for byte: a society whose first input names no
modules gains no hands, keeps no model, speaker name or own lines, and records what it recorded.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from exulanica.canonical import canonical_json
from exulanica.world.crossings import Crossing
from exulanica.world.role_decisions import DecisionDisposition
from exulanica.world.society import society_state_sha256
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_things import advance_things, initial_things_society

from things_society_support import compose, thing

HISTORY = Path(__file__).parent / "fixtures" / "society-things-before-modules.json"
GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)


def _stored_input():
    """The input as it was stored: the same composition, recording no modules."""
    document = compose((GATE, KNIGHT))
    document.pop("modules", None)
    document.pop("document_sha256")
    document["document_sha256"] = input_sha256(document)
    return document


def _events_sha256(events) -> str:
    return hashlib.sha256(
        canonical_json(
            [
                {
                    "event_id": str(e.event_id),
                    "tick": e.tick,
                    "kind": e.kind,
                    "subject_id": str(e.subject_id),
                    "object_id": None if e.object_id is None else str(e.object_id),
                    "document": e.document,
                }
                for e in events
            ]
        )
    ).hexdigest()


def test_a_society_of_things_made_before_its_modules_were_recorded_replays_as_it_ran():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    document = _stored_input()
    assert document["document_sha256"] == history["input_sha256"]
    seed = history["seed"]
    state = initial_things_society(
        uuid.UUID(history["society_id"]), seed, document, population=history["population"]
    )
    assert "modules" not in state
    said = 0
    for minute in history["minutes"]:
        decisions = [
            (stored["receipt"], DecisionDisposition(**stored["disposition"]))
            for stored in minute["decisions"]
        ]
        crossings = [
            Crossing(uuid.UUID(stored["crossing_id"]), stored["document"])
            for stored in minute["crossings"]
        ]
        planned, events = advance_purposeful_society(state, seed, [document])
        state, events, _bound = advance_things(
            state, planned, seed, document, events, crossings, decisions=decisions
        )
        assert (state["tick"], society_state_sha256(state), _events_sha256(events)) == (
            minute["tick"],
            minute["state_sha256"],
            minute["events_sha256"],
        )
        said += sum(1 for e in events if e.kind == "said")
    # The positive control: the history says lines, which a later change could record otherwise.
    assert said == sum(minute["said"] for minute in history["minutes"]) > 0
