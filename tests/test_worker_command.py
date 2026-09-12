"""The dedicated derivative-worker process contract, without starting a signal loop."""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from exulanica.ingest import worker_command

ROOT = Path(__file__).resolve().parents[1]


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


def test_the_module_entry_starts_under_python_dash_m():
    """`scripts/reference_instance.py` starts this worker with `python -m`, not the console script.

    Run from the repository root with the interpreter running this suite, so the module that
    answers is this checkout's rather than whatever copy another path would find first.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "exulanica.ingest.worker_command", "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "exulanica-derivative-worker" in completed.stdout
    assert "--once" in completed.stdout
    assert "Traceback" not in completed.stderr


def _is_main_guard(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    )


def test_the_main_guard_comes_after_every_definition():
    """What the `--help` test above cannot see on its own.

    argparse exits inside `parse_args` for `--help`, before `main()` builds a worker, so that test
    passed while `_build_detector` sat below the guard and every real `python -m` start failed with
    NameError. `python -m` executes the module top to bottom as `__main__`, so the guard has to be
    its last statement for `main()` to find everything it calls.
    """
    body = ast.parse(Path(worker_command.__file__).read_text()).body
    assert [index for index, node in enumerate(body) if _is_main_guard(node)] == [len(body) - 1]


@pytest.mark.parametrize(
    "enabled,vision_budget,embedding_budget", [(False, 40, 90), (True, 40, 90), (True, 90, 40)]
)
def test_both_worker_constructors_share_the_client_and_cover_each_model_gap(
    monkeypatch, tmp_path, enabled, vision_budget, embedding_budget
):
    from exulanica.api import services
    from exulanica.models.manifest import Role
    from exulanica.selection.embeddings import embed_capture

    class Database:
        @classmethod
        def from_env(cls, environ):
            return cls()

        @contextmanager
        def unscoped(self):
            yield None

    client = SimpleNamespace(
        worst_case_seconds=lambda role: {
            Role.VISION: vision_budget,
            Role.EMBEDDING: embedding_budget,
        }[role]
    )
    clients_built = []

    def make_client(**kwargs):
        clients_built.append(kwargs)
        return client

    built = {}
    depth, detector, segmenter = object(), object(), object()
    monkeypatch.setattr(worker_command, "Database", Database)
    monkeypatch.setattr(worker_command, "verify_schema", lambda database: None)
    monkeypatch.setattr(worker_command, "assert_runtime_role", lambda connection: None)
    monkeypatch.setattr(worker_command, "ModelClient", make_client)
    monkeypatch.setattr(worker_command, "_build_depth", lambda environ: depth)
    monkeypatch.setattr(worker_command, "_build_detector", lambda environ: detector)
    monkeypatch.setattr(worker_command, "_build_segmenter", lambda environ: segmenter)
    for module in (worker_command, services):
        monkeypatch.setattr(module, "NebiusVisionModel", lambda client: client)
        monkeypatch.setattr(
            module, "DerivativeWorker", lambda *args, **kwargs: built.update(kwargs)
        )
    args = SimpleNamespace(workspace=[str(uuid.uuid4())], name="scripted", poll_seconds=2.0)
    environ = {worker_command.DATA_DIR_ENV: str(tmp_path)}
    if enabled:
        environ[worker_command.MODEL_KEY_ENV] = "scripted-key"
    worker_command._build_worker(args, environ)
    assert clients_built == ([{"max_attempts": 1}] if enabled else [])
    assert (built["depth"], built["detector"], built["segmenter"]) == (depth, detector, segmenter)

    def check_contract():
        assert built["lease_seconds"] == (180 if enabled else 60)
        assert built["vision"] is (client if enabled else None)
        if enabled:
            assert built["embedding_pass"].func is embed_capture
            assert built["embedding_pass"].keywords == {"client": client}
        else:
            assert built["embedding_pass"] is None

    check_contract()
    built.clear()
    services.Services(
        database=Database(),
        readonly_database=Database(),
        store=None,
        tokens=SimpleNamespace(workspaces=frozenset()),
        executor_shares_the_write_role=True,
        model_client=client if enabled else None,
        runs_derivative_worker=True,
    ).build_derivative_worker()
    check_contract()
    assert clients_built == ([{"max_attempts": 1}] if enabled else [])
