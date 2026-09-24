"""Reviewed interaction-policy proposal lifecycle for Settings and Companion."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, TypeAlias

from fastapi import APIRouter, Depends, Path, Response
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictInt,
    StrictStr,
    model_validator,
)

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world import (
    INTERACTION_POLICY_REGISTRY,
    InteractionPolicyVersion,
    InteractionPreview,
    InteractionProposal,
    InteractionProposalRecord,
    ProposalOrigin,
    ProposalProvenance,
    StaleInteractionPolicy,
    WorldInteractionPolicyRepository,
)
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/interactions", tags=["world"])

InteractionValue: TypeAlias = StrictBool | StrictInt | StrictStr


class InteractionBaseBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_policy_version_id: uuid.UUID | None
    base_structure_snapshot_id: uuid.UUID | None
    base_topology_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")] | None

    @model_validator(mode="after")
    def complete_structure_base(self) -> InteractionBaseBody:
        if (self.base_structure_snapshot_id is None) != (self.base_topology_sha256 is None):
            raise ValueError("structure snapshot id and topology SHA-256 must be supplied together")
        return self


class InteractionPreviewBody(InteractionBaseBody):
    proposal_id: uuid.UUID
    origin: ProposalOrigin
    origin_reference: Annotated[str, Field(min_length=1, max_length=500)] | None = None
    capability_patch: dict[
        Annotated[str, Field(pattern=r"^[a-z][a-z0-9.-]*$")], InteractionValue
    ] = Field(min_length=1, max_length=32)
    proposal_input: dict[str, JsonValue]
    explanation: Annotated[str, Field(min_length=1, max_length=2000)]
    reference_ids: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=100
    )
    model_id: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    prompt_version: Annotated[str, Field(min_length=1, max_length=300)] | None = None
    refines_proposal_id: uuid.UUID | None = None


class InteractionApplyBody(InteractionBaseBody):
    pass


class InteractionRollbackBody(InteractionBaseBody):
    target_version_id: uuid.UUID
    origin: ProposalOrigin
    origin_reference: Annotated[str, Field(min_length=1, max_length=500)] | None = None


class InteractionProvenanceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: ProposalOrigin
    actor: uuid.UUID
    origin_reference: str | None


class InteractionVersionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    revision: int
    parent_version_id: uuid.UUID | None
    parameters: dict[str, InteractionValue]
    policy_sha256: str
    applied_from_proposal_id: uuid.UUID | None
    rollback_target_version_id: uuid.UUID | None
    provenance: InteractionProvenanceView
    created_at: dt.datetime


class InteractionStateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current: InteractionVersionView | None
    parameters: dict[str, InteractionValue]
    base_structure_snapshot_id: uuid.UUID | None
    base_topology_sha256: str | None


class InteractionPreviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: uuid.UUID
    proposal_id: uuid.UUID
    candidate_parameters: dict[str, InteractionValue]
    candidate_sha256: str
    created_at: dt.datetime


class InteractionProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: uuid.UUID
    provenance: InteractionProvenanceView
    capability_patch: dict[str, InteractionValue]
    base_policy_version_id: uuid.UUID | None
    base_structure_snapshot_id: uuid.UUID | None
    base_topology_sha256: str | None
    proposal_input: dict[str, JsonValue]
    explanation: str
    reference_ids: list[str]
    model_id: str | None
    prompt_version: str | None
    refines_proposal_id: uuid.UUID | None
    status: str
    validation_issues: list[str]
    created_at: dt.datetime
    updated_at: dt.datetime


class InteractionRecommendationView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_key: str
    proposed_value: InteractionValue
    accepted_observation_count: int
    rejected_observation_count: int
    explanation: str


def read_repository(
    connection: ReadOnlyConnection, session: CurrentSession, world_id: WorldId
) -> WorldInteractionPolicyRepository:
    require_world(connection, session.workspace_id, world_id)
    return WorldInteractionPolicyRepository(connection, session.workspace_id, world_id=world_id)


def write_repository(
    connection: ScopedConnection, session: CurrentSession, world_id: WorldId
) -> WorldInteractionPolicyRepository:
    require_world(connection, session.workspace_id, world_id)
    return WorldInteractionPolicyRepository(connection, session.workspace_id, world_id=world_id)


ReadInteraction = Annotated[WorldInteractionPolicyRepository, Depends(read_repository)]
WriteInteraction = Annotated[WorldInteractionPolicyRepository, Depends(write_repository)]


@router.get(
    "/catalog", summary="Reviewed comfort, navigation, disclosure, and initiative controls."
)
def catalog(_session: CurrentSession) -> dict[str, object]:
    return INTERACTION_POLICY_REGISTRY.catalog()


@router.get("/current", response_model=InteractionStateView)
def current(repository: ReadInteraction) -> InteractionStateView:
    state = repository.state()
    return InteractionStateView(
        current=None if state.current is None else _version_view(state.current),
        parameters=dict(state.parameters),
        base_structure_snapshot_id=state.base_structure_snapshot_id,
        base_topology_sha256=state.base_topology_sha256,
    )


@router.get("/versions", response_model=list[InteractionVersionView])
def versions(repository: ReadInteraction) -> list[InteractionVersionView]:
    return [_version_view(value) for value in repository.versions()]


@router.get("/proposals/{proposal_id}", response_model=InteractionProposalView)
def proposal_record(
    proposal_id: Annotated[uuid.UUID, Path()], repository: ReadInteraction
) -> InteractionProposalView:
    return _proposal_view(repository.proposal_record(proposal_id))


@router.get("/recommendations", response_model=list[InteractionRecommendationView])
def recommendations(repository: ReadInteraction) -> list[InteractionRecommendationView]:
    return [
        InteractionRecommendationView(
            capability_key=value.capability_key,
            proposed_value=value.proposed_value,
            accepted_observation_count=value.accepted_observation_count,
            rejected_observation_count=value.rejected_observation_count,
            explanation=value.explanation,
        )
        for value in repository.recommendations()
    ]


@router.post("/previews", response_model=InteractionPreviewView, status_code=201)
def preview(
    body: InteractionPreviewBody,
    repository: WriteInteraction,
    session: CurrentSession,
) -> InteractionPreviewView:
    created = repository.preview(
        InteractionProposal(
            body.proposal_id,
            ProposalProvenance(body.origin, session.actor, body.origin_reference),
            body.capability_patch,
            body.base_policy_version_id,
            body.base_structure_snapshot_id,
            body.base_topology_sha256,
            body.proposal_input,
            body.explanation,
            tuple(body.reference_ids),
            body.model_id,
            body.prompt_version,
            body.refines_proposal_id,
        )
    )
    return _preview_view(created)


@router.post("/previews/{preview_id}/apply", response_model=InteractionVersionView)
def apply(
    preview_id: Annotated[uuid.UUID, Path()],
    body: InteractionApplyBody,
    repository: WriteInteraction,
    session: CurrentSession,
) -> InteractionVersionView:
    return _version_view(
        repository.apply(
            preview_id,
            base_policy_version_id=body.base_policy_version_id,
            base_structure_snapshot_id=body.base_structure_snapshot_id,
            base_topology_sha256=body.base_topology_sha256,
            applied_by=session.actor,
        )
    )


@router.delete("/previews/{preview_id}", status_code=204)
def discard(
    preview_id: Annotated[uuid.UUID, Path()],
    repository: WriteInteraction,
    session: CurrentSession,
) -> Response:
    repository.discard(preview_id, discarded_by=session.actor)
    return Response(status_code=204)


@router.post("/rollback", response_model=InteractionVersionView)
def rollback(
    body: InteractionRollbackBody,
    repository: WriteInteraction,
    session: CurrentSession,
) -> InteractionVersionView:
    if body.base_policy_version_id is None:
        raise StaleInteractionPolicy("rollback requires a current policy version")
    return _version_view(
        repository.rollback(
            body.target_version_id,
            base_policy_version_id=body.base_policy_version_id,
            base_structure_snapshot_id=body.base_structure_snapshot_id,
            base_topology_sha256=body.base_topology_sha256,
            provenance=ProposalProvenance(body.origin, session.actor, body.origin_reference),
        )
    )


def _provenance_view(value: ProposalProvenance) -> InteractionProvenanceView:
    return InteractionProvenanceView(
        origin=value.origin, actor=value.actor, origin_reference=value.origin_reference
    )


def _version_view(value: InteractionPolicyVersion) -> InteractionVersionView:
    return InteractionVersionView(
        version_id=value.version_id,
        revision=value.revision,
        parent_version_id=value.parent_version_id,
        parameters=dict(value.parameters),
        policy_sha256=value.policy_sha256,
        applied_from_proposal_id=value.applied_from_proposal_id,
        rollback_target_version_id=value.rollback_target_version_id,
        provenance=_provenance_view(value.provenance),
        created_at=value.created_at,
    )


def _preview_view(value: InteractionPreview) -> InteractionPreviewView:
    return InteractionPreviewView(
        preview_id=value.preview_id,
        proposal_id=value.proposal.proposal_id,
        candidate_parameters=dict(value.candidate_parameters),
        candidate_sha256=value.candidate_sha256,
        created_at=value.created_at,
    )


def _proposal_view(value: InteractionProposalRecord) -> InteractionProposalView:
    proposal = value.proposal
    return InteractionProposalView(
        proposal_id=proposal.proposal_id,
        provenance=_provenance_view(proposal.provenance),
        capability_patch=dict(proposal.capability_patch),
        base_policy_version_id=proposal.base_policy_version_id,
        base_structure_snapshot_id=proposal.base_structure_snapshot_id,
        base_topology_sha256=proposal.base_topology_sha256,
        proposal_input=dict(proposal.proposal_input),
        explanation=proposal.explanation,
        reference_ids=list(proposal.reference_ids),
        model_id=proposal.model_id,
        prompt_version=proposal.prompt_version,
        refines_proposal_id=proposal.refines_proposal_id,
        status=value.status,
        validation_issues=list(value.validation_issues),
        created_at=value.created_at,
        updated_at=value.updated_at,
    )
