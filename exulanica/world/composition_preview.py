"""Server-authoritative composition: one resolver behind preview and apply.

A composition places an already-authorized representation into a named authored alternate
version through the existing object or environment edit history:

- a reviewed catalog asset, named by ``asset_key``, as an ``AuthoredObject`` via
  ``WorldObjectRepository.add_object``;
- an admitted environment source, named by admission, render asset, optional publication and
  selection, as an environment instance via ``WorldObjectRepository.add_environment``;
- a depth estimate from one reviewed photograph, named by the entry and attachment whose
  membership reaches it, as a point map instance via ``WorldObjectRepository.add_point_map``.

A saved-world source attachment is membership, not composition. It resolves, is classified with
``CompatibilityIntent.COMPOSE``, and is always refused. The photo point map kind is not an
exception to that: what it composes is the depth artifact reached THROUGH a current membership,
which is a different object with a different truth status and its own permission behind it, and
the attachment reference in the request says which membership rather than what to draw.

The request carries references and intent only. Everything that decides readiness is read here,
from the stored version row, the reviewed registry, the content-addressed store, admission rights
and the saved-world attachment rows, in the caller's workspace and world. No request field can
make a preview ready.

Preview is a dry run of apply rather than a second rule set: both call ``_resolve``, which runs the
repository's read-only validators (``validate_object_placement``, ``validate_environment_source``,
``validate_environment_placement``), and those share their validation code with the durable
writers. Apply then performs the durable write, which repeats the same validation under the
workspace lock, and translates a refusal raised there into the same reason vocabulary. For one
stored state, preview's ``blocked_reason`` and apply's refusal are therefore the same code.

No style or structure classification gates reviewed-asset or environment composition. The
durable writers compare the version's stored state and its source snapshot and nothing about
appearance, so a gate here would refuse edits the object and environment routes accept.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Literal

import psycopg
from psycopg import pq

from exulanica.errors import IntegrityError
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.environment_instances import (
    EnvironmentPlacement,
    EnvironmentSelection,
    SourceAnchor,
    environment_instance_document,
)
from exulanica.world.errors import (
    AssetNotPlaceable,
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    InvalidPointMapPlacement,
    PointMapNotPermitted,
    PointMapNotProduced,
    PointMapNotReadable,
    PointMapReviewDiffers,
    PointMapTooSparse,
    SourceAuthorityExpired,
    SourceNotCurrentMembership,
    StaleObjectBase,
    UnavailableAsset,
    UnknownWorldResource,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import (
    AuthoredObject,
    ObjectBehaviour,
    ObjectOrigin,
    Transform,
    object_document,
)
from exulanica.world.photo_point_maps import (
    PointMapInstance,
    PointMapPlacement,
    point_map_instance_document,
)
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.style_structure import (
    AuthoredVersionRef,
    CompatibilityIntent,
    SourceAttachmentRef,
)

__all__ = [
    "BLOCKED_REASONS",
    "CompositionBlocked",
    "CompositionPlacement",
    "CompositionPreview",
    "CompositionRequest",
    "EnvironmentAdmissionSource",
    "PhotoPointMapSource",
    "ReviewedAssetSource",
    "SourceAttachmentSource",
    "apply_composition",
    "preview_composition",
]

ChangeKind = Literal["add_object", "add_environment", "add_point_map", "none"]

#: Every code ``blocked_reason`` can carry. Stable: codes are added, never renamed.
BLOCKED_REASONS: frozenset[str] = frozenset(
    {
        "source_invalidated",
        "stale_base",
        "unknown_asset",
        "asset_not_placeable",
        "asset_bytes_unavailable",
        "environment_binding_unknown",
        "environment_withdrawn",
        "compose_not_permitted",
        "environment_bytes_unavailable",
        "environment_binding_drift",
        "unknown_attachment",
        "expired_source_not_composable",
        "attachment_is_not_composition",
        # The photo point map kind. Each names a different recovery, which is why none of them is
        # folded into one shared unavailable code: add the photograph back, allow 3D estimates
        # again, wait for the estimate, review it again, or accept that it cannot be placed.
        # (No quoted words in this block: a web test parses every quoted token between the
        # frozenset's parentheses as a code, and a quoted word in a comment reads as one.)
        "membership_not_current",
        "depth_not_permitted",
        "depth_not_produced",
        "review_differs_from_reference",
        "insufficient_depth",
        "point_map_bytes_unavailable",
        "placement_required",
        "invalid_placement",
        "subject_already_present",
    }
)

#: What a ready apply leaves unchanged on the version. Each entry is asserted by the PostgreSQL
#: composition tests against the stored version before and after apply.
_PRESERVES: tuple[str, ...] = (
    "source_snapshot_id",
    "style_version_id",
    "other_subjects",
    "prior_edits",
)


@dataclass(frozen=True, slots=True)
class ReviewedAssetSource:
    asset_key: str


@dataclass(frozen=True, slots=True)
class EnvironmentAdmissionSource:
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None
    selection: EnvironmentSelection


@dataclass(frozen=True, slots=True)
class SourceAttachmentSource:
    entry_id: uuid.UUID
    attachment_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PhotoPointMapSource:
    """The depth estimate reached through one saved world's current membership of a photograph.

    The same two identifiers :class:`SourceAttachmentSource` carries, and a different request:
    that one asks for the photograph itself to become geometry and is always refused; this one
    asks for the estimate the depth model made from it.
    """

    entry_id: uuid.UUID
    attachment_id: uuid.UUID


CompositionSource = (
    ReviewedAssetSource | EnvironmentAdmissionSource | SourceAttachmentSource | PhotoPointMapSource
)


@dataclass(frozen=True, slots=True)
class CompositionPlacement:
    """Where the person put it and what they called it. Validated by the durable validators."""

    subject_id: str
    region_id: str
    transform: Transform
    origin_role: str
    behaviour: ObjectBehaviour | None = None
    source_anchor: SourceAnchor | None = None


@dataclass(frozen=True, slots=True)
class CompositionRequest:
    base_state_sha256: str
    source: CompositionSource
    placement: CompositionPlacement | None = None


class CompositionBlocked(Exception):
    """Apply refused. ``str()`` is exactly the reason code, which is what a problem body carries."""

    def __init__(self, blocked_reason: str, detail: str | None = None) -> None:
        super().__init__(blocked_reason)
        self.blocked_reason = blocked_reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class CompositionPreview:
    """The server's verdict on one request against the stored state it read."""

    blocked_reason: str | None
    blocked_detail: str | None
    source: Mapping[str, Any]
    version: Mapping[str, Any]
    change_kind: ChangeKind
    subject_id: str | None
    subject_document: Mapping[str, Any] | None

    @property
    def availability(self) -> Literal["ready", "blocked"]:
        return "ready" if self.blocked_reason is None else "blocked"

    def document(self) -> dict[str, Any]:
        return {
            "availability": self.availability,
            "blocked_reason": self.blocked_reason,
            "blocked_detail": self.blocked_detail,
            "source": dict(self.source),
            "version": dict(self.version),
            "would_change": {
                "kind": self.change_kind,
                "subject_id": self.subject_id,
                "document": (
                    None if self.subject_document is None else dict(self.subject_document)
                ),
                "preserves": [] if self.change_kind == "none" else list(_PRESERVES),
            },
        }


