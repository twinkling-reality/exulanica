"""Declared playback timing, independent of deterministic simulation time."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

CONTROL_PROFILE = "exulanica.society-control/v1"
EVENT_PROFILE = "exulanica.society-control-event/v1"
SPEEDS = (1, 2, 4)
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
        or not 1000 <= base_tick_interval_ms <= 60000
        or base_tick_interval_ms % 4
    ):
        raise ValueError(
            "base playback cadence must be 1000..60000 whole milliseconds divisible by 4"
        )


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
