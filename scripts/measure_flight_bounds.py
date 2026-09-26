"""Measure the flight module over stated seeds: bounds, solids, homecoming, replay, request cost.

    uv run python scripts/measure_flight_bounds.py --seeds judged-2 --minutes 30 --out FILE
    uv run python scripts/measure_flight_bounds.py --request-cost --repeats 5 --out FILE

Every world is composed by the flight route's own composer
(:func:`exulanica.world.flight_input.compose_flight_input`) over a starter world's endless ground,
with objects placed as a person places them:

- ``small_square``: the small square laid out before the arrival point, facing the centre, as the
  arrangement route lays it out; its planter tree hosts 3 small birds;
- ``eight_trees``: eight planter trees on a 5 m by 8 m grid, each turned a sixth of a turn from the
  last, hosting 24 small birds, the flight module's largest population;
- ``crowded_crowns``: four of those trees and four more at 1.6 times their size, 2.5 m east of them,
  whose crowns fill the band the birds fly in;
- ``cluttered``: the small square, seven more trees where the page's timing harness plants them,
  and twenty more objects of every placeable kind across the far side of the ground, 24 small birds
  among 36 objects.

For each world and seed, the flight is served in windows of ``max_steps_per_request`` steps from step
0 for the stated simulated minutes, as a page asks for it; every window is computed twice, its
digest compared, and the whole run is judged by the independent checker
(:func:`exulanica.movement.flight_checks.check_windows`): each window, the move joining it to the
last, the move into every episode, every flyer at home at every episode's end, and every body clear
of every part. Each run is stamped with when it started and finished.

The request cost is process time, of the composer building a world's air, of one cold window at the
step before an episode ends (the most a window computes: 2,999 steps to reach it and 600 more), of
one cold window at an episode's first step, and of a window resumed from the one before it, as a
page reading minute after minute is served. It times the flight module's functions alone, not a
request's reading of the database or its answer.

Writes canonical JSON; nothing else. Pure computation: no database, no network, no store.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.movement.flight import (  # noqa: E402
    FLIGHT_MODULE,
    FlightInput,
    flight_input,
    flight_window,
)
from exulanica.movement.flight_checks import check_windows  # noqa: E402
from exulanica.world.arrangements import arrangement_catalog, lay_out  # noqa: E402
from exulanica.world.assets import reviewed_assets  # noqa: E402
from exulanica.world.authored_delta import AlternateVersion, delta_sha256  # noqa: E402
from exulanica.world.flight_input import compose_flight_input, served_window  # noqa: E402
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform  # noqa: E402
from exulanica.world.society_authored_ground import (  # noqa: E402
    DECLARED_HALF_EXTENT_MM,
    LATTICE_MM,
    SocietyGround,
    WalkableArea,
)
from exulanica.world.starter import (  # noqa: E402
    AUTHORED_GROUND_ELEVATION_MM,
    AUTHORED_GROUND_MODULE,
    AUTHORED_GROUND_MODULE_VERSION,
    AUTHORED_SPAWN_X_MM,
    AUTHORED_SPAWN_Z_MM,
    AUTHORED_STARTER_ELEMENT_ID,
    AUTHORED_STARTER_REGION_ID,
)

PROFILE = "exulanica.flight-bounds/v1"
#: The measurement's own world and version identities; a flyer's identity derives from them.
WORLD_ID = "world:authored:flight-bounds"
VERSION_ID = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/flight-bounds/version")
SNAPSHOT_ID = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/flight-bounds/snapshot")
#: A person standing where a starter world puts them, facing its centre (-z): half a turn.
FACING_THE_CENTRE = 3_141_593
#: The yaw between one tree and the next in the tree worlds, a sixth of a turn, in microradians.
TURN_STEP_MICRORADIANS = 1_047_198
TURN_MICRORADIANS = 6_283_185
#: The tall trees of the crowded world: 1.6 times the catalog tree, 9.04 m to the crown's top.
TALL_SCALE_MILLI = 1_600
#: How far east of its partner each tall tree stands, so their crowns overlap in plan.
TALL_OFFSET_MM = 2_500
WINDOW = FLIGHT_MODULE.value("max_steps_per_request")
EPISODE = FLIGHT_MODULE.value("episode_steps")
STEPS_PER_MINUTE = 60_000 // FLIGHT_MODULE.step_ms


def seeds(kind: str) -> list[str]:
    """Twelve seeds of the named set: ``judged`` for the record, ``development`` for tests."""
    return [
        hashlib.sha256(f"exulanica.flight/v1/{kind}/{index}".encode()).hexdigest()
        for index in range(12)
    ]


def _assets() -> dict[str, str]:
    return {asset.asset_key: asset.content_sha256 for asset in reviewed_assets()}


def ground() -> SocietyGround:
    """A starter world's endless ground, with the area the society declares on it."""
    return SocietyGround(
        world_id=WORLD_ID,
        snapshot_id=SNAPSHOT_ID,
        snapshot_sha256=hashlib.sha256(b"exulanica.flight-bounds/snapshot").hexdigest(),
        region_id=AUTHORED_STARTER_REGION_ID,
        element_id=AUTHORED_STARTER_ELEMENT_ID,
        module_key=AUTHORED_GROUND_MODULE,
        module_version=AUTHORED_GROUND_MODULE_VERSION,
        ground_kind="endless",
        elevation_mm=AUTHORED_GROUND_ELEVATION_MM,
        area=WalkableArea("declared", 0, 0, DECLARED_HALF_EXTENT_MM, DECLARED_HALF_EXTENT_MM),
        arrival_x_mm=AUTHORED_SPAWN_X_MM,
        arrival_z_mm=AUTHORED_SPAWN_Z_MM,
    )


