"""The project worker: a process of its own beside the API that keeps followed projects current.

Its startup refusals are read in this process; one run is a real process, started against a fake
World API on this machine and stopped with SIGTERM, as a runtime stops it.
"""

import io
import json
import os
import queue
import signal
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from exulanica.orchestration.project_worker import main
from exulanica.world_package.projects.repository import Project

from test_world_project_capture import TOKEN
from test_world_project_follow import follow, move, token, world  # noqa: F401 (fixtures)

ROOT = Path(__file__).resolve().parents[1]


def events(stream: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_the_worker_refuses_to_start_without_its_three_settings(tmp_path):
    stream = io.StringIO()
    assert main([], environ={}, stream=stream) == 1
    (failed,) = events(stream)
    assert failed["event"] == "startup_failed"
    assert "projects directory" in failed["message"]


def test_the_worker_refuses_a_token_it_may_not_read_and_says_no_path(tmp_path):
    real = tmp_path / "real-token"
    real.write_text(TOKEN, encoding="utf-8")
    link = tmp_path / "token-link"
    link.symlink_to(real)
    (tmp_path / "projects").mkdir()
    stream = io.StringIO()
    environ = {
        "EXULANICA_PROJECTS_DIRECTORY": str(tmp_path / "projects"),
        "EXULANICA_PROJECT_API_URL": "http://localhost:1",
        "EXULANICA_PROJECT_TOKEN_FILE": str(link),
    }
    assert main([], environ=environ, stream=stream) == 1
    (failed,) = events(stream)
    assert failed["event"] == "startup_failed"
    text = stream.getvalue()
    assert TOKEN not in text and str(tmp_path) not in text


def test_the_worker_refuses_an_api_it_may_not_reach_over_plain_http(tmp_path, token):  # noqa: F811
    (tmp_path / "projects").mkdir()
    stream = io.StringIO()
    arguments = ["--projects", str(tmp_path / "projects"), "--token-file", str(token)]
    assert main([*arguments, "--api", "http://api:8000"], environ={}, stream=stream) == 1
    assert events(stream)[0]["event"] == "startup_failed"


def test_a_running_worker_follows_on_its_own_and_stops_cleanly_on_sigterm(
    world,  # noqa: F811
    token,  # noqa: F811
    tmp_path,
):
    projects = tmp_path / "projects"
    folder = follow(world, token, projects / "demo")
    move(world, 5000)  # A change the world holds before the worker starts.
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ROOT), str(ROOT / "tests")])}
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "exulanica.orchestration.project_worker",
            "--projects",
            str(projects),
            "--api",
            world.url,
            "--token-file",
            str(token),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        cwd=tmp_path,
    )
    lines: queue.Queue[str] = queue.Queue()
    reader = threading.Thread(
        target=lambda: [lines.put(line) for line in process.stdout], daemon=True
    )
    reader.start()
    seen = []
    try:
        while not any(e.get("state") == "settling" for e in seen):
            seen.append(json.loads(lines.get(timeout=60)))
        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=120) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    reader.join(timeout=10)
    while not lines.empty():
        seen.append(json.loads(lines.get()))
    kinds = [e["event"] for e in seen]
    assert kinds[0] == "startup" and kinds[-1] == "stopped"
    assert "shutdown_requested" in kinds
    assert seen[-1]["recorded"] == 1
    recorded = [e for e in seen if e.get("state") == "checkpointed"]
    assert [e["message"] for e in recorded] == ["Moved the knight 5 m east"]
    assert Project(folder).history()[0]["message"] == "Moved the knight 5 m east"
    output = json.dumps(seen) + process.stderr.read()
    assert TOKEN not in output and str(tmp_path) not in output
    assert {method for method, _, _ in world.requests} == {"GET"}


@pytest.mark.parametrize("name", ["EXULANICA_PROJECTS_MAXIMUM", "EXULANICA_PROJECT_FINISH_SECONDS"])
def test_the_worker_s_host_figures_are_settings_with_bounds(tmp_path, token, name):  # noqa: F811
    (tmp_path / "projects").mkdir()
    stream = io.StringIO()
    environ = {
        "EXULANICA_PROJECTS_DIRECTORY": str(tmp_path / "projects"),
        "EXULANICA_PROJECT_API_URL": "http://localhost:1",
        "EXULANICA_PROJECT_TOKEN_FILE": str(token),
        name: "0",
    }
    assert main([], environ=environ, stream=stream) == 1
    assert events(stream)[0]["event"] == "startup_failed"
