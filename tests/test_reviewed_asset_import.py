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


def imported_fixture(payload=None):
    payload = reviewed_assets()[0].payload if payload is None else payload
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


def test_the_container_boundary_is_reached_through_validate_asset_import():
    """The seven cases above test the guard. This one tests the CALL, which nothing else did.

    Measured 2026-09-19: deleting `validate_import_container(payload)` from asset_import.py
    left every test in this file passing, 9 asked and none objecting, and a GLB carrying a URI
    reference to a resource this host does not hold was handed back a valid receipt. The reason
    no test noticed is that every one that drives this path uses an admissible GLB, and the two
    malformed payloads disagree with their manifest, so the size and digest checks refuse them
    before the container is ever looked at.

    So the input has to be built the other way round: take a payload that is NOT an admissible
    container and give it a manifest that describes it exactly. The two assertions below are the
    test rather than preamble to it, because they are what says the earlier guards cannot be the
    ones answering."""
    remote = glb({"asset": {"version": "2.0"}, "images": [{"uri": "https://example.org/held.png"}]})
    manifest, payload, licence = imported_fixture(remote)
    assert len(payload) == manifest.byte_size
    assert hashlib.sha256(payload).hexdigest() == manifest.content_sha256
    with pytest.raises(ValueError, match="must be embedded, not URI references"):
        validate_asset_import(manifest, payload, licence)


def test_refuses_unlicensed_or_unknown_manifest_fields():
    manifest, _, _ = imported_fixture()
    for fields in ({"licence_id": "unknown"}, {"extra": "ignored?"}, {"title": "  "}):
        with pytest.raises(ValidationError):
            ReviewedAssetImport.model_validate({**manifest.model_dump(), **fields})
