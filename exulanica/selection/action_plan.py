"""Asking the Companion for world work, and getting back the exact requests a direct client sends.

The Companion does not act on the world. It reads one utterance and answers with a plan whose
steps are the requests a direct client would send to the authorities that already exist, each with
that authority's own preview. The person confirms; the client sends those requests to the same
routes; the receipts are the authorities' own records; :mod:`exulanica.selection.action_outcome`
reads them back. So an operation reached through the Companion has the same permission, validation,
transaction and refusal as the same operation sent directly, because it is the same request.

    classify  ->  question        ->  the answer path, unchanged
        |     ->  capabilities    ->  what this world offers, read from the capability descriptors
        |     ->  simulation      ->  draft  ->  validate  ->  clarify, refuse, or prepare the chain
        |     ->  appearance      ->  the appearance drafter (:mod:`exulanica.selection.proposal`)
        +---- ->  world_edit      ->  draft  ->  validate  ->  clarify, refuse, or prepare step one

Rules the planner holds by construction rather than by asking the model:

*   **The model fills enums only.** The world-edit form is built at call time from the reads a
    direct client would make: the reviewed kinds a person may place, the objects this version holds
    (as opaque labels, so an id a client chose never reaches a hosted request) and the published
    arrangements. There is no field for an identifier the reads did not list, a position, a size, a
    permission or a route. Positions come from where the page says the person is pointing.
*   **Availability and permission are the capability descriptors'.** The route hands this module
    the version's capability read (``exulanica.api.routes.capabilities``); an operation the read
    calls unsupported, unavailable or not permitted is refused with the read's own code, and the
    operation vocabulary is never filtered by availability first, so a request is refused by its
    own code rather than approximated by an operation that happens to be offered.
*   **Ambiguity is asked about before anything is prepared.** Two kinds, objects or arrangements
    the words could mean, a missing place to put something, and an origin role the person has not
    stated all come back as a clarification carrying the typed action and the open slot. An origin
    role is the person's choice and is never inferred.
*   **Only the first step is prepared.** Each later step of a compound request is typed but
    unprepared, and is prepared (:func:`prepare_action`) against the state the previous step's
    receipt left, so every confirmed step was previewed against the state it will meet. Steps
    commit one at a time; no plan claims all-or-nothing.
*   **Previews are the authorities' own.** A step's preview is computed by the same domain function
    its preview route calls, on a repository the route opens only when the caller's grant holds that
    preview route's permission, inside a read-only transaction.
*   **Simulated time moves only through the playback controls, pinned to one clock read.** Every
    base a simulation step sends is the version's clock read (``exulanica.world-clock/v1``): the
    clock's revision, the control's revision, and the society's minute and state. A request to move
    time forward is a chain of control steps under one confirmation, each step taking its bases
    from the response to the one before; a refusal stops the chain where it is. The chain runs only
    while the world is paused: a playing world is paused first and played again at its speed last,
    and the plan shows both steps.
*   **Things are added by their kind, and beings asked by the route that takes direct requests.**
    A world edit may add a thing (``place_thing``) or ask one of the world's beings to go to a
    place or use it, or to pick a thing up, put it down, give it or take it (``direct_thing``);
    :mod:`exulanica.selection.action_things` reads, lays out and prepares both, from routes that
    already exist. Neither route has a preview, so their own checks run in process before a step is
    offered.
*   **A mind is chosen through the models route, for a being or a group the society itself
    holds.** A world edit may say who decides for a being, a kind, a role or everyone
    (``choose_mind``): an open model the server offers, or their own routine.
    :mod:`exulanica.selection.action_minds` reads the groups from the society's state and prepares
    the choice with the route's own checks, what it would cost and the world's hourly ceilings.
*   **A budget's figures are the person's own, read by code.** A world edit may set what the world
    spends on its minds in an hour (``set_minds_budget``). The drafter writes no number: the
    amounts are read from the person's sentence by :mod:`exulanica.selection.action_budget`
    and listed as options, an amount over a span that is not an hour is asked about and never
    converted, and a figure the words do not name is kept as the world has it.
*   **An erasure is asked for, never offered.** A simulation request may have a living town's
    people take in what was placed after they came (``take_in``), only where the capability read
    says they can. The step states what is lost and kept and that nothing undoes it; no other
    refusal suggests it.

The planner's parts: :mod:`exulanica.selection.action_vocabulary` holds its bounds, the kinds of
action and operation, its codes and the routes each operation is sent to;
:mod:`exulanica.selection.action_world` reads the world a plan is read against;
:mod:`exulanica.selection.action_drafting` asks the models, with their prompts and forms; and
:mod:`exulanica.selection.action_typing` reads a draft or a client's request back into typed steps.
This module prepares the typed steps and writes the plan document, and holds the entries the route
calls (:func:`plan_action` and :func:`prepare_action`).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json
from exulanica.models.client import ModelClient
from exulanica.selection import action_budget, action_minds, action_things
from exulanica.selection.action_drafting import (
    ACTION_PROMPT_VERSION,
    _draft_simulation,
    _draft_world_edit,
    _offered,
    classify_action,
)
from exulanica.selection.action_typing import (
    _Action,
    _availability,
    _clarification,
    _descriptor_refusal,
    _refusal,
    _requirements,
    _typed_from_draft,
    _typed_from_request,
    _Verdict,
)
from exulanica.selection.action_vocabulary import (
    _HANDS,
    _MATRIX,
    ACTION_PATH_CALLS,
    ACTION_REFUSALS,
    BRING_PEOPLE,
    BUDGET,
    CLARIFICATIONS,
    CONTROL,
    CONTROL_STEP,
    DIRECT,
    DRAFT_OPERATIONS,
    MAX_MINUTES,
    MAX_PLAN_STEPS,
    MAX_STEPS,
    MIND,
    PIECES,
    PLACE,
    PLAY,
    PLAY_GIVE_BACK,
    PRESENCE,
    STYLE_APPLY,
    STYLE_DISCARD,
    STYLE_PREVIEW,
    TAKE_IN,
    TAKE_IN_KEEPS,
    TAKE_IN_LOSES,
    THING_MOVE,
    THING_PLACE,
    THING_REMOVE,
    THING_UNDO,
    ActionKind,
    ClockReader,
    Grant,
    Minds,
    Pieces,
    Play,
    Previewer,
    SimulationAction,
    SocietyReader,
    WorldEditOperation,
    _Row,
    action_bound_seconds,
)

# Named here for the callers that read them from this module.
from exulanica.selection.action_vocabulary import (
    ARRANGE as ARRANGE,
)
from exulanica.selection.action_vocabulary import (
    MOVE as MOVE,
)
from exulanica.selection.action_vocabulary import (
    PLACE_PREVIEW as PLACE_PREVIEW,
)
from exulanica.selection.action_vocabulary import (
    REMOVE as REMOVE,
)
from exulanica.selection.action_vocabulary import (
    UNDO as UNDO,
)
from exulanica.selection.action_world import _Choice, _Context, _plain, _World, read_world
from exulanica.selection.calls import CallLog, ModelCall
from exulanica.selection.proposal import RefusalCode, appearance_change, source_catalogue
from exulanica.selection.request_names import RequestNames
from exulanica.selection.validation import Session
from exulanica.store.base import ContentAddressedStore
from exulanica.world import WorldNotConfigured, WorldStyleRepository
from exulanica.world.arrangements import ArrangementRequest, preview_arrangement
from exulanica.world.composition_preview import (
    CompositionPlacement,
    CompositionRequest,
    ReviewedAssetSource,
    preview_composition,
)
from exulanica.world.decision_roles import decision_roles
from exulanica.world.errors import InvalidObjectData
from exulanica.world.models import StyleVersion
from exulanica.world.object_edit_preview import (
    preview_object_move,
    preview_object_removal,
    preview_undo,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import ObjectOrigin, Transform, validate_transform
from exulanica.world.placed_things import UNSCALED_MILLI, PlacedThing, ThingKindReference
from exulanica.world.repository import AUTHORED_DESIGN_BASIS, EVIDENCE_BASIS
from exulanica.world.society_controls import SPEEDS
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_presence import AWAY, HERE
from exulanica.world.society_presence import refusal as presence_refusal
from exulanica.world.traffic_signal_repository import TrafficSignalRepository

__all__ = [
    "ACTION_PATH_CALLS",
    "ACTION_PROMPT_VERSION",
    "ACTION_REFUSALS",
    "BUDGET",
    "CLARIFICATIONS",
    "DIRECT",
    "DRAFT_OPERATIONS",
    "MAX_MINUTES",
    "MAX_PLAN_STEPS",
    "MAX_STEPS",
    "MIND",
    "PIECES",
    "PLAN_PROFILE",
    "PLAY",
    "PLAY_GIVE_BACK",
    "PRESENCE",
    "SIMULATION_OPERATIONS",
    "TAKE_IN",
    "TAKE_IN_KEEPS",
    "TAKE_IN_LOSES",
    "THING_MOVE",
    "THING_PLACE",
    "THING_REMOVE",
    "THING_UNDO",
    "ActionKind",
    "ClockReader",
    "Minds",
    "Pieces",
    "PlannedAction",
    "Play",
    "Previewer",
    "SimulationAction",
    "SocietyReader",
    "TimeSpending",
    "WorldEditOperation",
    "action_bound_seconds",
    "classify_action",
    "document_sha256",
    "plan_action",
    "plan_document_sha256",
    "prepare_action",
    "simulation_document",
    "time_spends",
]

PLAN_PROFILE: Final = "exulanica.companion-action-plan/v1"


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


# -- the plan document ---------------------------------------------------------------------------


def _digest_input(value: Any) -> Any:
    """``value`` with every float written as its shortest round-trip decimal, tagged.

    Floats never enter a digest input in this codebase (``exulanica.canonical``); a style
    parameter is one, so it enters as a tagged string that states it exactly.
    """
    if isinstance(value, float):
        return {"float": repr(value)}
    if isinstance(value, Mapping):
        return {str(key): _digest_input(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_digest_input(item) for item in value]
    return value


def _digest(document: Any) -> str:
    return hashlib.sha256(canonical_json(_digest_input(document))).hexdigest()


def document_sha256(document: Any) -> str:
    """The digest a plan gives a preview or recorded document, floats tagged as above."""
    return _digest(document)


def plan_document_sha256(document: Mapping[str, Any]) -> str:
    """The digest a plan names itself by: every member except the digest and the execution."""
    return _digest(
        {
            key: value
            for key, value in document.items()
            if key not in ("plan_sha256", "execution", "names")
        }
    )


def _document(
    *,
    outcome: str,
    kind: ActionKind,
    world_id: str,
    version_id: uuid.UUID,
    steps: Sequence[Mapping[str, Any]] = (),
    atomic: bool = False,
    clarification: Mapping[str, Any] | None = None,
    refusal: Mapping[str, Any] | None = None,
    capabilities: Sequence[Mapping[str, Any]] | None = None,
    proposal_speech: str | None = None,
    clock: Mapping[str, Any] | None = None,
    spends_by: Sequence[str] = (),
) -> dict[str, Any]:
    document: dict[str, Any] = {
        "profile": PLAN_PROFILE,
        "outcome": outcome,
        "kind": kind.value,
        "world_id": world_id,
        "version_id": str(version_id),
        "atomic": atomic,
        "steps": [dict(step) for step in steps],
        # Whether any step can lead to a hosted model call, stated before the one confirmation,
        # and the decision roles whose chosen models simulated minutes would ask.
        "spends": any(bool(step.get("spends")) for step in steps),
        "spends_by": list(spends_by),
        "clarification": None if clarification is None else dict(clarification),
        "refusal": None if refusal is None else dict(refusal),
        "capabilities": None if capabilities is None else [dict(item) for item in capabilities],
        "proposal_speech": proposal_speech,
        # The clock read a simulation plan's bases were taken from, as GET .../clock answered it.
        "clock": None if clock is None else dict(clock),
    }
    document["plan_sha256"] = plan_document_sha256(document)
    return document


@dataclass(frozen=True, slots=True)
class PlannedAction:
    """A plan document and what it cost to make: the calls, its prompt version and the names."""

    document: dict[str, Any]
    calls: tuple[ModelCall, ...] = ()
    prompt_version: str = ACTION_PROMPT_VERSION
    names: tuple[tuple[str, uuid.UUID], ...] = ()


def _world_edit_document(
    verdict: _Verdict, context: _Context, world: _World, previewer: Previewer
) -> dict[str, Any]:
    """Refuse, clarify, or prepare the first step and list the rest as pending."""
    common = {
        "kind": ActionKind.WORLD_EDIT,
        "world_id": world.world_id,
        "version_id": world.version_id,
    }
    if verdict.refusal is not None:
        return _document(outcome="refused", refusal=verdict.refusal, **common)
    refused = _availability(verdict.actions, world)
    if refused is not None:
        return _document(outcome="refused", refusal=refused, **common)
    if verdict.clarification is not None:
        return _document(outcome="clarify", clarification=verdict.clarification, **common)
    asked = _requirements(verdict.actions, context, world) or _too_many_for_models(
        verdict.actions, world
    )
    if asked is not None:
        return _document(outcome="clarify", clarification=asked, **common)
    first, *rest = verdict.actions
    prepared = _prepared_step(0, first, context, world, previewer)
    steps = [
        prepared,
        *(_pending_step(index, action, world) for index, action in enumerate(rest, start=1)),
    ]
    atomic = len(steps) == 1 and _MATRIX[first.operation].atomic
    if prepared["state"] == "not_permitted":
        return _document(
            outcome="refused",
            refusal=_refusal(
                "action_not_permitted",
                "the caller's grant does not hold the preview of the operation",
                operation=_MATRIX[first.operation].preview,
                step=0,
            ),
            steps=steps,
            **common,
        )
    if prepared["state"] == "blocked":
        return _document(
            outcome="refused",
            refusal=_refusal(
                "preview_blocked",
                "the authority's preview refused the step; its code is the step's",
                operation=prepared["operation"],
                step=0,
            ),
            steps=steps,
            **common,
        )
    return _document(outcome="plan", steps=steps, atomic=atomic, **common)


def _world_edit_plan(
    client: ModelClient,
    names: RequestNames,
    sent: str,
    context: _Context,
    world: _World,
    previewer: Previewer,
    *,
    log: CallLog,
) -> dict[str, Any]:
    """The world-edit branch of an utterance: draft, validate, then refuse, clarify or prepare.

    ``sent`` is the utterance with every name no right can release replaced (``names``). A grant
    that permits none of the edits the Companion prepares is refused before a draft is paid for.
    """
    if not any(
        bool((world.descriptor(row.commit) or {}).get("permitted")) for row in _MATRIX.values()
    ):
        return _document(
            outcome="refused",
            kind=ActionKind.WORLD_EDIT,
            world_id=world.world_id,
            version_id=world.version_id,
            refusal=_refusal(
                "action_not_permitted",
                "the caller's grant holds none of the world edits the Companion prepares",
                operation=PLACE,
                capability=world.descriptor(PLACE),
            ),
        )
    steps = _draft_world_edit(client, sent, world, log=log, placeholders=names.placeholders)
    if steps is None:
        return _document(
            outcome="refused",
            kind=ActionKind.WORLD_EDIT,
            world_id=world.world_id,
            version_id=world.version_id,
            refusal=_refusal("not_drafted", "the model could not fill the form twice"),
        )
    return _world_edit_document(_typed_from_draft(steps, world, sent), context, world, previewer)


# -- simulation: the playback controls, pinned to one clock read --------------------------------


@dataclass(frozen=True, slots=True)
class _Simulation:
    """One typed simulation request: the action and the value each slot resolved to, or None."""

    action: SimulationAction
    speed: int | None = None
    minutes: int | None = None
    region_id: str | None = None

    def document(self) -> dict[str, Any]:
        return {
            "operation": self.action.value,
            "speed": self.speed,
            "minutes": self.minutes,
            "region_id": self.region_id,
        }


#: The typed operations a simulation request is sent back to ``/selection/actions/prepare`` as.
SIMULATION_OPERATIONS: Final = frozenset(
    action.value for action in SimulationAction if action is not SimulationAction.OTHER
)


def _simulation_clarification(
    code: str, slot: str, action: _Simulation, candidates: Sequence[tuple[str, bool]] = ()
) -> dict[str, Any]:
    """What to ask about a simulation request, with the typed action and its slot left open."""
    assert code in CLARIFICATIONS
    document = action.document()
    document[slot] = None
    return {
        "code": code,
        "step": 0,
        "slot": slot,
        "candidates": [
            {"value": value, "title": "", "selected": selected} for value, selected in candidates
        ],
        "actions": [document],
    }


@dataclass(frozen=True, slots=True)
class TimeSpending:
    """The decision roles whose chosen models simulated time can ask, by what moves it on.

    ``playing``: while the world plays, the playback worker's decision phase asks each chosen
    person's model before a minute (``DecisionHost.before_minute``, the one path a person is asked
    by), and a coupled world's traffic asks each chosen light's model as it seals the minutes.
    ``stepping``: a control step asks no person's model, but on a coupled world with traffic the
    minute it runs is sealed in turn, and sealing it asks each chosen light's model. A legacy
    world's traffic runs on the wall clock whatever its people do, so neither asks a light there.
    """

    playing: tuple[str, ...] = ()
    stepping: tuple[str, ...] = ()


def time_spends(
    connection: psycopg.Connection,
    session: Session,
    world: _World,
    clock: Mapping[str, Any],
) -> TimeSpending:
    """What moving this version's time on can ask, from the owner's model choices now."""
    society = clock.get("society")
    if society is None:
        return TimeSpending()
    people: list[str] = []
    choices = SocietyModelChoiceRepository(
        connection, session.workspace_id, world_id=world.world_id
    )
    engine = str(society["engine"])
    for role in decision_roles().hosted_by(engine):
        # Whoever a model decides for as the host asks: a person's own choice, or the mind their
        # gate names for the travellers it lets in, under the contract the engine's terms state.
        contract = role.contract(role.terms(engine).versions)
        if any(
            choice["model"] is not None
            for choice in choices.deciding(world.version_id, role, contract).values()
        ):
            people.append(role.key)
    lights: list[str] = []
    traffic = clock.get("traffic")
    if traffic is not None and traffic.get("state") != "unavailable":
        signals = TrafficSignalRepository(
            connection, session.workspace_id, world.world_id, world.version_id
        ).current_choices()
        if any(choice.get("model") is not None for choice in signals.values()):
            lights = [role.key for role in decision_roles() if role.subject == "signal"]
    return TimeSpending(playing=(*people, *lights), stepping=tuple(lights))


def _simulation_step(
    index: int,
    action: Mapping[str, Any],
    operation: str,
    world: _World,
    *,
    body: Mapping[str, Any],
    body_from: Mapping[str, Mapping[str, Any]] | None = None,
    pins: Mapping[str, Any] | None = None,
    asks: Sequence[str] = (),
) -> dict[str, Any]:
    """One step of a simulation plan: the exact request, sent as it stands or, after the first,
    with the bases its ``body_from`` names taken from the previous step's response."""
    descriptor = world.descriptor(operation) or {}
    receipt, replay, compensation = {
        CONTROL: ("control_configured", "stale_society_state_refused", CONTROL),
        CONTROL_STEP: ("control_manual_step", "stale_society_state_refused", None),
        BRING_PEOPLE: ("society_created", "held_society_returned", None),
        PRESENCE: ("society_presence", "same_key_returns_the_recorded_request", PRESENCE),
        # The society is made again once: asked again, the route refuses by name and erases
        # nothing. Nothing undoes it.
        TAKE_IN: ("society_taken_in", "asked_again_is_refused", None),
    }[operation]
    step: dict[str, Any] = {
        "index": index,
        "action": dict(action),
        "state": "prepared" if index == 0 else "pending",
        "code": None,
        "operation": operation,
        "bind": {"version_id": str(world.version_id)},
        "query": {"world_id": world.world_id},
        "body": dict(body),
        "requires": list(descriptor.get("requires", ())),
        "permitted": bool(descriptor.get("permitted", False)),
        # Its descriptor's own spending, or a chosen model of a role the time it moves on asks.
        "spends": bool(descriptor.get("spends", False)) or bool(asks),
        "preview": None,
        "pins": None if pins is None else dict(pins),
        "effects": [dict(effect) for effect in descriptor.get("effects", ())],
        # One confirmation of the first step authorises the steps after it; each is its own commit.
        "confirmation": "required" if index == 0 else "chained",
        "replay": replay,
        "receipt": receipt,
        "compensation": None if compensation is None else {"operation": compensation},
    }
    if body_from is not None:
        step["body_from"] = {field: dict(source) for field, source in body_from.items()}
    return step


