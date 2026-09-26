"""What the people of a world were spared in an hour, read from what the engine recorded.

The score of the role "a person in your world" is declared as data, in
``assets/catalogs/society/society-person-score.v<N>.json``: each term, its weight, what it reads
and why. This module computes, exactly, the terms that read the world, from a run's states and
events as the engine produced them:

*   **Need above the threshold.** ``U`` is the need above the threshold summed over the people's
    person-minutes, from every minute's state. The threshold is the need at which the routine the
    run's input records prefers an activity to every other (:func:`need_threshold`), read from
    that routine and never stated here, so a routine with another threshold moves ``U``.
*   **Turns.** What each model decision did, from the ``decision_applied`` events the engine
    appends when a minute consumes a receipt: applied, or counted by the term whose catalog entry
    names its disposition. A disposition no term names is refused by name, never guessed.

A run's ``need_relief`` is ``(U_wait - U_run) / (U_wait - U_routine)`` on the same seed, the
waiting anchor scoring 0 and the routine 1 by construction. A run can score below 0, worse than
waiting, or above 1, better than the routine; nothing here clips it, and a reader shows it as it
is. A seed on which the routine spares less than the protocol's floor is excluded by name
(:data:`BELOW_FLOOR`), because a near-zero denominator would let one seed decide a mean.

What a model said about itself never reaches a score: this module reads engine states and the
dispositions the engine recorded, never a receipt, its call record, its tokens or its answer, and
the import rules keep the model client, the asking path and the API out of its reach (the "A
person's score cannot read a model" contract in ``pyproject.toml``). The call facts a comparison
reports beside the score, cost and latency among them, are read elsewhere and carry no weight.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Final

from exulanica.world.society_catalogs import ANY_KIND, PurposefulRoutine

__all__ = [
    "APPLIED",
    "BELOW_FLOOR",
    "DECISION_EVENT",
    "MINUTE_CLASSES",
    "PRIMARY_TERMS",
    "STATE_MEASURES",
    "TURN_TERMS",
    "PersonScore",
    "RunTerms",
    "ScoreRefused",
    "SeedScore",
    "need_threshold",
    "person_score",
    "run_terms",
    "seed_score",
    "state_measures",
]

#: Why a seed carries no score: the routine spared less need on it than the protocol's floor.
BELOW_FLOOR: Final = "need_below_floor"
#: The weighed terms, by the catalog key each is declared under: need relief, which this module
#: computes from states, and the turn terms, which it counts from events.
TURN_TERMS: Final = ("turns_refused", "turns_unanswered")
PRIMARY_TERMS: Final = ("need_relief", *TURN_TERMS)
#: The reported measures read from states, which carry no weight.
STATE_MEASURES: Final = ("activities_per_person", "waiting_share", "walking_share")
#: The event the engine appends for every receipt a minute consumes, and the disposition of one
#: whose choice the minute applied: ``DECISION_EVENT_KIND`` and the first of ``_DISPOSITIONS`` in
#: exulanica/world/society_model_decisions.py, which imports the model client and so is out of this
#: module's reach; tests/test_society_score.py holds the two equal.
DECISION_EVENT: Final = "decision_applied"
APPLIED: Final = "applied"
#: What a person-minute was: walking when the minute's path moved, doing something when an
#: activity was under way or finished in it, and otherwise waiting. The planner's action for a
#: person with nothing under way is ``idle`` and for a walk ``move``; neither is an activity.
MINUTE_CLASSES: Final = ("doing", "waiting", "walking")
_NOT_AN_ACTIVITY: Final = frozenset({"idle", "move"})
_UNDER_WAY: Final = frozenset({"active", "completed"})


class ScoreRefused(ValueError):
    """A run or a catalog the score cannot read, refused by name rather than scored otherwise."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code


@dataclass(frozen=True, slots=True)
class PersonScore:
    """The score a catalog version declares, in the form this module computes it."""

    #: Each weighed term's weight, in thousandths.
    weights: Mapping[str, int]
    #: For each disposition a weighed term counts, that term.
    counted: Mapping[str, str]


