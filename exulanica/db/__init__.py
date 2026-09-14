"""The one data layer. PostgreSQL 18 with pgvector, and nothing beside it.

There used to be two: the spine in ``exulanica/migrations/0001_spine.sql`` and a portable SQLite
mirror that the ingest path actually wrote. The mirror existed because no PostgreSQL with
pgvector was available when ingestion was written, and it was a fork waiting to happen: the
epistemic guards that carry the product's central promise exist only in PostgreSQL, and a
second schema is a second thing to keep true.

This package holds what every caller of the spine needs and no caller should reimplement:
opening a connection with a workspace attached, and applying the migration files.
"""

from exulanica.db.migrate import (
    MigrationReport,
    applied_migrations,
    apply_pending,
    provision_workspace,
    verify_schema,
)
from exulanica.db.roles import (
    EXECUTOR_ROLE,
    RUNTIME_ROLE,
    grant_workspace_partition,
    provision_runtime_role,
)
from exulanica.db.session import (
    DATABASE_URL_ENV,
    Database,
    DatabaseNotConfigured,
    set_workspace,
)

__all__ = [
    "DATABASE_URL_ENV",
    "EXECUTOR_ROLE",
    "RUNTIME_ROLE",
    "Database",
    "DatabaseNotConfigured",
    "MigrationReport",
    "applied_migrations",
    "apply_pending",
    "grant_workspace_partition",
    "provision_runtime_role",
    "provision_workspace",
    "set_workspace",
    "verify_schema",
]
