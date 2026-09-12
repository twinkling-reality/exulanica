"""Validated, canonical contracts for reusable environment source bytes."""

from __future__ import annotations

import hashlib
import re
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from exulanica.canonical import canonical_json

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class EnvironmentOperation(StrEnum):
    DISPLAY = "display"
    EXTRACT = "extract"
    INDEX = "index"
    PERSIST = "persist"
    MODIFY = "modify"
    COMPOSE = "compose"
    EXPORT = "export"
    MODEL_PROCESSING = "model_processing"


class OperationRights(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    display: StrictBool
    extract: StrictBool
    index: StrictBool
    persist: StrictBool
    modify: StrictBool
    compose: StrictBool
    export: StrictBool
    model_processing: StrictBool


class GeographicFrame(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(min_length=1)]
    crs: Annotated[str, Field(min_length=1)]
    axis_order: tuple[str, ...]
    horizontal_unit: Annotated[str, Field(min_length=1)]
    vertical_unit: Annotated[str, Field(min_length=1)]
    orientation: Annotated[str, Field(min_length=1)]
    altitude_reference: Annotated[str, Field(min_length=1)]

    @field_validator("axis_order")
    @classmethod
    def _axes_are_explicit(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) not in (2, 3) or any(not axis.strip() for axis in value):
            raise ValueError("axis_order must name two or three non-empty axes")
        if len(set(value)) != len(value):
            raise ValueError("axis_order axes must be distinct")
        return value


class GeographicBounds(BaseModel):
    """Integer coordinates plus an explicit decimal scale; digest inputs contain no floats."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["bbox", "polygon", "feature"]
    frame_name: Annotated[str, Field(min_length=1)]
    coordinate_scale: Annotated[int, Field(gt=0)]
    coordinates: tuple[int, ...]

    @model_validator(mode="after")
    def _shape_is_explicit(self) -> GeographicBounds:
        if self.kind == "bbox" and len(self.coordinates) not in (4, 6):
            raise ValueError("bbox coordinates must contain two 2D or two 3D corners")
        if self.kind == "polygon" and len(self.coordinates) < 6:
            raise ValueError("polygon coordinates must contain at least three 2D points")
        if self.kind == "feature" and not self.coordinates:
            raise ValueError("feature bounds require at least one integer identifier component")
        return self


class SourceAdmission(BaseModel):
    """A declaration about an exact local file. This type performs no I/O."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    admission_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    place_id: uuid.UUID
    provider_key: Annotated[str, Field(min_length=1)]
    provider_original_id: Annotated[str, Field(min_length=1)]
    provider_revision: Annotated[str, Field(min_length=1)]
    expected_sha256: str
    expected_byte_size: Annotated[int, Field(ge=0)]
    source_path: Annotated[str, Field(min_length=1)]
    member_path: str | None = None
    media_type: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")]
    geographic_frame: GeographicFrame
    geographic_bounds: GeographicBounds
    operation_rights: OperationRights
    attribution: Annotated[str, Field(min_length=1)]
    modification_notice: Annotated[str, Field(min_length=1)]
    local_path: Path

    @field_validator(
        "provider_key",
        "provider_original_id",
        "provider_revision",
        "source_path",
        "member_path",
        "attribution",
        "modification_notice",
    )
    @classmethod
    def _trimmed(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("text identity fields must not carry surrounding whitespace")
        return value

    @field_validator("expected_sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def _bounds_use_declared_frame(self) -> SourceAdmission:
        if self.geographic_bounds.frame_name != self.geographic_frame.name:
            raise ValueError("geographic bounds must name the declared frame")
        if not self.operation_rights.persist:
            raise ValueError("admitting local bytes requires the persist operation right")
        return self


class DerivedEnvironmentAsset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    admission_id: uuid.UUID
    parent_asset_id: uuid.UUID | None = None
    expected_sha256: str
    expected_byte_size: Annotated[int, Field(ge=0)]
    source_member_path: str | None = None
    media_type: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9.+-]*/[a-z0-9][a-z0-9.+-]*$")]
    derivation_kind: Annotated[str, Field(min_length=1)]
    derivation_lineage: dict[str, Any]
    geographic_frame: GeographicFrame
    geographic_bounds: GeographicBounds
    operation_rights: OperationRights
    attribution: Annotated[str, Field(min_length=1)]
    modification_notice: Annotated[str, Field(min_length=1)]
    local_path: Path

    @field_validator("expected_sha256")
    @classmethod
    def _digest(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def _coherent(self) -> DerivedEnvironmentAsset:
        if self.geographic_bounds.frame_name != self.geographic_frame.name:
            raise ValueError("geographic bounds must name the declared frame")
        if not self.operation_rights.persist:
            raise ValueError("registering derived bytes requires the persist operation right")
        inputs = self.derivation_lineage.get("input_sha256")
        method = self.derivation_lineage.get("method")
        if (
            not isinstance(method, str)
            or not method.strip()
            or not isinstance(inputs, list)
            or not inputs
            or any(not isinstance(item, str) or not _SHA256.fullmatch(item) for item in inputs)
        ):
            raise ValueError(
                "derivation_lineage requires a method and non-empty input_sha256 list"
            )
        canonical_json(self.derivation_lineage)
        return self


def source_receipt(value: SourceAdmission) -> tuple[dict[str, Any], bytes, bytes]:
    record = {
        "profile": "exulanica.environment-source-admission/v1",
        "admission_id": str(value.admission_id),
        "place_id": str(value.place_id),
        "provider": {
            "key": value.provider_key,
            "original_id": value.provider_original_id,
            "revision": value.provider_revision,
        },
        "source_sha256": value.expected_sha256,
        "source_path": value.source_path,
        "member_path": value.member_path,
        "media_type": value.media_type,
        "byte_size": value.expected_byte_size,
        "geographic_frame": value.geographic_frame.model_dump(mode="json"),
        "geographic_bounds": value.geographic_bounds.model_dump(mode="json"),
        "operation_rights": value.operation_rights.model_dump(mode="json"),
        "attribution": value.attribution,
        "modification_notice": value.modification_notice,
    }
    encoded = canonical_json(record)
    return record, encoded, hashlib.sha256(encoded).digest()


def derived_receipt(
    value: DerivedEnvironmentAsset, *, source_sha256: str
) -> tuple[dict[str, Any], bytes, bytes]:
    record = {
        "profile": "exulanica.derived-environment-asset/v1",
        "asset_id": str(value.asset_id),
        "admission_id": str(value.admission_id),
        "parent_asset_id": str(value.parent_asset_id) if value.parent_asset_id else None,
        "source_sha256": source_sha256,
        "content_sha256": value.expected_sha256,
        "source_member_path": value.source_member_path,
        "media_type": value.media_type,
        "byte_size": value.expected_byte_size,
        "derivation_kind": value.derivation_kind,
        "derivation_lineage": value.derivation_lineage,
        "geographic_frame": value.geographic_frame.model_dump(mode="json"),
        "geographic_bounds": value.geographic_bounds.model_dump(mode="json"),
        "operation_rights": value.operation_rights.model_dump(mode="json"),
        "attribution": value.attribution,
        "modification_notice": value.modification_notice,
    }
    encoded = canonical_json(record)
    return record, encoded, hashlib.sha256(encoded).digest()