def person_score(entries: Mapping[str, Mapping[str, Any]]) -> PersonScore:
    """The score the catalog's entries declare, refused by name where it is not the one computed
    here: exactly :data:`PRIMARY_TERMS` weighed, need relief read from states and the two turn
    terms from events, each disposition counted once, and the state measures reported."""
    primary = {key: entry for key, entry in entries.items() if entry["part"] == "primary"}
    if sorted(primary) != sorted(PRIMARY_TERMS):
        raise ScoreRefused("score_terms_not_computed", f"weighs {sorted(primary)}")
    reads = {key: primary[key]["reads"] for key in PRIMARY_TERMS}
    if reads != {"need_relief": "states", "turns_refused": "events", "turns_unanswered": "events"}:
        raise ScoreRefused("score_terms_not_computed", f"its terms read {reads}")
    measured = sorted(
        key
        for key, entry in entries.items()
        if entry["part"] == "held_out" and entry["reads"] == "states"
    )
    if measured != sorted(STATE_MEASURES):
        raise ScoreRefused("score_measures_not_computed", f"reports {measured} from states")
    counted: dict[str, str] = {}
    for key in TURN_TERMS:
        for disposition in primary[key]["dispositions"]:
            if disposition == APPLIED or disposition in counted:
                raise ScoreRefused("disposition_counted_twice", f"{disposition} in {key}")
            counted[str(disposition)] = key
    return PersonScore(
        weights={key: int(primary[key]["weight_milli"]) for key in PRIMARY_TERMS},
        counted=counted,
    )


def need_threshold(routine: PurposefulRoutine) -> int:
    """The need, in thousandths, at which ``routine`` prefers an activity to every other.

    The smallest positive ``preferred_at_need`` among the activities any object may offer, the
    set the planner reads when it asks what a tired person prefers. A routine that prefers
    nothing at any need gives the score no threshold, and is refused by name.
    """
    stated = [
        activity.preferred_at_need
        for activity in routine.activities.values()
        if activity.object_kind == ANY_KIND and activity.preferred_at_need > 0
    ]
    if not stated:
        raise ScoreRefused("routine_prefers_nothing", "the routine states no need threshold")
    return min(stated)


@dataclass(frozen=True, slots=True)
class RunTerms:
    """One run's exact terms, integers only, as the catalog's world-reading entries name them."""

    ticks: int
    threshold: int
    people: tuple[str, ...]
    #: Need above the threshold, summed over person-minutes.
    urgency: int
    #: Every turn: a receipt a minute consumed for one of the people.
    turns: int
    applied: int
    #: The turns each counting term counts, by its key.
    counted: tuple[tuple[str, int], ...]
    #: Why each turn that was not applied was not, by the reason the engine recorded.
    not_applied_reasons: tuple[tuple[str, int], ...]
    #: The person-minutes by what they were: walking, doing something, waiting.
    person_minutes: tuple[tuple[str, int], ...]
    #: For each person, how many different activities they were seen doing.
    activities: tuple[tuple[str, int], ...]

    def document(self) -> dict[str, Any]:
        """The terms as a record stores them: integers and sorted pairs, nothing derived."""
        return {
            "ticks": self.ticks,
            "threshold": self.threshold,
            "people": list(self.people),
            "urgency": self.urgency,
            "turns": self.turns,
            "applied": self.applied,
            "counted": dict(self.counted),
            "not_applied_reasons": dict(self.not_applied_reasons),
            "person_minutes": dict(self.person_minutes),
            "activities": dict(self.activities),
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> RunTerms:
        return cls(
            ticks=int(document["ticks"]),
            threshold=int(document["threshold"]),
            people=tuple(document["people"]),
            urgency=int(document["urgency"]),
            turns=int(document["turns"]),
            applied=int(document["applied"]),
            counted=tuple(sorted(document["counted"].items())),
            not_applied_reasons=tuple(sorted(document["not_applied_reasons"].items())),
            person_minutes=tuple(sorted(document["person_minutes"].items())),
            activities=tuple(sorted(document["activities"].items())),
        )


def _minute_class(person: Mapping[str, Any]) -> str:
    if len(person["motion_path_mm"]) > 1:
        return "walking"
    action = person["action"]
    if action["status"] in _UNDER_WAY and action["kind"] not in _NOT_AN_ACTIVITY:
        return "doing"
    return "waiting"


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
    score: PersonScore,
) -> RunTerms:
    """The exact terms of one run: ``states`` are its minutes after genesis, in order, and
    ``events`` every event its minutes produced (``SocietyEvent`` or its stored form).

    Only a state's ``need_milli``, path and action, and a ``decision_applied`` event's subject,
    disposition and reason are read. Every person named is in every minute, or the run is refused.
    """
    members = tuple(sorted(people))
    if not members:
        raise ScoreRefused("no_people", "a score is over at least one person")
    if not states:
        raise ScoreRefused("no_minutes", "a run with no minutes has nothing to score")
    ticks = [state["tick"] for state in states]
    if ticks != list(range(ticks[0], ticks[0] + len(ticks))):
        raise ScoreRefused("minutes_out_of_order", "a run's minutes are consecutive")
    held = frozenset(members)
    urgency = 0
    minutes: Counter[str] = Counter()
    seen: dict[str, set[str]] = {subject: set() for subject in members}
    for state in states:
        found = {person["id"]: person for person in state["inhabitants"]}
        if not held <= set(found):
            raise ScoreRefused("person_not_in_minute", "every person scored is in each minute")
        for subject in members:
            person = found[subject]
            urgency += max(0, int(person["need_milli"]) - threshold)
            kind = _minute_class(person)
            minutes[kind] += 1
            if kind == "doing":
                seen[subject].add(str(person["action"]["kind"]))
    turns = applied = 0
    counted: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    for event in events:
        kind, subject, document = _event_parts(event)
        if kind != DECISION_EVENT or subject not in held:
            continue
        turns += 1
        disposition = document["disposition"]
        if disposition == APPLIED:
            applied += 1
            continue
        term = score.counted.get(disposition)
        if term is None:
            raise ScoreRefused("disposition_not_scored", f"no term counts {disposition!r}")
        counted[term] += 1
        reasons[str(document["reason"])] += 1
    return RunTerms(
        ticks=len(states),
        threshold=threshold,
        people=members,
        urgency=urgency,
        turns=turns,
        applied=applied,
        counted=tuple(sorted({key: counted[key] for key in TURN_TERMS}.items())),
        not_applied_reasons=tuple(sorted(reasons.items())),
        person_minutes=tuple(sorted({key: minutes[key] for key in MINUTE_CLASSES}.items())),
        activities=tuple(sorted((subject, len(kinds)) for subject, kinds in seen.items())),
    )


