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
source-independent authored world that starts empty; ``generated`` is a source-independent world
the server generates from a reviewed recipe (:mod:`exulanica.world.world_recipes`). Each kind
states whether it is source-independent, which is what the style layer asks of a world. The
latest migration that lists the kinds in ``world_identity``'s CHECK restates the list, because a
database cannot import this module, and ``tests/test_worlds.py`` holds the two equal.

**How many.** :data:`WORLD_COUNT_POLICY` is read from ``world-count-policy.v3.json`` and states,
for every kind, the most worlds of that kind one workspace may hold, or ``null`` for a kind the
policy does not count, with the reason for each figure. Version 3 allows one personal-source
world, and for generated worlds states two chosen budgets in place of version 2's three: the
worlds a workspace may hold at once, and the tiles its generated worlds may come to in a day, each
with a figure for a signed-in person's workspace and one for a guest's, and each replaceable by a
deployment through the environment variable the policy names. Both are checked by the
server when a world is created, under the workspace lock every world writer takes, and a creation
past either is refused by name: :class:`WorldLimitReached`, or :class:`TileBudgetReached` with
the instant room returns. Worlds that already exist are never removed by a
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
import os
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
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
    "GENERATED",
    "PERSONAL_SOURCE",
    "WORLD_COUNT_POLICY",
    "WORLD_KINDS",
    "NoPersonalSourceWorld",
    "SeveralPersonalSourceWorlds",
    "TileBudgetReached",
    "UnknownWorldKind",
    "WorldCountPolicy",
    "WorldIdentity",
    "WorldKind",
    "WorldKindConflict",
    "WorldLimitReached",
    "WorldsReadOnly",
    "current_world_count_policy",
    "ensure_personal_source_world",
    "load_world_count_policy",
    "may_register_worlds",
    "new_world_id",
    "refuse_past_limit",
    "register_world",
    "require_world",
    "require_world_registration",
    "resolve_personal_source_world",
    "workspace_world",
    "workspace_worlds",
    "world_kind",
]

#: The kind of a world composed from the workspace's own photographs and other personal sources.
PERSONAL_SOURCE: Final = "personal-source"
#: The kind of a source-independent authored world that starts empty.
AUTHORED_STARTER: Final = "authored-starter"
#: The kind of a source-independent world the server generates from a reviewed recipe.
GENERATED: Final = "generated"

#: The migration that admitted the first two kinds, by file stem.
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
    #: Whether a world of this kind holds no personal source: nothing sourced may be activated in
    #: it and its composed topology is not overlaid, the style layer's rule for such a world.
    source_independent: bool
    #: Whether a world of this kind is drawn from generated tiles its own snapshot names, which
    #: its saved entry then declares for the page to draw (docs/adr/0027).
    draws_generated_tiles: bool = False
    #: Whether photographs may be attached to a saved world of this kind, and so composed into it.
    #: A generated world is never composed with photographs (docs/adr/0027).
    takes_photographs: bool = True


