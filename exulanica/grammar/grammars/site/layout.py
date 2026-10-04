"""How a site plan becomes records: one deterministic layout, connected by construction.

The site is a rectangle with its entry at the middle of its south edge. The layout, in order:

1. **The spine**, the plan's path part, runs north from the entry through the middle of the site.
   A zone placed across the far edge (``edge_back``) takes a strip the site's whole width, and a
   cross path the spine's width runs along that strip's front, so the far zone fronts a path too.
2. **Lots.** Every other zone takes a lot on one side of the spine: the strips either side are cut
   north from the entry into lots, one per zone, in order of placement (front, then middle, left
   and right, then back) and each as long as its share of its strip. A zone placed ``left`` or
   ``right`` keeps that side; any other goes to the side holding less so far. Every lot fronts the
   spine, so every zone is reached from the entry.
3. **A zone's contents**, in its lot's own frame (``u`` along the front, ``v`` into the lot): a
   walkable verge along the front; its structures in a row behind the verge, each with its door
   facing the front; a walkable lane, then its areas side by side to the back; its fixtures by
   their patterns in the free ground between; and its boundary round the lot, with a gate in the
   middle of its front.
4. **A structure** is four walls (its door in the front one) under a roof the drawing makes from
   its record; its rooms stand in a row along its front, a door in each wall between two rooms,
   so every room is reached from the entrance, and each room's fixtures stand by their patterns.

What a stage cannot fit (structures longer than their zone's front, rooms narrower than a person
can turn in, a fixture with nowhere clear to stand) is refused by name with the zone, the part and
the figures, never shrunk to fit: a candidate seed may fit where another did not, and a kind none
of whose seeds fit is refused by the kind's checks with that sentence.

Every figure is an integer number of millimetres; every placed thing keeps the clearance stated
for its enclosure below, and every draw is in the zone's or the structure's own domain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final

from exulanica.grammar.contract import StageContext
from exulanica.grammar.draw import DomainCursor
from exulanica.grammar.errors import InvalidParameterError
from exulanica.grammar.grammars.site.plan import (
    AreaPart,
    BoundaryPart,
    FixturePart,
    Look,
    PathPart,
    RoomPart,
    SitePlan,
    Span,
    StructurePart,
    ZonePlan,
)
from exulanica.grammar.grammars.site.records import (
    SiteAreaRecord,
    SiteExtentRecord,
    SiteFixtureRecord,
    SiteOpening,
    SitePathRecord,
    SiteRoomRecord,
    SiteStructureRecord,
    SiteWallRecord,
    SiteZoneRecord,
)

__all__ = ["DOOR_HEIGHT_MM", "SPACING", "Spacing", "lay_out"]

#: How tall a door's opening is: a standard doorway, 2,100 mm (2.1 m), and never taller than its
#: wall.
DOOR_HEIGHT_MM: Final = 2_100
#: A structure's outer walls and the walls between its rooms, in millimetres.
OUTER_WALL_MM: Final = 200
INNER_WALL_MM: Final = 100


@dataclass(frozen=True, slots=True)
class Spacing:
    """The clearances one enclosure lays things out with, each in millimetres.

    ``verge`` is the walkable strip inside a zone along its front; ``setback`` how far a
    structure's front stands behind the verge; ``structure_gap`` the walkable gap between two
    structures; ``lane`` the walkable way between the structures' backs and the areas behind them;
    ``side_margin`` and ``back_margin`` the ground kept clear at a lot's sides and back;
    ``area_gap`` the gap between two areas; ``clearance`` the room kept round every placed fixture
    and structure, which is wider than a walker (two 340 mm capsule radii); ``minimum_area`` and
    ``minimum_room`` the narrowest area and room laid.
    """

    verge: int
    setback: int
    structure_gap: int
    lane: int
    side_margin: int
    back_margin: int
    area_gap: int
    clearance: int
    minimum_area: int
    minimum_room: int


#: Outdoors a verge and a lane are 2 to 3 m, wide enough for two people to pass with a margin, and
#: a structure stands 1 m behind its verge; indoors the figures are a room's: 1 m along the inner
#: walls and 800 mm round furniture, enough for one person to pass between.
SPACING: Final = {
    "open": Spacing(
        verge=2_000,
        setback=1_000,
        structure_gap=3_000,
        lane=3_000,
        side_margin=2_000,
        back_margin=1_000,
        area_gap=1_000,
        clearance=1_000,
        minimum_area=4_000,
        minimum_room=1_800,
    ),
    "indoor": Spacing(
        verge=1_000,
        setback=500,
        structure_gap=1_000,
        lane=1_000,
        side_margin=1_000,
        back_margin=300,
        area_gap=600,
        clearance=800,
        minimum_area=1_200,
        minimum_room=1_800,
    ),
}


def _refuse(message: str) -> InvalidParameterError:
    return InvalidParameterError(message)


def _snap(value: int, module: int) -> int:
    """``value`` down to a whole number of ``module``."""
    return value // module * module


def _draw(cursor: DomainCursor, span: Span) -> int:
    """A figure from ``span``: one of its steps, drawn; a fixed span draws nothing."""
    if span.minimum == span.maximum:
        return span.minimum
    return span.minimum + cursor.integer(0, (span.maximum - span.minimum) // span.step) * span.step


@dataclass(frozen=True, slots=True)
class _Rect:
    """A rectangle in some frame: least and greatest of each axis."""

    a0: int
    b0: int
    a1: int
    b1: int

    def inflated(self, by: int) -> _Rect:
        return _Rect(self.a0 - by, self.b0 - by, self.a1 + by, self.b1 + by)

    def overlaps(self, other: _Rect) -> bool:
        return (
            self.a0 < other.a1 and other.a0 < self.a1 and self.b0 < other.b1 and other.b0 < self.b1
        )

    def within(self, other: _Rect) -> bool:
        return (
            other.a0 <= self.a0
            and self.a1 <= other.a1
            and other.b0 <= self.b0
            and self.b1 <= other.b1
        )


#: How a frame's local directions map to the site's sides, by the side its front faces: ``+u``,
#: ``-u``, ``+v`` (into the lot) and ``-v`` (towards its front).
_SIDES: Final = {
    "east": {"+u": "north", "-u": "south", "+v": "west", "-v": "east"},
    "west": {"+u": "south", "-u": "north", "+v": "east", "-v": "west"},
    "south": {"+u": "east", "-u": "west", "+v": "north", "-v": "south"},
    "north": {"+u": "west", "-u": "east", "+v": "south", "-v": "north"},
}
#: The quarter turns that take a slot's front (its +y) to face each side.
_YAW: Final = {"north": 0, "west": 1, "south": 2, "east": 3}


@dataclass(frozen=True, slots=True)
class _Frame:
    """A rectangle of the site with a front: ``u`` runs along the front, ``v`` into the rectangle
    from it. Each mapping is a proper rotation, so nothing laid in a frame is mirrored."""

    x0: int
    y0: int
    x1: int
    y1: int
    front: str

    @property
    def length(self) -> int:
        return self.y1 - self.y0 if self.front in ("east", "west") else self.x1 - self.x0

    @property
    def depth(self) -> int:
        return self.x1 - self.x0 if self.front in ("east", "west") else self.y1 - self.y0

    def point(self, u: int, v: int) -> tuple[int, int]:
        if self.front == "east":
            return self.x1 - v, self.y0 + u
        if self.front == "west":
            return self.x0 + v, self.y1 - u
        if self.front == "south":
            return self.x0 + u, self.y0 + v
        return self.x1 - u, self.y1 - v

    def rect(self, local: _Rect) -> _Rect:
        """A local rectangle (u0, v0, u1, v1) as the site's (x0, y0, x1, y1)."""
        ax, ay = self.point(local.a0, local.b0)
        bx, by = self.point(local.a1, local.b1)
        return _Rect(min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))

    def side(self, local_direction: str) -> str:
        return _SIDES[self.front][local_direction]

    def sub(self, local: _Rect) -> _Frame:
        """The frame of a local rectangle with the same front."""
        site = self.rect(local)
        return _Frame(site.a0, site.b0, site.a1, site.b1, self.front)


