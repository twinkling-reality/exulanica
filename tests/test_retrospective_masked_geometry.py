"""Retrospective bundles must contain a real count and disclose their snapshot limits."""

from __future__ import annotations

import json
import struct
from dataclasses import replace

import pytest
from exulanica.consent.regions import Silhouette
from exulanica.consent.states import resolve_presentation
from exulanica.evaluation import masked_geometry as evaluator
from exulanica.evaluation.reference_inputs import envelope
from exulanica.evidence.region import Rect
from exulanica.ingest.masked_geometry import GaussianView
from exulanica.ingest.person_state import CaptureRegionState


def _ply(opacity=1.0):
    return (
        b"ply\nformat binary_little_endian 1.0\nelement vertex 1\n"
        b"property float x\nproperty float y\nproperty float z\nproperty float opacity\n"
        b"end_header\n" + struct.pack("<ffff", 0, 0, 1, opacity)
    )


def _view():
    return GaussianView(
        "camera.jpg", (1, 0, 0, 0), (0, 0, 0), (100, 100), (100, 100), (50, 50), (), ()
    )


def test_retrospective_bundle_reports_geometry_inside_recorded_regions():
    region = Silhouette.from_rect(Rect.from_normalised(0.25, 0.25, 0.5, 0.5))
    result = evaluator.evaluate_ply(
        _ply(), [replace(_view(), masked=(region,), confirmed=(region,))]
    )
    assert result["masked_geometry"]["gaussians_over_masked_region"] == 1
    assert result["masked_geometry"]["gaussians_over_confirmed_region"] == 1
    assert result["recorded_masked_regions"] == 1
    assert result["privacy_verdict"] == "not established by this retrospective count"


def test_empty_regions_still_validate_actual_gaussian_bytes():
    with pytest.raises(ValueError, match="nonfinite opacity"):
        evaluator.evaluate_ply(_ply(float("nan")), [_view()])
    measured = evaluator.evaluate_ply(_ply(), [_view()])
    assert measured["masked_geometry"]["gaussians"] == 1
    assert measured["recorded_masked_regions"] == 0
    assert "historical training masks unavailable" in measured["region_basis"]
    assert len(measured["masked_geometry"]["views"]) == 1


def test_missing_or_duplicate_camera_membership_is_refused():
    for views in ([], [_view(), _view()]):
        with pytest.raises(ValueError, match="unique recovered camera"):
            evaluator.evaluate_ply(_ply(), views)


def test_unknown_subject_keeps_its_region_masked_in_camera_adapter():
    outline = Silhouette.from_rect(Rect.from_normalised(0.25, 0.25, 0.5, 0.5))
    state = CaptureRegionState(
        {b"key": outline}, {b"key": resolve_presentation(())}, {b"key": None}
    )
    camera = {
        "image_name": "camera.jpg",
        "calibration": {"model": "SIMPLE_RADIAL", "parameters": [100, 50, 50, 0.01]},
        "image_size": [100, 100],
        "quaternion_wxyz": [1, 0, 0, 0],
        "translation_xyz": [0, 0, 0],
    }
    view = evaluator.camera_view(camera, state)
    assert view.masked == (outline,)
    assert view.confirmed == ()
    result = evaluator.evaluate_ply(_ply(), [view])
    assert result["masked_geometry"]["margin_ppm"] == 20_000
    assert result["masked_geometry"]["gaussians_over_masked_region"] == 1


def test_predecessor_refuses_changed_record_and_extra_envelope_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluator, "ROOT", tmp_path)
    path = tmp_path / "previous.json"
    document = envelope({"measured": 1})
    path.write_text(json.dumps(document))
    assert evaluator.predecessor(path)["record_sha256"] == document["record_sha256"]
    document["record"]["measured"] = 2
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="envelope"):
        evaluator.predecessor(path)
    document = envelope({"measured": 1}) | {"extra": True}
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="envelope"):
        evaluator.predecessor(path)


def test_retained_blob_cannot_be_substituted_under_a_bound_digest(tmp_path):
    import hashlib

    digest = hashlib.sha256(b"original").hexdigest()
    path = tmp_path / "sha-256" / digest[:2] / digest[2:4] / digest
    path.parent.mkdir(parents=True)
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="content digest"):
        evaluator._blob(tmp_path, digest)
