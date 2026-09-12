from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.environment import (
    MAX_ENVIRONMENT_FEATURES,
    EnvironmentFeatureInput,
    EnvironmentFeatureKind,
    FeatureIndexPublication,
    GeographicBounds,
    GeographicFrame,
    build_feature_index,
    filter_features,
    segment_id,
    validate_feature_index,
)
from pydantic import ValidationError


def _frame() -> GeographicFrame:
    return GeographicFrame(
        name="provider-grid",
        crs="EPSG:6697",
        axis_order=("east", "north", "height"),
        horizontal_unit="metre",
        vertical_unit="metre",
        orientation="right-handed",
        altitude_reference="JGD2011",
    )


def _bounds() -> GeographicBounds:
    return GeographicBounds(
        kind="bbox",
        frame_name="provider-grid",
        coordinate_scale=1000,
        coordinates=(0, 0, 0, 10000, 10000, 10000),
    )


def _publication(*features: EnvironmentFeatureInput) -> FeatureIndexPublication:
    return FeatureIndexPublication(
        publication_id=uuid.UUID("61b0d774-a8bc-4d76-9850-eac7bd5194dd"),
        render_asset_id=uuid.UUID("2c92fc99-67f1-453d-aacd-1105c2229445"),
        features=features,
    )


def _bytes(value: FeatureIndexPublication) -> bytes:
    return build_feature_index(
        value,
        admission_id=uuid.UUID("8d1566cb-37cd-43db-b60a-b59023566d13"),
        provider_key="plateau",
        provider_original_id="shibuya",
        provider_revision="2023",
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
        geographic_frame=_frame(),
        geographic_bounds=_bounds(),
    )


def _validate(data: bytes):
    return validate_feature_index(
        data,
        admission_id=uuid.UUID("8d1566cb-37cd-43db-b60a-b59023566d13"),
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_asset_id=uuid.UUID("2c92fc99-67f1-453d-aacd-1105c2229445"),
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
    )


def test_catalog_is_bounded_sorted_unique_and_provider_derived():
    first = EnvironmentFeatureInput(
        provider_feature_id="gml-building-2",
        kind="building",
        bbox=(20, 20, 30, 30),
        label="Annex",
    )
    second = EnvironmentFeatureInput(
        provider_feature_id="gml-building-1",
        kind="building",
        bbox=(0, 0, 10, 10),
        label="Hall",
    )
    payload = _validate(_bytes(_publication(first, second)))
    identifiers = [feature["id"] for feature in payload["features"]]
    assert identifiers == sorted(identifiers)
    assert payload["features"][0]["id"] == segment_id(
        provider_key="plateau",
        provider_original_id="shibuya",
        provider_revision="2023",
        provider_feature_id=payload["features"][0]["provider_feature_id"],
    )

    with pytest.raises(ValidationError, match="unique"):
        _publication(first, first)
    with pytest.raises(ValidationError, match="at most 512"):
        FeatureIndexPublication(
            render_asset_id=uuid.uuid4(),
            features=tuple(
                EnvironmentFeatureInput(
                    provider_feature_id=str(index),
                    kind="other",
                    bbox=(0, 0, 1, 1),
                )
                for index in range(MAX_ENVIRONMENT_FEATURES + 1)
            ),
        )


def test_digest_id_and_sort_tampering_fail_validation():
    document = json.loads(
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="one", kind="terrain", bbox=(0, 0, 1, 1)
                ),
                EnvironmentFeatureInput(provider_feature_id="two", kind="water", bbox=(2, 2, 3, 3)),
            )
        )
    )
    document["index"]["features"].reverse()
    document["payload_sha256"] = hashlib.sha256(canonical_json(document["index"])).hexdigest()
    with pytest.raises(ValueError, match="sorted"):
        _validate(canonical_json(document))

    document["index"]["features"].sort(key=lambda feature: feature["id"])
    document["index"]["features"][0]["id"] = "0" * 32
    document["payload_sha256"] = hashlib.sha256(canonical_json(document["index"])).hexdigest()
    with pytest.raises(ValueError, match="provider-derived"):
        _validate(canonical_json(document))


def test_filters_are_typed_and_exact():
    features = _validate(
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="one",
                    kind="building",
                    bbox=(0, 0, 1, 1),
                    label="Hall",
                )
            )
        )
    )["features"]
    feature_id = features[0]["id"]
    assert (
        filter_features(
            features,
            feature_id=feature_id,
            kind=EnvironmentFeatureKind.BUILDING,
            bbox=(0, 0, 1, 1),
            label="Hall",
        )
        == features
    )
    assert filter_features(features, label="hall") == []
    assert filter_features(features, bbox=(0, 0, 2, 2)) == []
