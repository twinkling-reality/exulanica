"""Deterministic preparation of bounded official NYC Building Footprints data."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from exulanica.canonical import canonical_json
from exulanica.environment.admission import MAX_ENVIRONMENT_PAYLOAD_BYTES
from exulanica.environment.feature_index import MAX_ENVIRONMENT_FEATURES

DATASET_ID = "5zhs-2jue"
PROVIDER_KEY = "nyc-open-data"
DATASET_NAME = "BUILDING"
ENDPOINT = f"https://data.cityofnewyork.us/resource/{DATASET_ID}.geojson"
METADATA_URL = f"https://data.cityofnewyork.us/api/views/{DATASET_ID}"
TERMS_URL = "https://opendata.cityofnewyork.us/overview/#termsofuse"
FIELD_DOCUMENTATION_URL = (
    "https://github.com/CityOfNewYork/nyc-geo-metadata/blob/master/"
    "Metadata/Metadata_BuildingFootprints.md"
)
COORDINATE_SCALE = 10_000_000
QUERY_LIMIT = 1000
QUERY_FIELDS = (
    "the_geom",
    "name",
    "bin",
    "doitt_id",
    "base_bbl",
    "construction_year",
    "feature_code",
    "geom_source",
    "ground_elevation",
    "height_roof",
    "last_edited_date",
    "last_status_type",
)
QUERY_BOUNDS = (-739_930_000, 407_200_000, -739_840_000, 407_240_000)
QUERY_WHERE = "within_box(the_geom,40.724,-73.993,40.720,-73.984)"
QUERY_PARAMETERS = (
    ("$select", ",".join(QUERY_FIELDS)),
    ("$where", QUERY_WHERE),
    ("$order", "doitt_id"),
    ("$limit", str(QUERY_LIMIT)),
)
SOURCE_PROFILE = "exulanica.nyc-open-data-building-footprints/v1"
MANIFEST_PROFILE = "exulanica.nyc-open-data-preparation-manifest/v1"
PLAN_PROFILE = "exulanica.nyc-open-data-admission-index-plan/v1"
ADMISSION_NAMESPACE = uuid.UUID("63d1f09a-d76b-4e31-b3ae-f54e382b48aa")
ATTRIBUTION = "NYC Open Data, Office of Technology and Innovation (OTI), BUILDING dataset 5zhs-2jue"
MODIFICATION_NOTICE = (
    "Coordinates quantized to 1e-7 degree integers; rings canonically rotated and collections "
    "sorted; geometry is not clipped, simplified, inferred, or repaired."
)

_PROPERTY_FIELDS = frozenset(QUERY_FIELDS) - {"the_geom"}
_DECIMAL_FIELDS = frozenset({"ground_elevation", "height_roof"})
_INTEGER_FIELDS = frozenset({"construction_year", "feature_code"})


class InvalidNYCOpenData(ValueError):
    """The source cannot be canonicalized without guessing."""


@dataclass(frozen=True, slots=True)
class DownloadedNYCOpenData:
    data: bytes
    url: str
    response_headers: dict[str, str]


@dataclass(frozen=True, slots=True)
class PreparedArtifact:
    path: str
    data: bytes

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.data).hexdigest()

    @property
    def byte_size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class PreparedNYCOpenData:
    source_sha256: str
    source_byte_size: int
    feature_count: int
    shards: tuple[PreparedArtifact, ...]
    index_inputs: tuple[PreparedArtifact, ...]
    plan: PreparedArtifact
    manifest: PreparedArtifact


def query_url() -> str:
    """Return the one allowed, fully pinned public request URL."""
    return f"{ENDPOINT}?{urlencode(QUERY_PARAMETERS)}"


def download_bounded(*, timeout_seconds: int = 30) -> DownloadedNYCOpenData:
    """Fetch the bounded public response without credentials or retries."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    url = query_url()
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.geo+json",
            "User-Agent": "exulanica-nyc-open-data-preparation/1",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise InvalidNYCOpenData(f"NYC Open Data returned HTTP {response.status}")
        limit = MAX_ENVIRONMENT_PAYLOAD_BYTES + 1
        data = response.read(limit)
        if len(data) > MAX_ENVIRONMENT_PAYLOAD_BYTES:
            raise InvalidNYCOpenData("bounded NYC Open Data response exceeds 64 MiB")
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower()
            in {
                "content-type",
                "date",
                "etag",
                "last-modified",
                "x-soda2-data-out-of-date",
                "x-soda2-truth-last-modified",
                "x-socrata-requestid",
            }
        }
    return DownloadedNYCOpenData(data=data, url=url, response_headers=headers)


