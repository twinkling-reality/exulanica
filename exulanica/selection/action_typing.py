"""The Companion planner's typed actions: a draft or a client's request read back into typed steps,
and what each step needs before it can be prepared.

:func:`_typed_from_draft` reads each drafted label back through the list it was offered from, so a
slot holds only an option the world read listed. :func:`_typed_from_request` checks the typed
actions a client sends back (a clarification answered, or the rest of a compound request) against
the read each value must come from, as any direct body is checked. A step that needs something
neither the draft nor the page supplied comes back as one clarification (:func:`_requirements`),
and a step the capability read says cannot run is refused with the read's own code
(:func:`_availability`). :mod:`exulanica.selection.action_plan` prepares the typed steps.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from exulanica.selection import action_budget, action_minds, action_things
from exulanica.selection.action_drafting import _offered
from exulanica.selection.action_vocabulary import (
    _DRAFT_ACTS,
    _HANDS,
    _MATRIX,
    ACTION_REFUSALS,
    CLARIFICATIONS,
    WorldEditOperation,
)
from exulanica.selection.action_world import _Choice, _Context, _World
from exulanica.selection.proposal import RefusalCode
from exulanica.world.minds_budget import MindsBudgetRefused, budget_figures

# -- typed actions, and what each needs before it can be prepared -------------------------------


@dataclass(frozen=True, slots=True)
class _Action:
    """One typed change: an operation and the option each slot resolved to (None: not needed).

    A thing to add names its kind, the id minted for it when the plan was made and what it goes
    beside (``near``: ``thing:``, ``object:`` or ``being:`` and an id, or None for the pointed
    spot). A being asked to act names the act, the being and the place; asked for a hands act, the
    thing (``thing_id``, its placed id) and, to give or take, the other being (``with_id``)."""

    operation: WorldEditOperation
    asset_key: str | None = None
    object_id: str | None = None
    arrangement_key: str | None = None
    arrangement_version: int | None = None
    kind: str | None = None
    kind_version: int | None = None
    thing_id: str | None = None
    near: str | None = None
    act: str | None = None
    subject_id: str | None = None
    target_id: str | None = None
    with_id: str | None = None
    #: For new pieces: the kinds asked by key, and whether the request named them (with none named,
    #: the world's things are asked, and only those its look dresses with a default or nothing).
    kinds: tuple[str, ...] = ()
    named: bool = False
    #: For a mind: whom it is chosen for (``being:`` and an id, or a group the society holds:
    #: ``everyone``, ``kind:`` or ``role:`` and a key) and which (``routine``, or ``model:``, a
    #: provider, ``/`` and a model id).
    whom: str | None = None
    mind: str | None = None
    #: For a budget: the dollars (a decimal string of six places) and the model decisions the
    #: world's minds may come to in any hour of real time, which of the two the person's words
    #: named (the other is kept as the world has it), and what to ask first where the words gave
    #: no figure or one over another span (never part of the document).
    usd_per_hour: str | None = None
    decisions_per_hour: int | None = None
    figures_named: tuple[str, ...] = ()
    budget_question: str | None = None

    def document(self) -> dict[str, Any]:
        if self.operation is WorldEditOperation.SET_MINDS_BUDGET:
            return {
                "operation": self.operation.value,
                "usd_per_hour": self.usd_per_hour,
                "decisions_per_hour": self.decisions_per_hour,
                "figures_named": list(self.figures_named),
            }
        if self.operation in (WorldEditOperation.MOVE_THING, WorldEditOperation.REMOVE_THING):
            return {"operation": self.operation.value, "thing_id": self.thing_id}
        if self.operation in (WorldEditOperation.PLAY_BEING, WorldEditOperation.GIVE_BACK):
            return {"operation": self.operation.value, "subject_id": self.subject_id}
        if self.operation is WorldEditOperation.CHOOSE_MIND:
            return {"operation": self.operation.value, "whom": self.whom, "mind": self.mind}
        if self.operation is WorldEditOperation.REQUEST_PIECES:
            return {
                "operation": self.operation.value,
                "kinds": list(self.kinds),
                "named": self.named,
            }
        if self.operation is WorldEditOperation.PLACE_THING:
            return {
                "operation": self.operation.value,
                "kind": self.kind,
                "kind_version": self.kind_version,
                "thing_id": self.thing_id,
                "near": self.near,
            }
        if self.operation is WorldEditOperation.DIRECT_THING and self.act in _HANDS:
            return {
                "operation": self.operation.value,
                "act": self.act,
                "subject_id": self.subject_id,
                "thing_id": self.thing_id,
                "with_id": self.with_id,
            }
        if self.operation is WorldEditOperation.DIRECT_THING:
            return {
                "operation": self.operation.value,
                "act": self.act,
                "subject_id": self.subject_id,
                "target_id": self.target_id,
            }
        return {
            "operation": self.operation.value,
            "asset_key": self.asset_key,
            "object_id": self.object_id,
            "arrangement_key": self.arrangement_key,
            "arrangement_version": self.arrangement_version,
        }


@dataclass(slots=True)
class _Verdict:
    """What validation decided: typed actions, or the one clarification or refusal to answer."""

    actions: list[_Action] = field(default_factory=list)
    clarification: dict[str, Any] | None = None
    refusal: dict[str, Any] | None = None


def _refusal(
    code: str,
    detail: str,
    *,
    operation: str | None = None,
    capability: Mapping[str, Any] | None = None,
    step: int | None = None,
    alternatives: Sequence[str] = (),
) -> dict[str, Any]:
    assert code in ACTION_REFUSALS or code in {item.value for item in RefusalCode}, code
    return {
        "code": code,
        "detail": detail,
        "step": step,
        "operation": operation,
        "capability": None if capability is None else dict(capability),
        "alternatives": list(alternatives),
    }


def _by_label(choices: Sequence[_Choice], labels: Sequence[str]) -> list[_Choice]:
    found = {choice.label: choice for choice in choices}
    return [found[label] for label in dict.fromkeys(labels) if label in found]


def _names_other_steps_say(steps: Sequence[Mapping[str, Any]], world: _World) -> tuple[str, ...]:
    """The names code holds for the options a draft's steps name, but for its budget steps: each
    option's title as the form listed it, up to its first bracket or comma (the form adds a count
    or a note after those), and a group's own label for its kind or its role. They are looked up
    by the labels the draft named, in the lists the form was made from; no word a model wrote is
    among them."""
    # The budget's own options (an amount, nothing, the default) are never names, whichever step
    # a draft puts them in.
    budgets = {choice.label for choice in world.amounts}
    offered = {choice.label: choice for choice in _offered(world) if choice.label not in budgets}
    groups = {group.value: group for group in world.society_groups}
    names: list[str] = []
    for step in steps:
        if str(step["operation"]) == WorldEditOperation.SET_MINDS_BUDGET.value:
            continue
        for label in step.get("options") or ():
            choice = offered.get(label)
            if choice is None:
                continue
            names.append(choice.title.partition(" (")[0].partition(",")[0])
            group = groups.get(choice.value)
            if group is not None:
                names.extend(group.labels)
    return tuple(dict.fromkeys(name.strip() for name in names if name.strip()))


def _typed_from_draft(
    steps: Sequence[Mapping[str, Any]], world: _World, utterance: str | None = None
) -> _Verdict:
    """The drafted steps as typed actions, each slot read back through the option it names.

    Every label is looked up in the list it was offered from; the form's enums make any other value
    impossible, and this lookup is what makes it impossible here too. Candidates are kept for a
    clarification; a slot with none is decided per operation.

    Adding something is read by the list its label came from: a kind of object is placed as the
    reviewed object it is, and a kind of thing as a thing, whichever of the two operations names
    it, since the label alone says which. A thing to add is minted its id here, so a later step of
    the same request can name it before it exists; a step naming two kinds of thing, one of them a
    kind an earlier step adds, adds the other beside it.
    """
    verdict = _Verdict()
    actions: list[_Action] = []
    if utterance is not None and world.minds is not None:
        # A sentence that sets a budget and asks for something else says the names of what the
        # other steps act on. Those names, as code holds them for the options the draft named,
        # may stand in the other steps' own clause of the sentence (``action_budget.shape_of``).
        names = _names_other_steps_say(steps, world)
        world = dataclasses.replace(
            world,
            said_amounts=action_budget.amounts(utterance, names),
            said_fixed=action_budget.stated(utterance, names),
            said_shape=action_budget.shape_of(utterance, names)[1],
        )
    #: Each step's slots that name options: the step, the slot and the options it could mean.
    slots: list[tuple[int, str, list[_Choice]]] = []
    undone = False
    #: Each kind of thing and kind of object an earlier step adds, for a later step to name.
    added_things: dict[str, str] = {}
    added_objects: set[str] = set()
    #: Who holds each thing once the earlier steps' hands acts are done, by its placed id.
    holding: dict[str, str | None] = {}
    #: Each mind chosen so far in this request: whom for and which.
    minds_chosen: list[tuple[str, str]] = []
    #: Each thing step's options as drafted, and what they were read as: a later step drafted with
    #: the same options means the same again (two lanterns by the well), not the first beside it.
    repeated: dict[tuple[str, ...], tuple[_Action, list[tuple[str, list[_Choice]]]]] = {}
    for step in steps:
        # A step's place among the typed actions: a step said twice is typed once.
        index = len(actions)
        drafted = str(step["operation"])
        labels = step.get("options") or ()
        if drafted in _HANDS:
            action, named = _hands_step(drafted, labels, world, added_things, holding)
            actions.append(action)
            slots += [(index, slot, found) for slot, found in named]
            continue
        if drafted == WorldEditOperation.REQUEST_PIECES.value:
            asked = {kind.value for kind in _by_label(world.kinds, labels)}
            placed = {choice.value for choice in _by_label(world.placed, labels)}
            read = world.things
            things = () if read is None else read.placed
            asked |= {
                str(item.kind)
                for item in things
                if f"thing:{item.thing_id}" in placed and item.kind
            }
            named = bool(asked)
            if not named:
                asked = {str(item.kind) for item in things if item.kind}
            actions.append(
                _Action(WorldEditOperation.REQUEST_PIECES, kinds=tuple(sorted(asked)), named=named)
            )
            continue
        if drafted == WorldEditOperation.CHOOSE_MIND.value:
            action, named = _mind_step(labels, world, utterance)
            if _mind_already_chosen(action, named, minds_chosen, world):
                # The same choice again, or one being of a group an earlier step of this request
                # chose the same mind for: said once.
                continue
            if action.whom is not None and action.mind is not None:
                minds_chosen.append((action.whom, action.mind))
            actions.append(action)
            slots += [(index, slot, found) for slot, found in named]
            continue
        if drafted == WorldEditOperation.SET_MINDS_BUDGET.value:
            if any(a.operation is WorldEditOperation.SET_MINDS_BUDGET for a in actions):
                # One request sets one budget: its figures are the sentence's, read once.
                continue
            action, named = _budget_step(labels, world)
            actions.append(action)
            slots += [(index, slot, found) for slot, found in named]
            continue
        if drafted == WorldEditOperation.PLAY_BEING.value:
            named_kinds = {kind.value for kind in _by_label(world.kinds, labels)}
            beings = _by_label(world.beings, labels) or _of_kinds(world.beings, named_kinds, world)
            actions.append(
                _Action(
                    WorldEditOperation.PLAY_BEING,
                    subject_id=beings[0].value if beings else None,
                )
            )
            slots.append((index, "subject_id", beings))
            continue
        if drafted == WorldEditOperation.GIVE_BACK.value:
            # Whom the person plays is read from the society when the step is prepared.
            actions.append(_Action(WorldEditOperation.GIVE_BACK))
            continue
        if drafted in _DRAFT_ACTS:
            named_kinds = {kind.value for kind in _by_label(world.kinds, labels)}
            beings = _by_label(world.beings, labels) or _of_kinds(world.beings, named_kinds, world)
            places = _by_label(world.places, labels) or _places_of(
                [*_by_label(world.placed, labels), *_of_kinds(world.placed, named_kinds, world)],
                world,
            )
            actions.append(
                _Action(
                    WorldEditOperation.DIRECT_THING,
                    act=_DRAFT_ACTS[drafted],
                    subject_id=beings[0].value if beings else None,
                    target_id=places[0].value if places else None,
                )
            )
            slots += [(index, "subject_id", beings), (index, "target_id", places)]
            continue
        operation = WorldEditOperation(drafted)
        if operation is WorldEditOperation.OTHER:
            verdict.refusal = _refusal(
                "action_not_offered",
                "the request asks for a change the Companion does not prepare",
                step=index,
            )
            return verdict
        if operation is WorldEditOperation.UNDO_LAST_EDIT:
            # One request takes back the newest edit, once. A draft has been measured padding an
            # undo out to the form's three steps, and a plan that took back edits nobody named is
            # not offered whatever the words were; asking again takes back the next one.
            if undone:
                verdict.refusal = _refusal(
                    "action_not_offered",
                    "one request takes back one change; ask again to take back another",
                    step=index,
                )
                return verdict
            undone = True
        if operation in (WorldEditOperation.PLACE_OBJECT, WorldEditOperation.PLACE_THING):
            kinds = _by_label(world.kinds, labels)
            candidates = [
                asset
                for asset in _by_label(world.assets, labels)
                if asset.value not in added_objects
            ] or _by_label(world.assets, labels)
            # The list a label came from says what is added; where a step names both, the
            # operation it was drafted as says which.
            if kinds and (operation is WorldEditOperation.PLACE_THING or not candidates):
                again = repeated.get(tuple(labels))
                if again is None:
                    action, named = _thing_to_add(
                        index, kinds, labels, world, added_things, added_objects, utterance
                    )
                    repeated[tuple(labels)] = (action, named)
                else:
                    first, named = again
                    action = dataclasses.replace(
                        first,
                        thing_id=action_things.minted_thing_id(
                            world.version_id, world.state_sha256, index, str(first.kind)
                        ),
                    )
                if action.kind is not None:
                    added_things[action.kind] = str(action.thing_id)
                actions.append(action)
                slots += [(index, slot, found) for slot, found in named]
                continue
            if not candidates:
                verdict.refusal = _refusal(
                    "not_in_catalogue",
                    "the request names no kind the reviewed catalogue holds",
                    step=index,
                )
                return verdict
            actions.append(_Action(WorldEditOperation.PLACE_OBJECT, asset_key=candidates[0].value))
            added_objects.add(candidates[0].value)
            slots.append((index, "asset_key", candidates))
        elif operation in (WorldEditOperation.MOVE_OBJECT, WorldEditOperation.REMOVE_OBJECT):
            # Read by the list a label came from: a placed thing, or a being an author placed, is
            # moved or removed by the things routes, an object by the objects'.
            things = _placed_things_named(labels, world)
            if things:
                actions.append(
                    _Action(
                        WorldEditOperation.MOVE_THING
                        if operation is WorldEditOperation.MOVE_OBJECT
                        else WorldEditOperation.REMOVE_THING,
                        thing_id=things[0].value,
                    )
                )
                slots.append((index, "thing_id", things))
                continue
            candidates = _by_label(world.objects, labels)
            actions.append(
                _Action(operation, object_id=candidates[0].value if candidates else None)
            )
            slots.append((index, "object_id", candidates))
        elif operation is WorldEditOperation.PLACE_ARRANGEMENT:
            candidates = _by_label(world.arrangements, labels)
            if not candidates:
                verdict.refusal = _refusal(
                    "not_in_catalogue",
                    "the request names no published arrangement",
                    step=index,
                )
                return verdict
            key = candidates[0].value
            actions.append(
                _Action(
                    operation,
                    arrangement_key=key,
                    arrangement_version=world.arrangement_versions[key],
                )
            )
            slots.append((index, "arrangement_key", candidates))
        else:
            actions.append(_Action(operation))
    pieces = [
        index
        for index, action in enumerate(actions)
        if action.operation is WorldEditOperation.REQUEST_PIECES
    ]
    if pieces and len(actions) > 1:
        verdict.refusal = _refusal(
            "action_not_offered",
            "new pieces of the world's look are asked for on their own, apart from other changes",
            step=pieces[0],
        )
        return verdict
    verdict.actions = actions
    for index, slot, candidates in slots:
        if len(candidates) > 1:
            verdict.clarification = _clarification(
                _AMBIGUOUS[slot], index, slot, actions, candidates=candidates
            )
            return verdict
    return verdict


def _mind_already_chosen(
    action: _Action,
    named: Sequence[tuple[str, Sequence[_Choice]]],
    chosen: Sequence[tuple[str, str]],
    world: _World,
) -> bool:
    """Whether an earlier step of the same request already chose this mind for everything this
    step could mean: the same being or group, or a group that holds the being."""
    if action.mind is None:
        return False
    candidates = next((list(found) for slot, found in named if slot == "whom"), [])
    if not candidates:
        return False
    groups = {group.value: frozenset(group.subjects) for group in world.society_groups}

    def covered(whom: str) -> bool:
        for earlier, mind in chosen:
            if mind != action.mind:
                continue
            if earlier == whom:
                return True
            if whom.startswith("being:") and whom.removeprefix("being:") in groups.get(earlier, ()):
                return True
        return False

    return any(covered(choice.value) for choice in candidates)


def _placed_things_named(labels: Sequence[str], world: _World) -> list[_Choice]:
    """The placed things a move or a removal names, each by its placed id: a listed thing, or a
    listed being an author placed here (the society states the thing it was placed as). A being
    nobody placed, one of the world's own people or a visitor, is no placed thing."""
    named_kinds = {kind.value for kind in _by_label(world.kinds, labels)}
    found = [
        _Choice(label=choice.label, value=choice.value.removeprefix("thing:"), title=choice.title)
        for choice in (
            *_by_label(world.placed, labels),
            # A kind of thing named stands for the things of that kind standing here.
            *_of_kinds(world.placed, named_kinds, world),
        )
    ]
    society = None if world.things is None else world.things.society
    if society is not None:
        placed_as = {
            str(person["id"]): str(person["placed_id"])
            for person in society.state.get("inhabitants", ())
            if person.get("placed_id")
        }
        found += [
            _Choice(label=being.label, value=placed_as[being.value], title=being.title)
            for being in (
                *_by_label(world.beings, labels),
                *_of_kinds(world.beings, named_kinds, world),
            )
            if being.value in placed_as
        ]
        # A place a thing provides, named in its stead, is that thing.
        titles = {choice.value: choice.title for choice in world.placed}
        named_places = {choice.value for choice in _by_label(world.places, labels)}
        found += [
            _Choice(
                label=place.target_id,
                value=str(place.thing_id),
                title=titles.get(f"thing:{place.thing_id}", place.title),
            )
            for place in society.places
            if place.target_id in named_places and place.thing_id is not None
        ]
    distinct: dict[str, _Choice] = {}
    for choice in found:
        distinct.setdefault(choice.value, choice)
    return list(distinct.values())


