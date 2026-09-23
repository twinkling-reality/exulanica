"""Migration 0076: each pinned texture set's container profile and material class, and its walls.

The class lives in ``world_texture_set_class``, keyed by the pin's own ``(set_id, version)``, so no
0065 row is ever touched. What is checked here, on a schema this module migrates for itself (as
``tests/test_texture_set_migration.py`` does, and for the same reason: other tests act on the
session's spine schema):

- the layout function is the readers' table, pair for pair;
- the two tables joined are the published manifest, entry for entry;
- a class that does not describe the pinned bytes is refused, and so is a set pinned without one;
- a class row never changes or disappears, even for the owner, and the runtime reads and never
  writes it, before and after provisioning;
- the shared registrations a global reviewed table needs are made.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.db.registries import REGISTRY_TABLES
from exulanica.db.roles import EXECUTOR_ROLE, READ_ONLY_TABLES, RUNTIME_ROLE, provision_runtime_role
from exulanica.env import env_get
from exulanica.materials.classes import MATERIAL_CLASSES, TEXTURE_SET_PROFILES, allowed_channels
from exulanica.migrations import migration_directory
from exulanica.orchestration.judge_seed import GLOBAL_TABLES
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from pg_harness import migrated_schema, open_scratch_connection

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = migration_directory() / "0076_texture_set_classes.sql"
MANIFEST = ROOT / "assets" / "textures" / "manifest.json"
TABLE = "world_texture_set_class"
SETS = "world_texture_set"
V1 = "exulanica.texture-set/v1"
V2 = "exulanica.texture-set/v2"


def _code(text: str) -> str:
    """The SQL with its comments removed, so prose about a rule is not mistaken for the rule."""
    return "\n".join(line.split("--", 1)[0] for line in text.splitlines())


def _manifest_sets() -> list[dict]:
    return json.loads(MANIFEST.read_bytes())["sets"]


# -- the file ----------------------------------------------------------------------------------


def test_0076_is_shaped_like_its_neighbours_and_is_not_a_workspace_table():
    statements = [line for line in _code(MIGRATION.read_text()).splitlines() if line.strip()]
    assert statements[0] == "begin;"
    assert statements[1] == "select pg_advisory_xact_lock(119622309);"
    assert statements[-1] == "commit;"
    code = _code(MIGRATION.read_text())
    for absent in ("workspace_id", "ws_isolation", "row level security", "current_workspace"):
        assert absent not in code
    # No wall is lowered: nothing here disables a trigger or updates or deletes a pinned row.
    assert "disable trigger" not in code.lower()
    assert not re.search(r"\b(update|delete from)\s+world_texture_set\b", code, re.IGNORECASE)


def test_the_runtime_roles_it_grants_to_are_the_provisioned_ones():
    block = re.search(r"foreach r in array array\[([^\]]+)\] loop", MIGRATION.read_text())
    assert block is not None
    assert tuple(re.findall(r"'([a-z_]+)'", block.group(1))) == (RUNTIME_ROLE, EXECUTOR_ROLE)


def test_the_shared_registrations_name_the_table():
    # REGISTRY_TABLES feeds the harness's preserved set too; tests/test_registry_tables.py holds
    # each place that acts on the registries to all of them.
    assert TABLE in REGISTRY_TABLES
    assert TABLE in READ_ONLY_TABLES
    assert TABLE in GLOBAL_TABLES


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


def test_the_layout_function_is_the_readers_table_for_every_pair(connection):
    for profile in TEXTURE_SET_PROFILES:
        for material_class in MATERIAL_CLASSES:
            row = connection.execute(
                "select texture_set_layouts(%s, %s) as layouts", (profile, material_class)
            ).fetchone()
            expected = [list(layout) for layout in allowed_channels(profile, material_class)]
            assert row["layouts"] == expected, (profile, material_class)
    # A name outside the closed lists allows nothing, whichever of the two it is.
    for profile, material_class in (
        ("exulanica.texture-set/v3", "opaque"),
        ("exulanica.texture-set/v2", "emissive"),
        ("exulanica.texture-set/v1", "Opaque"),
    ):
        row = connection.execute(
            "select texture_set_layouts(%s, %s) as layouts", (profile, material_class)
        ).fetchone()
        assert row["layouts"] == [], (profile, material_class)


def test_the_table_checks_its_names_itself_as_well(connection):
    """The trigger refuses first, and the table's own checks stand behind it."""
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
    assert any(check.startswith("FOREIGN KEY (set_id, version) REFERENCES") for check in checks)
    assert any("container_profile" in check and V1 in check and V2 in check for check in checks)
    assert any(
        all(name in check for name in MATERIAL_CLASSES) and "material_class" in check
        for check in checks
    )
    assert any(
        "container_profile" in check
        and "material_class" in check
        and "'opaque'" in check
        and "ANY" not in check
        for check in checks
    )


def test_the_two_tables_joined_are_the_published_manifest(connection):
    rows = connection.execute(
        "select s.set_id, s.version, s.content_sha256, s.byte_size, s.width, s.height, "
        "s.extent_u_mm, s.extent_v_mm, s.channels, s.licence_id, s.licence_sha256, "
        "c.container_profile, c.material_class "
        f"from {SETS} s left join {TABLE} c using (set_id, version) order by s.set_id, s.version"
    ).fetchall()
    assert [
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
            "container_profile": row["container_profile"],
            "material_class": row["material_class"],
        }
        for row in rows
    ] == _manifest_sets()
    count = connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"]
    assert count == len(rows)


