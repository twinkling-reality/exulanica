"""Dressing a saved world with a scene, the way a server lays one into a new world.

:func:`dress_saved_world` lays a scene (:mod:`exulanica.world.scenes`) into a saved world from the
world's own arrival, through the same paths a person's edits and choices take:

1.  each thing is placed with the edit the things route makes
    (:meth:`~exulanica.world.object_repository.WorldObjectRepository.add_thing`), inside the binding
    to the saved entry every authored edit runs in (:func:`~exulanica.api.world_edit.bound_edit`),
    so the world reopens with it. The owner's own edits stand: a thing already placed as the
    scene places it is left as it is, and so is one of the same kind the owner moved, one the
    owner removed and one whose placing the owner undid, each listed; only a thing of another kind
    under the scene's id is refused (``scene_thing_placed_otherwise``);
2.  the version's society is made on the scene's engine as the society route makes one
    (:func:`~exulanica.api.society_making.make_society`), in the arrival's region; a refusal,
    such as a host that does not offer the engine, keeps the things placed and is answered by its
    code;
3.  each of the scene's minds is recorded as the world owner's choice for that being
    (``SocietyModelChoiceRepository.record_choice``, under the people's role), keyed by the scene's
    digest, the society and the thing in the demo builder's own namespace, so asking again, or
    dressing a world the builder built, records nothing new. A model the role does not take is
    refused for that being alone, by its code, and the routine decides for it. The owner's later
    choice stands: the latest choice decides, and what is reported is the scene's own choice.

Every refusal comes back by code: a scene's own (:class:`~exulanica.world.scenes.SceneRefused`),
an edit's (as the authored-edit routes answer it,
:func:`~exulanica.api.world_edit.object_problem_code`) and the society's (as the society routes
answer it, in the society field of the answer).

The gate travellers come through and the mind they are given are the grant's, recorded by the door
when the world's owner opens the gate, never here. Nothing here names a scene, a kind or a thing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from psycopg import pq

from exulanica.api.society_making import SocietyHooks, make_society, society_refusal
from exulanica.api.world_edit import (
    SavedEntryAdvanceBody,
    bound_edit,
    object_problem_code,
    writing_repository,
)
from exulanica.models.manifest import load_manifest
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.objects import ObjectOrigin
from exulanica.world.placed_things import ThingPlacement, named_kind
from exulanica.world.saved_entries import SavedWorldEntryRepository
from exulanica.world.scenes import Scene, SceneArrival, SceneRefused, places, scene_arrival
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)

__all__ = ["DRESSING_PROFILE", "MINDS_NAMESPACE", "DressedWorld", "dress_saved_world"]

DRESSING_PROFILE: Final = "exulanica.scene-dressing/v1"
#: The namespace of the keys a scene's minds are recorded under, the demo builder's own
#: (``scripts/demo/build_scene.py``): the same scene, society and thing always give the same key,
#: so asking again, from here or from the builder, is answered with the choice already recorded.
MINDS_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica.demo-scene-build/v1/minds")


@dataclass(frozen=True, slots=True)
class _Edit:
    """One edit's base and the saved entry it advances, as every authored edit body states them."""

    base_state_sha256: str
    saved_entry: SavedEntryAdvanceBody


