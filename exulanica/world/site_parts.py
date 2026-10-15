"""The parts a site world was made with, and a person's changes to them: moved, turned or removed.

A site world (a garden, a farm made from a world kind) is read back from its receipt as records
(:func:`~exulanica.world.composers.site_plan.records`), each with an identity its rule derives from
its owner and ordinal, never from its position (:mod:`exulanica.grammar.subjects`). A person may
change three kinds of them: a building (``site.structure``), a fixture standing in a garden area
(``site.fixture`` owned by a zone) and an area (``site.area``, a pond or a field). Paths, zones,
walls, rooms and the fixtures inside a building are not changed on their own: a building carries
its walls, rooms and room fixtures with it.

**A change is stored as an element override that names the part** (``part:<identity>``), in the
version's edit log like every authored edit, so undo and redo are the log's. Its transform is the
part's new pose in the region frame placed things use (``x_mm`` east, ``z_mm`` south of the
site's south-west corner) and its turn from how it was made, a whole number of quarter turns
counterclockwise seen from above (``yaw_microradians`` one of :data:`QUARTER_TURNS`): every part is
an axis-aligned rectangle, so no other turn can be drawn or walked. A removal is ``suppressed``.
The receipt is never changed, so the world as made still reads from it alone.

**The world as it stands** is the records with the version's changes applied
(:func:`apply_changes`), named by :func:`changes_sha256`, which keys what the kind worker makes
from them. A change is checked here against the records alone (:func:`check_change`: inside its own
zone, clear of every other part, path and pond, and the records' own rules); whether people still
reach every place is the walking place's, made from the changed records in the worker.

Pure: no connection and no store.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.errors import InvalidRecordError
from exulanica.grammar.grammars.site import check_site_records
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteFixtureRecord,
    SiteLoggiaRecord,
    SiteOpening,
    SitePathRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)
from exulanica.world.errors import ThingLandingRefused
from exulanica.world.objects import ElementOverride, Transform

__all__ = [
    "LAND_WORDS",
    "LAND_WORDS_OTHERWISE",
    "PART_CODES",
    "PART_PREFIX",
    "QUARTER_TURNS",
    "MadePart",
    "PartChange",
    "PartChangeRefused",
    "apply_changes",
    "changeable_parts",
    "changes_document",
    "changes_from_document",
    "changes_of",
    "changes_sha256",
    "check_change",
    "part_identity",
    "part_override",
    "people_of_part",
    "refused_people_words",
]

#: The prefix of an element override's id that names a made part rather than a snapshot element.
PART_PREFIX: Final = "part:"
#: The turns a made part may take, as a transform's yaw: none, then one to three quarter turns
#: counterclockwise seen from above (north to west), as a fixture's ``yaw_quarter_turns`` counts.
QUARTER_TURNS: Final = (0, 1_570_796, 3_141_593, 4_712_389)
_PROFILE: Final = "exulanica.site-part-changes/v1"
#: Every code a refused part change carries (:class:`PartChangeRefused`). Stable: codes are added,
#: never renamed.
PART_CODES: Final = frozenset(
    {
        "part_unknown",
        "part_not_changeable",
        "part_outside_zone",
        "part_blocked",
        "part_records_refused",
        "part_strands_people",
        "part_houses_people",
        "parts_not_served",
        # A world on land: the land grader's own codes (LAND_WORDS).
        "landform_cut_too_deep",
        "landform_corridor_too_steep",
        "landform_basin_over_locked",
        "landform_water_spills",
        "landform_unreachable",
        "landform_near_out_of_bounds",
        "landform_cascade_crossed",
        "landform_invalid",
    }
)
#: The sentence a person reads when the land of a world on land cannot take a part where a change
#: leaves it, by the land grader's own code (:mod:`exulanica.grammar.landform`). The grader's own
#: detail goes in ``where``.
LAND_WORDS: Final = {
    "landform_cut_too_deep": "Not here: the ground there is too steep to level for it.",
    "landform_corridor_too_steep": "Not here: the path to it would be too steep to walk.",
    "landform_basin_over_locked": "Not here: a pond cannot be dug over a path or another terrace.",
    "landform_water_spills": "Not here: water would spill out there.",
    "landform_unreachable": "Not here: people could no longer walk to it from the entry.",
    "landform_cascade_crossed": "Not here: it would cross the falling water.",
    "landform_near_out_of_bounds": (
        "Not here: the ground there would have to rise or fall further than this land allows."
    ),
}
#: What a land code the grader adds later is said with until it has its own sentence.
LAND_WORDS_OTHERWISE: Final = "Not here: the land cannot take it there."
#: A quarter turn counterclockwise: the side a door faced, to the side it faces after.
_TURNED: Final = {"north": "west", "west": "south", "south": "east", "east": "north"}

Kind = Literal["building", "fixture", "area"]


class PartChangeRefused(ThingLandingRefused):
    """A made part would be moved, turned or removed where the world does not take it: out of its
    own zone, onto another part, a path or water, or so that people no longer reach a place. It is
    answered as a placed thing's refused landing is (422, its ``code``, ``where`` and a sentence a
    person reads)."""


@dataclass(frozen=True, slots=True)
class PartChange:
    """One part's change: removed, or standing with its centre at ``centre_mm`` (east, north in
    the site's frame) turned ``quarter_turns`` from how it was made."""

    identity: str
    removed: bool
    centre_mm: tuple[int, int] | None = None
    quarter_turns: int = 0

    def document(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "removed": self.removed,
            "centre_mm": None if self.centre_mm is None else list(self.centre_mm),
            "quarter_turns": self.quarter_turns,
        }


