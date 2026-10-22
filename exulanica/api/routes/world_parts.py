"""The parts a made world was made with, changed by a person: listed, moved, turned and removed.

``GET .../parts`` answers every part of the version's world a person may change, as it stands with
the version's changes: a site world's buildings, fixtures of a garden area and areas, with their
words and garden area (:mod:`exulanica.world.site_parts`), or a made town's buildings
(``exulanica.town-parts/v1``, below). ``POST .../parts/{part_id}/move``
stands a part at a new centre, turned a whole number of quarter turns from how it was made;
``POST .../parts/{part_id}/remove`` removes it; ``POST .../parts/{part_id}/storeys`` stands a
building taller or lower, within the storeys the kind bounds catalog its world was made under
allows. Each has a preview that writes nothing and answers what the write would.

A change is held, before anything is kept, to the records alone (inside its own garden area, clear
of every other part, path and pond), then to the place its people walk, made again from the changed
records in the kind worker: every place of the world must still be reached from its entry. A part
somebody lives or works in is not removed, and the refusal names them; it may be moved, and they
follow it, since a person's home and work name the part, not its position. A refusal is answered as
a placed thing's refused landing is: 422, its code, ``where`` and a sentence a person reads.

A change is stored as an element override naming the part (``part:<identity>``) in the version's
edit log, so ``POST .../things/undo`` and ``.../things/redo`` undo and redo it as any edit. A site
on level ground (composer version 1) and one on land (version 5) are served; on land the land is
graded again for the changed layout, and a change it cannot take is refused by the land grader's
code. A world whose things stand on its parts and one made of terrain are refused by name.

A made town's building is removed, or stood taller or lower, through the same two routes and their
previews (:mod:`exulanica.world.town_parts`): the city grammar makes the town again with the
version's changes and this one (:func:`~exulanica.world.generated_worlds.town_records_with`), and a
storey count outside the lot's range is the grammar's refusal, in words. A removal is refused while
anybody lives or works in any of the building's premises, and a lowering when it takes away a
premises somebody lives or works in, naming them, or leaves fewer homes than the people who live
there, by how many. A write asks again under the workspace's lock it takes, the lock a society
is made and steps under, and refuses as stale a change that a society made or changed since the
request read the town would refuse; a storeys preview says what the change would be
(``landing.said``: taller adds homes nobody lives in yet). A building is not moved: it stands on its
lot. A kept change queues a bake of every tile it alters, in the edit's transaction
(:func:`~exulanica.world.version_tiles.queue_version_bakes`). The parts read lists the town's
buildings as the version's changes leave them, a removed one left out.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Path, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession
from exulanica.api.routes.society_models import _society
from exulanica.api.routes.world_things import ThingEditPreviewBody
from exulanica.api.world_edit import (
    BaseStateBody,
    EntryBoundEditBody,
    ReadObjects,
    WriteObjects,
    commit_edit,
    object_problem,
)
from exulanica.api.world_scope import WorldId
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.grammar.errors import GrammarError
from exulanica.grammar.grammars.city.generation.massing import BuildingStoreysRefused
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import (
    InvalidObjectData,
    InvalidStructuralData,
    StaleObjectBase,
    UnknownWorldResource,
)
from exulanica.world.generated_worlds import (
    generation_receipt,
    states_records,
    states_site,
    town_records,
    town_records_with,
)
from exulanica.world.kinds.worker import (
    PLACE_SECONDS,
    KindWorkWaiting,
    drawing_key,
    kind_worker,
    part_check_key,
    part_job,
    parts_job,
    place_key,
    placed_of,
    site_ground_place_id,
)
from exulanica.world.object_edit_preview import preview_part_change
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import MAX_YAW_MICRORADIANS
from exulanica.world.site_parts import (
    QUARTER_TURNS,
    PartChange,
    PartChangeRefused,
    changes_document,
    changes_sha256,
    part_override,
    people_of_part,
    refused_people_words,
)
from exulanica.world.society import UnknownSociety
from exulanica.world.society_city_place import town_homes
from exulanica.world.society_living import town_routine_of
from exulanica.world.town_parts import (
    building_changes,
    homes_refusal,
    people_of_building,
    people_refusal,
    premises_of,
    premises_taken,
    residents_by_premises,
    storeys_refusal,
    storeys_words,
    town_buildings,
)
from exulanica.world.version_tiles import changed_tiles, queue_version_bakes, version_changes
from exulanica.world.workspace_lock import lock_workspace

router = APIRouter(prefix="/world", tags=["world"])

#: What a site world of each composer version is answered when a part change is asked of it.
_NOT_SERVED: dict[int, str] = {
    2: "Not yet: things stand on this world's parts, so its parts are not changed yet.",
    3: "This world is made of terrain: it has no parts to change.",
    4: "This world is made of terrain: it has no parts to change.",
}
#: The composer versions whose parts a person may change: a site on level ground (1) and one on
#: land (5), whose land is graded again for the changed layout.
_SERVED: Final = frozenset({1, 5})


class PartPoseBody(BaseModel):
    """Where a part stands, region-local (east, up, south of the site's south-west corner), and its
    turn from how it was made: on the ground, a whole number of quarter turns."""

    model_config = ConfigDict(extra="forbid")

    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)

    def change(self, part_id: str) -> PartChange:
        if self.y_mm != 0 or self.yaw_microradians not in QUARTER_TURNS:
            raise InvalidObjectData(
                "a made part stands on the ground and turns in quarter turns "
                f"(yaw one of {', '.join(str(turn) for turn in QUARTER_TURNS)})"
            )
        return PartChange(
            part_id, False, (self.x_mm, -self.z_mm), QUARTER_TURNS.index(self.yaw_microradians)
        )


class MovePartBody(EntryBoundEditBody):
    pose: PartPoseBody


class MovePartPreviewBody(ThingEditPreviewBody):
    pose: PartPoseBody


PartId = Annotated[str, Path(min_length=36, max_length=36, pattern=r"^[0-9a-f-]{36}$")]


class _Changed:
    """The changes a version holds to its world's parts, and one more."""

    changes: tuple[PartChange, ...]

    def with_change(self, change: PartChange) -> tuple[PartChange, ...]:
        return (*(c for c in self.changes if c.identity != change.identity), change)

    def current(self, part_id: str) -> PartChange | None:
        """The change the version holds for this part, or None."""
        return next((c for c in self.changes if c.identity == part_id), None)


class _Site(_Changed):
    """The version's site world as a part change reads it: its receipt, and the changes it holds."""

    def __init__(self, repository: WorldObjectRepository, version_id: uuid.UUID) -> None:
        connection = repository.connection
        snapshot_id = repository.edit_base_row(version_id)["source_snapshot_id"]
        if not states_site(connection, repository.workspace_id, repository.world_id, snapshot_id):
            raise PartChangeRefused(
                "parts_not_served",
                {"made_from_a_kind": False},
                "This world was not made from a world kind: it has no parts to change.",
            )
        self.digest, receipt = generation_receipt(
            connection, repository.workspace_id, repository.world_id, snapshot_id
        )
        self.receipt = dict(receipt)
        version = int(self.receipt["composer"]["version"])
        if version not in _SERVED:
            raise PartChangeRefused(
                "parts_not_served",
                {"composer_version": version},
                _NOT_SERVED.get(version, "This world's parts are not changed here."),
            )
        self.workspace = str(repository.workspace_id)
        self.changes = repository.part_changes(version_id)


class _Town(_Changed):
    """The version's made town as a building change reads it: its records as its receipt makes
    them, and the changes the version holds."""

    def __init__(
        self, repository: WorldObjectRepository, version_id: uuid.UUID, snapshot_id: uuid.UUID
    ) -> None:
        self.connection = repository.connection
        self.workspace_id = repository.workspace_id
        self.world_id = repository.world_id
        self.snapshot_id = snapshot_id
        self.version_id = version_id
        self.made = town_records(self.connection, self.workspace_id, self.world_id, snapshot_id)
        self.changes = repository.part_changes(version_id)

    def records(
        self, changes: tuple[PartChange, ...], part_id: str, *, tiles: bool = False
    ) -> tuple[object, ...]:
        """The town's records with ``changes``, made by its grammar; a change the grammar refuses
        is refused in words, by the part it names. With ``tiles``, the tiles the changes alter are
        found too, refused where their documents are, and kept for the queue a write makes."""
        found = building_changes(changes)
        try:
            records = town_records_with(
                self.connection, self.workspace_id, self.world_id, self.snapshot_id, found
            ).records
            if tiles:
                changed_tiles(
                    self.connection, self.workspace_id, self.world_id, self.snapshot_id, found
                )
        except BuildingStoreysRefused as exc:
            raise storeys_refusal(exc) from exc
        except GrammarError as exc:
            raise PartChangeRefused(
                "part_records_refused",
                {"part_id": part_id, "detail": str(exc)},
                "Not changed: the town cannot be made with it.",
            ) from exc
        return tuple(records)

    def queue(self) -> None:
        """Queue a bake of every tile the version's kept changes alter, in the caller's
        transaction."""
        changes = version_changes(
            self.connection, self.workspace_id, self.world_id, self.snapshot_id, self.version_id
        )
        queue_version_bakes(
            self.connection,
            self.workspace_id,
            self.world_id,
            self.snapshot_id,
            self.version_id,
            changes,
        )


def _world(repository: WorldObjectRepository, version_id: uuid.UUID) -> _Site | _Town:
    """The version's world as a part change reads it: a made town, or else a site world (any
    other world is refused by name there)."""
    snapshot_id = repository.edit_base_row(version_id)["source_snapshot_id"]
    if states_records(
        repository.connection, repository.workspace_id, repository.world_id, snapshot_id
    ):
        return _Town(repository, version_id, snapshot_id)
    return _Site(repository, version_id)


def _moved_change(site: _Changed, part_id: str, pose: PartPoseBody) -> PartChange:
    """A move or turn of ``part_id``, keeping the storeys the version states for it."""
    current = site.current(part_id)
    return dataclasses.replace(
        pose.change(part_id), storeys=None if current is None else current.storeys
    )


def _storeys_change(site: _Changed, part_id: str, storeys: int) -> PartChange:
    """``part_id`` standing ``storeys`` high, keeping where the version stands it."""
    current = site.current(part_id)
    kept = PartChange(part_id, False) if current is None or current.removed else current
    return dataclasses.replace(kept, storeys=storeys)


def _check(world: _Site | _Town, change: PartChange) -> dict[str, Any]:
    """The verdict on ``change`` made to the version's world: the part's words, the world's
    changeable parts, and for a made town what the change takes away; or the refusal raised."""
    if isinstance(world, _Town):
        return _town_check(world, change)
    return _site_check(world, change)


def _town_check(town: _Town, change: PartChange) -> dict[str, Any]:
    """The town made again with ``change``: refused where its grammar refuses it, else the
    building's words, the town's buildings, the storeys it stood and the premises the change
    takes away (those it held as made or as the version holds it, and holds no longer); for a
    lowering, the homes each premises it keeps would hold (``homes_after``, by the town's place
    under the routine its receipt names, :func:`~exulanica.world.society_city_place.town_homes`)."""
    buildings = {building.identity: building for building in town_buildings(town.made.records)}
    building = buildings.get(change.identity)
    if building is None:
        raise PartChangeRefused(
            "part_unknown", {"part_id": change.identity}, "This world has no such part."
        )
    before = town.records(town.changes, change.identity)
    after = town.records(town.with_change(change), change.identity, tiles=True)
    stood = next(
        (b.storeys for b in town_buildings(before) if b.identity == change.identity),
        building.storeys,
    )
    taken = sorted(
        set(premises_taken(town.made.records, after, change.identity))
        | set(premises_taken(before, after, change.identity))
    )
    homes_after: dict[str, int] = {}
    if change.storeys is not None and change.storeys < stood:
        homes = town_homes(after, town.made.records, town_routine_of(town.made.receipt))
        homes_after = {p: homes.get(p, 0) for p in premises_of(after, change.identity)}
    return {
        "label": building.label,
        "part_ids": list(buildings),
        "storeys": stood,
        "premises_taken": taken,
        "homes_after": homes_after,
    }


def _site_check(site: _Site, change: PartChange) -> dict[str, Any]:
    """The kind worker's verdict on ``change`` made to ``site``: the place its people would walk,
    the part's words and the world's changeable parts, kept for the society to read under the
    changed world's key; or the refusal raised."""
    changes = site.with_change(change)
    digest = changes_sha256(changes)
    place_id = site_ground_place_id()
    worker = kind_worker()
    epoch = worker.epoch
    outcome = worker.run(
        part_check_key(site.workspace, site.digest, place_id, digest, change.identity),
        PLACE_SECONDS,
        part_job,
        site.workspace,
        site.receipt,
        site.digest,
        place_id,
        changes_document(changes),
        change.identity,
        workspace=site.workspace,
        kept=worker.places,
    )
    if outcome.status != "done" or outcome.value is None:
        raise KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)
    answer = outcome.value
    if answer["status"] != "done":
        if "where" in answer:
            raise PartChangeRefused(answer["code"], answer["where"], answer["detail"])
        raise InvalidStructuralData(str(answer["detail"]))
    worker.keep_composed(
        epoch, None, (place_key(site.workspace, site.digest, place_id, digest), placed_of(answer))
    )
    return answer


