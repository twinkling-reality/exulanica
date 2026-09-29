"""A run's options build each input's graph and standing exclusions once, and nothing moves.

A comparison's run and its replay build every due person's options from the run's frozen input,
minute after minute; while a run of minutes holds :func:`input_memo`, the input's walking graph and
the spots nobody stands at are built once per input object, known by its navigation and targets
objects themselves, at most as many inputs as the run holds, and dropped when the run ends. Two
inputs that differ in either are never taken for one another, and a run played with the memo
records exactly what it records without it.
"""

from __future__ import annotations

import copy
import uuid
from contextlib import nullcontext

import pytest
from exulanica.world import society_comparison, society_decision_contract
from exulanica.world.society_comparison import play
from exulanica.world.society_comparison_result import replay_document, verified_replay
from exulanica.world.society_decision_contract import (
    _MEMO,
    _crowded,
    _input_graph,
    input_memo,
)
from exulanica.world.society_planner import _graph, standing_exclusions

import living_square_support as square
import test_comparison_play_goldens as goldens

DOCUMENT = square.compose(square.square_objects())


def _fewer_targets(document):
    """The same navigation object, one target fewer: other standing exclusions, the same graph."""
    return {**document, "targets": list(document["targets"][:-1])}


def _fewer_edges(document):
    """Another navigation object with one edge fewer: another graph."""
    navigation = copy.deepcopy(document["navigation"])
    navigation["edges"] = navigation["edges"][:-1]
    return {**document, "navigation": navigation}


def test_inputs_that_differ_in_targets_or_navigation_are_never_taken_for_one_another():
    fewer_targets, fewer_edges = _fewer_targets(DOCUMENT), _fewer_edges(DOCUMENT)
    # The inputs do differ where each is read, so a memo that took one for another would fail.
    assert standing_exclusions(dict(fewer_targets)) != standing_exclusions(dict(DOCUMENT))
    assert _graph(dict(fewer_edges))[2] != _graph(dict(DOCUMENT))[2]
    with input_memo(3):
        for document in (DOCUMENT, fewer_targets, fewer_edges, DOCUMENT, fewer_targets):
            assert _crowded(document) == standing_exclusions(dict(document))
            assert _input_graph(document) == _graph(dict(document))
    assert _MEMO.get() is None, "nothing is kept once the run ends"


def test_each_input_is_built_once_within_its_bound_and_again_past_it(monkeypatch):
    built: list[int] = []
    real = society_decision_contract.standing_exclusions

    def counted(document):
        built.append(id(document["targets"]))
        return real(document)

    monkeypatch.setattr(society_decision_contract, "standing_exclusions", counted)
    other = _fewer_targets(DOCUMENT)
    with input_memo(2):
        for document in (DOCUMENT, other, DOCUMENT, other):
            _crowded(document)
    assert len(built) == 2
    built.clear()
    with input_memo(1):
        for document in (DOCUMENT, other, DOCUMENT):
            _crowded(document)
    assert len(built) == 3, "past its bound the least recently read input is built again"
    built.clear()
    for _ in range(2):
        _crowded(DOCUMENT)
    assert len(built) == 2, "outside a run each is built where it is read"


@pytest.mark.parametrize("arm", ["model", "group", "routine"])
def test_a_run_played_with_the_memo_records_what_it_records_without_it(monkeypatch, arm):
    plan = goldens._plans()[arm]
    scripted = goldens._Scripted(held_back=None)
    with_memo = play(plan, scripted)
    with monkeypatch.context() as patch:
        patch.setattr(society_comparison, "input_memo", lambda _inputs: nullcontext())
        without = play(plan, scripted)
    assert goldens._digests(with_memo) == goldens._digests(without)
    stored = list(zip(with_memo.requests, with_memo.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": with_memo.minute_digests},
        "events_sha256": with_memo.events_sha256,
        "receipts": {"count": len(with_memo.receipts), "sha256": with_memo.receipts_sha256},
    }
    replayed = verified_replay(plan, stored, outcome)
    drawn = replay_document(plan, {}, arm, "0" * 64, replayed, model_name=str)
    assert drawn["run_id"] == str(uuid.UUID(str(plan.run_id)))
