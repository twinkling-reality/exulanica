"""How a new society opens awake, without a database: the policy as its file states it, the host's
setting, the share of a state's people who are outdoors, and the stop rule over a stand-in
repository whose minutes are written here by hand.

The expected minutes are worked from the hand-written states alone: who is indoors in each is
stated below, so the first minute at which a share holds is counted by reading the list.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from pathlib import Path

import pytest
from exulanica.api import services
from exulanica.api.society_opening import (
    OPENING_OFF,
    SOCIETY_OPENING_ENV,
    SOCIETY_OPENING_POLICY,
    SocietyOpening,
    SocietyOpeningRefused,
    open_awake,
    opening_setting,
    outdoors_share_milli,
)
from exulanica.world.society import StaleSocietyState
from exulanica.world.world_clock import ClockRefused

POLICY_FILE = Path(__file__).resolve().parents[1] / "exulanica/world/society-opening-policy.v1.json"
VERSION = uuid.UUID(int=7)


def _state(outdoors: int, people: int = 20) -> dict:
    """A living state of ``people`` with the first ``outdoors`` of them outdoors."""
    return {
        "inhabitants": [
            {"id": f"person-{n}", "location": {"indoors": n >= outdoors}} for n in range(people)
        ]
    }


class Minutes:
    """A stand-in repository: minute ``n`` of a society is ``states[n]``; every advance is kept."""

    def __init__(self, states: list[dict], refuse_at: dict[int, Exception] | None = None) -> None:
        self.states = states
        self.refuse_at = refuse_at or {}
        self.asked: list[tuple[int, str]] = []

    def snapshot(self, tick: int) -> dict:
        return {"current_tick": tick, "state_sha256": f"digest-{tick}", "state": self.states[tick]}

    def advance(self, version_id, *, base_tick, base_state_sha256, actor=None, **_):
        assert version_id == VERSION
        self.asked.append((base_tick, base_state_sha256))
        if base_tick in self.refuse_at:
            raise self.refuse_at[base_tick]
        return self.snapshot(base_tick + 1)


def test_the_policy_is_read_as_its_file_states_it_and_is_on_by_default():
    document = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    values = document["values"]
    assert document["default"] == "on"
    assert SOCIETY_OPENING_POLICY.on == SocietyOpening(
        values["outdoors_share_milli"], values["minutes_maximum"], values["seconds_maximum"]
    )
    assert SOCIETY_OPENING_POLICY.default == SOCIETY_OPENING_POLICY.on
    # Every value is classed a chosen budget and gives its reason, and so does the default.
    for name in ("outdoors_share_milli", "minutes_maximum", "seconds_maximum"):
        assert document["classes"][name] == "chosen_budget"
        assert len(document["reasons"][name]) > 80
    assert len(document["reasons"]["default"]) > 80


def test_a_host_s_setting_is_absent_off_on_or_three_whole_numbers():
    on = SOCIETY_OPENING_POLICY.on
    assert opening_setting(None) == on
    assert opening_setting("  ") == on
    assert opening_setting("on") == on
    assert opening_setting("OFF") == OPENING_OFF and OPENING_OFF.off
    assert opening_setting("200:30:2") == SocietyOpening(200, 30, 2)
    assert not SocietyOpening(200, 30, 2).off
    # No minutes is off, whatever the share.
    assert opening_setting("200:0:5").off


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("yes", "society_opening_not_recognised"),
        ("150:60", "society_opening_not_recognised"),
        ("150:60:5:1", "society_opening_not_recognised"),
        ("15.0:60:5", "society_opening_not_recognised"),
        ("-150:60:5", "society_opening_not_recognised"),
        ("0:60:5", "society_opening_share_out_of_bounds"),
        ("1001:60:5", "society_opening_share_out_of_bounds"),
    ],
)
def test_a_setting_that_is_none_of_those_is_refused_by_name(value, code):
    with pytest.raises(SocietyOpeningRefused) as refused:
        opening_setting(value)
    assert refused.value.code == code
    assert SOCIETY_OPENING_ENV == "EXULANICA_SOCIETY_OPENING"


def test_the_share_outdoors_is_counted_from_the_state_and_unknown_where_it_does_not_say():
    assert outdoors_share_milli(_state(0)) == 0
    assert outdoors_share_milli(_state(3)) == 150
    assert outdoors_share_milli(_state(20)) == 1000
    # One in seven is 142 thousandths, never rounded up to a share that was not reached.
    assert outdoors_share_milli(_state(1, people=7)) == 142
    assert outdoors_share_milli({"inhabitants": []}) is None
    # A society of things says where its people are and not whether that is indoors.
    assert (
        outdoors_share_milli({"inhabitants": [{"id": "a", "location": {"node_id": "n"}}]}) is None
    )
    mixed = _state(3)
    del mixed["inhabitants"][5]["location"]["indoors"]
    assert outdoors_share_milli(mixed) is None


def test_it_advances_to_the_first_minute_the_share_is_outdoors_and_no_further():
    # Of 20 people: nobody out for three minutes, then 1, 2, 3 (15 percent at minute 5), then 9.
    minutes = Minutes([_state(n) for n in (0, 0, 0, 1, 2, 3, 9)])
    opened = open_awake(
        minutes, VERSION, minutes.snapshot(0), SocietyOpening(150, 60, 5), actor=None
    )
    assert opened["current_tick"] == 5
    assert minutes.asked == [(n, f"digest-{n}") for n in range(5)]


def test_it_stops_at_the_most_minutes_and_at_the_most_seconds():
    never = Minutes([_state(0)] * 50)
    assert (
        open_awake(never, VERSION, never.snapshot(0), SocietyOpening(150, 7, 5), actor=None)[
            "current_tick"
        ]
        == 7
    )
    # A clock that reads 0 at the start and 2 s more before each minute: at 2 s a minute is still
    # taken, at 4 s the 3 s are spent, so one minute is advanced.
    slow = Minutes([_state(0)] * 50)
    readings = iter(range(0, 1000, 2))
    opened = open_awake(
        slow,
        VERSION,
        slow.snapshot(0),
        SocietyOpening(150, 40, 3),
        actor=None,
        clock=lambda: float(next(readings)),
    )
    assert opened["current_tick"] == 1


def test_off_and_a_state_that_does_not_say_who_is_indoors_advance_nothing():
    minutes = Minutes([_state(0)] * 5)
    start = minutes.snapshot(0)
    assert open_awake(minutes, VERSION, start, OPENING_OFF, actor=None) is start
    things = Minutes([{"inhabitants": [{"id": "a", "location": {"node_id": "n"}}]}] * 5)
    begun = things.snapshot(0)
    assert open_awake(things, VERSION, begun, SocietyOpening(150, 60, 5), actor=None) is begun
    # Already awake: a place whose people stand outdoors from the first minute.
    square = Minutes([_state(20)] * 5)
    assert (
        open_awake(square, VERSION, square.snapshot(0), SocietyOpening(150, 60, 5), actor=None)[
            "current_tick"
        ]
        == 0
    )
    assert minutes.asked == things.asked == square.asked == []


@pytest.mark.parametrize(
    "refusal",
    [
        StaleSocietyState("society changed; reload before advancing"),
        ClockRefused("clock_lead_exhausted", "waits"),
    ],
)
def test_a_minute_somebody_else_took_or_a_clock_that_waits_leaves_the_society_where_it_reached(
    refusal,
):
    minutes = Minutes([_state(0)] * 9, refuse_at={3: refusal})
    opened = open_awake(
        minutes, VERSION, minutes.snapshot(0), SocietyOpening(150, 60, 5), actor=None
    )
    assert opened["current_tick"] == 3
    assert [tick for tick, _ in minutes.asked] == [0, 1, 2, 3]


def test_a_host_reads_the_setting_and_a_hand_built_services_opens_nothing():
    # A deployment that sets nothing opens its societies as the policy file says.
    assert services._society_opening(None) == SOCIETY_OPENING_POLICY.on
    assert services._society_opening("off") == OPENING_OFF
    assert services._society_opening("300:20:4") == SocietyOpening(300, 20, 4)
    with pytest.raises(services.SocietySettingRefused) as refused:
        services._society_opening("sometimes")
    assert refused.value.code == "society_opening_not_recognised"
    assert refused.value.variable == SOCIETY_OPENING_ENV
    assert SOCIETY_OPENING_ENV in str(refused.value)
    # A Services built by hand states no host: it opens nothing, as before the setting existed.
    (field,) = [f for f in dataclasses.fields(services.Services) if f.name == "society_opening"]
    assert field.default == OPENING_OFF
    # An operator is told the setting exists, and whether it is set.
    assert SOCIETY_OPENING_ENV in services.describe_configuration({})