def _state(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    *,
    stored: bool = False,
) -> Any:
    """The version's society's state, or None where the version has no society. ``stored`` reads it
    as stored, no input authorized, for the check a write repeats under the workspace's lock:
    authorizing there would take the asset read lock before the write composes the society's next
    input."""
    society = _society(repository.connection, session, request, repository.world_id)
    if stored:
        return society.stored_state(version_id)
    try:
        return society.snapshot(version_id)["state"]
    except UnknownSociety:
        return None


def _reads_people(world: _Site | _Town, change: PartChange, answer: dict[str, Any]) -> bool:
    """Whether the people of the version's society may refuse a change: a site part's removal, and
    a town's change that takes premises away or lowers a building's homes."""
    if isinstance(world, _Town):
        return bool(answer["premises_taken"] or answer.get("homes_after"))
    return change.removed


def _people_refusal(
    world: _Site | _Town, change: PartChange, answer: dict[str, Any], state: Any
) -> PartChangeRefused | None:
    """Why the people of a society's ``state`` refuse a change, or None: a site part removed that
    somebody lives or works in, or a town's premises taken away from somebody (all of a removed
    building's, a lowered one's upper premises), by name; and a town's lowering whose kept premises
    would hold fewer homes than the people who live there, by how many would lose a home, since
    nobody moves house."""
    if isinstance(world, _Site):
        people = people_of_part(state, change.identity)
        if not people:
            return None
        return PartChangeRefused(
            "part_houses_people",
            {"part_id": change.identity, "people": [name for name, _verb in people]},
            refused_people_words(answer["label"], people),
        )
    taken, homes = answer["premises_taken"], answer.get("homes_after") or {}
    people = people_of_building(state, taken) if taken else []
    if people:
        return people_refusal(
            people,
            building=change.identity,
            storeys=None if change.removed else change.storeys,
        )
    living = residents_by_premises(state, list(homes))
    lost = sum(max(0, count - homes[identity]) for identity, count in living.items())
    if lost and change.storeys is not None:
        return homes_refusal(lost, building=change.identity, storeys=change.storeys)
    return None


