"""Route P's fit: a creature's model made from a picture, to its skinned look or a refusal by code.

The paid step makes the picture, its cut-out and the 3D model; nothing here needs a GPU, so this runs
wherever the model is fetched to (this Mac, an operator's command, a server). From a creature look
request (its plan, rest skeleton and words), the picture's cut-out and the 3D model (positions,
triangles and vertex colours in the model's own frame, with its up and front named), it:

1.  turns the model into the slot frame and drops stray fragments (as route C does);
2.  lays the plan's skeleton in the full model (:mod:`embed`): scaled to the plan's height, its
    facing read from it, every chain in its own limb, a missing leg refused, other missing chains
    kept still;
3.  simplifies the model to the skin's triangle budget and places the copy as the full model was
    placed (the inside the skin is checked against stays the full model's: simplifying can tear a
    closed model open);
4.  turns every triangle of the copy to face out of the body (judged by the full model's inside),
    colours each triangle with its own swatch, skins it by bone heat with the still bones left out,
    and holds the rig to its checks for a fitted skeleton;
5.  measures how closely the model keeps its picture (:mod:`likeness`), recorded, never judged here;
6.  writes the skinned container (every plan bone a joint at its laid place, the still ones holding
    no vertex) and reads it back with the product's reader.

Each stage's measures go into the receipt; a refusal names its code and keeps the measures taken
before it, and nothing but the receipt is made.
"""

from __future__ import annotations

import io
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Final

import numpy as np
from exulanica_pieces.canonical import Refused, sha256_hex
from exulanica_pieces.geometry.mesh import Mesh, Simplifier, orient, simplify_to
from exulanica_pieces.geometry.skinned import write_skinned_glb
from exulanica_pieces.skinned import read_skinned_glb

from exulanica_appearance.creatures.colour import flat_colours
from exulanica_appearance.creatures.embed import (
    DEFAULT_SETTINGS,
    EmbedRefused,
    EmbedSettings,
    embed,
)
from exulanica_appearance.creatures.job import _main_parts, _slot, _without_slivers
from exulanica_appearance.creatures.likeness import likeness
from exulanica_appearance.creatures.request import CreatureRequest
from exulanica_appearance.creatures.rig import Inside, RigRefused, bone_heat, check_rig

__all__ = [
    "DEFAULT_FIT",
    "RECEIPT_PROFILE",
    "FitSettings",
    "Fitted",
    "fit_look",
    "model_from_npz",
    "plan_height",
]

RECEIPT_PROFILE: Final = "exulanica.creature-fit-receipt/v1"


@dataclass(frozen=True)
class FitSettings:
    """What a fit may be asked to do differently; each default is the value it was built with."""

    #: The skin's triangle budget, as route C's job settings state theirs.
    triangles: int = 20_000
    embed: EmbedSettings = DEFAULT_SETTINGS


DEFAULT_FIT: Final = FitSettings()


@dataclass(frozen=True)
class Fitted:
    """The skinned container, or None for a refusal, and the receipt either way."""

    container: bytes | None
    receipt: dict[str, Any] = field(default_factory=dict)


def plan_height(request: CreatureRequest) -> float:
    """The height the plan's rest skeleton stands to, metres: its highest joint or end."""
    return max(float(max(request.joints[bone][2], request.ends[bone][2])) for bone in request.bones)


def _mm(value: float) -> int:
    return round(value * 1000)


def _png_rgba(data: bytes) -> np.ndarray:
    from PIL import Image

    return np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))


