#!/usr/bin/env python3
"""Measure what a world generated from a recipe costs to make, read and live in.

    uv run python scripts/measure_generated_world.py --worlds 20 --out PATH

Pure: no database, no store and no model. For ``--worlds`` fresh world identities of one recipe
(``--recipe``, the small town by default) it measures, each with the wall-clock and the process CPU
time it took on this machine:

* **Generation**: the recipe's composer making the world for that identity, as
  ``POST /worlds/generated`` does before its transaction (``compose_generated_world``): the seed
  candidates it tried, the grammar's generation, the tile documents' checks and the arrival point.
* **Reading**: generating the world's records again from its receipt, as ``town_records`` does on a
  cold cache, held to the receipt's output digest.
* **Composing**: the purposeful society's input over the world's walking surfaces: the place the
  records make (``walking_surfaces_place``), then the input (``build_walking_surfaces_input``),
  and the population the ground's rule derives from it.
* **Living**: one purposeful tick of the world's own population, and of a stated population on the
  median world's graph, each over ``--ticks`` ticks from genesis with the routine deciding (no
  model); and one simulated hour, ``--ticks`` minutes from genesis, at the median and the largest
  population the recipe produced. A comparison replays a run's hour from its receipts through the
  same step, so the hour is what one replayed run of that population costs, less its receipts.

Before and after the whole run it samples the machine's CPU idle share over ten seconds (``top``),
and writes both into the output, so a run made on a busy machine says so. Run it inside
``.exulanica/bin/quiet-slot``.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import statistics
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_grounds import society_population
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
)
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import world_recipe

#: The stated populations one tick is measured at on the median world's graph: the comparison
#: protocol's eight and doublings of it up to the ground's bound.
STATED_POPULATIONS = (8, 16, 32, 64, 128)
#: How long the CPU idle share is sampled for, before and after the run, in seconds.
IDLE_SAMPLE_SECONDS = 10
_SEED = "5" * 64


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
    found = re.findall(r"CPU usage: .*?([0-9.]+)% idle", out)
    return float(found[-1]) if found else None


def timed(action: Callable[[], Any]) -> tuple[Any, float, float]:
    wall, cpu = time.perf_counter(), time.process_time()
    result = action()
    return result, time.perf_counter() - wall, time.process_time() - cpu


def spread(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    return {
        "min": round(ordered[0], 4),
        "median": round(statistics.median(ordered), 4),
        "p95": round(ordered[max(0, -(-95 * len(ordered) // 100) - 1)], 4),
        "max": round(ordered[-1], 4),
    }


def version_of(world_id: str, snapshot_id: uuid.UUID) -> AlternateVersion:
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


def ticks(document: dict[str, Any], population: int, count: int) -> tuple[list[float], float]:
    """Each tick's wall-clock seconds over ``count`` ticks from genesis, and the hour's total."""
    state = initial_purposeful_society(
        uuid.uuid5(uuid.NAMESPACE_URL, document["world_id"]), _SEED, document, population=population
    )
    each = []
    started = time.perf_counter()
    for _ in range(count):
        tick_started = time.perf_counter()
        state, _events = advance_purposeful_society(state, _SEED, [document])
        each.append(time.perf_counter() - tick_started)
    return each, time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", default="small_town")
    parser.add_argument("--worlds", type=int, default=20)
    parser.add_argument("--ticks", type=int, default=60)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    recipe = world_recipe(args.recipe)
    module = composer_module(recipe.composer_key, recipe.composer_version)
    policy = current_routine().policy
    standing = StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"])
    idle_before = idle_share()
    load_before = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    worlds = []
    for index in range(args.worlds):
        world_id = f"world:generated:measured-{index}"
        composed, gen_wall, gen_cpu = timed(lambda w=world_id: compose_generated_world(recipe, w))
        _, read_wall, read_cpu = timed(lambda c=composed: module.records(c.receipt))
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
        document, input_wall, input_cpu = timed(
            lambda g=ground, c=composed, w=world_id, s=snapshot_id: build_walking_surfaces_input(
                ground=g,
                version=version_of(w, s),
                place=walking_surfaces_place(g.place_id, c.records),
                input_seq=1,
                dependency_refs=[],
                availability="available",
                unavailable_reason=None,
                reviewed_affordances={},
                standing=standing,
            )
        )
        worlds.append(
            {
                "world_id": world_id,
                "candidate": composed.receipt["candidate"],
                "generation_s": gen_wall,
                "generation_cpu_s": gen_cpu,
                "records_again_s": read_wall,
                "records_again_cpu_s": read_cpu,
                "input_s": input_wall,
                "input_cpu_s": input_cpu,
                "nodes": len(document["navigation"]["nodes"]),
                "targets": len(document["targets"]),
                "population": society_population(document),
                "_document": document,
            }
        )
    by_population = sorted(worlds, key=lambda world: (world["population"], world["world_id"]))
    median_world = by_population[len(by_population) // 2]
    largest_world = by_population[-1]
    living = {}
    for label, world in (("median", median_world), ("largest", largest_world)):
        each, hour = ticks(world["_document"], world["population"], args.ticks)
        living[label] = {
            "world_id": world["world_id"],
            "population": world["population"],
            "nodes": world["nodes"],
            "tick_s": spread(each),
            "hour_s": round(hour, 3),
        }
    stated = {}
    for population in STATED_POPULATIONS:
        each, hour = ticks(median_world["_document"], population, args.ticks)
        stated[str(population)] = {"tick_s": spread(each), "hour_s": round(hour, 3)}
    idle_after = idle_share()
    load_after = subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    record = {
        "profile": "exulanica.generated-world-measurement/v1",
        "recipe": recipe.reference(),
        "worlds": args.worlds,
        "ticks": args.ticks,
        "machine": {"system": platform.platform(), "python": sys.version.split()[0]},
        "idle_percent_before": idle_before,
        "idle_percent_after": idle_after,
        "load_before": load_before,
        "load_after": load_after,
        "candidates_kept": sorted(world["candidate"] for world in worlds),
        "generation_s": spread([world["generation_s"] for world in worlds]),
        "generation_cpu_s": spread([world["generation_cpu_s"] for world in worlds]),
        "records_again_s": spread([world["records_again_s"] for world in worlds]),
        "input_s": spread([world["input_s"] for world in worlds]),
        "nodes": spread([float(world["nodes"]) for world in worlds]),
        "targets": spread([float(world["targets"]) for world in worlds]),
        "population": spread([float(world["population"]) for world in worlds]),
        "living": living,
        "stated_population_on_median_graph": stated,
    }
    args.out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("idle_percent_before", "idle_percent_after")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
