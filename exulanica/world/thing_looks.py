"""The look a thing wears in a version: one its world's owner chose, or one its crossing brought.

A look is chosen beside a thing, never in it: what a thing is and does is its kind's and the
society's, and nothing a society reads holds a look (:mod:`exulanica.things.looks`). A choice names
a shipped look by key, version and digest, one the thing library serves
(:mod:`exulanica.world.thing_library`), whose body plan is the thing's kind's, so a renderer can
always fetch and draw it. Choices are appended (migration 0156) and the latest per thing is the one
worn; a thing with none wears its kind's first look.

*   :func:`check_crossing_look` holds a look to the shipped library and to the thing's kind,
    reading nothing but the shipped catalogs, so a door refuses an arrival before it writes;
*   :func:`record_crossing_look` writes the look a visitor's crossing brought, on the minute's own
    connection, for an arrival the minute bound as arrived; one arrival records one look however
    often it is handed over;
*   :func:`look_choices` reads the latest choice per thing of a version, as
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
    """A shipped look by key, version and the digest of its document."""

    look: str
    version: int
    sha256: str

    def document(self) -> dict[str, Any]:
        return {"look": self.look, "sha256": self.sha256, "version": self.version}


def _named(raw: object, key: str) -> tuple[str, int, str] | None:
    """``raw`` as ``{<key>, version, sha256}``, or None for any other shape."""
    if not isinstance(raw, Mapping) or set(raw) != {key, "version", "sha256"}:
        return None
    name, version, sha256 = raw[key], raw["version"], raw["sha256"]
    if type(name) is not str or type(version) is not int or type(sha256) is not str:
        return None
    return name, version, sha256


def check_crossing_look(kind: Mapping[str, Any], look: Mapping[str, Any]) -> LookReference:
    """The look a thing of ``kind`` may wear, held to the shipped library and to the kind's body
    plan, or :class:`ThingLookRefused`. Reads only the shipped catalogs."""
    named_kind = _named(kind, "kind")
    try:
        if named_kind is None:
            raise InvalidThingPlacement("a thing names its kind by key, version and digest")
        shipped = shipped_kind(ThingKindReference(*named_kind))
    except InvalidThingPlacement as exc:
        raise ThingLookRefused("thing_kind_not_shipped", str(exc)) from exc
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
    worn = check_crossing_look(kind, look)
    connection.execute(
        "insert into world_thing_look(workspace_id,world_id,version_id,thing_id,look,"
        "look_version,look_sha256,chosen_by,crossing_id) "
        "values (%s,%s,%s,%s,%s,%s,%s,'crossing',%s) "
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
        ),
    )
    return worn


def _instant(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def look_choices(
    connection: Any, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> dict[str, Any]:
    """The latest look choice per thing of a version, in thing id order; an absent version, or
    another workspace's, is :class:`~exulanica.world.errors.UnknownWorldResource`."""
    held = connection.execute(
        "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
        "and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()
    if held is None:
        raise UnknownWorldResource("no such alternate version")
    rows = connection.execute(
        "select distinct on (thing_id) thing_id,placed_id,look,look_version,look_sha256,"
        "chosen_by,chosen_at from world_thing_look "
        "where workspace_id=%s and world_id=%s and version_id=%s "
        "order by thing_id, choice_id desc",
        (workspace_id, world_id, version_id),
    ).fetchall()
    return {
        "profile": LOOK_CHOICES_PROFILE,
        "version_id": str(version_id),
        "looks": [
            {
                "thing_id": str(row["thing_id"]),
                "placed_id": row["placed_id"],
                "look": LookReference(
                    row["look"], row["look_version"], bytes(row["look_sha256"]).hex()
                ).document(),
                "chosen_by": row["chosen_by"],
                "chosen_at": _instant(row["chosen_at"]),
            }
            for row in rows
        ],
    }
