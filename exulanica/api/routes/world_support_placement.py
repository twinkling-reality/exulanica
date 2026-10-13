"""Explicit, source-bound placement of passive rigid things on admitted site supports."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field, StrictInt

from exulanica.api.dependencies import CurrentSession
from exulanica.api.routes.world_things import ThingKindBody, WorkspaceKindBody
from exulanica.api.world_edit import (
    EntryBoundEditBody,
    ReadObjects,
    WriteObjects,
    commit_edit,
    object_problem,
)
from exulanica.api.world_version_document import AlternateVersionView
from exulanica.world.objects import MAX_YAW_MICRORADIANS, ObjectOrigin, Transform
from exulanica.world.placed_things import (
    UNSCALED_MILLI,
    ThingPlacement,
    named_kind,
    placed_thing_document,
    read_support_reference,
    workspace_kind_reference,
)
from exulanica.world.support_placement import SupportPlacementRefused
from exulanica.world.support_placement_source import (
    SupportPlacementSource,
    placed_kind,
    prepare_support_source,
    validate_bound_thing,
)

router = APIRouter(prefix="/world", tags=["world"])


class SupportedThingBody(EntryBoundEditBody):
    thing_id: str = Field(min_length=1, max_length=200)
    kind: ThingKindBody | WorkspaceKindBody
    region_id: str = Field(min_length=1, max_length=160)
    position_mm: tuple[StrictInt, StrictInt]
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)
    origin_role: Literal["fictional", "personal"]
    support: dict[str, Any]


def _placement(body: SupportedThingBody, source: SupportPlacementSource) -> ThingPlacement:
    reference = read_support_reference(body.support)
    surface = next(
        (
            s
            for s in source.network.document()["surfaces"]
            if s["surface_id"] == reference.surface_id
        ),
        None,
    )
    if surface is None:
        raise SupportPlacementRefused("support.surface_id", "names no admitted surface")
    return ThingPlacement(
        body.thing_id,
        workspace_kind_reference(body.kind.sha256)
        if isinstance(body.kind, WorkspaceKindBody)
        else named_kind(body.kind.kind, body.kind.version, body.kind.sha256),
        body.region_id,
        Transform(
            body.position_mm[0],
            surface["support_z_mm"],
            body.position_mm[1],
            body.yaw_microradians,
            UNSCALED_MILLI,
        ),
        ObjectOrigin("authored", body.origin_role),
    )


def _problem(exc: Exception) -> JSONResponse:
    if isinstance(exc, SupportPlacementRefused):
        return JSONResponse(
            status_code=422, content={"code": exc.code, "detail": exc.detail, "where": exc.where}
        )
    problem = object_problem(exc)
    if problem is None:
        raise exc
    return problem


@router.post(
    "/versions/{version_id}/things/on-support/preview",
    summary="Check passive rigid thing placement against an exact source support and state.",
)
def preview_supported_thing(
    version_id: Annotated[uuid.UUID, Path()], body: SupportedThingBody, repository: ReadObjects
) -> JSONResponse:
    try:
        source = prepare_support_source(
            repository, version_id, base_state_sha256=body.base_state_sha256
        )
        thing, receipt = repository.validate_thing_on_support(
            version_id,
            _placement(body, source),
            body.support,
            source,
            base_state_sha256=body.base_state_sha256,
        )
    except Exception as exc:
        return _problem(exc)
    return JSONResponse(
        content={
            "profile": "exulanica.support-placement-preview/v1",
            "placement": placed_thing_document(thing),
            "receipt": receipt.document(),
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.post(
    "/versions/{version_id}/things/on-support",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Save a passive rigid thing with explicit admitted support affinity.",
)
def place_supported_thing(
    version_id: Annotated[uuid.UUID, Path()],
    body: SupportedThingBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    try:
        source = prepare_support_source(
            repository, version_id, base_state_sha256=body.base_state_sha256
        )
        placement = _placement(body, source)
        return commit_edit(
            request,
            repository,
            version_id,
            body,
            lambda: repository.add_thing_on_support(
                version_id,
                placement,
                body.support,
                source,
                base_state_sha256=body.base_state_sha256,
                actor=session.actor,
            ),
        )
    except Exception as exc:
        return _problem(exc)


@router.get(
    "/versions/{version_id}/things/{thing_id}/support",
    summary="Read a placed thing's support affinity and current bounded clearance availability.",
)
def read_thing_support(
    version_id: Annotated[uuid.UUID, Path()],
    thing_id: Annotated[str, Path(max_length=200)],
    repository: ReadObjects,
) -> JSONResponse:
    version = repository.version(version_id)
    thing = repository._require_thing(version_id, thing_id)
    result = {
        "profile": "exulanica.support-placement-availability/v1",
        "thing_id": thing_id,
        "version_id": str(version_id),
        "state_sha256": version.state_sha256,
        "support": None if thing.support is None else thing.support.document(),
        "availability": "unbound"
        if thing.support is None
        else "removed"
        if thing.removed
        else "available",
        "code": None,
        "where": None,
        "society": {"availability": "not_applicable", "reason": None},
    }
    if thing.support is not None and not thing.removed:
        try:
            source = prepare_support_source(
                repository, version_id, base_state_sha256=version.state_sha256
            )
            validate_bound_thing(repository, version, thing, source)
            from exulanica.world.society_authored_ground import (
                read_authored_ground,
                supported_things_projection,
            )

            ground = read_authored_ground(
                repository.connection,
                repository.workspace_id,
                repository.world_id,
                version.source_snapshot_id,
                region_id=thing.region_id,
            )
            kinds = {}
            for current in version.things:
                if not current.removed and current.region_id == thing.region_id:
                    try:
                        kinds[current.thing_id] = placed_kind(repository, current)
                    except SupportPlacementRefused:
                        continue
            if ground is None:
                reason, records = "supported_thing_source_unavailable", []
            else:
                _, records, reason = supported_things_projection(version, ground, kinds, source)
            result["society"] = {
                "availability": "unavailable" if reason else "omitted",
                "reason": reason,
                "unavailable_affordances": records,
            }
        except SupportPlacementRefused as exc:
            result.update(availability="unavailable", code=exc.code, where=exc.where)
            result["society"] = {
                "availability": "unavailable",
                "reason": "supported_thing_clearance_unavailable",
            }
        except Exception as exc:
            return _problem(exc)
    return JSONResponse(content=result, headers={"Cache-Control": "private, no-store"})
