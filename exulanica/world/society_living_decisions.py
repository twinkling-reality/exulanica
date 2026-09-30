"""A person in a living society deciding what to do next: the person role's code for that family.

The person role (:mod:`exulanica.world.roles.person`) decides for a person in a purposeful society
and in a living one, and its adapter hands a living state here, by the state family the engine
table states for the state's engine. What differs from the purposeful person's contract is only
where the options come from and how the minute takes the answer; the contract itself (its action
catalog's words, its bounds and its reasons) is the person role's, unchanged:

*   **What the person may do** is the living engine's own answer set for them in the coming minute
    (:func:`~exulanica.world.society_living.next_minute_options`): one option for each activity the
    rule could start for them, at the target the rule itself picks for it, read by the action
    catalog's ``target`` words from the routine's words for the activity and the walk; and waiting a
    minute. A model chooses which of the things the routine offers comes first, never where the
    routine says nothing can be done. The options are shuffled by the society's seed, the person
    and the minute, as the purposeful person's are.
*   **What the person sees** is the minute, what they are doing, the job they hold, each need
    against the level at which the routine sees to it, and the options. Nothing in it names anybody.
*   **How the minute takes the answer**: every accepted choice is checked by the minute itself, on
    a trial of it, through the living engine's choice seam
    (:class:`~exulanica.world.society_choice.AppliedChoices`): the people a model decided for act
    first in decision order, each taking what their model chose where their turn still offers it,
    and otherwise the rule decides for them and the receipt is ``rejected`` with the reason. The
    minute then runs with the same choices in the same order, so what the trial found is what the
    minute does.

What it does not do: ask a model, store anything, or decide for anybody the owner did not choose a
model for. Nothing here reads a database.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Final

from exulanica.world.decision_roles import DecisionContract, DecisionRole
from exulanica.world.role_decisions import DecisionDisposition, written_messages
from exulanica.world.society import SOCIETY_NAMESPACE, SocietyEvent, society_state_sha256
from exulanica.world.society_catalogs import MINUTES_PER_DAY, RoutineModel
from exulanica.world.society_choice import WAIT_KEY, AppliedChoices, option_key
from exulanica.world.society_decision_contract import DecisionOption
from exulanica.world.society_living import (
    LivingPlace,
    advance_living_society,
    at_living_choice_point,
    input_routine,
    living_places,
    next_minute_options,
    routine_for,
)
from exulanica.world.society_planner import input_sha256

__all__ = [
    "DECISION_EVENT_KIND",
    "LivingSeam",
    "apply_living_receipts",
    "living_context",
    "living_decision_events",
    "living_due",
    "living_messages",
    "living_options",
    "living_seam",
    "living_situation",
    "living_step",
]

#: The event kind a consumed receipt is recorded under, the purposeful person's too.
DECISION_EVENT_KIND: Final = "decision_applied"
#: The dispositions a consumed receipt may have, the ones migration 0055 binds a transition to.
_DISPOSITIONS: Final = ("applied", "rejected", "unavailable", "stale", "superseded")


@dataclass(frozen=True)
class LivingSeam:
    """A living minute's seam: what it walks and under which routine, and the choices a chosen
    model made for it, applied through :class:`AppliedChoices`, the people they are for acting
    first in decision order."""

    seed: str
    places: Sequence[LivingPlace]
    routine: RoutineModel
    #: Each decided person's ordinal, and the activity and option key their model chose or
    #: :data:`~exulanica.world.society_choice.WAIT_KEY`.
    chosen: Mapping[int, tuple[str, str] | str] = field(default_factory=dict)
    #: The people decided for, by identity, in decision order: they act first.
    acting_first: tuple[str, ...] = ()

    def choices(self) -> AppliedChoices:
        return AppliedChoices(dict(self.chosen))


def living_step(
    state: dict[str, Any], seed: str, seam: LivingSeam
) -> tuple[dict[str, Any], tuple[SocietyEvent, ...]]:
    """One living minute over ``seam``: the rule, with the choices the seam holds applied first.

    The hook a run of minutes steps a living society by (a comparison's step, once a comparison
    runs a living engine), as the repository's advance does."""
    return advance_living_society(
        state,
        seed,
        seam.places,
        seam.routine,
        seam.choices(),
        acting_first=seam.acting_first,
    )


def living_seam(
    state: Mapping[str, Any], seed: str, sources: Sequence[dict[str, Any]]
) -> LivingSeam:
    """The seam a living minute over ``sources`` starts from, with nobody decided for yet."""
    routine = routine_for(dict(state))
    return LivingSeam(seed=seed, places=living_places(sources, routine), routine=routine)


def _person(state: Mapping[str, Any], subject_id: str) -> dict[str, Any]:
    person = next((p for p in state["inhabitants"] if p["id"] == subject_id), None)
    if person is None:
        raise ValueError("the subject is not one of this society's people")
    return person


def _place(source: Mapping[str, Any], routine: RoutineModel) -> LivingPlace:
    """The place the coming minute consumes last: the input the options are built over."""
    [place] = living_places([dict(source)], routine)
    return place


