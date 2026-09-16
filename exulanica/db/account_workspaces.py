"""Current account-owned workspace discovery through the isolated account database role."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Final

import psycopg
from psycopg.rows import dict_row

from exulanica.db.account_roles import AccountRoleUnsafe, assert_account_role
from exulanica.errors import ExulanicaError

__all__ = [
    "ACCOUNT_DATABASE_URL_ENV",
    "AccountWorkspaceSource",
    "AccountWorkspaceUnavailable",
    "active_owned_workspaces",
]

ACCOUNT_DATABASE_URL_ENV: Final = "EXULANICA_ACCOUNT_DATABASE_URL"
_DATABASE_TIMEOUT_SECONDS: Final = 5


class AccountWorkspaceUnavailable(ExulanicaError):
    """Discovery cannot establish its narrow role or matching world database boundary."""


def active_owned_workspaces(connection: psycopg.Connection) -> frozenset[uuid.UUID]:
    """Read current owner authority without treating a browser session as membership."""
    rows = connection.execute(
        "select w.workspace_id from account_workspace w "
        "join account_user u on u.user_id=w.owner_user_id "
        "join account_membership m on m.workspace_id=w.workspace_id "
        "and m.user_id=w.owner_user_id "
        "where u.disabled_at is null and w.disabled_at is null "
        "and m.revoked_at is null and m.membership_role='owner' "
        "order by w.workspace_id"
    ).fetchall()
    return frozenset(row["workspace_id"] for row in rows)


def _prepare(connection: psycopg.Connection) -> None:
    connection.execute("set time zone 'UTC'")
    connection.execute(
        "select set_config('statement_timeout', %s, false)",
        (f"{_DATABASE_TIMEOUT_SECONDS}s",),
    )


def _binding(connection: psycopg.Connection) -> tuple[object, ...]:
    """Compare resolved endpoints and effective schemas, not opaque DSN strings."""
    row = connection.execute(
        "select current_database() database_name,current_schema() schema_name,"
        "current_setting('search_path') search_path,inet_server_addr()::text server_address,"
        "inet_server_port() server_port"
    ).fetchone()
    if row is None or row["schema_name"] is None:
        raise AccountWorkspaceUnavailable("account workspace database has no effective schema")
    return (
        connection.info.host,
        connection.info.port,
        connection.info.dbname,
        row["database_name"],
        row["schema_name"],
        row["search_path"],
        row["server_address"],
        row["server_port"],
    )


@dataclass(frozen=True, slots=True)
class AccountWorkspaceSource:
    """Callable fresh-authority source for a separately hosted background worker."""

    account_database_url: str = field(repr=False)
    application_database_url: str = field(repr=False)

    def verify(self) -> AccountWorkspaceSource:
        """Fail startup unless account and world roles are narrow peers on one schema."""
        try:
            with psycopg.connect(
                self.account_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as account:
                _prepare(account)
                assert_account_role(account)
                account_binding = _binding(account)
            with psycopg.connect(
                self.application_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as application:
                _prepare(application)
                application_binding = _binding(application)
        except (psycopg.Error, AccountRoleUnsafe) as exc:
            raise AccountWorkspaceUnavailable(
                "account workspace database role is unavailable or unsafe"
            ) from exc
        if account_binding != application_binding:
            raise AccountWorkspaceUnavailable(
                "account and application URLs must name the same database/schema"
            )
        return self

    def __call__(self) -> frozenset[uuid.UUID]:
        """Open a fresh account-role connection so revocation is never a retained cache."""
        try:
            with psycopg.connect(
                self.account_database_url,
                autocommit=True,
                row_factory=dict_row,
                connect_timeout=_DATABASE_TIMEOUT_SECONDS,
            ) as connection:
                _prepare(connection)
                return active_owned_workspaces(connection)
        except psycopg.Error as exc:
            raise AccountWorkspaceUnavailable("account workspace discovery is unavailable") from exc
