"""Where a world is kept on GitHub: the GitHub projects that follow it, as their followers last
wrote it. (Not the project context of :mod:`exulanica.api.routes.world_projects`, which is what a
person keeps about their work in a world.)

``GET /world/github-projects`` answers ``exulanica.world-github-projects/v1``: each project
following the world (:mod:`exulanica.world.project_status`), newest written first, read from the
projects directory this instance is configured with (``EXULANICA_PROJECTS_DIRECTORY``, the
directory its project worker follows); with none configured, or none following the world, the list
is empty. It needs ``world.write``: only a person who may change the world sees where it is kept
and under which repository. No value a caller sends becomes a path, and nothing here reaches
GitHub.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.project_status import projects_directory, read_statuses
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["world"])


@router.get(
    "/github-projects",
    summary="The GitHub projects that keep this world, as their followers last wrote them.",
)
def world_github_projects(
    connection: ScopedConnection, session: CurrentSession, world_id: WorldId
) -> JSONResponse:
    require_world(connection, session.workspace_id, world_id)
    return JSONResponse(
        content={
            "profile": "exulanica.world-github-projects/v1",
            "world_id": world_id,
            "projects": read_statuses(projects_directory(), world_id),
        },
        headers={"Cache-Control": "private, no-store"},
    )
