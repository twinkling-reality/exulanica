#!/usr/bin/env python3
"""Measure how the v4 living society spreads over the destinations its place publishes.

This is the instrument the society decision experiment is judged against, and it runs the real
engine over the committed Flatiron district: ``scripts.record_living_society.flatiron_input`` is
imported rather than retyped, so the input this measures is the input the preview records.

Five counts are reported and they are five different sets. A figure without its set is not a
measurement, so none of them is ever summed into another:

    people                  inhabitants the place sized, once per run
    ticks                   simulated minutes advanced, once per run
    person_ticks            people times ticks, the denominator for every occupancy figure
    choices_asked           times the engine had to choose an activity, over the whole run
    choices_by_destination  of those, the ones that named a destination, per destination

``choices_asked`` is counted at the engine's own seam, by ``exulanica.world.society_choice``,
so the count is of calls that happened and not of events that survived deduplication. With no
provider configured every choice falls through to the deterministic chooser, which is what makes
this file usable as both the baseline and the arm: the instrument does not change between them.

Usage: ``uv run python -m scripts.measure_society_choice --seeds 4 --ticks 1440``.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from typing import Any, Final

from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_choice import ChoiceCounters, DeterministicChoices
from exulanica.world.society_living import (
    LIVING_PROFILE,
    LivingPlace,
    advance_living_society,
    initial_living_society,
)
from exulanica.world.society_place import place_from_society_input
from scripts.record_living_society import SEED, SOCIETY_ID, flatiron_input

DEFAULT_TICKS: Final = 1440
PROFILE: Final = "exulanica.society-choice-measurement/v1"


def _seeds(count: int) -> list[str]:
    """Distinct seeds derived from the recorder's own seed, so run one reproduces the preview."""
    if count == 1:
        return [SEED]
    return [SEED] + [f"{index:02x}" * 32 for index in range(1, count)]


def measure(seed: str, ticks: int, source: Any = None) -> dict[str, Any]:
    """Advance one society and report the five counts plus what moved.

    ``source`` is who answers each choice. Left unset it is the deterministic chooser, and
    that run is the baseline every arm is compared against.
    """
    routine = load_routine_model()
    document = flatiron_input()
    place_document = place_from_society_input(document, routine)
    place = LivingPlace(place_document, routine)
    counters = ChoiceCounters()
    choices = DeterministicChoices(counters) if source is None else source
    state = initial_living_society(
        SOCIETY_ID, seed, place, routine, branch_id=document["version_id"]
    )
    people = state["population"]["size"]
    start_positions = [tuple(p["position_mm"]) for p in state["inhabitants"]]
    travel = [0] * people
    moved = [False] * people
    holding = Counter()
    previous = start_positions
    started = time.monotonic()
    for _ in range(ticks):
        state, _events = advance_living_society(state, seed, [place], routine, choices)
        current = []
        for index, person in enumerate(state["inhabitants"]):
            point = tuple(person["position_mm"])
            step = abs(point[0] - previous[index][0]) + abs(point[1] - previous[index][1])
            travel[index] += step
            moved[index] = moved[index] or bool(step)
            current.append(point)
            goal = person["goal"]
            if goal and goal["destination_id"]:
                holding[goal["destination_id"]] += 1
        previous = current
    elapsed_s = time.monotonic() - started
    final = [tuple(p["position_mm"]) for p in state["inhabitants"]]
    return {
        "seed_sha256": seed,
        "engine_profile": LIVING_PROFILE,
        "district_document_sha256": document["district_document_sha256"],
        "input_sha256": document["document_sha256"],
        "place_sha256": place_document["document_sha256"],
        "final_state_sha256": society_state_sha256(state),
        "population_rule": state["population"]["rule"],
        "people": people,
        "ticks": ticks,
        "person_ticks": people * ticks,
        "destinations": sorted(place.destinations),
        "destination_capacity": {
            key: value["visitor_capacity"] for key, value in sorted(place.destinations.items())
        },
        "choices_asked": counters.asked,
        "choices_answered_by_model": counters.model,
        "choices_provider_silent": counters.provider_silent,
        "choices_below_threshold": counters.below_threshold,
        "choices_fallen_through": counters.fallback,
        "choices_by_destination": {
            key: counters.by_destination.get(key, 0) for key in sorted(place.destinations)
        },
        "choices_without_a_destination": counters.without_destination,
        "choices_with_nothing_possible": counters.nothing_possible,
        "destination_held_person_ticks": {
            key: holding.get(key, 0) for key in sorted(place.destinations)
        },
        "destination_held_person_ticks_total": sum(holding.values()),
        "distinct_positions_final_tick": len(set(final)),
        "people_who_ever_moved": sum(moved),
        "travel_mm_total": sum(travel),
        "travel_mm_median": sorted(travel)[people // 2],
        "travel_mm_max": max(travel),
        "wall_seconds": round(elapsed_s, 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=1, help="how many distinct seeds to run")
    parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS, help="simulated minutes")
    parser.add_argument("--output", type=str, default=None, help="where to write the record")
    args = parser.parse_args(argv)
    if not 1 <= args.seeds <= 32 or not 1 <= args.ticks <= 1440:
        raise SystemExit("--seeds is 1 to 32 and --ticks is 1 to 1440 simulated minutes")
    runs = [measure(seed, args.ticks) for seed in _seeds(args.seeds)]
    record = {
        "profile": PROFILE,
        "generator": {
            "script": "scripts/measure_society_choice.py",
            "seeds": args.seeds,
            "ticks": args.ticks,
        },
        "runs": runs,
    }
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
