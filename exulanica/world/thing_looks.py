"""The look a thing wears in a version: one its world's owner chose, or one its crossing brought.

A look is chosen beside a thing, never in it: what a thing is and does is its kind's and the
society's, and nothing a society reads holds a look (:mod:`exulanica.things.looks`). A choice names
a shipped look by key, version and digest, one the thing library serves
(:mod:`exulanica.world.thing_library`), whose body plan is the thing's kind's, so a renderer can
always fetch and draw it. Choices are appended (migration 0156) and the latest per thing is the one
worn; a thing with none wears its kind's first look.

*   :func:`check_crossing_look` holds a look to the shipped library, or to the looks a workspace
    keeps when asked on that workspace's connection, and to the thing's kind, so a door refuses an
    arrival before it writes;
*   :func:`record_crossing_look` writes the look a visitor's crossing brought, on the minute's own
    connection, for an arrival the minute bound as arrived; one arrival records one look however
    often it is handed over;
*   :func:`look_choices` reads the newest choice per thing of a version that it may still wear, as
    ``exulanica.thing-look-choices/v1``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from exulanica.world.errors import InvalidThingPlacement, UnknownWorldResource
from exulanica.world.placed_things import ThingKindReference, shipped_kind
from exulanica.world.thing_library import shipped_looks
from exulanica.world.thing_store import admitted_look_by_digest

__all__ = [
    "LOOK_CHOICES_PROFILE",
    "THING_LOOK_CODES",
    "LookReference",
    "ThingLookRefused",
    "check_crossing_look",
    "look_choices",
    "record_crossing_look",
]

LOOK_CHOICES_PROFILE: Final = "exulanica.thing-look-choices/v1"
#: Why a look may not be worn: the library holds no such look, its body plan is not the kind's, or
#: the thing's kind is not shipped at the digest it names.
THING_LOOK_CODES: Final = ("look_not_shipped", "look_unfit", "thing_kind_not_shipped")


class ThingLookRefused(ValueError):
    """A look a thing may not wear, named by one of :data:`THING_LOOK_CODES`."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class LookReference:
    """A shipped look by key, version and the digest of its document; or a look the workspace
    keeps, by the digest alone (``source`` ``workspace``, its key and version None)."""

    look: str | None
    version: int | None
    sha256: str
    source: str = "shipped"

    def document(self) -> dict[str, Any]:
        if self.source == "workspace":
            return {"sha256": self.sha256, "source": "workspace"}
        return {"look": self.look, "sha256": self.sha256, "version": self.version}


def _workspace_named(raw: object) -> str | None:
    """``raw`` as ``{source: workspace, sha256}``, its digest, or None for any other shape."""
    if not isinstance(raw, Mapping) or set(raw) != {"source", "sha256"}:
        return None
    if raw["source"] != "workspace" or type(raw["sha256"]) is not str:
        return None
    return raw["sha256"]


def _named(raw: object, key: str) -> tuple[str, int, str] | None:
    """``raw`` as ``{<key>, version, sha256}``, or None for any other shape."""
    if not isinstance(raw, Mapping) or set(raw) != {key, "version", "sha256"}:
        return None
    name, version, sha256 = raw[key], raw["version"], raw["sha256"]
    if type(name) is not str or type(version) is not int or type(sha256) is not str:
        return None
    return name, version, sha256


def check_crossing_look(
    kind: Mapping[str, Any],
    look: Mapping[str, Any],
    *,
    connection: Any = None,
    workspace_id: uuid.UUID | None = None,
) -> LookReference:
    """The look a thing of ``kind`` may wear, held to the shipped library, or, named by its digest
    alone (``{source: workspace, sha256}``), to the looks ``workspace_id`` keeps and has not
    withdrawn, read on ``connection``; and either to the kind's body plan; or
    :class:`ThingLookRefused`. With no connection it reads only the shipped catalogs, and a
    workspace's look is refused ``look_not_shipped``."""
    named_kind = _named(kind, "kind")
    try:
        if named_kind is None:
            raise InvalidThingPlacement("a thing names its kind by key, version and digest")
        shipped = shipped_kind(ThingKindReference(*named_kind))
    except InvalidThingPlacement as exc:
        raise ThingLookRefused("thing_kind_not_shipped", str(exc)) from exc
    digest = _workspace_named(look)
    if digest is not None:
        kept = (
            None
            if connection is None or workspace_id is None
            else admitted_look_by_digest(connection, workspace_id, digest)
        )
        if kept is None:
            raise ThingLookRefused(
                "look_not_shipped", "this workspace keeps no look with that digest"
            )
        if kept.body_plan != shipped.plan:
            raise ThingLookRefused(
                "look_unfit",
                f"a {kept.body_plan} look does not fit a {shipped.plan} {shipped.kind}",
            )
        return LookReference(None, None, kept.sha256, "workspace")
    named_look = _named(look, "look")
    worn = None if named_look is None else shipped_looks().get(named_look[:2])
    if worn is None or named_look is None or worn.sha256 != named_look[2]:
        raise ThingLookRefused(
            "look_not_shipped", "the library holds no look at that key, version and digest"
        )
    if worn.body_plan != shipped.plan:
        raise ThingLookRefused(
            "look_unfit", f"a {worn.body_plan} look does not fit a {shipped.plan} {shipped.kind}"
        )
    return LookReference(worn.look, worn.version, worn.sha256)


