"""A baked tile is published by ``exulanica_tiles`` through one function, and by nobody else.

Migration 0138 makes ``record_baked_tile_bake`` run with its owner's rights and revokes it from
PUBLIC; ``exulanica-db`` grants it to the tile role alone (``exulanica/db/tiles_role.py``). A
baked tile is global, so a role that could call it could put bytes in front of every workspace
whose world covers that tile. Each test here names a way that could go wrong: the API's role or
the read-only role holding EXECUTE, PUBLIC holding it, a later provisioning handing it back, a
name inside the function resolved through a caller's search path, or the worker accepting a
publisher that can do more than publish.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from exulanica.db.account_roles import provision_account_role
from exulanica.db.roles import provision_backup_role, provision_purge_role, provision_runtime_role
from exulanica.db.tiles_role import (
    PUBLISH_FUNCTION,
    TilesRoleUnsafe,
    assert_tiles_role,
    provision_tiles_role,
    tile_publishers,
)
from exulanica.env import env_get
from exulanica.ingest.generated_tiles_command import check_publisher
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from conftest import scratch_role_database
from pg_harness import open_scratch_connection

pytestmark = pytest.mark.postgres

#: The digest 0072's check requires of an edit delta: sha256 of the canonical JSON ``[]``.
NO_EDITS = hashlib.sha256(b"[]").digest()


@pytest.fixture
def roles(spine_schema) -> Iterator[dict[str, str]]:
    """Every role ``exulanica-db`` provisions, under names of this test's own, provisioned in
    ``exulanica-db``'s order on the migrated scratch schema, and dropped afterwards."""
    psycopg_module, scratch = spine_schema
    suffix = uuid.uuid4().hex[:12]
    names = {
        kind: f"{kind}_{suffix}" for kind in ("app", "ro", "purge", "accounts", "backup", "tiles")
    }
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        _provision_all(admin, names)
        yield {"scratch": scratch, **names}
    finally:
        for role in names.values():
            if admin.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone():
                admin.execute(sql.SQL("drop owned by {}").format(sql.Identifier(role)))
                admin.execute(sql.SQL("drop role {}").format(sql.Identifier(role)))
        admin.close()


def _provision_all(admin: psycopg.Connection, names: dict[str, str]) -> None:
    provision_runtime_role(admin, role=names["app"])
    provision_runtime_role(admin, role=names["ro"], read_only=True)
    provision_purge_role(admin, role=names["purge"])
    provision_account_role(admin, role=names["accounts"])
    provision_backup_role(admin, role=names["backup"])
    provision_tiles_role(admin, role=names["tiles"])


@contextmanager
def _as(roles: dict[str, str], kind: str) -> Iterator[psycopg.Connection]:
    """A connection whose current user is the role, in a transaction that is rolled back, so a
    stored bake never reaches another test's global ``baked_tile``."""
    database = scratch_role_database(roles["scratch"], roles[kind])
    with psycopg.connect(database.url, row_factory=dict_row) as connection:
        try:
            yield connection
        finally:
            connection.rollback()


def _signature(scratch: str) -> str:
    name, arguments = PUBLISH_FUNCTION
    return f'"{scratch}".{name}({arguments})'


def _arguments(container: bytes) -> tuple:
    digest = uuid.uuid4().bytes * 2
    return (
        uuid.uuid4(),
        1,
        hashlib.sha256(b"params").digest(),
        hashlib.sha256(digest).digest(),
        hashlib.sha256(b"seed").digest(),
        json.dumps([]),
        hashlib.sha256(b"catalog").digest(),
        NO_EDITS,
        0,
        0,
        0,
        250_000,
        0,
        hashlib.sha256(b"document").digest(),
        8,
        hashlib.sha256(container).digest(),
        len(container),
        hashlib.sha256(b"batch").digest(),
        hashlib.sha256(b"nav").digest(),
        json.dumps({}),
    )


_CALL = (
    "select record_baked_tile_bake(%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, "
    "%s, %s, %s, %s, %s, %s, %s::jsonb) as outcome"
)


def test_the_tile_role_alone_may_execute_the_publish_function(roles):
    """Not PUBLIC, not the API's role, not the read-only role, not any other role the same
    provisioning makes: the function's grantees are the tile role and the role-free owner."""
    with _as(roles, "app") as connection:
        publishers = tile_publishers(connection)
    assert roles["tiles"] in publishers
    assert "public" not in publishers
    for kind in ("app", "ro", "purge", "accounts", "backup"):
        assert roles[kind] not in publishers, kind


@pytest.mark.parametrize("kind", ["app", "ro"])
def test_the_api_role_and_the_read_only_role_are_refused_execute(roles, kind):
    with _as(roles, kind) as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute(_CALL, _arguments(b"container"))


