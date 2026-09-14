"""Actual placement/OPM validation and precise subset selection, without models or a database."""

from __future__ import annotations

import json

import numpy as np
import pytest
from exulanica.canonical import canonical_json
from exulanica.environment import scene_extraction as extraction
from exulanica.ingest.scene_segments import _opm_positions, _placed, _voxels

from test_reconstruction_placement import _maps, _receipt, _record


def _envelope(payload):
    return canonical_json(
        {
            "profile": "exulanica.scene-segments-envelope/v1",
            "payload_sha256": extraction.digest(canonical_json(payload)),
            "segments": payload,
        }
    )


@pytest.fixture
def inputs():
    record = _record()
    sources = _maps()
    points = _placed(record.placed[0].scene_from_opm, _opm_positions(sources["capture-a"].content))
    cells = sorted({tuple(c) for c in _voxels(points, 1000000) if c[0] < 1})
    identity = {
        "kind": "object",
        "label": "fixture surface",
        "subject_ref": None,
        "voxels": [list(map(int, c)) for c in cells],
    }
    segment = {
        **identity,
        "segment_id": extraction.digest(canonical_json(identity))[:32],
        "point_map_sources": [sources["capture-a"].content_sha256],
        "votes": {"min": 2},
        "regions": [],
    }
    payload = {
        "profile": "exulanica.scene-segments/v1",
        "scene_ref": "scene-1",
        "bindings": {
            "pose_receipt_sha256": extraction.digest(_receipt()),
            "placement_receipt_sha256": extraction.digest(record.to_bytes()),
            "gate_receipt_sha256": "c" * 64,
            "member_capture_refs": list(record.member_capture_refs),
            "point_map_inputs": [p.as_payload() for p in sources.values()],
            "object_mask_inputs": [],
            "person_regions": [],
            "gaussian_source": None,
        },
        "grid": {"frame": "scene", "voxel_size_microunits": 1000000},
        "segments": [segment],
    }
    return dict(
        workspace_ref="fixture-workspace",
        scene_ref="scene-1",
        segment_id=segment["segment_id"],
        segments_data=_envelope(payload),
        pose_data=_receipt(),
        placement_data=record.to_bytes(),
        gate_sha256="c" * 64,
        source_maps={p.content_sha256: p.content for p in sources.values()},
    )


def test_deterministic_subset_preserves_scene_frame_color_and_source_sample_address(inputs):
    candidate = extraction.build_surface_candidate(**inputs)
    assert candidate == extraction.build_surface_candidate(**inputs)
    manifest = json.loads(candidate.manifest)
    assert manifest["status"] == "candidate-not-admitted"
    assert not manifest["frame"]["metric_scale"]
    assert not manifest["admission"]["authorized_for_publication"]
    assert manifest["geometry"]["sha256"] == extraction.digest(candidate.points_ply)
    payload = candidate.points_ply.split(b"end_header\n", 1)[1]
    dtype = [
        ("x", "<f8"),
        ("y", "<f8"),
        ("z", "<f8"),
        ("r", "u1"),
        ("g", "u1"),
        ("b", "u1"),
        ("source", "<u4"),
        ("sample", "<u4"),
    ]
    rows = np.frombuffer(payload, dtype=dtype)
    assert 0 < len(rows) < 2 * 768
    maps = _maps()
    placed = {r.capture_ref: r for r in _record().placed}
    for i, source in enumerate(manifest["selection"]["selected_sources"]):
        subset = rows[rows["source"] == i]
        original = _opm_positions(maps[source["capture_ref"]].content)[subset["sample"]]
        expected = _placed(placed[source["capture_ref"]].scene_from_opm, original)
        assert np.array_equal(np.stack([subset[n] for n in ("x", "y", "z")], axis=1), expected)
        assert np.all(subset["x"] < 1)
        assert np.all(subset["r"] == 128)
    claimed = manifest.pop("document_sha256")
    assert extraction.digest(canonical_json(manifest)) == claimed


@pytest.mark.parametrize(
    "field", ["pose_data", "placement_data", "source_maps", "segment_id", "scene_ref"]
)
def test_refuses_changed_or_unresolved_inputs(inputs, field):
    bad = dict(inputs)
    if field == "source_maps":
        bad[field] = {}
    elif field in ("segment_id", "scene_ref"):
        bad[field] = "another"
    else:
        bad[field] = b"changed"
    with pytest.raises(ValueError):
        extraction.build_surface_candidate(**bad)


@pytest.mark.parametrize(
    "change",
    [
        "person",
        "bad-grid",
        "duplicate-voxel",
        "unknown-profile",
        "changed-id",
        "empty",
        "wrong-frame",
    ],
)
def test_refuses_malformed_or_unsupported_selection(inputs, change):
    p = json.loads(inputs["segments_data"])["segments"]
    s = p["segments"][0]
    if change == "person":
        s["kind"] = "person"
        s["label"] = None
        s["subject_ref"] = "someone"
    elif change == "wrong-frame":
        p["grid"]["frame"] = "another-frame"
    elif change == "bad-grid":
        p["grid"]["voxel_size_microunits"] = False
    elif change == "duplicate-voxel":
        s["voxels"].append(s["voxels"][0])
    elif change == "unknown-profile":
        p["profile"] = "unknown"
    elif change == "changed-id":
        s["segment_id"] = "wrong"
    else:
        s["voxels"] = [[100000, 100000, 100000]]
    if change not in ("changed-id", "unknown-profile"):
        s["segment_id"] = extraction.digest(
            canonical_json({k: s[k] for k in ("kind", "label", "subject_ref", "voxels")})
        )[:32]
        inputs["segment_id"] = s["segment_id"]
    inputs["segments_data"] = _envelope(p)
    with pytest.raises(ValueError):
        extraction.build_surface_candidate(**inputs)


