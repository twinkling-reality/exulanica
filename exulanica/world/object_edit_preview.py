"""Server previews for the object edits that had none: move, remove and undo.

Transport-independent, like :mod:`exulanica.world.composition_preview`: each preview runs the read
that the durable writer runs first (the version row, then the base, then the subject), through the
repository's read-only validators, which share their checks with the writers
(``WorldObjectRepository.validate_object_move``, ``validate_object_removal``, ``validate_undo``,
including an undo's restore rules). So for one stored state a preview's ``blocked_reason`` is the
problem code the write answers for those checks, and a ready preview's ``after`` is the document
the write records.

One refusal a preview cannot foresee: a purposeful society on the version takes every accepted edit
as its next input inside the write's transaction, and refuses one it cannot take
(``424 unavailable_society_input``). Composing that input is the write's work, so a preview that was
ready can still meet that refusal, as a composition preview can.

Every read happens in one read-only, repeatable-read transaction and nothing is written. An
unknown, foreign or other-world version, and an unknown object, raise ``UnknownWorldResource``, the
same answer the write gives, so a preview says no more about another workspace than a write does.
The base is checked before the object is looked up, as the writer checks it, so a stale base is
reported for an object id nobody knows exactly as the write reports it.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg import pq

from exulanica.world.errors import (
    InvalidatedSourceVersion,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    StaleObjectBase,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import Transform, object_document
from exulanica.world.workspace_assets import WorkspaceAssetWithdrawn

__all__ = [
    "OBJECT_EDIT_BLOCKED_REASONS",
    "ObjectEditPreview",
    "preview_object_move",
    "preview_object_removal",
    "preview_undo",
    "read_only_snapshot",
]

EditKind = Literal["move_object", "remove_object", "undo"]

#: Each refusal a preview reports, and its code: the ``code`` the object routes answer the same
#: refusal with (``OBJECT_PROBLEMS`` in ``exulanica.api.world_edit``; a test holds the two equal).
_REFUSALS: Final[tuple[tuple[type[Exception], str], ...]] = (
    (InvalidatedSourceVersion, "invalidated_source_version"),
    (StaleObjectBase, "stale_object_base"),
    (InvalidObjectState, "invalid_object_state"),
    (InvalidObjectData, "invalid_object_data"),
    #: An undo whose environment instance left the binding the reversed edit stored.
    (InvalidEnvironmentState, "invalid_environment_state"),
    #: A move of an object whose workspace asset was withdrawn, or whose workspace was erased.
    (WorkspaceAssetWithdrawn, "withdrawn"),
)

#: Every code ``blocked_reason`` can carry. Stable: codes are added, never renamed.
OBJECT_EDIT_BLOCKED_REASONS: Final = frozenset(code for _kind, code in _REFUSALS)

#: What a ready edit leaves unchanged on the version, as a composition preview states it.
_PRESERVES: Final = ("source_snapshot_id", "style_version_id", "other_subjects", "prior_edits")


@dataclass(frozen=True, slots=True)
class ObjectEditPreview:
    """The server's verdict on one move, removal or undo against the stored state it read."""

    blocked_reason: str | None
    blocked_detail: str | None
    version: Mapping[str, Any]
    kind: EditKind
    subject_id: str | None
    #: The subject's document as it stands, and as the edit would leave it (null: absent).
    before: Mapping[str, Any] | None
    after: Mapping[str, Any] | None
    #: For an undo, the edit it would reverse.
    undoes: Mapping[str, Any] | None

    @property
    def availability(self) -> Literal["ready", "blocked"]:
        return "ready" if self.blocked_reason is None else "blocked"

    def document(self) -> dict[str, Any]:
        ready = self.blocked_reason is None
        return {
            "availability": self.availability,
            "blocked_reason": self.blocked_reason,
            "blocked_detail": self.blocked_detail,
            "version": dict(self.version),
            "would_change": {
                "kind": self.kind,
                "subject_id": self.subject_id,
                "before": None if self.before is None else dict(self.before),
                "after": None if self.after is None else dict(self.after),
                "undoes": None if self.undoes is None else dict(self.undoes),
                "preserves": list(_PRESERVES) if ready else [],
            },
        }


