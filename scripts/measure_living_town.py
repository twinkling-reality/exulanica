#!/usr/bin/env python3
"""Measure what a town's living society (``exulanica-society/v5``) costs and how its day divides.

    uv run python scripts/measure_living_town.py --recipe market_town \
        --values '{"city_extent_x_mm": 384000, "block_length_mm": 140000,
                   "storey_band_low": 3, "storey_band_high": 5}' --worlds 8 --out PATH

Pure: no database, no store and no model. For ``--worlds`` identities of one preset made with
``--values`` through the gate every request passes (``town_recipe``), it composes each town's
walking-surfaces-v2 input as the runtime does, and keeps the town whose homes hold the most people:
the largest the preset admits. For that town it measures, each minute's wall-clock and process CPU
time on this machine:

* **The day under v4's rule**: the same town's records made into a place under the district's
  living routine (every resident a position is open to takes it, no opening hours) and a whole
  simulated day from 06:00, as the living engine over a district plays it.
* **The day under the living town**: the town's own input and routine, a whole simulated day from
  its start; each minute's time, and on every hour the count of people at each activity and
  outdoors.
* **The stated 128**: the same town's graph with its homes holding 128 people, the ground's bound
  (``society-ground`` v2), each residential unit taking one more resident in address order until
  they do; ``--ticks`` minutes from genesis.
* **An hour's replay**: genesis and sixty minutes over the stored input, the work a replay of an
  hour does (a comparison's replay line), at the town's own population and at 128.

Before and after the whole run it samples the machine's CPU idle share over ten seconds (``top``)
and the load average, and writes both into the output. Run it inside ``.exulanica/bin/quiet-slot``.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import time
import uuid
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import GeneratedWorldRefused
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_living import (
    LIVING_PROFILE,
    LIVING_TOWN_PROFILE,
    LivingPlace,
    advance_living_society,
    current_routine,
    initial_living_society,
    input_routine,
    living_places,
    town_routine,
)
from exulanica.world.society_place import place_from_town_input, seal_place
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import town_recipe


#: The seed every measured society is made with: any lowercase SHA-256 text.
_SEED = "5" * 64
#: The population the town's ground holds at most (``society-ground`` v2, generated_town).
STATED_POPULATION = 128
#: How long the CPU idle share is sampled for, before and after the run, in seconds.
IDLE_SAMPLE_SECONDS = 10
#: The minutes of a replayed hour.
HOUR = 60


def version_of(world_id: str, snapshot_id: uuid.UUID) -> AlternateVersion:
    """A generated world's first authored version, with no edits, as the runtime reads it."""
    empty = AlternateVersion(
        version_id=uuid.uuid5(uuid.NAMESPACE_URL, world_id),
        world_id=world_id,
        source_snapshot_id=snapshot_id,
        parent_version_id=None,
        title="measured",
        style_version_id=None,
        state_sha256="0" * 64,
        edit_seq=0,
        source_invalidated=False,
        created_by=uuid.UUID(int=0),
        created_at="2026-09-29T00:00:00+00:00",
    )
    return AlternateVersion(
        **{
            **{field: getattr(empty, field) for field in empty.__slots__},
            "state_sha256": version_delta_sha256(empty),
        }
    )


