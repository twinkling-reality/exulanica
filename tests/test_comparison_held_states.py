"""A run of minutes digests each minute's state once and builds each asked person's options once.

Every minute of a comparison's run names the state it began from by its digest: in each request,
in each decision's check, in its events and in a society of things' phase. While the run plays,
it holds that state (:func:`~exulanica.world.society.holding_states`) and digests it once, and it
records the digest of every state it ends a minute in. It never changes a state after holding it,
so every digest the held state serves is the state's own, and a run played holding its states
records exactly what it records without. The options a person is asked with are built once a
minute, for what may be offered to them and for their request alike.
"""

from __future__ import annotations

import contextlib
import hashlib
from collections.abc import Iterator
from typing import Any

import pytest
from exulanica.canonical import canonical_json
from exulanica.world import role_decisions, society
from exulanica.world.roles import person
from exulanica.world.society import holding_states, society_state_sha256
from exulanica.world.society_comparison import play, replay
from exulanica.world.society_comparison_result import replay_document, verified_replay

import test_comparison_play_goldens as goldens
import test_society_things_comparison as things


def _fresh(state: Any) -> str:
    return hashlib.sha256(canonical_json(state)).hexdigest()


@contextlib.contextmanager
def _holding_nothing() -> Iterator[Any]:
    """A run of minutes that holds no state: every digest is taken where it is named."""
    yield _fresh


def _plans() -> dict[str, tuple[Any, Any]]:
    """A purposeful run with a model, and a society of things' run with a model that says lines
    and takes the sword, each with the answers it is asked with."""
    return {
        "purposeful": (goldens._plans()["model"], lambda: goldens._Scripted(held_back=None)),
        "things": (things._plan("model", group=things._knights(), ticks=20), things._Choosing),
    }


def _record(played: Any) -> dict[str, Any]:
    return {
        "states": played.minute_digests,
        "events": played.events_sha256,
        "receipts": played.receipts_sha256,
        "requests": [request["document_sha256"] for request in played.requests],
    }


@pytest.mark.parametrize("family", ["purposeful", "things"])
def test_a_run_holding_its_states_records_what_it_records_without(monkeypatch, family):
    plan, asking = _plans()[family]
    held = play(plan, asking())
    with monkeypatch.context() as patch:
        patch.setattr(role_decisions, "holding_states", _holding_nothing)
        unheld = play(plan, asking())
    assert _record(held) == _record(unheld)
    assert held.minute_digests == [_fresh(state) for state in held.states]
    stored = list(zip(held.requests, held.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": held.minute_digests},
        "events_sha256": held.events_sha256,
        "receipts": {"count": len(held.receipts), "sha256": held.receipts_sha256},
    }
    drawn = replay_document(
        plan, {}, "model", "0" * 64, verified_replay(plan, stored, outcome), model_name=str
    )
    with monkeypatch.context() as patch:
        patch.setattr(role_decisions, "holding_states", _holding_nothing)
        again = replay_document(
            plan, {}, "model", "0" * 64, verified_replay(plan, stored, outcome), model_name=str
        )
    assert drawn == again


def test_every_digest_a_held_state_serves_is_the_state_s_own(monkeypatch):
    plan, asking = _plans()["things"]
    served: list[str] = []
    real = holding_states

    @contextlib.contextmanager
    def checking() -> Iterator[Any]:
        with real() as hold:
            held = society._HELD.get()
            assert held is not None

            class _Checked(dict):
                def get(self, key: int, default: Any = None) -> Any:
                    found = super().get(key, default)
                    if found is not None:
                        assert _fresh(found[0]) == found[1], (
                            "a held state changed after it was held"
                        )
                        served.append(found[1])
                    return found

            checked = _Checked(held)
            token = society._HELD.set(checked)

            def handing(state: Any) -> str:
                checked.clear()
                digest = hold(state)
                checked[id(state)] = (state, digest)
                return digest

            try:
                yield handing
            finally:
                society._HELD.reset(token)

    monkeypatch.setattr(role_decisions, "holding_states", checking)
    played = play(plan, asking())
    # The minute's requests, its decisions' check, its events and its things phase each named
    # the state the minute began from: all of them read the held digest, the genesis's too.
    assert len(served) >= 4 * len(played.states)
    assert _fresh(played.start) in served, "the first minute holds the genesis it begins from"


def test_a_held_state_is_known_by_the_object_itself():
    state = {"tick": 1, "people": [{"id": "a"}]}
    with holding_states() as hold:
        digest = hold(state)
        assert digest == _fresh(state)
        assert society_state_sha256(state) == digest
        # A copy is digested where it is named, and a different state is never taken for it.
        assert society_state_sha256(dict(state)) == digest
        assert society_state_sha256({**state, "tick": 2}) != digest
        other = {"tick": 3, "people": []}
        assert hold(other) == _fresh(other)
        # Only the state handed over last is held.
        assert society._HELD.get() == {id(other): (other, _fresh(other))}
    assert society._HELD.get() is None, "nothing is held once the run ends"


def test_each_asked_person_s_options_are_built_once_a_minute(monkeypatch):
    plan, asking = _plans()["things"]
    built: list[tuple[str, int]] = []
    real = person.options

    def counted(role, state, source, subject_id, contract, *, seed):
        built.append((subject_id, state["tick"]))
        return real(role, state, source, subject_id, contract, seed=seed)

    monkeypatch.setattr(person, "options", counted)
    played = play(plan, asking())
    asked = [(request["subject_id"], request["base_tick"]) for request in played.requests]
    assert asked, "the run asked somebody"
    assert len(built) == len(set(built)), "nobody's options are built twice in a minute"
    assert set(asked) <= set(built)
    # A replay rebuilds every request from the options built once a minute, byte for byte.
    again = replay(
        plan,
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
    )
    assert again.requests == played.requests
