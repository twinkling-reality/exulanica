"""Canonical, bounded feature catalogs for one admitted environment source."""

from __future__ import annotations

import hashlib
import uuid
from enum import StrEnum
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from exulanica.canonical import canonical_json
from exulanica.environment.admission import GeographicBounds, GeographicFrame

MAX_ENVIRONMENT_FEATURES = 512
FEATURE_INDEX_PROFILE = "exulanica.environment-feature-index/v1"
FEATURE_INDEX_ENVELOPE = "exulanica.environment-feature-index-envelope/v1"
FEATURE_INDEX_DERIVATION = "environment-feature-index"


class InvalidEnvironmentFeatureFilter(ValueError):
    pass


class EnvironmentFeatureKind(StrEnum):
    BUILDING = "building"
    TERRAIN = "terrain"
    WATER = "water"
    VEGETATION = "vegetation"
    TRANSPORTATION = "transportation"
    STRUCTURE = "structure"
    OBJECT = "object"
    OTHER = "other"


class EnvironmentFeatureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_feature_id: Annotated[str, Field(min_length=1, max_length=512)]
    kind: EnvironmentFeatureKind
    bbox: tuple[int, ...]
    label: Annotated[str, Field(min_length=1, max_length=512)] | None = None
    render_batch_id: Annotated[int, Field(ge=0, le=2_147_483_647)] | None = None

    @field_validator("provider_feature_id", "label")
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        if value is not None and (value != value.strip() or not value):
            raise ValueError("feature identity text must be non-empty and trimmed")
        return value

    @field_validator("bbox")
    @classmethod
    def _bbox(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        if len(value) not in (4, 6):
            raise ValueError("feature bbox must contain two 2D or two 3D corners")
        dimensions = len(value) // 2
        if any(value[index] > value[index + dimensions] for index in range(dimensions)):
            raise ValueError("feature bbox minimum must not exceed its maximum")
        return value


class FeatureIndexPublication(BaseModel):
    """A request to publish a complete replacement catalog for one admission."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    publication_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    render_asset_id: uuid.UUID
    features: tuple[EnvironmentFeatureInput, ...]

    @model_validator(mode="after")
    def _bounded_and_unique(self) -> FeatureIndexPublication:
        if len(self.features) > MAX_ENVIRONMENT_FEATURES:
            raise ValueError(f"a feature index permits at most {MAX_ENVIRONMENT_FEATURES} features")
        identifiers = [feature.provider_feature_id for feature in self.features]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("provider feature identifiers must be unique within an admission")
        batch_ids = [
            feature.render_batch_id
            for feature in self.features
            if feature.render_batch_id is not None
        ]
        if len(batch_ids) != len(set(batch_ids)):
            raise ValueError("render batch identifiers must be unique within a catalog")
        return self


def segment_id(
    *,
    provider_key: str,
    provider_original_id: str,
    provider_revision: str,
    provider_feature_id: str,
    source_sha256: str,
) -> str:
    """Derive a segment identifier from provider identity and exact admitted source bytes."""
    identity = {
        "profile": "exulanica.environment-provider-feature/v1",
        "provider_key": provider_key,
        "provider_original_id": provider_original_id,
        "provider_revision": provider_revision,
        "provider_feature_id": provider_feature_id,
        "source_sha256": source_sha256,
    }
    return hashlib.sha256(canonical_json(identity)).hexdigest()[:32]


def build_feature_index(
    value: FeatureIndexPublication,
    *,
    admission_id: uuid.UUID,
    place_id: uuid.UUID,
    provider_key: str,
    provider_original_id: str,
    provider_revision: str,
    source_sha256: str,
    source_receipt_sha256: str,
    render_sha256: str,
    render_receipt_sha256: str,
    geographic_frame: GeographicFrame,
    geographic_bounds: GeographicBounds,
) -> bytes:
    dimensions = len(geographic_frame.axis_order)
    if any(len(feature.bbox) != dimensions * 2 for feature in value.features):
        raise ValueError("every feature bbox must match the admitted geographic frame dimensions")
    features = [
        {
            "id": segment_id(
                provider_key=provider_key,
                provider_original_id=provider_original_id,
                provider_revision=provider_revision,
                provider_feature_id=feature.provider_feature_id,
                source_sha256=source_sha256,
            ),
            "provider_feature_id": feature.provider_feature_id,
            "kind": feature.kind.value,
            "bbox": list(feature.bbox),
            "label": feature.label,
            "render_batch_id": feature.render_batch_id,
        }
        for feature in value.features
    ]
    features.sort(key=lambda feature: feature["id"])
    payload = {
        "profile": FEATURE_INDEX_PROFILE,
        "admission_id": str(admission_id),
        "place_id": str(place_id),
        "provider": {
            "key": provider_key,
            "original_id": provider_original_id,
            "revision": provider_revision,
        },
        "source": {
            "content_sha256": source_sha256,
            "receipt_sha256": source_receipt_sha256,
        },
        "render_asset": {
            "asset_id": str(value.render_asset_id),
            "content_sha256": render_sha256,
            "receipt_sha256": render_receipt_sha256,
        },
        "geographic_frame": geographic_frame.model_dump(mode="json"),
        "coordinate_scale": geographic_bounds.coordinate_scale,
        "geographic_bounds": geographic_bounds.model_dump(mode="json"),
        "features": features,
    }
    envelope = {
        "profile": FEATURE_INDEX_ENVELOPE,
        "payload_sha256": hashlib.sha256(canonical_json(payload)).hexdigest(),
        "index": payload,
    }
    return canonical_json(envelope) + b"\n"


def validate_feature_index(
    data: bytes,
    *,
    admission_id: uuid.UUID,
    place_id: uuid.UUID,
    source_sha256: str,
    source_receipt_sha256: str,
    render_asset_id: uuid.UUID,
    render_sha256: str,
    render_receipt_sha256: str,
) -> dict[str, Any]:
    import json

    document = json.loads(data)
    if not isinstance(document, dict) or set(document) != {"profile", "payload_sha256", "index"}:
        raise ValueError("the environment feature index envelope is malformed")
    if document["profile"] != FEATURE_INDEX_ENVELOPE:
        raise ValueError("the environment feature index envelope version is unsupported")
    payload = document["index"]
    if not isinstance(payload, dict) or payload.get("profile") != FEATURE_INDEX_PROFILE:
        raise ValueError("the environment feature index version is unsupported")
    if set(payload) != {
        "profile",
        "admission_id",
        "place_id",
        "provider",
        "source",
        "render_asset",
        "geographic_frame",
        "coordinate_scale",
        "geographic_bounds",
        "features",
    }:
        raise ValueError("the environment feature index payload is malformed")
    if document["payload_sha256"] != hashlib.sha256(canonical_json(payload)).hexdigest():
        raise ValueError("the environment feature index payload disagrees with its digest")
    expected = {
        "admission_id": str(admission_id),
        "place_id": str(place_id),
        "source": {
            "content_sha256": source_sha256,
            "receipt_sha256": source_receipt_sha256,
        },
        "render_asset": {
            "asset_id": str(render_asset_id),
            "content_sha256": render_sha256,
            "receipt_sha256": render_receipt_sha256,
        },
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"the environment feature index is bound to another {key}")
    provider = payload.get("provider")
    frame = GeographicFrame.model_validate(payload.get("geographic_frame"))
    bounds = GeographicBounds.model_validate(payload.get("geographic_bounds"))
    if (
        bounds.frame_name != frame.name
        or payload.get("coordinate_scale") != bounds.coordinate_scale
        or not isinstance(provider, dict)
        or set(provider) != {"key", "original_id", "revision"}
        or any(not isinstance(provider[key], str) or not provider[key] for key in provider)
    ):
        raise ValueError("the environment feature index geographic binding is malformed")
    raw_features = payload.get("features")
    if not isinstance(raw_features, list) or len(raw_features) > MAX_ENVIRONMENT_FEATURES:
        raise ValueError("the environment feature list is malformed or exceeds its bound")
    identifiers: list[str] = []
    provider_ids: list[str] = []
    for raw in raw_features:
        if not isinstance(raw, dict) or set(raw) != {
            "id",
            "provider_feature_id",
            "kind",
            "bbox",
            "label",
            "render_batch_id",
        }:
            raise ValueError("an environment feature record is malformed")
        feature = EnvironmentFeatureInput.model_validate(
            {
                "provider_feature_id": raw["provider_feature_id"],
                "kind": raw["kind"],
                "bbox": raw["bbox"],
                "label": raw["label"],
                "render_batch_id": raw["render_batch_id"],
            }
        )
        expected_id = segment_id(
            provider_key=str(provider["key"]),
            provider_original_id=str(provider["original_id"]),
            provider_revision=str(provider["revision"]),
            provider_feature_id=feature.provider_feature_id,
            source_sha256=source_sha256,
        )
        if raw["id"] != expected_id:
            raise ValueError("an environment feature id is not provider-derived")
        identifiers.append(expected_id)
        provider_ids.append(feature.provider_feature_id)
        if len(feature.bbox) != len(frame.axis_order) * 2:
            raise ValueError(
                "an environment feature bbox disagrees with the geographic frame dimensions"
            )
    if identifiers != sorted(identifiers) or len(identifiers) != len(set(identifiers)):
        raise ValueError("environment features must be sorted and unique")
    if len(provider_ids) != len(set(provider_ids)):
        raise ValueError("provider feature identifiers must be unique")
    batch_ids = [
        feature["render_batch_id"]
        for feature in raw_features
        if feature["render_batch_id"] is not None
    ]
    if len(batch_ids) != len(set(batch_ids)):
        raise ValueError("render batch identifiers must be unique")
    return payload


def filter_features(
    features: list[dict[str, Any]],
    *,
    feature_id: str | None = None,
    kind: EnvironmentFeatureKind | None = None,
    bbox: tuple[int, ...] | None = None,
    label: str | None = None,
    dimensions: int,
) -> list[dict[str, Any]]:
    """Apply exact identity filters and inclusive spatial bbox intersection."""
    if bbox is not None and len(bbox) != dimensions * 2:
        raise InvalidEnvironmentFeatureFilter(
            "query bbox dimensionality must match the catalog geographic frame"
        )

    def intersects(feature_bbox: list[int]) -> bool:
        if bbox is None:
            return True
        return all(
            feature_bbox[axis] <= bbox[axis + dimensions]
            and bbox[axis] <= feature_bbox[axis + dimensions]
            for axis in range(dimensions)
        )

    return [
        feature
        for feature in features
        if (feature_id is None or feature["id"] == feature_id)
        and (kind is None or feature["kind"] == kind.value)
        and intersects(feature["bbox"])
        and (label is None or feature["label"] == label)
    ]
