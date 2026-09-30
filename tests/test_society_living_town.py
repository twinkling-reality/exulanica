"""The living town (``exulanica-society/v5``): a town's people live its day, and a chosen model may
decide for some of them.

Pure: every town here is generated from a recipe and composed as the runtime composes it
(``tests/living_town_support.py``), with no database, store or model. What a stored society does
with the same engine is in ``tests/test_society_living_town_postgres.py``.
"""

from __future__ import annotations

import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from exulanica.world.decision_roles import RoleRefused, decision_roles
from exulanica.world.role_decisions import play_minutes, replay_minutes
from exulanica.world.society_catalogs import (
    MINUTES_PER_DAY,
    ROUTINE_VERSIONS,
    TOWN_ROUTINE_VERSIONS,
    load_routine_model,
)
from exulanica.world.society_engines import CREATES, society_engine
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
)
from exulanica.world.society_living_decisions import LivingSeam, living_step
from exulanica.world.society_place import place_from_town_input
from exulanica.world.society_planner import validate_society_input

from living_town_support import SEED, town_input

ROOT = Path(__file__).resolve().parents[1]
SOCIETY = uuid.UUID("5a5a5a5a-0000-4000-8000-000000000005")
PERSON_ROLE = "society_decision"


def _town(document: dict[str, Any] | None = None) -> tuple[dict, Any, Any, dict]:
    document = town_input() if document is None else document
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    return document, routine, place, state


def test_the_table_creates_the_living_town_over_a_town_and_keeps_v2_for_other_saved_worlds():
    assert CREATES["town"] == LIVING_TOWN_PROFILE
    assert CREATES["saved_world"] == "exulanica-society/v2"
    engine = society_engine(LIVING_TOWN_PROFILE)
    assert engine.state_family == "living" and engine.saved_world and engine.owner_model_choice
    assert not engine.comparisons and not engine.experiments and not engine.directed_actions


def test_every_use_the_city_grammar_places_keeps_hours_and_shifts():
    """Each use class the city grammar may give a premises (``assets/catalogs/use-class.v1.json``)
    has an entry in the town's use-class catalog stating its opening hours, and exactly a
    workplace names the shifts its positions work; a use the grammar gains without one fails."""
    grammar = json.loads((ROOT / "assets/catalogs/use-class.v1.json").read_text(encoding="utf-8"))
    town = load_routine_model(versions=TOWN_ROUTINE_VERSIONS)
    for entry in grammar["entries"]:
        use = town.use_classes.get(entry["key"])
        assert use is not None, f"the town's routine states no hours for {entry['key']}"
        assert use.opening is not None
        assert bool(use.shifts) == (use.kind == "workplace"), entry["key"]
        assert all(shift in town.shifts for shift in use.shifts)


def test_a_district_s_routine_keeps_no_hours_and_a_town_s_does():
    assert not load_routine_model(versions=ROUTINE_VERSIONS).keeps_hours
    town = load_routine_model(versions=TOWN_ROUTINE_VERSIONS)
    assert town.keeps_hours
    assert 0 < town.policy["employment_share_milli"] < 1000


