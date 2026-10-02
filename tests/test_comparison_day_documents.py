"""What a day's run records of each hour, and of its day, built from played hours with no database.

``exulanica/world/society_comparison_day.py`` seals each hour of a living town's day: its minute
digests, its events and receipts, the fifth score's terms with each person's kinds, and each
person's minute-by-minute record; the state the hour ended in is stored as the canonical bytes its
last minute's digest names; and a completed day's outcome binds its hours by digest and its terms
assembled from theirs. These tests hold each of those to what the hours played, the minute record to
the run's own drawing of the same hour, and a day that skips an hour or miscounts its receipts to a
refusal.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest
from exulanica.world import society_score_v5
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison import HOUR_TICKS, HourStart, RunPlan, first_hour, play_hour
from exulanica.world.society_comparison_day import (
    ACTIVITY_CODES,
    DAY_RUN_PROFILE,
    HOUR_PROFILE,
    WAITING,
    WALKING,
    day_outcome,
    hour_document,
    state_bytes,
    state_from_bytes,
    vocabulary,
)
from exulanica.world.society_comparison_living_drawing import replay_document
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE

from living_town_support import town_input

CONTRACT = decision_contract()
HOURS = 3
DEFINITION = {"document_sha256": "d" * 64, "window_ticks": HOURS * HOUR_TICKS}
DIGEST = "e" * 64
CATALOGS = load_comparison_catalogs(
    versions={
        "society-person-score": 5,
        "society-comparison-protocol": 3,
        "society-comparison-seeds": 5,
    }
)
CALLS = {
    "asked": 2,
    "first_answers_refused": 0,
    "cost_usd": "0.00010000",
    "cost_known": True,
    "latencies_ms": [900, 1100],
}


class _Choosing:
    def offerable(self, _tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            options = request["context"]["options"]
            option = options[int(request["document_sha256"][:8], 16) % len(options)]
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _plan() -> RunPlan:
    return RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, "day-documents"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, "day-documents:society"),
        seed="day-documents-development",
        population=12,
        inputs=(town_input(),),
        ticks=HOURS * HOUR_TICKS,
        decider={"kind": "model", "provider": "nebius_token_factory", "model_id": "test/model"},
        provider_config={
            "provider": "nebius_token_factory",
            "model_id": "test/model",
            "mechanism": "tool_call",
            "choice_seq": None,
            "manifest_sha256": "0" * 64,
            "prompt_version": "society-person-choice/v1",
            "contract": CONTRACT.binding(),
            "deadline_ms": 20_000,
        },
        contract=CONTRACT,
        engine_profile=LIVING_TOWN_PROFILE,
    )


def _hours(plan: RunPlan):
    start = first_hour(plan)
    found = []
    for hour in range(HOURS):
        played = play_hour(plan, _Choosing(), start=start)
        document = hour_document(
            plan,
            DEFINITION,
            "model_a",
            DIGEST,
            start,
            played,
            CATALOGS,
            calls=CALLS,
            others_calls=None,
        )
        found.append((start, played, document))
        start = HourStart(hour + 1, played.states[-1], start.first_sequence + len(played.receipts))
    return found


def test_a_sealed_hour_states_what_its_minutes_played():
    plan = _plan()
    for start, played, document in _hours(plan):
        assert document["profile"] == HOUR_PROFILE
        assert (document["hour"], document["first_tick"], document["ticks"]) == (
            start.hour,
            start.hour * HOUR_TICKS,
            HOUR_TICKS,
        )
        assert document["minutes"]["state_sha256"] == played.minute_digests
        assert document["receipts"]["count"] == len(played.receipts)
        assert document["receipts"]["first_sequence"] == start.first_sequence
        assert (
            document["clock"]["end"]["minute_of_day"]
            == (played.states[-1]["clock"]["minute_of_day"])
        )
        terms = document["terms"]
        assert set(terms[society_score_v5.KINDS]) == {p["id"] for p in start.state["inhabitants"]}
        assert {p: len(k) for p, k in terms[society_score_v5.KINDS].items()} == terms["activities"]


def test_a_persons_minute_record_is_their_hour_as_the_runs_drawing_draws_it():
    plan = _plan()
    activities, places = vocabulary(plan)
    code_of = {activity["kind"]: activity["code"] for activity in activities}
    place_of = {place["destination_id"]: index for index, place in enumerate(places)}
    _start, played, document = _hours(plan)[1]
    drawing = replay_document(plan, "model_a", DIGEST, played, model_name=str)
    assert [activity["kind"] for activity in drawing["activities"]] == list(code_of)
    seen = set()
    for offset, frame in enumerate(drawing["minutes"][1:]):
        for person in frame["people"]:
            if len(person["path"]) > 1:
                expected = WALKING
            elif person["status"] in ("active", "completed") and person["action"] in code_of:
                expected = code_of[person["action"]]
            else:
                expected = WAITING
            record = document["people"][person["id"]]
            assert record["doing"][offset] == expected
            seen.add(expected)
            heading = [entry for entry in record["heading"] if entry[0] <= offset][-1][1]
            # As the page compares two sides' minutes: a goal's place, or none for no goal and for
            # a goal at no place.
            goal = person["goal"]
            target = None if goal is None else goal["target_id"]
            assert heading == (None if target is None else place_of[target])
    # The hour shows people walking, waiting and doing something, so every code is exercised.
    assert {WALKING, WAITING} <= seen and seen - {WALKING, WAITING}
    assert all(code in ACTIVITY_CODES for code in seen - {WALKING, WAITING})


def test_the_state_an_hour_ended_in_is_stored_as_the_bytes_its_digest_names():
    plan = _plan()
    _start, played, document = _hours(plan)[0]
    data = state_bytes(played.states[-1])
    digest = document["minutes"]["state_sha256"][-1]
    assert state_from_bytes(data, digest) == played.states[-1]
    with pytest.raises(ValueError, match="not the one"):
        state_from_bytes(data.replace(b'"tick":60', b'"tick":61'), digest)


def test_a_completed_day_binds_its_hours_and_assembles_its_terms_from_theirs():
    plan = _plan()
    hours = [document for _start, _played, document in _hours(plan)]
    receipts = [
        receipt["document_sha256"]
        for _start, played, _document in _hours(plan)
        for receipt in played.receipts
    ]
    outcome = day_outcome(DEFINITION, "model_a", DIGEST, hours, receipts)
    assert outcome["profile"] == DAY_RUN_PROFILE
    assert outcome["minutes"] == {
        "count": HOURS * HOUR_TICKS,
        "hours": [hour["document_sha256"] for hour in hours],
    }
    assert outcome["receipts"]["count"] == len(receipts)
    assert outcome["terms"] == society_score_v5.day_terms([hour["terms"] for hour in hours])
    assert society_score_v5.KINDS not in outcome["terms"]
    assert outcome["calls"]["asked"] == HOURS * CALLS["asked"]
    assert outcome["calls"]["latencies_ms"] == HOURS * CALLS["latencies_ms"]
    assert outcome["others_calls"] is None
    with pytest.raises(ValueError, match="every hour of its window"):
        day_outcome(DEFINITION, "model_a", DIGEST, hours[:-1], receipts)
    with pytest.raises(ValueError, match="its hours' receipts"):
        day_outcome(DEFINITION, "model_a", DIGEST, hours, receipts[:-1])
    with pytest.raises(ValueError, match="its own run's"):
        day_outcome(DEFINITION, "model_b", DIGEST, hours, receipts)


def test_only_a_society_that_keeps_a_day_seals_one():
    plan = _plan()
    start, played, _document = _hours(plan)[0]
    purposeful = dataclasses.replace(plan, engine_profile="exulanica-society/v2")
    with pytest.raises(ValueError, match="window_not_offered"):
        hour_document(
            purposeful,
            DEFINITION,
            "model_a",
            DIGEST,
            start,
            played,
            CATALOGS,
            calls=None,
            others_calls=None,
        )
