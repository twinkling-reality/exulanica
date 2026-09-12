"""The wire schema of ``GET /graph``. One explicit, closed document.

Not a route and barely a Python concern: these field names are a contract with
``web/packages/graph-client/src/client.ts``, and the TypeScript side has its own copy. Kept in one
file because these rows are one document, and because ``GraphPayload`` gives no field a default,
so a section the assembler forgets is a ValidationError rather than a silent null.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AssertionRow",
    "EntityRow",
    "GraphPayload",
    "HistoryRow",
    "MemberPersonRegionRow",
    "OccurrenceRow",
    "ProposalRow",
    "ReconstructionSceneMemberRow",
    "ReconstructionSceneRow",
    "SceneGeneratedGeometryRow",
    "SceneGenerationModelRow",
    "SceneGeometryReferenceRow",
    "SceneGroupRow",
    "ScenePointMapPlacementRow",
]


class AssertionRow(BaseModel):
    """One claim about an entity, with what produced it.

    ``produced_by`` is a discriminated shape rather than a string because the four provenance
    classes carry different obligations: an inference must name its run, a user statement must
    name a human, an external lookup must carry its url and when it was retrieved.
    """

    model_config = ConfigDict(extra="forbid")

    assertion_id: uuid.UUID
    kind: str
    predicate_key: str
    status: str
    object_value: Any
    support_span_ids: list[uuid.UUID]
    produced_by: dict[str, Any]
    asserted_at: str
    supersedes: uuid.UUID | None


class HistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    event_type: str
    actor: uuid.UUID
    payload: dict[str, Any]
    undoes: uuid.UUID | None
    created_at: str


class EntityRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: uuid.UUID
    entity_class: str
    display_name: str | None
    merged_into: uuid.UUID | None
    occurrence_count: int
    capture_ids: list[uuid.UUID]
    first_seen: str | None
    last_seen: str | None
    open_question_count: int
    assertions: list[AssertionRow]
    history: list[HistoryRow]
    #: Open disputes naming this entity's assertions. Empty until something writes a dispute,
    #: and empty here means "none recorded" rather than "not looked for".
    contradictions: list[dict[str, Any]]


class OccurrenceRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    occurrence_id: uuid.UUID
    capture_id: uuid.UUID
    occurrence_class: str
    primary_span_id: uuid.UUID
    entity_id: uuid.UUID | None
    link_state: str | None
    captured_at: str | None


class ProposalRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: uuid.UUID
    occurrence_id: uuid.UUID
    entity_id: uuid.UUID
    rank: int
    outcome: str
    basis: dict[str, Any]
    #: What this proposal carries that the user has not already refused for this pair. NULL when
    #: nothing about the pair was refused before, which is the ordinary case rather than a
    #: missing value. Decision id-4 requires an interface asking again to say what is new.
    new_modality: str | None
    suppressed_by_rejection: bool
    #: The spans the proposed occurrence rests on, so a confirmation surface can show them.
    support_span_ids: list[uuid.UUID]


class SceneGroupRow(BaseModel):
    """One run of captures close in time, and close in space when they carry a position.

    A PROPOSAL about arrangement, not a place and not an entity. ``orimera/ingest/scenes.py``
    is explicit that a scene-local grouping is not a persistent entity, and nothing here promotes
    it to one: the group has no name, and the place proposal that may be attached to it is a
    separate artifact that requires user confirmation.

    ``positioned_member_count`` is carried separately from ``member_count`` because a group whose
    members mostly had no fix was clustered on time alone, and a centroid computed from three of
    sixteen photographs is a different kind of number from one computed from all sixteen.
    """

    model_config = ConfigDict(extra="forbid")

    group_id: uuid.UUID
    ordinal: int
    capture_ids: list[uuid.UUID]
    first_utc: str | None
    last_utc: str | None
    member_count: int
    positioned_member_count: int
    #: Null when no member carried a position. Not zero: zero is a real radius.
    radius_m: int | None
    centroid_lat_e7: int | None
    centroid_lon_e7: int | None
    #: The reconstruction rung the captures in this group earned, WORST FIRST.
    #:
    #: The worst rather than the best or the mean, and that is the honest reduction. A region is
    #: navigable at the level of its weakest part: a group where one photograph has no geometry
    #: has a hole in it, and reporting the average would describe a region nobody can walk
    #: through as though they could. `null` means nothing in the group has been through
    #: reconstruction at all, which is a different fact from rung 4 and is not flattened into it.
    rung: int | None
    #: How many of the group's captures have a recorded rung. A rung derived from two of sixteen
    #: photographs is a weaker claim than one derived from all sixteen, and an interface that
    #: showed them identically would be flattening that.
    rung_capture_count: int


class SceneGeometryReferenceRow(BaseModel):
    """Authenticated, digest-declared bytes for one exact point-map artifact."""

    model_config = ConfigDict(extra="forbid")

    href: str
    authorization: Literal["workspace-bearer"]
    content_sha256: str
    byte_size: int


class ScenePointMapPlacementRow(BaseModel):
    """A verified scene transform and the exact immutable point map it places."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: uuid.UUID
    content_sha256: str
    container: str | None
    scene_from_opm_row_major: list[float]
    local_units_to_scene_units: float
    scale_status: Literal["colmap-correspondence-fit"]
    state: Literal["available", "bytes_missing"]
    reference: SceneGeometryReferenceRow | None


