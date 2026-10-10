"""A town's people are admitted by the measured cost of their minute, not by a head count.

The society ground catalog's sixth version states no head count for a town. It states, for each
engine a town's society is made with, the 95th percentile minute a measurement took at several
populations on each walking graph it ran over, and the share of a host's slowest minute a society
may take. The figures below were typed from the scale record itself (profile
``exulanica.worlds-measure-scale/v1``, SHA-256 ``6f0cf86f...``), each ``minute_wall_ms.p95`` in
microseconds, and every expected reading was worked by hand from them, so neither comes from the
reader under test.
"""

from __future__ import annotations

import json

import pytest
from exulanica.api.services import SocietySettingRefused, _minute_cost_scale_milli
from exulanica.grammar.errors import CatalogError
from exulanica.world.society_engines import ENGINES
from exulanica.world.society_grounds import (
    CATALOG_DIRECTORY,
    CATALOG_VERSION,
    SocietyPopulationRefused,
    admit_people_by_cost,
    load_society_grounds,
    refuse_population,
    server_runs,
    society_ground_for_composer,
    society_grounds,
)
from exulanica.world.society_minute_cost import (
    ESTIMATE,
    MEASURED,
    HostMinute,
    MinuteEstimate,
    PeopleCeiling,
    estimated_minute,
    people_within,
)

V2, V5, V7 = "exulanica-society/v2", "exulanica-society/v5", "exulanica-society/v7"
RECORD = {
    "profile": "exulanica.worlds-measure-scale/v1",
    "sha256": "6f0cf86f18afc8c79055966cf6427e9b3c1301c98f7c547749f25381e66765a9",
}
#: ``{engine: {walking nodes: [(people, p95 minute in microseconds)]}}``, as the record states
#: them: the small town preset and the market town, the living town over a day and the society
#: of things over two hours.
MEASURED_POINTS = {
    V5: {
        632: [(50, 3_901), (100, 7_530), (250, 27_222), (500, 46_571), (1000, 82_815)],
        950: [(84, 7_685), (100, 9_304), (250, 29_879), (500, 50_885), (1000, 93_419)],
    },
    V7: {
        666: [(102, 54_996), (252, 109_366), (502, 209_478)],
        1002: [(102, 73_004), (252, 155_692), (502, 297_778)],
    },
}
#: The purposeful society's two figures, as the catalog's fifth version and the specification's
#: tick reason state them: one tick of 128 people at the 95th percentile, 78 ms on 387 walking
#: nodes and 159 ms on 962.
STATED_POINTS = {V2: {387: [(128, 78_000)], 962: [(128, 159_000)]}}
#: A host that states nothing: an 8 s base interval at its slowest speed, the measured machine.
DEFAULT_HOST = HostMinute(slowest_minute_ms=8_000)


def _town():
    return society_ground_for_composer("city-grammar-town")


def _cost(engine: str):
    return next(cost for cost in _town().minute_cost if cost.engine == engine)


def test_a_town_states_no_head_count_and_the_measured_points_of_each_engine():
    town = _town()
    assert town.population == 0 and town.population_rule == "residents"
    read = {
        cost.engine: {graph.walking_nodes: list(graph.points) for graph in cost.graphs}
        for cost in town.minute_cost
    }
    assert read == {**MEASURED_POINTS, **STATED_POINTS}
    # The engines measured in the run name its record and its machine; the one measured without
    # a record says so rather than borrowing one.
    for engine in (V5, V7):
        cost = _cost(engine)
        assert cost.record == RECORD
        assert (cost.machine, cost.runtime) == ("macOS-26.7-arm64-arm-64bit", "Python 3.11.6")
    assert _cost(V2).record is None and "No record" in _cost(V2).source
    # A tenth of the slowest minute, and every other ground still states its head count.
    assert town.minute_share_milli == 100
    others = {g.key: (g.population, g.minute_cost, g.minute_share_milli) for g in society_grounds()}
    del others["generated_town"]
    assert others == {
        "authored_starter": (8, (), 0),
        "made_world": (8, (), 0),
        "generated_site": (128, (), 0),
    }


def test_every_engine_a_towns_society_is_made_with_states_its_points():
    made_with = {
        engine.engine
        for engine in ENGINES
        if engine.creatable and engine.saved_world and engine.takes_inputs
    }
    assert made_with == {V2, V5, V7} == {cost.engine for cost in _town().minute_cost}


