"""The alternate version as a client reads it, and how every route builds one.

Every route that answers with an authored version answers with :class:`AlternateVersionView`,
built here from the domain version, so the reviewed asset catalog, the objects, the environment
instances and the placed depth estimates reach a client in one shape whichever route produced
them. Asset availability is resolved against the actual store by :func:`rendered_version` rather
than assumed: a renderer holding the body must be able to tell a reviewed mesh it may draw from one
whose bytes are gone.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, JsonValue

from exulanica.store.base import ContentAddressedStore
from exulanica.world import (
    AlternateVersion,
    ReviewedAssetRow,
    Transform,
    WorldObjectRepository,
    coverage_statement,
    point_map_instance_document,
    scale_statement,
    truth_statement,
)


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
    #: Whether a person may place this asset as an object, as its declared kind says. An object a
    #: version already holds embeds its asset whatever this says, and keeps drawing.
    placeable: bool


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
    point_map_instance_id: str | None
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
    #: Placed depth estimates from reviewed photographs, each with the state it can be drawn in.
    #: Availability is computed on read and is deliberately not part of ``state_sha256``: a right
    #: ending is not an edit, and a token that moved with one would refuse unrelated changes.
    point_map_instances: list[dict[str, JsonValue]]
    edits: list[VersionEditView]


def asset_view(asset: ReviewedAssetRow) -> ReviewedAssetView:
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
        placeable=asset.placeable,
    )


def transform_view(transform: Transform) -> TransformView:
    return TransformView(**transform.document())


def alternate_version_view(
    version: AlternateVersion, assets: dict[str, ReviewedAssetRow]
) -> AlternateVersionView:
    """``assets`` is keyed by content digest, which is how an object names one."""
    return AlternateVersionView(
        schema_version=(
            3 if version.point_map_instances else 2 if version.environment_instances else 1
        ),
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
                asset=asset_view(assets[obj.asset_sha256]),
                region_id=obj.region_id,
                transform=transform_view(obj.transform),
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
                    None if override.transform is None else transform_view(override.transform)
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
        point_map_instances=[
            {
                **point_map_instance_document(instance),
                "availability": instance.availability,
                "unavailable_reason": instance.unavailable_reason,
                # The three sentences an interface must not paraphrase. They are computed from the
                # stored placement rather than written in the client, so the words a person reads
                # about scale and coverage cannot drift from what the server placed.
                "truth": truth_statement(),
                "scale": scale_statement(instance),
                "coverage": coverage_statement(),
            }
            for instance in version.point_map_instances
        ],
        edits=[
            VersionEditView(
                edit_id=edit.edit_id,
                edit_seq=edit.edit_seq,
                kind=edit.kind,
                object_id=edit.object_id,
                element_id=edit.element_id,
                environment_instance_id=edit.environment_instance_id,
                point_map_instance_id=edit.point_map_instance_id,
                undone_edit_id=edit.undone_edit_id,
                base_state_sha256=edit.base_state_sha256,
                result_state_sha256=edit.result_state_sha256,
                actor=edit.actor,
                recorded_at=edit.recorded_at,
            )
            for edit in version.edits
        ],
    )


def rendered_version(
    repository: WorldObjectRepository, version: AlternateVersion, store: ContentAddressedStore
) -> AlternateVersionView:
    """One version body, with every asset's availability resolved against the actual store.

    Resolved rather than assumed. A renderer holding this body must be able to tell a reviewed
    mesh it may draw from one whose bytes are gone, and the answer to that has to come from
    looking.
    """
    return alternate_version_view(
        version, {asset.content_sha256: asset for asset in repository.reviewed_assets(store)}
    )
