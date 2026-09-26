"""A saved world's flight, read: the flyers its objects host, step by step, for a page to draw.

Nothing is stored. The server composes the flight from the world version (its ground, its placed
objects and the catalogs), once for each version state it is asked about, and computes the window
of steps asked for with the flight movement module; the page draws what it is handed and runs no
steering of its own. A window beyond the module's bounds is refused before anything is composed.
Each flying kind's body and wing are reviewed components, named with their registry rows so the
page fetches the exact bytes by key.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import get_services
from exulanica.api.world_edit import ReadObjects
from exulanica.movement.flight import FlightRefused, check_request
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world.flight_input import saved_world_flight, served_window
from exulanica.world.flight_kinds import flight_kind_catalog
from exulanica.world.reviewed_catalog import ReviewedCatalog

router = APIRouter(prefix="/world", tags=["world"])

#: A window a request did not bound: the module's refusals, a caller's to correct.
_REQUEST_REFUSALS = frozenset({"flight_step_out_of_range", "flight_window_too_long"})


def _refusal(error: FlightRefused) -> JSONResponse:
    status = 422 if error.code in _REQUEST_REFUSALS else 409
    return JSONResponse(status_code=status, content={"code": error.code, "detail": error.detail})


@router.get(
    "/versions/{version_id}/flight",
    summary="The flyers a saved world's objects host, as steps of its flight for a page to draw.",
)
def world_flight(
    version_id: Annotated[uuid.UUID, Path()],
    repository: ReadObjects,
    request: Request,
    from_step: Annotated[int, Query()] = 0,
    steps: Annotated[int, Query()] = 600,
) -> Any:
    try:
        check_request(from_step, steps)
    except FlightRefused as error:
        return _refusal(error)
    rows = ReviewedCatalog(repository.connection).assets(get_services(request).store)
    registry = {row.asset_key: row for row in rows}
    try:
        flight = saved_world_flight(
            repository, version_id, {row.content_sha256: row.asset_key for row in rows}
        )
        window = served_window(flight, from_step, steps)
    except FlightRefused as error:
        return _refusal(error)
    except MovementModuleNotConnected as error:
        return JSONResponse(status_code=409, content={"code": error.code, "detail": str(error)})

    def asset(key: str) -> dict[str, Any]:
        row = registry.get(key)
        if row is None:
            return {"asset_key": key, "availability": "unregistered"}
        return {
            "asset_key": key,
            "media_type": row.media_type,
            "content_sha256": row.content_sha256,
            "byte_size": row.byte_size,
            "availability": row.availability,
        }

    kinds = [
        {
            "key": kind.key,
            "title": kind.title,
            "body": asset(kind.body_asset_key),
            "wing": asset(kind.wing_asset_key),
            "wing_hinge_mm": list(kind.wing_hinge_mm),
            "max_bank_mrad": kind.figures.max_bank_mrad,
            "flap_cycle_ms": kind.figures.flap_cycle_ms,
        }
        for kind in flight_kind_catalog().kinds
        if kind.key in flight.kinds
    ]
    return {
        **window,
        "world_id": flight.world_id,
        "version_id": flight.version_id,
        "kinds": kinds,
        "unplaced": [dict(row) for row in flight.unplaced],
    }
