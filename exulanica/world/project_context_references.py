"""What a project item points at in the world, and what has become of it since.

A project keeps the ids of records the world's own authorities hold: an accepted edit, an applied
appearance, a control receipt, a simulated event, an open appearance preview, a Companion answer.
It copies none of them. Every reference is checked when an item is written, so a person cannot
keep a pointer to nothing, and resolved again at every read, so what a reader is shown is what the
authority says now: a deleted source makes a reference unavailable, a withdrawn answer withdrawn,
an id that names nothing missing, and ids that disagree with the record a mismatch. The kinds are
a closed list in code; a request never chooses what is resolved or how.

The fields of each kind carry the names the Companion's action receipts use for the same ids: the
operation is the route that performed it, keyed as ``exulanica.api.permissions`` keys routes, and
the ids are the authority's own. A receipt says more than a reference keeps (what an edit did and
to which object, a proposal's and a preview's status, an appearance revision), so a client builds
a reference from a receipt by taking the fields its kind lists and nothing else.

Two ways to ask. :meth:`ReferenceResolver.check` is what a write asks: whether each record exists,
agrees with its ids and still stands on an available source. It reads rows and takes no lock
beyond them, because a write here holds its project's row lock and must never wait for the
workspace lock a society read takes (``docs/project-context.md``, locking).
:meth:`ReferenceResolver.resolve` is what a read asks, and adds the society's own current
authorization of the input a simulated event consumed, which is the check the society's events
read applies, lock included.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

import psycopg

from exulanica.world.repository import OPEN_PREVIEW_LIFETIME
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_repository import SocietyRepository

__all__ = [
    "CONTROL_OPERATIONS",
    "EDIT_OPERATIONS",
    "MAX_REFERENCES",
    "OUTCOME_KINDS",
    "REFERENCE_PROFILE",
    "SIMULATED_KINDS",
    "STYLE_OPERATIONS",
    "WORLD_PLANE",
    "InvalidReference",
    "Reference",
    "ReferenceKind",
    "ReferenceResolver",
    "ReferenceState",
    "Resolution",
    "parse_reference",
    "parse_references",
]

REFERENCE_PROFILE: Final = "exulanica.project-reference/v1"

#: The most records one revision of an item points at. An arrangement applied in one transaction
#: records one edit per object it adds, and the reviewed arrangements add fewer than this.
MAX_REFERENCES: Final = 8


class ReferenceKind(StrEnum):
    WORLD_EDIT = "world_edit"
    STYLE_VERSION = "style_version"
    SOCIETY_CONTROL = "society_control"
    SOCIETY_EVENT = "society_event"
    STYLE_PREVIEW = "style_preview"
    COMPANION_ANSWER = "companion_answer"


class ReferenceState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    WITHDRAWN = "withdrawn"
    MISSING = "missing"
    MISMATCH = "mismatch"


#: Records of the shared world, which any reader holding world.read may already open. Another
#: person shown a shared item sees these; a Companion answer is its asker's own and is never shown.
WORLD_PLANE: Final = frozenset(
    {
        ReferenceKind.WORLD_EDIT,
        ReferenceKind.STYLE_VERSION,
        ReferenceKind.SOCIETY_CONTROL,
        ReferenceKind.SOCIETY_EVENT,
        ReferenceKind.STYLE_PREVIEW,
    }
)

#: What a decision may name: accepted operations. What an event may name: simulated records.
OUTCOME_KINDS: Final = frozenset(
    {ReferenceKind.WORLD_EDIT, ReferenceKind.STYLE_VERSION, ReferenceKind.SOCIETY_CONTROL}
)
SIMULATED_KINDS: Final = frozenset({ReferenceKind.SOCIETY_EVENT})

#: The routes whose success appends a row to the version's edit history. Each is a declared
#: write route (``tests/test_project_context_assembly.py``).
EDIT_OPERATIONS: Final = frozenset(
    {
        "POST /world/versions/{version_id}/arrangements/apply",
        "POST /world/versions/{version_id}/compositions/apply",
        "POST /world/versions/{version_id}/compositions/photo-point-maps/apply",
        "POST /world/versions/{version_id}/environment-instances",
        "POST /world/versions/{version_id}/environment-instances/undo",
        "POST /world/versions/{version_id}/environment-instances/{instance_id}/move",
        "POST /world/versions/{version_id}/environment-instances/{instance_id}/remove",
        "POST /world/versions/{version_id}/objects",
        "POST /world/versions/{version_id}/objects/undo",
        "POST /world/versions/{version_id}/objects/{object_id}/behaviour",
        "POST /world/versions/{version_id}/objects/{object_id}/move",
        "POST /world/versions/{version_id}/objects/{object_id}/remove",
        "POST /world/versions/{version_id}/things",
        "POST /world/versions/{version_id}/things/undo",
        "POST /world/versions/{version_id}/things/{thing_id}/move",
        "POST /world/versions/{version_id}/things/{thing_id}/remove",
    }
)
#: The routes whose success records an appearance version.
STYLE_OPERATIONS: Final = frozenset(
    {"POST /world/styles/previews/{preview_id}/apply", "POST /world/styles/rollback"}
)
#: The control routes, and the receipt kind each records (``world_society_control_event``).
_CONTROL_RECEIPTS: Final = MappingProxyType(
    {
        "PUT /world/versions/{version_id}/society/control": "configured",
        "POST /world/versions/{version_id}/society/control/steps": "manual_step",
    }
)
CONTROL_OPERATIONS: Final = frozenset(_CONTROL_RECEIPTS)

_SHA256: Final = re.compile(r"^[0-9a-f]{64}$")


class InvalidReference(ValueError):
    """A reference that is not of a known kind, or not in its kind's shape. Never quotes a value."""


