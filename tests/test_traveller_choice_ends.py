"""A gate's choice decides strictly before its end, to the second, by the clock it is read with.

The database's clock is read in the statement that asks, so the PostgreSQL test cannot meet the
end exactly; this holds the rule itself at the boundary.
"""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta

from exulanica.world.society_model_choice_repository import (
    SocietyModelChoiceRepository,
    decides_at,
)

END = "2026-10-07T21:30:00Z"
AT_END = datetime(2026, 10, 7, 21, 30, tzinfo=UTC)


def test_a_gate_s_choice_decides_before_its_end_and_not_at_it():
    assert decides_at(END, AT_END - timedelta(microseconds=1))
    assert not decides_at(END, AT_END)
    assert not decides_at(END, AT_END + timedelta(seconds=1))
    # A group stored with no end, which the table no longer admits, still reads as deciding.
    assert decides_at(None, AT_END)


def test_every_gate_s_choice_states_its_grant_s_end():
    # Every grant ends within a day, so a gate's choice is never recorded without an end.
    parameter = inspect.signature(SocietyModelChoiceRepository.record_traveller_choice).parameters
    assert parameter["ends_at"].default is inspect.Parameter.empty