def _share(part: int, whole: int) -> Fraction:
    return Fraction(part, whole) if whole else Fraction(0)


def state_measures(run: RunTerms) -> dict[str, Fraction]:
    """The run's reported measures from states, exact: they need no anchor and carry no weight."""
    minutes = dict(run.person_minutes)
    total = sum(minutes.values())
    return {
        "activities_per_person": Fraction(
            sum(count for _, count in run.activities), len(run.people)
        ),
        "waiting_share": _share(minutes["waiting"], total),
        "walking_share": _share(minutes["walking"], total),
    }


@dataclass(frozen=True, slots=True)
class SeedScore:
    """One run's score on one seed against that seed's two anchors, exact and unclipped."""

    excluded: str | None
    need_relief: Fraction | None
    #: Each turn term's share of the run's turns, which needs no anchor.
    shares: Mapping[str, Fraction]
    score: Fraction | None


def seed_score(
    run: RunTerms,
    *,
    waiting: RunTerms,
    routine: RunTerms,
    score: PersonScore,
    floor: int,
) -> SeedScore:
    """The run's score on its seed: each weighed term times its weight in thousandths.

    ``waiting`` and ``routine`` are the same seed's anchor runs over the same people and window.
    Below the floor the seed is excluded by name and carries no score; the shares are still
    stated, since they do not depend on the anchors.
    """
    for anchor in (waiting, routine):
        if (anchor.people, anchor.ticks, anchor.threshold) != (
            run.people,
            run.ticks,
            run.threshold,
        ):
            raise ScoreRefused("anchor_mismatch", "anchors run the same people, window, threshold")
    counted = dict(run.counted)
    shares = {key: _share(counted[key], run.turns) for key in TURN_TERMS}
    spared = waiting.urgency - routine.urgency
    if spared < floor or spared <= 0:
        return SeedScore(BELOW_FLOOR, None, shares, None)
    relief = Fraction(waiting.urgency - run.urgency, spared)
    terms = {"need_relief": relief, **shares}
    total = sum((terms[key] * score.weights[key] / 1000 for key in PRIMARY_TERMS), Fraction(0))
    return SeedScore(None, relief, shares, total)