def _mind_step(
    labels: Sequence[str], world: _World, utterance: str | None = None
) -> tuple[_Action, list[tuple[str, list[_Choice]]]]:
    """A drafted choice of a mind, read back: whom it is for and which mind, each with every
    option the words could mean. A kind of thing named stands for the group of that kind here; a
    being named beside a group that holds nobody else is that being, said twice.

    The person's own words are held to what the drafter named, where the plan was made from words
    (``utterance``): a kind's or a role's group counts only when its own label is in them, so a
    group this world does not hold is asked about with the groups it does hold, never replaced by
    another; and a model is the one their words name by its served name
    (:func:`exulanica.selection.action_minds.said_minds`), so a word several offered models share
    is asked about among them, and a draft naming a model the words name none of is asked about
    among every mind. A model the draft names whose name the words say in full stands, so a
    request giving two groups a model each is read a step at a time. Their own routine is the
    drafter's reading alone: it asks nobody."""
    named_kinds = {kind.value for kind in _by_label(world.kinds, labels)}
    whom = [
        *(
            _Choice(label=being.label, value=f"being:{being.value}", title=being.title)
            for being in _by_label(world.beings, labels)
        ),
        *_by_label(world.groups, labels),
        *(
            group
            for group in world.groups
            if group.value.removeprefix("kind:") in named_kinds and group.value.startswith("kind:")
        ),
    ]
    if utterance is not None:
        # Every label a group answers to: a kind's, a role's, or both where they name the same
        # beings. Everyone has one only where a role names them all.
        words = {group.value: group.labels for group in world.society_groups}
        members = {group.value: frozenset(group.subjects) for group in world.society_groups}

        def names_group(value: str) -> bool:
            return any(action_minds.said(label, utterance) for label in words.get(value, ()))

        whom = [
            choice
            for choice in whom
            if choice.value == action_minds.EVERYONE
            or not words.get(choice.value)
            or names_group(choice.value)
        ]
        # The groups the person's own words name, by a kind's or a role's label.
        spoken_groups = [choice for choice in world.groups if names_group(choice.value)]
        if spoken_groups:
            kept: list[_Choice] = []
            for choice in whom:
                if choice.value.startswith("being:"):
                    being = choice.value.removeprefix("being:")
                    holding = [group for group in spoken_groups if being in members[group.value]]
                    if not holding:
                        # The words name a group this being is not in: the draft's being is not
                        # what they asked for.
                        continue
                    kept.append(choice)
                    # One of several the words' group holds: that one, or all of them, is asked.
                    kept += [group for group in holding if len(members[group.value]) > 1]
                elif choice.value == action_minds.EVERYONE:
                    # Everyone drafted where the words name another group: which is asked. Where
                    # the one group they name is everyone, by a role all of them hold, it stands.
                    kept += [
                        choice,
                        *(group for group in spoken_groups if group.value != choice.value),
                    ]
                else:
                    kept.append(choice)
            whom = kept or spoken_groups
        else:
            # No kind's or role's label in the words: a being stands only by its own name in them
            # (who is meant by "him" or "that one" is the person's to say).
            names = (
                {}
                if world.things is None or world.things.society is None
                else {
                    f"being:{being.id}": being.display_name for being in world.things.society.beings
                }
            )
            whom = [
                choice
                for choice in whom
                if not choice.value.startswith("being:")
                or action_minds.said(names.get(choice.value, ""), utterance)
            ]
    seen: list[frozenset[str]] = []
    distinct: list[_Choice] = []
    for choice in whom:
        subjects = action_minds.subjects_of(choice.value, world.society_groups)
        held = frozenset(subjects or (choice.value,))
        if held not in seen:
            seen.append(held)
            distinct.append(choice)
    minds = _by_label(world.mind_choices, labels)
    drafted_models = [choice for choice in minds if choice.value != action_minds.ROUTINE]
    if utterance is not None and world.minds is not None and drafted_models:
        offered = {
            action_minds.mind_value(model.provider, model.model_id): model
            for model in world.minds.models()
        }
        spoken = {
            action_minds.mind_value(model.provider, model.model_id)
            for model in action_minds.said_minds(utterance, tuple(offered.values()))
        }
        routine = [choice for choice in minds if choice.value == action_minds.ROUTINE]
        in_full = [
            choice
            for choice in drafted_models
            if action_minds.said_in_full(utterance, offered[choice.value])
        ]
        if in_full:
            minds = [*routine, *in_full]
        elif not spoken:
            # The words name no offered model: their own routine if the draft read that too, else
            # which mind is the person's to say.
            minds = routine
        elif len(spoken) == 1 and spoken <= {choice.value for choice in drafted_models}:
            minds = [*routine, *(c for c in drafted_models if c.value in spoken)]
        else:
            wanted = spoken | (
                {choice.value for choice in drafted_models} if len(spoken) == 1 else set()
            )
            minds = [*routine, *(c for c in world.mind_choices if c.value in wanted)]
    action = _Action(
        WorldEditOperation.CHOOSE_MIND,
        whom=distinct[0].value if distinct else None,
        mind=minds[0].value if minds else None,
    )
    return action, [("whom", distinct), ("mind", minds)]


