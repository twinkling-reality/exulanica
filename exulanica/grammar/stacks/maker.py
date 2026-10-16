"""The sea stack maker: a sea stack and a seed made into an unchanged ``exulanica.volume/v1``.

One pure function of a stack document and a seed, in whole numbers: the same stack and seed make
the same volume, digest for digest. What a shoulder's bearing, height and size are is drawn from
SHA-256 of the seed under the sea stack profile's prefix, the stack's id, what is drawn and its
index; nothing else is drawn. The volume's id is the stack's id, its frame is the stack's (level 0
the sea's surface where it is placed), and it is read against the volume catalog version the
stack's sections are bounded by, within its part limit (at most seven parts).

**What reads as a sea stack.** Judged in the application on 15 October; these are the maker's
rules:

* A trunk column from its foot to its top, its rims rounded little (1 m); shoulders as spheres
  blended about 4 m into it; a cap at the top, so the top is level at ``height_mm`` whatever the
  weathering below it.
* Beds varied every way (the volume catalog's version 2 strata; for example amplitude about
  1000 mm, period about 4500, spread about 2500, relief about 600, offset about 700, tilt about 3
  degrees): stacks with even beds read as rings, and stacks with no beds read as soft clay. The
  stack states its own erosion and strata; the maker passes them on unchanged.
* Shallow rock that faces up just under the water reads as a bright turquoise block in the bay's
  water. On a stack with its arch floor 3 m under the surface, 31 percent of its rock in the top
  3 m of water faced up; with the floor 7 m under, 6 percent. So a passage's floor lies at least
  6 m under, shoulders swell above the water only, and the trunk's flank away from its lean faces
  up by at most 1 in 4 (:data:`~exulanica.grammar.stacks.document.FLANK_PERMILLE`). The beds still
  decide most of it: the field lays bed 0 on level 0 with a recessed join, so across seeds 4 to 33
  percent of a stack's surface realized at the 2 m cell, in the top 3 m of water, faces up by more
  than 17 degrees; the tests hold the stacks they make to under 15 percent under their own seed.

**Parts, in order.**

1. ``trunk``: a column leaned by the stack's lean, its axis crossing level 0 at the origin. It
   reaches the weathering and 1 m below the foot, so weathering never lifts the foot off the sea
   floor (the field is solid on its axis just above ``-foot_mm``), and its rounded top rim lies
   above the cap. Its radius runs linearly from ``base_radius_mm`` at the foot to
   ``top_radius_mm`` at the top, carried on to its ends (at least 1 m at each).
2. ``shoulder_<n>``: spheres blended 4 m into the trunk, bearings a turn over their number apart
   from a drawn first and each moved by up to a fifth of that, centred on the trunk's axis at 30 to
   75 percent of its height, each 45 to 75 percent of the trunk's radius there and standing out of
   the trunk by 35 to 65 percent of its own radius.
3. ``arch``: a passage carved along its bearing (blend 1.5 m), centred on the trunk's axis at its
   floor, ``floor_mm`` under level 0, its round head's crown ``rise_mm`` above, running through the
   whole stack.
4. ``top``: a cap at ``height_mm`` (blend 800 mm).
"""

from __future__ import annotations

import hashlib
from typing import Any, Final

from exulanica.grammar.stacks.catalog import VOLUME_CATALOG_VERSION
from exulanica.grammar.stacks.document import PROFILE, SeaStackDocument, trunk_radius
from exulanica.grammar.volumes import PROFILE as VOLUME_PROFILE
from exulanica.grammar.volumes import (
    TURN_ONE,
    VolumeDocument,
    read_volume_document,
    sin_cos,
    volume_catalog,
)

__all__ = ["axis_point", "make_sea_stack"]

_FULL_TURN: Final = 360_000
#: How round the trunk's rims are: a sea stack's edges are sharp.
_TRUNK_ROUND_MM: Final = 1_000
#: How far the trunk reaches below its foot, besides the weathering.
_SINK_MM: Final = 1_000
_SHOULDER_BLEND_MM: Final = 4_000
_SHOULDER_LEAST_MM: Final = 1_500
_ARCH_BLEND_MM: Final = 1_500
_CAP_BLEND_MM: Final = 800


def _draws(seed: bytes, stack_id: str, what: bytes, index: int) -> tuple[int, int, int, int]:
    """Four 64-bit draws for ``what`` at ``index``, from the seed under the profile's prefix."""
    digest = hashlib.sha256(
        PROFILE.encode()
        + b"\x1f"
        + seed
        + b"\x1f"
        + stack_id.encode()
        + b"\x1f"
        + what
        + b"\x1f"
        + index.to_bytes(8, "big")
    ).digest()
    a, b, c, d = (int.from_bytes(digest[at : at + 8], "big") for at in (0, 8, 16, 24))
    return a, b, c, d


