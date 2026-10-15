"""The Companion planner's preparation: each typed step as the exact request a direct client sends,
with its pins and the authority's own preview.

:func:`_prepared_step` builds a step's path values and bodies (:func:`_bodies`) and asks for its
preview by the preview route's own key, so the route decides from the caller's grant whether a
preview repository is opened at all. A thing step, whose route has no preview, runs that route's
own checks in process (:mod:`exulanica.selection.action_things`). A later step of a compound
request is typed now and prepared after the previous step's receipt (:func:`_pending_step`). The
``_with_*`` readers add to a world read what playing a being, a budget, minds and new pieces rest
on, with the descriptors of the routes no version descriptor states.
:mod:`exulanica.selection.action_plan` writes the plan document from the prepared steps.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.selection import action_budget, action_minds, action_things
from exulanica.selection.action_digests import _digest
from exulanica.selection.action_typing import _Action, _clarification
from exulanica.selection.action_vocabulary import (
    _HANDS,
    _MATRIX,
    BUDGET,
    MIND,
    PIECES,
    PLAY,
    PLAY_GIVE_BACK,
    Grant,
    Minds,
    Pieces,
    Play,
    Previewer,
    WorldEditOperation,
    _Row,
)
from exulanica.selection.action_world import _Choice, _Context, _plain, _World
from exulanica.world.arrangements import ArrangementRequest, preview_arrangement
from exulanica.world.composition_preview import (
    CompositionPlacement,
    CompositionRequest,
    ReviewedAssetSource,
    preview_composition,
)
from exulanica.world.errors import InvalidObjectData
from exulanica.world.object_edit_preview import (
    preview_object_move,
    preview_object_removal,
    preview_undo,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ObjectOrigin, Transform, validate_transform
from exulanica.world.placed_things import UNSCALED_MILLI, PlacedThing, ThingKindReference

# -- preparing a step: the exact request, its pins and the authority's preview ------------------


def _minted_object_id(world: _World, step: int, asset_key: str) -> str:
    """The id a placed object gets: the reviewed key and a digest of where it was planned.

    The version's ``edit_seq`` never repeats, so a later plan never reuses an undone object's id.
    """
    digest = hashlib.sha256(
        canonical_json(
            {
                "version_id": str(world.version_id),
                "edit_seq": world.edit_seq,
                "step": step,
                "asset_key": asset_key,
            }
        )
    ).hexdigest()
    return f"companion:{asset_key}:{digest[:12]}"


def _transform(value: Mapping[str, Any]) -> Transform:
    return Transform(
        int(value["x_mm"]),
        int(value["y_mm"]),
        int(value["z_mm"]),
        int(value["yaw_microradians"]),
        int(value["scale_milli"]),
    )


def _bodies(
    action: _Action, context: _Context, world: _World, step: int
) -> tuple[dict[str, str], dict[str, Any], dict[str, Any]]:
    """The path values, the commit body and the preview body of one step."""
    bind = {"version_id": str(world.version_id)}
    base = {"base_state_sha256": world.state_sha256}
    entry = {"saved_entry": context.edit_entry()}
    operation = action.operation
    if operation is WorldEditOperation.PLACE_OBJECT:
        assert action.asset_key is not None and context.placement is not None
        placement = {
            "subject_id": _minted_object_id(world, step, action.asset_key),
            "region_id": context.placement["region_id"],
            "transform": _plain(context.placement["transform"]),
            "origin_role": context.origin_role,
            "behaviour": None,
            "source_anchor": None,
        }
        preview = {
            **base,
            "source": {"kind": "reviewed_asset", "asset_key": action.asset_key},
            "placement": placement,
        }
        return bind, {**preview, **entry}, preview
    if operation is WorldEditOperation.MOVE_OBJECT:
        assert action.object_id is not None and context.placement is not None
        preview = {**base, "transform": _plain(context.placement["transform"])}
        return {**bind, "object_id": action.object_id}, {**preview, **entry}, preview
    if operation is WorldEditOperation.REMOVE_OBJECT:
        assert action.object_id is not None
        return {**bind, "object_id": action.object_id}, {**base, **entry}, dict(base)
    if operation is WorldEditOperation.UNDO_LAST_EDIT:
        return bind, {**base, **entry}, dict(base)
    assert operation is WorldEditOperation.PLACE_ARRANGEMENT
    assert action.arrangement_key is not None and context.viewer is not None
    preview = {
        **base,
        "arrangement_key": action.arrangement_key,
        "arrangement_version": action.arrangement_version,
        "viewer": _plain(context.viewer),
        "origin_role": context.origin_role,
    }
    return bind, {**preview, **entry}, preview


def _preview_document(
    repository: WorldObjectRepository, action: _Action, world: _World, preview: Mapping[str, Any]
) -> dict[str, Any]:
    """The document the step's preview route answers for this body, from the same function."""
    version_id = world.version_id
    base = str(preview["base_state_sha256"])
    operation = action.operation
    if operation is WorldEditOperation.PLACE_OBJECT:
        placement = preview["placement"]
        request = CompositionRequest(
            base_state_sha256=base,
            source=ReviewedAssetSource(str(preview["source"]["asset_key"])),
            placement=CompositionPlacement(
                subject_id=str(placement["subject_id"]),
                region_id=str(placement["region_id"]),
                transform=_transform(placement["transform"]),
                origin_role=str(placement["origin_role"]),
            ),
        )
        return preview_composition(repository, version_id, request).document()
    if operation is WorldEditOperation.MOVE_OBJECT:
        assert action.object_id is not None
        return preview_object_move(
            repository,
            version_id,
            action.object_id,
            _transform(preview["transform"]),
            base_state_sha256=base,
        ).document()
    if operation is WorldEditOperation.REMOVE_OBJECT:
        assert action.object_id is not None
        return preview_object_removal(
            repository, version_id, action.object_id, base_state_sha256=base
        ).document()
    if operation is WorldEditOperation.UNDO_LAST_EDIT:
        return preview_undo(repository, version_id, base_state_sha256=base).document()
    viewer = preview["viewer"]
    request_ = ArrangementRequest(
        base_state_sha256=base,
        key=str(preview["arrangement_key"]),
        version=int(preview["arrangement_version"]),
        viewer_x_mm=int(viewer["x_mm"]),
        viewer_z_mm=int(viewer["z_mm"]),
        viewer_yaw_microradians=int(viewer["yaw_microradians"]),
        origin_role=str(preview["origin_role"]),
        viewer_region_id=viewer.get("region_id"),
    )
    return preview_arrangement(repository, version_id, request_).document()


