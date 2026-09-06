"""The World Read API: the one route a generative world model reads a real place through.

Roadmap Phase 10 capability 1. The bundle and every decision inside it are
:mod:`exulanica.graph.world_read`, one layer down. What is left here is the route: take the
workspace off the session, ask for one scene, and turn "not readable" into the same answer for
every reason it might not be readable.

Three things this route does that are not obvious.

**404 for a foreign scene, never 403.** The evaluation methodology's M10 requires it: a 403 would
confirm that a scene id exists and belongs to somebody, which is exactly what a cross-tenant probe
is looking for. Nonexistent and foreign ids are indistinguishable from outside.

**410 for a withdrawn scene, and it comes for free.** The bundle is built from
``reconstruction_scene_rows``, whose query already excludes anything ``tombstone_blocks_scene``
covers, so a withdrawn scene simply is not there and the caller receives 404. That is not good
enough for a caller holding a bundle from before the deletion, so the withdrawal is checked
explicitly and answered 410: the fact that a person deleted something is a fact they are entitled
to, and it is different from the thing never having existed.

**Read-only connection.** A route that hands a world model everything it may condition on is the
last place that should hold a connection able to write.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.services import Services
from exulanica.graph.observations import scene_observations
from exulanica.graph.world_read import world_read_bundle

router = APIRouter(prefix="/world-read", tags=["world-read"])


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _withdrawn(connection: Any, workspace: uuid.UUID, scene_id: uuid.UUID) -> bool:
    """Whether this workspace's own scene was withdrawn, as opposed to never existing.

    Asked only after the bundle came back empty, and only about a scene row that is in this
    workspace, so the answer cannot distinguish another tenant's ids from absent ones.
    """
    row = connection.execute(
        "select tombstone_blocks_scene(%s, %s) as blocked "
        "from reconstruction_scene where workspace_id = %s and scene_id = %s",
        (workspace, scene_id, workspace, scene_id),
    ).fetchone()
    return bool(row is not None and row["blocked"])


@router.get(
    "/scenes/{scene_id}",
    summary="What a generative world model may condition on for one scene, digest-bound.",
)
def scene_bundle(
    scene_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        bundle = world_read_bundle(connection, session.workspace_id, scene_id, services.store)
        if bundle is None:
            if _withdrawn(connection, session.workspace_id, scene_id):
                return _problem(410, "tombstoned", "this reconstructed scene was withdrawn")
            return _problem(404, "unknown_reference", "no such scene")
    return JSONResponse(content=bundle)


@router.get(
    "/scenes/{scene_id}/observations",
    summary="Which photographs actually observed each retained sparse point.",
)
def scene_observation_graph(
    scene_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    """Click-to-evidence's recorded half.

    A scene with no accepted pose receipt answers 404 alongside a missing and a foreign one. That
    is deliberate: "this scene exists but its pose was refused" is a fact about somebody's library,
    and the read surface does not distinguish reasons a caller may not have.
    """
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        records = scene_observations(connection, session.workspace_id, scene_id, services.store)
        if records is None:
            if _withdrawn(connection, session.workspace_id, scene_id):
                return _problem(410, "tombstoned", "this reconstructed scene was withdrawn")
            return _problem(404, "unknown_reference", "no observation graph for this scene")
    return JSONResponse(content=records)