@dataclass(frozen=True, slots=True)
class DressedWorld:
    """What a dressing did: the scene by digest, the world and version, the things it placed now and
    the ones it left as the owner left them, the version's state, the society (its id and state, or
    the code of its refusal) and each mind with the code of its refusal, if any."""

    scene: dict[str, Any]
    world_id: str
    entry_id: uuid.UUID
    version_id: uuid.UUID
    things_added: int
    #: The scene's things the owner moved, of the same kind, left where the owner put them.
    things_left_moved: tuple[str, ...]
    #: The scene's things the owner removed, which stay removed.
    things_left_removed: tuple[str, ...]
    #: The scene's things whose placing the owner undid, which stay out.
    things_left_undone: tuple[str, ...]
    state_sha256: str
    edit_seq: int
    society: dict[str, Any]
    minds: tuple[dict[str, Any], ...]

    def document(self) -> dict[str, Any]:
        return {
            "profile": DRESSING_PROFILE,
            "scene": self.scene,
            "world_id": self.world_id,
            "entry_id": str(self.entry_id),
            "version_id": str(self.version_id),
            "things_added": self.things_added,
            "things_left_moved": list(self.things_left_moved),
            "things_left_removed": list(self.things_left_removed),
            "things_left_undone": list(self.things_left_undone),
            "state_sha256": self.state_sha256,
            "edit_seq": self.edit_seq,
            "society": self.society,
            "minds": list(self.minds),
        }


def _undone(version: Any, thing_id: str) -> bool:
    """Whether the owner undid this thing's newest placing: an undo names the newest add_thing
    edit of its id. Undo is a stack and an undo is never itself undone, so a thing placed again
    after an undo answers by its newest placing, not by an older one."""
    placings = [
        edit for edit in version.edits if edit.kind == "add_thing" and edit.thing_id == thing_id
    ]
    if not placings:
        return False
    newest = max(placings, key=lambda edit: edit.edit_seq).edit_id
    return any(edit.kind == "undo" and edit.undone_edit_id == newest for edit in version.edits)


def dress_saved_world(
    hooks: SocietyHooks, connection: Any, session: Any, entry_id: uuid.UUID, scene: Scene
) -> DressedWorld:
    """Lay ``scene`` into the saved world ``entry_id`` names, in ``session``'s workspace and as its
    actor, and answer what was done, or refuse by code.

    Preconditions, which this checks only in part: the caller has already found the actor allowed
    to change the world and to cause what its minds spend (``world.write`` and ``model.invoke`` on
    the workspace, which a guest's own workspace holds); nothing here checks a permission. The
    connection is the workspace's, idle and outside any transaction: each step commits its own, so
    a dressing stopped part way is finished by asking again, and a society of things is made only
    on an idle connection; a connection inside a transaction is refused before anything is read.
    """
    if connection.info.transaction_status != pq.TransactionStatus.IDLE:
        raise RuntimeError("a dressing needs an idle connection: each of its steps commits its own")
    entries = SavedWorldEntryRepository(connection, session.workspace_id, hooks.services.store)
    try:
        entry = entries.entry(entry_id)
    except UnknownWorldResource as exc:
        raise SceneRefused(
            "scene_world_unknown", "this workspace holds no such saved world"
        ) from exc
    arrival = scene_arrival(entry)
    laid = places(scene, arrival)
    world_id, version_id = entry.world_id, entry.authored_version_id
    repository = writing_repository(
        connection, session, hooks.services, hooks.authored_edit, world_id
    )
    added = 0
    left: dict[str, list[str]] = {"moved": [], "removed": [], "undone": []}
    for thing_id, kind, transform in laid:
        version = repository.version(version_id, with_availability=False)
        reference = named_kind(kind["kind"], kind["version"])
        current = next((thing for thing in version.things if thing.thing_id == thing_id), None)
        if current is not None and current.removed:
            # A removal is the owner's own edit, and a dressing never undoes it.
            left["removed"].append(thing_id)
            continue
        if current is None and _undone(version, thing_id):
            # So is an undo of its placing: the thing stays out.
            left["undone"].append(thing_id)
            continue
        if current is not None:
            if current.kind != reference:
                raise SceneRefused(
                    "scene_thing_placed_otherwise",
                    f"{thing_id} is placed already, as another kind",
                )
            if (current.region_id, current.transform) != (arrival.region_id, transform):
                left["moved"].append(thing_id)
            continue
        bound = entries.entry(entry_id)
        edit = _Edit(
            base_state_sha256=version.state_sha256,
            saved_entry=SavedEntryAdvanceBody(
                entry_id=entry_id,
                base_revision=bound.revision,
                authored_state_sha256=bound.authored_state_sha256,
                authored_edit_seq=bound.authored_edit_seq,
            ),
        )
        placement = ThingPlacement(
            thing_id=thing_id,
            kind=reference,
            region_id=arrival.region_id,
            transform=transform,
            origin=ObjectOrigin("authored", "fictional"),
        )
        try:
            bound_edit(
                repository,
                version_id,
                edit,
                lambda placement=placement, base=version.state_sha256: repository.add_thing(
                    version_id, placement, base_state_sha256=base, actor=session.actor
                ),
            )
        except Exception as exc:
            answer = object_problem_code(exc)
            if answer is None:
                raise
            raise SceneRefused(answer[1], f"{thing_id}: {exc}") from exc
        added += 1
    version = repository.version(version_id, with_availability=False)
    entry = entries.entry(entry_id)
    if (entry.authored_state_sha256, entry.authored_edit_seq) != (
        version.state_sha256,
        version.edit_seq,
    ):
        raise SceneRefused(
            "scene_world_moved", "the saved world does not reopen at the version dressed"
        )
    society, minds = _bring_to_life(
        hooks, connection, session, world_id, version_id, scene, arrival
    )
    return DressedWorld(
        scene=scene.reference(),
        world_id=world_id,
        entry_id=entry_id,
        version_id=version_id,
        things_added=added,
        things_left_moved=tuple(left["moved"]),
        things_left_removed=tuple(left["removed"]),
        things_left_undone=tuple(left["undone"]),
        state_sha256=version.state_sha256,
        edit_seq=version.edit_seq,
        society=society,
        minds=minds,
    )