@dataclass(frozen=True, slots=True)
class MadePart:
    """A part a person may change, as it stands: what it is, its words, its garden area, its
    centre (east, north), its size along east and north as it is turned, and its turn."""

    identity: str
    kind: Kind
    part_key: str
    label: str
    zone_identity: str
    zone_label: str
    centre_mm: tuple[int, int]
    size_mm: tuple[int, int]
    quarter_turns: int

    def document(self) -> dict[str, Any]:
        return {
            "part_id": self.identity,
            "kind": self.kind,
            "part_key": self.part_key,
            "label": self.label,
            "zone_id": self.zone_identity,
            "zone_label": self.zone_label,
            "centre_mm": list(self.centre_mm),
            "size_mm": list(self.size_mm),
            "quarter_turns": self.quarter_turns,
        }


# -- stored form ---------------------------------------------------------------------------------


def part_identity(element_id: str) -> str | None:
    """The part an override's id names, or None for an override of a snapshot element."""
    return element_id[len(PART_PREFIX) :] if element_id.startswith(PART_PREFIX) else None


def part_override(change: PartChange) -> ElementOverride:
    """The element override that stores ``change``: its pose in the region frame (south is minus
    north), or its removal."""
    element_id = f"{PART_PREFIX}{change.identity}"
    if change.removed:
        return ElementOverride(element_id=element_id, suppressed=True)
    if change.centre_mm is None:
        raise ValueError("a part that stays needs its centre")
    east, north = change.centre_mm
    return ElementOverride(
        element_id=element_id,
        suppressed=False,
        transform=Transform(
            x_mm=east,
            y_mm=0,
            z_mm=-north,
            yaw_microradians=QUARTER_TURNS[change.quarter_turns % 4],
            scale_milli=1_000,
        ),
    )


def changes_of(overrides: Iterable[ElementOverride]) -> tuple[PartChange, ...]:
    """The part changes among a version's overrides, by identity. An override of a part that is
    neither suppressed nor stands at a quarter turn, at its own size and on the ground, is refused:
    no route writes one."""
    changes = []
    for override in overrides:
        identity = part_identity(override.element_id)
        if identity is None:
            continue
        if override.suppressed:
            changes.append(PartChange(identity, True))
            continue
        transform = override.transform
        if (
            transform is None
            or transform.yaw_microradians not in QUARTER_TURNS
            or transform.scale_milli != 1_000
            or transform.y_mm != 0
        ):
            raise ValueError(f"part {identity} is changed in a way no part can stand")
        changes.append(
            PartChange(
                identity,
                False,
                (transform.x_mm, -transform.z_mm),
                QUARTER_TURNS.index(transform.yaw_microradians),
            )
        )
    return tuple(sorted(changes, key=lambda change: change.identity))


def changes_document(changes: Sequence[PartChange]) -> list[dict[str, Any]]:
    """Changes as plain data, in identity order: what the kind worker is handed."""
    return [change.document() for change in sorted(changes, key=lambda c: c.identity)]


def changes_from_document(document: Sequence[Mapping[str, Any]]) -> tuple[PartChange, ...]:
    """The changes :func:`changes_document` wrote."""
    return tuple(
        PartChange(
            str(item["identity"]),
            bool(item["removed"]),
            None
            if item["centre_mm"] is None
            else (int(item["centre_mm"][0]), int(item["centre_mm"][1])),
            int(item["quarter_turns"]),
        )
        for item in document
    )


