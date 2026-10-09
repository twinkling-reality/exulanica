"""A society's event summaries name a visitor by what it is, in a society made since the crossing
module's second version, and as they always did in one that recorded the first.

Two visitors cross into a society of things through the gate, one its own program decides for and
one the world decides for, and one crossing is refused; the minute's events and the visitors'
explanations are read as stored.
"""

from __future__ import annotations

from exulanica.abilities.registry import CROSSING, CROSSING_NAMING_VISITORS
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_things import advance_things, initial_things_society

from things_society_support import SEED, SOCIETY, arrival, compose, reference, thing

GATE = thing("gate", "gate", 1, 0, 9_000, yaw=3_141_593)
WELL = thing("well", "well", 2, -4_000, 2_000)


def _crossed(modules=None):
    """The first minute of a society of things into which two visitors cross and a third, of a kind
    no shipped kind names, is refused; ``modules`` as its first input recorded them, else now."""
    document = compose((GATE, WELL))
    if modules is not None:
        document["modules"] = sorted(modules)
        document["document_sha256"] = input_sha256(document)
    state = initial_things_society(SOCIETY, SEED, document, population=6)
    planned, events = advance_purposeful_society(state, SEED, [document])
    unknown = {**reference("visitor", 1), "kind": "dragon"}
    crossings = [
        arrival(1),
        arrival(2, kind=reference("traveller", 2), decided_by="world"),
        arrival(3, kind=unknown),
    ]
    return advance_things(state, planned, SEED, document, events, crossings)


def _summaries(state, events):
    visitors = {p["id"]: p for p in state["inhabitants"] if p["came_by"] == "crossed"}
    arrived = {
        visitors[str(e.subject_id)]["crossing"].get("decided_by", "program"): e.document["summary"]
        for e in events
        if e.kind == "thing_arrived"
    }
    [refused] = [e.document["summary"] for e in events if e.kind == "arrival_refused"]
    explained = {p["explanation"]["summary"] for p in visitors.values()}
    return arrived, refused, explained


def test_a_society_names_a_visitor_by_what_it_is_and_one_made_before_as_it_did():
    state, events, _ = _crossed()
    assert CROSSING_NAMING_VISITORS in state["modules"]
    arrived, refused, explained = _summaries(state, events)
    assert arrived == {
        "program": "Visitor (from outside, decided by its own program): arrived; crossed in.",
        "world": "Traveller (from outside, decided by this world): arrived; crossed in.",
    }
    assert refused == "A visitor (from outside): not arrived; unknown kind."
    assert explained == set(arrived.values())
    # The society's own people are simulated, as ever.
    assert all(
        "(simulated)" in e.document["summary"]
        for e in events
        if e.kind not in ("thing_arrived", "arrival_refused")
    )
    # A society that recorded the first version names its visitors as it always did.
    before = [m for m in state["modules"] if m != CROSSING_NAMING_VISITORS] + [CROSSING]
    state, events, _ = _crossed(before)
    arrived, refused, explained = _summaries(state, events)
    assert arrived == {
        "program": "Visitor (simulated): arrived; crossed in.",
        "world": "Traveller (simulated): arrived; crossed in.",
    }
    assert refused == "A visitor (simulated): not arrived; unknown kind."
    assert explained == set(arrived.values())