def _budget_step(
    labels: Sequence[str], world: _World
) -> tuple[_Action, list[tuple[str, list[_Choice]]]]:
    """A drafted budget for the world's minds, read back. Its figures are the amounts code read
    in the person's sentence (``world.said_amounts``), whatever the draft named among them: the
    drafter says that a budget is asked for, and which of the two budgets with no figure, which
    is planned only where the sentence's own words state it too (``world.said_fixed``) and code
    read no amount. Everything else is asked: no figure, an amount the words do not state
    plainly, two amounts of one kind, an amount over a span that is not an hour, a figure the
    budget's record cannot hold (:func:`exulanica.selection.action_budget.resolve`)."""
    operation = WorldEditOperation.SET_MINDS_BUDGET
    if world.minds is None:
        return _Action(operation, budget_question="budget_required"), []
    held = world.minds.budget()
    fixed = [
        choice.value
        for choice in _by_label(world.amounts, labels)
        if choice.value in (action_budget.NOTHING, action_budget.DEFAULT)
    ]
    resolved = action_budget.resolve(
        world.said_amounts,
        fixed,
        held["now"],
        held["default"],
        world.said_fixed,
        world.said_shape,
    )
    if resolved.usd_per_hour is not None and resolved.decisions_per_hour is not None:
        try:
            budget_figures(resolved.usd_per_hour, resolved.decisions_per_hour)
        except MindsBudgetRefused:
            # A figure the budget's record cannot hold is asked for here, not refused at send.
            return _Action(operation, budget_question="budget_required"), []
    action = _Action(
        operation,
        usd_per_hour=resolved.usd_per_hour,
        decisions_per_hour=resolved.decisions_per_hour,
        figures_named=resolved.named,
        budget_question=resolved.question if resolved.slot is None else None,
    )
    if resolved.slot is None:
        return action, []
    candidates = [
        _Choice(label=value, value=value, title=action_budget.figure_title(resolved.slot, value))
        for value in resolved.candidates
    ]
    return action, [(resolved.slot, candidates)]