def _bases_from(previous: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Where a control step after ``previous`` takes its bases: from the control read a
    configuration answers, or from the control and society a control step answers."""
    step = int(previous["index"])
    if previous["operation"] == CONTROL:
        fields = {
            "base_revision": "revision",
            "base_tick": "current_tick",
            "base_state_sha256": "state_sha256",
        }
    else:
        fields = {
            "base_revision": "control.revision",
            "base_tick": "society.current_tick",
            "base_state_sha256": "society.state_sha256",
        }
    return {base: {"step": step, "field": field} for base, field in fields.items()}


def _simulation_steps(
    action: _Simulation, world: _World, clock: Mapping[str, Any], spending: TimeSpending
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    """The exact requests, the first pinned to the clock read and each later one to the response
    to the step before it, and every decision role whose chosen model a step can ask."""
    society = clock["society"]
    clock_revision = int(clock["revision"])
    pins = {
        "clock_revision": clock_revision,
        "control_revision": int(society["control_revision"]),
        "tick": int(society["tick"]),
        "society_state_sha256": str(society["state_sha256"]),
    }
    speed = int(society["speed"])
    if action.action is not SimulationAction.ADVANCE:
        mode = {
            SimulationAction.PLAY: "playing",
            SimulationAction.PAUSE: "paused",
        }.get(action.action, str(society["mode"]))
        chosen = speed if action.speed is None else action.speed
        typed = _Simulation(action.action, speed=chosen)
        body = {
            "base_revision": pins["control_revision"],
            "mode": mode,
            "speed": chosen,
            "base_clock_revision": clock_revision,
        }
        asks = spending.playing if mode == "playing" else ()
        step = _simulation_step(
            0, typed.document(), CONTROL, world, body=body, pins=pins, asks=asks
        )
        return [step], asks
    assert action.minutes is not None
    steps: list[dict[str, Any]] = []
    playing = society["mode"] == "playing"
    if playing:
        steps.append(
            _simulation_step(
                0,
                _Simulation(SimulationAction.PAUSE, speed=speed).document(),
                CONTROL,
                world,
                body={
                    "base_revision": pins["control_revision"],
                    "mode": "paused",
                    "speed": speed,
                    "base_clock_revision": clock_revision,
                },
                pins=pins,
            )
        )
    for minute in range(1, action.minutes + 1):
        first = not steps
        typed = {**action.document(), "minute": minute}
        steps.append(
            _simulation_step(
                len(steps),
                typed,
                CONTROL_STEP,
                world,
                body={
                    "base_revision": pins["control_revision"] if first else None,
                    "base_tick": pins["tick"] if first else None,
                    "base_state_sha256": pins["society_state_sha256"] if first else None,
                    "base_clock_revision": clock_revision,
                },
                body_from=None if first else _bases_from(steps[-1]),
                pins=pins if first else None,
                asks=spending.stepping,
            )
        )
    if playing:
        # Played again at the speed it ran at, as the last step: a chain stopped before it leaves
        # the world paused, and nothing resumes it on its own.
        steps.append(
            _simulation_step(
                len(steps),
                _Simulation(SimulationAction.PLAY, speed=speed).document(),
                CONTROL,
                world,
                body={
                    "base_revision": None,
                    "mode": "playing",
                    "speed": speed,
                    "base_clock_revision": clock_revision,
                },
                body_from={"base_revision": _bases_from(steps[-1])["base_revision"]},
                asks=spending.playing,
            )
        )
    asked = (*spending.stepping, *(spending.playing if playing else ()))
    return steps, tuple(dict.fromkeys(asked))


def _simulation_requirements(
    action: _Simulation, society: Mapping[str, Any]
) -> dict[str, Any] | None:
    """What a simulation request needs and neither the draft nor the page supplied."""
    if action.action is SimulationAction.SET_SPEED and action.speed is None:
        return _simulation_clarification(
            "speed_required",
            "speed",
            action,
            [(str(speed), speed == society.get("speed")) for speed in SPEEDS],
        )
    if action.action is SimulationAction.ADVANCE and action.minutes is None:
        return _simulation_clarification("minutes_required", "minutes", action)
    return None


def _unchanged(action: _Simulation, society: Mapping[str, Any]) -> bool:
    """Whether the request asks for the state the playback controls already hold."""
    mode, speed = society.get("mode"), society.get("speed")
    if action.action is SimulationAction.PAUSE:
        return mode == "paused"
    if action.action is SimulationAction.PLAY:
        return mode == "playing" and action.speed in (None, speed)
    if action.action is SimulationAction.SET_SPEED:
        return action.speed == speed
    return False


def _bring_people(
    action: _Simulation, context: _Context, world: _World, common: Mapping[str, Any]
) -> dict[str, Any]:
    """People brought into the version's region, with the engine the capability read names."""
    refused = _descriptor_refusal(BRING_PEOPLE, world)
    if refused is not None:
        return _document(outcome="refused", refusal=refused, **common)
    if world.society_held:
        return _document(
            outcome="refused",
            refusal=_refusal(
                "no_change",
                "this version already holds its people",
                operation=BRING_PEOPLE,
                capability=world.descriptor(BRING_PEOPLE),
            ),
            **common,
        )
    region = action.region_id
    if region is not None and region not in world.region_ids:
        return _document(
            outcome="refused",
            refusal=_refusal("not_in_catalogue", "no region of this version has that id"),
            **common,
        )
    pointed = next(
        (
            str(place["region_id"])
            for place in (context.placement, context.viewer)
            if place is not None and place.get("region_id") in world.region_ids
        ),
        None,
    )
    if region is None:
        region = world.region_ids[0] if len(world.region_ids) == 1 else pointed
    if region is None:
        return _document(
            outcome="clarify",
            clarification=_simulation_clarification(
                "region_required",
                "region_id",
                action,
                [(candidate, candidate == pointed) for candidate in world.region_ids],
            ),
            **common,
        )
    typed = _Simulation(SimulationAction.BRING_PEOPLE, region_id=region)
    body: dict[str, Any] = {"region_id": region}
    if world.society_engine is not None:
        body["profile"] = world.society_engine
    step = _simulation_step(0, typed.document(), BRING_PEOPLE, world, body=body)
    return _document(outcome="plan", steps=[step], **common)


def _presence(
    action: _Simulation, world: _World, clock: Mapping[str, Any], common: Mapping[str, Any]
) -> dict[str, Any]:
    """Everyone sent away, or brought back: the one request the presence route takes, pinned to
    the minute and the state the clock read gave. Refused with the capability read's own state and
    code where the engine keeps its people or nobody lives here, and with the route's own name
    where the society's state already holds what is asked (``nobody_to_send_away``,
    ``already_here``: the route's pure check, run in process). The world and its history stay."""
    refused = _descriptor_refusal(PRESENCE, world)
    if refused is not None:
        return _document(outcome="refused", refusal=refused, **common)
    society = clock.get("society")
    if society is None:
        return _document(
            outcome="refused",
            refusal=_refusal("action_unavailable", "the version holds no people yet"),
            **common,
        )
    wanted = AWAY if action.action is SimulationAction.SEND_AWAY else HERE
    held = None if world.things is None else world.things.society
    blocked = None if held is None else presence_refusal(dict(held.state), wanted)
    pins = {
        "clock_revision": int(clock["revision"]),
        "tick": int(society["tick"]),
        "society_state_sha256": str(society["state_sha256"]),
    }
    key = uuid.uuid5(
        uuid.UUID(int=0),
        f"{world.world_id}|{world.version_id}|{pins['tick']}|{pins['society_state_sha256']}|"
        f"{wanted}|presence",
    )
    step = _simulation_step(
        0,
        _Simulation(action.action).document(),
        PRESENCE,
        world,
        body={
            "idempotency_key": str(key),
            "presence": wanted,
            "base_tick": pins["tick"],
            "base_state_sha256": pins["society_state_sha256"],
        },
        pins=pins,
    )
    if blocked is not None:
        step.update({"state": "blocked", "code": blocked, "body": None})
        return _document(
            outcome="refused",
            refusal=_refusal(
                "preview_blocked",
                "the society's state already holds what the request asks for",
                operation=PRESENCE,
                step=0,
            ),
            steps=[step],
            **common,
        )
    return _document(outcome="plan", steps=[step], **common)


def _take_in(
    action: _Simulation, world: _World, clock: Mapping[str, Any], common: Mapping[str, Any]
) -> dict[str, Any]:
    """A living town's people taking in what was placed after they came: the one request the
    take-in route takes, which has no body. Offered only where the capability read says the
    route would take it; anywhere else it is refused with the read's own state and code (no
    society, nothing placed to take in, a society that takes its newcomers in already, an input
    that cannot be composed). The step states what the erasure loses and keeps
    (:data:`TAKE_IN_LOSES`, :data:`TAKE_IN_KEEPS`) and that nothing undoes it; its pins are the
    minute the day would be lost at, for the sheet's words. It is alone in its plan."""
    refused = _descriptor_refusal(TAKE_IN, world)
    if refused is not None:
        return _document(outcome="refused", refusal=refused, **common)
    society = clock.get("society")
    pins = (
        None
        if society is None
        else {
            "clock_revision": int(clock["revision"]),
            "tick": int(society["tick"]),
            "society_state_sha256": str(society["state_sha256"]),
        }
    )
    step = _simulation_step(
        0, _Simulation(action.action).document(), TAKE_IN, world, body={}, pins=pins
    )
    step["erases"] = {
        "undo": False,
        "loses": list(TAKE_IN_LOSES),
        "keeps": list(TAKE_IN_KEEPS),
    }
    return _document(outcome="plan", steps=[step], **common)


def simulation_document(
    action: _Simulation,
    context: _Context,
    world: _World,
    clock: Mapping[str, Any],
    spending: TimeSpending,
) -> dict[str, Any]:
    """A typed simulation request refused, asked about, or planned as the exact requests."""
    common: dict[str, Any] = {
        "kind": ActionKind.SIMULATION,
        "world_id": world.world_id,
        "version_id": world.version_id,
        "clock": clock,
    }
    if action.action is SimulationAction.OTHER:
        return _document(
            outcome="refused",
            refusal=_refusal(
                "action_not_offered",
                "the request asks the world's time or people for something the Companion does "
                "not prepare",
            ),
            **common,
        )
    if action.minutes is not None and not 1 <= action.minutes <= MAX_MINUTES:
        return _document(
            outcome="refused",
            refusal=_refusal(
                "action_not_offered", f"time moves forward 1 to {MAX_MINUTES} minutes at once"
            ),
            **common,
        )
    if action.action is SimulationAction.BRING_PEOPLE:
        return _bring_people(action, context, world, common)
    if action.action in (SimulationAction.SEND_AWAY, SimulationAction.BRING_BACK):
        return _presence(action, world, clock, common)
    if action.action is SimulationAction.TAKE_IN:
        return _take_in(action, world, clock, common)
    society = clock.get("society")
    needed = [CONTROL_STEP] if action.action is SimulationAction.ADVANCE else [CONTROL]
    if action.action is SimulationAction.ADVANCE and (society or {}).get("mode") == "playing":
        needed = [CONTROL, CONTROL_STEP]
    for operation in needed:
        refused = _descriptor_refusal(operation, world)
        if refused is not None:
            bring = world.descriptor(BRING_PEOPLE) or {}
            if (
                society is None
                and bring.get("state") == "available"
                and bring.get("permitted")
                and not world.society_held
            ):
                refused["alternatives"] = [SimulationAction.BRING_PEOPLE.value]
            return _document(outcome="refused", refusal=refused, **common)
    if society is None:
        # The descriptors refuse a control before a society is brought; a read that disagrees
        # with them is answered by the clock read, which every base comes from.
        return _document(
            outcome="refused",
            refusal=_refusal("action_unavailable", "the version holds no people yet"),
            **common,
        )
    asked = _simulation_requirements(action, society)
    if asked is not None:
        return _document(outcome="clarify", clarification=asked, **common)
    if _unchanged(action, society):
        return _document(
            outcome="refused",
            refusal=_refusal(
                "no_change",
                "the playback controls already hold what the request asks for",
                operation=CONTROL,
                capability=world.descriptor(CONTROL),
            ),
            **common,
        )
    steps, asked = _simulation_steps(action, world, clock, spending)
    return _document(outcome="plan", steps=steps, spends_by=asked, **common)


def _simulation_plan(
    connection: psycopg.Connection,
    client: ModelClient,
    names: RequestNames,
    sent: str,
    session: Session,
    context: _Context,
    world: _World,
    clock: ClockReader,
    *,
    log: CallLog,
) -> dict[str, Any]:
    """The simulation branch of an utterance: draft, validate, then refuse, clarify or prepare.

    A server that states none of the simulation controls, or a grant that permits none of them,
    is refused before a draft is paid for.
    """
    stated = [
        world.descriptor(operation)
        for operation in (CONTROL, CONTROL_STEP, BRING_PEOPLE, PRESENCE, TAKE_IN)
    ]
    if not any(stated) or not any(bool(found.get("permitted")) for found in stated if found):
        return _document(
            outcome="refused",
            kind=ActionKind.SIMULATION,
            world_id=world.world_id,
            version_id=world.version_id,
            refusal=(
                _refusal(
                    "action_not_permitted",
                    "the caller's grant holds none of the simulation controls the Companion "
                    "prepares",
                    operation=CONTROL,
                    capability=world.descriptor(CONTROL),
                )
                if any(stated)
                else _refusal(
                    "action_not_offered",
                    "this server states no capability for the simulation controls",
                    operation=CONTROL,
                )
            ),
        )
    read = clock()
    drafted = _draft_simulation(client, sent, read, log=log, placeholders=names.placeholders)
    if drafted is None:
        return _document(
            outcome="refused",
            kind=ActionKind.SIMULATION,
            world_id=world.world_id,
            version_id=world.version_id,
            refusal=_refusal("not_drafted", "the model could not fill the form twice"),
            clock=read,
        )
    action = _Simulation(
        SimulationAction(drafted["action"]), speed=drafted["speed"], minutes=drafted["minutes"]
    )
    return simulation_document(
        action, context, world, read, time_spends(connection, session, world, read)
    )


def prepare_action(
    connection: psycopg.Connection,
    request: Mapping[str, Any],
    session: Session,
    *,
    world_id: str,
    capabilities: Mapping[str, Any],
    store: ContentAddressedStore | None,
    previewer: Previewer,
    clock: ClockReader,
    society: SocietyReader | None = None,
    minds: Minds | None = None,
    play: Play | None = None,
    grant: Grant | None = None,
) -> dict[str, Any]:
    """Typed actions to a plan, with no model: a clarification answered, or a later step.

    ``request`` is the route's validated body. The actions are untrusted input validated as any
    direct body is, against the same reads a plan from words uses. A simulation request comes
    alone, as the route's body holds it.
    """
    context = _Context.read(request)
    world = read_world(
        connection,
        session,
        context,
        world_id=world_id,
        capabilities=capabilities,
        store=store,
        society=society,
    )
    if world.state_sha256 != context.base_state_sha256:
        return _stale(world)
    world = _with_budget(_with_minds(world, minds), grant, None)
    if grant is not None:
        world = _with_play(world, grant, play)
    actions = request["actions"]
    if actions[0]["operation"] in SIMULATION_OPERATIONS:
        (typed,) = actions
        read = clock()
        action = _Simulation(
            SimulationAction(typed["operation"]),
            speed=typed.get("speed"),
            minutes=typed.get("minutes"),
            region_id=typed.get("region_id"),
        )
        return simulation_document(
            action, context, world, read, time_spends(connection, session, world, read)
        )
    return _world_edit_document(_typed_from_request(actions, world), context, world, previewer)


def _stale(world: _World) -> dict[str, Any]:
    return _document(
        outcome="refused",
        kind=ActionKind.WORLD_EDIT,
        world_id=world.world_id,
        version_id=world.version_id,
        refusal=_refusal(
            "stale_version",
            "the version changed since the page read it; read it again and ask again",
        ),
    )


def capabilities_listing(world: _World, appearance: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What a person can ask for here, one entry per Companion action, from the descriptors.

    Codes only: words for people are the experience owner's.
    """
    listing: list[dict[str, Any]] = []
    offered = [(operation.value, row.commit) for operation, row in _MATRIX.items()]
    offered += [
        ("control_simulation", CONTROL),
        ("advance_time", CONTROL_STEP),
        ("bring_people", BRING_PEOPLE),
        ("send_away", PRESENCE),
        ("take_in", TAKE_IN),
    ]
    for action, operation in offered:
        descriptor = world.descriptor(operation)
        listing.append(
            {
                "action": action,
                "offered": descriptor is not None,
                "operation": operation,
                "state": None if descriptor is None else descriptor.get("state"),
                "code": None if descriptor is None else descriptor.get("code"),
                "permitted": False if descriptor is None else bool(descriptor.get("permitted")),
                "effects": [] if descriptor is None else list(descriptor.get("effects", ())),
            }
        )
    listing.insert(len(_MATRIX), {"action": "change_appearance", "offered": True, **appearance})
    return listing


def question_document(world: _World) -> dict[str, Any]:
    return _document(
        outcome="question",
        kind=ActionKind.QUESTION,
        world_id=world.world_id,
        version_id=world.version_id,
    )


def capabilities_document(world: _World, appearance: Mapping[str, Any]) -> dict[str, Any]:
    return _document(
        outcome="capabilities",
        kind=ActionKind.CAPABILITIES,
        world_id=world.world_id,
        version_id=world.version_id,
        capabilities=capabilities_listing(world, appearance),
    )


def iter_labels(world: _World) -> Iterator[str]:
    """Every option label the drafter was shown, for tests that hold the form to the reads."""
    for choice in _offered(world):
        yield choice.label


# -- appearance: the style lifecycle's two requests ------------------------------------------------


def _style_state(
    connection: psycopg.Connection, session: Session, world_id: str
) -> StyleVersion | None:
    """The world's current style version, or None for a world with no reviewed appearance."""
    try:
        return WorldStyleRepository(connection, session.workspace_id, world_id=world_id).current()
    except WorldNotConfigured:
        return None


def appearance_capability(
    connection: psycopg.Connection,
    session: Session,
    world: _World,
    *,
    store: ContentAddressedStore | None,
    grant: Grant,
) -> dict[str, Any]:
    """Whether the look can be changed here, per basis, from the style domain's own reads.

    The style lifecycle is world-scoped and no version descriptor states it, so this reads what the
    appearance path itself checks: a reviewed appearance to propose against, and for the evidence
    basis, evidence the world holds.
    """
    requires, permitted = grant(STYLE_PREVIEW)
    style = _style_state(connection, session, world.world_id)
    if style is None:
        state, code = "unavailable", "world_not_configured"
        evidence = {"state": state, "code": code}
        authored = {"state": state, "code": code}
    else:
        state, code = "available", None
        cites = source_catalogue(
            connection, session.workspace_id, world_id=world.world_id, store=store
        )
        evidence = (
            {"state": "available", "code": None}
            if cites
            else {"state": "unavailable", "code": RefusalCode.NO_EVIDENCE.value}
        )
        authored = {"state": "available", "code": None}
    return {
        "operation": STYLE_PREVIEW,
        "state": state,
        "code": code,
        "requires": requires,
        "permitted": permitted,
        "bases": {EVIDENCE_BASIS: evidence, AUTHORED_DESIGN_BASIS: authored},
        "effects": [],
    }


def _appearance_document(
    connection: psycopg.Connection,
    client: ModelClient,
    sent: str,
    session: Session,
    names: RequestNames,
    log: CallLog,
    request: Mapping[str, Any],
    world: _World,
    *,
    store: ContentAddressedStore | None,
    grant: Grant,
) -> tuple[dict[str, Any], str]:
    """An appearance request as the style lifecycle's two requests, or its refusal.

    Step 0 creates the style preview: a durable proposal and preview record the lifecycle
    declares, never a change of the current look, and the person confirms it like any step.
    Step 1 applies that preview; its path takes the preview id step 0's receipt names.
    """
    common = {
        "kind": ActionKind.APPEARANCE,
        "world_id": world.world_id,
        "version_id": world.version_id,
    }
    basis = str(request.get("appearance_basis") or EVIDENCE_BASIS)
    requires, permitted = grant(STYLE_PREVIEW)
    if not permitted:
        return _document(
            outcome="refused",
            refusal=_refusal(
                "action_not_permitted",
                "the caller's grant does not hold the style lifecycle's writes",
                operation=STYLE_PREVIEW,
                capability={"operation": STYLE_PREVIEW, "requires": requires, "permitted": False},
            ),
            **common,
        ), ACTION_PROMPT_VERSION
    style = _style_state(connection, session, world.world_id)
    outcome = appearance_change(
        connection,
        client,
        sent,
        session,
        names,
        log,
        current=None if style is None else style.global_style,
        world_id=world.world_id,
        store=store,
        basis=basis,
    )
    if outcome.proposal is None:
        assert outcome.refusal is not None
        refused = outcome.refusal
        return _document(
            outcome="refused",
            refusal=_refusal(
                refused.code.value,
                refused.detail,
                operation=STYLE_PREVIEW,
                alternatives=(
                    [AUTHORED_DESIGN_BASIS] if refused.code is RefusalCode.NO_EVIDENCE else []
                ),
            ),
            **common,
        ), outcome.prompt_version
    assert style is not None
    proposal = outcome.proposal
    reference = {
        "profile_id": proposal.profile.profile_id,
        "profile_version": proposal.profile.profile_version,
        "parameters": dict(proposal.profile.parameters),
    }
    pins = {
        "base_style_version_id": str(style.version_id),
        "base_topology_digest": style.topology_digest,
    }
    drawn = {
        "profile": reference,
        "changed": list(proposal.changed),
        "modules": list(proposal.modules),
        "reference_ids": list(proposal.reference_ids),
        "appearance_basis": proposal.basis,
        "model_id": outcome.model_id,
        "prompt_version": outcome.prompt_version,
    }
    # A fresh id per plan: confirming one plan twice is refused by the lifecycle's unique id,
    # and asking again after a discard or a refusal makes a new proposal rather than meeting it.
    proposal_id = uuid.uuid4()
    preview_body = {
        "proposal_id": str(proposal_id),
        "origin": "companion",
        "origin_reference": f"companion-action-plan:{proposal_id}",
        "scope": {"kind": "global", "region_id": None},
        **pins,
        "profile": reference,
        "reference_ids": list(proposal.reference_ids),
        "model_id": outcome.model_id,
        "prompt_version": outcome.prompt_version,
        "refines_proposal_id": None,
        "appearance_basis": proposal.basis,
    }
    entry = request.get("saved_entry")
    style_entry = (
        None
        if entry is None or entry.get("style_version_id") is None
        else {key: _plain(value) for key, value in entry.items()}
    )
    apply_requires, apply_permitted = grant(STYLE_APPLY)
    steps = [
        {
            "index": 0,
            "action": {"operation": "propose_appearance", "appearance_basis": proposal.basis},
            "state": "prepared",
            "code": None,
            "operation": STYLE_PREVIEW,
            "bind": {},
            "query": {"world_id": world.world_id},
            "body": preview_body,
            "requires": requires,
            "permitted": permitted,
            # The style lifecycle's writes ask no model; the drafting was this request's own.
            "spends": False,
            "preview": {
                "operation": None,
                "body": None,
                "document": drawn,
                "document_sha256": _digest(drawn),
            },
            "pins": pins,
            "effects": [],
            "confirmation": "required",
            "replay": "proposal_id_refused",
            "receipt": "style_preview",
            "compensation": {"operation": STYLE_DISCARD},
        },
        {
            "index": 1,
            "action": {"operation": "apply_appearance", "appearance_basis": proposal.basis},
            "state": "pending",
            "code": None,
            "operation": STYLE_APPLY,
            "bind": {"preview_id": None},
            "bind_from": {"preview_id": {"step": 0, "field": "preview_id"}},
            "query": {"world_id": world.world_id},
            "body": {**pins, "saved_entry": style_entry},
            "requires": apply_requires,
            "permitted": apply_permitted,
            "spends": False,
            "preview": None,
            "pins": pins,
            "effects": [],
            "confirmation": "required",
            "replay": "invalid_preview_state_refused",
            "receipt": "style_version",
            "compensation": None,
        },
    ]
    return _document(
        outcome="plan", steps=steps, proposal_speech=proposal.spoken, **common
    ), outcome.prompt_version


# -- one utterance ---------------------------------------------------------------------------------


def _placeholders(names: RequestNames) -> tuple[tuple[str, uuid.UUID], ...]:
    return tuple((label, entity_id) for entity_id, label in names.placeholders.items())


def plan_action(
    connection: psycopg.Connection,
    client: ModelClient,
    request: Mapping[str, Any],
    session: Session,
    *,
    world_id: str,
    capabilities: Mapping[str, Any],
    store: ContentAddressedStore | None,
    previewer: Previewer,
    grant: Grant,
    clock: ClockReader,
    society: SocietyReader | None = None,
    pieces: Pieces | None = None,
    minds: Minds | None = None,
    play: Play | None = None,
) -> PlannedAction:
    """One utterance to a plan, a clarification, a refusal, what this world offers, or a question.

    ``request`` is the route's validated body. The version the page shows must still be current:
    a stale base is refused before any model is asked, so no call is spent planning against a
    state the person is no longer looking at. Every call the request pays for is recorded; an
    error that ends it carries that record to the problem body, as the appearance path's does.
    ``clock`` is read only for a simulation request.
    """
    context = _Context.read(request)
    world = read_world(
        connection,
        session,
        context,
        world_id=world_id,
        capabilities=capabilities,
        store=store,
        society=society,
    )
    if world.state_sha256 != context.base_state_sha256:
        return PlannedAction(_stale(world))
    world = _with_play(_with_minds(_with_pieces(world, grant, pieces), minds), grant, play)
    log = CallLog()
    prompt_version = ACTION_PROMPT_VERSION
    try:
        names = RequestNames.read(connection, session.workspace_id)
        sent = names.sendable(str(request["utterance"]))
        # The amounts a budget's figures come from are read from the words as they are sent.
        world = _with_budget(world, grant, sent)
        calling = client.with_attempts(log.attempt)
        kind, _classified_by = classify_action(
            calling, sent, log=log, placeholders=names.placeholders
        )
        if kind is ActionKind.WORLD_EDIT:
            document = _world_edit_plan(calling, names, sent, context, world, previewer, log=log)
        elif kind is ActionKind.APPEARANCE:
            document, prompt_version = _appearance_document(
                connection,
                calling,
                sent,
                session,
                names,
                log,
                request,
                world,
                store=store,
                grant=grant,
            )
        elif kind is ActionKind.SIMULATION:
            document = _simulation_plan(
                connection, calling, names, sent, session, context, world, clock, log=log
            )
        elif kind is ActionKind.CAPABILITIES:
            document = capabilities_document(
                world,
                appearance_capability(connection, session, world, store=store, grant=grant),
            )
        else:
            document = question_document(world)
    except Exception as failed:
        log.on_failure(prompt_version).note(failed)
        raise
    return PlannedAction(
        document, calls=log.calls, prompt_version=prompt_version, names=_placeholders(names)
    )