def _prepared_step(
    index: int,
    action: _Action,
    context: _Context,
    world: _World,
    previewer: Previewer,
) -> dict[str, Any]:
    """Step ``index`` with its exact request, pins and the authority's preview.

    The preview repository is asked for by the preview route's key, so the route decides from the
    caller's grant whether one is opened at all.
    """
    row = _MATRIX[action.operation]
    if action.operation is WorldEditOperation.REQUEST_PIECES:
        return _prepared_pieces_step(index, action, world)
    if action.operation is WorldEditOperation.CHOOSE_MIND:
        return _prepared_mind_step(index, action, world)
    if action.operation in (WorldEditOperation.MOVE_THING, WorldEditOperation.REMOVE_THING):
        return _prepared_thing_edit_step(index, action, context, world)
    if action.operation in (WorldEditOperation.PLAY_BEING, WorldEditOperation.GIVE_BACK):
        return _prepared_play_step(index, action, world)
    if action.operation is WorldEditOperation.SET_MINDS_BUDGET:
        return _prepared_budget_step(index, action, world)
    if row.preview is None:
        return _prepared_things_step(index, action, context, world)
    descriptor = world.descriptor(row.commit) or {}
    bind, body, preview_body = _bodies(action, context, world, index)
    with previewer(row.preview) as repository:
        if repository is None:
            # The route's own permission check refused the preview: the step is not permitted.
            refused = _step(
                index, action, row, world, "not_permitted", "action_not_permitted", bind
            )
            refused["permitted"] = False
            return refused
        document = _preview_document(repository, action, world, preview_body)
    blocked = document.get("blocked_reason")
    step = _step(index, action, row, world, "blocked" if blocked else "prepared", blocked, bind)
    step.update(
        {
            "body": body,
            "requires": list(descriptor.get("requires", ())),
            "permitted": bool(descriptor.get("permitted", False)),
            "preview": {
                "operation": row.preview,
                "body": preview_body,
                "document": document,
                "document_sha256": _digest(document),
            },
            "pins": {"base_state_sha256": world.state_sha256, "edit_seq": world.edit_seq},
            "effects": [dict(effect) for effect in descriptor.get("effects", ())],
        }
    )
    return step


