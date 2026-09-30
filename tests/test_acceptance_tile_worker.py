"""The acceptance launcher owns one real generated-tile worker for its workspace."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "acceptance_tile_launcher", ROOT / "scripts" / "acceptance" / "launch.py"
)
assert SPEC is not None and SPEC.loader is not None
LAUNCH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCH)


def _worker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str) -> tuple[dict, dict]:
    worktree = tmp_path / "checkout"
    program = worktree / ".venv" / "bin" / "exulanica-generated-tile-worker"
    program.parent.mkdir(parents=True)
    program.touch()
    logs = tmp_path / "logs"
    logs.mkdir()
    state_file = tmp_path / "state.json"
    state = {"pids": {}}
    observed: dict = {}

    def spawn(command, cwd, environment, log):
        observed.update(command=command, cwd=cwd, environment=environment, log=log)
        log.write_text(json.dumps({"component": "generated-tile-worker", "event": event}))
        return 12345

    monkeypatch.setattr(LAUNCH, "spawn", spawn)
    monkeypatch.setattr(LAUNCH, "command_of", lambda pid: " ".join(observed["command"]))
    monkeypatch.setattr(LAUNCH, "process_started_at", lambda pid: "Wed Sep 30 09:00:00 2026")
    exports = {
        "EXULANICA_DATABASE_URL": "postgresql://exulanica_app@localhost/runtime",
        "OWNER_URL": "postgresql://localhost/owner",
    }
    if event == "startup":
        LAUNCH.start_tile_worker(
            worktree, exports, tmp_path / "data", "workspace", logs, state, state_file
        )
    else:
        with pytest.raises(LAUNCH.Refused, match="tile-worker-startup"):
            LAUNCH.start_tile_worker(
                worktree, exports, tmp_path / "data", "workspace", logs, state, state_file
            )
    assert json.loads(state_file.read_text())["pids"]["tile_worker"] == 12345
    return observed, state


def test_worker_uses_runtime_claims_owner_publication_and_one_workspace(tmp_path, monkeypatch):
    observed, state = _worker(tmp_path, monkeypatch, "startup")
    assert observed["command"][-2:] == ["--workspace", "workspace"]
    assert observed["environment"]["EXULANICA_DATABASE_URL"].startswith(
        "postgresql://exulanica_app@"
    )
    assert observed["environment"]["EXULANICA_TILE_PUBLISHER_DATABASE_URL"] == (
        "postgresql://localhost/owner"
    )
    assert observed["environment"]["EXULANICA_DATA_DIR"] == str(tmp_path / "data")
    assert state["pids"] == {"tile_worker": 12345}


def test_worker_startup_failure_is_refused_with_a_recorded_pid_for_cleanup(tmp_path, monkeypatch):
    _worker(tmp_path, monkeypatch, "startup_failed")


def test_only_worker_events_count_as_bakes(tmp_path):
    log = tmp_path / "worker.log"
    log.write_text(
        "noise\n"
        + json.dumps({"component": "other", "event": "bake", "status": "baked"})
        + "\n"
        + json.dumps({"component": "generated-tile-worker", "event": "bake", "status": "baked"})
    )
    assert LAUNCH.tile_worker_events(log) == [
        {"component": "generated-tile-worker", "event": "bake", "status": "baked"}
    ]


def test_status_surfaces_a_worker_that_exited_and_down_leaves_it_alone(
    tmp_path, monkeypatch, capsys
):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    run_dir = tmp_path / "run"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    (logs / "generated-tile-worker.log").write_text(
        json.dumps({"component": "generated-tile-worker", "event": "startup"})
        + "\n"
        + json.dumps({"component": "generated-tile-worker", "event": "bake", "status": "failed"})
    )
    state = {
        "pids": {"tile_worker": 12345},
        "tile_worker_identity": {
            "executable": str(tmp_path / ".venv/bin/exulanica-generated-tile-worker"),
            "workspace": "workspace",
            "started_at": "Wed Sep 30 09:00:00 2026",
        },
        "run_dir": str(run_dir),
        "database": {"started_by_launcher": False},
    }
    (state_dir / "state.json").write_text(json.dumps(state))
    monkeypatch.setattr(LAUNCH, "recorded_checkout", lambda path: tmp_path)
    monkeypatch.setattr(LAUNCH, "state_dir", lambda worktree: state_dir)
    monkeypatch.setattr(LAUNCH, "command_of", lambda pid: "")
    monkeypatch.setattr(LAUNCH, "process_started_at", lambda pid: "")
    killed = []
    monkeypatch.setattr(LAUNCH.os, "killpg", lambda *args: killed.append(args))
    arguments = argparse.Namespace(worktree=str(tmp_path))

    LAUNCH.status(arguments)
    shown = capsys.readouterr().out
    assert "tile_worker: pid 12345 gone" in shown
    assert '"running": false' in shown and '"failed": 1' in shown

    LAUNCH.down(arguments)
    assert killed == []
    assert not (state_dir / "state.json").exists()


def test_same_executable_cannot_claim_another_workspace_or_creation(tmp_path, monkeypatch):
    program = str(tmp_path / ".venv/bin/exulanica-generated-tile-worker")
    state = {
        "pids": {"tile_worker": 12345},
        "tile_worker_identity": {
            "executable": program,
            "workspace": "ours",
            "started_at": "Wed Sep 30 09:00:00 2026",
        },
    }
    killed = []
    monkeypatch.setattr(LAUNCH.os, "killpg", lambda *args: killed.append(args))
    monkeypatch.setattr(LAUNCH.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(LAUNCH, "command_of", lambda pid: f"{program} --workspace another")
    monkeypatch.setattr(
        LAUNCH, "process_started_at", lambda pid: state["tile_worker_identity"]["started_at"]
    )
    assert not LAUNCH.tile_worker_running(state)
    LAUNCH.stop_tile_worker(state)
    assert killed == []

    monkeypatch.setattr(LAUNCH, "command_of", lambda pid: f"{program} --workspace ours")
    monkeypatch.setattr(LAUNCH, "process_started_at", lambda pid: "Wed Sep 30 09:00:01 2026")
    assert not LAUNCH.tile_worker_running(state)
    LAUNCH.stop_tile_worker(state)
    assert killed == []


def test_down_stops_the_matching_worker_process_group(tmp_path, monkeypatch):
    program = str(tmp_path / ".venv/bin/exulanica-generated-tile-worker")
    state = {
        "pids": {"tile_worker": 12345},
        "tile_worker_identity": {
            "executable": program,
            "workspace": "ours",
            "started_at": "Wed Sep 30 09:00:00 2026",
        },
    }
    killed = []
    monkeypatch.setattr(LAUNCH.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(LAUNCH.os, "killpg", lambda *args: killed.append(args))
    monkeypatch.setattr(
        LAUNCH, "command_of", lambda pid: "" if killed else f"{program} --workspace ours"
    )
    monkeypatch.setattr(LAUNCH, "process_started_at", lambda pid: "Wed Sep 30 09:00:00 2026")
    LAUNCH.stop_tile_worker(state)
    assert killed == [(12345, LAUNCH.signal.SIGTERM)]
