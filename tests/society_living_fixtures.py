"""Places for the v4 living society: a synthetic sidewalk grid and the real Flatiron input.

The grid is a fictional 4 m lattice with one visit marker and three rest pads, the same shape of
offer the Flatiron interpretation publishes, so properties can be checked quickly over many
seeds. The Flatiron input is composed offline from the committed district assets by the same
adapter the runtime uses, with no database and no rights assertion.
"""

from __future__ import annotations

import json
import uuid
from functools import cache
from pathlib import Path

from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_place import place_from_society_input

from society_fixtures import seal

ROOT = Path(__file__).resolve().parents[1]
GRID_VERSION = uuid.UUID("6c1f0d36-7a0f-4e8e-9d0e-2f1b8a4c5d01")
GRID_SOCIETY = uuid.uuid5(GRID_VERSION, "exulanica-society/v1")
SEEDS = tuple(f"{n:02x}" * 32 for n in range(1, 13))


@cache
def routine():
    return load_routine_model()


def grid_input(columns: int = 10, rows: int = 6, version_id: uuid.UUID = GRID_VERSION) -> dict:
    version = str(version_id)
    nodes = [
        {
            "node_id": f"walk:{x:02d}:{z:02d}",
            "subject_id": "walk-envelope",
            "position_mm": [x * 4000, z * 4000],
        }
        for x in range(columns)
        for z in range(rows)
    ]
    edges = []
    for x in range(columns):
        for z in range(rows):
            for dx, dz in ((1, 0), (0, 1)):
                if x + dx < columns and z + dz < rows:
                    a, b = f"walk:{x:02d}:{z:02d}", f"walk:{x + dx:02d}:{z + dz:02d}"
                    edges.append(
                        {
                            "edge_id": f"{a}|{b}",
                            "from_node_id": a,
                            "to_node_id": b,
                            "length_mm": 4000,
                            "subject_id": "walk-envelope",
                        }
                    )

    def target(name, node, affordance, duration):
        return {
            "target_id": f"district:{name}:{affordance}",
            "subject_id": f"district:{name}",
            "node_id": node,
            "affordance": affordance,
            "duration_ticks": duration,
            "origin": "district",
            "object_id": None,
            "version_id": version,
            "enabled": True,
        }

    targets = sorted(
        [
            target("marker", "walk:01:01", "visit", 1),
            target("pad-a", f"walk:{columns - 2:02d}:01", "rest", 3),
            target("pad-b", f"walk:01:{rows - 2:02d}", "rest", 3),
            target("pad-c", f"walk:{columns - 2:02d}:{rows - 2:02d}", "rest", 3),
        ],
        key=lambda t: t["target_id"],
    )
    return seal(
        {
            "profile": "exulanica.society-input/v1",
            "input_seq": 1,
            "world_id": "atlas:default",
            "version_id": version,
            "district_id": "synthetic-grid",
            "district_document_sha256": "a" * 64,
            "base_artifact_sha256": "b" * 64,
            "frame": {
                "name": "flatiron-local-mm",
                "origin_crs84_e7": [-739897000, 407410000],
                "axis_order": ["east", "south"],
                "horizontal_unit": "millimetre",
                "altitude_reference": "authored-flat-ground",
            },
            "authored_state": {"edit_seq": 0, "delta_sha256": "c" * 64},
            "navigation": {
                "profile": "bounded-sidewalk-graph/v1",
                "clearance_mm": 450,
                "nodes": sorted(nodes, key=lambda n: n["node_id"]),
                "edges": sorted(edges, key=lambda e: e["edge_id"]),
                "destinations": [
                    {k: t[k] for k in ("node_id", "affordance", "duration_ticks", "subject_id")}
                    | {"destination_id": t["target_id"]}
                    for t in targets
                ],
                "unavailable_reason": None,
            },
            "targets": targets,
            "dependency_refs": [
                {"kind": "fixture", "identity": "synthetic-grid", "sha256": "d" * 64}
            ],
            "availability": "available",
            "unavailable_reason": None,
        }
    )


def grid_place(document: dict | None = None) -> dict:
    return place_from_society_input(document or grid_input(), routine())


@cache
def flatiron_input_json() -> str:
    """The Flatiron society input exactly as the offline recording composes it, with no edits."""
    from scripts.record_living_society import FLATIRON_INTERPRETATION, flatiron_input

    return json.dumps(flatiron_input(FLATIRON_INTERPRETATION))


def flatiron_input() -> dict:
    return json.loads(flatiron_input_json())
