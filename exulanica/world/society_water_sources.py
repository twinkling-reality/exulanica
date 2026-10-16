"""The water a site's kind worker and a town's composer hand its society's composition.

A society of things over a world's own walking surfaces is composed by the runtime
(:mod:`exulanica.api.society_runtime`) from what it reads before the asset read lock: a site's place
from the kind worker, which hands the site's water over with it, and a town's records, whose land
holds its water. Each becomes a :class:`~exulanica.world.society_water.WaterStatement`: the bodies
the world's composer laid swim nodes over, and what a way to the water's shore keeps clear of.
:func:`water_for_input` hands it to the inputs of a society that swims and to no other, reading
which that is from its first input's row. Apart from :mod:`exulanica.world.society_water` because
it reads the composers and a row, which no society engine does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg

from exulanica.world.composers.city_grammar_town import swim_nodes as town_swim_nodes
from exulanica.world.society_site_place import site_obstructions
from exulanica.world.society_water import WaterStatement, records_swimming

__all__ = ["site_water", "town_water", "water_for_input"]


def site_water(answer: Mapping[str, Any]) -> WaterStatement | None:
    """The water a site world's kind worker hands over with its place (``water``), and what a way
    to its shore keeps clear of: every part its records block walking with (``blocked_parts``) but
    its water. None where the answer states no water, as one kept before the worker stated any."""
    bodies, parts = answer.get("water"), answer.get("blocked_parts")
    if bodies is None or parts is None:
        return None
    dry = [part["box"] for part in parts if part["part"] != "water"]
    return WaterStatement(tuple(bodies), site_obstructions(dry).steps)


def town_water(
    receipt: Mapping[str, Any], records: Sequence[object], obstructions: Any
) -> WaterStatement | None:
    """The water a town's receipt and records hold (``city_grammar_town.swim_nodes``), a way to its
    shore kept clear of the town's own buildings, street furniture and trees (``obstructions``,
    whose ``steps`` answers it); None where the town holds none."""
    bodies = town_swim_nodes(receipt, records)
    return WaterStatement(tuple(bodies), obstructions.steps) if bodies else None


def water_for_input(
    connection: psycopg.Connection, binding: Any, seq: int, water: WaterStatement | None
) -> WaterStatement | None:
    """The water a things input ``seq`` of ``binding``'s version (its workspace, world and version)
    is composed with: ``water``, its world's, for a first input, which lays it where the movement
    modules it records name a swimming, and for a later one where its society's first input
    recorded one; none for any other. Rows only, and none read where the world holds no water."""
    if water is None or seq == 1:
        return water
    row = connection.execute(
        "select i.document->'movement_modules' as modules from world_society s "
        "join world_society_input i on i.workspace_id=s.workspace_id "
        "and i.society_id=s.society_id and i.input_seq=1 "
        "where s.workspace_id=%s and s.world_id=%s and s.version_id=%s",
        (binding.workspace_id, binding.world_id, binding.version_id),
    ).fetchone()
    return water if row is not None and records_swimming(row["modules"]) else None