def _places_of(named: Sequence[_Choice], world: _World) -> list[_Choice]:
    """The listed places that belong to the listed things a walk or a use names: a person sends a
    being to the well, and the well is gone to at its place. Several are asked about by name."""
    society = None if world.things is None else world.things.society
    if society is None or not named:
        return []
    things = {choice.value.removeprefix("thing:") for choice in named}
    owned = {place.target_id for place in society.places if place.thing_id in things}
    return [choice for choice in world.places if choice.value in owned]


#: The clarification a slot asks when the words could mean more than one listed option.
_AMBIGUOUS: Final = {
    "asset_key": "asset_ambiguous",
    "object_id": "object_ambiguous",
    "arrangement_key": "arrangement_ambiguous",
    "kind": "kind_ambiguous",
    "near": "anchor_ambiguous",
    "subject_id": "being_ambiguous",
    "target_id": "place_ambiguous",
    "thing_id": "thing_ambiguous",
    "whom": "whom_ambiguous",
    "mind": "mind_ambiguous",
    "usd_per_hour": "budget_ambiguous",
    "decisions_per_hour": "budget_ambiguous",
}


def _anchors(world: _World) -> tuple[_Choice, ...]:
    """What a thing may be put beside, each valued as a typed action's ``near`` names it."""
    return (
        *world.placed,
        *(dataclasses.replace(choice, value=f"object:{choice.value}") for choice in world.objects),
        *(dataclasses.replace(choice, value=f"being:{choice.value}") for choice in world.beings),
    )


