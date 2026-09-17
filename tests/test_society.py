from __future__ import annotations

import uuid

from exulanica.world.society import SOCIETY_POPULATION, society_state_sha256
from exulanica.world.society_legacy import advance_society, initial_society

SOCIETY_ID = uuid.UUID("c32c5ab2-f171-4e28-93c0-3b438f90273d")
SEED = "7a" * 32


def test_society_has_128_synthetic_people_schedules_relationships_and_bounded_memory():
    state = initial_society(SOCIETY_ID, SEED)

    assert len(state["inhabitants"]) == SOCIETY_POPULATION == 128
    assert len({held["id"] for held in state["inhabitants"]}) == 128
    assert all(held["synthetic"] is True for held in state["inhabitants"])
    assert all(held["schedule"] for held in state["inhabitants"])
    assert len(state["relationships"]) == 64

    for _ in range(600):
        state, _events = advance_society(state, SEED)
    assert state["tick"] == 600
    assert all(len(held["memory"]) <= 16 for held in state["inhabitants"])


def test_society_generation_and_replay_are_byte_deterministic():
    first = initial_society(SOCIETY_ID, SEED)
    second = initial_society(SOCIETY_ID, SEED)
    assert society_state_sha256(first) == society_state_sha256(second)

    first_events = []
    second_events = []
    for _ in range(500):
        first, events = advance_society(first, SEED)
        first_events.extend(events)
        second, events = advance_society(second, SEED)
        second_events.extend(events)

    assert first == second
    assert first_events == second_events
    assert first_events
    assert all(event.document["synthetic"] is True for event in first_events)