def preview_composition(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
) -> CompositionPreview:
    """Resolve one request against stored state. Takes no lock and writes nothing.

    Every read happens in one read-only, repeatable-read transaction, so the verdict and the
    version it names come from one snapshot: a writer committing between two reads cannot make
    preview report ``stale_base`` beside a version block that still equals the base. Raises
    ``UnknownWorldResource`` for an absent, foreign or other-world version. Every other refusal is
    a blocked preview.
    """
    with _one_read_only_snapshot(repository.connection):
        return _resolve(repository, version_id, request).preview


def apply_composition(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
    *,
    actor: uuid.UUID,
) -> AlternateVersion:
    """Resolve again and perform exactly the resolved change, or raise ``CompositionBlocked``.

    Call it inside the write transaction that also advances any saved-world entry, after that
    entry's lock, so the resolution and the write see one state. The durable writer repeats every
    check under the workspace lock; a refusal it raises is translated into the reason preview would
    report for the same state. Anything else it raises is not a composition verdict and propagates
    unchanged.
    """
    resolved = _resolve(repository, version_id, request)
    preview = resolved.preview
    if preview.blocked_reason is not None:
        raise CompositionBlocked(preview.blocked_reason, preview.blocked_detail)
    subject = resolved.subject
    try:
        if isinstance(subject, AuthoredObject):
            return repository.add_object(
                version_id, subject, base_state_sha256=request.base_state_sha256, actor=actor
            )
        if isinstance(subject, PointMapInstance):
            return repository.add_point_map(
                version_id,
                PointMapPlacement(
                    instance_id=subject.instance_id,
                    entry_id=subject.source.entry_id,
                    attachment_id=subject.source.attachment_id,
                    region_id=subject.region_id,
                    transform=subject.transform,
                    origin=subject.origin,
                ),
                base_state_sha256=request.base_state_sha256,
                actor=actor,
            )
        assert isinstance(subject, EnvironmentPlacement), "a ready resolution names its subject"
        return repository.add_environment(
            version_id, subject, base_state_sha256=request.base_state_sha256, actor=actor
        )
    except Exception as exc:
        refusals = (
            _OBJECT_WRITE_REFUSALS
            if isinstance(subject, AuthoredObject)
            else _POINT_MAP_WRITE_REFUSALS
            if isinstance(subject, PointMapInstance)
            else _ENVIRONMENT_WRITE_REFUSALS
        )
        reason = _reason(exc, refusals)
        if reason is None:
            raise
        raise CompositionBlocked(reason, str(exc)) from exc


