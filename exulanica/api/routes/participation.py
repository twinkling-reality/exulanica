"""Browser invitations and read-only observation of one granted world."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentParticipant, CurrentSession, ScopedConnection
from exulanica.api.participation import ParticipationRuntime
from exulanica.api.world_scope import WorldId
from exulanica.epistemics.saved_names import recogniser, saved_names
from exulanica.participation.contracts import NOTICE, notice_reference, public_world_words
from exulanica.participation.repository import InvitationRepository, ParticipationRefused


def _no_store(response: Response) -> None:
    response.headers.update(_HEADERS)


router = APIRouter(tags=["participation"], dependencies=[Depends(_no_store)])
BODY_LIMITS = (
    ("POST", "/world/invitations", 4096),
    ("POST", "/participation/redeem", 1024),
    ("POST", "/world/invitations/{grant_id}/revoke", 256),
    ("POST", "/participation/{grant_id}/leave", 256),
)
_HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class IssueBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    version_id: uuid.UUID
    expires_at: AwareDatetime
    world_words: str = Field(min_length=1, max_length=80)


class RedeemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    invitation: str = Field(min_length=1, max_length=128)
    notice_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _runtime(request: Request) -> ParticipationRuntime:
    runtime = getattr(request.app.state, "participation", None)
    if runtime is None:
        raise ParticipationRefused()
    return runtime


@router.post("/world/invitations")
def issue(
    body: IssueBody,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> dict:
    runtime = _runtime(request)
    runtime.host_open(session.workspace_id)
    if recogniser(saved_names(connection, session.workspace_id))(body.world_words):
        raise ParticipationRefused()
    try:
        public_world_words(body.world_words)
        return InvitationRepository(connection, session.workspace_id).issue(
            world_id,
            body.version_id,
            key=body.idempotency_key,
            actor=session.actor,
            expires_at=body.expires_at,
            world_words=body.world_words,
            eligible=runtime.eligible,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/world/invitations")
def invitations(
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
    after: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict:
    _runtime(request)
    return InvitationRepository(connection, session.workspace_id).listed(
        world_id, after=after, limit=limit
    )


@router.get("/world/invitations/{grant_id}")
def invitation(
    grant_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> dict:
    _runtime(request)
    repository = InvitationRepository(connection, session.workspace_id)
    return repository.view(repository.row(grant_id))


@router.post("/world/invitations/{grant_id}/revoke")
def revoke(
    grant_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> dict:
    _runtime(request)
    return InvitationRepository(connection, session.workspace_id).revoke(grant_id, session.actor)


@router.get("/participation/notice")
def notice(request: Request) -> dict:
    _runtime(request)
    return {"notice": NOTICE, "notice_sha256": notice_reference()["sha256"]}


@router.post("/participation/redeem")
def redeem(body: RedeemBody, request: Request, session: CurrentSession) -> dict:
    return _runtime(request).redeem(session, body.invitation, body.notice_sha256)


@router.get("/participation/{grant_id}")
def grant(request: Request, participant: CurrentParticipant) -> dict:
    return _runtime(request).grant(participant)


@router.get("/participation/{grant_id}/world")
def world(request: Request, participant: CurrentParticipant) -> dict:
    return _runtime(request).world(participant)


@router.get("/participation/{grant_id}/society")
def society(request: Request, participant: CurrentParticipant) -> dict:
    return _runtime(request).society(participant)


@router.get("/participation/{grant_id}/world/tiles/{baked_tile_id}/bytes")
def tile(baked_tile_id: uuid.UUID, request: Request, participant: CurrentParticipant) -> Response:
    data, media = _runtime(request).tile(participant, baked_tile_id)
    return Response(data, media_type=media, headers=_HEADERS)


@router.get("/participation/{grant_id}/world/files/{sha256}")
def file(
    sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")],
    request: Request,
    participant: CurrentParticipant,
) -> Response:
    data, media = _runtime(request).file(participant, sha256)
    return Response(data, media_type=media, headers=_HEADERS)


@router.post("/participation/{grant_id}/leave", status_code=204)
def leave(request: Request, participant: CurrentParticipant, session: CurrentSession) -> Response:
    _runtime(request).leave(participant, session.actor)
    return Response(status_code=204, headers=_HEADERS)
