"""A saved world's traffic, read: the vehicles its roads hold, second by second, for a page to draw.

Nothing is stored and nothing is read from the store. The server reads the roads the world's own
records state (the version's snapshot's records, generated again from the world's receipt and held
to its output digest: :func:`exulanica.world.traffic_host.saved_world_roads`) and cuts the window of
seconds asked for from whole episodes the traffic's worker process computes, the worker
``GET /tiles/traffic`` also uses, so no request computes a second itself.

It is read with ``world.read``, like the world's own tiles, and charges nothing: a world's traffic
is bounded by the tiles its recipe states and the fleet rule, not by a quota. The traffic keeps
shared real time: second ``n`` is the ``n``\\ th second since the Unix epoch, so every page showing
a world shows its vehicles in the same places, and every answer carries ``clock_second``, the
clock's second as it was answered. The answer names the world and version it was asked for, and the
version of the world's roads (``roads_version``, the digest of the receipt its records come from),
which every version of one world shares.

Refusals, each by name: a window beyond the module's bounds or more than ``clock_reach_steps`` from
the clock is 422 before anything is read; a version the world does not hold is 404
``unknown_reference``; a world whose snapshot states no records, or whose records state no lane, is
404 ``roads_not_stated``; roads the traffic compiler cannot drive are 409 ``roads_unavailable`` with
its reason, and a world whose places would host more vehicles than the roads module drives is 409
``roads_world_too_large``; a world whose receipt no longer generates its records is 409 by the
reader's name (``generated_world_grammar_changed``, ``generated_world_catalogs_changed``,
``generated_world_output_changed`` or ``generated_world_unreadable``); a worker that stopped is 503
``traffic_worker_unavailable``, which a page tries again.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query
from fastapi.responses import JSONResponse, Response

from exulanica.api.traffic_answer import refusal_status, vehicles_encoded
from exulanica.api.world_edit import ReadObjects
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import unreadable_reason
from exulanica.world.traffic_episodes import TrafficRefused, check_clock, check_request
from exulanica.world.traffic_host import saved_world_roads, served_window, traffic_clock

__all__ = ["router"]

router = APIRouter(prefix="/world", tags=["world"])
#: A window is cut from episodes named by their input's digest and nothing personal, but a world's
#: traffic moves with the clock, so a browser keeps no copy.
_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"code": code, "detail": detail}, headers=_HEADERS
    )


@router.get(
    "/versions/{version_id}/traffic",
    summary="The vehicles a saved world's roads hold, second by second, for a page to draw.",
)
def world_traffic(
    version_id: Annotated[uuid.UUID, Path()],
    repository: ReadObjects,
    from_second: Annotated[int | None, Query()] = None,
    seconds: Annotated[int, Query()] = 60,
) -> Response:
    clock = traffic_clock()
    start = clock if from_second is None else from_second
    try:
        check_request(start, seconds)
        check_clock(start, clock)
    except TrafficRefused as error:
        return _problem(refusal_status(error), error.code, error.detail)
    version = repository.version(version_id, with_availability=False)
    try:
        value = saved_world_roads(
            repository.connection,
            repository.workspace_id,
            repository.world_id,
            version.source_snapshot_id,
        )
        window = served_window(value, start, seconds)
    except TrafficRefused as error:
        return _problem(refusal_status(error), error.code, error.detail)
    except UnsupportedNetworkError as error:
        return _problem(409, "roads_unavailable", str(error))
    except InvalidStructuralData as error:
        return _problem(409, unreadable_reason(error), str(error))
    answer = {
        **window,
        "clock_second": traffic_clock(),
        "world_id": repository.world_id,
        "version_id": str(version.version_id),
        "roads_version": value.version_id,
    }
    return Response(vehicles_encoded(answer), media_type="application/json", headers=_HEADERS)