def _answered(operation: Any) -> Any:
    try:
        return operation()
    except UnknownWorldResource:
        raise
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem


@router.get(
    "/versions/{version_id}/parts",
    response_model=dict[str, object],
    summary="The parts of a site world a person may change, as they stand. Writes nothing.",
)
def read_parts(
    version_id: uuid.UUID, repository: ReadObjects, world_id: WorldId
) -> Response | dict[str, object]:
    def read() -> dict[str, object]:
        site = _world(repository, version_id)
        if isinstance(site, _Town):
            return _town_parts(site, world_id, version_id)
        changes = changes_document(site.changes)
        worker = kind_worker()
        outcome = worker.run(
            f"{drawing_key(site.workspace, site.digest, changes_sha256(site.changes))}:parts",
            PLACE_SECONDS,
            parts_job,
            site.workspace,
            site.receipt,
            site.digest,
            changes,
            workspace=site.workspace,
            kept=worker.drawings,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=True, reason=outcome.reason)
        if outcome.value["status"] != "done":
            raise InvalidStructuralData(str(outcome.value["detail"]))
        return {
            "profile": "exulanica.site-parts/v1",
            "world_id": world_id,
            "version_id": str(version_id),
            "parts": outcome.value["parts"],
            "storeys_most": outcome.value.get("storeys_most"),
            "changes": changes,
        }

    return _answered(read)


