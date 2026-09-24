"""How the rehearsal starts the acceptance launcher and takes the application it serves.

``scripts/rehearsal/rehearse.py`` runs the repository's own launcher by default,
``scripts/acceptance/launch.py``, with ``up --production``, in an environment with every
``EXULANICA_`` variable removed. In a run with a hosted model it puts back exactly one: the step
list's ``spend.bound_usd`` as ``EXULANICA_BUDGET_USD``, which the launcher requires and passes to
the API, so the API itself refuses a model call past the run's bound. The application is the
production build the launcher made and serves, and the rehearsal records that build and the page
the preview served, and looks for the workspace token in it as well as in its own run directory.

These run ``Run.launcher_up`` and ``Run.take_build`` without starting anything: the launcher is
stopped at the process boundary, the preview's answer is given, and the model environment file is
never read.
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


def _run(
    tmp_path: Path,
    monkeypatch,
    *,
    model: bool,
    launcher: Path | None = LAUNCHER,
    bound_usd: str | None = None,
):
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
    return REHEARSE.Run(
        Namespace(
            worktree=str(ROOT),
            out=str(out),
            slot=1,
            model_env=str(model_env) if model else None,
            bound_usd=bound_usd,
            sessions=None,
            reuse_database=False,
            launcher=None if launcher is None else str(launcher),
            gpu_slot=None,
        )
    )


def _launch(
    tmp_path: Path, monkeypatch, *, model: bool, bound_usd: str | None = None
) -> tuple[list[str], dict[str, str]]:
    """Run ``launcher_up`` up to the launcher process; return its command and environment."""
    run = _run(tmp_path, monkeypatch, model=model, bound_usd=bound_usd)
    calls: list[tuple[list[str], dict[str, str]]] = []

    def stopped_at_the_boundary(command, **options):
        calls.append((command, options["env"]))
        return subprocess.CompletedProcess(command, 2, "", "stopped by the test")

    monkeypatch.setattr(REHEARSE.subprocess, "run", stopped_at_the_boundary)
    with pytest.raises(REHEARSE.Refused, match="the launcher refused"):
        run.launcher_up()
    assert len(calls) == 1
    return calls[0]


def test_the_rehearsal_runs_the_repositorys_own_launcher_unless_told_otherwise(
    tmp_path, monkeypatch
):
    run = _run(tmp_path, monkeypatch, model=False, launcher=None)

    assert run.launcher_path == LAUNCHER


def test_a_model_run_asks_for_a_production_build_and_hands_over_the_step_lists_bound(
    tmp_path, monkeypatch
):
    command, environment = _launch(tmp_path, monkeypatch, model=True)

    assert environment["EXULANICA_BUDGET_USD"] == BOUND
    assert [name for name in environment if name.startswith("EXULANICA_")] == [
        "EXULANICA_BUDGET_USD"
    ]
    assert command[-1] == "--model"
    assert "--production" in command
    assert str(LAUNCHER) in command


def test_a_run_may_lower_the_bound_it_hands_over_and_never_raise_it(tmp_path, monkeypatch):
    above = str(steplist.Decimal(BOUND) + 1)
    for index, refused in enumerate((above, "0", "-0.01", "NaN", "a dollar")):
        each = tmp_path / f"refused-{index}"
        each.mkdir()
        with pytest.raises(REHEARSE.Refused, match="--bound-usd"):
            _run(each, monkeypatch, model=True, bound_usd=refused)
    lower = str(steplist.Decimal(BOUND) / 10)
    _, environment = _launch(tmp_path, monkeypatch, model=True, bound_usd=lower)
    assert environment["EXULANICA_BUDGET_USD"] == lower


def test_a_run_without_a_model_asks_for_a_production_build_and_hands_over_no_bound(
    tmp_path, monkeypatch
):
    command, environment = _launch(tmp_path, monkeypatch, model=False)

    assert not [name for name in environment if name.startswith("EXULANICA_")]
    assert "--model" not in command
    assert "--production" in command


def _launched_state(run_dir: Path, mode: str = "production") -> dict:
    build = {
        "command": "vite build --outDir <run>/app-build --emptyOutDir",
        "vite": "vite/6.4.3",
        "seconds": 3.5,
        "development_token_in_environment": False,
        "index_html_sha256": "a" * 64,
        "scripts": {"index.js": "b" * 64},
    }
    return {
        "run_dir": str(run_dir),
        "ports": {"database": 19205, "api": 19206, "vite": 19207, "browser": 19208},
        "app": {
            "mode": mode,
            "build": build,
            "served_index_sha256": "a" * 64,
            "served_index_is_the_build": True,
        },
    }


def test_the_run_takes_the_launchers_production_build_and_keeps_what_the_preview_served(
    tmp_path, monkeypatch
):
    run = _run(tmp_path, monkeypatch, model=False)
    run.state = _launched_state(tmp_path / "launcher-run")
    run.preview_port = run.state["ports"]["vite"]
    asked: list[str] = []
    monkeypatch.setattr(
        REHEARSE, "wait_http", lambda url, seconds: (asked.append(url), (200, {}))[1]
    )

    run.take_build()

    assert run.build_directory == tmp_path / "launcher-run" / "app-build"
    assert run.build["mode"] == "production"
    assert run.build["served_index_sha256"] == run.build["index_html_sha256"]
    assert run.build["served_index_is_the_build"] is True
    assert run.build["development_token_in_environment"] is False
    assert asked == ["http://localhost:19207/api/healthz"]


def test_a_launcher_that_served_no_production_build_is_refused(tmp_path, monkeypatch):
    run = _run(tmp_path, monkeypatch, model=False)
    run.state = _launched_state(tmp_path / "launcher-run", mode="development")
    run.preview_port = run.state["ports"]["vite"]

    with pytest.raises(REHEARSE.Refused, match="no production build"):
        run.take_build()


def test_the_leak_check_reads_the_production_build_as_well_as_the_run_directory(
    tmp_path, monkeypatch
):
    run = _run(tmp_path, monkeypatch, model=False)
    run.token = "a-synthetic-workspace-token"
    run.build_directory = tmp_path / "launcher-run" / "app-build"
    (run.build_directory / "assets").mkdir(parents=True)
    (run.build_directory / "assets" / "main.js").write_text(f"const token = '{run.token}';")
    (run.build_directory / "index.html").write_text("<html></html>")
    (run.out / "summary.txt").write_text(f"token {run.token}")

    assert run.leak_check() == ["app-build/assets/main.js", "summary.txt"]
