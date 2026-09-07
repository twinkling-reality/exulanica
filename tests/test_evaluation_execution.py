"""Execution provenance is read from real ledger rows and never estimated."""

from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

from exulanica.corpus.__main__ import main as corpus_main
from exulanica.db.session import Database
from exulanica.evaluation.cli import main as evaluation_main
from exulanica.evaluation.execution import execution_snapshot
from exulanica.evaluation.provenance import verify_archive
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.repository import IngestRepository
from exulanica.store.local import LocalContentAddressedStore

from conftest import CountingVisionModel, ingest_observed, write_photo


def test_execution_snapshot_carries_actual_runs_cost_timing_attempts_and_reuse(
    tmp_path: Path, photo_dir: Path, repository, workspace_id
):
    first = write_photo(photo_dir, "first.jpg")
    second = write_photo(photo_dir, "second.jpg", size=(120, 90))
    sources = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (first, second)]
    model = CountingVisionModel()
    pipeline = PhotoIngestPipeline(
        repository,
        LocalContentAddressedStore(tmp_path / "blobs"),
        vision=model,
    )
    # Twice over the same two photographs, because the second pass is what produces the reuse
    # events asserted below. One call per photograph rather than ingest_directory, because the
    # vision stage now needs a screening receipt keyed to a capture that does not exist until
    # intake has committed, and this test reads what the model call recorded.
    for _ in range(2):
        for path in (first, second):
            ingest_observed(pipeline, repository, path)

    snapshot = execution_snapshot(repository.connection, workspace_id, sources)
    assert snapshot["source_coverage"]["complete"] is True
    # Two passes over two photographs, each recorded as an intake run and a derivatives run.
    assert snapshot["summary"]["runs"] == 8
    assert snapshot["summary"]["reuse_events"] == 4
    assert snapshot["summary"]["duration_ms"]["observations"] >= 6
    assert snapshot["summary"]["cost"]["totals"]["input_tokens"] == "1544"
    assert snapshot["summary"]["cost"]["totals"]["output_tokens"] == "420"
    assert snapshot["summary"]["cost"]["totals"]["usd_estimate"] == "0.00097560"
    assert snapshot["summary"]["cost"]["totals"]["gpu_seconds"] is None
    assert snapshot["summary"]["models_answered"] == [
        {
            "endpoint": "test",
            "model_id": "MiniMaxAI/MiniMax-M3",
            "provider": "test",
        }
    ]
    assert snapshot["summary"]["model_ids_tried"] == ["MiniMaxAI/MiniMax-M3"]
    assert snapshot["summary"]["model_attempt_provenance_complete"] is True
    model_events = [
        event for event in snapshot["pipeline_events"] if event["model_ref"] is not None
    ]
    assert len(model_events) == 2
    assert all(event["models_tried"] == ["MiniMaxAI/MiniMax-M3"] for event in model_events)
    assert len(snapshot["stage_definitions"]) >= 5
    # The test harness applies SQL directly and records no schema_migrations rows. The snapshot
    # preserves that absence instead of filling it from the current package.
    assert snapshot["applied_migrations"] == []
    assert all(
        "host" not in event and "error_message" not in event
        for event in snapshot["pipeline_events"]
    )


def test_execution_snapshot_names_a_source_that_was_never_run(repository, workspace_id):
    absent = "ab" * 32
    snapshot = execution_snapshot(repository.connection, workspace_id, [absent])
    assert snapshot["source_coverage"] == {
        "declared": [absent],
        "with_pipeline_run": [],
        "missing_pipeline_run": [absent],
        "complete": False,
    }
    assert snapshot["summary"]["runs"] == 0


def test_cli_creates_and_reverifies_a_complete_legacy_archive(
    tmp_path: Path, cli_database, monkeypatch
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    corpus_main(["--out", str(corpus), "--frames-per-trip", "3"], stream=io.StringIO())
    data = tmp_path / "data"
    workspace = uuid.uuid4()
    database = Database.from_env()
    with database.session(workspace) as connection:
        repository = IngestRepository(connection, workspace)
        PhotoIngestPipeline(
            repository,
            LocalContentAddressedStore(data / "blobs"),
            vision=CountingVisionModel(),
        ).ingest_directory(corpus)

    # repository_snapshot itself has a real-Git test. This integration test supplies a frozen
    # state because the source tree is necessarily dirty while the new implementation is tested.
    monkeypatch.setattr(
        "exulanica.evaluation.cli.repository_snapshot",
        lambda _path: {"commit": "1" * 40, "tree": "2" * 40, "dirty": False},
    )
    archives = tmp_path / "archives"
    archives.mkdir()
    output = io.StringIO()
    assert (
        evaluation_main(
            [
                "run",
                "--corpus",
                str(corpus),
                "--workspace",
                str(workspace),
                "--data-dir",
                str(data),
                "--archive-parent",
                str(archives),
                "--repository",
                str(tmp_path),
            ],
            output,
        )
        == 0
    )
    archive = next(archives.iterdir())
    receipt = verify_archive(archive)
    assert receipt.root_sha256 in output.getvalue()
    assert (archive / "snapshots/database-execution.json").is_file()
