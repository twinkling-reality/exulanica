"""How the people a comparison scores fared in an hour, and, apart, what their model answered.

The second version of the score of the role "a person in your world",
``assets/catalogs/society/society-person-score.v2.json``, scores one thing: how the people fared.
Its one weighed term is need relief over the people a comparison scores (its group): ``U`` is the
need above the threshold summed over their person-minutes, read from every minute's state, and a
run's relief is ``(U_wait - U_run) / (U_wait - U_routine)`` on the same seed, waiting scoring 0 and
the routine 1 by construction and nothing clipped. The threshold is the recorded routine's own
(:func:`~exulanica.world.society_score.need_threshold`), read from the routine a run's input
records. A seed on which the routine spares the group less than the protocol's floor per person is
excluded by name (:data:`BELOW_FLOOR`).

What the model deciding for them answered is reliability, reported beside the score and never
weighed: each turn, a ``decision_applied`` event the engine appends when a minute consumes a
receipt, falls in exactly one class the catalog declares by the engine's disposition and, where a
class names one, the contract's reason code. Answered: the minute applied the model's choice.
Refused: the answer was not one of the offered actions. Not answered: no answer in time, a failed
call, no time or budget to ask. Not applied: an offered action the minute did not apply. The last
two are the turns left to the routine. Each is kept by reason and reported in two forms: a share
of the run's own turns, and a rate per choice point the routine had for the same people on the
same seed, a count the routine's own run records before any model run of that seed starts.

Nothing a model says reaches the score: :func:`seed_score` reads the urgency of three runs and
nothing else, and a timeout reaches it only through what the routine then did. Where everybody
outside the group follows their routine, as a judged comparison requires, the anchors ask nobody:
a model that answers no turn then scores exactly the routine's 1, its reliability saying so beside
it, and no model's answers move the rates' denominator. A model deciding for somebody outside the
group is asked in every arm, the anchors included, so in a development comparison that has one,
both move with its answers too. The import rules keep the model client, the asking path and the
API out of this module's reach (the "A person's score cannot read a model" contract in
``pyproject.toml``).

:mod:`exulanica.world.society_score` computes the first version and is left as the first judged
comparison registered it: that comparison's pre-registration binds its digest. This module reads
its threshold rule and its minute classes from there rather than restating either.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from exulanica.world.society_catalogs import RELIABILITY_PART
from exulanica.world.society_score import (
    APPLIED,
    BELOW_FLOOR,
    DECISION_EVENT,
    MINUTE_CLASSES,
    ScoreRefused,
    _minute_class,
    need_threshold,
)

__all__ = [
    "ANSWERED",
    "BELOW_FLOOR",
    "DISPOSITIONS",
    "LEFT_TO_ROUTINE",
    "PRIMARY_TERM",
    "REFUSED",
    "RELIABILITY_CLASSES",
    "STATE_MEASURES",
    "PersonScore",
    "Reliability",
    "RunTerms",
    "ScoreRefused",
    "SeedScore",
    "need_threshold",
    "person_score",
    "reliability",
    "run_terms",
    "seed_score",
    "state_measures",
]

#: The one weighed term, read from states alone.
PRIMARY_TERM: Final = "need_relief"
#: What each turn of the scored people was, by the catalog key each class is declared under:
#: answered, refused, and the two ways a turn is left to the routine.
ANSWERED: Final = "answered"
REFUSED: Final = "refused"
LEFT_TO_ROUTINE: Final = ("not_answered", "not_applied")
RELIABILITY_CLASSES: Final = (ANSWERED, REFUSED, *LEFT_TO_ROUTINE)
#: The measures read from states that carry no weight.
STATE_MEASURES: Final = (
    "activities_per_person",
    "minutes_by_activity",
    "waiting_share",
    "walking_share",
)
#: Every disposition the engine records for a consumed receipt: ``_DISPOSITIONS`` in
#: exulanica/world/society_model_decisions.py, which imports the model client and so is out of this
#: module's reach; tests/test_society_score_v2.py holds the two equal.
DISPOSITIONS: Final = ("applied", "rejected", "unavailable", "stale", "superseded")


@dataclass(frozen=True, slots=True)
class PersonScore:
    """The second score as its catalog declares it, in the form this module computes it."""

    #: The weighed term's weight, in thousandths.
    weight_milli: int
    #: Each reliability class: the dispositions it counts, and the reason codes it narrows them
    #: to, or none for any reason.
    classes: Mapping[str, tuple[frozenset[str], frozenset[str]]]

    def turn_class(self, disposition: str, reason: str) -> str:
        """The one class a turn falls in: a class naming this disposition and this reason, else
        the class naming the disposition for any reason; any other turn is refused by name."""
        narrowed = [
            key
            for key, (dispositions, reasons) in self.classes.items()
            if disposition in dispositions and reason in reasons
        ]
        broad = [
            key
            for key, (dispositions, reasons) in self.classes.items()
            if disposition in dispositions and not reasons
        ]
        found = narrowed or broad
        if len(found) != 1:
            raise ScoreRefused(
                "turn_not_classified", f"{disposition!r} for {reason!r} falls in {found}"
            )
        return found[0]


def person_score(entries: Mapping[str, Mapping[str, Any]]) -> PersonScore:
    """The score the catalog's entries declare, refused by name where it is not the one computed
    here: need relief alone weighed and read from states, exactly :data:`RELIABILITY_CLASSES`
    reported from events with every disposition the engine records in one class for any reason
    and the answered class counting ``applied`` alone, and :data:`STATE_MEASURES` reported."""
    primary = {key: entry for key, entry in entries.items() if entry["part"] == "primary"}
    if sorted(primary) != [PRIMARY_TERM] or primary[PRIMARY_TERM]["reads"] != "states":
        raise ScoreRefused("score_terms_not_computed", f"weighs {sorted(primary)}")
    declared = {key: entry for key, entry in entries.items() if entry["part"] == RELIABILITY_PART}
    if sorted(declared) != sorted(RELIABILITY_CLASSES):
        raise ScoreRefused("reliability_not_computed", f"reports {sorted(declared)}")
    classes = {
        key: (
            frozenset(str(value) for value in entry["dispositions"]),
            frozenset(str(value) for value in entry["reasons"]),
        )
        for key, entry in declared.items()
    }
    if classes[ANSWERED] != (frozenset({APPLIED}), frozenset()):
        raise ScoreRefused("reliability_not_computed", "answered counts the applied turns alone")
    for disposition in DISPOSITIONS:
        broad = [
            key for key, (held, reasons) in classes.items() if disposition in held and not reasons
        ]
        if len(broad) != 1:
            raise ScoreRefused(
                "disposition_counted_twice", f"{disposition} for any reason is in {broad}"
            )
    for key, (held, _reasons) in classes.items():
        if not held <= set(DISPOSITIONS):
            raise ScoreRefused("disposition_not_recorded", f"{key} counts {sorted(held)}")
    measured = sorted(
        key
        for key, entry in entries.items()
        if entry["part"] == "held_out" and entry["reads"] == "states"
    )
    if measured != sorted(STATE_MEASURES):
        raise ScoreRefused("score_measures_not_computed", f"reports {measured} from states")
    return PersonScore(weight_milli=int(primary[PRIMARY_TERM]["weight_milli"]), classes=classes)


@dataclass(frozen=True, slots=True)
class RunTerms:
    """One run's exact terms over the people it scores, integers only."""

    ticks: int
    threshold: int
    #: The people scored: the comparison's group.
    people: tuple[str, ...]
    #: Need above the threshold, summed over the scored people's person-minutes.
    urgency: int
    #: The scored people's person-minutes at the routine's choice point, as the run's own loop
    #: found them: the routine anchor's is the denominator no model's answers can move.
    choice_points: int
    #: Every turn: a receipt a minute consumed for one of the scored people.
    turns: int
    #: The turns in each reliability class.
    classes: tuple[tuple[str, int], ...]
    #: For each class a turn can be left to the routine by, how many turns each reason left.
    reasons: tuple[tuple[str, tuple[tuple[str, int], ...]], ...]
    #: The person-minutes by what they were: walking, doing something, waiting.
    person_minutes: tuple[tuple[str, int], ...]
    #: The person-minutes spent doing something, by the activity the person was doing.
    minutes_by_activity: tuple[tuple[str, int], ...]
    #: For each person, how many different activities they were seen doing.
    activities: tuple[tuple[str, int], ...]
    #: Everybody else in the run, and the need above the threshold they carried: reported, since a
    #: group's choices can take a place another person wanted.
    others: tuple[str, ...]
    others_urgency: int

    def document(self) -> dict[str, Any]:
        """The terms as an outcome stores them: integers and sorted pairs, nothing derived."""
        return {
            "ticks": self.ticks,
            "threshold": self.threshold,
            "people": list(self.people),
            "urgency": self.urgency,
            "choice_points": self.choice_points,
            "turns": self.turns,
            "classes": dict(self.classes),
            "reasons": {key: dict(counts) for key, counts in self.reasons},
            "person_minutes": dict(self.person_minutes),
            "minutes_by_activity": dict(self.minutes_by_activity),
            "activities": dict(self.activities),
            "others": list(self.others),
            "others_urgency": self.others_urgency,
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> RunTerms:
        return cls(
            ticks=int(document["ticks"]),
            threshold=int(document["threshold"]),
            people=tuple(document["people"]),
            urgency=int(document["urgency"]),
            choice_points=int(document["choice_points"]),
            turns=int(document["turns"]),
            classes=tuple(sorted(document["classes"].items())),
            reasons=tuple(
                sorted(
                    (key, tuple(sorted(counts.items())))
                    for key, counts in document["reasons"].items()
                )
            ),
            person_minutes=tuple(sorted(document["person_minutes"].items())),
            minutes_by_activity=tuple(sorted(document["minutes_by_activity"].items())),
            activities=tuple(sorted(document["activities"].items())),
            others=tuple(document["others"]),
            others_urgency=int(document["others_urgency"]),
        )


def _event_parts(event: Any) -> tuple[str, str, Mapping[str, Any]]:
    """An event's kind, subject and document, from a ``SocietyEvent`` or its stored form."""
    if isinstance(event, Mapping):
        return str(event["event_kind"]), str(event["subject_id"]), event["document"]
    return str(event.kind), str(event.subject_id), event.document


def run_terms(
    states: Sequence[Mapping[str, Any]],
    events: Iterable[Any],
    *,
    people: Iterable[str],
    threshold: int,
    choice_points: int,
    score: PersonScore,
) -> RunTerms:
    """The exact terms of one run over ``people``: ``states`` are its minutes after genesis, in
    order, ``events`` every event its minutes produced, and ``choice_points`` the scored people's
    person-minutes at the routine's choice point as the run's loop found them.

    Only a state's ``need_milli``, path and action, and a ``decision_applied`` event's subject,
    disposition and reason are read. Every person scored is in every minute, or the run is refused.
    """
    members = tuple(sorted(people))
    if not members:
        raise ScoreRefused("no_people", "a score is over at least one person")
    if not states:
        raise ScoreRefused("no_minutes", "a run with no minutes has nothing to score")
    if choice_points < 0:
        raise ScoreRefused("choice_points_negative", "a run counts its choice points from zero")
    ticks = [state["tick"] for state in states]
    if ticks != list(range(ticks[0], ticks[0] + len(ticks))):
        raise ScoreRefused("minutes_out_of_order", "a run's minutes are consecutive")
    held = frozenset(members)
    everybody = sorted({person["id"] for person in states[0]["inhabitants"]})
    others = tuple(subject for subject in everybody if subject not in held)
    urgency = others_urgency = 0
    minutes: Counter[str] = Counter()
    doing: Counter[str] = Counter()
    seen: dict[str, set[str]] = {subject: set() for subject in members}
    for state in states:
        found = {person["id"]: person for person in state["inhabitants"]}
        if not held <= set(found):
            raise ScoreRefused("person_not_in_minute", "every person scored is in each minute")
        for subject, person in found.items():
            above = max(0, int(person["need_milli"]) - threshold)
            if subject not in held:
                others_urgency += above
                continue
            urgency += above
            kind = _minute_class(person)
            minutes[kind] += 1
            if kind == "doing":
                activity = str(person["action"]["kind"])
                doing[activity] += 1
                seen[subject].add(activity)
    turns = 0
    classes: Counter[str] = Counter()
    reasons: dict[str, Counter[str]] = {key: Counter() for key in RELIABILITY_CLASSES}
    for event in events:
        kind, subject, document = _event_parts(event)
        if kind != DECISION_EVENT or subject not in held:
            continue
        turns += 1
        reason = str(document["reason"])
        found_class = score.turn_class(str(document["disposition"]), reason)
        classes[found_class] += 1
        if found_class != ANSWERED:
            reasons[found_class][reason] += 1
    return RunTerms(
        ticks=len(states),
        threshold=threshold,
        people=members,
        urgency=urgency,
        choice_points=choice_points,
        turns=turns,
        classes=tuple(sorted({key: classes[key] for key in RELIABILITY_CLASSES}.items())),
        reasons=tuple(
            sorted(
                (key, tuple(sorted(counts.items())))
                for key, counts in reasons.items()
                if key != ANSWERED
            )
        ),
        person_minutes=tuple(sorted({key: minutes[key] for key in MINUTE_CLASSES}.items())),
        minutes_by_activity=tuple(sorted(doing.items())),
        activities=tuple(sorted((subject, len(kinds)) for subject, kinds in seen.items())),
        others=others,
        others_urgency=others_urgency,
    )


def _share(part: int, whole: int) -> Fraction:
    return Fraction(part, whole) if whole else Fraction(0)


def state_measures(run: RunTerms) -> dict[str, Any]:
    """The run's reported measures from states, exact: they need no anchor and carry no weight."""
    minutes = dict(run.person_minutes)
    total = sum(minutes.values())
    return {
        "activities_per_person": Fraction(
            sum(count for _, count in run.activities), len(run.people)
        ),
        "minutes_by_activity": {
            activity: _share(count, total) for activity, count in run.minutes_by_activity
        },
        "waiting_share": _share(minutes["waiting"], total),
        "walking_share": _share(minutes["walking"], total),
    }


@dataclass(frozen=True, slots=True)
class SeedScore:
    """One run's score on one seed against that seed's two anchors, exact and unclipped."""

    excluded: str | None
    need_relief: Fraction | None
    score: Fraction | None


def seed_score(
    run: RunTerms,
    *,
    waiting: RunTerms,
    routine: RunTerms,
    score: PersonScore,
    floor_per_person: int,
) -> SeedScore:
    """The run's score on its seed: need relief times its weight, and nothing else.

    ``waiting`` and ``routine`` are the same seed's anchor runs over the same people and window.
    Below the floor, per scored person, the seed is excluded by name and carries no score. No
    turn, reason, answer or answer time is read: only the three runs' urgency.
    """
    for anchor in (waiting, routine):
        if (anchor.people, anchor.ticks, anchor.threshold) != (
            run.people,
            run.ticks,
            run.threshold,
        ):
            raise ScoreRefused("anchor_mismatch", "anchors run the same people, window, threshold")
    spared = waiting.urgency - routine.urgency
    if spared < floor_per_person * len(run.people) or spared <= 0:
        return SeedScore(BELOW_FLOOR, None, None)
    relief = Fraction(waiting.urgency - run.urgency, spared)
    return SeedScore(None, relief, relief * score.weight_milli / 1000)


@dataclass(frozen=True, slots=True)
class Reliability:
    """What one run's model answered, apart from its score: counts, shares of its own turns, and
    rates per choice point the routine had for the same people on the same seed."""

    turns: int
    counts: Mapping[str, int]
    #: Answered, refused and left to the routine, each over the run's own turns.
    shares: Mapping[str, Fraction] | None
    #: The same three per choice point of the routine's run, or None where no routine run of the
    #: seed recorded its choice points.
    per_routine_choice: Mapping[str, Fraction] | None
    routine_choice_points: int | None


def _three(counts: Mapping[str, int]) -> dict[str, int]:
    return {
        ANSWERED: counts[ANSWERED],
        REFUSED: counts[REFUSED],
        "left_to_routine": sum(counts[key] for key in LEFT_TO_ROUTINE),
    }


def reliability(run: RunTerms, *, routine: RunTerms | None) -> Reliability:
    """``run``'s reliability, with the rates' denominator taken from ``routine``, the same seed's
    routine run over the same people: its choice points, which no model's answers can move."""
    counts = dict(run.classes)
    three = _three(counts)
    points = None if routine is None else routine.choice_points
    if routine is not None and (routine.people, routine.ticks) != (run.people, run.ticks):
        raise ScoreRefused("anchor_mismatch", "the routine run scores the same people and window")
    return Reliability(
        turns=run.turns,
        counts=counts,
        shares=None if run.turns == 0 else {key: _share(n, run.turns) for key, n in three.items()},
        per_routine_choice=None
        if not points
        else {key: Fraction(n, points) for key, n in three.items()},
        routine_choice_points=points,
    )
