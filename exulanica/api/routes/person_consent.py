"""The reviewer's surface: what is in this photograph, and what has each person agreed to.

This replaces the one question the old gate asked. Instead of attesting that a photograph contains
nobody, a reviewer reads the proposed regions, confirms or corrects them, and records a decision
per person. Every write here is an immutable receipt naming the authenticated actor.

**No request body may name an actor or an actor role.** The authenticated session owns every
decision recorded through these routes, and they are all recorded as ``owner``. A body that could
say ``actor_role: "subject"`` would let the account holder manufacture the photographed person's
consent, which is precisely the thing the three-consent split exists to make impossible to fake.
A genuine subject-facing route needs a credential this system does not yet issue, and it will be
its own module when it does.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Path
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.person_review import (
    create_subject,
    record_consent,
    record_region_edits,
    review_list,
)
from exulanica.ingest.repository import IngestRepository

router = APIRouter(tags=["person-regions"])

RegionKey = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class RegionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region_key: RegionKey
    action: str = Field(pattern=r"^(confirm|add|delete)$")
    shape: str = Field(default="polygon", pattern=r"^(box|polygon)$")
    #: Optional for a confirmation or a deletion: the recorded outline is used. Required to add a
    #: region the detector missed, which is the case a reviewer most needs.
    silhouette: dict[str, Any] | None = None
    subject_id: uuid.UUID | None = None


class RegionEdits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edits: list[RegionEdit] = Field(min_length=1, max_length=200)


class NewSubject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Set only when this person has actually been named. A subject with no entity is somebody
    #: present and owed a decision whose name nobody knows, which is the ordinary case.
    entity_id: uuid.UUID | None = None


class ConsentDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consent_scope: str = Field(pattern=r"^(presence|naming|likeness|temporary_hide)$")
    decision: str = Field(pattern=r"^(granted|revoked|withdrawn)$")
    region_key: RegionKey | None = None
    valid_until: AwareDatetime | None = None


@router.get("/person-regions/{capture_id}", summary="Who is in this photograph, and their state.")
def regions(
    capture_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    repository = IngestRepository(connection, session.workspace_id)
    try:
        found = review_list(repository, capture_id)
    except PrivacyAdmissionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "capture_id": str(capture_id),
        # Said explicitly rather than left to be inferred from an empty list. "Nobody has looked"
        # and "somebody looked and found nobody" are different answers and only the second one may
        # let a photograph through.
        #
        # CORRECTED 2026-09-07: this was `"screened" if found else "unscreened"`, which made the
        # two answers the same one. `review_list` excludes deleted regions, so a reviewer who
        # examined a photograph and deleted every false positive left it reporting that nobody had
        # looked, and the review screen would have told the next reviewer exactly that about work
        # somebody had just finished. It also disagreed with the graph payload, which asks
        # `review_states_for_captures` over the raw table and answered `screened` for the same
        # photograph. Both now ask the same question of the same rows: has anybody ever been
        # proposed or recorded here.
        "review_state": (
            "screened"
            if repository.capture_has_person_regions(capture_id=capture_id)
            else "unscreened"
        ),
        "regions": found,
    }


@router.post("/person-regions/{capture_id}/edits", status_code=201)
def edit_regions(
    capture_id: Annotated[uuid.UUID, Path()],
    body: RegionEdits,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    """Confirm, correct or delete proposed regions. Each edit is its own receipt."""
    try:
        with connection.transaction():
            written = record_region_edits(
                IngestRepository(connection, session.workspace_id),
                capture_id=capture_id,
                actor=session.actor,
                edits=[edit.model_dump() for edit in body.edits],
            )
    except PrivacyAdmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"capture_id": str(capture_id), "recorded": written}


@router.post("/person-subjects", status_code=201)
def new_subject(
    body: NewSubject,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    """Create somebody a decision can be about, named or not."""
    with connection.transaction():
        subject_id = create_subject(
            IngestRepository(connection, session.workspace_id),
            actor=session.actor,
            entity_id=body.entity_id,
        )
    return {"subject_id": str(subject_id)}


@router.post("/person-subjects/{subject_id}/consents", status_code=201)
def add_consent(
    subject_id: Annotated[uuid.UUID, Path()],
    body: ConsentDecision,
    connection: ScopedConnection,
    session: CurrentSession,
) -> dict[str, Any]:
    """Record one consent transition, as the account holder and never as the subject."""
    try:
        with connection.transaction():
            consent_id = record_consent(
                IngestRepository(connection, session.workspace_id),
                subject_id=subject_id,
                actor=session.actor,
                consent_scope=body.consent_scope,
                decision=body.decision,
                region_key=bytes.fromhex(body.region_key) if body.region_key else None,
                valid_until=body.valid_until,
                effective_at=dt.datetime.now(dt.UTC),
            )
    except PrivacyAdmissionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "consent_id": str(consent_id),
        "subject_id": str(subject_id),
        # Echoed so a caller cannot believe it recorded the subject's own decision.
        "actor_role": "owner",
    }
