#!/usr/bin/env python3
"""Measure what a living town's routine spares its people over a day: a day comparison's floor.

    uv run python scripts/measure_living_day_anchors.py --out RECORD

Pure: no database, no store and no model. A comparison scores each model run on a seed against
that seed's two anchors, waiting (the score's zero) and the routine (its one), and a seed on which
the routine spares the scored people less than the protocol's floor per person is excluded by name
(``need_below_floor``). The first protocol's floor was measured on the starter world's small square
over an hour, in the purposeful score's one-need unit; a living town's day is scored in the living
unit, every supported need above its own threshold, over 1440 minutes. This measures that floor's
ground:

- **Towns.** The towns the living town's reading line was measured on, as its record names them
  (``docs/evaluation/2026-10-01-living-comparison-replay.json``), every one inside the admitted
  specification, each composed again through the same path and held to the population the record
  states for it.
- **Seeds.** Every development seed the seed catalog a day comparison is defined under commits,
  by its text; the record names each by digest.
- **Anchors.** For each town and seed, the routine's day and waiting's day for everybody, played
  hour by hour as a day comparison's host plays them (``play_hour``), each hour's terms the fifth
  score's and the day's assembled from them (``exulanica/world/society_score_v5.py``).
- **Floor.** The first protocol's rule, restated per person and for a day: a quarter of the median,
  over every town and seed, of the need the routine's day spares each person against waiting's,
  rounded down to the hundred.

Every figure is an integer or a decimal string to four places, the floor derived from the exact
values, and the record takes the digest-bound form every retained record takes, naming the tree
and each changed file by digest. The protocol a day comparison is defined under states the floor
this derives, so the catalogs read here are the day's score and seeds; which protocol they load
beside them changes nothing measured.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import uuid
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_living_comparison_replay import compose

from exulanica.canonical import canonical_json
from exulanica.world import society_score_v5
from exulanica.world.society_catalogs import (
    COMPARISON_PROTOCOL_CATALOG,
    COMPARISON_SEEDS_CATALOG,
    DAY_COMPARISON_VERSIONS,
    PERSON_SCORE_CATALOG,
    load_comparison_catalogs,
)
from exulanica.world.society_comparison import (
    HOUR_TICKS,
    HourStart,
    RunPlan,
    first_hour,
    play_hour,
)
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_living import LIVING_TOWN_PROFILE, input_routine

PROFILE: Final = "exulanica.digest-bound-record/v1"
KIND: Final = "exulanica.living-day-anchors-measurement/v1"
ROOT: Final = Path(__file__).resolve().parents[1]
#: The record whose towns this measures: the living town's reading line.
TOWNS_RECORD: Final = "docs/evaluation/2026-10-01-living-comparison-replay.json"
#: A day, in the society's minutes.
DAY_TICKS: Final = 1440
#: The anchors a comparison scores a run against: the score's one, then its zero.
ANCHORS: Final = (("routine", {"kind": "routine"}), ("wait", {"kind": "wait"}))
#: The first protocol's floor rule: a quarter of the median, rounded down to the hundred.
FLOOR_SHARE: Final = Fraction(1, 4)
FLOOR_STEP: Final = 100


class _AsksNobody:
    """An anchor's day asks nobody."""

    def offerable(self, tick: int, due: Any) -> Any:
        raise AssertionError("an anchor asks nobody")

    def answers(self, requests: Any) -> Any:
        raise AssertionError("an anchor asks nobody")


def _decimal(value: Fraction) -> str:
    """A value as a decimal string to four places, rounded half to even."""
    written = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_EVEN
    )
    return format(written + Decimal(0), "f")


