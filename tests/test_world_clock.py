"""The world clock's pure parts: its profiles, its timelines, the crossing occupancy a society
minute records, the feed traffic reads from it, and the demand envelope; and, over a generated
town with no database, that walkers reach its traffic and no car enters an occupied crossing."""

from __future__ import annotations

import copy

import pytest
from exulanica.traffic.inputs import LOOKAHEAD_S, CrossingEntry, CrossingFeed
from exulanica.world.traffic_episodes import EPISODE
from exulanica.world.world_clock import (
    COUPLED,
    LEGACY,
    ClockRefused,
    Era,
    clock_profile,
    clock_profiles,
    crossing_edges,
    crossing_feeds,
    envelope_report,
    feed_projection_sha256,
    lead_room,
    minute_occupancy,
    occupancy_intervals,
    timeline_origin,
    traffic_timebase,
)

from living_town_support import town_input
from world_clock_support import (
    ORIGIN,
    band_identities,
    drive,
    episode_feeds,
    judged,
    town_roads,
    walk,
)

# -- profiles and timelines -----------------------------------------------------------------------


def test_the_profiles_state_what_each_system_does_and_only_the_coupled_one_couples():
    profiles = clock_profiles()
    assert set(profiles) == {LEGACY, COUPLED}
    legacy, coupled = profiles[LEGACY], profiles[COUPLED]
    assert (legacy.lead_ticks, legacy.crossings_fed) == (0, False)
    assert (coupled.lead_ticks, coupled.crossings_fed) == (2, True)
    # The lead is the least that lets traffic advance: its lookahead in minutes, and one more.
    assert coupled.lead_ticks == -(-LOOKAHEAD_S // coupled.seconds_per_tick) + 1
    assert coupled.crossing_lookahead_seconds == LOOKAHEAD_S
    assert (traffic_timebase(LEGACY), traffic_timebase(COUPLED)) == ("unix", "world")
    assert legacy.traffic_module.endswith("roads/v1") and coupled.profile.endswith("coupled-v1")
    with pytest.raises(ClockRefused) as refused:
        clock_profile("real_time_everywhere")
    assert refused.value.code == "clock_profile_unknown"


@pytest.mark.parametrize(
    ("now", "latest", "expected"),
    [
        (1_790_000_000, None, 1_790_000_400),
        # On a boundary, strictly after it: a legacy segment ending there keeps its second.
        (1_789_999_200, None, 1_790_000_400),
        (1_790_000_000, 1_790_001_600, 1_790_002_800),
        (1_790_001_000, 1_790_000_100, 1_790_001_600),
    ],
)
def test_a_timeline_origin_is_a_whole_episode_after_the_clock_and_every_legacy_segment(
    now, latest, expected
):
    origin = timeline_origin(now, latest)
    assert origin == expected
    assert origin % EPISODE == 0 and origin > now and (latest is None or origin > latest)


def test_an_era_maps_ticks_traffic_seconds_and_flight_steps_both_ways():
    era = Era(1, 725, 60, ORIGIN)
    assert era.start_world_second == 43_500
    # Tick 726's minute covers world seconds [43500, 43560): traffic's first minute of the era.
    assert era.traffic_second(era.world_second_of_tick(725)) == ORIGIN
    assert era.world_second(ORIGIN + 61) == 43_561
    assert era.flight_step(43_500) == ORIGIN * 10
    assert era.world_second_of_step(ORIGIN * 10 + 615) == 43_561


def test_lead_room_is_what_the_society_may_still_commit_before_traffic_seals_again():
    assert lead_room(2, 10, 10) == 2
    assert lead_room(2, 11, 10) == 1
    assert lead_room(2, 12, 10) == 0
    assert lead_room(2, 13, 10) == 0


# -- a minute's occupancy -------------------------------------------------------------------------

EDGE = {
    "edge_id": "footway:3:left:900|footway:3:right:900",
    "from_node_id": "footway:3:left:900",
    "to_node_id": "footway:3:right:900",
    "from_position_mm": [0, 0],
    "to_position_mm": [12_000, 0],
    "length_mm": 12_000,
}
CROSSINGS = {EDGE["edge_id"]: "crossing-record-a"}


def _person(identity: str, *, edge: dict | None, speed: int = 72_000) -> dict:
    return {
        "id": identity,
        "walk_speed_mm_per_tick": speed,
        "location": {
            "node_id": None if edge else "footway:1:left:0",
            "edge": edge,
            "spot_id": None,
            "destination_id": None,
            "indoors": False,
        },
    }


def _states(before_people: list[dict], after_people: list[dict], tick: int = 40):
    return (
        {"tick": tick - 1, "inhabitants": before_people},
        {"tick": tick, "inhabitants": after_people},
    )


def test_an_entered_crossing_is_shifted_to_world_seconds_as_recorded():
    before, after = _states([_person("p", edge=None)], [_person("p", edge=None)])
    events = [
        {
            "tick": 40,
            "subject_id": "p",
            "crossings": [
                {"crossing_id": "crossing-record-a", "arrival_second": 51, "duration_seconds": 11}
            ],
        }
    ]
    document = minute_occupancy(
        society_id="s",
        era=1,
        before=before,
        after=after,
        events=events,
        crossings_by_edge=CROSSINGS,
        place_sha256="0" * 64,
    )
    # Tick 40's minute begins at world second 2340; the walk runs past the minute's end.
    assert document["intervals"] == [
        {
            "crossing_id": "crossing-record-a",
            "from_second": 2391,
            "through_second": 2402,
            "subject_id": "p",
            "basis": "entered",
        }
    ]
    assert document["minute_start_second"] == 2340 and len(document["document_sha256"]) == 64


def test_a_walker_standing_on_a_crossing_holds_it_the_whole_minute_though_it_records_no_entry():
    # Stopped part way across (its plan abandoned, or waiting): no leg enters the crossing, so
    # no event records it, and the minute's recorded entries would leave the crossing free.
    standing = _person("p", edge={**EDGE, "progress_mm": 5_000})
    before, after = _states([standing], [copy.deepcopy(standing)])
    document = minute_occupancy(
        society_id="s",
        era=1,
        before=before,
        after=after,
        events=[],
        crossings_by_edge=CROSSINGS,
        place_sha256="0" * 64,
    )
    assert [(i["from_second"], i["through_second"], i["basis"]) for i in document["intervals"]] == [
        (2340, 2399, "on_crossing_at_minute_start")
    ]


def test_a_walker_leaving_a_crossing_holds_it_until_the_rest_of_it_is_walked():
    on = _person("p", edge={**EDGE, "progress_mm": 6_000}, speed=72_000)
    off = _person("p", edge=None)
    before, after = _states([on], [off])
    document = minute_occupancy(
        society_id="s",
        era=1,
        before=before,
        after=after,
        events=[],
        crossings_by_edge=CROSSINGS,
        place_sha256="0" * 64,
    )
    # 6,000 mm left at 72,000 mm a minute is five seconds: the floor, whose claim reaches the next.
    assert [(i["from_second"], i["through_second"]) for i in document["intervals"]] == [
        (2340, 2345)
    ]


def test_an_entry_of_another_minute_or_of_a_crossing_the_place_does_not_hold_is_refused():
    before, after = _states([], [])
    with pytest.raises(ClockRefused, match="crossing_occupancy_mismatch"):
        minute_occupancy(
            society_id="s",
            era=1,
            before=before,
            after=after,
            events=[{"tick": 39, "subject_id": "p", "crossings": []}],
            crossings_by_edge=CROSSINGS,
            place_sha256="0" * 64,
        )
    with pytest.raises(ClockRefused, match="crossing_occupancy_mismatch"):
        minute_occupancy(
            society_id="s",
            era=1,
            before=before,
            after=after,
            events=[
                {
                    "tick": 40,
                    "subject_id": "p",
                    "crossings": [
                        {"crossing_id": "elsewhere", "arrival_second": 3, "duration_seconds": 9}
                    ],
                }
            ],
            crossings_by_edge=CROSSINGS,
            place_sha256="0" * 64,
        )
    with pytest.raises(ClockRefused, match="crossing_edge_ambiguous"):
        crossing_edges(
            [
                {"crossings": [{"edge_id": "e", "crossing_id": "a"}]},
                {"crossings": [{"edge_id": "e", "crossing_id": "b"}]},
            ]
        )


# -- the feed -------------------------------------------------------------------------------------


def _interval(first: int, last: int, crossing: str = "record-a", who: str = "p") -> dict:
    return {
        "crossing_id": crossing,
        "from_second": first,
        "through_second": last,
        "subject_id": who,
        "basis": "entered",
        "tick": first // 60 + 1,
    }


def test_the_feed_clips_to_its_episode_holds_each_interval_once_and_grows_without_changing():
    era = Era(1, 0, 60, ORIGIN)
    bands = {"record-a": "crossing:3:900"}
    intervals = [
        _interval(-5, 7),  # begun before the episode: clipped to its start
        _interval(100, 111),  # feed 1 holds its first two minutes
        _interval(185, 185),  # a single second still holds its band a second
        _interval(1250, 1262),  # the next episode's first minute, inside the lookahead
        _interval(-90, -80),  # over before the episode: left out
    ]
    small = crossing_feeds(
        intervals,
        era=era,
        episode_first_second=ORIGIN,
        covers_through_local_second=179,
        bands=bands,
    )
    assert [feed.covers_through_second for feed in small] == [119, 179]
    assert small[0].entries == (
        CrossingEntry("crossing:3:900", 0, 7, "p:0:entered"),
        CrossingEntry("crossing:3:900", 100, 11, "p:2:entered"),
    )
    assert small[1].entries == ()
    full = crossing_feeds(
        intervals,
        era=era,
        episode_first_second=ORIGIN,
        covers_through_local_second=EPISODE + LOOKAHEAD_S - 1,
        bands=bands,
    )
    assert len(full) == 20 and full[-1].covers_through_second == EPISODE + LOOKAHEAD_S - 1
    # What a feed holds does not depend on how far the episode is sealed.
    assert full[:2] == small
    assert feed_projection_sha256(full[:2]) == feed_projection_sha256(small)
    assert full[2].entries == (CrossingEntry("crossing:3:900", 185, 1, "p:4:entered"),)
    assert full[19].entries == (CrossingEntry("crossing:3:900", 1250, 12, "p:21:entered"),)
    with pytest.raises(ClockRefused, match="crossing_occupancy_unmapped"):
        crossing_feeds(
            [_interval(10, 20, crossing="record-b")],
            era=era,
            episode_first_second=ORIGIN,
            covers_through_local_second=119,
            bands=bands,
        )
    with pytest.raises(ClockRefused, match="crossing_feed_span"):
        crossing_feeds(
            [], era=era, episode_first_second=ORIGIN, covers_through_local_second=150, bands=bands
        )


def test_the_envelope_names_the_windows_without_a_long_enough_free_run():
    report = envelope_report(
        [("a", 10, 20), ("a", 100, 179), ("b", 0, 399)],
        start=0,
        end=400,
        window_seconds=180,
        gap_seconds=62,
    )
    # Free runs of a: 0-9, 21-99 (79 s) and 180-399. A window starting at 39 to 61 holds neither
    # 62 seconds of 21-99 nor of 180 onwards.
    assert report["a"]["outside_window_starts"] == [[39, 61]]
    assert report["a"]["longest_occupied_run_seconds"] == 80
    assert report["b"]["outside_window_starts"] == [[0, 220]]
    assert report["b"]["occupied_seconds"] == 400


# -- a generated town, coupled without a database ------------------------------------------------


@pytest.fixture(scope="module")
def small_town():
    walked = walk(warm=120, minutes=22)
    value, ready = town_roads()
    return walked, value, ready


def test_the_town_s_people_walk_exactly_the_crossings_its_roads_carry_as_bands(small_town):
    walked, _value, ready = small_town
    place = town_input()["living"]["place"]
    assert {crossing["crossing_id"] for crossing in place["crossings"]} == set(
        band_identities(ready)
    )
    assert all(band.junction is not None for band in ready.network.bands)
    crossings = {i["crossing_id"] for i in occupancy_intervals(walked.occupancy)}
    assert crossings, "the town's people crossed a carriageway in these minutes"


def test_a_walker_who_keeps_walking_is_already_covered_by_the_crossing_it_entered(small_town):
    walked, _value, _ready = small_town
    intervals = occupancy_intervals(walked.occupancy)
    entered = [i for i in intervals if i["basis"] == "entered"]
    standing = [i for i in intervals if i["basis"] == "on_crossing_at_minute_start"]
    assert standing, "somebody was part way across a street as a minute began"
    for interval in standing:
        if interval["through_second"] == interval["from_second"] + 59:
            continue  # still on it at the minute's end: the next minute's interval goes on
        if interval["from_second"] == walked.era.start_world_second:
            continue  # entered before the era, where no occupancy is recorded
        assert any(
            other["crossing_id"] == interval["crossing_id"]
            and other["subject_id"] == interval["subject_id"]
            and other["from_second"] <= interval["from_second"]
            and interval["through_second"] <= other["through_second"]
            for other in entered
        ), interval


def test_walkers_reach_the_town_s_traffic_and_no_car_enters_an_occupied_crossing(small_town):
    walked, value, ready = small_town
    episode = ORIGIN // EPISODE
    feeds = episode_feeds(walked, ready, episode, through_segment=19)
    fed = sum(len(feed.entries) for feed in feeds)
    assert fed > 0, "the feed carries the walkers the society recorded"
    states, continuation = drive(value, ready, episode, 20, feeds)
    assert judged(ready, states, continuation, feeds) == []
    waited = {
        vehicle["id"]
        for state in states
        for vehicle in state["vehicles"]
        if vehicle["wait_reason"] == "pedestrian_due"
    }
    assert waited, "some vehicle waited for a walker the feed put on a crossing"


def test_the_checker_catches_the_cars_a_feed_would_have_stopped(small_town):
    """The control: every crossing held from the second minute on stops every car at them when
    it is fed, and the same traffic run with nobody walking is caught driving through them."""
    _walked, value, ready = small_town
    episode = ORIGIN // EPISODE
    planted = tuple(
        sorted(
            (
                CrossingEntry(band.society_crossing_id, 60, EPISODE, "planted")
                for band in ready.network.bands
            ),
            key=lambda entry: (entry.arrival_second, entry.crossing_id, entry.source),
        )
    )
    held = tuple(
        CrossingFeed(seq, 60 * seq + 59, planted if seq == 1 else ()) for seq in range(1, 21)
    )
    fed_states, fed_continuation = drive(value, ready, episode, 20, held)
    assert judged(ready, fed_states, fed_continuation, held) == []
    blind_states, blind_continuation = drive(value, ready, episode, 20, None)
    caught = judged(ready, blind_states, blind_continuation, held)
    assert caught and {violation.kind for violation in caught} == {"crossing_conflict"}
