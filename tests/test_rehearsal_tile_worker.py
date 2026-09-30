"""A rehearsed town passes only when the launcher's worker baked its saved tiles."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "rehearsal"))
SPEC = importlib.util.spec_from_file_location(
    "rehearsal_tile_worker", ROOT / "scripts" / "rehearsal" / "rehearse.py"
)
assert SPEC is not None and SPEC.loader is not None
REHEARSE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REHEARSE)


def _run(tmp_path: Path, events: list[dict], running: bool):
    arguments = argparse.Namespace(
        worktree=str(ROOT),
        out=str(tmp_path),
        slot=0,
        launcher=None,
        gpu_slot=None,
        model_env=None,
        bound_usd=None,
    )
    run = REHEARSE.Run(arguments)
    run.state = {"run_dir": str(tmp_path), "pids": {"tile_worker": 12345}}
    run.launcher = SimpleNamespace(
        tile_worker_events=lambda log: events,
        tile_worker_running=lambda state: running,
    )
    run.facts = {"town": {"world_id": "town-world"}}
    run.outcomes = {
        "make-town-with-values": {
            "status": "passed",
            "observations": [
                {
                    "id": "tiles-baked",
                    "ok": True,
                    "observed": {
                        "tiles": [
                            {
                                "tile_x": 0,
                                "tile_y": 0,
                                "state": "baked",
                                "baked_tile_id": "baked-tile",
                            }
                        ]
                    },
                }
            ],
        }
    }
    return run


def _bake(world: str = "town-world", status: str = "baked") -> dict:
    return {
        "component": "generated-tile-worker",
        "event": "bake",
        "world_id": world,
        "tile": [0, 0],
        "status": status,
        "baked_tile_id": "baked-tile",
    }


def test_a_bake_of_the_saved_town_from_the_running_worker_passes(tmp_path):
    run = _run(tmp_path, [_bake()], True)
    run.verify_town_worker()
    assert run.outcomes["make-town-with-values"]["observations"][-1]["ok"] is True


def test_a_startup_without_a_matching_bake_or_a_live_worker_fails(tmp_path):
    for events, running in [([], True), ([_bake("other-world")], True), ([_bake()], False)]:
        run = _run(tmp_path, events, running)
        run.verify_town_worker()
        assert run.outcomes["make-town-with-values"]["observations"][-1]["ok"] is False