def changes_sha256(changes: Sequence[PartChange]) -> str:
    """The digest of a version's part changes, or the empty string for none, so whatever is keyed
    by the receipt and these keeps its key for a world nobody changed."""
    if not changes:
        return ""
    return sha256_of_canonical({"profile": _PROFILE, "changes": changes_document(changes)}).hex()


# -- the parts -----------------------------------------------------------------------------------


def _words(key: str, uses: Mapping[str, Any] | None) -> str:
    use = None if uses is None else uses.get(key)
    label = getattr(use, "label", "") if use is not None else ""
    return label or key.replace("_", " ")


def _fixture_size(record: SiteFixtureRecord) -> tuple[int, int]:
    if record.yaw_quarter_turns % 2 == 0:
        return record.width_mm, record.depth_mm
    return record.depth_mm, record.width_mm


def _box(record: object) -> tuple[int, int, int, int]:
    """A part's footprint, ``(x0, y0, x1, y1)`` east and north, as the place blocks it."""
    if isinstance(record, SiteFixtureRecord):
        along_x, along_y = _fixture_size(record)
        x0, y0 = record.x_mm - along_x // 2, record.y_mm - along_y // 2
        return x0, y0, x0 + along_x, y0 + along_y
    return (
        record.min_x_mm,  # type: ignore[attr-defined]
        record.min_y_mm,  # type: ignore[attr-defined]
        record.max_x_mm,  # type: ignore[attr-defined]
        record.max_y_mm,  # type: ignore[attr-defined]
    )


def _centre(record: object) -> tuple[int, int]:
    if isinstance(record, SiteFixtureRecord):
        return record.x_mm, record.y_mm
    x0, y0, x1, y1 = _box(record)
    return (x0 + x1) // 2, (y0 + y1) // 2


def _zone_of(record: object) -> str | None:
    if isinstance(record, SiteStructureRecord | SiteAreaRecord):
        return record.zone_identity
    if isinstance(record, SiteFixtureRecord):
        return record.owner_identity
    return None


def changeable_parts(
    records: Sequence[object], uses: Mapping[str, Any] | None = None
) -> tuple[MadePart, ...]:
    """Every part a person may change, in the records' order: each building, each fixture of a
    garden area and each area, with its words (its kind's where it gives them, else its key's)."""
    zones = {r.identity: r for r in records if isinstance(r, SiteZoneRecord)}
    parts = []
    for record in records:
        zone_id = _zone_of(record)
        if zone_id is None or zone_id not in zones:
            continue
        x0, y0, x1, y1 = _box(record)
        kind: Kind = (
            "building"
            if isinstance(record, SiteStructureRecord)
            else "fixture"
            if isinstance(record, SiteFixtureRecord)
            else "area"
        )
        parts.append(
            MadePart(
                identity=record.identity,  # type: ignore[attr-defined]
                kind=kind,
                part_key=record.part_key,  # type: ignore[attr-defined]
                label=_words(record.part_key, uses),  # type: ignore[attr-defined]
                zone_identity=zone_id,
                zone_label=_words(zones[zone_id].zone_key, uses),
                centre_mm=_centre(record),
                size_mm=(x1 - x0, y1 - y0),
                quarter_turns=record.yaw_quarter_turns
                if isinstance(record, SiteFixtureRecord)
                else 0,
            )
        )
    return tuple(parts)


def _part(records: Sequence[object], identity: str) -> object:
    """The changeable part of this identity, or refused by name: no such part, or one a person
    does not change on its own."""
    zones = {r.identity for r in records if isinstance(r, SiteZoneRecord)}
    for record in records:
        if getattr(record, "identity", None) != identity:
            continue
        if _zone_of(record) in zones:
            return record
        raise PartChangeRefused(
            "part_not_changeable",
            {"part_id": identity},
            "That part cannot be changed on its own: only a building, a fixture in a garden area "
            "or an area can.",
        )
    raise PartChangeRefused("part_unknown", {"part_id": identity}, "This world has no such part.")


# -- applying changes ----------------------------------------------------------------------------


