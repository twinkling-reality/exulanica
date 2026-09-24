"""Offline restoration with an external deletion checkpoint, over real PostgreSQL and bytes."""

from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from dataclasses import replace

import psycopg
import pytest
from exulanica.api.app import create_app
from exulanica.api.authorisation import load_token_directory
from exulanica.api.services import Services
from exulanica.db.local.cluster import client_program
from exulanica.db.local.refusals import LocalDatabaseRefused
from exulanica.db.roles import provision_purge_role, provision_runtime_role
from exulanica.deletion.restore import (
    RestoreRefused,
    checkpoint,
    prepare_restore,
    replay,
    verify_restore,
)
from exulanica.graph import read_snapshot
from exulanica.ingest.scenes import run_scene_grouping
from fastapi.testclient import TestClient

from test_purge import (
    _APP_PASSWORD,
    _APP_ROLE,
    _PURGE_PASSWORD,
    _PURGE_ROLE,
)
from test_purge import (
    purged as purged,
)
from tests_support_api import EVERY_PERMISSION


def _purge_database(purged):
    return purged.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD)


def _app(purged, marker):
    token = "restore-test-owner-token-" + uuid.uuid4().hex
    services = Services(
        database=purged.database(),
        readonly_database=purged.database(),
        store=purged.store,
        tokens=load_token_directory(
            {
                "EXULANICA_API_TOKENS": json.dumps(
                    {
                        token: {
                            "workspace_id": str(purged.workspace_id),
                            "actor": str(uuid.uuid4()),
                            "permissions": EVERY_PERMISSION,
                        }
                    }
                )
            }
        ),
        executor_shares_the_write_role=True,
        model_client=None,
        restore_state_path=marker,
    )
    return create_app(services, verify=False), {"Authorization": f"Bearer {token}"}


def _postgres_tool(name):
    # The PostgreSQL 18 client, from the places exulanica.db.local.cluster states, never the older
    # unversioned client Homebrew leaves first on PATH. A missing compatible client is a failed
    # real-restore prerequisite, never a skipped proof.
    try:
        return client_program(name)
    except LocalDatabaseRefused as missing:
        pytest.fail(missing.detail)


