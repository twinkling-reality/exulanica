"""Workspace-owned artifact rows share content, never row identities or access."""

import hashlib
import json
import secrets
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.roles import provision_purge_role, provision_runtime_role
from exulanica.deletion.worker import PurgeWorker
from exulanica.evidence.blob import BlobId
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.privacy import authorize_synthetic_capture, record_synthetic_exemption
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import ARTIFACT_NAMESPACE, artifact_id_for
from exulanica.store.local import LocalContentAddressedStore
from fastapi.testclient import TestClient

from conftest import photo_bytes, scratch_role_database
from test_place_alignment_build import world as world


def legacy_artifact_id(key, *, workspace_id):
    """Emulate the historical writer when creating fixtures, without rewriting stored IDs."""
    return uuid.uuid5(ARTIFACT_NAMESPACE, key)


def test_artifact_identity_requires_workspace_and_preserves_determinism():
    key = hashlib.sha256(b"synthetic stage identity").hexdigest()
    first, second = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(TypeError):
        artifact_id_for(key)
    assert artifact_id_for(key, workspace_id=first) == artifact_id_for(key, workspace_id=first)
    assert artifact_id_for(key, workspace_id=first) != artifact_id_for(key, workspace_id=second)
    assert artifact_id_for(key, workspace_id=first) != legacy_artifact_id(key, workspace_id=first)


@pytest.mark.parametrize("historical_first", [False, True])
def test_identical_uploads_remain_isolated_and_survive_other_workspace_deletion(
    repository, spine_schema, tmp_path, monkeypatch, historical_first
):
    """Both workspaces stay live throughout import, retry, reference checks and purge."""
    _, scratch = spine_schema
    app_role = "exulanica_artifact_identity_app_suite"
    purge_role = "exulanica_artifact_identity_purge_suite"
    provision_runtime_role(repository.connection, role=app_role, password=secrets.token_urlsafe(32))
    provision_purge_role(repository.connection, role=purge_role, password=secrets.token_urlsafe(32))
    database = scratch_role_database(scratch, app_role)
    workspaces = [repository.workspace_id, uuid.uuid4()]
    tokens = [
        "artifact-first-workspace-token-long-enough",
        "artifact-second-workspace-token-long-enough",
    ]
    monkeypatch.setenv(
        "EXULANICA_API_TOKENS",
        json.dumps(
            {
                token: {"workspace_id": str(ws), "actor": str(uuid.uuid4())}
                for token, ws in zip(tokens, workspaces, strict=True)
            }
        ),
    )
    store = LocalContentAddressedStore(tmp_path / "blobs")
    services = Services(
        database=database,
        readonly_database=database,
        store=store,
        tokens=load_token_directory(),
        executor_shares_the_write_role=True,
        model_client=None,
    )
    data = photo_bytes()
    captures, spans, artifacts = [], [], []

    def rows(ws):
        with database.session(ws) as connection:
            return connection.execute(
                "select artifact_id,idempotency_key,content_sha256 from artifact "
                "order by idempotency_key"
            ).fetchall()

    with TestClient(create_app(services, verify=False)) as client:

        def upload(index):
            response = client.post(
                "/intake",
                files=[("files", ("same.jpg", data, "image/jpeg"))],
                headers={"Authorization": f"Bearer {tokens[index]}"},
            )
            assert response.status_code == 202, response.text
            assert response.json()["refused"] == [], response.text
            return response.json()["accepted"][0]

        for index, ws in enumerate(workspaces):
            with monkeypatch.context() as patch:
                if index == 0 and historical_first:
                    patch.setattr("exulanica.ingest.pipeline.artifact_id_for", legacy_artifact_id)
                accepted = upload(index)
                capture_id = uuid.UUID(accepted["capture_id"])
                captures.append(capture_id)
                assert accepted["blob_sha256"] == hashlib.sha256(data).hexdigest()
                with database.session(ws) as connection:
                    repo = IngestRepository(connection, ws)
                    outcome = PhotoIngestPipeline(repo, store).ingest_derivatives(capture_id)
                    assert outcome.error is None, outcome.error
                    authorization = authorize_synthetic_capture(
                        repo,
                        capture_id=capture_id,
                        actor=uuid.uuid4(),
                        generator_manifest={
                            "profile": "exulanica.synthetic-test-corpus/v1",
                            "notice": "SYNTHETIC TEST FIXTURE",
                        },
                        authorization_scope={"purpose": "artifact workspace identity test"},
                    )
                    record_synthetic_exemption(
                        repo, authorization_id=authorization.authorization_id
                    )
                    spans.append(
                        connection.execute("select span_id from evidence_span").fetchone()[
                            "span_id"
                        ]
                    )
            artifacts.append(rows(ws))
            assert artifacts[-1]

        assert captures[0] != captures[1]
        assert [row["idempotency_key"] for row in artifacts[0]] == [
            row["idempotency_key"] for row in artifacts[1]
        ]
        assert [bytes(row["content_sha256"]) for row in artifacts[0]] == [
            bytes(row["content_sha256"]) for row in artifacts[1]
        ]
        assert {row["artifact_id"] for row in artifacts[0]}.isdisjoint(
            row["artifact_id"] for row in artifacts[1]
        )
        if historical_first:
            assert all(
                row["artifact_id"]
                == legacy_artifact_id(row["idempotency_key"], workspace_id=workspaces[0])
                for row in artifacts[0]
            )
        for index, ws in enumerate(workspaces):
            assert uuid.UUID(upload(index)["capture_id"]) == captures[index]
            with database.session(ws) as connection:
                outcome = PhotoIngestPipeline(
                    IngestRepository(connection, ws), store
                ).ingest_derivatives(captures[index])
                assert outcome.error is None, outcome.error
                assert (
                    connection.execute(
                        "select artifact_id from artifact where artifact_id=%s",
                        (artifacts[1 - index][0]["artifact_id"],),
                    ).fetchone()
                    is None
                )
            assert rows(ws) == artifacts[index]
            headers = {"Authorization": f"Bearer {tokens[index]}"}
            own = client.get(f"/evidence/{spans[index]}", headers=headers)
            assert own.status_code == 200, own.text
            assert own.content == data
            assert client.get(f"/evidence/{spans[1 - index]}", headers=headers).status_code == 404

        with database.session(workspaces[0]) as connection:
            IngestRepository(connection, workspaces[0]).insert_tombstone(
                scope="capture",
                capture_id=captures[0],
                requested_by=uuid.uuid4(),
                reason="delete the first synthetic workspace photograph",
            )
        result = PurgeWorker(
            scratch_role_database(scratch, purge_role),
            store,
            frozenset({workspaces[0]}),
            name="artifact-identity-purge",
        ).drain()
        assert result.failed == 0 and result.errors == [], result
        assert result.skipped >= 1
        assert store.get(BlobId(hashlib.sha256(data).digest())) == data
        assert rows(workspaces[1]) == artifacts[1]
        for row in artifacts[1]:
            assert store.exists(BlobId(bytes(row["content_sha256"])))
        survivor = client.get(
            f"/evidence/{spans[1]}", headers={"Authorization": f"Bearer {tokens[1]}"}
        )
        assert survivor.status_code == 200, survivor.text
        assert survivor.content == data


