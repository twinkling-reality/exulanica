#!/usr/bin/env python3
"""Measure what reading a living town's day costs, hour by hour, by its people.

    .exulanica/bin/quiet-slot uv run python scripts/measure_living_day_replay.py \\
        --worlds 8 --repeats 3 --out RECORD

Pure: no database, no store and no model. A comparison over a day seals each run hour by hour,
and the run route reads a day's run one sealed hour at a time
(``GET .../comparisons/{id}/runs/{run}?hour=h``):
- it reads the state the hour before it sealed from its stored bytes (the first hour's genesis
  is built again);
- it replays the hour from that state through the receipts the hour recorded, held to the hour's
  record;
- it answers the document the page draws, with where the hour lies in the day.

The day route (``GET .../runs/{run}/day``) sets out the day from its sealed hours with no replay.
This measures both for the living town (``exulanica-society/v5``) at every hour of its day, as
``scripts/measure_living_comparison_replay.py`` measured reading an hour's run:

- **Graphs.** The hour line's: for each town preset, ``--worlds`` fresh identities composed
  through the path the runtime composes a town's input by, the median and the largest by
  population measured. The stress town too, *outside the admitted specification*, composed only
  to measure a run at the town ground's bound and never offered as a world.
- **Points.** On each graph, at its own population: one day nobody is decided for (the routine),
  one a model arm decides for everybody, and one for each stated group.
  - Each day is played once, hour by hour, with scripted answers the engine applies: the most
    receipts such a run can hold, not any model's behaviour.
  - Each hour is sealed as the runner seals it: its document, and the state it ended in as the
    canonical bytes a sealed hour stores.
  - Every hour is then read ``--repeats`` times as the run route reads it, and the day as the
    day route reads it.
- **Line.** A point's read is its dearest: the slowest 95th percentile of its 24 hours' reads and
  of its day's.
  - The line is the hour line's form, ``fixed + per_person x population + per_decided x decided +
    per_pair x population x decided``.
  - It lies on or above every point, its margins summing to the least, by the hour line's own fit.
  - From it and the fourth protocol's pair budget come the most people a day's comparison of a
    living town runs and the most of them a model may decide for.

It runs in phases, and the record states each and whether it was gated:
- **Compose and play**, not gated and not timed: every graph composed and every point's day played
  and sealed, which takes whatever the machine gives it.
- **Gate**, right before the first read: the hour line's idle gate, at least 70 percent CPU idle
  over ten seconds, sampled until it holds for at most ``--gate-wait-seconds`` (twenty minutes),
  and refused, with nothing read and no record written, once that wait is spent.
- **Reads**, gated: before every point's reads the one-minute load is waited for to fall under 8,
  for at most ten minutes, or the run stops. A point whose reads end with the load at 8 or over is
  read again, up to twice, every attempt recorded and only the last kept; one whose every read ends
  so stops the run. The mean idle is taken over the reads alone, from the
  gate's sample and one after the last read, and a record whose mean falls under 50 percent is
  written with ``discard: true``.

Run it inside ``.exulanica/bin/quiet-slot``. ``--smoke`` runs it without the gates, for trying the
script, and always writes ``discard: true``. Every duration is in whole microseconds and every
share a decimal string, in the digest-bound form every retained record takes. The code a replay
executes is bound by the drawing digest (``CODE_SHA256``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent))

import measure_living_comparison_replay as hour_line
from measure_comparison_replay import (
    IDLE_BEFORE_PERCENT,
    IDLE_MEAN_PERCENT,
    LOAD_MOST,
    LOAD_WAIT_SECONDS,
    idle_share,
    load_average,
    settled,
)

from exulanica.canonical import canonical_json
from exulanica.world.society_catalogs import comparison_catalogs_for_engine
from exulanica.world.society_comparison import (
    HOUR_TICKS,
    HourStart,
    RunPlan,
    first_hour,
    genesis,
    hours_of,
    play_hour,
    replay_hour,
)
from exulanica.world.society_comparison_day import (
    day_document,
    hour_document,
    hour_events_sha256,
    hour_window,
    state_bytes,
    state_from_bytes,
)
from exulanica.world.society_comparison_reading import PAIR_RUNS, ReadingBound
from exulanica.world.society_comparison_result import protocol_value, replay_document
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE
from exulanica.world.society_person_label import person_label
from exulanica.world.society import society_state_sha256

PROFILE: Final = "exulanica.digest-bound-record/v1"
KIND: Final = "exulanica.living-day-replay-measurement/v1"
#: What a sealed hour names its definition by, where no definition is stored.
_DEFINITION: Final = {"document_sha256": "0" * 64}
#: How long the reads' idle gate is waited for before the run is refused, and how often it is
#: sampled meanwhile (each sample itself takes the gate's ten seconds).
GATE_WAIT_SECONDS: Final = 1200
GATE_POLL_SECONDS: Final = 20
#: How many times more a point is read where its reads end with the one-minute load over the
#: gate's most; a point whose every read ends so stops the run.
READS_AGAIN_MOST: Final = 2


def _named(model_id: str) -> str:
    return model_id


def _reads(action: Callable[[], bytes], repeats: int) -> tuple[bytes, dict[str, int]]:
    walls = []
    body = b""
    for _ in range(repeats):
        body, wall_us, _cpu_us = hour_line._microseconds(action)
        walls.append(wall_us)
    return body, hour_line._spread(walls)


@dataclass(frozen=True)
class Day:
    """One point's day, played and sealed hour by hour: what its reads replay."""

    world: dict[str, Any]
    decided: int
    plan: RunPlan
    sealed: tuple[dict[str, Any], ...]


