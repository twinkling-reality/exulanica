"""A world project: what one person chose to keep about their work in one world.

`docs/project-context.md` is the contract; migration 0127 is the schema. A project is bound to an
authored version of one world and holds items: goals, preferences, questions and tasks in the
person's own words or in words they accepted from a suggestion, decisions that name accepted
records, and events that name simulated ones. Each item keeps its corrections as revisions. The
ids an item points at are resolved against their own authorities at every read
(:mod:`exulanica.world.project_context_references`), and the context a reader may hand onward is
assembled, bounded, from current rows every time (:mod:`exulanica.world.project_context_assembly`).

**The actor is a constructor argument and every statement carries it**, for the reason
:class:`~exulanica.world.companion_memory.CompanionMemoryRepository` gives: row-level security
sees the workspace and never the person, so the clause naming the person is the whole of what keeps
two people of one workspace apart. Only a project's owner writes it. Another person reads a
project, and each item in it, only while the owner shares it; a proposal, a correction history, a
Companion answer and the audit are the owner's alone.

**Nothing here reaches the interaction-policy plane, a permission or a model.** The module imports
none of them, which an import contract in ``pyproject.toml`` holds; a preference kept here is what
a person said they want, and deciding what the system may do is a different plane's review.

**Locking.** A write takes the Companion answers it names ``FOR SHARE`` in id order, then its
project ``FOR UPDATE``, then its items, and an item it copies ``FOR SHARE`` last. A deletion that
reaches items through answers locks their projects in id order before the items, and a workspace
tombstone updates answers (0043) before projects and items (0127). None of them takes the workspace
advisory lock while holding one of these rows: ``tg_world_structure_invalidate_on_tombstone``
takes it after the rows above, so a write that held it while waiting for an answer row could close
a cycle. Reference checks on the write path read rows only; the society authorization a read
applies, which takes the workspace lock, runs only on reads, which hold no row lock.

One kind of path does not follow the project-first order: a deletion reaching copies of an item,
which live in other projects, takes those copies without their projects. Two such deletions
coming at each other's projects can wait on each other; the database ends one of them, and every
write here is tried again (:data:`_DEADLOCK_ATTEMPTS`) before it answers ``project_context_busy``.
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Concatenate, Final, ParamSpec, TypeVar

import psycopg
from psycopg.types.json import Jsonb

from exulanica.canonical import canonical_json
from exulanica.db.guards import TOMBSTONE_REFUSAL
from exulanica.epistemics.saved_names import PLACEHOLDER
from exulanica.errors import ExulanicaError, TombstonedError
from exulanica.world.companion_memory import SIMULATED_LABEL
from exulanica.world.project_context_assembly import Assembly, Budget, Candidate, assemble
from exulanica.world.project_context_references import (
    OUTCOME_KINDS,
    SIMULATED_KINDS,
    InvalidReference,
    Reference,
    ReferenceKind,
    ReferenceResolver,
    ReferenceState,
    Resolution,
    parse_references,
)

__all__ = [
    "LIST_DEFAULT",
    "LIST_MAX",
    "MAX_ITEMS",
    "MAX_PENDING",
    "MAX_PROJECTS",
    "MAX_REVISIONS",
    "MAX_SOURCES",
    "NOTE_MAX",
    "TEXT_MAX",
    "TITLE_MAX",
    "AuditItem",
    "Binding",
    "ContextView",
    "IdempotencyKeyReused",
    "InvalidProjectContext",
    "ItemBasis",
    "ItemKind",
    "ItemOrigin",
    "ItemStatus",
    "ItemView",
    "NotProjectOwner",
    "ProjectAudit",
    "ProjectContextBusy",
    "ProjectContextError",
    "ProjectContextLimit",
    "ProjectContextRepository",
    "ProjectItemNotCurrent",
    "ProjectView",
    "ReferenceRefused",
    "ReferenceView",
    "Reuse",
    "RevisionView",
    "ShareView",
    "StaleProjectContext",
    "UnknownProjectContext",
    "WithdrawalReason",
]

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

#: Creating a project counts a person's live projects in one world under this lock, so the count
#: bound holds under concurrent creation. Its own key, never the workspace lock's: it is taken
#: before any row lock.
_CREATION_LOCK_SEED: Final = 880_127

#: The key a creation holds shared and a workspace tombstone exclusively (migration 0127), so a
#: project created while its workspace is deleted is either deleted with it or refused.
_PLANE_KEY: Final = "world_project:{workspace}"

#: How many times a write is tried when the database ended it to break a lock cycle.
_DEADLOCK_ATTEMPTS: Final = 3

#: The unique indexes an idempotency key is held to (migration 0127).
_REQUEST_KEYS: Final = frozenset({"world_project_request_key", "world_project_item_request_key"})


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


# -- failures ----------------------------------------------------------------------------------


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


class _KeyRace(Exception):
    """Another request under the same idempotency key committed first; look it up again."""


class ReferenceRefused(ProjectContextError):
    """A record an item names is not one it may name now: its source was deleted, or its ids
    disagree with the record. The status and code are the authority's own."""

    def __init__(self, resolution: Resolution) -> None:
        code = resolution.code or "reference_mismatch"
        super().__init__(f"a named record is {resolution.state.value}: {code}")
        self.code = code
        self.status = 424 if code == "unavailable_society_input" else 409


# -- views -------------------------------------------------------------------------------------


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


# -- the repository ----------------------------------------------------------------------------


def _digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _words(value: str | None, name: str, maximum: int, *, required: bool) -> str | None:
    if value is None:
        if required:
            raise InvalidProjectContext(f"{name} is required")
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvalidProjectContext(f"{name} is 1 to {maximum} characters")
    # The refusal never quotes the text: a label that is not a placeholder may be a name.
    if PLACEHOLDER.search(value) or SIMULATED_LABEL.search(value):
        raise InvalidProjectContext(
            f"{name} carries a placeholder, which a project item cannot resolve to anyone"
        )
    return value


_Args = ParamSpec("_Args")
_Result = TypeVar("_Result")


def _retrying(
    method: Callable[Concatenate[ProjectContextRepository, _Args], _Result],
) -> Callable[Concatenate[ProjectContextRepository, _Args], _Result]:
    """Try a write again when the database ended it to break a lock cycle; each try is a
    transaction of its own, so a later one starts from what committed meanwhile."""

    @functools.wraps(method)
    def write(self: ProjectContextRepository, *args: _Args.args, **kwargs: _Args.kwargs) -> _Result:
        for attempt in range(1, _DEADLOCK_ATTEMPTS + 1):
            try:
                return method(self, *args, **kwargs)
            except psycopg.errors.DeadlockDetected:
                if attempt == _DEADLOCK_ATTEMPTS:
                    raise ProjectContextBusy(
                        "the project is being changed by another request; try again"
                    ) from None
        raise AssertionError("unreachable")

    return write


