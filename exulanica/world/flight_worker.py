"""The flight's episodes, computed in a worker process and kept for the windows cut from them.

The flight's step is pure Python, and Python runs one thread at a time: computed on a request's
thread, a window holds the interpreter's lock, and every other request the server is answering
waits for it. Measured on a release server, one cold window of 24 flyers (about half a second)
slowed the slowest health answer beside it from at most 9 ms to 146 to 222 ms
(docs/evaluation/2026-09-25-flight-bounds-v2.json). So a server computes flight here instead:

- **one worker process**, started by the first read (the standard library's process pool, one
  process, spawned), computes whole episodes
  (:func:`exulanica.movement.flight_episodes.compute_episode`) and hands them back packed; a
  request waiting for one holds no lock. The worker ends itself when the server's process is gone,
  however that ended;
- **episodes wait here, not in the pool**: the pool is handed one episode at a time, so which
  episode goes next is decided when the worker is free. An episode a read is waiting for goes
  before one asked for ahead of need, and among either the one asked for first goes first. At most
  :data:`QUEUE_LIMIT` episodes wait; one asked for ahead of need is not queued past it, and one a
  read needs pushes out the oldest of those, or, with none to push out, is refused;
- **an edit replaces an input**: a read names its version's edit sequence, and a later one for the
  same world version supersedes every earlier input of it. Episodes of a superseded input still
  waiting are dropped, reads waiting on them refused, its kept episodes let go, and one being
  computed when it was superseded is handed to whoever waits for it and not kept;
- **episodes are kept** by the input digest and episode, the :data:`EPISODE_LIMIT` most recently
  used; they are computed bytes keyed by content and grant nothing, so a request still reads its
  world through the database, as the route does, before any episode is cut for it;
- **the next episode is asked for ahead of need** whenever a window is served, so a page reading
  ahead of its clock waits only for its first read;
- **one deadline a read**: a read is refused as ``flight_worker_unavailable`` when the episodes it
  needs are not all done :data:`WAIT_SECONDS` after it began, however many it spans; a worker that
  dies refuses the reads waiting on it the same way, and the next read starts a new process.

A request's own work is its window cut from at most two packed episodes: at most
``max_steps_per_request`` steps of each flyer's samples, copied as integers.

**The worker is the episode worker's** (:mod:`exulanica.world.episode_worker`): this module binds
it to the flight, its episode length, its wire form, its job, its window and its refusal, and
keeps the names a caller reads.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import Executor
from typing import Any, Final

from exulanica.movement.flight import FlightInput, FlightRefused, check_request
from exulanica.movement.flight_episodes import (
    EPISODE,
    PackedEpisode,
    compute_episode,
    watch_parent,
    window_of,
    wire,
    worker_report,
)
from exulanica.world.episode_worker import (
    EPISODE_LIMIT,
    QUEUE_LIMIT,
    WAIT_SECONDS,
    EpisodeWorker,
    Key,
    Line,
    worker_pool,
)

__all__ = [
    "EPISODE_LIMIT",
    "QUEUE_LIMIT",
    "WAIT_SECONDS",
    "FlightEpisodes",
    "FlightWorkerUnavailable",
    "Key",
    "Line",
    "process_pool",
]


class FlightWorkerUnavailable(FlightRefused):
    """The worker process died, or did not finish an episode in time: a server failure, retried."""

    def __init__(self, detail: str) -> None:
        super().__init__("flight_worker_unavailable", detail)

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.detail,))


def process_pool() -> Executor:
    """One spawned worker process: nothing of the server's own state is inherited by it, and it
    watches for the server's process to be gone."""
    return worker_pool(watch_parent)


class _Flight:
    """The flight, as the episode worker reads a module."""

    subject: Final = "flight"
    episode_steps: Final = EPISODE
    refusal: Final = FlightWorkerUnavailable
    #: The flight's own job, handed to the worker process as it is.
    compute: Final = staticmethod(compute_episode)

    def check(self, from_step: int, steps: int) -> None:
        check_request(from_step, steps)

    def digest(self, value: FlightInput) -> str:
        return value.sha256

    def line(self, value: FlightInput) -> Line:
        return (value.world_id, value.version_id)

    def wire(self, value: FlightInput) -> dict[str, Any]:
        return wire(value)

    def window(
        self,
        value: FlightInput,
        episodes: dict[int, PackedEpisode],
        from_step: int,
        steps: int,
    ) -> dict[str, Any]:
        return window_of(value, episodes, from_step, steps)


class FlightEpisodes(EpisodeWorker[FlightInput, PackedEpisode]):
    """Episodes one worker computes, kept and cut into windows; safe to share between threads."""

    def __init__(
        self,
        executor: Callable[[], Executor] = process_pool,
        *,
        limit: int = EPISODE_LIMIT,
        queue_limit: int = QUEUE_LIMIT,
        wait_seconds: float = WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            _Flight(),
            executor,
            limit=limit,
            queue_limit=queue_limit,
            wait_seconds=wait_seconds,
            clock=clock,
        )

    def report(self) -> dict[str, Any]:
        """:func:`exulanica.movement.flight_episodes.worker_report`, answered by the worker."""
        return self.ask(worker_report)
