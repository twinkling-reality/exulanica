"""Migration 0065: the texture set catalog, its pins, and who may touch it.

Two schemas, for two reasons that were measured rather than guessed.

The session's ``spine_schema`` is checked for structure. Its rows and grants are not trusted
here, because other tests act on that schema between these: the per-test truncation in
``tests/conftest.py`` runs against it, and ``tests/test_personal_request_replay.py`` provisions the
real ``exulanica_app`` role on it. So the pins and the grants are checked on a schema this module
migrates for itself, with every migration applied exactly as it is on disk, and nothing else
touching it, and no row or privilege assertion here depends on test order.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.roles import (
    EXECUTOR_ROLE,
    READ_ONLY_TABLES,
    RUNTIME_ROLE,
    provision_runtime_role,
)
from exulanica.env import env_get
from exulanica.migrations import migration_directory, migrations
from exulanica.world.texture_assets import TEXTURE_SET_ID_PATTERN, load_texture_catalog
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pg_harness import migrated_schema, open_scratch_connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = migration_directory() / "0065_texture_set_digests.sql"
MANIFEST = ROOT / "assets" / "textures" / "manifest.json"


def _runtime_roles(path: Path) -> tuple[str, ...]:
    """The roles a migration's read-only block loops over, read from the SQL itself."""
    block = re.search(r"foreach r in array array\[([^\]]+)\] loop", path.read_text())
    assert block is not None, f"{path.name} has no runtime-role grant loop"
    return tuple(re.findall(r"'([a-z_]+)'", block.group(1)))


#: The roles 0065 makes the catalog read-only for, read from the migration and compared below with
#: the roles `exulanica.db.roles` provisions.
RUNTIME_ROLES = _runtime_roles(MIGRATION)
TABLE = "world_texture_set"


