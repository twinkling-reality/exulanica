"""``exulanica-local-db`` restores a backup taken before migration 0106 that holds a model right.

Before 0106, ``privacy_canonical`` resolved its own name through the caller's path, and
``pg_restore`` loads rows under an empty one, so the receipt CHECK of the first model right in a
dump stopped the restore (``exulanica.db.load_functions``). A backup that cannot be restored is the
loss a backup exists to prevent, and every backup taken before 0106 is such a dump the moment it
holds one model right. The restore now loads the schema, gives each function the rows will run a
path of its own, then loads the rows. The control arm is the same restore without that step,
which fails where every earlier restore of such a dump failed.
"""

from __future__ import annotations

import uuid

import pytest
from exulanica.db.local import backup as backup_module
from exulanica.db.local.backup import verify_backup
from exulanica.db.local.refusals import LocalDatabaseRefused, Refusal
from exulanica.evidence import BlobId
from exulanica.ingest.repository import IngestRepository
from exulanica.migrations import migrations
from exulanica.models.manifest import Role

from test_local_database_postgres import _init, _only_backup, _state, cli, migration_files
from test_local_database_postgres import module_machine as module_machine
from test_local_database_postgres import servers as servers
from test_search_entries_on_stop import _authorize, _grant

pytestmark = pytest.mark.postgres

#: The migration that gave ``privacy_canonical`` a path of its own.
PINNED_IN = "0106"


def _grant_a_model_right(database, manifest) -> int:
    """A photograph, the account holder's authority over it and its search rights, as the owner."""
    port = database.cluster.running_port()
    with database.connect(port) as connection:
        repository = IngestRepository(connection, uuid.uuid4())
        payload = b"a photograph whose search right is granted before migration 0106"
        blob = BlobId.of_bytes(payload)
        repository.upsert_blob(
            blob, byte_size=len(payload), media_type="image/jpeg", storage_key=f"test/{blob.hex}"
        )
        capture = repository.insert_capture(blob, device_id=None, started_at=None)
        authorization = _authorize(repository, capture.capture_id)
        rights = _grant(
            repository, capture.capture_id, authorization.authorization_id, Role.EMBEDDING, manifest
        )
        return len(rights)


def _grants(connection) -> list:
    """Every privilege on every relation and function of the schema, defaults written out.

    An ACL equal to its object's default is the same privileges as none, and ``pg_dump`` writes
    none: measured, the unsectioned restore this one replaced drops the owner's explicit entry on
    ``predicate_predicate_id_seq`` exactly as this one does. So privileges are compared, not ACLs.
    """
    return connection.execute(
        "select c.oid::regclass::text as object, a.grantor::regrole::text as grantor, "
        "case a.grantee when 0 then 'PUBLIC' else a.grantee::regrole::text end as grantee, "
        "a.privilege_type from pg_class c "
        "join pg_namespace n on n.oid = c.relnamespace, lateral aclexplode(coalesce(c.relacl, "
        "acldefault((case c.relkind when 'S' then 's' else 'r' end)::\"char\", c.relowner))) a "
        "where n.nspname = 'public' "
        "union all select p.oid::regprocedure::text, a.grantor::regrole::text, "
        "case a.grantee when 0 then 'PUBLIC' else a.grantee::regrole::text end, "
        "a.privilege_type from pg_proc p join pg_namespace n on n.oid = p.pronamespace, "
        "lateral aclexplode(coalesce(p.proacl, acldefault('f'::\"char\", p.proowner))) a "
        "where n.nspname = 'public' order by 1, 2, 3, 4"
    ).fetchall()


def test_a_backup_taken_before_0106_that_holds_a_model_right_restores(
    module_machine, servers, manifest, tmp_path, monkeypatch
):
    after = sum(1 for migration in migrations() if migration.version >= PINNED_IN)
    with migration_files(tmp_path / "migrations", drop_last=after) as versions:
        assert versions[-1] < PINNED_IN, versions[-1]
        database = _init(servers, tmp_path / "database")
        granted = _grant_a_model_right(database, manifest)
        with database.connect(database.cluster.running_port()) as connection:
            source_grants = _grants(connection)
        stopped = cli("stop", "--directory", database.root)
        assert stopped.status == 0, stopped.err
    backup = _only_backup(database, "stop")
    assert backup.migrations[-1] == versions[-1]
    assert backup.row_counts["public.personal_model_right"] == granted >= 1

    with monkeypatch.context() as unpinned:
        unpinned.setattr(backup_module, "pin_loading_functions", lambda connection: [])
        with pytest.raises(LocalDatabaseRefused) as refused:
            verify_backup(backup)
    assert refused.value.refusal is Refusal.RESTORE_FAILED
    assert "privacy_canonical" in refused.value.detail
    assert "personal_model_right" in refused.value.detail

    verified = cli("verify", "--directory", database.root)
    assert verified.status == 0, verified.err
    assert f"restorable: {backup.dump}" in verified.out

    restored_at = tmp_path / "restored"
    restored = cli("restore", "--directory", restored_at, backup.dump)
    assert restored.status == 0, restored.err
    copy = servers.track(restored_at)
    versions_restored, counts = _state(copy)
    assert counts == backup.row_counts
    assert tuple(versions_restored) == backup.migrations
    with copy.connect(copy.cluster.running_port()) as connection:
        assert _grants(connection) == source_grants
        [config] = (
            connection.execute("select proconfig from pg_proc where proname = 'privacy_canonical'")
            .fetchone()
            .values()
        )
    assert config == ["search_path=public, pg_catalog, pg_temp"]
