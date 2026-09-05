"""The appearance-only world customization API.

Routes validate transport shapes and delegate to :mod:`exulanica.world`.  There is no topology
mutation endpoint: topology registration belongs to the reviewed composition workflow, so a
browser, Settings, or Companion request cannot move a region or rewrite an evidence binding.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal, TypeAlias

from fastapi import APIRouter, Depends, Path, Response
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    model_validator,
)

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.world import (
    STYLE_REGISTRY,
    ProposalOrigin,
    ProposalProvenance,
    StyleProposal,
    StyleProposalRecord,
    StyleReference,
    StyleScope,
    StyleVersion,
    WorldSourceMedia,
    WorldStyleRepository,
)

router = APIRouter(prefix="/world", tags=["world"])

StyleValue: TypeAlias = StrictBool | StrictInt | StrictFloat | StrictStr


class StyleReferenceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: Annotated[
        str,
        Field(
            pattern=r"^[a-z][a-z0-9.-]*$",
            max_length=200,
            validation_alias=AliasChoices("profile_id", "profileId"),
        ),
    ]
    profile_version: Annotated[
        int, Field(ge=1, validation_alias=AliasChoices("profile_version", "profileVersion"))
    ]
    parameters: dict[str, StyleValue] = Field(default_factory=dict, max_length=100)


class StyleScopeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["global", "region"]
    region_id: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=500,
            validation_alias=AliasChoices("region_id", "islandId"),
        ),
    ] = None

    @model_validator(mode="after")
    def exact_scope(self) -> StyleScopeBody:
        if (self.kind == "global") != (self.region_id is None):
            raise ValueError("global scope has no region_id; region scope requires one")
        return self


class PreviewBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: Annotated[
        uuid.UUID, Field(validation_alias=AliasChoices("proposal_id", "proposalId"))
    ]
    origin: ProposalOrigin
    origin_reference: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=500,
            validation_alias=AliasChoices("origin_reference", "originReference"),
        ),
    ] = None
    scope: StyleScopeBody
    base_style_version_id: Annotated[
        uuid.UUID,
        Field(validation_alias=AliasChoices("base_style_version_id", "baseStyleVersionId")),
    ]
    base_topology_digest: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            validation_alias=AliasChoices("base_topology_digest", "baseTopologyDigest"),
        ),
    ]
    profile: StyleReferenceBody
    reference_ids: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list,
        max_length=100,
        validation_alias=AliasChoices("reference_ids", "referenceIds"),
    )
    model_id: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=300,
            validation_alias=AliasChoices("model_id", "modelId"),
        ),
    ] = None
    prompt_version: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=300,
            validation_alias=AliasChoices("prompt_version", "promptVersion"),
        ),
    ] = None
    refines_proposal_id: Annotated[
        uuid.UUID | None,
        Field(validation_alias=AliasChoices("refines_proposal_id", "refinesProposalId")),
    ] = None


class ApplyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_style_version_id: Annotated[
        uuid.UUID,
        Field(validation_alias=AliasChoices("base_style_version_id", "baseStyleVersionId")),
    ]
    base_topology_digest: Annotated[
        str,
        Field(
            min_length=1,
            max_length=256,
            validation_alias=AliasChoices("base_topology_digest", "baseTopologyDigest"),
        ),
    ]


class RollbackBody(ApplyBody):
    target_version_id: Annotated[
        uuid.UUID, Field(validation_alias=AliasChoices("target_version_id", "targetVersionId"))
    ]
    origin: ProposalOrigin
    origin_reference: Annotated[
        str | None,
        Field(
            min_length=1,
            max_length=500,
            validation_alias=AliasChoices("origin_reference", "originReference"),
        ),
    ] = None


class ProvenanceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    origin: ProposalOrigin
    actor: uuid.UUID
    origin_reference: str | None


class StyleReferenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str
    profile_version: int
    parameters: dict[str, StyleValue]


class RegionStyleView(StyleReferenceView):
    region_id: str


class StyleVersionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: uuid.UUID
    revision: int
    parent_version_id: uuid.UUID | None
    topology_digest: str
    global_style: StyleReferenceView
    region_styles: list[RegionStyleView]
    applied_from_proposal_id: uuid.UUID | None
    rollback_target_version_id: uuid.UUID | None
    provenance: ProvenanceView | None
    created_at: dt.datetime
    warnings: list[str]
    recipe_binding: dict[str, JsonValue]
    capability_mapping: dict[str, str]
    reference_ids: list[str]
    model_id: str | None
    prompt_version: str | None
    refines_proposal_id: uuid.UUID | None


class StyleStateView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_topology_digest: str
    current: StyleVersionView


class PreviewView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preview_id: uuid.UUID
    proposal_id: uuid.UUID
    candidate: StyleVersionView
    created_at: dt.datetime


class StyleProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: uuid.UUID
    provenance: ProvenanceView
    scope: StyleScopeBody
    base_style_version_id: uuid.UUID
    base_topology_digest: str
    profile: StyleReferenceView
    reference_ids: list[str]
    model_id: str | None
    prompt_version: str | None
    refines_proposal_id: uuid.UUID | None
    recipe_binding: dict[str, JsonValue]
    capability_mapping: dict[str, str]
    status: str
    validation_issues: list[str]
    created_at: dt.datetime
    updated_at: dt.datetime


class SourceAssetProvenanceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    evidence_span_id: uuid.UUID


class SourceAssetReferenceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    href: str
    authorization: Literal["workspace-bearer"]
    provenance: SourceAssetProvenanceView


class SourceMediaView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: uuid.UUID
    slot_key: str
    region_id: str | None
    state: Literal["available", "unavailable_asset", "missing_evidence"]
    reason: str | None
    evidence_span_id: uuid.UUID | None
    evidence_path: str | None
    modality: str | None
    media_type: str | None
    byte_size: int | None
    width: int | None
    height: int | None
    captured_at: dt.datetime | None
    captured_at_uncertainty_ms: int | None
    asset_reference: SourceAssetReferenceView | None
    capture_ids: tuple[uuid.UUID, ...]


def read_repository(
    connection: ReadOnlyConnection, session: CurrentSession
) -> WorldStyleRepository:
    return WorldStyleRepository(connection, session.workspace_id)


def write_repository(connection: ScopedConnection, session: CurrentSession) -> WorldStyleRepository:
    return WorldStyleRepository(connection, session.workspace_id)


ReadWorld = Annotated[WorldStyleRepository, Depends(read_repository)]
WriteWorld = Annotated[WorldStyleRepository, Depends(write_repository)]


@router.get("/styles/catalog", summary="Reviewed world profiles and capability-backed controls.")
def catalog(_session: CurrentSession) -> dict[str, object]:
    return STYLE_REGISTRY.catalog()


@router.get(
    "/styles/current",
    response_model=StyleStateView,
    summary="The current immutable style version and protected topology digest.",
)
def current(repository: ReadWorld) -> StyleStateView:
    return StyleStateView(
        current_topology_digest=repository.current_topology_digest(),
        current=_version_view(repository.current()),
    )


@router.get(
    "/styles/versions",
    response_model=list[StyleVersionView],
    summary="Immutable style history, including rollback versions.",
)
def versions(repository: ReadWorld) -> list[StyleVersionView]:
    return [_version_view(version) for version in repository.versions()]


@router.post(
    "/styles/previews",
    response_model=PreviewView,
    status_code=201,
    summary="Validate an isolated appearance preview without changing current state.",
)
def preview(body: PreviewBody, repository: WriteWorld, session: CurrentSession) -> PreviewView:
    proposal = StyleProposal(
        proposal_id=body.proposal_id,
        provenance=ProposalProvenance(body.origin, session.actor, body.origin_reference),
        scope=StyleScope(body.scope.kind, body.scope.region_id),
        base_style_version_id=body.base_style_version_id,
        base_topology_digest=body.base_topology_digest,
        profile=_reference(body.profile),
        reference_ids=tuple(body.reference_ids),
        model_id=body.model_id,
        prompt_version=body.prompt_version,
        refines_proposal_id=body.refines_proposal_id,
    )
    created = repository.preview(proposal)
    return PreviewView(
        preview_id=created.preview_id,
        proposal_id=created.proposal.proposal_id,
        candidate=_version_view(created.candidate),
        created_at=created.created_at,
    )


@router.get(
    "/styles/proposals/{proposal_id}",
    response_model=StyleProposalView,
    summary="Inspect one authorised style proposal, provenance, and lifecycle state.",
)
def proposal(proposal_id: Annotated[uuid.UUID, Path()], repository: ReadWorld) -> StyleProposalView:
    return _proposal_view(repository.proposal(proposal_id))


@router.post(
    "/styles/previews/{preview_id}/apply",
    response_model=StyleVersionView,
    summary="Atomically apply one still-current preview as a new immutable version.",
)
def apply(
    preview_id: Annotated[uuid.UUID, Path()],
    body: ApplyBody,
    repository: WriteWorld,
    session: CurrentSession,
) -> StyleVersionView:
    return _version_view(
        repository.apply(
            preview_id,
            base_style_version_id=body.base_style_version_id,
            base_topology_digest=body.base_topology_digest,
            applied_by=session.actor,
        )
    )


@router.delete(
    "/styles/previews/{preview_id}",
    status_code=204,
    summary="Discard an isolated preview without changing style state.",
)
def discard(
    preview_id: Annotated[uuid.UUID, Path()],
    repository: WriteWorld,
    session: CurrentSession,
) -> Response:
    repository.discard(preview_id, discarded_by=session.actor)
    return Response(status_code=204)


@router.post(
    "/styles/rollback",
    response_model=StyleVersionView,
    summary="Restore historical style values by creating a new immutable version.",
)
def rollback(
    body: RollbackBody, repository: WriteWorld, session: CurrentSession
) -> StyleVersionView:
    return _version_view(
        repository.rollback(
            body.target_version_id,
            base_style_version_id=body.base_style_version_id,
            base_topology_digest=body.base_topology_digest,
            provenance=ProposalProvenance(body.origin, session.actor, body.origin_reference),
        )
    )


@router.get(
    "/source-media",
    response_model=list[SourceMediaView],
    summary="Protected topology source slots with honest availability states.",
)
def source_media(
    repository: ReadWorld, services: Annotated[Services, Depends(get_services)]
) -> list[SourceMediaView]:
    # `Services` is supplied below through an explicit dependency override; keeping it out of
    # the repository means the persistence layer cannot fetch arbitrary URLs or own bytes.
    return [_source_view(source) for source in repository.source_media(services.store)]


@router.get(
    "/source-media/{source_id}",
    response_model=SourceMediaView,
    summary="Require one authorised source slot to have available local evidence bytes.",
)
def require_source_media(
    source_id: Annotated[uuid.UUID, Path()],
    repository: ReadWorld,
    services: Annotated[Services, Depends(get_services)],
) -> SourceMediaView:
    return _source_view(repository.require_source_media(source_id, services.store))


def _reference(body: StyleReferenceBody) -> StyleReference:
    return StyleReference(body.profile_id, body.profile_version, body.parameters)


def _reference_view(reference: StyleReference) -> StyleReferenceView:
    return StyleReferenceView(
        profile_id=reference.profile_id,
        profile_version=reference.profile_version,
        parameters=dict(reference.parameters),
    )


def _version_view(version: StyleVersion) -> StyleVersionView:
    provenance = None
    if version.provenance is not None:
        provenance = ProvenanceView(
            origin=version.provenance.origin,
            actor=version.provenance.actor,
            origin_reference=version.provenance.origin_reference,
        )
    return StyleVersionView(
        version_id=version.version_id,
        revision=version.revision,
        parent_version_id=version.parent_version_id,
        topology_digest=version.topology_digest,
        global_style=_reference_view(version.global_style),
        region_styles=[
            RegionStyleView(
                region_id=region_id,
                profile_id=reference.profile_id,
                profile_version=reference.profile_version,
                parameters=dict(reference.parameters),
            )
            for region_id, reference in sorted(version.region_styles.items())
        ],
        applied_from_proposal_id=version.applied_from_proposal_id,
        rollback_target_version_id=version.rollback_target_version_id,
        provenance=provenance,
        created_at=version.created_at,
        warnings=list(version.warnings),
        recipe_binding=dict(version.recipe_binding),
        capability_mapping=dict(version.capability_mapping),
        reference_ids=list(version.reference_ids),
        model_id=version.model_id,
        prompt_version=version.prompt_version,
        refines_proposal_id=version.refines_proposal_id,
    )


def _proposal_view(record: StyleProposalRecord) -> StyleProposalView:
    proposal = record.proposal
    return StyleProposalView(
        proposal_id=proposal.proposal_id,
        provenance=ProvenanceView(
            origin=proposal.provenance.origin,
            actor=proposal.provenance.actor,
            origin_reference=proposal.provenance.origin_reference,
        ),
        scope=StyleScopeBody(kind=proposal.scope.kind, region_id=proposal.scope.region_id),
        base_style_version_id=proposal.base_style_version_id,
        base_topology_digest=proposal.base_topology_digest,
        profile=_reference_view(proposal.profile),
        reference_ids=list(proposal.reference_ids),
        model_id=proposal.model_id,
        prompt_version=proposal.prompt_version,
        refines_proposal_id=proposal.refines_proposal_id,
        recipe_binding=dict(record.recipe_binding),
        capability_mapping=dict(record.capability_mapping),
        status=record.status,
        validation_issues=list(record.validation_issues),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _source_view(source: WorldSourceMedia) -> SourceMediaView:
    asset_reference = None
    if source.evidence_path is not None and source.evidence_span_id is not None:
        asset_reference = SourceAssetReferenceView(
            href=source.evidence_path,
            authorization="workspace-bearer",
            provenance=SourceAssetProvenanceView(
                source_id=source.source_id,
                evidence_span_id=source.evidence_span_id,
            ),
        )
    return SourceMediaView(
        source_id=source.source_id,
        slot_key=source.slot_key,
        region_id=source.region_id,
        state=source.state.value,
        reason=source.reason,
        evidence_span_id=source.evidence_span_id,
        evidence_path=source.evidence_path,
        modality=source.modality,
        media_type=source.media_type,
        byte_size=source.byte_size,
        width=source.width,
        height=source.height,
        captured_at=source.captured_at,
        captured_at_uncertainty_ms=source.captured_at_uncertainty_ms,
        asset_reference=asset_reference,
        capture_ids=source.capture_ids,
    )