def _bring_to_life(
    hooks: SocietyHooks,
    connection: Any,
    session: Any,
    world_id: str,
    version_id: uuid.UUID,
    scene: Scene,
    arrival: SceneArrival,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]:
    """The version's society on the scene's engine and each mind recorded; or, when the society is
    refused, the code of its refusal and no mind. The society's answer always has the same four
    fields."""
    engine = scene.document["engine"]
    try:
        made = make_society(
            hooks,
            connection,
            session,
            world_id,
            version_id,
            region_id=arrival.region_id,
            profile=engine,
        )
    except Exception as exc:
        refusal = society_refusal(exc)
        if refusal is None:
            raise
        refused = {"society_id": None, "engine": engine, "state_sha256": None}
        return {**refused, "refused": refusal.code}, ()
    people = {
        person["placed_id"]: person["id"]
        for person in made["state"]["inhabitants"]
        if person.get("came_by") == "placed"
    }
    role = person_role()
    manifest = load_manifest()
    contract = role.contract()
    choices = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    minds = []
    for mind in scene.document["minds"]:
        person = people.get(mind["thing_id"])
        decider = mind["decider"]
        model = (
            None
            if decider["kind"] == "routine"
            else {"provider": decider["provider"], "model_id": decider["model_id"]}
        )
        recorded: dict[str, Any] = {
            "thing_id": mind["thing_id"],
            "person_id": person,
            "model": model,
        }
        if person is None:
            minds.append({**recorded, "refused": "person_not_in_this_world"})
            continue
        key = uuid.uuid5(MINDS_NAMESPACE, f"{scene.sha256}:{made['society_id']}:{mind['thing_id']}")
        try:
            choices.record_choice(
                version_id,
                role,
                request_id=key,
                subjects=[person],
                model=model,
                chosen_by=session.actor,
                manifest=manifest,
                contract=contract,
            )
        except ModelChoiceRefused as exc:
            minds.append({**recorded, "refused": exc.code})
            continue
        minds.append({**recorded, "refused": None})
    society = {
        "society_id": made["society_id"],
        "engine": made["profile"],
        "state_sha256": made["state_sha256"],
        "refused": None,
    }
    return society, tuple(minds)
