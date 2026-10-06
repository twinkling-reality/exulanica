"""The style pack format's piece budgets: what one piece of a look family may weigh.

``assets/style-packs/piece-budgets.v1.json`` is the one source of these numbers. It states, per
family, the triangles at the first level of detail (per metre of the piece's own width for a
tiled family), the materials, the largest texture side and the binary glTF file's size, plus the
share a second level of detail may keep and the vertices a triangle may bring. The style pack
reader and the generated piece records both read it through :func:`read_budgets`, so a piece is
generated against the same numbers the page draws it against, and a request names the file's
digest.

The file is canonical JSON with one newline, like the colour table, and is read strictly: exact
keys, look families only, whole numbers only, exactly one triangle rule per family and every limit
positive.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from exulanica_pieces.canonical import Refused, exact_keys, is_count, parse_canonical, sha256_hex
from exulanica_pieces.vocabulary import FAMILIES

__all__ = [
    "BUDGETS_PATH",
    "BUDGETS_PROFILE",
    "PieceBudget",
    "PieceBudgets",
    "read_budgets",
]

BUDGETS_PROFILE: Final = "exulanica.style-pack-piece-budgets/v1"
#: Relative to the repository root.
BUDGETS_PATH: Final = "assets/style-packs/piece-budgets.v1.json"
_DOCUMENT_KEYS: Final = (
    "about",
    "families",
    "lod1_share_permille",
    "profile",
    "vertices_per_triangle",
)
_FAMILY_KEYS: Final = (
    "glb_bytes",
    "materials",
    "texture_side_px",
    "triangles",
    "triangles_per_metre",
)


@dataclass(frozen=True, slots=True)
class PieceBudget:
    """What one piece of a family may weigh at its first level of detail, as one binary glTF."""

    triangles: int
    triangles_per_metre: int
    materials: int
    texture_side_px: int
    glb_bytes: int

    def triangle_limit(self, width_mm: int) -> int:
        """A tiled family's limit scales with the piece's own width; every other's is fixed."""
        if self.triangles_per_metre:
            return self.triangles_per_metre * width_mm // 1000
        return self.triangles


@dataclass(frozen=True, slots=True)
class PieceBudgets:
    """The read file: each family's budget, the shared rules, and the file's sha256."""

    families: Mapping[str, PieceBudget]
    lod1_share_permille: int
    vertices_per_triangle: int
    sha256: str


def read_budgets(repository: Path) -> PieceBudgets:
    """The committed budgets and the sha256 of the file's bytes, or a refusal naming the fault."""
    raw = (repository / BUDGETS_PATH).read_bytes()
    if not raw.endswith(b"\n"):
        raise Refused(f"{BUDGETS_PATH} ends with one newline")
    document = exact_keys(parse_canonical(raw[:-1], BUDGETS_PATH), _DOCUMENT_KEYS, BUDGETS_PATH)
    if document["profile"] != BUDGETS_PROFILE:
        raise Refused(f"{BUDGETS_PATH} is not {BUDGETS_PROFILE}")
    share = document["lod1_share_permille"]
    if not is_count(share, 1) or share > 1000:
        raise Refused(f"{BUDGETS_PATH}: lod1_share_permille is 1 to 1,000")
    if not is_count(document["vertices_per_triangle"], 1):
        raise Refused(f"{BUDGETS_PATH}: vertices_per_triangle is a whole number from 1")
    families = document["families"]
    if not isinstance(families, dict) or not families:
        raise Refused(f"{BUDGETS_PATH}: families holds at least one family")
    budgets: dict[str, PieceBudget] = {}
    for family, values in families.items():
        where = f"{BUDGETS_PATH}: families.{family}"
        if family not in FAMILIES:
            raise Refused(f"{where}: not a look family")
        entry = exact_keys(values, _FAMILY_KEYS, where)
        if not all(is_count(value) for value in entry.values()):
            raise Refused(f"{where}: every budget is a whole number")
        budget = PieceBudget(**entry)
        if (budget.triangles == 0) == (budget.triangles_per_metre == 0):
            raise Refused(f"{where}: states triangles or triangles per metre, exactly one")
        if min(budget.materials, budget.texture_side_px, budget.glb_bytes) <= 0:
            raise Refused(f"{where}: every limit is positive")
        budgets[family] = budget
    return PieceBudgets(
        families=MappingProxyType(budgets),
        lod1_share_permille=share,
        vertices_per_triangle=document["vertices_per_triangle"],
        sha256=sha256_hex(raw),
    )
