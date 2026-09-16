"""L-shaped walkway and reviewed fictional markers, not admitted/personal world evidence."""

import uuid
from copy import deepcopy

from exulanica.world.society_planner import input_sha256

VERSION = uuid.UUID("2aabed81-6d84-45b9-9118-955577550ca1")
SOCIETY = uuid.uuid5(VERSION, "exulanica-society/v1")
SEED = "7a" * 32


def seal(document):
    document["document_sha256"] = input_sha256(document)
    return document


def society_input(version_id=VERSION):
    version = str(version_id)
    targets = [
        {
            "target_id": "authored:bench:rest",
            "subject_id": "authored:bench",
            "node_id": "c",
            "affordance": "rest",
            "duration_ticks": 3,
            "origin": "authored",
            "object_id": "object:bench",
            "version_id": version,
            "enabled": True,
        },
        {
            "target_id": "district:marker:visit",
            "subject_id": "district:marker",
            "node_id": "b",
            "affordance": "visit",
            "duration_ticks": 1,
            "origin": "district",
            "object_id": None,
            "version_id": version,
            "enabled": True,
        },
    ]
    return seal(
        {
            "profile": "exulanica.society-input/v1",
            "input_seq": 1,
            "world_id": "atlas:default",
            "version_id": version,
            "district_id": "synthetic-walkway",
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
                "nodes": [
                    {"node_id": n, "subject_id": "walk:" + n, "position_mm": point}
                    for n, point in [
                        ("a", [0, 0]),
                        ("b", [40000, 0]),
                        ("c", [40000, 40000]),
                        ("d", [90000, 0]),
                    ]
                ],
                "edges": [
                    {
                        "edge_id": "ab",
                        "from_node_id": "a",
                        "to_node_id": "b",
                        "length_mm": 40000,
                        "subject_id": "walk:ab",
                    },
                    {
                        "edge_id": "bc",
                        "from_node_id": "b",
                        "to_node_id": "c",
                        "length_mm": 40000,
                        "subject_id": "walk:bc",
                    },
                ],
                "destinations": [
                    {
                        "destination_id": "district:marker:visit",
                        "subject_id": "district:marker",
                        "node_id": "b",
                        "affordance": "visit",
                        "duration_ticks": 1,
                    }
                ],
                "unavailable_reason": None,
            },
            "targets": targets,
            "dependency_refs": [
                {"kind": "fixture", "identity": "synthetic-walkway", "sha256": "d" * 64}
            ],
            "availability": "available",
            "unavailable_reason": None,
        }
    )


def edited(document):
    result = deepcopy(document)
    result["input_seq"] += 1
    result["authored_state"]["edit_seq"] += 1
    result["authored_state"]["delta_sha256"] = f"{result['input_seq']:064x}"
    return result