def _thing_to_add(
    index: int,
    kinds: Sequence[_Choice],
    labels: Sequence[str],
    world: _World,
    added_things: Mapping[str, str],
    added_objects: set[str],
    utterance: str | None = None,
) -> tuple[_Action, list[tuple[str, list[_Choice]]]]:
    """A place step naming kinds of thing: the kind it adds, and what it goes beside.

    One kind named is the one added. Of two or more, those an earlier step adds are what it goes
    beside, when exactly one other is left to add; of two with no earlier step's, the one that
    already stands in the world names what the other goes beside (a knight by the well, where a
    well stands), every listed thing or being of that kind, so two of them are asked about by name.
    Where both of two kinds stand in the world (a knight by the well, where a knight and a well
    stand), the person's own words decide, where the plan was made from words (``utterance``): the
    kind they say right after "by", "beside", "near" or "next to" is what the other goes beside.
    Otherwise the kind is asked about. Beside that, what it goes beside is any listed thing, object
    or being the step names, or a kind of object an earlier step adds (the newest of that kind the
    Companion placed)."""
    anchors = _by_label(_anchors(world), labels)
    if len(kinds) == 1:
        to_add = list(kinds)
    else:
        later = [kind for kind in kinds if kind.value not in added_things]
        earlier = [kind for kind in kinds if kind.value in added_things]
        standing = [kind for kind in later if _standing(kind.value, world)]
        if len(later) == 1 and earlier:
            to_add = later
            anchors += [
                dataclasses.replace(kind, value=f"thing:{added_things[kind.value]}")
                for kind in earlier
            ]
        elif not earlier and len(later) == 2 and len(standing) == 1:
            to_add = [kind for kind in later if kind.value != standing[0].value]
            anchors += _standing(standing[0].value, world)
        elif not earlier and len(later) == 2 and len(standing) == 2 and utterance is not None:
            beside = [kind for kind in later if _said_beside(kind.title, utterance)]
            if len(beside) == 1:
                to_add = [kind for kind in later if kind.value != beside[0].value]
                anchors += _standing(beside[0].value, world)
            else:
                to_add = list(kinds)
        else:
            to_add = list(kinds)
    # A thing named both by its label and by its kind is one place to go beside.
    anchors = list({anchor.value: anchor for anchor in anchors}.values())
    anchors += [
        dataclasses.replace(asset, value=f"newest-object:{asset.value}")
        for asset in _by_label(world.assets, labels)
        if asset.value in added_objects
    ]
    kind = to_add[0].value
    offered = world.things.kind(kind) if world.things is not None else None
    action = _Action(
        WorldEditOperation.PLACE_THING,
        kind=kind,
        kind_version=None if offered is None else offered.version,
        thing_id=action_things.minted_thing_id(world.version_id, world.state_sha256, index, kind),
        near=anchors[0].value if anchors else None,
    )
    return action, [("kind", list(to_add)), ("near", list(anchors))]


#: The words that, said right before a kind's label, make it what a thing goes beside.
_BESIDE_WORDS: Final = ("by", "beside", "near", "next to")
_ARTICLES: Final = ("", "the ", "a ", "an ")


def _said_beside(label: str, utterance: str) -> bool:
    """Whether the person's words put something beside the kind ``label`` names: one of "by",
    "beside", "near" or "next to", then the label, with or without an article ("by the well",
    "next to a well"). The label is matched as :func:`exulanica.selection.action_minds.said`
    matches one, whatever follows it ("near the wells")."""
    return any(
        action_minds.said(f"{word} {article}{label}", utterance)
        for word in _BESIDE_WORDS
        for article in _ARTICLES
    )


