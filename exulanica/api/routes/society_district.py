"""Authenticated exact district presentation for the registered society frame."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.society_district import SocietyDistrictView, society_district_view
from exulanica.api.world_scope import WorldId
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world", tags=["society"])
_HEADERS = {"Cache-Control": "private, no-store"}


@router.get("/versions/{version_id}/society/district", response_model=SocietyDistrictView)
def society_district(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    request: Request,
    response: Response,
    world_id: WorldId,
) -> Any:
    response.headers.update(_HEADERS)
    runtime = getattr(get_services(request), "society_runtime", None)
    try:
        require_world(connection, session.workspace_id, world_id)
        if runtime is None:
            raise UnavailableSocietyInput("society district runtime is not configured")
        return society_district_view(runtime, connection, session, version_id, world_id=world_id)
    except UnknownWorldResource:
        return JSONResponse(
            status_code=404,
            content={"code": "unknown_reference", "detail": "no such registered society district"},
            headers=_HEADERS,
        )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424,
            content={"code": "unavailable_society_input", "detail": str(exc)},
            headers=_HEADERS,
        )
