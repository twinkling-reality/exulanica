"""A living town's fourth-score terms over a day, assembled exactly from its hours.

A day comparison runs each arm for a living town's whole day, its 1440 minutes, and the host plays
and seals each run hour by hour (:mod:`exulanica.world.society_comparison`), so no host holds a day
of states. The fifth version of the score, ``society-person-score.v5.json``, is the fourth's
(:mod:`exulanica.world.society_score_v4`) over that window: half need relief, half variety,
anchored on the same seed's waiting and routine days, nothing clipped, with what each model
answered reported apart. What is new is how a day's terms are computed, not what they are:

- **An hour's terms** (:func:`hour_terms`) are the fourth score's terms over that hour, with the
  activity kinds each scored person was seen doing in it, held to the hour's own count of them.
- **A day's terms** (:func:`day_terms`) are every count of its hours summed and each scored
  person's kinds united, so variety counts a kind once per person in the day, as the score counts
  it once in its window. They are the terms the fourth score computes over the whole day's states
  (``tests/test_society_score_v5.py``), in the fourth score's own form, so the fourth score's
  anchored math reads them.

Nothing here reads a model, a database or a clock, and the import rules keep the model client,
the asking path and the API out of its reach, as they keep them out of every score's.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final

from exulanica.world import society_score_v2, society_score_v3, society_score_v4
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_score import ScoreRefused, _minute_class

__all__ = [
    "CATALOG_VERSION",
    "KINDS",
    "day_terms",
    "hour_terms",
    "score",
    "validate_terms",
]

#: The version of the ``society-person-score`` catalog this module computes.
CATALOG_VERSION: Final = 5
#: The member of an hour's terms naming each scored person's activity kinds in that hour.
KINDS: Final = "activity_kinds"
#: The members of an hour's terms that are counts summed over a day, as the fourth score's terms
#: state them.
_SUMMED: Final = ("ticks", "urgency", "choice_points", "turns", "others_urgency")
#: The members every hour of a day states alike.
_SAME: Final = ("threshold", "people", "others", "need_thresholds", "need_unit")


def _kinds(
    states: Sequence[Mapping[str, Any]], people: Iterable[str], routine: RoutineModel
) -> dict[str, set[str]]:
    """Each scored person's performed activity kinds over ``states``, by the fourth score's
    projection of a minute and the score's own minute class: a minute counts a kind only when the
    person was doing a catalogued activity of the routine, active or completed, and not walking."""
    seen: dict[str, set[str]] = {subject: set() for subject in sorted(people)}
    for state in states:
        for person in state["inhabitants"]:
            held = seen.get(person["id"])
            if held is None:
                continue
            action = person["action"]
            performed = action["kind"] in routine.activities and action["status"] in (
                "active",
                "completed",
            )
            projected = {
                "motion_path_mm": person["motion_path_mm"],
                "action": {
                    "kind": action["kind"] if performed else "idle",
                    "status": action["status"] if performed else "active",
                },
            }
            if _minute_class(projected) == "doing":
                held.add(str(action["kind"]))
    return seen


def hour_terms(
    states: Sequence[Mapping[str, Any]],
    events: Iterable[Any],
    *,
    people: Iterable[str],
    choice_points: int,
    routine: RoutineModel,
    score: society_score_v2.PersonScore,
) -> dict[str, Any]:
    """One hour's terms: the fourth score's over ``states`` and ``events``, and each scored
    person's activity kinds in the hour, which must be exactly as many as the fourth score counted
    for them, or the hour is refused by name (``hour_kinds_not_counted``)."""
    members = sorted(people)
    terms = society_score_v4.run_terms(
        states,
        events,
        people=members,
        choice_points=choice_points,
        routine=routine,
        score=score,
    )
    kinds = _kinds(states, members, routine)
    if {subject: len(held) for subject, held in kinds.items()} != dict(terms["activities"]):
        raise ScoreRefused(
            "hour_kinds_not_counted", "an hour's kinds are not the ones its terms count"
        )
    return {**terms, KINDS: {subject: sorted(held) for subject, held in sorted(kinds.items())}}


def _summed(hours: Sequence[Mapping[str, Any]], key: str) -> dict[str, int]:
    total: Counter[str] = Counter()
    for hour in hours:
        total.update({name: int(value) for name, value in hour[key].items()})
    return dict(sorted(total.items()))


def day_terms(hours: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """A day's terms from its hours' (:func:`hour_terms`), in order: every count summed and each
    scored person's kinds united, in the fourth score's own form. Hours that score other people,
    name other needs or another threshold, or state no kinds, are refused by name
    (``day_hours_differ``)."""
    if not hours:
        raise ScoreRefused("no_minutes", "a day with no hours has nothing to score")
    first = hours[0]
    for hour in hours:
        if any(hour[key] != first[key] for key in _SAME) or KINDS not in hour:
            raise ScoreRefused("day_hours_differ", "a day's hours score one group, one way")
        if sorted(hour[KINDS]) != sorted(first["people"]):
            raise ScoreRefused("day_hours_differ", "an hour states kinds for other people")
    kinds: dict[str, set[str]] = {subject: set() for subject in first["people"]}
    for hour in hours:
        for subject, held in hour[KINDS].items():
            kinds[subject].update(held)
    reasons: dict[str, Counter[str]] = {}
    for hour in hours:
        for key, counts in hour["reasons"].items():
            reasons.setdefault(key, Counter()).update(
                {name: int(value) for name, value in counts.items()}
            )
    return {
        **{key: sum(int(hour[key]) for hour in hours) for key in _SUMMED},
        "threshold": first["threshold"],
        "people": list(first["people"]),
        "classes": _summed(hours, "classes"),
        "reasons": {key: dict(sorted(counts.items())) for key, counts in sorted(reasons.items())},
        "person_minutes": _summed(hours, "person_minutes"),
        "minutes_by_activity": _summed(hours, "minutes_by_activity"),
        "activities": {subject: len(held) for subject, held in sorted(kinds.items())},
        "others": list(first["others"]),
        "need_thresholds": dict(first["need_thresholds"]),
        "need_unit": first["need_unit"],
    }


def validate_terms(document: Mapping[str, Any]) -> society_score_v2.RunTerms:
    """A stored day's terms, in the fourth score's form with its need identity and units, or a
    refusal by the fourth score's name."""
    return society_score_v4.validate_terms(document)


def score(catalog: Mapping[str, Mapping[str, Any]]) -> society_score_v3.PersonScore:
    """The fifth catalog has the fourth's weights and reliability mapping exactly."""
    return society_score_v3.person_score(catalog)
