"""How a new society opens awake, without a database: the policy as each version of its file
states it, the host's setting, the share of a state's people who are outdoors and of its beings
who are doing something, and the stop rule over a stand-in repository whose minutes are written
here by hand.

The expected minutes are worked from the hand-written states alone: who is indoors and who is idle
in each is stated below, so the first minute at which a share holds is counted by reading the list.
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
    active_share_milli,
    load_opening_policy,
    open_awake,
    opening_setting,
    outdoors_share_milli,
)
from exulanica.world.society import StaleSocietyState
from exulanica.world.world_clock import ClockRefused

WORLD = Path(__file__).resolve().parents[1] / "exulanica/world"
POLICY_FILE = WORLD / "society-opening-policy.v2.json"
POLICY_V1_FILE = WORLD / "society-opening-policy.v1.json"
VERSION = uuid.UUID(int=7)
#: The policy in force, read here from its file and not from the module under test.
STATED = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
THINGS = frozenset(STATED["active_share_state_families"])


def _state(outdoors: int, people: int = 20) -> dict:
    """A living state of ``people`` with the first ``outdoors`` of them outdoors."""
    return {
        "inhabitants": [
            {"id": f"person-{n}", "location": {"indoors": n >= outdoors}} for n in range(people)
        ]
    }


def _beings(active: int, beings: int = 10) -> dict:
    """A state of ``beings`` that says what each is doing and not who is indoors, as a society of
    things states it: the first ``active`` of them stand, the rest are idle."""
    return {
        "inhabitants": [
            {
                "id": f"being-{n}",
                "location": {"node_id": f"node-{n}", "edge": None},
                "action": {"kind": "stand" if n < active else "idle"},
            }
            for n in range(beings)
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
    document = STATED
    values = document["values"]
    assert (document["version"], document["default"]) == (2, "on")
    assert SOCIETY_OPENING_POLICY.version == 2
    assert SOCIETY_OPENING_POLICY.on == SocietyOpening(
        values["outdoors_share_milli"],
        values["minutes_maximum"],
        values["seconds_maximum"],
        active_share_milli=values["active_share_milli"],
        minutes_minimum=values["minutes_minimum"],
        active_state_families=frozenset(document["active_share_state_families"]),
    )
    assert SOCIETY_OPENING_POLICY.default == SOCIETY_OPENING_POLICY.on
    # The share doing something is stated for the society of things alone, and the least minutes
    # are fewer than the most.
    assert document["active_share_state_families"] == ["things"]
    assert 1 <= values["active_share_milli"] <= 1000
    assert 0 < values["minutes_minimum"] < values["minutes_maximum"]
    # Every value is classed a chosen budget and gives its reason, and so do the default and the
    # families.
    assert set(values) == set(document["classes"])
    for name in values:
        assert document["classes"][name] == "chosen_budget"
        assert len(document["reasons"][name]) > 80
    assert len(document["reasons"]["default"]) > 80
    assert len(document["reasons"]["active_share_state_families"]) > 80


def test_version_1_of_the_policy_is_still_read_and_means_what_it_meant():
    document = json.loads(POLICY_V1_FILE.read_text(encoding="utf-8"))
    values = document["values"]
    before = load_opening_policy(POLICY_V1_FILE)
    assert before.version == document["version"] == 1 and before.default_on
    # One share, no least minutes, and no state read by what its beings do.
    assert before.on == SocietyOpening(
        values["outdoors_share_milli"], values["minutes_maximum"], values["seconds_maximum"]
    )
    assert (before.on.active_share_milli, before.on.minutes_minimum) == (0, 0)
    assert before.on.active_state_families == frozenset()
    # What version 2 keeps from it, it keeps unchanged.
    for name in ("outdoors_share_milli", "minutes_maximum", "seconds_maximum"):
        assert STATED["values"][name] == values[name]


@pytest.mark.parametrize(
    "change",
    [
        {"version": 3},
        {"active_share_state_families": []},
        {"active_share_state_families": "things"},
        {"values": {**STATED["values"], "active_share_milli": 0}},
        {"values": {**STATED["values"], "minutes_minimum": -1}},
        {"classes": {**STATED["classes"], "minutes_minimum": "leftover"}},
        {
            "reasons": {
                name: reason
                for name, reason in STATED["reasons"].items()
                if name != "active_share_state_families"
            }
        },
    ],
)
def test_a_version_2_file_that_does_not_state_all_of_it_is_refused(change, tmp_path):
    path = tmp_path / "society-opening-policy.json"
    path.write_text(json.dumps({**STATED, **change}), encoding="utf-8")
    with pytest.raises(SocietyOpeningRefused):
        load_opening_policy(path)
    # Positive control: the file as it stands is read.
    path.write_text(json.dumps(STATED), encoding="utf-8")
    assert load_opening_policy(path) == SOCIETY_OPENING_POLICY


def test_a_host_s_setting_is_absent_off_on_or_three_to_five_whole_numbers():
    on = SOCIETY_OPENING_POLICY.on
    active = STATED["values"]["active_share_milli"]
    assert opening_setting(None) == on
    assert opening_setting("  ") == on
    assert opening_setting("on") == on
    assert opening_setting("OFF") == OPENING_OFF and OPENING_OFF.off
    # Three numbers state the seconds as the whole wait: no least minutes; the share doing
    # something and the families it is read for are the policy's.
    assert opening_setting("200:30:2") == SocietyOpening(
        200, 30, 2, active_share_milli=active, minutes_minimum=0, active_state_families=THINGS
    )
    assert not SocietyOpening(200, 30, 2).off
    # A fourth is the least minutes, a fifth the share doing something.
    assert opening_setting("200:30:2:8") == SocietyOpening(
        200, 30, 2, active_share_milli=active, minutes_minimum=8, active_state_families=THINGS
    )
    assert opening_setting("200:30:2:8:900") == SocietyOpening(
        200, 30, 2, active_share_milli=900, minutes_minimum=8, active_state_families=THINGS
    )
    # A share doing something of 0 reads no state by what its beings do: version 1's meaning.
    assert opening_setting("200:30:2:0:0") == SocietyOpening(200, 30, 2)
    # No minutes is off, whatever the share.
    assert opening_setting("200:0:5").off
    # Under version 1 of the policy three numbers mean exactly what they meant.
    assert opening_setting("200:30:2", load_opening_policy(POLICY_V1_FILE)) == SocietyOpening(
        200, 30, 2
    )


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ("yes", "society_opening_not_recognised"),
        ("150:60", "society_opening_not_recognised"),
        ("150:60:5:1:500:9", "society_opening_not_recognised"),
        ("150:60:5:ten", "society_opening_not_recognised"),
        ("150:60:5:1:1001", "society_opening_share_out_of_bounds"),
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


def test_the_share_doing_something_is_counted_from_the_state_and_unknown_where_it_does_not_say():
    assert active_share_milli(_beings(0)) == 0
    assert active_share_milli(_beings(5)) == 500
    assert active_share_milli(_beings(10)) == 1000
    # Two in seven is 285 thousandths, never rounded up to a share that was not reached.
    assert active_share_milli(_beings(2, beings=7)) == 285
    assert active_share_milli({"inhabitants": []}) is None
    # A living state as this file writes it says who is indoors and not what anyone does.
    assert active_share_milli(_state(3)) is None
    unsaid = _beings(5)
    del unsaid["inhabitants"][2]["action"]["kind"]
    assert active_share_milli(unsaid) is None


def test_a_society_of_things_is_advanced_to_the_first_minute_its_share_is_doing_something():
    # Of 10 beings: all idle at minute 0, then 2, 4 and 5 doing something: exactly half at
    # minute 3, which is the share reached.
    half = SocietyOpening(150, 60, 5, active_share_milli=500, active_state_families=THINGS)
    minutes = Minutes([_beings(n) for n in (0, 2, 4, 5, 9)])
    opened = open_awake(minutes, VERSION, minutes.snapshot(0), half, actor=None, family="things")
    assert opened["current_tick"] == 3
    assert minutes.asked == [(n, f"digest-{n}") for n in range(3)]
    # Already doing something: nothing is advanced.
    busy = Minutes([_beings(6)] * 3)
    assert (
        open_awake(busy, VERSION, busy.snapshot(0), half, actor=None, family="things")[
            "current_tick"
        ]
        == 0
    )
    assert busy.asked == []


def test_what_beings_do_is_read_only_for_the_families_the_opening_names():
    half = SocietyOpening(150, 60, 5, active_share_milli=500, active_state_families=THINGS)
    for family in (None, "purposeful", "legacy", "living"):
        left = Minutes([_beings(n) for n in (0, 2, 4, 6, 9)])
        begun = left.snapshot(0)
        assert open_awake(left, VERSION, begun, half, actor=None, family=family) is begun
        assert left.asked == []
    # No share stated (version 1's values), or no family named: left at its first minute.
    for opening in (
        SocietyOpening(150, 60, 5),
        SocietyOpening(150, 60, 5, active_share_milli=500),
        SocietyOpening(150, 60, 5, active_state_families=THINGS),
    ):
        left = Minutes([_beings(n) for n in (0, 2, 4, 6, 9)])
        begun = left.snapshot(0)
        assert open_awake(left, VERSION, begun, opening, actor=None, family="things") is begun
    # A state that says who is indoors is read by the outdoors share, whatever its family: here
    # everyone is doing something from the start and nobody is outdoors until minute 2.
    indoors = [_state(n) for n in (0, 0, 3, 9)]
    for state in indoors:
        for person in state["inhabitants"]:
            person["action"] = {"kind": "stand"}
    said = Minutes(indoors)
    opened = open_awake(said, VERSION, said.snapshot(0), half, actor=None, family="things")
    assert opened["current_tick"] == 2


def test_the_least_minutes_are_advanced_before_the_seconds_are_counted():
    # A host on which every minute takes 2 s, and a budget of 3 s. Without a least the seconds
    # are spent after two minutes; with a least of 4, four minutes are advanced first.
    def taking_two_seconds(minutes: Minutes):
        return lambda: 2.0 * len(minutes.asked)

    plain = Minutes([_state(0)] * 50)
    opened = open_awake(
        plain,
        VERSION,
        plain.snapshot(0),
        SocietyOpening(150, 40, 3),
        actor=None,
        clock=taking_two_seconds(plain),
    )
    assert opened["current_tick"] == 2
    least = SocietyOpening(150, 40, 3, minutes_minimum=4)
    never = Minutes([_state(0)] * 50)
    opened = open_awake(
        never, VERSION, never.snapshot(0), least, actor=None, clock=taking_two_seconds(never)
    )
    assert opened["current_tick"] == 4
    # The share reached before the least stops it at once: 15 percent at minute 2.
    reached = Minutes([_state(n) for n in (0, 0, 3, 3, 3, 3)])
    opened = open_awake(
        reached, VERSION, reached.snapshot(0), least, actor=None, clock=taking_two_seconds(reached)
    )
    assert opened["current_tick"] == 2
    # A least above the most minutes is held to the most.
    capped = Minutes([_state(0)] * 50)
    opened = open_awake(
        capped,
        VERSION,
        capped.snapshot(0),
        SocietyOpening(150, 3, 3, minutes_minimum=9),
        actor=None,
        clock=taking_two_seconds(capped),
    )
    assert opened["current_tick"] == 3
    # On a clock that never runs out the least changes nothing: the most minutes stop it.
    quick = Minutes([_state(0)] * 50)
    opening = SocietyOpening(150, 7, 5, minutes_minimum=4)
    assert open_awake(quick, VERSION, quick.snapshot(0), opening, actor=None)["current_tick"] == 7


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
    assert services._society_opening("300:20:4") == SocietyOpening(
        300,
        20,
        4,
        active_share_milli=STATED["values"]["active_share_milli"],
        active_state_families=THINGS,
    )
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
