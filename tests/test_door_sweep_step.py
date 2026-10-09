"""The maintenance pass runs the door's sweep as one of its steps, and says what it did.

Each pass reports the sweep in its status file: not configured where no runtime role is given, else
how many grants it settled and how many departures it wrote, and a failure code while a grant it
could not settle is held back (later passes take it after the rest). The sweep itself is held
against PostgreSQL in ``tests/test_door_world_decides_postgres.py``; here the pass's own wiring,
with the other steps standing still and only the door's own failure codes judged, so a step added
later changes nothing here.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from exulanica.orchestration.installation import maintenance as maintenance_module
from exulanica.orchestration.installation.maintenance import Maintenance

_OTHER_STEPS = (
    "_check_role",
    "_check_definer",
    "_export",
    "_purge",
    "_purge_backup_copies",
    "_backup",
    "_verify",
    "_retain",
    "_queues",
    "_unlisted",
)


def _pass(tmp_path: Path, monkeypatch, runtime_url: str | None) -> dict:
    for step in _OTHER_STEPS:
        monkeypatch.setattr(Maintenance, step, lambda self, status: None)
    runner = Maintenance(
        backup_url="postgresql://backup@nowhere/exulanica",
        purge_url=None,
        custody=tmp_path / "custody",
        backup_directory=tmp_path / "sets",
        status_path=tmp_path / "status" / "maintenance.json",
        stores=None,  # type: ignore[arg-type]
        policy=None,  # type: ignore[arg-type]
        identity={},
        restore_state_path=None,
        backup_domains=(),
        runtime_url=runtime_url,
    )
    return runner.run_pass()


def _door_failures(status: dict) -> list[str]:
    return [code for code in status["failures"] if code.startswith("door_sweep")]


def test_a_pass_with_no_runtime_role_says_the_sweep_is_not_configured(tmp_path, monkeypatch):
    status = _pass(tmp_path, monkeypatch, None)
    assert status["door_sweep"] == {"configured": False}
    assert _door_failures(status) == []


STUCK = uuid.UUID("0e2c6f0a-8d4b-4c1e-9a7f-3b5d2e1c4a90")


@pytest.mark.parametrize(
    ("swept", "failures"),
    [
        ({"grants": 2, "departures": 3, "failed": 0, "stuck": []}, []),
        ({"grants": 1, "departures": 1, "failed": 1, "stuck": [STUCK]}, ["door_sweep_incomplete"]),
        ({"grants": 1, "departures": 0, "failed": 0, "stuck": [STUCK]}, ["door_sweep_incomplete"]),
    ],
)
def test_a_pass_sweeps_as_the_runtime_role_and_reports_what_it_settled(
    tmp_path, monkeypatch, swept, failures
):
    seen = []

    def sweep(finder, runtime, *, deferred=()):
        seen.append((finder.url, runtime.url, tuple(deferred)))
        return dict(swept)

    monkeypatch.setattr(maintenance_module, "sweep", sweep)
    status = _pass(tmp_path, monkeypatch, "postgresql://runtime@nowhere/exulanica")
    assert seen == [
        ("postgresql://backup@nowhere/exulanica", "postgresql://runtime@nowhere/exulanica", ())
    ]
    assert status["door_sweep"] == {
        "configured": True,
        **swept,
        "stuck": [str(grant_id) for grant_id in swept["stuck"]],
    }
    assert _door_failures(status) == failures


def test_the_next_pass_takes_the_grants_the_last_one_left_stuck_after_the_rest(
    tmp_path, monkeypatch
):
    passed = []

    def sweep(finder, runtime, *, deferred=()):
        passed.append(tuple(deferred))
        return {"grants": 1, "departures": 0, "failed": 0, "stuck": [STUCK]}

    for step in _OTHER_STEPS:
        monkeypatch.setattr(Maintenance, step, lambda self, status: None)
    monkeypatch.setattr(maintenance_module, "sweep", sweep)
    runner = Maintenance(
        backup_url="postgresql://backup@nowhere/exulanica",
        purge_url=None,
        custody=tmp_path / "custody",
        backup_directory=tmp_path / "sets",
        status_path=tmp_path / "status" / "maintenance.json",
        stores=None,  # type: ignore[arg-type]
        policy=None,  # type: ignore[arg-type]
        identity={},
        restore_state_path=None,
        backup_domains=(),
        runtime_url="postgresql://runtime@nowhere/exulanica",
    )
    runner.run_pass()
    runner.run_pass()
    assert passed == [(), (STUCK,)]


def test_a_pass_sweeps_before_it_backs_up(tmp_path, monkeypatch):
    order = []
    for step in _OTHER_STEPS:
        monkeypatch.setattr(Maintenance, step, lambda self, status, _step=step: order.append(_step))
    monkeypatch.setattr(
        Maintenance, "_door_sweep", lambda self, status: order.append("_door_sweep")
    )
    Maintenance(
        backup_url="postgresql://backup@nowhere/exulanica",
        purge_url=None,
        custody=tmp_path / "custody",
        backup_directory=tmp_path / "sets",
        status_path=tmp_path / "status" / "maintenance.json",
        stores=None,  # type: ignore[arg-type]
        policy=None,  # type: ignore[arg-type]
        identity={},
        restore_state_path=None,
        backup_domains=(),
    ).run_pass()
    assert order.index("_door_sweep") < order.index("_backup")
