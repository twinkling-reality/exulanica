"""A world's moments, formed from one minute's society records by the versioned rule (no database).

The rule says which records a person would tell: a line said to someone (the first between two
characters a meeting), a line said to everyone near, a decision to go somewhere or leave, a thing
handed over; never a routine's moves, waiting or carrying on. Synthetic societies only.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from exulanica.world.society import SocietyEvent
from exulanica.world.society_moments import (
    RULES_PROFILE,
    form_moments,
    load_rules,
    merge_moments,
    moment_id_of,
    place_of,
    scene_of,
)

RULES = load_rules()
VERSION = uuid.UUID("11111111-1111-4111-8111-111111111111")
TEO = uuid.UUID("22222222-2222-4222-8222-222222222222")
INES = uuid.UUID("33333333-3333-4333-8333-333333333333")
MARCO = uuid.UUID("44444444-4444-4444-8444-444444444444")
FAR = uuid.UUID("55555555-5555-4555-8555-555555555555")


class Known:
    """The moments written before, as the rule asks them."""

    def __init__(self, met: set[frozenset[uuid.UUID]] | None = None, went: dict | None = None):
        self.pairs = met or set()
        self.went = went or {}

    def met(self, first: uuid.UUID, second: uuid.UUID) -> bool:
        return frozenset((first, second)) in self.pairs

    def last_went(self, subject: uuid.UUID) -> int | None:
        return self.went.get(subject)


def _person(person: uuid.UUID, x: int, y: int, **more) -> dict:
    return {
        "id": str(person),
        "position_mm": [x, y],
        "motion_path_mm": [[x - 500, y], [x, y]],
        "action": {"kind": "rest", "target_id": "bench-thing", "activity": "resting on a bench"},
        "goal": {"partner_id": None},
        **more,
    }


STATE = {
    "tick": 412,
    "inhabitants": [
        _person(TEO, 1000, 1000),
        _person(INES, 1800, 1000),
        _person(MARCO, 9000, 1000),
        _person(FAR, 90000, 1000),
    ],
    "things": [
        {"id": "bench-thing", "placed_id": "bench-1", "position_mm": [1500, 1400]},
        {"id": "lamp-thing", "placed_id": "lamp-1", "position_mm": [30000, 1400]},
        {"id": "held-thing", "placed_id": None, "position_mm": [1000, 1000]},
    ],
}


def _event(kind: str, subject: uuid.UUID, number: int, **document) -> SocietyEvent:
    return SocietyEvent(
        event_id=uuid.UUID(int=number),
        tick=412,
        kind=kind,
        subject_id=subject,
        object_id=None,
        document=document,
    )


def _said(
    subject: uuid.UUID, to: uuid.UUID | None, number: int, decider: str = "model"
) -> SocietyEvent:
    return _event(
        "said",
        subject,
        number,
        thing={
            "request_id": str(uuid.UUID(int=900 + number)),
            "line": "Morning, Ines.",
            "to": None if to is None else str(to),
            "decider": decider,
            **({"model": {"provider": "nebius", "model_id": "nano"}} if decider == "model" else {}),
        },
    )


def _decided(subject: uuid.UUID, number: int, origin: str = "model") -> SocietyEvent:
    return _event(
        "decision_applied",
        subject,
        number,
        origin=origin,
        disposition="applied",
        request_id=str(uuid.UUID(int=700 + number)),
        model={"provider": "nebius", "model_id": "super"} if origin == "model" else None,
    )


def _form(events, known=None, options=None):
    return form_moments(RULES, VERSION, STATE, events, known or Known(), options or {})


def test_the_first_line_between_two_characters_is_a_meeting_and_a_later_one_is_speech():
    (first,) = _form([_said(TEO, INES, 1)])
    assert (first.kind, first.subjects) == ("met", (TEO, INES))
    assert first.decider == {"kind": "model", "model": {"provider": "nebius", "model_id": "nano"}}
    assert first.request_id == uuid.UUID(int=901)
    (later,) = _form([_said(TEO, INES, 2)], Known(met={frozenset((TEO, INES))}))
    assert later.kind == "spoke"
    (everyone,) = _form([_said(MARCO, None, 3, decider="person")])
    assert (everyone.kind, everyone.subjects) == ("spoke_to_all", (MARCO,))
    assert everyone.decider == {"kind": "person", "model": None}


def test_a_line_said_as_the_two_meet_is_read_with_the_meeting():
    """The engine's meeting of two comes first in a minute; a line one says to the other then is
    part of that moment, so History shows it; its id, anchor and kind stay the meeting's."""
    contact = _event(
        "social_contact", TEO, 4, outcome="talk_started", goal={"partner_id": str(INES)}
    )
    line = _said(TEO, INES, 6)
    (alone,) = _form([contact])
    (met,) = _form([contact, line])
    assert (met.kind, met.subjects, met.anchor_event_id) == ("met", (TEO, INES), contact.event_id)
    assert met.moment_id == alone.moment_id
    assert met.event_ids == (contact.event_id, line.event_id)
    # The positive control: without the meeting, the line makes its own moment.
    (said,) = _form([line])
    assert said.event_ids == (line.event_id,)
    # A line to someone else that minute is not part of the meeting.
    (other,) = _form([contact, _said(TEO, MARCO, 7)])
    assert other.event_ids == (contact.event_id,)
    # The one spoken to keeps a line of their own in their own moment.
    moments = _form([contact, _said(INES, TEO, 8)])
    assert {m.subjects[0]: m.event_ids for m in moments} == {
        TEO: (contact.event_id,),
        INES: (uuid.UUID(int=8),),
    }


