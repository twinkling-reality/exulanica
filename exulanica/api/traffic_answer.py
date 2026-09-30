"""How a traffic route answers: the status each refusal takes, and a window encoded by vehicle.

Two routes serve windows of the roads module, ``GET /tiles/traffic`` for a baked city the
development page walks and ``GET /world/versions/{version_id}/traffic`` for a saved world, and both
answer alike: a window its caller bounded wrongly is the caller's to correct (422), a world whose
records state no roads is not found (404), roads the traffic cannot drive or a world too large for
it are a conflict naming the compiler's or the fleet rule's reason (409), and a worker that stopped
or did not finish in time is the server's (503), which a page tries again.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Final

from exulanica.world.traffic_episodes import TrafficRefused
from exulanica.world.traffic_host import TrafficWorkerUnavailable

__all__ = ["REQUEST_REFUSALS", "refusal_status", "vehicles_encoded"]

#: A window a request did not bound: the roads module's refusals, a caller's to correct.
REQUEST_REFUSALS: Final = frozenset({"traffic_second_out_of_range", "traffic_window_too_long"})


def refusal_status(error: TrafficRefused) -> int:
    """The HTTP status a traffic refusal is answered with."""
    if isinstance(error, TrafficWorkerUnavailable):
        return 503
    if error.code == "roads_not_stated":
        return 404
    return 422 if error.code in REQUEST_REFUSALS else 409


def vehicles_encoded(answer: Mapping[str, Any]) -> bytes:
    """The answer as JSON, a vehicle at a time, so a request answered beside this one waits for at
    most one vehicle's seconds rather than the whole window's."""

    def encode(value: object) -> bytes:
        return json.dumps(
            value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
        ).encode()

    rest = encode({key: value for key, value in answer.items() if key != "vehicles"})
    vehicles = b",".join(encode(row) for row in answer["vehicles"])
    return b'{"vehicles":[' + vehicles + b"]," + rest[1:]
