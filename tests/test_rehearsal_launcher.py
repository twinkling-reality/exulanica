"""The rehearsal hands the acceptance launcher the run's spend bound, and nothing else it holds.

``scripts/rehearsal/rehearse.py`` starts the launcher in an environment with every ``EXULANICA_``
variable removed. In a run with a hosted model it then puts back exactly one: the step list's
``spend.bound_usd`` as ``EXULANICA_BUDGET_USD``, which the launcher requires and passes to the API,
so the API itself refuses a model call past the run's bound. These tests run ``Run.launcher_up``
with the in-repository launcher and stop it at the process boundary: nothing is started, and the
model environment file is never read.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
from argparse import Namespace
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
REHEARSAL = ROOT / "scripts" / "rehearsal"
LAUNCHER = ROOT / "scripts" / "acceptance" / "launch.py"
sys.path.insert(0, str(REHEARSAL))

import steplist  # noqa: E402


def _rehearse() -> ModuleType:
    spec = importlib.util.spec_from_file_location("rehearsal_rehearse", REHEARSAL / "rehearse.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REHEARSE = _rehearse()
BOUND = steplist.load()["spend"]["bound_usd"]


def _launch(tmp_path: Path, monkeypatch, *, model: bool) -> tuple[list[str], dict[str, str]]:
    """Run ``launcher_up`` up to the launcher process; return its command and environment."""
    temporary = tmp_path / "system-temporary"
    temporary.mkdir()
    monkeypatch.setenv("TMPDIR", str(temporary))
    monkeypatch.setattr(tempfile, "tempdir", None)
    # A value in the caller's shell must never reach the launcher: only the run's own bound does.
    monkeypatch.setenv("EXULANICA_BUDGET_USD", "999.00")
    out = tmp_path / "out"
    out.mkdir()
    model_env = tmp_path / "model.env"
    model_env.write_text("")
    run = REHEARSE.Run(
        Namespace(
            worktree=str(ROOT),
            out=str(out),
            slot=1,
            model_env=str(model_env) if model else None,
            sessions=None,
            reuse_database=False,
            launcher=str(LAUNCHER),
            gpu_slot=None,
        )
    )
    calls: list[tuple[list[str], dict[str, str]]] = []

    def stopped_at_the_boundary(command, **options):
        calls.append((command, options["env"]))
        return subprocess.CompletedProcess(command, 2, "", "stopped by the test")

    monkeypatch.setattr(REHEARSE.subprocess, "run", stopped_at_the_boundary)
    with pytest.raises(REHEARSE.Refused, match="the launcher refused"):
        run.launcher_up()
    assert len(calls) == 1
    return calls[0]


def test_a_model_run_hands_the_launcher_the_step_lists_bound(tmp_path, monkeypatch):
    command, environment = _launch(tmp_path, monkeypatch, model=True)

    assert environment["EXULANICA_BUDGET_USD"] == BOUND
    assert [name for name in environment if name.startswith("EXULANICA_")] == [
        "EXULANICA_BUDGET_USD"
    ]
    assert command[-1] == "--model"
    assert str(LAUNCHER) in command


def test_a_run_without_a_model_hands_the_launcher_no_bound(tmp_path, monkeypatch):
    command, environment = _launch(tmp_path, monkeypatch, model=False)

    assert not [name for name in environment if name.startswith("EXULANICA_")]
    assert "--model" not in command
