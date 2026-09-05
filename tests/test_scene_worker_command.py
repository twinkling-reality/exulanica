"""The separate pose worker command refuses missing provenance and reports observed outcomes."""

from __future__ import annotations

import io
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

from exulanica.ingest import scene_worker_command


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
