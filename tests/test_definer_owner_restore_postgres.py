"""A backup restores across migration 0161 in both directions with every definer narrowly owned.

0161 creates ``exulanica_definer`` and makes it the owner of every SECURITY DEFINER function. A role
belongs to the server, not the dump, so a restore must bring it back before the functions it owns;
and a dump taken before 0161 holds no such role. Each arm runs on its own fresh server, as a
restore onto a new machine does, and ends where ``exulanica-db`` would: provisioning has run and
:func:`~exulanica.db.definer_role.assert_definer_role` passes.

*   **Taken before 0161, restored, then upgraded.** The restored copy's definers belong to the
    migrating owner, as they did when the backup was taken; ``upgrade`` applies 0161, whose
    provisioning checks the result, and every definer then belongs to the narrow role.
*   **Taken after 0161, restored.** The manifest records the role with its attributes, the restore
    creates it before the schema, and the copy's definers keep that owner.
"""

from __future__ import annotations

import pytest
from exulanica.db.definer_role import (
    DEFINER_MIGRATION,
    DEFINER_ROLE,
    assert_definer_role,
    definer_role_installed,
)
from exulanica.migrations import migrations

from test_local_database_postgres import _init, _only_backup, _state, cli, migration_files
from test_local_database_postgres import module_machine as module_machine
from test_local_database_postgres import servers as servers

pytestmark = pytest.mark.postgres


def _owners(database) -> dict[str, str]:
    """Each SECURITY DEFINER function of the database's schema and the role that owns it."""
    with database.connect(database.cluster.running_port()) as connection:
        return {
            row["signature"]: row["owner"]
            for row in connection.execute(
                "select p.oid::regprocedure::text signature, pg_get_userbyid(p.proowner) owner "
                "from pg_proc p where p.pronamespace = current_schema()::regnamespace "
                "and p.prosecdef"
            ).fetchall()
        }


def _checked(database) -> None:
    """The check passes, privileges included, and a definer runs in the copy: its body reads the
    spending tables as the narrow owner, under row-level security, with the grants restored."""
    with database.connect(database.cluster.running_port()) as connection:
        assert definer_role_installed(connection)
        assert_definer_role(connection)
        connection.execute("select * from spending_authority_facts()").fetchall()


def test_a_backup_taken_before_0161_restores_and_upgrades_to_a_narrow_owner(
    module_machine, servers, tmp_path
):
    after = sum(1 for migration in migrations() if migration.version >= DEFINER_MIGRATION)
    with migration_files(tmp_path / "older-code", drop_last=after) as versions:
        assert versions[-1] < DEFINER_MIGRATION, versions[-1]
        database = _init(servers, tmp_path / "database")
        before = _owners(database)
        stopped = cli("stop", "--directory", database.root)
        assert stopped.status == 0, stopped.err
    backup = _only_backup(database, "stop")
    assert backup.migrations[-1] == versions[-1]
    assert DEFINER_ROLE not in {role["name"] for role in backup.manifest["roles"]}
    assert before and DEFINER_ROLE not in set(before.values()), before

    restored_at = tmp_path / "restored"
    restored = cli("restore", "--directory", restored_at, backup.dump)
    assert restored.status == 0, restored.err
    copy = servers.track(restored_at)
    assert _owners(copy) == before

    upgraded = cli("upgrade", "--directory", copy.root)
    assert upgraded.status == 0, upgraded.err
    versions_after, _ = _state(copy)
    assert DEFINER_MIGRATION in versions_after
    owners = _owners(copy)
    assert set(before) <= set(owners)
    assert set(owners.values()) == {DEFINER_ROLE}, owners
    _checked(copy)


def test_a_backup_taken_after_0161_restores_the_role_before_the_functions_it_owns(
    module_machine, servers, tmp_path
):
    database = _init(servers, tmp_path / "database")
    owners = _owners(database)
    assert owners and set(owners.values()) == {DEFINER_ROLE}, owners
    stopped = cli("stop", "--directory", database.root)
    assert stopped.status == 0, stopped.err
    backup = _only_backup(database, "stop")
    (recorded,) = [role for role in backup.manifest["roles"] if role["name"] == DEFINER_ROLE]
    assert not any(
        recorded[attribute]
        for attribute in (
            "rolsuper",
            "rolinherit",
            "rolcreaterole",
            "rolcreatedb",
            "rolcanlogin",
            "rolreplication",
            "rolbypassrls",
        )
    ), recorded
    assert not [
        m for m in backup.manifest["memberships"] if DEFINER_ROLE in (m["role"], m["member"])
    ]

    restored_at = tmp_path / "restored"
    restored = cli("restore", "--directory", restored_at, backup.dump)
    assert restored.status == 0, restored.err
    copy = servers.track(restored_at)
    assert _owners(copy) == owners
    _checked(copy)


def test_a_later_migration_that_adds_a_definer_without_handing_it_over_stops_the_deployment(
    module_machine, servers, tmp_path
):
    """A definer a later migration creates belongs to the migrating owner until that migration
    hands it to the narrow role. ``init`` provisions as ``exulanica-db`` does, so it refuses."""
    later = (
        "begin;\n"
        "create function a_later_definer() returns integer language sql security definer "
        "set search_path = pg_catalog, pg_temp as 'select 1';\n"
        "revoke all on function a_later_definer() from public;\n"
        "commit;\n"
    )
    with migration_files(tmp_path / "later-code", extra={"9001_a_later_definer.sql": later}):
        result = cli("init", "--directory", tmp_path / "database")
    assert result.status != 0
    assert "a_later_definer()" in result.err, result.err
    assert "not owned by exulanica_definer" in result.err, result.err


def test_a_restore_carrying_a_widened_definer_owner_is_refused(module_machine, servers, tmp_path):
    """The manifest records the role as the source held it; a role widened on the source (here
    given LOGIN) comes back widened, and the restore refuses the copy before offering it."""
    database = _init(servers, tmp_path / "database")
    with database.connect(database.cluster.running_port()) as connection:
        connection.execute(f"alter role {DEFINER_ROLE} login")
    stopped = cli("stop", "--directory", database.root)
    assert stopped.status == 0, stopped.err
    backup = _only_backup(database, "stop")
    (recorded,) = [role for role in backup.manifest["roles"] if role["name"] == DEFINER_ROLE]
    assert recorded["rolcanlogin"]
    restored = cli("restore", "--directory", tmp_path / "restored", backup.dump)
    assert restored.status != 0
    assert "can log in" in restored.err, restored.err
