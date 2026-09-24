"""How many inhabitants use each object of a small square in 30 simulated minutes, before and after.

usage: uv run python scripts/measure_furniture_use.py --out <file.json>

In process and without a database, from the product's own parts:

- the ground is the starter world's own (``authored_starter_candidate``, read the way the society
  reads a saved world's snapshot, ``authored_ground_from_snapshot``);
- the square stands where the arrangement resolver puts it for a person at the world's arrival
  point facing its centre (``exulanica.world.arrangements.lay_out``);
- the world is composed as a saved world is (``build_authored_ground_society_input_v2``) under the
  reviewed affordance registry a host registers (``reviewed_affordance_registry``), with the
  standing figures the society runtime reads;
- inhabitants are the saved-world population (``AUTHORED_GROUND_POPULATION``), advanced by the
  engine a saved world runs by default (``exulanica-society/v2``, the purposeful planner), one tick
  a simulated minute.

Two arms over the same positions and turns:

- ``after``: the square's furniture, as the world object catalog states it;
- ``before``: each object replaced by the marker of the same use, the one kind of thing a person
  could place before the catalog held furniture: a marker plate where people rest, a marker cube
  where they visit. A kind nobody uses (the lamp post) has no marker and is left out.

A use is an inhabitant starting an activity at an object: the planner's ``route_progressed`` event
whose outcome is ``action_started`` and whose target names the object. Per object and seed the
script counts the distinct inhabitants who start one and the activities started. Seeds are
``sha256("furniture-use:<n>")`` for n = 1 to 12.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from exulanica.environment.district_geometry import segment_blocked
from exulanica.world.arrangements import arrangement_catalog, lay_out
from exulanica.world.assets import reviewed_assets
from exulanica.world.authored_delta import AlternateVersion, delta_sha256
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.society_authored_ground import (
    AUTHORED_GROUND_POPULATION,
    LATTICE_MM,
    SocietyGround,
    StandingPolicy,
    authored_ground_from_snapshot,
    build_authored_ground_society_input_v2,
)
from exulanica.world.society_composition import reviewed_affordance_registry
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import (
    PURPOSEFUL_PROFILE,
    advance_purposeful_society,
    initial_purposeful_society,
)
from exulanica.world.starter import (
    AUTHORED_SPAWN_X_MM,
    AUTHORED_SPAWN_Z_MM,
    authored_starter_candidate,
)

#: The measurement the brief asks for: 12 seeds, 30 simulated minutes (a tick is one minute).
SEED_COUNT = 12
TICKS = 30
#: Where the person stands and faces when they ask: the arrival point, facing the world's centre
#: (-z), which is half a turn, as the web client states a heading (yaw = atan2(fx, fz)).
FACING_THE_CENTRE_MICRORADIANS = 3_141_593
ARRANGEMENT_KEY = "small_square"
#: The marker of each use, for the before arm: what a person could place before the catalog.
MARKER_OF_USE = {"rest": "cc0.marker-plate", "visit": "cc0.marker-cube"}
WORLD_ID = "world:authored:furniture-use-measurement"
SNAPSHOT_ID = uuid.UUID(int=1)
VERSION_ID = uuid.UUID(int=2)
SOCIETY_ID = uuid.UUID(int=3)


def seeds() -> list[str]:
    return [
        hashlib.sha256(f"furniture-use:{n}".encode()).hexdigest() for n in range(1, SEED_COUNT + 1)
    ]


def starter_ground() -> SocietyGround:
    candidate = authored_starter_candidate(WORLD_ID)
    return authored_ground_from_snapshot(
        world_id=WORLD_ID,
        snapshot_id=SNAPSHOT_ID,
        snapshot_sha256=candidate.graph_sha256,
        composer_key=candidate.composer_key,
        composer_version=candidate.composer_version,
        topology=candidate.topology,
        placement=candidate.placement,
    )


def square_objects(ground: SocietyGround, arm: str) -> list[tuple[str, AuthoredObject]]:
    """Each object of the arm as ``(what it is, the object)``, in the arrangement's order."""
    square = arrangement_catalog().by_key()[ARRANGEMENT_KEY]
    layout = lay_out(
        square,
        viewer_x_mm=AUTHORED_SPAWN_X_MM,
        viewer_z_mm=AUTHORED_SPAWN_Z_MM,
        viewer_yaw_microradians=FACING_THE_CENTRE_MICRORADIANS,
        spacing_mm=LATTICE_MM,
    )
    digests = {asset.asset_key: asset.content_sha256 for asset in reviewed_assets()}
    out: list[tuple[str, AuthoredObject]] = []
    for index, placed in enumerate(layout.objects):
        kind = placed.placement.kind
        if arm == "after":
            asset_key = kind.asset_key
        elif kind.use.affordance in MARKER_OF_USE:
            asset_key = MARKER_OF_USE[kind.use.affordance]
        else:
            continue
        name = f"{index + 1}-{kind.key}"
        out.append(
            (
                name,
                AuthoredObject(
                    object_id=f"object:{name}",
                    asset_sha256=digests[asset_key],
                    region_id=ground.region_id,
                    transform=Transform(
                        placed.centre[0],
                        ground.elevation_mm,
                        placed.centre[1],
                        placed.yaw_microradians,
                        1000,
                    ),
                    origin=ObjectOrigin("authored", "fictional"),
                ),
            )
        )
    return out


