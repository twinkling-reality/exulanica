"""A world version's moments, for its History (exulanica.world.society_moments).

*   ``GET /world/versions/{version_id}/history/moments`` answers
    ``exulanica.world-history-moments/v1``: what the version's characters did that a person would
    tell, newest last, at most ``limit`` before minute ``before``, each with the lines said in it,
    who decided, where, the run it happened in, its scene and the other models' answers to its
    decision. ``more`` says whether earlier ones exist. A version whose world has no society has no
    moments. It writes nothing.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.routes.society import _call, _repository
from exulanica.api.routes.society_control import repository as control_repository
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.world.society_moments import MOMENTS_PROFILE, READ_MOST, read_moments

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["history"])


@router.get("/versions/{version_id}/history/moments")
def read_version_moments(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    before: Annotated[int | None, Query(ge=0)] = None,
    limit: Annotated[int, Query(ge=1, le=READ_MOST)] = 50,
) -> Any:
    """The version's moments, newest last."""

    def read() -> Any:
        with connection.transaction():
            row = _repository(connection, session, request, world_id)._row(version_id)
            if row is None:
                return {
                    "profile": MOMENTS_PROFILE,
                    "version_id": str(version_id),
                    "now": None,
                    "moments": [],
                    "more": False,
                }
            sessions = control_repository(connection, session, request, world_id).sessions(
                version_id
            )
            manifest = load_manifest()
            return read_moments(
                connection,
                session.workspace_id,
                row,
                before=before,
                limit=limit,
                sessions=sessions,
                model_name=manifest.model_name,
            )

    return _call(read, invalid_status=409)
