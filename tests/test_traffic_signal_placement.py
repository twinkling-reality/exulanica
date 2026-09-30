"""Signals traffic places by rule where a high street crosses another street.

The ``signal-placement`` catalog's entry names which junctions get a signal: a junction of its
legs where a segment of one of its hierarchies meets another street. The derivation places them
(``exulanica/traffic/city_derivation.py`` ``_signals``) and the road input takes them
(``road_input_from_city(signals=...)``). Without a placement nothing about signals is derived and
the derivation is the v1 one, byte for byte.
"""

from __future__ import annotations

import dataclasses
import hashlib
import math

import pytest
from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.city.catalogs import load_city_catalogs
from exulanica.grammar.grammars.city.generation.corridor import CORRIDOR_CITY_IDENTITY
from exulanica.grammar.grammars.city.roads import JunctionApproachRecord, LaneRecord
from exulanica.grammar.grammars.city.streets import StreetSegmentRecord
from exulanica.grammar.records import record_payload
from exulanica.traffic.catalogs import load_traffic_catalogs
from exulanica.traffic.city_derivation import (
    DERIVATION_PROFILE,
    PLACEMENT_KEY,
    SIGNALS_PROFILE,
    derive_road_records,
)
from exulanica.traffic.city_roads import road_input_from_city
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.network import compile_network
from exulanica.world.generated_worlds import compose_specified_world

import traffic_corridor_support as corridor

#: The corridor's derived records and derivation document, canonical, as the derivation at main
#: 731066f8 (before signals were placed) gave them: computed by loading that commit's
#: city_derivation.py beside this tree's and deriving the corridor with both (6,692 records).
V1_CORRIDOR_SHA256 = "1091ea5d3b3e054bd951159b52f1939f4f6b35039448f28d224c81d2b95c0724"
#: A generated town with a high street crossed by two streets, the lock sample's first world.
PRESET, WORLD_ID = "small_town", "world:generated:departures-0"


def _town():
    composed = compose_specified_world(PRESET, None, WORLD_ID)
    return (
        composed.records,
        str(composed.receipt["subject_identity"]),
        int(composed.receipt["grammar"]["grammar_version"]),
    )


def _derive(records, city, version, placement_key=PLACEMENT_KEY):
    return derive_road_records(
        records,
        load_traffic_catalogs(),
        load_city_catalogs(grammar_version=version),
        city_identity=city,
        placement_key=placement_key,
    )


def test_without_a_placement_the_derivation_is_the_v1_one_byte_for_byte():
    derived = derive_road_records(
        corridor.records(),
        load_traffic_catalogs(),
        load_city_catalogs(grammar_version=corridor.VERSION),
        city_identity=CORRIDOR_CITY_IDENTITY,
    )
    assert derived.signals == () and derived.placement is None
    assert derived.document()["profile"] == DERIVATION_PROFILE
    body = canonical_json(
        {"records": [record_payload(r) for r in derived.records], "document": derived.document()}
    )
    assert hashlib.sha256(body).hexdigest() == V1_CORRIDOR_SHA256


def test_a_signal_is_placed_where_the_high_street_crosses_a_street_and_runs_a_phase_each():
    records, city, version = _town()
    derived = _derive(records, city, version)
    catalogs = load_traffic_catalogs()
    placement = catalogs.placement(PLACEMENT_KEY)
    segments = {r.identity: r for r in records if type(r) is StreetSegmentRecord}
    lanes = {r.identity: r for r in records if type(r) is LaneRecord}
    ranks = {
        (r.junction_identity, r.segment_identity): r.priority_rank
        for r in records
        if type(r) is JunctionApproachRecord
    }
    named = [
        r
        for r in records
        if type(r).__name__ == "JunctionRecord"
        and len(r.segment_identities) == placement.legs
        and any(segments[s].hierarchy in placement.hierarchies for s in r.segment_identities)
    ]
    # The positive control: the town has junctions the rule names.
    assert named
    placed = sorted(signal.junction for signal in derived.signals)
    assert placed == sorted(r.identity for r in named)
    assert derived.document()["profile"] == SIGNALS_PROFILE
    connections = {c.identity: c for c in derived.connections}
    for signal in derived.signals:
        groups = {group.group: group for group in signal.groups}
        assert set(groups) == {"phase_a", "phase_b", "walk_a", "walk_b"}
        # The first phase is the street the city makes the major road, the second the other.
        for phase, rank in (("phase_a", 0), ("phase_b", 1)):
            assert groups[phase].connections
            for identity in groups[phase].connections:
                source = lanes[connections[identity].from_lane_identity].segment_identity
                assert ranks[(signal.junction, source)] == rank
        # Walkers cross the street whose traffic is held: the minor street during phase_a.
        for walk, crossed_rank in (("walk_a", 1), ("walk_b", 0)):
            assert groups[walk].crossings
            for identity in groups[walk].crossings:
                crossing = next(r for r in records if getattr(r, "identity", None) == identity)
                assert ranks[(signal.junction, crossing.segment_identity)] == crossed_rank
    network = compile_network(
        road_input_from_city(
            derived.records, catalogs, city_identity=city, signals=derived.signals
        ),
        catalogs,
    )
    for signal in derived.signals:
        junction = network.junctions[signal.junction]
        assert junction.rule == "signal" and junction.signal.identity == signal.identity


def test_a_named_junction_whose_city_ranks_no_one_street_major_is_refused_by_name():
    records, city, version = _town()
    derived = _derive(records, city, version)
    junction = derived.signals[0].junction
    # One leg of the major road made a stop approach: the city's ranks no longer name one street
    # as the major road (the priority junction still compiles, one major approach and three
    # stopping), so no street runs the first phase.
    [demoted] = [
        r
        for r in records
        if type(r) is JunctionApproachRecord
        and r.junction_identity == junction
        and r.priority_rank == 0
    ][:1]
    planted = tuple(
        dataclasses.replace(r, priority_rank=1, control="stop") if r is demoted else r
        for r in records
    )
    with pytest.raises(UnsupportedNetworkError, match="ranks no one street its major road"):
        _derive(planted, city, version)


