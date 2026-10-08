"""A lost source is recovered into an isolated server from a backup set and an export, timed.

The source here is the test schema; the target is a scratch PostgreSQL cluster of its own with a
content store of its own, so nothing the recovery does can be satisfied by the source still being
there. A withdrawal made after the backup is replayed; one made after the export is reported as
lost; a stale authority leaves the target refusing.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.parse
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.definer_role import DEFINER_ROLE, DefinerRoleUnsafe, assert_definer_role
from exulanica.db.local.cluster import HOST, scratch_cluster
from exulanica.db.roles import provision_backup_role, provision_purge_role, provision_runtime_role
from exulanica.db.session import Database
from exulanica.deletion.restore import DECLARATION_PROFILE, RestoreRefused, verify_restore
from exulanica.evidence.blob import BlobId
from exulanica.orchestration.installation.backup_set import (
    BackupSetRefused,
    Namespace,
    read_backup_set,
    take_backup_set,
)
from exulanica.orchestration.installation.recovery import Target, recover_declared
from exulanica.orchestration.restore import WRITERS
from exulanica.store.configured import local_content_stores
from exulanica.store.local import LocalContentAddressedStore

from test_local_database_postgres import _require_server_binaries
from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged
from test_restore_replay import _capture
from test_restore_withdrawal_export import _export, _foreign_tombstone

_ROLE = "exulanica_recovery_test"
_PASSWORD = "recovery-test-" + uuid.uuid4().hex
_LAG = dt.timedelta(minutes=10)


def _with_path(url: str, scratch: str) -> str:
    options = urllib.parse.quote(f"-csearch_path={scratch},public", safe="")
    return f"{url}{'&' if '?' in url else '?'}options={options}"


def _declare(tmp_path, export, incident):
    envelope = json.loads(export.read_bytes())
    path = tmp_path / "custody" / "declaration.json"
    path.write_text(
        json.dumps(
            {
                "profile": DECLARATION_PROFILE,
                "declaration_id": str(uuid.uuid4()),
                "export_sha256": envelope["record_sha256"],
                "incident_at": incident.isoformat(),
                "reason": "the source host was lost",
            }
        )
    )
    return path


@pytest.fixture
def source(purged, tmp_path):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)
    backup_store = LocalContentAddressedStore(tmp_path / "backup-store" / "blobs")
    taken = take_backup_set(
        backup_url=purged.database(role=_ROLE, password=_PASSWORD).url,
        directory=tmp_path / "backup-sets",
        namespaces=[Namespace("blobs", purged.store, backup_store)],
        custody=tmp_path / "custody",
        restore_state_path=None,
        backup_domains=[purged.store.root, tmp_path / "backup-store"],
        identity={"profile": "single-host"},
        role=_ROLE,
    )
    return taken, backup_store


def _target(cluster, port, owner, database, scratch, tmp_path):
    # The purge role comes back with the dump's roles, without a password; provisioning gives it
    # one before the replay connects as it.
    purge = f"postgresql://{_PURGE_ROLE}:{_PURGE_PASSWORD}@{HOST}:{port}/{database}"
    return Target(
        maintenance_url=cluster.url(port, owner, "postgres"),
        database_url=_with_path(cluster.url(port, owner, database), scratch),
        purge_url=_with_path(purge, scratch),
        stores=local_content_stores(tmp_path / "target-store"),
    )


def _provision(scratch):
    def provision(database: Database) -> None:
        # The test schema records no migration versions, so only the roles are provisioned here;
        # an installation runs exulanica-db, which also migrates.
        with database.unscoped() as connection:
            connection.execute(f'set search_path to "{scratch}", public')
            provision_runtime_role(connection, role=_APP_ROLE, password=_APP_PASSWORD)
            provision_purge_role(connection, role=_PURGE_ROLE, password=_PURGE_PASSWORD)

    return provision


def test_a_lost_source_is_recovered_into_an_isolated_server(purged, source, tmp_path):
    _require_server_binaries()
    taken, backup_store = source
    objects = sorted(blob.hex for blob in purged.store.iter_blob_ids())
    deleted = purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    export, _ = _export(purged, tmp_path)
    lost = _foreign_tombstone(purged)
    declaration = _declare(tmp_path, export, dt.datetime.now(dt.UTC))
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        # Only the restored target's store: the source's bytes are never read by the recovery.
        result = recover_declared(
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            export=export,
            custody=export.parent,
            declaration=declaration,
            max_export_lag=_LAG,
            marker=tmp_path / "control" / "restore.json",
            target=target,
            provision=_provision(purged.scratch),
        )
        restored = Database(target.database_url)
        verify_restore(restored, tmp_path / "control" / "restore.json")
        with restored.unscoped() as connection:
            tombstones = {
                str(row["tombstone_id"])
                for row in connection.execute("select tombstone_id from tombstone").fetchall()
            }
            receipt = connection.execute("select * from restore_replay_receipt").fetchone()
        target_store = target.stores.blobs
        assert str(deleted) in tombstones
        assert str(lost["tombstone_id"]) not in tombstones
        assert receipt["recovery_mode"] == "declared"
        # The deleted photograph's bytes were in the backup and are gone from the target.
        survivors = sorted(blob.hex for blob in target_store.iter_blob_ids())
        assert len(survivors) < len(objects)
        assert result["objects_copied"] == len(objects)
        assert "are not restored" in result["loss_window"]
        assert result["recovery_seconds"] > 0
        print(f"RECOVERY_SECONDS {result['recovery_seconds']}")


def _checking_provision(scratch):
    """The roles, then the definer check ``exulanica-db`` runs after them (migration 0161)."""
    roles = _provision(scratch)

    def provision(database: Database) -> None:
        roles(database)
        with database.unscoped() as connection:
            connection.execute(f'set search_path to "{scratch}", public')
            assert_definer_role(connection)

    return provision


@pytest.mark.parametrize("widened", [False, True])
def test_a_recovery_keeps_the_definer_owner_and_refuses_one_the_server_widened(
    purged, source, tmp_path, widened
):
    """The installation restore keeps a role the target server already has. Restored onto a
    fresh server, every definer comes back with its narrow owner and grants; onto one whose
    exulanica_definer can log in, the role is kept as found and the check refuses it."""
    _require_server_binaries()
    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    declaration = _declare(tmp_path, export, dt.datetime.now(dt.UTC))
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        if widened:
            with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as admin:
                admin.execute(f"create role {DEFINER_ROLE} login")
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)

        def recover():
            return recover_declared(
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                export=export,
                custody=export.parent,
                declaration=declaration,
                max_export_lag=_LAG,
                marker=tmp_path / "control" / "restore.json",
                target=target,
                provision=_checking_provision(purged.scratch),
            )

        if widened:
            with pytest.raises(DefinerRoleUnsafe, match="can log in"):
                recover()
            return
        recover()
        with Database(target.database_url).unscoped() as connection:
            owners = connection.execute(
                "select distinct pg_get_userbyid(p.proowner) as owner from pg_proc p "
                "where p.pronamespace = current_schema()::regnamespace and p.prosecdef"
            ).fetchall()
            assert [row["owner"] for row in owners] == [DEFINER_ROLE]
            # A definer runs in the copy as its narrow owner, with the restored grants.
            connection.execute("select * from spending_authority_facts()").fetchall()


def test_a_stale_authority_leaves_the_target_refusing(purged, source, tmp_path):
    _require_server_binaries()
    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    late = dt.datetime.now(dt.UTC) + _LAG + dt.timedelta(minutes=1)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        with pytest.raises(RestoreRefused, match="not current"):
            recover_declared(
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                export=export,
                custody=export.parent,
                declaration=_declare(tmp_path, export, late),
                max_export_lag=_LAG,
                marker=tmp_path / "control" / "restore.json",
                target=Target(
                    maintenance_url=cluster.url(port, owner, "postgres"),
                    database_url=cluster.url(port, owner, database),
                    purge_url=cluster.url(port, owner, database),
                    stores=local_content_stores(tmp_path / "unused-target-store"),
                ),
                provision=lambda _database: None,
            )
        # Nothing was loaded: the refusal came before the target was touched.
        with psycopg.connect(cluster.url(port, owner, "postgres")) as connection:
            names = [row[0] for row in connection.execute("select datname from pg_database")]
        assert database not in names


def _unseal(purged, sealed, tmp_path):
    """Test hygiene: complete the shared test schema's own seal, so later tests may delete again."""
    from exulanica.deletion.restore import prepare_restore, replay

    from test_restore_replay import _purge_database

    marker = tmp_path / "control" / f"unseal-{uuid.uuid4().hex}.json"
    prepare_restore(sealed, marker)
    replay(
        purged.database(), _purge_database(purged), purged.store, sealed, marker, writers=WRITERS
    )


