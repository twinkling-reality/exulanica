"""The gate in a 0 A.D. match: a spot on its map, the units standing on it, and what the adapter
asks the game to do there.

A unit's template is its game type with ``/`` written as ``:`` (``units/athen/infantry_spearman_b``
crosses as ``units:athen:infantry_spearman_b``), since a mapping's game types hold no ``/``.
The JavaScript is run in the game's simulation through its interface's ``/evaluate``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "Gate",
    "Unit",
    "at_gate",
    "bring_back",
    "game_type",
    "place_marker",
    "remove",
    "template",
]


@dataclass(frozen=True, slots=True)
class Gate:
    """A circle on the map, in the game's own units (x and z), and the player whose units cross."""

    x: float
    z: float
    radius: float
    player: int

    def holds(self, x: float, z: float) -> bool:
        return math.hypot(x - self.x, z - self.z) <= self.radius


@dataclass(frozen=True, slots=True)
class Unit:
    """A unit the game reports: its entity id, template and owner."""

    entity: int
    template: str
    owner: int


def game_type(template_name: str) -> str:
    """The game type a template crosses as."""
    return template_name.replace("/", ":")


def template(game_type_name: str) -> str:
    """The template a game type names."""
    return game_type_name.replace(":", "/")


def _position(entity: Mapping[str, Any]) -> tuple[float, float] | None:
    position = entity.get("position")
    if not isinstance(position, list | tuple) or len(position) < 2:
        return None
    try:
        # The AI interface writes [x, z]; a three-part position is [x, y, z].
        return float(position[0]), float(position[-1])
    except (TypeError, ValueError):
        return None


def at_gate(state: Mapping[str, Any], gate: Gate, crossing: Iterable[str]) -> list[Unit]:
    """The gate player's units standing on the gate whose templates may cross, lowest id first."""
    allowed = set(crossing)
    found = []
    for key, entity in (state.get("entities") or {}).items():
        if not isinstance(entity, Mapping) or entity.get("owner") != gate.player:
            continue
        name = entity.get("template")
        where = _position(entity)
        if name in allowed and where is not None and gate.holds(*where):
            found.append(Unit(entity=int(key), template=str(name), owner=gate.player))
    return sorted(found, key=lambda unit: unit.entity)


def remove(unit: Unit) -> str:
    """JavaScript that takes ``unit`` out of the match, answering whether it was there."""
    return f"(() => {{ Engine.DestroyEntity({int(unit.entity)}); return true; }})()"


def bring_back(template_name: str, owner: int, gate: Gate) -> str:
    """JavaScript that puts a unit of ``template_name`` back on the gate for ``owner``, answering
    its new entity id."""
    return (
        "(() => {"
        f" let ent = Engine.AddEntity({json.dumps(template_name)});"
        " let position = Engine.QueryInterface(ent, IID_Position);"
        f" position.JumpTo({float(gate.x)}, {float(gate.z)});"
        " let ownership = Engine.QueryInterface(ent, IID_Ownership);"
        f" ownership.SetOwner({int(owner)});"
        " return ent; })()"
    )


def place_marker(template_name: str, gate: Gate) -> str:
    """JavaScript that stands the gate's marker (a standard, by its template) on the gate,
    answering its entity id."""
    return (
        "(() => {"
        f" let ent = Engine.AddEntity({json.dumps(template_name)});"
        " let position = Engine.QueryInterface(ent, IID_Position);"
        f" position.JumpTo({float(gate.x)}, {float(gate.z)});"
        " return ent; })()"
    )
