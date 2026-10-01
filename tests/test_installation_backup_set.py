"""A backup set is taken as the backup role, carries every stored object and restores exactly.

The database dump is the one the personal install already proves; what is added here is the
order (dump, bytes, a later withdrawal export, manifest last), the key-for-key store copy with its
digests, and a verification that fails by name on a missing or damaged object.
"""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from exulanica.db.local.backup import ROLE_ATTRIBUTES, Backup, _create_roles
from exulanica.db.roles import provision_backup_role
from exulanica.deletion.restore import RestoreRefused
from exulanica.orchestration.installation.backup_set import (
    BackupSetRefused,
    Namespace,
    read_backup_set,
    take_backup_set,
    verify_backup_set,
)
from exulanica.store.local import LocalContentAddressedStore

from test_purge import purged as purged
from test_restore_replay import _capture

_ROLE = "exulanica_backup_set_test"
_PASSWORD = "backup-set-test-" + uuid.uuid4().hex


@pytest.fixture
def backup(purged, tmp_path):
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        provision_backup_role(connection, role=_ROLE, password=_PASSWORD)
    target = LocalContentAddressedStore(tmp_path / "backup-store" / "blobs")

    def take(**overrides):
        arguments = {
            "backup_url": purged.database(role=_ROLE, password=_PASSWORD).url,
            "directory": tmp_path / "backup-sets",
            "namespaces": [Namespace("blobs", purged.store, target)],
            "custody": tmp_path / "custody",
            "restore_state_path": None,
            "backup_domains": [purged.store.root, tmp_path / "backup-store"],
            "identity": {"profile": "single-host", "code_revision": "a" * 40},
            "role": _ROLE,
        }
        arguments.update(overrides)
        return take_backup_set(**arguments)

    return take, target


def test_a_set_holds_every_object_and_a_later_export_and_restores(purged, backup):
    take, target = backup
    purged.tombstone_the_capture(_capture(purged))
    taken = take()
    record = read_backup_set(taken.directory).manifest["record"]
    source = sorted(blob.hex for blob in purged.store.iter_blob_ids())
    assert record["store"]["keys"] == len(source) > 0
    assert sorted(blob.hex for blob in target.iter_blob_ids()) == source
    assert record["withdrawal_export"]["covered_through"] >= record["database"]["snapshot_taken_in"]
    assert record["identity"]["code_revision"] == "a" * 40
    proved = verify_backup_set(taken.directory, {"blobs": target})
    assert proved["objects"] == len(source)
    assert proved["rows"] == record["database"]["rows"] > 0


def test_a_second_set_copies_only_what_is_new(purged, backup):
    take, target = backup
    take()
    before = {blob.hex for blob in target.iter_blob_ids()}
    added = purged.store.put_bytes(b"a later photograph's bytes " + uuid.uuid4().bytes).blob_id
    second = take()
    assert {blob.hex for blob in target.iter_blob_ids()} == before | {added.hex}
    assert read_backup_set(second.directory).manifest["record"]["store"]["keys"] == len(before) + 1


def test_verification_names_a_missing_or_damaged_object(purged, backup, tmp_path):
    take, target = backup
    taken = take()
    victim = next(iter(target.iter_blob_ids()))
    path = target.root / "sha-256" / victim.hex[:2] / victim.hex[2:4] / victim.hex
    assert path.exists()
    original = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(b"not the bytes this key names")
    with pytest.raises(BackupSetRefused, match="backup_object_corrupt"):
        verify_backup_set(taken.directory, {"blobs": target})
    path.unlink()
    with pytest.raises(BackupSetRefused, match="backup_object_missing"):
        verify_backup_set(taken.directory, {"blobs": target})
    path.write_bytes(original)
    manifest = taken.directory / "backup-set.json"
    envelope = json.loads(manifest.read_bytes())
    envelope["record"]["store"]["keys"] = 0
    manifest.write_text(json.dumps(envelope))
    with pytest.raises(BackupSetRefused, match="backup_set_invalid"):
        verify_backup_set(taken.directory, {"blobs": target})


