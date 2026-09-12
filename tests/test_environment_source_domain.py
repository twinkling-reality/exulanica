from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest
from exulanica.environment import (
    GeographicBounds,
    GeographicFrame,
    OperationRights,
    SourceAdmission,
    source_receipt,
)
from pydantic import ValidationError


def _rights(**changes: bool) -> dict[str, bool]:
    value = {
        "display": True,
        "extract": True,
        "index": True,
        "persist": True,
        "modify": True,
        "compose": True,
        "export": False,
        "model_processing": False,
    }
    value.update(changes)
    return value


def _source(**changes):
    data = {
        "admission_id": uuid.UUID("76c2f035-bb06-46ce-9720-95be786a7198"),
        "place_id": uuid.UUID("f22b081e-9bf6-44f0-a881-d542932668bc"),
        "provider_key": "plateau",
        "provider_original_id": "shibuya-2023-citygml-v3",
        "provider_revision": "2023",
        "expected_sha256": "7deee52ded16c15cbab062586f298ff132ad1b4f3ea3f567e4facf3875800fe6",
        "expected_byte_size": 649954662,
        "source_path": "https://example.invalid/official-archive.zip",
        "member_path": "udx/bldg/53393567.gml",
        "media_type": "application/zip",
        "geographic_frame": GeographicFrame(
            name="plateau-epsg-6697",
            crs="EPSG:6697",
            axis_order=("east", "north", "height"),
            horizontal_unit="metre",
            vertical_unit="metre",
            orientation="right-handed",
            altitude_reference="JGD2011 vertical datum",
        ),
        "geographic_bounds": GeographicBounds(
            kind="bbox",
            frame_name="plateau-epsg-6697",
            coordinate_scale=1000,
            coordinates=(0, 0, 0, 1, 1, 1),
        ),
        "operation_rights": OperationRights.model_validate(_rights()),
        "attribution": "Project PLATEAU / source attribution required",
        "modification_notice": "Modified outputs must be identified.",
        "local_path": Path("/already/local/archive.zip"),
    }
    data.update(changes)
    return SourceAdmission.model_validate(data)


def test_operation_rights_are_closed_and_export_is_independent():
    assert _source().operation_rights.export is False
    with pytest.raises(ValidationError):
        OperationRights.model_validate({**_rights(), "redistribute": True})
    malformed = _rights()
    malformed.pop("extract")
    with pytest.raises(ValidationError):
        OperationRights.model_validate(malformed)
    with pytest.raises(ValidationError):
        OperationRights.model_validate({**_rights(), "export": "yes"})


def test_source_receipt_is_canonical_digest_bound_and_excludes_local_path():
    first = source_receipt(_source())
    second = source_receipt(_source())
    assert first == second
    record, encoded, digest = first
    assert record["operation_rights"]["export"] is False
    assert "local_path" not in record
    assert hashlib.sha256(encoded).digest() == digest


def test_frame_mismatch_and_digest_malformed_fail_validation():
    with pytest.raises(ValidationError):
        _source(expected_sha256="ABC")
    with pytest.raises(ValidationError):
        _source(
            geographic_bounds=GeographicBounds(
                kind="bbox",
                frame_name="another-frame",
                coordinate_scale=1,
                coordinates=(0, 0, 1, 1),
            )
        )
