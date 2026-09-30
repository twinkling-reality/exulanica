"""How the people a comparison scores fared in an hour: half the need they were spared, half the
variety of what they did.

The third version of the score of the role "a person in your world",
``assets/catalogs/society/society-person-score.v3.json``, weighs two terms, each read from states
alone and anchored on the same seed, waiting scoring 0 and the routine 1, and nothing clipped:

- need relief, exactly the second version's (:func:`exulanica.world.society_score_v2.seed_score`):
  ``(U_wait - U_run) / (U_wait - U_routine)``, ``U`` the need above the routine's threshold summed
  over the group's person-minutes;
- variety: ``(V_run - V_wait) / (V_routine - V_wait)``, ``V`` the count of different activity kinds
  each of the group's people was seen doing, summed over them. A kind is the action a minute's state
  names while a person is doing something, one of the recorded routine's own activities, so a
  person's count is bounded by the kinds it offers; walking and waiting are never kinds.

The score is each term times its catalog weight, over a thousand. Both terms are the second
version's :class:`~exulanica.world.society_score_v2.RunTerms`: the urgency and the per-person
activity counts it already records, so a run's stored terms are its terms under either version and
nothing is read here that the second version does not read. What each model answered is the second
version's reliability, reported beside the score and never weighed. A seed on which the routine
spares the group less than the protocol's floor is excluded by the second version's name
(:data:`~exulanica.world.society_score_v2.BELOW_FLOOR`); one on which the routine's people did no
more kinds than waiting's is excluded as :data:`NO_VARIETY`, since the term has no scale there.

The import rules keep the model client, the asking path and the API out of this module's reach (the
"A person's score cannot read a model" contract in ``pyproject.toml``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from exulanica.world import society_score_v2
from exulanica.world.society_catalogs import RELIABILITY_PART
from exulanica.world.society_score import ScoreRefused
from exulanica.world.society_score_v2 import BELOW_FLOOR, RunTerms

__all__ = [
    "BELOW_FLOOR",
    "CATALOG_VERSION",
    "NO_VARIETY",
    "PRIMARY_TERMS",
    "PersonScore",
    "RunTerms",
    "SeedScore",
    "person_score",
    "seed_score",
    "variety",
]

#: The version of the ``society-person-score`` catalog this module computes.
CATALOG_VERSION: Final = 3
#: The weighed terms, each read from states: how much need the group was spared, and how many
#: different kinds of thing its people did.
NEED_RELIEF: Final = society_score_v2.PRIMARY_TERM
VARIETY: Final = "variety"
PRIMARY_TERMS: Final = (NEED_RELIEF, VARIETY)
#: Why a seed carries no score when the routine's people did no more kinds than waiting's.
NO_VARIETY: Final = "variety_not_spared"
#: The weights of a score's terms add up to one whole, in thousandths.
WHOLE_MILLI: Final = 1000


@dataclass(frozen=True, slots=True)
class PersonScore:
    """The third score as its catalog declares it: each weighed term's weight, in thousandths, and
    the second version's reliability classes and measures, which it reports unchanged."""

    weights: Mapping[str, int]
    reliability: society_score_v2.PersonScore

    def turn_class(self, disposition: str, reason: str) -> str:
        return self.reliability.turn_class(disposition, reason)


def person_score(entries: Mapping[str, Mapping[str, Any]]) -> PersonScore:
    """The score the catalog's entries declare, refused by name where it is not the one computed
    here: exactly :data:`PRIMARY_TERMS` weighed, each reading states, their weights adding up to
    :data:`WHOLE_MILLI`; the reliability classes and the reported measures the second version's
    reader accepts."""
    primary = {key: entry for key, entry in entries.items() if entry["part"] == "primary"}
    if sorted(primary) != sorted(PRIMARY_TERMS) or any(
        entry["reads"] != "states" for entry in primary.values()
    ):
        raise ScoreRefused("score_terms_not_computed", f"weighs {sorted(primary)}")
    weights = {key: int(entry["weight_milli"]) for key, entry in primary.items()}
    if sum(weights.values()) != WHOLE_MILLI:
        raise ScoreRefused("score_weights_not_whole", f"weights add up to {sum(weights.values())}")
    # The second version's reader holds the rest: one weighed need relief, the reliability classes
    # and the measures. It is shown the same entries with need relief as the one weighed term.
    rest = {
        key: entry
        for key, entry in entries.items()
        if key != VARIETY and (entry["part"] != "primary" or key == NEED_RELIEF)
    }
    parts = ("primary", RELIABILITY_PART, "held_out")
    if any(entry["part"] not in parts for entry in rest.values()):
        raise ScoreRefused("score_terms_not_computed", "a part this score does not read")
    return PersonScore(weights=weights, reliability=society_score_v2.person_score(rest))


def variety(run: RunTerms) -> int:
    """``V``: the different activity kinds each scored person was seen doing, summed over them."""
    return sum(count for _person, count in run.activities)


@dataclass(frozen=True, slots=True)
class SeedScore:
    """One run's score on one seed against that seed's two anchors, exact and unclipped, with each
    term apart."""

    excluded: str | None
    need_relief: Fraction | None
    variety: Fraction | None
    score: Fraction | None


def seed_score(
    run: RunTerms,
    *,
    waiting: RunTerms,
    routine: RunTerms,
    score: PersonScore,
    floor_per_person: int,
) -> SeedScore:
    """The run's score on its seed: each term times its weight, over a thousand.

    ``waiting`` and ``routine`` are the same seed's anchor runs over the same people and window.
    Need relief is the second version's, with its floor; a seed below it, or on which the routine's
    people did no more kinds than waiting's, is excluded by name and carries no score. No turn,
    reason, answer or answer time is read: only the three runs' urgency and activity counts.
    """
    need = society_score_v2.seed_score(
        run,
        waiting=waiting,
        routine=routine,
        score=score.reliability,
        floor_per_person=floor_per_person,
    )
    if need.excluded is not None or need.need_relief is None:
        return SeedScore(need.excluded, None, None, None)
    spread = variety(routine) - variety(waiting)
    if spread <= 0:
        return SeedScore(NO_VARIETY, None, None, None)
    kinds = Fraction(variety(run) - variety(waiting), spread)
    total = (
        need.need_relief * score.weights[NEED_RELIEF] + kinds * score.weights[VARIETY]
    ) / WHOLE_MILLI
    return SeedScore(None, need.need_relief, kinds, total)