def _of_kinds(choices: Sequence[_Choice], kinds: set[str], world: _World) -> list[_Choice]:
    """The listed beings or placed things, of ``choices``, whose kind a step names by its key: a
    drafter may say knight for the knight that stands in the world."""
    read = world.things
    if not kinds or read is None:
        return []
    values = {f"thing:{item.thing_id}" for item in read.placed if item.kind in kinds}
    if read.society is not None:
        values |= {being.id for being in read.society.beings if being.kind in kinds}
    return [choice for choice in choices if choice.value in values]


def _standing(kind: str, world: _World) -> list[_Choice]:
    """The listed things and beings of ``kind`` that already stand in the world, as a step may go
    beside them."""
    read = world.things
    if read is None:
        return []
    values = {f"thing:{item.thing_id}" for item in read.placed if item.kind == kind}
    if read.society is not None:
        values |= {f"being:{being.id}" for being in read.society.beings if being.kind == kind}
    return [choice for choice in _anchors(world) if choice.value in values]


def _things_held(world: _World) -> tuple[_Choice, ...]:
    """The listed things a hands step may name, each valued by its placed id."""
    return tuple(
        dataclasses.replace(choice, value=choice.value.removeprefix("thing:"))
        for choice in world.placed
    )


def _holder(world: _World, holding: Mapping[str, str | None], placed_id: str) -> str | None:
    """Who holds a thing once this plan's earlier hands acts are done, else who holds it now."""
    if placed_id in holding:
        return holding[placed_id]
    society = None if world.things is None else world.things.society
    if society is None:
        return None
    return action_things.holder(society, action_things.society_thing_id(world.world_id, placed_id))


def _hands_step(
    act: str,
    labels: Sequence[str],
    world: _World,
    added_things: Mapping[str, str],
    holding: dict[str, str | None],
) -> tuple[_Action, list[tuple[str, list[_Choice]]]]:
    """A hands step: the being asked, the thing and, to give or take, the other being.

    The thing is a listed thing, or for a listed kind the thing of that kind an earlier step of
    this request adds (by the id it was minted), else the listed things of that kind. A put-down
    naming no thing is of what the being holds. Which being holds the thing is read from the
    society, or from what the earlier steps have them do, never from the order the labels came in:
    the holder gives, is taken from, and puts down. What the step does is then held for the steps
    after it."""
    beings = _by_label(world.beings, labels)
    things = _by_label(_things_held(world), labels)
    read = world.things
    kinds = {} if read is None else {item.thing_id: item.kind for item in read.placed}
    for kind in _by_label(world.kinds, labels):
        if kind.value in added_things:
            things.append(dataclasses.replace(kind, value=added_things[kind.value]))
        else:
            things += [
                c
                for c in _things_held(world)
                if kinds.get(c.value) == kind.value and c not in things
            ]
    if not things and act == "put_down" and len(beings) == 1:
        things = [
            c for c in _things_held(world) if _holder(world, holding, c.value) == beings[0].value
        ]
    thing = things[0].value if things else None
    held_by = None if thing is None else _holder(world, holding, thing)
    named = [being.value for being in beings]
    subject: str | None
    other: str | None = None
    if act not in ("give", "take"):
        subject = named[0] if named else held_by if act == "put_down" else None
    elif len(named) == 2:
        # The holder gives, and is the one taken from, whichever order the two came in; where
        # neither holds it, the order is all there is.
        first, second = named
        if held_by == (second if act == "give" else first):
            first, second = second, first
        subject, other = first, second
    elif len(named) == 1 and held_by is not None and held_by != named[0]:
        subject, other = (held_by, named[0]) if act == "give" else (named[0], held_by)
    else:
        subject = named[0] if named else held_by if act == "give" else None
        other = held_by if act == "take" and subject != held_by else None
    if thing is not None and subject is not None:
        holding[thing] = None if act == "put_down" else other if act == "give" else subject
    action = _Action(
        WorldEditOperation.DIRECT_THING,
        act=act,
        subject_id=subject,
        thing_id=thing,
        with_id=other,
    )
    deciding = beings if act not in ("give", "take") or len(beings) > 2 else []
    return action, [("subject_id", deciding), ("thing_id", things)]


def _clarification(
    code: str,
    step: int,
    slot: str | None,
    actions: Sequence[_Action],
    *,
    candidates: Sequence[_Choice] = (),
) -> dict[str, Any]:
    """What to ask, with the typed actions as drafted and the slot left open.

    The answer comes back to :func:`prepare_action` as typed actions with the slot filled; it is
    validated there as any direct body is, so this carries nothing the server must trust.
    """
    assert code in CLARIFICATIONS
    open_actions = []
    for index, action in enumerate(actions):
        document = action.document()
        if index == step and slot:
            document[slot] = None
            if slot == "arrangement_key":
                document["arrangement_version"] = None
            if slot == "kind":
                document["kind_version"] = None
        open_actions.append(document)
    return {
        "code": code,
        "step": step,
        "slot": slot or None,
        "candidates": [
            {"value": choice.value, "title": choice.title, "selected": choice.selected}
            for choice in candidates
        ],
        "actions": open_actions,
    }