def _plan(world: dict[str, Any], decided: int, window: int) -> RunPlan:
    population = world["population"]
    base = {
        "run_id": uuid.uuid5(uuid.NAMESPACE_URL, f"{world['world_id']}:day:{decided}"),
        "society_id": uuid.uuid5(uuid.NAMESPACE_URL, world["world_id"]),
        "seed": hour_line._SEED,
        "population": population,
        "inputs": (world["document"],),
        "ticks": window,
        "contract": decision_contract(),
        "engine_profile": LIVING_TOWN_PROFILE,
    }
    routine = RunPlan(decider={"kind": "routine"}, provider_config=None, **base)
    if decided == 0:
        return routine
    people = sorted(person["id"] for person in genesis(routine)["inhabitants"])
    return RunPlan(
        decider=hour_line._MODEL,
        provider_config=hour_line._config(),
        group=None if decided >= population else frozenset(people[:decided]),
        **base,
    )


def play_day(world: dict[str, Any], decided: int, window: int, catalogs: Any) -> Day:
    """One day of ``world``'s people, a model deciding for ``decided`` of them (nobody: the
    routine; all of them: everybody), played once hour by hour and every hour sealed as a host
    seals it. Nothing here is timed: the play is not read."""
    plan = _plan(world, decided, window)
    sealed: list[dict[str, Any]] = []
    start = first_hour(plan)
    for hour in range(hours_of(plan)):
        played = play_hour(plan, hour_line._Applied(), start=start)
        document = hour_document(
            plan,
            _DEFINITION,
            "model_a",
            "0" * 64,
            start,
            played,
            catalogs,
            calls=None,
            others_calls=None,
        )
        end = played.states[-1]
        sealed.append(
            {
                "document": document,
                "stored": list(zip(played.requests, played.receipts, strict=True)),
                "first_sequence": start.first_sequence,
                "end_state": state_bytes(end),
                "end_state_sha256": society_state_sha256(end),
            }
        )
        start = HourStart(hour + 1, end, start.first_sequence + len(played.receipts))
        del played
    return Day(world, decided, plan, tuple(sealed))


