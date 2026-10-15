"""The pictures a picture search found, held in this process for the person who asked.

A source's catalog entry may pass a picture's address and words (``passed``): served to the person
who asked, so their browser shows each picture from its own website, and never kept. This is the
only place they are held: in this process's memory, by workspace and reference request, for at
most :data:`HELD_SECONDS`, and for at most :data:`MAX_HELD_REQUESTS` requests at once (the oldest
goes first). Nothing here writes to a database, a store or a log, and nothing outlives the
process: a restart, or a second API process that did not play the job, holds none, and the route
answers so.

Only the request's own requester reads them: the route reads the request as its requester first,
and only then asks this holding by the request's id. A request that is stopped forgets them.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final

from exulanica.references.adapters.base import MAX_WEB_PICTURES, WebPicture

__all__ = [
    "HELD_SECONDS",
    "MAX_HELD_REQUESTS",
    "HeldPictures",
    "PictureHolding",
    "held_pictures",
]

#: How long a search's pictures are held: long enough to look and pick, short enough that they are
#: gone well within the hour.
HELD_SECONDS: Final = 30 * 60
#: The most requests whose pictures are held at once in one process.
MAX_HELD_REQUESTS: Final = 256


@dataclass(frozen=True, slots=True)
class HeldPictures:
    """One request's pictures, and how many whole seconds they are still held."""

    pictures: tuple[WebPicture, ...]
    seconds_left: int

    def __repr__(self) -> str:
        return f"HeldPictures(pictures={len(self.pictures)}, seconds_left={self.seconds_left})"


class PictureHolding:
    """Pictures by (workspace, request), each held until its time is up. Safe across threads: the
    reference worker's thread holds, the routes read and forget."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        seconds: int = HELD_SECONDS,
        capacity: int = MAX_HELD_REQUESTS,
    ) -> None:
        if seconds <= 0 or capacity <= 0:
            raise ValueError("a holding holds something for some time")
        self._clock = clock
        self._seconds = seconds
        self._capacity = capacity
        self._lock = threading.Lock()
        self._held: OrderedDict[tuple[uuid.UUID, uuid.UUID], tuple[float, tuple[WebPicture, ...]]]
        self._held = OrderedDict()

    def hold(
        self, workspace_id: uuid.UUID, reference_id: uuid.UUID, pictures: Sequence[WebPicture]
    ) -> None:
        """Hold ``pictures`` for the request from now, in place of any it held."""
        pictures = tuple(pictures)
        if len(pictures) > MAX_WEB_PICTURES or not all(
            isinstance(picture, WebPicture) for picture in pictures
        ):
            raise ValueError(f"a request holds at most {MAX_WEB_PICTURES} web pictures")
        key = (workspace_id, reference_id)
        with self._lock:
            now = self._clock()
            self._drop_expired(now)
            self._held.pop(key, None)
            self._held[key] = (now + self._seconds, pictures)
            while len(self._held) > self._capacity:
                self._held.popitem(last=False)

    def read(self, workspace_id: uuid.UUID, reference_id: uuid.UUID) -> HeldPictures | None:
        """The request's pictures while they are held, or None."""
        with self._lock:
            now = self._clock()
            self._drop_expired(now)
            found = self._held.get((workspace_id, reference_id))
        if found is None:
            return None
        until, pictures = found
        return HeldPictures(pictures=pictures, seconds_left=max(0, int(until - now)))

    def forget(self, workspace_id: uuid.UUID, reference_id: uuid.UUID) -> None:
        """Let the request's pictures go now."""
        with self._lock:
            self._held.pop((workspace_id, reference_id), None)

    def __len__(self) -> int:
        with self._lock:
            self._drop_expired(self._clock())
            return len(self._held)

    def _drop_expired(self, now: float) -> None:
        for key in [key for key, (until, _pictures) in self._held.items() if until <= now]:
            del self._held[key]


_PROCESS_HOLDING: Final = PictureHolding()


def held_pictures() -> PictureHolding:
    """This process's holding: the one the worker holds into and the routes read."""
    return _PROCESS_HOLDING