def version_of(objects: Sequence[AuthoredObject]) -> AlternateVersion:
    return AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=SNAPSHOT_ID,
        parent_version_id=None,
        title="A world of my own",
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects, element_overrides=(), environment_instances=(), point_map_instances=()
        ),
        edit_seq=len(objects),
        source_invalidated=False,
        created_by=uuid.UUID(int=4),
        created_at="2026-09-24T00:00:00+00:00",
        objects=tuple(objects),
    )


def compose(ground: SocietyGround, objects: Sequence[AuthoredObject]) -> dict[str, Any]:
    policy = current_routine().policy
    return build_authored_ground_society_input_v2(
        ground=ground,
        version=version_of(objects),
        input_seq=1,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=reviewed_affordance_registry(),
        segment_blocked=segment_blocked,
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
    )


def uses(document: dict[str, Any], seed: str) -> dict[str, dict[str, int]]:
    """Per object id: distinct inhabitants who started an activity there, and activities started."""
    state = initial_purposeful_society(
        SOCIETY_ID, seed, document, population=AUTHORED_GROUND_POPULATION
    )
    people: dict[str, set[str]] = {}
    starts: dict[str, int] = {}
    for _ in range(TICKS):
        state, events = advance_purposeful_society(state, seed, [document])
        for event in events:
            doc = event.document
            target = doc.get("target") or {}
            object_id = target.get("object_id")
            if event.kind != "route_progressed" or doc.get("outcome") != "action_started":
                continue
            if object_id is None:
                continue
            people.setdefault(object_id, set()).add(str(doc["subject_id"]))
            starts[object_id] = starts.get(object_id, 0) + 1
    return {
        object_id: {"inhabitants": len(people[object_id]), "activities": starts[object_id]}
        for object_id in people
    }


def summary(values: list[int]) -> dict[str, Any]:
    return {
        "per_seed": values,
        "min": min(values),
        "mean": round(statistics.fmean(values), 2),
        "max": max(values),
    }


def measure_arm(ground: SocietyGround, arm: str) -> dict[str, Any]:
    named = square_objects(ground, arm)
    document = compose(ground, [obj for _, obj in named])
    targets = {t["object_id"]: t for t in document["targets"] if t["origin"] == "authored"}
    runs = [uses(document, seed) for seed in seeds()]
    objects: dict[str, Any] = {}
    for name, obj in named:
        target = targets.get(obj.object_id)
        objects[name] = {
            "asset_key": next(
                a.asset_key for a in reviewed_assets() if a.content_sha256 == obj.asset_sha256
            ),
            "affordance": None if target is None else target["affordance"],
            "places": None if target is None else len(target.get("place_node_ids", [])),
            "inhabitants": summary(
                [run.get(obj.object_id, {}).get("inhabitants", 0) for run in runs]
            ),
            "activities": summary(
                [run.get(obj.object_id, {}).get("activities", 0) for run in runs]
            ),
        }
    totals = [sum(run[o]["inhabitants"] for o in run) for run in runs]
    started = [sum(run[o]["activities"] for o in run) for run in runs]
    return {
        "availability": document["availability"],
        "unavailable_reason": document["unavailable_reason"],
        "unavailable_affordances": document["unavailable_affordances"],
        "input_sha256": document["document_sha256"],
        "objects": objects,
        "object_inhabitant_pairs": summary(totals),
        "activities_started": summary(started),
        "objects_used": summary([len(run) for run in runs]),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="where to write the JSON record")
    args = parser.parse_args(argv)
    ground = starter_ground()
    record = {
        "measurement": "furniture use in a small square",
        "script": "scripts/measure_furniture_use.py",
        "engine": PURPOSEFUL_PROFILE,
        "population": AUTHORED_GROUND_POPULATION,
        "ticks": TICKS,
        "seeds": seeds(),
        "ground": {"module_version": ground.module_version, "area": ground.area.document()},
        "arms": {arm: measure_arm(ground, arm) for arm in ("before", "after")},
    }
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    for arm, result in record["arms"].items():
        print(f"{arm}: {result['availability']}, input {result['input_sha256'][:12]}")
        for name, row in result["objects"].items():
            print(
                f"  {name:<22} {row['asset_key']:<22} {row['affordance'] or '-':<6} "
                f"places {row['places'] if row['places'] is not None else '-':>2}  "
                f"inhabitants mean {row['inhabitants']['mean']:>5} "
                f"(min {row['inhabitants']['min']}, max {row['inhabitants']['max']})  "
                f"activities mean {row['activities']['mean']:>5}"
            )
        print(
            f"  objects used per seed mean {result['objects_used']['mean']}; "
            f"object-inhabitant pairs mean {result['object_inhabitant_pairs']['mean']}; "
            f"activities started mean {result['activities_started']['mean']}"
        )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
