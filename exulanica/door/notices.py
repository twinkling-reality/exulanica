"""What one process tells itself about the door, so waiting is not polling a database.

Two things wait on the channel. A held poll waits for something to send its bridge, and the
decision host's asker waits for a bridge's answer. Both find out from the database in the end,
because the playback worker may run in another process than the request that answered. Within one
process they need not wait for their next read: the asker that writes an ask, and the route that
stores an answer, say so here, and whoever waits on it wakes at once. A notice is a hint to read
sooner and never a fact: every decision is taken from what the database holds.

:class:`HeldPolls` keeps one held poll per grant and shares this process's held polls fairly: a
ceiling on all of them, a share for each workspace and a share for each bridge, so one workspace or
one bridge cannot take every place. When the process or a bridge is full, a new poll from a
workspace holding fewer takes the place of the oldest poll of the workspace holding the most, whose
bridge is answered at once with nothing to send and polls again; so the places are shared evenly
among the workspaces that want them, and only a workspace that would hold as many as everyone else
is answered ``door_busy``. One process serves at most half its places' worth of workspaces through
one bridge; more need more processes (the deployment guide, 5.4). A bridge that polls
again while its last poll is still held ends that one with nothing to send, so a dropped connection
never leaves two polls reading for one grant.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

__all__ = [
    "ANSWERS_REMEMBERED",
    "GRANTS_REMEMBERED",
    "HELD_POLLS_MAXIMUM",
    "HELD_POLLS_PER_WORKSPACE",
    "HELLOS_PER_MINUTE",
    "HeldPolls",
    "Hellos",
    "Notices",
]

#: The most polls one process holds open at once, across every grant. Each is a socket and a
#: place in the streams admission class, never a thread or a connection; the ceiling is half the
#: class's default 128, so progress streams keep their room.
HELD_POLLS_MAXIMUM: Final = 64
#: The most one workspace holds: half its default share of eight streams, so its own progress
#: streams keep room, and sixteen workspaces before the process's ceiling is reached.
HELD_POLLS_PER_WORKSPACE: Final = 4
#: Hellos one grant may say in a minute in one process. A bridge says hello when it starts and after
#: a refusal that asks it to; more than this is an adapter restarting in a loop, which costs a
#: mapping check and a write each time.
HELLOS_PER_MINUTE: Final = 6
#: How many answered requests a process remembers for waiting askers. An answer stored for an ask
#: that another process is waiting on wakes nobody here; the oldest is forgotten first, so the set
#: never grows with the number of answers.
ANSWERS_REMEMBERED: Final = 4096
#: How many grants' ask counts a process remembers. The least recently asked is forgotten first;
#: a poll that finds its grant's count changed only reads the database once more than it needed.
GRANTS_REMEMBERED: Final = 4096


@dataclass
class Notices:
    """Counts of asks written and the requests answered, as this process has seen them."""

    _condition: threading.Condition = field(default_factory=threading.Condition)
    _asks: OrderedDict[uuid.UUID, int] = field(default_factory=OrderedDict)
    _answered: OrderedDict[uuid.UUID, None] = field(default_factory=OrderedDict)

    def asked(self, grant_id: uuid.UUID) -> None:
        with self._condition:
            self._asks[grant_id] = self._asks.get(grant_id, 0) + 1
            self._asks.move_to_end(grant_id)
            while len(self._asks) > GRANTS_REMEMBERED:
                self._asks.popitem(last=False)
            self._condition.notify_all()

    def asks(self, grant_id: uuid.UUID) -> int:
        """How many asks this process has written for ``grant_id``: a number to compare, never a
        position in the channel."""
        with self._condition:
            return self._asks.get(grant_id, 0)

    def answered(self, request_id: uuid.UUID) -> None:
        with self._condition:
            self._answered[request_id] = None
            self._answered.move_to_end(request_id)
            while len(self._answered) > ANSWERS_REMEMBERED:
                self._answered.popitem(last=False)
            self._condition.notify_all()

    def wait_for_answer(self, request_id: uuid.UUID, timeout: float) -> bool:
        """Wait up to ``timeout`` seconds for this process to store an answer to ``request_id``."""
        with self._condition:
            return self._condition.wait_for(
                lambda: request_id in self._answered, timeout=max(0.0, timeout)
            )

    def forget(self, request_id: uuid.UUID) -> None:
        with self._condition:
            self._answered.pop(request_id, None)


@dataclass
class HeldPolls:
    """One held poll per grant; at most :data:`HELD_POLLS_MAXIMUM` in this process, at most
    ``per_workspace`` for one workspace, and at most half of the ceiling for one bridge, so a second
    bridge always finds room; places shared evenly among workspaces when either ceiling is
    reached."""

    maximum: int = HELD_POLLS_MAXIMUM
    per_workspace: int = HELD_POLLS_PER_WORKSPACE
    _lock: threading.Lock = field(default_factory=threading.Lock)
    #: grant -> (token, workspace, bridge) of the poll it holds.
    _held: dict[uuid.UUID, tuple[uuid.UUID, uuid.UUID, str]] = field(default_factory=dict)

    @property
    def per_bridge(self) -> int:
        return max(1, self.maximum // 2)

    def hold(self, grant_id: uuid.UUID, workspace_id: uuid.UUID, bridge: str) -> uuid.UUID | None:
        """A token for a new poll of ``grant_id``, which ends any poll it already held; None when
        its workspace already holds its share, or when the bridge or the process is full and no
        workspace there holds two more polls than this one would."""
        with self._lock:
            if grant_id not in self._held:
                if sum(1 for _t, w, _b in self._held.values() if w == workspace_id) >= (
                    self.per_workspace
                ):
                    return None
                bridge_full = (
                    sum(1 for _t, _w, b in self._held.values() if b == bridge) >= self.per_bridge
                )
                if bridge_full or len(self._held) >= self.maximum:
                    taken = self._fair_place(workspace_id, bridge if bridge_full else None)
                    if taken is None:
                        return None
                    # The poll whose place is taken no longer holds it, and answers at once.
                    del self._held[taken]
            token = uuid.uuid4()
            self._held[grant_id] = (token, workspace_id, bridge)
            return token

    def _fair_place(self, workspace_id: uuid.UUID, bridge: str | None) -> uuid.UUID | None:
        """The grant whose place a new poll of ``workspace_id`` takes, among the polls of ``bridge``
        or of the whole process: the oldest poll of the workspace holding the most there, if it
        holds at least two more than ``workspace_id`` does; else None."""
        counts: dict[uuid.UUID, int] = {}
        oldest: dict[uuid.UUID, uuid.UUID] = {}
        for held_grant, (_token, held_workspace, held_bridge) in self._held.items():
            if bridge is not None and held_bridge != bridge:
                continue
            counts[held_workspace] = counts.get(held_workspace, 0) + 1
            oldest.setdefault(held_workspace, held_grant)
        if not counts:
            return None
        most = max(counts, key=lambda workspace: counts[workspace])
        if counts[most] < counts.get(workspace_id, 0) + 2:
            return None
        return oldest[most]

    def holds(self, grant_id: uuid.UUID, token: uuid.UUID) -> bool:
        """Whether the poll with ``token`` is still the one held for ``grant_id``."""
        with self._lock:
            held = self._held.get(grant_id)
            return held is not None and held[0] == token

    def release(self, grant_id: uuid.UUID, token: uuid.UUID) -> None:
        with self._lock:
            held = self._held.get(grant_id)
            if held is not None and held[0] == token:
                del self._held[grant_id]


@dataclass
class Hellos:
    """How many hellos each grant said in the last minute in this process, and whether one more is
    admitted: at most :data:`HELLOS_PER_MINUTE`. Grants that said none for a minute are forgotten,
    so the count never grows with the number of grants."""

    per_minute: int = HELLOS_PER_MINUTE
    monotonic: Callable[[], float] = time.monotonic
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _said: dict[uuid.UUID, deque[float]] = field(default_factory=dict)

    def admit(self, grant_id: uuid.UUID) -> bool:
        now = self.monotonic()
        with self._lock:
            for stale in [
                key for key, said in self._said.items() if not said or now - said[-1] >= 60.0
            ]:
                del self._said[stale]
            said = self._said.setdefault(grant_id, deque())
            while said and now - said[0] >= 60.0:
                said.popleft()
            if len(said) >= self.per_minute:
                return False
            said.append(now)
            return True