def _median(values: list[Fraction]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _towns() -> list[dict[str, Any]]:
    """The towns the reading record measured inside the specification, by preset and index, with
    the population it states for each."""
    record = json.loads((ROOT / TOWNS_RECORD).read_text(encoding="utf-8"))["record"]
    return [
        {"preset": graph["preset"], "index": graph["index"], "population": graph["population"]}
        for graph in record["graphs"]
        if not graph["outside_specification"]
    ]


def _day(world: dict[str, Any], seed: str, decider: dict[str, Any], catalogs: Any) -> dict:
    """One anchor's day over everybody: its terms, assembled from its hours, and each hour's
    urgency."""
    plan = RunPlan(
        run_id=uuid.uuid5(uuid.NAMESPACE_URL, f"{world['world_id']}:{seed}:{decider['kind']}"),
        society_id=uuid.uuid5(uuid.NAMESPACE_URL, world["world_id"]),
        seed=seed,
        population=world["population"],
        inputs=(world["document"],),
        ticks=DAY_TICKS,
        decider=decider,
        provider_config=None,
        contract=decision_contract(),
        engine_profile=LIVING_TOWN_PROFILE,
    )
    routine = input_routine(world["document"])
    score = society_score_v5.score(catalogs.score).reliability
    start = first_hour(plan)
    people = [person["id"] for person in start.state["inhabitants"]]
    hours = []
    for hour in range(DAY_TICKS // HOUR_TICKS):
        played = play_hour(plan, _AsksNobody(), start=start)
        hours.append(
            society_score_v5.hour_terms(
                played.states,
                played.events,
                people=people,
                choice_points=sum(played.choice_points[subject] for subject in people),
                routine=routine,
                score=score,
            )
        )
        start = HourStart(hour + 1, played.states[-1], start.first_sequence)
    day = society_score_v5.day_terms(hours)
    return {
        "urgency": day["urgency"],
        "variety": sum(day["activities"].values()),
        "choice_points": day["choice_points"],
        "hourly_urgency": [hour["urgency"] for hour in hours],
    }


def _source() -> dict[str, Any]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    changed = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    paths = sorted(line[3:] for line in changed)
    return {
        "head": head,
        "changed_files_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in paths
            if (ROOT / path).is_file()
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    source = _source()
    # The day's score and seeds. The day's protocol states what this derives, so the hour's is
    # loaded beside them: no protocol value is read here.
    catalogs = load_comparison_catalogs(
        versions={**DAY_COMPARISON_VERSIONS, COMPARISON_PROTOCOL_CATALOG: 3}
    )
    seeds = [
        (str(entry["seed_digest"]), str(entry["seed"]))
        for _key, entry in sorted(catalogs.seeds.items())
        if entry["phase"] == "development"
    ]
    towns = []
    spared: list[Fraction] = []
    for town in _towns():
        world = compose(town["preset"], town["index"])
        if world["population"] != town["population"]:
            raise SystemExit(
                f"refused: {world['world_id']} composes {world['population']} people, and the "
                f"record states {town['population']}"
            )
        measured = []
        for digest, seed in seeds:
            routine, wait = (_day(world, seed, decider, catalogs) for _name, decider in ANCHORS)
            per_person = Fraction(wait["urgency"] - routine["urgency"], world["population"])
            spared.append(per_person)
            measured.append(
                {
                    "seed_digest": digest,
                    "routine": routine,
                    "wait": wait,
                    "spared_per_person": _decimal(per_person),
                }
            )
            print(
                json.dumps(
                    {
                        "world": world["world_id"],
                        "seed": digest[:12],
                        "spared_per_person": _decimal(per_person),
                        "variety": [routine["variety"], wait["variety"]],
                    }
                ),
                flush=True,
            )
        towns.append(
            {
                "world_id": world["world_id"],
                "preset": world["preset"],
                "index": world["index"],
                "population": world["population"],
                "seeds": measured,
            }
        )
    median = _median(spared)
    floor = int(median * FLOOR_SHARE) // FLOOR_STEP * FLOOR_STEP
    record = {
        "kind": KIND,
        "engine": LIVING_TOWN_PROFILE,
        "script": "scripts/measure_living_day_anchors.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source": source,
        "towns_record": TOWNS_RECORD,
        "towns_record_sha256": hashlib.sha256((ROOT / TOWNS_RECORD).read_bytes()).hexdigest(),
        "window_ticks": DAY_TICKS,
        "hour_ticks": HOUR_TICKS,
        "catalogs": {
            PERSON_SCORE_CATALOG: catalogs.versions[PERSON_SCORE_CATALOG],
            COMPARISON_SEEDS_CATALOG: catalogs.versions[COMPARISON_SEEDS_CATALOG],
        },
        "towns": towns,
        "derived": {
            "spared_per_person_median": _decimal(median),
            "spared_per_person_least": _decimal(min(spared)),
            "spared_per_person_most": _decimal(max(spared)),
            "points": len(spared),
            "rule": "a quarter of the median spared per person, rounded down to the hundred",
            "need_relief_floor_per_person": floor,
        },
        "limits": [
            "The anchors ask nobody, so the floor is a property of the routine and the towns, not "
            "of any model.",
            "Development seeds alone: the floor is set before any held-out seed is run.",
        ],
    }
    wrapped = {
        "profile": PROFILE,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
        "record": record,
    }
    args.out.write_text(json.dumps(wrapped, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(record["derived"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
