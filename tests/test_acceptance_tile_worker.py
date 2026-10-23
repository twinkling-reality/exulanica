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


def _worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, event: str, *, personal: bool = False
) -> tuple[dict, dict]:
    worktree = tmp_path / "checkout"
    program = worktree / ".venv" / "bin" / "exulanica-generated-tile-worker"
    program.parent.mkdir(parents=True)
    program.touch()
    logs = tmp_path / "logs"
    logs.mkdir()
    state_file = tmp_path / "state.json"
    state: dict = {"pids": {}, **({"personal": True} if personal else {})}
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


def test_a_personal_install_s_worker_bakes_a_town_s_two_tiles_at_once_by_its_environment(
    tmp_path, monkeypatch
):
    observed, state = _worker(tmp_path, monkeypatch, "startup", personal=True)
    assert observed["environment"]["EXULANICA_TILE_BAKES_AT_ONCE"] == "2"
    # Given by the environment, so its command is the worker's own as the identity check reads it.
    assert observed["command"][-2:] == ["--workspace", "workspace"]
    assert LAUNCH.tile_worker_running(state)
    (tmp_path / "shared").mkdir()
    shared, _ = _worker(tmp_path / "shared", monkeypatch, "startup")
    assert "EXULANICA_TILE_BAKES_AT_ONCE" not in shared["environment"]


class _Stopped(BaseException):
    """Ends a worker the test runs in daemon mode, as nothing the worker catches would."""


def _command(
    monkeypatch: pytest.MonkeyPatch,
    argv: list[str],
    environ: dict[str, str],
    *,
    passes: list[object] | None = None,
    sleeps: list[float] | None = None,
    once: bool = True,
) -> tuple[int | None, list[dict], dict]:
    """The worker's command run, its database, roles and stores stood in for: what it answered (None
    when stopped while running), the events it said and what its baker was given. Each of ``passes``
    is one drain: an exception it raises, or ``"baked"`` for one tile baked; past the last the
    worker is stopped. Every wait it asks for is put in ``sleeps``."""
    import contextlib
    import io
    import uuid
    from types import SimpleNamespace

    from exulanica.ingest import generated_tiles_command as command
    from exulanica.ingest.generated_tiles import BakeOutcome

    given: dict = {}

    class Baker:
        def __init__(self, **kwargs: object) -> None:
            given.update(kwargs)

        def drain(self, workspaces: object) -> list[BakeOutcome]:
            if passes is not None:
                if not passes:
                    raise _Stopped
                step = passes.pop(0)
                if isinstance(step, Exception):
                    raise step
            tile = BakeOutcome(uuid.uuid4(), "world:generated:w", (0, 0), "baked", "", None, 6.25)
            return [tile]

    database = SimpleNamespace(
        session=None, unscoped=lambda: contextlib.nullcontext(None), url="postgresql://unused"
    )
    monkeypatch.setattr(command, "Database", SimpleNamespace(from_env=lambda environ: database))
    monkeypatch.setattr(command, "verify_schema", lambda database: None)
    monkeypatch.setattr(command, "assert_runtime_role", lambda connection: None)
    monkeypatch.setattr(command, "check_publisher", lambda url, environ: None)
    monkeypatch.setattr(
        command, "content_stores", lambda environ: SimpleNamespace(tiles=None, version_tiles=None)
    )
    monkeypatch.setattr(command, "GeneratedTileBaker", Baker)
    monkeypatch.setattr(command.time, "sleep", (sleeps if sleeps is not None else []).append)
    stream = io.StringIO()
    environ = {"EXULANICA_TILE_PUBLISHER_DATABASE_URL": "postgresql://unused", **environ}
    workspace = ["--workspace", str(uuid.uuid4()), *(["--once"] if once else [])]
    answered: int | None
    try:
        answered = command.main([*workspace, *argv], environ=environ, stream=stream)
    except _Stopped:
        answered = None
    events = [json.loads(line) for line in stream.getvalue().splitlines()]
    return answered, events, given


