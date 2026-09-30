"""A loaded functional rehearsal continues when only a declared timing claim fails."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rehearsal"))

import rehearse  # noqa: E402
import steplist  # noqa: E402
import timing_phase  # noqa: E402


def test_browser_capture_requires_both_shared_slots_in_gpu_then_quiet_order():
    gpu = Path("/slots/gpu")
    quiet = Path("/slots/quiet")
    command = ["node", "session.mjs"]
    assert rehearse.browser_slot_command(gpu, quiet, command) == [str(gpu), str(quiet), *command]
    with pytest.raises(rehearse.Refused, match="both GPU and quiet slots"):
        rehearse.browser_slot_command(gpu, None, command)


def _step(name: str) -> dict:
    return next(step for step in steplist.load()["steps"] if step["id"] == name)


def _observations(step: dict, broken: set[str]) -> list[dict]:
    return [
        {"id": item["id"], "ok": item["id"] not in broken}
        for group in step["expect"].values()
        for item in group
    ]


def _outcome(observations: list[dict], reason: str | None = None) -> dict:
    broken = [item["id"] for item in observations if not item["ok"]]
    return {
        "status": "failed",
        "reason": reason or "did not hold: " + ", ".join(broken),
        "observations": observations,
    }


def test_timing_claims_are_declared_without_dropping_functional_checks():
    walking = _step("play-and-watch-walking")
    birds = _step("birds-fly-and-perch")
    assert set(walking["timing_observations"]) == {"walking-continuously", "host-plays"}
    assert set(birds["timing_observations"]) == {"page-stays-responsive"}
    assert {item["id"] for group in walking["expect"].values() for item in group} >= {
        "walkers-visible-moving",
        "host-playing",
        "minutes-pass",
        "play-offered",
    }
    broken = json.loads(json.dumps(steplist.load()))
    next(step for step in broken["steps"] if step["id"] == walking["id"])["timing_observations"] = [
        "absent"
    ]
    assert any(
        "timing_observations names an undeclared result" in item
        for item in steplist.problems(broken, steplist.read_gates(broken["gate_sources"]))
    )


def test_only_timing_failures_allow_continuation_in_python_and_browser_driver():
    step = _step("play-and-watch-walking")
    cases = [
        (_observations(step, {"walking-continuously", "host-plays"}), None, True),
        (_observations(step, {"walkers-visible-moving"}), None, False),
        (
            _observations(step, {"walking-continuously"}),
            "did not hold: walking-continuously; no screenshot was captured",
            False,
        ),
        (_observations(step, {"walking-continuously"})[:-1], None, False),
    ]
    duplicated = _observations(step, {"walking-continuously"})
    duplicated[-1] = dict(duplicated[0])
    cases.append((duplicated, None, False))
    payload = []
    for observations, reason, expected in cases:
        outcome = _outcome(observations, reason)
        assert steplist.timing_only_failure(step, outcome) is expected
        payload.append({"step": step, "observations": observations, "reason": outcome["reason"]})
    script = (
        "import { readFileSync } from 'node:fs'; "
        "import { timingOnlyFailure } from './scripts/rehearsal/continuation.mjs'; "
        "const cases = JSON.parse(readFileSync(0, 'utf8')); "
        "console.log(JSON.stringify(cases.map(c => "
        "timingOnlyFailure(c.step, c.observations, c.reason))));"
    )
    ran = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    assert json.loads(ran.stdout) == [expected for _, _, expected in cases]


def test_a_later_session_can_follow_a_timing_only_failure():
    step = _step("play-and-watch-walking")
    observed = _observations(step, {"host-plays"})
    run = object.__new__(rehearse.Run)
    run.steps = steplist.load()
    run.outcomes = {step["id"]: _outcome(observed)}
    assert run.status_of(step["id"]) == "passed"
    dependent = _step("inspect-an-inhabitant")
    assert run.blocked(dependent) is None
    run.outcomes[step["id"]] = _outcome(_observations(step, {"host-playing"}))
    assert run.status_of(step["id"]) == "failed"
    assert "requires play-and-watch-walking" in run.blocked(dependent)


def test_running_flag_without_a_durable_tick_is_a_functional_failure():
    script = (
        "import { hostProgresses } from './scripts/rehearsal/continuation.mjs'; "
        "const running = {mode:'playing', host_playback:{running:true}}; "
        "console.log(JSON.stringify([hostProgresses(running, running, 0), "
        "hostProgresses(running, running, 1)]));"
    )
    ran = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        text=True,
        capture_output=True,
        cwd=ROOT,
        check=True,
    )
    assert json.loads(ran.stdout) == [False, True]


def test_timing_phase_refuses_a_busy_start_without_opening_a_browser(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    receipt = tmp_path / "timing-receipt.json"
    monkeypatch.setattr(timing_phase, "idle_share", lambda: Decimal("69.9"))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timing_phase.py",
            "--plan",
            str(plan),
            "--receipt",
            str(receipt),
            "--timeout-seconds",
            "60",
        ],
    )
    assert timing_phase.main() == 0
    document = json.loads(receipt.read_text())
    assert document["status"] == "idle_gate_refused"
    assert document["idle_before_percent"] == "69.9"
    assert not (tmp_path / "session.json").exists()


def test_timing_phase_discards_a_low_mean_even_after_an_idle_start(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    receipt = tmp_path / "timing-receipt.json"
    samples = iter((Decimal("80"), Decimal("49")))
    monkeypatch.setattr(timing_phase, "idle_share", lambda: next(samples))

    class Child:
        pid = 1
        returncode = 0
        polls = 0

        def poll(self):
            self.polls += 1
            return None if self.polls <= 2 else 0

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(timing_phase.subprocess, "Popen", lambda *args, **kwargs: Child())
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timing_phase.py",
            "--plan",
            str(plan),
            "--receipt",
            str(receipt),
            "--timeout-seconds",
            "60",
        ],
    )
    assert timing_phase.main() == 0
    document = json.loads(receipt.read_text())
    assert document["status"] == "discarded_load"
    assert document["idle_mean_percent"] == "49"


def test_timing_phase_signal_stops_only_its_session_and_writes_receipt(tmp_path, monkeypatch):
    plan = tmp_path / "plan.json"
    plan.write_text("{}")
    receipt = tmp_path / "timing-receipt.json"
    actual_popen = subprocess.Popen
    preview = actual_popen(
        [sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True
    )
    children = []
    ready = tmp_path / "timing-child-ready"

    def open_session(*_args, **kwargs):
        child = actual_popen(
            [
                sys.executable,
                "-c",
                "import pathlib, signal, sys, time; "
                "signal.signal(signal.SIGTERM, lambda *_: (time.sleep(6), sys.exit(0))); "
                "pathlib.Path(sys.argv[1]).write_text('ready'); time.sleep(30)",
                str(ready),
            ],
            **kwargs,
        )
        children.append(child)
        return child

    samples = 0

    def signal_after_start():
        nonlocal samples
        samples += 1
        if samples == 1:
            return Decimal("80")
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists() and children[0].poll() is None
        os.kill(os.getpid(), signal.SIGTERM)
        time.sleep(1)  # The handler interrupts before this line.
        raise AssertionError("SIGTERM did not interrupt the timing phase")

    monkeypatch.setattr(timing_phase, "idle_share", signal_after_start)
    monkeypatch.setattr(timing_phase.subprocess, "Popen", open_session)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "timing_phase.py",
            "--plan",
            str(plan),
            "--receipt",
            str(receipt),
            "--timeout-seconds",
            "60",
        ],
    )
    try:
        assert timing_phase.main() == 128 + signal.SIGTERM
        document = json.loads(receipt.read_text())
        assert document["status"] == "interrupted"
        assert document["session_exit"] == 0  # Six-second cleanup beat the TERM grace.
        assert children[0].poll() is not None
        assert preview.poll() is None
    finally:
        os.killpg(preview.pid, signal.SIGTERM)
        preview.wait(timeout=5)
