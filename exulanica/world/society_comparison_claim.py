"""Whether two models' people fared differently, judged by the protocol a comparison registered.

A comparison runs the same seeds with each arm. For two arms the paired difference on a seed is
the second arm's score minus the first's, and a claim is made from those differences alone:

*   **Interval.** A percentile bootstrap over seeds: ``bootstrap_resamples`` resamples of the
    seeds with replacement, each position drawn from ``sha256(key:resample:position)`` as every
    other draw the society makes is, so the same scores give the same interval on any machine. The
    interval holds the middle ``interval_per_mille`` of the resampled means. Every hypothesis of
    one comparison is read from the same resamples.
*   **Test.** Each registered hypothesis is two-sided: its p-value is twice the smaller share of
    resampled means on either side of zero, a mean of exactly zero counting on both. Holm's
    step-down procedure holds the family's error at ``family_alpha_per_mille``.
*   **Run-to-run variation.** A control pair, one model run twice on the same seeds, bounds what
    variation alone produces: the larger end, in size, of its interval.

The verdict is the server's, and the only source of the words "different" and "no measured
difference": a difference is ``different`` only when Holm rejects its hypothesis and its mean
exceeds the control bound; otherwise it is ``no_measured_difference``, stated with its interval.
A comparison run on development seeds, or read under scoring code other than the code it
registered, is ``not_judged`` whatever its numbers, and one with a run still missing or failed is
``incomplete``; the reader of a comparison decides those, by the names in
:data:`NOT_JUDGED_REASONS`.

Nothing here reads a world, a model or a database: scores in, a verdict out. Scores are exact
fractions and stay exact through every mean; only a reader rounds them for display.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Final

__all__ = [
    "NOT_JUDGED_REASONS",
    "VERDICTS",
    "Difference",
    "Protocol",
    "Resamples",
    "Verdict",
    "difference",
    "family_differences",
    "holm",
    "judge",
]

#: Every verdict a comparison can carry. The page has words for exactly these (``VERDICT_WORDS``
#: in web/packages/app/src/ui/society-comparison.ts, held to this tuple by a parity test).
VERDICTS: Final = (
    "different",
    "no_measured_difference",
    "not_judged",
    "incomplete",
)
#: Why a comparison is not judged: its seeds are development seeds, which are looked at freely;
#: the code that scores it now is not the code it registered; or fewer than two of its seeds
#: carry a score for every arm the claim reads, too few for an interval. The page has words for
#: each.
NOT_JUDGED_REASONS: Final = (
    "development_seeds",
    "scored_under_other_code",
    "too_few_seeds_scored",
)


@dataclass(frozen=True, slots=True)
class Protocol:
    """The protocol a claim is made under, as the comparison protocol catalog states it."""

    resamples: int
    interval_per_mille: int
    family_alpha_per_mille: int

    def __post_init__(self) -> None:
        if self.resamples < 1:
            raise ValueError("a protocol resamples at least once")
        if not 0 < self.interval_per_mille < 1000 or not 0 < self.family_alpha_per_mille < 1000:
            raise ValueError("a protocol states an interval level and a family error rate")


class Resamples:
    """The seeds each resample draws, by position, shared by every hypothesis of one comparison."""

    def __init__(self, key: str, count: int, protocol: Protocol) -> None:
        if count < 2:
            raise ValueError("an interval needs at least two seeds")
        self.count = count
        self.protocol = protocol
        self.draws = tuple(
            tuple(
                int.from_bytes(
                    hashlib.sha256(f"{key}:{resample}:{position}".encode()).digest()[:8], "big"
                )
                % count
                for position in range(count)
            )
            for resample in range(protocol.resamples)
        )

    def summarise(
        self, values: Sequence[Fraction]
    ) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        """Mean, interval ends and two-sided p-value of ``values``, one per seed, exactly."""
        if len(values) != self.count:
            raise ValueError("one value per seed the resamples were drawn over")
        # A common denominator keeps every resampled sum an integer; the order and the sign of a
        # sum are those of its mean, so nothing below needs a fraction until the ends are read.
        scale = math.lcm(*(value.denominator for value in values))
        scaled = [value.numerator * (scale // value.denominator) for value in values]
        sums = sorted(sum(scaled[index] for index in draw) for draw in self.draws)
        resamples = self.protocol.resamples
        outside = resamples * (1000 - self.protocol.interval_per_mille) // 2000
        at_or_below = sum(1 for total in sums if total <= 0)
        at_or_above = sum(1 for total in sums if total >= 0)
        p_value = min(Fraction(1), Fraction(2 * min(at_or_below, at_or_above), resamples))
        divisor = scale * self.count
        return (
            Fraction(sum(scaled), divisor),
            Fraction(sums[outside], divisor),
            Fraction(sums[resamples - 1 - outside], divisor),
            p_value,
        )


@dataclass(frozen=True, slots=True)
class Difference:
    """One registered comparison of two arms: ``second`` minus ``first`` over shared seeds."""

    first: str
    second: str
    seeds: tuple[str, ...]
    mean: Fraction
    low: Fraction
    high: Fraction
    p_value: Fraction


@dataclass(frozen=True, slots=True)
class Verdict:
    """The server's verdict on a judged comparison's primary difference."""

    code: str
    #: The arm whose people fared better, set only when the code is ``different``.
    higher: str | None
    primary: Difference
    control: Difference
    control_bound: Fraction
    #: The registered hypotheses Holm rejects, as (first, second) pairs.
    rejected: tuple[tuple[str, str], ...]
    differences: tuple[Difference, ...]


def _shared_seeds(scores: Mapping[str, Mapping[str, Fraction | None]], *arms: str) -> list[str]:
    return sorted(
        seed for seed in scores[arms[0]] if all(scores[arm].get(seed) is not None for arm in arms)
    )


def difference(
    scores: Mapping[str, Mapping[str, Fraction | None]],
    first: str,
    second: str,
    resamples: Resamples,
    seeds: Sequence[str],
) -> Difference:
    """``second`` minus ``first`` on ``seeds``, the seeds ``resamples`` was drawn over."""
    values = [scores[second][seed] - scores[first][seed] for seed in seeds]  # type: ignore[operator]
    mean, low, high, p_value = resamples.summarise(values)
    return Difference(first, second, tuple(seeds), mean, low, high, p_value)


def holm(p_values: Mapping[tuple[str, str], Fraction], alpha: Fraction) -> set[tuple[str, str]]:
    """The hypotheses Holm's step-down procedure rejects at family error ``alpha``."""
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    rejected: set[tuple[str, str]] = set()
    for rank, (name, p_value) in enumerate(ordered):
        if p_value > alpha / (len(ordered) - rank):
            break
        rejected.add(name)
    return rejected