@pytest.mark.parametrize(
    ("engine", "people", "nodes", "expected"),
    [
        # At a measured point, the point itself.
        (V7, 252, 1002, MinuteEstimate(155_692, MEASURED)),
        (V5, 1000, 632, MinuteEstimate(82_815, MEASURED)),
        # Between two: 73,004 + (155,692 - 73,004) * 26 / 150, rounded up.
        (V7, 128, 1002, MinuteEstimate(87_337, MEASURED)),
        # Fewer people than any run held: the first point, which never understates.
        (V7, 10, 666, MinuteEstimate(54_996, MEASURED)),
        # A town is read on the smallest measured graph at or above its own nodes.
        (V7, 252, 632, MinuteEstimate(109_366, MEASURED)),
        (V7, 252, 667, MinuteEstimate(155_692, MEASURED)),
        # Past the last point by people: 297,778 + (297,778 - 155,692) * 126 / 250, rounded up.
        (V7, 628, 1002, MinuteEstimate(369_390, ESTIMATE)),
        # A graph larger than any measured: the largest row, in proportion to the nodes.
        (V7, 128, 1300, MinuteEstimate(113_312, ESTIMATE)),
        # One measured population states no rise: past it, in proportion to the people.
        (V2, 128, 632, MinuteEstimate(159_000, MEASURED)),
        (V2, 256, 632, MinuteEstimate(318_000, ESTIMATE)),
    ],
)
def test_a_minute_is_read_between_measured_points_and_named_an_estimate_past_them(
    engine, people, nodes, expected
):
    assert estimated_minute(_cost(engine), people, nodes) == expected


def test_a_hosts_scale_multiplies_every_reading():
    cost = _cost(V7)
    assert estimated_minute(cost, 128, 1002, scale_milli=2_000).microseconds == 174_674
    assert estimated_minute(cost, 128, 1002, scale_milli=500).microseconds == 43_669
    with pytest.raises(ValueError, match="at least one"):
        estimated_minute(cost, 0, 1002)


def test_an_estimate_is_served_with_its_name_beside_the_figure():
    assert MinuteEstimate(369_390, ESTIMATE).document() == {"minute_ms": 370, "basis": "estimate"}
    assert PeopleCeiling(1385, ESTIMATE).document() == {"people": 1385, "basis": "estimate"}


def test_the_most_people_a_server_runs_is_the_last_whose_minute_fits():
    # By hand on the market town's graph at 800 ms: 1,385 people take 799,626 microseconds and
    # 1,386 take 800,195, both past the last measured point.
    assert server_runs(_town(), V7, 1002, DEFAULT_HOST) == PeopleCeiling(1385, ESTIMATE)
    # Whatever the search, the answer is the last that fits, for every engine, graph and host.
    hosts = (DEFAULT_HOST, HostMinute(60_000), HostMinute(8_000, 3_000), HostMinute(1_000, 4_000))
    for cost in _town().minute_cost:
        for nodes in (300, 666, 1002, 2_000):
            for host in hosts:
                budget = host.budget_us(_town().minute_share_milli)
                runs = people_within(cost, nodes, budget, scale_milli=host.cost_scale_milli)
                scale = host.cost_scale_milli

                def minute(people, cost=cost, nodes=nodes, scale=scale):
                    return estimated_minute(cost, people, nodes, scale_milli=scale)

                assert minute(runs.people + 1).microseconds > budget
                if runs.people:
                    assert minute(runs.people).microseconds <= budget
                    assert runs.basis == minute(runs.people).basis
    # A ceiling inside the measured points is not called an estimate, and a host too slow for
    # one person runs nobody.
    assert people_within(_cost(V7), 1002, 155_692) == PeopleCeiling(252, MEASURED)
    assert people_within(_cost(V7), 1002, 73_003).people == 0
    # A ground that states a head count states no ceiling by cost.
    assert server_runs(society_ground_for_composer("site-plan"), V5, 900, DEFAULT_HOST) is None


def _first_input(people: int, nodes: int, profile: str = "city-walking-surfaces/v1") -> dict:
    return {
        "navigation": {"profile": profile, "nodes": [{"node_id": f"n{i}"} for i in range(nodes)]},
        "population": {"rule": "residents", "size": people},
    }