# -- shapes -------------------------------------------------------------------------------------


def _world(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidReference("world_id is a world id of 1 to 200 characters")
    return value


def _uuid(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise InvalidReference(f"{name} is a UUID")
    try:
        return str(uuid.UUID(value))
    except ValueError:
        raise InvalidReference(f"{name} is a UUID") from None


def _count(value: object, name: str, *, least: int) -> int:
    if type(value) is not int or value < least:
        raise InvalidReference(f"{name} is a whole number of at least {least}")
    return value


def _digest(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise InvalidReference(f"{name} is a lowercase SHA-256 in hex")
    return value


def _operation(value: object, allowed: frozenset[str]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise InvalidReference("operation is not a route that records this kind of reference")
    return value


def _optional(value: object, parse: Callable[[object], Any]) -> Any:
    return None if value is None else parse(value)


def _object_id(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        raise InvalidReference("object_id is an object id of 1 to 200 characters")
    return value


#: Each kind's fields, and how each is read. Every field is required in a reference; a field a
#: kind states as optional is present with ``null``.
_SHAPES: Final[Mapping[ReferenceKind, Mapping[str, Callable[[object], Any]]]] = MappingProxyType(
    {
        ReferenceKind.WORLD_EDIT: {
            "operation": lambda v: _operation(v, EDIT_OPERATIONS),
            "world_id": _world,
            "version_id": lambda v: _uuid(v, "version_id"),
            "edit_id": lambda v: _uuid(v, "edit_id"),
            "edit_seq": lambda v: _count(v, "edit_seq", least=1),
            "result_state_sha256": lambda v: _digest(v, "result_state_sha256"),
        },
        ReferenceKind.STYLE_VERSION: {
            "operation": lambda v: _operation(v, STYLE_OPERATIONS),
            "world_id": _world,
            "style_version_id": lambda v: _uuid(v, "style_version_id"),
            "preview_id": lambda v: _optional(v, lambda x: _uuid(x, "preview_id")),
            "proposal_id": lambda v: _optional(v, lambda x: _uuid(x, "proposal_id")),
        },
        ReferenceKind.SOCIETY_CONTROL: {
            "operation": lambda v: _operation(v, CONTROL_OPERATIONS),
            "world_id": _world,
            "version_id": lambda v: _uuid(v, "version_id"),
            "revision": lambda v: _count(v, "revision", least=1),
            "tick": lambda v: _optional(v, lambda x: _count(x, "tick", least=0)),
            "state_sha256": lambda v: _optional(v, lambda x: _digest(x, "state_sha256")),
        },
        ReferenceKind.SOCIETY_EVENT: {
            "world_id": _world,
            "version_id": lambda v: _uuid(v, "version_id"),
            "event_id": lambda v: _uuid(v, "event_id"),
            "tick": lambda v: _count(v, "tick", least=1),
            "input_seq": lambda v: _optional(v, lambda x: _count(x, "input_seq", least=1)),
            "object_id": lambda v: _optional(v, _object_id),
            "edit_seq": lambda v: _optional(v, lambda x: _count(x, "edit_seq", least=1)),
            "edit_id": lambda v: _optional(v, lambda x: _uuid(x, "edit_id")),
        },
        ReferenceKind.STYLE_PREVIEW: {
            "world_id": _world,
            "preview_id": lambda v: _uuid(v, "preview_id"),
        },
        ReferenceKind.COMPANION_ANSWER: {
            "answer_id": lambda v: _uuid(v, "answer_id"),
        },
    }
)


@dataclass(frozen=True, slots=True)
class Reference:
    """One record, by the ids its authority keeps. ``fields`` is in canonical form."""

    kind: ReferenceKind
    fields: Mapping[str, Any]

    def document(self) -> dict[str, Any]:
        """The stored and served form: the kind and every field, ``null`` included."""
        return {"kind": self.kind.value, **self.fields}

    def world_plane(self) -> bool:
        return self.kind in WORLD_PLANE


def parse_reference(value: object) -> Reference:
    """Read one reference, refusing an unknown kind, a missing or extra field, or a bad value."""
    if not isinstance(value, Mapping):
        raise InvalidReference("a reference is an object naming its kind")
    try:
        kind = ReferenceKind(value.get("kind"))
    except ValueError:
        raise InvalidReference("a reference names a kind this server resolves") from None
    shape = _SHAPES[kind]
    given = set(value) - {"kind"}
    if given != set(shape):
        raise InvalidReference(f"a {kind.value} reference names exactly {sorted(shape)}")
    fields = {name: parse(value[name]) for name, parse in shape.items()}
    if kind is ReferenceKind.SOCIETY_CONTROL:
        stepped = _CONTROL_RECEIPTS[fields["operation"]] == "manual_step"
        if stepped != (fields["tick"] is not None and fields["state_sha256"] is not None) or (
            not stepped and (fields["tick"] is not None or fields["state_sha256"] is not None)
        ):
            raise InvalidReference("a step names its tick and state; a configuration names neither")
    if kind is ReferenceKind.SOCIETY_EVENT and (fields["edit_seq"] is None) != (
        fields["edit_id"] is None
    ):
        raise InvalidReference("an edit is named by both its sequence and its id, or neither")
    return Reference(kind, MappingProxyType(fields))


def parse_references(values: Iterable[object]) -> tuple[Reference, ...]:
    """Read an item's references, at most :data:`MAX_REFERENCES`, none named twice."""
    references = tuple(parse_reference(value) for value in values)
    if len(references) > MAX_REFERENCES:
        raise InvalidReference(f"an item names at most {MAX_REFERENCES} records")
    documents = {repr(sorted(reference.document().items())) for reference in references}
    if len(documents) != len(references):
        raise InvalidReference("an item names each record once")
    return references


# -- resolution ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Resolution:
    """What a reference's authority says now. ``code`` is the authority's own refusal code for an
    unavailable record; ``detail`` a stable word for where a record is in its own lifecycle (a
    preview ``open`` or ``applied``, an answer ``superseded``)."""

    state: ReferenceState
    code: str | None = None
    detail: str | None = None


_AVAILABLE: Final = Resolution(ReferenceState.AVAILABLE)
_MISSING: Final = Resolution(ReferenceState.MISSING)
_MISMATCH: Final = Resolution(ReferenceState.MISMATCH, "reference_mismatch")
_INVALIDATED: Final = Resolution(ReferenceState.UNAVAILABLE, "invalidated_source_version")
_SOCIETY_UNAVAILABLE: Final = Resolution(ReferenceState.UNAVAILABLE, "unavailable_society_input")


class ReferenceResolver:
    """Resolves references for one reader in one workspace.

    ``input_authorizer`` is the society's authorization of one input document, as the society
    routes bind it to their connection and session; without it a simulated event cannot be
    authorized and reads as unavailable, which is what the society's own read answers then.
    """

    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        actor_id: uuid.UUID,
        *,
        input_authorizer: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.actor_id = actor_id
        self.input_authorizer = input_authorizer

    def check(self, references: Sequence[Reference]) -> tuple[Resolution, ...]:
        """What a write asks: existence, agreement and source, reading rows and nothing more."""
        return self._resolve(references, authorize=False)

    def resolve(self, references: Sequence[Reference]) -> tuple[Resolution, ...]:
        """What a read asks: :meth:`check`, and the society's current authorization."""
        return self._resolve(references, authorize=True)

    def _resolve(
        self, references: Sequence[Reference], *, authorize: bool
    ) -> tuple[Resolution, ...]:
        found: dict[int, Resolution] = {}
        by_kind: dict[ReferenceKind, list[tuple[int, Reference]]] = {}
        for index, reference in enumerate(references):
            by_kind.setdefault(reference.kind, []).append((index, reference))
        resolvers: Mapping[ReferenceKind, Callable[[list[tuple[int, Reference]]], None]] = {
            ReferenceKind.WORLD_EDIT: lambda group: found.update(self._edits(group)),
            ReferenceKind.STYLE_VERSION: lambda group: found.update(self._styles(group)),
            ReferenceKind.SOCIETY_CONTROL: lambda group: found.update(self._controls(group)),
            ReferenceKind.SOCIETY_EVENT: lambda group: found.update(
                self._events(group, authorize=authorize)
            ),
            ReferenceKind.STYLE_PREVIEW: lambda group: found.update(self._previews(group)),
            ReferenceKind.COMPANION_ANSWER: lambda group: found.update(self._answers(group)),
        }
        for kind, group in by_kind.items():
            resolvers[kind](group)
        return tuple(found[index] for index in range(len(references)))

    def _invalidated(self, versions: Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
        """Which ``(world_id, version_id)`` pairs stand on a source a deletion invalidated.

        The structural plane's own record, as the object repository reads it: nothing here
        writes an invalidation.
        """
        pairs = sorted(set(versions))
        if not pairs:
            return set()
        rows = self.connection.execute(
            "select v.world_id, v.version_id::text as version_id from world_alternate_version v "
            "where v.workspace_id=%s and (v.world_id, v.version_id::text) in "
            "(select * from unnest(%s::text[], %s::text[])) and exists ("
            "select 1 from world_structure_invalidation i where i.workspace_id=v.workspace_id "
            "and i.world_id=v.world_id and i.snapshot_id=v.source_snapshot_id)",
            (self.workspace_id, [w for w, _ in pairs], [v for _, v in pairs]),
        ).fetchall()
        return {(row["world_id"], row["version_id"]) for row in rows}

    def _edits(self, group: list[tuple[int, Reference]]) -> dict[int, Resolution]:
        rows = self.connection.execute(
            "select e.edit_id::text as edit_id, e.world_id, e.version_id::text as version_id, "
            "e.edit_seq, e.result_state_sha256 from world_alternate_version_edit e "
            "where e.workspace_id=%s and e.edit_id = any(%s::uuid[])",
            (self.workspace_id, [r.fields["edit_id"] for _, r in group]),
        ).fetchall()
        edits = {row["edit_id"]: row for row in rows}
        invalidated = self._invalidated(
            (row["world_id"], row["version_id"]) for row in edits.values()
        )
        resolved: dict[int, Resolution] = {}
        for index, reference in group:
            row = edits.get(reference.fields["edit_id"])
            if row is None:
                resolved[index] = _MISSING
            elif (
                row["world_id"],
                row["version_id"],
                row["edit_seq"],
                row["result_state_sha256"],
            ) != (
                reference.fields["world_id"],
                reference.fields["version_id"],
                reference.fields["edit_seq"],
                reference.fields["result_state_sha256"],
            ):
                resolved[index] = _MISMATCH
            elif (row["world_id"], row["version_id"]) in invalidated:
                resolved[index] = _INVALIDATED
            else:
                resolved[index] = _AVAILABLE
        return resolved

    def _styles(self, group: list[tuple[int, Reference]]) -> dict[int, Resolution]:
        rows = self.connection.execute(
            "select v.version_id::text as version_id, v.world_id, "
            "v.applied_from_proposal_id::text as proposal_id from world_style_version v "
            "where v.workspace_id=%s and v.version_id = any(%s::uuid[])",
            (self.workspace_id, [r.fields["style_version_id"] for _, r in group]),
        ).fetchall()
        versions = {row["version_id"]: row for row in rows}
        previews = {
            row["preview_id"]: row
            for row in self.connection.execute(
                "select p.preview_id::text as preview_id, p.world_id, "
                "p.proposal_id::text as proposal_id, p.status from world_style_preview p "
                "where p.workspace_id=%s and p.preview_id = any(%s::uuid[])",
                (
                    self.workspace_id,
                    [r.fields["preview_id"] for _, r in group if r.fields["preview_id"]],
                ),
            ).fetchall()
        }
        resolved: dict[int, Resolution] = {}
        for index, reference in group:
            fields = reference.fields
            row = versions.get(fields["style_version_id"])
            if row is None:
                resolved[index] = _MISSING
                continue
            agrees = row["world_id"] == fields["world_id"] and (
                fields["proposal_id"] is None or row["proposal_id"] == fields["proposal_id"]
            )
            if fields["preview_id"] is not None:
                preview = previews.get(fields["preview_id"])
                agrees = agrees and (
                    preview is not None
                    and preview["world_id"] == fields["world_id"]
                    and preview["status"] == "applied"
                    and (
                        fields["proposal_id"] is None
                        or preview["proposal_id"] == fields["proposal_id"]
                    )
                )
            resolved[index] = _AVAILABLE if agrees else _MISMATCH
        return resolved

    def _controls(self, group: list[tuple[int, Reference]]) -> dict[int, Resolution]:
        resolved: dict[int, Resolution] = {}
        invalidated = self._invalidated(
            (r.fields["world_id"], r.fields["version_id"]) for _, r in group
        )
        for index, reference in group:
            fields = reference.fields
            receipt = _CONTROL_RECEIPTS[fields["operation"]]
            row = self.connection.execute(
                "select c.document->>'tick_to' as tick, c.document->>'state_sha256' as state "
                "from world_society_control_event c join world_society s "
                "on s.workspace_id=c.workspace_id and s.society_id=c.society_id "
                "where c.workspace_id=%s and s.world_id=%s and s.version_id=%s "
                "and c.document->>'kind'=%s and (c.document->>'revision')::bigint=%s "
                "and (%s::bigint is null or (c.document->>'tick_to')::bigint=%s::bigint) "
                "and (%s::text is null or c.document->>'state_sha256'=%s::text) "
                "order by c.event_seq limit 1",
                (
                    self.workspace_id,
                    fields["world_id"],
                    fields["version_id"],
                    receipt,
                    fields["revision"],
                    fields["tick"],
                    fields["tick"],
                    fields["state_sha256"],
                    fields["state_sha256"],
                ),
            ).fetchone()
            if row is None:
                resolved[index] = _MISSING
            elif (fields["world_id"], fields["version_id"]) in invalidated:
                resolved[index] = _SOCIETY_UNAVAILABLE
            else:
                resolved[index] = _AVAILABLE
        return resolved

    def _events(
        self, group: list[tuple[int, Reference]], *, authorize: bool
    ) -> dict[int, Resolution]:
        rows = self.connection.execute(
            "select e.event_id::text as event_id, s.world_id, s.version_id::text as version_id, "
            "e.tick, e.document->>'input_seq' as input_seq from world_society_event e "
            "join world_society s on s.workspace_id=e.workspace_id and s.society_id=e.society_id "
            "where e.workspace_id=%s and e.event_id = any(%s::uuid[])",
            (self.workspace_id, [r.fields["event_id"] for _, r in group]),
        ).fetchall()
        events = {row["event_id"]: row for row in rows}
        invalidated = self._invalidated(
            (row["world_id"], row["version_id"]) for row in events.values()
        )
        refused: dict[tuple[str, str], Resolution] = {}
        if authorize:
            for world_id, version_id in sorted(
                {(row["world_id"], row["version_id"]) for row in events.values()} - invalidated
            ):
                refusal = self._society_refusal(world_id, uuid.UUID(version_id))
                if refusal is not None:
                    refused[(world_id, version_id)] = refusal
        resolved: dict[int, Resolution] = {}
        for index, reference in group:
            fields = reference.fields
            row = events.get(fields["event_id"])
            if row is None:
                resolved[index] = _MISSING
                continue
            input_seq = None if row["input_seq"] is None else int(row["input_seq"])
            if (row["world_id"], row["version_id"], row["tick"]) != (
                fields["world_id"],
                fields["version_id"],
                fields["tick"],
            ) or (fields["input_seq"] is not None and fields["input_seq"] != input_seq):
                resolved[index] = _MISMATCH
            elif (row["world_id"], row["version_id"]) in invalidated:
                resolved[index] = _SOCIETY_UNAVAILABLE
            else:
                resolved[index] = refused.get((row["world_id"], row["version_id"]), _AVAILABLE)
        return resolved

    def _society_refusal(self, world_id: str, version_id: uuid.UUID) -> Resolution | None:
        """The society's own answer to whether its current input may be read, or None if it may.

        The same authorization the society's state and events reads apply; it takes the
        workspace lock those reads take, which is why only :meth:`resolve` asks it.
        """
        society = SocietyRepository(
            self.connection,
            self.workspace_id,
            world_id=world_id,
            input_authorizer=self.input_authorizer,
        )
        try:
            society.snapshot(version_id)
        except UnavailableSocietyInput:
            return _SOCIETY_UNAVAILABLE
        except UnknownSociety:
            return _MISSING
        return None

    def _previews(self, group: list[tuple[int, Reference]]) -> dict[int, Resolution]:
        rows = self.connection.execute(
            "select p.preview_id::text as preview_id, p.world_id, "
            "case when p.status='open' and p.created_at <= now() - %s::interval "
            "then 'expired' else p.status end as status from world_style_preview p "
            "where p.workspace_id=%s and p.preview_id = any(%s::uuid[])",
            (
                OPEN_PREVIEW_LIFETIME,
                self.workspace_id,
                [r.fields["preview_id"] for _, r in group],
            ),
        ).fetchall()
        previews = {row["preview_id"]: row for row in rows}
        resolved: dict[int, Resolution] = {}
        for index, reference in group:
            row = previews.get(reference.fields["preview_id"])
            if row is None:
                resolved[index] = _MISSING
            elif row["world_id"] != reference.fields["world_id"]:
                resolved[index] = _MISMATCH
            else:
                resolved[index] = Resolution(ReferenceState.AVAILABLE, detail=row["status"])
        return resolved

    def _answers(self, group: list[tuple[int, Reference]]) -> dict[int, Resolution]:
        """Only the reader's own answers resolve: another person's are missing, never withdrawn."""
        rows = self.connection.execute(
            "select a.answer_id::text as answer_id, a.status::text as status "
            "from companion_answer a where a.workspace_id=%s and a.actor_id=%s "
            "and a.answer_id = any(%s::uuid[])",
            (self.workspace_id, self.actor_id, [r.fields["answer_id"] for _, r in group]),
        ).fetchall()
        answers = {row["answer_id"]: row["status"] for row in rows}
        resolved: dict[int, Resolution] = {}
        for index, reference in group:
            status = answers.get(reference.fields["answer_id"])
            if status is None:
                resolved[index] = _MISSING
            elif status == "withdrawn":
                resolved[index] = Resolution(ReferenceState.WITHDRAWN)
            else:
                resolved[index] = Resolution(
                    ReferenceState.AVAILABLE, detail=None if status == "active" else status
                )
        return resolved