class SceneUnposedPhotographRow(BaseModel):
    """The image a viewer may see of one member, for drawing its unplaced depth in full detail.

    The route is the viewer route, ``/evidence/{span_id}/masked``, which serves the original when
    nobody in the photograph needs hiding and a current masked derivative when somebody does. The
    digest is the one that route resolved to when the graph was read, so a client that receives
    other bytes, because a consent changed in between, refuses them and draws the depth's own
    colours instead. It is never a way to reach an original the viewer route would not serve.
    """

    model_config = ConfigDict(extra="forbid")

    href: str
    authorization: Literal["workspace-bearer"]
    content_sha256: str
    byte_size: int


class SceneUnposedPointMapRow(BaseModel):
    """A member's own point map, offered because its scene's pose recovered no photograph.

    No transform, on purpose. Pose recovery found no position for any member, so there is no
    measured relation between one photograph's depth and another's, and saying where each one
    stands would be a claim nothing recorded. The client lays these out in an arrangement it
    labels as unmeasured. The bytes are the ones the scene's own placement record names by digest,
    read under the same live checks as a placed member's, so the lineage is the scene's and not a
    loose derivative's. Offered only when no member registered: a scene that placed some members
    keeps its excluded members as photographs, because mixing measured and unmeasured panels in
    one frame would let the unmeasured ones borrow the measured ones' authority, and a pose that
    registered members but was refused keeps its recorded meaning until that is decided.
    """

    model_config = ConfigDict(extra="forbid")

    artifact_id: uuid.UUID
    content_sha256: str
    container: str | None
    state: Literal["available", "bytes_missing"]
    reference: SceneGeometryReferenceRow | None
    #: Without a default, following this file's rule. Null when the viewer may currently see no
    #: image of this photograph, in which case the depth is drawn in its own colours.
    photograph: SceneUnposedPhotographRow | None


class SceneRecoveredCalibrationRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str
    width: int
    height: int
    fx: float
    fy: float
    cx: float
    cy: float
    parameters: list[float]


class SceneRecoveredCameraRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_from_camera_row_major: list[float]
    calibration: SceneRecoveredCalibrationRow
    projection: Literal["pinhole", "pinhole-approximation"]


class MemberPersonRegionRow(BaseModel):
    """One person in one photograph: their state, their outline, and never their pixels.

    The outline is here and the pixels are not, which is the whole presentation rule in one
    model. A masked region is drawn as a silhouette; the bytes behind it were replaced with
    neutral fill before reconstruction ever read them, so there is nothing here for a client bug
    to reveal.

    ``display_name`` is null unless naming was consented, somebody has actually been named, and
    that person has not withdrawn. Three separate conditions. The first two are separate because a
    person may consent to being named before anybody names them, and a name that appeared without
    the first would be the exact failure the three-consent split exists to prevent. The third is
    separate because a withdrawal is not a fourth consent and cannot be expressed by revoking one:
    ``person_consent_is_granted`` has no withdrawal term, so a subject who withdrew still holds
    their old naming receipt and the name has to be taken back above it.
    """

    model_config = ConfigDict(extra="forbid")

    region_id: str
    state: Literal["unknown", "present", "shown", "hidden", "withdrawn"]
    silhouette_ppm: list[list[int]]
    display_name: str | None
    subject_id: uuid.UUID | None