#: Every kind of world, in the order the kind CHECK lists them.
WORLD_KINDS: Final[tuple[WorldKind, ...]] = (
    WorldKind(
        PERSONAL_SOURCE,
        "a world composed from the workspace's own photographs and other personal sources",
        "world:personal:",
        _ADMITTED_BY,
        source_independent=False,
    ),
    WorldKind(
        AUTHORED_STARTER,
        "a source-independent authored world that starts empty",
        "world:authored:",
        _ADMITTED_BY,
        source_independent=True,
    ),
    WorldKind(
        GENERATED,
        "a source-independent world the server generates from a reviewed recipe",
        "world:generated:",
        "0118_a_world_is_generated_from_a_recipe",
        source_independent=True,
        draws_generated_tiles=True,
        takes_photographs=False,
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


class TileBudgetReached(WorldLimitReached):
    """A creation whose tiles would take the workspace past the tiles its generated worlds may
    come to in a day. A kind of :class:`WorldLimitReached`, so every caller that refuses the one
    refuses the other, by this one's own code and words."""

    code: Final = "tile_budget_reached"  # type: ignore[misc]

    def __init__(
        self,
        kind: str,
        limit: int,
        policy: WorldCountPolicy,
        *,
        asked: int,
        returns_at: dt.datetime,
    ) -> None:
        self.kind = kind
        self.limit = limit
        self.policy = policy
        self.asked = asked
        self.returns_at = returns_at
        at = returns_at.astimezone(dt.UTC)
        Exception.__init__(
            self,
            f"this workspace has made as many towns as it may in one day; it can make this one "
            f"from {at:%H:%M} UTC on {at.day} {at:%B} (its towns of the last day come to {limit} "
            f"tiles, the day's budget, and this one is {asked})",
        )


class WorldsReadOnly(Exception):
    """A deployment whose database role may read worlds and not register one (the judge stack)."""

    code: Final = "worlds_read_only"

    def __init__(self) -> None:
        super().__init__(
            "this deployment's database role cannot register a world, so no world is made here; "
            "nothing was generated or written"
        )


def may_register_worlds(connection: psycopg.Connection) -> bool:
    """Whether this connection's role may insert ``world_identity``, the first write every world
    creation makes. A probe of one grant: a role holding it may still lack a later table."""
    row = (
        connection.cursor(row_factory=dict_row)
        .execute("select has_table_privilege('world_identity', 'INSERT') as allowed")
        .fetchone()
    )
    return row is not None and bool(row["allowed"])


def require_world_registration(connection: psycopg.Connection) -> None:
    """Refuse a world creation before any of its work, where the role cannot register a world."""
    if not may_register_worlds(connection):
        raise WorldsReadOnly()


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
    #: The most worlds of a kind a guest's workspace may hold, where that differs (version 3).
    guest_limits: Mapping[str, int] = field(default_factory=dict)
    #: The tiles a workspace's worlds of one kind may come to in a window (version 3): the kind,
    #: the window in seconds, and the figure for a signed-in person's workspace and a guest's.
    tiles_a_day: Mapping[str, Any] | None = None
    #: The environment variable a deployment states each figure in, by the figure's path.
    environment: Mapping[str, str] = field(default_factory=dict)

    def _stated(
        self, path: str, figure: int | None, environ: Mapping[str, str] | None
    ) -> int | None:
        """``figure``, or the deployment's own where its variable states a whole number of at
        least 1; anything else in the variable is refused by name, never read as no bound."""
        name = self.environment.get(path)
        value = (os.environ if environ is None else environ).get(name, "").strip() if name else ""
        if not value:
            return figure
        if not value.isascii() or not value.isdigit() or int(value) < 1:
            raise ValueError(f"{name} must be a whole number of at least 1, not {value!r}")
        return int(value)

    def limit(
        self, kind: str, *, guest: bool = False, environ: Mapping[str, str] | None = None
    ) -> int | None:
        """The most worlds of ``kind`` one workspace may hold, a guest's where ``guest``; ``None``
        when the policy sets no limit."""
        world_kind(kind)
        if kind not in self.limits:
            raise UnknownWorldKind(f"{self.policy_id} version {self.version} states no {kind!r}")
        if guest and kind in self.guest_limits:
            return self._stated(f"guest_limits.{kind}", self.guest_limits[kind], environ)
        return self._stated(f"limits.{kind}", self.limits[kind], environ)

    def tiles_in_a_day(
        self, kind: str, *, guest: bool = False, environ: Mapping[str, str] | None = None
    ) -> tuple[int, int] | None:
        """The tiles a workspace's worlds of ``kind`` may come to and the window in seconds they
        are counted over, a guest's figure where ``guest``; ``None`` for a kind with no budget."""
        budget = self.tiles_a_day
        if budget is None or budget["kind"] != kind:
            return None
        path = "tiles_a_day.guest_limit" if guest else "tiles_a_day.limit"
        figure = self._stated(path, budget["guest_limit" if guest else "limit"], environ)
        assert figure is not None
        return figure, budget["window_seconds"]

    def reference(self) -> dict[str, Any]:
        return {"policy_id": self.policy_id, "version": self.version, "sha256": self.sha256}


def load_world_count_policy(path: Path) -> WorldCountPolicy:
    """Read and check a policy document: every kind stated exactly once, each limit at least 1,
    and from version 2 on a reason for each kind's figure."""
    document = json.loads(path.read_text(encoding="utf-8"))
    version = document.get("version")
    if type(version) is not int or version < 1:
        raise ValueError(f"{path.name} needs a positive integer version")
    keys = {"policy_id", "version", "scope", "limits"} | ({"reasons"} if version >= 2 else set())
    if version >= 3:
        keys |= {"guest_limits", "tiles_a_day", "environment"}
    if set(document) != keys:
        raise ValueError(f"{path.name} must state {', '.join(sorted(keys))} only")
    if document["scope"] != "workspace":
        raise ValueError(f"{path.name} counts per {document['scope']!r}; only workspace is read")
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
    reasons = document.get("reasons", {})
    reasoned = known | ({"tiles_a_day"} if version >= 3 else set())
    if "reasons" in keys and (
        set(reasons) != reasoned
        or any(not isinstance(text, str) or not text.strip() for text in reasons.values())
    ):
        raise ValueError(
            f"{path.name} must state a reason for exactly the kinds {sorted(known)}"
            + (" and for tiles_a_day" if version >= 3 else "")
        )
    guest_limits: dict[str, int] = {}
    tiles_a_day: dict[str, Any] | None = None
    environment: dict[str, str] = {}
    if version >= 3:
        whole = lambda value: type(value) is int and value >= 1  # noqa: E731
        guest_limits = dict(document["guest_limits"])
        if not set(guest_limits) <= {kind for kind, limit in limits.items() if limit is not None}:
            raise ValueError(f"{path.name} states a guest's limit for a kind it does not count")
        if not all(whole(limit) for limit in guest_limits.values()):
            raise ValueError(f"{path.name} states a guest's limit that is not a whole number >= 1")
        tiles_a_day = dict(document["tiles_a_day"])
        if set(tiles_a_day) != {"kind", "window_seconds", "limit", "guest_limit"} or (
            tiles_a_day["kind"] not in known
            or not all(
                whole(tiles_a_day[key]) for key in ("window_seconds", "limit", "guest_limit")
            )
        ):
            raise ValueError(
                f"{path.name} states tiles_a_day as a kind, a window in seconds and two figures"
            )
        environment = dict(document["environment"])
        figures = {f"limits.{kind}" for kind, limit in limits.items() if limit is not None}
        figures |= {f"guest_limits.{kind}" for kind in guest_limits}
        figures |= {"tiles_a_day.limit", "tiles_a_day.guest_limit"}
        if not set(environment) <= figures or not all(
            isinstance(name, str) and name.startswith("EXULANICA_") for name in environment.values()
        ):
            raise ValueError(
                f"{path.name} names an environment variable for something it does not state"
            )
    return WorldCountPolicy(
        policy_id=document["policy_id"],
        version=document["version"],
        limits=MappingProxyType(dict(limits)),
        sha256=sha256_of_canonical(document).hex(),
        guest_limits=MappingProxyType(guest_limits),
        tiles_a_day=None if tiles_a_day is None else MappingProxyType(tiles_a_day),
        environment=MappingProxyType(environment),
    )


#: The policy the server checks every world creation against.
WORLD_COUNT_POLICY: WorldCountPolicy = load_world_count_policy(
    Path(__file__).with_name("world-count-policy.v3.json")
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


def refuse_past_limit(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    kind: str,
    *,
    policy: WorldCountPolicy | None = None,
    guest: bool = False,
    tiles: int = 0,
) -> None:
    """Refuse a world of ``kind`` that would take the workspace past the count policy: the worlds
    it may hold, then, for a world of ``tiles`` tiles, the tiles its worlds may come to in a day.
    ``guest`` reads a guest's figures.

    :func:`register_world` asks it under the workspace lock, where its answer is the one that
    holds. A caller about to do expensive work before registering (generating a world) asks it
    first, unlocked: a cheap early refusal that may be stale, never a permission.

    The day's tiles are counted from the worlds the workspace made in the window and each one's
    receipt, every tile of a world made, baked already or not. Nothing here reads whether a world
    was later removed, so removing and making again cannot reopen the bound.
    """
    counted = current_world_count_policy() if policy is None else policy
    limit = counted.limit(kind, guest=guest)
    if limit is not None:
        with connection.cursor(row_factory=dict_row) as cursor:
            held = cursor.execute(
                "select count(*) as held from world_identity where workspace_id=%s and kind=%s",
                (workspace_id, kind),
            ).fetchone()
        assert held is not None
        if held["held"] >= limit:
            raise WorldLimitReached(kind, limit, counted)
    budget = counted.tiles_in_a_day(kind, guest=guest)
    if budget is None or tiles <= 0:
        return
    most, window = budget
    with connection.cursor(row_factory=dict_row) as cursor:
        made = cursor.execute(
            "select i.created_at, "
            "  coalesce(max(jsonb_array_length(r.receipt->'tiles')), 0) as tiles, "
            "  statement_timestamp() as now "
            "from world_identity i left join world_generation_receipt r "
            "  on r.workspace_id=i.workspace_id and r.world_id=i.world_id "
            "  and jsonb_typeof(r.receipt->'tiles')='array' "
            "where i.workspace_id=%s and i.kind=%s "
            "  and i.created_at > statement_timestamp() - make_interval(secs => %s) "
            "group by i.world_id, i.created_at order by i.created_at, i.world_id",
            (workspace_id, kind, window),
        ).fetchall()
    spent = sum(row["tiles"] for row in made)
    if spent + tiles <= most:
        return
    # Room returns when enough of the oldest worlds have left the window for this one to fit; a
    # world of more tiles than the whole budget never fits, and is told the window's length.
    returns_at = None
    for row in made:
        spent -= row["tiles"]
        if spent + tiles <= most:
            returns_at = row["created_at"] + dt.timedelta(seconds=window)
            break
    if returns_at is None:
        now = made[0]["now"] if made else dt.datetime.now(dt.UTC)
        returns_at = now + dt.timedelta(seconds=window)
    raise TileBudgetReached(kind, most, counted, asked=tiles, returns_at=returns_at)


def register_world(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    world_id: str,
    kind: str,
    created_by: uuid.UUID,
    reason: str,
    guest: bool = False,
    tiles: int = 0,
) -> WorldIdentity:
    """Create a world of ``kind``, or return the registration already made for that id.

    The count policy is read here, when the world is created, and :class:`WorldLimitReached`
    refuses a creation past its limit, as :class:`TileBudgetReached` does one whose ``tiles``
    pass the day's budget; ``guest`` reads a guest's figures. An id already registered with the
    same kind is returned
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
        refuse_past_limit(connection, workspace_id, kind, policy=policy, guest=guest, tiles=tiles)
        with connection.cursor(row_factory=dict_row) as cursor:
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
