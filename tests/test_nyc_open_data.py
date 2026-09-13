from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pytest
from exulanica.environment.admission import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.environment.nyc_open_data import (
    COORDINATE_SCALE,
    DATASET_ID,
    QUERY_BOUNDS,
    QUERY_LIMIT,
    InvalidNYCOpenData,
    bbox_intersects,
    canonical_features,
    canonical_geometry,
    coordinate_integer,
    prepare,
    provider_feature_id,
    query_url,
    write_prepared,
)

FIXTURE = Path(__file__).parent / "fixtures" / "nyc-open-data-building-footprints.geojson"
REVISION = "2026-09-07T15:51:51Z"
RETRIEVED = "2026-09-13T01:16:36Z"


def _properties(identity: str, **updates: object) -> dict[str, object]:
    properties: dict[str, object] = {
        "name": None,
        "bin": "1000000",
        "doitt_id": identity,
        "base_bbl": "1000010001",
        "construction_year": "1900",
        "feature_code": "2100",
        "geom_source": "Photogrammetric",
        "ground_elevation": "12.00",
        "height_roof": "0",
        "last_edited_date": "2026-09-01T00:00:00.000Z",
        "last_status_type": "Constructed",
    }
    properties.update(updates)
    return properties


def _feature(identity: str, *, west: float = -73.99) -> dict[str, object]:
    return {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [west, 40.721],
                    [west + 0.0001, 40.721],
                    [west + 0.0001, 40.7211],
                    [west, 40.7211],
                    [west, 40.721],
                ]
            ],
        },
        "properties": _properties(identity),
    }


def _collection(*features: dict[str, object]) -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": list(features),
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _prepare(data: bytes, **kwargs: object):
    return prepare(
        data,
        provider_revision=REVISION,
        retrieval_timestamp=RETRIEVED,
        response_headers={"ETag": "fixture-etag", "ignored": "not retained"},
        **kwargs,
    )


def test_official_fixture_has_stable_identity_crs_and_integer_coordinates():
    data = FIXTURE.read_bytes()
    features = canonical_features(data)

    assert [feature["provider_feature_id"] for feature in features] == [
        "doitt_id:2327",
        "doitt_id:3385",
    ]
    assert features[0]["properties"]["bin"] == "bin:1006070"
    assert features[0]["properties"]["height_roof_source_value"] == "54.04"
    assert features[0]["geometry"]["coordinates"][0][0][0] == [
        -739_904_139,
        407_238_475,
    ]
    assert COORDINATE_SCALE == 10_000_000


def test_exact_query_is_public_bounded_and_pinned():
    url = query_url()
    assert url.startswith(f"https://data.cityofnewyork.us/resource/{DATASET_ID}.geojson?")
    assert "%24limit=1000" in url
    assert "%24order=doitt_id" in url
    assert "within_box%28the_geom%2C40.724%2C-73.993%2C40.720%2C-73.984%29" in url
    assert QUERY_LIMIT == 1000


def test_provider_identity_has_no_bin_or_position_fallback():
    assert provider_feature_id(_properties("42")) == "doitt_id:42"
    for invalid in (None, 42, "", "0", "01", "-1", " 42"):
        with pytest.raises(InvalidNYCOpenData, match="DOITT_ID"):
            provider_feature_id(_properties("42", doitt_id=invalid))

    first = _feature("42")
    second = _feature("42", west=-73.989)
    with pytest.raises(InvalidNYCOpenData, match="duplicate DOITT_ID"):
        canonical_features(_collection(first, second))


def test_dummy_or_malformed_bin_is_metadata_null_and_never_identity():
    million = canonical_features(_collection(_feature("1")))[0]
    malformed = _feature("2")
    malformed["properties"]["bin"] = "not-a-bin"  # type: ignore[index]
    second = canonical_features(_collection(malformed))[0]
    assert million["properties"]["bin"] is None
    assert second["properties"]["bin"] is None
    assert second["provider_feature_id"] == "doitt_id:2"


def test_decimal_conversion_uses_explicit_half_even_and_rejects_bad_coordinates():
    assert coordinate_integer("-73.99000005", axis="longitude") == -739_900_000
    assert coordinate_integer("-73.99000015", axis="longitude") == -739_900_002
    assert coordinate_integer("40.72000005", axis="latitude") == 407_200_000
    with pytest.raises(InvalidNYCOpenData, match="range"):
        coordinate_integer("181", axis="longitude")
    with pytest.raises(InvalidNYCOpenData, match="finite"):
        coordinate_integer("NaN", axis="latitude")


