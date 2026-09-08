"""Exact personal authority through the real receipt policy and mask stage."""

import copy
import datetime as dt
import json

import pytest
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest.personal_admission import execute, load_manifest
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.store.local import LocalContentAddressedStore

from conftest import photo_bytes
from test_personal_admission_command import document


def test_changed_region_requires_current_mask_before_geometry(repository, tmp_path):
    data = photo_bytes()
    doc = document(data)
    doc["workspace_id"] = str(repository.workspace_id)
    path = tmp_path / "manifest.json"
    pipeline = PhotoIngestPipeline(repository, LocalContentAddressedStore(tmp_path / "blobs"))

    def run(operation, **changes):
        doc.update(
            operation=operation,
            recorded_at=dt.datetime.now(dt.UTC).isoformat(),
            review="not-reviewed",
            edits=[],
        )
        doc.update(changes)
        path.write_text(json.dumps(doc))
        return execute(load_manifest(path), data, pipeline)

    admission = run("admit")
    doc["source"]["capture_id"] = admission["capture_id"]
    doc["authorization_id"] = admission["authorization_id"]
    detection = run("detect")
    doc["screening_id"] = detection["screening_id"]
    with pytest.raises(PrivacyAdmissionError, match=r"failed, blocked|stale"):
        run("geometry-check")
    reviewed = run("review", review="no-person")
    assert reviewed["eligibility_state"] == "eligible"
    doc["screening_id"] = reviewed["screening_id"]
    run("geometry-check")
    outline = {"kind": "polygon", "points": [[0, 0], [500000, 0], [500000, 500000], [0, 500000]]}
    edit = {"action": "add", "region_key": "a" * 64, "silhouette": outline}
    blocked = run("review", review="confirmed-regions", edits=[edit])
    assert blocked["eligibility_state"] == "blocked"
    # Exact replay uses the existing edit and screening, never a new review sequence.
    replay = execute(load_manifest(path), data, pipeline)
    assert replay["screening_id"] == blocked["screening_id"]
    assert (
        repository.connection.execute(
            "select count(*) n from person_region where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["n"]
        == 1
    )
    conflicting = copy.deepcopy(doc)
    conflicting["edits"][0]["silhouette"]["points"][1][0] = 700000
    path.write_text(json.dumps(conflicting))
    with pytest.raises(ValueError, match="dated edit conflicts"):
        execute(load_manifest(path), data, pipeline)
    doc["screening_id"] = detection["screening_id"]
    masked = run("mask")
    assert "masked_source" in masked["stages_run"]
    screened = run("rescreen", review="confirmed-regions")
    assert screened["eligibility_state"] == "eligible"
    doc["screening_id"] = screened["screening_id"]
    run("geometry-check")
    retry = run("retry")
    assert not retry["stages_run"]
    changed = copy.deepcopy(edit)
    changed["action"] = "confirm"
    changed["silhouette"]["points"][1][0] = 750000
    blocked = run("review", review="confirmed-regions", edits=[changed])
    assert blocked["eligibility_state"] == "blocked"
    with pytest.raises(PrivacyAdmissionError, match=r"failed, blocked|stale"):
        run("geometry-check")
    doc["screening_id"] = detection["screening_id"]
    assert "masked_source" in run("retry")["stages_run"]
    assert run("rescreen", review="confirmed-regions")["eligibility_state"] == "eligible"