# -- resolution --------------------------------------------------------------------------------


@contextmanager
def _one_read_only_snapshot(connection: psycopg.Connection) -> Iterator[None]:
    """A read-only, repeatable-read transaction, or the caller's transaction when one is open.

    Isolation is chosen when a transaction begins, so inside a transaction the caller already
    opened, that transaction's snapshot rules apply and this adds only a savepoint.
    """
    if connection.info.transaction_status != pq.TransactionStatus.IDLE:
        with connection.transaction():
            yield
        return
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read, read only")
        yield


@dataclass(frozen=True, slots=True)
class _Resolution:
    preview: CompositionPreview
    subject: AuthoredObject | EnvironmentPlacement | PointMapInstance | None


_BASE_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    (InvalidatedSourceVersion, "source_invalidated"),
    (StaleObjectBase, "stale_base"),
)
_ENVIRONMENT_SOURCE_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    (UnknownWorldResource, "environment_binding_unknown"),
    (EnvironmentSourceWithdrawn, "environment_withdrawn"),
    (EnvironmentCompositionDenied, "compose_not_permitted"),
    (UnavailableAsset, "environment_bytes_unavailable"),
    (EnvironmentBindingDrift, "environment_binding_drift"),
    # The store holds bytes under the pinned digest that do not verify as those bytes: the exact
    # pinned bytes are no more available than if they were absent.
    (IntegrityError, "environment_bytes_unavailable"),
    # Before a destination exists, the only data a source can get wrong is its selection: a
    # feature id or render batch the exact publication does not contain.
    (InvalidEnvironmentData, "environment_binding_unknown"),
)
_OBJECT_PLACEMENT_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    *_BASE_REFUSALS,
    (UnavailableAsset, "asset_bytes_unavailable"),
    # Before its parent class: a component named by a placement is its own verdict.
    (AssetNotPlaceable, "asset_not_placeable"),
    (InvalidObjectData, "invalid_placement"),
    (InvalidObjectState, "subject_already_present"),
)
#: The point map source's refusals, in the resolver's own order. ``UnknownWorldResource`` stands
#: for both an attachment nobody made and one whose pinned rows no longer agree with each other:
#: in both cases this world's reference to that photograph is not something that resolves, and
#: splitting them would tell a caller which of somebody else's rows had moved.
_POINT_MAP_SOURCE_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    (UnknownWorldResource, "unknown_attachment"),
    (SourceNotCurrentMembership, "membership_not_current"),
    (SourceAuthorityExpired, "expired_source_not_composable"),
    (PointMapNotPermitted, "depth_not_permitted"),
    (PointMapReviewDiffers, "review_differs_from_reference"),
    (PointMapNotProduced, "depth_not_produced"),
    (PointMapTooSparse, "insufficient_depth"),
    (PointMapNotReadable, "point_map_bytes_unavailable"),
    (UnavailableAsset, "point_map_bytes_unavailable"),
    (IntegrityError, "point_map_bytes_unavailable"),
)
_POINT_MAP_PLACEMENT_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    *_BASE_REFUSALS,
    (InvalidObjectState, "subject_already_present"),
    *_POINT_MAP_SOURCE_REFUSALS,
    (InvalidPointMapPlacement, "invalid_placement"),
    (InvalidObjectData, "invalid_placement"),
)

