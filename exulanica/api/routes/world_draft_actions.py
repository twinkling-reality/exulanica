"""Workspace Companion preparation/readback uses the ordinary durable world-draft authority."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.routes.world_making import (
    DESCRIPTION_CHARACTERS,
    DraftWorldBody,
    _durable_view,
    read_world_draft_offer,
)
from exulanica.api.services import Services
from exulanica.selection.world_draft_plan import OPERATION, PROFILE, digest, prepare_world_draft
from exulanica.world.world_draft_jobs import WorldDraftRefused, WorldDraftRepository, terms_sha256

router = APIRouter(prefix="/selection/world-drafts", tags=["selection"])


class PrepareBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Annotated[str, Field(min_length=1, max_length=DESCRIPTION_CHARACTERS)]
    idempotency_key: uuid.UUID = Field(default_factory=uuid.uuid4)

    @field_validator("description")
    @classmethod
    def _says_something(cls, value: str) -> str:
        return DraftWorldBody._says_something(value)


class OutcomeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: dict[str, Any]


@router.post("/prepare")
def prepare(
    body: PrepareBody,
    connection: ReadOnlyConnection,
    request: Request,
    session: CurrentSession,
    held: HeldPermissions,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> dict[str, Any]:
    # Share the normal body's validation, including blank/length and no actor substitution.
    validated = DraftWorldBody(description=body.description, idempotency_key=body.idempotency_key)
    offer = read_world_draft_offer(connection, request, session, held, services, guest)
    return prepare_world_draft(
        validated.description, body.idempotency_key, offer.model_dump(mode="json")
    )


@router.post("/outcome", response_model=None)
def outcome(
    body: OutcomeBody,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> dict[str, Any] | JSONResponse:
    plan = body.plan
    try:
        if plan.get("profile") != PROFILE or digest(plan) != plan.get("plan_sha256"):
            raise ValueError("plan digest")
        (step,) = plan["steps"]
        if step["operation"] != OPERATION or step["confirmation"] != "required":
            raise ValueError("operation")
        asked = DraftWorldBody.model_validate(step["body"])
        if asked.idempotency_key is None:
            raise ValueError("request identity")
    except (KeyError, ValueError, TypeError):
        return JSONResponse(status_code=422, content={"code": "invalid_world_draft_plan"})
    repo = WorldDraftRepository(connection, session.workspace_id)
    start = repo.by_request(session.actor, asked.idempotency_key)
    if start is None:
        return {
            "profile": "exulanica.companion-world-draft-outcome/v1",
            "state": "not_started",
            "result": None,
        }
    try:
        row = repo.get(session.actor, start["draft_id"])
    except WorldDraftRefused:
        return JSONResponse(status_code=404, content={"code": "world_draft_unknown"})
    if row["terms_sha256"] != terms_sha256(asked.description, asked.operation, asked.maximum_usd):
        return JSONResponse(status_code=409, content={"code": "world_draft_terms_mismatch"})
    view = _durable_view(row, connection, services)
    return dict(
        profile="exulanica.companion-world-draft-outcome/v1",
        state="ready"
        if view.state == "ready"
        else "refused"
        if view.state == "refused"
        else "pending",
        result=view.model_dump(mode="json"),
        outcome_sha256=None if row["outcome"] is None else row["outcome"]["document_sha256"],
    )
