"""Custody of withdrawal exports: where they may live and how many are kept.

An export is a full cross-workspace copy of every withdrawal's identifying fields, written as
often as withdrawals change. Custody therefore keeps only what a recovery can use: the newest few
valid exports of the database pruning, and every export a retained backup set names, because a
crash recovery needs an export no older than its backup. Of another source's exports (another
database, or the one a restored database came from, which no longer writes any), only its newest
and the referenced ones are kept: the newest is what the custody rule for exports compares
against. Nothing but export files is ever touched: checkpoints, markers and declarations are the
operator's files at the operator's paths, and are left alone.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from pathlib import Path
from typing import Final

from exulanica.canonical import canonical_json
from exulanica.deletion.queue import STORED_KINDS
from exulanica.deletion.restore import EXPORT_PROFILE, RestoreRefused

__all__ = [
    "DEFAULT_KEEP",
    "UNLISTED_PREFIX",
    "ExportFile",
    "erased_targets",
    "exports",
    "prune_exports",
    "require_newest",
]

#: The name a restore's listing of bytes written after its backup starts with, beside the
#: marker; maintenance reports every listed key the live store still holds.
UNLISTED_PREFIX: Final = "objects-not-in-backup-"

#: How many of the newest valid exports custody keeps when a caller states no other number.
DEFAULT_KEEP: Final = 3


class ExportFile:
    """One valid export in custody: its path, digest and the time it covers."""

    __slots__ = ("covered_through", "path", "sha256", "source_identity")

    def __init__(
        self, path: Path, sha256: str, covered_through: str, source_identity: str | None
    ) -> None:
        self.path = path
        self.sha256 = sha256
        self.covered_through = covered_through
        self.source_identity = source_identity


def _valid(path: Path) -> ExportFile | None:
    try:
        envelope = json.loads(path.read_bytes())
    except (OSError, ValueError):
        return None
    record = envelope.get("record") if isinstance(envelope, dict) else None
    if (
        not isinstance(record, dict)
        or envelope.get("state") != "exported"
        or record.get("profile") != EXPORT_PROFILE
        or not isinstance(record.get("covered_through"), str)
    ):
        return None
    digest = hashlib.sha256(canonical_json(record)).hexdigest()
    if envelope.get("record_sha256") != digest:
        return None
    identity = record.get("source_identity")
    return ExportFile(
        path, digest, record["covered_through"], identity if isinstance(identity, str) else None
    )


def exports(directory: Path) -> list[ExportFile]:
    """Every valid export in ``directory``, newest first. A damaged file is not an export."""
    found = [
        export for path in sorted(directory.glob("*.json")) if (export := _valid(path)) is not None
    ]
    return sorted(found, key=lambda export: export.covered_through, reverse=True)


def prune_exports(
    directory: Path,
    *,
    source_identity: str,
    keep: int = DEFAULT_KEEP,
    referenced: Collection[str] = (),
) -> list[Path]:
    """Remove valid exports but this source's newest ``keep``, every other source's newest, and
    those ``referenced``.

    ``source_identity`` is the pruning database's, from
    :func:`exulanica.deletion.restore.source_identity`. Exports that name no source form one group
    of their own. Returns what it removed. A damaged or partial export is left for an operator to
    inspect rather than guessed at.
    """
    if keep < 1:
        raise ValueError("custody keeps at least the newest export")
    retained = set(referenced)
    seen: dict[str | None, int] = {}
    found = exports(directory)
    for export in found:
        count = seen.get(export.source_identity, 0)
        if count < (keep if export.source_identity == source_identity else 1):
            retained.add(export.sha256)
        seen[export.source_identity] = count + 1
    removed = []
    for export in found:
        if export.sha256 not in retained:
            export.path.unlink()
            removed.append(export.path)
    return removed


def require_newest(export: Path, custody: Path) -> str:
    """The digest of ``export`` when it is the newest valid export in ``custody``, the
    installation's custody directory, wherever the file given was copied; a refusal otherwise.

    A crash recovery replays the newest export there, so a withdrawal an older export lacks is
    never left out because an older file was named.
    """
    digest = _valid(export)
    newest = exports(custody)[:1]
    if digest is None or not newest or newest[0].sha256 != digest.sha256:
        raise RestoreRefused(
            f"the declared export is not the newest valid export in custody ({custody}); a crash "
            "recovery replays the newest"
        )
    return digest.sha256


def erased_targets(custody: Path) -> set[str]:
    """The stored purge targets the newest export in ``custody`` names: the gaps a declared
    recovery, which replays that export, accepts in a backup copy, and so the only ones
    maintenance erases there and verification accepts."""
    newest = exports(custody)[:1]
    if not newest:
        return set()
    record = json.loads(newest[0].path.read_bytes())["record"]
    return {
        target["target_ref"]
        for item in record["tombstones"]
        for target in item["targets"]
        if target["target_kind"] in STORED_KINDS
    }
