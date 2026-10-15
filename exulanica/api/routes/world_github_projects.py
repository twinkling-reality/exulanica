"""Where a world is kept on GitHub: the GitHub projects that follow it, as their followers last
wrote it, and a person's request to start keeping it. (Not the project context of
:mod:`exulanica.api.routes.world_projects`, which is what a person keeps about their work in a
world.)

``GET /world/github-projects`` answers ``exulanica.world-github-projects/v1``: each project
following the world (:mod:`exulanica.world.project_status`), newest written first, and each
request to keep it in a project that its follower has not taken yet
(:mod:`exulanica.world.project_requests`), read from the projects directory this instance is
configured with (``EXULANICA_PROJECTS_DIRECTORY``, the directory its project worker follows); with
none configured, or none following the world, both lists are empty.

``POST /world/github-projects`` asks the follower to keep a version of the world in a project, its
readable text kept or not, and answers the request (202): the follower takes it on its next scan,
makes the project's folder itself and removes the request, or marks it refused by a code. A world
has one request at a time; asked again while one waits, the route answers that one. Only a
version the requester's workspace holds is taken (404 ``unknown_reference`` else, as for
another workspace's world); where no projects directory is configured, 409
``projects_not_kept``. ``DELETE /world/github-projects/requests/{request_id}`` withdraws one of the
world's requests (204; 404 ``unknown_reference`` for none such).

They need ``world.write``: only a person who may change the world sees where it is kept and asks
for it to be kept. No value a caller sends becomes a path, no answer holds one, and nothing here
reaches GitHub.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Path
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, StrictBool

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.project_requests import (
    RequestRefused,
    read_requests,
    request_project,
    withdraw_request,
)
from exulanica.world.project_status import projects_directory, read_statuses
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["world"])

_NO_STORE = {"Cache-Control": "private, no-store"}


class ProjectRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The version to keep: one of this world's, held by the requester's workspace.
    version_id: uuid.UUID
    #: Whether the project keeps readable text (names and words a person wrote); such a project
    #: publishes only to a private repository.
    readable: StrictBool = False


@router.get(
    "/github-projects",
    summary="The GitHub projects that keep this world, as their followers last wrote them.",
)
def world_github_projects(
    connection: ScopedConnection, session: CurrentSession, world_id: WorldId
) -> JSONResponse:
    require_world(connection, session.workspace_id, world_id)
    directory = projects_directory()
    return JSONResponse(
        content={
            "profile": "exulanica.world-github-projects/v1",
            "world_id": world_id,
            "projects": read_statuses(directory, world_id),
            "requests": read_requests(directory, (str(session.workspace_id), world_id)),
        },
        headers=_NO_STORE,
    )


@router.post(
    "/github-projects",
    status_code=202,
    summary="Ask the project worker to keep a version of this world in a project.",
)
def request_world_github_project(
    body: ProjectRequestBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> JSONResponse:
    directory = projects_directory()
    if directory is None:
        return JSONResponse(
            status_code=409,
            content={"code": "projects_not_kept", "detail": "this server keeps no world's project"},
        )
    require_world(connection, session.workspace_id, world_id)
    held = connection.execute(
        "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
        "and version_id=%s",
        (session.workspace_id, world_id, body.version_id),
    ).fetchone()
    if held is None:
        raise UnknownWorldResource("no such alternate version")
    try:
        document = request_project(
            directory,
            workspace_id=str(session.workspace_id),
            world_id=world_id,
            version_id=str(body.version_id),
            readable=body.readable,
            now=datetime.now(UTC),
        )
    except RequestRefused as exc:
        return JSONResponse(
            status_code=409, content={"code": "project_request_refused", "detail": str(exc)}
        )
    return JSONResponse(status_code=202, content=document, headers=_NO_STORE)


@router.delete(
    "/github-projects/requests/{request_id}",
    status_code=204,
    summary="Withdraw a request to keep this world in a project.",
)
def withdraw_world_github_project_request(
    request_id: Annotated[str, Path(pattern="^[0-9a-f]{32}$")],
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    require_world(connection, session.workspace_id, world_id)
    try:
        withdrawn = withdraw_request(
            projects_directory(), request_id, (str(session.workspace_id), world_id)
        )
    except RequestRefused:
        withdrawn = False
    if not withdrawn:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no such request"}
        )
    return Response(status_code=204)
