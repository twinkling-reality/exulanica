"""A crash recovery replays the newest withdrawal export only under a declaration, or refuses.

The sealed checkpoint of ``tests/test_restore_replay.py`` needs the source stopped, which a lost
source cannot be. These tests hold the export that stands in for it to the same replay, over real
PostgreSQL dumps and bytes, and to the refusals a declared recovery adds.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import threading
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.deletion.restore import (
    DECLARATION_PROFILE,
    MAX_EXPORT_LAG,
    RestoreRefused,
    checkpoint,
    export_withdrawals,
    prepare_restore,
    replay,
    verify_restore,
)
from exulanica.orchestration.installation.custody import exports, prune_exports
from exulanica.orchestration.restore import WRITERS
from exulanica.orchestration.restore import main as restore_command

from test_purge import purged as purged
from test_restore_replay import _backup, _capture, _purge_database, _restore

_LAG = dt.timedelta(minutes=10)


def _declare(tmp_path, export_path, *, incident_at=None):
    envelope = json.loads(export_path.read_bytes())
    covered = dt.datetime.fromisoformat(envelope["record"]["covered_through"])
    path = tmp_path / "custody" / f"declaration-{uuid.uuid4().hex}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "profile": DECLARATION_PROFILE,
                "declaration_id": str(uuid.uuid4()),
                "export_sha256": envelope["record_sha256"],
                "incident_at": (incident_at or covered + dt.timedelta(seconds=30)).isoformat(),
                "reason": "the source host was lost",
            }
        )
    )
    return path


def _foreign_tombstone(purged):
    """A tombstone that queues no bytes: a whole foreign workspace with nothing in it."""
    foreign = uuid.uuid4()
    with purged.database().session(foreign) as connection:
        return connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by) values (%s,'workspace',%s) "
            "returning tombstone_id, requested_at",
            (foreign, uuid.uuid4()),
        ).fetchone()


def _export(purged, tmp_path, *, database=None, directory=None, marker=None):
    return export_withdrawals(
        database or purged.database(),
        directory or tmp_path / "custody",
        restore_state_path=marker,
        backup_domains=(purged.store.root,),
    )


def _replay(purged, source, marker):
    return replay(
        purged.database(), _purge_database(purged), purged.store, source, marker, writers=WRITERS
    )


def test_declared_recovery_replays_the_export_and_reports_the_loss_window(purged, tmp_path):
    objects = list(purged.store.iter_blob_ids())
    dump, blobs = _backup(purged, tmp_path)
    deleted = purged.tombstone_the_capture(_capture(purged))
    assert purged.worker().drain().destroyed >= 3
    export, digest = _export(purged, tmp_path)
    # Accepted by the source after its newest export, then the source is lost.
    lost = _foreign_tombstone(purged)
    declaration = _declare(tmp_path, export)
    marker = tmp_path / "control" / "restore.json"
    attempt = prepare_restore(export, marker, declaration_path=declaration, max_export_lag=_LAG)
    _restore(purged, dump, blobs)
    assert all(purged.store.exists(blob) for blob in objects)
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)
    assert _replay(purged, export, marker) == attempt
    verify_restore(purged.database(), marker)
    assert not any(purged.store.exists(blob) for blob in objects)
    assert purged.rows("select 1 from tombstone where tombstone_id=%s", deleted)
    assert not purged.rows("select 1 from tombstone where tombstone_id=%s", lost["tombstone_id"])
    recovery = json.loads(marker.read_bytes())["recovery"]
    covered = dt.datetime.fromisoformat(recovery["covered_through"])
    incident = dt.datetime.fromisoformat(recovery["incident_at"])
    # The lost withdrawal is not silently lost: it falls inside the window the marker declares.
    assert covered < lost["requested_at"] <= incident
    assert recovery["loss_window_microseconds"] == (incident - covered) // dt.timedelta(
        microseconds=1
    )
    receipt = purged.rows("select * from restore_replay_receipt")[0]
    assert receipt["restore_id"] == attempt and receipt["checkpoint_sha256"] == digest


def test_an_export_takes_no_lock_and_no_seal(purged, tmp_path):
    foreign = uuid.uuid4()
    opened, release = threading.Event(), threading.Event()
    exported: list[object] = []

    def hold_an_open_tombstone_write() -> None:
        with purged.database().session(foreign) as connection, connection.transaction():
            connection.execute(
                "insert into tombstone(workspace_id,scope,requested_by) values (%s,'workspace',%s)",
                (foreign, uuid.uuid4()),
            )
            opened.set()
            release.wait(timeout=60)

    writer = threading.Thread(target=hold_an_open_tombstone_write)
    writer.start()
    try:
        assert opened.wait(timeout=30)
        # A checkpoint's exclusive lock would wait behind that open write for ever.
        runner = threading.Thread(target=lambda: exported.append(_export(purged, tmp_path)))
        runner.start()
        runner.join(timeout=30)
        assert not runner.is_alive(), "the export waited on a lock"
    finally:
        release.set()
        writer.join(timeout=30)
    path, _digest = exported[0]
    record = json.loads(path.read_bytes())["record"]
    assert {item["tombstone"]["workspace_id"] for item in record["tombstones"]} == set()
    assert not purged.rows("select * from restore_control")
    # Nothing is sealed: the write committed, and another is still accepted.
    assert purged.rows("select 1 from tombstone where workspace_id=%s", foreign)
    purged.tombstone_the_capture(_capture(purged))


def test_an_export_is_refused_without_its_declaration(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    with pytest.raises(RestoreRefused, match="declared crash recovery"):
        prepare_restore(export, marker)
    assert not marker.exists()
    # A marker written by hand without the declaration does not let replay through either.
    attempt = prepare_restore(
        export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
    )
    state = json.loads(marker.read_bytes())
    del state["recovery"]
    marker.write_text(json.dumps(state))
    with pytest.raises(RestoreRefused, match="recovery declaration"):
        _replay(purged, export, marker)
    assert attempt and not purged.rows("select * from restore_replay_receipt")


def test_a_sealed_checkpoint_takes_no_declaration(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    sealed = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), sealed)
    with pytest.raises(RestoreRefused, match="planned restore"):
        prepare_restore(
            sealed,
            tmp_path / "restore.json",
            declaration_path=_declare(tmp_path, export),
            max_export_lag=_LAG,
        )
    # A sealed source is mid-restore and is no authority for an export.
    with pytest.raises(RestoreRefused, match="sealed or replay"):
        _export(purged, tmp_path, directory=tmp_path / "later")


def test_a_lagging_or_inconsistent_authority_fails_closed(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    covered = dt.datetime.fromisoformat(
        json.loads(export.read_bytes())["record"]["covered_through"]
    )
    marker = tmp_path / "control" / "restore.json"
    late = _declare(tmp_path, export, incident_at=covered + _LAG + dt.timedelta(seconds=1))
    with pytest.raises(RestoreRefused, match="not current"):
        prepare_restore(export, marker, declaration_path=late, max_export_lag=_LAG)
    early = _declare(tmp_path, export, incident_at=covered - dt.timedelta(seconds=1))
    with pytest.raises(RestoreRefused, match="after the declared incident"):
        prepare_restore(export, marker, declaration_path=early, max_export_lag=_LAG)
    # The bound is the installation's: a declaration cannot widen it by asking for zero or less.
    with pytest.raises(RestoreRefused, match="positive and at most"):
        prepare_restore(
            export,
            marker,
            declaration_path=_declare(tmp_path, export),
            max_export_lag=dt.timedelta(0),
        )
    other = _declare(tmp_path, export)
    stated = json.loads(other.read_bytes())
    stated["export_sha256"] = "0" * 64
    other.write_text(json.dumps(stated))
    with pytest.raises(RestoreRefused, match="different export"):
        prepare_restore(export, marker, declaration_path=other, max_export_lag=_LAG)
    assert not marker.exists()


def test_a_changed_or_foreign_catalog_export_is_refused_by_name(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    original = export.read_bytes()
    changed = json.loads(original)
    changed["record"]["tombstones"] = []
    export.write_text(json.dumps(changed))
    with pytest.raises(RestoreRefused, match="digest"):
        prepare_restore(
            export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
        )
    # Re-digested under another catalog, as an export from another release would be.
    foreign = json.loads(original)
    foreign["record"]["withdrawal_catalog"] = {"profile": "another", "sha256": "0" * 64}
    foreign["record_sha256"] = hashlib.sha256(canonical_json(foreign["record"])).hexdigest()
    export.write_text(json.dumps(foreign))
    with pytest.raises(RestoreRefused, match="another withdrawal catalog"):
        prepare_restore(
            export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
        )
    assert not marker.exists()


def test_an_export_older_than_the_backup_is_refused(purged, tmp_path):
    export, _ = _export(purged, tmp_path)
    purged.tombstone_the_capture(_capture(purged))
    dump, blobs = _backup(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    prepare_restore(
        export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
    )
    _restore(purged, dump, blobs)
    with pytest.raises(RestoreRefused, match="older than the backup"):
        _replay(purged, export, marker)
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)


def _rewrite(path, change):
    """Edit an export or marker file as a careless or hostile custodian could."""
    value = json.loads(path.read_bytes())
    change(value)
    if "record" in value and "record_sha256" in value:
        value["record_sha256"] = hashlib.sha256(canonical_json(value["record"])).hexdigest()
    path.write_text(json.dumps(value))


def test_no_export_while_a_restore_is_not_complete(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    dump, blobs = _backup(purged, tmp_path)
    source = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), source)
    marker = tmp_path / "control" / "restore.json"
    prepare_restore(source, marker)
    _restore(purged, dump, blobs)
    # The restored database's own control row came from the backup and says nothing pending;
    # only the marker knows. An export now would date backup-era content as current.
    with pytest.raises(RestoreRefused, match="restore is not complete"):
        _export(purged, tmp_path, directory=tmp_path / "later", marker=marker)
    _replay(purged, source, marker)
    _export(purged, tmp_path, directory=tmp_path / "later", marker=marker)


def test_a_standby_source_is_refused(purged, tmp_path):
    from exulanica.db.session import Database

    base = purged.database().url
    # A function of the same name, found before pg_catalog on this connection's path only.
    with purged.database().unscoped() as connection:
        connection.execute(
            f'create function "{purged.scratch}".pg_is_in_recovery() returns boolean '
            "language sql as 'select true'"
        )
    try:
        standby = Database(
            url=base.replace(
                f"-csearch_path%3D{purged.scratch}%2Cpublic",
                f"-csearch_path%3D{purged.scratch}%2Cpg_catalog%2Cpublic",
            )
        )
        assert standby.url != base
        with pytest.raises(RestoreRefused, match="standby"):
            _export(purged, tmp_path, database=standby)
    finally:
        with purged.database().unscoped() as connection:
            connection.execute(f'drop function "{purged.scratch}".pg_is_in_recovery()')


def test_covered_through_is_the_transaction_start(purged, tmp_path):
    before = purged.rows("select clock_timestamp() as at")[0]["at"]
    export, _ = _export(purged, tmp_path)
    after = purged.rows("select clock_timestamp() as at")[0]["at"]
    covered = dt.datetime.fromisoformat(
        json.loads(export.read_bytes())["record"]["covered_through"]
    )
    assert before <= covered <= after


def test_a_hand_made_or_edited_recovery_does_not_replay(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    prepare_restore(
        export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
    )
    original = marker.read_bytes()
    for change, message in (
        (lambda m: m.__setitem__("recovery", {"mode": "declared"}), "no export lag bound"),
        (lambda m: m.__setitem__("recovery", None), "recovery declaration its marker records"),
        (
            lambda m: m["recovery"].__setitem__("loss_window_microseconds", 0),
            "does not match its declaration",
        ),
        (
            lambda m: m["recovery"].__setitem__("max_export_lag_microseconds", 10**12),
            "at most",
        ),
    ):
        marker.write_bytes(original)
        _rewrite(marker, change)
        with pytest.raises(RestoreRefused, match=message):
            _replay(purged, export, marker)
    assert not purged.rows("select * from restore_replay_receipt")


def test_malformed_declarations_and_exports_are_refused_by_name(purged, tmp_path):
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    for change in (
        lambda d: d.__setitem__("declaration_id", 12345),
        lambda d: d.__setitem__("incident_at", None),
        lambda d: d.__setitem__("incident_at", "2026-09-30T12:00:00"),
    ):
        declaration = _declare(tmp_path, export)
        _rewrite(declaration, change)
        with pytest.raises(RestoreRefused):
            prepare_restore(export, marker, declaration_path=declaration, max_export_lag=_LAG)
    zoneless = tmp_path / "custody" / "zoneless.json"
    zoneless.write_bytes(export.read_bytes())
    _rewrite(zoneless, lambda e: e["record"].__setitem__("covered_through", "2026-09-30T12:00:00"))
    with pytest.raises(RestoreRefused, match="time zone"):
        prepare_restore(
            zoneless, marker, declaration_path=_declare(tmp_path, zoneless), max_export_lag=_LAG
        )
    assert not marker.exists()


def test_the_lag_bound_is_capped_recorded_and_never_given_alone(purged, tmp_path):
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    with pytest.raises(RestoreRefused, match="at most"):
        prepare_restore(
            export,
            marker,
            declaration_path=_declare(tmp_path, export),
            max_export_lag=MAX_EXPORT_LAG + dt.timedelta(seconds=1),
        )
    with pytest.raises(RestoreRefused, match="declared crash recovery"):
        prepare_restore(export, marker, max_export_lag=_LAG)
    sealed = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), sealed)
    with pytest.raises(RestoreRefused, match="no declaration or lag bound"):
        prepare_restore(sealed, marker, max_export_lag=_LAG)
    assert not marker.exists()


def test_custody_is_kept_apart_from_backups_and_bounded(purged, tmp_path):
    with pytest.raises(RestoreRefused, match="backup domain"):
        _export(purged, tmp_path, directory=purged.store.root / "custody")
    custody = tmp_path / "custody"
    made = [_export(purged, tmp_path)[1] for _ in range(4)]
    (custody / "restore.json").write_text("{}")
    assert [export.sha256 for export in exports(custody)] == made[::-1]
    identity = exports(custody)[0].source_identity
    assert identity and all(export.source_identity == identity for export in exports(custody))
    # Another source, such as the database a restore replaced, keeps its newest export only.
    foreign, stale = custody / "foreign.json", custody / "foreign-stale.json"
    foreign.write_bytes(exports(custody)[0].path.read_bytes())
    stale.write_bytes(exports(custody)[-1].path.read_bytes())
    for path in (foreign, stale):
        _rewrite(path, lambda e: e["record"].__setitem__("source_identity", "0" * 64))
    paths = {export.sha256: export.path for export in exports(custody)}
    removed = prune_exports(custody, source_identity=identity, keep=2, referenced={made[0]})
    assert set(removed) == {paths[made[1]], stale}
    assert {export.sha256 for export in exports(custody)} >= {made[0], made[2], made[3]}
    assert foreign.exists() and (custody / "restore.json").exists()


def test_a_database_older_than_custody_cannot_export_or_prune(purged, tmp_path):
    """A restored database that has not replayed, or another database, lacks what custody holds."""
    dump, blobs = _backup(purged, tmp_path)
    purged.tombstone_the_capture(_capture(purged))
    real, _ = _export(purged, tmp_path)
    _restore(purged, dump, blobs)
    # No marker names this restore: the database alone is older than the newest export.
    with pytest.raises(RestoreRefused, match="older than that export"):
        _export(purged, tmp_path)
    assert [export.path for export in exports(tmp_path / "custody")] == [real]


def _profile_naming(tmp_path, marker, monkeypatch):
    """A single-host profile whose restore marker is ``marker``, declared to the commands."""
    from pathlib import Path as _Path

    shipped = _Path(__file__).resolve().parents[1] / "deploy" / "profiles" / "single-host.json"
    document = json.loads(shipped.read_text())
    document["recovery"]["restore_state_path"] = str(marker)
    path = tmp_path / "profile.json"
    path.write_text(json.dumps(document))
    monkeypatch.setenv("EXULANICA_INSTALLATION_PROFILE", str(path))
    monkeypatch.delenv("EXULANICA_RESTORE_STATE_PATH", raising=False)
    # Where _export writes: a declared recovery replays the newest export there.
    monkeypatch.setenv("EXULANICA_CUSTODY_DIRECTORY", str(tmp_path / "custody"))
    return path


def test_the_receipt_and_the_command_state_the_loss_window(purged, tmp_path, capsys, monkeypatch):
    dump, blobs = _backup(purged, tmp_path)
    purged.tombstone_the_capture(_capture(purged))
    export, _ = _export(purged, tmp_path)
    declaration = _declare(tmp_path, export)
    marker = tmp_path / "control" / "restore.json"
    monkeypatch.setenv("EXULANICA_DATABASE_URL", purged.database().url)
    monkeypatch.setenv("EXULANICA_DATA_DIR", str(tmp_path / "unused-data"))
    _profile_naming(tmp_path, marker, monkeypatch)
    restore_command(
        [
            "prepare",
            "--checkpoint",
            str(export),
            "--marker",
            str(marker),
            "--declaration",
            str(declaration),
            "--max-export-lag-seconds",
            "600",
        ]
    )
    assert "are not restored" in capsys.readouterr().out
    _restore(purged, dump, blobs)
    _replay(purged, export, marker)
    receipt = purged.rows("select * from restore_replay_receipt")[0]
    recovery = json.loads(marker.read_bytes())["recovery"]
    assert receipt["recovery_mode"] == "declared"
    assert receipt["covered_through"] == dt.datetime.fromisoformat(recovery["covered_through"])
    assert receipt["incident_at"] == dt.datetime.fromisoformat(recovery["incident_at"])
    assert receipt["loss_window_microseconds"] == recovery["loss_window_microseconds"]
    assert receipt["max_export_lag_microseconds"] == 600_000_000


def test_a_planned_restore_receipt_records_no_window(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    source = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), source)
    marker = tmp_path / "control" / "restore.json"
    prepare_restore(source, marker)
    _replay(purged, source, marker)
    receipt = purged.rows("select * from restore_replay_receipt")[0]
    assert receipt["recovery_mode"] is None and receipt["loss_window_microseconds"] is None


def test_more_malformed_inputs_are_refused_by_name(purged, tmp_path):
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    for change in (
        lambda d: d.__setitem__("reason", 1.5),
        lambda d: d.__setitem__("reason", "  "),
        lambda d: d.__setitem__("note", "an extra field"),
    ):
        declaration = _declare(tmp_path, export)
        _rewrite(declaration, change)
        with pytest.raises(RestoreRefused):
            prepare_restore(export, marker, declaration_path=declaration, max_export_lag=_LAG)
    prepare_restore(
        export, marker, declaration_path=_declare(tmp_path, export), max_export_lag=_LAG
    )
    original = marker.read_bytes()
    _rewrite(marker, lambda m: m["recovery"].__setitem__("max_export_lag_microseconds", 10**30))
    with pytest.raises(RestoreRefused, match="at most"):
        _replay(purged, export, marker)
    marker.write_bytes(original)
    _rewrite(marker, lambda m: m.__setitem__("restore_id", 12345))
    with pytest.raises(RestoreRefused, match="attempt identity"):
        verify_restore(purged.database(), marker)


def test_an_installation_starts_with_a_marker_that_declares_no_restore(purged, tmp_path):
    from exulanica.deletion.restore import initialise_restore_state

    marker = tmp_path / "control" / "restore.json"
    with pytest.raises(RestoreRefused, match="unavailable"):
        verify_restore(purged.database(), marker)
    assert initialise_restore_state(marker) is True
    assert initialise_restore_state(marker) is False
    verify_restore(purged.database(), marker)
    _export(purged, tmp_path, marker=marker)
    # A planned restore may begin from it, and the marker then refuses until replayed.
    source = tmp_path / "custody" / "checkpoint.json"
    checkpoint(purged.database(), source)
    prepare_restore(source, marker)
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)


def test_the_command_takes_the_profiles_bound_and_marker_and_may_only_lower_the_bound(
    purged, tmp_path, monkeypatch
):
    export, _ = _export(purged, tmp_path)
    marker = tmp_path / "control" / "restore.json"
    monkeypatch.setenv("EXULANICA_DATABASE_URL", purged.database().url)
    declaration = _declare(tmp_path, export)
    arguments = ["prepare", "--checkpoint", str(export), "--declaration", str(declaration)]
    # Without a profile a declared recovery has no bound to take.
    monkeypatch.delenv("EXULANICA_INSTALLATION_PROFILE", raising=False)
    with pytest.raises(SystemExit):
        restore_command([*arguments, "--marker", str(marker), "--max-export-lag-seconds", "60"])
    _profile_naming(tmp_path, marker, monkeypatch)
    with pytest.raises(SystemExit):
        restore_command([*arguments, "--max-export-lag-seconds", "601"])
    with pytest.raises(SystemExit):
        restore_command([*arguments, "--marker", str(tmp_path / "elsewhere.json")])
    restore_command([*arguments, "--max-export-lag-seconds", "300"])
    assert json.loads(marker.read_bytes())["recovery"]["max_export_lag_microseconds"] == 300_000_000
    marker.unlink()
    restore_command(arguments)
    assert json.loads(marker.read_bytes())["recovery"]["max_export_lag_microseconds"] == 600_000_000


def test_an_open_withdrawal_refuses_the_export(purged, tmp_path):
    """A session signed out after the backup is current again in a restore that has not replayed."""
    from test_installation_recovery import _sign_in_and_out, _sign_out

    session = _sign_in_and_out(purged, sign_out=False)
    dump, blobs = _backup(purged, tmp_path)
    _sign_out(purged, session)
    _export(purged, tmp_path)
    _restore(purged, dump, blobs)
    with pytest.raises(RestoreRefused, match="older than that export"):
        _export(purged, tmp_path)


def test_a_declared_prepare_replays_only_the_newest_export_in_custody(
    purged, tmp_path, monkeypatch
):
    import shutil

    older, _ = _export(purged, tmp_path)
    purged.tombstone_the_capture(_capture(purged))
    newer, _ = _export(purged, tmp_path)
    copied = tmp_path / "elsewhere" / "older.json"
    copied.parent.mkdir()
    shutil.copy(older, copied)
    marker = tmp_path / "control" / "restore.json"
    monkeypatch.setenv("EXULANICA_DATABASE_URL", purged.database().url)
    _profile_naming(tmp_path, marker, monkeypatch)

    def prepare(export):
        declaration = _declare(tmp_path, export)
        restore_command(["prepare", "--checkpoint", str(export), "--declaration", str(declaration)])

    # Older than custody's newest, in custody or copied alone into another directory.
    for export in (older, copied):
        with pytest.raises(RestoreRefused, match="not the newest"):
            prepare(export)
    assert not marker.exists()
    monkeypatch.delenv("EXULANICA_CUSTODY_DIRECTORY")
    with pytest.raises(SystemExit):
        prepare(newer)
    monkeypatch.setenv("EXULANICA_CUSTODY_DIRECTORY", str(tmp_path / "custody"))
    prepare(newer)
    assert json.loads(marker.read_bytes())["state"] == "pending"
