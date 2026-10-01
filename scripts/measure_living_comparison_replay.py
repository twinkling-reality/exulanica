#!/usr/bin/env python3
"""Measure what reading one completed run of a living town's comparison costs, by its people.

    .exulanica/bin/quiet-slot uv run python scripts/measure_living_comparison_replay.py \\
        --worlds 8 --repeats 5 --out RECORD

Pure: no database, no store and no model. The run route (``GET .../comparisons/{id}/runs/{run}``)
serves a completed run's stored drawing, or replays the run from the requests and receipts it
stored, holds the replay to what the run recorded and answers the document the page draws. This
measures that replay for the living town (``exulanica-society/v5``), the engine a generated town's
society runs, as ``scripts/measure_comparison_replay.py`` measured it for the purposeful engine:

- **Graphs.** For each town preset, ``--worlds`` fresh identities are composed through the path
  the runtime composes a town's input by, and the median and the largest by population are
  measured. So is one stress town *outside the admitted specification*: the market town's three
  tiles with 100 m blocks, which the specification refuses because its homes approach the town
  ground's bound, composed only to measure a run at that bound. It is never offered as a world.
- **Points.** On each graph, at the world's own population and at every stated population below
  it (:data:`STATED_POPULATIONS`), one hour nobody is decided for (the routine) and one hour a
  model arm decides for everybody; at the world's own population also each stated group
  (:data:`STATED_GROUPS`). Every run is played once with scripted answers the engine applies (the
  most receipts such a run can hold, not any model's behaviour), then read ``--repeats`` times as
  the route reads it: ``verified_replay``, ``replay_document`` and the JSON body. The stored
  drawing is encoded once and read back as a read serves it.
- **Line.** From every point's 95th percentile read, the cost ``fixed + per_person x population +
  per_decided x decided + per_pair x population x decided`` on or above every point whose
  margins sum to the least (the purposeful measurement's criterion, solved over every vertex of
  its linear program, a coefficient of zero included), and from
  it and the protocol's pair budget the most people a comparison of a living town runs and the
  most of them a model may decide for.

The machine gate is the purposeful measurement's: at least 70 percent CPU idle over ten seconds
before the run (refused otherwise), the one-minute load under 8 before every point, and a record
whose mean idle falls under 50 percent is written with ``discard: true``. Run it inside
``.exulanica/bin/quiet-slot``. Every duration is written in whole microseconds, every share as a
decimal string, and the record in the digest-bound form every retained record takes. The code a
replay executes is bound by the drawing digest (``CODE_SHA256``), so the record names exactly the
replay it measured.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import itertools
import json
import math
import os
import platform
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_comparison_replay import (
    IDLE_BEFORE_PERCENT,
    IDLE_MEAN_PERCENT,
    LOAD_MOST,
    idle_share,
    load_average,
    settled,
)

from exulanica.canonical import canonical_json
from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_authored_ground import (
    StandingPolicy,
    authored_ground_from_snapshot,
)
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison import RunPlan, genesis, play
from exulanica.world.society_comparison_drawing import (
    CODE_SHA256,
    decode,
    encode,
    with_names,
)
from exulanica.world.society_comparison_reading import PAIR_RUNS, ReadingBound
from exulanica.world.society_comparison_result import (
    protocol_value,
    replay_document,
    verified_replay,
)
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE, town_routine
from exulanica.world.society_walking_surfaces import (
    build_walking_surfaces_input,
    walking_surfaces_place,
)
from exulanica.world.world_recipes import (
    load_specification_schemas,
    specification_tiles,
    town_recipe,
    world_recipe,
)

PROFILE: Final = "exulanica.digest-bound-record/v1"
KIND: Final = "exulanica.living-comparison-replay-measurement/v1"
#: The town presets measured, each at its median and largest identity by population.
PRESETS: Final = ("small_town", "market_town")
#: Populations a run is also replayed at on each graph, below the world's own: doublings from the
#: first protocol's eight. A living genesis places at most one inhabitant per home.
STATED_POPULATIONS: Final = (8, 16, 32, 64)
#: The groups a model decides for, at each measured world's own population.
STATED_GROUPS: Final = (4, 8, 16)
#: The stress town: the market town's three tiles with blocks shorter than the specification
#: admits (it holds three-tile towns to 130 or 140 m, because shorter blocks put more homes in a
#: town than its society ground takes). Composed only to measure a run near the ground's bound.
STRESS_PRESET: Final = "market_town"
STRESS_BLOCK_LENGTH_MM: Final = 100_000
#: The stress identities tried, and the least population one must reach to be measured.
STRESS_TRIES: Final = 6
STRESS_POPULATION_LEAST: Final = 120
#: The generated town ground's bound, which society creation enforces (society-ground.v2.json).
GROUND_BOUND: Final = 128
_SEED: Final = "7" * 64
_MODEL: Final = {
    "kind": "model",
    "provider": "nebius_token_factory",
    "model_id": "measured/scripted",
}


def _version_of(world_id: str, snapshot_id: uuid.UUID) -> AlternateVersion:
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
        created_at="2026-09-30T00:00:00+00:00",
    )
    return AlternateVersion(
        **{
            **{name: getattr(empty, name) for name in empty.__slots__},
            "state_sha256": version_delta_sha256(empty),
        }
    )


def _stress_recipe() -> Any:
    """The market town with blocks the specification refuses for three tiles: its schema's own
    specification of those values, with the check that refuses them left out."""
    preset = world_recipe(STRESS_PRESET)
    schema = load_specification_schemas()[preset.specification_name]
    chosen = {**dict(preset.values or {}), "block_length_mm": STRESS_BLOCK_LENGTH_MM}
    document = schema.specification(chosen)
    return dataclasses.replace(
        preset,
        specification=document,
        tiles=specification_tiles(document),
        values=MappingProxyType(dict(sorted(chosen.items()))),
    )


def compose(preset: str, index: int, *, stress: bool = False) -> dict[str, Any]:
    """One town for a fresh identity and its living society's first input, composed as the
    runtime composes a town's input."""
    kind = "stress" if stress else preset
    world_id = f"world:generated:living-replay-measured-{kind}-{index}"
    recipe = _stress_recipe() if stress else town_recipe(preset)
    composed = compose_generated_world(recipe, world_id)
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
        version=_version_of(world_id, snapshot_id),
        place=walking_surfaces_place(ground.place_id, composed.records, routine),
        input_seq=1,
        dependency_refs=[],
        availability="available",
        unavailable_reason=None,
        reviewed_affordances={},
        standing=StandingPolicy(policy["standing_spacing_mm"], policy["standing_radius_mm"]),
        living=routine,
    )
    return {
        "world_id": world_id,
        "preset": preset,
        "index": index,
        "outside_specification": stress,
        "nodes": len(document["navigation"]["nodes"]),
        "population": int(document["population"]["size"]),
        "document": document,
    }


