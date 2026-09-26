"""The alternate version as a client reads it, and how every route builds one.

Every route that answers with an authored version answers with :class:`AlternateVersionView`,
built here from the domain version, so the reviewed asset catalog, the objects, the environment
instances and the placed depth estimates reach a client in one shape whichever route produced
them. Asset and placement availability are resolved against the actual store by
:func:`rendered_version` rather than assumed: a renderer holding the body must be able to tell a
reviewed mesh it may draw from one whose bytes are gone.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field, JsonValue

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
from exulanica.world.object_catalog import NO_ACTIVITY, world_object_catalog
from exulanica.world.society_catalogs import purposeful_routine


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


#: The frame every position in an asset's use is stated in, as the world object catalog states it.
PART_FRAME = (
    "Millimetres in the kind's own part frame, about the bottom centre of what it draws: +x runs "
    "across the kind, +y is its front, the side that faces the person who places it, and +z is "
    "up. A placed object carries this frame by its transform: turned by its yaw about +z and "
    "scaled by its scale, with the part frame's +y toward the region's -z, so a point [x, y, z] "
    "is [x, z, -y] in the region's east, up and south axes before the turn."
)


class SeatView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_mm: list[int] = Field(
        description="Where the resting person's pelvis is drawn, [x, y, z]. " + PART_FRAME
    )
    faces: str = Field(
        description="The side of the kind the seated person faces: +y, +x, -y or -x."
    )


class PlaceView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    position_mm: list[int] = Field(
        description="Where an inhabitant stands to use the kind, [x, y]. " + PART_FRAME
    )
    faces: str = Field(
        description="The side of the kind a person standing here faces, across the place's side."
    )
    seat: SeatView | None = Field(
        description="Where a person resting here is drawn sitting, or null where people stand."
    )


class ObjectUseView(BaseModel):
    """What inhabitants do with a kind and where, derived by the world object catalog."""

    model_config = ConfigDict(extra="forbid")

    affordance: str
    places: list[PlaceView] | None = Field(
        description=(
            "One place per person, in the order the society fills them; null for a marker, "
            "whose places the society derives from its footprint and whose people stand."
        )
    )


class ObjectActivityView(BaseModel):
    """What inhabitants do at a kind and how long each stays, in the purposeful routine's words."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(
        description="The routine's entry for the kind, or its affordance's entry for every kind "
        "that states none of its own."
    )
    label: str = Field(description="What a person there is doing, in the routine's words.")
    duration_minimum_ticks: int = Field(
        description="The shortest stay, in the society's ticks of one simulated minute each."
    )
    duration_maximum_ticks: int = Field(
        description="The longest stay, in the society's ticks of one simulated minute each."
    )


class PlaceableAssetView(ReviewedAssetView):
    """A reviewed asset as the registry reads serve it, with what inhabitants do with it."""

    use: ObjectUseView | None = Field(
        description="The kind's use, as the world object catalog derives it; null for an asset "
        "the catalog does not state, such as a character part."
    )
    activity: ObjectActivityView | None = Field(
        description="What inhabitants do at the kind and for how long, as the purposeful routine "
        "a saved world's next society input records states it; null for a kind inhabitants do "
        "not use and for an asset the catalog does not state."
    )


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


def object_use_view(asset_key: str) -> ObjectUseView | None:
    """The use the world object catalog derives for an asset, or ``None`` for one it lacks.

    Served from the catalog's own derivation, the one the society's registry rows read, so the
    page draws people at the places the society fills and at no other.
    """
    kind = world_object_catalog().by_asset_key().get(asset_key)
    if kind is None:
        return None
    use = kind.use
    if use.places is None:
        return ObjectUseView(affordance=use.affordance, places=None)
    facing = use.facing or ()
    seats = use.seats or ()
    return ObjectUseView(
        affordance=use.affordance,
        places=[
            PlaceView(
                position_mm=list(place),
                faces=faces,
                seat=None
                if seat is None
                else SeatView(position_mm=list(seat.position_mm), faces=seat.faces),
            )
            for place, faces, seat in zip(use.places, facing, seats, strict=True)
        ],
    )


def object_activity_view(asset_key: str) -> ObjectActivityView | None:
    """What inhabitants do at an asset's kind, or ``None`` where they do nothing there.

    The routine's own answer, asked as the society's composer asks it for a placed object of the
    kind (``build_authored_ground_society_input_v3``): the kind's entry, else its affordance's, in
    the routine a new input records. A kind nobody uses is never asked, as the composer never asks
    for it, and neither is an asset the world object catalog does not state.
    """
    kind = world_object_catalog().by_asset_key().get(asset_key)
    if kind is None or kind.use.affordance == NO_ACTIVITY:
        return None
    activity = purposeful_routine().at_object(kind.use.affordance, kind.key)
    return ObjectActivityView(
        key=activity.key,
        label=activity.label,
        duration_minimum_ticks=activity.duration_minimum,
        duration_maximum_ticks=activity.duration_maximum,
    )


def placeable_asset_view(asset: ReviewedAssetRow) -> PlaceableAssetView:
    return PlaceableAssetView(
        **asset_view(asset).model_dump(),
        use=object_use_view(asset.asset_key),
        activity=object_activity_view(asset.asset_key),
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
    """One version body, with every asset's and placement's availability resolved against the store.

    Resolved rather than assumed. A renderer holding this body must be able to tell a reviewed
    mesh it may draw from one whose bytes are gone, and the answer to that has to come from
    looking. Looking reads the store, so a route calls this after the transaction that wrote
    ``version`` has committed: a writer returns its version without availability, because it may
    hold the global asset read lock until then (``docs/asset-read-currency.md``).
    """
    return alternate_version_view(
        repository.with_availability(version),
        {asset.content_sha256: asset for asset in repository.reviewed_assets(store)},
    )
