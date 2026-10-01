"""An independent client keeps a world project in one process and resumes it in another.

Both processes run the standard-library client with ``-S -s -E`` against the real application on a
loopback socket, as the runtime role a deployment uses. They share nothing but the server and a
note of ids: the second finds the same accepted edit, by id and result digest, corrects, deletes
and assembles, and the rows are then checked from the database rather than from the client's
own report.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest
from exulanica.api.app import create_app

import project_context_support as support
from project_context_support import OWNER
from test_developer_client import CLIENT_ROOT, _serving

pytestmark = pytest.mark.postgres


@pytest.fixture
def served(tmp_path, repository, spine_schema):
    """The test client for setting up, and a second application on a loopback socket, served
    from the same services, for the client processes."""
    for api in support.projects_api(tmp_path, repository, spine_schema):
        services = support.services_for(
            api.scratch, api.grants, api.client.app.state.services.store
        )
        with _serving(create_app(services, verify=False)) as url:
            yield api, url


def _client(url: str, command: str, note, transcript, *extra: str):
    return subprocess.run(
        [
            sys.executable,
            "-S",
            "-s",
            "-E",
            "-m",
            "exulanica_client.project_context",
            command,
            "--base-url",
            url,
            "--note",
            str(note),
            "--transcript",
            str(transcript),
            *extra,
        ],
        cwd=CLIENT_ROOT,
        env={"EXULANICA_TOKEN": OWNER, "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_second_process_resumes_the_project_the_first_kept(served, tmp_path):
    api, url = served
    saved = support.starter(api)
    support.place(api, saved, "cc0.bench", "bench", "bench")
    note, first, second = tmp_path / "note.json", tmp_path / "one.json", tmp_path / "two.json"
    question = "Will the square be used at dusk?"

    recorded = _client(
        url, "record", note, first, "--entry-id", saved["entry_id"], "--question", question
    )
    assert recorded.returncode == 0, recorded.stdout + recorded.stderr
    kept = json.loads(note.read_text())
    assert kept["reference"]["kind"] == "world_edit"

    resumed = _client(url, "resume", note, second)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    record = json.loads(second.read_text())
    assert record["result"] == "confirmed"
    assert all(check["holds"] for check in record["checks"]), record["checks"]
    assert OWNER not in first.read_text() + second.read_text()

    # Held against the rows, not the client's own account.
    rows = api.repository.connection.execute(
        "select r.text from world_project_item_revision r where r.item_id=%s",
        (kept["items"]["question"],),
    ).fetchall()
    assert rows and all(row["text"] is None for row in rows)
    goal = api.repository.connection.execute(
        "select r.text from world_project_item_revision r join world_project_item i "
        "using (workspace_id, item_id) where i.item_id=%s and r.revision=i.current_revision",
        (kept["items"]["goal"],),
    ).fetchone()
    assert goal["text"] == "People rest in the shade"