def preview_object_move(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    object_id: str,
    transform: Transform,
    *,
    base_state_sha256: str,
) -> ObjectEditPreview:
    """What ``POST .../objects/{object_id}/move`` would record. Takes no lock and writes nothing."""
    with read_only_snapshot(repository.connection):
        version = _version_block(repository, version_id)
        try:
            current, moved = repository.validate_object_move(
                version_id, object_id, transform, base_state_sha256=base_state_sha256
            )
        except Exception as exc:
            return _blocked(exc, version, "move_object", object_id)
        return ObjectEditPreview(
            None,
            None,
            version,
            "move_object",
            object_id,
            object_document(current),
            object_document(moved),
            None,
        )


def preview_object_removal(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    object_id: str,
    *,
    base_state_sha256: str,
) -> ObjectEditPreview:
    """What ``POST .../objects/{object_id}/remove`` would record. No lock, and no write."""
    with read_only_snapshot(repository.connection):
        version = _version_block(repository, version_id)
        try:
            current, removed = repository.validate_object_removal(
                version_id, object_id, base_state_sha256=base_state_sha256
            )
        except Exception as exc:
            return _blocked(exc, version, "remove_object", object_id)
        return ObjectEditPreview(
            None,
            None,
            version,
            "remove_object",
            object_id,
            object_document(current),
            object_document(removed),
            None,
        )


def preview_undo(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    *,
    base_state_sha256: str,
) -> ObjectEditPreview:
    """What ``POST .../objects/undo`` would record. Takes no lock and writes nothing."""
    with read_only_snapshot(repository.connection):
        version = _version_block(repository, version_id)
        try:
            candidate = repository.validate_undo(version_id, base_state_sha256=base_state_sha256)
        except Exception as exc:
            return _blocked(exc, version, "undo", None)
        return ObjectEditPreview(
            None,
            None,
            version,
            "undo",
            candidate.subject_id,
            candidate.current,
            candidate.restores,
            {
                "edit_id": str(candidate.edit_id),
                "edit_seq": candidate.edit_seq,
                "kind": candidate.kind,
                "subject": candidate.subject.value,
            },
        )


def _version_block(repository: WorldObjectRepository, version_id: uuid.UUID) -> dict[str, Any]:
    """The version a verdict was reached on, as a composition preview names it.

    Raises ``UnknownWorldResource`` for an absent, foreign or other-world version, before anything
    else is read, as the write does.
    """
    row = repository.edit_base_row(version_id)
    return {
        "authored_version_id": str(row["version_id"]),
        "world_id": row["world_id"],
        "state_sha256": row["state_sha256"],
        "edit_seq": int(row["edit_seq"]),
        "source_snapshot_id": str(row["source_snapshot_id"]),
        "style_version_id": (
            None if row["style_version_id"] is None else str(row["style_version_id"])
        ),
    }


def _blocked(
    exc: Exception, version: Mapping[str, Any], kind: EditKind, subject_id: str | None
) -> ObjectEditPreview:
    """A refusal the write would answer with a code, as a blocked preview; anything else raises.

    ``UnknownWorldResource`` is not in the table, so an unknown object propagates to the same
    404 the write answers.
    """
    for refused, code in _REFUSALS:
        if isinstance(exc, refused):
            return ObjectEditPreview(code, str(exc), version, kind, subject_id, None, None, None)
    raise exc


@contextmanager
def read_only_snapshot(connection: psycopg.Connection) -> Iterator[None]:
    """A read-only, repeatable-read transaction, or a savepoint in the caller's own transaction.

    The same rule as the composition and arrangement previews: isolation is chosen when a
    transaction begins, so inside one the caller opened, that transaction's rules apply.
    """
    if connection.info.transaction_status != pq.TransactionStatus.IDLE:
        with connection.transaction():
            yield
        return
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read, read only")
        yield