def _within(draw: int, low: int, high: int) -> int:
    return low + draw % (high - low + 1)


def _up(stack: SeaStackDocument) -> tuple[int, int, int]:
    """The trunk's axis, leaned by its tilt toward its bearing, at :data:`TURN_ONE`."""
    sin_tilt, cos_tilt = sin_cos(stack.tilt_mdeg)
    sin_toward, cos_toward = sin_cos(stack.toward_mdeg)
    return sin_tilt * sin_toward // TURN_ONE, sin_tilt * cos_toward // TURN_ONE, cos_tilt


def axis_point(stack: SeaStackDocument, height_mm: int) -> tuple[int, int, int]:
    """Where the trunk's axis crosses ``height_mm``: the origin at level 0, moved along its lean
    above and below it."""
    up_x, up_y, up_z = _up(stack)
    return height_mm * up_x // up_z, height_mm * up_y // up_z, height_mm


def _trunk(stack: SeaStackDocument) -> dict[str, Any]:
    weathering = stack.weathering_mm
    low = -(stack.foot_mm + weathering + _SINK_MM)
    high = stack.height_mm + _TRUNK_ROUND_MM + weathering + _CAP_BLEND_MM
    _, cos_tilt = sin_cos(stack.tilt_mdeg)
    x, y, z = axis_point(stack, low)
    return {
        "id": "trunk",
        "shape": "column",
        "at_mm": [x, y, z],
        "tilt_mdeg": stack.tilt_mdeg,
        "toward_mdeg": stack.toward_mdeg,
        # Its length along its leaned axis spans low to high upright: a ceiling, so it never
        # falls short of the cap.
        "height_mm": -(-(high - low) * TURN_ONE // cos_tilt),
        "base_radius_mm": max(_TRUNK_ROUND_MM, trunk_radius(stack, low)),
        "top_radius_mm": max(_TRUNK_ROUND_MM, trunk_radius(stack, high)),
        "round_mm": _TRUNK_ROUND_MM,
    }


def _shoulders(stack: SeaStackDocument, seed: bytes) -> list[dict[str, Any]]:
    count = stack.shoulders
    if not count:
        return []
    apart = _FULL_TURN // count
    first = _draws(seed, stack.id, b"shoulders", 0)[0] % _FULL_TURN
    shoulders = []
    for index in range(count):
        turn, rise, size, stand = _draws(seed, stack.id, b"shoulder", index)
        bearing = (first + index * apart + _within(turn, -apart // 5, apart // 5)) % _FULL_TURN
        height = stack.height_mm * _within(rise, 300, 750) // 1000
        across = trunk_radius(stack, height)
        radius = max(_SHOULDER_LEAST_MM, across * _within(size, 450, 750) // 1000)
        out = across - radius + radius * _within(stand, 350, 650) // 1000
        sine, cosine = sin_cos(bearing)
        x, y, z = axis_point(stack, height)
        shoulders.append(
            {
                "id": f"shoulder_{index}",
                "shape": "sphere",
                "at_mm": [x + out * sine // TURN_ONE, y + out * cosine // TURN_ONE, z],
                "radius_mm": radius,
                "blend_mm": _SHOULDER_BLEND_MM,
            }
        )
    return shoulders


def _arch(stack: SeaStackDocument) -> list[dict[str, Any]]:
    arch = stack.arch
    if arch is None:
        return []
    x, y, z = axis_point(stack, -arch.floor_mm)
    return [
        {
            "id": "arch",
            "shape": "arch",
            "at_mm": [x, y, z],
            # A part's north turned counterclockwise by its yaw runs along the bearing clockwise.
            "yaw_mdeg": (_FULL_TURN - arch.bearing_mdeg) % _FULL_TURN,
            "width_mm": arch.width_mm,
            "spring_mm": arch.floor_mm + arch.rise_mm - arch.width_mm // 2,
            "depth_mm": 4 * max(stack.base_radius_mm, stack.top_radius_mm)
            + 2 * stack.weathering_mm
            + 4_000,
            "blend_mm": _ARCH_BLEND_MM,
        }
    ]


def make_sea_stack(stack: SeaStackDocument, seed: bytes) -> VolumeDocument:
    """The volume ``stack`` is under ``seed``, read by the volume reader against the volume
    catalog version its sections are bounded by."""
    raw = {
        "profile": VOLUME_PROFILE,
        "id": stack.id,
        "look": stack.look,
        "top_look": stack.top_look,
        "walk": stack.walk,
        "erosion": dict(stack.erosion),
        "strata": dict(stack.strata),
        "parts": [
            _trunk(stack),
            *_shoulders(stack, seed),
            *_arch(stack),
            {"id": "top", "shape": "cap", "height_mm": stack.height_mm, "blend_mm": _CAP_BLEND_MM},
        ],
    }
    return read_volume_document(raw, volume_catalog(VOLUME_CATALOG_VERSION))
