"""The one-shot that gives an already published scene the projection it was published without.

The scene worker writes a projection from now on. Every scene published before it did has none,
and its first graph read in every fresh process still rebuilds the placement from every point map.
These tests pin what the backfill writes, that it writes it once, and the two refusals that keep it
from making a scene slower than it found it. The last group pins what it does with a projection that
can no longer answer: purged, flagged, or missing its bytes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import uuid
from pathlib import Path

import pytest
from exulanica.errors import TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.graph import read_snapshot
from exulanica.graph.asset_read_policy import clear_scene_inputs_memo
from exulanica.graph.reconstruction_scenes import clear_placement_memo
from exulanica.ingest.scene_projection import (
    SCENE_PROJECTION_KIND,
    SCENE_PROJECTION_STAGE,
    projection_identity_key,
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
    replacement_id = artifact_id_for(key, workspace_id=repository.workspace_id)
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
    """Every projection row the scene has, purged or not, oldest first."""
    return repository.connection.execute(
        "select artifact_id,content_sha256,byte_size,idempotency_key,storage_key,purged_at,"
        "needs_repair from artifact where workspace_id=%s and scene_id=%s and kind=%s "
        "order by created_at,artifact_id",
        (repository.workspace_id, scene_id, SCENE_PROJECTION_KIND),
    ).fetchall()


def _unlink(store, content_sha256):
    path = store.root / store.key_for(BlobId(bytes(content_sha256)))
    path.chmod(0o644)
    path.unlink()


def _purge(repository, store, row):
    """Purge one row the way the deletion queue does, in its order.

    Bytes destroyed first, then the row marked with `storage_key` cleared in the same statement,
    which is `mark_purged` in `exulanica/deletion/queue.py`.
    """
    _unlink(store, row["content_sha256"])
    repository.connection.execute(
        "update artifact set purged_at=now(),storage_key=null "
        "where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, row["artifact_id"]),
    )


def _served_without_rebuilding(repository, store, monkeypatch):
    """The scene as the graph serves it with the rebuild made impossible.

    The same proof `test_a_cold_graph_read_serves_the_projection_without_rebuilding_the_placement`
    uses: if the read still produces the scene, a projection answered it. If no projection can,
    the rebuild it falls back to raises instead.
    """

    def refuse(*args, **kwargs):
        raise AssertionError("the graph rebuilt the placement instead of reading a projection")

    with monkeypatch.context() as patch:
        patch.setattr("exulanica.graph.reconstruction_scenes.validate_placement_record", refuse)
        patch.setattr("exulanica.graph.reconstruction_scenes.recovered_camera_records", refuse)
        return _scenes(repository, store).reconstruction_scenes[0]


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


# ---------------------------------------------------------------------------------------
# A projection that can no longer answer. Observed 2026-09-11: three purged projection rows whose
# bytes were gone still held their ids, `insert_scene_artifact` is `on conflict do nothing`, the
# backfill refused with "an existing projection disagrees", and the scene rebuilt its placement on
# every cold read with nothing in the response saying so.
# ---------------------------------------------------------------------------------------


def test_the_backfill_replaces_a_purged_projection_under_the_next_generation(
    repository, tmp_path, monkeypatch
):
    """The observed failure, and the purge left exactly as the purger wrote it."""
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-purged"
    )
    before = _served_without_rebuilding(repository, store, monkeypatch)
    [published] = _rows(repository, scene_id)
    _purge(repository, store, published)
    with pytest.raises(AssertionError, match="rebuilt the placement"):
        _served_without_rebuilding(repository, store, monkeypatch)

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "written", outcome
    assert outcome["generation"] == 1
    assert outcome["passed_over"] == [
        {"generation": 0, "artifact_id": str(published["artifact_id"]), "state": "purged"}
    ]
    purged, replacement = _rows(repository, scene_id)
    # The purged row is the record that its bytes were destroyed, and it still says so: same id,
    # same content digest, still purged, still pointing at no object.
    assert purged["artifact_id"] == published["artifact_id"]
    assert purged["content_sha256"] == published["content_sha256"]
    assert purged["purged_at"] is not None
    assert purged["storage_key"] is None
    # The replacement is a new identity, not the old one reused, and carries the same bytes
    # because the stage is deterministic.
    assert replacement["idempotency_key"] == projection_identity_key(
        published["idempotency_key"], 1
    )
    assert replacement["artifact_id"] == artifact_id_for(
        replacement["idempotency_key"], workspace_id=repository.workspace_id
    )
    assert replacement["artifact_id"] != published["artifact_id"]
    assert uuid.UUID(outcome["artifact_id"]) == replacement["artifact_id"]
    assert replacement["content_sha256"] == published["content_sha256"]
    assert replacement["purged_at"] is None
    # And the fast path is back, serving exactly what it served before the purge.
    after = _served_without_rebuilding(repository, store, monkeypatch)
    assert after.model_dump_json() == before.model_dump_json()

    again = _one(repository, store, scene_id)
    assert again["action"] == "already-present"
    assert again["generation"] == 1
    assert len(_rows(repository, scene_id)) == 2


@pytest.mark.parametrize("state", ["needs_repair", "no_content"])
def test_the_backfill_passes_over_every_projection_the_graph_would_not_offer(
    repository, tmp_path, monkeypatch, state
):
    """Spent means what the reader's candidate query says, not just purged.

    `needs_repair` is how the pipeline records bytes that are gone and cannot be reproduced, and
    it is what an operator sets on a projection the backfill refused, after finding out why. A row
    recording no content names nothing to heal. Neither is ever offered to a reader, so neither
    may hold the scene's fast path hostage, and neither is rewritten on the way past.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, f"backfill-{state}"
    )
    before = _served_without_rebuilding(repository, store, monkeypatch)
    [published] = _rows(repository, scene_id)
    _unlink(store, published["content_sha256"])
    change = (
        "needs_repair=true"
        if state == "needs_repair"
        else "content_sha256=null,byte_size=null,storage_key=null"
    )
    repository.connection.execute(
        f"update artifact set {change} where workspace_id=%s and artifact_id=%s",
        (repository.workspace_id, published["artifact_id"]),
    )
    spent_before = _rows(repository, scene_id)

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "written", outcome
    assert outcome["generation"] == 1
    assert outcome["passed_over"] == [
        {"generation": 0, "artifact_id": str(published["artifact_id"]), "state": state}
    ]
    spent, replacement = _rows(repository, scene_id)
    assert spent == spent_before[0]
    assert replacement["idempotency_key"] == projection_identity_key(
        published["idempotency_key"], 1
    )
    after = _served_without_rebuilding(repository, store, monkeypatch)
    assert after.model_dump_json() == before.model_dump_json()