_ENVIRONMENT_PLACEMENT_REFUSALS: tuple[tuple[type[Exception], str], ...] = (
    *_BASE_REFUSALS,
    (InvalidEnvironmentState, "subject_already_present"),
    *(pair for pair in _ENVIRONMENT_SOURCE_REFUSALS if pair[0] is not InvalidEnvironmentData),
    (InvalidEnvironmentData, "invalid_placement"),
)
#: The durable write's refusals. ``InvalidObjectState`` / ``InvalidEnvironmentState`` are left
#: out on purpose: after a ready resolution a duplicate id is only reachable through a moved base,
#: which the writer reports first as stale, so the state errors a writer can still raise mean
#: something else (the society input adapter) and must keep their own code.
_OBJECT_WRITE_REFUSALS = tuple(
    pair for pair in _OBJECT_PLACEMENT_REFUSALS if pair[0] is not InvalidObjectState
)
_ENVIRONMENT_WRITE_REFUSALS = tuple(
    pair for pair in _ENVIRONMENT_PLACEMENT_REFUSALS if pair[0] is not InvalidEnvironmentState
)
_POINT_MAP_WRITE_REFUSALS = tuple(
    pair for pair in _POINT_MAP_PLACEMENT_REFUSALS if pair[0] is not InvalidObjectState
)


def _reason(exc: Exception, table: tuple[tuple[type[Exception], str], ...]) -> str | None:
    for kind, reason in table:
        if isinstance(exc, kind):
            return reason
    return None


@dataclass(frozen=True, slots=True)
class _Frame:
    """What every verdict on one request states, whatever the verdict is."""

    version: Mapping[str, Any]
    kind: ChangeKind
    subject_id: str | None

    def blocked(self, reason: str, detail: str, source: Mapping[str, Any]) -> _Resolution:
        return _Resolution(
            CompositionPreview(
                reason, detail, source, self.version, self.kind, self.subject_id, None
            ),
            None,
        )

    def ready(
        self,
        source: Mapping[str, Any],
        document: Mapping[str, Any],
        subject: AuthoredObject | EnvironmentPlacement | PointMapInstance,
    ) -> _Resolution:
        return _Resolution(
            CompositionPreview(
                None, None, source, self.version, self.kind, self.subject_id, document
            ),
            subject,
        )


def _resolve(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
) -> _Resolution:
    row = repository.edit_base_row(version_id)
    source = request.source
    frame = _Frame(
        version={
            "authored_version_id": str(row["version_id"]),
            "world_id": row["world_id"],
            "state_sha256": row["state_sha256"],
            "edit_seq": int(row["edit_seq"]),
            "source_snapshot_id": str(row["source_snapshot_id"]),
            "style_version_id": (
                None if row["style_version_id"] is None else str(row["style_version_id"])
            ),
        },
        kind=(
            "add_object"
            if isinstance(source, ReviewedAssetSource)
            else "add_environment"
            if isinstance(source, EnvironmentAdmissionSource)
            else "add_point_map"
            if isinstance(source, PhotoPointMapSource)
            else "none"
        ),
        subject_id=None if request.placement is None else request.placement.subject_id,
    )
    try:
        repository.require_edit_base(row, request.base_state_sha256)
    except (InvalidatedSourceVersion, StaleObjectBase) as exc:
        reason = _reason(exc, _BASE_REFUSALS)
        assert reason is not None
        return frame.blocked(reason, str(exc), _unresolved_source_view(source))
    if isinstance(source, SourceAttachmentSource):
        reason, detail = _attachment_refusal(repository, version_id, source)
        return frame.blocked(reason, detail, _unresolved_source_view(source))
    if isinstance(source, PhotoPointMapSource):
        return _resolve_photo_point_map(repository, version_id, request, source, frame)
    if isinstance(source, ReviewedAssetSource):
        return _resolve_reviewed_asset(repository, version_id, request, source, frame)
    return _resolve_environment(repository, version_id, request, source, frame)


