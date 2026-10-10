"""What one simulated minute of a society costs a host, read from measured points.

A ground whose people are the world's own states, in place of a head count, what a minute of a
society over it was measured to take (``minute_cost`` in the society ground catalog): for each
engine, on each walking graph a measurement ran over, the 95th percentile minute at several
populations, with what measured them, the record that holds the run where one was kept, and the
machine it ran on. This module reads those points and nothing else:

- :func:`estimated_minute`: the minute a society of some people over a walking graph of some
  nodes takes, read on the smallest measured graph at or above the town's nodes, between the
  nearest measured populations.
- :func:`people_within`: the most people whose minute fits a budget.

Every answer carries its **basis**. ``measured`` says it was read between measured points, or at
the first one for fewer people than any run held, which never understates. ``estimate`` says it
was read past the last measured point: more people than any run held, carried along the last
measured rise (in proportion to the people, where a graph was measured at one population only),
or a walking graph larger than any measured, carried in proportion to its nodes.
The basis is part of the value, so no caller can serve an estimate without its name.

A host states how its own machine compares with the measured ones as one figure
(:class:`HostMinute`, ``EXULANICA_MINUTE_COST_SCALE``): every reading is multiplied by it. How
much of a minute a society may take is the ground's stated share of the host's slowest minute,
a chosen budget, not a measurement.

Pure integer arithmetic over microseconds, rounded up, so two hosts with the same settings admit
the same towns. No connection, no store and no clock.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final, Literal

from exulanica.grammar.errors import CatalogError

__all__ = [
    "COST_SCALE_UNIT_MILLI",
    "ESTIMATE",
    "MEASURED",
    "EngineMinuteCost",
    "HostMinute",
    "MeasuredGraph",
    "MinuteEstimate",
    "PeopleCeiling",
    "estimated_minute",
    "minute_cost_field",
    "minute_costs",
    "people_within",
]

Basis = Literal["measured", "estimate"]
#: Read between measured points, or at the first for fewer people than any run held.
MEASURED: Final = "measured"
#: Read past the last measured point, by people or by walking nodes.
ESTIMATE: Final = "estimate"
#: A host whose machine is taken to be the measured one: a scale of one, in thousandths.
COST_SCALE_UNIT_MILLI: Final = 1000

_SHA256_LENGTH: Final = 64
_ENGINE_KEYS: Final = frozenset({"engine", "source", "record", "machine", "runtime", "graphs"})
_RECORD_KEYS: Final = frozenset({"profile", "sha256"})
_GRAPH_KEYS: Final = frozenset({"town", "walking_nodes", "points"})
_POINT_KEYS: Final = frozenset({"people", "minute_p95_us"})


@dataclass(frozen=True, slots=True)
class MeasuredGraph:
    """One walking graph a measurement ran over, and the minute it took at each population."""

    #: The town whose graph it is, in the measurement's own words.
    town: str
    walking_nodes: int
    #: ``(people, 95th percentile minute in microseconds)``, by people ascending.
    points: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class EngineMinuteCost:
    """What a minute of one engine was measured to take, and what measured it."""

    engine: str
    #: What measured the points, in words: the script or run that produced them.
    source: str
    #: The record that holds the run, by profile and digest; None where none was kept.
    record: Mapping[str, str] | None
    machine: str
    runtime: str
    #: By walking nodes ascending.
    graphs: tuple[MeasuredGraph, ...]


@dataclass(frozen=True, slots=True)
class HostMinute:
    """What one host gives a simulated minute.

    ``slowest_minute_ms`` is the longest wait the host leaves between two minutes of a society at
    play: its base interval at its slowest speed. ``cost_scale_milli`` is how its machine compares
    with the measured ones, in thousandths (2000 for a machine twice as slow), one deployment's own
    figure; a host that states none is read as the measured machine.
    """

    slowest_minute_ms: int
    cost_scale_milli: int = COST_SCALE_UNIT_MILLI

    def budget_us(self, share_milli: int) -> int:
        """The longest a minute may take here, in microseconds: ``share_milli`` thousandths of
        the slowest minute."""
        return self.slowest_minute_ms * share_milli


@dataclass(frozen=True, slots=True)
class MinuteEstimate:
    """A minute's cost and how it was read."""

    microseconds: int
    basis: Basis

    def document(self) -> dict[str, Any]:
        """As served: whole milliseconds, rounded up, with the basis beside the figure."""
        return {"minute_ms": _ceil_div(self.microseconds, 1000), "basis": self.basis}