def test_boundary_intersection_is_inclusive_and_outside_records_fail_closed():
    touching = (QUERY_BOUNDS[0] - 10, QUERY_BOUNDS[1], QUERY_BOUNDS[0], QUERY_BOUNDS[1] + 10)
    assert bbox_intersects(touching, QUERY_BOUNDS)

    outside = _feature("3", west=-74.1)
    with pytest.raises(InvalidNYCOpenData, match="does not intersect"):
        canonical_features(_collection(outside))


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        (None, "geometry"),
        ({"type": "Point", "coordinates": [-73.99, 40.72]}, "Polygon"),
        ({"type": "Polygon", "coordinates": []}, "exterior"),
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-73.99, 40.721],
                        [-73.989, 40.721],
                        [-73.989, 40.722],
                        [-73.99, 40.722],
                    ]
                ],
            },
            "closed",
        ),
        (
            {
                "type": "Polygon",
                "coordinates": [
                    [
                        [-73.99, 40.721, 1],
                        [-73.989, 40.721, 1],
                        [-73.989, 40.722, 1],
                        [-73.99, 40.721, 1],
                    ]
                ],
            },
            "longitude and latitude",
        ),
    ],
)
def test_malformed_or_ambiguous_geometry_is_rejected(geometry, message):
    if geometry is not None:
        geometry = json.loads(json.dumps(geometry), parse_float=Decimal)
    with pytest.raises(InvalidNYCOpenData, match=message):
        canonical_geometry(geometry)


def test_ring_rotation_polygon_order_and_feature_order_are_deterministic():
    first = _feature("20")
    second = _feature("3", west=-73.989)
    reversed_input = _collection(first, second)
    ordered_input = _collection(second, first)
    assert canonical_features(reversed_input) == canonical_features(ordered_input)

    ring = first["geometry"]["coordinates"][0]  # type: ignore[index]
    rotated = [*ring[2:-1], *ring[:2], ring[2]]
    first["geometry"]["coordinates"][0] = rotated  # type: ignore[index]
    assert (
        canonical_features(_collection(first))[0]["geometry"]
        == canonical_features(_collection(_feature("20")))[0]["geometry"]
    )


def test_sharding_obeys_512_features_and_uses_separate_admissions():
    data = _collection(*(_feature(str(index + 1)) for index in range(513)))
    prepared = _prepare(data)
    plan = json.loads(prepared.plan.data)

    assert prepared.feature_count == 513
    assert [len(json.loads(shard.data)["features"]) for shard in prepared.shards] == [512, 1]
    assert len({entry["admission_id"] for entry in plan["entries"]}) == 2
    assert all(entry["publication"]["publications_for_admission"] == 1 for entry in plan["entries"])
    assert all(entry["limits"]["features_at_most_512"] for entry in plan["entries"])


def test_byte_sharding_and_hard_64_mib_cap_fail_before_oversize():
    data = _collection(_feature("1"), _feature("2", west=-73.989))
    one_feature_size = len(_prepare(_collection(_feature("1"))).shards[0].data)
    prepared = _prepare(data, max_bytes=one_feature_size)

    assert len(prepared.shards) == 2
    assert all(shard.byte_size <= one_feature_size for shard in prepared.shards)
    assert all(shard.byte_size <= MAX_ENVIRONMENT_PAYLOAD_BYTES for shard in prepared.shards)
    with pytest.raises(ValueError, match="64 MiB"):
        _prepare(data, max_bytes=MAX_ENVIRONMENT_PAYLOAD_BYTES + 1)
    with pytest.raises(InvalidNYCOpenData, match="one canonical feature"):
        _prepare(_collection(_feature("1")), max_bytes=1)


def test_manifest_plan_and_writes_are_reproducible_and_digest_bound(tmp_path):
    data = FIXTURE.read_bytes()
    first = _prepare(data)
    second = _prepare(data)

    assert first == second
    assert first.manifest.sha256 == hashlib.sha256(first.manifest.data).hexdigest()
    manifest = json.loads(first.manifest.data)
    assert manifest["request"]["source_sha256"] == hashlib.sha256(data).hexdigest()
    assert manifest["request"]["response_headers"] == {"etag": "fixture-etag"}
    assert manifest["canonicalization"]["boundary"] == "inclusive_bbox_intersection"
    plan = json.loads(first.plan.data)
    assert plan["strategy"] == "one_source_admission_and_one_current_publication_per_shard"
    assert plan["entries"][0]["admission"]["operation_rights"]["status"] == (
        "legal_review_required"
    )
    assert plan["entries"][0]["publication"]["status"] == "blocked"

    write_prepared(first, tmp_path)
    for artifact in (*first.shards, *first.index_inputs, first.plan, first.manifest):
        assert (tmp_path / artifact.path).read_bytes() == artifact.data


def test_unexpected_properties_and_noncanonical_values_are_rejected():
    feature = _feature("1")
    feature["properties"]["unexpected"] = "value"  # type: ignore[index]
    with pytest.raises(InvalidNYCOpenData, match="field selection"):
        canonical_features(_collection(feature))

    feature = _feature("1")
    feature["properties"]["height_roof"] = 12.5  # type: ignore[index]
    with pytest.raises(InvalidNYCOpenData, match="decimal text"):
        canonical_features(_collection(feature))
