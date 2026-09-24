"""The worlds a workspace holds: each registered with its kind, and how many of a kind it may hold.

A world is a row of ``world_identity`` (migration 0099) before any world table names it: its id,
its kind, the workspace that owns it, how it came to exist and when. Every table with a
``world_id`` column carries a foreign key to that row, so a world cannot come into existence as a
side effect of a write, and every creation passes :func:`register_world`, which is where the count
policy is checked. The export ledger ``world_package_export`` is the one table with rows that name
no world: a training dataset export keeps its dataset package id in ``world_id``, and 0099 keys
only the ledger's world exports.

**Kinds.** :data:`WORLD_KINDS` is the one list. ``personal-source`` is a world composed from the
workspace's own photographs and other personal sources; ``authored-starter`` is a
source-independent authored world that starts empty. Migration 0099's CHECK restates the list,
because a database cannot import this module, and ``tests/test_worlds.py`` holds the two equal.

**How many.** :data:`WORLD_COUNT_POLICY` is read from ``world-count-policy.v1.json`` and states,
for every kind, the most worlds of that kind one workspace may hold, or ``null`` for a kind the
policy does not count. Version 1 allows one personal-source world. The limit is checked by the
server when a world is created, under the workspace lock every world writer takes, and a creation
past it is refused as :class:`WorldLimitReached`. Worlds that already exist are never removed by a
policy: the policy governs creation. Allowing several personal-source worlds is another version of
the policy; what else it needs is in ``docs/saved-world-entry.md``.

**The personal-source world.** Code that means "the world composed from this workspace's own
sources" asks :func:`resolve_personal_source_world`, which answers from the registry and refuses by
name when there is none or when there are several. It never answers with a fixed id. A request
that names its world does not need it: routes take a required ``world_id``.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from exulanica.canonical import sha256_of_canonical
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.workspace_lock import lock_workspace

__all__ = [
    "AUTHORED_STARTER",
    "PERSONAL_SOURCE",
    "WORLD_COUNT_POLICY",
    "WORLD_KINDS",
    "NoPersonalSourceWorld",
    "SeveralPersonalSourceWorlds",
    "UnknownWorldKind",
    "WorldCountPolicy",
    "WorldIdentity",
    "WorldKind",
    "WorldKindConflict",
    "WorldLimitReached",
    "current_world_count_policy",
    "ensure_personal_source_world",
    "load_world_count_policy",
    "new_world_id",
    "register_world",
    "require_world",
    "resolve_personal_source_world",
    "workspace_world",
    "workspace_worlds",
    "world_kind",
]

#: The kind of a world composed from the workspace's own photographs and other personal sources.
PERSONAL_SOURCE: Final = "personal-source"
#: The kind of a source-independent authored world that starts empty.
AUTHORED_STARTER: Final = "authored-starter"

#: The migration that admitted both kinds, by file stem.
_ADMITTED_BY: Final = "0099_a_world_is_registered_before_it_holds_anything"

#: The longest world id the registry and every world table accept.
WORLD_ID_MAX_LENGTH: Final = 200


@dataclass(frozen=True, slots=True)
class WorldKind:
    """One kind of world: its stored name, what it is, how a new one's id is spelled."""

    name: str
    summary: str
    #: The prefix a newly created world of this kind is given, followed by a random UUID. An id is
    #: an identity and nothing more: nothing reads a world's kind from its id, and a world
    #: registered before 0099 keeps whatever id it had.
    id_prefix: str
    #: The migration whose CHECK first listed this kind, by file stem.
    admitted_by: str


#: Every kind of world, in the order migration 0099's CHECK lists them.
WORLD_KINDS: Final[tuple[WorldKind, ...]] = (
    WorldKind(
        PERSONAL_SOURCE,
        "a world composed from the workspace's own photographs and other personal sources",
        "world:personal:",
        _ADMITTED_BY,
    ),
    WorldKind(
        AUTHORED_STARTER,
        "a source-independent authored world that starts empty",
        "world:authored:",
        _ADMITTED_BY,
    ),
)


class UnknownWorldKind(ValueError):
    """A kind no entry of :data:`WORLD_KINDS` names."""


class WorldLimitReached(Exception):
    """A creation that would give the workspace more worlds of its kind than the policy allows."""

    code: Final = "world_limit_reached"

    def __init__(self, kind: str, limit: int, policy: WorldCountPolicy) -> None:
        self.kind = kind
        self.limit = limit
        self.policy = policy
        super().__init__(
            f"this workspace already holds {limit} {kind} "
            f"world{'' if limit == 1 else 's'}, the most {policy.policy_id} version "
            f"{policy.version} allows"
        )


