"""Where people can stand on a volume: its walkable tops, ``exulanica.volume-sheet/v1``.

Only the topmost face of a volume is walked: undersides, cliff faces and the soffits of overhangs
never are, and a volume whose ``walk`` is ``none`` has no tops. On the 1 m lattice of the volume's
own frame, in whole numbers:

* **The top of a column** is found from above. A column is searched only where an added part can
  reach it (:attr:`~exulanica.grammar.volumes.field.VolumeField.extent` and each part's reach), from
  just above the highest such reach downward, each step as long as the air round the point is
  certain (:meth:`~exulanica.grammar.volumes.field.VolumeField.air_reach`) and never shorter than
  :data:`SEARCH_STEP_MM`, then by halving to the millimetre: the highest height whose field is at
  most zero below air. A solid thinner than the shortest step can be stepped over; nothing that
  thin is stood on.
* **A cell is walkable** when its four corners have tops, no edge between them climbs more than 1 in
  4 (the land's walking grade, :data:`~exulanica.grammar.landform.WALK_GRADE_PERMILLE`), and each
  corner has headroom: the field :data:`HEAD_MM` above its top is at least :data:`CLEAR_MM`, so no
  solid of the volume lies within that distance of a standing person's head.
* **Each 4-connected set of walkable cells is a surface** named ``top:<n>`` in the order its first
  cell comes from the south-west, row by row. A sheet holds the heights on its rectangle's lattice
  (a point with no top takes the sheet's lowest height, under a cell that is not walkable) and its
  walkable cells as runs per row.

Turning a sheet into exact contact geometry (``heightfield-geometry/v1``) is the walking layer's;
this module only states where the tops are. A sheet is a pure function of the volume document, the
seed, the volume rules its field is evaluated by and any heights given for its top, named by
:func:`~exulanica.grammar.volumes.realize.input_sha256` and its ``rules_version``; a sheet of any
rules this server serves reads back. Its identity is the SHA-256 of its canonical JSON.
"""

from __future__ import annotations

import functools
import hashlib
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar.landform import WALK_GRADE_PERMILLE
from exulanica.grammar.volumes.document import VolumeRefused
from exulanica.grammar.volumes.field import VolumeField
from exulanica.grammar.volumes.realize import input_sha256
from exulanica.grammar.volumes.rules import SERVED_VOLUME_RULES

__all__ = [
    "CLEAR_MM",
    "HEAD_MM",
    "SEARCH_STEP_MM",
    "SHEET_CELL_MM",
    "SHEET_PROFILE",
    "VolumeSheet",
    "read_volume_sheet",
    "volume_tops",
]

SHEET_PROFILE: Final = "exulanica.volume-sheet/v1"
#: The lattice a top is found on.
SHEET_CELL_MM: Final = 1_000
#: The step a column is searched down by before halving to the millimetre.
SEARCH_STEP_MM: Final = 250
#: Where a standing person's head is above a top, and how clear of solid it stays.
HEAD_MM: Final = 1_200
CLEAR_MM: Final = 1_000
#: The most an edge of a walkable cell climbs.
_RISE_MM: Final = SHEET_CELL_MM * WALK_GRADE_PERMILLE // 1000
#: Heights a sheet may state: within the reach of any part of a volume.
_HEIGHT_BOUND_MM: Final = 4_000_000
_KEYS: Final = frozenset(
    {
        "profile",
        "input_sha256",
        "volume_sha256",
        "rules_version",
        "surface",
        "origin_mm",
        "cell_mm",
        "columns",
        "rows",
        "height_mm",
        "walkable",
    }
)


@dataclass(frozen=True)
class VolumeSheet:
    """One walkable top of a volume: heights on a rectangle of the 1 m lattice, rows from the
    south, and its walkable cells as ``(row, first column, last column)`` runs."""

    input_sha256: str
    volume_sha256: str
    rules_version: int
    surface: str
    origin_mm: tuple[int, int]
    columns: int
    rows: int
    height_mm: tuple[int, ...]
    walkable: tuple[tuple[int, int, int], ...]

    def document(self) -> dict[str, Any]:
        return {
            "profile": SHEET_PROFILE,
            "input_sha256": self.input_sha256,
            "volume_sha256": self.volume_sha256,
            "rules_version": self.rules_version,
            "surface": self.surface,
            "origin_mm": list(self.origin_mm),
            "cell_mm": SHEET_CELL_MM,
            "columns": self.columns,
            "rows": self.rows,
            "height_mm": list(self.height_mm),
            "walkable": [list(run) for run in self.walkable],
        }

    @functools.cached_property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_json(self.document())).hexdigest()

    @property
    def cells(self) -> int:
        return sum(last - first + 1 for _, first, last in self.walkable)


