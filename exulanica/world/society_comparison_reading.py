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

So the most people a comparison runs, and the most of them a model may decide for in any one of
its runs, are derived, never stated (:class:`ReadingBound`). A comparison whose dearest run would
read for longer is refused by name (:func:`reading_refusal`): ``population_over_comparison_bound``
when the society alone is too many for a run nobody is decided for,
``decided_over_comparison_bound`` when the people a model decides for are. The first two protocol
versions state ``population_maximum`` and bound nothing else.

Nothing here reads a world, a model or a database: a protocol, a population and a definition's
body in, a bound or a refusal out.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.world.society_catalogs import COMPARISON_PROTOCOL_CATALOG, ComparisonCatalogs
from exulanica.world.society_comparison_verdict import ComparisonRefused, protocol_values

__all__ = [
    "PAIR_RUNS",
    "READING_REFUSALS",
    "ReadingBound",
    "decided_maximum",
    "decided_people",
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
#: The first protocol version whose population bound is derived from a measured read.
_DERIVED_FROM: Final = 3
#: Why a comparison's reading does not fit, by the code it is refused with.
READING_REFUSALS: Final = ("population_over_comparison_bound", "decided_over_comparison_bound")


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
        """The most people a run nobody is decided for may hold."""
        return max(0, (self.run_us - self.fixed_us) // self.per_person_us)

    def decided_most(self, population: int) -> int:
        """The most of ``population`` people a model may decide for in one run."""
        room = self.run_us - self.estimate_us(population, 0)
        return max(
            0, min(population, room // (self.per_decided_us + self.per_pair_us * population))
        )


def reading_bound(catalogs: ComparisonCatalogs) -> ReadingBound | None:
    """The protocol's bound on reading one run, or None for a protocol that states its population
    maximum instead."""
    if int(catalogs.versions[COMPARISON_PROTOCOL_CATALOG]) < _DERIVED_FROM:
        return None
    values = protocol_values(catalogs)
    if values["replay_per_person_us"] < 1 or values["replay_per_decided_person_us"] < 1:
        raise ComparisonRefused(
            "protocol_keys", "the protocol's replay line states no cost for a person"
        )
    return ReadingBound(
        run_us=values["pair_replay_budget_ms"] * _US_PER_MS // PAIR_RUNS,
        fixed_us=values["replay_fixed_ms"] * _US_PER_MS,
        per_person_us=values["replay_per_person_us"],
        per_decided_us=values["replay_per_decided_person_us"],
        per_pair_us=values["replay_per_decided_pair_us"],
    )


def population_maximum(catalogs: ComparisonCatalogs) -> int:
    """The most people a comparison under ``catalogs`` runs: derived from the protocol's replay
    line, or the figure an earlier protocol states."""
    bound = reading_bound(catalogs)
    if bound is None:
        return protocol_values(catalogs)["population_maximum"]
    return bound.population_most()


def decided_maximum(catalogs: ComparisonCatalogs, population: int) -> int:
    """The most of a society of ``population`` people a model may decide for in one run of a
    comparison under ``catalogs``; an earlier protocol bounds only the population."""
    bound = reading_bound(catalogs)
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
    catalogs: ComparisonCatalogs, population: int, body: Mapping[str, Any] | None = None
) -> tuple[str, str] | None:
    """Why a comparison of ``population`` people defined by ``body`` cannot be read within the
    protocol's bound, as a code of :data:`READING_REFUSALS` and a sentence, or None. Without a
    body, only the population is held."""
    most = population_maximum(catalogs)
    if population > most:
        return (
            "population_over_comparison_bound",
            f"{population} people; a comparison runs at most {most}",
        )
    if body is None:
        return None
    decided = max(decided_people(body, population).values(), default=0)
    allowed = decided_maximum(catalogs, population)
    if decided > allowed:
        return (
            "decided_over_comparison_bound",
            f"a model decides for {decided} of {population} people in one run; a comparison of "
            f"{population} people lets a model decide for at most {allowed}",
        )
    return None