class _Applied:
    """Answers every request with one of its own offered options, chosen by the request's digest,
    so the engine applies each and the run holds a receipt for every choice point."""

    def offerable(self, tick: int, due: Any) -> dict[str, frozenset[str]]:
        return {subject: frozenset(o.label for o in options) for subject, options in due.items()}

    def answers(self, requests: Any) -> list[dict[str, Any]]:
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


def _microseconds(action: Callable[[], Any]) -> tuple[Any, int, int]:
    """What ``action`` returns, and how long it took in wall-clock and process CPU microseconds."""
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    result = action()
    return result, (time.perf_counter_ns() - wall) // 1000, (time.process_time_ns() - cpu) // 1000


def _nearest_rank(values: list[int], per_cent: int) -> int:
    ordered = sorted(values)
    return ordered[max(0, -(-per_cent * len(ordered) // 100) - 1)]


def _spread(values: list[int]) -> dict[str, int]:
    ordered = sorted(values)
    return {
        "min": ordered[0],
        "median": _nearest_rank(ordered, 50),
        "p95": _nearest_rank(ordered, 95),
        "max": ordered[-1],
    }


def point(
    world: dict[str, Any], population: int, decided: int, repeats: int, window: int
) -> dict[str, Any]:
    """One run of ``population`` of ``world``'s people, a model deciding for ``decided`` of them
    (nobody: the routine; all of them: everybody), played once and read ``repeats`` times."""
    base = {
        "run_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{world['world_id']}:{population}:{decided}"),
        "society_id": uuid.uuid5(uuid.NAMESPACE_URL, world["world_id"]),
        "seed": _SEED,
        "population": population,
        "inputs": (world["document"],),
        "ticks": window,
        "contract": decision_contract(),
        "engine_profile": LIVING_TOWN_PROFILE,
    }
    routine = RunPlan(decider={"kind": "routine"}, provider_config=None, **base)
    if decided == 0:
        plan = routine
    else:
        people = sorted(person["id"] for person in genesis(routine)["inhabitants"])
        plan = RunPlan(
            decider=_MODEL,
            provider_config=_config(),
            group=None if decided >= population else frozenset(people[:decided]),
            **base,
        )
    played, play_wall_us, play_cpu_us = _microseconds(lambda: play(plan, _Applied()))
    stored = list(zip(played.requests, played.receipts, strict=True))
    outcome = {
        "status": "completed",
        "minutes": {"state_sha256": played.minute_digests},
        "events_sha256": played.events_sha256,
        "receipts": {"count": len(played.receipts), "sha256": played.receipts_sha256},
    }
    stored_bytes = sum(
        len(canonical_json(request)) + len(canonical_json(receipt)) for request, receipt in stored
    )
    del played

    def read() -> tuple[bytes, dict[str, Any]]:
        again = verified_replay(plan, stored, outcome)
        document = replay_document(
            plan, {}, "model_a", "0" * 64, again, model_name=lambda model_id: model_id
        )
        return JSONResponse(content=jsonable_encoder(document)).body, document

    walls, cpus = [], []
    body, document = b"", {}
    for _ in range(repeats):
        (body, document), wall_us, cpu_us = _microseconds(read)
        walls.append(wall_us)
        cpus.append(cpu_us)
    drawing = encode(document)
    stored_walls = []
    for _ in range(repeats):
        _served, wall_us, _cpu_us = _microseconds(
            lambda: (
                JSONResponse(
                    content=jsonable_encoder(with_names(decode(drawing), lambda model_id: model_id))
                ).body
            )
        )
        stored_walls.append(wall_us)
    return {
        "graph": world["world_id"],
        "population": population,
        "decided": min(decided, population),
        "receipts": len(stored),
        "stored_request_receipt_bytes": stored_bytes,
        "play_wall_us": play_wall_us,
        "play_cpu_us": play_cpu_us,
        "read_wall_us": _spread(walls),
        "read_cpu_us": _spread(cpus),
        "body_bytes": len(body),
        "drawing_bytes": drawing.document_bytes,
        "drawing_gzip_bytes": len(drawing.document_gzip),
        "stored_read_wall_us": _spread(stored_walls),
    }


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float] | None:
    """The solution of a small linear system by elimination with partial pivoting, or None when
    it has no unique one."""
    size = len(vector)
    rows = [[*matrix[i], vector[i]] for i in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(rows[row][column]))
        if abs(rows[pivot][column]) < 1e-12:
            return None
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for row in range(size):
            if row != column:
                factor = rows[row][column] / rows[column][column]
                rows[row] = [a - factor * b for a, b in zip(rows[row], rows[column], strict=True)]
    return [rows[i][size] / rows[i][i] for i in range(size)]


def _fit(points: list[dict[str, Any]], *, pairs: bool) -> dict[str, Any]:
    """The cost on or above every point's 95th percentile read, with ``pairs`` its
    population-times-decided term, whose margins over the points sum to the least: the purposeful
    measurement's criterion (``bounding_fit``), solved as the small linear program it is. Its
    optimum is a vertex where as many constraints as coefficients hold with equality, a point's
    or a coefficient's own lower bound of zero; ``bounding_fit`` tries only points' and finds no
    cost where a coefficient's best value is zero. The coefficients are then rounded up to whole
    microseconds and the fixed cost is the smallest whole millisecond that leaves no point above
    the rounded cost, as there."""
    terms = 4 if pairs else 3
    rows = [
        (
            (
                1.0,
                float(item["population"]),
                float(item["decided"]),
                float(item["population"] * item["decided"]),
            )[:terms],
            item["read_wall_us"]["p95"] / 1000,
        )
        for item in points
    ]
    constraints = [(list(x), y) for x, y in rows] + [
        ([float(i == j) for j in range(terms)], 0.0) for i in range(terms)
    ]
    objective = [sum(x[i] for x, _ in rows) for i in range(terms)]
    best: tuple[float, list[float]] | None = None
    for chosen in itertools.combinations(range(len(constraints)), terms):
        found = _solve([constraints[i][0] for i in chosen], [constraints[i][1] for i in chosen])
        if found is None or any(value < -1e-9 for value in found):
            continue
        found = [max(0.0, value) for value in found]
        if all(sum(c * v for c, v in zip(found, x, strict=True)) >= y - 1e-6 for x, y in rows):
            total = sum(c * o for c, o in zip(found, objective, strict=True))
            if best is None or total < best[0]:
                best = (total, found)
    if best is None:
        raise ValueError("no cost lies on or above every point")
    coefficients_us = [math.ceil(value * 1000) for value in best[1][1:]]

    def rest_us(x: tuple[float, ...], y: float) -> int:
        """What the point's read leaves, in whole microseconds rounded up, over the rounded
        coefficients' part of the cost."""
        return math.ceil(y * 1000 - sum(c * v for c, v in zip(coefficients_us, x[1:], strict=True)))

    fixed_ms = max(0, -(-max(rest_us(x, y) for x, y in rows) // 1000))
    names = ["replay_per_person_us", "replay_per_decided_person_us", "replay_per_decided_pair_us"]
    return {
        "replay_fixed_ms": fixed_ms,
        **dict(zip(names, coefficients_us, strict=False)),
        "margins": [
            {
                "graph": item["graph"],
                "population": item["population"],
                "decided": item["decided"],
                "p95_us": item["read_wall_us"]["p95"],
                "margin_us": fixed_ms * 1000 - rest_us(x, y),
            }
            for item, (x, y) in zip(points, rows, strict=True)
        ],
    }


def _derived(line: dict[str, Any], populations: list[int]) -> dict[str, Any]:
    """The most people a living town's comparison runs and the most a model may decide for, from
    the fitted line and the protocol's pair budget, as the reading bound derives them."""
    catalogs = load_comparison_catalogs()
    budget_ms = protocol_value(catalogs, "pair_replay_budget_ms")
    bound = ReadingBound(
        run_us=budget_ms * 1000 // PAIR_RUNS,
        fixed_us=line["replay_fixed_ms"] * 1000,
        per_person_us=line["replay_per_person_us"],
        per_decided_us=line["replay_per_decided_person_us"],
        per_pair_us=line["replay_per_decided_pair_us"],
    )
    shown = sorted({*populations, GROUND_BOUND})
    return {
        "pair_replay_budget_ms": budget_ms,
        "run_budget_us": bound.run_us,
        "population_most": bound.population_most(),
        "decided_most": [
            {
                "population": population,
                "decided_most": bound.decided_most(population),
                "estimate_everybody_us": bound.estimate_us(population, population),
            }
            for population in shown
        ],
    }


def _source() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
    ).stdout.strip()
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    return {
        "head": head,
        "changed_paths": sorted(line[3:] for line in changed),
        "drawing_code_sha256": CODE_SHA256,
    }


def _percent(value: float | None) -> str | None:
    return None if value is None else str(Decimal(str(value)))


def _refuse_machine_paths(text: str) -> None:
    """A record states no location of this machine: its home, its temporary folders or the
    account that ran it."""
    fragments = [str(Path.home()), "/" + "private" + "/", "/var/" + "folders/"]
    user = os.environ.get("USER")
    if user:
        fragments.append(f"/{user}/")
    for fragment in fragments:
        if fragment and fragment in text:
            raise SystemExit("refused: the record would state a location of this machine")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worlds", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = _source()
    idle_before, load_before = idle_share(), load_average()
    if idle_before is not None and idle_before < IDLE_BEFORE_PERCENT:
        print(f"refused: the machine is {idle_before}% idle, under {IDLE_BEFORE_PERCENT}%")
        return 3
    window = protocol_value(load_comparison_catalogs(), "window_ticks")
    graphs: list[dict[str, Any]] = []
    surveyed: dict[str, list[int]] = {}
    for preset in PRESETS:
        worlds = sorted(
            (compose(preset, index) for index in range(args.worlds)),
            key=lambda world: (world["population"], world["world_id"]),
        )
        surveyed[preset] = [world["population"] for world in worlds]
        graphs.extend([worlds[len(worlds) // 2], worlds[-1]])
    stress = None
    for index in range(STRESS_TRIES):
        try:
            found = compose(STRESS_PRESET, index, stress=True)
        except Exception as exc:  # the recipe refuses most identities, by name
            print(f"stress identity {index} not measured: {type(exc).__name__}", flush=True)
            continue
        if STRESS_POPULATION_LEAST <= found["population"] <= GROUND_BOUND:
            stress = found
            break
    if stress is not None:
        graphs.append(stress)
    points = []
    for world in graphs:
        own = world["population"]
        populations = sorted({own, *(p for p in STATED_POPULATIONS if p < own)})
        runs = [(population, decided) for population in populations for decided in (0, population)]
        runs += [(own, group) for group in STATED_GROUPS if group < own]
        for population, decided in runs:
            load = settled()
            found = point(world, population, decided, args.repeats, window)
            found["load_1m"] = {"before": str(load), "after": str(round(os.getloadavg()[0], 2))}
            points.append(found)
            print(
                json.dumps(
                    {
                        key: found[key]
                        for key in ("graph", "population", "decided", "read_wall_us", "load_1m")
                    }
                ),
                flush=True,
            )
    idle_after, load_after = idle_share(), load_average()
    mean_idle = (
        None
        if idle_before is None or idle_after is None
        else (Decimal(str(idle_before)) + Decimal(str(idle_after))) / 2
    )
    line = _fit(points, pairs=True)
    record = {
        "kind": KIND,
        "engine": LIVING_TOWN_PROFILE,
        "source": source,
        "script": "scripts/measure_living_comparison_replay.py",
        "window_ticks": window,
        "repeats": args.repeats,
        "machine": {
            "system": platform.platform(),
            "python": sys.version.split()[0],
            "cpus": os.cpu_count(),
        },
        "gate": {
            "idle_percent_before": _percent(idle_before),
            "idle_percent_after": _percent(idle_after),
            "idle_percent_before_least": str(IDLE_BEFORE_PERCENT),
            "idle_percent_mean_least": str(IDLE_MEAN_PERCENT),
            "load_most_before_each_point": str(LOAD_MOST),
            "load_before": load_before,
            "load_after": load_after,
        },
        "discard": mean_idle is not None and mean_idle < Decimal(str(IDLE_MEAN_PERCENT)),
        "surveyed_populations": surveyed,
        "graphs": [
            {
                key: world[key]
                for key in (
                    "world_id",
                    "preset",
                    "index",
                    "outside_specification",
                    "nodes",
                    "population",
                )
            }
            for world in graphs
        ],
        "stress_measured": stress is not None,
        "points": points,
        "line": line,
        "line_without_pairs": _fit(points, pairs=False),
        "derived": _derived(line, [world["population"] for world in graphs]),
        "limits": [
            "Scripted answers the engine applies: the most receipts a run can hold, not any "
            "model's behaviour.",
            "One simulated hour per run; a full day is not measured.",
            "The stress town is outside the admitted specification and is never offered as a world.",
        ],
    }
    text = canonical_json(record).decode()
    _refuse_machine_paths(text)
    wrapped = {
        "profile": PROFILE,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
        "record": record,
    }
    args.out.write_text(json.dumps(wrapped, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"line": line, "discard": record["discard"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
