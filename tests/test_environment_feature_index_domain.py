from __future__ import annotations

import hashlib
import json
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.environment import (
    FEATURE_INDEX_ENVELOPE_V1,
    FEATURE_INDEX_ENVELOPE_V2,
    FEATURE_INDEX_PROFILE_V1,
    FEATURE_INDEX_PROFILE_V2,
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
        place_id=uuid.UUID("22c1d8ac-79b3-44b8-b72c-5967aed94f99"),
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


def _bytes_2d(value: FeatureIndexPublication) -> bytes:
    return build_feature_index(
        value,
        admission_id=uuid.UUID("8d1566cb-37cd-43db-b60a-b59023566d13"),
        place_id=uuid.UUID("22c1d8ac-79b3-44b8-b72c-5967aed94f99"),
        provider_key="nyc-open-data",
        provider_original_id="buildings",
        provider_revision="2026",
        source_sha256="1" * 64,
        source_receipt_sha256="2" * 64,
        render_sha256="3" * 64,
        render_receipt_sha256="4" * 64,
        geographic_frame=GeographicFrame(
            name="nyc-open-data-crs84",
            crs="OGC:CRS84",
            axis_order=("longitude", "latitude"),
            horizontal_unit="degree",
            vertical_unit="not_applicable",
            orientation="east-north",
            altitude_reference="not_applicable_2d",
        ),
        geographic_bounds=GeographicBounds(
            kind="bbox",
            frame_name="nyc-open-data-crs84",
            coordinate_scale=10_000_000,
            coordinates=(0, 0, 10, 20),
        ),
    )


def _validate(data: bytes):
    return validate_feature_index(
        data,
        admission_id=uuid.UUID("8d1566cb-37cd-43db-b60a-b59023566d13"),
        place_id=uuid.UUID("22c1d8ac-79b3-44b8-b72c-5967aed94f99"),
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
        bbox=(20, 20, 0, 30, 30, 10),
        label="Annex",
        render_batch_id=2,
    )
    second = EnvironmentFeatureInput(
        provider_feature_id="gml-building-1",
        kind="building",
        bbox=(0, 0, 0, 10, 10, 10),
        label="Hall",
        render_batch_id=1,
    )
    payload = _validate(_bytes(_publication(first, second)))
    built = json.loads(_bytes(_publication(first, second)))
    assert built["profile"] == FEATURE_INDEX_ENVELOPE_V2
    assert built["index"]["profile"] == FEATURE_INDEX_PROFILE_V2
    identifiers = [feature["id"] for feature in payload["features"]]
    assert identifiers == sorted(identifiers)
    assert payload["place_id"] == "22c1d8ac-79b3-44b8-b72c-5967aed94f99"
    assert payload["geographic_frame"]["name"] == "provider-grid"
    assert payload["coordinate_scale"] == 1000
    assert payload["features"][0]["id"] == segment_id(
        provider_key="plateau",
        provider_original_id="shibuya",
        provider_revision="2023",
        provider_feature_id=payload["features"][0]["provider_feature_id"],
        source_sha256="1" * 64,
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
                    bbox=(0, 0, 0, 1, 1, 1),
                )
                for index in range(MAX_ENVIRONMENT_FEATURES + 1)
            ),
        )
    with pytest.raises(ValueError, match="dimensions"):
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="two-dimensional",
                    kind="other",
                    bbox=(0, 0, 1, 1),
                )
            )
        )


def test_digest_id_and_sort_tampering_fail_validation():
    document = json.loads(
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="one", kind="terrain", bbox=(0, 0, 0, 1, 1, 1)
                ),
                EnvironmentFeatureInput(
                    provider_feature_id="two", kind="water", bbox=(2, 2, 2, 3, 3, 3)
                ),
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


def test_identity_filters_are_exact_and_bbox_filter_intersects():
    features = _validate(
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="one",
                    kind="building",
                    bbox=(0, 0, 0, 10, 10, 10),
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
            bbox=(5, 5, 5, 15, 15, 15),
            label="Hall",
            dimensions=3,
        )
        == features
    )
    assert filter_features(features, label="hall", dimensions=3) == []
    assert (
        filter_features(
            features,
            bbox=(20, 20, 20, 30, 30, 30),
            dimensions=3,
        )
        == []
    )
    with pytest.raises(ValueError, match="dimensionality"):
        filter_features(features, bbox=(0, 0, 10, 10), dimensions=3)