def test_a_set_refuses_an_unreadable_table_and_custody_inside_a_backup(purged, backup, tmp_path):
    take, _ = backup
    added = f'"{purged.scratch}".added_after_the_backup_role'
    with purged.database().unscoped() as connection:
        connection.execute(f"create table {added} (x int)")
        # Granted by default privilege when the owner creates it; one without the grant refuses.
        connection.execute(f'revoke select on {added} from "{_ROLE}"')
    try:
        with pytest.raises(BackupSetRefused, match="backup_role_incomplete"):
            take()
    finally:
        with purged.database().unscoped() as connection:
            connection.execute(f"drop table {added}")
    with pytest.raises(RestoreRefused, match="backup domain"):
        take(custody=tmp_path / "backup-sets" / "custody")
    shutil.rmtree(tmp_path / "backup-sets", ignore_errors=True)


def test_a_set_carries_no_sign_in_secrets(purged, backup):
    """Pending logins and browser sessions hold plaintext nonces, verifiers and CSRF tokens."""
    import subprocess

    from exulanica.orchestration.installation.backup_set import EPHEMERAL_TABLES

    from test_restore_replay import _postgres_tool

    take, _ = backup
    taken = take()
    dump = taken.database
    assert dump.manifest["excluded_table_data"] == sorted(EPHEMERAL_TABLES)
    contents = subprocess.run(
        [_postgres_tool("pg_restore"), "--list", str(dump.dump)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    for table in EPHEMERAL_TABLES:
        assert f"TABLE {purged.scratch} {table} " in contents or f" {table} " in contents
        assert not any(
            "TABLE DATA" in line and f" {table} " in line for line in contents.splitlines()
        ), table


def test_an_object_erased_by_a_purge_is_accepted_and_no_other(purged, backup):
    take, target = backup
    taken = take()
    victim = next(iter(target.iter_blob_ids()))
    path = target.root / "sha-256" / victim.hex[:2] / victim.hex[2:4] / victim.hex
    path.unlink()
    with pytest.raises(BackupSetRefused, match="backup_object_missing"):
        verify_backup_set(taken.directory, {"blobs": target}, erased={"0" * 64})
    proved = verify_backup_set(taken.directory, {"blobs": target}, erased={victim.hex})
    assert proved["erased_objects"] == 1


def test_no_password_reaches_a_program_argument(purged, backup, monkeypatch):
    """Arguments are visible to every process on the host; the backup role reads every row."""
    import exulanica.db.local.backup as local_backup

    real, seen = local_backup.run, []

    def recording(program, *arguments, refusal):
        seen.append((program, arguments))
        return real(program, *arguments, refusal=refusal)

    monkeypatch.setattr(local_backup, "run", recording)
    take, _ = backup
    take()
    assert seen and seen[0][0] == "pg_dump"
    for _program, arguments in seen:
        assert not any(_PASSWORD in argument for argument in arguments), arguments


def test_a_restore_beside_existing_roles_grants_only_the_roles_it_creates(purged, tmp_path):
    # A membership revoked on the server after the backup was taken stays revoked.
    suffix = uuid.uuid4().hex[:8]
    parent, kept, created = (f"d3_{name}_{suffix}" for name in ("parent", "kept", "created"))
    attributes = {name: name == "rolinherit" for name in ROLE_ATTRIBUTES}
    manifest = {
        "roles": [
            {"name": name, "connection_limit": -1, **attributes} for name in (parent, kept, created)
        ],
        "memberships": [
            {"role": parent, "member": member, "admin": False, "inherit": True, "set": True}
            for member in (kept, created)
        ],
    }
    with purged.database().unscoped() as connection:
        connection.execute(f'create role "{parent}" nologin')
        connection.execute(f'create role "{kept}" nologin')
    try:
        with purged.database().unscoped() as connection:
            _create_roles(connection, Backup(tmp_path / "unused", manifest), keep_existing=True)
            members = {
                row[0] if isinstance(row, tuple) else row["rolname"]
                for row in connection.execute(
                    "select m.rolname from pg_auth_members a join pg_roles m on m.oid = a.member "
                    "join pg_roles r on r.oid = a.roleid where r.rolname = %s",
                    (parent,),
                ).fetchall()
            }
        assert members == {created}
    finally:
        with purged.database().unscoped() as connection:
            for name in (created, kept, parent):
                connection.execute(f'drop role if exists "{name}"')


def test_a_schema_that_records_its_migrations_verifies(purged, backup):
    """Versions recorded in a deployment schema other than public are read back from that schema.

    The dump reads them through the connection's own schema and the restored copy is opened
    without it, so before the manifest named the schema a populated schema failed verification.
    """
    from exulanica.migrations import migrations

    take, target = backup
    inserted = []
    with purged.database().unscoped() as connection:
        connection.execute(f'set search_path to "{purged.scratch}", public')
        for migration in migrations():
            row = connection.execute(
                "insert into schema_migrations (version, checksum) values (%s, %s) "
                "on conflict (version) do nothing returning version",
                (migration.version, migration.checksum),
            ).fetchone()
            if row is not None:
                inserted.append(migration.version)
    try:
        taken = take()
        assert taken.database.manifest["migrations_schema"] == purged.scratch
        verify_backup_set(taken.directory, {"blobs": target})
    finally:
        # Only the rows this test wrote: another fixture may have recorded the rest.
        with purged.database().unscoped() as connection:
            connection.execute(f'set search_path to "{purged.scratch}", public')
            connection.execute("delete from schema_migrations where version = any(%s)", (inserted,))


def test_a_password_file_matches_any_host_and_holds_one_url_each():
    """A Unix-socket host is looked up as localhost and a multi-host URL by each host: a file of
    its own per URL, any host and port, matches every case and nothing beyond this invocation."""
    import os
    import stat

    from exulanica.db.local.backup import _passwordless
    from psycopg.conninfo import conninfo_to_dict

    urls = (
        "host=/var/run/postgresql port=5432 user=owner password=one:two dbname=x",
        "host=a,b port=5432,5433 user=owner password=three dbname=x",
        "postgresql://reader@127.0.0.1:5432/x",
    )
    with _passwordless(*urls) as rewritten:
        files = [conninfo_to_dict(url).get("passfile") for url in rewritten]
        assert files[2] is None and rewritten[2] == urls[2]
        assert files[0] != files[1]
        contents = [Path(name).read_text(encoding="utf-8") for name in files[:2]]
        modes = [stat.S_IMODE(os.stat(name).st_mode) for name in files[:2]]
        assert all("password" not in conninfo_to_dict(url) for url in rewritten)
    assert contents == ["*:*:*:owner:one\\:two\n", "*:*:*:owner:three\n"]
    assert modes == [0o600, 0o600]
    assert not any(os.path.exists(name) for name in files[:2])


def test_a_set_binds_its_dump_manifest(purged, backup, tmp_path):
    """A restore acts on the dump manifest's roles and memberships, so the set's digest covers
    it: an edited manifest, whose own digest still names the dump, is refused."""
    from exulanica.db.local.backup import MANIFEST_SUFFIX

    take, target = backup
    taken = take()
    manifest = taken.database.dump.with_suffix(MANIFEST_SUFFIX)
    document = json.loads(manifest.read_text())
    document["memberships"].append(
        {"role": "exulanica_app", "member": "intruder", "admin": True, "inherit": True, "set": True}
    )
    manifest.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n")
    with pytest.raises(BackupSetRefused, match="not the one the set records"):
        verify_backup_set(taken.directory, {"blobs": target})
    # And a restore checks the same binding before it writes anything.
    from exulanica.orchestration.installation.recovery import Target, _check_set
    from exulanica.store.configured import local_content_stores

    named = f"postgresql://unused/{taken.database.database}"
    unused = Target(named, named, named, stores=local_content_stores(tmp_path / "unused"))
    with pytest.raises(BackupSetRefused, match="not the one the set records"):
        _check_set(taken.directory, unused)