def test_a_new_society_is_admitted_by_the_cost_of_its_minute_on_the_host_that_makes_it():
    # What a new town starts with, on each engine, is far inside a default host's minute.
    for engine in (V2, V5, V7):
        admit_people_by_cost(_first_input(128, 1002), engine, DEFAULT_HOST)
    admit_people_by_cost(_first_input(1385, 1002), V7, DEFAULT_HOST)
    with pytest.raises(SocietyPopulationRefused) as refused:
        admit_people_by_cost(_first_input(1386, 1002), V7, DEFAULT_HOST)
    assert refused.value.code == "people_over_cost"
    # The refusal says the minute, what the server gives one and what it runs, each estimate
    # named as one.
    assert refused.value.detail == (
        "a minute of 1386 people here takes about 801 ms (an estimate, read past the last "
        "measured point), and this server gives a minute 800 ms; it runs about 1385 people "
        "(an estimate, read past the last measured point) here"
    )
    # A host with a longer minute runs them; one whose machine is three times slower does not
    # run 502, a measured point, and says so without calling it an estimate.
    admit_people_by_cost(_first_input(1386, 1002), V7, HostMinute(60_000))
    with pytest.raises(SocietyPopulationRefused) as slower:
        admit_people_by_cost(_first_input(502, 1002), V7, HostMinute(8_000, 3_000))
    assert slower.value.detail.startswith("a minute of 502 people here takes 894 ms, and")
    # The living town's minute is the cheap one: the same people, the same graph, admitted.
    admit_people_by_cost(_first_input(1386, 1002), V5, DEFAULT_HOST)


def test_an_engine_with_no_measured_minute_is_refused_by_name_and_other_grounds_are_not_asked():
    with pytest.raises(SocietyPopulationRefused) as refused:
        admit_people_by_cost(_first_input(128, 1002), "exulanica-society/v4", DEFAULT_HOST)
    assert refused.value.code == "minute_cost_not_measured"
    # A ground that states a head count is not admitted by cost, whatever the host.
    slow = HostMinute(1_000, 1_000_000)
    admit_people_by_cost(_first_input(8, 121, "authored-ground-lattice/v1"), V2, slow)
    admit_people_by_cost(_first_input(128, 900, "site-walking-surfaces/v1"), V5, slow)
    # An input that states no walking graph is refused where the society is made, not here.
    admit_people_by_cost(_first_input(128, 0), V7, slow)


def test_a_town_refuses_nobody_and_no_head_count():
    town = _town()
    refuse_population(100_000, town)
    with pytest.raises(SocietyPopulationRefused) as nobody:
        refuse_population(0, town)
    assert nobody.value.code == "world_holds_no_residents"
    site = society_ground_for_composer("site-plan")
    refuse_population(128, site)
    with pytest.raises(SocietyPopulationRefused) as over:
        refuse_population(129, site)
    assert over.value.code == "population_over_tick_budget"


def test_every_published_version_of_the_ground_catalog_still_reads():
    assert CATALOG_VERSION == 6
    by_version = {
        version: {ground.key: ground for ground in load_society_grounds(version=version)}
        for version in range(1, CATALOG_VERSION + 1)
    }
    # The fifth version keeps the head count it stated, and no version before the sixth states a
    # measured cost.
    assert by_version[5]["generated_town"].population == 128
    assert all(
        not ground.minute_cost and not ground.minute_share_milli
        for version in range(1, CATALOG_VERSION)
        for ground in by_version[version].values()
    )
    # Apart from the head count and the cost, the sixth version's grounds are the fifth's.
    for key, ground in by_version[6].items():
        earlier = by_version[5][key]
        for name in ("composer_key", "navigation_profile", "navigation", "arrival", "floor"):
            assert getattr(ground, name) == getattr(earlier, name)
        assert ground.population_kind == earlier.population_kind
        assert ground.record_subjects == earlier.record_subjects


