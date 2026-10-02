"""``exulanica-installation init --adopt``: a marker for an installed database that never had one.

On an installed database a missing marker is lost custody, so a database installed without a
profile had no command that gave it one. Adopting writes the marker the database's own restore
record supports, and every other case is refused with nothing written:

*   no ``restore_control`` row, no receipt: ``none``;
*   a ``complete`` row whose receipt matches it: ``complete``, with that attempt in ``completed``,
    so the same checkpoint is never restored again;
*   refused: a marker already there, no schema, a schema before the restore controls, a sealed
    checkpoint, a replay under way, a completed restore without a receipt or with another's, and
    receipts with no control row.

Each case writes the scratch schema's restore rows itself and removes them after, because the
schema is shared by the session and a sealed row refuses every tombstone written beside it.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.db.session import Database
from exulanica.deletion.restore import RestoreRefused, completed_restores, prepare_restore
from exulanica.env import env_get
from exulanica.orchestration.installation.cli import main

from test_installation_facts import PROFILES
from tests_support_api import scratch_database

pytestmark = pytest.mark.postgres

_DIGEST = "a" * 64
_OTHER = "b" * 64


@pytest.fixture
def adopting(spine_schema, monkeypatch, tmp_path) -> Iterator[tuple[Database, Path]]:
    """The scratch schema's database, the profile pointed at a marker under ``tmp_path``, and the
    restore rows cleared before and after."""
    _psycopg, scratch = spine_schema
    database = scratch_database(scratch)
    marker = _profile(monkeypatch, tmp_path)
    monkeypatch.setenv("EXULANICA_RESTORE_DATABASE_URL", database.url)
    _clear(database)
    try:
        yield database, marker
    finally:
        _clear(database)


def _profile(monkeypatch, tmp_path):
    document = json.loads((PROFILES / "single-host.json").read_text())
    marker = tmp_path / "control" / "restore.json"
    document["recovery"]["restore_state_path"] = str(marker)
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(document))
    monkeypatch.setenv("EXULANICA_INSTALLATION_PROFILE", str(profile))
    monkeypatch.delenv("EXULANICA_RESTORE_STATE_PATH", raising=False)
    return marker


def _clear(database: Database) -> None:
    with database.unscoped() as connection:
        connection.execute("delete from restore_replay_receipt")
        connection.execute("delete from restore_control")


def _control(
    database: Database,
    state: str,
    restore_id: uuid.UUID | None,
    checkpoint_id: uuid.UUID,
    digest: str = _DIGEST,
) -> None:
    with database.unscoped() as connection:
        connection.execute(
            "insert into restore_control (checkpoint_id,checkpoint_sha256,state,restore_id) "
            "values (%s,%s,%s,%s)",
            (checkpoint_id, digest, state, restore_id),
        )


def _receipt(
    database: Database,
    restore_id: uuid.UUID,
    checkpoint_id: uuid.UUID,
    digest: str,
    completed_at: str = "2026-01-01T00:00:00Z",
) -> None:
    with database.unscoped() as connection:
        connection.execute(
            "insert into restore_replay_receipt "
            "(restore_id,checkpoint_id,checkpoint_sha256,tombstone_count,completed_at) "
            "values (%s,%s,%s,0,%s)",
            (restore_id, checkpoint_id, digest, completed_at),
        )


def _refused(capsys, marker, words: str) -> None:
    assert main(["init", "--adopt"]) == 1
    error = capsys.readouterr().err
    assert words in error and "nothing was written" in error, error
    assert not marker.exists()


def test_a_database_with_no_restore_record_adopts_none(adopting, capsys):
    _database, marker = adopting
    assert main(["init", "--adopt"]) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "none"
    written = json.loads(marker.read_text())
    assert written["state"] == "none" and "adopted_at" in written
    # A second adoption finds the marker and refuses rather than writing over it.
    assert main(["init", "--adopt"]) == 1
    assert "already exists" in capsys.readouterr().err
    assert json.loads(marker.read_text()) == written


def _sealed_checkpoint(path: Path, checkpoint_id: uuid.UUID) -> str:
    """A sealed checkpoint with no tombstones, so a digest names a real checkpoint file."""
    record = {
        "profile": "exulanica.restore-tombstone-checkpoint/v1",
        "checkpoint_id": str(checkpoint_id),
        "tombstones": [],
    }
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    path.write_bytes(
        canonical_json(
            {
                "profile": "exulanica.digest-bound-record/v1",
                "record": record,
                "record_sha256": digest,
                "state": "sealed",
            }
        )
    )
    return digest


def test_completed_restores_adopt_complete_and_none_is_ever_reopened(adopting, tmp_path):
    """Two restores completed here: the earlier one's receipt outlives its control row, which the
    later one replaced. A marker lost and adopted must still refuse both checkpoints."""
    database, marker = adopting
    earlier, latest = tmp_path / "earlier.json", tmp_path / "latest.json"
    earlier_id, latest_id = uuid.uuid4(), uuid.uuid4()
    earlier_digest = _sealed_checkpoint(earlier, earlier_id)
    latest_digest = _sealed_checkpoint(latest, latest_id)
    earlier_restore, latest_restore = uuid.uuid4(), uuid.uuid4()
    _receipt(database, earlier_restore, earlier_id, earlier_digest, "2026-01-01T00:00:00Z")
    _control(database, "complete", latest_restore, latest_id, latest_digest)
    _receipt(database, latest_restore, latest_id, latest_digest, "2026-02-01T00:00:00Z")
    assert main(["init", "--adopt"]) == 0
    written = json.loads(marker.read_text())
    assert (written["state"], written["restore_id"], written["checkpoint_id"]) == (
        "complete",
        str(latest_restore),
        str(latest_id),
    )
    assert completed_restores(written) == [
        {"checkpoint_sha256": earlier_digest, "restore_id": str(earlier_restore)},
        {"checkpoint_sha256": latest_digest, "restore_id": str(latest_restore)},
    ]
    for checkpoint in (earlier, latest):
        with pytest.raises(RestoreRefused, match="already complete"):
            prepare_restore(checkpoint, marker)


@pytest.mark.parametrize("state", ["sealed", "replaying"])
def test_a_restore_in_progress_is_refused(adopting, capsys, state):
    database, marker = adopting
    restore_id = None if state == "sealed" else uuid.uuid4()
    _control(database, state, restore_id, uuid.uuid4())
    _refused(capsys, marker, f"restore control is {state}")


def test_a_completed_restore_without_a_receipt_is_refused(adopting, capsys):
    database, marker = adopting
    _control(database, "complete", uuid.uuid4(), uuid.uuid4())
    _refused(capsys, marker, "no replay receipt that matches it")


@pytest.mark.parametrize("differs", ["checkpoint_id", "checkpoint_sha256"])
def test_a_completed_restore_whose_receipt_differs_is_refused(adopting, capsys, differs):
    database, marker = adopting
    restore_id, checkpoint_id = uuid.uuid4(), uuid.uuid4()
    _control(database, "complete", restore_id, checkpoint_id)
    _receipt(
        database,
        restore_id,
        uuid.uuid4() if differs == "checkpoint_id" else checkpoint_id,
        _OTHER if differs == "checkpoint_sha256" else _DIGEST,
    )
    _refused(capsys, marker, "no replay receipt that matches it")


def test_receipts_without_a_control_row_are_refused(adopting, capsys):
    database, marker = adopting
    _receipt(database, uuid.uuid4(), uuid.uuid4(), _DIGEST)
    _refused(capsys, marker, "receipts but no restore control row")


@pytest.mark.parametrize("schema", ["empty", "before_restore_controls"])
def test_a_database_without_the_schema_or_its_restore_controls_is_refused(
    adopting, capsys, monkeypatch, schema
):
    database, marker = adopting
    name = f"adopt_{schema}_{uuid.uuid4().hex[:8]}"
    with database.unscoped() as connection:
        connection.execute(f"create schema {name}")
        if schema == "before_restore_controls":
            connection.execute(f"create table {name}.schema_migrations (version text)")
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    options = urllib.parse.quote(f"-csearch_path={name}", safe="")
    monkeypatch.setenv(
        "EXULANICA_RESTORE_DATABASE_URL", f"{base}{'&' if '?' in base else '?'}options={options}"
    )
    try:
        words = "no applied schema" if schema == "empty" else "predates the restore controls"
        _refused(capsys, marker, words)
    finally:
        with database.unscoped() as connection:
            connection.execute(f"drop schema {name} cascade")


def test_init_without_adopt_still_refuses_an_installed_database_and_names_adopt(adopting, capsys):
    _database, marker = adopting
    assert main(["init"]) == 1
    error = capsys.readouterr().err
    assert "missing on an installed database" in error and "init --adopt" in error
    assert not marker.exists()