def _town_parts(town: _Town, world_id: str, version_id: uuid.UUID) -> dict[str, object]:
    """A made town's buildings as the version's changes leave them: a removed one is left out."""
    records = town.records(town.changes, "")
    return {
        "profile": "exulanica.town-parts/v1",
        "world_id": world_id,
        "version_id": str(version_id),
        "parts": [building.document() for building in town_buildings(records)],
        "changes": changes_document(town.changes),
    }


def _held(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    world: _Site | _Town,
    change: PartChange,
    answer: dict[str, Any],
) -> None:
    """Refuse a change for the people of the version's society it would leave without their home
    or their work (:func:`_people_refusal`), the society read as a person reads it: a preview and
    the change, before it is written."""
    if not _reads_people(world, change, answer):
        return
    state = _state(request, repository, session, version_id)
    refusal = None if state is None else _people_refusal(world, change, answer, state)
    if refusal is not None:
        raise refusal


def _held_still(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    world: _Site | _Town,
    change: PartChange,
    answer: dict[str, Any],
) -> None:
    """Refuse as stale a checked change that the version's society would now refuse: the write
    asks again under the workspace's lock, which a society is made and steps under, so a society
    made or changed since :func:`_held` read it is counted. The society is read as stored and its
    people are not named here; asked again, the change or its preview names them."""
    if not _reads_people(world, change, answer):
        return
    state = _state(request, repository, session, version_id, stored=True)
    if state is not None and _people_refusal(world, change, answer, state) is not None:
        raise StaleObjectBase(
            "who lives or works where changed since the change was checked; "
            "read it again and re-issue the edit"
        )