def test_the_backfill_heals_a_live_projection_whose_bytes_are_gone(
    repository, tmp_path, monkeypatch
):
    """Missing bytes the receipts reproduce are written back under the same identity.

    What a run killed between the row commit and the byte flush leaves behind. The row is live and
    names exactly the content the receipts produce, so nothing about its identity is wrong and no
    new generation is taken: the object is put back where the row already points.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-bytes-gone"
    )
    before = _served_without_rebuilding(repository, store, monkeypatch)
    [published] = _rows(repository, scene_id)
    _unlink(store, published["content_sha256"])
    with pytest.raises(AssertionError, match="rebuilt the placement"):
        _served_without_rebuilding(repository, store, monkeypatch)

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "already-present", outcome
    assert outcome["repaired_missing_bytes"] is True
    assert outcome["generation"] == 0
    assert "passed_over" not in outcome
    assert uuid.UUID(outcome["artifact_id"]) == published["artifact_id"]
    assert _rows(repository, scene_id) == [published]
    assert store.exists(BlobId(bytes(published["content_sha256"])))
    after = _served_without_rebuilding(repository, store, monkeypatch)
    assert after.model_dump_json() == before.model_dump_json()


def test_the_backfill_still_refuses_a_live_projection_its_receipts_do_not_reproduce(
    repository, tmp_path
):
    """The genuine disagreement, which moving to the next generation must not paper over.

    The row is live, unflagged and names other content under the same identity, so the stage has
    disagreed with itself and writing past it would absorb that. Its bytes are absent here because
    a live row whose bytes are present is answered as already present without recomputing, which
    is what keeps a run resumable; absence is what makes the backfill recompute and compare.
    """
    store, _captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-disagrees"
    )
    [published] = _rows(repository, scene_id)
    other = BlobId(hashlib.sha256(b"a projection this stage never produced").digest())
    assert not store.exists(other)
    _unlink(store, published["content_sha256"])
    repository.connection.execute(
        "update artifact set content_sha256=%s,storage_key=%s "
        "where workspace_id=%s and artifact_id=%s",
        (other.digest, store.key_for(other), repository.workspace_id, published["artifact_id"]),
    )
    [disagreeing] = _rows(repository, scene_id)

    outcome = _one(repository, store, scene_id)

    assert outcome["action"] == "refused", outcome
    assert "disagrees" in outcome["reason"]
    assert outcome["generation"] == 0
    assert "passed_over" not in outcome
    # Nothing written, nothing flagged, nothing moved past: the row is exactly as it was found.
    assert _rows(repository, scene_id) == [disagreeing]
    assert not store.exists(BlobId(bytes(published["content_sha256"])))


def test_a_projection_a_deletion_purged_is_never_written_back(repository, tmp_path):
    """Passing over a purged row must not become a way round the deletion that purged it.

    A deletion that purges a scene's projection reaches the scene, so the backfill does not select
    it, a run that selected it before the deletion landed is skipped, and the database refuses the
    next generation outright, exactly as it refuses the first.
    """
    store, captures, _point_artifacts, _job_id, scene_id = _published(
        repository, tmp_path, "backfill-deleted"
    )
    selected_before = repository.connection.execute(
        backfill._SCENES, (repository.workspace_id, scene_id, scene_id)
    ).fetchone()
    assert selected_before is not None
    [published] = _rows(repository, scene_id)
    repository.insert_tombstone(
        scope="capture",
        capture_id=captures[2],
        requested_by=uuid.uuid4(),
        reason="delete one member of a projected scene",
    )
    _purge(repository, store, published)

    assert (
        repository.connection.execute(
            backfill._SCENES, (repository.workspace_id, scene_id, scene_id)
        ).fetchone()
        is None
    )
    outcome = backfill._project_one(repository, store, selected_before)
    assert outcome["action"] == "skipped", outcome
    [still_purged] = _rows(repository, scene_id)
    assert still_purged["purged_at"] is not None
    assert not store.exists(BlobId(bytes(published["content_sha256"])))

    spec = stage(SCENE_PROJECTION_STAGE)
    next_key = projection_identity_key(published["idempotency_key"], 1)
    with pytest.raises(TombstonedError):
        repository.insert_scene_artifact(
            artifact_id=artifact_id_for(next_key, workspace_id=repository.workspace_id),
            kind=spec.output_kind,
            scene_id=scene_id,
            stage_key=spec.key,
            stage_version=spec.version,
            params_digest=spec.params_digest,
            input_digest=input_digest_of([]),
            idempotency_key=next_key,
            content_sha256=bytes(published["content_sha256"]),
            storage_key=store.key_for(BlobId(bytes(published["content_sha256"]))),
            byte_size=published["byte_size"],
            produced_by_event=None,
        )
    assert _rows(repository, scene_id) == [still_purged]


def test_a_projection_identity_generation_is_the_base_key_at_zero_and_distinct_after():
    base = hashlib.sha256(b"a scene artifact key").hexdigest()
    assert projection_identity_key(base, 0) == base
    generations = [projection_identity_key(base, generation) for generation in range(5)]
    assert len(set(generations)) == 5
    assert all(len(key) == 64 for key in generations)
    # A generation of one key is not a generation of another.
    other = hashlib.sha256(b"another scene artifact key").hexdigest()
    assert projection_identity_key(other, 1) not in generations
    for bad in (-1, True, 1.0):
        with pytest.raises(ValueError, match="non-negative integer"):
            projection_identity_key(base, bad)
    with pytest.raises(ValueError, match="SHA-256"):
        projection_identity_key("not a key", 1)


@pytest.mark.parametrize("missing_bytes", [False, True])
def test_backfill_reuses_historical_projection_id(repository, tmp_path, monkeypatch, missing_bytes):
    from test_artifact_workspace_identity import legacy_artifact_id

    with monkeypatch.context() as patch:
        patch.setattr("exulanica.ingest.scene_reconstruction.artifact_id_for", legacy_artifact_id)
        store, _, _, _, scene_id = _published(repository, tmp_path, "legacy-projection")
    before = _rows(repository, scene_id)
    assert len(before) == 1
    original = before[0]
    assert original["artifact_id"] == legacy_artifact_id(
        original["idempotency_key"], workspace_id=repository.workspace_id
    )
    if missing_bytes:
        _unlink(store, original["content_sha256"])
    _one(repository, store, scene_id)
    assert _rows(repository, scene_id) == before
    assert store.exists(BlobId(bytes(original["content_sha256"])))
    assert _served_without_rebuilding(repository, store, monkeypatch).scene_id == scene_id
