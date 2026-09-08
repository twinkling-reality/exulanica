"""Labelled fixtures through the real database, authenticated route and offline recipient."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.graph.world_read import world_read_bundle
from exulanica.graph.world_read_verification import EvidenceError, verify
from exulanica.ingest.person_review import create_subject, record_consent, record_region_edits

from test_api import deployment as deployment
from test_screening_currency import ACTOR, KEY, OUTLINE
from test_world_read_route import _place_in, _scene_in

AT = "2026-09-08T00:00:00Z"


def _save(name, value):
    root = os.environ.get("WORLD_READ_RECIPIENT_ARTIFACTS")
    if root:
        target = Path(root) / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(canonical_json(value))


def _reseal(envelope):
    bundle = envelope["bundle"]
    evidence = bundle["recipient_evidence"]
    evidence["evidence_sha256"] = sha256_of_canonical(evidence["record"]).hex()
    bundle["recorded_sha256"] = sha256_of_canonical(
        {key: bundle[key] for key in bundle["recorded_keys"]}
    ).hex()
    envelope["bundle_sha256"] = sha256_of_canonical(bundle).hex()
    return envelope


def _verify(envelope, at=AT):
    return verify(envelope, at=at, expected_bundle_sha256=envelope["bundle_sha256"])


def _person(repository, capture):
    subject = create_subject(repository, actor=ACTOR)
    record_region_edits(
        repository,
        capture_id=capture,
        actor=ACTOR,
        edits=[
            {
                "action": "add",
                "region_key": KEY.hex(),
                "subject_id": str(subject),
                "silhouette": OUTLINE.as_digest_input(),
            }
        ],
    )
    record_consent(
        repository,
        subject_id=subject,
        actor=ACTOR,
        consent_scope="likeness",
        decision="granted",
        effective_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC),
    )
    return subject


def test_recipient_route_canonical_clean_process(deployment, repository, tmp_path):
    scene = _scene_in(deployment, repository, tmp_path)
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene}")
    assert response.status_code == 200, response.text
    envelope = response.json()
    path = tmp_path / "bundle.json"
    path.write_bytes(canonical_json(envelope))
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_world_read_recipient_evidence.py",
            str(path),
            "--at",
            AT,
            "--expected-bundle-sha256",
            envelope["bundle_sha256"],
        ],
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if "DATABASE" not in k},
    )
    assert result.returncode == 0, result.stderr
    evaluation = json.loads(result.stdout)
    assert all(p["state"] == "available" for p in evaluation["point_lineage"].values())
    assert evaluation["release"] == "internal_only"
    _save("route-bundle.json", envelope)
    _save("clean-process-evaluation.json", evaluation)
    foreign = deployment.as_stranger("GET", f"/world-read/scenes/{scene}")
    assert foreign.status_code == 404
    _save("foreign-response.json", foreign.json())


def test_recipient_consent_expiry_and_record_movement(deployment, repository, tmp_path):
    from unittest.mock import patch

    from exulanica.ingest.person_review import review_list
    from exulanica.ingest.privacy import authorize_personal_capture, record_human_screening

    from conftest import write_point_map

    configured = {}
    boundary = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=15)

    def write_with_person(repo, store, blob, payload):
        capture = repo.live_capture_for_blob(blob).capture_id
        if not configured:
            subject = _person(repo, capture)
            record_consent(
                repo,
                subject_id=subject,
                actor=ACTOR,
                consent_scope="naming",
                decision="granted",
                effective_at=boundary - dt.timedelta(days=1),
                valid_until=boundary,
            )
            configured.update(capture=capture, subject=subject)
        auth = authorize_personal_capture(
            repo,
            capture_id=capture,
            actor=ACTOR,
            account_authority_basis="Generated fixture, no personal media",
            authorization_scope={"purpose": "recipient test"},
            purpose="recipient test",
        )
        screen = record_human_screening(
            repo,
            authorization_id=auth.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=review_list(repo, capture),
        )
        return write_point_map(repo, store, blob, payload, privacy_screening_id=screen.screening_id)

    with patch("test_world_read_route.write_point_map", write_with_person):
        scene = _scene_in(deployment, repository, tmp_path)
    path = f"/world-read/scenes/{scene}"
    capture, subject = configured["capture"], configured["subject"]
    first = deployment.as_owner("GET", path)
    assert first.status_code == 200, first.text
    first = first.json()
    tampered = copy.deepcopy(first)
    region = next(
        c["regions"][0]
        for c in tampered["bundle"]["recipient_evidence"]["record"]["captures"]
        if c["regions"]
    )
    region["receipts"][0]["record"]["decision"] = "revoked"
    with pytest.raises(EvidenceError, match="consent_digest_mismatch"):
        _verify(_reseal(tampered))
    time.sleep(max(0, (boundary - dt.datetime.now(dt.UTC)).total_seconds()) + 0.02)
    response = deployment.as_owner("GET", path)
    assert response.status_code == 404, response.text
    second = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    assert first["bundle"]["recorded_sha256"] == second["bundle"]["recorded_sha256"]
    key = str(capture)
    earlier = _verify(first, (boundary - dt.timedelta(seconds=1)).isoformat())
    later = _verify(second, (boundary + dt.timedelta(seconds=1)).isoformat())
    assert earlier["people"][key][0]["scopes"]["naming"] is True
    assert later["people"][key][0]["scopes"]["naming"] is False
    assert later["people"][key][0]["scopes"]["presence"] is False
    assert later["people"][key][0]["scopes"]["likeness"] is True
    _save("consent-before-expiry.json", first)
    _save("consent-after-expiry.json", second)
    _save("evaluation-before-expiry.json", earlier)
    _save("evaluation-after-expiry.json", later)
    # A withdrawal is a write and is terminal, even in a historical-time evaluation.
    record_consent(
        repository,
        subject_id=subject,
        actor=ACTOR,
        consent_scope="likeness",
        decision="withdrawn",
        effective_at=dt.datetime.now(dt.UTC),
    )
    withdrawn = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    assert withdrawn["bundle"]["recorded_sha256"] != second["bundle"]["recorded_sha256"]
    assert _verify(withdrawn)["people"][key][0]["withdrawn"] is True
    assert deployment.as_owner("GET", path).status_code == 404
    assert (
        _verify(first, (boundary + dt.timedelta(days=1)).isoformat())["people"][key][0]["withdrawn"]
        is False
    )
    _save("withdrawn-recorded-bundle.json", withdrawn)


def test_recipient_rejects_omission_and_output_mismatch(deployment, repository, tmp_path):
    scene = _scene_in(deployment, repository, tmp_path)
    envelope = deployment.as_owner("GET", f"/world-read/scenes/{scene}").json()
    omitted = copy.deepcopy(envelope)
    omitted["bundle"]["recipient_evidence"]["record"]["point_maps"].pop()
    with pytest.raises(EvidenceError, match="geometry_lineage_missing"):
        _verify(_reseal(omitted))
    changed = copy.deepcopy(envelope)
    changed["bundle"]["geometry"][0]["content_sha256"] = "f" * 64
    with pytest.raises(EvidenceError, match="geometry_output_mismatch"):
        _verify(_reseal(changed))
    changed = copy.deepcopy(envelope)
    changed["bundle"]["recipient_evidence"]["record"]["point_maps"][0]["lineage"]["read_sha256"] = (
        "e" * 64
    )
    with pytest.raises(EvidenceError, match="point_pose_source_mismatch"):
        _verify(_reseal(changed))
    omitted["bundle"]["recipient_evidence"]["record"]["point_maps"].pop()
    with pytest.raises(EvidenceError, match="bundle_digest_mismatch"):
        _verify(omitted)


def test_recipient_scene_place_compatibility(deployment, repository, tmp_path):
    scene, _, place = _place_in(deployment, repository, tmp_path)
    scene_bundle = deployment.as_owner("GET", f"/world-read/scenes/{scene}").json()
    response = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}", params={"at": "2026-09-16T00:00:00Z"}
    )
    assert response.status_code == 200, response.text
    placed = response.json()
    assert placed["bundle"]["scene"]["scene_id"] == str(scene)
    assert placed["bundle"]["recipient_evidence"] == scene_bundle["bundle"]["recipient_evidence"]
    assert _verify(placed)["release"] == "internal_only"
    _save("place-bundle.json", placed)
    unresolved = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}", params={"at": "2000-01-01T00:00:00Z"}
    )
    assert unresolved.status_code == 200, unresolved.text
    assert _verify(unresolved.json())["reason"] == "no_version_at_that_time"
    _save("unresolved-place-bundle.json", unresolved.json())


def test_recipient_trained_publication_and_source_controls(deployment, repository, tmp_path):
    from exulanica.store.local import LocalContentAddressedStore

    from test_training_inputs import scene_sample

    root = tmp_path / "trained"
    root.mkdir()
    _, materials = scene_sample(repository, root)
    store = LocalContentAddressedStore(root / "store")
    for blob in store.iter_blob_ids():
        deployment.store.put_bytes(store.get(blob))
    scene = materials[0]["provenance"]["scene_id"]
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene}")
    assert response.status_code == 200, response.text
    envelope = response.json()
    assert any(g["kind"] == "trained_geometry" for g in envelope["bundle"]["geometry"])
    assert _verify(envelope)["release"] == "internal_only"
    _save("trained-route-bundle.json", envelope)
    changed = copy.deepcopy(envelope)
    geometry = next(g for g in changed["bundle"]["geometry"] if g["kind"] == "trained_geometry")
    geometry["content_sha256"] = "f" * 64
    with pytest.raises(EvidenceError, match="trained_output_mismatch"):
        _verify(_reseal(changed))


def test_recipient_masked_sources_and_stale_lineage(deployment, repository, tmp_path):
    import uuid
    from unittest.mock import patch

    from exulanica.ingest.person_review import review_list
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.ingest.privacy import (
        authorize_personal_capture,
        record_human_screening,
        record_person_detection_screening,
    )

    from conftest import write_point_map

    configured = {}

    def masked_point(repo, store, blob, payload):
        capture = repo.live_capture_for_blob(blob).capture_id
        mask = None
        auth = authorize_personal_capture(
            repo,
            capture_id=capture,
            actor=ACTOR,
            account_authority_basis="Generated mask fixture; no personal media",
            authorization_scope={"purpose": "recipient mask test"},
            purpose="recipient mask test",
        )
        if not configured:
            record_region_edits(
                repo,
                capture_id=capture,
                actor=ACTOR,
                edits=[
                    {
                        "action": "add",
                        "region_key": KEY.hex(),
                        "silhouette": OUTLINE.as_digest_input(),
                    }
                ],
            )
            detection = record_person_detection_screening(
                repo,
                authorization_id=auth.authorization_id,
                authorized_by=ACTOR,
                purpose="generated region fixture",
            )
            outcome = PhotoIngestPipeline(repo, store).ingest_derivatives(
                capture, privacy_screening_id=detection.screening_id
            )
            assert outcome.error is None, outcome.error
            mask = repo.current_capture_artifacts(capture_ids=[capture], kind="masked_source")[
                capture
            ]
            configured.update(capture=capture, mask=mask)
        screen = record_human_screening(
            repo,
            authorization_id=auth.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=review_list(repo, capture),
        )
        if mask is None:
            return write_point_map(
                repo, store, blob, payload, privacy_screening_id=screen.screening_id
            )
        stored = store.put_bytes(payload)
        repo.insert_artifact(
            artifact_id=uuid.uuid4(),
            kind="point_map",
            source_blob=blob,
            stage_key="depth",
            stage_version=99,
            params_digest=b"p" * 32,
            input_digest=b"i" * 32,
            idempotency_key=str(uuid.uuid4()),
            content_sha256=stored.blob_id.digest,
            storage_key=store.key_for(stored.blob_id),
            byte_size=stored.byte_size,
            produced_by_event=None,
            privacy_screening_id=screen.screening_id,
            read_source_sha256=mask.content_sha256,
        )

    with patch("test_world_read_route.write_point_map", masked_point):
        scene = _scene_in(deployment, repository, tmp_path)
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene}")
    assert response.status_code == 200, response.text
    envelope = response.json()
    record = envelope["bundle"]["recipient_evidence"]["record"]
    point = next(p for p in record["point_maps"] if p["lineage"].get("mode") == "masked")
    assert point["lineage"]["read_sha256"] == configured["mask"].content_sha256.hex()
    assert point["lineage"]["mask_manifest"]["state"] == "available"
    result = _verify(envelope)
    assert result["release"] == "internal_only"
    assert result["point_lineage"][point["artifact_id"]]["state"] == "available"
    changed_input = copy.deepcopy(envelope)
    altered_input = next(
        p
        for p in changed_input["bundle"]["recipient_evidence"]["record"]["point_maps"]
        if p["lineage"].get("mode") == "masked"
    )
    altered_input["lineage"]["mask_build"]["input_sha256"] = "e" * 64
    with pytest.raises(EvidenceError, match="mask_input_commitment_mismatch"):
        _verify(_reseal(changed_input))
    # A legacy producer may have omitted the snapshot. The wire can preserve exact byte
    # lineage while refusing the missing coverage proof, without guessing a replacement.
    legacy = copy.deepcopy(envelope)
    legacy_point = next(
        p
        for p in legacy["bundle"]["recipient_evidence"]["record"]["point_maps"]
        if p["lineage"].get("mode") == "masked"
    )
    legacy_point["lineage"]["mask_build"] = {
        "state": "unavailable",
        "reason": "legacy_mask_build_snapshot_missing",
    }
    assert _verify(_reseal(legacy))["point_lineage"][point["artifact_id"]] == {
        "state": "unavailable",
        "reason": "legacy_mask_build_snapshot_missing",
    }
    _save("legacy-protocol-fixture.json", legacy)
    _save("masked-route-bundle.json", envelope)
    changed = copy.deepcopy(envelope)
    altered = next(
        p
        for p in changed["bundle"]["recipient_evidence"]["record"]["point_maps"]
        if p["lineage"].get("mode") == "masked"
    )
    manifest = altered["lineage"]["mask_manifest"]
    body = json.loads(manifest["json_utf8"])
    body["masks"] = []
    manifest["json_utf8"] = canonical_json(body).decode()
    manifest["sha256"] = sha256_of_canonical(body).hex()
    with pytest.raises(EvidenceError, match="stale_derivative_lineage"):
        _verify(_reseal(changed))
    changed_outline = copy.deepcopy(envelope)
    outlined = next(
        c
        for c in changed_outline["bundle"]["recipient_evidence"]["record"]["captures"]
        if c["regions"]
    )
    outlined["regions"][0]["silhouette"]["points"][1][0] = 600000
    with pytest.raises(EvidenceError, match="stale_derivative_lineage"):
        _verify(_reseal(changed_outline))
    # A new persisted region cannot retroactively become part of the old mask.
    record_region_edits(
        repository,
        capture_id=configured["capture"],
        actor=ACTOR,
        edits=[
            {
                "action": "add",
                "region_key": (b"b" * 32).hex(),
                "silhouette": OUTLINE.as_digest_input(),
            }
        ],
    )
    stale = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    with pytest.raises(EvidenceError, match="stale_derivative_lineage"):
        _verify(stale)
    assert deployment.as_owner("GET", f"/world-read/scenes/{scene}").status_code == 404
    _save("stale-mask-recorded-bundle.json", stale)
