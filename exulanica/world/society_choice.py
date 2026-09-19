"""The seam where the living society's next action is chosen, and who is allowed to choose it.

The engine has always chosen with one rule, ``society_living._choose``: the most pressing
reachable activity with room. That rule is not replaced here and it is not optional. It is named
as the fallback, and everything else in this module exists to let something else answer first and
to record, per choice, whether it did.

Three things this module is built around, and each of them is a decision taken before it:

**The decision is recorded, never the decider.** A live session asks, takes the typed answer and
writes the answer into the record. A replay reads the recorded answer and never calls anything.
A world that behaves differently depending on a flag is two worlds, and a memory located because
somebody walked there loses its provenance the moment that walk cannot be reproduced. So
``RecordedChoices`` is not a mode of the model path; it is the only thing a replay ever uses, and
it cannot reach a provider because it holds none.

**The threshold is the knob and it starts nearly closed.** ``ModelChoices`` takes an answer only
when its calibrated confidence reaches ``threshold_milli``. Below it the deterministic chooser
answers, and the counters separate the two. A threshold of 1000 means the model must be certain,
which is where an experiment starts; lowering it is how the model earns decisions.

**Nothing may become load bearing on the model.** Every path through ``ModelChoices`` that does
not produce an answer, including a provider that raises, ends at the same deterministic chooser,
so a society whose provider is unreachable runs exactly as it runs today. ``tests`` proves that by
running one with a provider that raises on every call.

``ChoiceCounters`` names different sets and never adds one into another. ``asked`` counts calls to
this seam. ``not_the_rule`` and ``fallback`` partition it by who answered, and they partition on
``RULE`` against not-``RULE`` rather than on model against not-model, so a bound or an oracle
counts honestly. Three separate counts say why a fallback happened: ``below_threshold`` had an
answer and rejected it for confidence, ``answered_outside_the_set`` had one and rejected it for
naming a thing that was not offered, and ``provider_silent`` had none at all. A single "the model
did not decide" count would hide which of the three is happening, and they call for different
actions. People and ticks are not counted here because they belong to the run, not to the seam.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Final, Protocol

__all__ = [
    "MODEL",
    "RULE",
    "ChoiceAnswer",
    "ChoiceCounters",
    "ChoiceDecision",
    "ChoiceProvider",
    "ChoiceQuestion",
    "ChoiceSource",
    "DeterministicChoices",
    "ModelChoices",
    "RecordedChoices",
    "choice_question",
]

#: What answered one choice. Recorded on every decision, so a record states who chose.
#: ``RULE`` is the engine's own chooser and is the fallback of everything else here. Anything
#: else is a name for whoever was asked first, and the counters partition by ``RULE`` against
#: not-``RULE`` rather than by model against not-model, so a bound or an oracle counts honestly.
RULE: Final = "deterministic_chooser"
MODEL: Final = "model"

#: Confidence is milli, like every other fraction in the society, so no float reaches a digest.
CONFIDENCE_SCALE: Final = 1000

#: The only option fields a provider is ever shown. Generated world state, and nothing else.
_SHOWN_OPTION_KEYS: Final = (
    "option_key",
    "activity",
    "destination_id",
    "spot_id",
    "cost_mm",
    "load_milli",
    "urgency",
    "because",
)


@dataclass
class ChoiceCounters:
    """Sets counted apart. ``asked`` is ``not_the_rule`` plus ``fallback``, and nothing else."""

    asked: int = 0
    not_the_rule: int = 0
    fallback: int = 0
    below_threshold: int = 0
    answered_outside_the_set: int = 0
    provider_silent: int = 0
    without_destination: int = 0
    nothing_possible: int = 0
    by_destination: Counter[str] = field(default_factory=Counter)

    def record(self, decision: ChoiceDecision) -> None:
        self.asked += 1
        if decision.decided_by == RULE:
            self.fallback += 1
        else:
            self.not_the_rule += 1
        if decision.rejected_confidence_milli is not None:
            self.below_threshold += 1
        if decision.answered_outside_the_set:
            self.answered_outside_the_set += 1
        if decision.provider_silent:
            self.provider_silent += 1
        if decision.destination_id is not None:
            self.by_destination[decision.destination_id] += 1
        elif decision.blocked_reason is not None:
            self.nothing_possible += 1
        else:
            self.without_destination += 1


@dataclass(frozen=True, slots=True)
class ChoiceQuestion:
    """One inhabitant's closed answer set, as generated world state and nothing else.

    ``options`` is the set the deterministic chooser was about to pick from, so a model that
    answers this question is choosing among the same things the rule would. It carries no
    photograph, no caption and nothing derived from one; see the module docstring of
    ``exulanica.models.model_rights`` for what crossing that line would require.

    **ONE ROW PER ACTIVITY, AND THE TARGET INSIDE IT WAS ALREADY NARROWED.** ``society_living``
    builds each row by choosing that activity's best target first, so this question asks WHICH
    ACTIVITY and not which destination. Anyone running a destination-choice experiment must widen
    ``_question`` to carry every target rather than the narrowed pick, or they will measure a
    model choosing between things that were already decided.

    MEASURED on the Flatiron place, 120 ticks, 2026-09-19, so the size of what is hidden is stated
    rather than guessed: the narrowing discards essentially nothing for destinations, because
    ``rest`` offers a mean of 1.07 reachable pads with room and ``visit`` offers exactly 1.00. It
    discards a great deal for ``stroll``, which offers about 47 standing spots and picks among
    them by a seeded hash. So on that place a destination choice barely exists to be made, and the
    wide choice is which paving stone to stand on.
    """

    subject_ordinal: int
    tick: int
    minute_of_day: int
    day: int
    needs: dict[str, int]
    options: tuple[dict[str, Any], ...]

    @property
    def option_keys(self) -> tuple[str, ...]:
        """The closed answer set a typed decision must land inside."""
        return tuple(option["option_key"] for option in self.options)

    def payload(self) -> dict[str, Any]:
        """Exactly what a provider may be shown, assembled here and nowhere else.

        ``options`` carries an ``outcome`` holding live engine objects, and a provider must never
        receive one: it is not serialisable, it is not generated world state in the sense a model
        right means, and a payload built by whoever happens to be calling would drift from this
        rule the first time an engine field is added. So the allowed keys are listed, and a new
        engine field is invisible to every provider until somebody adds it to this tuple.
        """
        return {
            "subject_ordinal": self.subject_ordinal,
            "tick": self.tick,
            "minute_of_day": self.minute_of_day,
            "day": self.day,
            "needs": dict(self.needs),
            "options": [
                {key: option[key] for key in _SHOWN_OPTION_KEYS if key in option}
                for option in self.options
            ],
        }


@dataclass(frozen=True, slots=True)
class ChoiceAnswer:
    """A typed answer and its calibrated confidence. ``option_key`` is never free text."""

    option_key: str
    confidence_milli: int

    def __post_init__(self) -> None:
        if type(self.confidence_milli) is not int or not 0 <= self.confidence_milli <= 1000:
            raise ValueError("confidence is 0 to 1000 milli")


@dataclass(frozen=True, slots=True)
class ChoiceDecision:
    """What the seam returned, and who decided it. This is what a session record stores."""

    outcome: Any
    decided_by: str
    option_key: str | None
    destination_id: str | None
    blocked_reason: str | None
    confidence_milli: int | None = None
    rejected_confidence_milli: int | None = None
    answered_outside_the_set: bool = False
    provider_silent: bool = False

    def recorded(self) -> dict[str, Any]:
        """The decision as a record stores it: the answer and who gave it, never the decider."""
        return {
            "decided_by": self.decided_by,
            "option_key": self.option_key,
            "confidence_milli": self.confidence_milli,
            "rejected_confidence_milli": self.rejected_confidence_milli,
        }


class ChoiceProvider(Protocol):
    """Answers a batch of questions at once, typed, or returns nothing for one it will not answer.

    A batch, because the candidate this seam exists for answers every question of a tick in one
    parallel pass. A provider that can only answer one at a time satisfies this by returning a
    one-entry mapping, and the seam does not care which it is.
    """

    def answer(self, questions: tuple[ChoiceQuestion, ...]) -> dict[int, ChoiceAnswer]: ...


class ChoiceSource(Protocol):
    """What the engine asks. ``deterministic`` is the rule, and it is always available."""

    records: bool

    def decide(
        self,
        question: Callable[[], ChoiceQuestion],
        deterministic: Callable[[], Any],
    ) -> ChoiceDecision: ...


def _outcome_keys(outcome: Any) -> tuple[str | None, str | None, str | None]:
    """Read an engine outcome without retyping what the engine means by one."""
    if isinstance(outcome, str):
        return None, None, outcome
    _activity, pick, _because = outcome
    destination_id = pick.get("destination_id")
    return option_key(pick), destination_id, None


def option_key(pick: dict[str, Any]) -> str:
    """The stable name of one option. A destination and a plain spot are both addressable."""
    return f"{pick.get('destination_id') or ''}|{pick.get('spot_id') or ''}"


@dataclass(frozen=True, slots=True)
class DeterministicChoices:
    """The rule, alone. With this source the engine produces exactly the state it always has."""

    counters: ChoiceCounters | None = None

    #: A run that consulted nothing records nothing new, so its events stay byte for byte.
    records: ClassVar[bool] = False

    def decide(
        self,
        question: Callable[[], ChoiceQuestion],
        deterministic: Callable[[], Any],
    ) -> ChoiceDecision:
        outcome = deterministic()
        key, destination_id, blocked = _outcome_keys(outcome)
        decision = ChoiceDecision(
            outcome=outcome,
            decided_by=RULE,
            option_key=key,
            destination_id=destination_id,
            blocked_reason=blocked,
        )
        if self.counters is not None:
            self.counters.record(decision)
        return decision


@dataclass(frozen=True, slots=True)
class ModelChoices:
    """Ask the provider, take the answer only above the bar, and fall through to the rule.

    The provider is asked for one question at a time here. Batching a whole tick is the candidate
    model's reason for existing and is a separate change to the engine's loop; this class is the
    part that decides whether an answer is taken, and it is the part the threshold experiment
    moves. Every failure of the provider, including an exception, falls through to the rule.
    """

    provider: ChoiceProvider
    threshold_milli: int
    counters: ChoiceCounters | None = None

    #: Every choice of this run states who answered it, the fallen-through ones included.
    records: ClassVar[bool] = True

    def __post_init__(self) -> None:
        if type(self.threshold_milli) is not int or not 0 <= self.threshold_milli <= 1000:
            raise ValueError("the threshold is 0 to 1000 milli")

    def decide(
        self,
        question: Callable[[], ChoiceQuestion],
        deterministic: Callable[[], Any],
    ) -> ChoiceDecision:
        asked = question()
        answer: ChoiceAnswer | None = None
        if asked.options:
            try:
                answer = self.provider.answer((asked,)).get(0)
            except Exception:
                answer = None
        taken = answer if answer is not None and answer.option_key in asked.option_keys else None
        if taken is not None and taken.confidence_milli >= self.threshold_milli:
            chosen = next(o for o in asked.options if o["option_key"] == taken.option_key)
            decision = ChoiceDecision(
                outcome=chosen["outcome"],
                decided_by=MODEL,
                option_key=taken.option_key,
                destination_id=chosen.get("destination_id"),
                blocked_reason=None,
                confidence_milli=taken.confidence_milli,
            )
        else:
            outcome = deterministic()
            key, destination_id, blocked = _outcome_keys(outcome)
            decision = ChoiceDecision(
                outcome=outcome,
                decided_by=RULE,
                option_key=key,
                destination_id=destination_id,
                blocked_reason=blocked,
                rejected_confidence_milli=taken.confidence_milli if taken is not None else None,
                answered_outside_the_set=answer is not None and taken is None,
                provider_silent=answer is None and bool(asked.options),
            )
        if self.counters is not None:
            self.counters.record(decision)
        return decision


@dataclass(frozen=True, slots=True)
class RecordedChoices:
    """A replay. Reads the recorded answer for this choice; holds no provider and calls none.

    The recorded answer names an option key, so a replay whose place no longer offers that option
    is a replay of a different world. That is an error rather than a silent re-decision: a record
    that quietly re-chooses is a record that cannot be audited.
    """

    recorded: tuple[dict[str, Any], ...]
    counters: ChoiceCounters | None = None
    records: ClassVar[bool] = True
    _cursor: list[int] = field(default_factory=lambda: [0], compare=False)

    def decide(
        self,
        question: Callable[[], ChoiceQuestion],
        deterministic: Callable[[], Any],
    ) -> ChoiceDecision:
        index = self._cursor[0]
        if index >= len(self.recorded):
            raise ValueError("the record holds fewer decisions than this replay asks for")
        self._cursor[0] = index + 1
        entry = self.recorded[index]
        if entry["decided_by"] == RULE:
            outcome = deterministic()
            key, destination_id, blocked = _outcome_keys(outcome)
            decision = ChoiceDecision(
                outcome=outcome,
                decided_by=RULE,
                option_key=key,
                destination_id=destination_id,
                blocked_reason=blocked,
                rejected_confidence_milli=entry["rejected_confidence_milli"],
            )
        else:
            asked = question()
            options = {o["option_key"]: o for o in asked.options}
            if entry["option_key"] not in options:
                raise ValueError("the recorded option is not offered by this place")
            chosen = options[entry["option_key"]]
            decision = ChoiceDecision(
                outcome=chosen["outcome"],
                decided_by=MODEL,
                option_key=entry["option_key"],
                destination_id=chosen.get("destination_id"),
                blocked_reason=None,
                confidence_milli=entry["confidence_milli"],
            )
        if self.counters is not None:
            self.counters.record(decision)
        return decision


def choice_question(
    *,
    subject_ordinal: int,
    tick: int,
    minute_of_day: int,
    day: int,
    needs: dict[str, int],
    options: tuple[dict[str, Any], ...],
) -> ChoiceQuestion:
    """Build one question. Kept here so the engine never assembles a provider payload itself."""
    return ChoiceQuestion(
        subject_ordinal=subject_ordinal,
        tick=tick,
        minute_of_day=minute_of_day,
        day=day,
        needs=dict(needs),
        options=options,
    )
