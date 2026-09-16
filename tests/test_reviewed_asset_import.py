from __future__ import annotations

import hashlib
import json
import struct

import pytest
from exulanica.world.asset_import import (
    ReviewedAssetImport,
    validate_asset_import,
    validate_import_container,
)
from exulanica.world.assets import reviewed_assets
from pydantic import ValidationError


def imported_fixture():
    payload = reviewed_assets()[0].payload
    licence = b"Upstream fixture licence evidence, CC0-1.0."
    manifest = ReviewedAssetImport(
        profile="exulanica.reviewed-asset-import/v1",
        asset_key="test.imported-asset",
        title="Imported example",
        summary="A synthetic import test, not a character asset.",
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_size=len(payload),
        licence_id="CC0-1.0",
        licence_sha256=hashlib.sha256(licence).hexdigest(),
        source_url="https://example.org/fixture",
        source_revision="fixture-v1",
        producer="test-builder/v1",
    )
    return manifest, payload, licence


def glb(document):
    body = json.dumps(document).encode()
    body += b" " * (-len(body) % 4)
    return struct.pack("<IIIII", 0x46546C67, 2, len(body) + 20, len(body), 0x4E4F534A) + body


def test_receipt_preserves_upstream_provenance_and_exact_bytes():
    manifest, payload, licence = imported_fixture()
    receipt = validate_asset_import(manifest, payload, licence)
    assert json.loads(receipt)["licence_sha256"] == hashlib.sha256(licence).hexdigest()
    assert json.loads(receipt)["source_revision"] == "fixture-v1"
    assert receipt == validate_asset_import(manifest, payload, licence)
    with pytest.raises(ValueError, match="asset bytes"):
        validate_asset_import(manifest, payload[:-1], licence)
    with pytest.raises(ValueError, match="licence evidence"):
        validate_asset_import(manifest, payload, licence + b"changed")


@pytest.mark.parametrize(
    "document",
    [
        {"asset": {"version": "2.0"}, "images": [{"uri": "https://example.org/private.png"}]},
        {
            "asset": {"version": "2.0"},
            "buffers": [{"uri": "data:application/octet-stream;base64,AA=="}],
        },
        {"asset": {"version": "2.0"}, "extensionsRequired": ["unknown"]},
        {"asset": {"version": "2.0"}, "extensionsUsed": ["KHR_draco_mesh_compression"]},
        {"asset": {"version": "2.0"}, "buffers": [{"byteLength": 10}]},
        {"asset": "2.0"},
        {"asset": {"version": "2.0"}, "extensionsUsed": [None]},
    ],
)
def test_refuses_unavailable_or_unreviewed_dependencies(document):
    with pytest.raises(ValueError):
        validate_import_container(glb(document))


def test_refuses_unlicensed_or_unknown_manifest_fields():
    manifest, _, _ = imported_fixture()
    for fields in ({"licence_id": "unknown"}, {"extra": "ignored?"}, {"title": "  "}):
        with pytest.raises(ValidationError):
            ReviewedAssetImport.model_validate({**manifest.model_dump(), **fields})
