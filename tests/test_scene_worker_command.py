"""The separate pose worker command refuses missing provenance and reports observed outcomes."""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from exulanica.ingest import scene_worker_command
from exulanica.ingest.scene_worker import SceneReconstructionWorker


def test_startup_refuses_to_guess_a_database_or_pose_provenance():
    output = io.StringIO()
    assert scene_worker_command.main(
        ["--once", "--workspace", str(uuid.uuid4())], environ={}, stream=output
    ) == 1
    event = json.loads(output.getvalue())
    assert event["component"] == "scene-worker"
    assert event["event"] == "startup_failed"
    assert event["failure_class"] == "DatabaseNotConfigured"


def test_worker_makes_a_configured_relative_data_directory_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    configured = Path("campaign/data")

    resolved = scene_worker_command._worker_data_directory(
        {scene_worker_command.env_name("DATA_DIR"): str(configured)}
    )

    assert resolved == tmp_path / configured
    assert resolved.is_absolute()


def test_once_mode_sweeps_scratch_and_reports_scene_outcomes(monkeypatch):
    class FakeWorker:
        name = "pose-a"
        job_ids = None

        def cleanup_abandoned(self):
            return ("workspace/job",)

        def drain_observed(self):
            return [
                SimpleNamespace(status="succeeded"),
                SimpleNamespace(status="cancelled"),
            ]

    monkeypatch.setattr(scene_worker_command, "_build", lambda args, environment: FakeWorker())
    output = io.StringIO()

    assert scene_worker_command.main(["--once"], environ={}, stream=output) == 0

    assert [json.loads(line) for line in output.getvalue().splitlines()] == [
        {
            "component": "scene-worker",
            "event": "startup",
            "removed_scratch": 1,
            "worker": "pose-a",
        },
        {
            "cancelled": 1,
            "component": "scene-worker",
            "event": "stopped",
            "failed": 0,
            "jobs": 2,
            "succeeded": 1,
        },
    ]


def test_job_scope_comes_from_flags_and_environment_and_refuses_non_uuids():
    first, second = uuid.uuid4(), uuid.uuid4()

    assert scene_worker_command.parse_job_ids([], {}) is None
    assert scene_worker_command.parse_job_ids(
        [str(first)], {scene_worker_command.JOB_IDS_ENV: f"{second}, "}
    ) == frozenset({first, second})
    with pytest.raises(ValueError, match="UUIDs only"):
        scene_worker_command.parse_job_ids(["not-a-job"], {})


def test_a_scoped_worker_reports_its_jobs_at_startup_and_refuses_an_empty_scope(monkeypatch):
    job = uuid.uuid4()

    class FakeWorker:
        name = "rented-gpu"
        job_ids = frozenset({job})

        def cleanup_abandoned(self):
            return ()

        def drain_observed(self):
            return []

    monkeypatch.setattr(scene_worker_command, "_build", lambda args, environment: FakeWorker())
    output = io.StringIO()
    assert scene_worker_command.main(["--once", "--job", str(job)], environ={}, stream=output) == 0
    startup = json.loads(output.getvalue().splitlines()[0])
    assert startup["job_ids"] == [str(job)]

    with pytest.raises(ValueError, match="at least one job id"):
        SceneReconstructionWorker(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            Path("scratch"),
            frozenset({uuid.uuid4()}),
            name="scoped",
            code_revision="0" * 40,
            execution_image="image@sha256:" + "0" * 64,
            job_ids=frozenset(),
        )