def test_segment_identity_binds_source_bytes_and_render_batch_ids_are_optional_unique():
    identity = {
        "provider_key": "provider",
        "provider_original_id": "city",
        "provider_revision": "2026-09",
        "provider_feature_id": "building-1",
    }
    first = segment_id(**identity, source_sha256="1" * 64)
    assert first == segment_id(**identity, source_sha256="1" * 64)
    assert first != segment_id(**identity, source_sha256="2" * 64)

    feature = EnvironmentFeatureInput(
        provider_feature_id="one",
        kind="building",
        bbox=(0, 0, 0, 1, 1, 1),
        render_batch_id=7,
    )
    with pytest.raises(ValidationError, match="batch"):
        _publication(feature, feature.model_copy(update={"provider_feature_id": "two"}))
    assert (
        _publication(feature.model_copy(update={"render_batch_id": None}))
        .features[0]
        .render_batch_id
        is None
    )


def test_integer_footprint_and_semantic_identity_are_bbox_bound():
    footprint = {
        "type": "MultiPolygon",
        "coordinates": [[[[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]]]],
    }
    feature = EnvironmentFeatureInput(
        provider_feature_id="doitt_id:2327",
        kind="building",
        bbox=(0, 0, 10, 20),
        render_batch_id=0,
        footprint=footprint,
        semantic_properties={"bin": "bin:1006070", "name": None},
    )
    assert feature.footprint == footprint
    assert feature.semantic_properties["bin"] == "bin:1006070"

    with pytest.raises(ValidationError, match="extent"):
        EnvironmentFeatureInput.model_validate(
            {**feature.model_dump(), "bbox": (0, 0, 9, 20)}
        )


def test_exact_legacy_v1_shape_remains_accepted_and_versions_cannot_mix():
    document = json.loads(
        _bytes(
            _publication(
                EnvironmentFeatureInput(
                    provider_feature_id="legacy",
                    kind="building",
                    bbox=(0, 0, 0, 10, 10, 10),
                    label="Legacy",
                    render_batch_id=1,
                )
            )
        )
    )
    document["profile"] = FEATURE_INDEX_ENVELOPE_V1
    document["index"]["profile"] = FEATURE_INDEX_PROFILE_V1
    for feature in document["index"]["features"]:
        del feature["footprint"]
        del feature["semantic_properties"]
    document["payload_sha256"] = hashlib.sha256(canonical_json(document["index"])).hexdigest()
    legacy_bytes = canonical_json(document) + b"\n"

    assert _validate(legacy_bytes)["features"][0] == {
        "bbox": [0, 0, 0, 10, 10, 10],
        "id": segment_id(
            provider_key="plateau",
            provider_original_id="shibuya",
            provider_revision="2023",
            provider_feature_id="legacy",
            source_sha256="1" * 64,
        ),
        "kind": "building",
        "label": "Legacy",
        "provider_feature_id": "legacy",
        "render_batch_id": 1,
    }

    mixed = json.loads(legacy_bytes)
    mixed["profile"] = FEATURE_INDEX_ENVELOPE_V2
    with pytest.raises(ValueError, match="versions disagree"):
        _validate(canonical_json(mixed))

    unknown = json.loads(legacy_bytes)
    unknown["profile"] = "exulanica.environment-feature-index-envelope/v99"
    with pytest.raises(ValueError, match="unsupported"):
        _validate(canonical_json(unknown))


def test_v2_extended_payload_is_deterministic_digest_bound_and_exact():
    feature = EnvironmentFeatureInput(
        provider_feature_id="doitt_id:2327",
        kind="building",
        bbox=(0, 0, 10, 20),
        render_batch_id=0,
        footprint={
            "type": "MultiPolygon",
            "coordinates": [[[[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]]]],
        },
        semantic_properties={"bin": "bin:1006070", "name": None},
    )
    first = _bytes_2d(_publication(feature))
    second = _bytes_2d(_publication(feature))
    assert first == second
    document = json.loads(first)
    assert document["payload_sha256"] == hashlib.sha256(
        canonical_json(document["index"])
    ).hexdigest()
    assert set(document["index"]["features"][0]) == {
        "id",
        "provider_feature_id",
        "kind",
        "bbox",
        "label",
        "render_batch_id",
        "footprint",
        "semantic_properties",
    }

    document["index"]["features"][0]["unknown"] = True
    document["payload_sha256"] = hashlib.sha256(canonical_json(document["index"])).hexdigest()
    with pytest.raises(ValueError, match="malformed"):
        _validate(canonical_json(document))
