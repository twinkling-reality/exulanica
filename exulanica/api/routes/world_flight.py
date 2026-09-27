"""A saved world's flight, read: the flyers its objects host, step by step, for a page to draw.

Nothing is stored. The server composes the flight from the world version (its ground, its placed
objects and the catalogs), once for each version state it is asked about, and cuts the window of
steps asked for from whole episodes the flight's worker process computes
(:mod:`exulanica.world.flight_worker`), so no request waits on another's flight; the page draws
what it is handed and runs no steering of its own.

The flight keeps shared real time: step n is the nth 100 ms since the Unix epoch, read from this
server's clock, so every page showing a world shows its birds in the same places at the same
moment. A read that names no ``from_step`` starts at the clock's step; every answer carries
``clock_step``, the clock's step as it was answered, which the page keeps. A window more than
``clock_reach_steps`` from the clock, or beyond the module's bounds, is refused before anything is
composed, and a worker that has stopped answers 503 ``flight_worker_unavailable``, which a page
tries again. The answer is encoded once, by the standard library's JSON encoder, straight to bytes.
Each flying kind's body and wing are reviewed components, named with their registry rows so the
page fetches the exact bytes by key.
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse, Response

from exulanica.api.dependencies import get_services
from exulanica.api.world_edit import ReadObjects
from exulanica.movement.flight import FlightRefused, check_clock, check_request
from exulanica.movement.registry import MovementModuleNotConnected
from exulanica.world.flight_input import flight_clock, saved_world_flight, served_window
from exulanica.world.flight_kinds import flight_kind_catalog
from exulanica.world.flight_worker import FlightWorkerUnavailable
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
    from_step: Annotated[int | None, Query()] = None,
    steps: Annotated[int, Query()] = 600,
) -> Any:
    clock = flight_clock()
    start = clock if from_step is None else from_step
    try:
        check_request(start, steps)
        check_clock(start, clock)
    except FlightRefused as error:
        return _refusal(error)
    rows = ReviewedCatalog(repository.connection).assets(get_services(request).store)
    registry = {row.asset_key: row for row in rows}
    try:
        flight, generation = saved_world_flight(
            repository, version_id, {row.content_sha256: row.asset_key for row in rows}
        )
        window = served_window(flight, start, steps, generation=generation)
    except FlightWorkerUnavailable as error:
        return JSONResponse(status_code=503, content={"code": error.code, "detail": error.detail})
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
    answer = {
        **window,
        "clock_step": flight_clock(),
        "world_id": flight.world_id,
        "version_id": flight.version_id,
        "kinds": kinds,
        "unplaced": [dict(row) for row in flight.unplaced],
    }
    return Response(_encoded(answer), media_type="application/json")


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def _encoded(answer: dict[str, Any]) -> bytes:
    """The answer as JSON, in FastAPI's own form, encoded a flyer at a time.

    Every value is already JSON's own (text, whole numbers, lists), so nothing walks tens of
    thousands of samples to convert them first. The standard library's encoder holds the
    interpreter's lock for the whole of one call, so the samples are encoded one flyer to a call:
    a request the server answers beside this one waits for at most one flyer's samples.
    """
    rest = _json({key: value for key, value in answer.items() if key != "flyers"})
    flyers = b",".join(_json(row) for row in answer["flyers"])
    return b'{"flyers":[' + flyers + b"]," + rest[1:]
