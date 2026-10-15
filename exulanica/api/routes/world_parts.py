"""The parts a site world was made with, changed by a person: listed, moved, turned and removed.

``GET .../parts`` answers every part of the version's site world a person may change (each
building, each fixture of a garden area, each area), as it stands with the version's changes, with
its words and its garden area (:mod:`exulanica.world.site_parts`). ``POST .../parts/{part_id}/move``
stands a part at a new centre, turned a whole number of quarter turns from how it was made;
``POST .../parts/{part_id}/remove`` removes it. Each has a preview that writes nothing and answers
what the write would.

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
"""

from __future__ import annotations

import uuid
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
from exulanica.world.errors import InvalidObjectData, InvalidStructuralData, UnknownWorldResource
from exulanica.world.generated_worlds import generation_receipt, states_site
from exulanica.world.kinds.worker import (
    PLACE_SECONDS,
    KindWorkWaiting,
    drawing_key,
    kind_worker,
    part_check_key,
    part_job,
    parts_job,
    place_key,
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


class _Site:
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

    def with_change(self, change: PartChange) -> tuple[PartChange, ...]:
        return (*(c for c in self.changes if c.identity != change.identity), change)


def _check(site: _Site, change: PartChange) -> dict[str, Any]:
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
    placed = {key: answer[key] for key in ("status", "place", "blocked", "blocked_parts")}
    worker.keep_composed(
        epoch, None, (place_key(site.workspace, site.digest, place_id, digest), placed)
    )
    return answer


def _people(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    part_id: str,
    label: str,
) -> None:
    """Refuse removing a part somebody of the version's society lives or works in, by name."""
    society = _society(repository.connection, session, request, repository.world_id)
    try:
        state = society.snapshot(version_id)["state"]
    except UnknownSociety:
        return
    people = people_of_part(state, part_id)
    if people:
        raise PartChangeRefused(
            "part_houses_people",
            {"part_id": part_id, "people": [name for name, _verb in people]},
            refused_people_words(label, people),
        )


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
        site = _Site(repository, version_id)
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
            "changes": changes,
        }

    return _answered(read)


def _move(
    repository: WorldObjectRepository, version_id: uuid.UUID, part_id: str, pose: PartPoseBody
) -> tuple[PartChange, dict[str, Any]]:
    change = pose.change(part_id)
    return change, _check(_Site(repository, version_id), change)


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
    change, answer = checked
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.set_part_change(
            version_id,
            part_override(change),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
            part_ids=frozenset(answer["part_ids"]),
        ),
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
        lambda: _preview(repository, version_id, part_id, body.base_state_sha256, body.pose)
    )


def _removal(
    request: Request,
    repository: WorldObjectRepository,
    session: Any,
    version_id: uuid.UUID,
    part_id: str,
) -> tuple[PartChange, dict[str, Any]]:
    change = PartChange(part_id, True)
    answer = _check(_Site(repository, version_id), change)
    _people(request, repository, session, version_id, part_id, answer["label"])
    return change, answer


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
    change, answer = checked
    return commit_edit(
        request,
        repository,
        version_id,
        body,
        lambda: repository.set_part_change(
            version_id,
            part_override(change),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
            part_ids=frozenset(answer["part_ids"]),
        ),
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
            None,
            people=lambda label: _people(request, repository, session, version_id, part_id, label),
        )
    )


def _preview(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    part_id: str,
    base_state_sha256: str,
    pose: PartPoseBody | None,
    *,
    people: Any = None,
) -> dict[str, object]:
    """A move's or a removal's preview: the worker's verdict, then the repository's read-only
    checks; a refusal of either is the preview's ``blocked_reason`` with its words and ``where``."""
    kind: Literal["move_part", "remove_part"] = "remove_part" if pose is None else "move_part"
    change = PartChange(part_id, True) if pose is None else pose.change(part_id)
    refusal: PartChangeRefused | None = None
    part_ids: frozenset[str] = frozenset()
    try:
        answer = _check(_Site(repository, version_id), change)
        part_ids = frozenset(answer["part_ids"])
        if people is not None:
            people(answer["label"])
    except PartChangeRefused as exc:
        refusal = exc
    return preview_part_change(
        repository,
        version_id,
        kind,
        part_override(change),
        base_state_sha256=base_state_sha256,
        part_ids=part_ids,
        refusal=refusal,
    ).document()
