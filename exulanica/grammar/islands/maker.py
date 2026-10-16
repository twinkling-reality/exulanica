"""The island maker: a sky island and a seed made into an unchanged ``exulanica.volume/v1``.

The volume is in the island's own frame (x east, y north, z up, whole millimetres): its top is
capped flat at height 0 by a cap part, or by the island's top land where it states one, and the
top outline is centred on the origin (the middle of the box round the slab's and the lobes' top
discs). Its id is the island's id, its looks, walk,
erosion and strata are the island's, and it is read by the volume reader under the volume catalog
version the island's catalog names, so what the maker returns is a volume any volume reader admits.
It lists at most the volume catalog's part limit: a slab, up to four lobes, the underside's parts,
up to four fingers and the cap make at most 16.

**Whole numbers and the seed.** Every value is an integer computed with integer arithmetic (turns
by :func:`~exulanica.grammar.volumes.turns.sin_cos`, square roots exact floors), and every drawn
value comes from SHA-256 of the seed under the island profile's prefix and the island's id, one
stream for each part by its name, so adding a finger never moves the keel. The same island and seed
make the same volume, byte for byte.

**What reads as a floating island.** Measured by looking at volumes drawn in the application:

* The top is a wide slab whose top overhangs its base (its base radius about four fifths of its
  top's), and each further lobe a smaller slab of its own, overhanging the same way, blended into
  it over 1.5 to 2.5 m so their joins crease.
* The underside narrows steadily downward and never widens again below the slab: every underside
  part's top lies inside the slab or inside the part it hangs from, and every part leans outward
  going up or tapers faster than it leans, so its reach from the island's axis does not grow
  downward. A part that reached past the slab's edge below it would make a skirt or a pot.
* ``cone``: one keel, a column whose top radius sits inside the slab's base and whose base radius
  is at least half its toe's width, leaned a few degrees (never more than its taper allows), its
  top under the slab's centre, ending in a blunt flattened toe block set slightly off its axis and
  blended into the keel over 2.5 to 3 m. A narrow keel ending in a rounded part reads as a drop or
  a knob, and so does a toe wider than the keel's foot under weathering, which narrows the keel
  into a neck above it: the toe is at most 0.45 as tall as it is wide, rounded 0.6 to 0.8 m, its
  top inside the keel's foot and its corners and offset within the foot's radius. Two leaning
  roots, widening upward into the slab, and two lumps tilted 18 to 30 degrees sit on the
  underside inside the taper. A small island reads floating with a deep keel, about 1.3 to 1.5
  times its top width below its widest bed: that depth is the island's ``depth_mm``.
* ``bowl``: one wide, upright column rounded at its foot into a bowl, with the two tilted lumps;
  it reads shallow at a depth of about half the radius.
* ``spires``: three to five narrow keels, the first on the axis to the full depth and the rest
  shorter round it, each leaning outward going up and ending in its own flat foot; a toe block on
  a keel this narrow reads as a drop.
* Fingers are thick, blunt limbs (columns whose foot is about three quarters of their top's
  radius, rounded by a third of it), hanging from the keel, the bowl or a spire. Thin tapering
  limbs read as melted drips and are never made. A keel's or a spire's foot and a finger's top
  are at least three quarters of the weathering's amplitude and a metre in radius, and a root's or
  a finger's foot at least three quarters of that, wherever the slab and the part a finger hangs
  from are wide enough, so weathering does not eat through one and leave its end floating.
* The slab and the lobes reach above the cap by their rounding and the weathering's amplitude, so
  the cap cuts their rounding away and the top is level at 0 wherever rock lies under it.
* A top land (:attr:`~exulanica.grammar.islands.document.IslandDocument.top`) is the volume's
  ``top_land`` over the square round the top's discs grown by a tenth, in whole 2 m, its datum the
  island's top height 0. The maker realizes it as the field will
  (:class:`~exulanica.grammar.volumes.TopLandSurface`), then makes the island as if its top were
  level at the land's lowest height (or 0, where the land never falls below it), so the rim and
  the underside hang below the lowest point, and raises the slab and the lobes by the land's
  relief, so they reach above its highest point by their rounding and the weathering as they reach
  above a level cap: the land cuts every point of the top. A slab raised so keeps its base and its
  widest radius and leans less.
* Varied strata read well on islands (amplitude 700 to 1100 mm, period 2800 to 4500 mm, thinner
  beds on smaller islands and never under 2 m for a 2 m drawing cell, a spread, relief about 600,
  offset 500 to 700, tilt 4 to 5 degrees). They are the island's own section and passed on as
  stated.

The tests pin made volumes by digest, so a change that moves any part of one is seen.

Nothing here opens a database, a store or evidence.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Final

from exulanica.grammar.geometry import integer_sqrt
from exulanica.grammar.islands.document import PROFILE, IslandDocument
from exulanica.grammar.volumes import (
    PROFILE as VOLUME_PROFILE,
)
from exulanica.grammar.volumes import (
    TURN_ONE,
    TopLand,
    TopLandSurface,
    VolumeDocument,
    read_volume_document,
    sin_cos,
    volume_catalog,
)

__all__ = ["make_island_volume"]

_FULL: Final = 360_000
#: How far the slab reaches past where the cap cuts it beyond its rounding and the weathering, so
#: the cap cuts its rounding away and no weathering reaches down through the top.
_OVER_MM: Final = 500
#: A top land's square is whole 2 m, as the volume reader holds it.
_SQUARE_STEP_MM: Final = 2_000

Part = dict[str, Any]
Point = tuple[int, int, int]


class _Draws:
    """One part's stream of drawn whole numbers from the island's key and the part's name."""

    __slots__ = ("_count", "_pool", "_seed")

    def __init__(self, key: bytes, name: str) -> None:
        self._seed = key + b"\x1f" + name.encode()
        self._pool = b""
        self._count = 0

    def between(self, low: int, high: int) -> int:
        """A whole number from ``low`` to ``high``, both included."""
        if len(self._pool) < 8:
            counter = self._count.to_bytes(4, "big")
            self._pool += hashlib.sha256(self._seed + counter).digest()
            self._count += 1
        value = int.from_bytes(self._pool[:8], "big")
        self._pool = self._pool[8:]
        return low + value % (high - low + 1)

    def share(self, whole: int, low: int, high: int) -> int:
        """A drawn share of ``whole``, from ``low`` to ``high`` hundredths."""
        return whole * self.between(low, high) // 100


