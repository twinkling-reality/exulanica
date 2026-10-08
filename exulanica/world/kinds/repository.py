"""A workspace's own world kinds: each version kept as admitted (migration 0140).

A kind a creator uploads, or a model drafts from a person's words (kept once it passes, without a
separate accept: the person asked for it and it was paid for), is read and held to both
stages of its checks (:mod:`exulanica.world.kinds.document`, :mod:`exulanica.world.kinds.samples`)
before it is appended here, with the report its sample worlds passed. A version is appended once
and never changed; an edit is a new version. Rows stay inside their workspace by row-level
security, and the kinds the product ships are files (:mod:`exulanica.world.kinds.library`), never
rows.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.world.kinds.catalogs import load_kind_catalogs
from exulanica.world.kinds.document import KindDocument, KindRefused, read_kind
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "KINDS_PER_WORKSPACE",
    "KindCapReached",
    "KindUnreadable",
    "KindVersionExists",
    "StoredKind",
    "WorkspaceKinds",
]

#: The most kind versions one workspace keeps. Each is checked by building its sample worlds, so the
#: cap bounds how much generation one workspace can ask of the kind worker, as the count policy
#: bounds its generated worlds; 64 is four times the library a creator is expected to use
#: (the town and a dozen kinds of their own, each revised once or twice). An edit is a version.
KINDS_PER_WORKSPACE: Final = 64

_log = logging.getLogger(__name__)

_COLUMNS: Final = "kind,version,document_sha256,document,origin,validation,created_by,created_at"
_EXISTS: Final = (
    "this workspace already holds kind {kind} version {version}, or the same document under "
    "another version"
)
_CAP: Final = "this workspace keeps {cap} kind versions, the most it may"
#: Kept documents already read, by their digest and the catalogs read with: a listing reads up to
#: :data:`KINDS_PER_WORKSPACE` documents, each the same every time while the catalogs are.
_READ_KEPT: Final = 128
_read_lock = threading.Lock()
_read: OrderedDict[tuple[str, tuple[str, ...]], KindDocument | str] = OrderedDict()


def _read_stored(document: object, document_sha256: str) -> KindDocument | str:
    """A kept document read again, or why it no longer reads, once per digest and catalogs."""
    key = (document_sha256, tuple(sorted(load_kind_catalogs().sha256.values())))
    with _read_lock:
        found = _read.get(key)
        if found is not None:
            _read.move_to_end(key)
            return found
    outcome: KindDocument | str
    try:
        outcome = read_kind(document)
    except KindRefused as exc:
        outcome = f"no longer reads: {exc}"
    else:
        if outcome.sha256 != document_sha256:
            outcome = "reads to another digest"
    with _read_lock:
        _read[key] = outcome
        while len(_read) > _READ_KEPT:
            _read.popitem(last=False)
    return outcome


class KindCapReached(ValueError):
    """A workspace that already keeps as many kind versions as it may."""

    code: Final = "kind_cap_reached"


class KindUnreadable(ValueError):
    """A kept kind the catalogs this server holds no longer read: its worlds cannot be made."""

    code: Final = "kind_unreadable"


class KindVersionExists(ValueError):
    """A version the workspace already holds, under its key and number or by its digest."""

    code: Final = "kind_version_exists"


@dataclass(frozen=True, slots=True)
class StoredKind:
    """One version of a workspace's kind, read again from its document."""

    kind: KindDocument
    validation: Mapping[str, Any]
    created_by: uuid.UUID
    created_at: Any


