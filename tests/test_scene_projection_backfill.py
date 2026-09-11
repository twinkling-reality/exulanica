"""The one-shot that gives an already published scene the projection it was published without.

The scene worker writes a projection from now on. Every scene published before it did has none,
and its first graph read in every fresh process still rebuilds the placement from every point map.
These tests pin what the backfill writes, that it writes it once, and the two refusals that keep it
from making a scene slower than it found it.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from exulanica.evidence.blob import BlobId
from exulanica.graph import read_snapshot
from exulanica.graph.asset_read_policy import clear_scene_inputs_memo
from exulanica.graph.reconstruction_scenes import clear_placement_memo
from exulanica.ingest.scene_projection import (
    SCENE_PROJECTION_KIND,
    validate_scene_projection,
)
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.ingest.stages import (
    artifact_id_for,
    idempotency_key,
    input_digest_of,
    stage,
)

from test_scene_reconstruction_pipeline import (
    FakeColmap,
    _numeric_point_map,
    _processor,
    _queued_scene,
)

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "backfill_scene_projections.py"
spec = importlib.util.spec_from_file_location("backfill_scene_projections", MODULE)
assert spec is not None and spec.loader is not None
backfill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backfill)


def _published(repository, tmp_path, worker):
    clear_placement_memo()
    clear_scene_inputs_memo()
    store, captures, point_artifacts, job_id = _queued_scene(repository, tmp_path)
    claimed = repository.claim_reconstruction_scene(worker=worker, lease_seconds=60)
    assert claimed is not None
    outcome = _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claimed)
    assert outcome.status == "succeeded"
    return store, captures, point_artifacts, job_id, outcome.scene_id


def _rebuild(repository, store, tmp_path, captures, point_artifacts):
    """Supersede one member's point map and publish the scene again. Returns the new job id.

    The same sequence as
    `test_a_new_point_map_build_supersedes_the_displayed_build_without_rewriting_history`, which is
    the only way to move `reconstruction_scene.current_job_id`: it is append-only and advances.
    """
    capture = repository.capture(captures[0])
    assert capture is not None
    spec = stage("depth")
    input_digest = input_digest_of([])
    key = idempotency_key(
        capture.blob_id, spec, input_digest, binding={"model_id": "test/depth-model-v2"}
    )
    replacement_id = artifact_id_for(key)
    replacement = store.put_bytes(_numeric_point_map(0, color=129))
    privacy = repository.connection.execute(
        "select privacy_screening_id from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[0]),
    ).fetchone()
    assert privacy is not None
    repository.insert_artifact(
        artifact_id=replacement_id,
        kind=spec.output_kind,
        source_blob=capture.blob_id,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=input_digest,
        idempotency_key=key,
        content_sha256=replacement.blob_id.digest,
        storage_key=store.key_for(replacement.blob_id),
        byte_size=replacement.byte_size,
        produced_by_event=None,
        privacy_screening_id=privacy["privacy_screening_id"],
    )
    repository.connection.execute(
        "update artifact set superseded_by=%s where workspace_id=%s and artifact_id=%s",
        (replacement_id, repository.workspace_id, point_artifacts[0]),
    )
    report = run_scene_grouping(repository)
    assert len(report.reconstruction_jobs) == 1
    claim = repository.claim_reconstruction_scene(worker="backfill-rebuild", lease_seconds=60)
    assert claim is not None
    assert (
        _processor(repository, store, tmp_path, FakeColmap(registered=3)).process(claim).status
        == "succeeded"
    )
    return report.reconstruction_jobs[0]


def _drop_projection(repository, store, scene_id):
    """Take the scene back to how it looked before the projection stage existed.

    The rows are removed rather than marked purged, because a scene published by the old worker
    never had one at all, and `purged_at` would be a different thing that the reader also skips.
    """
    rows = repository.connection.execute(
        "select artifact_id,content_sha256 from artifact where workspace_id=%s and scene_id=%s "
        "and kind=%s",
        (repository.workspace_id, scene_id, SCENE_PROJECTION_KIND),
    ).fetchall()
    for row in rows:
        repository.connection.execute(
            "delete from pipeline_event where output_artifact_ids @> array[%s]::uuid[]",
            (row["artifact_id"],),
        )
        repository.connection.execute(
            "delete from artifact where workspace_id=%s and artifact_id=%s",
            (repository.workspace_id, row["artifact_id"]),
        )
        path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
        if path.is_file():
            path.chmod(0o644)
            path.unlink()
    return len(rows)


def _rows(repository, scene_id):
    return repository.connection.execute(
        "select artifact_id,content_sha256,byte_size from artifact where workspace_id=%s "
        "and scene_id=%s and kind=%s",
        (repository.workspace_id, scene_id, SCENE_PROJECTION_KIND),
    ).fetchall()


def _scenes(repository, store):
    clear_placement_memo()
    clear_scene_inputs_memo()
    return read_snapshot(repository.connection, repository.workspace_id, store)


def _one(repository, store, scene_id):
    row = repository.connection.execute(
        backfill._SCENES, (repository.workspace_id, scene_id, scene_id)
    ).fetchone()
    assert row is not None
    return backfill._project_one(repository, store, row)


def test_the_backfill_writes_the_projection_a_published_scene_was_published_without(
    repository, tmp_path
):
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-write"
    )
    before = _scenes(repository, store).reconstruction_scenes[0]
    assert _drop_projection(repository, store, scene_id) == 1
    assert _rows(repository, scene_id) == []
    without = _scenes(repository, store).reconstruction_scenes[0]
    assert without.model_dump_json() == before.model_dump_json()

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "written", outcome
    assert outcome["member_count"] == 3
    assert outcome["placed_member_count"] == 3
    rows = _rows(repository, scene_id)
    assert len(rows) == 1
    assert bytes(rows[0]["content_sha256"]).hex() == outcome["projection_sha256"]
    # The graph serves it, and serves exactly what it served without it.
    assert (
        _scenes(repository, store).reconstruction_scenes[0].model_dump_json()
        == before.model_dump_json()
    )


def test_the_backfill_writes_what_the_worker_would_have_written(repository, tmp_path):
    """Same stage, same deterministic artifact id, same bytes.

    Otherwise a backfilled scene and a freshly published one would be two formats, and the reader
    would be proving two things rather than one.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-identical"
    )
    published = _rows(repository, scene_id)[0]
    _drop_projection(repository, store, scene_id)

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "written"
    assert uuid.UUID(outcome["artifact_id"]) == published["artifact_id"]
    assert outcome["projection_sha256"] == bytes(published["content_sha256"]).hex()
    assert outcome["byte_size"] == published["byte_size"]