@dataclass(slots=True)
class _Emitter:
    """Collects records and numbers each owner's records of a kind from 0, in emission order."""

    context: StageContext
    records: list[object] = field(default_factory=list)
    ordinals: dict[tuple[str, str], int] = field(default_factory=dict)

    def next(self, subject_kind: str, owner: str) -> tuple[str, int]:
        ordinal = self.ordinals.get((subject_kind, owner), 0)
        self.ordinals[(subject_kind, owner)] = ordinal + 1
        return self.context.identity(subject_kind, owner, ordinal), ordinal


def _wall(
    emitter: _Emitter,
    owner: str,
    part_key: str,
    frame: _Frame,
    start: tuple[int, int],
    end: tuple[int, int],
    thickness: int,
    height: int,
    look: Look,
    openings: Sequence[tuple[int, int, int, str]],
) -> None:
    """A wall from local ``start`` to ``end`` (one axis only), with openings stated as (offset from
    ``start``, width, height, kind); written from its lesser end, so offsets are turned when the
    local direction runs against the site's axis."""
    sx, sy = frame.point(*start)
    ex, ey = frame.point(*end)
    length = abs(ex - sx) + abs(ey - sy)
    reversed_ = (ex, ey) < (sx, sy)
    if reversed_:
        sx, sy, ex, ey = ex, ey, sx, sy
    stated = sorted(
        (
            SiteOpening(
                offset_mm=(length - offset - width) if reversed_ else offset,
                width_mm=width,
                height_mm=min(opening_height, height),
                kind=kind,
            )
            for offset, width, opening_height, kind in openings
        ),
        key=lambda opening: opening.offset_mm,
    )
    identity, ordinal = emitter.next("site_wall", owner)
    emitter.records.append(
        SiteWallRecord(
            identity=identity,
            owner_identity=owner,
            ordinal=ordinal,
            part_key=part_key,
            start_x_mm=sx,
            start_y_mm=sy,
            end_x_mm=ex,
            end_y_mm=ey,
            thickness_mm=thickness,
            height_mm=height,
            look_family=look.family,
            look_leaf=look.leaf,
            openings=tuple(stated),
        )
    )