def _prepared_things_step(
    index: int, action: _Action, context: _Context, world: _World
) -> dict[str, Any]:
    """A thing step with its exact request and pins, from a route with no preview: the route's own
    checks run in process (:mod:`exulanica.selection.action_things`), and a step they refuse is
    ``blocked`` with the route's code. A direct step that must wait for the society's next minute
    is ``pending`` with the code that says so; a client prepares it again before sending."""
    row = _MATRIX[action.operation]
    descriptor = world.descriptor(row.commit) or {}
    if action.operation is WorldEditOperation.PLACE_THING:
        body, code = _thing_placement(index, action, context, world)
        pins: dict[str, Any] | None = {
            "base_state_sha256": world.state_sha256,
            "edit_seq": world.edit_seq,
        }
        state = "blocked" if code is not None else "prepared"
    else:
        society = None if world.things is None else world.things.society
        if society is None:
            body, code = None, "unavailable_society_input"
        else:
            body, code = action_things.direct_body(
                society,
                requested_by=world.actor or uuid.UUID(int=0),
                subject_id=str(action.subject_id),
                act=str(action.act),
                target_id=action.target_id,
                thing_id=(
                    None
                    if action.thing_id is None
                    else action_things.society_thing_id(world.world_id, action.thing_id)
                ),
                with_id=action.with_id,
            )
        pins = (
            None
            if society is None
            else {"tick": society.tick, "society_state_sha256": society.state_sha256}
        )
        state = (
            "prepared"
            if code is None
            else "pending"
            if code in action_things.WAIT_CODES
            else "blocked"
        )
    step = _step(index, action, row, world, state, code)
    step.update(
        {
            "body": body,
            "requires": list(descriptor.get("requires", ())),
            "permitted": bool(descriptor.get("permitted", False)),
            "pins": pins,
            "effects": [dict(effect) for effect in descriptor.get("effects", ())],
            "titles": _titles(action, world),
        }
    )
    return step


def _prepared_pieces_step(index: int, action: _Action, world: _World) -> dict[str, Any]:
    """A request for new pieces of the world's look, with the estimate its route answers with, so
    the sheet names the time and the cost before the person confirms. Blocked with the code that
    says why when nothing can be asked (``exulanica.generation.offer.WorldPieces.offer``)."""
    row = _MATRIX[action.operation]
    kinds = {kind.key: kind for kind in (() if world.things is None else world.things.kinds)}
    assert world.pieces is not None  # the step is offered only where the route hands it
    prepared = world.pieces.offer(
        [
            (kinds[key].key, kinds[key].version, kinds[key].label)
            for key in action.kinds
            if key in kinds
        ],
        named=action.named,
        idempotency_key=uuid.uuid5(
            uuid.UUID(int=0), f"{world.world_id}|{world.state_sha256}|{index}|pieces"
        ),
    )
    step = _step(
        index, action, row, world, "prepared" if prepared.code is None else "blocked", prepared.code
    )
    step.update(
        {
            # World-scoped: the route takes the world in its body, and no path value.
            "bind": {},
            "query": {},
            "body": prepared.body,
            "titles": prepared.titles or None,
            "estimate": prepared.estimate,
        }
    )
    return step


def _prepared_thing_edit_step(
    index: int, action: _Action, context: _Context, world: _World
) -> dict[str, Any]:
    """A placed thing moved to where the person points, or taken away: the request its route
    takes, with the route's own checks run in process, since it has no preview. A thing that does
    not stand in this version is ``blocked`` with ``invalid_object_state``; a move to a spot in
    another region, or one no pose can state, with ``invalid_thing_placement``; a move with
    nowhere free near the spot with ``no_free_place_near``. It stands at the ground's elevation
    where the version states one, turned to face the person, as a thing added there would."""
    row = _MATRIX[action.operation]
    descriptor = world.descriptor(row.commit) or {}
    read = world.things
    thing_id = str(action.thing_id)
    standing = None if read is None else read.anchors.get(("thing", thing_id))
    body: dict[str, Any] | None = None
    code: str | None = None
    if read is None or standing is None:
        code = "invalid_object_state"
    elif action.operation is WorldEditOperation.REMOVE_THING:
        body = {"base_state_sha256": world.state_sha256, "saved_entry": context.edit_entry()}
    else:
        footprint, region_id, y_now = standing
        placement = context.placement or {}
        transform = placement.get("transform") or {}
        if str(placement.get("region_id")) != region_id:
            code = "invalid_thing_placement"
        else:
            viewer = context.viewer_point()
            taken = [found for taken_id, found in read.taken if taken_id != thing_id]
            if read.society is not None:
                placed_as = {
                    str(person["id"])
                    for person in read.society.state.get("inhabitants", ())
                    if person.get("placed_id") == thing_id
                }
                taken += [b.footprint for b in read.society.beings if b.id not in placed_as]
            y_mm = read.elevation_mm if read.elevation_mm is not None else y_now
            current = next((t for t in world.placed_things if t.thing_id == thing_id), None)
            # Where the move's route will let it stand, as that route judges it.
            fits = (
                None
                if current is None
                else action_things.landing_fits(
                    world.landings.get(region_id),
                    world.placed_things,
                    thing=current,
                    y_mm=y_mm,
                    yaw_at=lambda point: action_things.facing_yaw(
                        point, viewer, otherwise=int(transform["yaw_microradians"])
                    ),
                )
            )
            point = action_things.lay_out(
                footprint.half_mm,
                anchor=None,
                spot=(int(transform["x_mm"]), int(transform["z_mm"])),
                viewer=viewer,
                taken=taken,
                fits=fits,
            )
            if point is None:
                code = "no_free_place_near"
            else:
                yaw = action_things.facing_yaw(
                    point, viewer, otherwise=int(transform["yaw_microradians"])
                )
                moved = action_things.thing_transform(point, y_mm, yaw)
                try:
                    validate_transform(moved)
                except InvalidObjectData:
                    code = "invalid_thing_placement"
                else:
                    body = {
                        "base_state_sha256": world.state_sha256,
                        "pose": {
                            "x_mm": moved.x_mm,
                            "y_mm": moved.y_mm,
                            "z_mm": moved.z_mm,
                            "yaw_microradians": moved.yaw_microradians,
                        },
                        "saved_entry": context.edit_entry(),
                    }
    step = _step(
        index,
        action,
        row,
        world,
        "prepared" if code is None else "blocked",
        code,
        {"version_id": str(world.version_id), "thing_id": thing_id},
    )
    step.update(
        {
            "body": body,
            "pins": {"base_state_sha256": world.state_sha256, "edit_seq": world.edit_seq},
            "effects": [dict(effect) for effect in descriptor.get("effects", ())],
            "titles": _titles(action, world),
        }
    )
    return step


