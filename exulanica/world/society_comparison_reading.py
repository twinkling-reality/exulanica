"""What reading one run of a comparison may cost, and the people that allows.

The run route replays a completed run from what it stored whenever it is read
(``GET .../comparisons/{comparison_id}/runs/{run_id}``), and the page reads a seed's two runs at
once, which one process replays one after the other. From its third version the comparison
protocol states the most such a pair may take to read, ``pair_replay_budget_ms``, a declared
figure, and the line a run's read is estimated by, measured with
``scripts/measure_comparison_replay.py``: ``replay_fixed_ms``, what any run's read costs,
``replay_per_person_us``, what each of the society's people adds to it for the hour,
``replay_per_decided_person_us``, what each person a model decides for adds beside that, since the
replay rebuilds every turn a model was asked and holds it to what the run stored, and
``replay_per_decided_pair_us``, what each decided person adds for each person of the society, since
building a decided person's options reads everybody else. A run's read is estimated as ``fixed +
per_person x population + per_decided x decided + per_pair x population x decided``, and every run
of a comparison is held to the pair's budget over :data:`PAIR_RUNS`.

**A line per engine.** The protocol's line was measured on the purposeful engine, whose people
build their options every minute. A living town's people are asked only at the engine's own
choice points, and its replay costs several times less for the same people, so a line measured on
that engine reads its runs. The catalog :data:`READING_CATALOG` states the line of each state
family measured apart from the protocol's, bound to the measurement record it was read from by
path and digest; a family it does not name reads the protocol's own line. Which family a
comparison's runs are is the family whose score its catalogs hold
(:data:`~exulanica.world.society_catalogs.COMPARISON_SCORE_BY_FAMILY`, and for a day
:data:`~exulanica.world.society_catalogs.DAY_SCORE_BY_FAMILY`), the tables a definition is held
to when it is recorded, or the family its caller names. The pair's budget is the protocol's for
every family.

**A day, by the hour.** A comparison whose window is longer than an hour is read one hour at a
time, each hour replayed from the state its previous hour sealed, so a read of it is an hour's;
but a day's later hours are not its first, and the hour's line was measured on a run's first hour
alone. So a day is read by a line measured over every hour of a day, which the catalog states for
a family by the window it was measured over (``window_ticks``, an hour where an entry states
none). A day of a family the catalog states no such line for is refused by name
(``window_not_offered``), never read by an hour's line.

So the most people a comparison runs, and the most of them a model may decide for in any one of
its runs, are derived, never stated (:class:`ReadingBound`). A comparison whose dearest run would
read for longer is refused by name (:func:`reading_refusal`): ``population_over_comparison_bound``
when the society is too many for a run in which a model decides for even one of them,
``decided_over_comparison_bound`` when the people a model decides for are. The first two protocol
versions state ``population_maximum`` and bound nothing else.

Nothing here reads a world, a model or a database: a protocol, a family's measured line, a
population and a definition's body in, a bound or a refusal out.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Final

from exulanica.world.society_catalogs import (
    COMPARISON_SCORE_BY_FAMILY,
    DAY_SCORE_BY_FAMILY,
    ComparisonCatalogs,
)
from exulanica.world.society_comparison_verdict import (
    ComparisonRefused,
    protocol_values,
    score_version,
)

__all__ = [
    "LINE_KEYS",
    "PAIR_RUNS",
    "READING_CATALOG",
    "READING_REFUSALS",
    "WINDOW_NOT_OFFERED",
    "ReadingBound",
    "decided_maximum",
    "decided_people",
    "family_of",
    "measured_line",
    "population_maximum",
    "reading_bound",
    "reading_refusal",
]

#: The runs of one seed the page reads at once, one for each side. One process replays them one
#: after the other, so each run's read is held to this share of the pair's budget.
PAIR_RUNS: Final = 2
#: Microseconds in a millisecond: the protocol states the budget and the fixed cost in whole
#: milliseconds and what each person adds in whole microseconds.
_US_PER_MS: Final = 1000
#: Why a comparison's reading does not fit, by the code it is refused with.
READING_REFUSALS: Final = ("population_over_comparison_bound", "decided_over_comparison_bound")
#: Why a comparison over a window is not offered: no line read over that window was measured.
WINDOW_NOT_OFFERED: Final = "window_not_offered"
#: The window an entry of the reading catalog was measured over where it states none: an hour.
_HOUR_TICKS: Final = 60
#: The four figures a reading line states, by the names the protocol states its own under.
LINE_KEYS: Final = (
    "replay_fixed_ms",
    "replay_per_person_us",
    "replay_per_decided_person_us",
    "replay_per_decided_pair_us",
)
#: The lines measured apart from the protocol's, by state family and window: a derived catalog,
#: each entry naming the measurement record it was read from, its digest and how it was read.
READING_CATALOG: Final = (
    Path(__file__).resolve().parents[2]
    / "assets"
    / "catalogs"
    / "society-comparison-cost"
    / "society-comparison-reading.v3.json"
)
_CATALOG_ID: Final = "society-comparison-reading"
_CATALOG_VERSION: Final = 3
#: How an entry's line is read from its record: the record's fitted ``line``.
_EXTRACTION: Final = "replay_line"


@dataclass(frozen=True, slots=True)
class ReadingBound:
    """The most one run's read may take, and the measured line a read is estimated by, in
    microseconds."""

    run_us: int
    fixed_us: int
    per_person_us: int
    per_decided_us: int
    per_pair_us: int

    def estimate_us(self, population: int, decided: int) -> int:
        """What reading one run of ``population`` people, ``decided`` of them decided by a model,
        is estimated to take."""
        return (
            self.fixed_us
            + self.per_person_us * population
            + (self.per_decided_us + self.per_pair_us * population) * decided
        )

    def population_most(self) -> int:
        """The most people a comparison's run may hold: a run in which a model decides for one of
        them still fits, since every comparison has a model arm deciding for at least one person.
        It is the largest population whose :meth:`decided_most` is at least one, solved from the
        line: ``fixed + per_person x p + per_decided + per_pair x p`` within the run's share."""
        room = self.run_us - self.fixed_us - self.per_decided_us
        return max(0, room // (self.per_person_us + self.per_pair_us))

    def decided_most(self, population: int) -> int:
        """The most of ``population`` people a model may decide for in one run."""
        room = self.run_us - self.estimate_us(population, 0)
        return max(
            0, min(population, room // (self.per_decided_us + self.per_pair_us * population))
        )


def family_of(catalogs: ComparisonCatalogs) -> str | None:
    """The state family whose score ``catalogs`` hold, as the definition tables state each
    family's score over an hour and over a day, or None for a score no family is defined under now
    (an earlier comparison's)."""
    held = score_version(catalogs)
    return next(
        (
            family
            for table in (COMPARISON_SCORE_BY_FAMILY, DAY_SCORE_BY_FAMILY)
            for family, score in table.items()
            if score == held
        ),
        None,
    )


@cache
def _catalog_lines(path: Path) -> dict[tuple[str, int], dict[str, Any]]:
    """Each family's measured line the catalog at ``path`` states, by family and the window it was
    measured over, with where it was read from; refused by name where the catalog is not one this
    code reads."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("catalog_id") != _CATALOG_ID or document.get("catalog_version") != (
        _CATALOG_VERSION
    ):
        raise ComparisonRefused("reading_catalog", "not a comparison reading catalog this reads")
    lines: dict[tuple[str, int], dict[str, Any]] = {}
    for entry in document["entries"]:
        family = entry.get("state_family")
        window = entry.get("window_ticks", _HOUR_TICKS)
        values = {key: entry.get(key) for key in LINE_KEYS}
        if (
            entry.get("key") != (family if window == _HOUR_TICKS else f"{family}-{window}")
            or family not in COMPARISON_SCORE_BY_FAMILY
            or type(window) is not int
            or window < _HOUR_TICKS
            or window % _HOUR_TICKS
            or (family, window) in lines
            or entry.get("extraction") != _EXTRACTION
            or not isinstance(entry.get("source"), str)
            or not isinstance(entry.get("source_sha256"), str)
            or any(type(value) is not int or value < 0 for value in values.values())
            or values["replay_per_person_us"] < 1
            or values["replay_per_decided_person_us"] < 1
        ):
            raise ComparisonRefused("reading_catalog", f"entry {entry.get('key')!r} is malformed")
        lines[(family, window)] = {
            **values,
            "source": entry["source"],
            "source_sha256": entry["source_sha256"],
            "window_ticks": window,
        }
    return lines


def measured_line(family: str | None, window: int = _HOUR_TICKS) -> dict[str, Any] | None:
    """The line measured for ``family`` over ``window`` apart from the protocol's, with the record
    it was read from, or None where the reading catalog names none for it (an hour's comparison
    then reads the protocol's own). The catalog ships with the code: one that is missing is an
    error, never a quiet fallback."""
    if family is None:
        return None
    return _catalog_lines(READING_CATALOG).get((family, window))


def reading_bound(catalogs: ComparisonCatalogs, family: str | None = None) -> ReadingBound | None:
    """The protocol's bound on reading one run of a comparison of ``family`` (left out, the family
    whose score ``catalogs`` hold), or None for a protocol that states no replay line, an earlier
    one stating its population maximum instead. The pair's budget is always the protocol's; the
    line is the family's measured one where the reading catalog states it, else the protocol's.
    A window longer than an hour is read by its family's line over that window alone, and one the
    catalog states none for is refused by name (``window_not_offered``)."""
    values = protocol_values(catalogs)
    if "pair_replay_budget_ms" not in values:
        return None
    window = values["window_ticks"]
    named = family_of(catalogs) if family is None else family
    measured = measured_line(named, window)
    if window > _HOUR_TICKS and measured is None:
        raise ComparisonRefused(
            WINDOW_NOT_OFFERED,
            f"no line has been measured for reading a {named or 'society'}'s runs over "
            f"{window} minutes",
        )
    line = values if measured is None else measured
    if line["replay_per_person_us"] < 1 or line["replay_per_decided_person_us"] < 1:
        raise ComparisonRefused(
            "protocol_keys", "the protocol's replay line states no cost for a person"
        )
    return ReadingBound(
        run_us=values["pair_replay_budget_ms"] * _US_PER_MS // PAIR_RUNS,
        fixed_us=line["replay_fixed_ms"] * _US_PER_MS,
        per_person_us=line["replay_per_person_us"],
        per_decided_us=line["replay_per_decided_person_us"],
        per_pair_us=line["replay_per_decided_pair_us"],
    )


def population_maximum(catalogs: ComparisonCatalogs, family: str | None = None) -> int:
    """The most people a comparison of ``family`` under ``catalogs`` runs: derived from its read
    line (:meth:`ReadingBound.population_most`), or the figure an earlier protocol states."""
    bound = reading_bound(catalogs, family)
    if bound is None:
        return protocol_values(catalogs)["population_maximum"]
    return bound.population_most()


def decided_maximum(
    catalogs: ComparisonCatalogs, population: int, family: str | None = None
) -> int:
    """The most of a society of ``population`` people a model may decide for in one run of a
    comparison of ``family`` under ``catalogs``; an earlier protocol bounds only the population."""
    bound = reading_bound(catalogs, family)
    return population if bound is None else bound.decided_most(population)


def decided_people(body: Mapping[str, Any], population: int) -> dict[str, int]:
    """For each arm of a definition's ``body``, how many people a model decides for in one of its
    runs: the group under a model arm (everybody where the group is everybody) and, in every arm,
    anybody outside it whose owner chose a model."""
    group = body["group"]["people"]
    others = sum(1 for other in body["others"] if other["provider_config"] is not None)
    size = population if group is None else len(group)
    return {
        key: (size if arm["provider_config"] is not None else 0) + others
        for key, arm in body["arms"].items()
    }


def reading_refusal(
    catalogs: ComparisonCatalogs,
    population: int,
    body: Mapping[str, Any] | None = None,
    family: str | None = None,
) -> tuple[str, str] | None:
    """Why a comparison of ``population`` people defined by ``body`` cannot be read within the
    protocol's bound, as a code of :data:`READING_REFUSALS` and a sentence, or None. Without a
    body, only the population is held. ``family`` is the state family of the society's engine;
    left out, the family whose score ``catalogs`` hold."""
    most = population_maximum(catalogs, family)
    if population > most:
        return (
            "population_over_comparison_bound",
            f"{population} people; a comparison runs at most {most}",
        )
    if body is None:
        return None
    decided = max(decided_people(body, population).values(), default=0)
    allowed = decided_maximum(catalogs, population, family)
    if decided > allowed:
        return (
            "decided_over_comparison_bound",
            f"a model decides for {decided} of {population} people in one run; a comparison of "
            f"{population} people lets a model decide for at most {allowed}",
        )
    return None
