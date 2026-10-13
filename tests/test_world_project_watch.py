"""Automatic checkpoints with a fake clock and a fake reader; no world, server or remote."""

import subprocess
import threading
from copy import deepcopy

import pytest
from exulanica.world_package.projects.capture import Capture
from exulanica.world_package.projects.checkpoint import ProjectError
from exulanica.world_package.projects.repository import Author, Project, create
from exulanica.world_package.projects.watch import Policy, Watcher

from test_world_project import sample

AUTHOR = Author("Synthetic Student", "student@example.invalid")


class World:
    """What capture would return; tests change it between polls."""

    def __init__(self, checkpoint):
        self.checkpoint = checkpoint
        self.down = False

    def read(self):
        if self.down:
            raise ProjectError("world API read GET version did not complete")
        return Capture(deepcopy(self.checkpoint), {})


class Clock:
    def __init__(self):
        self.now = 1_760_000_000.0

    def __call__(self):
        return self.now


def commits(folder):
    return int(
        subprocess.run(
            ["git", f"--git-dir={folder / '.git'}", "rev-list", "--count", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        ).stdout
    )


@pytest.fixture
def setup(tmp_path):
    project, _ = sample()
    folder = tmp_path / "project"
    create(folder, project, author=AUTHOR)
    world, clock = World(deepcopy(project)), Clock()
    policy = Policy(poll_seconds=15, settle_seconds=120, daily_cap=2)
    watcher = Watcher(Project(folder, author=AUTHOR), world.read, policy, clock)
    return project, folder, world, clock, watcher


def move(world, x_mm):
    world.checkpoint["things"][0]["transform"]["x_mm"] = x_mm


def test_settles_before_recording_and_restarts_when_the_selection_moves_again(setup):
    _, folder, world, clock, watcher = setup
    assert watcher.step() == {"state": "clean"}
    move(world, 1000)
    assert watcher.step()["state"] == "settling"
    assert Project(folder).timeline()["pending"] == ["moved the knight 1 m east"]
    clock.now += 100
    move(world, 2000)  # Still changing: the settle period starts again.
    assert watcher.step()["pending"] == ["moved the knight 2 m east"]
    clock.now += 100
    assert watcher.step()["state"] == "settling"
    clock.now += 20
    recorded = watcher.step()
    assert recorded["state"] == "checkpointed"
    assert recorded["message"] == "Moved the knight 2 m east"
    assert commits(folder) == 2
    assert watcher.step() == {"state": "clean"}


def test_edits_that_cancel_out_record_nothing(setup):
    project, folder, world, clock, watcher = setup
    world.checkpoint["models"], world.checkpoint["decisions"] = [], []
    assert watcher.step()["pending"] == [
        "unassigned synthetic-model from the knight",
        "dropped 1 decision record",
    ]
    clock.now += 60
    world.checkpoint = deepcopy(project)
    assert watcher.step() == {"state": "clean"}
    clock.now += 600
    assert watcher.step() == {"state": "clean"}
    assert commits(folder) == 1
    assert Project(folder).timeline()["pending"] == []


def test_daily_cap_holds_changes_pending_until_the_next_day(setup):
    _, folder, world, clock, watcher = setup
    for x_mm in (1000, 2000):
        move(world, x_mm)
        watcher.step()
        clock.now += 120
        assert watcher.step()["state"] == "checkpointed"
    move(world, 3000)
    watcher.step()
    clock.now += 120
    assert watcher.step()["state"] == "capped"
    assert commits(folder) == 3
    clock.now += 86_400
    assert watcher.step()["state"] == "checkpointed"


def test_run_stops_cleanly_and_records_the_pending_change_once(setup):
    _, folder, world, _, watcher = setup
    move(world, 4000)
    stop = threading.Event()
    seen = []

    def report(outcome):
        seen.append(outcome["state"])
        stop.set()

    final = watcher.run(stop, report)
    assert final["state"] == "checkpointed"
    assert seen == ["settling", "checkpointed"]
    assert commits(folder) == 2


def test_an_unreachable_world_is_reported_and_nothing_is_recorded(setup):
    _, folder, world, _, watcher = setup
    world.down = True
    stop = threading.Event()
    seen = []

    def report(outcome):
        seen.append(outcome["state"])
        stop.set()

    assert watcher.run(stop, report)["state"] == "unreachable"
    assert seen == ["unreachable", "unreachable"]
    assert commits(folder) == 1


@pytest.mark.parametrize(
    "policy",
    [
        {"poll_seconds": 1},
        {"poll_seconds": 600},
        {"settle_seconds": 10},
        {"daily_cap": 0},
    ],
)
def test_policy_bounds(policy):
    with pytest.raises(ProjectError):
        Policy(**policy)


def test_growing_evidence_is_recorded_after_the_maximum_pending_time(tmp_path):
    from test_world_project_repository import evidence_from, more_records

    project, _ = sample()
    world_doc, evidence = evidence_from(project)
    folder = tmp_path / "project"
    create(folder, world_doc, author=AUTHOR, evidence=[evidence])
    clock = Clock()
    feed = {"evidence": evidence}

    def read():
        return Capture(deepcopy(world_doc), {}, evidence=deepcopy(feed["evidence"]))

    policy = Policy(poll_seconds=15, settle_seconds=120, max_pending_seconds=600, daily_cap=5)
    watcher = Watcher(Project(folder, author=AUTHOR), read, policy, clock)
    assert watcher.step() == {"state": "clean"}
    states = []
    for minute in range(1, 12):
        # A model decides every minute, so the evidence never settles.
        feed["evidence"] = more_records(evidence, minute)
        clock.now += 60
        states.append(watcher.step()["state"])
    assert states.index("checkpointed") == 10  # Ten minutes after the first pending change.
    assert states[:10] == ["settling"] * 10
    assert commits(folder) == 2
    assert Project(folder).timeline()["checkpoints"][0]["summary"] == []


def test_a_capture_window_never_loses_records_and_long_sessions_continue(tmp_path, monkeypatch):
    from exulanica.world_package.projects import repository

    from test_world_project_repository import evidence_from, more_records

    project, _ = sample()
    world_doc, evidence = evidence_from(project)
    folder = tmp_path / "project"
    create(folder, world_doc, author=AUTHOR)
    clock = Clock()
    full = more_records(evidence, 7)  # Eight records in all.
    feed = {"window": full["decisions"][:3]}

    def read():
        return Capture(deepcopy(world_doc), {}, evidence={**full, "decisions": feed["window"]})

    policy = Policy(poll_seconds=15, settle_seconds=15, max_pending_seconds=15, daily_cap=50)
    watcher = Watcher(Project(folder, author=AUTHOR), read, policy, clock)
    monkeypatch.setattr(repository, "SESSION_LIMIT", 5)
    for start in range(0, 8, 2):
        feed["window"] = full["decisions"][start : start + 3]  # The window slides on.
        watcher.step()
        clock.now += 30
        watcher.step()
    sessions = Project(folder).sessions_at("HEAD")
    assert sorted(sessions) == ["session-one-2.json", "session-one.json"]
    assert [len(sessions[name]["decisions"]) for name in sorted(sessions)] == [3, 5]
    kept = {d["record_id"] for s in sessions.values() for d in s["decisions"]}
    assert kept == {d["record_id"] for d in full["decisions"]}
