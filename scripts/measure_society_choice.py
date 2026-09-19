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
import hashlib
import json
import sys
import time
from collections import Counter
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import load_routine_model
from exulanica.world.society_choice import (
    RULE,
    ChoiceCounters,
    ChoiceDecision,
    DeterministicChoices,
    option_key,
)
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


class GreedyDestinationBound:
    """A chooser that never declines a destination, run as the experiment's positive control.

    Not a model, not a proposal, and not something anybody would ship: it takes a destination
    whenever the closed answer set offers one, breaking ties towards the least loaded and then
    the nearest, and leaves the rest to the rule.

    It is greedy and therefore NOT an optimum: a scheduler with foresight could in principle beat
    it, and on at least one seed it scores below the rule, because taking the nearest destination
    now can leave somebody with nothing later. What it does bound is how OFTEN a destination is
    chosen, since it declines none.

    The airtight ceiling is arithmetic instead, and ``occupancy`` reports it: a destination whose
    visitor capacity is one can be held by one person per tick, so capacity times ticks is every
    person-tick of occupancy that exists to be won. This arm exists to show what a chooser that
    wants nothing else actually collects out of that, which is the experiment's whole premise
    measured for nothing.
    """

    records = False

    def __init__(self, counters: ChoiceCounters | None = None) -> None:
        self.counters = counters

    def decide(self, question: Any, deterministic: Any) -> ChoiceDecision:
        asked = question()
        named = [option for option in asked.options if option["destination_id"]]
        if named:
            pick = min(named, key=lambda o: (o["load_milli"], o["cost_mm"], o["option_key"]))
            decision = ChoiceDecision(
                outcome=pick["outcome"],
                decided_by="greedy_destination_bound",
                option_key=pick["option_key"],
                destination_id=pick["destination_id"],
                blocked_reason=None,
                confidence_milli=1000,
            )
        else:
            outcome = deterministic()
            blocked = outcome if isinstance(outcome, str) else None
            decision = ChoiceDecision(
                outcome=outcome,
                decided_by=RULE,
                option_key=None if blocked else option_key(outcome[1]),
                destination_id=None if blocked else outcome[1].get("destination_id"),
                blocked_reason=blocked,
            )
        if self.counters is not None:
            self.counters.record(decision)
        return decision


ARMS: Final = {"rule": None, "greedy-destination-bound": GreedyDestinationBound}


def _seeds(count: int) -> list[str]:
    """Distinct seeds derived from the recorder's own seed, so run one reproduces the preview."""
    if count == 1:
        return [SEED]
    return [SEED] + [f"{index:02x}" * 32 for index in range(1, count)]


def measure(seed: str, ticks: int, arm: str = "rule") -> dict[str, Any]:
    """Advance one society and report the counts plus what moved.

    ``arm`` names who answers each choice. ``rule`` is the deterministic chooser and is the
    baseline every other arm is compared against; the instrument is otherwise identical, which
    is the only way a difference between two runs can be attributed to the chooser.
    """
    routine = load_routine_model()
    document = flatiron_input()
    place_document = place_from_society_input(document, routine)
    place = LivingPlace(place_document, routine)
    counters = ChoiceCounters()
    source = ARMS[arm]
    choices = DeterministicChoices(counters) if source is None else source(counters)
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
        "arm": arm,
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
        "choices_not_answered_by_the_rule": counters.not_the_rule,
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
        # Milliseconds as an integer: a float may never enter a digest input.
        "wall_milliseconds": int(elapsed_s * 1000),
    }


def occupancy(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """What the destinations could ever hold, against what they did hold.

    The ceiling is arithmetic from the place's own contract: a destination whose visitor capacity
    is one can be held by one person in one tick and no chooser can beat that. It is stated here
    because it is the figure that decides whether a better chooser has anything to win, and a
    result reported without it would look like an improvement waiting to be found.
    """
    rows = []
    for run in runs:
        held = run["destination_held_person_ticks"]
        ceiling = sum(run["destination_capacity"].values()) * run["ticks"]
        counts = sorted(held.values())
        rows.append(
            {
                "seed_sha256": run["seed_sha256"],
                "arm": run["arm"],
                "held_person_ticks_total": sum(counts),
                "ceiling_person_ticks": ceiling,
                "headroom_person_ticks": ceiling - sum(counts),
                "headroom_share_of_person_ticks_milli": (
                    (ceiling - sum(counts)) * 1000 // run["person_ticks"]
                ),
                "busiest_minus_quietest_person_ticks": counts[-1] - counts[0],
                "choices_naming_a_destination": (
                    run["choices_asked"]
                    - run["choices_without_a_destination"]
                    - run["choices_with_nothing_possible"]
                ),
            }
        )
    return {
        "note": (
            "headroom is every person-tick of destination occupancy that a perfect chooser "
            "could add and the deterministic chooser did not. It is not an estimate."
        ),
        "per_run": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=1, help="how many distinct seeds to run")
    parser.add_argument("--ticks", type=int, default=DEFAULT_TICKS, help="simulated minutes")
    parser.add_argument("--output", type=str, default=None, help="where to write the record")
    parser.add_argument(
        "--arms",
        nargs="+",
        default=["rule"],
        choices=sorted(ARMS),
        help="who answers each choice; every arm runs over every seed",
    )
    parser.add_argument(
        "--evaluation-record",
        type=str,
        default=None,
        help="also seal the runs as a digest-bound record at this path, under `record`",
    )
    parser.add_argument(
        "--subject", type=str, default=None, help="the subject line of the sealed record"
    )
    args = parser.parse_args(argv)
    if not 1 <= args.seeds <= 32 or not 1 <= args.ticks <= 1440:
        raise SystemExit("--seeds is 1 to 32 and --ticks is 1 to 1440 simulated minutes")
    runs = [measure(seed, args.ticks, arm) for arm in args.arms for seed in _seeds(args.seeds)]
    record = {
        "profile": PROFILE,
        "generator": {
            "script": "scripts/measure_society_choice.py",
            "seeds": args.seeds,
            "ticks": args.ticks,
            "arms": list(args.arms),
        },
        "occupancy": occupancy(runs),
        "runs": runs,
    }
    text = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    elif not args.evaluation_record:
        sys.stdout.write(text)
    if args.evaluation_record:
        sealed = {
            "profile": "exulanica.digest-bound-record/v1",
            "record": {**record, "subject": args.subject or "society destination occupancy"},
        }
        sealed["record_sha256"] = hashlib.sha256(canonical_json(sealed["record"])).hexdigest()
        with open(args.evaluation_record, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(sealed, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
