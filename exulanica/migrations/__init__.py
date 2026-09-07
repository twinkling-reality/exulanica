"""Forward-only SQL migrations, and the checksums the application verifies at boot.

Migrations are numbered, plain SQL, one file per migration, each wrapped in its own
transaction. There are no down migrations: a mistake is corrected by a new forward file.

The checksum matters more than it looks. An edited migration is a silent schema fork: two
deployments claim the same version and have different tables, and the difference shows up much
later as a wrong answer rather than as an error. ``verify_applied`` is what lets a service
refuse to start on drift instead of discovering it that way.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Migration", "migration_directory", "migrations", "verify_applied"]

_MIGRATION_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True, slots=True, order=True)
class Migration:
    """One migration file, identified by its numeric version."""

    version: str
    path: Path

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @property
    def checksum(self) -> bytes:
        """SHA-256 of the file bytes, exactly as they are on disk."""
        return hashlib.sha256(self.path.read_bytes()).digest()


def migration_directory() -> Path:
    return Path(__file__).resolve().parent


def migrations() -> Iterator[Migration]:
    """Return every migration in version order, refusing a malformed set.

    Eager rather than lazy, and that is load-bearing. A generator body does not run until the
    first ``next()``, so a caller that pulls a single item would never reach the uniqueness
    check below. Enumerating is the one place every consumer passes through, which is why the
    refusal lives here rather than in each of them.
    """
    found: list[Migration] = []
    filenames_by_version: dict[str, list[str]] = {}
    for path in sorted(migration_directory().glob("*.sql")):
        match = _MIGRATION_RE.match(path.name)
        if match is None:
            raise ValueError(
                f"{path.name} does not match NNNN_lower_snake.sql; migration ordering is by "
                "filename, so an unparseable name is an ordering bug waiting to happen"
            )
        found.append(Migration(version=match.group(1), path=path))
        filenames_by_version.setdefault(match.group(1), []).append(path.name)

    # Migration numbers are assigned centrally and nothing enforces that. Two branches that each
    # add an 0038 merge with no textual conflict, because neither touched the other's file, and
    # every consumer downstream is wrong in a different way: ``apply_pending`` runs BOTH SQL
    # bodies and then records only the first, because it writes with "on conflict (version) do
    # nothing"; the next boot compares that one recorded checksum against the other file and
    # reports checksum drift on a schema that is already forked; ``verify_applied`` builds
    # {version: checksum} and drops one file out of the dict entirely; the health route's
    # expected list carries the version twice against a database that has it once, so the schema
    # check never reports ok again. Refusing to enumerate is the only answer that reaches all of
    # them, and it says duplicate rather than drift.
    collisions = sorted(
        (version, names) for version, names in filenames_by_version.items() if len(names) > 1
    )
    if collisions:
        detail = "; ".join(f"{version}: {', '.join(names)}" for version, names in collisions)
        raise ValueError(
            "two migration files claim the same version, which is a schema fork rather than a "
            f"naming quibble: {detail}. Renumber the later file; nothing renumbers it for you."
        )
    return iter(found)


def verify_applied(applied: dict[str, bytes]) -> None:
    """Compare recorded checksums against the files on disk, or raise.

    ``applied`` is ``{version: checksum}`` read from ``schema_migrations``. Every applied
    version must still exist on disk with the identical checksum. Unapplied files are fine;
    they are pending. An applied version that is missing or altered is drift.
    """
    on_disk = {migration.version: migration.checksum for migration in migrations()}
    problems: list[str] = []
    for version, checksum in sorted(applied.items()):
        if version not in on_disk:
            problems.append(f"{version}: applied to the database but absent from the package")
        elif on_disk[version] != checksum:
            problems.append(
                f"{version}: checksum drift, database has {checksum.hex()[:16]}..., "
                f"file hashes to {on_disk[version].hex()[:16]}..."
            )
    if problems:
        raise RuntimeError("schema drift, refusing to start:\n  " + "\n  ".join(problems))