def _ring_walls(
    emitter: _Emitter,
    owner: str,
    part_key: str,
    frame: _Frame,
    thickness: int,
    height: int,
    look: Look,
    front_openings: Sequence[tuple[int, int, int, str]],
    skip: frozenset[str] = frozenset(),
) -> None:
    """Four walls on the inside of a frame's edges, the front one with its openings (offsets from
    its u = 0 end). ``skip`` names the local edges (``front``, ``back``, ``low``, ``high``) that
    another wall already stands on."""
    half = thickness // 2
    length, depth = frame.length, frame.depth
    edges = {
        "front": ((0, half), (length, half), front_openings),
        "back": ((0, depth - half), (length, depth - half), ()),
        "low": ((half, 0), (half, depth), ()),
        "high": ((length - half, 0), (length - half, depth), ()),
    }
    for name in ("front", "back", "low", "high"):
        if name in skip:
            continue
        start, end, openings = edges[name]
        _wall(emitter, owner, part_key, frame, start, end, thickness, height, look, openings)


def _place(
    *,
    pattern: str,
    part: FixturePart,
    count: int,
    area: _Rect,
    occupied: list[_Rect],
    clearance: int,
    cursor: DomainCursor,
    where: str,
) -> list[tuple[_Rect, str]]:
    """``count`` footprints for ``part`` inside the local rectangle ``area``, each with the local
    direction its front faces, clear of everything ``occupied`` and of each other; refused by name
    when they do not all fit."""
    w, d = part.width_mm, part.depth_mm
    width_u = area.a1 - area.a0
    depth_v = area.b1 - area.b0

    def footprint(cu: int, cv: int, facing: str) -> _Rect:
        along_u, along_v = (w, d) if facing in ("-v", "+v") else (d, w)
        return _Rect(
            cu - along_u // 2,
            cv - along_v // 2,
            cu - along_u // 2 + along_u,
            cv - along_v // 2 + along_v,
        )

    def along(number: int, size: int) -> list[int]:
        """``number`` centres along u, spread evenly where there is room and never closer than
        ``size`` plus the clearance, the group centred in the area."""
        if number <= 0:
            return []
        pitch = max(size + clearance, (width_u - clearance) // number)
        span = pitch * (number - 1) + size
        first = area.a0 + (width_u - span) // 2 + size // 2
        return [first + pitch * index for index in range(number)]

    candidates: list[tuple[int, int, str]] = []
    if pattern == "row":
        for cu in along(count, w):
            candidates.append((cu, area.b0 + clearance + d // 2, "-v"))
    elif pattern == "grid":
        columns = 1
        while columns * columns < count:
            columns += 1
        rows = (count + columns - 1) // columns
        pitch_u, pitch_v = width_u // columns, depth_v // rows
        for index in range(count):
            row, column = divmod(index, columns)
            candidates.append(
                (
                    area.a0 + pitch_u * column + pitch_u // 2,
                    area.b0 + pitch_v * row + pitch_v // 2,
                    "-v",
                )
            )
    elif pattern in ("cluster", "centre"):
        centre_u, centre_v = (area.a0 + area.a1) // 2, (area.b0 + area.b1) // 2
        columns = 1
        while columns * columns < count:
            columns += 1
        pitch_u, pitch_v = w + clearance, d + clearance
        origin_u = centre_u - (pitch_u * (columns - 1)) // 2
        rows = (count + columns - 1) // columns
        origin_v = centre_v - (pitch_v * (rows - 1)) // 2
        for index in range(count):
            row, column = divmod(index, columns)
            candidates.append((origin_u + pitch_u * column, origin_v + pitch_v * row, "-v"))
    elif pattern in ("back_wall", "perimeter"):
        inset = 0 if pattern == "back_wall" else clearance // 2
        along_back = max(1, (width_u - clearance) // (w + clearance))
        back_count = count if pattern == "back_wall" else min(count, along_back)
        for cu in along(back_count, w):
            candidates.append((cu, area.b1 - inset - d // 2, "-v"))
        rest = count - back_count
        if rest:
            low_count = (rest + 1) // 2
            for side, number, cu in (
                ("+u", low_count, area.a0 + inset + d // 2),
                ("-u", rest - low_count, area.a1 - inset - d // 2),
            ):
                pitch = max(w + clearance, (depth_v - d - 2 * clearance) // max(number, 1))
                for index in range(number):
                    candidates.append(
                        (cu, area.b0 + d + clearance + pitch * index + pitch // 2, side)
                    )
    elif pattern == "scatter":
        cell = max(w, d) + 2 * clearance
        columns, rows = width_u // cell, depth_v // cell
        cells = [(column, row) for row in range(rows) for column in range(columns)]
        order = sorted(cells, key=lambda c: (cursor.number(), c))
        slack = cell - max(w, d) - clearance
        for column, row in order:
            jitter_u = cursor.integer(0, max(slack, 0)) - slack // 2 if slack > 0 else 0
            jitter_v = cursor.integer(0, max(slack, 0)) - slack // 2 if slack > 0 else 0
            candidates.append(
                (
                    area.a0 + column * cell + cell // 2 + jitter_u,
                    area.b0 + row * cell + cell // 2 + jitter_v,
                    "-v",
                )
            )
    else:
        raise _refuse(f"{where}: a fixture is not laid out by {pattern}")
    step = max(200, (min(w, d) + clearance) // 2)
    grid = [
        (gu, gv)
        for gu in range(area.a0 + step // 2, area.a1, step)
        for gv in range(area.b0 + step // 2, area.b1, step)
    ]

    def fits(rect: _Rect) -> bool:
        return rect.within(area) and not any(rect.overlaps(other) for other in occupied)

    placed: list[tuple[_Rect, str]] = []
    for cu, cv, facing in candidates:
        if len(placed) == count:
            break
        rect = footprint(cu, cv, facing)
        if not fits(rect):
            if pattern == "scatter":
                continue
            # The nearest free point facing the same way: a row, a back wall or a perimeter
            # fixture slides along its own line past a doorway's clear way; a grid, cluster or
            # centred fixture steps to the nearest free point of a grid over the area.
            if pattern in ("row", "back_wall", "perimeter"):
                if facing in ("-v", "+v"):
                    line = [(gu, cv) for gu in range(area.a0 + step // 2, area.a1, step)]
                else:
                    line = [(cu, gv) for gv in range(area.b0 + step // 2, area.b1, step)]
            else:
                line = grid
            found = None
            for gu, gv in sorted(
                line, key=lambda g: ((g[0] - cu) * (g[0] - cu) + (g[1] - cv) * (g[1] - cv), g)
            ):
                trial = footprint(gu, gv, facing)
                if fits(trial):
                    found = trial
                    break
            if found is None:
                break
            rect = found
        placed.append((rect, facing))
        occupied.append(rect.inflated(clearance))
    if len(placed) < count:
        raise _refuse(
            f"{where}: {count} of {part.key} ({w} by {d} mm) do not fit {pattern} in "
            f"{width_u} by {depth_v} mm with {clearance} mm clear round each; {len(placed)} did"
        )
    return placed


def _fixtures(
    emitter: _Emitter,
    owner: str,
    frame: _Frame,
    placed: Sequence[tuple[_Rect, str]],
    part: FixturePart,
) -> None:
    for rect, facing in placed:
        x_mid, y_mid = frame.point((rect.a0 + rect.a1) // 2, (rect.b0 + rect.b1) // 2)
        identity, ordinal = emitter.next("site_fixture", owner)
        emitter.records.append(
            SiteFixtureRecord(
                identity=identity,
                owner_identity=owner,
                ordinal=ordinal,
                part_key=part.key,
                x_mm=x_mid,
                y_mm=y_mid,
                yaw_quarter_turns=_YAW[frame.side(facing)],
                width_mm=part.width_mm,
                depth_mm=part.depth_mm,
                height_mm=part.height_mm,
                roles=tuple(sorted(part.roles)),
                look_family=part.look.family,
                look_leaf=part.look.leaf,
                seats=part.seats,
                stands=part.stands,
                sleepers=part.sleepers,
                blocks=part.blocks,
            )
        )


def _structure(
    emitter: _Emitter,
    plan: SitePlan,
    zone_identity: str,
    lot: _Frame,
    local: _Rect,
    part: StructurePart,
    storeys: int,
    cursor: DomainCursor,
    where: str,
) -> int:
    """One structure in its lot: its record, its walls, and its rooms with what they hold. Returns
    where its door is along its front, from its own u = 0 end."""
    parts = plan.by_key()
    spacing = SPACING["indoor"]
    frame = lot.sub(local)
    length, depth = frame.length, frame.depth
    height = storeys * part.storey_height_mm
    rooms: list[RoomPart] = []
    for holding in part.rooms:
        room = parts[holding.part]
        assert isinstance(room, RoomPart)
        rooms.extend([room] * _draw(cursor, holding.count))
    door = bool(rooms) or bool(part.roles)
    inner = length - 2 * OUTER_WALL_MM
    bounds = [0]
    if rooms:
        total = sum(room.share for room in rooms)
        running = 0
        for room in rooms[:-1]:
            running += room.share
            bounds.append(_snap(inner * running // total, 100))
        bounds.append(inner)
        narrow = min(b - a for a, b in pairwise(bounds)) - INNER_WALL_MM
        if narrow < spacing.minimum_room:
            raise _refuse(
                f"{where}: {part.key} is {length} mm along its front and its {len(rooms)} rooms "
                f"leave one {narrow} mm wide, under {spacing.minimum_room} mm"
            )
        if depth - 2 * OUTER_WALL_MM < spacing.minimum_room:
            raise _refuse(f"{where}: {part.key} is {depth} mm deep, too shallow for a room")
    # The entrance is in the middle of the front, moved to the middle of its room when a wall
    # between two rooms stands there.
    door_u = length // 2
    for split in bounds[1:-1]:
        wall_u = OUTER_WALL_MM + split
        if abs(door_u - wall_u) < part.door_width_mm // 2 + INNER_WALL_MM:
            room_index = next(i for i, b in enumerate(bounds[1:]) if OUTER_WALL_MM + b > door_u)
            door_u = OUTER_WALL_MM + (bounds[room_index] + bounds[room_index + 1]) // 2
    door_x, door_y = frame.point(door_u, 0)
    site = lot.rect(local)
    identity, ordinal = emitter.next("site_structure", zone_identity)
    emitter.records.append(
        SiteStructureRecord(
            identity=identity,
            zone_identity=zone_identity,
            ordinal=ordinal,
            part_key=part.key,
            min_x_mm=site.a0,
            min_y_mm=site.b0,
            max_x_mm=site.a1,
            max_y_mm=site.b1,
            storeys=storeys,
            storey_height_mm=part.storey_height_mm,
            roof_form=part.roof_form,
            roles=tuple(sorted(part.roles)),
            look_family=part.look.family,
            look_leaf=part.look.leaf,
            roof_family=part.roof_look.family,
            roof_leaf=part.roof_look.leaf,
            wall_family=part.wall_look.family,
            wall_leaf=part.wall_look.leaf,
            door_width_mm=part.door_width_mm if door else 0,
            door_x_mm=door_x,
            door_y_mm=door_y,
            door_facing=lot.front,
            room_count=len(rooms),
        )
    )
    entrance = (
        [(door_u - part.door_width_mm // 2, part.door_width_mm, DOOR_HEIGHT_MM, "door")]
        if door
        else []
    )
    _ring_walls(
        emitter,
        identity,
        part.key,
        frame,
        OUTER_WALL_MM,
        height,
        part.wall_look,
        entrance,
    )
    if not rooms:
        return door_u
    v0, v1 = OUTER_WALL_MM, depth - OUTER_WALL_MM
    for split in bounds[1:-1]:
        u = OUTER_WALL_MM + split
        middle = (v0 + v1) // 2
        _wall(
            emitter,
            identity,
            part.key,
            frame,
            (u, v0),
            (u, v1),
            INNER_WALL_MM,
            part.storey_height_mm,
            part.wall_look,
            [(middle - v0 - part.door_width_mm // 2, part.door_width_mm, DOOR_HEIGHT_MM, "door")],
        )
    for index, room in enumerate(rooms):
        u0 = OUTER_WALL_MM + bounds[index] + (INNER_WALL_MM // 2 if index else 0)
        u1 = (
            OUTER_WALL_MM
            + bounds[index + 1]
            - (INNER_WALL_MM // 2 if index < len(rooms) - 1 else 0)
        )
        room_local = _Rect(u0, v0, u1, v1)
        room_site = frame.rect(room_local)
        room_identity, room_ordinal = emitter.next("site_room", identity)
        emitter.records.append(
            SiteRoomRecord(
                identity=room_identity,
                structure_identity=identity,
                ordinal=room_ordinal,
                part_key=room.key,
                min_x_mm=room_site.a0,
                min_y_mm=room_site.b0,
                max_x_mm=room_site.a1,
                max_y_mm=room_site.b1,
                roles=tuple(sorted(room.roles)),
                floor_family=room.look.family,
                floor_leaf=room.look.leaf,
            )
        )
        # Keep every doorway clear: the entrance and each door between rooms, on both sides.
        occupied: list[_Rect] = []
        reach = part.door_width_mm // 2 + spacing.clearance
        if u0 <= door_u <= u1 and door:
            occupied.append(_Rect(door_u - reach, v0, door_u + reach, v0 + spacing.clearance + 600))
        middle = (v0 + v1) // 2
        for split in bounds[1:-1]:
            u = OUTER_WALL_MM + split
            if u0 - INNER_WALL_MM <= u <= u1 + INNER_WALL_MM:
                occupied.append(
                    _Rect(
                        u - spacing.clearance - 600,
                        middle - reach,
                        u + spacing.clearance + 600,
                        middle + reach,
                    )
                )
        room_area = _Rect(u0, v0, u1, v1)
        for holding_index, holding in enumerate(room.holds):
            fixture = parts[holding.part]
            assert isinstance(fixture, FixturePart)
            count = _draw(cursor, holding.count)
            placed = _place(
                pattern=holding.pattern,
                part=fixture,
                count=count,
                area=room_area,
                occupied=occupied,
                clearance=spacing.clearance,
                cursor=cursor,
                where=f"{where} room {room.key} holding {holding_index}",
            )
            _fixtures(emitter, room_identity, frame, placed, fixture)
    return door_u


def _zone(
    emitter: _Emitter,
    plan: SitePlan,
    zone: ZonePlan,
    ordinal: int,
    lot: _Frame,
    root: str,
    perimeter: frozenset[str],
) -> str:
    """One zone in its lot: its record, structures, areas, fixtures and boundary."""
    parts = plan.by_key()
    spacing = SPACING[plan.enclosure]
    cursor = emitter.context.cursor(f"zone.{zone.key}")
    where = f"zone {zone.key}"
    site = _Rect(lot.x0, lot.y0, lot.x1, lot.y1)
    gate_x, gate_y = lot.point(lot.length // 2, 0)
    identity = emitter.context.identity("site_zone", root, ordinal)
    emitter.records.append(
        SiteZoneRecord(
            identity=identity,
            ordinal=ordinal,
            zone_key=zone.key,
            min_x_mm=site.a0,
            min_y_mm=site.b0,
            max_x_mm=site.a1,
            max_y_mm=site.b1,
            frontage=lot.front,
            access=zone.access,
            ground_family=zone.ground.family,
            ground_leaf=zone.ground.leaf,
            gate_x_mm=gate_x,
            gate_y_mm=gate_y,
        )
    )
    length, depth = lot.length, lot.depth
    counts = [_draw(cursor, holding.count) for holding in zone.holds]
    structures: list[tuple[StructurePart, int, int, int]] = []
    areas: list[AreaPart] = []
    fixtures: list[tuple[int, FixturePart, int, str]] = []
    for index, (holding, count) in enumerate(zip(zone.holds, counts, strict=True)):
        part = parts[holding.part]
        for _ in range(count):
            if isinstance(part, StructurePart):
                structures.append(
                    (
                        part,
                        _draw(cursor, part.width_mm),
                        _draw(cursor, part.depth_mm),
                        _draw(cursor, part.storeys),
                    )
                )
            elif isinstance(part, AreaPart):
                areas.append(part)
        if isinstance(part, FixturePart):
            fixtures.append((index, part, count, holding.pattern))
    occupied: list[_Rect] = []
    v = spacing.verge
    behind = v
    if structures:
        total = sum(w for _, w, _, _ in structures) + spacing.structure_gap * (len(structures) - 1)
        room = length - 2 * spacing.side_margin
        if total > room:
            raise _refuse(
                f"{where} is {length} mm along its front and its {len(structures)} structures "
                f"need {total} mm with {spacing.structure_gap} mm between them; {room} mm is free"
            )
        deepest = max(d for _, _, d, _ in structures)
        front = v + spacing.setback
        if front + deepest > depth - spacing.back_margin:
            raise _refuse(
                f"{where} is {depth} mm deep and a structure {deepest} mm deep needs "
                f"{front + deepest + spacing.back_margin} mm"
            )
        u = spacing.side_margin + _snap((room - total) // 2, plan.module_mm)
        for index, (part, w, d, storeys) in enumerate(structures):
            local = _Rect(u, front, u + w, front + d)
            door_u = u + _structure(
                emitter,
                plan,
                identity,
                lot,
                local,
                part,
                storeys,
                emitter.context.cursor(f"zone.{zone.key}.structure_{index}"),
                f"{where} structure {index}",
            )
            occupied.append(local.inflated(spacing.clearance))
            # The way from its door to the zone's front stays clear.
            reach = part.door_width_mm // 2 + spacing.clearance
            occupied.append(_Rect(door_u - reach, 0, door_u + reach, front))
            u += w + spacing.structure_gap
        behind = front + deepest
    yard_end = depth - spacing.back_margin
    if areas:
        # In front of its areas a zone keeps a band for its fixtures, as deep as its largest
        # fixture with room round it, then a walkable lane the areas are reached from.
        reach = max((max(part.width_mm, part.depth_mm) for _, part, _, _ in fixtures), default=0)
        band = reach + 2 * spacing.clearance if reach else 0
        yard_end = behind + band
        start = yard_end + spacing.lane
        end = depth - spacing.back_margin
        if end - start < spacing.minimum_area:
            raise _refuse(
                f"{where} leaves {end - start} mm for its areas, under {spacing.minimum_area} mm"
            )
        usable = length - 2 * spacing.side_margin
        width = _snap((usable - spacing.area_gap * (len(areas) - 1)) // len(areas), plan.module_mm)
        if width < spacing.minimum_area:
            raise _refuse(
                f"{where} is {length} mm along its front and its {len(areas)} areas would each be "
                f"{width} mm wide, under {spacing.minimum_area} mm"
            )
        for index, part in enumerate(areas):
            u0 = spacing.side_margin + index * (width + spacing.area_gap)
            local = _Rect(u0, start, u0 + width, end)
            area_site = lot.rect(local)
            access_x, access_y = lot.point(u0 + width // 2, start - spacing.lane // 2)
            area_identity, area_ordinal = emitter.next("site_area", identity)
            emitter.records.append(
                SiteAreaRecord(
                    identity=area_identity,
                    zone_identity=identity,
                    ordinal=area_ordinal,
                    part_key=part.key,
                    min_x_mm=area_site.a0,
                    min_y_mm=area_site.b0,
                    max_x_mm=area_site.a1,
                    max_y_mm=area_site.b1,
                    roles=tuple(sorted(part.roles)),
                    look_family=part.look.family,
                    look_leaf=part.look.leaf,
                    access_x_mm=access_x,
                    access_y_mm=access_y,
                )
            )
            occupied.append(local)
    # The side margins stay clear the whole depth of the lot: with the verge and the lane they are
    # the zone's corridors, along which everything in it is reached.
    yard = _Rect(spacing.side_margin, v, length - spacing.side_margin, yard_end)
    for index, part, count, pattern in fixtures:
        if count == 0:
            continue
        placed = _place(
            pattern=pattern,
            part=part,
            count=count,
            area=yard,
            occupied=occupied,
            clearance=spacing.clearance,
            cursor=emitter.context.cursor(f"zone.{zone.key}.fixtures_{index}"),
            where=f"{where} holding {index}",
        )
        _fixtures(emitter, identity, lot, placed, part)
    if zone.boundary:
        boundary = parts[zone.boundary]
        assert isinstance(boundary, BoundaryPart)
        gate = (
            length // 2 - boundary.gate_width_mm // 2,
            boundary.gate_width_mm,
            boundary.height_mm,
            "gate",
        )
        _ring_walls(
            emitter,
            identity,
            boundary.key,
            lot,
            boundary.thickness_mm,
            boundary.height_mm,
            boundary.look,
            [gate],
            skip=perimeter,
        )
    return identity


def _need(plan: SitePlan, zone: ZonePlan) -> int:
    """The least length along its front a zone's lot can have: room for its widest possible row
    of structures, or of areas, at the largest each holding may draw, with the gaps and margins
    the layout keeps; two modules for a zone that holds neither."""
    parts = plan.by_key()
    spacing = SPACING[plan.enclosure]
    structures: list[tuple[StructurePart, int]] = []
    for holding in zone.holds:
        held = parts[holding.part]
        if isinstance(held, StructurePart):
            structures.append((held, holding.count.maximum))
    areas = sum(h.count.maximum for h in zone.holds if isinstance(parts[h.part], AreaPart))
    need = 2 * plan.module_mm
    if structures:
        count = sum(number for _, number in structures)
        widths = sum(part.width_mm.maximum * number for part, number in structures)
        need = max(need, widths + spacing.structure_gap * (count - 1) + 2 * spacing.side_margin)
    if areas:
        need = max(
            need,
            areas * spacing.minimum_area + spacing.area_gap * (areas - 1) + 2 * spacing.side_margin,
        )
    return -(-need // plan.module_mm) * plan.module_mm


def _allot(plan: SitePlan, zones: Sequence[ZonePlan], length: int, front: str) -> list[int]:
    """Each zone's length along one side of the spine: first what it needs (:func:`_need`), then
    the rest of the side shared by the zones' shares, on the module; refused by name when the
    side cannot hold what its zones need."""
    if not zones:
        return []
    module = plan.module_mm
    needs = [_need(plan, zone) for zone in zones]
    if sum(needs) > length:
        stated = ", ".join(f"{zone.key} {need} mm" for zone, need in zip(zones, needs, strict=True))
        raise _refuse(
            f"the side of the spine facing {front} is {length} mm long and its zones need "
            f"{sum(needs)} mm ({stated})"
        )
    surplus = length - sum(needs)
    total = sum(zone.share for zone in zones)
    lengths = [
        need + _snap(surplus * zone.share // total, module)
        for zone, need in zip(zones, needs, strict=True)
    ]
    lengths[-1] += length - sum(lengths)
    return lengths


def lay_out(plan: SitePlan, context: StageContext) -> tuple[object, ...]:
    """Every record of a site, in emission order: extent, paths, zones with all they hold, and the
    site's own boundary."""
    parts = plan.by_key()
    module = plan.module_mm
    width, depth = plan.width_mm, plan.depth_mm
    emitter = _Emitter(context)
    root = context.subject_identity
    spine = parts[plan.spine]
    assert isinstance(spine, PathPart)
    boundary = parts.get(plan.boundary) if plan.boundary else None
    assert boundary is None or isinstance(boundary, BoundaryPart)
    inset = 0 if boundary is None else _snap(boundary.thickness_mm + module - 1, module)
    if spine.width_mm % module or spine.width_mm < module:
        raise _refuse(f"the spine {spine.key} is {spine.width_mm} mm wide, not whole modules")
    if plan.entry_width_mm > spine.width_mm:
        raise _refuse("the site's entry is no wider than its spine")
    x0 = _snap((width - spine.width_mm) // 2, module)
    x1 = x0 + spine.width_mm
    entry_x = (x0 + x1) // 2
    extent_identity = context.identity("site_extent", root, 0)
    emitter.records.append(
        SiteExtentRecord(
            identity=extent_identity,
            kind_key=plan.kind,
            width_mm=width,
            depth_mm=depth,
            module_mm=module,
            enclosure=plan.enclosure,
            ground_family=plan.ground.family,
            ground_leaf=plan.ground.leaf,
            entry_x_mm=entry_x,
            entry_width_mm=plan.entry_width_mm,
            wall_height_mm=boundary.height_mm if plan.enclosure == "indoor" and boundary else 0,
            wall_thickness_mm=boundary.thickness_mm
            if plan.enclosure == "indoor" and boundary
            else 0,
        )
    )
    back = next((zone for zone in plan.zones if zone.placement == "edge_back"), None)
    top = depth - inset
    paths: list[_Rect] = []
    if back is not None:
        far = _snap((depth - 2 * inset) * back.share // 1000, module)
        top = depth - inset - far - spine.width_mm
        if far < 2 * module or top - inset < 2 * module:
            raise _refuse(
                f"zone {back.key} takes {far} mm of a site {depth} mm deep, leaving the rest "
                f"{top - inset} mm"
            )
        paths.append(_Rect(x0, inset, x1, top + spine.width_mm))
        paths.append(_Rect(inset, top, width - inset, top + spine.width_mm))
    else:
        paths.append(_Rect(x0, inset, x1, top))
    for rect in paths:
        identity, ordinal = emitter.next("site_path", root)
        emitter.records.append(
            SitePathRecord(
                identity=identity,
                ordinal=ordinal,
                part_key=spine.key,
                min_x_mm=rect.a0,
                min_y_mm=rect.b0,
                max_x_mm=rect.a1,
                max_y_mm=rect.b1,
                roles=tuple(sorted(spine.roles)),
                look_family=spine.look.family,
                look_leaf=spine.look.leaf,
            )
        )
    if x0 - inset < 4 * module:
        raise _refuse(f"the site is {width} mm wide; its sides of the spine are too narrow")
    rank = {"front": 0, "left": 1, "right": 1, "middle": 1, "back": 2}
    core = sorted(
        ((index, zone) for index, zone in enumerate(plan.zones) if zone.placement != "edge_back"),
        key=lambda pair: (rank[pair[1].placement], pair[0]),
    )
    left: list[tuple[int, ZonePlan]] = []
    right: list[tuple[int, ZonePlan]] = []
    left_share = right_share = 0
    for index, zone in core:
        if zone.placement == "left" or (zone.placement != "right" and left_share <= right_share):
            left.append((index, zone))
            left_share += zone.share
        else:
            right.append((index, zone))
            right_share += zone.share
    # A wall another stands on is not drawn twice: the site's own boundary stands on a lot's
    # outer edges, and of two neighbouring lots that both have boundaries the southern one stands
    # on the edge between them. In a lot fronting east u runs north, so its south edge is ``low``;
    # fronting west u runs south, so its south edge is ``high``.
    for strip, front, chosen in (
        ((inset, x0), "east", left),
        ((x1, width - inset), "west", right),
    ):
        south, north = ("low", "high") if front == "east" else ("high", "low")
        lengths = _allot(plan, [zone for _, zone in chosen], top - inset, front)
        start = inset
        bounded_before = False
        for position, (index, zone) in enumerate(chosen):
            end = start + lengths[position]
            lot = _Frame(strip[0], start, strip[1], end, front)
            skip: set[str] = set()
            if boundary is not None:
                skip.add("back")
                if start == inset:
                    skip.add(south)
                if back is None and end == depth - inset:
                    skip.add(north)
            if bounded_before:
                skip.add(south)
            _zone(emitter, plan, zone, index, lot, root, frozenset(skip))
            bounded_before = bool(zone.boundary)
            start = end
    if back is not None:
        index = plan.zones.index(back)
        lot = _Frame(inset, top + spine.width_mm, width - inset, depth - inset, "south")
        _zone(
            emitter,
            plan,
            back,
            index,
            lot,
            root,
            frozenset({"back", "low", "high"}) if boundary is not None else frozenset(),
        )
    if boundary is not None:
        site = _Frame(0, 0, width, depth, "south")
        entry = (
            entry_x - plan.entry_width_mm // 2,
            plan.entry_width_mm,
            DOOR_HEIGHT_MM if plan.enclosure == "indoor" else boundary.height_mm,
            "door" if plan.enclosure == "indoor" else "gate",
        )
        _ring_walls(
            emitter,
            extent_identity,
            boundary.key,
            site,
            boundary.thickness_mm,
            boundary.height_mm,
            boundary.look,
            [entry],
        )
    return tuple(emitter.records)