def test_a_routine_meeting_is_a_moment_once_and_a_routine_s_choices_never():
    contact = _event(
        "social_contact", TEO, 4, outcome="talk_started", goal={"partner_id": str(INES)}
    )
    (met,) = _form([contact])
    assert (met.kind, met.decider["kind"]) == ("met", "routine")
    assert _form([contact], Known(met={frozenset((TEO, INES))})) == []
    moved = _event("route_progressed", TEO, 5, outcome="moved")
    assert _form([moved]) == []


def test_a_decision_to_go_somewhere_is_a_moment_spaced_and_waiting_is_never_one():
    decided = _decided(INES, 6)
    request = uuid.UUID(int=706)
    market = {request: {"kind": "target", "target_id": "market", "activity": "visiting"}}
    (went,) = _form([decided], options=market)
    assert (went.kind, went.subjects, went.request_id) == ("went", (INES,), request)
    assert went.target == {"target_id": "market", "activity": "visiting"}
    assert went.decider == {"kind": "model", "model": {"provider": "nebius", "model_id": "super"}}
    within = Known(went={INES: 412 - RULES.went_spacing_minutes + 1})
    assert _form([decided], within, market) == [], "a change of mind inside the spacing"
    after = Known(went={INES: 412 - RULES.went_spacing_minutes})
    assert len(_form([decided], after, market)) == 1
    for kind in ("wait", "stand", "carry_on"):
        assert _form([decided], options={request: {"kind": kind}}) == [], kind


def test_a_decision_to_talk_is_a_meeting_the_first_time_then_talking():
    request = uuid.UUID(int=713)
    talk = {request: {"kind": "talk", "partner_id": str(INES)}}
    (first,) = _form([_decided(TEO, 13)], options=talk)
    assert (first.kind, first.subjects) == ("met", (TEO, INES))
    (later,) = _form([_decided(TEO, 13)], Known(met={frozenset((TEO, INES))}), talk)
    assert later.kind == "talked"


def test_a_thing_handed_over_names_both_and_the_thing_by_any_decider():
    gave = _event("gave", TEO, 7, thing={"thing": "lantern-thing", "with": str(INES)})
    (moment,) = _form([gave])
    assert (moment.kind, moment.subjects, moment.thing) == ("gave", (TEO, INES), "lantern-thing")
    assert moment.decider["kind"] == "routine"
    followed = _event("followed", TEO, 8, thing={"with": str(INES)})
    assert _form([followed]) == [], "following by a routine is not told"
    (told,) = _form([followed, _decided(TEO, 9, origin="person")])
    assert (told.kind, told.decider["kind"]) == ("followed", "person")


def test_one_moment_a_subject_a_minute_the_rule_s_order_first():
    request = uuid.UUID(int=710)
    moments = _form(
        [_decided(TEO, 10), _said(TEO, INES, 11)], options={request: {"kind": "target"}}
    )
    assert [moment.kind for moment in moments] == ["met"]


def test_where_a_moment_happened_is_the_nearest_placed_thing_within_the_rule_s_reach():
    assert place_of(RULES, STATE, TEO) == {"placed_id": "bench-1", "thing_id": "bench-thing"}
    assert place_of(RULES, STATE, FAR) is None, "nothing placed within reach"
    assert place_of(RULES, STATE, uuid.uuid4()) is None


def test_a_scene_holds_the_people_as_the_live_drawing_reads_them_and_no_camera():
    scene = scene_of(RULES, STATE, (INES, TEO))
    assert [one["id"] for one in scene["people"]] == [str(INES), str(TEO), str(MARCO)]
    assert scene["people"][0]["position_mm"] == [1800, 1000]
    assert scene["people"][0]["path_mm"] == [[1300, 1000], [1800, 1000]]
    assert scene["people"][0]["action"] == {
        "kind": "rest",
        "target_id": "bench-thing",
        "activity": "resting on a bench",
    }
    assert set(scene) == {"state_sha256", "people_catalog_sha256", "people"}
    assert len(scene["state_sha256"]) == 64


