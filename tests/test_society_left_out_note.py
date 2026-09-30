"""A content answer says which societies at the question's place it left out, and why.

The selection executor leaves a society out of a question's content when it cannot be read under
current authorization (``SocietyLeftOut`` in ``exulanica/selection/executor.py``); the answer then
says so first, in one note, rather than answering as though its people were not there.
"""

from __future__ import annotations

import re
import uuid

from exulanica.selection import question as question_module
from exulanica.selection.executor import LeftOutSociety, SocietyLeftOut


def _left(reason: SocietyLeftOut, n: int = 1) -> LeftOutSociety:
    return LeftOutSociety(uuid.UUID(int=n), uuid.UUID(int=100 + n), reason)


def test_every_reason_has_its_words():
    assert set(question_module._SOCIETY_LEFT_OUT_WHY) == set(SocietyLeftOut)


def test_one_society_is_named_by_its_place_with_why():
    note = question_module._societies_left_out([_left(SocietyLeftOut.INPUT_UNAVAILABLE)])
    assert note == (
        "The people simulated at this place could not be read for this answer, so it leaves them "
        "out: something they are made from is not available now."
    )


def test_several_societies_are_said_as_several_and_each_reason_once():
    note = question_module._societies_left_out(
        [
            _left(SocietyLeftOut.READ_RACED, 1),
            _left(SocietyLeftOut.READ_RACED, 2),
            _left(SocietyLeftOut.INPUTS_DO_NOT_CHECK, 3),
        ]
    )
    assert note.startswith("The people of more than one society simulated at this place")
    assert note.count(question_module._SOCIETY_LEFT_OUT_WHY[SocietyLeftOut.READ_RACED]) == 1
    assert question_module._SOCIETY_LEFT_OUT_WHY[SocietyLeftOut.INPUTS_DO_NOT_CHECK] in note


def test_no_note_carries_a_digit_or_a_bracketed_label():
    """The page draws a bracketed label as a person or a place."""
    for reason in SocietyLeftOut:
        for count in (1, 2):
            note = question_module._societies_left_out([_left(reason, n) for n in range(count)])
            assert not re.search(r"\d|\[[^\]]*\]", note), note
