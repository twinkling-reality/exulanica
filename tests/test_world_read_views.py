"""Generated media through SQL, read-only authenticated HTTP, and offline byte checks."""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.db.roles import provision_runtime_role
from exulanica.evidence.blob import BlobId
from exulanica.graph.world_read_verification import EvidenceError, verify_downloads
from exulanica.ingest.person_review import record_region_edits

from conftest import photo_bytes, scratch_role_database, write_photo
from test_api import deployment as deployment
from test_place_read_bundle import _bind, _second_scene
from test_screening_currency import ACTOR, KEY, OUTLINE
from test_world_read_evidence import AT, _masked_scene, _reseal
from test_world_read_route import _scene_in


@pytest.fixture(autouse=True)
def readonly(deployment, repository, spine_schema, monkeypatch, request):
    _, schema = spine_schema
    provision_runtime_role(repository.connection, role="exulanica_ro", read_only=True)
    database = scratch_role_database(schema, "exulanica_ro")
    services = deployment.client.app.state.services
    deployment.client.app.state.services = dataclasses.replace(
        services, readonly_database=database, executor_shares_the_write_role=False
    )
    with database.session(repository.workspace_id) as connection:
        row = connection.execute(
            "select current_user as role, rolsuper, rolbypassrls, "
            "has_table_privilege(current_user,'capture','INSERT') as writes "
            "from pg_roles where rolname=current_user"
        ).fetchone()
        assert row == {
            "role": "exulanica_ro",
            "rolsuper": False,
            "rolbypassrls": False,
            "writes": False,
        }

    events = []
    responses = []
    original_request = deployment._request

    def observed(token, method, path, **kwargs):
        response = original_request(token, method, path, **kwargs)
        events.append(
            {
                "method": method,
                "path": path,
                "status": response.status_code,
                "byte_size": len(response.content),
                "sha256": hashlib.sha256(response.content).hexdigest(),
                "range": kwargs.get("headers", {}).get("Range"),
            }
        )
        responses.append(response.content)
        return response

    monkeypatch.setattr(deployment, "_request", observed)
    yield
    if target := os.environ.get("WORLD_READ_VIEW_ARTIFACTS"):
        folder = Path(target) / request.node.name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "requests.json").write_bytes(canonical_json(events))
        for index, response in enumerate(responses):
            (folder / f"response-{index:03d}.bin").write_bytes(response)


def bundle(deployment, scene):
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene}")
    assert response.status_code == 200, response.text
    return response.json()


def available(envelope):
    views = [v for v in envelope["bundle"]["views"] if v["photo_bytes"]["state"] == "available"]
    assert views, envelope["bundle"]["views"]
    return views


def download(deployment, envelope):
    downloads = {}
    for view in available(envelope):
        desc = view["photo_bytes"]
        response = deployment.as_owner("GET", desc["fetch"])
        assert response.status_code == 200, response.text
        assert hashlib.sha256(response.content).hexdigest() == desc["sha256"]
        assert response.headers["content-type"] == desc["media_type"]
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-exulanica-view-sha256"] == desc["sha256"]
        downloads[view["capture_id"]] = response.content
    return downloads


def offline(envelope, downloads):
    return verify_downloads(
        envelope, downloads, at=AT, expected_bundle_sha256=envelope["bundle_sha256"]
    )


def retain_and_replay(label, envelope, downloads, tmp_path):
    root = Path(os.environ.get("WORLD_READ_VIEW_ARTIFACTS", tmp_path)) / label
    root.mkdir(parents=True, exist_ok=True)
    (root / "bundle.json").write_bytes(canonical_json(envelope))
    for capture, data in downloads.items():
        (root / f"{capture}.image").write_bytes(data)
    script = Path(__file__).resolve().parents[1] / "scripts/verify_world_read_view_evidence.py"
    clean = {
        k: v
        for k, v in os.environ.items()
        if not any(word in k.upper() for word in ("DATABASE", "POSTGRES", "PYTHONPATH"))
    }
    guard = (
        "import runpy,sys,psycopg; "
        "psycopg.connect=lambda *a,**k: (_ for _ in ()).throw("
        "RuntimeError('offline DB forbidden')); "
        "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name='__main__')"
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            guard,
            str(script),
            str(root / "bundle.json"),
            "--downloads",
            str(root),
            "--at",
            AT,
            "--expected-bundle-sha256",
            envelope["bundle_sha256"],
        ],
        cwd=tmp_path,
        env=clean,
        capture_output=True,
        text=True,
    )
    (root / "offline-result.json").write_text(result.stdout or result.stderr)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == offline(envelope, downloads)


