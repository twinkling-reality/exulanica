"""A model's raw mesh to a piece: orient, simplify, fit, palette, write, measure.

The same steps run on the rented machine and in the dry run; only the simplifier differs, and its
name and parameters are in the receipt.
"""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica_appearance.assets.glb import write_glb
from exulanica_appearance.assets.mesh import (
    Mesh,
    Simplifier,
    fit,
    flat_palette,
    orient,
    simplify_to,
)
from exulanica_appearance.assets.records import verdict
from exulanica_appearance.canonical import sha256_hex

__all__ = ["POSTPROCESS_VERSION", "Piece", "make_piece"]

POSTPROCESS_VERSION: Final = "exulanica.generated-asset-postprocess/v1"


@dataclass(frozen=True)
class Piece:
    glb: bytes
    steps: list[dict[str, Any]]
    measured: dict[str, Any]
    verdict: dict[str, Any]

    @property
    def sha256(self) -> str:
        return sha256_hex(self.glb)


def make_piece(
    raw: Mesh,
    *,
    up: str,
    front: str,
    request: Mapping[str, Any],
    simplifier: Simplifier,
    table: Sequence[int],
) -> Piece:
    """``raw`` in the model's own frame, whose up and front axes the route states."""
    steps: list[dict[str, Any]] = []
    mesh, step = orient(raw, up, front)
    steps.append(step)
    mesh, step = simplify_to(mesh, request["budget"]["triangles"], simplifier)
    steps.append(step)
    slot = dict(request["slot_mm"])
    if request["fit"] == "tile":
        # One module of the run: its own length along the width, the slot's height and depth.
        slot["width"] = request["tile_module_mm"]
    mesh, step = fit(mesh, request["fit"], slot)
    steps.append(step)
    palette = request["pack"]["palette"]
    mesh, swatch, step = flat_palette(mesh, palette)
    steps.append(step)
    glb = write_glb(mesh, swatch, palette, table)
    steps.append({"bytes": len(glb), "step": "write"})
    size = next(item for item in steps if item["step"] == "fit")["size_mm"]
    measured = {
        "glb_bytes": len(glb),
        "materials": 1,
        "size_mm": size,
        "texture_side_px": 0,
        "triangles": len(mesh.triangles),
        "vertices": _written_vertices(glb),
    }
    return Piece(glb, steps, measured, verdict(measured, request["budget"]))


def _written_vertices(glb: bytes) -> int:
    """The vertex count the container states, which is what the page uploads."""
    length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + length])
    return int(document["accessors"][0]["count"])