def _backup(purged, tmp_path):
    """Dump the way an operator's backup does, privileges included.

    The restore below drops and rebuilds the session's shared schema, so whatever this dump omits
    is missing from every test that runs after this file in the same process. Dumped without
    privileges, the migrations' own ``revoke all on function ... from public`` went with it and
    every SECURITY DEFINER function came back executable by PUBLIC, which is the escalation those
    revokes exist to prevent: the definer-function privilege test passes alone and fails after
    this file. ``--no-owner`` stays, because the restoring role owns the rebuilt schema.
    """
    dump = tmp_path / "before-deletion.sql"
    completed = subprocess.run(
        [
            _postgres_tool("pg_dump"),
            "--dbname",
            purged.database().url,
            "--schema",
            purged.scratch,
            "--no-owner",
            "--file",
            str(dump),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    blobs = tmp_path / "before-deletion-blobs"
    shutil.copytree(purged.store.root, blobs)
    return dump, blobs


def _restore(purged, dump, blobs):
    purged.repository.connection.execute(f'drop schema "{purged.scratch}" cascade')
    restored = subprocess.run(
        [
            _postgres_tool("psql"),
            "--dbname",
            purged.database().url,
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--file",
            str(dump),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert restored.returncode == 0, restored.stderr
    shutil.rmtree(purged.store.root)
    shutil.copytree(blobs, purged.store.root)
    with purged.database().unscoped() as connection:
        provision_runtime_role(connection, role=_APP_ROLE, password=_APP_PASSWORD)
        provision_purge_role(connection, role=_PURGE_ROLE, password=_PURGE_PASSWORD)
    # Provisioning grants; it never revokes PUBLIC's execute, because the migrations do that where
    # they create the function. So a restore is the one moment those revokes can be lost, and this
    # schema is the session's, shared with every test that runs after this file. Asked as a
    # property rather than a list of names: an owner-rights function added later is covered by it
    # without anyone remembering to come back here. A null proacl is the default ACL, which grants
    # PUBLIC execute, and grantee 0 is PUBLIC.
    executable_by_public = purged.rows(
        "select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace, "
        "lateral aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a "
        "where n.nspname=%s and p.prosecdef and a.grantee=0 and a.privilege_type='EXECUTE' "
        "order by p.proname",
        purged.scratch,
    )
    assert executable_by_public == [], executable_by_public


def _capture(purged):
    return purged.rows("select capture_id from capture")[0]["capture_id"]


def test_a_real_predeletion_restore_replays_bytes_spans_graph_and_aggregates(purged, tmp_path):
    run_scene_grouping(purged.repository)
    before = read_snapshot(purged.repository.connection, purged.workspace_id, purged.store)
    assert before.occurrences and before.scene_groups
    spans = purged.rows("select span_id from evidence_span")
    assert spans
    objects = list(purged.store.iter_blob_ids())
    assert len(objects) >= 3
    dump, blobs = _backup(purged, tmp_path)
    original_id = purged.tombstone_the_capture(_capture(purged))
    assert purged.worker().drain().destroyed >= 3
    source = tmp_path / "independent-journal" / "checkpoint.json"
    marker = tmp_path / "independent-control" / "restore.json"
    digest = checkpoint(purged.database(), source)
    attempt = prepare_restore(source, marker)
    _restore(purged, dump, blobs)
    assert purged.rows("select count(*) as n from tombstone")[0]["n"] == 0
    assert all(purged.store.exists(blob) for blob in objects)
    assert read_snapshot(purged.repository.connection, purged.workspace_id).occurrences
    # The database gate itself was rolled back with the backup; only the independent marker
    # remembers this restore. It must refuse before replay even though the old graph is live.
    assert not purged.rows("select * from restore_control")
    pending_app, _ = _app(purged, marker)
    with pytest.raises(RestoreRefused, match="pending"), TestClient(pending_app):
        pass
    assert (
        replay(purged.database(), _purge_database(purged), purged.store, source, marker) == attempt
    )
    assert not any(purged.store.exists(blob) for blob in objects)
    assert purged.rows("select tombstone_id from tombstone where tombstone_id=%s", original_id)
    after = read_snapshot(purged.repository.connection, purged.workspace_id, purged.store)
    assert not after.occurrences and not after.scene_groups
    assert all(row["stale"] for row in purged.rows("select stale from derived_artifact"))
    app, headers = _app(purged, marker)
    with TestClient(app) as client:
        assert client.get("/graph", headers=headers).json()["occurrences"] == []
        for span in spans:
            assert client.get(f"/evidence/{span['span_id']}", headers=headers).status_code == 410
    receipt = purged.rows("select * from restore_replay_receipt")[0]
    assert receipt["restore_id"] == attempt and receipt["checkpoint_sha256"] == digest
    assert receipt["tombstone_count"] == 1
    count = purged.rows("select count(*) as n from tombstone")[0]["n"]
    replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    assert purged.rows("select count(*) as n from tombstone")[0]["n"] == count
    assert purged.rows("select * from restore_replay_receipt") == [receipt]


def test_partial_replay_refuses_startup_before_any_worker_can_start(purged, tmp_path, monkeypatch):
    purged.tombstone_the_capture(_capture(purged))
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(purged.database(), source)
    prepare_restore(source, marker)
    # One destructive operation fails after replayed tombstones have committed. The real store
    # is restored before testing startup; refusal therefore comes from incomplete replay state.
    with monkeypatch.context() as mutation:
        mutation.setattr(
            "exulanica.deletion.worker.privileged_purger",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk offline")),
        )
        with pytest.raises(RestoreRefused, match="purge incomplete"):
            replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    assert not purged.rows("select * from restore_replay_receipt")
    app, _ = _app(purged, marker)
    started = []
    monkeypatch.setattr(Services, "build_derivative_worker", lambda _self: started.append(True))
    with pytest.raises(RestoreRefused, match="pending"), TestClient(app):
        pass
    assert started == []
    replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    verify_restore(purged.database(), marker)


def test_completed_database_jobs_do_not_certify_restored_old_object_bytes(purged, tmp_path):
    objects = {blob: purged.store.get(blob) for blob in purged.store.iter_blob_ids()}
    purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    assert {row["state"] for row in purged.rows("select state from purge_job")} == {"done"}
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(purged.database(), source)
    prepare_restore(source, marker)
    for payload in objects.values():
        purged.store.put_bytes(payload)
    replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    assert not any(purged.store.exists(blob) for blob in objects)
    assert len(purged.rows("select * from restore_replay_receipt")) == 1


def test_checkpoint_seals_raw_sql_and_only_administrators_can_certify_restore(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    foreign = uuid.uuid4()
    statement = "insert into tombstone(workspace_id,scope,requested_by) values (%s,'workspace',%s)"
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="workspace context"):
        purged.repository.connection.execute(statement, (foreign, uuid.uuid4()))
    # Raw administrative SQL still declares the workspace whose tombstone it writes.
    with purged.database().session(foreign) as connection:
        connection.execute(statement, (foreign, uuid.uuid4()))
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint(purged.database(), checkpoint_path)
    archived = json.loads(checkpoint_path.read_bytes())["record"]["tombstones"]
    assert {item["tombstone"]["workspace_id"] for item in archived} == {
        str(purged.workspace_id),
        str(foreign),
    }
    with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"):
        purged.repository.insert_tombstone(scope="workspace", requested_by=uuid.uuid4())
    runtime = purged.database(role=_APP_ROLE, password=_APP_PASSWORD)
    with runtime.session(purged.workspace_id) as connection:
        for table in ("restore_control", "restore_replay_receipt"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"update {table} set checkpoint_id=gen_random_uuid()")
        for table in ("restore_control", "restore_replay_receipt", "tombstone", "capture"):
            assert not connection.execute(
                "select has_table_privilege(current_user,%s,'DELETE') as allowed", (table,)
            ).fetchone()["allowed"]
    with pytest.raises(RestoreRefused, match="administrative complete view"):
        checkpoint(runtime, tmp_path / "narrow-checkpoint.json")
    with pytest.raises(RestoreRefused, match="sealed"):
        verify_restore(runtime)


def test_corrupt_checkpoint_and_restored_receipt_cannot_authorize_a_new_attempt(purged, tmp_path):
    purged.tombstone_the_capture(_capture(purged))
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(purged.database(), source)
    original = source.read_bytes()
    changed = json.loads(original)
    changed["record"]["tombstones"] = []
    source.write_text(json.dumps(changed))
    with pytest.raises(RestoreRefused, match="digest"):
        prepare_restore(source, marker)
    source.write_bytes(original)
    prepare_restore(source, marker)
    replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    # A fresh attempt invalidates a real previous receipt, even if a restore would retain it.
    prepare_restore(source, marker)
    state = json.loads(marker.read_bytes())
    state["state"] = "complete"
    marker.write_text(json.dumps(state))
    with pytest.raises(RestoreRefused, match="receipt"):
        verify_restore(purged.database(), marker)
    app, _ = _app(purged, marker)
    app.state.services = replace(app.state.services, restore_state_path=tmp_path / "missing.json")
    with pytest.raises(RestoreRefused, match="unavailable"), TestClient(app):
        pass


def test_shared_live_bytes_leave_restore_refusing_and_foreign_capture_intact(purged, tmp_path):
    from exulanica.evidence.blob import BlobId

    capture = _capture(purged)
    blob = BlobId(bytes(purged.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    foreign = uuid.uuid4()
    foreign_capture = purged.repository.connection.execute(
        "insert into capture (workspace_id,blob_sha256) values (%s,%s) returning capture_id",
        (foreign, blob.digest),
    ).fetchone()["capture_id"]
    purged.tombstone_the_capture(capture)
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(purged.database(), source)
    prepare_restore(source, marker)
    with pytest.raises(RestoreRefused, match="purge incomplete"):
        replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    assert purged.store.exists(blob)
    assert purged.rows("select deleted_at from capture where capture_id=%s", foreign_capture) == [
        {"deleted_at": None}
    ]
    assert not purged.rows("select * from restore_replay_receipt")
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)


def test_backup_older_than_blocklisted_capture_refuses_missing_address_binding(purged, tmp_path):
    from exulanica.ingest.pipeline import PhotoIngestPipeline

    from conftest import photo_bytes

    dump, blobs = _backup(purged, tmp_path)
    payload = photo_bytes(when="2026:08:28 11:00:00")
    outcome = PhotoIngestPipeline(purged.repository, purged.store).ingest_intake(
        payload, filename="after-backup.jpg"
    )
    assert outcome.error is None
    purged.repository.insert_tombstone(
        scope="capture",
        capture_id=outcome.capture_id,
        requested_by=uuid.uuid4(),
        blocklist_hash=True,
    )
    source, marker = tmp_path / "checkpoint.json", tmp_path / "restore.json"
    checkpoint(purged.database(), source)
    prepare_restore(source, marker)
    _restore(purged, dump, blobs)
    assert not purged.rows("select capture_id from capture where capture_id=%s", outcome.capture_id)
    with pytest.raises(RestoreRefused, match="capture binding"):
        replay(purged.database(), _purge_database(purged), purged.store, source, marker)
    assert not purged.rows("select * from restore_replay_receipt")
    with pytest.raises(RestoreRefused, match="pending"):
        verify_restore(purged.database(), marker)
