"""A person playing one being ("Play this one"), in memory: the decider, giving a being back, and
what a minute takes from the person's answer.

A choice names a person playing a being by account. Giving the being back records a choice naming
the same person with ``ended``: the being is decided for again as it was before the play began, by
its own earlier choice, or, with none, by whatever decides for a being no choice names (a gate's
group, or the routine), so nothing is copied. A minute takes the person's latest answer for it where
the request offers its label, else the request's idle option, ``person_no_answer``.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.world.deciders import DeciderRefused, decider, is_played, receipt_decider
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_play import answer_document, person_result

ACCOUNT = str(uuid.UUID(int=0xA1))
SUBJECT = str(uuid.UUID(int=0x5B))
MODEL = {"kind": "model", "provider": "nebius", "model_id": "m"}
PLAYED = {"kind": "person", "account_id": ACCOUNT}


def test_a_person_playing_a_being_is_named_by_account_beside_the_owner_s_requests():
    assert is_played(decider(PLAYED)) and not is_played(decider({"kind": "person"}))
    with pytest.raises(DeciderRefused, match="account"):
        decider({"kind": "person", "account_id": "Hazel"})


def _row(sequence: int, described: dict, *, ended: str | None = None) -> dict:
    role = person_role()
    document = {
        "profile": role.choice_profile,
        "choice_seq": sequence,
        role.choice_subjects: [SUBJECT],
        "decider": described,
        "chosen_by": ACCOUNT,
        **({"ended": ended} if ended else {}),
    }
    return {"document": document, "recorded_at": None}


def test_giving_a_being_back_restores_what_decided_for_it_before_the_play():
    current = SocietyModelChoiceRepository._current
    role = person_role()
    # Its own choice of a model, then a play: the person decides; given back, the model again.
    assert current(role, [_row(1, MODEL), _row(2, PLAYED)])[SUBJECT]["decider"] == PLAYED
    restored = current(role, [_row(1, MODEL), _row(2, PLAYED), _row(3, PLAYED, ended="given_back")])
    assert restored[SUBJECT]["decider"] == MODEL
    # With no own choice before, nothing is copied: no choice names it, so a gate's group or the
    # routine decides for it again.
    assert current(role, [_row(1, PLAYED), _row(2, PLAYED, ended="player_left")]) == {}


def test_a_minute_takes_the_person_s_answer_else_carries_on():
    context = {
        "options": [
            {"label": "go to the well, 6 m away", "kind": "target"},
            {"label": "say something to everyone near you", "kind": "say_all"},
            {"label": "carry on", "kind": "carry_on"},
        ]
    }
    kinds = ("say_to", "say_all")
    answered = answer_document(SUBJECT, 7, "say something to everyone near you", "Good night.")
    taken = person_result(context, "carry on", answered, line_kinds=kinds)
    assert (taken["status"], taken["reason"], taken["proposal"]["line"]) == (
        "accepted",
        "validated_choice",
        "Good night.",
    )
    assert taken["provider"]["kind"] == "person" and taken["provider"]["answer_sha256"]
    assert receipt_decider(taken) == "person"
    # No answer, or one the minute no longer offers: the being carries on, never the routine.
    for answer in (None, answer_document(SUBJECT, 7, "go to the bench", None)):
        idle = person_result(context, "carry on", answer, line_kinds=kinds)
        assert (idle["reason"], idle["proposal"]["label"], idle["provider"]["answer_sha256"]) == (
            "person_no_answer",
            "carry on",
            None,
        )
