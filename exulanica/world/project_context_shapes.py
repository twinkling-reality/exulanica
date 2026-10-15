"""What a world project is made of, as its repository and its readers name it.

The declared bounds (``docs/project-context.md`` states them), the vocabulary of an item (its kind,
the basis it is written on, its status, its origin and why it was withdrawn) with the rules for
which basis each kind may take, the refusals this plane owns with the status and stable code the
API answers each with, and the views a read returns.
:class:`~exulanica.world.project_context.ProjectContextRepository` reads and writes them; nothing
here opens the database.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from exulanica.errors import ExulanicaError
from exulanica.world.project_context_assembly import Assembly
from exulanica.world.project_context_references import Resolution

#: Declared bounds. Characters, counts and revisions, as ``docs/project-context.md`` states them.
TITLE_MAX: Final = 200

TEXT_MAX: Final = 2_000

NOTE_MAX: Final = 2_000

#: Live projects one person keeps in one world.
MAX_PROJECTS: Final = 50

#: Items a project holds that are not deleted.
MAX_ITEMS: Final = 500

#: Revisions one item may take, its first included.
MAX_REVISIONS: Final = 50

#: Suggestions a project holds waiting for review.
MAX_PENDING: Final = 50

#: Records an item is drawn from: Companion answers and an item it copies.
MAX_SOURCES: Final = 16

LIST_DEFAULT: Final = 50

LIST_MAX: Final = 100


class ItemKind(StrEnum):
    GOAL = "goal"
    PREFERENCE = "preference"
    QUESTION = "question"
    TASK = "task"
    DECISION = "decision"
    EVENT = "event"


class ItemBasis(StrEnum):
    USER_STATEMENT = "user_statement"
    INFERRED_SUGGESTION = "inferred_suggestion"
    RECORDED_OUTCOME = "recorded_outcome"
    SIMULATED_EVENT = "simulated_event"


class ItemStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"


class ItemOrigin(StrEnum):
    PERSON = "person"
    COMPANION = "companion"


class WithdrawalReason(StrEnum):
    DELETED = "deleted"
    REJECTED = "rejected"
    PROJECT_DELETED = "project_deleted"
    SOURCE_WITHDRAWN = "source_withdrawn"
    WORKSPACE_DELETED = "workspace_deleted"


#: What an item of each kind is written as. Held equal to the revision guard of migration 0127.
_WORDED: Final = frozenset({ItemKind.GOAL, ItemKind.PREFERENCE, ItemKind.QUESTION, ItemKind.TASK})

_BASES: Final[Mapping[ItemKind, frozenset[ItemBasis]]] = MappingProxyType(
    {
        **{
            kind: frozenset({ItemBasis.USER_STATEMENT, ItemBasis.INFERRED_SUGGESTION})
            for kind in _WORDED
        },
        ItemKind.DECISION: frozenset({ItemBasis.RECORDED_OUTCOME}),
        ItemKind.EVENT: frozenset({ItemBasis.SIMULATED_EVENT}),
    }
)

#: What the person's own correction of each kind is filed as.
_CORRECTED_BASIS: Final[Mapping[ItemKind, ItemBasis]] = MappingProxyType(
    {
        **{kind: ItemBasis.USER_STATEMENT for kind in _WORDED},
        ItemKind.DECISION: ItemBasis.RECORDED_OUTCOME,
        ItemKind.EVENT: ItemBasis.SIMULATED_EVENT,
    }
)

#: Kinds that close when done. A preference, a decision and an event are corrected or deleted.
_RESOLVABLE: Final = frozenset({ItemKind.GOAL, ItemKind.QUESTION, ItemKind.TASK})

_KIND_ORDER: Final = tuple(kind.value for kind in ItemKind)


class ProjectContextError(ExulanicaError):
    """A refusal this plane owns, with the status and stable code the API answers it with."""

    status: int = 422
    code: str = "invalid_project_context"


class UnknownProjectContext(ProjectContextError):
    """Absent, deleted, another person's private record, another workspace's, or a world the
    project is not in: one answer, so none of them can be told from an id nobody minted."""

    status = 404
    code = "unknown_reference"


class InvalidProjectContext(ProjectContextError):
    status = 422
    code = "invalid_project_context"


class StaleProjectContext(ProjectContextError):
    status = 409
    code = "stale_project_context"


class IdempotencyKeyReused(ProjectContextError):
    status = 409
    code = "idempotency_key_reused"


class NotProjectOwner(ProjectContextError):
    """A person who may read a shared project asked to change it."""

    status = 403
    code = "not_project_owner"


class ProjectItemNotCurrent(ProjectContextError):
    status = 409
    code = "project_item_not_current"


class ProjectContextLimit(ProjectContextError):
    status = 409

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ProjectContextBusy(ProjectContextError):
    """A write the database ended to break a lock cycle, every time it was tried."""

    status = 503
    code = "project_context_busy"


class ReferenceRefused(ProjectContextError):
    """A record an item names is not one it may name now: its source was deleted, or its ids
    disagree with the record. The status and code are the authority's own."""

    def __init__(self, resolution: Resolution) -> None:
        code = resolution.code or "reference_mismatch"
        super().__init__(f"a named record is {resolution.state.value}: {code}")
        self.code = code
        self.status = 424 if code == "unavailable_society_input" else 409


