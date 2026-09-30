"""Independently measure a saved town arrival against its generated occupied extents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import psycopg

from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.world.composers import city_grammar_town
from exulanica.world.generated_worlds import town_records


def measure(
    receipt: dict[str, Any], records: tuple[object, ...], served: dict[str, Any]
) -> dict[str, Any]:
    """Use the full occupied rectangle, not a tree trunk or furniture centre."""
    policy_file = Path(city_grammar_town.__file__).with_name("town-arrival.v1.json")
    policy_bytes = policy_file.read_bytes()
    policy = json.loads(policy_bytes)
    point = receipt["arrival"]["position_mm"]
    x, y = point
    occupied = [
        record.extent
        for record in records
        if isinstance(record, (StreetFurnitureRecord, StreetTreeRecord))
    ]
    squared = [
        max(extent.min_x_mm - x, 0, x - extent.max_x_mm) ** 2
        + max(extent.min_y_mm - y, 0, y - extent.max_y_mm) ** 2
        for extent in occupied
    ]
    nearest = min(squared) if squared else None
    expected_arrival = [x, receipt["arrival"]["support_z_mm"], -y]
    facing = receipt["arrival"]["facing_mm"]
    expected_facing = [facing[0], -facing[1]]
    clearance = policy["minimum_object_clearance_mm"]
    policy_digest = hashlib.sha256(policy_bytes).hexdigest()
    return {
        "profile": "exulanica.rehearsal-town-arrival-measure/v1",
        "policy_profile": policy["profile"],
        "policy_sha256": policy_digest,
        "receipt_policy": receipt.get("arrival_policy"),
        "spot_id": receipt["arrival"].get("spot_id"),
        "served_arrival_mm": served.get("arrival_mm"),
        "receipt_arrival_in_served_frame_mm": expected_arrival,
        "served_facing_mm": served.get("arrival_facing_mm"),
        "receipt_facing_in_served_frame_mm": expected_facing,
        "occupied_count": len(occupied),
        "nearest_object_distance_squared_mm": nearest,
        "minimum_object_clearance_mm": clearance,
        "ok": (
            policy["profile"] == "exulanica.town-arrival/v1"
            and receipt.get("arrival_policy")
            == {"profile": policy["profile"], "sha256": policy_digest}
            and str(receipt["arrival"].get("spot_id", "")).startswith("footway:")
            and served.get("arrival_mm") == expected_arrival
            and served.get("arrival_facing_mm") == expected_facing
            and any(expected_facing)
            and nearest is not None
            and nearest >= clearance * clearance
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=uuid.UUID, required=True)
    parser.add_argument("--world", required=True)
    parser.add_argument("--snapshot", type=uuid.UUID, required=True)
    args = parser.parse_args()
    served = json.load(sys.stdin)
    with psycopg.connect(os.environ["EXULANICA_DATABASE_URL"]) as connection:
        generated = town_records(connection, args.workspace, args.world, args.snapshot)
    result = measure(dict(generated.receipt), generated.records, served)
    result.update(
        world_id=args.world,
        source_snapshot_id=str(args.snapshot),
        receipt_sha256=generated.receipt_sha256,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
