"""A program outside the application reads a comparison started from it, its runs and decisions.

The developer client in ``clients/python`` (``python -m exulanica_client comparisons``) runs as a
separate process with ``-S -s -E``, so no site-packages directory is importable, holding a token
granted ``world.read`` alone, against the real application served over a loopback socket. The
comparison it reads was started through the start route and played by the host's worker with a
scripted model. What it reports is then held to the repository rather than to its own account:
every run it read is a run the comparison recorded, and the asks it counted are the receipts the
comparison stored for that run.
"""

from __future__ import annotations

import json
import subprocess
import sys
import uuid

import pytest
from exulanica.api.app import create_app
from exulanica.db.session import set_workspace

import test_developer_client as developer
import test_society_comparison_start_postgres as start_tests
import test_society_stay_requests_api as stays

saved_world = start_tests.saved_world
started = start_tests.started
pytestmark = pytest.mark.postgres


def _asked(world: dict, run_id: str) -> int:
    """The receipts the comparison stored for a run whose model was asked, read as the owner."""
    connection = world["connection"]
    set_workspace(connection, world["workspace"])
    return connection.execute(
        "select count(*) as n from society_comparison_decision where workspace_id=%s "
        "and world_id=%s and run_id=%s and receipt->'provider' <> 'null'::jsonb",
        (world["workspace"], world["binding"].world_id, uuid.UUID(run_id)),
    ).fetchone()["n"]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_client_reads_a_started_comparison_its_runs_and_decisions(started, tmp_path):
    world, client = started["world"], started["client"]
    stays._inhabited(world, client)
    body = start_tests._body()
    assert start_tests._start(started, body).status_code == 201
    assert start_tests._worker(started).run_once(world["workspace"]) is True
    transcript = tmp_path / "comparison.json"
    with developer._serving(create_app(client.app.state.services, verify=False)) as url:
        run = subprocess.run(
            [
                sys.executable,
                "-S",
                "-s",
                "-E",
                "-m",
                "exulanica_client",
                "comparisons",
                "--base-url",
                url,
                "--world",
                world["binding"].world_id,
                "--version",
                str(world["binding"].version_id),
                "--transcript",
                str(transcript),
            ],
            cwd=developer.CLIENT_ROOT,
            env={"EXULANICA_TOKEN": start_tests.READER_TOKEN, "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=120,
        )
    assert run.returncode == 0, run.stdout + run.stderr
    record = json.loads(transcript.read_text())
    assert record["result"] == "confirmed"
    assert all(check["holds"] for check in record["checks"]), record["checks"]
    assert record["comparison"]["comparison_id"] == body["comparison_id"]
    assert record["comparison"]["start"]["state"] == "finished"
    # Only reads: the token holds world.read alone, and the client sent nothing else.
    assert {exchange["method"] for exchange in record["exchanges"]} == {"GET"}
    [model_run] = record["runs_read"]
    assert model_run["arm"] == "model_a"
    # Held against the repository, not the client's own account of what it read.
    assert model_run["asked"] == _asked(world, model_run["run_id"]) > 0
    everything = run.stdout + run.stderr + transcript.read_text()
    assert start_tests.READER_TOKEN not in everything