def _typed_from_request(actions: Sequence[Mapping[str, Any]], world: _World) -> _Verdict:
    """Typed actions a client sent back (a clarification answered, or the rest of a compound
    request), each value checked against the read it must come from, as any direct body is."""
    verdict = _Verdict()
    for index, raw in enumerate(actions):
        operation = WorldEditOperation(raw["operation"])
        if operation in (WorldEditOperation.OTHER, WorldEditOperation.REQUEST_PIECES):
            # New pieces are planned from words alone, whole at once: never a later step.
            verdict.refusal = _refusal(
                "action_not_offered", "the Companion does not prepare this change", step=index
            )
            return verdict
        asset_key = raw.get("asset_key")
        object_id = raw.get("object_id")
        arrangement_key = raw.get("arrangement_key")
        if operation is WorldEditOperation.PLACE_OBJECT:
            if asset_key is not None and asset_key not in {c.value for c in world.assets}:
                verdict.refusal = _refusal(
                    "not_in_catalogue", "no placeable reviewed kind has that key", step=index
                )
                return verdict
            verdict.actions.append(_Action(operation, asset_key=asset_key))
        elif operation in (WorldEditOperation.MOVE_OBJECT, WorldEditOperation.REMOVE_OBJECT):
            # An object this version does not hold is left to the authority, which answers it the
            # way it answers a direct request: the preview reports it, never this module.
            verdict.actions.append(_Action(operation, object_id=object_id))
        elif operation is WorldEditOperation.PLACE_ARRANGEMENT:
            if arrangement_key is not None and arrangement_key not in world.arrangement_versions:
                verdict.refusal = _refusal(
                    "not_in_catalogue", "no published arrangement has that key", step=index
                )
                return verdict
            verdict.actions.append(
                _Action(
                    operation,
                    arrangement_key=arrangement_key,
                    arrangement_version=(
                        None
                        if arrangement_key is None
                        else world.arrangement_versions[arrangement_key]
                    ),
                )
            )
        elif operation in (WorldEditOperation.MOVE_THING, WorldEditOperation.REMOVE_THING):
            # A thing this version does not hold is the preparation's to say, by the route's code.
            verdict.actions.append(_Action(operation, thing_id=_text_or_none(raw.get("thing_id"))))
        elif operation in (WorldEditOperation.PLAY_BEING, WorldEditOperation.GIVE_BACK):
            verdict.actions.append(
                _Action(operation, subject_id=_text_or_none(raw.get("subject_id")))
            )
        elif operation is WorldEditOperation.CHOOSE_MIND:
            # A group this society does not hold and a mind the server does not offer are refused
            # here, as any direct body naming them is; a being that is not here is the route's
            # own check to refuse, when the step is prepared.
            whom = _text_or_none(raw.get("whom"))
            mind = _text_or_none(raw.get("mind"))
            if whom is not None and not (
                whom.startswith("being:")
                or action_minds.subjects_of(whom, world.society_groups) is not None
            ):
                verdict.refusal = _refusal(
                    "not_in_catalogue", "this world holds no such group of beings", step=index
                )
                return verdict
            if mind is not None and mind not in {choice.value for choice in world.mind_choices}:
                verdict.refusal = _refusal(
                    "not_in_catalogue", "no mind offered here has that name", step=index
                )
                return verdict
            verdict.actions.append(_Action(operation, whom=whom, mind=mind))
        elif operation is WorldEditOperation.SET_MINDS_BUDGET:
            # Figures a client sent back are checked as the budget route's body is; a figure
            # left open is asked for when the step's needs are read.
            usd = _text_or_none(raw.get("usd_per_hour"))
            decisions = raw.get("decisions_per_hour")
            if isinstance(decisions, str) and decisions.isascii() and decisions.isdigit():
                # A clarification's candidate comes back as the text it was offered as.
                decisions = int(decisions)
            try:
                checked_usd, checked_decisions = budget_figures(
                    "0" if usd is None else usd, 0 if decisions is None else decisions
                )
            except MindsBudgetRefused:
                verdict.refusal = _refusal(
                    "not_understood", "a budget is dollars and decisions an hour", step=index
                )
                return verdict
            named = raw.get("figures_named") or ()
            if named and world.minds is not None:
                # A figure the person did not name is kept "as it is": as the world has it when
                # this is read, not as it stood when the step was first made. A question answered
                # later, or a later step prepared again, then puts back nothing somebody set since.
                held = world.minds.budget()["now"]
                if "usd_per_hour" not in named and usd is not None:
                    checked_usd = Decimal(str(held["usd_per_hour"]))
                if "decisions_per_hour" not in named and decisions is not None:
                    checked_decisions = int(held["decisions_per_hour"])
            verdict.actions.append(
                _Action(
                    operation,
                    usd_per_hour=None if usd is None else action_budget.usd_text(checked_usd),
                    decisions_per_hour=None if decisions is None else checked_decisions,
                    figures_named=tuple(
                        figure for figure in action_budget.FIGURES if figure in named
                    ),
                )
            )
        elif operation is WorldEditOperation.PLACE_THING:
            typed = _thing_from_request(raw, world, index)
            if isinstance(typed, dict):
                verdict.refusal = typed
                return verdict
            verdict.actions.append(typed)
        elif operation is WorldEditOperation.DIRECT_THING:
            # A being, a place or a thing this society does not hold is left to the route's own
            # builder, which answers it the way it answers a direct request
            # (``unknown_inhabitant``, ``canonical_target_changed``, ``thing_gone``), when the step
            # is prepared.
            act = raw.get("act")
            if act not in action_things.DIRECT_ACTS and act not in _HANDS:
                verdict.refusal = _refusal(
                    "action_not_offered",
                    "a being is asked to go to a place, use it, or do something with its hands",
                    step=index,
                )
                return verdict
            hands = act in _HANDS
            verdict.actions.append(
                _Action(
                    operation,
                    act=str(act),
                    subject_id=_text_or_none(raw.get("subject_id")),
                    target_id=None if hands else _text_or_none(raw.get("target_id")),
                    thing_id=_text_or_none(raw.get("thing_id")) if hands else None,
                    with_id=_text_or_none(raw.get("with_id")) if hands else None,
                )
            )
        else:
            verdict.actions.append(_Action(operation))
    return verdict


def _text_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


#: What a typed thing step's ``near`` may name, by its prefix.
_NEAR_PREFIXES: Final = ("thing:", "object:", "being:", "newest-object:")


def _thing_from_request(
    raw: Mapping[str, Any], world: _World, index: int
) -> _Action | dict[str, Any]:
    """A typed thing step a client sent back, its kind checked against the kinds offered, its
    minted id against the shape minted here, and its ``near`` against the forms it may take; or the
    refusal. Whether what ``near`` names is still here is the preparation's to say."""
    kind = raw.get("kind")
    offered = None if kind is None or world.things is None else world.things.kind(str(kind))
    if kind is not None and offered is None:
        return _refusal("not_in_catalogue", "no kind of thing to add has that key", step=index)
    version = raw.get("kind_version")
    if offered is not None and version is not None and version != offered.version:
        return _refusal("not_in_catalogue", "that kind is offered at another version", step=index)
    thing_id = raw.get("thing_id")
    if thing_id is not None and (kind is None or not action_things.valid_minted_id(thing_id, kind)):
        return _refusal(
            "not_understood", "a thing to add carries the id its plan minted", step=index
        )
    near = raw.get("near")
    if near is not None and not (
        isinstance(near, str) and near.startswith(_NEAR_PREFIXES) and len(near) <= 300
    ):
        return _refusal("not_understood", "a thing goes beside something named", step=index)
    return _Action(
        WorldEditOperation.PLACE_THING,
        kind=None if offered is None else offered.key,
        kind_version=None if offered is None else offered.version,
        thing_id=None if thing_id is None else str(thing_id),
        near=None if near is None else str(near),
    )