def _prepared_play_step(index: int, action: _Action, world: _World) -> dict[str, Any]:
    """The person starting to play a being, or giving back the one they play: the request the
    play routes take, with the choice record's own checks run with no lock and nothing recorded.
    Blocked with the route's code where it would refuse (``engine_takes_no_play``,
    ``being_played``, ``decided_from_outside``, ``decider_not_allowed``, ``not_played``), and with
    ``no_change`` where the person plays that being already. Playing asks no model: it spends
    nothing, and the being's own mind rests until it is given back."""
    row = _MATRIX[action.operation]
    assert world.play is not None  # the step is offered only where the route hands it
    giving = action.operation is WorldEditOperation.GIVE_BACK
    read = world.play.play_preview(None if giving else action.subject_id)
    played = [str(subject) for subject in read["played"]]
    subject = action.subject_id
    code = read["code"]
    if giving and code is None:
        if subject is None and len(played) == 1:
            subject = played[0]
        if subject is None or subject not in played:
            code = "not_played"
    elif code is None and read["playing"]:
        code = "no_change"
    key = uuid.uuid5(
        uuid.UUID(int=0),
        f"{world.world_id}|{world.version_id}|{read['choice_seq']}|{index}|{subject}|"
        f"{action.operation.value}",
    )
    typed = dataclasses.replace(action, subject_id=subject)
    bind = {"version_id": str(world.version_id)}
    if giving:
        bind["subject_id"] = str(subject)
    step = _step(index, typed, row, world, "prepared" if code is None else "blocked", code, bind)
    body: dict[str, Any] | None = None
    if code is None:
        body = {"idempotency_key": str(key)}
        if not giving:
            body["subject_id"] = str(subject)
    step.update(
        {
            "body": body,
            "spends": False,
            "pins": {"choice_seq": read["choice_seq"]},
            "titles": _titles(typed, world),
        }
    )
    return step


def _with_play(world: _World, grant: Grant, play: Play | None) -> _World:
    """``world`` with playing a being and the descriptors of the two routes that start and end a
    play, which no version descriptor states (their subject is one being of a society): available
    while the version holds a society, permitted as the caller's grant says, spending nothing.
    Without ``play`` the steps are not offered."""
    if play is None:
        return dataclasses.replace(
            world,
            descriptors={
                key: value
                for key, value in world.descriptors.items()
                if key not in (PLAY, PLAY_GIVE_BACK)
            },
        )
    descriptors = dict(world.descriptors)
    for operation in (PLAY, PLAY_GIVE_BACK):
        requires, permitted = grant(operation)
        descriptors[operation] = {
            "operation": operation,
            "state": "available" if world.society_held else "unavailable",
            "code": None if world.society_held else "society_unavailable",
            "requires": list(requires),
            "permitted": permitted,
            "spends": False,
            "effects": [],
        }
    return dataclasses.replace(world, play=play, descriptors=descriptors)