@dataclass(frozen=True, slots=True)
class Binding:
    """The version a project works on, as its authority reads now and as it was when bound."""

    version_id: uuid.UUID
    state: str
    code: str | None
    state_sha256: str
    edit_seq: int
    bound_at: dt.datetime
    bound_state_sha256: str
    bound_edit_seq: int
    #: The world's saved entry, where it has one, and the version that entry opens now.
    entry_id: uuid.UUID | None
    entry_version_id: uuid.UUID | None


@dataclass(frozen=True, slots=True)
class ProjectView:
    project_id: uuid.UUID
    world_id: str
    title: str
    revision: int
    created_at: dt.datetime
    changed_at: dt.datetime
    owner_is_reader: bool
    #: The open share of the project itself, or None. Another reader sees one by definition.
    share_id: uuid.UUID | None
    binding: Binding
    #: Items this reader may see: active ones by kind, and how many are resolved or proposed.
    counts: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class ReferenceView:
    reference: Mapping[str, Any]
    state: str
    code: str | None
    detail: str | None


@dataclass(frozen=True, slots=True)
class Reuse:
    """The item an item was copied from: its own world, project and id."""

    world_id: str
    project_id: uuid.UUID
    item_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class ItemView:
    item_id: uuid.UUID
    project_id: uuid.UUID
    project_revision: int
    kind: ItemKind
    basis: ItemBasis
    origin: ItemOrigin
    status: ItemStatus
    revision: int
    created_at: dt.datetime
    changed_at: dt.datetime
    recorded_at: dt.datetime
    reviewed_at: dt.datetime | None
    resolved_at: dt.datetime | None
    text: str | None
    note: str | None
    references: tuple[ReferenceView, ...]
    #: References into planes this reader may not see: another person's Companion answers.
    hidden_references: int
    share_id: uuid.UUID | None
    owner_is_reader: bool
    #: The owner's own: the Companion answers it was drawn from and the item it copied.
    source_answer_ids: tuple[uuid.UUID, ...]
    reused_from: Reuse | None


@dataclass(frozen=True, slots=True)
class RevisionView:
    revision: int
    basis: ItemBasis
    origin: ItemOrigin
    text: str | None
    note: str | None
    references: tuple[Mapping[str, Any], ...]
    recorded_at: dt.datetime


@dataclass(frozen=True, slots=True)
class ShareView:
    share_id: uuid.UUID
    item_id: uuid.UUID | None
    shared_at: dt.datetime


@dataclass(frozen=True, slots=True)
class AuditItem:
    item_id: uuid.UUID
    kind: ItemKind
    status: ItemStatus
    created_at: dt.datetime
    reviewed_at: dt.datetime | None
    resolved_at: dt.datetime | None
    withdrawn_at: dt.datetime | None
    withdrawn_reason: WithdrawalReason | None
    #: Each revision's basis, origin and instant, in order; never its words.
    revisions: tuple[tuple[ItemBasis, ItemOrigin, dt.datetime], ...]


@dataclass(frozen=True, slots=True)
class ProjectAudit:
    """What remains of a project that may have been deleted: that things existed and when they
    ended, and none of what they said."""

    project_id: uuid.UUID
    world_id: str
    created_at: dt.datetime
    withdrawn_at: dt.datetime | None
    #: True when a tombstone deleted the project rather than its owner.
    withdrawn_by_tombstone: bool
    revision: int
    bindings: tuple[tuple[int, uuid.UUID, dt.datetime], ...]
    items: tuple[AuditItem, ...]
    shares: tuple[tuple[uuid.UUID, uuid.UUID | None, dt.datetime, dt.datetime | None], ...]


@dataclass(frozen=True, slots=True)
class ContextView:
    project: ProjectView
    assembly: Assembly
