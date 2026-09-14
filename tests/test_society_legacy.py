"""Frozen v1 compatibility and characterization, using pure synthetic fixtures."""

import uuid
from copy import deepcopy

from exulanica.world.society import advance_society, initial_society, society_state_sha256

SOCIETY_ID = uuid.UUID("c32c5ab2-f171-4e28-93c0-3b438f90273d")
SEED = "7a" * 32


def test_v1_digest_vectors_remain_exact():
    state = initial_society(SOCIETY_ID, SEED)
    assert (
        society_state_sha256(state)
        == "78d042d3c2ea21d2feb77a52a7bf6e6d6fde5b8f791af5a0a2ce11377fd9a418"
    )
    for tick in range(1, 501):
        state, _ = advance_society(state, SEED)
        if tick == 1:
            assert (
                society_state_sha256(state)
                == "4f1c3f62f431377c89ba8ebe1e8686e058fc301f9518987d0efcc0a4a90bc4d6"
            )
    assert (
        society_state_sha256(state)
        == "be86f3c69d40865f78d98d42fb34838a5001dd1f96e8ce5f830330679c8850a4"
    )


def test_v1_motion_is_independent_of_destination_and_has_no_arrival():
    state = initial_society(SOCIETY_ID, SEED)
    other = deepcopy(state)
    other["inhabitants"][0]["destination"] = "nonexistent:unreachable"
    stepped, events = advance_society(state, SEED)
    changed, _ = advance_society(other, SEED)
    assert stepped["inhabitants"][0]["position_mm"] == changed["inhabitants"][0]["position_mm"]
    assert stepped["inhabitants"][0]["position_mm"] != state["inhabitants"][0]["position_mm"]
    assert events == ()


def test_v1_transition_does_not_mutate_caller_and_population_is_not_view_budget():
    state = initial_society(SOCIETY_ID, SEED, population=512)
    before = deepcopy(state)
    stepped, _ = advance_society(state, SEED)
    assert before == state
    assert len(stepped["inhabitants"]) == 512
    assert [p["id"] for p in stepped["inhabitants"]] == [p["id"] for p in state["inhabitants"]]