def _placed(object_id: str, asset_key: str, x: int, z: int, yaw: int, scale: int) -> AuthoredObject:
    return AuthoredObject(
        object_id=object_id,
        asset_sha256=_assets()[asset_key],
        region_id=AUTHORED_STARTER_REGION_ID,
        transform=Transform(x, AUTHORED_GROUND_ELEVATION_MM, z, yaw, scale),
        origin=ObjectOrigin("authored", "fictional"),
    )


def square_objects() -> tuple[AuthoredObject, ...]:
    """The small square before the arrival point, as the arrangement route lays it out."""
    square = arrangement_catalog().by_key()["small_square"]
    layout = lay_out(
        square,
        viewer_x_mm=AUTHORED_SPAWN_X_MM,
        viewer_z_mm=AUTHORED_SPAWN_Z_MM,
        viewer_yaw_microradians=FACING_THE_CENTRE,
        spacing_mm=LATTICE_MM,
    )
    return tuple(
        _placed(
            f"{square.key}-1-{index}-{placed.placement.kind.key}",
            placed.placement.kind.asset_key,
            placed.centre[0],
            placed.centre[1],
            placed.yaw_microradians,
            1000,
        )
        for index, placed in enumerate(layout.objects, 1)
    )


def tree_objects(
    count: int, scale_milli: int = 1000, east_mm: int = 0
) -> tuple[AuthoredObject, ...]:
    """``count`` planter trees on a 5 m by 8 m grid, each turned a sixth of a turn from the last."""
    prefix = "tree" if scale_milli == 1000 and east_mm == 0 else "tall-tree"
    return tuple(
        _placed(
            f"{prefix}-{index}",
            "cc0.planter-tree",
            -8_000 + (index % 4) * 5_000 + east_mm,
            -8_000 + (index // 4) * 8_000,
            index * TURN_STEP_MICRORADIANS % TURN_MICRORADIANS,
            scale_milli,
        )
        for index in range(count)
    )


#: Where the page's timing harness plants seven more trees beside the small square: at least 4 m
#: from each other and from the square's tree, so no tree's crown, grown by a bird's half span,
#: reaches another's perch columns and every tree starts its three birds.
HARNESS_TREES = (
    (-9_000, -9_500),
    (-4_000, -10_500),
    (4_000, -10_500),
    (9_000, -9_500),
    (-9_500, 1_000),
    (9_500, 1_000),
    (0, -10_500),
)
#: The kinds that clutter the far side of the cluttered world, in the order they are laid out.
CLUTTER_KINDS = (
    "cc0.bench",
    "cc0.cafe-table",
    "cc0.market-stall",
    "cc0.seating-planter",
    "cc0.lamp-post",
)


def cluttered_objects() -> tuple[AuthoredObject, ...]:
    """The small square, the harness's seven trees, and twenty objects on a 4 m grid beyond it."""
    trees = tuple(
        _placed(f"harness-tree-{index}", "cc0.planter-tree", x, z, FACING_THE_CENTRE, 1000)
        for index, (x, z) in enumerate(HARNESS_TREES)
    )
    clutter = tuple(
        _placed(
            f"clutter-{index}",
            CLUTTER_KINDS[index % len(CLUTTER_KINDS)],
            -8_000 + (index % 5) * 4_000,
            5_000 + (index // 5) * 2_000,
            index * TURN_STEP_MICRORADIANS % TURN_MICRORADIANS,
            1000,
        )
        for index in range(20)
    )
    return square_objects() + trees + clutter


def world_objects(name: str) -> tuple[AuthoredObject, ...]:
    if name == "small_square":
        return square_objects()
    if name == "eight_trees":
        return tree_objects(8)
    if name == "crowded_crowns":
        return tree_objects(4) + tree_objects(4, TALL_SCALE_MILLI, TALL_OFFSET_MM)
    if name == "cluttered":
        return cluttered_objects()
    raise ValueError(f"no world named {name!r}")


WORLDS = ("small_square", "eight_trees", "crowded_crowns", "cluttered")


def compose(name: str) -> FlightInput:
    """A world's flight, composed by the route's own composer."""
    objects = world_objects(name)
    version = AlternateVersion(
        version_id=VERSION_ID,
        world_id=WORLD_ID,
        source_snapshot_id=SNAPSHOT_ID,
        parent_version_id=None,
        title=name,
        style_version_id=None,
        state_sha256=delta_sha256(
            objects=objects, element_overrides=(), environment_instances=(), point_map_instances=()
        ),
        edit_seq=len(objects),
        source_invalidated=False,
        created_by=uuid.UUID(int=1),
        created_at="2026-09-25T00:00:00+00:00",
        objects=objects,
    )
    keys = {digest: key for key, digest in _assets().items()}
    return compose_flight_input(
        world_id=WORLD_ID, version=version, ground=ground(), asset_keys=keys
    )


def seeded(flight: FlightInput, seed: str) -> FlightInput:
    """The same world flown from another seed: every draw differs, nothing else."""
    return flight_input(
        world_id=flight.world_id,
        version_id=flight.version_id,
        seed=seed,
        occupancy=flight.occupancy,
        perches=flight.perches,
        kinds=flight.kinds,
        flyers=flight.flyers,
        solids=flight.solids,
        unplaced=flight.unplaced,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def run_bounds(seed_kind: str, minutes: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "profile": PROFILE,
        "seeds": {"kind": seed_kind, "values": seeds(seed_kind)},
        "minutes": minutes,
        "window_steps": WINDOW,
        "started_at": _now(),
        "worlds": {},
    }
    steps = minutes * STEPS_PER_MINUTE
    for name in WORLDS:
        base = compose(name)
        world: dict[str, Any] = {
            "flyers": len(base.flyers),
            "perches": len(base.perches),
            "unplaced": [dict(row) for row in base.unplaced],
            "solids": len(base.solids),
            "solid_cells": base.occupancy.solid_cells(),
            "clearance_mm": base.clearance_mm,
            "occupancy_sha256": base.occupancy.sha256,
            "started_at": _now(),
            "runs": [],
        }
        for seed in seeds(seed_kind):
            flight = seeded(base, seed)
            started = time.process_time()
            windows = []
            mismatched = 0
            for start in range(0, steps, WINDOW):
                window = flight_window(flight, start, WINDOW)
                mismatched += _digest(window) != _digest(flight_window(flight, start, WINDOW))
                windows.append(window)
            check = check_windows(flight, windows)
            rules = Counter(violation["rule"] for violation in check.violations)
            world["runs"].append(
                {
                    "seed": seed,
                    "input_sha256": flight.sha256,
                    "violation_count": len(check.violations),
                    "violations_by_rule": dict(sorted(rules.items())),
                    "violations": check.violations[:20],
                    "late_home": check.late_home,
                    "late_home_reported": sum(len(window["late_home"]) for window in windows),
                    "episode_ends": check.episode_ends,
                    "guard_interventions": check.guard_holds,
                    "segments": check.segments,
                    "state_samples": dict(sorted(check.states.items())),
                    "replay_mismatches": mismatched,
                    "windows_sha256": _digest([_digest(window) for window in windows]),
                    "process_seconds_milli": round((time.process_time() - started) * 1000),
                }
            )
        world["finished_at"] = _now()
        out["worlds"][name] = world
    out["finished_at"] = _now()
    return out


def _timed(repeats: int, run: Any) -> dict[str, Any]:
    times = []
    for index in range(repeats):
        started = time.process_time()
        run(index)
        times.append(round((time.process_time() - started) * 1_000_000))
    return {"process_us": times, "median_us": sorted(times)[len(times) // 2]}


def run_request_cost(repeats: int) -> dict[str, Any]:
    """Process time of the flight module's parts of a request, in the worlds with 24 flyers."""
    worst = EPISODE - 1
    out: dict[str, Any] = {
        "profile": f"{PROFILE}/request-cost",
        "window_steps": WINDOW,
        "started_at": _now(),
        "arms": [],
    }
    for name in ("eight_trees", "cluttered"):
        flight = compose(name)
        arms = {
            "compose the air and perches": lambda _index, name=name: compose(name),
            f"cold window from step {worst}": (
                lambda _index, flight=flight: flight_window(flight, worst, WINDOW)
            ),
            f"cold window from step {EPISODE}": (
                lambda _index, flight=flight: flight_window(flight, EPISODE, WINDOW)
            ),
        }
        for label, run in arms.items():
            out["arms"].append(
                {"world": name, "flyers": len(flight.flyers), "arm": label, **_timed(repeats, run)}
            )
        # A page reading minute after minute: each window resumes from the one before.
        served_window(flight, 0, WINDOW)
        resumed = _timed(
            repeats,
            lambda index, flight=flight: served_window(flight, (index + 1) * WINDOW, WINDOW),
        )
        out["arms"].append(
            {
                "world": name,
                "flyers": len(flight.flyers),
                "arm": "window resumed from the one before",
                **resumed,
            }
        )
    out["finished_at"] = _now()
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--seeds", choices=("judged", "judged-2", "development"), default="development"
    )
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--request-cost", action="store_true")
    parser.add_argument("--repeats", type=int, default=5)
    arguments = parser.parse_args()
    if arguments.request_cost:
        result = run_request_cost(arguments.repeats)
    else:
        result = run_bounds(arguments.seeds, arguments.minutes)
    Path(arguments.out).write_bytes(canonical_json(result))


if __name__ == "__main__":
    main()
