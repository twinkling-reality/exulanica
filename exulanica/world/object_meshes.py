"""Form parts as integer triangles in an object's own frame.

A catalog kind (:mod:`exulanica.world.object_catalog`) states its shape as the city grammar's form
parts, and this module turns them into triangles by the grammar's own rule, as
``web/packages/loom-tess/src/core/form-parts.ts`` implements it for a street: the same integer
circle, the same outlines and the same surface frames, for one object standing at the origin and
facing its own ``+x``. At that pose the grammar's measure moves a half millimetre ``h`` along an
axis to ``floor(h / 2)``, so a vertex here is the tessellator's vertex for that object.

**No floating point.** Every position, surface coordinate and direction below is an integer: the
circle is built by chord bisection from the four axis points, with the grammar's integer measure
at ``S = 10**6``, so no sine is taken and the triangles are the same on every machine. Directions
are left unnormalised; the writer that packs them for a renderer normalises them.

**Surface frames**, as the grammar fixes them for an object part: a side takes ``s`` as the
distance walked round the part from its local ``+x`` (walked once, round its widest ring, so a
meridian keeps its ``s`` from bottom to top) and ``t = base - z``; a top takes ``s = +x`` and
``t = +y``; an underside ``s = +x`` and ``t = -y``; an ellipsoid triangle takes the frame its own
normal leans towards, at 45 degrees exactly.

**What this adds to the tessellator** is a direction at each vertex, for lighting. A box face and
a cap are flat, so each takes its face's normal. A prism's side and an ellipsoid are the surfaces
their parts describe (an elliptic cylinder or cone, an ellipsoid), so each vertex takes that
surface's normal at its meridian, and the facets shade round. The tangent is the direction ``s``
increases in, which a normal map needs.
"""

from __future__ import annotations

import functools
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from exulanica.grammar.grammars.city.common import FormPart

__all__ = [
    "FormTriangle",
    "FormVertex",
    "PlanExtent",
    "SurfaceFrame",
    "form_triangles",
    "parts_extent",
    "unit_circle",
]

#: The scale the grammar's integer measure works at (``corners.py``, ``form-parts.ts``).
SCALE: Final = 1_000_000
#: A part's top scale is in millionths (``common.py``).
MILLIONTHS: Final = 1_000_000

SurfaceFrame = Literal["vertical", "top", "underside"]
Direction = tuple[int, int, int]
_Plan = tuple[int, int]


@dataclass(frozen=True, slots=True)
class FormVertex:
    """One corner of a triangle: where it is, its surface coordinates, and its directions."""

    x_mm: int
    y_mm: int
    z_mm: int
    s_mm: int
    t_mm: int
    #: The outward surface direction at this corner, exact and unnormalised.
    normal: Direction
    #: The direction ``s`` increases in, exact and unnormalised.
    tangent: Direction


@dataclass(frozen=True, slots=True)
class FormTriangle:
    """A triangle, counter-clockwise seen from outside, and the frame its ``s`` and ``t`` use."""

    surface_role: str
    frame: SurfaceFrame
    vertices: tuple[FormVertex, FormVertex, FormVertex]


@dataclass(frozen=True, slots=True)
class PlanExtent:
    """The box every vertex of some parts lies in, in the part frame's millimetres."""

    min_x: int
    min_y: int
    min_z: int
    max_x: int
    max_y: int
    max_z: int


def _move(vector: _Plan, halves: int) -> _Plan:
    """The grammar's measure: how far to move on each axis to travel ``halves / 2`` along ``v``."""
    length = math.isqrt((vector[0] ** 2 + vector[1] ** 2) * SCALE * SCALE)
    if length == 0:
        raise ValueError("a direction of zero length has no measure")
    return (
        (vector[0] * halves * SCALE) // (2 * length),
        (vector[1] * halves * SCALE) // (2 * length),
    )


@functools.cache
def unit_circle(count: int) -> tuple[_Plan, ...]:
    """``count`` points of the circle of radius ``SCALE``, first on ``+x``, counter-clockwise.

    Built by chord bisection from the four axis points, so ``count`` is a power of two of at
    least four: each bisection inserts the normalised sum of two neighbours between them.
    """
    if count < 4 or count & (count - 1):
        raise ValueError(f"a circle is built for a power of two of at least 4, not {count}")
    points: list[_Plan] = [(SCALE, 0), (0, SCALE), (-SCALE, 0), (0, -SCALE)]
    while len(points) < count:
        bisected: list[_Plan] = []
        for index, here in enumerate(points):
            after = points[(index + 1) % len(points)]
            bisected.append(here)
            bisected.append(_move((here[0] + after[0], here[1] + after[1]), 2 * SCALE))
        points = bisected
    return tuple(points)