def test_the_backfill_is_idempotent(repository, tmp_path):
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-idempotent"
    )
    _drop_projection(repository, store, scene_id)

    first = _one(repository, store, scene_id)
    second = _one(repository, store, scene_id)

    assert first["action"] == "written"
    assert second["action"] == "already-present"
    assert second["projection_sha256"] == first["projection_sha256"]
    assert len(_rows(repository, scene_id)) == 1


def test_the_backfill_never_offers_a_superseded_build(repository, tmp_path):
    """The refusal that keeps it from making a scene slower than it found it.

    Nothing in `exulanica.ingest` ever sets `artifact.superseded_by` on a scene artifact, so every
    projection a scene has had stays live and the graph offers the newest few by `created_at`. A
    projection written now for a build that has been superseded would be the newest and would fail
    every binding. The query selects through `reconstruction_scene.current_job_id`, so a superseded
    build is not offered at all rather than offered and skipped downstream.

    Staged as a real rebuild, because both scene tables are append-only and the pointer can only
    advance.
    """
    store, captures, point_artifacts, first_job_id, scene_id = _published(
        repository, tmp_path, "backfill-superseded"
    )
    assert _one(repository, store, scene_id)["job_id"] == str(first_job_id)
    first_projection = _rows(repository, scene_id)[0]

    second_job_id = _rebuild(repository, store, tmp_path, captures, point_artifacts)
    assert second_job_id != first_job_id

    offered = _one(repository, store, scene_id)
    assert offered["job_id"] == str(second_job_id), (
        "the backfill must project the scene's current build, never a superseded one"
    )
    assert offered["action"] == "already-present", "the rebuild published its own projection"

    # The hazard this refusal exists for is real: the superseded build's projection is still live.
    live = {row["artifact_id"] for row in _rows(repository, scene_id)}
    assert first_projection["artifact_id"] in live
    assert len(live) == 2


def test_the_backfill_refuses_a_scene_whose_point_map_bytes_are_gone(repository, tmp_path):
    """A projection transcribes a validated placement. It cannot validate one it cannot read."""
    store, _captures, point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-missing"
    )
    _drop_projection(repository, store, scene_id)
    row = repository.connection.execute(
        "select content_sha256 from artifact where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, point_artifacts[1]),
    ).fetchone()
    path = store.root / store.key_for(BlobId(bytes(row["content_sha256"])))
    path.chmod(0o644)
    path.unlink()

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "skipped"
    assert "missing its bytes" in outcome["reason"]
    assert _rows(repository, scene_id) == []


def test_what_the_backfill_writes_validates_against_the_scene_it_names(repository, tmp_path):
    store, captures, point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-validates"
    )
    _drop_projection(repository, store, scene_id)
    outcome = _one(repository, store, scene_id)

    data = store.get(BlobId.from_hex(outcome["projection_sha256"]))
    payload = json.loads(data)["projection"]
    projection = validate_scene_projection(
        data,
        expected_scene_ref=str(scene_id),
        pose_receipt_sha256=outcome["pose_receipt_sha256"],
        placement_receipt_sha256=outcome["placement_receipt_sha256"],
        gate_receipt_sha256=outcome["gate_receipt_sha256"],
        member_capture_refs=[str(item) for item in captures],
        point_map_inputs=[
            (item["capture_ref"], item["artifact_ref"], item["content_sha256"])
            for item in payload["bindings"]["point_map_inputs"]
        ],
    )
    assert projection.scene_ref == str(scene_id)
    assert {member.capture_ref for member in projection.placed} == {str(item) for item in captures}
    assert [item[1] for item in projection.point_map_inputs] == [
        str(item) for item in point_artifacts
    ]

    with pytest.raises(ValueError, match="another member list"):
        validate_scene_projection(
            data,
            expected_scene_ref=str(scene_id),
            pose_receipt_sha256=outcome["pose_receipt_sha256"],
            placement_receipt_sha256=outcome["placement_receipt_sha256"],
            gate_receipt_sha256=outcome["gate_receipt_sha256"],
            member_capture_refs=[str(captures[0])],
            point_map_inputs=[
                (item["capture_ref"], item["artifact_ref"], item["content_sha256"])
                for item in payload["bindings"]["point_map_inputs"]
            ],
        )
