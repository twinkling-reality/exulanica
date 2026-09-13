"""The appearance-only world customization API.

Routes validate transport shapes and delegate to :mod:`exulanica.world`.  There is no topology
mutation endpoint: topology registration belongs to the reviewed composition workflow, so a
browser, Settings, or Companion request cannot move a region or rewrite an evidence binding.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Final, Literal, TypeAlias

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import JSONResponse
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
from exulanica.evidence.blob import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world import (
    GLB_MEDIA_TYPE,
    MAX_SCALE_MILLI,
    MAX_YAW_MICRORADIANS,
    STYLE_REGISTRY,
    AlternateVersion,
    AuthoredObject,
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentPlacement,
    EnvironmentSelection,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    InvalidStructuralData,
    ObjectBehaviour,
    ObjectOrigin,
    ProposalOrigin,
    ProposalProvenance,
    ReviewedAssetRow,
    SourceAnchor,
    StaleObjectBase,
    StaleStructuralBase,
    StyleProposal,
    StyleProposalRecord,
    StyleReference,
    StyleScope,
    StyleVersion,
    Transform,
    UnavailableAsset,
    WorldObjectRepository,
    WorldSourceMedia,
    WorldStyleRepository,
)
from exulanica.world.bootstrap import bootstrap_world

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


# ------------------------------------------------------------------------------------------
# Authored world versions and created objects.
#
# A separate surface on the same router, and separate for a reason worth stating where the code
# is. The style routes above adapt an existing frontend recipe, so they accept camelCase aliases
# alongside snake_case. This surface has no prior client, `world_read.py` and `world_write.py`
# accept snake_case only, and the graph-client fixtures are snake_case. Inventing a second casing
# for a contract nobody has generated against yet would be inventing the problem the aliases
# above exist to solve.
#
# Domain failures here are mapped locally rather than through an `app.py` exception handler,
# following `world_write.py`. Registering this router therefore adds no global handler, and the
# response shape is the same `{code, detail}` every other route returns.
# ------------------------------------------------------------------------------------------


class TransformBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: StrictInt throughout. A float here would be refused by the canonical encoder later with a
    #: message about digests; refusing it at the transport edge names the field instead.
    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)
    scale_milli: StrictInt = Field(ge=1, le=MAX_SCALE_MILLI)

    def domain(self) -> Transform:
        return Transform(self.x_mm, self.y_mm, self.z_mm, self.yaw_microradians, self.scale_milli)


class BehaviourBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behaviour_key: str = Field(max_length=200)
    behaviour_version: int = Field(ge=1)
    parameters: dict[str, JsonValue]

    def domain(self) -> ObjectBehaviour:
        return ObjectBehaviour(self.behaviour_key, self.behaviour_version, self.parameters)


class BootstrapWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_topology_digest: str = Field(min_length=1, max_length=256)
    title: str = Field(default="My alternate world", min_length=1, max_length=200)


class BootstrapWorldView(BaseModel):
    snapshot: Literal["applied", "reused"]
    snapshot_id: uuid.UUID
    regions: list[str]
    version: Literal["created", "reused"]
    version_id: uuid.UUID
    state_sha256: str


class CreateVersionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=200)
    source_snapshot_id: uuid.UUID | None = None
    parent_version_id: uuid.UUID | None = None
    style_version_id: uuid.UUID | None = None


class AddObjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(min_length=64, max_length=64)
    object_id: str = Field(min_length=1, max_length=200)
    #: By content digest, not by reviewed name. A key is a pointer that could be repointed; the
    #: digest is the bytes, and it is what the version's state digest covers.
    asset_sha256: str = Field(min_length=64, max_length=64)
    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody
    #: The person chooses. Product direction is explicit that the first slice asks rather than
    #: classifies, so there is no default and no inference from the asset.
    origin_role: Literal["fictional", "personal"]
    behaviour: BehaviourBody | None = None


class SourceAnchorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_name: str = Field(min_length=1, max_length=200)
    coordinate_scale: StrictInt = Field(gt=0)
    coordinates: tuple[StrictInt, ...] = Field(min_length=2, max_length=3)

    def domain(self) -> SourceAnchor:
        return SourceAnchor(self.frame_name, self.coordinate_scale, self.coordinates)


class EnvironmentSelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["whole_asset", "feature"]
    feature_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    render_batch_id: StrictInt | None = Field(default=None, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def complete(self) -> EnvironmentSelectionBody:
        if self.kind == "feature" and (
            self.feature_id is None or self.render_batch_id is None
        ):
            raise ValueError("feature selection requires feature_id and render_batch_id")
        if self.kind == "whole_asset" and (
            self.feature_id is not None or self.render_batch_id is not None
        ):
            raise ValueError("whole-asset selection cannot name a feature or render batch")
        return self

    def domain(self) -> EnvironmentSelection:
        return EnvironmentSelection(self.kind, self.feature_id, self.render_batch_id)


class AddEnvironmentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    instance_id: str = Field(min_length=1, max_length=200)
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None = None
    selection: EnvironmentSelectionBody
    source_anchor: SourceAnchorBody
    region_id: str = Field(min_length=1, max_length=500)
    transform: TransformBody
    origin_role: Literal["fictional", "personal"]


class MoveObjectBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(min_length=64, max_length=64)
    transform: TransformBody


class BaseStateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(min_length=64, max_length=64)


class ReviewedAssetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_key: str
    title: str
    summary: str
    media_type: str
    content_sha256: str
    byte_size: int
    licence_id: str
    licence_sha256: str
    availability: str


class ObjectBehaviourView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behaviour_key: str
    behaviour_version: int
    parameters: dict[str, JsonValue]


class TransformView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    coordinate_space: str
    coordinate_unit: str
    x_mm: int
    y_mm: int
    z_mm: int
    yaw_microradians: int
    scale_milli: int


class ObjectOriginView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    role: str


class AuthoredObjectView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    asset: ReviewedAssetView
    region_id: str
    transform: TransformView
    origin: ObjectOriginView
    behaviour: ObjectBehaviourView | None
    removed: bool


class ElementOverrideView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    element_id: str
    suppressed: bool
    transform: TransformView | None


class VersionEditView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: uuid.UUID
    edit_seq: int
    kind: str
    object_id: str | None
    element_id: str | None
    environment_instance_id: str | None
    undone_edit_id: uuid.UUID | None
    base_state_sha256: str
    result_state_sha256: str
    actor: uuid.UUID
    recorded_at: str


class AlternateVersionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int
    version_id: uuid.UUID
    world_id: str
    source_snapshot_id: uuid.UUID
    parent_version_id: uuid.UUID | None
    title: str
    origin: str
    style_version_id: uuid.UUID | None
    state_sha256: str
    edit_seq: int
    source_invalidated: bool
    created_by: uuid.UUID
    created_at: str
    objects: list[AuthoredObjectView]
    element_overrides: list[ElementOverrideView]
    environment_instances: list[dict[str, JsonValue]]
    edits: list[VersionEditView]


def object_read_repository(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> WorldObjectRepository:
    return WorldObjectRepository(connection, session.workspace_id, store=services.store)


def object_write_repository(
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> WorldObjectRepository:
    return WorldObjectRepository(connection, session.workspace_id, store=services.store)


ReadObjects = Annotated[WorldObjectRepository, Depends(object_read_repository)]
WriteObjects = Annotated[WorldObjectRepository, Depends(object_write_repository)]

#: The domain failures this surface maps itself, and the code each one answers with. Reused
#: classes are absent on purpose: `UnknownWorldResource` and `UnavailableAsset` already have
#: application-wide handlers and must keep answering identically here.
_OBJECT_PROBLEMS: Final[tuple[tuple[type[Exception], int, str], ...]] = (
    (InvalidEnvironmentData, 422, "invalid_environment_data"),
    (InvalidEnvironmentState, 409, "invalid_environment_state"),
    (EnvironmentBindingDrift, 409, "environment_binding_drift"),
    (EnvironmentSourceWithdrawn, 410, "withdrawn"),
    (EnvironmentCompositionDenied, 403, "operation_denied"),
    (InvalidObjectData, 422, "invalid_object_data"),
    (InvalidStructuralData, 422, "invalid_structural_data"),
    (StaleStructuralBase, 409, "stale_structural_base"),
    (StaleObjectBase, 409, "stale_object_base"),
    (InvalidObjectState, 409, "invalid_object_state"),
    (InvalidatedSourceVersion, 409, "invalidated_source_version"),
)


def _object_problem(exc: Exception) -> JSONResponse | None:
    for kind, status, code in _OBJECT_PROBLEMS:
        if isinstance(exc, kind):
            return JSONResponse(status_code=status, content={"code": code, "detail": str(exc)})
    return None


def _asset_view(asset: ReviewedAssetRow) -> ReviewedAssetView:
    return ReviewedAssetView(
        asset_key=asset.asset_key,
        title=asset.title,
        summary=asset.summary,
        media_type=asset.media_type,
        content_sha256=asset.content_sha256,
        byte_size=asset.byte_size,
        licence_id=asset.licence_id,
        licence_sha256=asset.licence_sha256,
        availability=asset.availability,
    )


def _transform_view(transform: Transform) -> TransformView:
    return TransformView(**transform.document())


def _alternate_version_view(
    version: AlternateVersion, assets: dict[str, ReviewedAssetRow]
) -> AlternateVersionView:
    """``assets`` is keyed by content digest, which is how an object names one."""
    return AlternateVersionView(
        schema_version=2 if version.environment_instances else 1,
        version_id=version.version_id,
        world_id=version.world_id,
        source_snapshot_id=version.source_snapshot_id,
        parent_version_id=version.parent_version_id,
        title=version.title,
        origin="authored",
        style_version_id=version.style_version_id,
        state_sha256=version.state_sha256,
        edit_seq=version.edit_seq,
        source_invalidated=version.source_invalidated,
        created_by=version.created_by,
        created_at=version.created_at,
        objects=[
            AuthoredObjectView(
                object_id=obj.object_id,
                asset=_asset_view(assets[obj.asset_sha256]),
                region_id=obj.region_id,
                transform=_transform_view(obj.transform),
                origin=ObjectOriginView(kind=obj.origin.kind, role=obj.origin.role),
                behaviour=(
                    None
                    if obj.behaviour is None
                    else ObjectBehaviourView(
                        behaviour_key=obj.behaviour.behaviour_key,
                        behaviour_version=obj.behaviour.behaviour_version,
                        parameters=dict(obj.behaviour.parameters),
                    )
                ),
                removed=obj.removed,
            )
            for obj in version.objects
        ],
        element_overrides=[
            ElementOverrideView(
                element_id=override.element_id,
                suppressed=override.suppressed,
                transform=(
                    None if override.transform is None else _transform_view(override.transform)
                ),
            )
            for override in version.element_overrides
        ],
        environment_instances=[
            {
                **{
                    "instance_id": instance.instance_id,
                    "source": instance.source.document(),
                    "region_id": instance.region_id,
                    "transform": instance.transform.document(),
                    "origin": instance.origin.document(),
                    "removed": instance.removed,
                },
                "availability": instance.availability,
            }
            for instance in version.environment_instances
        ],
        edits=[
            VersionEditView(
                edit_id=edit.edit_id,
                edit_seq=edit.edit_seq,
                kind=edit.kind,
                object_id=edit.object_id,
                element_id=edit.element_id,
                environment_instance_id=edit.environment_instance_id,
                undone_edit_id=edit.undone_edit_id,
                base_state_sha256=edit.base_state_sha256,
                result_state_sha256=edit.result_state_sha256,
                actor=edit.actor,
                recorded_at=edit.recorded_at,
            )
            for edit in version.edits
        ],
    )


def _rendered(
    repository: WorldObjectRepository, version: AlternateVersion, store: ContentAddressedStore
) -> AlternateVersionView:
    """One version body, with every asset's availability resolved against the actual store.

    Resolved rather than assumed. A renderer holding this body must be able to tell a reviewed
    mesh it may draw from one whose bytes are gone, and the answer to that has to come from
    looking.
    """
    return _alternate_version_view(
        version, {asset.content_sha256: asset for asset in repository.reviewed_assets(store)}
    )


@router.get(
    "/assets",
    response_model=list[ReviewedAssetView],
    summary="The reviewed CC0 asset registry, read-only, with real byte availability.",
)
def reviewed_asset_catalog(repository: ReadObjects, request: Request) -> list[ReviewedAssetView]:
    store = get_services(request).store
    return [_asset_view(asset) for asset in repository.reviewed_assets(store)]


@router.get(
    "/assets/{asset_key}",
    response_model=ReviewedAssetView,
    summary="One reviewed asset and whether its bytes are present.",
)
def reviewed_asset(
    asset_key: Annotated[str, Path(max_length=200)],
    repository: ReadObjects,
    request: Request,
) -> ReviewedAssetView:
    return _asset_view(repository.reviewed_asset(asset_key, get_services(request).store))


@router.get(
    "/assets/{asset_key}/bytes",
    summary="The reviewed geometry itself. Never a citation target and never evidence.",
    responses={200: {"content": {GLB_MEDIA_TYPE: {}}}},
)
def reviewed_asset_bytes(
    asset_key: Annotated[str, Path(max_length=200)],
    repository: ReadObjects,
    request: Request,
) -> Response:
    store = get_services(request).store
    asset = repository.reviewed_asset(asset_key, store)
    if asset.availability != "available":
        # The same code and the same honesty as `/world/source-media`, reached through the same
        # application handler rather than a second 424 written out here: the row survived and the
        # bytes did not, and nothing substitutes a different mesh for the one that is gone.
        raise UnavailableAsset("the reviewed asset row exists and its bytes do not")
    payload = store.get(BlobId.from_hex(asset.content_sha256))
    return Response(
        content=payload,
        media_type=asset.media_type,
        headers={
            "ETag": f'"{asset.content_sha256}"',
            # NOT the point map's `no-store`, and the difference is the reasoning. That route
            # serves a personal derivative a tombstone has to be able to reach, so a cached copy
            # is a copy deletion cannot clear. A reviewed CC0 mesh is global reviewed data that
            # holds nothing personal, so it is cacheable.
            #
            # Cacheable, but NOT `immutable`. The bytes are immutable under content addressing;
            # this URL is not, because it is keyed by `asset_key` and a migration could point
            # that key at a different digest. `immutable` tells the browser never to revalidate,
            # which would make the ETag below unable to correct it. An hour, and a validator.
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )


@router.get(
    "/assets/{asset_key}/licence",
    summary="The licence text the reviewed bytes are published under.",
    responses={200: {"content": {"text/plain": {}}}},
)
def reviewed_asset_licence(
    asset_key: Annotated[str, Path(max_length=200)],
    repository: ReadObjects,
    request: Request,
) -> Response:
    store = get_services(request).store
    asset = repository.reviewed_asset(asset_key, store)
    licence = BlobId.from_hex(asset.licence_sha256)
    if not store.exists(licence):
        raise UnavailableAsset("the licence text for this asset is not in the store")
    return Response(
        content=store.get(licence),
        media_type="text/plain; charset=utf-8",
        headers={
            "ETag": f'"{asset.licence_sha256}"',
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )


@router.get(
    "/versions",
    response_model=list[AlternateVersionView],
    summary="Every alternate world version in this workspace, newest first.",
)
def alternate_versions(repository: ReadObjects, request: Request) -> list[AlternateVersionView]:
    store = get_services(request).store
    assets = {asset.content_sha256: asset for asset in repository.reviewed_assets(store)}
    return [_alternate_version_view(version, assets) for version in repository.versions()]


@router.post(
    "/versions",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Create an alternate version from a source snapshot or from another version.",
)
def create_alternate_version(
    body: CreateVersionBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    try:
        version = repository.create_version(
            source_snapshot_id=body.source_snapshot_id,
            parent_version_id=body.parent_version_id,
            title=body.title,
            style_version_id=body.style_version_id,
            created_by=session.actor,
        )
    except Exception as exc:
        problem = _object_problem(exc)
        if problem is None:
            raise
        return problem
    return _rendered(repository, version, get_services(request).store)


@router.post(
    "/versions/bootstrap",
    response_model=BootstrapWorldView,
    summary="Open the first snapshot and alternate from the current composed sources.",
)
def bootstrap_alternate_version(
    body: BootstrapWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
) -> Response | BootstrapWorldView:
    try:
        return BootstrapWorldView(
            **bootstrap_world(
                connection,
                workspace_id=session.workspace_id,
                actor=session.actor,
                base_topology_digest=body.base_topology_digest,
                title=body.title,
            )
        )
    except Exception as exc:
        problem = _object_problem(exc)
        if problem is None:
            raise
        return problem


@router.get(
    "/versions/{version_id}",
    response_model=AlternateVersionView,
    summary="One alternate version with its objects, overrides and edit history.",
)
def alternate_version(
    version_id: Annotated[uuid.UUID, Path()],
    repository: ReadObjects,
    request: Request,
) -> AlternateVersionView:
    return _rendered(repository, repository.version(version_id), get_services(request).store)


@router.post(
    "/versions/{version_id}/environment-instances",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Place one exact environment asset or feature against the current version state.",
)
def add_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    body: AddEnvironmentBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    placement = EnvironmentPlacement(
        instance_id=body.instance_id,
        admission_id=body.admission_id,
        render_asset_id=body.render_asset_id,
        publication_id=body.publication_id,
        selection=body.selection.domain(),
        source_anchor=body.source_anchor.domain(),
        region_id=body.region_id,
        transform=body.transform.domain(),
        origin=ObjectOrigin("authored", body.origin_role),
    )
    return _edit(
        request,
        repository,
        lambda: repository.add_environment(
            version_id,
            placement,
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/{instance_id}/move",
    response_model=AlternateVersionView,
    summary="Move an available, still-authorized environment instance without changing its source.",
)
def move_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    instance_id: Annotated[str, Path(max_length=200)],
    body: MoveObjectBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.move_environment(
            version_id,
            instance_id,
            body.transform.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/{instance_id}/remove",
    response_model=AlternateVersionView,
    summary="Store a removal, including when the pinned source has since been withdrawn.",
)
def remove_environment_instance(
    version_id: Annotated[uuid.UUID, Path()],
    instance_id: Annotated[str, Path(max_length=200)],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.remove_environment(
            version_id,
            instance_id,
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/environment-instances/undo",
    response_model=AlternateVersionView,
    summary="Undo the newest authored edit from stored history, even after source withdrawal.",
)
def undo_environment_edit(
    version_id: Annotated[uuid.UUID, Path()],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.undo(
            version_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/objects",
    response_model=AlternateVersionView,
    status_code=201,
    summary="Add one authored object against an explicit base version state.",
)
def add_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    body: AddObjectBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    obj = AuthoredObject(
        object_id=body.object_id,
        asset_sha256=body.asset_sha256,
        region_id=body.region_id,
        transform=body.transform.domain(),
        origin=ObjectOrigin("authored", body.origin_role),
        behaviour=None if body.behaviour is None else body.behaviour.domain(),
    )
    return _edit(
        request,
        repository,
        lambda: repository.add_object(
            version_id, obj, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/objects/{object_id}/move",
    response_model=AlternateVersionView,
    summary="Replace one authored object's region-local transform.",
)
def move_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    object_id: Annotated[str, Path(max_length=200)],
    body: MoveObjectBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.move_object(
            version_id,
            object_id,
            body.transform.domain(),
            base_state_sha256=body.base_state_sha256,
            actor=session.actor,
        ),
    )


@router.post(
    "/versions/{version_id}/objects/{object_id}/remove",
    response_model=AlternateVersionView,
    summary="Store a removal. POST rather than DELETE: this appends history, it destroys nothing.",
)
def remove_authored_object(
    version_id: Annotated[uuid.UUID, Path()],
    object_id: Annotated[str, Path(max_length=200)],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.remove_object(
            version_id, object_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


@router.post(
    "/versions/{version_id}/objects/undo",
    response_model=AlternateVersionView,
    summary="Reverse the newest object edit, from the document that edit stored.",
)
def undo_authored_edit(
    version_id: Annotated[uuid.UUID, Path()],
    body: BaseStateBody,
    repository: WriteObjects,
    session: CurrentSession,
    request: Request,
) -> Response | AlternateVersionView:
    return _edit(
        request,
        repository,
        lambda: repository.undo(
            version_id, base_state_sha256=body.base_state_sha256, actor=session.actor
        ),
    )


def _edit(
    request: Request,
    repository: WorldObjectRepository,
    operation: Callable[[], AlternateVersion],
) -> Response | AlternateVersionView:
    """Run one mutation and answer with the whole version, or with this surface's problem shape.

    The whole version rather than the changed object, because the caller needs the new
    ``state_sha256`` to make its next edit and a second round trip to fetch it is a second chance
    for another writer to move the base first.
    """
    try:
        version = operation()
    except Exception as exc:
        problem = _object_problem(exc)
        if problem is None:
            raise
        return problem
    return _rendered(repository, version, get_services(request).store)
