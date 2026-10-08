"""Whether a generation session can take requests now: off, starting, warm or ended.

The operator starts a session for a stated window (Nebius AI Cloud, the operator's account) and
registers it with the product; the session writes a heartbeat into the bucket every 30 seconds with
its state (``loading``, ``idle``, ``working``, and ``ended: <reason>`` on its last). The product
reads it this way:

- **off**: no session is registered, or its window has ended;
- **starting**: registered and inside its window, with no heartbeat yet or one that says it is
  still loading its models (the measured cold start, about 11 minutes from asking);
- **warm**: its latest heartbeat is idle or working and is at most :data:`BEAT_STALE_SECONDS` old;
- **ended**: its latest heartbeat says it ended, or the heartbeats stopped (the last is older than
  :data:`BEAT_STALE_SECONDS`), so the session will take nothing more.

Only a warm session is given a queue entry: an entry written for a session that is not taking any
would hold its requests' reservations past their dispatch window.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Final, Literal

__all__ = ["BEAT_STALE_SECONDS", "SessionState", "session_state"]

#: Three missed heartbeats: the session writes one every 30 seconds.
BEAT_STALE_SECONDS: Final = 90
_INSTANT: Final = "%Y-%m-%dT%H:%M:%SZ"

SessionState = Literal["off", "starting", "warm", "ended"]


def session_state(
    *,
    registered: bool,
    window_ends_at: datetime | None,
    beat: Mapping[str, Any] | None,
    now: datetime,
) -> SessionState:
    """The session's state from its registration, its window and its latest heartbeat."""
    if not registered or window_ends_at is None or now >= window_ends_at:
        return "off"
    if beat is None:
        return "starting"
    state = str(beat["state"])
    if state.startswith("ended"):
        return "ended"
    at = datetime.strptime(str(beat["at"]), _INSTANT).replace(tzinfo=UTC)
    if (now - at).total_seconds() > BEAT_STALE_SECONDS:
        return "ended"
    if state == "loading":
        return "starting"
    if state in ("idle", "working"):
        return "warm"
    return "ended"
