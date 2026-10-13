"""The rule of a day, asked directly: when a shift is due, where a person plans from, and how long
a stay that begins now lasts. The living society's own tests hold the rule as a whole through its
pinned minutes; these hold the three answers a whole day's digest does not single out."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from exulanica.world.society_catalogs import MINUTES_PER_DAY
from exulanica.world.society_day import seeded_span, shift_due, start_node, stay_ticks

SEED = "7" * 64
#: Somebody who works from eight in the morning for eight hours and has worked no shift yet.
WORKER = {
    "ordinal": 3,
    "work": {"shift_start_minute": 480, "shift_minutes": 480},
    "last_shift_day": None,
}
SHIFT = SimpleNamespace(mode="shift", key="work")
MEAL = SimpleNamespace(mode="need", key="eat_out", duration_minimum=20, duration_maximum=60)


def test_a_shift_is_due_from_the_commute_lead_before_it_begins_until_it_ends():
    lead = 30
    assert shift_due(WORKER, 449, 0, lead) == (False, 0, 0)
    # Due while there is still the lead to walk there in, and it says how long until it ends.
    assert shift_due(WORKER, 450, 0, lead) == (True, 0, 510)
    assert shift_due(WORKER, 480, 0, lead) == (True, 0, 480)
    assert shift_due(WORKER, 959, 0, lead) == (True, 0, 1)
    assert shift_due(WORKER, 960, 0, lead) == (False, 0, 0)
    # With no lead it is due only once it has begun.
    assert shift_due(WORKER, 479, 0, 0) == (False, 0, 0)
    # A shift worked today is not due again today, and tomorrow's is.
    worked = {**WORKER, "last_shift_day": 0}
    assert shift_due(worked, 600, 0, lead) == (False, 0, 0)
    assert shift_due(worked, 450, 1, lead) == (True, 1, 510)


def test_a_shift_that_runs_past_midnight_belongs_to_the_day_it_began():
    night = {**WORKER, "work": {"shift_start_minute": 1320, "shift_minutes": 480}}
    # At 01:40 on the second day the shift that began at 22:00 on the first is still due.
    assert shift_due(night, 100, 1, 30) == (True, 0, 260)
    assert shift_due({**night, "last_shift_day": 0}, 100, 1, 30) == (False, 1, 0)


def test_a_person_plans_from_the_node_they_stand_at_or_the_one_their_edge_leads_to():
    standing = {"location": {"node_id": "node:a", "edge": None}}
    assert start_node(standing) == "node:a"
    walking = {
        "location": {
            "node_id": None,
            "edge": {"from_node_id": "node:a", "to_node_id": "node:b", "progress_mm": 400},
        }
    }
    assert start_node(walking) == "node:b"


def test_a_shift_s_stay_lasts_to_the_shift_s_end_however_late_the_arrival():
    begin = 2 * MINUTES_PER_DAY + 480
    on_time = stay_ticks(WORKER, SHIFT, None, SEED, 9, begin, 2)
    assert on_time == 480
    assert stay_ticks(WORKER, SHIFT, None, SEED, 9, begin + 100, 2) == 380
    # Early, by the commute lead: the stay runs from arrival to the shift's end.
    assert stay_ticks(WORKER, SHIFT, None, SEED, 9, begin - 20, 2) == 500
    # Arriving as it ends, or after, is still one minute of work, never none.
    assert stay_ticks(WORKER, SHIFT, None, SEED, 9, begin + 480, 2) == 1
    assert stay_ticks(WORKER, SHIFT, None, SEED, 9, begin + 600, 2) == 1


def test_a_stay_takes_its_destination_s_fixed_length_or_a_seeded_draw_in_the_activity_s_range():
    fixed = {"duration_ticks": 7}
    assert stay_ticks(WORKER, MEAL, fixed, SEED, 9, 1_000, None) == 7
    drawn = stay_ticks(WORKER, MEAL, {"duration_ticks": None}, SEED, 9, 1_000, None)
    assert drawn == stay_ticks(WORKER, MEAL, None, SEED, 9, 1_000, None)
    assert 20 <= drawn <= 60
    # The draw is the seeded one for this activity, this minute and this person, and no other.
    assert drawn == seeded_span(SEED, "duration:eat_out:9", WORKER["ordinal"], 20, 60)
    lengths = {
        stay_ticks({**WORKER, "ordinal": n}, MEAL, None, SEED, tick, 1_000, None)
        for n in range(8)
        for tick in range(8)
    }
    assert len(lengths) > 8 and all(20 <= length <= 60 for length in lengths)


@pytest.mark.parametrize(("low", "high"), [(1, 1), (0, 9), (-30, 30)])
def test_a_seeded_draw_stays_inside_its_range_and_reaches_both_ends(low: int, high: int):
    drawn = {seeded_span(SEED, f"draw:{n}", n, low, high) for n in range(400)}
    assert min(drawn) == low and max(drawn) == high
