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

import numpy as np

from exulanica_pieces.canonical import sha256_hex
from exulanica_pieces.geometry.glb import write_glb
from exulanica_pieces.geometry.hold import measure_hold
from exulanica_pieces.geometry.mesh import (
    Mesh,
    Simplifier,
    fit,
    flat_palette,
    orient,
    simplify_to,
)
from exulanica_pieces.records import box_fill_permille, measures_box_fill, verdict

__all__ = ["POSTPROCESS_VERSION", "Piece", "make_piece"]

#: v2 adds the yaw choice of a contained piece; an output is cached under its version, so a piece
#: made by v1 is never served as v2.
POSTPROCESS_VERSION: Final = "exulanica.generated-asset-postprocess/v2"


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
    if request["fit"] == "contain":
        mesh, yaw = _better_yaw(mesh, slot)
        steps[0]["yaw_degrees"] = yaw
    mesh, step = fit(mesh, request["fit"], slot)
    steps.append(step)
    fitted = mesh
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
    hold = request.get("hold")
    if hold is not None:
        measured["hold"] = measure_hold(fitted, slot, size, hold)
    if measures_box_fill(request):
        measured["box_fill_permille"] = box_fill_permille(size, slot)
    return Piece(glb, steps, measured, verdict(measured, request["budget"], hold))


def _better_yaw(mesh: Mesh, slot: Mapping[str, int]) -> tuple[Mesh, int]:
    """The mesh as it stands or turned 90 degrees about glTF +Y, whichever the contain fit leaves
    filling more of the slot's longest side; a tie keeps it as it stands.

    A model may draw a thing's long side across the picture or into it, and the contain fit of a
    thin box then shrinks it by its depth (measured on Nebius, 2026-10-07: market stalls 600 to
    905 per mille turned, benches drawn end-on 96 to 660). Turning is a proper rotation, so the
    winding and the normals stay right."""
    turned = Mesh(
        np.stack([mesh.positions[:, 2], mesh.positions[:, 1], -mesh.positions[:, 0]], axis=1),
        mesh.triangles,
        mesh.colours,
    )
    fills = []
    for candidate in (mesh, turned):
        _, step = fit(candidate, "contain", slot)
        fills.append(box_fill_permille(step["size_mm"], slot))
    return (turned, 90) if fills[1] > fills[0] else (mesh, 0)


def _written_vertices(glb: bytes) -> int:
    """The vertex count the container states, which is what the page uploads."""
    length = struct.unpack_from("<I", glb, 12)[0]
    document = json.loads(glb[20 : 20 + length])
    return int(document["accessors"][0]["count"])
