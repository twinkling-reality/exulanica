"""A look: one representation of a body, read and held to the look kind that draws it.

A look, profile ``exulanica.look/v1``, is one way a thing of a body plan may be drawn: an armoured
knight, a blocky figure, a drifting light, a sword. It is its own versioned, fingerprinted
document, apart from what the thing is, so any look of a thing's body plan may be chosen for it
and nothing it does changes: no look reference ever enters a society's input, state or decision
context. It names its look kind (:mod:`exulanica.things.catalogs`), the body plan it fits, the
container it draws where its kind draws one, a rig mapping the plan's required bones where its
kind is rigged, the light it is where its kind is a light, the look role a style pack dresses
where its kind is one, how its pictures are sampled, and its origin.

Pure: no connection, no store.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.things.catalogs import ThingCatalogs, thing_catalogs
from exulanica.things.origin import OriginRefused, read_origin

__all__ = [
    "LOOK_PROFILE",
    "SAMPLINGS",
    "Look",
    "LookRefused",
    "read_look",
]

LOOK_PROFILE: Final = "exulanica.look/v1"
#: How a look's pictures are sampled: smoothly, or by the nearest texel, which pixel art needs.
SAMPLINGS: Final = ("linear", "nearest")
_KEY: Final = re.compile(r"[a-z][a-z0-9-]{0,47}")
_HEX64: Final = re.compile(r"[0-9a-f]{64}")
_JOINT: Final = re.compile(r"[A-Za-z0-9_.:-]{1,64}")
_CLIP: Final = re.compile(r"[A-Za-z0-9_. -]{1,64}")
_ROLE: Final = re.compile(r"[a-z]+\.[a-z][a-z0-9_]{0,47}")
_TOP: Final = frozenset(
    {
        "profile",
        "look",
        "version",
        "label",
        "body_plan",
        "look_kind",
        "container",
        "rig",
        "height_mm",
        "sampling",
        "light",
        "role",
        "origin",
    }
)
#: The motions a rig may name clips for: the body plans' motions.
_MOTIONS: Final = ("idle", "walk", "run", "reach", "hold", "talk", "sit")
#: The motions that carry a body over the ground: a rig may state how fast each of its clips does,
#: so whoever draws it can match the clip to the pace it is drawn moving at.
_MOVING: Final = ("walk", "run")
#: The fields a rig always states, and those it may.
_RIG: Final = frozenset({"bones", "clips"})
_RIG_MAY: Final = frozenset({"sockets", "ground_speed_mm_per_s"})


class LookRefused(ValueError):
    """A look this code will not read, by a code and the field at fault."""

    def __init__(self, code: str, where: str, detail: str) -> None:
        super().__init__(f"{code} at {where}: {detail}")
        self.code = code
        self.where = where
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Look:
    """A read look: identity, what draws it and the document itself."""

    look: str
    version: int
    label: str
    body_plan: str
    look_kind: str
    document: Mapping[str, Any]
    sha256: str

    def reference(self) -> dict[str, Any]:
        return {"look": self.look, "version": self.version, "sha256": self.sha256}


def _refuse(where: str, detail: str, code: str = "look_invalid") -> LookRefused:
    return LookRefused(code, where, detail)


def _closed(where: str, value: object, keys: frozenset[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise _refuse(where, f"states exactly {sorted(keys)}")
    return value


def _whole(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise _refuse(where, f"is a whole number from {minimum} to {maximum}")
    return value


def _rig(
    where: str,
    value: object,
    plan_bones: frozenset[str],
    required: tuple[str, ...],
    plan_sockets: frozenset[str],
) -> None:
    if not isinstance(value, Mapping) or not _RIG <= set(value) <= _RIG | _RIG_MAY:
        raise _refuse(where, f"states {sorted(_RIG)} and may state {sorted(_RIG_MAY)}")
    rig = value
    bones = rig["bones"]
    if not isinstance(bones, Mapping) or not bones:
        raise _refuse(f"{where}.bones", "maps body plan bones to the rig's joints")
    for bone, joint in bones.items():
        if bone not in plan_bones:
            raise _refuse(f"{where}.bones.{bone}", "is not one of the plan's bones")
        if type(joint) is not str or _JOINT.fullmatch(joint) is None:
            raise _refuse(f"{where}.bones.{bone}", "names one of the rig's joints")
    if len(set(bones.values())) != len(bones):
        raise _refuse(f"{where}.bones", "maps each joint once")
    missing = [bone for bone in required if bone not in bones]
    if missing:
        raise _refuse(
            f"{where}.bones", f"maps every required bone; missing {missing}", "look_rig_short"
        )
    clips = rig["clips"]
    if not isinstance(clips, Mapping):
        raise _refuse(f"{where}.clips", "maps motions to the rig's clip names")
    for motion, clip in clips.items():
        if motion not in _MOTIONS:
            raise _refuse(f"{where}.clips.{motion}", f"is one of {list(_MOTIONS)}")
        if type(clip) is not str or _CLIP.fullmatch(clip) is None:
            raise _refuse(f"{where}.clips.{motion}", "names one of the rig's clips")
    if "sockets" in rig:
        # Where a held thing goes in this rig: each of the plan's sockets, by the rig's joint.
        sockets = rig["sockets"]
        if not isinstance(sockets, Mapping) or not sockets:
            raise _refuse(f"{where}.sockets", "maps the plan's sockets to the rig's joints")
        for socket, joint in sockets.items():
            if socket not in plan_sockets:
                raise _refuse(f"{where}.sockets.{socket}", "is not one of the plan's sockets")
            if type(joint) is not str or _JOINT.fullmatch(joint) is None:
                raise _refuse(f"{where}.sockets.{socket}", "names one of the rig's joints")
        if len(set(sockets.values())) != len(sockets):
            raise _refuse(f"{where}.sockets", "maps each joint once")
    if "ground_speed_mm_per_s" in rig:
        # How fast each moving clip carries the body, in whole millimetres a second, at the
        # look's own height.
        speeds = rig["ground_speed_mm_per_s"]
        if not isinstance(speeds, Mapping) or not speeds:
            raise _refuse(f"{where}.ground_speed_mm_per_s", "maps moving motions to speeds")
        for motion, speed in speeds.items():
            if motion not in _MOVING or motion not in clips:
                raise _refuse(
                    f"{where}.ground_speed_mm_per_s.{motion}",
                    f"is one of {list(_MOVING)} with a clip of its own",
                )
            _whole(f"{where}.ground_speed_mm_per_s.{motion}", speed, 1, 10_000)


def read_look(raw: object, *, catalogs: ThingCatalogs | None = None) -> Look:
    """``raw`` as a look, every field checked against the look kinds and body plans, or
    :class:`LookRefused`."""
    catalogs = catalogs or thing_catalogs()
    document = _closed("look", raw, _TOP)
    if document["profile"] != LOOK_PROFILE:
        raise _refuse("profile", f"is {LOOK_PROFILE}")
    if type(document["look"]) is not str or _KEY.fullmatch(document["look"]) is None:
        raise _refuse("look", "is a lowercase key")
    version = _whole("version", document["version"], 1, 10_000)
    label = document["label"]
    if type(label) is not str or not 1 <= len(label) <= 80 or label != label.strip().lower():
        raise _refuse("label", "is lowercase words, at most 80 characters")
    plan = catalogs.plan(str(document["body_plan"]))
    if plan is None:
        raise _refuse("body_plan", "names a body plan the catalog states", "look_reference_unknown")
    look_kind = catalogs.look_kinds.get(str(document["look_kind"]))
    if look_kind is None:
        raise _refuse("look_kind", "names a look kind the catalog states", "look_reference_unknown")
    if plan.name not in look_kind.plans:
        raise _refuse(
            "look_kind", f"a {look_kind.key} look fits {list(look_kind.plans)}", "look_unfit"
        )
    container = document["container"]
    if look_kind.container == "required":
        held = _closed("container", container, frozenset({"sha256", "bytes", "media_type"}))
        if type(held["sha256"]) is not str or _HEX64.fullmatch(held["sha256"]) is None:
            raise _refuse("container.sha256", "is the container's SHA-256 in lowercase hex")
        _whole("container.bytes", held["bytes"], 1, 32 * 1024 * 1024)
        if held["media_type"] != "model/gltf-binary":
            raise _refuse("container.media_type", "is model/gltf-binary")
    elif container is not None:
        raise _refuse("container", f"a {look_kind.key} look draws no file")
    rig = document["rig"]
    if look_kind.rig:
        _rig(
            "rig",
            rig,
            plan.bone_names,
            plan.required_bones,
            frozenset(socket.key for socket in plan.sockets),
        )
    elif rig is not None:
        raise _refuse("rig", f"a {look_kind.key} look names no rig")
    height = document["height_mm"]
    if "height_mm" in plan.size:
        low, high = plan.size["height_mm"]
        _whole("height_mm", height, low, high)
    elif height is not None:
        raise _refuse("height_mm", "only a look of a body with a height states one")
    if document["sampling"] not in SAMPLINGS:
        raise _refuse("sampling", f"is one of {list(SAMPLINGS)}")
    light = document["light"]
    if look_kind.light:
        lit = _closed("light", light, frozenset({"colour", "intensity_milli", "radius_mm"}))
        colour = lit["colour"]
        if type(colour) is not str or re.fullmatch(r"#[0-9a-f]{6}", colour) is None:
            raise _refuse("light.colour", "is an sRGB colour, #rrggbb in lowercase")
        _whole("light.intensity_milli", lit["intensity_milli"], 1, 100_000)
        _whole("light.radius_mm", lit["radius_mm"], 10, 20_000)
    elif light is not None:
        raise _refuse("light", f"a {look_kind.key} look is no light")
    role = document["role"]
    if look_kind.role:
        if type(role) is not str or _ROLE.fullmatch(role) is None:
            raise _refuse("role", "is a look role, family.leaf")
    elif role is not None:
        raise _refuse("role", f"a {look_kind.key} look names no look role")
    try:
        read_origin(document["origin"], where="origin")
    except OriginRefused as exc:
        raise _refuse("origin", str(exc), "look_origin_invalid") from exc
    return Look(
        look=str(document["look"]),
        version=version,
        label=str(label),
        body_plan=plan.name,
        look_kind=look_kind.key,
        document=MappingProxyType(dict(document)),
        sha256=sha256_of_canonical(dict(document)).hex(),
    )