def living_due(state: Mapping[str, Any], subject_id: str) -> bool:
    """Whether the rule chooses for this person in the coming minute."""
    return at_living_choice_point(_person(state, subject_id))


def living_options(
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    contract: DecisionContract,
    *,
    seed: str,
) -> tuple[DecisionOption, ...]:
    """What this person may be asked to do in the coming minute, in the order a model reads it:
    each row of the engine's own answer set, then waiting, shuffled by the society's seed, the
    person and the minute. Empty where the rule will not choose for them, or nothing but waiting
    is left: such a person is left to the routine."""
    routine = routine_for(dict(state))
    if input_routine(dict(source)).sha256 != routine.sha256:
        return ()
    rows = next_minute_options(dict(state), seed, _place(source, routine), routine, subject_id)
    if not rows:
        return ()
    options: list[DecisionOption] = []
    for key, activity, pick, _because in rows[: contract.value("options_maximum") - 1]:
        options.append(
            DecisionOption(
                label=contract.words["target"].format(
                    activity=activity.label, metres=round(pick["cost_mm"] / 1000)
                ),
                kind="target",
                action=contract.action_keys["target"],
                target_id=option_key(pick),
                activity=key,
                walk_mm=pick["cost_mm"],
            )
        )
    options.append(
        DecisionOption(
            label=contract.words["wait"],
            kind="wait",
            action=contract.action_keys["wait"],
            target_id=None,
            activity=None,
            walk_mm=None,
        )
    )
    random.Random(f"{seed}:{subject_id}:{state['tick']}").shuffle(options)
    return tuple(options)


