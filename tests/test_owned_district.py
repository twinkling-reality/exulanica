from __future__ import annotations

import hashlib
import json
from pathlib import Path

from exulanica.environment.owned_district import (
    BUILDING_DATASET,
    SIDEWALK_DATASET,
    DownloadedLayer,
    compile_district,
    write_bundle,
)

BUILDINGS = Path(__file__).parent / "fixtures" / "nyc-open-data-building-footprints.geojson"


def _sidewalk() -> bytes:
    return json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [-73.9902, 40.7419],
                                [-73.9898, 40.7419],
                                [-73.9898, 40.7421],
                                [-73.9902, 40.7421],
                                [-73.9902, 40.7419],
                            ]
                        ],
                    },
                    "properties": {
                        "source_id": "fixture-walk",
                        "sub_code": "0",
                        "feat_code": "3800",
                        "status": "Unchanged",
                    },
                }
            ],
            "crs": {
                "type": "name",
                "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
            },
        },
        separators=(",", ":"),
    ).encode()


def _layer(dataset: str, data: bytes) -> DownloadedLayer:
    return DownloadedLayer(dataset, data, f"https://example.invalid/{dataset}", "fixture-v1")


def test_compiler_is_deterministic_engine_neutral_and_lineage_bound(tmp_path):
    buildings = _layer(BUILDING_DATASET, BUILDINGS.read_bytes())
    sidewalks = _layer(SIDEWALK_DATASET, _sidewalk())

    first = compile_district(buildings, sidewalks)
    second = compile_district(buildings, sidewalks)
    document = json.loads(first.data)
    manifest = json.loads(first.manifest)

    assert first == second
    assert document["profile"] == "exulanica.owned-district/v1"
    assert document["frame"]["altitude_reference"] == "authored-flat-ground"
    assert document["road_completion"]["generated"] is True
    assert document["navigation"]["collision"] == "building-exterior-rings"
    assert document["buildings"][0]["id"].startswith("doitt_id:")
    assert len(document["materials"]) == 7
    assert all(record["operation_rights"]["modify"] for record in document["source_records"])
    assert manifest["artifact"]["sha256"] == hashlib.sha256(first.data).hexdigest()

    write_bundle(tmp_path, buildings, sidewalks, first)
    assert (tmp_path / "flatiron-owned-district.json").read_bytes() == first.data
    assert (tmp_path / "source" / "buildings.geojson").read_bytes() == buildings.data


def test_compiler_rejects_wrong_layer_identity():
    wrong = _layer("wrong", BUILDINGS.read_bytes())
    sidewalks = _layer(SIDEWALK_DATASET, _sidewalk())

    try:
        compile_district(wrong, sidewalks)
    except ValueError as error:
        assert "dataset identity" in str(error)
    else:
        raise AssertionError("wrong source identity must fail")