def read_day(day: Day, repeats: int) -> dict[str, Any]:
    """Every hour of ``day`` read ``repeats`` times as the run route reads one, and the day as the
    day route reads it, with the dearest of those reads, which the line is fitted on."""
    plan, sealed = day.plan, day.sealed

    def read_hour(hour: int) -> bytes:
        held = sealed[hour]
        if hour == 0:
            begun = first_hour(plan)
        else:
            before = sealed[hour - 1]
            begun = HourStart(
                hour,
                state_from_bytes(before["end_state"], before["end_state_sha256"]),
                held["first_sequence"],
            )
        document = held["document"]
        again = replay_hour(
            plan,
            held["stored"],
            start=begun,
            minute_digests=document["minutes"]["state_sha256"],
        )
        if (
            hour_events_sha256(again) != document["events_sha256"]
            or len(again.receipts) != document["receipts"]["count"]
        ):
            raise SystemExit(f"hour {hour} does not replay to what it sealed")
        drawn = replay_document(plan, {}, "model_a", "0" * 64, again, model_name=_named)
        body = {**drawn, "window": hour_window(plan, document)}
        return JSONResponse(content=jsonable_encoder(body)).body

    def read_whole_day() -> bytes:
        people = first_hour(plan).state["inhabitants"]
        deciders = {}
        for person in people:
            decider, _config = plan.decider_for(person["id"])
            deciders[person["id"]] = (
                {"kind": decider["kind"]}
                if decider["kind"] != "model"
                else {
                    "kind": "model",
                    "provider": decider["provider"],
                    "model_id": decider["model_id"],
                    "name": _named(decider["model_id"]),
                }
            )
        document = day_document(
            plan,
            [held["document"] for held in sealed],
            arm="model_a",
            seed_digest_text="0" * 64,
            status="completed",
            deciders=deciders,
            names={person["id"]: person_label(person) for person in people},
        )
        return JSONResponse(content=jsonable_encoder(document)).body

    hours = []
    for hour in range(len(sealed)):
        body, spread = _reads(lambda hour=hour: read_hour(hour), repeats)
        hours.append(
            {
                "hour": hour,
                "receipts": sealed[hour]["document"]["receipts"]["count"],
                "state_bytes": len(sealed[hour - 1]["end_state"]) if hour else 0,
                "body_bytes": len(body),
                "read_wall_us": spread,
            }
        )
    day_body, day_spread = _reads(read_whole_day, repeats)
    dearest = max(hours, key=lambda found: found["read_wall_us"]["p95"])
    dearest_read = max(dearest["read_wall_us"]["p95"], day_spread["p95"])
    return {
        "graph": day.world["world_id"],
        "population": day.world["population"],
        "decided": min(day.decided, day.world["population"]),
        "receipts": sum(found["receipts"] for found in hours),
        "hours": hours,
        "day_read_wall_us": day_spread,
        "day_body_bytes": len(day_body),
        # What the line is fitted on: the slowest read the point's day serves, of an hour or of
        # the day.
        "read_wall_us": {
            "p95": dearest_read,
            "from": "day" if day_spread["p95"] >= dearest["read_wall_us"]["p95"] else "hour",
            "hour": dearest["hour"],
        },
    }


def point(
    world: dict[str, Any], decided: int, repeats: int, window: int, catalogs: Any
) -> dict[str, Any]:
    """One point: its day played and sealed, then read."""
    return read_day(play_day(world, decided, window, catalogs), repeats)


def decided_counts(world: dict[str, Any]) -> list[int]:
    """Whom a model decides for at a graph's points: nobody, everybody and each stated group
    smaller than the town."""
    own = world["population"]
    return [0, own, *(group for group in hour_line.STATED_GROUPS if group < own)]


def refusal(idle_before: float | None, *, smoke: bool) -> str | None:
    """Why a run is refused before it starts, or None: the machine was less idle than the gate
    asks over the ten seconds before it. A smoke run is not gated, and an idle share that could not
    be read refuses nothing, as the hour line's gate reads it."""
    if smoke or idle_before is None or idle_before >= IDLE_BEFORE_PERCENT:
        return None
    return f"refused: the machine is {idle_before}% idle, under {IDLE_BEFORE_PERCENT}%"


def discarded(mean_idle: Decimal | None, *, smoke: bool) -> bool:
    """Whether a record is written to be discarded: every smoke run's, and a run's whose mean idle
    fell under the gate's least."""
    return smoke or (mean_idle is not None and mean_idle < Decimal(str(IDLE_MEAN_PERCENT)))


