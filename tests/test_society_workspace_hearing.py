"""Recorded speech versions govern whether workspace-kind offers reach the hearing read."""

from __future__ import annotations

import copy

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_decision_contract import choice_options
from exulanica.world.society_planner import advance_purposeful_society, input_sha256
from exulanica.world.society_things import advance_things, initial_things_society

from test_society_made_kinds import _contract, _made, _placed
from test_society_things import _receipt
from things_society_support import SEED, SOCIETY, compose, thing


def _scene(version=2, *, hears=True, distance=2000):
    digest, form = _made("horse")
    if not hears:
        form = copy.deepcopy(form)
        form["offers"] = [o for o in form["offers"] if o["key"] != "hear"]
    knight = thing("speaker", "knight", 1, 3000, 3000)
    recipient = _placed("recipient", digest, 4000, 3000)
    document = compose((knight, recipient), made_kinds={digest: form})
    document["modules"] = sorted(
        m.replace("say/v2", f"say/v{version}") for m in document["modules"]
    )
    document["document_sha256"] = input_sha256(document)
    state = initial_things_society(SOCIETY, SEED, document, population=1)
    speaker = next(p for p in state["inhabitants"] if p["placed_id"] == "speaker")
    recipient = next(p for p in state["inhabitants"] if p["placed_id"] == "recipient")
    recipient["position_mm"] = [speaker["position_mm"][0] + distance, speaker["position_mm"][1]]
    option = next(
        o
        for o in choice_options(state, document, speaker["id"], _contract(), seed=SEED)
        if o.kind == "say_all"
    )
    return state, document, speaker, recipient, _receipt(speaker, option, line="Hello from nearby.")


def _minute(state, document, receipt, before=None):
    planned, events = advance_purposeful_society(
        state, SEED, [document] if before is None else [before, document]
    )
    return advance_things(state, planned, SEED, document, events, (), decisions=[receipt])


@pytest.mark.parametrize(
    ("version", "hears", "distance", "expected"),
    [
        (1, True, 2000, False),
        (2, True, 2000, True),
        (2, False, 2000, False),
        (2, True, 8001, False),
        (2, True, 8000, True),
    ],
)
def test_hearing_uses_recorded_version_offers_and_actual_range(version, hears, distance, expected):
    state, document, _speaker, recipient, receipt = _scene(version, hears=hears, distance=distance)
    after, events, _ = _minute(state, document, receipt)
    said = next(e for e in events if e.kind == "said")
    assert (recipient["id"] in said.document["thing"]["heard_by"]) is expected
    heard = next(p for p in after["inhabitants"] if p["id"] == recipient["id"]).get("heard", [])
    assert bool(heard) is expected


def test_a_departed_workspace_being_cannot_hear_even_with_prior_run_form():
    state, document, _speaker, recipient, receipt = _scene()
    gone = compose(
        (thing("speaker", "knight", 1, 3000, 3000),),
        input_seq=2,
        edit_seq=document["authored_state"]["edit_seq"] + 1,
    )
    after, events, _ = _minute(state, gone, receipt, before=document)
    assert recipient["id"] not in {p["id"] for p in after["inhabitants"]}
    said = next(e for e in events if e.kind == "said")
    assert recipient["id"] not in said.document["thing"]["heard_by"]


@pytest.mark.parametrize("version", [1, 2])
def test_the_recorded_version_replays_same_state_and_event_bytes(version):
    state, document, _speaker, _recipient, receipt = _scene(version)
    a, ea, _ = _minute(copy.deepcopy(state), document, receipt)
    b, eb, _ = _minute(copy.deepcopy(state), document, receipt)
    assert society_state_sha256(a) == society_state_sha256(b)
    assert [e.document for e in ea] == [e.document for e in eb]


def test_shipped_hearers_still_hear_a_workspace_speaker():
    state, document, speaker, recipient, _ = _scene()
    option = next(
        o
        for o in choice_options(state, document, recipient["id"], _contract(), seed=SEED)
        if o.kind == "say_all"
    )
    after, events, _ = _minute(state, document, _receipt(recipient, option, line="I heard you."))
    said = next(e for e in events if e.kind == "said")
    assert speaker["id"] in said.document["thing"]["heard_by"]
    assert (
        next(p for p in after["inhabitants"] if p["id"] == speaker["id"])["heard"][-1]["line"]
        == "I heard you."
    )
