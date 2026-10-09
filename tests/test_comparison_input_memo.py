"""A run checks each input once and builds what depends on it alone once, and nothing moves.

A comparison's run and its replay read the run's frozen inputs minute after minute; while a run of
minutes holds :func:`input_memo`, each input object is checked once, and the input's walking
graph, the routes over it, the spots nobody stands at and the digest of its navigation are built
once per input, known by its navigation and targets objects themselves, at most as many inputs as
the run holds, and dropped when the run ends. Two inputs that differ in either are never taken for
one another, an input object never checked is checked where it is read, and a run played with the
memo records exactly what it records without it.
"""

from __future__ import annotations

import copy
import uuid
from contextlib import nullcontext

import pytest
from exulanica.world import society_comparison, society_planner
from exulanica.world.society_comparison import play
from exulanica.world.society_comparison_result import replay_document, verified_replay
from exulanica.world.society_decision_contract import _crowded, _input_graph, input_memo
from exulanica.world.society_planner import (
    _MEMO,
    _graph,
    _input_routes,
    _navigation_sha256,
    _paths,
    standing_exclusions,
    validate_society_input,
)

import living_square_support as square
import test_comparison_play_goldens as goldens
import test_society_things_comparison as things

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
    real = society_planner.standing_exclusions

    def counted(document):
        built.append(id(document["targets"]))
        return real(document)

    monkeypatch.setattr(society_planner, "standing_exclusions", counted)
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


def test_an_input_is_checked_once_while_a_run_holds_the_memo(monkeypatch):
    checked: list[int] = []
    real = society_planner._validate_society_input

    def counted(document):
        checked.append(id(document))
        return real(document)

    monkeypatch.setattr(society_planner, "_validate_society_input", counted)
    other = _fewer_targets(DOCUMENT)
    other["document_sha256"] = society_planner.input_sha256(other)
    with input_memo(2):
        for document in (DOCUMENT, other, DOCUMENT, other):
            validate_society_input(document)
        assert checked == [id(DOCUMENT), id(other)]
        # An object never checked is checked where it is read, and refused when it is not valid,
        # however much of a checked input it shares.
        broken = {**DOCUMENT, "input_seq": "1"}
        with pytest.raises(ValueError):
            validate_society_input(broken)
        with pytest.raises(ValueError):
            validate_society_input(broken)
    assert checked.count(id(broken)) == 2, "a refused input is never taken for checked"
    checked.clear()
    for _ in range(2):
        validate_society_input(DOCUMENT)
    assert checked == [id(DOCUMENT)] * 2, "outside a run each is checked where it is read"


def test_routes_and_the_navigation_digest_are_built_once_per_input(monkeypatch):
    walked: list[str] = []
    real = society_planner._paths

    def counted(start, adjacent):
        walked.append(start)
        return real(start, adjacent)

    monkeypatch.setattr(society_planner, "_paths", counted)
    fewer_edges = _fewer_edges(DOCUMENT)
    starts = sorted(_graph(dict(DOCUMENT))[0])[:3]
    with input_memo(2):
        for document in (DOCUMENT, fewer_edges, DOCUMENT, fewer_edges):
            adjacent = _input_graph(document)[1]
            for start in starts:
                assert _input_routes(document, start, adjacent) == _paths(start, adjacent)
            assert _navigation_sha256(document) == society_planner.society_state_sha256(
                document["navigation"]
            )
    # Each start walked once per graph inside the run.
    assert len(walked) == 2 * len(starts)
    assert _MEMO.get() is None


@pytest.mark.parametrize("arm", ["model", "group", "routine", "things"])
def test_a_run_played_with_the_memo_records_what_it_records_without_it(monkeypatch, arm):
    if arm == "things":
        plan = things._plan("model", group=things._knights(), ticks=20)
        scripted = things._Choosing()
    else:
        plan = goldens._plans()[arm]
        scripted = goldens._Scripted(held_back=None)
    with_memo = play(plan, scripted)
    if arm == "things":
        scripted = things._Choosing()
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