def test_the_tile_role_publishes_once_and_cannot_write_the_table_itself(roles):
    """Through the function: stored, then identical for the same bytes, then a fault for
    different bytes. Around it: no insert, update or read of the table."""
    arguments = _arguments(b"first container")
    with _as(roles, "tiles") as connection:
        assert connection.execute(_CALL, arguments).fetchone()["outcome"] == "stored"
        assert connection.execute(_CALL, arguments).fetchone()["outcome"] == "identical"
        changed = list(arguments)
        changed[15] = hashlib.sha256(b"other container").digest()
        assert connection.execute(_CALL, tuple(changed)).fetchone()["outcome"] == (
            "nondeterminism_detected"
        )
    with _as(roles, "tiles") as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("select 1 from baked_tile limit 1")
    with _as(roles, "tiles") as connection, pytest.raises(psycopg.errors.InsufficientPrivilege):
        connection.execute("update baked_tile set state = state")


def test_provisioning_again_gives_execute_back_to_nobody(roles, spine_schema):
    """Every role provisioner runs again, as every deployment's exulanica-db does after its
    migrations; the grantees are unchanged."""
    psycopg_module, scratch = spine_schema
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        before = tile_publishers(admin)
        _provision_all(admin, {k: v for k, v in roles.items() if k != "scratch"})
        after = tile_publishers(admin)
    finally:
        admin.close()
    assert after == before
    assert "public" not in after
    for kind in ("app", "ro", "purge", "accounts", "backup"):
        assert roles[kind] not in after, kind


def test_the_function_runs_as_its_owner_with_every_name_qualified(spine_schema):
    """SECURITY DEFINER, a search path of pg_catalog and pg_temp alone, and every relation and
    function the body names qualified, so no object a caller creates can stand in for one."""
    psycopg_module, scratch = spine_schema
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        row = admin.execute(
            "select p.prosecdef, p.proconfig, p.prosrc from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = %s and p.proname = %s",
            (scratch, PUBLISH_FUNCTION[0]),
        ).fetchone()
    finally:
        admin.close()
    assert row["prosecdef"] is True
    assert row["proconfig"] == ["search_path=pg_catalog, pg_temp"]
    body = re.sub(r"--[^\n]*", "", row["prosrc"])
    # `select * into stored` is PL/pgSQL's own variable, not a relation; `insert into` is.
    relations = re.findall(
        r"\b(?:from|insert\s+into|update|join)\s+([A-Za-z_\"][\w.\"]*)", body, re.I
    )
    assert relations, "the body names no relation"
    for name in relations:
        assert name.startswith((f'"{scratch}".', f"{scratch}.")), name
    calls = re.findall(r"([A-Za-z_][\w.]*)\s*\(", body)
    keywords = {"if", "values", "and", "or", "not", "in", "insert", "returns"}
    unqualified = [name for name in calls if "." not in name and name.lower() not in keywords]
    # Every function call is pg_catalog's, written as such; the column list after an insert's
    # table name is the only parenthesis that follows a bare word.
    assert unqualified == [], unqualified
    assert all(
        name.startswith("pg_catalog.") or name.startswith((f"{scratch}.", f'"{scratch}".'))
        for name in calls
        if "." in name
    ), calls


def test_the_worker_check_accepts_the_tile_role_and_refuses_anything_wider(roles, spine_schema):
    with _as(roles, "tiles") as connection:
        assert_tiles_role(connection)
    # The API's role reaches tables.
    with _as(roles, "app") as connection, pytest.raises(TilesRoleUnsafe):
        assert_tiles_role(connection)
    # The tile role given one table read by hand is refused, until the next provisioning takes it
    # back.
    psycopg_module, scratch = spine_schema
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        admin.execute(
            sql.SQL("grant select on capture to {}").format(sql.Identifier(roles["tiles"]))
        )
        with _as(roles, "tiles") as connection, pytest.raises(TilesRoleUnsafe, match="table"):
            assert_tiles_role(connection)
        provision_tiles_role(admin, role=roles["tiles"])
    finally:
        admin.close()
    with _as(roles, "tiles") as connection:
        assert_tiles_role(connection)


def test_the_worker_refuses_a_wider_publisher_on_the_public_profile_and_warns_elsewhere(
    roles, tmp_path
):
    """The ruling for an installation that has not provisioned the tile role yet: elsewhere it
    keeps baking as the owner, with a warning; a public server never publishes as the owner."""
    profiles = pathlib.Path(__file__).resolve().parents[1] / "deploy" / "profiles"
    public = {"EXULANICA_INSTALLATION_PROFILE": str(profiles / "public.json")}
    elsewhere = {"EXULANICA_INSTALLATION_PROFILE": str(profiles / "single-host-server-only.json")}
    tiles = scratch_role_database(roles["scratch"], roles["tiles"]).url
    # The harness's own connection, as the schema's owner, the URL a worker held before 0138.
    owner = make_conninfo(
        env_get("TEST_DATABASE_URL"), options=f"-csearch_path={roles['scratch']},public"
    )
    with psycopg.connect(owner) as connection:
        assert connection.execute(
            "select rolsuper from pg_roles where rolname = current_user"
        ).fetchone()[0]
    assert check_publisher(tiles, public) is None
    assert check_publisher(tiles, elsewhere) is None
    with pytest.raises(TilesRoleUnsafe, match="public profile publishes only as the tile role"):
        check_publisher(owner, public)
    assert check_publisher(owner, elsewhere)
    assert check_publisher(owner, {})
