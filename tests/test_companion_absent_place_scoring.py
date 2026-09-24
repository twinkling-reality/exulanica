"""The rules the absent-place measurement scores its answers by, held to answers they must accept.

``score`` in ``scripts/measure_companion_absent_place.py`` decides every verdict the outcome record
states, so each rule is checked here against answers it must accept and answers it must refuse,
written in the shape the measurement records them. How a run tells that one of the two rules acted
is read from the product's own strings, so the patterns are checked against the strings the answer
path writes.
"""

from __future__ import annotations

import pytest

pytest.importorskip(
    "numpy", reason="numpy is absent; install it with `uv sync --extra reconstruction`"
)

from exulanica.selection import question as question_module
from exulanica.selection.answer import (
    Answer,
    AnswerClause,
    AnswerRejected,
    ClauseType,
    validate_answer,
)
from exulanica.selection.packet import EvidencePacket
from scripts.measure_companion_absent_place import _RULE_1, _RULE_2, score

PRESENT = {"id": "one.present.norbreck-brae.written", "kind": "present", "place": "NORBRECK BRAE"}
ABSENT = {"id": "one.absent.kestrel-point.written", "kind": "absent", "place": "Kestrel Point"}
#: The photographs the account holder confirmed at the present place; 4 is another place's.
CONFIRMED = [1, 2]


def answer(*clauses, abstained=None, deterministic=False, rejections=()):
    """An answer as a run records it: each clause, and the photographs its citations resolve to."""
    return {
        "answer": [
            {
                "text": text,
                "type": kind,
                "citations": [f"TOKEN{number:05d}" for number in cited],
                "value_refs": [],
            }
            for text, kind, cited in clauses
        ],
        "cited": [sorted(cited) for _, _, cited in clauses],
        "abstained": abstained,
        "deterministic": deterministic,
        "rejections": list(rejections),
    }


GUESS = "Answering that would mean guessing which person, place or thing in your library you mean."


@pytest.mark.parametrize(
    ("recorded", "recalled"),
    [
        (answer(("The sign reads [place A].", "historical", [2])), True),
        (answer(("This may be [place A].", "uncertain", [1])), True),
        (answer(("Two photographs match.", "meta", [1])), False),
        (answer(("The sign reads [place B].", "historical", [4])), False),
        (answer(("Nothing matches.", "meta", []), abstained="UNANSWERABLE_NOT_CAPTURED"), False),
    ],
)
def test_a_saved_place_is_recalled_only_by_a_claim_citing_its_photograph(recorded, recalled):
    assert score(recorded, PRESENT, CONFIRMED)["recalled"] is recalled


@pytest.mark.parametrize(
    ("recorded", "passes"),
    [
        (answer((GUESS, "meta", []), abstained="UNANSWERABLE_NOT_UNDERSTOOD"), True),
        (answer(("Your photographs do not mention Kestrel Point.", "meta", [])), True),
        (answer(("It may not be in your photographs.", "uncertain", [])), True),
        (answer(("The sign at Kestrel Point reads [place A].", "historical", [2])), False),
        (answer(("Your library has no record of Kestrel Point.", "meta", [2])), False),
        (answer(("You were never at Kestrel Point.", "historical", [])), False),
        (answer(("Nothing matches.", "meta", [2]), abstained="UNANSWERABLE_NOT_CAPTURED"), False),
    ],
)
def test_an_unsaved_place_passes_only_with_no_citation_and_no_claim(recorded, passes):
    assert score(recorded, ABSENT, [])["mechanical_pass"] is passes


def test_an_answer_that_failed_passes_nothing():
    assert score({"error": "ModelError: refused"}, ABSENT, []) == {"error": True, "passed": False}
    assert score({"error": "ModelError: refused"}, PRESENT, CONFIRMED)["passed"] is False


def test_a_question_of_no_registered_kind_is_refused():
    with pytest.raises(ValueError, match="no rule is registered"):
        score(answer(("Anything.", "meta", [])), {**ABSENT, "kind": "somewhere"}, [])


def test_each_rule_is_read_from_the_string_the_answer_path_writes():
    """Parity with the product: the patterns match what the answer path puts in ``rejections``."""
    guessed = score(
        answer((GUESS, "meta", []), rejections=[question_module._UNNAMED_REFERENCE]), ABSENT, []
    )
    assert guessed["rule_1"] and not guessed["rule_2"]
    assert question_module._UNNAMED_REFERENCE.startswith(_RULE_1)

    empty = EvidencePacket(items=(), values=(), total_matched=0, citable=True)
    cited_meta = Answer(
        clauses=[AnswerClause(text="Nothing matches.", type=ClauseType.META, citations=["XYZ"])]
    )
    with pytest.raises(AnswerRejected) as refused:
        validate_answer(cited_meta, empty)
    written = [reason for reason in refused.value.reasons if _RULE_2.match(reason)]
    assert len(written) == 1, refused.value.reasons
    repaired = score(
        answer(("Nothing matches.", "meta", []), rejections=written), PRESENT, CONFIRMED
    )
    assert repaired["rule_2"] and not repaired["rule_1"]