def family_differences(
    scores: Mapping[str, Mapping[str, Fraction | None]],
    *,
    family: Sequence[tuple[str, str]],
    key: str,
    protocol: Protocol,
) -> tuple[dict[tuple[str, str], Difference], set[tuple[str, str]]]:
    """Every registered difference over the seeds each arm of the family scored, from one set of
    resamples, and the hypotheses Holm rejects among them."""
    arms = sorted({arm for pair in family for arm in pair})
    seeds = _shared_seeds(scores, *arms)
    tested = Resamples(f"{key}:family", len(seeds), protocol)
    found = {pair: difference(scores, *pair, tested, seeds) for pair in family}
    rejected = holm(
        {pair: result.p_value for pair, result in found.items()},
        Fraction(protocol.family_alpha_per_mille, 1000),
    )
    return found, rejected


def judge(
    scores: Mapping[str, Mapping[str, Fraction | None]],
    *,
    primary: tuple[str, str],
    family: Sequence[tuple[str, str]],
    control: tuple[str, str],
    key: str,
    protocol: Protocol,
) -> Verdict:
    """The verdict on ``primary`` under Holm over ``family`` and the ``control`` bound.

    ``scores`` maps each arm to its exact score on each seed, ``None`` where the seed is excluded.
    The family is read over the seeds every arm it names scored, the control over the seeds both
    of its arms scored; ``key`` is the comparison's definition digest, so its draws are its own.
    """
    if primary not in family:
        raise ValueError("the primary comparison is one of the registered family")
    found, rejected = family_differences(scores, family=family, key=key, protocol=protocol)
    control_seeds = _shared_seeds(scores, *control)
    variation = difference(
        scores, *control, Resamples(f"{key}:control", len(control_seeds), protocol), control_seeds
    )
    bound = max(abs(variation.low), abs(variation.high))
    main = found[primary]
    code, higher = "no_measured_difference", None
    if primary in rejected and abs(main.mean) > bound:
        code, higher = "different", (main.second if main.mean > 0 else main.first)
    return Verdict(
        code=code,
        higher=higher,
        primary=main,
        control=variation,
        control_bound=bound,
        rejected=tuple(sorted(rejected)),
        differences=tuple(found[pair] for pair in family),
    )
