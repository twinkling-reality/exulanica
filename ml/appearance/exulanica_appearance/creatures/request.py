"""A creature look request: what a job needs to sculpt one creature's look, and nothing about who
asked for it.

``exulanica.creature-look-request/v1`` holds the body plan (key, version, digest, bones with their
parents, chains), each bone's joint, end and thickness at rest in whole millimetres in the slot
frame, the sketch container's digest and length (the container travels beside the request), the
recipe's appearance words and its colours by role. No account, workspace or person's words: the
appearance words are the recipe's, drafted and checked. The product's request writer and this
reader meet only at the document, so neither imports the other.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

import numpy as np

__all__ = ["COLOUR_ROLES", "REQUEST_PROFILE", "CreatureRequest", "RequestRefused", "read_request"]

REQUEST_PROFILE: Final = "exulanica.creature-look-request/v1"
COLOUR_ROLES: Final = ("body", "belly", "accent", "eyes")
_BONE: Final = re.compile(r"[a-z][A-Za-z0-9]{0,47}")
_HEX: Final = re.compile(r"[0-9a-f]{64}")
_BONES_MAXIMUM: Final = 128
_MM_MAXIMUM: Final = 100_000


class RequestRefused(ValueError):
    pass


@dataclass(frozen=True)
class CreatureRequest:
    plan_key: str
    plan_version: int
    plan_sha256: str
    #: Bones in plan order, each parent before its children.
    bones: tuple[str, ...]
    parents: Mapping[str, str | None]
    chains: tuple[Mapping[str, Any], ...]
    #: Rest joints, ends and thicknesses, metres.
    joints: Mapping[str, np.ndarray]
    ends: Mapping[str, np.ndarray]
    radii: Mapping[str, float]
    sketch_sha256: str
    sketch_bytes: int
    appearance: str
    colour_words: Mapping[str, str]
    colours: Mapping[str, tuple[int, int, int]]


def _point(value: Any, where: str) -> np.ndarray:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(item, int) and not isinstance(item, bool) for item in value)
        or any(abs(item) > _MM_MAXIMUM for item in value)
    ):
        raise RequestRefused(f"{where} is three whole millimetres within {_MM_MAXIMUM}")
    return np.asarray(value, dtype=np.float64) / 1000


def read_request(raw: bytes) -> CreatureRequest:
    """``raw`` as a creature look request, or :class:`RequestRefused` naming the field at fault."""
    try:
        document = json.loads(raw)
    except ValueError as exc:
        raise RequestRefused(f"the request is not JSON: {exc}") from exc
    if not isinstance(document, dict) or document.get("profile") != REQUEST_PROFILE:
        raise RequestRefused(f"the request's profile is {REQUEST_PROFILE}")
    expected = {"profile", "plan", "rest", "sketch", "appearance", "colours"}
    if set(document) != expected:
        raise RequestRefused(f"the request holds exactly {sorted(expected)}")
    plan = document["plan"]
    if not isinstance(plan, dict) or set(plan) != {"key", "version", "sha256", "bones", "limbs"}:
        raise RequestRefused("plan holds key, version, sha256, bones and limbs")
    if not isinstance(plan["key"], str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", plan["key"]):
        raise RequestRefused("plan.key is a lowercase key")
    if (
        not isinstance(plan["version"], int)
        or isinstance(plan["version"], bool)
        or plan["version"] < 1
    ):
        raise RequestRefused("plan.version is a whole number from 1")
    if not isinstance(plan["sha256"], str) or not _HEX.fullmatch(plan["sha256"]):
        raise RequestRefused("plan.sha256 is 64 lowercase hex digits")
    raw_bones = plan["bones"]
    if not isinstance(raw_bones, list) or not 1 <= len(raw_bones) <= _BONES_MAXIMUM:
        raise RequestRefused(f"plan.bones holds 1 to {_BONES_MAXIMUM} bones")
    parents: dict[str, str | None] = {}
    for index, bone in enumerate(raw_bones):
        where = f"plan.bones[{index}]"
        if not isinstance(bone, dict) or set(bone) != {"name", "parent"}:
            raise RequestRefused(f"{where} holds name and parent")
        name, parent = bone["name"], bone["parent"]
        if not isinstance(name, str) or not _BONE.fullmatch(name) or name in parents:
            raise RequestRefused(f"{where}.name is a bone name of its own")
        if parent is None:
            if index != 0:
                raise RequestRefused(f"{where} is a second root; the first bone is the only root")
        elif parent not in parents:
            raise RequestRefused(f"{where}.parent names a bone before it")
        parents[name] = parent
    bones = tuple(parents)
    chains = plan["limbs"]
    if not isinstance(chains, list):
        raise RequestRefused("plan.limbs is a list")
    chained: set[str] = set()
    for index, chain in enumerate(chains):
        where = f"plan.limbs[{index}]"
        if not isinstance(chain, dict) or set(chain) != {"key", "role", "side", "order", "bones"}:
            raise RequestRefused(f"{where} holds key, role, side, order and bones")
        members = chain["bones"]
        if not isinstance(members, list) or not members or not all(m in parents for m in members):
            raise RequestRefused(f"{where}.bones names bones of the plan")
        if chained & set(members):
            raise RequestRefused(f"{where} shares a bone with another chain")
        if any(parents[members[k + 1]] != members[k] for k in range(len(members) - 1)):
            raise RequestRefused(f"{where}.bones run parent to child")
        chained |= set(members)
    rest = document["rest"]
    if not isinstance(rest, dict) or set(rest) != set(bones):
        raise RequestRefused("rest holds every bone of the plan and nothing else")
    joints: dict[str, np.ndarray] = {}
    ends: dict[str, np.ndarray] = {}
    radii: dict[str, float] = {}
    for bone in bones:
        entry = rest[bone]
        if not isinstance(entry, dict) or set(entry) != {"joint_mm", "end_mm", "radius_mm"}:
            raise RequestRefused(f"rest.{bone} holds joint_mm, end_mm and radius_mm")
        joints[bone] = _point(entry["joint_mm"], f"rest.{bone}.joint_mm")
        ends[bone] = _point(entry["end_mm"], f"rest.{bone}.end_mm")
        radius = entry["radius_mm"]
        if (
            not isinstance(radius, int)
            or isinstance(radius, bool)
            or not 1 <= radius <= _MM_MAXIMUM
        ):
            raise RequestRefused(f"rest.{bone}.radius_mm is a whole number from 1")
        radii[bone] = radius / 1000
    sketch = document["sketch"]
    if (
        not isinstance(sketch, dict)
        or set(sketch) != {"sha256", "bytes"}
        or not isinstance(sketch["sha256"], str)
        or not _HEX.fullmatch(sketch["sha256"])
        or not isinstance(sketch["bytes"], int)
        or sketch["bytes"] < 1
    ):
        raise RequestRefused("sketch holds the container's sha256 and its length in bytes")
    appearance = document["appearance"]
    if not isinstance(appearance, str) or not 12 <= len(appearance) <= 200:
        raise RequestRefused("appearance is 12 to 200 characters")
    if any(character.isdigit() for character in appearance):
        raise RequestRefused("appearance holds no numeral")
    colours = document["colours"]
    if not isinstance(colours, dict) or set(colours) != set(COLOUR_ROLES):
        raise RequestRefused(f"colours holds {', '.join(COLOUR_ROLES)}")
    words: dict[str, str] = {}
    srgb: dict[str, tuple[int, int, int]] = {}
    for role in COLOUR_ROLES:
        entry = colours[role]
        if (
            not isinstance(entry, dict)
            or set(entry) != {"word", "srgb"}
            or not isinstance(entry["word"], str)
            or not re.fullmatch(r"[a-z][a-z ]{0,38}[a-z]", entry["word"])
            or not isinstance(entry["srgb"], list)
            or len(entry["srgb"]) != 3
            or not all(
                isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 255
                for value in entry["srgb"]
            )
        ):
            raise RequestRefused(f"colours.{role} is a colour word and its sRGB, each 0 to 255")
        words[role] = entry["word"]
        srgb[role] = (entry["srgb"][0], entry["srgb"][1], entry["srgb"][2])
    return CreatureRequest(
        plan_key=plan["key"],
        plan_version=plan["version"],
        plan_sha256=plan["sha256"],
        bones=bones,
        parents=parents,
        chains=tuple(chains),
        joints=joints,
        ends=ends,
        radii=radii,
        sketch_sha256=sketch["sha256"],
        sketch_bytes=sketch["bytes"],
        appearance=appearance,
        colour_words=words,
        colours=srgb,
    )