class _Pose:
    """Points of a part turned about its made centre and carried to its new one, in whole
    millimetres: ``p -> centre' + R^k (p - centre)``."""

    def __init__(self, made: tuple[int, int], centre: tuple[int, int], turns: int) -> None:
        self.made = made
        self.centre = centre
        self.turns = turns % 4

    def point(self, x: int, y: int) -> tuple[int, int]:
        dx, dy = x - self.made[0], y - self.made[1]
        for _ in range(self.turns):
            dx, dy = -dy, dx
        return self.centre[0] + dx, self.centre[1] + dy

    def rectangle(self, x0: int, y0: int, x1: int, y1: int) -> tuple[int, int, int, int]:
        ax, ay = self.point(x0, y0)
        bx, by = self.point(x1, y1)
        return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)

    def facing(self, facing: str) -> str:
        for _ in range(self.turns):
            facing = _TURNED[facing]
        return facing


def _moved_rectangle(record: Any, pose: _Pose) -> Any:
    x0, y0, x1, y1 = pose.rectangle(
        record.min_x_mm, record.min_y_mm, record.max_x_mm, record.max_y_mm
    )
    return dataclasses.replace(record, min_x_mm=x0, min_y_mm=y0, max_x_mm=x1, max_y_mm=y1)


def _moved_wall(wall: SiteWallRecord, pose: _Pose) -> SiteWallRecord:
    """A wall carried and turned, written again from its lesser end, its openings' offsets turned
    where it now runs the other way (as the layout writes one)."""
    sx, sy = pose.point(wall.start_x_mm, wall.start_y_mm)
    ex, ey = pose.point(wall.end_x_mm, wall.end_y_mm)
    length = abs(ex - sx) + abs(ey - sy)
    reversed_ = (ex, ey) < (sx, sy)
    if reversed_:
        sx, sy, ex, ey = ex, ey, sx, sy
    openings = sorted(
        (
            SiteOpening(
                offset_mm=(length - o.offset_mm - o.width_mm) if reversed_ else o.offset_mm,
                width_mm=o.width_mm,
                height_mm=o.height_mm,
                kind=o.kind,
            )
            for o in wall.openings
        ),
        key=lambda opening: opening.offset_mm,
    )
    return dataclasses.replace(
        wall, start_x_mm=sx, start_y_mm=sy, end_x_mm=ex, end_y_mm=ey, openings=tuple(openings)
    )


def _moved_fixture(fixture: SiteFixtureRecord, pose: _Pose) -> SiteFixtureRecord:
    x, y = pose.point(fixture.x_mm, fixture.y_mm)
    return dataclasses.replace(
        fixture, x_mm=x, y_mm=y, yaw_quarter_turns=(fixture.yaw_quarter_turns + pose.turns) % 4
    )


def _carried(record: object, records: Sequence[object]) -> set[str]:
    """The identities a part carries with it: a building's walls, rooms (and the covered walk
    behind its arcade) and the fixtures in its rooms."""
    if not isinstance(record, SiteStructureRecord):
        return set()
    rooms = {
        r.identity
        for r in records
        if isinstance(r, SiteRoomRecord | SiteLoggiaRecord)
        and r.structure_identity == record.identity
    }
    walls = {
        r.identity
        for r in records
        if isinstance(r, SiteWallRecord) and r.owner_identity == record.identity
    }
    fixtures = {
        r.identity
        for r in records
        if isinstance(r, SiteFixtureRecord) and r.owner_identity in rooms
    }
    return rooms | walls | fixtures


def _apply(records: Sequence[object], change: PartChange) -> list[object]:
    part = _part(records, change.identity)
    carried = _carried(part, records) | {change.identity}
    if change.removed:
        return [r for r in records if getattr(r, "identity", None) not in carried]
    if change.centre_mm is None:
        raise ValueError("a part that stays needs its centre")
    pose = _Pose(_centre(part), change.centre_mm, change.quarter_turns)
    changed: list[object] = []
    for record in records:
        if getattr(record, "identity", None) not in carried:
            changed.append(record)
        elif isinstance(record, SiteFixtureRecord):
            changed.append(_moved_fixture(record, pose))
        elif isinstance(record, SiteWallRecord):
            changed.append(_moved_wall(record, pose))
        elif isinstance(record, SiteStructureRecord):
            moved = _moved_rectangle(record, pose)
            door_x, door_y = pose.point(record.door_x_mm, record.door_y_mm)
            changed.append(
                dataclasses.replace(
                    moved,
                    door_x_mm=door_x,
                    door_y_mm=door_y,
                    door_facing=pose.facing(record.door_facing),
                )
            )
        elif isinstance(record, SiteAreaRecord):
            moved = _moved_rectangle(record, pose)
            access_x, access_y = pose.point(record.access_x_mm, record.access_y_mm)
            changed.append(dataclasses.replace(moved, access_x_mm=access_x, access_y_mm=access_y))
        else:
            changed.append(_moved_rectangle(record, pose))
    return changed