def _top(field: VolumeField, x: int, y: int) -> int | None:
    """The top of the column at ``(x, y)``, or None where no solid is reached."""
    reaching = [
        solid.reach
        for solid in field.solids
        if not solid.carves
        and solid.reach[0][0] <= x <= solid.reach[1][0]
        and solid.reach[0][1] <= y <= solid.reach[1][1]
    ]
    if not reaching:
        return None
    ceiling = min(max(high[2] for _, high in reaching), field.extent[1][2]) + 1
    floor = min(low[2] for low, _ in reaching)
    air = ceiling
    z = ceiling - max(SEARCH_STEP_MM, field.air_reach(x, y, ceiling))
    while z >= floor - SEARCH_STEP_MM:
        if field.distance(x, y, z) <= 0:
            solid = z
            while air - solid > 1:
                middle = (air + solid) // 2
                if field.distance(x, y, middle) <= 0:
                    solid = middle
                else:
                    air = middle
            return solid
        air, z = z, z - max(SEARCH_STEP_MM, field.air_reach(x, y, z))
    return None


def volume_tops(field: VolumeField) -> tuple[VolumeSheet, ...]:
    """The volume's walkable tops, ``top:0`` first; none when it is not walked."""
    if field.document.walk != "tops":
        return ()
    cell = SHEET_CELL_MM
    (low_x, low_y, _), (high_x, high_y, _) = field.extent
    x0, y0 = -(-low_x // cell) * cell, -(-low_y // cell) * cell
    nx, ny = (high_x - x0) // cell + 1, (high_y - y0) // cell + 1
    if nx < 2 or ny < 2:
        return ()
    tops = [_top(field, x0 + i * cell, y0 + j * cell) for j in range(ny) for i in range(nx)]
    clear = []
    for j in range(ny):
        for i in range(nx):
            top = tops[j * nx + i]
            head = (
                None if top is None else field.distance(x0 + i * cell, y0 + j * cell, top + HEAD_MM)
            )
            clear.append(head is not None and head >= CLEAR_MM)

    def walkable(i: int, j: int) -> bool:
        corners = [(j + dj) * nx + i + di for dj in (0, 1) for di in (0, 1)]
        heights = [height for height in (tops[corner] for corner in corners) if height is not None]
        if len(heights) < 4 or not all(clear[corner] for corner in corners):
            return False
        a, b, c, d = heights
        return max(abs(a - b), abs(c - d), abs(a - c), abs(b - d)) <= _RISE_MM

    open_cells = {(i, j) for j in range(ny - 1) for i in range(nx - 1) if walkable(i, j)}
    sheets: list[VolumeSheet] = []
    seen: set[tuple[int, int]] = set()
    for j in range(ny - 1):
        for i in range(nx - 1):
            if (i, j) not in open_cells or (i, j) in seen:
                continue
            component, frontier = [], [(i, j)]
            seen.add((i, j))
            while frontier:
                ci, cj = frontier.pop()
                component.append((ci, cj))
                for neighbour in ((ci + 1, cj), (ci - 1, cj), (ci, cj + 1), (ci, cj - 1)):
                    if neighbour in open_cells and neighbour not in seen:
                        seen.add(neighbour)
                        frontier.append(neighbour)
            sheets.append(_sheet(field, len(sheets), component, tops, nx, (x0, y0)))
    return tuple(sheets)


def _sheet(
    field: VolumeField,
    number: int,
    component: list[tuple[int, int]],
    tops: list[int | None],
    nx: int,
    origin: tuple[int, int],
) -> VolumeSheet:
    i0, i1 = min(i for i, _ in component), max(i for i, _ in component)
    j0, j1 = min(j for _, j in component), max(j for _, j in component)
    columns, rows = i1 - i0 + 2, j1 - j0 + 2
    stated = [tops[(j0 + j) * nx + i0 + i] for j in range(rows) for i in range(columns)]
    lowest = min(height for height in stated if height is not None)
    cells = set(component)
    runs: list[tuple[int, int, int]] = []
    for j in range(j0, j1 + 1):
        i = i0
        while i <= i1:
            if (i, j) in cells:
                first = i
                while i + 1 <= i1 and (i + 1, j) in cells:
                    i += 1
                runs.append((j - j0, first - i0, i - i0))
            i += 1
    return VolumeSheet(
        input_sha256=input_sha256(field),
        volume_sha256=field.document.sha256,
        rules_version=field.rules,
        surface=f"top:{number}",
        origin_mm=(origin[0] + i0 * SHEET_CELL_MM, origin[1] + j0 * SHEET_CELL_MM),
        columns=columns,
        rows=rows,
        height_mm=tuple(lowest if height is None else height for height in stated),
        walkable=tuple(runs),
    )


def read_volume_sheet(raw: object, expected_sha256: str | None = None) -> VolumeSheet:
    """Admit a sheet document, or refuse it by path; with ``expected_sha256``, only the sheet that
    digest names."""
    if not isinstance(raw, dict) or set(raw) != _KEYS:
        raise VolumeRefused(f"a volume sheet has exactly {sorted(_KEYS)}")
    if raw["profile"] != SHEET_PROFILE:
        raise VolumeRefused(f"profile is {SHEET_PROFILE}", path="profile")
    for name in ("input_sha256", "volume_sha256"):
        digest = raw[name]
        if not (
            isinstance(digest, str)
            and len(digest) == 64
            and all(ch in "0123456789abcdef" for ch in digest)
        ):
            raise VolumeRefused(f"{name} is a SHA-256 in lowercase hex", path=name)
    rules = raw["rules_version"]
    if type(rules) is not int or rules not in SERVED_VOLUME_RULES:
        served = ", ".join(str(version) for version in SERVED_VOLUME_RULES)
        raise VolumeRefused(
            f"this server reads sheets of volume rules versions {served}, got {rules!r}",
            path="rules_version",
            code="volume_rules_changed",
        )
    surface = raw["surface"]
    if not (
        isinstance(surface, str)
        and surface.startswith("top:")
        and surface[4:].isdigit()
        and str(int(surface[4:])) == surface[4:]
    ):
        raise VolumeRefused(f"surface is top:<n>, got {surface!r}", path="surface")
    origin = raw["origin_mm"]
    if not (
        isinstance(origin, list)
        and len(origin) == 2
        and all(type(v) is int and -_HEIGHT_BOUND_MM <= v <= _HEIGHT_BOUND_MM for v in origin)
    ):
        raise VolumeRefused("origin_mm is two whole numbers", path="origin_mm")
    if raw["cell_mm"] != SHEET_CELL_MM or type(raw["cell_mm"]) is not int:
        raise VolumeRefused(f"a v1 sheet's cell is {SHEET_CELL_MM} mm", path="cell_mm")
    columns, rows = raw["columns"], raw["rows"]
    if not all(type(v) is int and 2 <= v <= 2_401 for v in (columns, rows)):
        raise VolumeRefused("columns and rows are 2 to 2401 lattice points", path="columns")
    heights = raw["height_mm"]
    if not (
        isinstance(heights, list)
        and len(heights) == columns * rows
        and all(type(h) is int and -_HEIGHT_BOUND_MM <= h <= _HEIGHT_BOUND_MM for h in heights)
    ):
        raise VolumeRefused("height_mm is a whole number at every lattice point", path="height_mm")
    runs = raw["walkable"]
    if not isinstance(runs, list) or not runs:
        raise VolumeRefused("walkable lists at least one run", path="walkable")
    read_runs: list[tuple[int, int, int]] = []
    for index, run in enumerate(runs):
        if not (
            isinstance(run, list)
            and len(run) == 3
            and all(type(v) is int for v in run)
            and 0 <= run[0] < rows - 1
            and 0 <= run[1] <= run[2] < columns - 1
            and (not read_runs or (run[0], run[1]) > (read_runs[-1][0], read_runs[-1][2] + 1))
        ):
            raise VolumeRefused(
                "a run is a row and its first and last cells, in order, not touching the one "
                "before it",
                path=f"walkable[{index}]",
            )
        read_runs.append((run[0], run[1], run[2]))
    out = VolumeSheet(
        input_sha256=raw["input_sha256"],
        volume_sha256=raw["volume_sha256"],
        rules_version=rules,
        surface=surface,
        origin_mm=(origin[0], origin[1]),
        columns=columns,
        rows=rows,
        height_mm=tuple(heights),
        walkable=tuple(read_runs),
    )
    if expected_sha256 is not None and out.sha256 != expected_sha256:
        raise VolumeRefused(
            "the sheet is not the one its digest names", code="volume_digest_mismatch"
        )
    return out