def idle_share() -> float | None:
    """The CPU idle percentage over the next ten seconds, from ``top``, or None off macOS."""
    if platform.system() != "Darwin":
        return None
    out = subprocess.run(
        ["top", "-l", "2", "-s", str(IDLE_SAMPLE_SECONDS), "-n", "0"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lines = [line for line in out.splitlines() if line.startswith("CPU usage")]
    return float(lines[-1].split(",")[2].split("%")[0].strip())


def load() -> str:
    return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()


def spread(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 3),
        "median": round(statistics.median(ordered), 3),
        "p95": round(ordered[max(0, -(-95 * len(ordered) // 100) - 1)], 3),
        "max": round(ordered[-1], 3),
    }


def timed(run: Callable[[], Any]) -> tuple[Any, float, float]:
    wall, cpu = time.perf_counter(), time.process_time()
    value = run()
    return value, time.perf_counter() - wall, time.process_time() - cpu


def town(recipe, index: int) -> dict[str, Any] | None:
    world_id = f"world:generated:living-town-measured-{index}"
    try:
        composed = compose_generated_world(recipe, world_id)
    except GeneratedWorldRefused:
        return None
    snapshot_id = uuid.uuid5(uuid.NAMESPACE_URL, composed.receipt_sha256)
    ground = authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=composed.receipt_sha256,
        composer_key=composed.candidate.composer_key,
        composer_version=composed.candidate.composer_version,
        topology=composed.candidate.topology,
        placement=composed.candidate.placement,
    )
    routine = town_routine()
    policy = routine.policy
    document = build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=walking_surfaces_place(ground.place_id, composed.records, routine),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        living=routine,
    )
    return {"world_id": world_id, "document": document, "records": composed.records}


def day(state: dict[str, Any], place: LivingPlace, routine, minutes: int) -> dict[str, Any]:
    """``minutes`` minutes from ``state``: each minute's times and, on every hour, the counts."""
    wall, cpu, hours = [], [], {}
    for _ in range(minutes):
        (state, _events), w, c = timed(
            lambda s=state: advance_living_society(s, _SEED, [place], routine)
        )
        wall.append(w * 1000)
        cpu.append(c * 1000)
        minute = state["clock"]["minute_of_day"]
        if minute % 60 == 0:
            kinds = Counter(p["action"]["kind"] for p in state["inhabitants"])
            hours[f"{minute // 60:02d}:00"] = {
                "outdoors": sum(1 for p in state["inhabitants"] if not p["location"]["indoors"]),
                "at_work": kinds["work"],
                "activities": dict(sorted(kinds.items())),
            }
    return {"tick_wall_ms": spread(wall), "tick_cpu_ms": spread(cpu), "hourly": hours}


def with_homes(document: dict[str, Any], population: int) -> dict[str, Any]:
    """The town's living input with its homes holding ``population`` people, one more resident
    for each residential unit in address order until they do; the rest of the place unchanged."""
    changed = json.loads(json.dumps(document))
    place = changed["living"]["place"]
    homes = sorted(
        (d for d in place["destinations"] if d["resident_capacity"]),
        key=lambda d: d["destination_id"],
    )
    total = sum(d["resident_capacity"] for d in homes)
    index = 0
    while total < population:
        homes[index % len(homes)]["resident_capacity"] += 1
        total += 1
        index += 1
    place.pop("document_sha256")
    seal_place(place)
    changed["population"]["size"] = population
    return changed


def genesis(document: dict[str, Any], profile: str, routine, place: LivingPlace, size: int):
    return initial_living_society(
        uuid.uuid5(uuid.NAMESPACE_URL, document["world_id"]),
        _SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=size,
        profile=profile,
    )


def replay_hour(document: dict[str, Any], size: int) -> float:
    """Genesis and sixty minutes over a stored input, with no place prepared before: seconds."""

    def run() -> None:
        routine = input_routine(document)
        [place] = living_places([document], routine, {})
        state = genesis(document, LIVING_TOWN_PROFILE, routine, place, size)
        for _ in range(HOUR):
            state, _ = advance_living_society(state, _SEED, [place], routine)

    return timed(run)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", default="market_town")
    parser.add_argument("--values", default=None, help="a JSON object of the preset's values")
    parser.add_argument("--worlds", type=int, default=8)
    parser.add_argument("--ticks", type=int, default=240)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    recipe = town_recipe(args.recipe, json.loads(args.values) if args.values else None)
    idle_before, load_before = idle_share(), load()
    towns, refused = [], 0
    for index in range(args.worlds):
        made = town(recipe, index)
        if made is None:
            refused += 1
        else:
            towns.append(made)
    largest = max(towns, key=lambda t: t["document"]["population"]["size"])
    document = largest["document"]
    size = document["population"]["size"]
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    v5 = day(genesis(document, LIVING_TOWN_PROFILE, routine, place, size), place, routine, 1440)
    district = current_routine()
    district_place = LivingPlace(
        {
            **place_from_town_input(
                {
                    **document,
                    "living": {
                        "routine": district.binding(),
                        "place": walking_surfaces_place(
                            document["district_id"], largest["records"], district
                        ),
                    },
                }
            ),
        },
        district,
    )
    state = genesis(document, LIVING_PROFILE, district, district_place, size)
    # The district's routine starts at 08:00; its day is measured from the town's 06:00 alike.
    start = routine.policy["start_minute_of_day"]
    state["clock"] = {"start_minute_of_day": start, "minute_of_day": start, "day": 0}
    v4 = day(state, district_place, district, 1440)
    stated_document = with_homes(document, STATED_POPULATION)
    [stated_place] = living_places([stated_document], routine, {})
    stated = day(
        genesis(stated_document, LIVING_TOWN_PROFILE, routine, stated_place, STATED_POPULATION),
        stated_place,
        routine,
        args.ticks,
    )
    record = {
        "script": "scripts/measure_living_town.py",
        "recipe": args.recipe,
        "values": json.loads(args.values) if args.values else None,
        "worlds_asked": args.worlds,
        "worlds_refused": refused,
        "residents_by_world": [t["document"]["population"]["size"] for t in towns],
        "largest": {
            "world_id": largest["world_id"],
            "residents": size,
            "nodes": len(document["living"]["place"]["nodes"]),
            "spots": len(document["living"]["place"]["spots"]),
            "destinations": len(document["living"]["place"]["destinations"]),
            "input_json_bytes": len(json.dumps(document)),
        },
        "day_v4_rule": v4,
        "day_v5": v5,
        "stated_128": {
            "ticks": args.ticks,
            **{k: stated[k] for k in ("tick_wall_ms", "tick_cpu_ms")},
        },
        "replay_hour_s": {
            "town": {"people": size, "seconds": round(replay_hour(document, size), 3)},
            "stated_128": {
                "people": STATED_POPULATION,
                "seconds": round(replay_hour(stated_document, STATED_POPULATION), 3),
            },
        },
        "machine": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "idle_before_percent": idle_before,
            "idle_after_percent": idle_share(),
            "load_before": load_before,
            "load_after": load(),
        },
    }
    args.out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("largest", "stated_128", "replay_hour_s")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
