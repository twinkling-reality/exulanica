"""Connections to the spine, and the two settings every one of them carries.

Neither setting is optional, and neither is a convenience.

*   **``exulanica.workspace_id``.** 62 tables are under FORCE row-level security keyed on
    ``current_workspace()``, whose policy is ``workspace_id = current_workspace()`` and which
    reads exactly this setting. One more, ``consent_record``, is forced too and keyed on the
    tenant instead, which is why the number here counts the workspace-keyed ones rather than the
    forced ones. "One more" rather than an ordinal, because the ordinal read "twenty-third"
    beside a count of forty-eight and had read that way through several migrations: only the
    count is measured, by
    ``test_the_prose_count_of_workspace_isolated_tables_matches_the_schema`` against a live
    schema, and it reads nothing at all out of a word. A session that does not declare a
    workspace therefore reads nothing and writes nothing: every SELECT returns empty and every
    INSERT fails its WITH CHECK. The tombstone and epistemic guards go further and call
    ``assert_workspace_context()``, which raises rather than failing open, because a guard that
    silently sees no tombstones is worse than no guard at all. So a connection is only ever
    handed out with a workspace attached.

*   **UTC.** PostgreSQL renders ``timestamptz`` in the session time zone, so a connection left
    on the server's local zone hands back ``2026-08-28T13:47-04:00`` for a column the code
    reads as UTC. Nothing breaks immediately; scene grouping still compares correct instants.
    What breaks is the moment one of those values is written into a payload field named ``utc``
    and read back somewhere that assumes the name.

The migration path is the one exception: :meth:`Database.unscoped` opens a connection with no
workspace, because applying DDL is not a workspace-scoped act and there is no workspace to name
before the schema exists.

Both hand out dictionary rows. Column names are the readable half of a query that already spells
out its own SELECT list, and a positional row makes adding a column to that list a silent
reindexing of every caller.

**There is no connection pool here, and that is a decision rather than an omission.** This is the
file somebody would edit to add one, so the measurement lives here as well as in
``docs/deployment.md`` section 12.1.

``psycopg_pool``'s default reset does nothing when a connection's transaction status is IDLE, and
under the autocommit :meth:`Database.session` deliberately chooses, a returned connection is
always IDLE. So nothing is reset, and **the workspace travels to the next borrower**. Probed as a
non-superuser against real FORCE row-level security tables: a borrower that declared no workspace
read the previous borrower's rows, then a different workspace's rows after a different previous
borrower, and ``assert_workspace_context`` PASSED for a workspace it had never named. Two
sentences in this repository become false at that moment: what :meth:`Database.unscoped` says
below about a role row-level security does reach, and migration 0001's whole reason for making
that guard raise rather than fail open.
``tests/test_row_level_security.py`` holds the pair as an assertion.

What the tax being avoided actually is, over the local unix socket section 3 documents: 1.270 ms
to open a connection, 1.689 ms for this whole shape plus one workspace-scoped query, against
0.045 ms for the pooled equivalent. About 1.6 ms per request, on requests whose real work is a
model call measured in seconds.

If that trade ever flips, the pool needs three things and not two:

*   ``reset=lambda conn: conn.execute("reset all")``. Not ``discard all``, which deallocates
    server-side prepared statements while psycopg's client-side map still believes in them: the
    next auto-prepared execute fails with SQLSTATE 26000.
*   The time zone moved into the startup packet (``?options=-c timezone=UTC``) or a role default,
    because ``reset all`` also undoes the ``SET`` below, measured putting a connection back on
    the server's local zone. The UTC paragraph above says why that is not optional either.
*   :meth:`unscoped` never drawing from the pool at all.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.env import env_get, env_name
from exulanica.errors import ExulanicaError

__all__ = ["DATABASE_URL_ENV", "Database", "DatabaseNotConfigured", "set_workspace"]

#: Canonical connection-string name. :func:`env_get` also accepts ``EXULANICA_DATABASE_URL``.
#: Tests point ``EXULANICA_TEST_DATABASE_URL`` at a scratch database instead; nothing reads both.
DATABASE_URL_ENV: Final = env_name("DATABASE_URL")


class DatabaseNotConfigured(ExulanicaError):
    """No connection string. Raised rather than defaulted, because a default would connect."""


def set_workspace(connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
    """Declare the workspace for the rest of this session.

    ``is_local`` is false so the setting outlives the transaction that sets it. A transaction-
    local setting would evaporate at the first commit and every subsequent statement would run
    with no workspace, which reads as "this workspace is empty" rather than as an error.
    """
    workspace = str(workspace_id)
    connection.execute("select set_config('exulanica.workspace_id', %s, false)", (workspace,))


@dataclass(frozen=True, slots=True)
class Database:
    """A connection string, and the two ways to open a connection against it."""

    url: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Database:
        environ = os.environ if environ is None else environ
        url = env_get("DATABASE_URL", environ)
        if not url:
            raise DatabaseNotConfigured(
                f"{DATABASE_URL_ENV} is not set (EXULANICA_DATABASE_URL is accepted as an alias). "
                "Exulanica has one data layer and it is PostgreSQL 18 with pgvector; there is no "
                "local fallback to run without."
            )
        return cls(url=url)

    @contextmanager
    def unscoped(self) -> Iterator[psycopg.Connection]:
        """A connection with no workspace. For migrations, the schema check and nothing else.

        This opens a connection and declines to declare a workspace. That is the whole of what
        it does, and **what the connection can then see is a property of the role behind the URL
        rather than of this method**. The distinction is not decoration: the sentence here used
        to read "every table under row-level security is invisible through this connection", and
        that is false for the role the composition actually uses.

        *   **As a role row-level security reaches**, which ``exulanica_app`` is, every one of the
            fifty-seven workspace-keyed forced tables reads empty. The policy is ``workspace_id =
            current_workspace()``, ``current_workspace()`` is NULL with nothing declared, and
            ``NULL = anything`` is not true. So a caller that wanted workspace data and reached
            for this gets an empty result rather than another workspace's rows.
        *   **As a superuser, nothing is hidden at all.** PostgreSQL bypasses row security
            outright for a superuser or a role holding BYPASSRLS, and ``force row level
            security`` does not reach either: it makes an ordinary owner subject to the policy,
            not a superuser. The database owner is a superuser on a default installation, so the
            same call on the same schema hands back the row the bullet above returns none of.

        Both halves are asserted against a live schema in ``tests/test_row_level_security.py``,
        one per role, because a sentence that was false once should not be a sentence again.
        ``compose.yaml`` gives the API and derivative worker ``exulanica_app`` and reserves the
        owner URL for the one-shot migration container. Production startup also refuses a
        superuser, a BYPASSRLS role, or an owner of a row-level-security table, so deployment
        drift cannot silently select the second bullet.

        **The migration path relies on neither bullet.** It needs DDL rights and
        ``schema_migrations``, which carries no row-level security at all, so it works under
        either role that can run the DDL. The reason it declares no workspace is that there is no
        workspace to name before the schema exists, not that the emptiness is useful to it.
        """
        with psycopg.connect(self.url, row_factory=dict_row) as connection:
            connection.execute("set time zone 'UTC'")
            yield connection

    @contextmanager
    def session(self, workspace_id: uuid.UUID) -> Iterator[psycopg.Connection]:
        """A connection scoped to one workspace, in UTC, in autocommit.

        Autocommit is deliberate. Every multi-statement unit in this codebase already brackets
        itself with an explicit transaction, and an implicit one opened by the first statement
        would hold a snapshot open across whatever the caller does next, including a model call
        that takes ten seconds.
        """
        with psycopg.connect(self.url, autocommit=True, row_factory=dict_row) as connection:
            connection.execute("set time zone 'UTC'")
            set_workspace(connection, workspace_id)
            yield connection
