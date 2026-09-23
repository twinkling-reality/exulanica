"""The named reasons ``exulanica-local-db`` stops.

A stop is one of two kinds. Most are refusals decided before anything changed: a location that is
not durable, a restore over existing data, a migration without a fresh backup. A few follow a step
that was attempted and failed, such as ``pg_dump`` or a migration. The command exits
:data:`REFUSED_EXIT` for the first kind and :data:`FAILED_EXIT` for the second, and prints the
name either way, so a person, a script and a test can each tell which rule stopped it. A new
reason is a new member here, never a bare message.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from exulanica.errors import ExulanicaError

__all__ = ["FAILED_EXIT", "FAILURES", "REFUSED_EXIT", "LocalDatabaseRefused", "Refusal"]


class Refusal(StrEnum):
    """Why the command stopped. The value is the name it prints."""

    #: The data directory would be inside a temporary directory, which is disposable.
    TEMPORARY_DIRECTORY = "temporary-directory"
    #: The data directory would be under the base directory of the disposable test servers.
    TEST_SERVER_DIRECTORY = "test-server-directory"
    #: A new data directory, or a restore, would be written where files already are.
    EXISTING_DATA = "existing-data"
    #: The directory holds no data directory this command created.
    NOT_A_LOCAL_DATABASE = "not-a-local-database"
    #: No PostgreSQL 18 or newer server binaries were found.
    POSTGRES_MISSING = "postgres-missing"
    #: The port the server needs is held by another process.
    PORT_IN_USE = "port-in-use"
    #: The data directory was made by a different PostgreSQL major version than the binaries.
    SERVER_VERSION = "server-version"
    #: Another client is connected, so an upgrade would change the schema under it.
    IN_USE = "in-use"
    #: The database records a migration this code does not have, or has with other bytes.
    SCHEMA_DRIFT = "schema-drift"
    #: There is no backup to verify.
    NO_BACKUP = "no-backup"
    #: A backup has no manifest this command can read.
    BACKUP_UNREADABLE = "backup-unreadable"
    #: A dump's bytes no longer hash to the SHA-256 its manifest recorded.
    DIGEST_MISMATCH = "digest-mismatch"
    #: A restored copy holds other row counts, or other migrations, than its manifest recorded.
    ROW_COUNTS_DIFFER = "row-counts-differ"
    #: The pending migrations failed on a scratch copy, so the real database was not touched.
    REHEARSAL_FAILED = "rehearsal-failed"
    #: A migration was asked for without a backup taken in the same maintenance session.
    NO_FRESH_BACKUP = "no-fresh-backup"
    #: ``initdb`` or ``pg_ctl`` failed.
    SERVER_FAILED = "server-failed"
    #: ``pg_dump`` failed.
    BACKUP_FAILED = "backup-failed"
    #: ``pg_restore``, or the roles a dump needs, failed.
    RESTORE_FAILED = "restore-failed"
    #: A migration failed on the real database after its rehearsal passed.
    MIGRATION_FAILED = "migration-failed"


#: The stops that follow an attempted step rather than precede any change.
FAILURES: Final = frozenset(
    {
        Refusal.SERVER_FAILED,
        Refusal.BACKUP_FAILED,
        Refusal.RESTORE_FAILED,
        Refusal.MIGRATION_FAILED,
    }
)

#: Exit status for a refusal, which changed nothing, and for a failed step.
REFUSED_EXIT: Final = 2
FAILED_EXIT: Final = 1


class LocalDatabaseRefused(ExulanicaError):
    """``exulanica-local-db`` stopped for a named reason."""

    def __init__(self, refusal: Refusal, detail: str) -> None:
        super().__init__(f"{refusal.value}: {detail}")
        self.refusal = refusal
        self.detail = detail

    @property
    def exit_status(self) -> int:
        return FAILED_EXIT if self.refusal in FAILURES else REFUSED_EXIT