def _resolve_reviewed_asset(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
    source: ReviewedAssetSource,
    frame: _Frame,
) -> _Resolution:
    try:
        asset = repository.reviewed_asset(source.asset_key, repository.store)
    except UnknownWorldResource:
        return frame.blocked(
            "unknown_asset",
            f"no reviewed asset is named {source.asset_key}",
            _unresolved_source_view(source),
        )
    view = {
        "kind": "reviewed_asset",
        "asset_key": source.asset_key,
        "content_sha256": asset.content_sha256,
        # ``unknown`` (a repository with no store) maps to null: nobody looked.
        "bytes": {"available": "available", "unavailable_asset": "unavailable"}.get(
            asset.availability
        ),
    }
    # The asset's declared kind before its bytes: a component is never placeable, whether or not
    # its bytes are present, so restoring them is not the recovery.
    try:
        asset.require_placeable()
    except AssetNotPlaceable as exc:
        return frame.blocked("asset_not_placeable", str(exc), view)
    if asset.availability != "available":
        return frame.blocked(
            "asset_bytes_unavailable", "the reviewed asset row exists and its bytes do not", view
        )
    placement = request.placement
    if placement is None:
        return frame.blocked("placement_required", "the source resolves; name a placement", view)
    if placement.source_anchor is not None:
        return frame.blocked("invalid_placement", "a reviewed asset takes no source anchor", view)
    obj = AuthoredObject(
        object_id=placement.subject_id,
        asset_sha256=asset.content_sha256,
        region_id=placement.region_id,
        transform=placement.transform,
        origin=ObjectOrigin("authored", placement.origin_role),
        behaviour=placement.behaviour,
    )
    try:
        checked = repository.validate_object_placement(
            version_id, obj, base_state_sha256=request.base_state_sha256
        )
    except Exception as exc:
        reason = _reason(exc, _OBJECT_PLACEMENT_REFUSALS)
        if reason is None:
            raise
        return frame.blocked(reason, str(exc), view)
    return frame.ready(view, object_document(checked), checked)


def _resolve_environment(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
    source: EnvironmentAdmissionSource,
    frame: _Frame,
) -> _Resolution:
    unresolved = _unresolved_source_view(source)
    try:
        resolution = repository.validate_environment_source(
            source.admission_id,
            source.render_asset_id,
            source.publication_id,
            source.selection,
        )
    except Exception as exc:
        reason = _reason(exc, _ENVIRONMENT_SOURCE_REFUSALS)
        if reason is None:
            raise
        if reason == "environment_bytes_unavailable" and repository.store is not None:
            unresolved = {**unresolved, "bytes": "unavailable"}
        return frame.blocked(reason, str(exc), unresolved)
    view = {**unresolved, "content_sha256": resolution.render_sha256, "bytes": "available"}
    placement = request.placement
    if placement is None:
        return frame.blocked("placement_required", "the source resolves; name a placement", view)
    if placement.behaviour is not None:
        return frame.blocked(
            "invalid_placement", "an environment instance takes no behaviour", view
        )
    if placement.source_anchor is None:
        return frame.blocked(
            "invalid_placement", "an environment placement needs a source anchor", view
        )
    environment = EnvironmentPlacement(
        instance_id=placement.subject_id,
        admission_id=source.admission_id,
        render_asset_id=source.render_asset_id,
        publication_id=source.publication_id,
        selection=source.selection,
        source_anchor=placement.source_anchor,
        region_id=placement.region_id,
        transform=placement.transform,
        origin=ObjectOrigin("authored", placement.origin_role),
    )
    try:
        # The source this request resolved above, so each pinned blob is read once.
        instance = repository.validate_environment_placement(
            version_id,
            environment,
            base_state_sha256=request.base_state_sha256,
            resolved_source=resolution,
        )
    except Exception as exc:
        reason = _reason(exc, _ENVIRONMENT_PLACEMENT_REFUSALS)
        if reason is None:
            raise
        return frame.blocked(reason, str(exc), view)
    return frame.ready(view, environment_instance_document(instance), environment)