class ProjectContextRepository:
    """Project context for one person in one world of one workspace."""

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
        world_id: str,
        *,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor_id = actor_id
        self.world_id = world_id
        self.input_authorizer = input_authorizer

    def _resolver(self) -> ReferenceResolver:
        return ReferenceResolver(
            self.connection,
            self.workspace_id,
            self.actor_id,
            input_authorizer=self.input_authorizer,
        )

    @contextmanager
    def _writing(self) -> Iterator[None]:
        """One write's transaction. A workspace a tombstone deleted as a whole takes nothing new,
        and the database's refusal of it reaches the caller as the deletion it is."""
        try:
            with self.connection.transaction():
                yield
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name in _REQUEST_KEYS:
                raise _KeyRace from exc
            raise
        except psycopg.errors.IntegrityConstraintViolation as exc:
            if TOMBSTONE_REFUSAL not in str(exc):
                raise
            raise TombstonedError(
                "this workspace was deleted, so nothing new is kept in it"
            ) from exc

    # -- the project row, as this reader may see it --------------------------------------------

    def _project_row(
        self, project_id: uuid.UUID, *, lock: bool = False, owner: bool = False
    ) -> Mapping[str, Any]:
        """The live project if this reader owns it or it is shared with them.

        ``owner`` refuses a visible project this reader does not own with :class:`NotProjectOwner`,
        and everything else with :class:`UnknownProjectContext`.
        """
        row = self.connection.execute(
            "select p.*, p.owner_actor_id=%(actor)s as owned, ("
            " select s.share_id from world_project_share s where s.workspace_id=p.workspace_id"
            " and s.project_id=p.project_id and s.item_id is null and s.withdrawn_at is null"
            ") as project_share_id from world_project p "
            "where p.workspace_id=%(ws)s and p.world_id=%(world)s and p.project_id=%(project)s "
            "and p.withdrawn_at is null and (p.owner_actor_id=%(actor)s or exists ("
            " select 1 from world_project_share s where s.workspace_id=p.workspace_id"
            " and s.project_id=p.project_id and s.item_id is null and s.withdrawn_at is null))"
            + (" for update of p" if lock else ""),
            {
                "ws": self.workspace_id,
                "world": self.world_id,
                "project": project_id,
                "actor": self.actor_id,
            },
        ).fetchone()
        if row is None:
            raise UnknownProjectContext("no such project")
        if owner and not row["owned"]:
            raise NotProjectOwner("only this project's owner changes it")
        return row

    def _advance(self, project: Mapping[str, Any]) -> int:
        """Move the project's revision by one, as every write does."""
        row = self.connection.execute(
            "update world_project set revision=revision+1, changed_at=now() "
            "where workspace_id=%s and world_id=%s and project_id=%s returning revision",
            (self.workspace_id, self.world_id, project["project_id"]),
        ).fetchone()
        assert row is not None
        return int(row["revision"])

    @staticmethod
    def _require_base(project: Mapping[str, Any], base_revision: int) -> None:
        if type(base_revision) is not int or base_revision != project["revision"]:
            raise StaleProjectContext(
                "this project changed since it was read; read it again before changing it"
            )

    def _version(self, version_id: uuid.UUID) -> Mapping[str, Any]:
        """A version of this world, with whether a deletion invalidated its source."""
        row = self.connection.execute(
            "select v.version_id, v.world_id, v.state_sha256, v.edit_seq, exists ("
            " select 1 from world_structure_invalidation i where i.workspace_id=v.workspace_id"
            " and i.world_id=v.world_id and i.snapshot_id=v.source_snapshot_id) as invalidated "
            "from world_alternate_version v "
            "where v.workspace_id=%s and v.world_id=%s and v.version_id=%s",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if row is None:
            raise UnknownProjectContext("no such version in this world")
        return row

    # -- reads ---------------------------------------------------------------------------------

    def projects(self, *, limit: int = LIST_DEFAULT) -> tuple[ProjectView, ...]:
        """This world's projects this reader owns or may read, most recently changed first."""
        if type(limit) is not int or not 1 <= limit <= LIST_MAX:
            raise InvalidProjectContext(f"limit is between 1 and {LIST_MAX}")
        with self.connection.transaction():
            # The rows the views are built from, in one statement: a project deleted after this
            # list was read is listed as it was, never refused as unknown halfway through.
            rows = self.connection.execute(
                "select p.*, p.owner_actor_id=%(actor)s as owned, ("
                " select s.share_id from world_project_share s where s.workspace_id=p.workspace_id"
                " and s.project_id=p.project_id and s.item_id is null and s.withdrawn_at is null"
                ") as project_share_id from world_project p "
                "where p.workspace_id=%(ws)s and p.world_id=%(world)s and p.withdrawn_at is null "
                "and (p.owner_actor_id=%(actor)s or exists ("
                " select 1 from world_project_share s where s.workspace_id=p.workspace_id"
                " and s.project_id=p.project_id and s.item_id is null"
                " and s.withdrawn_at is null)) "
                "order by p.changed_at desc, p.project_id limit %(limit)s",
                {
                    "ws": self.workspace_id,
                    "world": self.world_id,
                    "actor": self.actor_id,
                    "limit": limit,
                },
            ).fetchall()
            return tuple(self._project_view(row) for row in rows)

    def project(self, project_id: uuid.UUID) -> ProjectView:
        with self.connection.transaction():
            return self._project_view(self._project_row(project_id))

    def _project_view(self, row: Mapping[str, Any]) -> ProjectView:
        version = self._version(row["version_id"])
        bound = self.connection.execute(
            "select b.state_sha256, b.edit_seq, b.bound_at from world_project_binding b "
            "where b.workspace_id=%s and b.world_id=%s and b.project_id=%s "
            "order by b.binding_seq desc limit 1",
            (self.workspace_id, self.world_id, row["project_id"]),
        ).fetchone()
        assert bound is not None
        entry = self.connection.execute(
            "select e.entry_id, e.authored_version_id from saved_world_entry e "
            "where e.workspace_id=%s and e.world_id=%s",
            (self.workspace_id, self.world_id),
        ).fetchone()
        counts = {kind: 0 for kind in _KIND_ORDER} | {"resolved": 0, "proposed": 0}
        for count in self.connection.execute(
            "select i.kind::text as kind, i.status::text as status, count(*) as n "
            "from world_project_item i where i.workspace_id=%(ws)s and i.world_id=%(world)s "
            "and i.project_id=%(project)s and i.status<>'withdrawn' and (%(owned)s or ("
            " i.status in ('active','resolved') and exists (select 1 from world_project_share s"
            " where s.workspace_id=i.workspace_id and s.item_id=i.item_id"
            " and s.withdrawn_at is null))) group by i.kind, i.status",
            {
                "ws": self.workspace_id,
                "world": self.world_id,
                "project": row["project_id"],
                "owned": row["owned"],
            },
        ).fetchall():
            key = count["kind"] if count["status"] == ItemStatus.ACTIVE else count["status"]
            counts[key] += int(count["n"])
        return ProjectView(
            project_id=row["project_id"],
            world_id=row["world_id"],
            title=row["title"],
            revision=int(row["revision"]),
            created_at=row["created_at"],
            changed_at=row["changed_at"],
            owner_is_reader=bool(row["owned"]),
            share_id=row["project_share_id"],
            binding=Binding(
                version_id=version["version_id"],
                state="unavailable" if version["invalidated"] else "available",
                code="invalidated_source_version" if version["invalidated"] else None,
                state_sha256=version["state_sha256"],
                edit_seq=int(version["edit_seq"]),
                bound_at=bound["bound_at"],
                bound_state_sha256=bound["state_sha256"],
                bound_edit_seq=int(bound["edit_seq"]),
                entry_id=None if entry is None else entry["entry_id"],
                entry_version_id=None if entry is None else entry["authored_version_id"],
            ),
            counts=MappingProxyType(counts),
        )

    def _item_rows(
        self,
        project: Mapping[str, Any],
        *,
        statuses: frozenset[ItemStatus] | None = None,
        item_id: uuid.UUID | None = None,
    ) -> list[Mapping[str, Any]]:
        """The items this reader may see, each with its current revision and open share."""
        return self.connection.execute(
            "select i.*, r.basis::text as basis, r.origin::text as origin, r.text, r.note, "
            "r.refs, r.recorded_at, (select s.share_id from world_project_share s"
            " where s.workspace_id=i.workspace_id and s.item_id=i.item_id"
            " and s.withdrawn_at is null) as share_id "
            "from world_project_item i join world_project_item_revision r "
            "on r.workspace_id=i.workspace_id and r.item_id=i.item_id "
            "and r.revision=i.current_revision "
            "where i.workspace_id=%(ws)s and i.world_id=%(world)s and i.project_id=%(project)s "
            "and i.status<>'withdrawn' and (%(item)s::uuid is null or i.item_id=%(item)s::uuid) "
            "and (%(statuses)s::text[] is null or i.status::text = any(%(statuses)s::text[])) "
            "and (%(owned)s or (i.status in ('active','resolved') and exists ("
            " select 1 from world_project_share s where s.workspace_id=i.workspace_id"
            " and s.item_id=i.item_id and s.withdrawn_at is null))) "
            "order by i.created_at, i.item_id",
            {
                "ws": self.workspace_id,
                "world": self.world_id,
                "project": project["project_id"],
                "item": item_id,
                "statuses": None if statuses is None else sorted(s.value for s in statuses),
                "owned": project["owned"],
            },
        ).fetchall()

    def _sources(self, item_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[Mapping[str, Any]]]:
        if not item_ids:
            return {}
        grouped: dict[uuid.UUID, list[Mapping[str, Any]]] = {}
        for row in self.connection.execute(
            "select s.item_id, s.source_answer_id, s.source_item_id, i.world_id, i.project_id "
            "from world_project_item_source s left join world_project_item i "
            "on i.workspace_id=s.workspace_id and i.item_id=s.source_item_id "
            "where s.workspace_id=%s and s.item_id = any(%s) order by s.item_id, s.ordinal",
            (self.workspace_id, list(item_ids)),
        ).fetchall():
            grouped.setdefault(row["item_id"], []).append(row)
        return grouped

    def _views(
        self, project: Mapping[str, Any], rows: Sequence[Mapping[str, Any]], *, resolve: bool
    ) -> list[ItemView]:
        """Item views, references resolved in one batch and filtered for this reader."""
        owned = bool(project["owned"])
        shown: list[list[Reference]] = []
        hidden: list[int] = []
        for row in rows:
            references = parse_references(row["refs"] or ())
            visible = [r for r in references if owned or r.world_plane()]
            shown.append(visible)
            hidden.append(len(references) - len(visible))
        flat = [reference for group in shown for reference in group]
        resolver = self._resolver()
        resolutions = iter(resolver.resolve(flat) if resolve else resolver.check(flat))
        sources = self._sources([row["item_id"] for row in rows]) if owned else {}
        views = []
        for row, references, hidden_count in zip(rows, shown, hidden, strict=True):
            reused = next(
                (
                    Reuse(s["world_id"], s["project_id"], s["source_item_id"])
                    for s in sources.get(row["item_id"], ())
                    if s["source_item_id"] is not None
                ),
                None,
            )
            views.append(
                ItemView(
                    item_id=row["item_id"],
                    project_id=row["project_id"],
                    project_revision=int(project["revision"]),
                    kind=ItemKind(row["kind"]),
                    basis=ItemBasis(row["basis"]),
                    origin=ItemOrigin(row["origin"]),
                    status=ItemStatus(row["status"]),
                    revision=int(row["current_revision"]),
                    created_at=row["created_at"],
                    changed_at=row["changed_at"],
                    recorded_at=row["recorded_at"],
                    reviewed_at=row["reviewed_at"],
                    resolved_at=row["resolved_at"],
                    text=row["text"],
                    # Why the owner corrected an item is part of its correction history, which
                    # is the owner's alone; another reader sees the words that stand.
                    note=row["note"] if owned else None,
                    references=tuple(
                        ReferenceView(
                            reference=MappingProxyType(reference.document()),
                            state=resolution.state.value,
                            code=resolution.code,
                            detail=resolution.detail,
                        )
                        for reference, resolution in zip(
                            references,
                            [next(resolutions) for _ in references],
                            strict=True,
                        )
                    ),
                    hidden_references=hidden_count,
                    share_id=row["share_id"],
                    owner_is_reader=owned,
                    source_answer_ids=tuple(
                        s["source_answer_id"]
                        for s in sources.get(row["item_id"], ())
                        if s["source_answer_id"] is not None
                    ),
                    reused_from=reused,
                )
            )
        return views

    def items(
        self, project_id: uuid.UUID, *, statuses: frozenset[ItemStatus] | None = None
    ) -> tuple[ItemView, ...]:
        """Every item this reader may see, oldest first, with what each names resolved now."""
        if statuses is not None and ItemStatus.WITHDRAWN in statuses:
            raise InvalidProjectContext("a deleted item is not read back")
        with self.connection.transaction():
            project = self._project_row(project_id)
            rows = self._item_rows(project, statuses=statuses)
            return tuple(self._views(project, rows, resolve=True))

    def item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> ItemView:
        with self.connection.transaction():
            project = self._project_row(project_id)
            rows = self._item_rows(project, item_id=item_id)
            if not rows:
                raise UnknownProjectContext("no such item")
            return self._views(project, rows, resolve=True)[0]

    def history(self, project_id: uuid.UUID, item_id: uuid.UUID) -> tuple[RevisionView, ...]:
        """Every revision of one of this reader's own items, with its words: the correction
        history. Another reader of a shared item sees its current words only."""
        with self.connection.transaction():
            project = self._project_row(project_id)
            if not project["owned"]:
                raise NotProjectOwner("a correction history is its owner's")
            rows = self.connection.execute(
                "select r.revision, r.basis::text as basis, r.origin::text as origin, r.text, "
                "r.note, r.refs, r.recorded_at from world_project_item_revision r "
                "join world_project_item i on i.workspace_id=r.workspace_id "
                "and i.item_id=r.item_id where i.workspace_id=%s and i.world_id=%s "
                "and i.project_id=%s and i.item_id=%s and i.status<>'withdrawn' "
                "order by r.revision",
                (self.workspace_id, self.world_id, project_id, item_id),
            ).fetchall()
        if not rows:
            raise UnknownProjectContext("no such item")
        return tuple(
            RevisionView(
                revision=int(row["revision"]),
                basis=ItemBasis(row["basis"]),
                origin=ItemOrigin(row["origin"]),
                text=row["text"],
                note=row["note"],
                references=tuple(
                    MappingProxyType(reference.document())
                    for reference in parse_references(row["refs"] or ())
                ),
                recorded_at=row["recorded_at"],
            )
            for row in rows
        )

    def audit(self, project_id: uuid.UUID) -> ProjectAudit:
        """The non-content residue of one of this reader's projects, deleted or not."""
        with self.connection.transaction():
            project = self.connection.execute(
                "select p.* from world_project p where p.workspace_id=%s and p.world_id=%s "
                "and p.project_id=%s and p.owner_actor_id=%s",
                (self.workspace_id, self.world_id, project_id, self.actor_id),
            ).fetchone()
            if project is None:
                # A shared reader may know the project exists; the residue is still its owner's.
                self._project_row(project_id, owner=True)
                raise UnknownProjectContext("no such project")
            bindings = self.connection.execute(
                "select b.binding_seq, b.version_id, b.bound_at from world_project_binding b "
                "where b.workspace_id=%s and b.world_id=%s and b.project_id=%s "
                "order by b.binding_seq",
                (self.workspace_id, self.world_id, project_id),
            ).fetchall()
            items = self.connection.execute(
                "select i.item_id, i.kind::text as kind, i.status::text as status, "
                "i.created_at, i.reviewed_at, i.resolved_at, i.withdrawn_at, "
                "i.withdrawn_reason::text as withdrawn_reason from world_project_item i "
                "where i.workspace_id=%s and i.world_id=%s and i.project_id=%s "
                "order by i.created_at, i.item_id",
                (self.workspace_id, self.world_id, project_id),
            ).fetchall()
            recorded: dict[uuid.UUID, list[tuple[ItemBasis, ItemOrigin, dt.datetime]]] = {}
            for revision in self.connection.execute(
                "select r.item_id, r.basis::text as basis, r.origin::text as origin, "
                "r.recorded_at from world_project_item_revision r join world_project_item i "
                "on i.workspace_id=r.workspace_id and i.item_id=r.item_id "
                "where i.workspace_id=%s and i.world_id=%s and i.project_id=%s "
                "order by r.item_id, r.revision",
                (self.workspace_id, self.world_id, project_id),
            ).fetchall():
                recorded.setdefault(revision["item_id"], []).append(
                    (
                        ItemBasis(revision["basis"]),
                        ItemOrigin(revision["origin"]),
                        revision["recorded_at"],
                    )
                )
            shares = self.connection.execute(
                "select s.share_id, s.item_id, s.shared_at, s.withdrawn_at "
                "from world_project_share s where s.workspace_id=%s and s.project_id=%s "
                "order by s.shared_at, s.share_id",
                (self.workspace_id, project_id),
            ).fetchall()
        return ProjectAudit(
            project_id=project["project_id"],
            world_id=project["world_id"],
            created_at=project["created_at"],
            withdrawn_at=project["withdrawn_at"],
            withdrawn_by_tombstone=project["withdrawn_by"] is not None,
            revision=int(project["revision"]),
            bindings=tuple(
                (int(b["binding_seq"]), b["version_id"], b["bound_at"]) for b in bindings
            ),
            items=tuple(
                AuditItem(
                    item_id=row["item_id"],
                    kind=ItemKind(row["kind"]),
                    status=ItemStatus(row["status"]),
                    created_at=row["created_at"],
                    reviewed_at=row["reviewed_at"],
                    resolved_at=row["resolved_at"],
                    withdrawn_at=row["withdrawn_at"],
                    withdrawn_reason=None
                    if row["withdrawn_reason"] is None
                    else WithdrawalReason(row["withdrawn_reason"]),
                    revisions=tuple(recorded.get(row["item_id"], ())),
                )
                for row in items
            ),
            shares=tuple(
                (s["share_id"], s["item_id"], s["shared_at"], s["withdrawn_at"]) for s in shares
            ),
        )

    def context(
        self, project_id: uuid.UUID, *, budget: Budget, focus: str | None = None
    ) -> ContextView:
        """The bounded context this reader may hand onward, assembled from current rows.

        Active items only: a proposal has not been accepted, and a resolved item is done. Each
        entry carries where its words came from, and what it names with its state now. Nothing
        is kept of the assembly but what the caller keeps of it.
        """
        with self.connection.transaction():
            project = self._project_row(project_id)
            view = self._project_view(project)
            rows = self._item_rows(project, statuses=frozenset({ItemStatus.ACTIVE}))
            items = self._views(project, rows, resolve=True)
        candidates = []
        for item in items:
            entry = {
                "item_id": str(item.item_id),
                "revision": item.revision,
                "kind": item.kind.value,
                "basis": item.basis.value,
                "origin": item.origin.value,
                "written_by_reader": item.owner_is_reader,
                "recorded_at": item.recorded_at,
                "text": item.text,
                "note": item.note,
                "references": [
                    {
                        "reference": dict(reference.reference),
                        "state": reference.state,
                        "code": reference.code,
                        "detail": reference.detail,
                    }
                    for reference in item.references
                ],
            }
            pointing = item.kind in (ItemKind.DECISION, ItemKind.EVENT)
            candidates.append(
                Candidate(
                    item_id=item.item_id,
                    revision=item.revision,
                    kind=item.kind.value,
                    changed_at=item.changed_at,
                    text=item.text,
                    entry=entry,
                    required_available=not pointing
                    or any(r.state == ReferenceState.AVAILABLE for r in item.references),
                )
            )
        return ContextView(
            project=view,
            assembly=assemble(
                candidates,
                project_revision=view.revision,
                budget=budget,
                focus=focus,
                omitted={
                    "pending_review": view.counts["proposed"],
                    "resolved": view.counts["resolved"],
                },
            ),
        )

    # -- writes: the project -------------------------------------------------------------------

    @_retrying
    def create_project(
        self, *, title: str, version_id: uuid.UUID, idempotency_key: uuid.UUID | None = None
    ) -> tuple[ProjectView, bool]:
        """A new project bound to a version of this world; ``True`` when this call created it.

        An exact retry of a key is answered with the project it created before anything else is
        checked, and a key used for another request is refused by name, also when the two arrive
        together.
        """
        title = _words(title, "title", TITLE_MAX, required=True)
        digest = _digest(
            {
                "operation": "create_project",
                "world_id": self.world_id,
                "title": title,
                "version_id": str(version_id),
            }
        )
        keyed = (
            "select p.project_id as id, p.world_id, p.request_sha256, p.withdrawn_at "
            "from world_project p where p.workspace_id=%s and p.owner_actor_id=%s "
            "and p.request_id=%s"
        )
        try:
            return self._create_project(title, version_id, idempotency_key, digest, keyed)
        except _KeyRace:
            # The same key committed first under another creation lock, in another world.
            assert idempotency_key is not None
            with self._writing():
                found = self._keyed(keyed, idempotency_key, digest)
                if found is None:
                    raise IdempotencyKeyReused(
                        "this idempotency key was used for a different request"
                    ) from None
                return self._project_view(self._project_row(found)), False

    def _create_project(
        self,
        title: str,
        version_id: uuid.UUID,
        idempotency_key: uuid.UUID | None,
        digest: str,
        keyed: str,
    ) -> tuple[ProjectView, bool]:
        with self._writing():
            self.connection.execute(
                "select pg_advisory_xact_lock_shared(hashtextextended(%s,0))",
                (_PLANE_KEY.format(workspace=self.workspace_id),),
            )
            self.connection.execute(
                "select pg_advisory_xact_lock(hashtextextended(%s,%s))",
                (f"{self.workspace_id}:{self.actor_id}:{self.world_id}", _CREATION_LOCK_SEED),
            )
            if idempotency_key is not None:
                found = self._keyed(keyed, idempotency_key, digest)
                if found is not None:
                    return self._project_view(self._project_row(found)), False
            version = self._version(version_id)
            if version["invalidated"]:
                raise ReferenceRefused(
                    Resolution(ReferenceState.UNAVAILABLE, "invalidated_source_version")
                )
            live = self.connection.execute(
                "select count(*) as n from world_project p where p.workspace_id=%s "
                "and p.world_id=%s and p.owner_actor_id=%s and p.withdrawn_at is null",
                (self.workspace_id, self.world_id, self.actor_id),
            ).fetchone()
            if live["n"] >= MAX_PROJECTS:
                raise ProjectContextLimit(
                    "project_limit_reached",
                    f"a person keeps at most {MAX_PROJECTS} projects in one world",
                )
            row = self.connection.execute(
                "insert into world_project (workspace_id,world_id,owner_actor_id,title,"
                "version_id,request_id,request_sha256) values (%s,%s,%s,%s,%s,%s,%s) "
                "returning project_id",
                (
                    self.workspace_id,
                    self.world_id,
                    self.actor_id,
                    title,
                    version_id,
                    idempotency_key,
                    None if idempotency_key is None else digest,
                ),
            ).fetchone()
            assert row is not None
            self._bind(row["project_id"], version, binding_seq=1)
            return self._project_view(self._project_row(row["project_id"])), True

    def _keyed(self, statement: str, key: uuid.UUID, digest: str) -> uuid.UUID | None:
        """The id a key already made, or None; a deleted one is unknown, another request refused.

        ``statement`` selects the row's ``id``, ``world_id``, ``request_sha256`` and
        ``withdrawn_at`` by workspace, person and key, in that order of parameters.
        """
        found = self.connection.execute(
            statement, (self.workspace_id, self.actor_id, key)
        ).fetchone()
        if found is None:
            return None
        if found["withdrawn_at"] is not None:
            raise UnknownProjectContext("the request this key made has been deleted")
        # A project renamed since has no digest: what the key made no longer reads as that
        # request, so it is not answered as one.
        if found["world_id"] != self.world_id or found["request_sha256"] != digest:
            raise IdempotencyKeyReused("this idempotency key was used for a different request")
        return found["id"]

    def _bind(self, project_id: uuid.UUID, version: Mapping[str, Any], *, binding_seq: int) -> None:
        self.connection.execute(
            "insert into world_project_binding (workspace_id,project_id,binding_seq,world_id,"
            "version_id,state_sha256,edit_seq,bound_by) values (%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                project_id,
                binding_seq,
                self.world_id,
                version["version_id"],
                version["state_sha256"],
                version["edit_seq"],
                self.actor_id,
            ),
        )

    @_retrying
    def update_project(
        self,
        project_id: uuid.UUID,
        *,
        base_revision: int,
        title: str,
        version_id: uuid.UUID,
    ) -> ProjectView:
        """Rename the project, or bind it to another version of the same world."""
        title = _words(title, "title", TITLE_MAX, required=True)
        with self._writing():
            project = self._project_row(project_id, lock=True, owner=True)
            self._require_base(project, base_revision)
            if title == project["title"] and version_id == project["version_id"]:
                return self._project_view(project)
            if version_id != project["version_id"]:
                version = self._version(version_id)
                if version["invalidated"]:
                    raise ReferenceRefused(
                        Resolution(ReferenceState.UNAVAILABLE, "invalidated_source_version")
                    )
                self.connection.execute(
                    "update world_project set version_id=%s where workspace_id=%s "
                    "and world_id=%s and project_id=%s",
                    (version_id, self.workspace_id, self.world_id, project_id),
                )
                latest = self.connection.execute(
                    "select max(binding_seq) as n from world_project_binding b "
                    "where b.workspace_id=%s and b.world_id=%s and b.project_id=%s",
                    (self.workspace_id, self.world_id, project_id),
                ).fetchone()
                self._bind(project_id, version, binding_seq=int(latest["n"]) + 1)
            if title != project["title"]:
                # The creation digest covers the title it replaces, and a digest of a short title
                # is the title to anyone who can guess it; nothing else keeps an old title.
                self.connection.execute(
                    "update world_project set title=%s, request_sha256=null where workspace_id=%s "
                    "and world_id=%s and project_id=%s",
                    (title, self.workspace_id, self.world_id, project_id),
                )
            self._advance(project)
            return self._project_view(self._project_row(project_id))

    @_retrying
    def delete_project(self, project_id: uuid.UUID) -> None:
        """Delete the project: its title, every item's words and every share, for good.

        Never blocked by a stale base: a deletion is a person's right, not an edit that could
        conflict with one. Migration 0127's triggers erase the words and close the shares.
        """
        with self._writing():
            self._project_row(project_id, lock=True, owner=True)
            self.connection.execute(
                "update world_project set withdrawn_at=now(), changed_at=now() "
                "where workspace_id=%s and world_id=%s and project_id=%s",
                (self.workspace_id, self.world_id, project_id),
            )

    # -- writes: items -------------------------------------------------------------------------

    def _checked(self, references: Sequence[Reference]) -> None:
        """Refuse a reference its authority does not hold as named, or holds on a deleted source."""
        for resolution in self._resolver().check(references):
            if resolution.state in (ReferenceState.MISSING, ReferenceState.WITHDRAWN):
                raise UnknownProjectContext("an item names a record that is not in this world")
            if resolution.state is not ReferenceState.AVAILABLE:
                raise ReferenceRefused(resolution)

    def _lock_answers(self, answer_ids: Sequence[str]) -> None:
        """Hold the Companion answers an item is drawn from, so none is deleted under it."""
        wanted = sorted(set(answer_ids))
        if not wanted:
            return
        rows = self.connection.execute(
            "select a.answer_id from companion_answer a where a.workspace_id=%s "
            "and a.actor_id=%s and a.answer_id = any(%s::uuid[]) and a.status<>'withdrawn' "
            "order by a.answer_id for share",
            (self.workspace_id, self.actor_id, wanted),
        ).fetchall()
        if len(rows) != len(wanted):
            raise UnknownProjectContext("an item names an answer this person does not hold")

    @staticmethod
    def _answer_ids(references: Sequence[Reference]) -> list[str]:
        return [
            r.fields["answer_id"] for r in references if r.kind is ReferenceKind.COMPANION_ANSWER
        ]

    @staticmethod
    def _allowed(kind: ItemKind, references: Sequence[Reference]) -> None:
        allowed = {ItemKind.DECISION: OUTCOME_KINDS, ItemKind.EVENT: SIMULATED_KINDS}.get(kind)
        if allowed is not None and (
            not references or any(r.kind not in allowed for r in references)
        ):
            raise InvalidProjectContext(
                f"a {kind.value} names one or more records of the kinds it keeps"
            )

    def _references(self, values: Sequence[object]) -> tuple[Reference, ...]:
        try:
            return parse_references(values)
        except InvalidReference as exc:
            raise InvalidProjectContext(str(exc)) from exc

    @_retrying
    def add_item(
        self,
        project_id: uuid.UUID,
        *,
        base_revision: int,
        kind: ItemKind | None = None,
        basis: ItemBasis | None = None,
        text: str | None = None,
        note: str | None = None,
        references: Sequence[object] = (),
        reuse: Reuse | None = None,
        idempotency_key: uuid.UUID | None = None,
    ) -> tuple[ItemView, bool]:
        """Keep one item, or copy one of this person's items from another project.

        A suggestion (basis ``inferred_suggestion``) is the Companion's words about the person; it
        must name the Companion answers it was drawn from, and it waits for review before any
        context holds it. A copy takes the source's kind, words and references as they are now
        and is deleted with its source; a later correction of the source does not reach it.
        """
        parsed: tuple[Reference, ...] = ()
        if reuse is not None:
            if any(v is not None for v in (kind, basis, text, note)) or references:
                raise InvalidProjectContext("a copy takes everything from the item it copies")
            if reuse.project_id == project_id:
                raise InvalidProjectContext("a copy goes into another project than its source's")
            source_key: dict[str, Any] = {
                "world_id": reuse.world_id,
                "project_id": str(reuse.project_id),
                "item_id": str(reuse.item_id),
            }
            request: dict[str, Any] = {"reuse": source_key}
        else:
            if kind is None or basis is None:
                raise InvalidProjectContext("an item names its kind and basis")
            if basis not in _BASES[kind]:
                raise InvalidProjectContext(f"a {kind.value} is not a {basis.value}")
            worded = kind in _WORDED
            text = _words(text, "text", TEXT_MAX, required=worded)
            note = _words(note, "note", NOTE_MAX, required=False)
            if worded and note is not None:
                raise InvalidProjectContext("a note says why an item was corrected")
            parsed = self._references(references)
            self._allowed(kind, parsed)
            if basis is ItemBasis.INFERRED_SUGGESTION and not self._answer_ids(parsed):
                raise InvalidProjectContext(
                    "a suggestion names the Companion answers it was drawn from"
                )
            request = {
                "kind": kind.value,
                "basis": basis.value,
                "text": text,
                "note": note,
                "references": [r.document() for r in parsed],
            }
        digest = _digest(
            {
                "operation": "add_item",
                "world_id": self.world_id,
                "project_id": str(project_id),
                **request,
            }
        )
        keyed = (
            "select i.item_id as id, i.world_id, i.request_sha256, i.withdrawn_at "
            "from world_project_item i where i.workspace_id=%s and i.author_actor_id=%s "
            "and i.request_id=%s"
        )
        try:
            return self._add_item(
                project_id,
                base_revision=base_revision,
                kind=kind,
                basis=basis,
                text=text,
                note=note,
                parsed=parsed,
                reuse=reuse,
                idempotency_key=idempotency_key,
                digest=digest,
                keyed=keyed,
            )
        except _KeyRace:
            # The same key committed first into another project of this person's.
            assert idempotency_key is not None
            with self._writing():
                found = self._keyed(keyed, idempotency_key, digest)
                if found is None:
                    raise IdempotencyKeyReused(
                        "this idempotency key was used for a different request"
                    ) from None
                return self._written(project_id, found), False

    def _add_item(
        self,
        project_id: uuid.UUID,
        *,
        base_revision: int,
        kind: ItemKind | None,
        basis: ItemBasis | None,
        text: str | None,
        note: str | None,
        parsed: tuple[Reference, ...],
        reuse: Reuse | None,
        idempotency_key: uuid.UUID | None,
        digest: str,
        keyed: str,
    ) -> tuple[ItemView, bool]:
        with self._writing():
            if idempotency_key is not None:
                found = self._keyed(keyed, idempotency_key, digest)
                if found is not None:
                    return self._written(project_id, found), False
            copied = None
            if reuse is not None:
                copied = self._copied(reuse, lock=False)
                kind, basis = copied["kind"], copied["basis"]
                # The words that stand, not why they were last corrected: that note belongs to
                # the source's own history.
                text, note = copied["text"], None
                parsed = copied["references"]
            assert kind is not None and basis is not None
            self._checked(parsed)
            self._lock_answers(self._answer_ids(parsed))
            project = self._project_row(project_id, lock=True, owner=True)
            if idempotency_key is not None:
                # Again under the project's lock: a retry that waited for the request it repeats
                # is answered with what that request made, not refused as stale.
                found = self._keyed(keyed, idempotency_key, digest)
                if found is not None:
                    return self._written(project_id, found), False
            self._require_base(project, base_revision)
            # Last in the lock order, and read again under the lock: a copy is of the item as it
            # stands when the copy is made, never of words it no longer has.
            if (
                reuse is not None
                and copied is not None
                and self._copied(reuse, lock=True)["revision"] != copied["revision"]
            ):
                raise StaleProjectContext("the item being copied changed; copy it again")
            counts = self.connection.execute(
                "select count(*) as n, count(*) filter (where i.status='proposed') as pending "
                "from world_project_item i where i.workspace_id=%s and i.world_id=%s "
                "and i.project_id=%s and i.status<>'withdrawn'",
                (self.workspace_id, self.world_id, project_id),
            ).fetchone()
            if counts["n"] >= MAX_ITEMS:
                raise ProjectContextLimit(
                    "project_item_limit_reached", f"a project holds at most {MAX_ITEMS} items"
                )
            suggestion = basis is ItemBasis.INFERRED_SUGGESTION
            if suggestion and counts["pending"] >= MAX_PENDING:
                raise ProjectContextLimit(
                    "pending_suggestion_limit_reached",
                    f"a project holds at most {MAX_PENDING} suggestions waiting for review",
                )
            answers = sorted(set(self._answer_ids(parsed)))
            if len(answers) + (reuse is not None) > MAX_SOURCES:
                raise InvalidProjectContext(f"an item is drawn from at most {MAX_SOURCES} records")
            row = self.connection.execute(
                "insert into world_project_item (workspace_id,world_id,project_id,author_actor_id,"
                "kind,status,request_id,request_sha256) values (%s,%s,%s,%s,%s,%s,%s,%s) "
                "returning item_id",
                (
                    self.workspace_id,
                    self.world_id,
                    project_id,
                    self.actor_id,
                    kind.value,
                    (ItemStatus.PROPOSED if suggestion else ItemStatus.ACTIVE).value,
                    idempotency_key,
                    None if idempotency_key is None else digest,
                ),
            ).fetchone()
            assert row is not None
            item_id = row["item_id"]
            self._revise(
                item_id,
                1,
                basis,
                ItemOrigin.COMPANION if suggestion else ItemOrigin.PERSON,
                text,
                note,
                parsed,
            )
            ordinal = 0
            for answer_id in answers:
                self._source(item_id, ordinal, answer_id=answer_id)
                ordinal += 1
            if reuse is not None:
                self._source(item_id, ordinal, item=reuse.item_id)
            self._advance(project)
            return self._written(project_id, item_id), True

    def _copied(self, reuse: Reuse, *, lock: bool) -> dict[str, Any]:
        """The item a copy is taken from: this person's own, accepted, in another live project of
        theirs, in any world of the workspace. ``lock`` holds it ``FOR SHARE`` so it cannot be
        deleted before the copy's source row names it."""
        row = self.connection.execute(
            "select i.kind::text as kind, i.current_revision, r.basis::text as basis, r.text, "
            "r.note, r.refs from world_project_item i join world_project p "
            "on p.workspace_id=i.workspace_id and p.project_id=i.project_id "
            "join world_project_item_revision r on r.workspace_id=i.workspace_id "
            "and r.item_id=i.item_id and r.revision=i.current_revision "
            "where i.workspace_id=%s and i.world_id=%s and i.project_id=%s and i.item_id=%s "
            "and i.author_actor_id=%s and i.status in ('active','resolved') "
            "and p.withdrawn_at is null" + (" for share of i" if lock else ""),
            (
                self.workspace_id,
                reuse.world_id,
                reuse.project_id,
                reuse.item_id,
                self.actor_id,
            ),
        ).fetchone()
        if row is None:
            raise UnknownProjectContext("no item of this person's to copy")
        return {
            "kind": ItemKind(row["kind"]),
            "basis": ItemBasis(row["basis"]),
            "revision": int(row["current_revision"]),
            "text": row["text"],
            "note": row["note"],
            "references": parse_references(row["refs"] or ()),
        }

    def _revise(
        self,
        item_id: uuid.UUID,
        revision: int,
        basis: ItemBasis,
        origin: ItemOrigin,
        text: str | None,
        note: str | None,
        references: Sequence[Reference],
    ) -> None:
        self.connection.execute(
            "insert into world_project_item_revision (workspace_id,item_id,revision,basis,origin,"
            "text,note,refs,recorded_by) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (
                self.workspace_id,
                item_id,
                revision,
                basis.value,
                origin.value,
                text,
                note,
                Jsonb([r.document() for r in references]),
                self.actor_id,
            ),
        )

    def _source(
        self,
        item_id: uuid.UUID,
        ordinal: int,
        *,
        answer_id: str | None = None,
        item: uuid.UUID | None = None,
    ) -> None:
        self.connection.execute(
            "insert into world_project_item_source (workspace_id,item_id,ordinal,"
            "source_answer_id,source_item_id) values (%s,%s,%s,%s,%s)",
            (self.workspace_id, item_id, ordinal, answer_id, item),
        )

    def _written(self, project_id: uuid.UUID, item_id: uuid.UUID) -> ItemView:
        """What a write reports: the item as the checks of the write path read it.

        A write's own transaction may not ask the society for its authorization, which takes the
        workspace lock; a read of the item afterwards resolves it in full.
        """
        project = self._project_row(project_id)
        rows = self._item_rows(project, item_id=item_id)
        if not rows:
            raise UnknownProjectContext("no such item")
        return self._views(project, rows, resolve=False)[0]

    def _item_row(self, project: Mapping[str, Any], item_id: uuid.UUID) -> Mapping[str, Any]:
        row = self.connection.execute(
            "select i.* from world_project_item i where i.workspace_id=%s and i.world_id=%s "
            "and i.project_id=%s and i.item_id=%s and i.status<>'withdrawn' for update",
            (self.workspace_id, self.world_id, project["project_id"], item_id),
        ).fetchone()
        if row is None:
            raise UnknownProjectContext("no such item")
        return row

    @_retrying
    def correct_item(
        self,
        project_id: uuid.UUID,
        item_id: uuid.UUID,
        *,
        base_revision: int,
        text: str | None = None,
        note: str | None = None,
        references: Sequence[object] | None = None,
    ) -> ItemView:
        """Record the person's correction as the item's next revision; the earlier one stays in
        its history, readable by its owner, until the item is deleted."""
        note = _words(note, "note", NOTE_MAX, required=False)
        parsed = None if references is None else self._references(references)
        with self._writing():
            if parsed is not None:
                self._checked(parsed)
                self._lock_answers(self._answer_ids(parsed))
            project = self._project_row(project_id, lock=True, owner=True)
            self._require_base(project, base_revision)
            item = self._item_row(project, item_id)
            kind = ItemKind(item["kind"])
            if item["status"] not in (ItemStatus.PROPOSED, ItemStatus.ACTIVE):
                raise ProjectItemNotCurrent("a resolved item is closed; add a new one")
            if item["current_revision"] >= MAX_REVISIONS:
                raise ProjectContextLimit(
                    "item_revision_limit_reached",
                    f"an item takes at most {MAX_REVISIONS} revisions",
                )
            current = self.connection.execute(
                "select r.text, r.note, r.refs from world_project_item_revision r "
                "where r.workspace_id=%s and r.item_id=%s and r.revision=%s",
                (self.workspace_id, item_id, item["current_revision"]),
            ).fetchone()
            kept = parsed if parsed is not None else parse_references(current["refs"] or ())
            self._allowed(kind, kept)
            worded = kind in _WORDED
            text = _words(text, "text", TEXT_MAX, required=worded)
            if not worded and text is None and parsed is None:
                raise InvalidProjectContext("a correction changes the words or the records")
            revision = int(item["current_revision"]) + 1
            self.connection.execute(
                "update world_project_item set current_revision=%s, changed_at=now() "
                "where workspace_id=%s and world_id=%s and item_id=%s",
                (revision, self.workspace_id, self.world_id, item_id),
            )
            self._revise(
                item_id,
                revision,
                _CORRECTED_BASIS[kind],
                ItemOrigin.PERSON,
                text if text is not None else current["text"],
                note,
                kept,
            )
            held = {
                row["source_answer_id"]
                for row in self.connection.execute(
                    "select s.source_answer_id from world_project_item_source s "
                    "where s.workspace_id=%s and s.item_id=%s and s.source_answer_id is not null",
                    (self.workspace_id, item_id),
                ).fetchall()
            }
            added = sorted(set(self._answer_ids(kept)) - {str(a) for a in held})
            ordinal = self.connection.execute(
                "select count(*) as n from world_project_item_source s "
                "where s.workspace_id=%s and s.item_id=%s",
                (self.workspace_id, item_id),
            ).fetchone()["n"]
            if ordinal + len(added) > MAX_SOURCES:
                raise InvalidProjectContext(f"an item is drawn from at most {MAX_SOURCES} records")
            for offset, answer_id in enumerate(added):
                self._source(item_id, ordinal + offset, answer_id=answer_id)
            self._advance(project)
            return self._written(project_id, item_id)

    @_retrying
    def review_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, base_revision: int, accept: bool
    ) -> tuple[int, ItemView | None]:
        """Decide a suggestion: accepted, it joins the context; rejected, its words are erased.

        Returns the project's new revision and the accepted item, or None for a rejection, which
        leaves nothing to show.
        """
        with self._writing():
            project = self._project_row(project_id, lock=True, owner=True)
            self._require_base(project, base_revision)
            item = self._item_row(project, item_id)
            if item["status"] != ItemStatus.PROPOSED:
                raise ProjectItemNotCurrent("only a suggestion waiting for review is decided")
            if accept:
                self.connection.execute(
                    "update world_project_item set status='active', reviewed_at=now(), "
                    "changed_at=now() where workspace_id=%s and world_id=%s and item_id=%s",
                    (self.workspace_id, self.world_id, item_id),
                )
            else:
                self.connection.execute(
                    "update world_project_item set status='withdrawn', withdrawn_at=now(), "
                    "withdrawn_reason='rejected', changed_at=now() "
                    "where workspace_id=%s and world_id=%s and item_id=%s",
                    (self.workspace_id, self.world_id, item_id),
                )
            revision = self._advance(project)
            return revision, (self._written(project_id, item_id) if accept else None)

    @_retrying
    def resolve_item(
        self, project_id: uuid.UUID, item_id: uuid.UUID, *, base_revision: int
    ) -> ItemView:
        """Close a goal, question or task that is done: readable still, out of the context."""
        with self._writing():
            project = self._project_row(project_id, lock=True, owner=True)
            self._require_base(project, base_revision)
            item = self._item_row(project, item_id)
            if ItemKind(item["kind"]) not in _RESOLVABLE:
                raise InvalidProjectContext("a goal, a question or a task is resolved")
            if item["status"] != ItemStatus.ACTIVE:
                raise ProjectItemNotCurrent("only an active item is resolved")
            self.connection.execute(
                "update world_project_item set status='resolved', resolved_at=now(), "
                "changed_at=now() where workspace_id=%s and world_id=%s and item_id=%s",
                (self.workspace_id, self.world_id, item_id),
            )
            self._advance(project)
            return self._written(project_id, item_id)

    @_retrying
    def delete_item(self, project_id: uuid.UUID, item_id: uuid.UUID) -> int:
        """Delete one item and every copy of it, erasing their words; the project's new revision.

        Never blocked by a stale base, for the reason :meth:`delete_project` gives.
        """
        with self._writing():
            project = self._project_row(project_id, lock=True, owner=True)
            self._item_row(project, item_id)
            self.connection.execute(
                "update world_project_item set status='withdrawn', withdrawn_at=now(), "
                "withdrawn_reason='deleted', changed_at=now() "
                "where workspace_id=%s and world_id=%s and item_id=%s",
                (self.workspace_id, self.world_id, item_id),
            )
            return self._advance(project)

    # -- writes: sharing -----------------------------------------------------------------------

    @_retrying
    def share(
        self,
        project_id: uuid.UUID,
        *,
        base_revision: int,
        project: bool,
        item_ids: Sequence[uuid.UUID],
    ) -> tuple[int, tuple[ShareView, ...]]:
        """Open shares of the project and of listed items; what is already shared stays so.

        Another person of the workspace reads a shared project's title, binding and counts, and a
        shared item's current words and world records, while both shares are open.
        """
        wanted = sorted(set(item_ids))
        if not project and not wanted:
            raise InvalidProjectContext("a share names the project, items, or both")
        if len(wanted) > MAX_ITEMS:
            raise InvalidProjectContext(f"a share names at most {MAX_ITEMS} items")
        with self._writing():
            row = self._project_row(project_id, lock=True, owner=True)
            self._require_base(row, base_revision)
            # Held until the shares are written, in id order after the project: a deletion
            # reaching one of them through a copied source waits, and then closes the share too.
            statuses = {
                r["item_id"]: r["status"]
                for r in self.connection.execute(
                    "select i.item_id, i.status::text as status from world_project_item i "
                    "where i.workspace_id=%s and i.world_id=%s and i.project_id=%s "
                    "and i.item_id = any(%s) and i.status<>'withdrawn' "
                    "order by i.item_id for share",
                    (self.workspace_id, self.world_id, project_id, wanted),
                ).fetchall()
            }
            if set(statuses) != set(wanted):
                raise UnknownProjectContext("no such item in this project")
            if ItemStatus.PROPOSED in statuses.values():
                raise ProjectItemNotCurrent("a suggestion is shared once it is accepted")
            changed = False
            for item_id in ([None] if project else []) + list(wanted):
                inserted = self.connection.execute(
                    "insert into world_project_share (workspace_id,project_id,item_id,shared_by) "
                    "select %s,%s,%s,%s where not exists (select 1 from world_project_share s "
                    "where s.workspace_id=%s and s.project_id=%s "
                    "and s.item_id is not distinct from %s and s.withdrawn_at is null)",
                    (
                        self.workspace_id,
                        project_id,
                        item_id,
                        self.actor_id,
                        self.workspace_id,
                        project_id,
                        item_id,
                    ),
                ).rowcount
                changed = changed or inserted > 0
            revision = self._advance(row) if changed else int(row["revision"])
            shares = self.connection.execute(
                "select s.share_id, s.item_id, s.shared_at from world_project_share s "
                "where s.workspace_id=%s and s.project_id=%s and s.withdrawn_at is null "
                "order by s.shared_at, s.share_id",
                (self.workspace_id, project_id),
            ).fetchall()
        return revision, tuple(
            ShareView(share_id=s["share_id"], item_id=s["item_id"], shared_at=s["shared_at"])
            for s in shares
        )

    @_retrying
    def stop_share(self, project_id: uuid.UUID, share_id: uuid.UUID) -> int:
        """Stop one share; the next read by anyone else no longer shows what it opened."""
        with self._writing():
            row = self._project_row(project_id, lock=True, owner=True)
            stopped = self.connection.execute(
                "update world_project_share set withdrawn_at=now() where workspace_id=%s "
                "and project_id=%s and share_id=%s and withdrawn_at is null",
                (self.workspace_id, project_id, share_id),
            ).rowcount
            if not stopped:
                raise UnknownProjectContext("no such open share")
            return self._advance(row)
