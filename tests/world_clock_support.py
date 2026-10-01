"""A generated town's walkers and its traffic, coupled without a database, for the clock's tests.

The living town walks the town's own place (``living_town_support``); each committed minute's
crossing occupancy is projected as the society repository records it in a coupled era; traffic
runs its episodes over the same town's roads with the feeds that occupancy projects; and every
transition can be judged by the independent traffic checker. Pure: no connection, no store, no
model.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from functools import cache
from itertools import pairwise
from typing import Any

from exulanica.traffic.checks import TransitionChecker, Violation
from exulanica.traffic.inputs import CrossingFeed, TrafficInputs, TripRequest
from exulanica.world.generated_worlds import compose_generated_world
from exulanica.world.society_living import (
    LIVING_TOWN_PROFILE,
    advance_living_society,
    initial_living_society,
    input_routine,
    living_places,
)
from exulanica.world.traffic_episodes import (
    EPISODE,
    Prepared,
    TrafficInput,
    home_segment,
    prepared,
    road_records,
    traffic_input,
)
from exulanica.world.world_clock import (
    Era,
    crossing_edges,
    crossing_feeds,
    minute_occupancy,
    occupancy_intervals,
)
from exulanica.world.world_recipes import town_recipe

from living_town_support import SEED, town_input

SOCIETY = uuid.UUID("5a5a5a5a-0000-4000-8000-00000000c10c")
#: Any whole traffic episode serves as a test era's timeline origin.
ORIGIN = 1_000 * EPISODE


@dataclass(frozen=True)
class Walked:
    """A town's minutes, walked from the era's start: their occupancy and the era itself."""

    era: Era
    occupancy: tuple[dict[str, Any], ...]
    states: tuple[dict[str, Any], ...]


@cache
def town_roads(recipe: str = "small_town", index: int = 0) -> tuple[TrafficInput, Prepared]:
    """The traffic input of the town ``living_town_support`` composes, and its compiled roads."""
    world_id = f"world:generated:living-town-{recipe}-{index}"
    composed = compose_generated_world(town_recipe(recipe, None), world_id)
    value = traffic_input(
        world_id=world_id,
        version_id=composed.receipt_sha256,
        city_identity=str(composed.receipt["subject_identity"]),
        grammar_version=int(composed.receipt["grammar"]["grammar_version"]),
        records=road_records(composed.records),
    )
    return value, prepared(value)


def band_identities(ready: Prepared) -> dict[str, str]:
    return {band.identity: band.society_crossing_id for band in ready.network.bands}


def walk(recipe: str = "small_town", index: int = 0, *, warm: int, minutes: int) -> Walked:
    """``warm`` minutes of the town's day from 06:00, then ``minutes`` more whose occupancy is
    projected, the era beginning where the warm minutes end."""
    document = town_input(recipe, (), index)
    routine = input_routine(document)
    [place] = living_places([document], routine, {})
    state = initial_living_society(
        SOCIETY,
        SEED,
        place,
        routine,
        branch_id=document["version_id"],
        population=document["population"]["size"],
        profile=LIVING_TOWN_PROFILE,
    )
    for _ in range(warm):
        state, _events = advance_living_society(state, SEED, [place], routine)
    era = Era(1, state["tick"], 60, ORIGIN)
    edges = crossing_edges([place.document])
    documents = []
    states = [state]
    for _ in range(minutes):
        before = state
        state, events = advance_living_society(state, SEED, [place], routine)
        documents.append(
            minute_occupancy(
                society_id=str(SOCIETY),
                era=1,
                before=before,
                after=state,
                events=[event.document for event in events],
                crossings_by_edge=edges,
                place_sha256=place.document["document_sha256"],
            )
        )
        states.append(state)
    return Walked(era, tuple(documents), tuple(states))


def episode_feeds(
    walked: Walked, ready: Prepared, episode: int, *, through_segment: int
) -> tuple[CrossingFeed, ...]:
    """The feeds episode ``episode`` of the era's timeline reads, through ``through_segment``."""
    return crossing_feeds(
        occupancy_intervals(walked.occupancy),
        era=walked.era,
        episode_first_second=episode * EPISODE,
        covers_through_local_second=60 * (through_segment + 1) + 59,
        bands=band_identities(ready),
    )


def drive(
    value: TrafficInput,
    ready: Prepared,
    episode: int,
    segments: int,
    feeds: tuple[CrossingFeed, ...] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """``segments`` minutes of one episode from its genesis, fed ``feeds`` (None: nobody walks)."""
    states, continuation, _summary, point = home_segment(
        value, ready, episode, 60 * segments, None, feeds=feeds
    )
    assert point is None
    return states, continuation


def judged(
    ready: Prepared,
    states: list[dict[str, Any]],
    continuation: dict[str, Any],
    feeds: tuple[CrossingFeed, ...],
) -> list[Violation]:
    """Every violation the independent checker finds in the run, against ``feeds``."""
    trips = tuple(TripRequest(**item) for item in continuation["trips"])
    checker = TransitionChecker(ready.network, ready.catalogs, TrafficInputs(trips, feeds))
    found = []
    for before, after in pairwise(states):
        found.extend(checker.check(before, after))
    return found
