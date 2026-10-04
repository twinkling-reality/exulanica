"""Look roles, fit rules and budgets: what a generated piece is for and what it may weigh.

A look role is ``family.leaf``. The families are a closed list shared by world kinds, style packs and
generated assets; leaves are open, so a drafted kind may name ``structure.milking_parlour``. Each
family has one fit rule, which says how a piece meets its slot:

- ``contain``: uniform scale until the piece fits inside the slot, base on the floor;
- ``fill``: the page stretches the piece to the slot, each axis within 0.8 to 1.25 of the piece's
  own size, so a piece for such a slot must already be close to it;
- ``tile``: one module repeated along the slot's width (a fence, a moulding);
- ``surface``: a material, never a mesh.

Generation makes meshes for the families in :data:`GENERATED_FAMILIES` only. Characters and animals
need rigs and motion, whole structures would move the doors and windows a kind fixes, and surface
families are materials, which the texture path makes.

The budgets are the style pack format's per-family budgets for one piece at its first level of
detail. They are provisional until the pack format is approved, and they sit on top of the
container limits the static profile already holds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from exulanica_appearance.canonical import Refused

__all__ = [
    "BUDGETS",
    "BUDGETS_STATUS",
    "FAMILIES",
    "FILL_RATIO_PER_MILLE",
    "FIT",
    "GENERATED_FAMILIES",
    "Budget",
    "budget_for",
    "split_role",
]

FAMILIES: Final = frozenset(
    {
        "ground",
        "path",
        "road",
        "water",
        "structure",
        "roof",
        "wall",
        "door",
        "window",
        "fixture",
        "prop",
        "plant",
        "boundary",
        "vehicle",
        "animal",
        "character",
    }
)

FIT: Final = MappingProxyType(
    {
        "fixture": "contain",
        "prop": "contain",
        "plant": "contain",
        "vehicle": "contain",
        "animal": "contain",
        "structure": "contain",
        "door": "fill",
        "window": "fill",
        "boundary": "tile",
        "ground": "surface",
        "path": "surface",
        "road": "surface",
        "water": "surface",
        "wall": "surface",
        "roof": "surface",
    }
)

GENERATED_FAMILIES: Final = frozenset(
    {"fixture", "prop", "plant", "vehicle", "boundary", "door", "window"}
)

#: A fill slot stretches each axis of a piece by at most this much either way, in per mille.
FILL_RATIO_PER_MILLE: Final = (800, 1250)

_ROLE: Final = re.compile(r"([a-z]+)\.([a-z][a-z0-9_]{0,63})")


@dataclass(frozen=True, slots=True)
class Budget:
    """One piece's ceiling. ``triangles`` is per metre of run for a tiled family."""

    triangles: int
    materials: int
    texture_side_px: int
    glb_bytes: int
    per_metre: bool = False

    def document(self) -> dict[str, int | bool]:
        return {
            "glb_bytes": self.glb_bytes,
            "materials": self.materials,
            "per_metre": self.per_metre,
            "texture_side_px": self.texture_side_px,
            "triangles": self.triangles,
        }


BUDGETS_STATUS: Final = (
    "provisional: the style pack format's numbers, until that format is approved"
)

#: Kilobytes in the pack format's table are read as 1,000 bytes, the smaller reading.
BUDGETS: Final = MappingProxyType(
    {
        "window": Budget(400, 2, 256, 64_000),
        "door": Budget(1_500, 3, 512, 160_000),
        "fixture": Budget(1_500, 2, 256, 160_000),
        "prop": Budget(1_500, 2, 256, 160_000),
        "plant": Budget(3_000, 2, 512, 300_000),
        "plant.shrub": Budget(800, 2, 512, 300_000),
        "vehicle": Budget(4_000, 3, 512, 400_000),
        "boundary": Budget(200, 2, 256, 64_000, per_metre=True),
    }
)

#: Vertices a piece may hold, as a multiple of its triangle ceiling.
VERTICES_PER_TRIANGLE: Final = 3


def split_role(role: object) -> tuple[str, str]:
    """``family.leaf`` split, or a refusal: the family must be one of the closed list."""
    match = _ROLE.fullmatch(role) if isinstance(role, str) else None
    if match is None:
        raise Refused(f"look role {role!r} is not family.leaf in lower case")
    family, leaf = match.group(1), match.group(2)
    if family not in FAMILIES:
        raise Refused(f"look role {role!r} names a family outside the closed list")
    return family, leaf


def budget_for(role: str) -> Budget:
    """The budget of a role generation may make: its own entry, else its family's."""
    family, _ = split_role(role)
    if family not in GENERATED_FAMILIES:
        raise Refused(f"look role {role!r} is in family {family!r}, which generation does not make")
    return BUDGETS.get(role) or BUDGETS[family]