def _resolve_photo_point_map(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: CompositionRequest,
    source: PhotoPointMapSource,
    frame: _Frame,
) -> _Resolution:
    """Resolve the estimate, then the placement, in the durable writer's own order."""
    unresolved = _unresolved_source_view(source)
    try:
        resolved = repository.validate_point_map_source(source.entry_id, source.attachment_id)
    except Exception as exc:
        reason = _reason(exc, _POINT_MAP_SOURCE_REFUSALS)
        if reason is None:
            raise
        if reason == "point_map_bytes_unavailable" and repository.store is not None:
            unresolved = {**unresolved, "bytes": "unavailable"}
        return frame.blocked(reason, str(exc), unresolved)
    view = {
        **unresolved,
        "content_sha256": resolved.point_map_sha256,
        "bytes": "available",
        "capture_id": str(resolved.capture_id),
        "model": resolved.model.document(),
        "declared_metric": resolved.declared_metric,
        "rung": resolved.rung,
    }
    placement = request.placement
    if placement is None:
        return frame.blocked("placement_required", "the source resolves; name a placement", view)
    if placement.behaviour is not None:
        return frame.blocked("invalid_placement", "a placed estimate takes no behaviour", view)
    if placement.source_anchor is not None:
        return frame.blocked("invalid_placement", "a placed estimate takes no source anchor", view)
    instance = PointMapPlacement(
        instance_id=placement.subject_id,
        entry_id=source.entry_id,
        attachment_id=source.attachment_id,
        region_id=placement.region_id,
        transform=placement.transform,
        origin=ObjectOrigin("authored", placement.origin_role),
    )
    try:
        checked = repository.validate_point_map_placement(
            version_id,
            instance,
            base_state_sha256=request.base_state_sha256,
            resolved_source=resolved,
        )
    except Exception as exc:
        reason = _reason(exc, _POINT_MAP_PLACEMENT_REFUSALS)
        if reason is None:
            raise
        return frame.blocked(reason, str(exc), view)
    return frame.ready(view, point_map_instance_document(checked), checked)


def _attachment_refusal(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    source: SourceAttachmentSource,
) -> tuple[str, str]:
    """Always a refusal. Which one depends on whether the reference names a real attachment."""
    found = repository.connection.execute(
        "select 1 from saved_world_source_attachment a "
        "join saved_world_entry e on e.workspace_id=a.workspace_id and e.entry_id=a.entry_id "
        "where a.workspace_id=%s and a.entry_id=%s and a.attachment_id=%s and e.world_id=%s",
        (repository.workspace_id, source.entry_id, source.attachment_id, repository.world_id),
    ).fetchone()
    if found is None:
        return "unknown_attachment", "no such attachment on a saved world of this world"
    decision = WorldStyleRepository(
        repository.connection, repository.workspace_id, world_id=repository.world_id
    ).classify_structure_style_compatibility(
        intent=CompatibilityIntent.COMPOSE,
        authored=AuthoredVersionRef(version_id),
        attachments=(SourceAttachmentRef(source.attachment_id),),
    )
    if decision.token == "unknown_reference":
        return "unknown_attachment", "the attachment's authority rows do not resolve"
    return decision.token, "attachment membership is a project reference, not composition"


def _unresolved_source_view(source: CompositionSource) -> dict[str, Any]:
    if isinstance(source, ReviewedAssetSource):
        return {
            "kind": "reviewed_asset",
            "asset_key": source.asset_key,
            "content_sha256": None,
            "bytes": None,
        }
    if isinstance(source, EnvironmentAdmissionSource):
        return {
            "kind": "environment_admission",
            "admission_id": str(source.admission_id),
            "render_asset_id": str(source.render_asset_id),
            "publication_id": None if source.publication_id is None else str(source.publication_id),
            "selection": source.selection.document(),
            "content_sha256": None,
            "bytes": None,
        }
    if isinstance(source, PhotoPointMapSource):
        return {
            "kind": "photo_point_map",
            "entry_id": str(source.entry_id),
            "attachment_id": str(source.attachment_id),
            "content_sha256": None,
            "bytes": None,
            "capture_id": None,
            "model": None,
            "declared_metric": None,
            "rung": None,
        }
    return {
        "kind": "source_attachment",
        "entry_id": str(source.entry_id),
        "attachment_id": str(source.attachment_id),
        "content_sha256": None,
        "bytes": "not_applicable",
    }