class WorldKindConflict(Exception):
    """A world id already registered with a different kind."""

    code: Final = "world_kind_conflict"


class NoPersonalSourceWorld(LookupError):
    """The workspace holds no personal-source world."""

    code: Final = "no_personal_source_world"


class SeveralPersonalSourceWorlds(LookupError):
    """The workspace holds more than one personal-source world, so none is "the" one."""

    code: Final = "several_personal_source_worlds"

    def __init__(self, world_ids: tuple[str, ...]) -> None:
        self.world_ids = world_ids
        super().__init__(
            f"this workspace holds {len(world_ids)} personal-source worlds; name the one meant"
        )


def world_kind(name: str) -> WorldKind:
    """The kind of that name, or a refusal naming it."""
    for kind in WORLD_KINDS:
        if kind.name == name:
            return kind
    raise UnknownWorldKind(f"no world kind is named {name!r}")


def new_world_id(kind: str) -> str:
    """A fresh identity for a world of ``kind``."""
    return f"{world_kind(kind).id_prefix}{uuid.uuid4()}"


@dataclass(frozen=True, slots=True)
class WorldCountPolicy:
    """The most worlds of each kind one workspace may hold, as one versioned document."""

    policy_id: str
    version: int
    limits: Mapping[str, int | None]
    #: SHA-256 of the canonical document, recorded on every world created under it.
    sha256: str

    def limit(self, kind: str) -> int | None:
        """The most worlds of ``kind`` one workspace may hold; ``None`` when it sets no limit."""
        world_kind(kind)
        if kind not in self.limits:
            raise UnknownWorldKind(f"{self.policy_id} version {self.version} states no {kind!r}")
        return self.limits[kind]

    def reference(self) -> dict[str, Any]:
        return {"policy_id": self.policy_id, "version": self.version, "sha256": self.sha256}


