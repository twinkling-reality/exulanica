"""The dedicated derivative-worker process contract, without starting a signal loop."""

from __future__ import annotations

import ast
import io
import json
import subprocess
import sys
import uuid
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
