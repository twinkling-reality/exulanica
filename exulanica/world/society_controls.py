"""Declared playback timing, independent of deterministic simulation time."""

from __future__ import annotations

import datetime as dt
import math
import uuid
from dataclasses import dataclass

CONTROL_PROFILE = "exulanica.society-control/v1"
EVENT_PROFILE = "exulanica.society-control-event/v1"
SPEEDS = (1, 2, 4)
#: The host's base wait between simulated minutes, in whole milliseconds, and its declared bounds.
#: Every speed divides the base exactly, so an effective interval is never a rounded one.
BASE_TICK_INTERVAL_MIN_MS = 1000
BASE_TICK_INTERVAL_MAX_MS = 60000
BASE_TICK_INTERVAL_DIVISOR = math.lcm(*SPEEDS)
#: Measured (docs/evaluation/2026-09-24-living-world-pace.json) on saved worlds of eight people and
#: four or eight objects on a ring 6 m in radius: a person there walks a median 10.0 m in a
#: walking minute, which over 8 s is 1.26 m/s at 1x, inside the ordinary walking the society policy
#: states; tests/test_living_world_pace.py holds the default to that. It is a figure about those
#: worlds, not the speed a renderer draws. A renderer walks a person at their own walking pace and
#: walks a tick's path evenly over the presented interval only when it is too long for that pace,
#: so a world whose ticks take people farther, up to the 60 m a new society's bound allows, is
#: drawn faster than a walk at this base; EXULANICA_SOCIETY_TICK_INTERVAL_MS sets a longer one.
#: At 4x this base still leaves 2 s between minutes.
DEFAULT_BASE_TICK_INTERVAL_MS = 8000
MAX_CATCHUP_TICKS = 3
#: How long a playback claim holds a society before another worker may take it: the 30-second
#: expiry the society contract's playback policy declares (``docs/synthetic-society-contract.md``).
#: Declared with the playback leases (migration 0059), not measured, and no derivation is
#: recorded; a decision's deadline must end inside it, and a comparison start is leased for it.
LEASE_SECONDS = 30
MAX_CLAIM_ATTEMPTS = 3


class LeaseLost(Exception):
    """This claim no longer authorizes a committed automatic tick."""


def validate_settings(mode: str, speed: int, base_tick_interval_ms: int) -> None:
    if mode not in ("paused", "playing") or type(speed) is not int or speed not in SPEEDS:
        raise ValueError("unsupported playback mode or speed")
    if (
        type(base_tick_interval_ms) is not int
        or not BASE_TICK_INTERVAL_MIN_MS <= base_tick_interval_ms <= BASE_TICK_INTERVAL_MAX_MS
        or base_tick_interval_ms % BASE_TICK_INTERVAL_DIVISOR
    ):
        raise ValueError(
            f"base playback cadence must be {BASE_TICK_INTERVAL_MIN_MS}.."
            f"{BASE_TICK_INTERVAL_MAX_MS} whole milliseconds divisible by "
            f"{BASE_TICK_INTERVAL_DIVISOR}"
        )


def effective_interval_ms(base_tick_interval_ms: int, speed: int) -> int:
    """The minimum wait between batches at ``speed``: the base divided by the chosen speed."""
    validate_settings("paused", speed, base_tick_interval_ms)
    return base_tick_interval_ms // speed


def utc(value: dt.datetime | None) -> str | None:
    return None if value is None else value.astimezone(dt.UTC).isoformat(timespec="microseconds")


def ticks_due(now: dt.datetime, due_at: dt.datetime, interval_ms: int) -> int:
    if now < due_at:
        return 0
    elapsed = now - due_at
    milliseconds = elapsed.days * 86400000 + elapsed.seconds * 1000 + elapsed.microseconds // 1000
    return milliseconds // interval_ms + 1


@dataclass(frozen=True)
class ControlClaim:
    workspace_id: uuid.UUID
    #: The world the claimed society belongs to. A workspace holds the default world and every
    #: saved world a person made, and the claim is only executed in the world it was taken in.
    world_id: str
    society_id: uuid.UUID
    version_id: uuid.UUID
    token: uuid.UUID
    revision: int
    actor: uuid.UUID