@dataclass(frozen=True, slots=True)
class PeopleCeiling:
    """The most people whose minute fits a budget, and how that minute was read."""

    people: int
    basis: Basis

    def document(self) -> dict[str, Any]:
        return {"people": self.people, "basis": self.basis}


def _ceil_div(numerator: int, denominator: int) -> int:
    return -(-numerator // denominator)


def _graph(cost: EngineMinuteCost, walking_nodes: int) -> tuple[MeasuredGraph, bool]:
    """The measured graph a town of ``walking_nodes`` is read on, and whether the town's graph is
    larger than any measured: the smallest measured graph at or above the town's nodes, so a town
    is never read on a graph smaller than its own while a larger one was measured."""
    for graph in cost.graphs:
        if graph.walking_nodes >= walking_nodes:
            return graph, False
    return cost.graphs[-1], True


def _along(points: tuple[tuple[int, int], ...], people: int) -> tuple[int, bool]:
    """The minute at ``people`` along one graph's points, and whether it lies past the last."""
    first_people, first_us = points[0]
    if people <= first_people:
        return first_us, False
    for (low, low_us), (high, high_us) in pairwise(points):
        if people <= high:
            return low_us + _ceil_div((high_us - low_us) * (people - low), high - low), False
    if len(points) == 1:
        # One measured population states no rise: past it, a minute grows with its people.
        return _ceil_div(first_us * people, first_people), True
    (low, low_us), (high, high_us) = points[-2:]
    return high_us + _ceil_div((high_us - low_us) * (people - high), high - low), True


def estimated_minute(
    cost: EngineMinuteCost,
    people: int,
    walking_nodes: int,
    *,
    scale_milli: int = COST_SCALE_UNIT_MILLI,
) -> MinuteEstimate:
    """The 95th percentile minute of ``people`` over a graph of ``walking_nodes``, on a host whose
    machine is ``scale_milli`` thousandths of the measured one, with its basis."""
    if people < 1 or walking_nodes < 1 or scale_milli < 1:
        raise ValueError("a minute is read for people, walking nodes and a scale of at least one")
    graph, larger = _graph(cost, walking_nodes)
    microseconds, past = _along(graph.points, people)
    if larger:
        microseconds = _ceil_div(microseconds * walking_nodes, graph.walking_nodes)
    return MinuteEstimate(
        _ceil_div(microseconds * scale_milli, COST_SCALE_UNIT_MILLI),
        ESTIMATE if larger or past else MEASURED,
    )


def people_within(
    cost: EngineMinuteCost,
    walking_nodes: int,
    budget_us: int,
    *,
    scale_milli: int = COST_SCALE_UNIT_MILLI,
) -> PeopleCeiling:
    """The most people whose minute over a graph of ``walking_nodes`` takes at most ``budget_us``
    microseconds, with the basis of that minute; nobody where one person's does not fit.

    A minute never falls as people are added and rises past the last measured point (the catalog
    holds its points to that), so the search ends."""

    def read(people: int) -> MinuteEstimate:
        return estimated_minute(cost, people, walking_nodes, scale_milli=scale_milli)

    if read(1).microseconds > budget_us:
        return PeopleCeiling(0, read(1).basis)
    fits = 1
    while read(fits * 2).microseconds <= budget_us:
        fits *= 2
    over = fits * 2
    while over - fits > 1:
        middle = (fits + over) // 2
        if read(middle).microseconds <= budget_us:
            fits = middle
        else:
            over = middle
    return PeopleCeiling(fits, read(fits).basis)


def _positive(where: str, value: object) -> int:
    if type(value) is not int or value < 1:
        raise CatalogError(f"{where} is a positive integer, got {value!r}")
    return value


def _words(where: str, value: object) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise CatalogError(f"{where} is non-empty text with no surrounding space")
    return value


def _keys(where: str, value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise CatalogError(f"{where} states exactly {sorted(keys)}")
    return value


def _points(where: str, value: object) -> list[dict[str, int]]:
    if not isinstance(value, list) or not value:
        raise CatalogError(f"{where} states at least one measured point")
    points = [
        {
            name: _positive(f"{where}[{index}].{name}", _keys(where, raw, _POINT_KEYS)[name])
            for name in ("people", "minute_p95_us")
        }
        for index, raw in enumerate(value)
    ]
    for low, high in pairwise(points):
        if high["people"] <= low["people"]:
            raise CatalogError(f"{where} is in order of people, none twice")
        if high["minute_p95_us"] < low["minute_p95_us"]:
            raise CatalogError(f"{where}: a minute never falls as people are added")
    if len(points) > 1 and points[-1]["minute_p95_us"] <= points[-2]["minute_p95_us"]:
        raise CatalogError(f"{where}: the last measured point rises above the one before it")
    return points


def minute_cost_field(where: str, value: object) -> list[dict[str, Any]]:
    """A ground's ``minute_cost``, checked: no engine twice; each with what measured it, its
    record or none, its machine and its graphs by walking nodes ascending; each graph with its
    points by people ascending, whose minute never falls and rises at the end. An empty
    list states no measured cost: the ground states a head count instead."""
    if not isinstance(value, list):
        raise CatalogError(f"{where} is a list of engines with their measured points")
    engines: list[dict[str, Any]] = []
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        stated = _keys(at, raw, _ENGINE_KEYS)
        record = stated["record"]
        if record is not None:
            record = _keys(f"{at}.record", record, _RECORD_KEYS)
            digest = record["sha256"]
            if (
                type(digest) is not str
                or len(digest) != _SHA256_LENGTH
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise CatalogError(f"{at}.record.sha256 is a lowercase SHA-256 digest")
            record = {"profile": _words(f"{at}.record.profile", record["profile"]), **record}
        graphs = stated["graphs"]
        if not isinstance(graphs, list) or not graphs:
            raise CatalogError(f"{at}.graphs states at least one measured walking graph")
        read = [
            {
                "town": _words(f"{at}.graphs[{g}].town", graph["town"]),
                "walking_nodes": _positive(
                    f"{at}.graphs[{g}].walking_nodes", graph["walking_nodes"]
                ),
                "points": _points(f"{at}.graphs[{g}].points", graph["points"]),
            }
            for g, raw_graph in enumerate(graphs)
            for graph in (_keys(f"{at}.graphs[{g}]", raw_graph, _GRAPH_KEYS),)
        ]
        if any(high["walking_nodes"] <= low["walking_nodes"] for low, high in pairwise(read)):
            raise CatalogError(f"{at}.graphs is in order of walking nodes, none twice")
        engines.append(
            {
                "engine": _words(f"{at}.engine", stated["engine"]),
                "source": _words(f"{at}.source", stated["source"]),
                "record": record,
                "machine": _words(f"{at}.machine", stated["machine"]),
                "runtime": _words(f"{at}.runtime", stated["runtime"]),
                "graphs": read,
            }
        )
    named = [engine["engine"] for engine in engines]
    if len(set(named)) != len(named):
        raise CatalogError(f"{where} names an engine twice")
    return engines


def minute_costs(checked: object) -> tuple[EngineMinuteCost, ...]:
    """The engines' costs a checked ``minute_cost`` (:func:`minute_cost_field`) states."""
    engines = minute_cost_field("minute_cost", checked)
    return tuple(
        EngineMinuteCost(
            engine=engine["engine"],
            source=engine["source"],
            record=None if engine["record"] is None else dict(engine["record"]),
            machine=engine["machine"],
            runtime=engine["runtime"],
            graphs=tuple(
                MeasuredGraph(
                    town=graph["town"],
                    walking_nodes=graph["walking_nodes"],
                    points=tuple(
                        (point["people"], point["minute_p95_us"]) for point in graph["points"]
                    ),
                )
                for graph in engine["graphs"]
            ),
        )
        for engine in engines
    )