def _budget_prepared(action: _Action, world: _World) -> action_budget.PreparedBudget:
    assert world.minds is not None  # the step is offered only where the route hands it
    society = None if world.things is None else world.things.society
    everyone = next(
        (group for group in world.society_groups if group.value == action_minds.EVERYONE), None
    )
    return action_budget.prepare(
        world.minds,
        world_id=world.world_id,
        usd_per_hour=str(action.usd_per_hour),
        decisions_per_hour=int(action.decisions_per_hour or 0),
        named=action.figures_named,
        # This society's own head count, as its state holds it; None where the version has none.
        beings=None if society is None else 0 if everyone is None else len(everyone.subjects),
    )


def _prepared_budget_step(
    index: int, action: _Action, world: _World, state: str = "prepared"
) -> dict[str, Any]:
    """A budget for the world's minds, with the request the budget route takes and what it comes
    to for this world as it stands (``budget``: the budget now and asked, both ceilings and which
    runs out first, the hour so far, how long it lasts for the beings a model decides for here,
    and what this server allows above it), so the sheet says all of it before the person
    confirms. Blocked with ``no_change`` where the world's budget already reads both figures.
    Setting a budget asks no model and spends nothing."""
    row = _MATRIX[action.operation]
    assert world.minds is not None
    prepared = _budget_prepared(action, world)
    step = _step(
        index,
        action,
        row,
        world,
        state if prepared.code is None else "blocked",
        prepared.code,
        {"version_id": str(world.version_id), "role_key": world.minds.role_key},
    )
    step.update(
        {
            "body": prepared.body if state == "prepared" else None,
            "spends": False,
            "pins": prepared.pins,
            "titles": {},
            "budget": prepared.facts,
        }
    )
    return step


def _with_budget(world: _World, grant: Grant | None, utterance: str | None) -> _World:
    """``world`` with the budget route's descriptor, which no version descriptor states (a budget
    is the world's): available wherever the route hands who decides for the world's beings,
    permitted as the caller's grant says, spending nothing. With the person's ``utterance``, the
    amounts code read in it and the drafter's options for a budget: each amount, then the two
    budgets a person may name with no figure. Without ``minds`` or a grant the step is not
    offered."""
    if world.minds is None or grant is None:
        return world
    requires, permitted = grant(BUDGET)
    descriptor = {
        "operation": BUDGET,
        "state": "available",
        "code": None,
        "requires": list(requires),
        "permitted": permitted,
        "spends": False,
        "effects": [],
    }
    said = () if utterance is None else action_budget.amounts(utterance)
    choices = (
        *(
            _Choice(
                label=f"amount-{index}",
                value=f"amount:{index}",
                title=action_budget.title(amount),
                detail=f"The request's words: {amount.words}",
            )
            for index, amount in enumerate(said, start=1)
        ),
        _Choice(
            label="budget-nothing",
            value=action_budget.NOTHING,
            title="nothing",
            detail="No AI is asked at all: 0 dollars and 0 decisions an hour.",
        ),
        _Choice(
            label="budget-default",
            value=action_budget.DEFAULT,
            title="the default",
            detail="The budget a world has before anyone sets one.",
        ),
    )
    return dataclasses.replace(
        world,
        said_amounts=said,
        said_fixed=() if utterance is None else action_budget.stated(utterance),
        said_shape=None if utterance is None else action_budget.shape_of(utterance)[1],
        amounts=choices,
        descriptors={**world.descriptors, BUDGET: descriptor},
    )


def _mind_prepared(index: int, action: _Action, world: _World) -> action_minds.PreparedMind:
    assert world.minds is not None  # the step is offered only where the route hands it
    return action_minds.prepare(
        world.minds,
        world_id=world.world_id,
        version_id=world.version_id,
        index=index,
        whom=str(action.whom),
        mind=str(action.mind),
        found=world.society_groups,
    )


def _prepared_mind_step(index: int, action: _Action, world: _World) -> dict[str, Any]:
    """A choice of who decides, with the request the models route takes, what the choice comes to
    (how many it names, who is left out and why, how many beings models run against the world's
    bound, the groups this world holds) and what it will cost, so the sheet says all of it before
    the person confirms. Blocked with the route's own code where the route would refuse it
    (:func:`exulanica.selection.action_minds.prepare`). Only a model spends, once the world
    plays; the routine asks nobody."""
    row = _MATRIX[action.operation]
    descriptor = world.descriptor(row.commit) or {}
    prepared = _mind_prepared(index, action, world)
    assert world.minds is not None
    step = _step(
        index,
        action,
        row,
        world,
        "prepared" if prepared.code is None else "blocked",
        prepared.code,
        {"version_id": str(world.version_id), "role_key": world.minds.role_key},
    )
    step.update(
        {
            "body": prepared.body,
            "spends": prepared.spends,
            "pins": prepared.pins or None,
            "effects": [dict(effect) for effect in descriptor.get("effects", ())],
            "titles": _titles(action, world),
            "mind": {
                **prepared.facts,
                "groups_here": [
                    {"value": group.value, "title": group.title, "count": len(group.subjects)}
                    for group in world.society_groups
                ],
            },
            "cost": prepared.cost,
        }
    )
    return step


