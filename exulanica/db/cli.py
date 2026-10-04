"""``exulanica-db``: bring a database up to the schema and the roles this code expects.

One command, because there is only one correct order and offering a second way to ask is
offering a way to get it wrong. Migrations first, then the workspace and account roles.

**Run it as the SAME role that applies migrations.** ``provision_runtime_role`` ends with
``alter default privileges ... grant ... on tables``, and PostgreSQL applies default privileges
only to objects created by the role that executed that statement. Provision as one principal and
migrate as another and the grants stop covering tables a later migration adds, which surfaces as
``permission denied`` from a route rather than from here.

Passwords are optional. ``provision_runtime_role`` sets one only when given one, and a deployment
authenticating by certificate or by peer has none to set; inventing one would be creating a
credential nobody asked for.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Final

from exulanica.db.account_roles import ACCOUNT_ROLE, provision_account_role
from exulanica.db.migrate import apply_pending
from exulanica.db.roles import (
    BACKUP_ROLE,
    EXECUTOR_ROLE,
    PURGE_ROLE,
    RUNTIME_ROLE,
    provision_backup_role,
    provision_purge_role,
    provision_runtime_role,
)
from exulanica.db.session import Database
from exulanica.db.tiles_role import TILES_ROLE, provision_tiles_role
from exulanica.env import env_get, env_name

__all__ = [
    "ACCOUNT_ROLE_PASSWORD_ENV",
    "APP_ROLE_PASSWORD_ENV",
    "BACKUP_ROLE_PASSWORD_ENV",
    "EXECUTOR_ROLE_PASSWORD_ENV",
    "PURGE_ROLE_PASSWORD_ENV",
    "main",
    "provision_database",
]

APP_ROLE_PASSWORD_ENV: Final = env_name("APP_ROLE_PASSWORD")
EXECUTOR_ROLE_PASSWORD_ENV: Final = env_name("EXECUTOR_ROLE_PASSWORD")
PURGE_ROLE_PASSWORD_ENV: Final = env_name("PURGE_ROLE_PASSWORD")
ACCOUNT_ROLE_PASSWORD_ENV: Final = env_name("ACCOUNT_ROLE_PASSWORD")
BACKUP_ROLE_PASSWORD_ENV: Final = env_name("BACKUP_ROLE_PASSWORD")


def provision(stream: Any) -> int:
    return provision_database(Database.from_env(), stream)


def provision_database(database: Database, stream: Any) -> int:
    """Migrate ``database`` and provision every role, with passwords from the environment."""
    report = apply_pending(database)
    for version in report.applied:
        print(f"  applied  {version}", file=stream)
    if not report.changed:
        print("schema: up to date", file=stream)

    app_password = env_get("APP_ROLE_PASSWORD")
    executor_password = env_get("EXECUTOR_ROLE_PASSWORD")
    purge_password = env_get("PURGE_ROLE_PASSWORD")
    account_password = env_get("ACCOUNT_ROLE_PASSWORD")
    backup_password = env_get("BACKUP_ROLE_PASSWORD")
    tiles_password = env_get("TILES_ROLE_PASSWORD")
    with database.unscoped() as connection:
        provision_runtime_role(connection, role=RUNTIME_ROLE, password=app_password)
        provision_runtime_role(
            connection, role=EXECUTOR_ROLE, password=executor_password, read_only=True
        )
        provision_purge_role(connection, role=PURGE_ROLE, password=purge_password)
        provision_account_role(connection, role=ACCOUNT_ROLE, password=account_password)
        provision_backup_role(connection, role=BACKUP_ROLE, password=backup_password)
        provision_tiles_role(connection, role=TILES_ROLE, password=tiles_password)
    print(
        f"roles: {RUNTIME_ROLE} may select, insert and update and may not delete; "
        f"{EXECUTOR_ROLE} may select and nothing else; {PURGE_ROLE} may mark bytes purged "
        "and may read every workspace's content hashes, which is the one question a shared "
        "blob makes unanswerable inside one workspace; "
        f"{ACCOUNT_ROLE} may access only account persistence; "
        f"{BACKUP_ROLE} may read every row for a backup and write nothing; "
        f"{TILES_ROLE} may publish a baked tile and do nothing else",
        file=stream,
    )
    return 0


def main(argv: list[str] | None = None, stream: Any = None) -> int:
    parser = argparse.ArgumentParser(
        prog="exulanica-db", description="Apply pending migrations, then grant runtime roles."
    )
    parser.parse_args(argv)
    return provision(stream or sys.stdout)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
