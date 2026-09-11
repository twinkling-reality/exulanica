"""The dedicated derivative-worker process contract, without starting a signal loop."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from exulanica.ingest import worker_command


def test_workspace_configuration_is_explicit_deduplicated_and_validated():
    first, second = uuid.uuid4(), uuid.uuid4()
    resolved = worker_command.parse_workspaces(
        [str(first)], {worker_command.WORKSPACES_ENV: f"{first}, {second}"}
    )
    assert resolved == frozenset({first, second})
    with pytest.raises(ValueError, match="silently drains nothing"):
        worker_command.parse_workspaces([], {})
    with pytest.raises(ValueError, match="UUIDs only"):
        worker_command.parse_workspaces(["all"], {})


def test_startup_failure_is_machine_readable_and_returns_failure():
    output = io.StringIO()
    result = worker_command.main(
        ["--once", "--workspace", str(uuid.uuid4())], environ={}, stream=output
    )
    assert result == 1
    event = json.loads(output.getvalue())
    assert event["component"] == "derivative-worker"
    assert event["event"] == "startup_failed"
    assert event["failure_class"] == "DatabaseNotConfigured"


def test_depth_configuration_is_explicit_and_passes_the_pinned_model_binding(monkeypatch):
    from exulanica.reconstruction import moge

    captured = {}

    class FakeDepth:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(moge, "MoGeDepthModel", FakeDepth)

    assert worker_command._build_depth({}) is None
    depth = worker_command._build_depth(
        {
            worker_command.DEPTH_MODEL_ENV: "moge",
            worker_command.DEPTH_MODEL_ID_ENV: "example/moge-checkpoint",
            worker_command.DEPTH_MODEL_REVISION_ENV: "a" * 40,
            worker_command.DEPTH_DEVICE_ENV: "cuda",
        }
    )

    assert isinstance(depth, FakeDepth)
    assert captured == {
        "model_id": "example/moge-checkpoint",
        "revision": "a" * 40,
        "max_edge_px": 512,
        "device": "cuda",
    }
    with pytest.raises(ValueError, match="must be 'moge' or 'unavailable'"):
        worker_command._build_depth({worker_command.DEPTH_MODEL_ENV: "automatic"})
    with pytest.raises(ValueError, match="full lowercase Git commit"):
        worker_command._build_depth(
            {
                worker_command.DEPTH_MODEL_ENV: "moge",
                worker_command.DEPTH_MODEL_REVISION_ENV: "main",
            }
        )


class _RecordingSegmenter:
    """Stands in for `LocalObjectSegmenter`, which would load SAM 2.1 and torch in this process."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_segmentation_is_off_unless_an_operator_names_the_local_segmenter(monkeypatch):
    from exulanica.ingest.stages import segmentation

    monkeypatch.setattr(segmentation, "LocalObjectSegmenter", _RecordingSegmenter)
    model = worker_command.SEGMENTATION_MODEL_ENV
    device = worker_command.SEGMENTATION_DEVICE_ENV

    assert worker_command._build_segmenter({}) is None
    assert worker_command._build_segmenter({model: " Unavailable "}) is None
    # A device alone turns nothing on: the model switch is the only switch.
    assert worker_command._build_segmenter({device: "cpu"}) is None

    automatic = worker_command._build_segmenter({model: "local"})
    assert isinstance(automatic, _RecordingSegmenter)
    assert automatic.kwargs == {"device": None}
    pinned = worker_command._build_segmenter({model: "LOCAL", device: "cpu"})
    assert pinned.kwargs == {"device": "cpu"}

    with pytest.raises(ValueError, match="must be 'local' or 'unavailable'"):
        worker_command._build_segmenter({model: "sam2"})


def test_the_worker_hands_the_configured_segmenter_to_its_jobs(monkeypatch, tmp_path):
    """The gap this closes: the environment built depth and a detector and never a segmenter."""
    from exulanica.ingest.stages import segmentation

    monkeypatch.setattr(segmentation, "LocalObjectSegmenter", _RecordingSegmenter)

    class Database:
        @classmethod
        def from_env(cls, environ):
            return cls()

        @contextmanager
        def unscoped(self):
            yield None

    built = {}
    monkeypatch.setattr(worker_command, "Database", Database)
    monkeypatch.setattr(worker_command, "verify_schema", lambda database: None)
    monkeypatch.setattr(worker_command, "assert_runtime_role", lambda connection: None)
    monkeypatch.setattr(
        worker_command, "DerivativeWorker", lambda *args, **kwargs: built.update(kwargs)
    )
    args = SimpleNamespace(workspace=[str(uuid.uuid4())], name="segmenting", poll_seconds=2.0)
    environ = {worker_command.DATA_DIR_ENV: str(tmp_path)}

    worker_command._build_worker(args, environ)
    assert built["segmenter"] is None

    worker_command._build_worker(
        args,
        {
            **environ,
            worker_command.SEGMENTATION_MODEL_ENV: "local",
            worker_command.SEGMENTATION_DEVICE_ENV: "mps",
        },
    )
    assert isinstance(built["segmenter"], _RecordingSegmenter)
    assert built["segmenter"].kwargs == {"device": "mps"}


def test_neither_worker_imports_the_native_runtime_the_other_one_loads():
    """pycolmap and torch abort one process on macOS (`pycolmap_executor.py`). The scene worker
    now lifts segments, and its lift imports the segmentation stage's module for two constants,
    so this holds that importing the scene worker still pulls in no torch, no transformers and
    no model, and that the derivative worker, which builds the segmenter, pulls in no pycolmap.
    Each in a child process, because this one's `sys.modules` belongs to the whole suite."""
    probes = {
        "exulanica.ingest.scene_worker_command": ("torch", "transformers"),
        "exulanica.ingest.worker_command": ("pycolmap",),
    }
    for module, forbidden in probes.items():
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                f"import sys, {module}; "
                f"print(sorted(name for name in {forbidden!r} if name in sys.modules))",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert completed.stdout.strip() == "[]", (module, completed.stdout)


def test_once_mode_uses_observed_lifecycle_and_reports_terminal_counts(monkeypatch):
    class FakeWorker:
        name = "worker-a"
        workspace_count = 2

        def __init__(self):
            self.observed = False

        def drain_observed(self):
            self.observed = True
            return [
                SimpleNamespace(failed=1, cancelled=2, unavailable=3),
                SimpleNamespace(failed=0, cancelled=0, unavailable=0),
            ]

    worker = FakeWorker()
    monkeypatch.setattr(worker_command, "_build_worker", lambda args, environ: worker)
    output = io.StringIO()

    assert worker_command.main(["--once"], environ={}, stream=output) == 0
    assert worker.observed
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert events == [
        {
            "component": "derivative-worker",
            "event": "startup",
            "mode": "once",
            "worker": "worker-a",
            "workspaces": 2,
        },
        {
            "cancelled": 2,
            "component": "derivative-worker",
            "event": "stopped",
            "failed": 1,
            "jobs": 2,
            "unavailable": 3,
        },
    ]