def _along(bearing: int, distance: int) -> tuple[int, int]:
    """The point ``distance`` from the origin toward a compass bearing (clockwise from north)."""
    sine, cosine = sin_cos(bearing % _FULL)
    return distance * sine // TURN_ONE, distance * cosine // TURN_ONE


def _column(
    part_id: str,
    at: Point,
    height: int,
    base: int,
    top: int,
    rounding: int,
    *,
    tilt: int = 0,
    toward: int = 0,
    blend: int = 0,
) -> Part:
    rounding = max(0, min(rounding, base, top, (height - 1) // 2))
    return {
        "id": part_id,
        "shape": "column",
        "at_mm": list(at),
        "height_mm": height,
        "base_radius_mm": base,
        "top_radius_mm": top,
        "round_mm": rounding,
        "tilt_mdeg": tilt,
        "toward_mdeg": toward % _FULL,
        "blend_mm": blend,
    }


def _box(
    part_id: str,
    at: Point,
    size: Point,
    rounding: int,
    *,
    yaw: int,
    tilt: int,
    toward: int,
    blend: int,
) -> Part:
    return {
        "id": part_id,
        "shape": "box",
        "at_mm": list(at),
        "size_mm": list(size),
        "round_mm": max(0, min(rounding, min(size) // 2)),
        "yaw_mdeg": yaw % _FULL,
        "tilt_mdeg": tilt,
        "toward_mdeg": toward % _FULL,
        "blend_mm": blend,
    }


def _least(island: IslandDocument) -> int:
    """The radius under which weathering at its fullest can eat through a limb, a keel's foot or
    a spire and leave its end floating as debris."""
    weathering = int(island.erosion["amplitude_mm"]) + int(island.strata["amplitude_mm"])
    return weathering * 3 // 4 + 1_000


def _lean_within(tilt: int, height: int, room: int) -> int:
    """The largest tilt, ``tilt`` or less by half degrees, whose lean over ``height`` is at most
    ``room``."""
    while tilt > 0 and sin_cos(tilt)[0] * height > room * TURN_ONE:
        tilt -= 500
    return max(tilt, 0)


@dataclass(frozen=True, slots=True)
class _Core:
    """A leaning column fingers hang from: its axis and radius at its foot and at its top."""

    foot: Point
    foot_radius: int
    head: Point
    head_radius: int
    #: The bearing of its head from the island's axis, or None for a core on the axis.
    outward: int | None

    def at(self, z: int) -> tuple[int, int, int]:
        """Its axis's east and north and its radius at height ``z``."""
        span = max(1, self.head[2] - self.foot[2])
        along = min(span, max(0, z - self.foot[2]))
        return (
            self.foot[0] + (self.head[0] - self.foot[0]) * along // span,
            self.foot[1] + (self.head[1] - self.foot[1]) * along // span,
            self.foot_radius + (self.head_radius - self.foot_radius) * along // span,
        )


def _keel(
    key: bytes,
    name: str,
    head: Point,
    head_radius: int,
    foot_radius: int,
    floor: int,
    *,
    outward: int | None,
    toe_most: int | None,
) -> tuple[list[Part], _Core]:
    """A leaning keel from ``head`` (its top's centre) down to ``floor``, and the core fingers hang
    from. ``outward`` is the bearing it leans toward going up (its head farther out than its foot),
    or None for a keel whose head is on the axis, leaned only as far as its taper allows. With
    ``toe_most`` it ends in a blunt, flattened toe block at most that tall, set off its axis;
    without, in its own flat foot."""
    draws = _Draws(key, name)
    parts: list[Part] = []
    if toe_most is None:
        # A lean of at most 9 degrees drops the foot's rim by at most 0.16 of its radius.
        foot_z = floor + foot_radius * 16 // 100
    else:
        toe_tilt = draws.between(3_000, 6_000)
        toe_width = max(1_000, draws.share(foot_radius, 118, 130))
        toe_depth = max(1_000, draws.share(toe_width, 85, 95))
        toe_height = max(1_000, min(toe_most, toe_width * 45 // 100))
        lift = integer_sqrt(toe_width * toe_width + toe_depth * toe_depth) // 2
        toe_floor = floor + lift * sin_cos(toe_tilt)[0] // TURN_ONE
        foot_z = toe_floor + toe_height // 2
    rise = head[2] - foot_z
    tilt = draws.between(4_000, 9_000)
    if outward is None:
        bearing = draws.between(0, _FULL - 1)
        tilt = _lean_within(tilt, rise, (head_radius - foot_radius) * 4 // 5)
    else:
        bearing = outward + draws.between(-20_000, 20_000)
        tilt = _lean_within(tilt, rise, integer_sqrt(head[0] * head[0] + head[1] * head[1]))
    sine, cosine = sin_cos(tilt)
    height = max(1_000, rise * TURN_ONE // cosine)
    east, north = _along(bearing, height * sine // TURN_ONE)
    foot = (head[0] - east, head[1] - north, foot_z)
    parts.append(
        _column(
            name,
            foot,
            height,
            foot_radius,
            head_radius,
            foot_radius // 5,
            tilt=tilt,
            toward=bearing,
            blend=draws.between(1_500, 2_000),
        )
    )
    if toe_most is not None:
        off_east, off_north = _along(draws.between(0, _FULL - 1), draws.share(foot_radius, 5, 10))
        parts.append(
            _box(
                f"{name}_toe",
                (foot[0] + off_east, foot[1] + off_north, toe_floor),
                (toe_width, toe_depth, toe_height),
                draws.between(600, 800),
                yaw=draws.between(0, _FULL - 1),
                tilt=toe_tilt,
                toward=draws.between(0, _FULL - 1),
                blend=min(draws.between(2_500, 3_000), 2 * toe_height),
            )
        )
    return parts, _Core(foot, foot_radius, head, head_radius, outward)


def _roots(key: bytes, island: IslandDocument, slab_base: int) -> list[Part]:
    """Two roots widening upward into the slab, leaning outward, inside the slab's base."""
    rim, below = island.rim_mm, island.depth_mm - island.rim_mm
    parts: list[Part] = []
    first = _Draws(key, "roots").between(0, _FULL - 1)
    for index in (1, 2):
        draws = _Draws(key, f"root_{index}")
        bearing = first + (index - 1) * draws.between(120_000, 240_000)
        foot_radius = max(_least(island) * 3 // 4, draws.share(slab_base, 7, 11))
        head_radius = max(2 * foot_radius, draws.share(slab_base, 30, 40))
        reach = max(0, slab_base * 92 // 100 - head_radius)
        height = max(1_000, draws.share(below, 30, 45))
        tilt = _lean_within(draws.between(12_000, 18_000), height, reach)
        sine, cosine = sin_cos(tilt)
        head_z = -rim + draws.share(rim, 10, 30)
        head_east, head_north = _along(bearing, reach)
        lean_east, lean_north = _along(bearing, height * sine // TURN_ONE)
        foot = (
            head_east - lean_east,
            head_north - lean_north,
            head_z - height * cosine // TURN_ONE,
        )
        parts.append(
            _column(
                f"root_{index}",
                foot,
                height,
                foot_radius,
                head_radius,
                foot_radius // 2,
                tilt=tilt,
                toward=bearing,
                blend=draws.between(1_000, 1_800),
            )
        )
    return parts


def _lumps(key: bytes, island: IslandDocument, slab_base: int) -> list[Part]:
    """Two boxes tilted 18 to 30 degrees outward, straddling the slab's base inside it."""
    rim, below = island.rim_mm, island.depth_mm - island.rim_mm
    parts: list[Part] = []
    first = _Draws(key, "lumps").between(0, _FULL - 1)
    for index in (1, 2):
        draws = _Draws(key, f"lump_{index}")
        bearing = first + (index - 1) * draws.between(120_000, 240_000)
        across = max(500, draws.share(slab_base, 40, 55))
        size = (
            across,
            max(500, draws.share(across, 70, 85)),
            max(500, min(draws.share(slab_base, 35, 45), (rim + below) // 2)),
        )
        half = integer_sqrt(size[0] * size[0] + size[1] * size[1]) // 2
        east, north = _along(bearing, max(0, slab_base * 9 // 10 - half))
        parts.append(
            _box(
                f"lump_{index}",
                (east, north, -rim - draws.share(size[2], 45, 60)),
                size,
                min(size) // 8,
                yaw=draws.between(0, _FULL - 1),
                tilt=draws.between(18_000, 30_000),
                toward=bearing + draws.between(-30_000, 30_000),
                blend=draws.between(900, 1_300),
            )
        )
    return parts


def _underside(
    key: bytes, island: IslandDocument, slab_base: int
) -> tuple[list[Part], list[_Core]]:
    rim, depth = island.rim_mm, island.depth_mm
    least = _least(island)
    if island.underside == "cone":
        draws = _Draws(key, "cone")
        head_radius = draws.share(slab_base, 82, 92)
        foot_radius = min(
            head_radius * 4 // 5,
            max(least, draws.share(head_radius, 40, 48), draws.share(depth, 12, 14)),
        )
        head = (0, 0, -draws.share(rim, 45, 60))
        keel, core = _keel(
            key,
            "keel",
            head,
            head_radius,
            foot_radius,
            -depth,
            outward=None,
            toe_most=max(1_500, min(depth // 9, 12_000)),
        )
        roots = _roots(key, island, slab_base)
        lumps = _lumps(key, island, slab_base)
        return [keel[0], *roots, *lumps, keel[1]], [core]
    if island.underside == "bowl":
        draws = _Draws(key, "bowl")
        head_z = -rim // 2
        height = depth + head_z
        head_radius = draws.share(slab_base, 88, 94)
        foot_radius = max(1_500, draws.share(slab_base, 38, 48))
        east, north = _along(draws.between(0, _FULL - 1), draws.share(slab_base, 0, 8))
        bowl = _column(
            "bowl",
            (east, north, -depth),
            height,
            foot_radius,
            head_radius,
            foot_radius * 7 // 10,
            blend=draws.between(1_500, 2_000),
        )
        core = _Core((east, north, -depth), foot_radius, (east, north, head_z), head_radius, None)
        return [bowl, *_lumps(key, island, slab_base)], [core]
    draws = _Draws(key, "spires")
    count = 3 + draws.between(0, 2)
    first = draws.between(0, _FULL - 1)
    parts: list[Part] = []
    cores: list[_Core] = []
    below = depth - rim
    for index in range(count):
        spire = _Draws(key, f"spire_{index + 1}")
        head_z = -spire.share(rim, 40, 60)
        if index == 0:
            head_radius = max(least * 5 // 4, spire.share(slab_base, 28, 34))
            head = (0, 0, head_z)
            floor, outward = -depth, None
        else:
            head_radius = max(least * 5 // 4, spire.share(slab_base, 24, 32))
            bearing = first + index * _FULL // count + spire.between(-20_000, 20_000)
            east, north = _along(
                bearing, spire.share(max(0, slab_base * 88 // 100 - head_radius), 75, 100)
            )
            head = (east, north, head_z)
            floor, outward = -rim - spire.share(below, 45, 80), bearing
        foot_radius = min(head_radius * 4 // 5, max(least, spire.share(head_radius, 28, 36)))
        made, core = _keel(
            key,
            f"spire_{index + 1}",
            head,
            head_radius,
            foot_radius,
            floor,
            outward=outward,
            toe_most=None,
        )
        parts.extend(made)
        cores.append(core)
    return parts, cores


def _fingers(key: bytes, island: IslandDocument, cores: list[_Core]) -> list[Part]:
    """Thick, blunt limbs hanging from the cores, each leaning outward going up from its foot."""
    rim, depth, least = island.rim_mm, island.depth_mm, _least(island)
    parts: list[Part] = []
    first = _Draws(key, "fingers").between(0, _FULL - 1)
    for index in range(island.fingers):
        draws = _Draws(key, f"finger_{index + 1}")
        core = cores[draws.between(0, len(cores) - 1)]
        if core.outward is None:
            bearing = first + index * _FULL // island.fingers + draws.between(-15_000, 15_000)
        else:
            bearing = core.outward + draws.between(-60_000, 60_000)
        head_z = min(-rim - draws.share(-rim - core.foot[2], 8, 35), core.head[2] - 500)
        east, north, radius = core.at(head_z)
        head_radius = min(radius * 3 // 4, max(least, draws.share(core.head_radius, 16, 24)))
        out_east, out_north = _along(bearing, max(0, radius - head_radius - head_radius // 4))
        height = max(1_500, draws.share(head_z + depth, 30, 55))
        tilt = draws.between(0, 10_000)
        sine, cosine = sin_cos(tilt)
        lean_east, lean_north = _along(bearing, height * sine // TURN_ONE)
        foot_radius = min(head_radius, max(least * 4 // 5, draws.share(head_radius, 65, 80)))
        parts.append(
            _column(
                f"finger_{index + 1}",
                (
                    east + out_east - lean_east,
                    north + out_north - lean_north,
                    head_z - height * cosine // TURN_ONE,
                ),
                height,
                foot_radius,
                head_radius,
                foot_radius // 3,
                tilt=tilt,
                toward=bearing,
                blend=draws.between(300, 500),
            )
        )
    return parts


def _slab(
    part_id: str, at: Point, base: int, top: int, over: int, rounding: int, blend: int, rise: int
) -> Part:
    """A slab from ``base`` radius at its point up to ``top`` radius at the cap's level, reaching
    ``over`` past the cap, where its top is wider still by the same overhang; raised by ``rise``
    above that with the same base and widest radius."""
    height = -at[2] + over
    widest = base + (top - base) * height // -at[2]
    return _column(part_id, at, height + rise, base, widest, rounding, blend=blend)


def _top(key: bytes, island: IslandDocument, rise: int) -> tuple[list[Part], int, list[Point]]:
    """The slab and its lobes, raised by ``rise``, the slab's base radius, and each one's disc at
    the cap's level (east, north, radius)."""
    radius, rim = island.radius_mm, island.rim_mm
    draws = _Draws(key, "slab")
    slab_top = radius * (95 - 3 * island.lobes) // 100 if island.lobes > 1 else radius
    slab_base = draws.share(slab_top, 76, 84)
    rounding = max(300, min(rim // 7, 4_000))
    weathering = int(island.erosion["amplitude_mm"]) + int(island.strata["amplitude_mm"])
    over = rounding + weathering + _OVER_MM
    parts: list[Part] = [_slab("slab", (0, 0, -rim), slab_base, slab_top, over, rounding, 0, rise)]
    discs: list[Point] = [(0, 0, slab_top)]
    lobes = island.lobes - 1
    first = draws.between(0, _FULL - 1)
    for index in range(lobes):
        lobe = _Draws(key, f"lobe_{index + 1}")
        bearing = first + index * _FULL // lobes + lobe.between(-25_000, 25_000)
        distance = lobe.share(radius, 40, 55)
        east, north = _along(bearing, distance)
        top = radius - distance
        floor = lobe.share(rim, 55, 85)
        discs.append((east, north, top))
        parts.append(
            _slab(
                f"lobe_{index + 1}",
                (east, north, -floor),
                lobe.share(top, 74, 82),
                top,
                over,
                min(rounding, floor // 4),
                lobe.between(1_500, 2_500),
                rise,
            )
        )
    return parts, slab_base, discs


def _centred(parts: list[Part], discs: list[Point], drop: int = 0) -> list[Part]:
    """The parts moved level so the box round the top's discs is centred on the origin, and down by
    ``drop``."""
    east = -(min(x - r for x, _, r in discs) + max(x + r for x, _, r in discs)) // 2
    north = -(min(y - r for _, y, r in discs) + max(y + r for _, y, r in discs)) // 2
    for part in parts:
        at = part["at_mm"]
        part["at_mm"] = [at[0] + east, at[1] + north, at[2] - drop]
    return parts


def _square(discs: list[Point]) -> int:
    """The side of the top land's square: the box round the top's discs grown by a tenth, in whole
    2 m."""
    across = max(
        max(x + r for x, _, r in discs) - min(x - r for x, _, r in discs),
        max(y + r for _, y, r in discs) - min(y - r for _, y, r in discs),
    )
    return -(-(across * 11 // 10) // _SQUARE_STEP_MM) * _SQUARE_STEP_MM


def make_island_volume(island: IslandDocument, seed: bytes) -> VolumeDocument:
    """The island as a volume: its slab and lobes, its underside, its fingers, capped flat at 0 or
    by its top land."""
    key = hashlib.sha256(PROFILE.encode() + b"\x1f" + seed + b"\x1f" + island.id.encode()).digest()
    blend = max(400, min(island.rim_mm // 8, 1_200))
    top_land: TopLand | None = None
    drop = rise = 0
    if island.top is not None:
        _, _, outline = _top(key, island, 0)
        top_land = TopLand(land=island.top, side_mm=_square(outline), blend_mm=blend)
        surface = TopLandSurface(top_land, island.id)
        drop = max(0, -surface.lowest)
        rise = max(0, surface.highest) + drop
    top, slab_base, discs = _top(key, island, rise)
    underside, cores = _underside(key, island, slab_base)
    fingers = _fingers(key, island, cores)
    catalog = volume_catalog(island.volume_catalog_version)
    parts = _centred([*top, *underside, *fingers], discs, drop)
    raw: dict[str, Any] = {
        "profile": VOLUME_PROFILE,
        "id": island.id,
        "look": island.look,
        "top_look": island.top_look,
        "walk": island.walk,
        "erosion": dict(island.erosion),
        "strata": dict(island.strata),
        "parts": parts,
    }
    if top_land is None:
        parts.append({"id": "top", "shape": "cap", "height_mm": 0, "blend_mm": blend})
    else:
        raw["top_land"] = {
            "land": top_land.land.canonical(),
            "side_mm": top_land.side_mm,
            "blend_mm": top_land.blend_mm,
        }
    return read_volume_document(raw, catalog)