def _too_many_for_models(actions: Sequence[_Action], world: _World) -> dict[str, Any] | None:
    """Where the first step's choice would run more beings by models than the world's contract
    allows and another group this world holds would fit, the question: which instead. The answer
    is never picked for the person; with nothing that fits, the step is blocked by the route's
    own code instead."""
    first = actions[0]
    if (
        first.operation is not WorldEditOperation.CHOOSE_MIND
        or world.minds is None
        or first.mind in (None, action_minds.ROUTINE)
        or first.whom is None
    ):
        return None
    asked = _mind_prepared(0, first, world)
    if asked.code != "too_many_model_people":
        return None
    fitting = [
        choice
        for choice in world.groups
        if choice.value != first.whom
        and _mind_prepared(0, dataclasses.replace(first, whom=choice.value), world).code is None
    ]
    if not fitting:
        return None
    return {
        **_clarification("too_many_people_for_models", 0, "whom", actions, candidates=fitting),
        "facts": {
            "asked": asked.facts["subjects"],
            "bound": asked.facts["bound"],
            "run_now": asked.facts["run_now"],
        },
    }


def _with_minds(world: _World, minds: Minds | None) -> _World:
    """``world`` with who may decide for its beings and the drafter's options for a mind: the
    minds a being may be given, their own routine first, and the groups the society holds, by an
    opaque label and with how many each is. Without ``minds`` the step is not offered; with no
    society a plan may read there are no groups, and the models route's descriptor says why."""
    if minds is None:
        return dataclasses.replace(
            world,
            descriptors={key: value for key, value in world.descriptors.items() if key != MIND},
        )
    choices = (
        _Choice(
            label="mind-routine",
            value=action_minds.ROUTINE,
            title="their own routine",
            detail="What they would do anyway. No AI is asked.",
        ),
        *(
            _Choice(
                label=f"mind-{index}",
                value=action_minds.mind_value(model.provider, model.model_id),
                title=model.name,
                detail=model.description,
            )
            for index, model in enumerate(minds.models(), start=1)
        ),
    )
    society = None if world.things is None else world.things.society
    if society is None:
        stated = world.descriptor(MIND)
        descriptors = dict(world.descriptors)
        if stated is not None and stated.get("state") == "available":
            descriptors[MIND] = {
                **stated,
                "state": "unavailable",
                "code": "unavailable_society_input",
            }
        return dataclasses.replace(
            world, minds=minds, mind_choices=choices, descriptors=descriptors
        )
    found = action_minds.groups(society.state)
    groups = tuple(
        _Choice(
            label=f"group-{index}",
            value=group.value,
            title=f"{group.title} ({len(group.subjects)})",
        )
        for index, group in enumerate(found, start=1)
    )
    return dataclasses.replace(
        world, minds=minds, groups=groups, mind_choices=choices, society_groups=found
    )


def _with_pieces(world: _World, grant: Grant, pieces: Pieces | None) -> _World:
    """``world`` with what new pieces of its look rest on and the descriptor of the route that
    asks for them, which no version descriptor states (its route is world-scoped): available while
    the world wears a look pieces can be made in, permitted as the caller's grant says, spending.
    Without ``pieces`` the step is not offered."""
    if pieces is None:
        return world
    requires, permitted = grant(PIECES)
    available = pieces.available()
    descriptor = {
        "operation": PIECES,
        "state": "available" if available else "unavailable",
        "code": None if available else "look_not_served",
        "requires": list(requires),
        "permitted": permitted,
        "spends": True,
        "effects": [],
    }
    return dataclasses.replace(
        world, pieces=pieces, descriptors={**world.descriptors, PIECES: descriptor}
    )