def fit_look(
    request: CreatureRequest,
    model: Mesh,
    *,
    up: str,
    front: str,
    cutout_png: bytes,
    simplifier: Simplifier,
    table: Sequence[int],
    settings: FitSettings = DEFAULT_FIT,
) -> Fitted:
    """One creature's look from its picture's model, or a refusal; never raises for the model."""
    # Whole seconds per stage, as route C's receipts hold them: a record holds integers.
    seconds: dict[str, int] = {}
    receipt: dict[str, Any] = {
        "profile": RECEIPT_PROFILE,
        "route": "P",
        "plan": {
            "key": request.plan_key,
            "sha256": request.plan_sha256,
            "version": request.plan_version,
        },
        "inputs": {
            "cutout": sha256_hex(cutout_png),
            "model_triangles": len(model.triangles),
            "model_vertices": len(model.positions),
        },
        "seconds": seconds,
    }
    stage = "frame"
    try:
        start = time.monotonic()
        turned, turn_record = orient(model, up, front)
        whole, parts_record = _main_parts(_slot(turned).compact())
        receipt["steps"] = [turn_record, parts_record]
        seconds["frame"] = round(time.monotonic() - start)
        stage = "embed"
        start = time.monotonic()
        try:
            fitted = embed(
                whole.positions,
                whole.triangles,
                bones=request.bones,
                parents=request.parents,
                chains=request.chains,
                joints=request.joints,
                ends=request.ends,
                height=plan_height(request),
                settings=settings.embed,
            )
        except EmbedRefused as refusal:
            receipt["embed"] = refusal.measures
            raise
        seconds["embed"] = round(time.monotonic() - start)
        receipt["embed"] = {
            **fitted.measures,
            "yaw_degrees": fitted.yaw_degrees,
            "matched": sorted(leaf for leaf, end in fitted.matched.items() if end is not None),
            "unmatched": sorted(leaf for leaf, end in fitted.matched.items() if end is None),
            "still": list(fitted.still),
        }
        stage = "simplify"
        start = time.monotonic()
        simplified, simplify_record = simplify_to(whole, settings.triangles, simplifier)
        cleaned, slivers = _without_slivers(simplified)
        cleaned, cleaned_parts = _main_parts(cleaned)
        receipt["steps"] += [
            simplify_record,
            {"step": "slivers", "removed": slivers},
            cleaned_parts,
        ]
        positions = fitted.place(cleaned.positions)
        triangles, turned_over = _outward(positions, cleaned.triangles, fitted.inside)
        receipt["steps"].append({"step": "outward", "turned": turned_over})
        colours, palette = flat_colours(cleaned.colours, triangles)
        receipt["swatches"] = len(palette)
        seconds["simplify"] = round(time.monotonic() - start)
        stage = "rig"
        start = time.monotonic()
        moving = [bone for bone in request.bones if bone not in fitted.still]
        local, weights = bone_heat(
            positions, triangles, moving, fitted.joints, fitted.ends, fitted.inside
        )
        to_plan = np.array([request.bones.index(bone) for bone in moving], dtype=np.int64)
        indices = to_plan[local]
        chains = [chain for chain in request.chains if not set(chain["bones"]) & set(fitted.still)]
        size = float(np.ptp(positions, axis=0).max())
        try:
            checks = check_rig(
                positions=positions,
                indices=local,
                weights=weights,
                bones=moving,
                parents={bone: request.parents[bone] for bone in moving},
                plan_joints=request.joints,
                joints=fitted.joints,
                ends=fitted.ends,
                chains=chains,
                inside=fitted.inside,
                size=size,
                fitted=True,
            )
        except RigRefused as refusal:
            if refusal.checks is not None:
                receipt["rig"] = _rig_record(refusal.checks, fitted.inside.voxel)
            raise
        receipt["rig"] = _rig_record(checks, fitted.inside.voxel)
        seconds["rig"] = round(time.monotonic() - start)
        stage = "likeness"
        start = time.monotonic()
        measured = likeness(positions, triangles, colours, _png_rgba(cutout_png))
        receipt["likeness"] = {
            "yaw_degrees": measured.yaw_degrees,
            "pitch_degrees": measured.pitch_degrees,
            "outline_overlap_per_mille": measured.outline_overlap_per_mille,
            "colour_difference_milli": measured.colour_difference_milli,
            "picture_mean_srgb": None
            if measured.picture_mean_srgb is None
            else list(measured.picture_mean_srgb),
            "model_mean_srgb": None
            if measured.model_mean_srgb is None
            else list(measured.model_mean_srgb),
        }
        seconds["likeness"] = round(time.monotonic() - start)
        stage = "container"
        start = time.monotonic()
        container = write_skinned_glb(
            positions_m=positions,
            triangles=triangles,
            triangle_colours_srgb8=colours,
            joint_indices=indices,
            joint_weights=weights,
            bones=request.bones,
            parents=request.parents,
            rest_m=fitted.joints,
            table=table,
        )
        read = read_skinned_glb(
            container,
            bones={bone: f"bone:{bone}" for bone in request.bones},
            plan_parents=request.parents,
        )
        seconds["container"] = round(time.monotonic() - start)
    except (EmbedRefused, RigRefused) as refusal:
        receipt["outcome"] = "refused"
        receipt["refusal"] = {"code": refusal.code, "detail": refusal.detail}
        return Fitted(None, receipt)
    except Refused as refusal:
        receipt["outcome"] = "refused"
        receipt["refusal"] = {"code": f"{stage}_refused", "detail": str(refusal)}
        return Fitted(None, receipt)
    receipt["outcome"] = "passed"
    receipt["output"] = {
        "bytes": len(container),
        "joints": len(read.joints),
        "sha256": sha256_hex(container),
        "triangles": read.triangles,
        "height_mm": _mm(float(np.ptp(positions[:, 2]))),
    }
    return Fitted(container, receipt)


def _outward(
    positions: np.ndarray, triangles: np.ndarray, inside: Inside
) -> tuple[np.ndarray, int]:
    """Every triangle turned to face out of the body, and how many were turned. A simplified copy
    can turn triangles over (measured on a model made from a picture: about one in thirteen after
    the stand-in clusterer, against one in a hundred in the full model), and a renderer that culls
    back faces draws a turned triangle as a hole. A triangle faces out when the full model's inside
    is shallower a voxel and a half along its normal than the same distance against it; on a tie it
    is left as it is."""
    corners = positions[triangles]
    normal = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    length = np.linalg.norm(normal, axis=1, keepdims=True)
    normal = normal / np.where(length > 0, length, 1.0)
    middle = corners.mean(axis=1)
    reach = 1.5 * inside.voxel
    ahead = inside.depth_at(middle + normal * reach)
    behind = inside.depth_at(middle - normal * reach)
    over = ahead > behind
    turned = triangles.copy()
    turned[over] = turned[over][:, ::-1]
    return turned, int(over.sum())


def _rig_record(checks: Any, voxel: float) -> dict[str, Any]:
    """What the rig's checks measured, as a receipt holds it, passed or refused."""
    return {
        "voxel_mm": _mm(voxel),
        "joint_moved_mm": {bone: _mm(value) for bone, value in checks.joint_moved_m.items()},
        "inside_per_mille": {
            bone: round(value * 1000) for bone, value in checks.inside_share.items()
        },
        "moved_vertices": dict(checks.moved_vertices),
        "leaked_per_mille": {
            key: round(value * 1000) for key, value in checks.leaked_share.items()
        },
    }


def model_from_npz(data: bytes) -> Mesh:
    """A model as the paid step writes it: positions, triangles and vertex colours, compressed."""
    arrays = np.load(io.BytesIO(data))
    return Mesh(
        arrays["positions"].astype(np.float64),
        arrays["triangles"].astype(np.int64),
        arrays["colours"].astype(np.uint8),
    )
