"""The rule the place-link measurement scores its answers by, held to right and wrong answers.

``score`` in ``scripts/measure_companion_place_link.py`` decides every verdict the outcome record
states, so each question's rule is checked here against an answer it must accept and answers it
must refuse, written in the shape ``POST /selection/ask`` returns.
"""

from __future__ import annotations

import pytest
from scripts.measure_companion_place_link import blob_id, score

PLACE = "0190a000-0000-7000-8000-00000000000b"
ELSEWHERE = "0190a000-0000-7000-8000-00000000000c"
SHA = {1: "11" * 32, 2: "22" * 32, 3: "33" * 32}
BY_BLOB = {blob_id(sha): number for number, sha in SHA.items()}
CITATIONS = {
    f"TOKEN0000{number}": f"exulanica://blob/{blob_id(sha)}/img#v=1&m=still_image&t=0,0.000000001"
    for number, sha in SHA.items()
}
DATES = {1: "2026-08-14", 2: "2026-08-16", 3: "2026-08-15"}


def body(*clauses, names=None, abstained=None, deterministic=False):
    return {
        "answer": {
            "clauses": [
                {"text": text, "type": kind, "citations": list(cited), "value_refs": []}
                for text, kind, cited in clauses
            ]
        },
        "citations": CITATIONS,
        "names": names if names is not None else {"[place A]": PLACE},
        "abstained": abstained,
        "deterministic": deterministic,
    }


def verdict(question, answer, status=200):
    return score(
        question,
        status,
        answer,
        place_entity_id=PLACE,
        by_blob=BY_BLOB,
        confirmed={1, 2},
        dates=DATES,
    )["right"]


BOTH = ("TOKEN00001", "TOKEN00002")


@pytest.mark.parametrize(
    ("answer", "right"),
    [
        (body(("The sign reads [place A].", "historical", ["TOKEN00001"])), True),
        (body(("[Place A] is written on the sign.", "historical", ["[TOKEN00002]"])), True),
        (body(("The sign reads [place A].", "historical", ["TOKEN00003"])), False),
        (body(("The sign reads [place A].", "meta", [])), False),
        (
            body(
                ("The sign reads [place A].", "historical", ["TOKEN00001"]),
                names={"[place A]": ELSEWHERE},
            ),
            False,
        ),
        (
            body(("The sign reads [place A].", "historical", ["TOKEN00001"]), deterministic=True),
            False,
        ),
    ],
)
def test_what_the_sign_says(answer, right):
    assert verdict("sign", answer) is right


@pytest.mark.parametrize(
    ("answer", "right"),
    [
        (body(("These photographs were taken at [place A].", "historical", BOTH)), True),
        (
            body(
                ("This photograph was taken at [place A].", "historical", ["TOKEN00001"]),
                ("So was this one.", "historical", ["TOKEN00002"]),
            ),
            True,
        ),
        (body(("I have no information about photographs taken there.", "meta", [])), False),
        (body(("This one was taken there.", "historical", ["TOKEN00001"])), False),
        (body(("All three were.", "historical", [*BOTH, "TOKEN00003"])), False),
        (body(("Taken there.", "historical", BOTH), abstained="UNANSWERABLE_NOT_CAPTURED"), False),
    ],
)
def test_which_photographs_were_taken_there(answer, right):
    assert verdict("which", answer) is right


@pytest.mark.parametrize(
    ("text", "right"),
    [
        ("They were taken on 14 August 2026 and 16 August 2026.", True),
        ("They were taken on 2026-08-14 and 2026-08-16.", True),
        ("They were taken on the 14th and the 16th of August.", True),
        ("They were taken on 14 August 2026.", False),
        ("They were taken on 14 August 2025 and 16 August 2025.", False),
        ("They were taken on 15 August 2026 and 16 August 2026.", False),
    ],
)
def test_when_they_were_taken(text, right):
    assert verdict("when", body((text, "historical", BOTH))) is right


def test_a_date_with_no_confirmed_photograph_cited_is_not_right():
    stated = body(("They were taken on 14 August 2026 and 16 August 2026.", "meta", []))
    assert verdict("when", stated) is False


def test_a_refused_request_is_not_right():
    assert verdict("which", {"detail": "no model credential"}, status=503) is False


def test_a_question_with_no_registered_rule_is_refused():
    with pytest.raises(ValueError, match="no rule is registered"):
        verdict("who", body(("Nobody.", "meta", [])))