def _decimal(value: Any, *, path: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise InvalidNYCOpenData(f"{path} must be an exact decimal")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise InvalidNYCOpenData(f"{path} must be an exact decimal") from exc
    if not result.is_finite():
        raise InvalidNYCOpenData(f"{path} must be finite")
    return result


def coordinate_integer(value: Any, *, axis: str) -> int:
    """Convert an exact GeoJSON decimal to the frozen integer geographic frame."""
    number = _decimal(value, path=f"geometry.{axis}")
    bound = Decimal(180 if axis == "longitude" else 90)
    if number < -bound or number > bound:
        raise InvalidNYCOpenData(f"geometry.{axis} is outside its geographic range")
    return int((number * COORDINATE_SCALE).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _point(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise InvalidNYCOpenData("each coordinate must contain longitude and latitude only")
    return (
        coordinate_integer(value[0], axis="longitude"),
        coordinate_integer(value[1], axis="latitude"),
    )


def _ring(value: Any) -> tuple[tuple[int, int], ...]:
    if not isinstance(value, list) or len(value) < 4:
        raise InvalidNYCOpenData("a ring must contain at least four points")
    points: list[tuple[int, int]] = []
    for raw_point in value:
        point = _point(raw_point)
        if not points or point != points[-1]:
            points.append(point)
    if len(points) < 4 or points[0] != points[-1]:
        raise InvalidNYCOpenData("a ring must remain explicitly closed after quantization")
    open_ring = points[:-1]
    if len(set(open_ring)) < 3:
        raise InvalidNYCOpenData("a ring must contain three distinct quantized points")
    minimum = min(open_ring)
    rotations = [
        tuple(open_ring[index:] + open_ring[:index])
        for index, point in enumerate(open_ring)
        if point == minimum
    ]
    canonical = min(rotations)
    return (*canonical, canonical[0])


def _polygon(value: Any) -> tuple[tuple[tuple[int, int], ...], ...]:
    if not isinstance(value, list) or not value:
        raise InvalidNYCOpenData("a polygon must contain an exterior ring")
    exterior = _ring(value[0])
    interiors = tuple(sorted(_ring(ring) for ring in value[1:]))
    return (exterior, *interiors)


def canonical_geometry(value: Any) -> dict[str, Any]:
    """Validate and canonicalize Polygon or MultiPolygon into integer MultiPolygon."""
    if not isinstance(value, dict) or set(value) != {"type", "coordinates"}:
        raise InvalidNYCOpenData("geometry must contain only type and coordinates")
    geometry_type = value["type"]
    coordinates = value["coordinates"]
    if geometry_type == "Polygon":
        polygons = (_polygon(coordinates),)
    elif geometry_type == "MultiPolygon":
        if not isinstance(coordinates, list) or not coordinates:
            raise InvalidNYCOpenData("a multipolygon must contain at least one polygon")
        polygons = tuple(_polygon(polygon) for polygon in coordinates)
    else:
        raise InvalidNYCOpenData("building geometry must be Polygon or MultiPolygon")
    return {
        "type": "MultiPolygon",
        "coordinates": [
            [[[longitude, latitude] for longitude, latitude in ring] for ring in polygon]
            for polygon in sorted(polygons)
        ],
    }


def geometry_bbox(geometry: dict[str, Any]) -> tuple[int, int, int, int]:
    points = [point for polygon in geometry["coordinates"] for ring in polygon for point in ring]
    longitudes = [point[0] for point in points]
    latitudes = [point[1] for point in points]
    return min(longitudes), min(latitudes), max(longitudes), max(latitudes)


def bbox_intersects(left: tuple[int, int, int, int], right: tuple[int, int, int, int]) -> bool:
    """Use inclusive rectangle intersection, including boundary-only contact."""
    return (
        left[0] <= right[2] and right[0] <= left[2] and left[1] <= right[3] and right[1] <= left[3]
    )


def provider_feature_id(properties: dict[str, Any]) -> str:
    value = properties.get("doitt_id")
    if isinstance(value, bool) or not isinstance(value, str) or not value.isascii():
        raise InvalidNYCOpenData("DOITT_ID must be an ASCII base-10 integer string")
    if not value.isdigit() or value.startswith("0") or int(value) <= 0:
        raise InvalidNYCOpenData("DOITT_ID must be a positive canonical base-10 integer")
    return f"doitt_id:{value}"


def _bin(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 7 or not value.isascii() or not value.isdigit():
        return None
    if value[1:] == "000000" or value[0] not in "12345":
        return None
    return f"bin:{value}"


def _optional_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip() or not value:
        raise InvalidNYCOpenData(f"{field} must be null or non-empty trimmed text")
    return value


def _canonical_decimal_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise InvalidNYCOpenData(f"{field} must be null or decimal text")
    number = _decimal(value, path=field)
    if number == 0:
        return "0"
    rendered = format(number.normalize(), "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _canonical_integer_text(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise InvalidNYCOpenData(f"{field} must be null or unsigned integer text")
    return str(int(value))


def _canonical_properties(value: Any) -> tuple[str, dict[str, Any]]:
    if not isinstance(value, dict) or set(value) != _PROPERTY_FIELDS:
        raise InvalidNYCOpenData("feature properties disagree with the pinned field selection")
    identity = provider_feature_id(value)
    properties: dict[str, Any] = {
        "base_bbl": _optional_text(value["base_bbl"], field="base_bbl"),
        "bin": _bin(value["bin"]),
        "construction_year": _canonical_integer_text(
            value["construction_year"], field="construction_year"
        ),
        "feature_code": _canonical_integer_text(value["feature_code"], field="feature_code"),
        "geom_source": _optional_text(value["geom_source"], field="geom_source"),
        "ground_elevation_source_value": _canonical_decimal_text(
            value["ground_elevation"], field="ground_elevation"
        ),
        "height_roof_source_value": _canonical_decimal_text(
            value["height_roof"], field="height_roof"
        ),
        "last_edited_date": _optional_text(value["last_edited_date"], field="last_edited_date"),
        "last_status_type": _optional_text(value["last_status_type"], field="last_status_type"),
        "name": _optional_text(value["name"], field="name"),
    }
    return identity, properties


def canonical_features(data: bytes) -> tuple[dict[str, Any], ...]:
    """Parse, validate, select, and sort one exact bounded GeoJSON response."""
    try:
        document = json.loads(data, parse_float=Decimal, parse_int=Decimal)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InvalidNYCOpenData("source is not valid UTF-8 GeoJSON") from exc
    expected_crs = {
        "type": "name",
        "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
    }
    if (
        not isinstance(document, dict)
        or set(document) != {"type", "features", "crs"}
        or document["type"] != "FeatureCollection"
        or document["crs"] != expected_crs
        or not isinstance(document["features"], list)
        or len(document["features"]) > QUERY_LIMIT
    ):
        raise InvalidNYCOpenData("source is not the expected bounded CRS84 FeatureCollection")
    canonical: list[dict[str, Any]] = []
    identities: set[str] = set()
    for raw in document["features"]:
        if (
            not isinstance(raw, dict)
            or set(raw) != {"type", "geometry", "properties"}
            or raw["type"] != "Feature"
        ):
            raise InvalidNYCOpenData("each source item must be a GeoJSON Feature")
        identity, properties = _canonical_properties(raw["properties"])
        if identity in identities:
            raise InvalidNYCOpenData(f"duplicate DOITT_ID identity: {identity}")
        identities.add(identity)
        geometry = canonical_geometry(raw["geometry"])
        bbox = geometry_bbox(geometry)
        if not bbox_intersects(bbox, QUERY_BOUNDS):
            raise InvalidNYCOpenData(
                f"feature {identity} does not intersect the pinned query bounds"
            )
        canonical.append(
            {
                "provider_feature_id": identity,
                "bbox": list(bbox),
                "geometry": geometry,
                "properties": properties,
            }
        )
    canonical.sort(key=lambda feature: feature["provider_feature_id"])
    return tuple(canonical)


def _source_payload(features: list[dict[str, Any]], *, provider_revision: str) -> dict[str, Any]:
    return {
        "profile": SOURCE_PROFILE,
        "provider": {
            "key": PROVIDER_KEY,
            "dataset_id": DATASET_ID,
            "dataset_name": DATASET_NAME,
            "revision": provider_revision,
        },
        "query": {
            "endpoint": ENDPOINT,
            "parameters": dict(QUERY_PARAMETERS),
            "bounds": list(QUERY_BOUNDS),
        },
        "geographic_frame": {
            "name": "nyc-open-data-crs84",
            "crs": "OGC:CRS84",
            "axis_order": ["longitude", "latitude"],
            "horizontal_unit": "degree",
            "vertical_unit": "not_applicable",
            "orientation": "east-north",
            "altitude_reference": "not_applicable_2d",
        },
        "coordinate_scale": COORDINATE_SCALE,
        "attribution": ATTRIBUTION,
        "modification_notice": MODIFICATION_NOTICE,
        "features": features,
    }


def _encoded_source(features: list[dict[str, Any]], *, provider_revision: str) -> bytes:
    return canonical_json(_source_payload(features, provider_revision=provider_revision)) + b"\n"


def _shard_features(
    features: tuple[dict[str, Any], ...],
    *,
    provider_revision: str,
    max_features: int,
    max_bytes: int,
) -> tuple[bytes, ...]:
    if not 1 <= max_features <= MAX_ENVIRONMENT_FEATURES:
        raise ValueError(f"max_features must be between 1 and {MAX_ENVIRONMENT_FEATURES}")
    if max_bytes <= 0 or max_bytes > MAX_ENVIRONMENT_PAYLOAD_BYTES:
        raise ValueError("max_bytes must be positive and at most 64 MiB")
    shards: list[bytes] = []
    current: list[dict[str, Any]] = []
    for feature in features:
        candidate = [*current, feature]
        encoded = _encoded_source(candidate, provider_revision=provider_revision)
        if len(candidate) <= max_features and len(encoded) <= max_bytes:
            current = candidate
            continue
        if not current:
            raise InvalidNYCOpenData("one canonical feature exceeds the shard byte limit")
        shards.append(_encoded_source(current, provider_revision=provider_revision))
        current = [feature]
        encoded = _encoded_source(current, provider_revision=provider_revision)
        if len(encoded) > max_bytes:
            raise InvalidNYCOpenData("one canonical feature exceeds the shard byte limit")
    if current or not features:
        shards.append(_encoded_source(current, provider_revision=provider_revision))
    return tuple(shards)


def _artifact_record(artifact: PreparedArtifact) -> dict[str, Any]:
    return {
        "path": artifact.path,
        "byte_size": artifact.byte_size,
        "sha256": artifact.sha256,
    }


def prepare(
    data: bytes,
    *,
    provider_revision: str,
    retrieval_timestamp: str,
    response_headers: dict[str, str],
    max_features: int = MAX_ENVIRONMENT_FEATURES,
    max_bytes: int = MAX_ENVIRONMENT_PAYLOAD_BYTES,
) -> PreparedNYCOpenData:
    """Create canonical shards, index inputs, and a no-write admission plan."""
    if not provider_revision or provider_revision != provider_revision.strip():
        raise ValueError("provider_revision must be non-empty trimmed text")
    if not retrieval_timestamp or retrieval_timestamp != retrieval_timestamp.strip():
        raise ValueError("retrieval_timestamp must be non-empty trimmed text")
    features = canonical_features(data)
    shard_bytes = _shard_features(
        features,
        provider_revision=provider_revision,
        max_features=max_features,
        max_bytes=max_bytes,
    )
    shards: list[PreparedArtifact] = []
    indexes: list[PreparedArtifact] = []
    plan_entries: list[dict[str, Any]] = []
    for ordinal, encoded in enumerate(shard_bytes):
        digest = hashlib.sha256(encoded).hexdigest()
        stem = f"building-footprints-{ordinal:04d}-{digest}"
        shard = PreparedArtifact(path=f"sources/{stem}.json", data=encoded)
        shards.append(shard)
        shard_document = json.loads(encoded)
        index_payload = {
            "profile": "exulanica.environment-feature-index-input/v1",
            "source_sha256": digest,
            "features": [
                {
                    "provider_feature_id": feature["provider_feature_id"],
                    "kind": "building",
                    "bbox": feature["bbox"],
                    "label": feature["properties"]["name"],
                    "render_batch_id": None,
                }
                for feature in shard_document["features"]
            ],
        }
        index_data = canonical_json(index_payload) + b"\n"
        if len(index_data) > MAX_ENVIRONMENT_PAYLOAD_BYTES:
            raise InvalidNYCOpenData("feature-index input exceeds the 64 MiB payload limit")
        index = PreparedArtifact(path=f"indexes/{stem}.feature-index.json", data=index_data)
        indexes.append(index)
        admission_name = canonical_json(
            {
                "provider_revision": provider_revision,
                "query_url": query_url(),
                "ordinal": ordinal,
                "source_sha256": digest,
            }
        ).decode("utf-8")
        admission_id = str(uuid.uuid5(ADMISSION_NAMESPACE, admission_name))
        plan_entries.append(
            {
                "ordinal": ordinal,
                "admission_id": admission_id,
                "source": _artifact_record(shard),
                "feature_index_input": _artifact_record(index),
                "feature_count": len(index_payload["features"]),
                "limits": {
                    "source_under_64_mib": shard.byte_size <= MAX_ENVIRONMENT_PAYLOAD_BYTES,
                    "index_under_64_mib": index.byte_size <= MAX_ENVIRONMENT_PAYLOAD_BYTES,
                    "features_at_most_512": len(index_payload["features"])
                    <= MAX_ENVIRONMENT_FEATURES,
                },
                "admission": {
                    "provider_key": PROVIDER_KEY,
                    "provider_original_id": f"{DATASET_ID}:hero-corridor:{ordinal:04d}",
                    "provider_revision": provider_revision,
                    "expected_sha256": digest,
                    "expected_byte_size": shard.byte_size,
                    "source_path": query_url(),
                    "member_path": shard.path,
                    "media_type": "application/vnd.exulanica.nyc-building-footprints+json",
                    "geographic_frame": {
                        "name": "nyc-open-data-crs84",
                        "crs": "OGC:CRS84",
                        "axis_order": ["longitude", "latitude"],
                        "horizontal_unit": "degree",
                        "vertical_unit": "not_applicable",
                        "orientation": "east-north",
                        "altitude_reference": "not_applicable_2d",
                    },
                    "geographic_bounds": {
                        "kind": "bbox",
                        "frame_name": "nyc-open-data-crs84",
                        "coordinate_scale": COORDINATE_SCALE,
                        "coordinates": list(QUERY_BOUNDS),
                    },
                    "attribution": ATTRIBUTION,
                    "modification_notice": MODIFICATION_NOTICE,
                    "place_id": {"status": "integration_input_required"},
                    "operation_rights": {
                        "status": "legal_review_required",
                        "reason": (
                            "primary portal terms establish public access and disclaimers but "
                            "do not enumerate Exulanica operation rights"
                        ),
                    },
                },
                "publication": {
                    "status": "blocked",
                    "reason": "an exact separately admitted render_asset_id is required",
                    "publications_for_admission": 1,
                },
            }
        )
    plan_data = (
        canonical_json(
            {
                "profile": PLAN_PROFILE,
                "dataset_id": DATASET_ID,
                "strategy": "one_source_admission_and_one_current_publication_per_shard",
                "entries": plan_entries,
            }
        )
        + b"\n"
    )
    plan = PreparedArtifact(path="admission-index-plan.json", data=plan_data)
    selected_headers = {
        key.lower(): value
        for key, value in response_headers.items()
        if key.lower()
        in {
            "content-type",
            "date",
            "etag",
            "last-modified",
            "x-soda2-data-out-of-date",
            "x-soda2-truth-last-modified",
            "x-socrata-requestid",
        }
    }
    manifest_record = {
        "profile": MANIFEST_PROFILE,
        "dataset": {
            "id": DATASET_ID,
            "name": DATASET_NAME,
            "provider_revision": provider_revision,
            "metadata_url": METADATA_URL,
            "field_documentation_url": FIELD_DOCUMENTATION_URL,
            "terms_url": TERMS_URL,
        },
        "request": {
            "url": query_url(),
            "retrieved_at": retrieval_timestamp,
            "response_headers": selected_headers,
            "source_sha256": hashlib.sha256(data).hexdigest(),
            "source_byte_size": len(data),
        },
        "canonicalization": {
            "coordinate_scale": COORDINATE_SCALE,
            "rounding": "decimal_round_half_even",
            "boundary": "inclusive_bbox_intersection",
            "identity": "doitt_id_positive_canonical_integer_no_fallback",
        },
        "feature_count": len(features),
        "artifacts": [
            *(_artifact_record(artifact) for artifact in shards),
            *(_artifact_record(artifact) for artifact in indexes),
            _artifact_record(plan),
        ],
    }
    manifest = PreparedArtifact(path="manifest.json", data=canonical_json(manifest_record) + b"\n")
    return PreparedNYCOpenData(
        source_sha256=hashlib.sha256(data).hexdigest(),
        source_byte_size=len(data),
        feature_count=len(features),
        shards=tuple(shards),
        index_inputs=tuple(indexes),
        plan=plan,
        manifest=manifest,
    )


def write_prepared(value: PreparedNYCOpenData, destination: Path) -> None:
    """Write prepared artifacts only after checking every declared digest and size."""
    artifacts = (*value.shards, *value.index_inputs, value.plan, value.manifest)
    for artifact in artifacts:
        if artifact.byte_size > MAX_ENVIRONMENT_PAYLOAD_BYTES:
            raise InvalidNYCOpenData(f"{artifact.path} exceeds the 64 MiB payload limit")
        path = destination / artifact.path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(artifact.data)
        written = path.read_bytes()
        if (
            len(written) != artifact.byte_size
            or hashlib.sha256(written).hexdigest() != artifact.sha256
        ):
            raise InvalidNYCOpenData(f"written artifact verification failed: {artifact.path}")
