"""Applying migration 0001 to a real server, for the tests that need one.

Three things about this migration make a naive harness wrong, and all three were learned by
running it:

*   **The file carries its own ``begin;`` and ``commit;``.** Applying it and then calling
    ``rollback()`` does not undo it: the embedded COMMIT has already landed by the time control
    returns. A harness written that way silently leaves a schema behind, and the next run fails
    with "type assertion_kind already exists". So the schema is created inside a throwaway
    namespace and that namespace is dropped afterwards.
*   **The target is PostgreSQL 18 with pgvector, and this harness requires it.** Substituting
    ``gen_random_uuid()`` for ``uuidv7()`` and ``bytea`` for ``halfvec(4096)`` so the suite
    could run on an older server made the suite green while the vector path had never executed
    even once, and it hid a real defect: a test wrote raw bytes into ``embedding.v`` and passed,
    because under the substitution the column was ``bytea``. A wrong server is a loud failure
    naming what is missing, not a silent fake.
*   **Extensions are database-wide objects and ``create extension if not exists`` races.** Two
    connections applying the migration at once can both pass the existence check, and the loser
    gets ``duplicate key (extname)``. They are created here, once, in ``public``, under an
    advisory lock, before the throwaway schema goes on the search path. Creating them inside the
    scratch schema instead would put ``halfvec`` somewhere the next run cannot resolve and would
    drop it again with the schema.

Nothing outside the throwaway schema is read or written, apart from those extensions, and the
database name must contain "test" before the harness will touch it at all.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from exulanica.env import env_get, env_name
from exulanica.migrations import migrations

#: uuidv7() is a PostgreSQL 18 built-in. Nothing older can run this schema unfaked.
REQUIRED_SERVER_VERSION: int = 180_000

#: Declared by the migration itself. btree_gist is not optional: without it three GiST indexes
#: fail to build, because core GiST has no operator class for bytea or uuid.
REQUIRED_EXTENSIONS: tuple[str, ...] = ("vector", "pgcrypto", "pg_trgm", "btree_gist")

#: The same advisory lock key migration 0001 takes, so creating the extensions here and applying
#: the migration elsewhere serialise against each other rather than racing.
_EXTENSION_LOCK_KEY = 119_622_309


class WrongServer(Exception):
    """The configured server cannot run the schema without substitutions."""


def require_target(conn) -> None:
    """Refuse a server that is not the documented target, naming exactly what is missing.

    This raises rather than skipping. Skipping is right when no database was configured at all;
    here the operator pointed the suite at a specific server, and quietly testing a different
    schema than the one that ships is the failure mode this whole harness exists to avoid.
    """
    missing: list[str] = []
    version = conn.execute("show server_version_num").fetchone()[0]
    if int(version) < REQUIRED_SERVER_VERSION:
        shown = conn.execute("show server_version").fetchone()[0]
        missing.append(f"PostgreSQL 18 or newer for uuidv7(), server is {shown}")
    available = {
        row[0]
        for row in conn.execute(
            "select name from pg_available_extensions where name = any(%s)",
            (list(REQUIRED_EXTENSIONS),),
        ).fetchall()
    }
    for extension in REQUIRED_EXTENSIONS:
        if extension not in available:
            missing.append(f"the {extension} extension is not available on this server")
    if missing:
        raise WrongServer(
            f"{env_name('TEST_DATABASE_URL')} points at a server that "
            "cannot run migration 0001:\n  "
            + "\n  ".join(missing)
            + "\n\nThe schema is not portable and it is not shimmed. On macOS:\n"
            "  brew install postgresql@18 pgvector && brew services start postgresql@18"
        )


def ensure_extensions(conn) -> None:
    """Create the required extensions in ``public``, serialised against concurrent runs."""
    conn.execute("select pg_advisory_xact_lock(%s)", (_EXTENSION_LOCK_KEY,))
    for extension in REQUIRED_EXTENSIONS:
        conn.execute(f"create extension if not exists {extension} with schema public")
    conn.commit()


def apply_migration(conn, scratch: str) -> None:
    """Create schema ``scratch`` and apply every migration into it, in order, verbatim.

    ``search_path`` is set at session level rather than with SET LOCAL, because each migration
    commits partway through this function and a transaction-local setting would not survive it.
    """
    cursor = conn.cursor()
    cursor.execute(f'create schema "{scratch}"')
    cursor.execute(f'set search_path to "{scratch}", public')
    for migration in migrations():
        cursor.execute(migration.sql)


@contextmanager
def migrated_schema() -> Iterator[tuple]:
    """Yield ``(psycopg, connection)`` with every migration applied, unmodified, to a throwaway
    schema.

    Skips the calling test when no database is configured, when psycopg is not installed, or
    when the configured database is not obviously a scratch one. Fails, rather than skipping,
    when a database *is* configured but is the wrong server.
    """
    url = env_get("TEST_DATABASE_URL")
    if not url:
        # These tests are the only executable proof of invariant 4: that a model cannot write a
        # name into canonical state. Skipping them silently makes a default run look green while
        # the product's core epistemic guarantee is unverified. CI sets EXULANICA_REQUIRE_POSTGRES
        # so the absence is a failure there, not a shrug.
        if env_get("REQUIRE_POSTGRES"):
            pytest.fail(
                f"{env_name('REQUIRE_POSTGRES')} is set but {env_name('TEST_DATABASE_URL')} is "
                "not. The epistemic guard tests cannot run, and they are not optional here."
            )
        pytest.skip(f"set {env_name('TEST_DATABASE_URL')} to a scratch PostgreSQL database")
    psycopg = pytest.importorskip(
        "psycopg", reason="psycopg is a required dependency; run `uv sync`"
    )
    if "test" not in url.rsplit("/", 1)[-1]:
        pytest.skip("refusing a database whose name does not contain 'test'")

    scratch = f"exulanica_test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url) as conn:
        require_target(conn)
        ensure_extensions(conn)
        apply_migration(conn, scratch)
        try:
            yield psycopg, conn
        finally:
            # Uncommitted rows go back; the schema the migration committed has to be dropped.
            conn.rollback()
            conn.execute(f'drop schema "{scratch}" cascade')
            conn.commit()


def open_scratch_connection(psycopg, scratch: str):
    """A fresh autocommit connection into an already-migrated throwaway schema.

    Autocommit is not a preference here, it is required. ``IngestRepository.transaction()``
    has to be an OUTERMOST transaction that commits on exit; on a connection with autocommit
    off, psycopg opens an implicit transaction at the first statement, every later
    ``transaction()`` degrades to a savepoint inside it, and nothing is ever committed. The
    pipeline's rule that object-store writes happen only after the database transaction commits
    would then be testing nothing at all.
    """
    url = env_get("TEST_DATABASE_URL")
    assert url is not None
    connection = psycopg.connect(url, autocommit=True)
    connection.execute(f'set search_path to "{scratch}", public')
    connection.execute("set time zone \'UTC\'")
    return connection