def test_scene_segments_retry_reuses_historical_id(repository, tmp_path, monkeypatch):
    from exulanica.ingest import scene_segments

    from test_scene_segments import SceneSegmenter, _published, _read, _segment_members

    store, captures, _, scene_id = _published(repository, tmp_path, "legacy-segments")
    _segment_members(repository, store, captures, SceneSegmenter())
    with monkeypatch.context() as patch:
        patch.setattr("exulanica.ingest.stages.artifact_id_for", legacy_artifact_id)
        original = scene_segments.publish_scene_segments(repository, store, scene_id)
    assert original["action"] == "written"
    retried = scene_segments.publish_scene_segments(repository, store, scene_id)
    assert retried["action"] == "already-present"
    assert retried["artifact_id"] == original["artifact_id"]
    assert retried["segments_sha256"] == original["segments_sha256"]
    read = _read(repository, store, scene_id)
    assert read.state == "available"
    rows = repository.connection.execute(
        "select artifact_id from artifact where workspace_id=%s and scene_id=%s and kind=%s",
        (repository.workspace_id, scene_id, scene_segments.SCENE_SEGMENTS_KIND),
    ).fetchall()
    assert rows == [{"artifact_id": uuid.UUID(original["artifact_id"])}]


def test_place_alignment_retry_preserves_historical_receipt_and_version_links(
    repository, tmp_path, monkeypatch, world
):
    from test_place_alignment_build import (
        _ANCHOR_FROM_SECOND,
        _JOINT_FROM_ANCHOR,
        JointColmap,
        _build,
        _compose,
    )

    store, place_id, anchor, second = world
    executor = JointColmap(
        {
            **anchor.joint(_JOINT_FROM_ANCHOR),
            **second.joint(_compose(_JOINT_FROM_ANCHOR, _ANCHOR_FROM_SECOND)),
        }
    )
    with monkeypatch.context() as patch:
        patch.setattr("exulanica.ingest.place_alignment.artifact_id_for", legacy_artifact_id)
        original = _build(
            repository,
            store,
            tmp_path,
            place_id=place_id,
            candidate=second.scene_id,
            against=anchor.scene_id,
            executor=executor,
        )
    assert original.accepted
    calls = list(executor.calls)
    retried = _build(
        repository,
        store,
        tmp_path,
        place_id=place_id,
        candidate=second.scene_id,
        against=anchor.scene_id,
        executor=executor,
    )
    assert retried.reused and retried.accepted
    assert retried.receipt_artifact_id == original.receipt_artifact_id
    assert retried.alignment_id == original.alignment_id
    assert executor.calls == calls
    links = repository.connection.execute(
        "select a.receipt_artifact_id,a.alignment_id from place_alignment a "
        "join place_version v on v.admitted_by_alignment_id=a.alignment_id "
        "where a.workspace_id=%s and a.place_id=%s",
        (repository.workspace_id, place_id),
    ).fetchall()
    assert links == [
        {"receipt_artifact_id": original.receipt_artifact_id, "alignment_id": original.alignment_id}
    ]
