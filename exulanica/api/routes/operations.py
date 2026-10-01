"""Authorised operational visibility for the caller's own derivative queue."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.corpus.decode import decode_counts
from exulanica.ingest.operations import (
    derivative_job,
    derivative_job_events,
    derivative_job_metrics,
    reconstruction_scene_job,
    reconstruction_scene_metrics,
    retry_reconstruction_scene_job,
)

router = APIRouter(prefix="/operations", tags=["operations"])


def _not_found(detail: str) -> JSONResponse:
    """404 ``unknown_reference`` in the problem shape, for an id this workspace cannot see.

    The same answer whether the id never existed or belongs to another workspace, because every
    lookup here is a workspace-scoped read.
    """
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"code": "unknown_reference", "detail": detail},
    )


@router.get("/capacity", summary="How much of each capacity class this API process holds now.")
def capacity(request: Request, session: CurrentSession) -> dict[str, Any]:
    """This process's admission limits and counts, and the decode bound's.

    Counts for the whole process, never another workspace's id; ``workspace_in_flight`` is the
    caller's own. This read is itself a request, so the requests class's ``in_flight`` includes it.
    Another API process keeps counts of its own (``docs/deployment.md`` section 5.4).
    """
    admission = getattr(request.app.state, "admission", None)
    counts = admission.snapshot(session.workspace_id) if admission is not None else {}
    return {**counts, "decodes": decode_counts()}


@router.get("/derivative-jobs", summary="Measured derivative queue health for this workspace.")
def jobs(connection: ScopedConnection, session: CurrentSession) -> dict[str, Any]:
    return derivative_job_metrics(connection, session.workspace_id)


@router.get(
    "/derivative-jobs/{job_id}",
    summary="One derivative job's state and progress.",
    response_model=dict[str, Any],
)
def job(
    job_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> dict[str, Any] | JSONResponse:
    """Whether the job is queued, running or finished, and how far it got.

    404 ``unknown_reference`` for a job this workspace cannot see, identically to one that never
    existed. The events route beside this one answers an empty replay for both; this is the read
    that tells an unknown job from one that has not reported yet.
    """
    result = derivative_job(connection, session.workspace_id, job_id)
    if result is None:
        return _not_found("derivative job not found")
    return result


@router.get(
    "/derivative-jobs/{job_id}/events",
    summary="Durable delivery replay for one derivative job.",
)
def job_events(
    job_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> list[dict[str, Any]]:
    return derivative_job_events(connection, session.workspace_id, job_id)


@router.get(
    "/reconstruction-scenes",
    summary="Measured reconstruction dependency and queue health for this workspace.",
)
def reconstruction_scenes(connection: ScopedConnection, session: CurrentSession) -> dict[str, Any]:
    return reconstruction_scene_metrics(connection, session.workspace_id)


@router.get(
    "/reconstruction-scenes/{job_id}",
    summary="Exact inputs, state and outputs for one reconstruction build.",
    response_model=dict[str, Any],
)
def reconstruction_scene_detail(
    job_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> dict[str, Any] | JSONResponse:
    result = reconstruction_scene_job(connection, session.workspace_id, job_id)
    if result is None:
        return _not_found("reconstruction build not found")
    return result


@router.post(
    "/reconstruction-scenes/{job_id}/retry",
    summary="Make one retryable failed reconstruction build immediately eligible.",
    response_model=dict[str, str],
)
def retry_reconstruction_scene(
    job_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession
) -> dict[str, str] | JSONResponse:
    with connection.transaction():
        result = retry_reconstruction_scene_job(
            connection,
            session.workspace_id,
            job_id,
        )
    if result is None:
        return _not_found("reconstruction build not found")
    if result != "retryable":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"reconstruction build is {result} and cannot be retried",
        )
    return {"status": "retryable"}
