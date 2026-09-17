"""Integer kinematics: one tick is one simulated second, speeds in mm/s, rates in mm/s per tick.

A vehicle moves ``v'`` millimetres in a tick where ``v'`` is its new speed, chosen from
``[max(0, v - b), min(v + a, cap)]``. ``b`` is the deceleration the controller plans with and
never exceeds.

**The safety rule.** :func:`braking_run` ``P(v, k)`` is how far a vehicle at speed ``v`` travels
in ``k`` more ticks of full braking. A follower may pick ``v'`` only if, for every ``k >= 0``,

    v' + P_f(v', k) + gap  <=  D + P_l(v_l, k + 1)

where ``D`` is the gap to the leader's rear now and the right side is the least the leader can
travel if it brakes fully from this tick on. Full braking always satisfies the rule when it held
last tick, and the leader's real progress can only be larger, so the rule holds forever by
induction. A static obstacle is a leader with speed zero.

**Speed caps ahead.** A lower cap at distance ``D`` is honoured if every tick that ends before or
at ``D`` is driven above the cap only while the vehicle has not reached ``D``.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

__all__ = [
    "braking_run",
    "cap_allows",
    "clearing_ticks",
    "follows_safely",
    "highest_speed",
    "reach_ticks",
    "stopping_distance",
]


def braking_run(speed: int, deceleration: int, ticks: int) -> int:
    """Distance covered in ``ticks`` ticks of full braking from ``speed``."""
    if speed <= 0 or ticks <= 0:
        return 0
    # Tick j moves max(0, speed - j * deceleration); the terms past speed // deceleration are
    # zero, and the one at exactly that index is zero too, so summing up to it is exact.
    moving = min(ticks, speed // deceleration)
    return moving * speed - deceleration * moving * (moving + 1) // 2


def stopping_distance(speed: int, deceleration: int) -> int:
    return braking_run(speed, deceleration, speed // deceleration + 1)


def _braking_ticks(speed: int, deceleration: int) -> int:
    return speed // deceleration + 1


def follows_safely(
    new_speed: int,
    deceleration: int,
    gap: int,
    distance: int,
    leader_speed: int,
    leader_deceleration: int,
) -> bool:
    """The safety rule above, checked for every ``k`` until both vehicles have stopped."""
    horizon = max(
        _braking_ticks(new_speed, deceleration), _braking_ticks(leader_speed, leader_deceleration)
    )
    for ticks in range(horizon + 1):
        own = new_speed + braking_run(new_speed, deceleration, ticks) + gap
        other = distance + braking_run(leader_speed, leader_deceleration, ticks + 1)
        if own > other:
            return False
    return True


def cap_allows(new_speed: int, deceleration: int, distance: int, cap: int) -> bool:
    """Whether a cap of ``cap`` starting ``distance`` ahead can still be met from ``new_speed``."""
    if new_speed <= cap:
        return True
    # The last tick still driven above the cap is the ``fast``-th one after this tick.
    fast = -(-(new_speed - cap) // deceleration) - 1
    return new_speed + braking_run(new_speed, deceleration, fast) <= distance


def highest_speed(low: int, high: int, allowed: Callable[[int], bool]) -> int | None:
    """The largest speed in ``[low, high]`` that ``allowed`` accepts, for a monotone ``allowed``."""
    if high < low or not allowed(low):
        return None
    while low < high:
        middle = (low + high + 1) // 2
        if allowed(middle):
            low = middle
        else:
            high = middle - 1
    return low


def reach_ticks(distance: int, speed: int, acceleration: int, cap: int) -> int:
    """The fewest ticks in which a vehicle accelerating flat out can cover ``distance``."""
    covered = 0
    ticks = 0
    while covered < distance:
        speed = min(speed + acceleration, cap)
        if speed <= 0:
            return 1 << 30
        covered += speed
        ticks += 1
    return ticks


@lru_cache(maxsize=65_536)
def clearing_ticks(
    distance: int, speed: int, acceleration: int, deceleration: int, cap: int
) -> int:
    """Ticks for the controller, alone, to bring its front ``distance`` forward.

    The vehicle starts at ``speed``, respects ``cap``, and treats a static obstacle exactly at
    ``distance`` as the thing it must be able to stop for, which is the slowest way a vehicle
    admitted with room beyond its region can be made to travel.
    """
    covered = 0
    ticks = 0
    while covered < distance:
        remaining = distance - covered
        low = max(0, speed - deceleration)
        high = max(low, min(speed + acceleration, cap))
        chosen = highest_speed(
            low,
            high,
            lambda candidate, remaining=remaining: follows_safely(
                candidate, deceleration, 0, remaining, 0, 1
            ),
        )
        speed = low if chosen is None else chosen
        covered += speed
        ticks += 1
        if ticks > 3600:
            raise AssertionError("a lone vehicle always reaches a static obstacle")
    return ticks