def load_world_count_policy(path: Path) -> WorldCountPolicy:
    """Read and check a policy document: every kind stated exactly once, each limit at least 1."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if set(document) != {"policy_id", "version", "scope", "limits"}:
        raise ValueError(f"{path.name} must state policy_id, version, scope and limits only")
    if document["scope"] != "workspace":
        raise ValueError(f"{path.name} counts per {document['scope']!r}; only workspace is read")
    if not isinstance(document["version"], int) or document["version"] < 1:
        raise ValueError(f"{path.name} needs a positive integer version")
    limits = document["limits"]
    stated = set(limits)
    known = {kind.name for kind in WORLD_KINDS}
    if stated != known:
        raise ValueError(
            f"{path.name} must state a limit for exactly the kinds {sorted(known)}, "
            f"not {sorted(stated)}"
        )
    for kind, limit in limits.items():
        if limit is not None and (type(limit) is not int or limit < 1):
            raise ValueError(f"{path.name} limits {kind} to {limit!r}; a limit is null or >= 1")
    return WorldCountPolicy(
        policy_id=document["policy_id"],
        version=document["version"],
        limits=MappingProxyType(dict(limits)),
        sha256=sha256_of_canonical(document).hex(),
    )


#: The policy the server checks every world creation against.
WORLD_COUNT_POLICY: WorldCountPolicy = load_world_count_policy(
    Path(__file__).with_name("world-count-policy.v1.json")
)


def current_world_count_policy() -> WorldCountPolicy:
    """The policy in force, read when it is asked for rather than bound when a module loads."""
    return WORLD_COUNT_POLICY


@dataclass(frozen=True, slots=True)
class WorldIdentity:
    world_id: str
    kind: str
    provenance: Mapping[str, Any]
    created_by: uuid.UUID | None
    created_at: dt.datetime


_COLUMNS: Final = "world_id,kind,provenance,created_by,created_at"


def _identity(row: Mapping[str, Any]) -> WorldIdentity:
    return WorldIdentity(
        world_id=row["world_id"],
        kind=row["kind"],
        provenance=MappingProxyType(dict(row["provenance"])),
        created_by=row["created_by"],
        created_at=row["created_at"],
    )


def workspace_worlds(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> tuple[WorldIdentity, ...]:
    """Every world the workspace holds, oldest first."""
    with connection.cursor(row_factory=dict_row) as cursor:
        rows = cursor.execute(
            f"select {_COLUMNS} from world_identity where workspace_id=%s "
            "order by created_at,world_id",
            (workspace_id,),
        ).fetchall()
    return tuple(_identity(row) for row in rows)


def workspace_world(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
) -> WorldIdentity | None:
    """One registered world, or ``None`` for an id the workspace does not hold."""
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            f"select {_COLUMNS} from world_identity where workspace_id=%s and world_id=%s",
            (workspace_id, world_id),
        ).fetchone()
    return None if row is None else _identity(row)


def require_world(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str
) -> WorldIdentity:
    """The registered world a request names, or :class:`UnknownWorldResource`.

    Another workspace's world and an id nobody registered are the same refusal: row-level
    security hides the first, so neither answer can tell a caller that a world exists elsewhere.
    """
    world = workspace_world(connection, workspace_id, world_id)
    if world is None:
        raise UnknownWorldResource("no such world")
    return world


def register_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    world_id: str,
    kind: str,
    created_by: uuid.UUID,
    reason: str,
) -> WorldIdentity:
    """Create a world of ``kind``, or return the registration already made for that id.

    The count policy is read here, when the world is created, and :class:`WorldLimitReached`
    refuses a creation past its limit. An id already registered with the same kind is returned
    unchanged, so a retried creation is not a second world; with another kind it is refused as
    :class:`WorldKindConflict`. ``reason`` names the path that created the world and is kept in
    its provenance with the policy version the creation was checked against.
    """
    world_kind(kind)
    clean_id = world_id.strip()
    if not 1 <= len(clean_id) <= WORLD_ID_MAX_LENGTH or clean_id != world_id:
        raise ValueError(
            f"a world id is 1 to {WORLD_ID_MAX_LENGTH} characters with no surrounding space"
        )
    if not reason.strip():
        raise ValueError("a world is registered with the reason it was created")
    policy = current_world_count_policy()
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        existing = workspace_world(connection, workspace_id, world_id)
        if existing is not None:
            if existing.kind != kind:
                raise WorldKindConflict(
                    f"world {world_id!r} is registered as {existing.kind}, not {kind}"
                )
            return existing
        limit = policy.limit(kind)
        with connection.cursor(row_factory=dict_row) as cursor:
            if limit is not None:
                held = cursor.execute(
                    "select count(*) as held from world_identity where workspace_id=%s and kind=%s",
                    (workspace_id, kind),
                ).fetchone()
                assert held is not None
                if held["held"] >= limit:
                    raise WorldLimitReached(kind, limit, policy)
            row = cursor.execute(
                "insert into world_identity (workspace_id,world_id,kind,provenance,created_by) "
                f"values (%s,%s,%s,%s,%s) returning {_COLUMNS}",
                (
                    workspace_id,
                    world_id,
                    kind,
                    Jsonb({"origin": "created", "reason": reason, "policy": policy.reference()}),
                    created_by,
                ),
            ).fetchone()
        assert row is not None
        return _identity(row)


def resolve_personal_source_world(connection: psycopg.Connection, workspace_id: uuid.UUID) -> str:
    """The id of the workspace's personal-source world.

    The one place code that means "the world composed from this workspace's own sources" learns
    which world that is. Refuses with :class:`NoPersonalSourceWorld` when the workspace holds
    none, and with :class:`SeveralPersonalSourceWorlds` when a policy allowed more than one, so a
    caller that needs one of several has to be told which.
    """
    worlds = tuple(
        world.world_id
        for world in workspace_worlds(connection, workspace_id)
        if world.kind == PERSONAL_SOURCE
    )
    if not worlds:
        raise NoPersonalSourceWorld("this workspace holds no personal-source world")
    if len(worlds) > 1:
        raise SeveralPersonalSourceWorlds(worlds)
    return worlds[0]


def ensure_personal_source_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    created_by: uuid.UUID,
    reason: str,
) -> str:
    """The personal-source world, created first when the workspace holds none.

    Resolution and creation happen under one workspace lock, so two concurrent callers on an
    empty workspace create one world between them rather than one each.
    """
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        try:
            return resolve_personal_source_world(connection, workspace_id)
        except NoPersonalSourceWorld:
            return register_world(
                connection,
                workspace_id,
                world_id=new_world_id(PERSONAL_SOURCE),
                kind=PERSONAL_SOURCE,
                created_by=created_by,
                reason=reason,
            ).world_id
