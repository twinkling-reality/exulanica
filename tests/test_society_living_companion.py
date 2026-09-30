"""Living-town people answers use the recorded state and events without raw engine levels."""

from __future__ import annotations

import uuid

from exulanica.selection.calls import CallLog
from exulanica.selection.inhabitant_words import inhabitant_words
from exulanica.selection.plan import SocietyAspect, SocietyScope, SocietySelector
from exulanica.selection.society_question import answer_about_society, build_scene
from exulanica.world.society_comparison import play

from test_society_living_comparison import _Choosing, _plan


def _answer(scene, aspect):
    return answer_about_society(
        scene,
        SocietySelector(scope=SocietyScope.SELECTED, aspect=aspect),
        client=None,
        saved=(),
        log=CallLog(),
        max_tokens=1000,
    )


def test_living_person_answer_before_and_after_play():
    played = play(_plan("routine"), _Choosing())
    subject = uuid.UUID(played.start["inhabitants"][0]["id"])
    for state in (played.start, played.states[-1]):
        scene = build_scene(
            {
                "society_id": uuid.UUID(state["society_id"]),
                "version_id": uuid.UUID(state["branch_id"]),
                "profile": state["profile"],
                "current_tick": state["tick"],
                "state": state,
            },
            targets=(),
            events=(),
            selected=subject,
            question="What is this person doing?",
            saved=(),
        )
        for aspect in (SocietyAspect.WHO, SocietyAspect.DOING, SocietyAspect.WHY):
            result = _answer(scene, aspect)
            assert result.answer is not None
            text = " ".join(clause.text for clause in result.answer.clauses)
            assert "[inhabitant A]" in text
            assert "of 1000" not in text
            assert "premises:" not in text


def test_living_words_name_work_and_reason_from_recorded_fields():
    said = inhabitant_words(
        {
            "ordinal": 6,
            "role": {"label": "shopkeeper"},
            "home": {"destination_id": "home"},
            "work": {"destination_id": "office"},
            "action": {"kind": "move", "reason": "following_route"},
            "goal": {"activity": "work", "reason": "shift_due", "because": "meal at 950 of 1000"},
        },
        lambda _target: None,
        lambda _partner: None,
    )
    assert (said.who, said.what, said.doing, said.why) == (
        "Resident 7",
        "A simulated shopkeeper in this town. They have a home and an assigned workplace.",
        "walking to work",
        "Their work shift is due.",
    )


def test_living_recent_answer_names_a_model_choice_from_its_decision_event():
    played = play(_plan("model"), _Choosing())
    applied = next(event for event in played.events if event.kind == "decision_applied")
    state = played.states[applied.tick - 1]
    subject = applied.subject_id
    event = {
        "event_id": str(applied.event_id),
        "tick": applied.tick,
        "event_kind": applied.kind,
        "subject_id": str(subject),
        "document": applied.document,
    }
    scene = build_scene(
        {
            "society_id": uuid.UUID(state["society_id"]),
            "version_id": uuid.UUID(state["branch_id"]),
            "profile": state["profile"],
            "current_tick": state["tick"],
            "state": state,
        },
        targets=(),
        events=(event,),
        selected=subject,
        question="What did the model choose?",
        saved=(),
    )
    result = _answer(scene, SocietyAspect.RECENT)
    assert result.answer is not None
    text = " ".join(clause.text for clause in result.answer.clauses)
    assert "A model chose for [inhabitant A]" in text
    assert "of 1000" not in text
    assert "premises:" not in text