def test_a_planned_restore_loses_nothing_and_the_source_can_serve_again(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    deleted = purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    sealed = tmp_path / "custody" / "checkpoint.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    try:
        with scratch_cluster(owner=owner) as (cluster, port):
            target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
            result = restore_planned(
                source=purged.database(),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=tmp_path / "control" / "restore.json",
                target=target,
                provision=_provision(purged.scratch),
            )
            with Database(target.database_url).unscoped() as connection:
                present = connection.execute(
                    "select 1 from tombstone where tombstone_id = %s", (deleted,)
                ).fetchone()
                receipt = connection.execute("select * from restore_replay_receipt").fetchone()
            assert present is not None
            assert receipt["recovery_mode"] is None
            assert result["mode"] == "planned" and result["source_kept_as"] is None
        # The checkpoint sealed the source; nothing more may be deleted there until it resumes.
        with pytest.raises(psycopg.errors.ObjectNotInPrerequisiteState, match="sealed"):
            purged.tombstone_the_capture(_capture(purged))
    finally:
        _unseal(purged, sealed, tmp_path)
    # The shared test schema's seal is completed again, so it serves and accepts deletions.
    verify_restore(purged.database())


def _a_door_credential_ended_long_ago(purged) -> str:
    """A world, a door grant and its channel credential, which the owner ended and which ended
    more than thirty days ago: its digest. The credential is written with triggers off, as only a
    superuser may, since the door stamps a secret's time at insert."""
    workspace = purged.workspace_id
    world = f"door-world-{uuid.uuid4().hex[:8]}"
    grant = uuid.uuid4()
    secret = uuid.uuid4().hex * 2
    with purged.database().session(workspace) as connection, connection.transaction():
        connection.execute(
            "insert into world_identity (workspace_id, world_id, kind, provenance, created_by) "
            "values (%s, %s, 'authored-starter', '{\"origin\": \"test\"}', %s)",
            (workspace, world, uuid.uuid4()),
        )
        connection.execute(
            "insert into door_grant (workspace_id, grant_id, world_id, bridge, issued_by) "
            "values (%s, %s, %s, 'test-bridge', %s)",
            (workspace, grant, world, uuid.uuid4()),
        )
        connection.execute("set local session_replication_role = replica")
        connection.execute(
            "insert into door_secret (secret_sha256, kind, bridge, workspace_id, grant_id, "
            "created_at, expires_at, revoked_at) values (%s, 'channel', 'test-bridge', %s, %s, "
            "now() - interval '40 days', now() - interval '31 days', now() - interval '39 days')",
            (secret, workspace, grant),
        )
    return secret


def test_an_ended_door_credential_never_makes_an_older_backup_unrestorable(
    purged, source, tmp_path
):
    """An owner ends a door credential long past its retention, a backup is taken, the door's
    retention runs, and that backup is restored: the revoked credential is kept, as a withdrawal
    is, backup sets carry no door secret, so the backup holds no withdrawal the checkpoint lacks,
    and the restored installation holds no credential."""
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    _first, backup_store = source
    secret = _a_door_credential_ended_long_ago(purged)
    taken = take_backup_set(
        backup_url=purged.database(role=_ROLE, password=_PASSWORD).url,
        directory=tmp_path / "backup-sets",
        namespaces=[Namespace("blobs", purged.store, backup_store)],
        custody=tmp_path / "custody",
        restore_state_path=None,
        backup_domains=[purged.store.root, tmp_path / "backup-store"],
        identity={"profile": "single-host"},
        role=_ROLE,
    )
    with purged.database().unscoped() as connection:
        connection.execute("select door_prune(1000)")
        kept = connection.execute(
            "select 1 from door_secret where secret_sha256 = %s", (secret,)
        ).fetchone()
    assert kept is not None
    sealed = tmp_path / "custody" / "checkpoint.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    try:
        with scratch_cluster(owner=owner) as (cluster, port):
            target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
            result = restore_planned(
                source=purged.database(),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=tmp_path / "control" / "restore.json",
                target=target,
                provision=_provision(purged.scratch),
            )
            with Database(target.database_url).unscoped() as connection:
                secrets_held = connection.execute(
                    "select count(*) as n from door_secret"
                ).fetchone()
            assert result["mode"] == "planned"
            assert secrets_held["n"] == 0
    finally:
        _unseal(purged, sealed, tmp_path)
    verify_restore(purged.database())


def _erase_from_backup(purged, backup_store, deleted):
    """What maintenance does after a completed purge: the backup copy loses those bytes too."""
    from exulanica.store.base import PurgeAuthorization, privileged_purger

    erased = []
    for row in purged.rows(
        "select target_ref from purge_job where tombstone_id=%s and target_kind in "
        "('blob','artifact') and state='done'",
        deleted,
    ):
        blob = BlobId.from_hex(row["target_ref"])
        if backup_store.exists(blob):
            privileged_purger(
                backup_store, PurgeAuthorization(str(deleted), "test", "erasure reaches backups")
            ).purge(blob)
            erased.append(blob)
    return erased


def test_a_recovery_accepts_backup_objects_a_purge_erased(purged, source, tmp_path):
    _require_server_binaries()
    taken, backup_store = source
    deleted = purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    erased = _erase_from_backup(purged, backup_store, deleted)
    assert erased
    export, _ = _export(purged, tmp_path)
    declaration = _declare(tmp_path, export, dt.datetime.now(dt.UTC))
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        result = recover_declared(
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            export=export,
            custody=export.parent,
            declaration=declaration,
            max_export_lag=_LAG,
            marker=tmp_path / "control" / "restore.json",
            target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
            provision=_provision(purged.scratch),
        )
    assert result["erased_objects"] == len(erased)


def test_a_failed_planned_restore_refuses_its_partial_copy_then_resumes(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    sealed = tmp_path / "custody" / "checkpoint.json"
    marker = tmp_path / "control" / "restore.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    try:
        with scratch_cluster(owner=owner) as (cluster, port):
            target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
            arguments = {
                "source": purged.database(),
                "checkpoint_path": sealed,
                "backup_set": taken.directory,
                "backup_stores": {"blobs": backup_store},
                "marker": marker,
                "target": target,
            }
            with pytest.raises(RuntimeError, match="fails this once"):
                restore_planned(**arguments, provision=failing)
            attempt = json.loads(marker.read_bytes())["restore_id"]
            with pytest.raises(RestoreRefused, match="partial copy"):
                restore_planned(**arguments, provision=_provision(purged.scratch))
            with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
                c.execute(f'drop database "{database}"')
            result = restore_planned(**arguments, provision=_provision(purged.scratch))
            assert result["restore_id"] == attempt
    finally:
        _unseal(purged, sealed, tmp_path)


def test_a_recovery_refuses_a_missing_object_no_purge_names(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.backup_set import BackupSetRefused

    taken, backup_store = source
    victim = next(iter(backup_store.iter_blob_ids()))
    (backup_store.root / "sha-256" / victim.hex[:2] / victim.hex[2:4] / victim.hex).unlink()
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with (
        scratch_cluster(owner=owner) as (cluster, port),
        pytest.raises(BackupSetRefused, match="backup_object_missing"),
    ):
        recover_declared(
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            export=export,
            custody=export.parent,
            declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            max_export_lag=_LAG,
            marker=tmp_path / "control" / "restore.json",
            target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
            provision=_provision(purged.scratch),
        )


def _sign_in_and_out(purged, *, sign_out=True):
    """One account, one browser session, then a sign-out: the withdrawal every logout writes."""
    import hashlib as _hashlib

    user, actor, workspace = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    state = _hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    session = _hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    digest = "a" * 64
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        connection.execute(
            "insert into account_user (user_id, actor_id) values (%s, %s)", (user, actor)
        )
        connection.execute(
            "insert into account_workspace (workspace_id, owner_user_id) values (%s, %s)",
            (workspace, user),
        )
        connection.execute(
            "insert into account_membership (workspace_id, user_id, membership_role) "
            "values (%s, %s, 'owner')",
            (workspace, user),
        )
        connection.execute(
            "insert into account_login_attempt (state_sha256, browser_sha256, config_sha256, "
            "callback_uri, return_uri, expires_at, outcome) values "
            "(%s, %s, %s, 'https://x/cb', 'https://x/', now() + interval '1 hour', 'succeeded')",
            (state, digest, digest),
        )
        connection.execute(
            "insert into account_browser_session (session_sha256, user_id, workspace_id, "
            "csrf_token, login_state_sha256, expires_at) values "
            "(%s, %s, %s, %s, %s, now() + interval '1 day')",
            (session, user, workspace, "c" * 32, state),
        )
    if sign_out:
        _sign_out(purged, session)
    return session


def _sign_out(purged, session):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        connection.execute(
            "update account_browser_session set revoked_at = now() where session_sha256 = %s",
            (session,),
        )


def test_a_recovered_installation_exports_and_backs_up_again_after_sign_outs(
    purged, source, tmp_path
):
    """Every sign-out writes a withdrawal of a row a backup set never carries."""
    _require_server_binaries()
    from exulanica.deletion.restore import export_withdrawals

    taken, backup_store = source
    session = _sign_in_and_out(purged)
    export, _ = _export(purged, tmp_path)
    assert any(
        item["kind"] == "session" and item["row"]["session_sha256"] == session
        for item in json.loads(export.read_bytes())["record"]["withdrawals"]
    )
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        recover_declared(
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            export=export,
            custody=export.parent,
            declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            max_export_lag=_LAG,
            marker=tmp_path / "control" / "restore.json",
            target=target,
            provision=_provision(purged.scratch),
        )
        # Into the same custody, where the lost source's export is the newest.
        again, _ = export_withdrawals(
            Database(target.database_url),
            tmp_path / "custody",
            restore_state_path=tmp_path / "control" / "restore.json",
            backup_domains=(tmp_path / "target-store",),
        )
    record = json.loads(again.read_bytes())["record"]
    assert record["source_identity"] != json.loads(export.read_bytes())["record"]["source_identity"]


def test_a_declared_recovery_resumes_after_a_failure(purged, source, tmp_path):
    _require_server_binaries()
    taken, backup_store = source
    purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    export, _ = _export(purged, tmp_path)
    declaration = _declare(tmp_path, export, dt.datetime.now(dt.UTC))
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        arguments = {
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "export": export,
            "custody": export.parent,
            "declaration": declaration,
            "max_export_lag": _LAG,
            "marker": marker,
            "target": target,
        }
        with pytest.raises(RuntimeError, match="fails this once"):
            recover_declared(**arguments, provision=failing)
        attempt = json.loads(marker.read_bytes())["restore_id"]
        with pytest.raises(RestoreRefused, match="partial copy"):
            recover_declared(**arguments, provision=_provision(purged.scratch))
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        result = recover_declared(**arguments, provision=_provision(purged.scratch))
    assert result["resumed"] is True and result["restore_id"] == attempt


def test_nothing_is_sealed_or_written_when_the_target_holds_the_source(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    with scratch_cluster(owner=owner) as (cluster, port):
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'create database "{database}"')
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        with pytest.raises(RestoreRefused, match="set-aside"):
            restore_planned(
                source=purged.database(),
                checkpoint_path=tmp_path / "custody" / "checkpoint.json",
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=target,
                provision=_provision(purged.scratch),
            )
        export, _ = _export(purged, tmp_path)
        with pytest.raises(RestoreRefused, match="empty database"):
            recover_declared(
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                export=export,
                custody=export.parent,
                declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
                max_export_lag=_LAG,
                marker=marker,
                target=target,
                provision=_provision(purged.scratch),
            )
    assert not marker.exists() and not (tmp_path / "custody" / "checkpoint.json").exists()
    # The source was never sealed: it still accepts a deletion.
    purged.tombstone_the_capture(_capture(purged))


def test_a_declared_recovery_replays_only_the_newest_export(purged, source, tmp_path):
    _require_server_binaries()
    import shutil

    taken, backup_store = source
    older, _ = _export(purged, tmp_path)
    purged.tombstone_the_capture(_capture(purged))
    _export(purged, tmp_path)
    # Copied alone into another directory, the older export is still not custody's newest.
    copied = tmp_path / "elsewhere" / "older.json"
    copied.parent.mkdir()
    shutil.copy(older, copied)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    with scratch_cluster(owner=owner) as (cluster, port):
        for export in (older, copied):
            with pytest.raises(RestoreRefused, match="not the newest"):
                recover_declared(
                    backup_set=taken.directory,
                    backup_stores={"blobs": backup_store},
                    export=export,
                    custody=tmp_path / "custody",
                    declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
                    max_export_lag=_LAG,
                    marker=tmp_path / "control" / "restore.json",
                    target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
                    provision=_provision(purged.scratch),
                )
    assert not (tmp_path / "control" / "restore.json").exists()


def _source_on_the_target_server(purged, source, tmp_path, cluster, port):
    """A database on the scratch server to act as a single host's live source."""
    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
    recover_declared(
        backup_set=taken.directory,
        backup_stores={"blobs": backup_store},
        export=export,
        custody=export.parent,
        declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
        max_export_lag=_LAG,
        marker=tmp_path / "control" / "first.json",
        target=target,
        provision=_provision(purged.scratch),
    )
    return target, owner, database


def test_a_set_aside_source_is_discarded_after_the_restore_and_never_resumed(
    purged, source, tmp_path
):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import (
        discard_set_aside,
        restore_planned,
        return_to_source,
    )

    from test_restore_replay import _purge_database

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    owner = loaded.database.owner_role
    with scratch_cluster(owner=owner) as (cluster, port):
        target, owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        result = restore_planned(
            source=Database(target.database_url),
            checkpoint_path=sealed,
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            marker=marker,
            target=target,
            provision=_provision(purged.scratch),
            set_aside=True,
        )
        kept = result["source_kept_as"]
        names = {
            row[0]
            for row in psycopg.connect(cluster.url(port, owner, "postgres"))
            .execute("select datname from pg_database")
            .fetchall()
        }
        assert {database, kept} <= names
        # Rerunning the completed restore reopens nothing: no rename, no reload, marker complete.
        with pytest.raises(RestoreRefused, match="already complete"):
            restore_planned(
                source=Database(target.database_url),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=target,
                provision=_provision(purged.scratch),
                set_aside=True,
            )
        assert json.loads(marker.read_bytes())["state"] == "complete"
        assert {
            row[0]
            for row in psycopg.connect(cluster.url(port, owner, "postgres"))
            .execute("select datname from pg_database")
            .fetchall()
        } == names
        # A later restore moves the marker on; the completed record keeps this set-aside
        # discardable, and the checkpoint still cannot be reopened.
        moved = json.loads(marker.read_bytes())
        moved.update(
            checkpoint_sha256="f" * 64,
            restore_id=str(uuid.uuid4()),
            checkpoint_id=str(uuid.uuid4()),
        )
        moved["completed"] = [
            *moved["completed"],
            {"checkpoint_sha256": "f" * 64, "restore_id": moved["restore_id"]},
        ]
        marker.write_text(json.dumps(moved))
        with pytest.raises(RestoreRefused, match="discard it instead"):
            return_to_source(
                target=target,
                name=database,
                source_purge=_purge_database(purged),
                checkpoint_path=sealed,
                marker=marker,
                set_aside=True,
            )
        assert (
            discard_set_aside(target=target, name=database, checkpoint_path=sealed, marker=marker)
            == kept
        )
        with psycopg.connect(cluster.url(port, owner, "postgres")) as connection:
            left = connection.execute(
                "select 1 from pg_database where datname = %s", (kept,)
            ).fetchone()
        assert left is None
        # A database that merely carries the set-aside name is never dropped.
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'create database "{kept}"')
        with pytest.raises(RestoreRefused, match="not the source this restore sealed"):
            discard_set_aside(target=target, name=database, checkpoint_path=sealed, marker=marker)


def test_an_unfinished_set_aside_restore_returns_to_its_source(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import (
        discard_set_aside,
        restore_planned,
        return_to_source,
    )

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    owner = loaded.database.owner_role

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    with scratch_cluster(owner=owner) as (cluster, port):
        target, owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        purge = target.purge_url
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        with pytest.raises(RuntimeError, match="fails this once"):
            restore_planned(
                source=Database(target.database_url),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=target,
                provision=failing,
                set_aside=True,
            )
        arguments = {
            "target": target,
            "name": database,
            "source_purge": Database(purge),
            "checkpoint_path": sealed,
            "marker": marker,
            "set_aside": True,
        }
        # While the restore is pending the set-aside source is the fallback: it is never dropped.
        with pytest.raises(RestoreRefused, match="has not completed"):
            discard_set_aside(target=target, name=database, checkpoint_path=sealed, marker=marker)
        # Without --set-aside it would replay into the partial copy that now holds the name.
        with pytest.raises(RestoreRefused, match="the source was set aside as"):
            return_to_source(**{**arguments, "set_aside": False})
        with pytest.raises(RestoreRefused, match="partial copy"):
            return_to_source(**arguments)
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        return_to_source(**arguments)
        verify_restore(Database(target.database_url), marker)


def test_bytes_written_after_the_backup_are_listed_for_the_operator(tmp_path):
    from exulanica.orchestration.installation.recovery import _report_unlisted

    stores = local_content_stores(tmp_path / "target-store")
    kept = stores.blobs.put_bytes(b"in the backup").blob_id
    later = stores.blobs.put_bytes(b"written after the backup").blob_id
    backup_set = tmp_path / "set"
    backup_set.mkdir()
    (backup_set / "keys.txt").write_text(f"blobs/{kept.hex}\n")
    target = Target("unused", "unused", "unused", stores=stores)
    restore_id = uuid.uuid4()
    (tmp_path / "control").mkdir()  # where the restore wrote its marker
    reported = _report_unlisted(backup_set, target, tmp_path / "control" / "m.json", restore_id)
    assert reported["objects_not_in_backup"] == 1
    listing = Path(reported["objects_not_in_backup_list"])
    assert listing.read_text() == f"blobs/{later.hex}\n"
    assert listing.stat().st_mode & 0o077 == 0
    # Nothing is removed: no tombstone names these bytes.
    assert stores.blobs.exists(later)


def test_a_set_aside_name_fits_postgresql_and_is_found_again():
    from exulanica.orchestration.installation.recovery import _kept_name

    restore_id = uuid.uuid4()
    for name in ("exulanica", "x" * 63, "é" * 31 + "x"):
        kept = _kept_name(name, restore_id)
        # PostgreSQL truncates a longer name, and a resumed attempt would then look for another.
        assert len(kept.encode()) <= 63
        assert kept.endswith(f"_before_{restore_id.hex[:8]}")
        assert _kept_name(name, restore_id) == kept


def test_a_damaged_key_list_or_another_database_name_refuses_before_anything(
    purged, source, tmp_path
):
    import shutil

    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    arguments = {
        "backup_stores": {"blobs": backup_store},
        "export": export,
        "custody": export.parent,
        "declaration": _declare(tmp_path, export, dt.datetime.now(dt.UTC)),
        "max_export_lag": _LAG,
        "marker": tmp_path / "control" / "restore.json",
        "provision": lambda _database: None,
    }
    loaded = read_backup_set(taken.directory)
    unused = local_content_stores(tmp_path / "unused-target-store")
    damaged = tmp_path / "damaged-set"
    shutil.copytree(taken.directory, damaged)
    with (damaged / "keys.txt").open("a") as keys:
        keys.write(f"blobs/{'0' * 64}\n")
    target = Target(
        "postgresql://unused/x",
        f"postgresql://unused/{loaded.database.database}",
        "postgresql://unused/x",
        stores=unused,
    )
    with pytest.raises(BackupSetRefused, match="key list"):
        recover_declared(backup_set=damaged, target=target, **arguments)
    elsewhere = Target(
        "postgresql://unused/x",
        "postgresql://unused/another",
        "postgresql://unused/x",
        stores=unused,
    )
    with pytest.raises(RestoreRefused, match="another"):
        recover_declared(backup_set=taken.directory, target=elsewhere, **arguments)
    assert not arguments["marker"].exists()


def test_a_planned_restore_interrupted_between_seal_and_marker_resumes(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.deletion.restore import checkpoint
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    sealed = tmp_path / "custody" / "checkpoint.json"
    marker = tmp_path / "control" / "restore.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    # What a crash after the seal and before the marker leaves: a sealed source, no marker.
    checkpoint(purged.database(), sealed)
    try:
        assert not marker.exists()
        with scratch_cluster(owner=owner) as (cluster, port):
            result = restore_planned(
                source=purged.database(),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
                provision=_provision(purged.scratch),
            )
        assert (
            result["mode"] == "planned" and json.loads(marker.read_bytes())["state"] == "complete"
        )
    finally:
        _unseal(purged, sealed, tmp_path)
    verify_restore(purged.database())


def test_set_aside_refuses_a_database_that_is_not_the_source(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    sealed = tmp_path / "custody" / "checkpoint.json"
    with scratch_cluster(owner=owner) as (cluster, port):
        # Another server holds an unrelated database of the set's name.
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'create database "{database}"')
        with psycopg.connect(cluster.url(port, owner, database), autocommit=True) as c:
            c.execute("create table unrelated (x int)")
        with pytest.raises(RestoreRefused, match="not the source database"):
            restore_planned(
                source=purged.database(),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
                provision=_provision(purged.scratch),
                set_aside=True,
            )
        with psycopg.connect(cluster.url(port, owner, database)) as c:
            assert c.execute("select to_regclass('unrelated')").fetchone()[0] is not None
    assert not marker.exists() and not sealed.exists()
    # Nothing was sealed: the source still accepts a deletion.
    purged.tombstone_the_capture(_capture(purged))


def test_return_names_the_right_step_when_the_source_was_never_set_aside(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.deletion.restore import checkpoint, prepare_restore
    from exulanica.orchestration.installation.recovery import return_to_source

    loaded = read_backup_set(source[0].directory)
    with scratch_cluster(owner=loaded.database.owner_role) as (cluster, port):
        target, _owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        # What a failure between the marker and the rename leaves: sealed, pending, not renamed.
        checkpoint(Database(target.database_url), sealed)
        prepare_restore(sealed, marker)
        arguments = {
            "target": target,
            "name": database,
            "source_purge": Database(target.purge_url),
            "checkpoint_path": sealed,
            "marker": marker,
        }
        with pytest.raises(RestoreRefused, match="never set aside"):
            return_to_source(set_aside=True, **arguments)
        return_to_source(set_aside=False, **arguments)
        verify_restore(Database(target.database_url), marker)


def test_a_replaying_target_without_its_attempt_and_a_damaged_marker_refuse(tmp_path):
    from exulanica.orchestration.installation.recovery import _pending, _refuse_target

    with pytest.raises(RestoreRefused, match="do not drop it"):
        _refuse_target("replaying", "exulanica", attempt_pending=False)
    damaged = tmp_path / "restore.json"
    damaged.write_text("{")
    with pytest.raises(RestoreRefused, match="unreadable"):
        _pending(damaged, "0" * 64)


def test_a_rerun_resumes_only_a_sealed_source(purged, source, tmp_path):
    """A source whose restore_control is not sealed for this checkpoint is not this restore's to
    resume, whatever the marker says: here it is mid-replay and no marker names it."""
    _require_server_binaries()
    from exulanica.deletion.restore import checkpoint
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    with scratch_cluster(owner=loaded.database.owner_role) as (cluster, port):
        target, _owner, _database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        checkpoint(Database(target.database_url), sealed)
        with psycopg.connect(target.database_url, autocommit=True) as connection:
            connection.execute("update restore_control set state = 'replaying'")
        with pytest.raises(RestoreRefused, match="not the source's seal"):
            restore_planned(
                source=Database(target.database_url),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=target,
                provision=_provision(purged.scratch),
            )
        assert not marker.exists()


def test_a_pending_declared_recovery_is_abandoned_for_a_newer_export(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import abandon_declared

    taken, backup_store = source
    first, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        common = {
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "custody": first.parent,
            "max_export_lag": _LAG,
            "marker": marker,
            "target": target,
        }
        declared = _declare(tmp_path, first, dt.datetime.now(dt.UTC))
        with pytest.raises(RuntimeError, match="fails this once"):
            recover_declared(export=first, declaration=declared, provision=failing, **common)
        # A newer export reaches custody: the pending attempt can be neither resumed nor replaced.
        purged.tombstone_the_capture(_capture(purged))
        newer, _ = _export(purged, tmp_path)
        newer_declared = _declare(tmp_path, newer, dt.datetime.now(dt.UTC))
        with pytest.raises(RestoreRefused, match="pending for another"):
            recover_declared(
                export=newer,
                declaration=newer_declared,
                provision=_provision(purged.scratch),
                **common,
            )
        # Abandoned only once nothing the attempt loaded remains.
        with pytest.raises(RestoreRefused, match="it is a partial copy"):
            abandon_declared(target=target, export=first, marker=marker)
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        abandoned = abandon_declared(target=target, export=first, marker=marker)
        state = json.loads(marker.read_bytes())
        assert state["state"] == "abandoned" and state["abandoned"] == abandoned
        # Abandoned still refuses serving, as pending did: a backup loaded by hand is not served.
        with pytest.raises(RestoreRefused, match="abandoned"):
            verify_restore(purged.database(), marker)
        result = recover_declared(
            export=newer,
            declaration=newer_declared,
            provision=_provision(purged.scratch),
            **common,
        )
    assert result["mode"] == "declared" and json.loads(marker.read_bytes())["state"] == "complete"


def test_a_failed_listing_does_not_fail_a_completed_restore(tmp_path, monkeypatch):
    from exulanica.orchestration.installation import recovery

    def unreachable(_backup_set, _target):
        raise OSError("the object store did not answer")

    monkeypatch.setattr(recovery, "unlisted_objects", unreachable)
    target = Target("unused", "unused", "unused", stores=local_content_stores(tmp_path / "s"))
    reported = recovery._report_unlisted(tmp_path, target, tmp_path / "m.json", uuid.uuid4())
    assert reported == {"objects_not_in_backup": None, "objects_not_in_backup_error": "OSError"}


def test_the_refusals_never_tell_the_operator_to_drop_a_source():
    from exulanica.orchestration.installation.recovery import _refuse_target

    for state, pending in (
        ("sealed_source", True),
        ("occupied", False),
        ("replaying", False),
        ("live", True),
        ("completed_here", True),
        ("completed_here", False),
    ):
        with pytest.raises(RestoreRefused) as refused:
            _refuse_target(state, "exulanica", attempt_pending=pending)
        assert "do not drop it" in str(refused.value)
    # The one "drop it" a replaying database gets: this attempt's copy, never completed.
    with pytest.raises(RestoreRefused) as refused:
        _refuse_target("replaying", "exulanica", attempt_pending=True)
    assert "never completed, so it has never served: drop it" in str(refused.value)
    # Under a pending attempt, written only after the target was found empty, an occupied target
    # is that attempt's partial copy, and the refusal still guards against a live one.
    with pytest.raises(RestoreRefused) as refused:
        _refuse_target("occupied", "exulanica", attempt_pending=True)
    assert "it is a partial copy" in str(refused.value)
    assert "if it is a live database, do not drop it" in str(refused.value)


def test_a_declared_recovery_interrupted_mid_replay_resumes_the_replay_only(
    purged, source, tmp_path, monkeypatch
):
    _require_server_binaries()
    from exulanica.deletion import restore

    taken, backup_store = source
    purged.tombstone_the_capture(_capture(purged))
    purged.worker().drain()
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database

    class Interrupted(RuntimeError):
        pass

    class stopped:
        def __init__(self, *args, **kwargs):
            raise Interrupted("the replay's purge never started")

        @classmethod
        def over(cls, *args, **kwargs):
            raise Interrupted("the replay's purge never started")

    with scratch_cluster(owner=owner) as (cluster, port):
        arguments = {
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "export": export,
            "custody": export.parent,
            "declaration": _declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            "max_export_lag": _LAG,
            "marker": tmp_path / "control" / "restore.json",
            "target": _target(cluster, port, owner, database, purged.scratch, tmp_path),
            "provision": _provision(purged.scratch),
        }
        with monkeypatch.context() as patched:
            patched.setattr(restore, "PurgeWorker", stopped)
            with pytest.raises(Interrupted):
                recover_declared(**arguments)
        # Loaded and replaying: the rerun replays and does not load again.
        result = recover_declared(**arguments)
    assert result["resumed"] is True and result["objects_copied"] == 0


def test_a_rerun_classifies_the_target_before_writing_a_marker(purged, source, tmp_path):
    """Cross-server: the old source is still sealed for C and no marker names C, while the target
    serves a live database. The rerun refuses it as live, writing nothing, rather than marking a
    new attempt pending and calling the live database a partial copy."""
    _require_server_binaries()
    from exulanica.deletion.restore import checkpoint
    from exulanica.orchestration.installation.recovery import _target_state, restore_planned

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    sealed = tmp_path / "custody" / "planned.json"
    marker = tmp_path / "control" / "planned.json"
    with scratch_cluster(owner=loaded.database.owner_role) as (cluster, port):
        target, _owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        completed = uuid.UUID(
            json.loads((tmp_path / "control" / "first.json").read_bytes())["restore_id"]
        )
        checkpoint(purged.database(), sealed)
        digest = json.loads(sealed.read_bytes())["record_sha256"]
        try:
            # The live database a restore completed in; the attempt that completed it is its own.
            assert _target_state(target, database, digest) == "live"
            assert _target_state(target, database, digest, completed) == "completed_here"
            with pytest.raises(
                RestoreRefused, match="is a live database, in which a restore completed"
            ):
                restore_planned(
                    source=purged.database(),
                    checkpoint_path=sealed,
                    backup_set=taken.directory,
                    backup_stores={"blobs": backup_store},
                    marker=marker,
                    target=target,
                    provision=_provision(purged.scratch),
                )
            assert not marker.exists()
        finally:
            _unseal(purged, sealed, tmp_path)


def test_a_partial_copy_whose_backup_carries_an_earlier_restore_is_not_called_live(
    purged, tmp_path
):
    """Every set taken after a completed restore carries that restore's complete row. A failed
    load of such a set is this attempt's partial copy: the rerun says so and resumes after the
    drop, instead of calling it live and keeping the installation down."""
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        connection.execute(
            "insert into restore_control (checkpoint_id,checkpoint_sha256,state,restore_id) "
            "values (%s,%s,'complete',%s)",
            (uuid.uuid4(), "e" * 64, uuid.uuid4()),
        )
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)
    backup_store = LocalContentAddressedStore(tmp_path / "backup-store" / "blobs")
    taken = take_backup_set(
        backup_url=purged.database(role=_ROLE, password=_PASSWORD).url,
        directory=tmp_path / "backup-sets",
        namespaces=[Namespace("blobs", purged.store, backup_store)],
        custody=tmp_path / "custody",
        restore_state_path=None,
        backup_domains=[purged.store.root, tmp_path / "backup-store"],
        identity={"profile": "single-host"},
        role=_ROLE,
    )
    sealed = tmp_path / "custody" / "checkpoint.json"
    marker = tmp_path / "control" / "restore.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    try:
        with scratch_cluster(owner=owner) as (cluster, port):
            target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
            arguments = {
                "source": purged.database(),
                "checkpoint_path": sealed,
                "backup_set": taken.directory,
                "backup_stores": {"blobs": backup_store},
                "marker": marker,
                "target": target,
            }
            with pytest.raises(RuntimeError, match="fails this once"):
                restore_planned(**arguments, provision=failing)
            with psycopg.connect(target.database_url) as c:
                assert c.execute("select state from restore_control").fetchone()[0] == "complete"
            with pytest.raises(RestoreRefused) as refused:
                restore_planned(**arguments, provision=_provision(purged.scratch))
            assert "it is a partial copy" in str(refused.value)
            assert "a live database, in which a restore completed" not in str(refused.value)
            with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
                c.execute(f'drop database "{database}"')
            result = restore_planned(**arguments, provision=_provision(purged.scratch))
            assert result["mode"] == "planned"
    finally:
        _unseal(purged, sealed, tmp_path)


def test_a_return_whose_replay_began_resumes(purged, source, tmp_path, monkeypatch):
    _require_server_binaries()
    from exulanica.deletion import restore
    from exulanica.orchestration.installation.recovery import restore_planned, return_to_source

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)

    class Interrupted(RuntimeError):
        pass

    class stopped:
        def __init__(self, *args, **kwargs):
            raise Interrupted("the return's purge never started")

        @classmethod
        def over(cls, *args, **kwargs):
            raise Interrupted("the return's purge never started")

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    with scratch_cluster(owner=loaded.database.owner_role) as (cluster, port):
        target, owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        with pytest.raises(RuntimeError, match="fails this once"):
            restore_planned(
                source=Database(target.database_url),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=target,
                provision=failing,
                set_aside=True,
            )
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        arguments = {
            "target": target,
            "name": database,
            "source_purge": Database(target.purge_url),
            "checkpoint_path": sealed,
            "marker": marker,
        }
        # Renamed back, then the replay stops: twice with --set-aside, which resumes it.
        for _ in range(2):
            with monkeypatch.context() as patched:
                patched.setattr(restore, "PurgeWorker", stopped)
                with pytest.raises(Interrupted):
                    return_to_source(set_aside=True, **arguments)
        # The source is mid-return under its own name. abandon, given the planned checkpoint,
        # refuses before it looks at that database: never "drop it".
        from exulanica.orchestration.installation.recovery import abandon_declared

        with pytest.raises(RestoreRefused) as refused:
            abandon_declared(target=target, export=sealed, marker=marker)
        assert "a planned restore is abandoned with return-to-source" in str(refused.value)
        assert "drop it" not in str(refused.value)
        # Without the flag the same return is resumed, and stops again.
        with monkeypatch.context() as patched:
            patched.setattr(restore, "PurgeWorker", stopped)
            with pytest.raises(Interrupted):
                return_to_source(set_aside=False, **arguments)
        # Its replay commits and the host stops before the marker is written; with --set-aside the
        # return then finishes the replay it recorded, now complete in the database.
        written = restore._write

        def crash_before_completion(path, value):
            if value.get("state") == "complete":
                raise OSError("the host stopped before the marker was written")
            written(path, value)

        with monkeypatch.context() as patched:
            patched.setattr(restore, "_write", crash_before_completion)
            with pytest.raises(OSError, match="before the marker"):
                return_to_source(set_aside=True, **arguments)
        committed = _replay_trace(target.database_url)
        return_to_source(set_aside=True, **arguments)
        assert _replay_trace(target.database_url) == committed  # completed, not replayed again
        verify_restore(Database(target.database_url), marker)


def test_an_abandoned_recovery_is_never_replayed_and_keeps_its_record(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.deletion.restore import replay
    from exulanica.orchestration.installation.recovery import abandon_declared

    from test_restore_replay import _purge_database

    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    earlier = {"checkpoint_sha256": "f" * 64, "restore_id": str(uuid.uuid4())}
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "profile": "exulanica.restore-state/v1",
                "state": "complete",
                "checkpoint_id": str(uuid.uuid4()),
                **earlier,
                "completed": [earlier],
            }
        )
    )

    def failing(_database):
        raise RuntimeError("the provisioning step fails this once")

    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        with pytest.raises(RuntimeError, match="fails this once"):
            recover_declared(
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                export=export,
                custody=export.parent,
                declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
                max_export_lag=_LAG,
                marker=marker,
                target=target,
                provision=failing,
            )
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        abandon_declared(target=target, export=export, marker=marker)
    state = json.loads(marker.read_bytes())
    assert state["state"] == "abandoned" and earlier in state["completed"]
    with pytest.raises(RestoreRefused, match="abandoned"):
        replay(
            purged.database(),
            _purge_database(purged),
            purged.store,
            export,
            marker,
            writers=WRITERS,
        )
    assert json.loads(marker.read_bytes()) == state


def test_a_replay_committed_before_its_marker_is_finished_by_the_rerun(
    purged, source, tmp_path, monkeypatch
):
    _require_server_binaries()
    from exulanica.deletion import restore

    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    written = restore._write

    def crash_before_completion(path, value):
        if value.get("state") == "complete":
            raise OSError("the host stopped before the marker was written")
        written(path, value)

    with scratch_cluster(owner=owner) as (cluster, port):
        arguments = {
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "export": export,
            "custody": export.parent,
            "declaration": _declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            "max_export_lag": _LAG,
            "marker": marker,
            "target": _target(cluster, port, owner, database, purged.scratch, tmp_path),
            "provision": _provision(purged.scratch),
        }
        with monkeypatch.context() as patched:
            patched.setattr(restore, "_write", crash_before_completion)
            with pytest.raises(OSError, match="before the marker"):
                recover_declared(**arguments)
        assert json.loads(marker.read_bytes())["state"] == "pending"
        committed = _replay_trace(arguments["target"].database_url)
        result = recover_declared(**arguments)
        # Completed from the committed replay: nothing is replayed again.
        assert _replay_trace(arguments["target"].database_url) == committed
    state = json.loads(marker.read_bytes())
    assert result["resumed"] is True and result["objects_copied"] == 0
    assert state["state"] == "complete"
    assert state["checkpoint_sha256"] in [item["checkpoint_sha256"] for item in state["completed"]]


def test_a_hand_edited_complete_marker_is_a_named_refusal():
    from exulanica.deletion.restore import _completing

    with pytest.raises(RestoreRefused, match="no completed attempt it can record"):
        _completing({"profile": "exulanica.restore-state/v1", "state": "complete"})


def test_a_source_on_another_server_is_returned_without_the_target_server(
    purged, source, tmp_path, monkeypatch
):
    """The restore into another server stopped mid-replay. --set-aside must not finish that copy
    as if it were the source; the source is returned without the flag, even with the target server
    down, and a source connection naming no database is refused by name."""
    _require_server_binaries()
    from dataclasses import replace

    from exulanica.deletion import restore
    from exulanica.orchestration.installation.recovery import restore_planned, return_to_source

    from test_restore_replay import _purge_database

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    sealed = tmp_path / "custody" / "checkpoint.json"
    marker = tmp_path / "control" / "restore.json"

    class Interrupted(RuntimeError):
        pass

    class stopped:
        def __init__(self, *args, **kwargs):
            raise Interrupted("the restore's purge never started")

        @classmethod
        def over(cls, *args, **kwargs):
            raise Interrupted("the restore's purge never started")

    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        with monkeypatch.context() as patched:
            patched.setattr(restore, "PurgeWorker", stopped)
            with pytest.raises(Interrupted):
                restore_planned(
                    source=purged.database(),
                    checkpoint_path=sealed,
                    backup_set=taken.directory,
                    backup_stores={"blobs": backup_store},
                    marker=marker,
                    target=target,
                    provision=_provision(purged.scratch),
                )
        arguments = {
            "name": database,
            "source_purge": _purge_database(purged),
            "checkpoint_path": sealed,
            "marker": marker,
        }
        # The target's copy is replaying the same attempt and checkpoint: not a source set aside.
        with pytest.raises(RestoreRefused, match="the restore's own copy"):
            return_to_source(target=target, set_aside=True, **arguments)
        # Nor without the flag, if the source connection names that copy: no return began in it.
        with pytest.raises(RestoreRefused, match="no return began in it"):
            return_to_source(target=target, set_aside=False, **arguments)
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        with pytest.raises(RestoreRefused, match="holds neither"):
            return_to_source(target=target, set_aside=True, **arguments)
        assert json.loads(marker.read_bytes())["state"] == "pending"
        missing = replace(target, database_url=cluster.url(port, owner, "no_such_database"))
        with pytest.raises(RestoreRefused, match="names no database that can be reached"):
            return_to_source(target=missing, set_aside=False, **arguments)
    # The target server is gone now; the source is returned on its own server.
    unreachable = "postgresql://nobody@127.0.0.1:1/postgres"
    back = Target(
        maintenance_url=unreachable,
        database_url=purged.database().url,
        purge_url=unreachable,
        stores=local_content_stores(purged.store.root.parent),
    )
    with pytest.raises(RestoreRefused, match="target server cannot be reached"):
        return_to_source(target=back, set_aside=True, **arguments)
    # The first return stops after its replay began; the second stops after its replay committed
    # and before the marker was written; each run resumes only because the first recorded the
    # source.
    with monkeypatch.context() as patched:
        patched.setattr(restore, "PurgeWorker", stopped)
        with pytest.raises(Interrupted):
            return_to_source(target=back, set_aside=False, **arguments)
    assert json.loads(marker.read_bytes())["returning"]
    written = restore._write

    def crash_before_completion(path, value):
        if value.get("state") == "complete":
            raise OSError("the host stopped before the marker was written")
        written(path, value)

    with monkeypatch.context() as patched:
        patched.setattr(restore, "_write", crash_before_completion)
        with pytest.raises(OSError, match="before the marker"):
            return_to_source(target=back, set_aside=False, **arguments)
    committed = _replay_trace(back.database_url)
    return_to_source(target=back, set_aside=False, **arguments)
    assert _replay_trace(back.database_url) == committed  # completed, not replayed again
    verify_restore(purged.database(), marker)


def test_abandon_after_the_replay_began_names_the_copy_to_drop(
    purged, source, tmp_path, monkeypatch
):
    _require_server_binaries()
    from exulanica.deletion import restore
    from exulanica.orchestration.installation.recovery import abandon_declared

    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"

    class Interrupted(RuntimeError):
        pass

    class stopped:
        def __init__(self, *args, **kwargs):
            raise Interrupted("the replay's purge never started")

        @classmethod
        def over(cls, *args, **kwargs):
            raise Interrupted("the replay's purge never started")

    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        with monkeypatch.context() as patched:
            patched.setattr(restore, "PurgeWorker", stopped)
            with pytest.raises(Interrupted):
                recover_declared(
                    backup_set=taken.directory,
                    backup_stores={"blobs": backup_store},
                    export=export,
                    custody=export.parent,
                    declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
                    max_export_lag=_LAG,
                    marker=marker,
                    target=target,
                    provision=_provision(purged.scratch),
                )
        with pytest.raises(RestoreRefused) as refused:
            abandon_declared(target=target, export=export, marker=marker)
        assert "this attempt's own copy, whose replay began" in str(refused.value)
        assert "drop it, then rerun or return from the attempt (or abandon" in str(refused.value)
        with psycopg.connect(cluster.url(port, owner, "postgres"), autocommit=True) as c:
            c.execute(f'drop database "{database}"')
        abandon_declared(target=target, export=export, marker=marker)
    assert json.loads(marker.read_bytes())["state"] == "abandoned"


def test_a_return_token_tells_the_source_from_a_database_with_the_same_server_and_oid(tmp_path):
    """A database another server cloned from the same data directory created can share the
    source's server identifier and oid. The return writes a one-off token into the source before
    its replay; the recorded identity includes it, and a rename keeps it."""
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import _database_identity, _mark_the_source

    with scratch_cluster(owner="exulanica") as (cluster, port):
        url = cluster.url(port, "exulanica", "postgres")
        before = _database_identity(url)
        recorded = _mark_the_source(url)
        assert recorded != before and before.endswith(":")
        assert _database_identity(url) == recorded
        # A second return writes a fresh token: an older record no longer matches.
        assert _mark_the_source(url) != recorded


def _replay_trace(url):
    """What a replay rewrites: restore_control's last update and every purge job's run."""
    with psycopg.connect(url) as c:
        control = c.execute("select updated_at from restore_control").fetchone()
        jobs = c.execute(
            "select purge_id, state, attempts, completed_at from purge_job order by purge_id"
        ).fetchall()
    return control, jobs


def _stale(marker):
    """The pending copy of a completed marker, as a marker restored from an older copy would be."""
    state = json.loads(marker.read_bytes())
    state["state"] = "pending"
    state["completed"] = [
        item for item in state.get("completed", []) if item["restore_id"] != state["restore_id"]
    ]
    marker.write_text(json.dumps(state))


def test_a_stale_pending_marker_never_has_a_served_planned_restore_dropped(
    purged, source, tmp_path
):
    """A set-aside restore completed and its copy served; the marker was then replaced by its
    pending copy. return-to-source --set-aside must not call the live copy one to drop."""
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned, return_to_source

    taken, backup_store = source
    loaded = read_backup_set(taken.directory)
    with scratch_cluster(owner=loaded.database.owner_role) as (cluster, port):
        target, _owner, database = _source_on_the_target_server(
            purged, source, tmp_path, cluster, port
        )
        sealed = tmp_path / "custody" / "planned.json"
        marker = tmp_path / "control" / "planned.json"
        arguments = {
            "source": Database(target.database_url),
            "checkpoint_path": sealed,
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "marker": marker,
            "target": target,
            "provision": _provision(purged.scratch),
            "set_aside": True,
        }
        restore_planned(**arguments)
        _stale(marker)
        with pytest.raises(RestoreRefused) as refused:
            return_to_source(
                target=target,
                name=database,
                source_purge=Database(target.purge_url),
                checkpoint_path=sealed,
                marker=marker,
                set_aside=True,
            )
        assert "may have served since: do not drop it" in str(refused.value)
        assert "never served" not in str(refused.value)
        # The rerun the refusal names completes the marker without replaying again.
        served = _replay_trace(target.database_url)
        result = restore_planned(**arguments)
        assert _replay_trace(target.database_url) == served
        assert result["resumed"] is True and result["tombstones_left_open"] == {}
        assert json.loads(marker.read_bytes())["state"] == "complete"


def test_a_stale_pending_marker_never_has_a_served_recovery_dropped(purged, source, tmp_path):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import abandon_declared

    taken, backup_store = source
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    with scratch_cluster(owner=owner) as (cluster, port):
        target = _target(cluster, port, owner, database, purged.scratch, tmp_path)
        arguments = {
            "backup_set": taken.directory,
            "backup_stores": {"blobs": backup_store},
            "export": export,
            "custody": export.parent,
            "declaration": _declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            "max_export_lag": _LAG,
            "marker": marker,
            "target": target,
            "provision": _provision(purged.scratch),
        }
        recover_declared(**arguments)
        _stale(marker)
        with pytest.raises(RestoreRefused) as refused:
            abandon_declared(target=target, export=export, marker=marker)
        assert "may have served since: do not drop it" in str(refused.value)
        assert "never served" not in str(refused.value)
        served = _replay_trace(target.database_url)
        result = recover_declared(**arguments)
        assert _replay_trace(target.database_url) == served
    assert result["resumed"] is True and json.loads(marker.read_bytes())["state"] == "complete"


def test_a_return_refuses_by_name_when_its_connection_cannot_comment_on_the_source():
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import _mark_the_source

    with scratch_cluster(owner="exulanica") as (cluster, port):
        with psycopg.connect(cluster.url(port, "exulanica", "postgres"), autocommit=True) as c:
            c.execute("create role reader login bypassrls password 'reader-not-owner'")
        reader = f"postgresql://reader:reader-not-owner@127.0.0.1:{port}/postgres"
        with pytest.raises(RestoreRefused, match="needs its owner or a superuser"):
            _mark_the_source(reader)


def _identical_probes(purged, tmp_path, photo_dir):
    """Q10's fixture: two EXIF-free 64x48 JPEGs of different colours, whose intake probe artifacts
    are identical bytes, both captured before the set is taken. Returns the set, its backup copy and
    the two captures."""
    import hashlib as _hashlib

    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from PIL import Image

    from conftest import CountingVisionModel, ingest_observed

    pipeline = PhotoIngestPipeline(purged.repository, purged.store, vision=CountingVisionModel())
    captures = []
    for index, colour in enumerate(((200, 30, 30), (30, 200, 30))):
        path = photo_dir / f"plain-{index}.jpg"
        Image.new("RGB", (64, 48), colour).save(path, "JPEG")
        outcome = ingest_observed(pipeline, purged.repository, path)
        assert outcome.error is None, outcome.error
        digest = _hashlib.sha256(path.read_bytes()).digest()
        captures.append(
            purged.rows("select capture_id from capture where blob_sha256=%s", digest)[0][
                "capture_id"
            ]
        )
    shared = purged.rows(
        "select content_sha256 from artifact where kind='probe' and content_sha256 is not null "
        "group by content_sha256 having count(distinct source_blob_sha256) > 1"
    )
    assert shared, "the two probes are the same bytes"
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)
    backup_store = LocalContentAddressedStore(tmp_path / "backup-store" / "blobs")
    taken = take_backup_set(
        backup_url=purged.database(role=_ROLE, password=_PASSWORD).url,
        directory=tmp_path / "backup-sets",
        namespaces=[Namespace("blobs", purged.store, backup_store)],
        custody=tmp_path / "custody",
        restore_state_path=None,
        backup_domains=[purged.store.root, tmp_path / "backup-store"],
        identity={"profile": "single-host"},
        role=_ROLE,
    )
    return taken, backup_store, captures, bytes(shared[0]["content_sha256"]).hex()


def test_a_recovery_completes_when_a_live_capture_shares_a_withdrawn_ones_probe(
    purged, tmp_path, photo_dir
):
    _require_server_binaries()
    taken, backup_store, (withdrawn, live), probe = _identical_probes(purged, tmp_path, photo_dir)
    tombstone = purged.tombstone_the_capture(withdrawn)
    purged.worker().drain()
    export, _ = _export(purged, tmp_path)
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    marker = tmp_path / "control" / "restore.json"
    with scratch_cluster(owner=owner) as (cluster, port):
        result = recover_declared(
            backup_set=taken.directory,
            backup_stores={"blobs": backup_store},
            export=export,
            custody=export.parent,
            declaration=_declare(tmp_path, export, dt.datetime.now(dt.UTC)),
            max_export_lag=_LAG,
            marker=marker,
            target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
            provision=_provision(purged.scratch),
        )
    left = result["tombstones_left_open"]
    assert list(left) == [str(tombstone)] and f"artifact:{probe}" in left[str(tombstone)]
    assert json.loads(marker.read_bytes())["state"] == "complete"
    assert live  # the live capture is the holder


def test_a_planned_restore_completes_when_a_live_capture_shares_a_withdrawn_ones_probe(
    purged, tmp_path, photo_dir
):
    _require_server_binaries()
    from exulanica.orchestration.installation.recovery import restore_planned

    taken, backup_store, (withdrawn, _live), probe = _identical_probes(purged, tmp_path, photo_dir)
    tombstone = purged.tombstone_the_capture(withdrawn)
    purged.worker().drain()
    sealed = tmp_path / "custody" / "checkpoint.json"
    marker = tmp_path / "control" / "restore.json"
    loaded = read_backup_set(taken.directory)
    owner, database = loaded.database.owner_role, loaded.database.database
    try:
        with scratch_cluster(owner=owner) as (cluster, port):
            result = restore_planned(
                source=purged.database(),
                checkpoint_path=sealed,
                backup_set=taken.directory,
                backup_stores={"blobs": backup_store},
                marker=marker,
                target=_target(cluster, port, owner, database, purged.scratch, tmp_path),
                provision=_provision(purged.scratch),
            )
        left = result["tombstones_left_open"]
        assert list(left) == [str(tombstone)] and f"artifact:{probe}" in left[str(tombstone)]
    finally:
        _unseal(purged, sealed, tmp_path)