def living_context(
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    subject_id: str,
    options: Sequence[DecisionOption],
    *,
    profile: str,
) -> dict[str, Any]:
    """What a living person sees, as a request of ``profile`` records it: the coming minute, what
    they are doing, the job they hold, each need against the level the routine sees to it at, and
    their options in order. ``engine`` names the state's engine, which says how it is read."""
    person = _person(state, subject_id)
    routine = routine_for(dict(state))
    absolute = state["clock"]["start_minute_of_day"] + state["tick"] + 1
    action = person["action"]
    return {
        "profile": profile,
        "engine": state["profile"],
        "subject_id": subject_id,
        "branch_id": state["branch_id"],
        "tick": state["tick"],
        "clock": {"minute_of_day": absolute % MINUTES_PER_DAY, "day": absolute // MINUTES_PER_DAY},
        "role": None if person["role"] is None else person["role"]["label"],
        "needs": [
            {
                "label": routine.needs[key].label,
                "milli": value,
                "seen_to_at_milli": routine.needs[key].threshold,
            }
            for key, value in sorted(person["needs"].items())
        ],
        "doing": {"kind": action["kind"], "status": action["status"], "reason": action["reason"]},
        "options": [option.as_record() for option in options],
    }


def living_situation(context: Mapping[str, Any]) -> list[str]:
    """A living person's situation as a model reads it, before their options."""
    clock = context["clock"]
    minute = clock["minute_of_day"]
    doing = context["doing"]
    if doing["status"] == "completed":
        now = "you have just finished what you were doing"
    elif doing["status"] == "blocked":
        now = "you could not do what you wanted"
    else:
        now = "you are free to choose what to do"
    lines = [
        f"It is {minute // 60:02d}:{minute % 60:02d} on day {clock['day']} in the town, and {now}.",
        f"You work as a {context['role']}." if context["role"] else "You have no job.",
    ]
    lines.extend(
        f"Need for {need['label']}: {need['milli']} of 1000; people here see to it once it "
        f"passes {need['seen_to_at_milli']}."
        for need in context["needs"]
    )
    return lines


def living_messages(
    role: DecisionRole, context: Mapping[str, Any], mechanism: Any
) -> list[dict[str, str]]:
    return written_messages(role, living_situation(context), context, mechanism)


def _checked(receipt: Mapping[str, Any], profile: str) -> None:
    if (
        receipt.get("profile") != profile
        or receipt["document_sha256"] != input_sha256(dict(receipt))
        or receipt["status"] not in ("accepted", "rejected", "unavailable", "stale")
    ):
        raise ValueError("a living society consumes only sealed person decision receipts")


def apply_living_receipts(
    state: Mapping[str, Any],
    source: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    seam: LivingSeam,
    *,
    profile: str,
) -> tuple[LivingSeam, tuple[DecisionDisposition, ...]]:
    """The minute's seam with every accepted choice it can take, and what each receipt did.

    A receipt that is not ``accepted`` does nothing; one asked over another state or input is
    ``stale``; a second receipt for somebody already decided this minute is ``superseded``; one
    for somebody not at a choice point is ``rejected``. Every other choice is tried on the minute
    itself, its people acting first in decision order, and is ``applied`` where their turn found
    what their model chose, otherwise ``rejected`` with the reason the seam gives.
    """
    if not receipts:
        return seam, ()
    prior = society_state_sha256(dict(state))
    sequences = [receipt["decision_seq"] for receipt in receipts]
    if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
        raise ValueError("person decision receipts are consumed once each, in decision order")
    people = {person["id"]: person for person in state["inhabitants"]}
    settled: dict[int, tuple[str, str]] = {}
    chosen: dict[int, tuple[str, str] | str] = {}
    order: list[str] = []
    tried: dict[int, int] = {}
    for index, receipt in enumerate(receipts):
        _checked(receipt, profile)
        subject = receipt["subject_id"]
        if receipt["status"] != "accepted":
            settled[index] = (receipt["status"], receipt["reason"])
        elif (
            receipt["base_tick"] != state["tick"]
            or receipt["base_state_sha256"] != prior
            or receipt["input_sha256"] != source["document_sha256"]
            or receipt["branch_id"] != state["branch_id"]
            or subject not in people
        ):
            settled[index] = ("stale", "decision_context_changed")
        elif subject in order:
            settled[index] = ("superseded", "subject_already_decided")
        elif not at_living_choice_point(people[subject]):
            settled[index] = ("rejected", "action_in_progress")
        else:
            option = DecisionOption.from_record(receipt["proposal"]["option"])
            ordinal = people[subject]["ordinal"]
            if option.kind == "wait":
                chosen[ordinal] = WAIT_KEY
            elif option.kind == "target" and option.activity and option.target_id:
                chosen[ordinal] = (option.activity, option.target_id)
            else:
                raise ValueError(f"a living person takes no {option.kind!r} choice")
            order.append(subject)
            tried[index] = ordinal
    decided = LivingSeam(
        seed=seam.seed,
        places=seam.places,
        routine=seam.routine,
        chosen=chosen,
        acting_first=tuple(order),
    )
    if tried:
        trial = decided.choices()
        advance_living_society(
            dict(state),
            seam.seed,
            seam.places,
            seam.routine,
            trial,
            acting_first=decided.acting_first,
        )
        for index, ordinal in tried.items():
            if ordinal in trial.taken:
                settled[index] = ("applied", receipts[index]["reason"])
            else:
                settled[index] = ("rejected", trial.refused.get(ordinal, "action_in_progress"))
    dispositions = tuple(
        DecisionDisposition(
            decision_seq=receipt["decision_seq"],
            request_id=receipt["request_id"],
            subject_id=receipt["subject_id"],
            disposition=settled[index][0],
            reason=settled[index][1],
            decision_sha256=receipt["document_sha256"],
        )
        for index, receipt in enumerate(receipts)
    )
    return decided, dispositions


def living_decision_events(
    previous_state: Mapping[str, Any],
    next_state: Mapping[str, Any],
    document: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    dispositions: Sequence[DecisionDisposition],
    events: tuple[SocietyEvent, ...],
) -> tuple[SocietyEvent, ...]:
    """The minute's events with one ``decision_applied`` event per consumed receipt appended,
    naming the person by the job they hold, as a living society's events do."""
    if len(receipts) != len(dispositions):
        raise ValueError("every consumed person decision has one disposition")
    if not receipts:
        return events
    people = {person["id"]: person for person in next_state["inhabitants"]}
    previous_digest = society_state_sha256(dict(previous_state))
    result = list(events)
    for receipt, disposition in zip(receipts, dispositions, strict=True):
        if disposition.disposition not in _DISPOSITIONS:
            raise ValueError(f"no disposition {disposition.disposition!r}")
        person = people.get(disposition.subject_id)
        role = "person" if person is None or person["role"] is None else person["role"]["label"]
        provider = receipt["provider"]
        order = len(result)
        event_document = {
            "summary": (
                f"A {role} (simulated): the model's decision was "
                f"{disposition.disposition}; {disposition.reason.replace('_', ' ')}."
            ),
            "synthetic": True,
            "profile": next_state["profile"],
            "branch_id": next_state["branch_id"],
            "subject_id": disposition.subject_id,
            "tick": next_state["tick"],
            "order": order,
            "input_seq": document["input_seq"],
            "input_sha256": document["document_sha256"],
            "reason": disposition.reason,
            "outcome": f"decision_{disposition.disposition}",
            "goal": None if person is None else deepcopy(person["goal"]),
            "action": None if person is None else deepcopy(person["action"]),
            "position_mm": None if person is None else list(person["position_mm"]),
            "motion_path_mm": None if person is None else deepcopy(person["motion_path_mm"]),
            "previous_state_sha256": previous_digest,
            "seed_sha256": previous_state["seed_sha256"],
            "origin": "model",
            "decision_seq": disposition.decision_seq,
            "request_id": disposition.request_id,
            "decision_sha256": disposition.decision_sha256,
            "disposition": disposition.disposition,
            "model": (
                None
                if provider is None
                else {"provider": provider["provider"], "model_id": provider["model_id"]}
            ),
            "chose": None if receipt["proposal"] is None else receipt["proposal"]["label"],
        }
        event_id = uuid.uuid5(
            SOCIETY_NAMESPACE,
            f"{previous_state['society_id']}:{next_state['tick']}:{order}:"
            f"{society_state_sha256(event_document)}",
        )
        result.append(
            SocietyEvent(
                event_id,
                next_state["tick"],
                DECISION_EVENT_KIND,
                uuid.UUID(disposition.subject_id),
                None,
                event_document,
            )
        )
    return tuple(result)