def _requirements(
    actions: Sequence[_Action], context: _Context, world: _World
) -> dict[str, Any] | None:
    """The first thing a step needs that neither the draft nor the page supplied, as a question."""
    for index, action in enumerate(actions):
        operation = action.operation
        if operation is WorldEditOperation.PLACE_THING:
            if action.kind is None:
                return _clarification(
                    "kind_ambiguous", index, "kind", actions, candidates=world.kinds
                )
            if context.origin_role is None:
                return {
                    **_clarification("origin_role_required", index, None, actions),
                    "candidates": [
                        {"value": "fictional", "title": "", "selected": False},
                        {"value": "personal", "title": "", "selected": False},
                    ],
                }
            if action.near is None and context.placement is None:
                return _clarification("placement_required", index, None, actions)
            continue
        if operation is WorldEditOperation.PLAY_BEING:
            if action.subject_id is None:
                return _clarification(
                    "being_required", index, "subject_id", actions, candidates=world.beings
                )
            continue
        if operation in (WorldEditOperation.GIVE_BACK, WorldEditOperation.REMOVE_THING):
            continue
        if operation is WorldEditOperation.SET_MINDS_BUDGET:
            if action.budget_question is not None:
                return _budget_question(action.budget_question, index, actions, world)
            if action.usd_per_hour is None or action.decisions_per_hour is None:
                return _budget_question("budget_required", index, actions, world)
            continue
        if operation is WorldEditOperation.MOVE_THING:
            if context.placement is None:
                return _clarification("placement_required", index, None, actions)
            continue
        if operation is WorldEditOperation.CHOOSE_MIND:
            if action.whom is None:
                return _clarification(
                    "whom_required", index, "whom", actions, candidates=world.groups
                )
            if action.mind is None:
                return _clarification(
                    "mind_required", index, "mind", actions, candidates=world.mind_choices
                )
            continue
        if operation is WorldEditOperation.DIRECT_THING:
            if action.subject_id is None:
                return _clarification(
                    "being_required", index, "subject_id", actions, candidates=world.beings
                )
            if action.act in _HANDS:
                if action.thing_id is None:
                    return _clarification(
                        "thing_ambiguous",
                        index,
                        "thing_id",
                        actions,
                        candidates=_things_held(world),
                    )
                if action.act in ("give", "take") and action.with_id is None:
                    return _clarification(
                        "being_required", index, "with_id", actions, candidates=world.beings
                    )
                continue
            if action.target_id is None:
                return _clarification(
                    "place_required", index, "target_id", actions, candidates=world.places
                )
            continue
        if operation is WorldEditOperation.PLACE_OBJECT and action.asset_key is None:
            return _clarification(
                "asset_ambiguous", index, "asset_key", actions, candidates=world.assets
            )
        if (
            operation in (WorldEditOperation.MOVE_OBJECT, WorldEditOperation.REMOVE_OBJECT)
            and action.object_id is None
        ):
            return _clarification(
                "object_required", index, "object_id", actions, candidates=world.objects
            )
        if operation is WorldEditOperation.PLACE_ARRANGEMENT and action.arrangement_key is None:
            return _clarification(
                "arrangement_ambiguous",
                index,
                "arrangement_key",
                actions,
                candidates=world.arrangements,
            )
        adds = operation in (WorldEditOperation.PLACE_OBJECT, WorldEditOperation.PLACE_ARRANGEMENT)
        if adds and context.origin_role is None:
            return {
                **_clarification("origin_role_required", index, None, actions),
                "candidates": [
                    {"value": "fictional", "title": "", "selected": False},
                    {"value": "personal", "title": "", "selected": False},
                ],
            }
        if (
            operation in (WorldEditOperation.PLACE_OBJECT, WorldEditOperation.MOVE_OBJECT)
            and context.placement is None
        ):
            return _clarification("placement_required", index, None, actions)
        if operation is WorldEditOperation.PLACE_ARRANGEMENT and context.viewer is None:
            return _clarification("viewer_required", index, None, actions)
    return None


def _budget_question(
    code: str, index: int, actions: Sequence[_Action], world: _World
) -> dict[str, Any]:
    """What to ask about a budget whose figure the words left open, with the budget the world
    has now as the question's facts, so the page can say what a new figure would replace."""
    asked = _clarification(code, index, None, actions)
    if world.minds is not None:
        now = world.minds.budget()["now"]
        # Whole numbers both, as a question's facts are: the dollars in millionths.
        asked["facts"] = {
            "usd_per_hour_microusd": int(Decimal(str(now["usd_per_hour"])) * 1_000_000),
            "decisions_per_hour": int(now["decisions_per_hour"]),
        }
    return asked


def _availability(actions: Sequence[_Action], world: _World) -> dict[str, Any] | None:
    """The first step the capability read says cannot run, refused with the read's own code."""
    for index, action in enumerate(actions):
        refused = _descriptor_refusal(_MATRIX[action.operation].commit, world, step=index)
        if refused is not None:
            return refused
    return None


def _descriptor_refusal(
    operation: str, world: _World, *, step: int | None = None
) -> dict[str, Any] | None:
    """``operation`` refused with the capability read's own state and code, or None to run it."""
    descriptor = world.descriptor(operation)
    if descriptor is None:
        return _refusal(
            "action_not_offered",
            "this server states no capability for the operation",
            operation=operation,
            step=step,
        )
    state = descriptor.get("state")
    if state == "unsupported":
        code, detail = "action_unsupported", "this world never supports the operation"
    elif state in ("unavailable", "unknown"):
        code, detail = "action_unavailable", "the operation is not available here now"
    elif not descriptor.get("permitted", False):
        code, detail = "action_not_permitted", "the caller's grant does not hold the operation"
    else:
        return None
    return _refusal(code, detail, operation=operation, capability=descriptor, step=step)