class WorkspaceKinds:
    """Append and read a workspace's kinds through one workspace-scoped connection."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self.connection = connection
        self.workspace_id = workspace_id

    def append(
        self, kind: KindDocument, validation: Mapping[str, Any], *, created_by: uuid.UUID
    ) -> StoredKind:
        """Keep a kind that passed both stages, refused by name when the workspace holds this
        version or this document already."""
        if validation.get("verdict") != "passed" or validation.get("kind") != kind.reference():
            raise KindRefused("kind_document_invalid", "its report is not its own passing report")
        try:
            with self.connection.transaction():
                lock_workspace(self.connection, self.workspace_id)
                with self.connection.cursor(row_factory=dict_row) as cursor:
                    held = cursor.execute(
                        "select count(*) as n from world_kind_version where workspace_id=%s",
                        (self.workspace_id,),
                    ).fetchone()
                if held is not None and held["n"] >= KINDS_PER_WORKSPACE:
                    raise KindCapReached(_CAP.format(cap=KINDS_PER_WORKSPACE))
                self.connection.execute(
                    "insert into world_kind_version (workspace_id,kind,version,document_sha256,"
                    "document,origin,validation,created_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        self.workspace_id,
                        kind.kind,
                        kind.version,
                        kind.sha256,
                        Jsonb(dict(kind.document)),
                        kind.origin,
                        Jsonb(dict(validation)),
                        created_by,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise KindVersionExists(_EXISTS.format(kind=kind.kind, version=kind.version)) from exc
        found = self.version(kind.kind, kind.version)
        assert found is not None
        return found

    def refuse_when_full(self) -> None:
        """Refuse when the workspace already keeps as many kind versions as it may
        (:class:`KindCapReached`): asked before anything is spent on a kind not yet written, such
        as a draft; the append asks again under the workspace's lock."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                "select count(*) as n from world_kind_version where workspace_id=%s",
                (self.workspace_id,),
            ).fetchone()
        if row is not None and row["n"] >= KINDS_PER_WORKSPACE:
            raise KindCapReached(_CAP.format(cap=KINDS_PER_WORKSPACE))

    def refuse_before_checks(self, kind: KindDocument) -> None:
        """Refuse a kind the append would refuse, before anything is built for it: a version or a
        document the workspace already keeps (:class:`KindVersionExists`), or a workspace already
        keeping as many versions as it may (:class:`KindCapReached`). Asked without the lock; the
        append asks both again under it."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                "select count(*) as n, coalesce(bool_or((kind=%s and version=%s) or "
                "document_sha256=%s), false) as held from world_kind_version "
                "where workspace_id=%s",
                (kind.kind, kind.version, kind.sha256, self.workspace_id),
            ).fetchone()
        if row is not None and row["held"]:
            raise KindVersionExists(_EXISTS.format(kind=kind.kind, version=kind.version))
        if row is not None and row["n"] >= KINDS_PER_WORKSPACE:
            raise KindCapReached(_CAP.format(cap=KINDS_PER_WORKSPACE))

    def _stored(self, row: Mapping[str, Any]) -> StoredKind:
        """A kept kind read again; :class:`KindUnreadable` when today's catalogs refuse it or it
        reads to another digest, never a refusal escaping as an error. Each document is read once
        per digest and catalogs (:func:`_read_stored`)."""
        kind = _read_stored(row["document"], row["document_sha256"])
        if isinstance(kind, str):
            raise KindUnreadable(f"kind {row['kind']} version {row['version']} {kind}")
        return StoredKind(
            kind=kind,
            validation=row["validation"],
            created_by=row["created_by"],
            created_at=row["created_at"],
        )

    def version(self, kind: str, version: int) -> StoredKind | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"select {_COLUMNS} from world_kind_version where workspace_id=%s and kind=%s "
                "and version=%s",
                (self.workspace_id, kind, version),
            ).fetchone()
        return None if row is None else self._stored(row)

    def latest(self, kind: str) -> StoredKind | None:
        with self.connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"select {_COLUMNS} from world_kind_version where workspace_id=%s and kind=%s "
                "order by version desc limit 1",
                (self.workspace_id, kind),
            ).fetchone()
        return None if row is None else self._stored(row)

    def kind_keys(self) -> frozenset[str]:
        """Every key the workspace keeps a kind under, whether or not its kind still reads: a new
        kind under one of these would be refused as a version the workspace holds."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                "select distinct kind from world_kind_version where workspace_id=%s",
                (self.workspace_id,),
            ).fetchall()
        return frozenset(str(row["kind"]) for row in rows)

    def every_latest(self) -> tuple[StoredKind, ...]:
        """The latest version of every kind the workspace holds, by key."""
        with self.connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                f"select distinct on (kind) {_COLUMNS} from world_kind_version "
                "where workspace_id=%s order by kind, version desc",
                (self.workspace_id,),
            ).fetchall()
        stored = []
        for row in rows:
            try:
                stored.append(self._stored(row))
            except KindUnreadable:
                # Listed by the kinds it can still read; the row itself stays kept.
                _log.warning(
                    "world kind %s version %s no longer reads", row["kind"], row["version"]
                )
        return tuple(stored)