def record_crossing_look(
    connection: Any,
    *,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    thing_id: uuid.UUID,
    crossing_id: uuid.UUID,
    kind: Mapping[str, Any],
    look: Mapping[str, Any],
) -> LookReference:
    """Record the look a visitor's crossing brought, for an arrival the minute bound as arrived:
    checked as :func:`check_crossing_look` checks it, written on ``connection`` in the caller's
    transaction, once per crossing (a repeat writes nothing)."""
    worn = check_crossing_look(kind, look, connection=connection, workspace_id=workspace_id)
    connection.execute(
        "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,look,"
        "look_version,look_sha256,chosen_by,crossing_id,source) "
        "values (%s,%s,%s,%s,%s,%s,%s,'crossing',%s,%s) "
        "on conflict (workspace_id,world_id,version_id,crossing_id) "
        "where crossing_id is not null do nothing",
        (
            workspace_id,
            world_id,
            version_id,
            thing_id,
            worn.look,
            worn.version,
            bytes.fromhex(worn.sha256),
            crossing_id,
            worn.source,
        ),
    )
    return worn


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def look_choices(
    connection: Any,
    workspace_id: uuid.UUID,
    world_id: str,
    version_id: uuid.UUID,
    *,
    thing_id: str | None = None,
) -> dict[str, Any]:
    """The look each thing of a version wears, in thing id order: its newest choice that still
    names a look to wear, a shipped look the library still serves at that digest or one the
    workspace still keeps and has not withdrawn (any other choice is passed by, and the one before
    it read). A thing whose worn look is a shipped one is listed in ``looks``, as every reader of
    this profile reads it; one whose worn look is the workspace's own, named by its digest alone, in
    ``workspace_looks``, which a reader that does not know it leaves alone (the thing then wears its
    kind's first look there). ``thing_id`` reads one thing's alone. The database picks the one row
    per thing, so a read stays one row per thing however many choices were appended. An absent
    version, or another workspace's, is :class:`~exulanica.world.errors.UnknownWorldResource`."""
    held = connection.execute(
        "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
        "and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if held is None:
        raise UnknownWorldResource("no such alternate version")
    served = [look for _key, look in sorted(shipped_looks().items())]
    passed: list[int] = []
    while True:
        rows = connection.execute(
            "select distinct on (c.thing_id) c.choice_id,c.thing_id,c.placed_id,c.look,"
            "c.look_version,c.look_sha256,c.chosen_by,c.chosen_at,c.source "
            "from world_thing_look c "
            "left join look_version v on c.source='workspace' and v.workspace_id=c.workspace_id "
            "and v.sha256=encode(c.look_sha256,'hex') "
            "left join look_withdrawal w on w.workspace_id=v.workspace_id and w.key=v.key "
            "and w.version=v.version "
            "where c.workspace_id=%s and c.world_id=%s and c.version_id=%s "
            "and (%s::uuid is null or c.thing_id=%s::uuid) "
            "and not (c.choice_id = any(%s::bigint[])) "
            "and case when c.source='workspace' then v.key is not null and w.key is null "
            "else (c.look,c.look_version,c.look_sha256) in "
            "(select * from unnest(%s::text[],%s::integer[],%s::bytea[])) end "
            "order by c.thing_id, c.choice_id desc",
            (
                workspace_id,
                world_id,
                version_id,
                thing_id,
                thing_id,
                passed,
                [look.look for look in served],
                [look.version for look in served],
                [bytes.fromhex(look.sha256) for look in served],
            ),
        ).fetchall()
        # A kept look whose stored document the reader now refuses is no look to wear either.
        unread = [
            row["choice_id"]
            for row in rows
            if row["source"] == "workspace"
            and admitted_look_by_digest(connection, workspace_id, bytes(row["look_sha256"]).hex())
            is None
        ]
        if not unread:
            break
        passed.extend(unread)
    shipped, own = [], []
    for row in sorted(rows, key=lambda row: str(row["thing_id"])):
        reference = LookReference(
            row["look"],
            row["look_version"],
            bytes(row["look_sha256"]).hex(),
            row["source"],
        )
        entry = {
            "thing_id": str(row["thing_id"]),
            "placed_id": row["placed_id"],
            "look": reference.document(),
            "chosen_by": row["chosen_by"],
            "chosen_at": _instant(row["chosen_at"]),
        }
        (own if row["source"] == "workspace" else shipped).append(entry)
    return {
        "profile": LOOK_CHOICES_PROFILE,
        "version_id": str(version_id),
        "looks": shipped,
        **({"workspace_looks": own} if own else {}),
    }
