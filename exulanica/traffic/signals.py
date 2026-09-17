"""Signal indications as a pure function of plan, offset and simulated second.

A controller's state is never stored: it is recomputed from the catalog plan, the record's
offset and the second, so the society lane can ask when a crossing shows walk without holding
any traffic state, and replay can never disagree with a stored copy.

The plan's cycle starts at second ``offset``. Second ``t`` shows the interval that contains
``(t - offset) mod cycle``. A vehicle group is ``green``, ``amber`` or ``red``; a pedestrian group
is ``walk``, ``clearance`` or ``dont_walk``.
"""

from __future__ import annotations

from typing import Final

from exulanica.traffic.catalogs import SignalPlan

__all__ = [
    "PEDESTRIAN_INDICATIONS",
    "VEHICLE_INDICATIONS",
    "interval_index",
    "pedestrian_indication",
    "seconds_until_red",
    "vehicle_indication",
]

VEHICLE_INDICATIONS: Final = ("green", "amber", "red")
PEDESTRIAN_INDICATIONS: Final = ("walk", "clearance", "dont_walk")
_MS: Final = 1000


def _boundaries(plan: SignalPlan) -> tuple[int, ...]:
    ends = []
    total = 0
    for interval in plan.intervals:
        total += interval.duration_ms // _MS
        ends.append(total)
    return tuple(ends)


def interval_index(plan: SignalPlan, offset_s: int, second: int) -> int:
    cycle = plan.cycle_ms // _MS
    position = (second - offset_s) % cycle
    for index, end in enumerate(_boundaries(plan)):
        if position < end:
            return index
    raise AssertionError("a position inside the cycle falls in an interval")


def vehicle_indication(plan: SignalPlan, offset_s: int, second: int, group: str) -> str:
    interval = plan.intervals[interval_index(plan, offset_s, second)]
    if group in interval.vehicle_green:
        return "green"
    if group in interval.vehicle_amber:
        return "amber"
    return "red"


def pedestrian_indication(plan: SignalPlan, offset_s: int, second: int, group: str) -> str:
    interval = plan.intervals[interval_index(plan, offset_s, second)]
    if group in interval.pedestrian_walk:
        return "walk"
    if group in interval.pedestrian_clearance:
        return "clearance"
    return "dont_walk"


def seconds_until_red(plan: SignalPlan, offset_s: int, second: int, group: str) -> int:
    """How many seconds from ``second`` on are not red: 0 if ``second`` itself is red.

    A plan in which the group is never red returns one full cycle, which is as far as any
    caller needs to look.
    """
    cycle = plan.cycle_ms // _MS
    for step in range(cycle):
        if vehicle_indication(plan, offset_s, second + step, group) == "red":
            return step
    return cycle
