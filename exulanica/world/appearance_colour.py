"""Pure declared-colour facts for an already admitted static GLB, never perceived colour.

The caller owns current appearance selection, source authorization, digest/byte verification and
world identity. This module reads only the existing static parser's inspected document/instances;
it cannot resolve a look, fetch bytes, create an entity, change a world or establish current rights.
Only referenced primitive instances count. An opaque, nonmetallic constant base factor with no
vertex colours, material maps or emission supports a fact. Other surfaces remain unknown.

Predicates use sRGB8 swatches or inclusive channel intervals, not named colours or a perceptual
distance. Linear factors are converted by the sRGB transfer function and rounded half upward to
8-bit channels. A match means at least one supported primitive matches; it says nothing about
surface dominance, camera visibility, lighting, texture pixels or source-world factual evidence.
A negative result requires complete known coverage. Counts describe work, never colour dominance.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from exulanica.world.static_glb import LIMITS, InspectedGlb
from exulanica.world.static_glb import PROFILE as STATIC_PROFILE

PROFILE = "exulanica.declared-appearance-colour/v1"
RGB8 = tuple[int, int, int]


def _channels(value: RGB8) -> None:
    if (
        type(value) is not tuple
        or len(value) != 3
        or any(type(channel) is not int or not 0 <= channel <= 255 for channel in value)
    ):
        raise ValueError("a colour has exactly three integer sRGB channels from 0 to 255")


@dataclass(frozen=True, slots=True)
class ColourSwatch:
    srgb8: RGB8

    def __post_init__(self) -> None:
        _channels(self.srgb8)

    def matches(self, channels: RGB8) -> bool:
        return channels == self.srgb8


@dataclass(frozen=True, slots=True)
class ColourInterval:
    lower: RGB8
    upper: RGB8

    def __post_init__(self) -> None:
        _channels(self.lower)
        _channels(self.upper)
        if any(low > high for low, high in zip(self.lower, self.upper, strict=True)):
            raise ValueError("each lower colour channel must be at most its upper channel")

    def matches(self, channels: RGB8) -> bool:
        return all(
            low <= value <= high
            for low, value, high in zip(self.lower, channels, self.upper, strict=True)
        )


def _srgb8(linear: float) -> int:
    value = 12.92 * linear if linear <= 0.0031308 else 1.055 * linear ** (1 / 2.4) - 0.055
    return min(255, max(0, math.floor(value * 255 + 0.5)))


def colour_facts(
    inspected: InspectedGlb | None,
    *,
    container_profile: str = STATIC_PROFILE,
    maximum_primitives: int = LIMITS.draw_calls,
) -> dict[str, Any]:
    """Bounded facts from admitted bytes. No admission or current-authority claim is made here.

    A caller with an unsupported profile passes None; it need not run a static parser on another
    format. Parsed containers admitted with larger custom limits are still bounded by this read.
    """
    if type(maximum_primitives) is not int or not 1 <= maximum_primitives <= LIMITS.draw_calls:
        raise ValueError(f"maximum_primitives must be from 1 to {LIMITS.draw_calls}")
    result: dict[str, Any] = {
        "profile": PROFILE,
        "container_profile": container_profile,
        "space": "srgb8",
        "basis": "constant_base_factor",
        "primitives": [],
        "coverage": {
            "state": "unknown",
            "reason": None,
            "total": None,
            "examined": 0,
            "known": 0,
            "unknown": None,
            "unexamined": None,
        },
    }
    coverage = result["coverage"]
    if container_profile != STATIC_PROFILE:
        coverage["reason"] = "unsupported_profile"
        return result
    if inspected is None:
        coverage["reason"] = "container_not_inspected"
        return result
    if not isinstance(inspected, InspectedGlb):
        raise TypeError("colour facts require the existing static GLB parser's inspected result")
    total = inspected.counts["draw_calls"]
    document = inspected.document
    materials = document.get("materials", [])
    rows = result["primitives"]
    for instance in inspected.instances:
        for index, primitive in enumerate(document["meshes"][instance.mesh]["primitives"]):
            if len(rows) == maximum_primitives:
                break
            material_index = primitive.get("material")
            material = {} if material_index is None else materials[material_index]
            pbr = material.get("pbrMetallicRoughness", {})
            rgba = pbr.get("baseColorFactor", [1, 1, 1, 1])
            reasons = []
            if "COLOR_0" in primitive["attributes"]:
                reasons.append("vertex_colour")
            if "baseColorTexture" in pbr:
                reasons.append("base_colour_texture")
            if material.get("alphaMode", "OPAQUE") != "OPAQUE" or rgba[3] != 1:
                reasons.append("transparency")
            if pbr.get("metallicFactor", 1) != 0:
                reasons.append("metallic_surface")
            if any(value != 0 for value in material.get("emissiveFactor", [0, 0, 0])):
                reasons.append("emission")
            if (
                any(
                    key in material
                    for key in ("normalTexture", "occlusionTexture", "emissiveTexture")
                )
                or "metallicRoughnessTexture" in pbr
            ):
                reasons.append("material_map")
            rows.append(
                {
                    "node": instance.node,
                    "mesh": instance.mesh,
                    "primitive": index,
                    "material": material_index,
                    "state": "unknown" if reasons else "known",
                    "reasons": reasons,
                    "linear_rgba": list(rgba),
                    "srgb8": None if reasons else [_srgb8(value) for value in rgba[:3]],
                }
            )
        if len(rows) == maximum_primitives:
            break
    unknown = sum(row["state"] == "unknown" for row in rows)
    unexamined = total - len(rows)
    coverage.update(
        {
            "state": "complete" if not unknown and not unexamined else "partial",
            "reason": "primitive_budget"
            if unexamined
            else "unsupported_surface"
            if unknown
            else None,
            "total": total,
            "examined": len(rows),
            "known": len(rows) - unknown,
            "unknown": unknown,
            "unexamined": unexamined,
        }
    )
    return result


def match_colour(facts: dict[str, Any], predicate: ColourSwatch | ColourInterval) -> dict[str, Any]:
    """Whether any known constant primitive matches, with the unmodified coverage beside it."""
    if facts.get("profile") != PROFILE:
        raise ValueError("unknown appearance colour facts profile")
    if not isinstance(predicate, (ColourSwatch, ColourInterval)):
        raise TypeError("a colour predicate is a numeric swatch or channel interval")
    matched = [
        row
        for row in facts["primitives"]
        if row["state"] == "known" and predicate.matches(tuple(row["srgb8"]))
    ]
    return {
        "state": "match"
        if matched
        else "no_match"
        if facts["coverage"]["state"] == "complete"
        else "unknown",
        "quantifier": "any_constant_primitive",
        "matches": matched,
        "coverage": facts["coverage"],
    }