def test_a_town_s_input_carries_the_living_place_its_records_name():
    document = town_input()
    validate_society_input(document)
    assert document["profile"] == "exulanica.society-input/walking-surfaces-v2"
    [named] = [ref for ref in document["dependency_refs"] if ref["kind"] == "city_place"]
    assert document["living"]["place"]["document_sha256"] == named["sha256"]
    # The purposeful society's input over the same town carries no living place.
    assert "living" not in town_input(living=False)
    # A place the input does not name is refused by name.
    changed = json.loads(json.dumps(document))
    changed["living"]["place"]["document_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="not the city place the input names"):
        validate_society_input(changed)


def test_nobody_stands_where_a_person_arrives():
    document = town_input()
    place = place_from_town_input(document)
    ax, az = document["navigation"]["arrival_mm"]
    near = [
        spot
        for spot in place["spots"]
        if (spot["position_mm"][0] - ax) ** 2 + (spot["position_mm"][1] - az) ** 2 <= 2_000**2
    ]
    assert all(spot["destination_ids"] for spot in near)
    assert len(place["spots"]) < len(document["living"]["place"]["spots"])


def test_a_town_s_people_live_in_its_homes_and_a_share_of_them_work_its_shifts():
    document, routine, place, state = _town()
    people = state["inhabitants"]
    assert state["profile"] == LIVING_TOWN_PROFILE
    assert len(people) == document["population"]["size"]
    # Everybody lives in one of the town's homes and starts the day there, indoors.
    assert all(person["home"] and person["location"]["indoors"] for person in people)
    workers = [person for person in people if person["work"]]
    share = routine.policy["employment_share_milli"]
    assert len(workers) == len(people) * share // 1000
    assert Counter(p["role_reason"] for p in people)["keeps_no_job"] == len(people) - len(workers)
    # Workplace-first: no workplace has a second worker while another has none.
    workplaces = {
        dest_id: dest for dest_id, dest in place.destinations.items() if dest["staff_capacity"]
    }
    staffed = Counter(person["work"]["destination_id"] for person in workers)
    assert max(staffed.values()) == 1 or len(staffed) == len(workplaces)
    # Each worker works a shift their workplace's use class names, give or take the jitter.
    jitter = routine.policy["shift_jitter_minutes"]
    for person in workers:
        use = routine.use_classes[place.destinations[person["work"]["destination_id"]]["use_class"]]
        starts = [routine.shifts[key] for key in use.shifts]
        assert any(
            min(
                (person["work"]["shift_start_minute"] - shift.start_minute) % MINUTES_PER_DAY,
                (shift.start_minute - person["work"]["shift_start_minute"]) % MINUTES_PER_DAY,
            )
            <= jitter
            and person["work"]["shift_minutes"] == shift.minutes
            for shift in starts
        )
    assert state["clock"]["minute_of_day"] == routine.policy["start_minute_of_day"]


def _day(document=None):
    """A whole simulated day of a town, minute by minute: every state and every event."""
    document, routine, place, state = _town(document)
    states, events = [state], []
    for _ in range(MINUTES_PER_DAY):
        state, produced = advance_living_society(state, SEED, [place], routine)
        states.append(state)
        events.extend(produced)
    return routine, place, states, events


@pytest.fixture(scope="module")
def day():
    return _day()


def test_a_premises_admits_visitors_in_its_hours_while_one_of_its_workers_is_there(day):
    routine, place, states, events = day
    before = {state["tick"]: state for state in states}
    visits = 0
    for event in events:
        goal = event.document.get("goal")
        if event.kind != "goal_selected" or not goal or not goal["destination_id"]:
            continue
        dest = place.destinations[goal["destination_id"]]
        use = routine.use_classes.get(dest["use_class"]) if dest["use_class"] else None
        if use is None or not use.staff_per_unit or goal["activity"] == "work":
            continue
        visits += 1
        assert use.open_at(event.document["minute_of_day"]), goal
        prior = before[event.tick - 1]
        assert any(
            person["action"]["kind"] == "work"
            and person["action"]["status"] == "active"
            and person["action"]["destination_id"] == goal["destination_id"]
            for person in prior["inhabitants"]
        ), goal
    assert visits > 0


def test_the_afternoon_no_longer_holds_every_resident_at_work(day):
    """The rhythm a town lives: asleep at night, a share at work in the afternoon, and the rest
    out on errands or at leisure then, never every resident at work (the v4 rule's day)."""
    routine, _place, states, _events = day
    by_minute = {state["clock"]["minute_of_day"]: state for state in states[1:]}
    people = len(states[0]["inhabitants"])
    for minute in range(13 * 60, 15 * 60 + 1, 30):
        kinds = Counter(p["action"]["kind"] for p in by_minute[minute]["inhabitants"])
        assert kinds["work"] <= people * routine.policy["employment_share_milli"] // 1000
        assert people - kinds["work"] > 0
        assert kinds["shop"] + kinds["eat_out"] + kinds["visit"] + kinds["stroll"] > 0
    night = Counter(p["action"]["kind"] for p in by_minute[3 * 60]["inhabitants"])
    assert night["sleep"] == people


def _scripted(role, contract, prefer: str):
    """A model that chooses the option whose activity is ``prefer`` when offered, else waits."""

    class Scripted:
        def offerable(self, tick, due):
            return {s: frozenset(o.label for o in options) for s, options in due.items()}

        def answers(self, requests):
            results = []
            for request in requests:
                options = request["context"]["options"]
                chosen = next((o for o in options if o["activity"] == prefer), None) or next(
                    o for o in options if o["kind"] == "wait"
                )
                results.append(
                    {
                        "status": "accepted",
                        "reason": "validated_choice",
                        "proposal": {"label": chosen["label"], "option": chosen},
                        "provider": None,
                    }
                )
            return results

    return Scripted()


def _played(minutes: int, chosen: set[str], asking):
    document, routine, _place, state = _town()
    role = decision_roles().role(PERSON_ROLE)
    contract = role.contract()
    config = {
        "provider": "scripted",
        "model_id": "scripted/stroller",
        "mechanism": "tool_call",
        "choice_seq": 1,
        "manifest_sha256": "a" * 64,
        "prompt_version": role.prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    roles = decision_roles().hosted_by(LIVING_TOWN_PROFILE)
    assert roles == (role,)

    def play(port):
        return play_minutes(
            roles,
            role,
            start=state,
            sources=[document],
            seed=SEED,
            ticks=minutes,
            step=lambda s, seed, _consumed, seam: living_step(s, seed, seam),
            config_for=lambda subject: config if subject in chosen else None,
            request_id_for=lambda subject, tick: uuid.uuid5(SOCIETY, f"{subject}:{tick}"),
            asking=port,
            seam=lambda _s, _due: LivingSeam(SEED, living_places([document], routine), routine),
        )

    return role, contract, state, play, play(asking(role, contract))


def test_a_chosen_model_decides_for_a_town_person_and_replay_equals_play():
    _document, _routine, _place, state = _town()
    # Two people with no job, whose day the routine leaves open.
    free = [p["id"] for p in state["inhabitants"] if p["work"] is None][:2]
    _role, _contract, _start, play, played = _played(
        240, set(free), lambda r, c: _scripted(r, c, "stroll")
    )
    assert played.receipts, "a person the owner chose a model for was asked"
    applied = [
        event
        for event in played.events
        if event.kind == "decision_applied" and event.document["disposition"] == "applied"
    ]
    assert applied
    # What the model chose is what the person did: every applied choice to walk is a walk.
    chosen = [
        event
        for event in played.events
        if event.kind == "goal_selected"
        and str(event.subject_id) in free
        and event.document.get("decision", {}).get("decided_by") == "model"
    ]
    assert chosen and all(event.document["goal"]["activity"] == "stroll" for event in chosen)
    # Nobody else's minute records a model's choice.
    assert all(
        str(event.subject_id) in free
        for event in played.events
        if event.document.get("decision", {}).get("decided_by") == "model"
    )
    # Replayed from the stored requests and receipts alone, asking nothing, minute for minute.
    stored = list(zip(played.requests, played.receipts, strict=True))
    again = replay_minutes(stored, minute_digests=played.minute_digests, play=play)
    assert again.minute_digests == played.minute_digests


def test_a_model_that_waits_keeps_its_person_where_they_are():
    _document, _routine, _place, state = _town()
    [person] = [p["id"] for p in state["inhabitants"] if p["work"] is None][:1]
    _role, _contract, _start, _play, played = _played(
        120, {person}, lambda r, c: _scripted(r, c, "no_such_activity")
    )
    # Waiting adds no kind of event of the engine's own: the receipt's event says what was chosen.
    waited = [
        e
        for e in played.events
        if e.kind == "decision_applied"
        and str(e.subject_id) == person
        and e.document["disposition"] == "applied"
    ]
    assert waited and all(e.document["chose"] == "wait here a minute" for e in waited)
    kinds = {e.kind for e in played.events}
    assert kinds <= {
        "action_completed",
        "blocked",
        "decision_applied",
        "goal_selected",
        "replanned",
        "route_progressed",
    }, kinds
    last = next(p for p in played.states[-1]["inhabitants"] if p["id"] == person)
    assert last["location"]["indoors"] and last["goal"] is None


def test_the_person_role_decides_only_in_the_families_it_serves():
    role = decision_roles().role(PERSON_ROLE)
    legacy = {"profile": "exulanica-society/v1", "inhabitants": []}
    with pytest.raises(RoleRefused, match="person_family_unsupported"):
        role.adapter.due(legacy, str(uuid.uuid4()))
