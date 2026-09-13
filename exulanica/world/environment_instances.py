"""Pure authored-world contracts for pinned environment selections."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.errors import InvalidEnvironmentData, InvalidObjectData
from exulanica.world.objects import ObjectOrigin, Transform, validate_origin, validate_transform

ENVIRONMENT_INSTANCE_ID_PATTERN: Final = "^[a-z0-9]([a-z0-9:._-]{0,198}[a-z0-9])?$"
_INSTANCE_ID = re.compile(ENVIRONMENT_INSTANCE_ID_PATTERN)
EnvironmentAvailability = Literal[
    "available", "unavailable_bytes", "withdrawn", "binding_drift", "unknown"
]


@dataclass(frozen=True, slots=True)
class SourceAnchor:
    frame_name: str
    coordinate_scale: int
    coordinates: tuple[int, ...]

    def document(self) -> dict[str, Any]:
        return {
            "coordinate_scale": self.coordinate_scale,
            "coordinates": list(self.coordinates),
            "frame_name": self.frame_name,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentSelection:
    kind: Literal["whole_asset", "feature"]
    feature_id: str | None = None
    render_batch_id: int | None = None

    def document(self) -> dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "kind": self.kind,
            "render_batch_id": self.render_batch_id,
        }


@dataclass(frozen=True, slots=True)
class EnvironmentSourceBinding:
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None
    source_sha256: str
    source_receipt_sha256: str
    render_sha256: str
    render_receipt_sha256: str
    index_sha256: str | None
    index_receipt_sha256: str | None
    publication_receipt_sha256: str | None
    place_id: uuid.UUID
    frame: Mapping[str, Any]
    bounds: Mapping[str, Any]
    anchor: SourceAnchor
    selection: EnvironmentSelection

    def document(self) -> dict[str, Any]:
        return {
            "admission_id": str(self.admission_id),
            "anchor": self.anchor.document(),
            "bounds": dict(self.bounds),
            "frame": dict(self.frame),
            "index": (
                None
                if self.publication_id is None
                else {
                    "content_sha256": self.index_sha256,
                    "publication_id": str(self.publication_id),
                    "publication_receipt_sha256": self.publication_receipt_sha256,
                    "receipt_sha256": self.index_receipt_sha256,
                }
            ),
            "place_id": str(self.place_id),
            "render_asset": {
                "asset_id": str(self.render_asset_id),
                "content_sha256": self.render_sha256,
                "receipt_sha256": self.render_receipt_sha256,
            },
            "selection": self.selection.document(),
            "source": {
                "content_sha256": self.source_sha256,
                "receipt_sha256": self.source_receipt_sha256,
            },
        }


@dataclass(frozen=True, slots=True)
class EnvironmentInstance:
    instance_id: str
    source: EnvironmentSourceBinding
    region_id: str
    transform: Transform
    origin: ObjectOrigin
    removed: bool = False
    availability: EnvironmentAvailability = "unknown"


@dataclass(frozen=True, slots=True)
class EnvironmentPlacement:
    instance_id: str
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID | None
    selection: EnvironmentSelection
    source_anchor: SourceAnchor
    region_id: str
    transform: Transform
    origin: ObjectOrigin


def environment_instance_document(instance: EnvironmentInstance) -> dict[str, Any]:
    """Canonical state, excluding externally changing byte and withdrawal availability."""
    return {
        "instance_id": instance.instance_id,
        "origin": instance.origin.document(),
        "region_id": instance.region_id,
        "removed": instance.removed,
        "source": instance.source.document(),
        "transform": instance.transform.document(),
    }


def validate_environment_instance(
    instance: EnvironmentInstance, *, region_ids: frozenset[str]
) -> EnvironmentInstance:
    if not _INSTANCE_ID.fullmatch(instance.instance_id):
        raise InvalidEnvironmentData("environment instance_id has an invalid shape")
    if instance.region_id not in region_ids:
        raise InvalidEnvironmentData(f"{instance.region_id} is not a region of the source snapshot")
    try:
        validate_transform(instance.transform)
        validate_origin(instance.origin)
    except InvalidObjectData as exc:
        raise InvalidEnvironmentData(str(exc)) from exc
    anchor = instance.source.anchor
    frame = instance.source.frame
    axes = frame.get("axis_order")
    if (
        not anchor.frame_name
        or anchor.frame_name != frame.get("name")
        or isinstance(anchor.coordinate_scale, bool)
        or not isinstance(anchor.coordinate_scale, int)
        or anchor.coordinate_scale <= 0
        or not isinstance(axes, list)
        or len(anchor.coordinates) != len(axes)
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in anchor.coordinates
        )
    ):
        raise InvalidEnvironmentData(
            "source anchor must be an integer point in the pinned source frame"
        )
    bounds = instance.source.bounds
    coordinates = bounds.get("coordinates")
    if (
        bounds.get("kind") == "bbox"
        and (
            bounds.get("coordinate_scale") != anchor.coordinate_scale
            or not isinstance(coordinates, list)
            or len(coordinates) != len(anchor.coordinates) * 2
            or any(
                not coordinates[index]
                <= anchor.coordinates[index]
                <= coordinates[index + len(anchor.coordinates)]
                for index in range(len(anchor.coordinates))
            )
        )
    ):
        raise InvalidEnvironmentData("source anchor must fall within the pinned source bounds")
    selection = instance.source.selection
    if selection.kind == "whole_asset":
        if (
            selection.feature_id is not None
            or selection.render_batch_id is not None
            or instance.source.publication_id is not None
        ):
            raise InvalidEnvironmentData("whole-asset placement cannot name a feature publication")
    elif (
        selection.kind != "feature"
        or selection.feature_id is None
        or not re.fullmatch(r"[0-9a-f]{32}", selection.feature_id)
        or selection.render_batch_id is None
        or instance.source.publication_id is None
    ):
        raise InvalidEnvironmentData("feature placement requires an exact feature and render batch")
    return instance