def test_a_placed_signal_for_a_junction_that_has_one_is_refused():
    records, city, version = _town()
    derived = _derive(records, city, version)
    catalogs = load_traffic_catalogs()
    signal = derived.signals[0]
    twice = (signal, dataclasses.replace(signal, identity=f"{signal.identity}-again"))
    with pytest.raises(UnsupportedNetworkError, match="which has a signal"):
        road_input_from_city(derived.records, catalogs, city_identity=city, signals=twice)


def test_a_window_serves_each_signal_s_heads_and_what_each_group_shows_every_second():
    """The window's signals are the network's, and each group's codes are what the plan shows at
    each second of the episode, the indications the step obeyed."""
    from exulanica.traffic.signals import (
        PEDESTRIAN_INDICATIONS,
        VEHICLE_INDICATIONS,
        pedestrian_indication,
        vehicle_indication,
    )
    from exulanica.world.traffic_episodes import (
        compute_episode,
        prepared,
        traffic_input,
        window_of,
        wire,
    )

    composed = compose_specified_world(PRESET, None, WORLD_ID)
    value = traffic_input(
        world_id=WORLD_ID,
        version_id=composed.receipt_sha256,
        city_identity=str(composed.receipt["subject_identity"]),
        grammar_version=int(composed.receipt["grammar"]["grammar_version"]),
        records=composed.records,
    )
    ready = prepared(value)
    episode = compute_episode(wire(value), 0)
    start, seconds = 25, 60
    window = window_of(value, {0: episode}, start, seconds)
    assert window["indications"] == {
        "vehicle": list(VEHICLE_INDICATIONS),
        "pedestrian": list(PEDESTRIAN_INDICATIONS),
    }
    signalled = sorted(
        junction.signal.identity
        for junction in ready.network.junctions.values()
        if junction.signal is not None
    )
    assert signalled and [signal["signal_id"] for signal in window["signals"]] == signalled
    for served in window["signals"]:
        spec = ready.network.junctions[served["junction_id"]].signal
        plan = ready.catalogs.plan(spec.plan)
        assert [group["group"] for group in served["groups"]] == [g.key for g in plan.groups]
        for group in served["groups"]:
            assert group["points_mm"] and len(group["codes"]) == seconds
            for index, code in enumerate(group["codes"]):
                second = start + index
                if group["kind"] == "vehicle":
                    shown = vehicle_indication(plan, spec.offset_s, second, group["group"])
                    assert VEHICLE_INDICATIONS[code] == shown
                else:
                    shown = pedestrian_indication(plan, spec.offset_s, second, group["group"])
                    assert PEDESTRIAN_INDICATIONS[code] == shown
        # A vehicle head stands level with the stop line of each lane its group releases, beside the
        # lane on the right, outside the corridor its vehicles sweep, so none drives through it.
        lanes = {
            ready.network.paths[connector].predecessors[0]
            for connector, group in spec.connector_groups
        }
        heads = [
            tuple(point)
            for group in served["groups"]
            if group["kind"] == "vehicle"
            for point in group["points_mm"]
        ]
        assert len(heads) == len(lanes)
        for lane_id in lanes:
            lane = ready.network.paths[lane_id]
            (ax, ay), (bx, by) = lane.line.piece(lane.line.piece_count - 1)
            run = math.hypot(bx - ax, by - ay)
            beside = [
                (x, y)
                for x, y in heads
                if abs((x - bx) * (bx - ax) + (y - by) * (by - ay)) / run <= 2
                and ((bx - ax) * (y - ay) - (by - ay) * (x - ax)) / run
                <= -(lane.extents[-1][1] - 2)
            ]
            assert len(beside) == 1, (lane_id, heads)
        # A minute of a 60 second plan shows every vehicle indication.
        assert {
            code
            for group in served["groups"]
            if group["kind"] == "vehicle"
            for code in group["codes"]
        } == {0, 1, 2}


@pytest.mark.parametrize("high_streets", [1, 2, 3])
@pytest.mark.parametrize("cross", ["local_street", "narrow_street"])
def test_city_grammar_v5_crossroads_get_signals_high_or_narrow_and_two_high_streets(
    high_streets, cross
):
    """At city grammar version 5 a town has up to three high streets and local or narrow cross
    streets: every crossroads the placement names gets a signal whose first phase is the city's
    major road, a crossroads of two high streets included, and the town's traffic runs."""
    from exulanica.grammar.grammars.city.roads import JunctionRecord

    import test_city_grammar_v5 as v5

    _seed, records = v5._records(high_street_count=high_streets, cross_street_hierarchy=cross)
    derived = _derive(records, v5._IDENTITY, 5)
    segments = {r.identity: r for r in records if type(r) is StreetSegmentRecord}
    crossroads = [
        r
        for r in records
        if type(r) is JunctionRecord
        and len(r.segment_identities) == 4
        and any(segments[s].hierarchy == "high_street" for s in r.segment_identities)
    ]
    assert crossroads, "the town has crossroads on a high street"
    assert sorted(s.junction for s in derived.signals) == sorted(r.identity for r in crossroads)
    catalogs = load_traffic_catalogs()
    network = compile_network(
        road_input_from_city(
            derived.records, catalogs, city_identity=v5._IDENTITY, signals=derived.signals
        ),
        catalogs,
    )
    assert all(network.junctions[r.identity].rule == "signal" for r in crossroads)
