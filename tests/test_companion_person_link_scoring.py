"""The rules the person-link measurement scores its answers by, held to answers they must read.

``scripts/measure_companion_person_link.py`` scores every answer mechanically before the measurer
reads any, and its pre-registration binds the rules; these are the cases each rule must decide.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

# The measuring script reuses the absent-place measurement's pairing, whose module draws its corpus
# with numpy.
pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

import measure_companion_person_link as measure

QUESTION = {"id": "person/p/which", "kind": "person", "expected": [1, 2, 3]}


def _answer(clauses, cited, **over):
    answer = {
        "answer": [{"text": text, "type": kind, "citations": []} for text, kind in clauses],
        "cited": cited,
        "abstained": None,
        "deterministic": False,
        "rejections": [],
        "calls": [{"role": measure.COMPOSER_ROLE}],
    }
    answer.update(over)
    return answer


def test_an_answer_citing_a_linked_photograph_passes():
    verdict = measure.score(
        _answer([("[person A] is in this photograph.", "historical")], [[2]]), QUESTION
    )
    assert verdict["passed"] and verdict["flagged"] == []


def test_an_answer_citing_a_photograph_not_linked_fails():
    verdict = measure.score(
        _answer([("[person A] is in these.", "historical")], [[2, 6]]), QUESTION
    )
    assert verdict["recalled"] and not verdict["only_expected"] and not verdict["passed"]


def test_a_meta_clause_citing_a_linked_photograph_is_not_recall():
    verdict = measure.score(_answer([("Three photographs matched.", "meta")], [[1]]), QUESTION)
    assert not verdict["passed"]


def test_an_abstention_and_an_error_fail():
    assert not measure.score(_answer([], [], abstained="UNANSWERABLE_NOT_CAPTURED"), QUESTION)[
        "passed"
    ]
    assert not measure.score({"error": "Timeout"}, QUESTION)["passed"]


@pytest.mark.parametrize(
    "text",
    [
        "[person A] is visible on the pier.",
        "[Person A] can be seen holding a cup.",
        "[person A] appears in this photograph.",
        "I recognised [person A] here.",
    ],
)
def test_a_clause_saying_a_person_was_seen_is_flagged_for_reading(text):
    assert measure.score(_answer([(text, "historical")], [[1]]), QUESTION)["flagged"] == [0]


def test_a_clause_restating_the_link_is_not_flagged():
    text = "This photograph is of [person A], and [person A] is in two more."
    assert measure.score(_answer([(text, "historical")], [[1]]), QUESTION)["flagged"] == []


def test_the_splits_share_nothing_and_every_person_question_expects_their_photographs():
    measure._refuse_overlaps()
    for split, spec in measure.SPLITS.items():
        for question in measure.questions(split):
            if question["kind"] == "person":
                assert question["expected"] == list(spec["people"][question["person"]])


def test_a_run_neither_arm_composed_is_not_scored():
    """Both arms abstained before the composer: the change was never asked, so nothing counts."""
    before_composer = {"calls": [{"role": "structured_extraction"}]}
    answers = []
    for run in (1, 2):
        for arm in ("baseline", "change"):
            composed = run == 2
            answer = _answer(
                [("[person A] is in this photograph.", "historical")] if composed else [],
                [[1]] if composed else [],
                abstained=None if composed else "UNANSWERABLE_NOT_CAPTURED",
            )
            if not composed:
                answer.update(before_composer)
            answers.append({"run": run, "question": QUESTION["id"], "arm": arm, **answer})
    counted = measure.tally({"questions": [QUESTION], "answers": answers})
    assert counted["per_question"][QUESTION["id"]] == {"scored_runs": 1, "baseline": 1, "change": 1}