def _titles(action: _Action, world: _World) -> dict[str, str]:
    """What a thing step names, as the reads label it: the kind and what it goes beside, or the
    being and the place, or the being, the thing and the other being. The labels the drafter and a
    clarification show, for the page's words."""
    read = world.things
    titles: dict[str, str | None] = {}
    if action.operation in (WorldEditOperation.MOVE_THING, WorldEditOperation.REMOVE_THING):
        named = None if read is None else _thing_title(str(action.thing_id), read)
        return {} if named is None else {"thing": named}
    if action.operation in (WorldEditOperation.PLAY_BEING, WorldEditOperation.GIVE_BACK):
        society = None if read is None else read.society
        named = next(
            (
                being.display_name
                for being in (() if society is None else society.beings)
                if being.id == action.subject_id
            ),
            None,
        )
        return {} if named is None else {"subject": named}
    if action.operation is WorldEditOperation.CHOOSE_MIND:
        whom = action.whom
        if whom is not None and whom.startswith("being:"):
            society = None if read is None else read.society
            titles["whom"] = next(
                (
                    being.display_name
                    for being in (() if society is None else society.beings)
                    if being.id == whom.removeprefix("being:")
                ),
                None,
            )
        else:
            titles["whom"] = next(
                (group.title for group in world.society_groups if group.value == whom), None
            )
        titles["mind"] = next(
            (choice.title for choice in world.mind_choices if choice.value == action.mind), None
        )
        return {key: value for key, value in titles.items() if value is not None}
    if action.operation is WorldEditOperation.PLACE_THING:
        kind = None if read is None or action.kind is None else read.kind(action.kind)
        titles["kind"] = None if kind is None else kind.label
        if action.near is not None:
            prefix, _, named = action.near.partition(":")
            if prefix == "thing":
                found = next((c for c in world.placed if c.value == action.near), None)
                minted = named.split(":")[1] if named.startswith("companion:") else None
                added = None if minted is None or read is None else read.kind(minted)
                titles["near"] = (
                    found.title if found is not None else None if added is None else added.label
                )
            elif prefix == "object":
                found = next((c for c in world.objects if c.value == named), None)
                titles["near"] = None if found is None else found.title.lower()
            elif prefix == "newest-object":
                found = next((c for c in world.assets if c.value == named), None)
                titles["near"] = None if found is None else found.title.lower()
            elif prefix == "being" and read is not None:
                being = read.being(named)
                titles["near"] = None if being is None else being.display_name
    elif action.operation is WorldEditOperation.DIRECT_THING and read is not None:
        being = None if action.subject_id is None else read.being(action.subject_id)
        titles["subject"] = None if being is None else being.display_name
        titles["act"] = action.act
        if action.act in _HANDS:
            other = None if action.with_id is None else read.being(action.with_id)
            titles["thing"] = (
                None if action.thing_id is None else _thing_title(action.thing_id, read)
            )
            titles["with"] = None if other is None else other.display_name
        else:
            place = None if action.target_id is None else read.place(action.target_id)
            titles["place"] = None if place is None else place.title
            titles["affordance"] = None if place is None else place.affordance
    return {key: value for key, value in titles.items() if value is not None}


def _thing_title(placed_id: str, read: action_things.ThingsRead) -> str | None:
    """A placed thing's kind label, or the kind's for one an earlier step of the plan adds."""
    found = next((item for item in read.placed if item.thing_id == placed_id), None)
    if found is not None:
        return found.label
    minted = placed_id.split(":")
    kind = read.kind(minted[1]) if len(minted) == 3 and minted[0] == "companion" else None
    return None if kind is None else kind.label


def _anchor(
    near: str, world: _World
) -> tuple[action_things.Footprint, str | None, int | None] | None:
    """What a thing is put beside, where it stands, its region and its height where known; None
    for something no longer here."""
    read = world.things
    if read is None:
        return None
    prefix, _, named = near.partition(":")
    if prefix == "being":
        being = read.being(named)
        if being is None or read.society is None:
            return None
        return being.footprint, read.society.region_id, None
    return read.footprint(prefix, named)


