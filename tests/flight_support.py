"""Worlds to fly over, composed as the flight route composes them, with no database.

The worlds are the flight bounds measurement's own (``scripts/measure_flight_bounds.py``): the small
square before a starter world's arrival point, eight planter trees, and the crowded crowns. Each
flight is composed by :func:`exulanica.world.flight_input.compose_flight_input`, the function the
route calls, from the reviewed assets' own digests.
"""

from __future__ import annotations

from functools import cache

from exulanica.movement.flight import FlightInput
from exulanica.movement.flight_checks import check_windows
from scripts.measure_flight_bounds import compose, seeded, seeds, square_objects

__all__ = [
    "DEVELOPMENT_SEEDS",
    "check_windows",
    "cluttered_flight",
    "crowded_flight",
    "seeded",
    "square_flight",
    "square_objects",
    "trees_flight",
]

#: Seeds for developing and testing the flight module, disjoint from the seeds the flight bounds
#: record judges, so the judged run is taken on seeds the module was never tuned on.
DEVELOPMENT_SEEDS = tuple(seeds("development"))


@cache
def square_flight() -> FlightInput:
    """The small square's flight: its tree's three small birds."""
    return compose("small_square")


@cache
def trees_flight() -> FlightInput:
    """Eight planter trees and their 24 small birds, the module's largest population."""
    return compose("eight_trees")


@cache
def crowded_flight() -> FlightInput:
    """Four trees among four taller ones whose crowns fill the band the birds fly in."""
    return compose("crowded_crowns")


@cache
def cluttered_flight() -> FlightInput:
    """The small square, seven more trees and twenty other objects: 24 birds among 36 objects."""
    return compose("cluttered")
