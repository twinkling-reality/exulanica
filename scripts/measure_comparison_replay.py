#!/usr/bin/env python3
"""Measure what reading one completed run of a comparison costs, by the people its society holds.

    uv run python scripts/measure_comparison_replay.py --worlds 20 --repeats 5 --out PATH

Pure: no database, no store and no model. The run route (``GET .../comparisons/{id}/runs/{run}``)
replays a completed run from the requests and receipts it stored, holds the replay to what the run
recorded, and answers the document the page draws. This measures that work, the part that grows
with the society's people: for ``--worlds`` fresh identities of one recipe (the small town by
default) it composes each world's society input, takes the median and the largest by population,
and on each of those two graphs, at the world's own population and at every stated population
(:data:`STATED_POPULATIONS`), it plays one hour nobody is decided for (the routine) and one hour of
a model arm deciding for everybody, and at the world's own population one deciding for each stated
group (:data:`STATED_GROUPS`), each with scripted answers that the engine applies (the most
receipts such a run can hold), and then, ``--repeats`` times, replays each as the route does:
:func:`~exulanica.world.society_comparison_result.verified_replay`,
:func:`~exulanica.world.society_comparison_result.replay_document` and the response body FastAPI
writes for it. Each repeat's wall-clock and process CPU time are recorded, with the body's size.

From every point's 95th percentile it states the read's cost as ``fixed + per_person x population
+ per_decided x decided + per_pair x population x decided``, since building a decided person's
options reads everybody else: of every such cost, with no coefficient below zero, that lies on or
above every point, the one whose margins over the points sum to the least, found at a vertex of the
points' constraints; its coefficients rounded up to whole microseconds and its fixed cost, rounded up
to a whole millisecond, the smallest that leaves no point above it. The comparison protocol's third version states it (``replay_fixed_ms``,
``replay_per_person_us``, ``replay_per_decided_person_us``, ``replay_per_decided_pair_us``), from
which the most people a comparison runs, and the most of them a model decides for, are derived
(:mod:`exulanica.world.society_comparison_reading`). The same fit without the last term is written
beside it, to show what the pair term changes. ``--refit RECORD`` fits a record's points again and
prints both fits, measuring nothing.

Before and after the run it samples the machine's CPU idle share over ten seconds (``top``). A run
whose idle share before is under :data:`IDLE_BEFORE_PERCENT` is refused, and one whose mean idle
share falls under :data:`IDLE_MEAN_PERCENT` is written with ``discard: true``. Before every point it
waits, at most :data:`LOAD_WAIT_SECONDS`, for the one-minute load average to fall under
:data:`LOAD_MOST`, the quiet slot's rule for a measurement to stand, records it before and after the
point, and stops, writing nothing, when it does not fall. Run it inside
``.exulanica/bin/quiet-slot`` then ``.exulanica/bin/gpu-slot``.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
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

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import composer_module
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_authored_ground import StandingPolicy, authored_ground_from_snapshot
from exulanica.world.society_comparison import RunPlan, play
from exulanica.world.society_comparison_result import replay_document, verified_replay
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_grounds import society_population
from exulanica.world.society_living import current_routine
from exulanica.world.society_planner import PURPOSEFUL_PROFILE, initial_purposeful_society
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import world_recipe

#: The stated populations a run is replayed at on each measured graph: the first protocol's eight
#: and doublings of it up to the generated town ground's bound of 128.
STATED_POPULATIONS = (8, 16, 32, 64, 128)
#: The groups a model decides for, at each measured world's own population.
STATED_GROUPS = (4, 8, 16)
#: The simulated minutes a run plays: the comparison protocol's window.
WINDOW_TICKS = 60
#: How long the CPU idle share is sampled for, before and after the run, in seconds.
IDLE_SAMPLE_SECONDS = 10
#: The timing rule: a run starts only on a machine at least this idle, and is discarded when the
#: mean of the idle shares before and after falls under the second figure.
IDLE_BEFORE_PERCENT = 70.0
IDLE_MEAN_PERCENT = 50.0
#: The one-minute load average above which a timing is repeated (``.exulanica/bin/quiet-slot``),
#: and how long, in seconds, a point waits for the machine to fall under it.
LOAD_MOST = 8.0
LOAD_WAIT_SECONDS = 600
LOAD_POLL_SECONDS = 10
_SEED = "7" * 64
_MODEL = {"kind": "model", "provider": "nebius_token_factory", "model_id": "measured/scripted"}


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


def load_average() -> str:
    return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()


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
            **{name: getattr(empty, name) for name in empty.__slots__},
            "state_sha256": version_delta_sha256(empty),
        }
    )


def compose(recipe_key: str, index: int) -> dict[str, Any]:
    """One world of the recipe for a fresh identity, and its society's first input."""
    recipe = world_recipe(recipe_key)
    module = composer_module(recipe.composer_key, recipe.composer_version)
    policy = current_routine().policy
    world_id = f"world:generated:replay-measured-{index}"
    composed = compose_generated_world(recipe, world_id)
    module.records(composed.receipt)
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
    document = build_walking_surfaces_input(
        ground=ground,
        version=version_of(world_id, snapshot_id),
        place=walking_surfaces_place(ground.place_id, composed.records),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
    )
    return {
        "world_id": world_id,
        "nodes": len(document["navigation"]["nodes"]),
        "population": society_population(document),
        "document": document,
    }


