"""Admitted generated photographs remain reviewable without a composed world or scene."""

from __future__ import annotations

import uuid

import pytest
from exulanica.consent.regions import Silhouette
from exulanica.ingest.person_review import record_region_edits

from test_asset_read_currency import delivery as delivery
from test_intake_upload import upload as upload
from test_screening_currency import ACTOR


def _structural_counts(upload):
    return upload.rows(
        "select (select count(*) from reconstruction_scene) scenes, "
        "(select count(*) from world_topology_contract) contracts, "
        "(select count(*) from world_topology_region) regions, "
        "(select count(*) from world_alternate_version) versions, "
        "(select count(*) from world_topology_source) sources, "
        "(select count(*) from world_structure_snapshot) snapshots, "
        "(select count(*) from reconstruction_scene_job) jobs"
    )


def test_intake_only_is_reviewable_without_structural_writes(upload):
    response = upload.one()
    assert response.status_code == 202, response.text
    before = _structural_counts(upload)
    response = upload.get("/graph/sources")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "private, no-store"
    [source] = response.json()
    [capture] = upload.rows("select capture_id from capture")
    [span] = upload.rows("select span_id from evidence_span where modality='still_image'")
    assert source["kind"] == "admitted_capture"
    assert source["capture_id"] == str(capture["capture_id"])
    assert source["evidence_span_id"] == str(span["span_id"])
    assert source["person_review_state"] == "unscreened"
    assert source["person_regions"] == []
    assert source["state"] == "available"
    assert upload.get(source["evidence_path"]).status_code == 200
    graph = upload.get("/graph")
    assert graph.status_code == 200, graph.text
    assert graph.json()["review_sources"] == [source]
    assert graph.json()["reconstruction_scenes"] == []
    assert _structural_counts(upload) == before


@pytest.mark.parametrize("route", ["/graph", "/graph/sources"])
def test_final_boundary_refreshes_person_state_and_withholds_changed_viewer(
    upload, monkeypatch, route
):
    assert upload.one().status_code == 202
    [capture] = upload.rows("select capture_id from capture")
    original = upload.store.exists
    armed = True

    def changed(blob):
        nonlocal armed
        exists = original(blob)
        if armed:
            armed = False
            record_region_edits(
                upload.repository,
                capture_id=capture["capture_id"],
                actor=ACTOR,
                edits=[
                    {
                        "action": "add",
                        "region_key": "ab" * 32,
                        "silhouette": Silhouette(
                            ((0, 0), (500000, 0), (0, 500000))
                        ).as_digest_input(),
                        "subject_id": None,
                    }
                ],
            )
        return exists

    monkeypatch.setattr(upload.store, "exists", changed)
    response = upload.get(route)
    assert response.status_code == 200, response.text
    body = response.json()
    [source] = body["review_sources"] if route == "/graph" else body
    assert source["person_review_state"] == "screened"
    assert source["person_regions"][0]["region_id"] == "ab" * 32
    assert source["person_regions"][0]["state"] == "unknown"
    assert source["state"] == "unavailable_asset"
    assert source["evidence_path"] is None
    assert source["content_sha256"] is None


@pytest.mark.parametrize("route", ["/graph", "/graph/sources"])
def test_tombstone_committed_during_buffer_read_removes_metadata(upload, monkeypatch, route):
    assert upload.one().status_code == 202
    [capture] = upload.rows("select capture_id from capture")
    original = upload.store.exists
    armed = True

    def deleted(blob):
        nonlocal armed
        exists = original(blob)
        if armed:
            armed = False
            upload.repository.insert_tombstone(
                scope="capture", capture_id=capture["capture_id"], requested_by=ACTOR
            )
        return exists

    monkeypatch.setattr(upload.store, "exists", deleted)
    response = upload.get(route)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["review_sources"] if route == "/graph" else body) == []


def test_missing_bytes_are_explicit_and_have_no_media_reference(upload, monkeypatch):
    assert upload.one().status_code == 202
    monkeypatch.setattr(upload.store, "exists", lambda _blob: False)
    [source] = upload.get("/graph/sources").json()
    assert source["state"] == "unavailable_asset"
    assert source["evidence_path"] is None
    assert source["content_sha256"] is None
    assert source["capture_id"]


def test_inventory_requires_workspace_session_and_cannot_cross_workspace(delivery):
    d = delivery
    assert d.client.get("/graph/sources").status_code == 401
    [source] = d.get("/graph/sources").json()
    assert source["capture_id"] == str(d.case.capture)
    assert d.get("/graph/sources", foreign=True).json() == []
    assert d.get(source["evidence_path"], foreign=True).status_code == 404


def test_withdrawn_person_removes_capture_and_denies_evidence(delivery):
    d = delivery
    c = d.case
    [source] = d.get("/graph/sources").json()
    c.edit(subject=c.subject)
    c.consent("withdrawn")
    assert d.get("/graph/sources").json() == []
    assert d.get(source["evidence_path"]).status_code in (404, 409, 410)


def test_current_mask_bytes_and_media_type_are_the_evidence_route_values(delivery):
    import hashlib

    d = delivery
    d.case.edit()
    d.case.build()
    [source] = d.get("/graph/sources").json()
    assert source["person_review_state"] == "screened"
    assert source["person_regions"][0]["state"] == "unknown"
    response = d.get(source["evidence_path"])
    assert response.status_code == 200, response.text
    assert source["content_sha256"] == hashlib.sha256(response.content).hexdigest()
    assert source["media_type"] == response.headers["content-type"] == "image/jpeg"


def test_span_tombstone_never_offers_whole_photograph(upload):
    assert upload.one().status_code == 202
    [capture] = upload.rows("select capture_id,blob_sha256 from capture")
    upload.repository.insert_tombstone(
        scope="interval",
        track_key="img",
        interval_ns=[(0, 1)],
        capture_id=capture["capture_id"],
        requested_by=uuid.uuid4(),
    )
    assert upload.get("/graph/sources").json() == []


def test_source_inventory_selects_whole_photograph_among_region_evidence(upload):
    from exulanica.evidence import BlobId, DisplayGeometry, EvidenceAddress, Rect, Region

    assert upload.one().status_code == 202
    [capture] = upload.rows("select blob_sha256 from capture")
    blob = BlobId(bytes(capture["blob_sha256"]))
    crop = upload.repository.upsert_span(
        EvidenceAddress.photograph(
            blob, region=Region(Rect(0, 0, 500000, 500000), DisplayGeometry(160, 100))
        )
    )
    whole = upload.repository.upsert_span(EvidenceAddress.photograph(blob))
    [source] = upload.get("/graph/sources").json()
    assert source["evidence_span_id"] == str(whole)
    assert source["evidence_span_id"] != str(crop)