@dataclass(frozen=True, slots=True)
class _Ring:
    """A part's plan outline at one height, in half millimetres, and the walk ``s`` measures."""

    points: tuple[_Plan, ...]
    around: tuple[int, ...]
    height_halves: int


def _plan_distance(start: _Plan, end: _Plan) -> int:
    return math.isqrt((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2)


def _ring(points: Sequence[_Plan], height_halves: int) -> _Ring:
    around = [0]
    for index in range(1, len(points)):
        around.append(around[-1] + _plan_distance(points[index - 1], points[index]))
    return _Ring(tuple(points), tuple(around), height_halves)


def _reference_around(rings: Sequence[_Ring]) -> tuple[int, ...]:
    """The walk round the ring with the longest outline, closed, for every ring of a part."""
    best, longest = rings[0], -1
    for ring in rings:
        perimeter = ring.around[-1] + _plan_distance(ring.points[-1], ring.points[0])
        if perimeter > longest:
            best, longest = ring, perimeter
    return (*best.around, longest)


def _world(plan: _Plan, height_halves: int) -> tuple[int, int, int]:
    """A half-millimetre point, in whole millimetres where the grammar's measure puts it."""
    return (plan[0] // 2, plan[1] // 2, height_halves // 2)


def _vertex(
    plan: _Plan,
    height_halves: int,
    frame: SurfaceFrame,
    around_halves: int,
    normal: Direction,
    tangent: Direction,
) -> FormVertex:
    x, y, z = _world(plan, height_halves)
    if frame == "vertical":
        s, t = around_halves // 2, -z
    elif frame == "top":
        s, t = x, y
    elif frame == "underside":
        s, t = x, -y
    else:
        raise ValueError(f"a surface frame is vertical, top or underside, not {frame!r}")
    return FormVertex(x, y, z, s, t, normal, tangent)


def _frame_by_normal(corners: Sequence[tuple[_Plan, int]]) -> SurfaceFrame:
    """Horizontal while a face's normal leans less than 45 degrees from vertical; exact."""
    points = [_world(plan, height) for plan, height in corners]
    u = tuple(points[2][axis] - points[0][axis] for axis in range(3))
    v = tuple(points[3][axis] - points[1][axis] for axis in range(3))
    nx = u[1] * v[2] - u[2] * v[1]
    ny = u[2] * v[0] - u[0] * v[2]
    nz = u[0] * v[1] - u[1] * v[0]
    if nz * nz < nx * nx + ny * ny:
        return "vertical"
    return "top" if nz > 0 else "underside"


#: The directions of a side's corner: the face it bounds, its meridian, which of the two rings it
#: lies on (0 the lower, 1 the upper), and the frame the face takes.
_SideDirections = Callable[[int, int, int, SurfaceFrame], tuple[Direction, Direction]]

_UP: Final = (0, 0, 1)
_DOWN: Final = (0, 0, -1)
#: The direction ``t`` increases in on a top (``t = +y``) and on an underside (``t = -y``).
_T_AXIS: Final[dict[SurfaceFrame, Direction]] = {"top": (0, 1, 0), "underside": (0, -1, 0)}


def _cross(a: Direction, b: Direction) -> Direction:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _flat_tangent(frame: SurfaceFrame, normal: Direction) -> Direction:
    """Where ``s = x`` increases along a top or an underside with this normal, ``t`` held.

    Holding ``t`` keeps a point in a plane of constant ``y``, so the direction is perpendicular to
    both that axis and the normal: ``cross(t_axis, normal)``, which is ``+x`` on a flat top or
    underside. Where the normal is along ``y`` the surface is that plane and ``s`` alone moves along
    it, so the direction is ``+x`` made perpendicular to the normal.
    """
    tangent = _cross(_T_AXIS[frame], normal)
    if tangent != (0, 0, 0):
        return tangent
    along = normal[0]
    length = normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2
    return (length - normal[0] * along, -normal[1] * along, -normal[2] * along)


def _side_triangles(
    role: str,
    lower: _Ring,
    upper: _Ring,
    around: Sequence[int],
    by_normal: bool,
    directions: _SideDirections,
) -> list[FormTriangle]:
    """The walls between two rings of the same count, counter-clockwise seen from outside.

    Where a ring's two corners coincide, at a cone's apex or an ellipsoid's pole, only the triangle
    the quad has left is made: a zero-area triangle is never emitted.
    """
    out: list[FormTriangle] = []
    count = len(lower.points)
    for index in range(count):
        following = (index + 1) % count
        around_here = around[index]
        around_next = around[count] if following == 0 else around[following]
        corners = (
            (lower.points[index], lower.height_halves),
            (lower.points[following], lower.height_halves),
            (upper.points[following], upper.height_halves),
            (upper.points[index], upper.height_halves),
        )
        frame: SurfaceFrame = _frame_by_normal(corners) if by_normal else "vertical"
        # Each corner: which of the four, how far round, its meridian, and which ring it lies on.
        a, b, c, d = (
            _vertex(*corners[corner], frame, walk, *directions(index, meridian, ring, frame))
            for corner, walk, meridian, ring in (
                (0, around_here, index, 0),
                (1, around_next, following, 0),
                (2, around_next, following, 1),
                (3, around_here, index, 1),
            )
        )
        if corners[0] == corners[1]:
            out.append(FormTriangle(role, frame, (a, c, d)))
        elif corners[2] == corners[3]:
            out.append(FormTriangle(role, frame, (a, b, c)))
        else:
            out.append(FormTriangle(role, frame, (a, b, c)))
            out.append(FormTriangle(role, frame, (a, c, d)))
    return out


def _cap_triangles(role: str, ring: _Ring, up: bool) -> list[FormTriangle]:
    """A convex ring as a fan, facing up when ``up`` and down otherwise; flat."""
    frame: SurfaceFrame = "top" if up else "underside"
    normal = _UP if up else _DOWN
    out: list[FormTriangle] = []
    points = ring.points
    for index in range(1, len(points) - 1):
        a, b, c = (
            _vertex(point, ring.height_halves, frame, 0, normal, _flat_tangent(frame, normal))
            for point in (points[0], points[index], points[index + 1])
        )
        out.append(FormTriangle(role, frame, (a, b, c) if up else (a, c, b)))
    return out


def _plan_outline(part: FormPart, scale_millionths: int) -> tuple[_Plan, ...]:
    """A prism's outline at a scale in millionths, inside its size ellipse, in half millimetres."""
    offset_x, offset_y = 2 * part.offset_x_mm, 2 * part.offset_y_mm
    return tuple(
        (
            offset_x + (part.size_x_mm * px * scale_millionths) // (SCALE * MILLIONTHS),
            offset_y + (part.size_y_mm * py * scale_millionths) // (SCALE * MILLIONTHS),
        )
        for px, py in unit_circle(part.segments)
    )


def _box_outline(part: FormPart) -> tuple[_Plan, ...]:
    """A box's corners in plan, half millimetres, counter-clockwise from ``(+x, -y)``."""
    offset_x, offset_y = 2 * part.offset_x_mm, 2 * part.offset_y_mm
    half_x, half_y = part.size_x_mm, part.size_y_mm
    return (
        (offset_x + half_x, offset_y - half_y),
        (offset_x + half_x, offset_y + half_y),
        (offset_x - half_x, offset_y + half_y),
        (offset_x - half_x, offset_y - half_y),
    )


def _box_triangles(part: FormPart) -> list[FormTriangle]:
    outline = _box_outline(part)
    bottom = _ring(outline, 2 * part.offset_z_mm)
    top = _ring(outline, 2 * (part.offset_z_mm + part.size_z_mm))

    def flat(
        face: int, meridian: int, ring: int, frame: SurfaceFrame
    ) -> tuple[Direction, Direction]:
        # A box face is flat: every corner of the face from corner ``face`` to the next takes the
        # face's outward normal, its edge turned a quarter clockwise in plan, and the edge itself
        # as the direction ``s`` walks.
        del meridian, ring, frame
        start, end = outline[face], outline[(face + 1) % len(outline)]
        edge = (end[0] - start[0], end[1] - start[1])
        return (edge[1], -edge[0], 0), (edge[0], edge[1], 0)

    return [
        *_side_triangles(
            part.surface_role, bottom, top, _reference_around((bottom, top)), False, flat
        ),
        *_cap_triangles(part.surface_role, top, True),
        *_cap_triangles(part.surface_role, bottom, False),
    ]


def _prism_triangles(part: FormPart) -> list[FormTriangle]:
    circle = unit_circle(part.segments)
    bottom = _ring(_plan_outline(part, MILLIONTHS), 2 * part.offset_z_mm)
    top_halves = 2 * (part.offset_z_mm + part.size_z_mm)
    taper = MILLIONTHS - part.top_scale_millionths

    def smooth(
        face: int, meridian: int, ring: int, frame: SurfaceFrame
    ) -> tuple[Direction, Direction]:
        # The surface a prism describes is an elliptic cylinder, or a cone where it tapers. With
        # semi-axes a, b, height h and top scale k its normal at meridian (cos, sin) is
        # (b h cos, a h sin, (1 - k) a b), here multiplied through by 4 S M to stay integral.
        del face, ring, frame
        cx, cy = circle[meridian % len(circle)]
        normal = (
            2 * part.size_y_mm * part.size_z_mm * cx * MILLIONTHS,
            2 * part.size_x_mm * part.size_z_mm * cy * MILLIONTHS,
            taper * part.size_x_mm * part.size_y_mm * SCALE,
        )
        return normal, (-part.size_x_mm * cy, part.size_y_mm * cx, 0)

    if part.top_scale_millionths == 0:
        # A cone: every top point is the axis, so each side is one triangle and there is no top.
        apex = (2 * part.offset_x_mm, 2 * part.offset_y_mm)
        top = _ring(tuple(apex for _ in bottom.points), top_halves)
        return [
            *_side_triangles(
                part.surface_role, bottom, top, _reference_around((bottom,)), False, smooth
            ),
            *_cap_triangles(part.surface_role, bottom, False),
        ]
    top = _ring(_plan_outline(part, part.top_scale_millionths), top_halves)
    return [
        *_side_triangles(
            part.surface_role, bottom, top, _reference_around((bottom, top)), False, smooth
        ),
        *_cap_triangles(part.surface_role, top, True),
        *_cap_triangles(part.surface_role, bottom, False),
    ]


def _ellipsoid_triangles(part: FormPart) -> list[FormTriangle]:
    meridians = unit_circle(part.segments)
    # The latitudes are multiples of 180 / rings degrees, the points of the 2 * rings circle:
    # band j is that circle's point j - rings / 2, counting from the bottom pole.
    latitudes = unit_circle(2 * part.rings)
    offset_x, offset_y = 2 * part.offset_x_mm, 2 * part.offset_y_mm
    centre_halves = 2 * part.offset_z_mm + part.size_z_mm

    def latitude(band: int) -> _Plan:
        return latitudes[(band - part.rings // 2) % len(latitudes)]

    def band_ring(band: int) -> _Ring:
        cosine, sine = latitude(band)
        points = tuple(
            (
                offset_x + (part.size_x_mm * mx * cosine) // (SCALE * SCALE),
                offset_y + (part.size_y_mm * my * cosine) // (SCALE * SCALE),
            )
            for mx, my in meridians
        )
        return _ring(points, centre_halves + (part.size_z_mm * sine) // SCALE)

    bands = [band_ring(band) for band in range(part.rings + 1)]
    around = _reference_around(bands)
    out: list[FormTriangle] = []
    for band in range(part.rings):

        def smooth(
            face: int, meridian: int, ring: int, frame: SurfaceFrame, band: int = band
        ) -> tuple[Direction, Direction]:
            # The ellipsoid's own normal at (cos lat cos lon, cos lat sin lon, sin lat) scaled by
            # its semi-axes is (cos lat cos lon / a, cos lat sin lon / b, sin lat / c), here
            # multiplied through by the three sizes to stay integral.
            del face
            lx, ly = latitude(band + ring)
            mx, my = meridians[meridian % len(meridians)]
            normal = (
                lx * mx * part.size_y_mm * part.size_z_mm,
                lx * my * part.size_x_mm * part.size_z_mm,
                ly * SCALE * part.size_x_mm * part.size_y_mm,
            )
            if frame != "vertical":
                return normal, _flat_tangent(frame, normal)
            return normal, (-part.size_x_mm * my, part.size_y_mm * mx, 0)

        out.extend(
            _side_triangles(part.surface_role, bands[band], bands[band + 1], around, True, smooth)
        )
    return out


def form_triangles(parts: Sequence[FormPart]) -> tuple[FormTriangle, ...]:
    """Every triangle ``parts`` make, in the object's own frame, part by part.

    A part the grammar would refuse is refused here by name, never defaulted: the catalog holds
    its parts to the grammar's shape rules before they reach this function.
    """
    out: list[FormTriangle] = []
    for part in parts:
        if part.shape == "box":
            out.extend(_box_triangles(part))
        elif part.shape == "prism":
            out.extend(_prism_triangles(part))
        elif part.shape == "ellipsoid":
            out.extend(_ellipsoid_triangles(part))
        else:
            raise ValueError(f"a form part is a box, a prism or an ellipsoid, not {part.shape!r}")
    return tuple(out)


def parts_extent(parts: Sequence[FormPart]) -> PlanExtent:
    """The box every vertex of ``parts`` lies in, exactly as the triangles place them."""
    vertices = [vertex for triangle in form_triangles(parts) for vertex in triangle.vertices]
    if not vertices:
        raise ValueError("parts with no triangles have no extent")
    return PlanExtent(
        min(vertex.x_mm for vertex in vertices),
        min(vertex.y_mm for vertex in vertices),
        min(vertex.z_mm for vertex in vertices),
        max(vertex.x_mm for vertex in vertices),
        max(vertex.y_mm for vertex in vertices),
        max(vertex.z_mm for vertex in vertices),
    )
