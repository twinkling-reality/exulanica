"""Migration 0065: the texture set catalog, its pins, and who may touch it.

Two schemas, for two reasons that were measured rather than guessed.

The session's ``spine_schema`` is checked for structure. Its rows are not trusted here: the
per-test truncation in ``tests/conftest.py`` empties every table outside ``_PRESERVED_TABLES``,
which does not yet name ``world_texture_set``, and ``tests/test_personal_request_replay.py``
provisions the real ``exulanica_app`` role on that schema, which grants it INSERT and UPDATE on
every table ``READ_ONLY_TABLES`` does not name. Either would make a row or privilege assertion
depend on test order. So the pins and the grants are checked on a schema this module migrates for
itself, with every migration applied exactly as it is on disk, and nothing else touching it.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.roles import READ_ONLY_TABLES, provision_runtime_role
from exulanica.migrations import migration_directory, migrations
from exulanica.world.texture_assets import TEXTURE_SET_ID_PATTERN, load_texture_catalog
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pg_harness import migrated_schema, open_scratch_connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = migration_directory() / "0065_texture_set_digests.sql"
MANIFEST = ROOT / "assets" / "textures" / "manifest.json"
RUNTIME_ROLES = ("exulanica_app", "exulanica_ro", "orimera_app", "orimera_ro")
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
    publish = (ROOT / "web/packages/loom-texture/src/publish.ts").read_text()
    assert f"export const SET_ID_PATTERN = /{TEXTURE_SET_ID_PATTERN}/;" in publish


def test_the_read_only_list_does_not_name_the_catalog_yet():
    """The deferral, stated as a fact so it cannot go stale in the documentation.

    ``exulanica/db/roles.py`` was closed to every lane when 0065 was written. When the table joins
    ``READ_ONLY_TABLES``, this test fails, and docs/texture-package.md and the provisioning test
    below should change with it.
    """
    assert TABLE not in READ_ONLY_TABLES
    assert TABLE in (ROOT / "docs" / "texture-package.md").read_text()


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
        pytest.skip(
            f"{role} does not exist on this server, so 0065's grant loop skipped it, as 0042's "
            "does; the provisioning test below covers enforcement without it"
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


def test_provisioning_grants_writes_that_the_trigger_still_refuses(connection):
    """The deferral, measured, and the reason the trigger exists.

    ``provision_runtime_role`` grants insert and update on every table and revokes them only from
    ``READ_ONLY_TABLES``. A role provisioned after 0065 therefore holds INSERT and UPDATE on the
    catalog, and the trigger is what refuses it. A suffixed role, because a role is a cluster
    object and this must not rewrite the developer's own ``exulanica_app``.
    """
    role = f"texture_app_{uuid.uuid4().hex[:12]}"
    try:
        provision_runtime_role(connection, role=role)
        granted = connection.execute(
            "select has_table_privilege(%(role)s, %(table)s, 'INSERT') as can_insert, "
            "has_table_privilege(%(role)s, %(table)s, 'UPDATE') as can_update, "
            "has_table_privilege(%(role)s, %(table)s, 'DELETE') as can_delete",
            {"role": role, "table": TABLE},
        ).fetchone()
        assert granted == {"can_insert": True, "can_update": True, "can_delete": False}

        connection.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="migrations"):
                _insert(connection)
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="pinned"):
                connection.execute(f"update {TABLE} set title = 'renamed'")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(f"delete from {TABLE}")
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