def _malformed(tmp_path, change) -> None:
    for path in CATALOG_DIRECTORY.glob("*.json"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    current = f"society-ground.v{CATALOG_VERSION}.json"
    document = json.loads((CATALOG_DIRECTORY / current).read_text("utf-8"))
    change({entry["key"]: entry for entry in document["entries"]})
    (tmp_path / current).write_text(json.dumps(document), encoding="utf-8")
    load_society_grounds(tmp_path)


def _graph(entries, engine: int = 2, graph: int = 0) -> dict:
    return entries["generated_town"]["minute_cost"][engine]["graphs"][graph]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda e: e["generated_town"].update(minute_cost=[]), "states the measured cost"),
        (lambda e: e["generated_town"].update(minute_share_milli=0), "states the measured cost"),
        (lambda e: e["generated_town"].update(minute_share_milli=1001), r"an int in \[0, 1000\]"),
        (lambda e: e["generated_town"].update(population=128), "states no measured cost"),
        (lambda e: e["authored_starter"].update(population=0), "people are the world's own"),
        (lambda e: e["generated_site"].update(minute_share_milli=100), "states no measured cost"),
        (lambda e: e["generated_town"]["minute_cost"].pop(), "the engines a town's society"),
        (
            lambda e: e["generated_town"]["minute_cost"][0].update(engine="exulanica-society/v4"),
            "the engines a town's society",
        ),
        (
            lambda e: e["generated_town"]["minute_cost"].append(
                dict(e["generated_town"]["minute_cost"][0])
            ),
            "names an engine twice",
        ),
        (lambda e: _graph(e)["points"].reverse(), "in order of people"),
        (lambda e: _graph(e)["points"][1].update(minute_p95_us=1), "never falls"),
        (
            lambda e: _graph(e)["points"][-1].update(
                minute_p95_us=_graph(e)["points"][-2]["minute_p95_us"]
            ),
            "rises above the one before",
        ),
        (lambda e: _graph(e)["points"].clear(), "at least one measured point"),
        (lambda e: _graph(e)["points"][0].update(people=0), "positive integer"),
        (lambda e: _graph(e)["points"][0].update(minute_ms=1), "states exactly"),
        (lambda e: _graph(e, graph=1).update(walking_nodes=1), "in order of walking nodes"),
        (
            lambda e: e["generated_town"]["minute_cost"][1]["record"].update(sha256="6f0cf86f"),
            "SHA-256",
        ),
        (lambda e: e["generated_town"]["minute_cost"][1].pop("machine"), "states exactly"),
    ],
    ids=[
        "no-head-count-and-no-cost",
        "no-share",
        "more-than-a-whole-minute",
        "a-head-count-and-a-cost",
        "a-lattice-with-no-head-count",
        "a-head-count-and-a-share",
        "an-engine-unmeasured",
        "an-engine-no-town-is-made-with",
        "an-engine-twice",
        "points-out-of-order",
        "a-minute-that-falls",
        "no-rise-at-the-end",
        "no-points",
        "nobody",
        "another-figure",
        "graphs-out-of-order",
        "a-short-digest",
        "no-machine",
    ],
)
def test_a_malformed_minute_cost_is_refused(tmp_path, change, message):
    with pytest.raises(CatalogError, match=message):
        _malformed(tmp_path, change)


@pytest.mark.parametrize(
    ("stated", "milli"),
    [
        (None, 1000),
        ("", 1000),
        (" 1 ", 1000),
        ("2", 2000),
        ("2.5", 2500),
        ("0.75", 750),
        ("0.001", 1),
        ("12.345", 12345),
        ("3.10", 3100),
    ],
)
def test_a_host_states_its_machines_scale_as_a_decimal_read_as_written(stated, milli):
    assert _minute_cost_scale_milli(stated) == milli


@pytest.mark.parametrize(
    "stated", ["0", "0.000", "-1", "1.2345", "1e3", "one", ".5", "1.", "1,5", "٢"]
)
def test_a_scale_that_is_not_a_positive_decimal_is_refused_by_name_at_startup(stated):
    with pytest.raises(SocietySettingRefused) as refused:
        _minute_cost_scale_milli(stated)
    assert refused.value.code == "minute_cost_scale_not_decimal"
    assert refused.value.variable == "EXULANICA_MINUTE_COST_SCALE"


def test_a_hosts_minute_budget_is_the_grounds_share_of_its_slowest_minute():
    # A tenth of 8 s is 800 ms, of a minute 6 s, in microseconds.
    assert DEFAULT_HOST.budget_us(100) == 800_000
    assert HostMinute(60_000).budget_us(100) == 6_000_000
