"""Run the two timing-sensitive browser steps after an idle gate, with both shared slots held.

The caller takes gpu-slot, then quiet-slot, before invoking this program. It gives a browser
session a separate result so a loaded functional run's values cannot become timing evidence.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
IDLE_BEFORE = Decimal("70")
IDLE_MEAN = Decimal("50")
IDLE_SECONDS = 10
IDLE_RE = re.compile(r"CPU usage: .*?([0-9.]+)% idle")


def now() -> str:
    return datetime.now(UTC).isoformat()


def idle_share() -> Decimal:
    """The second macOS top sample, ten seconds after its first sample."""
    if platform.system() != "Darwin":
        raise RuntimeError("CPU idle timing requires the macOS host")
    completed = subprocess.run(
        ["top", "-l", "2", "-s", str(IDLE_SECONDS), "-n", "0"],
        capture_output=True,
        text=True,
        timeout=IDLE_SECONDS + 15,
        check=True,
    )
    found = IDLE_RE.findall(completed.stdout)
    if len(found) < 2:
        raise RuntimeError("top gave no second CPU idle sample")
    return Decimal(found[-1])


def digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


class PhaseInterrupted(Exception):
    def __init__(self, signum: int) -> None:
        self.signum = signum
        super().__init__(f"signal {signum}")


def interrupt(signum: int, _frame: object) -> None:
    raise PhaseInterrupted(signum)


def stop_owned_session(child: subprocess.Popen[bytes]) -> None:
    """Stop only this session group, allowing Chrome's 5.3 s close path before KILL."""
    if child.poll() is not None:
        return
    with contextlib.suppress(ProcessLookupError):
        os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=10)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, required=True)
    args = parser.parse_args()
    plan = args.plan.resolve()
    receipt = args.receipt.resolve()
    if receipt.exists():
        raise SystemExit("the timing receipt already exists")
    session = plan.parent / "session.json"
    log = plan.parent / "session.log"
    record: dict[str, object] = {
        "profile": "exulanica.rehearsal-timing-phase/v1",
        "started_at": now(),
        "idle_sample_seconds": IDLE_SECONDS,
        "minimum_before_percent": str(IDLE_BEFORE),
        "minimum_mean_percent": str(IDLE_MEAN),
        "plan_sha256": digest(plan),
        "idle_before_percent": None,
        "idle_during_percent": [],
        "idle_mean_percent": None,
        "session_sha256": None,
        "session_exit": None,
        "status": "unverified",
    }
    child: subprocess.Popen[bytes] | None = None
    interrupted_signal: int | None = None
    previous_handlers = {
        signum: signal.signal(signum, interrupt) for signum in (signal.SIGTERM, signal.SIGINT)
    }
    try:
        before = idle_share()
        record["idle_before_percent"] = str(before)
        if before < IDLE_BEFORE:
            record["status"] = "idle_gate_refused"
            return 0
        with log.open("wb") as output:
            child = subprocess.Popen(
                ["node", str(HERE / "session.mjs"), str(plan)],
                cwd=HERE.parents[1],
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            samples: list[Decimal] = []
            deadline = time.monotonic() + args.timeout_seconds
            try:
                while child.poll() is None:
                    if time.monotonic() >= deadline:
                        record["status"] = "session_timeout"
                        break
                    sample = idle_share()
                    # A top sample that crosses the browser's exit includes idle time after
                    # the run, so it cannot lift the mean of the run itself.
                    if child.poll() is None:
                        samples.append(sample)
            finally:
                stop_owned_session(child)
            record["session_exit"] = child.returncode
            record["idle_during_percent"] = [str(value) for value in samples]
            record["session_sha256"] = digest(session)
            if samples:
                mean = sum(samples, Decimal(0)) / len(samples)
                record["idle_mean_percent"] = str(mean)
                if record["status"] == "session_timeout":
                    pass
                elif mean < IDLE_MEAN:
                    record["status"] = "discarded_load"
                elif child.returncode == 0 and session.exists():
                    record["status"] = "eligible"
                else:
                    record["status"] = "session_failed"
            elif record["status"] != "session_timeout":
                record["status"] = "no_during_sample"
    except PhaseInterrupted as error:
        interrupted_signal = error.signum
        record["status"] = "interrupted"
        record["reason"] = str(error)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        record["status"] = "sampling_failed"
        record["reason"] = f"{type(error).__name__}: {error}"
    finally:
        for signum in previous_handlers:
            signal.signal(signum, signal.SIG_IGN)
        # A signal can arrive during preflight or Popen, before the inner cleanup exists.
        if child is not None:
            stop_owned_session(child)
            record["session_exit"] = child.returncode
            record["session_sha256"] = digest(session)
        record["finished_at"] = now()
        receipt.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
        print(
            json.dumps(
                {
                    key: record[key]
                    for key in (
                        "status",
                        "idle_before_percent",
                        "idle_mean_percent",
                        "session_exit",
                    )
                }
            )
        )
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
    return 128 + interrupted_signal if interrupted_signal is not None else 0


if __name__ == "__main__":
    sys.exit(main())