def _code(text: str) -> str:
    """The SQL with its comments removed, so prose about a rule is not mistaken for the rule."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


# -- the file ----------------------------------------------------------------------------------


def test_0065_is_the_one_texture_migration_and_is_shaped_like_its_neighbours():
    texture = [m.path.name for m in migrations() if "texture" in m.path.name]
    assert texture == ["0065_texture_set_digests.sql"]
    assert re.fullmatch(r"(\d{4})_[a-z0-9_]+\.sql", MIGRATION.name)
    statements = [line for line in _code(MIGRATION.read_text()).splitlines() if line.strip()]
    assert statements[0] == "begin;"
    assert statements[1] == "select pg_advisory_xact_lock(119622309);"
    assert statements[-1] == "commit;"


def test_the_catalog_is_read_only_for_exactly_the_provisioned_runtime_roles():
    """The writer and the Selection executor, and no withdrawn pre-ADR-0011 name."""
    assert (RUNTIME_ROLE, EXECUTOR_ROLE) == RUNTIME_ROLES
    code = _code(MIGRATION.read_text())
    assert "if exists (select 1 from pg_roles where rolname = r)" in code


def test_the_catalog_is_not_a_workspace_table():
    code = _code(MIGRATION.read_text())
    assert "workspace_id" not in code
    assert "ws_isolation" not in code
    assert "row level security" not in code
    assert "current_workspace" not in code


def test_the_set_id_rule_is_the_asset_key_rule_character_for_character():
    reviewed = (migration_directory() / "0042_authored_world_objects.sql").read_text()
    asset_key = re.search(r"asset_key\s+text primary key check \(asset_key ~ '([^']+)'\)", reviewed)
    set_id = re.search(
        r"set_id\s+text not null check \(set_id ~ '([^']+)'\)", MIGRATION.read_text()
    )
    assert asset_key is not None and set_id is not None
    assert asset_key.group(1) == set_id.group(1) == TEXTURE_SET_ID_PATTERN
    library = (ROOT / "web/packages/loom-texture/src/library.ts").read_text()
    assert f"export const SET_ID_PATTERN = /{TEXTURE_SET_ID_PATTERN}/;" in library


def test_the_read_only_list_names_the_catalog():
    """0065 revokes writes on the catalog, and that revoke is not sufficient alone.

    ``provision_runtime_role`` grants ``select, insert, update`` on every table in the schema and
    then revokes insert and update on ``READ_ONLY_TABLES``. A pinned catalog absent from that tuple
    has its migration-time revoke handed straight back on the next deployment, as
    ``tests/test_world_objects.py`` says of 0042's registries.
    """
    assert TABLE in READ_ONLY_TABLES
    assert "world_reviewed_asset" in READ_ONLY_TABLES


# -- the spine schema --------------------------------------------------------------------------


def test_the_spine_schema_carries_the_catalog_with_its_checks_and_guard(spine_schema):
    psycopg_module, scratch = spine_schema
    connection = open_scratch_connection(psycopg_module, scratch)
    connection.row_factory = dict_row
    try:
        checks = {
            row["definition"]
            for row in connection.execute(
                "select pg_get_constraintdef(c.oid) as definition from pg_constraint c "
                "join pg_class t on t.oid = c.conrelid "
                "join pg_namespace n on n.oid = t.relnamespace "
                "where n.nspname = current_schema() and t.relname = %s",
                (TABLE,),
            ).fetchall()
        }
        assert "PRIMARY KEY (set_id, version)" in checks
        assert "UNIQUE (content_sha256)" in checks
        assert any("set_id ~" in check and "[a-z0-9.-]" in check for check in checks)
        assert any("content_sha256 ~" in check and "{64}" in check for check in checks)
        assert any("byte_size > 0" in check for check in checks)
        assert any("truth = 'invented'" in check for check in checks)
        triggers = {
            row["tgname"]
            for row in connection.execute(
                "select t.tgname from pg_trigger t join pg_class c on c.oid = t.tgrelid "
                "join pg_namespace n on n.oid = c.relnamespace "
                "where n.nspname = current_schema() and c.relname = %s and not t.tgisinternal",
                (TABLE,),
            ).fetchall()
        }
        assert triggers == {"tg_world_texture_set_is_migration_data"}
    finally:
        connection.close()


# -- a schema this module migrates for itself --------------------------------------------------


@pytest.fixture(scope="module")
def own_schema():
    with migrated_schema() as (psycopg_module, owner):
        scratch = owner.execute("select current_schema()").fetchone()[0]
        owner.commit()
        yield psycopg_module, scratch


@pytest.fixture
def connection(own_schema):
    psycopg_module, scratch = own_schema
    opened = open_scratch_connection(psycopg_module, scratch)
    opened.row_factory = dict_row
    try:
        yield opened
    finally:
        opened.close()


def test_the_pinned_rows_are_the_manifest_exactly(connection):
    rows = connection.execute(
        "select set_id, version, content_sha256, byte_size, width, height, extent_u_mm, "
        "extent_v_mm, channels, licence_id, licence_sha256, title, summary, media_type, truth "
        f"from {TABLE} order by set_id, version"
    ).fetchall()
    manifest = json.loads(MANIFEST.read_bytes())
    as_entries = [
        {
            "set_id": row["set_id"],
            "version": row["version"],
            "content_sha256": row["content_sha256"],
            "byte_size": row["byte_size"],
            "resolution": {"width": row["width"], "height": row["height"]},
            "channels": row["channels"],
            "extent_mm": {"u": row["extent_u_mm"], "v": row["extent_v_mm"]},
            "licence_id": row["licence_id"],
            "licence_sha256": row["licence_sha256"],
        }
        for row in rows
    ]
    assert as_entries == manifest["sets"]
    # And the descriptive columns are the containers' own headers, set by set.
    catalog = load_texture_catalog()
    for row in rows:
        pinned = catalog.sets[row["set_id"]]
        assert (row["title"], row["summary"]) == (pinned.title, pinned.summary)
        assert row["media_type"] == "application/vnd.exulanica.texture-set"
        assert row["truth"] == "invented"


def test_the_catalog_is_global_and_carries_no_isolation(connection):
    row = connection.execute(
        "select c.relrowsecurity, c.relforcerowsecurity, "
        "(select count(*) from pg_policies p where p.schemaname = n.nspname "
        " and p.tablename = c.relname) as policies, "
        "exists (select 1 from pg_attribute a where a.attrelid = c.oid "
        " and a.attname = 'workspace_id' and not a.attisdropped) as scoped "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = current_schema() and c.relname = %s",
        (TABLE,),
    ).fetchone()
    assert row == {
        "relrowsecurity": False,
        "relforcerowsecurity": False,
        "policies": 0,
        "scoped": False,
    }


@pytest.mark.parametrize("role", RUNTIME_ROLES)
def test_the_runtime_roles_read_the_catalog_and_cannot_write_it(connection, role):
    present = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
    if present is None:
        # 0065's grant loop, like 0042's, grants only to a role that exists when it runs. The one
        # server without the runtime roles is one nobody provisioned: every private test server
        # creates them before migrating, so there their absence is a defect, not a reason to skip.
        if env_get("TEST_POSTGRES") == "private":
            pytest.fail(f"{role} is missing on a private test server, which creates it first")
        pytest.skip(
            f"{role} was never created on this hand-started server, so 0065's grant loop had "
            "nothing to revoke from; a provisioned or private test server has it, and the "
            "provisioning test below covers enforcement either way"
        )
    privileges = connection.execute(
        "select has_table_privilege(%(role)s, %(table)s, 'SELECT') as can_read, "
        "has_table_privilege(%(role)s, %(table)s, 'INSERT') as can_insert, "
        "has_table_privilege(%(role)s, %(table)s, 'UPDATE') as can_update, "
        "has_table_privilege(%(role)s, %(table)s, 'DELETE') as can_delete",
        {"role": role, "table": TABLE},
    ).fetchone()
    assert privileges == {
        "can_read": True,
        "can_insert": False,
        "can_update": False,
        "can_delete": False,
    }


def _new_version_row() -> dict[str, object]:
    return {
        "set_id": "cc0.brick-running-bond",
        "version": 99,
        "title": "Brick, running bond",
        "summary": "A version nothing baked.",
        "media_type": "application/vnd.exulanica.texture-set",
        "truth": "invented",
        "content_sha256": "e" * 64,
        "byte_size": 1,
        "width": 1,
        "height": 1,
        "extent_u_mm": 1,
        "extent_v_mm": 1,
        "channels": Jsonb([]),
        "licence_id": "CC0-1.0",
        "licence_sha256": "d" * 64,
    }


def _insert(target) -> None:
    row = _new_version_row()
    target.execute(
        sql.SQL("insert into {} ({}) values ({})").format(
            sql.Identifier(TABLE),
            sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL(",").join(sql.Placeholder(name) for name in row),
        ),
        row,
    )


def _privileges(connection, role: str) -> dict[str, bool]:
    return connection.execute(
        "select has_table_privilege(%(role)s, %(table)s, 'SELECT') as can_read, "
        "has_table_privilege(%(role)s, %(table)s, 'INSERT') as can_insert, "
        "has_table_privilege(%(role)s, %(table)s, 'UPDATE') as can_update, "
        "has_table_privilege(%(role)s, %(table)s, 'DELETE') as can_delete",
        {"role": role, "table": TABLE},
    ).fetchone()


def test_provisioning_leaves_the_catalog_read_only_and_the_trigger_is_the_second_wall(
    connection,
):
    """Both walls, measured.

    ``provision_runtime_role`` grants insert and update on every table and revokes them from
    ``READ_ONLY_TABLES``, which names the catalog, so a role provisioned after 0065 can read it and
    write nothing. The trigger is the second wall: the same role, handed INSERT and UPDATE by a
    later mistake, is still refused. A suffixed role, because a role is a cluster object and this
    must not rewrite the developer's own ``exulanica_app``.
    """
    role = f"texture_app_{uuid.uuid4().hex[:12]}"
    try:
        provision_runtime_role(connection, role=role)
        assert _privileges(connection, role) == {
            "can_read": True,
            "can_insert": False,
            "can_update": False,
            "can_delete": False,
        }
        connection.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        try:
            assert connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"] == 8
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                _insert(connection)
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                connection.execute(f"update {TABLE} set title = 'renamed'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
                connection.execute(f"delete from {TABLE}")
        finally:
            connection.execute("reset role")

        connection.execute(
            sql.SQL("grant insert, update on {} to {}").format(
                sql.Identifier(TABLE), sql.Identifier(role)
            )
        )
        assert _privileges(connection, role)["can_insert"] is True
        connection.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="migrations"):
                _insert(connection)
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="pinned"):
                connection.execute(f"update {TABLE} set title = 'renamed'")
        finally:
            connection.execute("reset role")
        assert connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"] == 8
    finally:
        connection.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))


def test_a_pinned_row_never_changes_or_disappears_even_for_the_owner(connection):
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="new version"):
        connection.execute(f"update {TABLE} set content_sha256 = %s", ("f" * 64,))
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="pinned"):
        connection.execute(f"delete from {TABLE} where set_id = 'cc0.kerb-stone'")
    assert connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"] == 8


def test_the_owner_can_pin_a_new_version_as_a_later_migration_would(connection):
    with connection.transaction(force_rollback=True):
        _insert(connection)
        versions = connection.execute(
            f"select version from {TABLE} where set_id = 'cc0.brick-running-bond' order by version"
        ).fetchall()
        assert [row["version"] for row in versions] == [1, 99]
    assert connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"] == 8


def test_provisioning_before_0065_leaves_the_catalog_read_only_once_it_exists(monkeypatch):
    """Provisioning runs on schemas migrated part of the way, and must not assume a later table.

    A deployment provisions its runtime role before a pending migration runs, and tests provision
    schemas stopped below a migration, so provisioning revokes writes only on read-only tables
    that exist. Here a role is provisioned on a schema that stops before 0065. Applying 0065 then
    hands that role SELECT, INSERT and UPDATE on the new table through its default privileges,
    because 0065's own grant block names only the provisioned exulanica roles, and reprovisioning
    takes the writes back.
    """
    import pg_harness

    below = [migration for migration in migrations() if migration.version < "0065"]
    role = f"texture_upgrade_{uuid.uuid4().hex[:12]}"
    with monkeypatch.context() as patch:
        patch.setattr(pg_harness, "migrations", lambda: iter(below))
        with pg_harness.migrated_schema() as (_, admin):
            admin.row_factory = dict_row
            try:
                missing = admin.execute("select to_regclass(%s) as found", (TABLE,)).fetchone()
                assert missing["found"] is None
                provision_runtime_role(admin, role=role)
                admin.commit()
                admin.execute(MIGRATION.read_text())
                handed = _privileges(admin, role)
                assert handed["can_read"] and handed["can_insert"] and handed["can_update"]
                provision_runtime_role(admin, role=role)
                assert _privileges(admin, role) == {
                    "can_read": True,
                    "can_insert": False,
                    "can_update": False,
                    "can_delete": False,
                }
            finally:
                admin.rollback()
                present = admin.execute("select 1 from pg_roles where rolname = %s", (role,))
                if present.fetchone() is not None:
                    admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                    admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
                admin.commit()