class _Applied:
    """Answers every request with one of its own offered options, chosen by the request's digest,
    so the engine applies each and the run holds a receipt for every choice point."""

    def offerable(self, tick, due):
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests):
        results = []
        for request in requests:
            options = request["context"]["options"]
            option = options[int(request["document_sha256"][:12], 16) % len(options)]
            results.append(
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": option["label"], "option": option},
                    "provider": None,
                }
            )
        return results


def _config() -> dict[str, Any]:
    contract = decision_contract()
    return {
        "provider": _MODEL["provider"],
        "model_id": _MODEL["model_id"],
        "mechanism": "tool_call",
        "choice_seq": None,
        "manifest_sha256": "0" * 64,
        "prompt_version": "society-person-choice/v1",
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }


def timed(action: Callable[[], Any]) -> tuple[Any, float, float]:
    wall, cpu = time.perf_counter(), time.process_time()
    result = action()
    return result, time.perf_counter() - wall, time.process_time() - cpu


def point(world: dict[str, Any], population: int, decided: int, repeats: int) -> dict[str, Any]:
    """One run of ``population`` people on ``world``'s graph, a model deciding for ``decided`` of
    them (nobody: the routine; all of them: everybody), played once and read ``repeats`` times as
    the run route reads it."""
    society_id = uuid.uuid5(uuid.NAMESPACE_URL, world["world_id"])
    people = sorted(
        person["id"]
        for person in initial_purposeful_society(
            society_id,
            _SEED,
            world["document"],
            population=population,
            engine_profile=PURPOSEFUL_PROFILE,
        )["inhabitants"]
    )
    arm: dict[str, Any] = (
        {"decider": {"kind": "routine"}, "provider_config": None}
        if decided == 0
        else {
            "decider": _MODEL,
            "provider_config": _config(),
            "group": None if decided >= population else frozenset(people[:decided]),
        }
    )
    plan = RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{world['world_id']}:{population}:{decided}"),
        society_id=society_id,
        seed=_SEED,
        population=population,
        inputs=(world["document"],),
        ticks=WINDOW_TICKS,
        contract=decision_contract(),
        **arm,
    )
    played = play(plan, _Applied())
    stored = list(zip(played.requests, played.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }

    def read() -> bytes:
        again = verified_replay(plan, stored, outcome)
        document = replay_document(
            plan, {}, "model_a", "0" * 64, again, model_name=lambda model_id: model_id
        )
        return JSONResponse(content=jsonable_encoder(document)).body

    walls, cpus, size = [], [], 0
    for _ in range(repeats):
        body, wall, cpu = timed(read)
        walls.append(wall)
        cpus.append(cpu)
        size = len(body)
    return {
        "world_id": world["world_id"],
        "nodes": world["nodes"],
        "population": population,
        "decided": min(decided, population),
        "receipts": len(played.receipts),
        "body_bytes": size,
        "read_s": spread(walls),
        "read_cpu_s": spread(cpus),
    }


def settled() -> float:
    """The one-minute load average once it is under :data:`LOAD_MOST`, waiting at most
    :data:`LOAD_WAIT_SECONDS`; a machine that stays busier stops the run."""
    deadline = time.monotonic() + LOAD_WAIT_SECONDS
    while (load := os.getloadavg()[0]) >= LOAD_MOST:
        if time.monotonic() > deadline:
            raise SystemExit(f"stopped: the one-minute load stayed at {load:.2f}, over {LOAD_MOST}")
        time.sleep(LOAD_POLL_SECONDS)
    return round(load, 2)


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """The solution of a small linear system, by Gaussian elimination with partial pivoting."""
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(size):
            if row != column:
                factor = rows[row][column] / rows[column][column]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[column], strict=True)]
    return [rows[i][size] / rows[i][i] for i in range(size)]