def test_a_moment_s_id_is_the_same_from_the_minute_and_from_a_back_fill():
    (first,) = _form([_said(TEO, INES, 12)])
    (again,) = _form([_said(TEO, INES, 12)])
    assert first.moment_id == again.moment_id == moment_id_of(VERSION, RULES, uuid.UUID(int=12))
    assert moment_id_of(uuid.uuid4(), RULES, uuid.UUID(int=12)) != first.moment_id


def test_the_rule_is_a_versioned_file_refused_when_it_is_not_one(tmp_path: Path):
    shipped = json.loads(
        Path(__file__)
        .resolve()
        .parents[1]
        .joinpath("exulanica", "world", "society-moment-rules.v1.json")
        .read_text()
    )
    assert shipped["profile"] == RULES_PROFILE
    for change in ({"profile": "something/v1"}, {"exchange_minutes": 0}, {"order": ["went"]}):
        written = tmp_path / "rules.json"
        written.write_text(json.dumps({**shipped, **change}))
        with pytest.raises(ValueError):
            load_rules(written)
    wider = tmp_path / "wider.json"
    wider.write_text(json.dumps({**shipped, "place_radius_mm": 100}))
    assert place_of(load_rules(wider), STATE, TEO) is None, "a figure is read from the file"


def _read(kind: str, tick: int, subjects, **more) -> dict:
    return {
        "moment_id": f"{kind}-{tick}-{subjects[0]}",
        "tick": tick,
        "kind": kind,
        "subjects": [str(one) for one in subjects],
        "said": more.pop("said", []),
        "target": more.pop("target", None),
        "place": None,
        "decider": more.pop("decider", {"kind": "model", "model": None}),
        "branches": [],
        "scene": {},
        **more,
    }


def test_a_reply_within_the_exchange_is_a_line_of_the_moment_it_answers():
    first = _read("met", 400, (TEO, INES), said=[{"tick": 400, "line": "Morning."}])
    reply = _read("spoke", 404, (INES, TEO), said=[{"tick": 404, "line": "Early."}])
    later = 404 + RULES.exchange_minutes + 1
    late = _read("spoke", later, (TEO, INES), said=[{"tick": later, "line": "Again?"}])
    merged = merge_moments([first, reply, late], RULES)
    assert [m["kind"] for m in merged] == ["met", "spoke"]
    assert [line["line"] for line in merged[0]["said"]] == ["Morning.", "Early."]


def test_going_to_the_same_place_together_or_following_is_one_going():
    market = {"target_id": "market", "activity": "visiting"}
    ines = _read("went", 410, (INES,), target=market, decider={"kind": "person", "model": None})
    teo = _read("went", 410, (TEO,), target=market)
    elsewhere = _read("went", 410, (MARCO,), target={"target_id": "pier", "activity": None})
    merged = merge_moments([ines, teo, elsewhere], RULES)
    assert [m["subjects"] for m in merged] == [[str(INES), str(TEO)], [str(MARCO)]]
    assert merged[0]["decider"]["kind"] == "person", "the first decision's decider"
    follows = _read("followed", 420, (TEO, INES))
    goes = _read("went", 421, (INES,), target=market)
    (together,) = merge_moments([follows, goes], RULES)
    assert (together["kind"], together["subjects"], together["tick"]) == (
        "went",
        [str(INES), str(TEO)],
        420,
    )
    apart = _read("went", 420 + RULES.merge_minutes + 1, (INES,), target=market)
    assert len(merge_moments([_read("followed", 420, (TEO, INES)), apart], RULES)) == 2


def test_a_going_made_together_keeps_both_people_s_branches_each_naming_whose_it_is():
    market = {"target_id": "market", "activity": "visiting"}

    def asked(by, at: str) -> dict:
        return {"ask_id": f"ask-{by}", "asked_at": at, "by": str(by), "kind": "went"}

    ines = _read("went", 410, (INES,), target=market, branches=[asked(INES, "2026-10-16T09:02")])
    teo = _read("went", 410, (TEO,), target=market, branches=[asked(TEO, "2026-10-16T09:01")])
    (together,) = merge_moments([ines, teo], RULES)
    assert [(one["by"], one["ask_id"]) for one in together["branches"]] == [
        (str(TEO), f"ask-{TEO}"),
        (str(INES), f"ask-{INES}"),
    ], "both decisions' answers, oldest asked first"
    follows = _read("followed", 420, (TEO, INES), branches=[asked(TEO, "2026-10-16T09:03")])
    goes = _read("went", 421, (INES,), target=market, branches=[asked(INES, "2026-10-16T09:04")])
    (joined,) = merge_moments([follows, goes], RULES)
    assert [one["by"] for one in joined["branches"]] == [str(TEO), str(INES)]