class ReviewSourceRow(BaseModel):
    """An admitted photograph, not a reconstruction scene or a composition slot."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admitted_capture"]
    capture_id: uuid.UUID
    evidence_span_id: uuid.UUID
    captured_at: str | None
    media_type: str
    state: Literal["available", "unavailable_asset"]
    reason: str | None
    evidence_path: str | None
    content_sha256: str | None
    person_regions: list[MemberPersonRegionRow]
    person_review_state: Literal["unscreened", "screened", "stale"]


class ReconstructionSceneMemberRow(BaseModel):
    """One immutable member and its exact placement or explicit exclusion."""

    model_config = ConfigDict(extra="forbid")

    capture_id: uuid.UUID
    ordinal: int
    registered: bool
    placement: ScenePointMapPlacementRow | None
    #: Without a default, following this file's rule: a member row assembled without deciding
    #: whether its unplaced depth may be shown would silently answer no.
    unposed_point_map: SceneUnposedPointMapRow | None
    exclusion_reason: str | None
    #: Deliberately without a default, following this file's rule. A member row assembled without
    #: thinking about the people in it would report an unscreened photograph as having nobody in
    #: it, which is the failure mode this whole feature exists to remove.
    person_regions: list[MemberPersonRegionRow]
    person_review_state: Literal["unscreened", "screened", "stale"]
    recovered_camera: SceneRecoveredCameraRow | None = None


class SceneTrainingQualityRow(BaseModel):
    """The measured held-out appearance and accounting behind an accepted trained scene.

    Appearance-held-out numbers with pose conditioning, exactly as the trainer's quality receipt
    recorded them; a summary for the status line, never a rung or a physical-scale claim.
    """

    model_config = ConfigDict(extra="forbid")

    heldout_views: int
    psnr: float
    ssim: float
    lpips: float
    coverage_fraction: float
    floaters_fraction: float
    iterations_completed: int
    duration_seconds: float
    usd_cost: float
    gpu: str


class SceneTrainedGeometryRow(BaseModel):
    """A trained representation with its own bytes; it never carries a rung assertion."""

    model_config = ConfigDict(extra="forbid")

    artifact_id: uuid.UUID
    content_sha256: str
    container: Literal["sog/1"]
    scene_from_asset_row_major: list[float]
    bounds: dict[str, list[float]]
    state: Literal["available", "bytes_missing", "invalid"]
    reference: SceneGeometryReferenceRow | None
    quality: SceneTrainingQualityRow


class SceneGenerationModelRow(BaseModel):
    """Which model produced a generated surface, at which version."""

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider: str
    model_id: str
    model_version: str


class SceneGeneratedGeometryRow(BaseModel):
    """Content a world model imagined, in its own tier below every recorded rung.

    A separate model from :class:`SceneTrainedGeometryRow` rather than a flag on it, because a
    client that ignored a flag would draw imagination as record. To draw one of these a client has
    to have read a field whose name says what it is.

    ``seam`` is where the record stops, in words, and it is required of every valid generation.
    ``conditioning`` is what the model was actually shown, digest by digest, which is what makes
    "conditioned on the real place" checkable rather than asserted.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    artifact_id: uuid.UUID
    receipt_sha256: str | None
    tier: Literal["generated"]
    state: Literal["available", "invalid"]
    state_reason: str | None
    model: SceneGenerationModelRow | None
    prompt_sha256: str | None
    conditioning: list[dict[str, str]]
    world_read_bundle_sha256: str | None
    container: str | None
    content_sha256: str | None
    byte_size: int | None
    seam: str | None


class ReconstructionSceneRow(BaseModel):
    """A durable multi-photograph scene with recorded and deliverable state kept separate."""

    model_config = ConfigDict(extra="forbid")

    scene_id: uuid.UUID
    member_digest: str
    pose_receipt_sha256: str | None
    placement_receipt_sha256: str | None
    gate_digest: str | None
    recorded_rung: Literal[1, 2, 3, 4] | None
    recorded_reasons: list[str]
    displayed_rung: Literal[1, 2, 3, 4]
    display_reasons: list[str]
    member_count: int
    registered_member_count: int
    receipt_state: Literal["available", "missing", "invalid"]
    #: ``none_placed`` is a pose that recovered no member, which is not missing bytes: every point
    #: map can be present and verified while nothing has a position.
    placement_state: Literal[
        "available", "partial", "none_placed", "bytes_missing", "unavailable", "invalid"
    ]
    rendering_substrate: Literal[
        "posed_point_maps", "unposed_point_maps", "source_photographs", "gaussian_splats"
    ]
    #: What the status line says out loud. Counted server-side rather than derived in the client,
    #: so a client that failed to load the regions cannot report zero hidden people.
    hidden_person_count: int
    masked_member_count: int
    trained_geometry: SceneTrainedGeometryRow | None = None
    members: list[ReconstructionSceneMemberRow]
    #: Without a default, following this file's rule. A scene row assembled without deciding what
    #: to say about generated content would report an empty list, and an empty list of generations
    #: is the one thing a viewer must always be able to trust: it means nothing was generated, not
    #: that nobody looked.
    generated_geometry: list[SceneGeneratedGeometryRow]


class GraphPayload(BaseModel):
    """One immutable read of the workspace, at one state version."""

    model_config = ConfigDict(extra="forbid")

    state_version: int
    review_sources: list[ReviewSourceRow] = Field(default_factory=list)
    entities: list[EntityRow]
    occurrences: list[OccurrenceRow]
    proposals: list[ProposalRow]
    scene_groups: list[SceneGroupRow]
    reconstruction_scenes: list[ReconstructionSceneRow]
    never_same: list[tuple[uuid.UUID, uuid.UUID]]
    deleted_entity_ids: list[uuid.UUID]