def _kept(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    body: EntryBoundEditBody,
    actor: uuid.UUID,
    world: _Site | _Town,
    change: PartChange,
    answer: dict[str, Any],
    *,
    held: Callable[[], None] | None = None,
) -> Callable[[], AlternateVersion]:
    """The write of a checked change: its override in the version's edit log and, for a made town,
    a bake queued for every tile the version's changes now alter, in the same transaction.

    ``held`` asks again whether the people of the version's society refuse the change
    (:func:`_held_still`), under the workspace's lock taken here, which the write takes again, and
    before the override is written: a society of things reads its people from the version as it
    stands."""

    def keep() -> AlternateVersion:
        if held is not None:
            lock_workspace(repository.connection, repository.workspace_id)
            held()
        version = repository.set_part_change(
            version_id,
            part_override(change),
            base_state_sha256=body.base_state_sha256,
            actor=actor,
            part_ids=frozenset(answer["part_ids"]),
            # A site's check answers where the part stood as made; a town's building never turns.
            made_centre_mm=(
                tuple(answer["made_centre_mm"]) if answer.get("made_centre_mm") else None
            ),
        )
        if isinstance(world, _Town):
            world.queue()
        return version

    return keep


Checked = tuple[_Site | _Town, PartChange, dict[str, Any]]


def _move(
    repository: WorldObjectRepository, version_id: uuid.UUID, part_id: str, pose: PartPoseBody
) -> Checked:
    world = _world(repository, version_id)
    change = _moved_change(world, part_id, pose)
    return world, change, _check(world, change)


@router.post(
    "/versions/{version_id}/parts/{part_id}/move",
    response_model=AlternateVersionView,
    summary="Stand a made part at a new centre, turned in quarter turns, where the world takes it.",
)
def move_part(
    version_id: uuid.UUID,
    part_id: PartId,
    body: MovePartBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    checked = _answered(lambda: _move(repository, version_id, part_id, body.pose))
    if isinstance(checked, Response):
        return checked
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        _kept(repository, version_id, body, session.actor, *checked),
    )


@router.post(
    "/versions/{version_id}/parts/{part_id}/move/preview",
    response_model=dict[str, object],
    summary="What moving or turning a made part would record, and whether it may. Writes nothing.",
)
def move_part_preview(
    version_id: uuid.UUID, part_id: PartId, body: MovePartPreviewBody, repository: WriteObjects
) -> Response | dict[str, object]:
    return _answered(
        lambda: _preview(
            repository,
            version_id,
            part_id,
            body.base_state_sha256,
            "move_part",
            lambda site: _moved_change(site, part_id, body.pose),
        )
    )


def _removal(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    part_id: str,
) -> Checked:
    world = _world(repository, version_id)
    change = PartChange(part_id, True)
    answer = _check(world, change)
    _held(request, repository, session, version_id, world, change, answer)
    return world, change, answer


def _kept_held(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    body: EntryBoundEditBody,
    checked: Checked,
) -> Callable[[], AlternateVersion]:
    """The write of a checked removal or storeys change, asked again under the edit's lock for the
    people of the version's society it would leave without their home or work."""
    world, change, answer = checked
    return _kept(
        repository,
        version_id,
        body,
        session.actor,
        world,
        change,
        answer,
        held=lambda: _held_still(request, repository, session, version_id, world, change, answer),
    )