def wait_for_idle(
    *,
    smoke: bool,
    wait_seconds: float = GATE_WAIT_SECONDS,
    poll_seconds: float = GATE_POLL_SECONDS,
    idle: Callable[[], float | None] | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[float | None, int, str | None]:
    """The idle share the reads' gate admitted them at, how many seconds it was waited for, and,
    once the wait is spent without the gate holding, its refusal. A smoke run is not gated."""
    sample = idle or idle_share
    started = clock()
    while True:
        share = sample()
        refused = refusal(share, smoke=smoke)
        waited = round(clock() - started)
        if refused is None or clock() - started >= wait_seconds:
            return share, waited, refused
        sleep(poll_seconds)


def run(
    graphs: Sequence[dict[str, Any]],
    *,
    repeats: int,
    window: int,
    catalogs: Any,
    smoke: bool,
    wait_seconds: float = GATE_WAIT_SECONDS,
) -> dict[str, Any]:
    """The run's phases over ``graphs``: every point's day played (not gated, not timed), the
    reads' idle gate waited for, then every point's day read, each once the one-minute load is
    under the gate's most. The phases as the record states them, the points read, whether the
    record is discarded, and the gate's refusal, where it refused and nothing was read."""
    days = [
        play_day(world, count, window, catalogs)
        for world in graphs
        for count in decided_counts(world)
    ]
    phases: dict[str, Any] = {
        "play": {"gated": False, "timed": False, "days": len(days), "load_after": load_average()}
    }
    idle_before, waited, refused = wait_for_idle(smoke=smoke, wait_seconds=wait_seconds)
    phases["gate"] = {
        "gated": not smoke,
        "idle_percent": hour_line._percent(idle_before),
        "idle_percent_least": str(IDLE_BEFORE_PERCENT),
        "waited_seconds": waited,
        "wait_seconds_most": round(wait_seconds),
        "refused": refused,
    }
    if refused is not None:
        return {"phases": phases, "points": [], "discard": True, "refused": refused}
    load_before = load_average()
    points = []
    for day in days:
        attempts: list[dict[str, Any]] = []
        for _attempt in range(1 + READS_AGAIN_MOST):
            load = Decimal(str(round(os.getloadavg()[0], 2))) if smoke else settled()
            found = read_day(day, repeats)
            after = Decimal(str(round(os.getloadavg()[0], 2)))
            attempts.append(
                {
                    "load_1m": {"before": str(load), "after": str(after)},
                    "read_wall_us": found["read_wall_us"],
                }
            )
            # A point whose reads end with the machine busier than the gate allows may have been
            # read under another process's load: it is read again, and only the last is kept.
            if smoke or after < Decimal(str(LOAD_MOST)):
                break
        else:
            raise SystemExit(
                f"stopped: the one-minute load ended over {LOAD_MOST} after each of "
                f"{len(attempts)} reads of {found['graph']} with {found['decided']} decided"
            )
        found["load_1m"] = attempts[-1]["load_1m"]
        found["attempts"] = attempts
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
    idle_after = idle_share()
    mean_idle = (
        None
        if idle_before is None or idle_after is None
        else (Decimal(str(idle_before)) + Decimal(str(idle_after))) / 2
    )
    phases["reads"] = {
        "gated": not smoke,
        "timed": True,
        "idle_percent_before": hour_line._percent(idle_before),
        "idle_percent_after": hour_line._percent(idle_after),
        "idle_percent_mean": None if mean_idle is None else str(mean_idle),
        "idle_percent_mean_least": str(IDLE_MEAN_PERCENT),
        "load_most_before_each_point": str(LOAD_MOST),
        "load_most_after_each_point": str(LOAD_MOST),
        "reads_again_most": READS_AGAIN_MOST,
        "load_wait_seconds_most": LOAD_WAIT_SECONDS,
        "load_before": load_before,
        "load_after": load_average(),
    }
    return {
        "phases": phases,
        "points": points,
        "discard": discarded(mean_idle, smoke=smoke),
        "refused": None,
    }


def _derived(line: dict[str, Any], populations: list[int], catalogs: Any) -> dict[str, Any]:
    """The most people a day's comparison of a living town runs and the most a model may decide
    for, from the fitted line and the day's protocol's pair budget, as the reading bound derives
    them."""
    budget_ms = protocol_value(catalogs, "pair_replay_budget_ms")
    bound = ReadingBound(
        run_us=budget_ms * 1000 // PAIR_RUNS,
        fixed_us=line["replay_fixed_ms"] * 1000,
        per_person_us=line["replay_per_person_us"],
        per_decided_us=line["replay_per_decided_person_us"],
        per_pair_us=line["replay_per_decided_pair_us"],
    )
    shown = sorted({*populations, hour_line.GROUND_BOUND})
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--worlds", type=int, default=8)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-stress", action="store_true", help="measure no stress town")
    parser.add_argument(
        "--gate-wait-seconds",
        type=float,
        default=GATE_WAIT_SECONDS,
        help="how long the reads' idle gate is waited for",
    )
    parser.add_argument(
        "--smoke", action="store_true", help="no machine gate; the record is always discarded"
    )
    args = parser.parse_args()
    source = hour_line._source()
    catalogs = comparison_catalogs_for_engine(LIVING_TOWN_PROFILE, "day")
    window = protocol_value(catalogs, "window_ticks")
    if window % HOUR_TICKS:
        raise SystemExit("a day's window is a whole number of hours")
    load_at_start = load_average()
    graphs: list[dict[str, Any]] = []
    surveyed: dict[str, list[int]] = {}
    for preset in hour_line.PRESETS:
        worlds = sorted(
            (hour_line.compose(preset, index) for index in range(args.worlds)),
            key=lambda world: (world["population"], world["world_id"]),
        )
        surveyed[preset] = [world["population"] for world in worlds]
        for world in (worlds[len(worlds) // 2], worlds[-1]):
            if world["world_id"] not in {held["world_id"] for held in graphs}:
                graphs.append(world)
    stress = None
    for index in range(0 if args.no_stress else hour_line.STRESS_TRIES):
        try:
            found = hour_line.compose(hour_line.STRESS_PRESET, index, stress=True)
        except Exception as exc:  # the recipe refuses most identities, by name
            print(f"stress identity {index} not measured: {type(exc).__name__}", flush=True)
            continue
        if hour_line.STRESS_POPULATION_LEAST <= found["population"] <= hour_line.GROUND_BOUND:
            stress = found
            break
    if stress is not None:
        graphs.append(stress)
    measured = run(
        graphs,
        repeats=args.repeats,
        window=window,
        catalogs=catalogs,
        smoke=args.smoke,
        wait_seconds=args.gate_wait_seconds,
    )
    if measured["refused"] is not None:
        print(measured["refused"], flush=True)
        return 3
    points = measured["points"]
    line = hour_line._fit(points, pairs=True)
    record = {
        "kind": KIND,
        "engine": LIVING_TOWN_PROFILE,
        "source": source,
        "script": "scripts/measure_living_day_replay.py",
        "window_ticks": window,
        "hour_ticks": HOUR_TICKS,
        "repeats": args.repeats,
        "smoke": args.smoke,
        "machine": {
            "system": platform.platform(),
            "python": sys.version.split()[0],
            "cpus": os.cpu_count(),
        },
        "phases": {
            "compose": {"gated": False, "timed": False, "load_before": load_at_start},
            **measured["phases"],
        },
        "discard": measured["discard"],
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
        "line_without_pairs": hour_line._fit(points, pairs=False),
        "derived": _derived(line, [world["population"] for world in graphs], catalogs),
        "limits": [
            "Scripted answers the engine applies: the most receipts a run can hold, not any "
            "model's behaviour.",
            "Each graph is measured at its own population only, nobody, everybody and each "
            "stated group decided for.",
            "A sealed hour's asking facts are left out: scripted answers make no provider call.",
            "The stress town is outside the admitted specification and is never offered as a world.",
            "Composing and playing are neither gated nor timed; only the reads are.",
        ],
    }
    text = canonical_json(record).decode()
    hour_line._refuse_machine_paths(text)
    wrapped = {
        "profile": PROFILE,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
        "record": record,
    }
    args.out.write_text(json.dumps(wrapped, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"line": line, "derived": record["derived"], "discard": record["discard"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
