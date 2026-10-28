"""Where a world is kept on GitHub: the GitHub projects that follow it, as their followers last
wrote it, and a person's request to start keeping it. (Not the project context of
:mod:`exulanica.api.routes.world_projects`, which is what a person keeps about their work in a
world.)

``GET /world/github-projects`` answers ``exulanica.world-github-projects/v1``: each project
following the world (:mod:`exulanica.world.project_status`), newest written first, and each
request to keep it in a project that its follower has not taken yet
(:mod:`exulanica.world.project_requests`), read from the projects directory this instance is
configured with (``EXULANICA_PROJECTS_DIRECTORY``, the directory its project worker follows); with
none configured, or none following the world, both lists are empty. A project's status names no
workspace (its follower holds one bearer and is told none), so it is answered only where the
requester's workspace holds the version it follows: version identities are the server's own, so
one install's projects of another workspace's world under the same id are never shown.

``GET /world/github-projects/kept`` names no world and answers
``exulanica.world-github-keeping/v1`` for the requester's workspace: whether this instance keeps
worlds in projects at all (``kept_here``: a projects directory is configured, as the routes below
decide it) and how many of the workspace's worlds a project linked to a GitHub repository keeps
(``on_github``). It reads the statuses a world's own read reads and, as that read does, keeps only
those following a version the workspace holds, so another workspace's world under the same id is
never counted; a world counts once however many projects keep it, and none is 0.

``POST /world/github-projects`` asks the follower to keep a version of the world in a project, its
readable text kept or not, and answers the request (202): the follower takes it on its next scan,
makes the project's folder itself and removes the request, or marks it refused by a code. A world
has one request at a time; asked again while one waits, the route answers that one. Only a
version the requester's workspace holds is taken (404 ``unknown_reference`` else, as for
another workspace's world); where no projects directory is configured, 409
``projects_not_kept``. ``DELETE /world/github-projects/requests/{request_id}`` withdraws one of the
world's requests of either kind below (204; 404 ``unknown_reference`` for none such; 409
``publication_started`` for a repository being created).

``POST /world/github-projects/publications`` asks the follower to put a project it keeps on the
person's own GitHub, named by the project's identity as its status states it, with the repository
name the person chose or none (the follower then proposes one), and answers the request (202):
the follower reviews it with the person's GitHub CLI, writing nothing on GitHub, and the review is
answered in ``publications`` with the rest of the world's. Only a project whose status names this
world at a version the requester's workspace holds is taken (404 ``unknown_reference`` else), one
already linked to a repository is refused 409 ``project_linked``, and one whose repository is
being created 409 ``publication_started``. ``POST
/world/github-projects/publications/{request_id}/create`` is the person's yes to that review,
bound to its ``review_sha256`` (202): the follower then creates the private repository, links the
project to publish on its own and publishes it. It is refused 409 ``publication_not_reviewed``
before a review, ``publication_review_changed`` for another digest, ``publication_refused`` for a
refused request and ``publication_started`` once creating began. The server never runs the GitHub
CLI and holds no credential of the person's.

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
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.project_requests import (
    RepositoryName,
    RequestConflict,
    RequestRefused,
    confirm_publication,
    read_publications,
    read_requests,
    request_project,
    request_publication,
    withdraw_request,
)
from exulanica.world.project_status import projects_directory, read_every_status, read_statuses
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["world"])

_NO_STORE = {"Cache-Control": "private, no-store"}
_REQUEST_ID = "^[0-9a-f]{32}$"


def _conflict(exc: RequestConflict) -> JSONResponse:
    return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})


def _not_kept() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"code": "projects_not_kept", "detail": "this server keeps no world's project"},
    )


def _held(
    connection: ScopedConnection, session: CurrentSession, statuses: list[dict]
) -> list[dict]:
    """The statuses that follow a version the requester's workspace holds, in the world each
    names."""
    asked = []
    for status in statuses:
        try:
            asked.append(uuid.UUID(status["version_id"]))
        except ValueError:
            continue  # not a version identity the server made: held by nobody here
    if not asked:
        return []
    rows = connection.execute(
        "select world_id, version_id from world_alternate_version where workspace_id=%s "
        "and version_id = any(%s)",
        (session.workspace_id, asked),
    ).fetchall()
    held = {(row["world_id"], str(row["version_id"])) for row in rows}
    return [status for status in statuses if (status["world_id"], status["version_id"]) in held]


class ProjectRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The version to keep: one of this world's, held by the requester's workspace.
    version_id: uuid.UUID
    #: Whether the project keeps readable text (names and words a person wrote); such a project
    #: publishes only to a private repository.
    readable: StrictBool = False


class PublicationRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The project to put on GitHub, by the identity its status states.
    project_id: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9:._/-]+$")
    #: The repository's name, or none for the follower to propose one.
    name: RepositoryName | None = None


class PublicationCreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: The review the person said yes to, by its digest.
    review_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


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
            "projects": _held(connection, session, read_statuses(directory, world_id)),
            "requests": read_requests(directory, (str(session.workspace_id), world_id)),
            "publications": read_publications(directory, (str(session.workspace_id), world_id)),
        },
        headers=_NO_STORE,
    )


@router.get(
    "/github-projects/kept",
    summary="Whether this server keeps worlds, and how many of the workspace's are on GitHub.",
)
def world_github_keeping(connection: ScopedConnection, session: CurrentSession) -> JSONResponse:
    directory = projects_directory()
    linked = [status for status in read_every_status(directory) if status["link"] is not None]
    return JSONResponse(
        content={
            "profile": "exulanica.world-github-keeping/v1",
            "kept_here": directory is not None,
            "on_github": len({status["world_id"] for status in _held(connection, session, linked)}),
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
        return _not_kept()
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
    request_id: Annotated[str, Path(pattern=_REQUEST_ID)],
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    require_world(connection, session.workspace_id, world_id)
    try:
        withdrawn = withdraw_request(
            projects_directory(), request_id, (str(session.workspace_id), world_id)
        )
    except RequestConflict as exc:
        return _conflict(exc)
    except RequestRefused:
        withdrawn = False
    if not withdrawn:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no such request"}
        )
    return Response(status_code=204)


@router.post(
    "/github-projects/publications",
    status_code=202,
    summary="Ask the project worker to put a project it keeps on the person's own GitHub.",
)
def request_world_github_publication(
    body: PublicationRequestBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> JSONResponse:
    directory = projects_directory()
    if directory is None:
        return _not_kept()
    require_world(connection, session.workspace_id, world_id)
    statuses = _held(
        connection,
        session,
        [
            status
            for status in read_statuses(directory, world_id)
            if status["project_id"] == body.project_id
        ],
    )
    if not statuses:
        raise UnknownWorldResource("no such project")
    if any(status["link"] is not None for status in statuses):
        return JSONResponse(
            status_code=409,
            content={"code": "project_linked", "detail": "this project is linked to a repository"},
        )
    try:
        document = request_publication(
            directory,
            workspace_id=str(session.workspace_id),
            world_id=world_id,
            version_id=statuses[0]["version_id"],
            project_id=body.project_id,
            name=body.name,
            now=datetime.now(UTC),
        )
    except RequestConflict as exc:
        return _conflict(exc)
    except RequestRefused as exc:
        return JSONResponse(
            status_code=409, content={"code": "project_request_refused", "detail": str(exc)}
        )
    return JSONResponse(status_code=202, content=document, headers=_NO_STORE)


@router.post(
    "/github-projects/publications/{request_id}/create",
    status_code=202,
    summary="Say yes to the review of putting a project on GitHub: the worker creates it.",
)
def create_world_github_publication(
    request_id: Annotated[str, Path(pattern=_REQUEST_ID)],
    body: PublicationCreateBody,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> JSONResponse:
    directory = projects_directory()
    if directory is None:
        return _not_kept()
    require_world(connection, session.workspace_id, world_id)
    try:
        document = confirm_publication(
            directory,
            request_id,
            (str(session.workspace_id), world_id),
            body.review_sha256,
            datetime.now(UTC),
        )
    except RequestConflict as exc:
        return _conflict(exc)
    except RequestRefused:
        document = None
    if document is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "no such request"}
        )
    return JSONResponse(status_code=202, content=document, headers=_NO_STORE)