def test_the_table_is_global_and_carries_no_isolation(connection):
    row = connection.execute(
        "select c.relrowsecurity, c.relforcerowsecurity, "
        "(select count(*) from pg_policies p where p.schemaname = n.nspname "
        " and p.tablename = c.relname) as policies "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = current_schema() and c.relname = %s",
        (TABLE,),
    ).fetchone()
    assert row == {"relrowsecurity": False, "relforcerowsecurity": False, "policies": 0}


def _pin_a_new_version(connection, *, channels) -> None:
    """A set row a later migration might pin: a version nothing baked, with these channels."""
    row = {
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
        "channels": Jsonb(channels),
        "licence_id": "CC0-1.0",
        "licence_sha256": "d" * 64,
    }
    connection.execute(
        sql.SQL("insert into {} ({}) values ({})").format(
            sql.Identifier(SETS),
            sql.SQL(",").join(map(sql.Identifier, row)),
            sql.SQL(",").join(sql.Placeholder(name) for name in row),
        ),
        row,
    )


def _state_class(connection, profile: str, material_class: str) -> None:
    connection.execute(
        f"insert into {TABLE} (set_id, version, container_profile, material_class) "
        "values ('cc0.brick-running-bond', 99, %s, %s)",
        (profile, material_class),
    )


def _layout(profile: str, material_class: str) -> list:
    return list(allowed_channels(profile, material_class)[0])


def test_the_owner_can_pin_a_set_with_its_class_as_a_later_migration_would(connection):
    with connection.transaction(force_rollback=True):
        _pin_a_new_version(connection, channels=_layout(V2, "cutout"))
        _state_class(connection, V2, "cutout")
        connection.execute("set constraints all immediate")
        stated = connection.execute(
            f"select material_class from {TABLE} where set_id = 'cc0.brick-running-bond' "
            "and version = 99"
        ).fetchone()
        assert stated == {"material_class": "cutout"}


def test_a_set_pinned_without_its_class_does_not_commit(connection):
    with connection.transaction(force_rollback=True):
        _pin_a_new_version(connection, channels=_layout(V1, "opaque"))
        with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="without its"):
            connection.execute("set constraints all immediate")


@pytest.mark.parametrize(
    ("channels", "profile", "material_class"),
    [
        # The bytes are laid out as glazing, and the row says cutout.
        (_layout(V2, "glazing"), V2, "cutout"),
        # A v1 container is opaque by definition, so no layout is a v1 glazing layout.
        (_layout(V1, "opaque"), V1, "glazing"),
        # Names outside the closed lists allow no layout at all.
        (_layout(V1, "opaque"), "exulanica.texture-set/v3", "opaque"),
        (_layout(V2, "opaque"), V2, "emissive"),
    ],
)
def test_a_class_that_does_not_describe_the_pinned_bytes_is_refused(
    connection, channels, profile, material_class
):
    with connection.transaction(force_rollback=True):
        _pin_a_new_version(connection, channels=channels)
        with pytest.raises(psycopg.errors.CheckViolation, match="not a layout"):
            _state_class(connection, profile, material_class)


def test_a_class_for_a_set_nobody_pinned_is_refused(connection):
    with (
        connection.transaction(force_rollback=True),
        pytest.raises(psycopg.errors.CheckViolation, match="not a layout"),
    ):
        connection.execute(
            f"insert into {TABLE} (set_id, version, container_profile, material_class) "
            "values ('cc0.nothing', 1, %s, 'opaque')",
            (V1,),
        )


def test_a_class_row_never_changes_or_disappears_even_for_the_owner(connection):
    count = connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="new version"):
        connection.execute(f"update {TABLE} set material_class = 'decal'")
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="new version"):
        connection.execute(f"delete from {TABLE} where set_id = 'cc0.kerb-stone'")
    assert connection.execute(f"select count(*) as n from {TABLE}").fetchone()["n"] == count


def _privileges(connection, role: str) -> dict[str, bool]:
    return connection.execute(
        "select has_table_privilege(%(role)s, %(table)s, 'SELECT') as can_read, "
        "has_table_privilege(%(role)s, %(table)s, 'INSERT') as can_insert, "
        "has_table_privilege(%(role)s, %(table)s, 'UPDATE') as can_update, "
        "has_table_privilege(%(role)s, %(table)s, 'DELETE') as can_delete",
        {"role": role, "table": TABLE},
    ).fetchone()


READ_ONLY = {"can_read": True, "can_insert": False, "can_update": False, "can_delete": False}


@pytest.mark.parametrize("role", (RUNTIME_ROLE, EXECUTOR_ROLE))
def test_the_runtime_roles_read_the_classes_and_cannot_write_them(connection, role):
    present = connection.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone()
    if present is None:
        if env_get("TEST_POSTGRES") == "private":
            pytest.fail(f"{role} is missing on a private test server, which creates it first")
        pytest.skip(f"{role} was never created on this hand-started server")
    assert _privileges(connection, role) == READ_ONLY


def test_provisioning_leaves_the_classes_read_only_and_the_trigger_is_the_second_wall(connection):
    role = f"texture_class_app_{uuid.uuid4().hex[:12]}"
    try:
        provision_runtime_role(connection, role=role)
        assert _privileges(connection, role) == READ_ONLY
        connection.execute(
            sql.SQL("grant insert, update, delete on {} to {}").format(
                sql.Identifier(TABLE), sql.Identifier(role)
            )
        )
        connection.execute(sql.SQL("set role {}").format(sql.Identifier(role)))
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege, match="migrations"):
                _state_class(connection, V1, "opaque")
            with pytest.raises(psycopg.errors.IntegrityConstraintViolation, match="new version"):
                connection.execute(f"update {TABLE} set material_class = 'decal'")
        finally:
            connection.execute("reset role")
    finally:
        connection.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
        connection.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(role)))
