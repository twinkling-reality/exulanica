"""The comparisons of the models that ran a world's people: read, never run.

``GET /world/versions/{version_id}/society/comparisons`` lists a version's comparisons, newest
first, each with its arms and how far its runs got. ``GET .../comparisons/{comparison_id}`` gives
one comparison's scores, per seed and per arm, with intervals, its registered differences and the
server's verdict, which is the only source of the words a page shows for it. Both name every
model an arm asks by ``Manifest.model_name``, as the People panel's read does. ``GET
.../comparisons/{comparison_id}/runs/{run_id}`` replays one completed run from the requests and
receipts it stored, with no model call, holds the replay to what the run recorded, and returns
what the page draws: the place, each person's minutes and what every turn did. A replay that
differs from its record is refused by name (``run_replay_mismatch``), never shown.

None of these asks a model or writes anything. A comparison is defined and run by the local command
``python -m exulanica.orchestration.compare``. No response carries a run's seed.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_comparison import ReplayMismatch
from exulanica.world.society_comparison_repository import SocietyComparisonRepository
from exulanica.world.society_comparison_result import (
    ComparisonRefused,
    comparison_result,
    listing_document,
    replay_document,
    verified_replay,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/comparisons", tags=["society"])

__all__ = ["router"]

#: A run that has no completed hour to draw, answered by name rather than as a missing run.
RUN_NOT_COMPLETED: Final = "run_not_completed"


def _comparisons(
    connection: ScopedConnection, session: CurrentSession, request: Request, world_id: str
) -> SocietyComparisonRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyComparisonRepository(
        SocietyRepository(
            connection,
            session.workspace_id,
            world_id=world_id,
            input_authorizer=(
                None if authorizer is None else lambda doc: authorizer(connection, session, doc)
            ),
        )
    )


def _unavailable(exc: UnavailableSocietyInput) -> JSONResponse:
    return JSONResponse(
        status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
    )


@router.get("")
def society_comparisons(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    if comparisons.society._row(version_id) is None:
        raise UnknownSociety("society is unavailable")
    rows = comparisons.definitions(version_id)
    counts = comparisons.run_counts([row["comparison_id"] for row in rows])
    return listing_document(rows, counts, model_name=load_manifest().model_name)


@router.get("/{comparison_id}")
def society_comparison(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    row = comparisons.definition(version_id, comparison_id)
    return comparison_result(
        row, comparisons.runs(comparison_id), model_name=load_manifest().model_name
    )


@router.get("/{comparison_id}/runs/{run_id}")
def society_comparison_run(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    run_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    comparisons.definition(version_id, comparison_id)
    outcome = comparisons.outcome(run_id)
    try:
        plan, definition = comparisons.plan(comparison_id, run_id)
    except UnavailableSocietyInput as exc:
        return _unavailable(exc)
    except ComparisonRefused as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})
    if outcome is None or outcome["status"] != "completed":
        return JSONResponse(
            status_code=409,
            content={"code": RUN_NOT_COMPLETED, "detail": "this run has no completed hour"},
        )
    try:
        played = verified_replay(plan, comparisons.stored(run_id), outcome)
    except ReplayMismatch as exc:
        return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})
    return replay_document(plan, definition, outcome["arm"], outcome["seed_digest"], played)