@router.post(
    "/versions/{version_id}/parts/{part_id}/remove",
    response_model=AlternateVersionView,
    summary="Remove a made part nobody lives or works in, where people still reach every place.",
)
def remove_part(
    version_id: uuid.UUID,
    part_id: PartId,
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    checked = _answered(lambda: _removal(request, repository, session, version_id, part_id))
    if isinstance(checked, Response):
        return checked
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        _kept_held(request, repository, session, version_id, body, checked),
    )


@router.post(
    "/versions/{version_id}/parts/{part_id}/remove/preview",
    response_model=dict[str, object],
    summary="What removing one made part would record, and whether it may. Writes nothing.",
)
def remove_part_preview(
    version_id: uuid.UUID,
    part_id: PartId,
    body: ThingEditPreviewBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | dict[str, object]:
    return _answered(
        lambda: _preview(
            repository,
            version_id,
            part_id,
            body.base_state_sha256,
            "remove_part",
            lambda _site: PartChange(part_id, True),
            held=lambda world, change, answer: _held(
                request, repository, session, version_id, world, change, answer
            ),
        )
    )


class PartStoreysBody(EntryBoundEditBody):
    storeys: StrictInt = Field(ge=1, le=64)


class PartStoreysPreviewBody(ThingEditPreviewBody):
    storeys: StrictInt = Field(ge=1, le=64)


def _storeys(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    part_id: str,
    storeys: int,
) -> Checked:
    world = _world(repository, version_id)
    change = _storeys_change(world, part_id, storeys)
    answer = _check(world, change)
    _held(request, repository, session, version_id, world, change, answer)
    return world, change, answer


@router.post(
    "/versions/{version_id}/parts/{part_id}/storeys",
    response_model=AlternateVersionView,
    summary="Stand a made building taller or lower, within the storeys its world's kind allows.",
)
def part_storeys(
    version_id: uuid.UUID,
    part_id: PartId,
    body: PartStoreysBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    checked = _answered(
        lambda: _storeys(request, repository, session, version_id, part_id, body.storeys)
    )
    if isinstance(checked, Response):
        return checked
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        _kept_held(request, repository, session, version_id, body, checked),
    )


@router.post(
    "/versions/{version_id}/parts/{part_id}/storeys/preview",
    response_model=dict[str, object],
    summary="What standing a made building taller or lower would record. Writes nothing.",
)
def part_storeys_preview(
    version_id: uuid.UUID,
    part_id: PartId,
    body: PartStoreysPreviewBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | dict[str, object]:
    return _answered(
        lambda: _preview(
            repository,
            version_id,
            part_id,
            body.base_state_sha256,
            "part_storeys",
            lambda site: _storeys_change(site, part_id, body.storeys),
            held=lambda world, change, answer: _held(
                request, repository, session, version_id, world, change, answer
            ),
        )
    )


def _preview(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    part_id: str,
    base_state_sha256: str,
    kind: Literal["move_part", "remove_part", "part_storeys"],
    make: Callable[[_Changed], PartChange],
    *,
    held: Callable[[_Site | _Town, PartChange, dict[str, Any]], None] | None = None,
) -> dict[str, object]:
    """A move's, a removal's or a storeys change's preview: the verdict on the world's records and
    its people, then the repository's read-only checks; a refusal of either is the preview's
    ``blocked_reason`` with its words and ``where``. A made town's storeys change that may be kept
    says what it would be (``landing.said``)."""
    change = PartChange(part_id, True)
    refusal: PartChangeRefused | None = None
    part_ids: frozenset[str] = frozenset()
    said: str | None = None
    try:
        world = _world(repository, version_id)
        change = make(world)
        answer = _check(world, change)
        part_ids = frozenset(answer["part_ids"])
        if held is not None:
            held(world, change, answer)
        if isinstance(world, _Town) and change.storeys is not None:
            said = storeys_words(answer["storeys"], change.storeys)
    except PartChangeRefused as exc:
        refusal = exc
    document = preview_part_change(
        repository,
        version_id,
        kind,
        part_override(change),
        base_state_sha256=base_state_sha256,
        part_ids=part_ids,
        refusal=refusal,
    ).document()
    if said is not None and document["availability"] == "ready":
        document["landing"] = {**document["landing"], "said": said}
    return document
