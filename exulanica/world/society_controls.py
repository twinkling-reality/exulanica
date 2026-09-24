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
#: Measured (docs/evaluation/2026-09-24-living-world-pace.json): a person in a saved world walks a
#: median 10.0 m in a walking minute, and a renderer walks each path over the effective interval,
#: so 8 s shows 1.26 m/s at 1x, inside the ordinary walking the society policy states. At 4x it
#: still leaves 2 s between minutes. tests/test_living_world_pace.py holds it to both.
DEFAULT_BASE_TICK_INTERVAL_MS = 8000
MAX_CATCHUP_TICKS = 3
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