def test_scene_place_downloads_and_clean_offline_verification(deployment, repository, tmp_path):
    def oriented(directory, name, **kwargs):
        return write_photo(directory, name, orientation=6 if name == "wr0.jpg" else 1, **kwargs)

    with patch("test_world_read_route.write_photo", oriented):
        scene, configured = _masked_scene(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    downloads = download(deployment, first)
    values = available(first)
    masked = next(v for v in values if v["photo_bytes"]["kind"] == "masked")
    assert masked["capture_id"] == str(configured["capture"])
    desc = masked["photo_bytes"]
    assert (desc["width"], desc["height"]) == (160, 100)
    assert desc["source_sha256"] != desc["sha256"] == desc["pose_input_sha256"]
    from exulanica.corpus.decode import open_sensor

    original = deployment.store.get(BlobId.from_hex(desc["source_sha256"]))
    if target := os.environ.get("WORLD_READ_VIEW_ARTIFACTS"):
        (Path(target) / "generated-oriented-source.jpg").write_bytes(original)
    with open_sensor(original) as image:
        assert image.size == (100, 160) and image.getexif()[274] == 6
    with open_sensor(downloads[masked["capture_id"]]) as image:
        assert image.size == (160, 100) and image.getexif().get(274, 1) == 1
        assert all(abs(c - 128) <= 3 for c in image.getpixel((20, 20)))
    assert {v["photo_bytes"]["kind"] for v in values} == {"original", "masked"}
    retain_and_replay("scene", first, downloads, tmp_path)
    _, second = _second_scene(repository, deployment.store, tmp_path)
    place = _bind(repository, deployment.store, scene, second)
    response = deployment.as_owner(
        "GET", f"/world-read/places/{place.place_id}?at=2026-09-08T00:00:00Z"
    )
    assert response.status_code == 200, response.text
    placed = response.json()
    assert placed["bundle"]["views"] == first["bundle"]["views"]
    retain_and_replay("place", placed, download(deployment, placed), tmp_path)
    # Original citations retain original meaning, and cannot reveal this required mask's source.
    assert deployment.as_owner("GET", f"/evidence/{desc['span_id']}").status_code == 409
    unmasked = next(v["photo_bytes"] for v in values if v["photo_bytes"]["kind"] == "original")
    original_response = deployment.as_owner("GET", f"/evidence/{unmasked['span_id']}")
    assert hashlib.sha256(original_response.content).hexdigest() == unmasked["source_sha256"]


def test_bound_full_and_range_requests(deployment, repository, tmp_path):
    envelope = bundle(deployment, _scene_in(deployment, repository, tmp_path))
    desc = available(envelope)[0]["photo_bytes"]
    full = deployment.as_owner("GET", desc["fetch"])
    assert full.status_code == 200
    pieces = []
    for request_range, start, end in [("bytes=0-9", 0, 10), ("bytes=10-", 10, len(full.content))]:
        response = deployment.as_owner("GET", desc["fetch"], headers={"Range": request_range})
        assert response.status_code == 206
        assert response.content == full.content[start:end]
        assert response.headers["content-range"] == f"bytes {start}-{end - 1}/{len(full.content)}"
        assert response.headers["x-exulanica-view-sha256"] == desc["sha256"]
        pieces.append(response.content)
    assert hashlib.sha256(b"".join(pieces)).hexdigest() == desc["sha256"]
    assert (
        deployment.as_owner("GET", desc["fetch"], headers={"Range": "bytes=999999-"}).status_code
        == 416
    )
    assert deployment.client.get(desc["fetch"]).status_code == 401
    real = deployment.as_stranger("GET", desc["fetch"])
    invented = deployment.as_stranger(
        "GET", desc["fetch"].replace(desc["span_id"], str(uuid.uuid4()))
    )
    assert real.status_code == 404 and real.json() == invented.json()
    foreign_scene = desc["fetch"].replace(desc["scene_id"], str(uuid.uuid4()))
    assert deployment.as_owner("GET", foreign_scene).status_code == 404


def test_wrong_bytes_under_declared_digest_refuse_route(
    deployment, repository, tmp_path, monkeypatch
):
    scene = _scene_in(deployment, repository, tmp_path)
    envelope = bundle(deployment, scene)
    desc = available(envelope)[0]["photo_bytes"]
    original_get = deployment.store.get
    wrong = photo_bytes(when="2025:01:01 01:01:01", size=(desc["width"], desc["height"]))
    assert hashlib.sha256(wrong).hexdigest() != desc["sha256"]

    def get(blob):
        return wrong if blob.hex == desc["sha256"] else original_get(blob)

    monkeypatch.setattr(deployment.store, "get", get)
    response = deployment.as_owner("GET", desc["fetch"])
    assert response.status_code == 409, "wrong bytes were delivered under the declared digest"


def test_final_permission_check_refuses_during_fetch(deployment, repository, tmp_path, monkeypatch):
    scene = _scene_in(deployment, repository, tmp_path)
    envelope = bundle(deployment, scene)
    view = available(envelope)[0]
    desc = view["photo_bytes"]
    original_get = deployment.store.get
    reads = 0

    def get(blob):
        nonlocal reads
        data = original_get(blob)
        if blob.hex == desc["sha256"]:
            reads += 1
            if reads == 2:  # descriptor read first, actual download buffer second
                record_region_edits(
                    repository,
                    capture_id=uuid.UUID(view["capture_id"]),
                    actor=ACTOR,
                    edits=[
                        {
                            "action": "add",
                            "region_key": KEY.hex(),
                            "silhouette": OUTLINE.as_digest_input(),
                        }
                    ],
                )
        return data

    monkeypatch.setattr(deployment.store, "get", get)
    response = deployment.as_owner("GET", desc["fetch"], headers={"Range": "bytes=0-9"})
    assert reads == 2
    assert response.status_code == 409, "missing final permission check served changed selection"


def test_camera_pixel_space_refuses_route(deployment, repository, tmp_path):
    from test_scene_reconstruction_pipeline import FakeColmap

    class WrongCamera(FakeColmap):
        def __call__(self, command, cwd):
            result = super().__call__(command, cwd)
            if command[1] == "mapper":
                path = cwd / "sparse/0/cameras.txt"
                lines = []
                for line in path.read_text().splitlines():
                    fields = line.split()
                    fields[2] = str(int(fields[2]) + 7)
                    lines.append(" ".join(fields))
                path.write_text("\n".join(lines) + "\n")
            return result

    from test_scene_reconstruction_pipeline import _numeric_point_map

    with (
        patch("test_world_read_route.FakeColmap", WrongCamera),
        patch(
            "test_world_read_route._numeric_point_map", lambda index: _numeric_point_map(index + 7)
        ),
    ):
        scene = _scene_in(deployment, repository, tmp_path)
    envelope = bundle(deployment, scene)
    assert all(v["camera"] is not None for v in envelope["bundle"]["views"])
    assert {v["photo_bytes"].get("reason") for v in envelope["bundle"]["views"]} == {
        "camera_pixel_space_mismatch"
    }


@pytest.mark.parametrize("damage", ["missing", "corrupt"])
def test_store_damage_refuses_bound_download(deployment, repository, tmp_path, damage):
    scene = _scene_in(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    desc = available(first)[0]["photo_bytes"]
    path = deployment.store.root / deployment.store.key_for(BlobId.from_hex(desc["sha256"]))
    if damage == "missing":
        path.unlink()
    else:
        path.chmod(0o600)
        path.write_bytes(b"corrupt generated object")
    assert deployment.as_owner("GET", desc["fetch"]).status_code == 409
    after = bundle(deployment, scene)
    assert any(
        v["photo_bytes"].get("reason") == "view_bytes_missing_or_corrupt"
        for v in after["bundle"]["views"]
    )


@pytest.mark.parametrize("change", ["stale_mask", "missing_mask", "withdrawal"])
def test_mask_and_withdrawal_changes_refuse_old_binding(deployment, repository, tmp_path, change):
    scene, configured = _masked_scene(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    view = next(v for v in available(first) if v["photo_bytes"]["kind"] == "masked")
    desc = view["photo_bytes"]
    assert deployment.as_owner("GET", desc["fetch"]).status_code == 200
    if change == "stale_mask":
        record_region_edits(
            repository,
            capture_id=configured["capture"],
            actor=ACTOR,
            edits=[
                {
                    "action": "confirm",
                    "region_key": KEY.hex(),
                    "silhouette": {
                        "kind": "polygon",
                        "points": [[0, 0], [800000, 0], [800000, 800000], [0, 800000]],
                    },
                }
            ],
        )
    elif change == "missing_mask":
        mask = configured["mask"]
        (deployment.store.root / deployment.store.key_for(BlobId(mask.content_sha256))).unlink()
    else:
        repository.insert_tombstone(
            scope="capture",
            capture_id=configured["capture"],
            requested_by=ACTOR,
            reason="generated withdrawal",
        )
    response = deployment.as_owner("GET", desc["fetch"])
    assert response.status_code == (410 if change == "withdrawal" else 409), response.text


@pytest.mark.parametrize("damage", ["tamper", "camera", "malformed", "legacy"])
def test_offline_download_controls(deployment, repository, tmp_path, damage):
    envelope = bundle(deployment, _scene_in(deployment, repository, tmp_path))
    downloads = download(deployment, envelope)
    view = available(envelope)[0]
    if damage == "tamper":
        downloads[view["capture_id"]] += b"tamper"
        reason = "view_bytes_digest_mismatch"
    elif damage == "camera":
        view["camera"]["calibration"]["width"] += 1
        desc = view["photo_bytes"]
        from exulanica.graph.world_read_views import fetch_reference

        desc["binding_sha256"] = sha256_of_canonical(
            {k: v for k, v in desc.items() if k not in {"binding_sha256", "fetch"}}
        ).hex()
        desc["fetch"] = fetch_reference(desc, desc["binding_sha256"])
        _reseal(envelope)
        reason = "view_camera_mismatch"
    elif damage == "malformed":
        view["photo_bytes"] = ["unsupported"]
        _reseal(envelope)
        reason = "view_descriptor_malformed"
    else:
        for item in envelope["bundle"]["views"]:
            item.pop("photo_bytes")
        _reseal(envelope)
        assert {v["reason"] for v in offline(envelope, downloads)["views"].values()} == {
            "legacy_view_binding_missing"
        }
        retain_and_replay("legacy", envelope, downloads, tmp_path)
        return
    with pytest.raises(EvidenceError, match=reason):
        offline(envelope, downloads)


def test_addition_preserves_recorded_v2_identity(deployment, repository, tmp_path):
    envelope = bundle(deployment, _scene_in(deployment, repository, tmp_path))
    legacy = copy.deepcopy(envelope)
    for view in legacy["bundle"]["views"]:
        view.pop("photo_bytes")
    _reseal(legacy)
    assert legacy["bundle"]["recorded_sha256"] == envelope["bundle"]["recorded_sha256"]
    assert legacy["bundle_sha256"] != envelope["bundle_sha256"]
    assert legacy["bundle"]["recorded_keys"] == envelope["bundle"]["recorded_keys"]


def person_scene(deployment, repository, tmp_path):
    import datetime as dt

    from exulanica.ingest.person_review import create_subject, record_consent, review_list
    from exulanica.ingest.privacy import authorize_personal_capture, record_human_screening

    from conftest import write_point_map

    configured = {}
    boundary = dt.datetime.now(dt.UTC) + dt.timedelta(days=1)

    def point(repo, store, blob, payload):
        capture = repo.live_capture_for_blob(blob).capture_id
        if not configured:
            subject = create_subject(repo, actor=ACTOR)
            record_region_edits(
                repo,
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
                repo,
                subject_id=subject,
                actor=ACTOR,
                consent_scope="likeness",
                decision="granted",
                effective_at=boundary - dt.timedelta(days=2),
                valid_until=boundary,
            )
            configured.update(capture=capture, subject=subject, boundary=boundary)
        auth = authorize_personal_capture(
            repo,
            capture_id=capture,
            actor=ACTOR,
            account_authority_basis="Generated posed-view fixture only",
            authorization_scope={"purpose": "generated view test"},
            purpose="generated view test",
        )
        screen = record_human_screening(
            repo,
            authorization_id=auth.authorization_id,
            reviewed_by=ACTOR,
            sensitive_regions=review_list(repo, capture),
        )
        return write_point_map(repo, store, blob, payload, privacy_screening_id=screen.screening_id)

    with patch("test_world_read_route.write_point_map", point):
        scene = _scene_in(deployment, repository, tmp_path)
    return scene, configured


def test_expiry_exact_boundary_preserves_recorded_identity(
    deployment, repository, tmp_path, monkeypatch
):
    import datetime as dt

    from exulanica.api.routes import evidence, world_read
    from exulanica.graph import asset_read_policy, world_read_views
    from exulanica.graph.world_read import world_read_bundle

    scene, configured = person_scene(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    desc = next(
        v["photo_bytes"] for v in available(first) if v["capture_id"] == str(configured["capture"])
    )
    boundary = configured["boundary"]
    for instant, expected in [(boundary - dt.timedelta(microseconds=1), 200), (boundary, 409)]:
        for module in (asset_read_policy, world_read_views, evidence, world_read):
            monkeypatch.setattr(module, "evaluation_time", lambda connection, t=instant: t)
        response = deployment.as_owner("GET", desc["fetch"])
        assert response.status_code == expected, response.text
    second = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    assert first["bundle"]["recorded_sha256"] == second["bundle"]["recorded_sha256"]
    assert first["bundle_sha256"] != second["bundle_sha256"]


@pytest.mark.parametrize("during", [False, True])
def test_recorded_consent_change_requires_refresh(
    deployment, repository, tmp_path, monkeypatch, during
):
    from exulanica.ingest.person_review import record_consent

    scene, configured = person_scene(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    desc = next(
        v["photo_bytes"] for v in available(first) if v["capture_id"] == str(configured["capture"])
    )

    def change():
        # Same effective image selection, but a new recorded consent identity.
        record_consent(
            repository,
            subject_id=configured["subject"],
            actor=ACTOR,
            consent_scope="presence",
            decision="granted",
        )

    if during:
        original_get = deployment.store.get
        reads = 0

        def get(blob):
            nonlocal reads
            data = original_get(blob)
            if blob.hex == desc["sha256"]:
                reads += 1
                if reads == 2:
                    change()
            return data

        monkeypatch.setattr(deployment.store, "get", get)
    else:
        change()
    assert deployment.as_owner("GET", desc["fetch"]).status_code == 409


def test_lineage_change_during_fetch_refuses(deployment, repository, tmp_path, monkeypatch):
    scene = _scene_in(deployment, repository, tmp_path)
    desc = available(bundle(deployment, scene))[0]["photo_bytes"]
    original_get = deployment.store.get
    reads = 0

    def get(blob):
        nonlocal reads
        data = original_get(blob)
        if blob.hex == desc["sha256"]:
            reads += 1
            if reads == 2:
                repository.connection.execute(
                    "update artifact set needs_repair=true where workspace_id=%s "
                    "and content_sha256=decode(%s,'hex')",
                    (repository.workspace_id, desc["pose_receipt_sha256"]),
                )
        return data

    monkeypatch.setattr(deployment.store, "get", get)
    assert deployment.as_owner("GET", desc["fetch"]).status_code == 409
    assert reads == 2


def test_nonidentity_orientation_is_explicitly_unavailable(deployment, repository, tmp_path):
    # 180 degrees leaves non-square dimensions unchanged, so dimensions alone cannot catch it.
    def oriented(directory, name, **kwargs):
        return write_photo(directory, name, orientation=3, **kwargs)

    with patch("test_world_read_route.write_photo", oriented):
        scene = _scene_in(deployment, repository, tmp_path)
    envelope = bundle(deployment, scene)
    assert all(v["camera"] is not None for v in envelope["bundle"]["views"])
    assert {v["photo_bytes"].get("reason") for v in envelope["bundle"]["views"]} == {
        "pose_orientation_transform_unrecorded"
    }


def test_unregistered_members_and_legacy_bindings_remain_unavailable(
    deployment, repository, tmp_path
):
    from test_scene_reconstruction_pipeline import FakeColmap

    def partial(**kwargs):
        kwargs["registered"] = 2
        return FakeColmap(**kwargs)

    with patch("test_world_read_route.FakeColmap", partial):
        scene = _scene_in(deployment, repository, tmp_path)
    from exulanica.graph.world_read import world_read_bundle

    envelope = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    response = deployment.as_owner("GET", f"/world-read/scenes/{scene}")
    assert response.status_code == 200, response.text
    assert response.json() == envelope
    assert len(envelope["bundle"]["views"]) == 3
    view = next(v for v in envelope["bundle"]["views"] if not v["registered"])
    assert view["camera"] is None and view["exclusion_reason"]
    assert view["photo_bytes"]["reason"] == "view_not_registered_or_calibrated"
    source = next(
        c["source_sha256"]
        for c in envelope["bundle"]["recipient_evidence"]["record"]["captures"]
        if c["capture_id"] == view["capture_id"]
    )
    span = repository.connection.execute(
        "select span_id from evidence_span where workspace_id=%s and blob_sha256=decode(%s,'hex') "
        "and region is null",
        (repository.workspace_id, source),
    ).fetchone()["span_id"]
    path = (
        f"/evidence/{span}/masked?view_scene={scene}&view_capture={view['capture_id']}"
        f"&view_binding={'0' * 64}"
    )
    assert deployment.as_owner("GET", path).status_code == 409
    # Missing exact pose evidence must refuse, without changing any producer or historical receipt.
    from exulanica.graph.world_read_views import descriptor

    evidence = copy.deepcopy(envelope["bundle"]["recipient_evidence"])
    evidence["record"]["pose_receipt"] = {"state": "unavailable", "reason": "legacy"}
    candidate = {**view, "registered": True, "camera": {}}
    result = descriptor(
        repository.connection, repository.workspace_id, scene, candidate, evidence, deployment.store
    )
    assert result["reason"] == "pose_binding_unavailable"


@pytest.mark.parametrize("during", [False, True])
def test_rebuilt_selected_mask_never_rebinds_old_pose(
    deployment, repository, tmp_path, monkeypatch, during
):
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.ingest.privacy import record_person_detection_screening

    scene, configured = _masked_scene(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    desc = next(v["photo_bytes"] for v in available(first) if v["photo_bytes"]["kind"] == "masked")
    assert deployment.as_owner("GET", desc["fetch"]).status_code == 200
    replacement = {}

    def change():
        record_region_edits(
            repository,
            capture_id=configured["capture"],
            actor=ACTOR,
            edits=[
                {
                    "action": "add",
                    "region_key": (b"b" * 32).hex(),
                    "silhouette": {
                        "kind": "polygon",
                        "points": [
                            [500000, 500000],
                            [1000000, 500000],
                            [1000000, 1000000],
                            [500000, 1000000],
                        ],
                    },
                }
            ],
        )
        auth = repository.connection.execute(
            "select authorization_id from capture_reconstruction_authorization "
            "where workspace_id=%s and capture_id=%s order by authorized_at desc limit 1",
            (repository.workspace_id, configured["capture"]),
        ).fetchone()
        detection = record_person_detection_screening(
            repository,
            authorization_id=auth["authorization_id"],
            authorized_by=ACTOR,
            purpose="generated replacement mask",
        )
        outcome = PhotoIngestPipeline(repository, deployment.store).ingest_derivatives(
            configured["capture"], privacy_screening_id=detection.screening_id
        )
        assert outcome.error is None, outcome.error
        mask = repository.current_capture_artifacts(
            capture_ids=[configured["capture"]], kind="masked_source"
        )[configured["capture"]]
        replacement["digest"] = mask.content_sha256.hex()
        assert replacement["digest"] != desc["sha256"]

    if during:
        original_get = deployment.store.get
        reads = 0

        def get(blob):
            nonlocal reads
            data = original_get(blob)
            if blob.hex == desc["sha256"]:
                reads += 1
                if reads == 2:
                    change()
            return data

        monkeypatch.setattr(deployment.store, "get", get)
    else:
        change()
    refused = deployment.as_owner("GET", desc["fetch"], headers={"Range": "bytes=0-19"})
    assert refused.status_code == 409, refused.text
    current = deployment.as_owner("GET", f"/evidence/{desc['span_id']}/masked")
    assert current.status_code == 200, current.text
    assert hashlib.sha256(current.content).hexdigest() == replacement["digest"]
    from exulanica.graph.world_read import world_read_bundle

    changed = world_read_bundle(
        repository.connection, repository.workspace_id, scene, deployment.store
    )
    unavailable = next(
        v["photo_bytes"]
        for v in changed["bundle"]["views"]
        if v["capture_id"] == str(configured["capture"])
    )
    assert unavailable["state"] == "unavailable"
    assert unavailable["reason"] == "viewer_pose_transform_unrecorded"
    assert unavailable["pose_input_sha256"] == desc["sha256"]
    assert unavailable["selected_sha256"] == replacement["digest"]
    assert deployment.as_owner("GET", f"/world-read/scenes/{scene}").status_code == 404
    if target := os.environ.get("WORLD_READ_VIEW_ARTIFACTS"):
        folder = Path(target) / f"replacement-mask-{during}"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "current.image").write_bytes(current.content)
        (folder / "before.json").write_bytes(canonical_json(first))
        (folder / "unavailable-descriptor.json").write_bytes(canonical_json(unavailable))


@pytest.mark.parametrize("damage", ["partial", "invalid_digest", "wrong_binding", "wrong_capture"])
def test_malformed_or_mismatched_fetch_binding_refuses(deployment, repository, tmp_path, damage):
    desc = available(bundle(deployment, _scene_in(deployment, repository, tmp_path)))[0][
        "photo_bytes"
    ]
    path = desc["fetch"]
    if damage == "partial":
        path = path.split("&view_binding=")[0]
    elif damage == "invalid_digest":
        path = path.replace(desc["binding_sha256"], "not-a-digest")
    elif damage == "wrong_binding":
        path = path.replace(desc["binding_sha256"], "0" * 64)
    else:
        path = path.replace(desc["capture_id"], str(uuid.uuid4()))
    response = deployment.as_owner("GET", path)
    assert (
        response.status_code
        == {"partial": 422, "invalid_digest": 422, "wrong_binding": 409, "wrong_capture": 404}[
            damage
        ]
    )


def test_absent_legacy_screening_binding_refuses_actual_routes(deployment, repository, tmp_path):
    scene = _scene_in(deployment, repository, tmp_path)
    first = bundle(deployment, scene)
    view = available(first)[0]
    point = next(
        p
        for p in first["bundle"]["recipient_evidence"]["record"]["point_maps"]
        if p["capture_id"] == view["capture_id"]
    )
    # A generated pre-admission-shaped row, not a migration/backfill of retained data.
    # Reuse the existing legacy-fixture method from test_asset_read_currency. Current
    # producers correctly reject this row; only this local setup transaction emulates
    # pre-admission state. Every actual read runs after normal triggers are restored.
    with repository.connection.transaction():
        repository.connection.execute("set local session_replication_role=replica")
        repository.connection.execute(
            "update artifact set privacy_screening_id=null "
            "where workspace_id=%s and artifact_id=%s",
            (repository.workspace_id, point["artifact_id"]),
        )
    assert repository.connection.execute("show session_replication_role").fetchone()[
        "session_replication_role"
    ] == "origin"
    response = deployment.as_owner("GET", view["photo_bytes"]["fetch"])
    assert response.status_code == 409, response.text
    assert deployment.as_owner("GET", f"/world-read/scenes/{scene}").status_code == 404