def test_sampling_budget_is_explicit_and_rekeys_candidate(inputs):
    full = extraction.build_surface_candidate(**inputs)
    limited = extraction.build_surface_candidate(
        **inputs, policy=extraction.ExtractionPolicy(1, 100)
    )
    m = json.loads(limited.manifest)
    assert m["geometry"]["points"] <= 100
    assert len(m["selection"]["selected_sources"]) == 1
    assert limited != full


@pytest.mark.parametrize("args", [(0, 10), (9, 10), (1, 25001), (True, 10)])
def test_invalid_budgets_fail(args):
    with pytest.raises(ValueError):
        extraction.ExtractionPolicy(*args)


def test_map_bytes_cannot_change_behind_same_source_address(inputs):
    key = next(iter(inputs["source_maps"]))
    inputs["source_maps"][key] = b"not the pinned point map"
    with pytest.raises(ValueError, match="digest"):
        extraction.build_surface_candidate(**inputs)


@pytest.mark.parametrize(
    "case", ["withdrawn-initial", "withdrawn-final", "mask-changed", "segment-withheld", "allowed"]
)
def test_current_source_boundary_rechecks_before_return(monkeypatch, case):
    import uuid
    from contextlib import contextmanager
    from types import SimpleNamespace

    scene = uuid.UUID("11111111-1111-4111-8111-111111111111")
    workspace = uuid.UUID("22222222-2222-4222-8222-222222222222")
    capture = "33333333-3333-4333-8333-333333333333"
    payload = {
        "grid": {"frame": "scene", "voxel_size_microunits": 1},
        "segments": [
            {
                "segment_id": "picked",
                "kind": "object",
                "voxels": [[0, 0, 0]],
                "point_map_sources": [extraction.digest(b"map")],
            }
        ],
        "bindings": {
            "point_map_inputs": [
                {
                    "capture_ref": capture,
                    "artifact_ref": "map-ref",
                    "content_sha256": extraction.digest(b"map"),
                }
            ],
            "member_capture_refs": [capture],
            "object_mask_inputs": [],
        },
    }
    data = canonical_json({"segments": payload})
    blobs = {extraction.digest(x): x for x in [data, b"map", b"pose", b"placement"]}
    store = SimpleNamespace(size=lambda b: len(blobs[b.hex]), get=lambda b: blobs[b.hex])
    read = SimpleNamespace(
        state="available",
        segments=[] if case == "segment-withheld" else payload["segments"],
        content_sha256=extraction.digest(data),
        pose_receipt_sha256=extraction.digest(b"pose"),
        placement_receipt_sha256=extraction.digest(b"placement"),
        gate_receipt_sha256="c" * 64,
    )

    class Connection:
        @contextmanager
        def transaction(self):
            yield

        def execute(self, query, args=None):
            rows = []
            if "select distinct" in query:
                assert len(args) == 3
                assert args[-1] == extraction.scene_reader.OBJECT_MASK_KIND
            if case == "mask-changed" and "select distinct" in query:
                rows = [{"capture_id": capture, "artifact_id": scene, "content_sha256": b"x" * 32}]
            return SimpleNamespace(fetchall=lambda: rows)

    monkeypatch.setattr(extraction.scene_reader, "scene_segments_read", lambda *args: read)
    monkeypatch.setattr(
        extraction.scene_reader, "scene_segments_artifacts_live", lambda *args: True
    )
    monkeypatch.setattr(extraction, "scene_inputs", lambda *args: "buffered")
    monkeypatch.setattr(extraction, "evaluation_time", lambda *args: "initial")
    monkeypatch.setattr(
        extraction,
        "scene_allowed",
        lambda *args: (
            not (
                (case == "withdrawn-initial" and args[-1] == "initial")
                or (case == "withdrawn-final" and args[-1] == "final")
            )
        ),
    )

    @contextmanager
    def final(*args):
        yield "final"

    monkeypatch.setattr(extraction, "final_check", final)
    marker = extraction.SurfaceCandidate(b"manifest", b"points")
    monkeypatch.setattr(extraction, "build_surface_candidate", lambda **kwargs: marker)
    if case == "allowed":
        assert (
            extraction.prepare_current_surface(
                Connection(), store, workspace=workspace, scene=scene, segment_id="picked"
            )
            == marker
        )
    else:
        with pytest.raises(ValueError, match=r"unavailable|changed"):
            extraction.prepare_current_surface(
                Connection(), store, workspace=workspace, scene=scene, segment_id="picked"
            )