def apply_changes(records: Sequence[object], changes: Sequence[PartChange]) -> tuple[object, ...]:
    """The records with every change applied, in identity order (each part is changed from how it
    was made, so the order changes nothing). A change naming a part the records do not hold, or one
    a person may not change, is refused by name."""
    changed = list(records)
    for change in sorted(changes, key=lambda c: c.identity):
        changed = _apply(changed, change)
    return tuple(changed)


# -- checking a change ---------------------------------------------------------------------------


def _overlaps(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check_change(
    changed: Sequence[object],
    identity: str,
    *,
    root_identity: str,
    uses: Mapping[str, Any] | None = None,
) -> None:
    """Hold one changed part, as it stands in ``changed``, to the records: inside its own garden
    area; clear of every building, every other fixture, every path, every pond and, for a building
    or an area, every other area (a fixture may stand in a field); and the records' own rules.
    Refused as :class:`PartChangeRefused` with a sentence naming what is in the way. A removal is
    checked by the place, not here."""
    part = next((r for r in changed if getattr(r, "identity", None) == identity), None)
    if part is None:
        return
    zones = {r.identity: r for r in changed if isinstance(r, SiteZoneRecord)}
    zone = zones[_zone_of(part)]  # type: ignore[index]
    box = _box(part)
    where = {"part_id": identity, "box_mm": list(box)}
    if not (
        zone.min_x_mm <= box[0]
        and zone.min_y_mm <= box[1]
        and box[2] <= zone.max_x_mm
        and box[3] <= zone.max_y_mm
    ):
        raise PartChangeRefused(
            "part_outside_zone",
            {**where, "zone_id": zone.identity},
            f"Not here: it would leave the {_words(zone.zone_key, uses)}.",
        )
    carried = _carried(part, changed) | {identity}
    for other in changed:
        if getattr(other, "identity", None) in carried:
            continue
        if isinstance(other, SitePathRecord | SiteStructureRecord):
            what = _words(other.part_key, uses)
        elif isinstance(other, SiteAreaRecord):
            if "water" not in other.roles and isinstance(part, SiteFixtureRecord):
                continue
            what = _words(other.part_key, uses)
        elif isinstance(other, SiteFixtureRecord):
            if other.owner_identity not in zones:
                continue
            what = _words(other.part_key, uses)
        else:
            continue
        if _overlaps(box, _box(other)):
            raise PartChangeRefused(
                "part_blocked",
                {**where, "blocked_by": getattr(other, "identity", "")},
                f"Not here: it would stand on the {what}.",
            )
    try:
        check_site_records(changed, root_identity=root_identity)
    except InvalidRecordError as exc:
        raise PartChangeRefused(
            "part_records_refused",
            {**where, "detail": str(exc)},
            "Not here: the world's layout cannot take it there.",
        ) from exc


# -- the people a part houses or employs ----------------------------------------------------------


def people_of_part(state: Mapping[str, Any], identity: str) -> list[tuple[str, str]]:
    """Who lives or works in a part, as ``(name, "lives" | "works")`` in the society's order, read
    from either engine that keeps residents (:func:`~exulanica.world.town_people.resident_of`): a
    society of things names a premises by its record subject, a living town by its destination."""
    from exulanica.world.town_people import resident_of

    subjects = {f"site.structure:{identity}", f"site.area:{identity}", f"site.fixture:{identity}"}
    destinations = {f"structure:{identity}", f"area:{identity}", f"fixture:{identity}"}

    def names(premises: Mapping[str, Any] | None) -> bool:
        if premises is None:
            return False
        return (
            premises.get("subject_id") in subjects or premises.get("destination_id") in destinations
        )

    found = []
    for person in state.get("inhabitants", ()):
        resident = resident_of(state, person)
        if resident is None:
            continue
        name = str(person.get("display_name") or "someone")
        if names(resident["home"]):
            found.append((name, "lives"))
        elif names(resident["job"]):
            found.append((name, "works"))
    return found


def refused_people_words(label: str, people: Sequence[tuple[str, str]]) -> str:
    """The sentence a removal refused for its people reads: who lives or works in it, up to three
    by name."""
    shown = [f"{name} {verb} there" for name, verb in people[:3]]
    more = len(people) - len(shown)
    said = shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]
    if more:
        said += f", and {more} more"
    return f"Not removed: {said}. The {label} can be moved instead."