def _thing_placement(
    index: int, action: _Action, context: _Context, world: _World
) -> tuple[dict[str, Any] | None, str | None]:
    """The body ``POST .../things`` takes for this step, or the code it would refuse it with."""
    read = world.things
    kind = None if read is None or action.kind is None else read.kind(action.kind)
    if read is None or kind is None:
        return None, "invalid_thing_placement"
    viewer = context.viewer_point()
    spot_region = None if context.placement is None else str(context.placement["region_id"])
    spot_transform = None if context.placement is None else context.placement["transform"]
    if action.near is not None:
        anchored = _anchor(action.near, world)
        if anchored is None:
            return None, "anchor_not_here"
        anchor, region_id, anchor_y = anchored
        spot = None
    else:
        if spot_region is None or spot_transform is None:
            return None, "placement_required"
        anchor, region_id, anchor_y = None, spot_region, int(spot_transform["y_mm"])
        spot = (int(spot_transform["x_mm"]), int(spot_transform["z_mm"]))
    region = region_id or spot_region
    if region is None:
        return None, "invalid_thing_placement"
    taken = [footprint for _id, footprint in read.taken]
    if read.society is not None:
        taken += [being.footprint for being in read.society.beings]
    y_mm = (
        read.elevation_mm
        if read.elevation_mm is not None
        else anchor_y
        if anchor_y is not None
        else 0
        if spot_transform is None
        else int(spot_transform["y_mm"])
    )
    otherwise = 0 if spot_transform is None else int(spot_transform["yaw_microradians"])
    thing_id = action.thing_id or action_things.minted_thing_id(
        world.version_id, world.state_sha256, index, kind.key
    )
    origin_role = str(context.origin_role)
    # Where the add's route will let it stand, as that route judges it.
    fits = action_things.landing_fits(
        world.landings.get(region),
        world.placed_things,
        thing=PlacedThing(
            thing_id=thing_id,
            kind=ThingKindReference(kind.key, kind.version, kind.sha256),
            region_id=region,
            transform=Transform(0, y_mm, 0, 0, UNSCALED_MILLI),
            origin=ObjectOrigin("authored", origin_role),
        ),
        y_mm=y_mm,
        yaw_at=lambda point: action_things.facing_yaw(point, viewer, otherwise=otherwise),
    )
    point = action_things.lay_out(
        kind.half_mm, anchor=anchor, spot=spot, viewer=viewer, taken=taken, fits=fits
    )
    if point is None:
        return None, "no_free_place_near"
    yaw = action_things.facing_yaw(point, viewer, otherwise=otherwise)
    transform = action_things.thing_transform(point, y_mm, yaw)
    refused = action_things.placement_refusal(
        thing_id=thing_id,
        kind=kind,
        region_id=region,
        transform=transform,
        origin_role=origin_role,
        region_ids=frozenset(world.region_ids) or frozenset({region}),
        things=read,
    )
    if refused is not None:
        return None, refused
    return {
        "base_state_sha256": world.state_sha256,
        "thing_id": thing_id,
        "kind": {"kind": kind.key, "version": kind.version, "sha256": kind.sha256},
        "region_id": region,
        "pose": {
            "x_mm": transform.x_mm,
            "y_mm": transform.y_mm,
            "z_mm": transform.z_mm,
            "yaw_microradians": transform.yaw_microradians,
        },
        "origin_role": origin_role,
        "saved_entry": context.edit_entry(),
    }, None


def _step(
    index: int,
    action: _Action,
    row: _Row,
    world: _World,
    state: str,
    code: str | None,
    bind: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    descriptor = world.descriptor(row.commit) or {}
    return {
        "index": index,
        "action": action.document(),
        "state": state,
        "code": code,
        "operation": row.commit,
        "bind": dict(bind or {"version_id": str(world.version_id)}),
        "query": {"world_id": world.world_id},
        "body": None,
        "requires": list(descriptor.get("requires", ())),
        "permitted": bool(descriptor.get("permitted", False)),
        "spends": bool(descriptor.get("spends", False)),
        "preview": None,
        "pins": None,
        "effects": [],
        "confirmation": "required",
        "replay": row.replay,
        "receipt": row.receipt,
        "compensation": None if row.compensation is None else {"operation": row.compensation},
    }


def _pending_step(index: int, action: _Action, world: _World) -> dict[str, Any]:
    """A later step of a compound request: typed, prepared after the previous step's receipt.

    A later choice of a mind is confirmed with the first step, so it states before that yes what
    it comes to as the world stands now: how many beings it names, who is left out, what it may
    cost and whether it spends (:func:`_mind_prepared`), and one the route would refuse now is
    ``blocked`` with the route's code, so the plan is not confirmed. It is prepared again just
    before it is sent; a client stops it there if it then names more beings than were shown."""
    row = _MATRIX[action.operation]
    bind = {"version_id": str(world.version_id)}
    if action.object_id is not None:
        bind["object_id"] = action.object_id
    step = _step(index, action, row, world, "pending", None, bind)
    if row.preview is None:
        step["titles"] = _titles(action, world)
    if (
        action.operation is WorldEditOperation.CHOOSE_MIND
        and world.minds is not None
        and action.whom is not None
        and action.mind is not None
    ):
        shown = _mind_prepared(index, action, world)
        step.update(
            {
                "state": "pending" if shown.code is None else "blocked",
                "code": shown.code,
                "spends": shown.spends,
                "mind": {
                    **shown.facts,
                    "groups_here": [
                        {"value": group.value, "title": group.title, "count": len(group.subjects)}
                        for group in world.society_groups
                    ],
                },
                "cost": shown.cost,
            }
        )
    if action.operation is WorldEditOperation.SET_MINDS_BUDGET and world.minds is not None:
        # A later budget is confirmed with the first step, so it states before that yes what it
        # comes to as the world stands now. Its figures are the typed action's and cannot change
        # when it is prepared again; what a choice of minds before it adds is said then.
        return _prepared_budget_step(index, action, world, state="pending")
    return step
