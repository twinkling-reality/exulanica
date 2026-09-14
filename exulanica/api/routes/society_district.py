"""Authenticated exact district presentation for the registered society frame."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.society_district import SocietyDistrictView, society_district_view
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.society import UnavailableSocietyInput

router = APIRouter(prefix="/world", tags=["society"])
_HEADERS = {"Cache-Control": "private, no-store"}


@router.get("/versions/{version_id}/society/district", response_model=SocietyDistrictView)
def society_district(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    request: Request,
    response: Response,
) -> Any:
    response.headers.update(_HEADERS)
    runtime = getattr(get_services(request), "society_runtime", None)
    try:
        if runtime is None:
            raise UnavailableSocietyInput("society district runtime is not configured")
        return society_district_view(runtime, connection, session, version_id)
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