def bounding_fit(points: list[dict[str, Any]], *, pairs: bool) -> dict[str, Any]:
    """The cost on or above every point, with ``pairs`` its population-times-decided term, whose
    margins over the points sum to the least: a linear program over the non-negative coefficients,
    solved at a vertex, where as many point constraints as coefficients hold with equality. The
    coefficients are then rounded up to whole microseconds, and the fixed cost is the smallest whole
    millisecond that leaves no point above the rounded cost."""
    terms = 4 if pairs else 3
    rows = [
        (
            (
                1.0,
                float(p["population"]),
                float(p["decided"]),
                float(p["population"] * p["decided"]),
            )[:terms],
            p["read_s"]["p95"] * 1000,
        )
        for p in points
    ]
    objective = [sum(x[i] for x, _ in rows) for i in range(terms)]
    best: tuple[float, list[float]] | None = None
    for chosen in itertools.combinations(range(len(rows)), terms):
        try:
            found = _solve([list(rows[i][0]) for i in chosen], [rows[i][1] for i in chosen])
        except ZeroDivisionError:
            continue
        if any(value < 0 for value in found):
            continue
        if all(sum(c * v for c, v in zip(found, x, strict=True)) >= y - 1e-6 for x, y in rows):
            total = sum(c * o for c, o in zip(found, objective, strict=True))
            if best is None or total < best[0]:
                best = (total, found)
    if best is None:
        raise SystemExit("no cost lies above every point")
    coefficients_us = [math.ceil(value * 1000) for value in best[1][1:]]

    def rest(x: tuple[float, ...], y: float) -> float:
        return y - sum(c * value for c, value in zip(coefficients_us, x[1:], strict=True)) / 1000

    fixed_ms = max(0, math.ceil(max(rest(x, y) for x, y in rows)))
    names = ["replay_per_person_us", "replay_per_decided_person_us", "replay_per_decided_pair_us"]
    return {
        "replay_fixed_ms": fixed_ms,
        **dict(zip(names, coefficients_us, strict=False)),
        "margins_ms": [
            {
                "graph": p["graph"],
                "population": p["population"],
                "decided": p["decided"],
                "p95_ms": round(y),
                "margin_ms": round(fixed_ms - rest(x, y)),
            }
            for p, (x, y) in zip(points, rows, strict=True)
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--recipe", default="small_town")
    parser.add_argument("--worlds", type=int, default=20)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--refit", type=Path, help="fit a record's points again; measure nothing")
    args = parser.parse_args()
    if args.refit is not None:
        points = json.loads(args.refit.read_text(encoding="utf-8"))["points"]
        fits = {
            "line": bounding_fit(points, pairs=True),
            "line_without_pairs": bounding_fit(points, pairs=False),
        }
        print(json.dumps(fits, indent=1))
        return 0
    if args.out is None:
        parser.error("--out names where the record is written")
    idle_before, load_before = idle_share(), load_average()
    if idle_before is not None and idle_before < IDLE_BEFORE_PERCENT:
        print(f"refused: the machine is {idle_before}% idle, under {IDLE_BEFORE_PERCENT}%")
        return 3
    worlds = sorted(
        (compose(args.recipe, index) for index in range(args.worlds)),
        key=lambda world: (world["population"], world["world_id"]),
    )
    measured = {"median": worlds[len(worlds) // 2], "largest": worlds[-1]}
    points = []
    for label, world in measured.items():
        runs = [
            (population, decided)
            for population in sorted({world["population"], *STATED_POPULATIONS})
            for decided in (0, population)
        ] + [(world["population"], group) for group in STATED_GROUPS]
        for population, decided in runs:
            load = settled()
            found = point(world, population, decided, args.repeats)
            found["graph"] = label
            found["load_1m"] = {"before": load, "after": round(os.getloadavg()[0], 2)}
            points.append(found)
            print(
                json.dumps(
                    {k: found[k] for k in ("graph", "population", "decided", "read_s", "load_1m")}
                ),
                flush=True,
            )
    idle_after, load_after = idle_share(), load_average()
    mean_idle = (
        None
        if idle_before is None or idle_after is None
        else round((idle_before + idle_after) / 2, 2)
    )
    record = {
        "profile": "exulanica.comparison-replay-measurement/v3",
        "recipe": args.recipe,
        "worlds": args.worlds,
        "repeats": args.repeats,
        "window_ticks": WINDOW_TICKS,
        "machine": {"system": platform.platform(), "python": sys.version.split()[0]},
        "idle_percent_before": idle_before,
        "idle_percent_after": idle_after,
        "discard": mean_idle is not None and mean_idle < IDLE_MEAN_PERCENT,
        "load_before": load_before,
        "load_after": load_after,
        "populations": [world["population"] for world in worlds],
        "points": points,
        "line": bounding_fit(points, pairs=True),
        "line_without_pairs": bounding_fit(points, pairs=False),
    }
    args.out.write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: record[k] for k in ("idle_percent_before", "idle_percent_after", "line")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
