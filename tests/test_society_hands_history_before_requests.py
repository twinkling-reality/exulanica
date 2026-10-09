"""A society of things' history from before a person could ask for a hands act replays as it ran.

Hands requests (``exulanica.society-action-request/v2``) changed the minute's request rule, its
request events, the planner's handling of a requested wait and walk, the hands step's reasons
and the things state's check. No stored minute holds a v2 request, so a history recorded before
them must recompute byte for byte. ``fixtures/society-things-before-hands-requests.json`` was
recorded by the code before them (main 60f7b84e) running :func:`minute` below, the minute as the
repository composes it: in its first minute a person's v1 request sends a villager somewhere and
the knight's own model chooses to pick up a sword it must walk to; later its model chooses to put
the sword down, and quiet minutes follow. The fixture holds each minute's requests and sealed
receipts as stored and the digest of each minute's state and events.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from exulanica.world import society_actions
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import (
    append_role_events,
    apply_receipts,
    consumed_receipts,
)
from exulanica.world.society import society_state_sha256
from exulanica.world.society_actions import action_goal_policies, append_action_events
from exulanica.world.society_engines import society_engine
from exulanica.world.society_planner import advance_purposeful_society
from exulanica.world.society_things import advance_things, initial_things_society

from test_society_things_before_modules import _events_sha256
from things_society_support import compose, thing

HISTORY = Path(__file__).parent / "fixtures" / "society-things-before-hands-requests.json"
GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
KNIGHT = thing("knight", "knight", 1, 3_000, 3_000)
#: Far enough that the knight walks to an open node within reach first.
SWORD = thing("sword", "sword", 2, -3_000, 2_600)


def scene() -> dict[str, Any]:
    """The input every minute of the history reads."""
    return compose((GATE, KNIGHT, SWORD))


def minute(
    state: dict[str, Any],
    document: dict[str, Any],
    seed: str,
    requests: list[dict[str, Any]],
    receipts: list[dict[str, Any]],
):
    """One minute as the repository composes it: the requests' goal policies, every role's
    receipts applied over them, the planner, the requests' events and the roles' events, then the
    things phase with the receipts it consumed and, where the code takes them, the asked hands
    acts (none in a history from before requests could ask for one)."""
    roles = decision_roles().hosted_by(state["profile"])
    goal_policy, dispositions = action_goal_policies(state, document, requests)
    policies, decided = apply_receipts(roles, state, document, receipts, goal_policy)
    planned, events = advance_purposeful_society(state, seed, [document], goal_policy=policies)
    events = append_action_events(state, planned, document, requests, dispositions, events)
    if society_engine(state["profile"]).owner_model_choice:
        events = append_role_events(roles, state, planned, document, receipts, decided, events)
    applied = getattr(society_actions, "applied_hands", None)
    asked = {} if applied is None else {"asked": applied(requests, dispositions)}
    after, events, _bound = advance_things(
        state,
        planned,
        seed,
        document,
        events,
        (),
        decisions=consumed_receipts(receipts, decided),
        **asked,
    )
    return after, events


def test_a_history_from_before_hands_requests_replays_as_it_ran():
    history = json.loads(HISTORY.read_text(encoding="utf-8"))
    document = scene()
    assert document["document_sha256"] == history["input_sha256"]
    seed = history["seed"]
    state = initial_things_society(
        uuid.UUID(history["society_id"]), seed, document, population=history["population"]
    )
    kinds = []
    reasons = []
    for stored in history["minutes"]:
        state, events = minute(state, document, seed, stored["requests"], stored["receipts"])
        assert (state["tick"], society_state_sha256(state), _events_sha256(events)) == (
            stored["tick"],
            stored["state_sha256"],
            stored["events_sha256"],
        )
        kinds.extend(event.kind for event in events)
        reasons.extend(event.document.get("reason") for event in events)
    # The positive control: the history holds what hands requests changed the code for: a
    # person's request, a model's walk to a thing and its acts, and the decisions' own events.
    assert {"user_action_requested", "picked_up", "put_down"} <= set(kinds)
    assert {"chosen_by_their_model", "chose_to_pick_up", "chose_to_put_down"} <= set(reasons)