def test_the_worker_bakes_as_many_tiles_at_once_as_it_is_told_and_refuses_any_other_number(
    monkeypatch,
):
    # Told nothing, one at a time.
    answered, events, given = _command(monkeypatch, [], {})
    startup, bake = events
    assert answered == 0 and given["bakes_at_once"] == 1 and startup["bakes_at_once"] == 1
    # Each bake says how long it took.
    assert bake["event"] == "bake" and bake["seconds"] == 6.25
    # Told two, two at once; the argument wins over the environment.
    answered, events, given = _command(monkeypatch, [], {"EXULANICA_TILE_BAKES_AT_ONCE": "2"})
    assert given["bakes_at_once"] == 2 and events[0]["bakes_at_once"] == 2
    _, _, given = _command(
        monkeypatch, ["--bakes-at-once", "3"], {"EXULANICA_TILE_BAKES_AT_ONCE": "2"}
    )
    assert given["bakes_at_once"] == 3
    # Anything else stops the start by name, before the worker is built.
    for value in ("0", "5", "two", "1.5", "\u00b2"):
        answered, events, given = _command(monkeypatch, [], {"EXULANICA_TILE_BAKES_AT_ONCE": value})
        (failed,) = events
        assert (answered, failed["event"], given) == (1, "startup_failed", {})
        assert failed["message"].startswith("tile_bakes_at_once_out_of_bounds: ")
        assert "EXULANICA_TILE_BAKES_AT_ONCE" in failed["message"]


def test_a_pass_that_fails_costs_that_pass_and_the_worker_tries_again_after_a_growing_wait(
    monkeypatch,
):
    from exulanica.ingest.generated_tiles_command import PASS_RETRY_MOST_SECONDS

    failure = RuntimeError("the database did not answer")
    sleeps: list[float] = []
    passes: list[object] = [failure] * 6 + ["baked", failure]
    answered, events, _ = _command(monkeypatch, [], {}, passes=passes, sleeps=sleeps, once=False)
    # Still running when stopped: no failed pass ended it.
    assert answered is None
    assert [e["event"] for e in events] == ["startup", *["pass_failed"] * 6, "bake", "pass_failed"]
    said = {(e["failure_class"], e["message"]) for e in events if e["event"] == "pass_failed"}
    assert said == {("RuntimeError", "the database did not answer")}
    # The wait doubles from the poll to its bound, is the poll once a pass drains again, and then
    # doubles from the start.
    most = PASS_RETRY_MOST_SECONDS
    assert sleeps == [2.0, 4.0, 8.0, 16.0, most, most, 1.0, 2.0]
    assert [e["retry_seconds"] for e in events if e["event"] == "pass_failed"] == [
        2.0,
        4.0,
        8.0,
        16.0,
        most,
        most,
        2.0,
    ]
    # Told to bake what waits and stop, a failed pass is its answer.
    answered, events, _ = _command(monkeypatch, [], {}, passes=[failure])
    assert answered == 1 and events[-1]["event"] == "pass_failed"


def test_worker_runs_by_the_checkout_s_interpreter_so_a_trampoline_script_is_recognised(
    tmp_path, monkeypatch
):
    """A venv under a long path, or one with a space, gets console scripts that begin with a /bin/sh
    exec trampoline; started directly the worker reads "/bin/sh <script> ..." and is refused."""
    observed, state = _worker(tmp_path, monkeypatch, "startup")
    python = str(tmp_path / "checkout" / ".venv" / "bin" / "python")
    program = str(tmp_path / "checkout" / ".venv" / "bin" / "exulanica-generated-tile-worker")
    assert observed["command"] == [python, program, "--workspace", "workspace"]
    assert LAUNCH.tile_worker_running(state)
    # The positive control: the trampoline's own first command is not the worker.
    identity = {"executable": program, "workspace": "workspace"}
    assert not LAUNCH.worker_command_matches(f"/bin/sh {program} --workspace workspace", identity)


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
