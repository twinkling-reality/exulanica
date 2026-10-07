"""An agent's body in a world: its grant, the turns it gets, and what happened to it.

A world's owner lets an agent in by issuing a grant and handing over its key. :meth:`Body.connect`
says hello on that grant's channel with this library's version, the agents' mapping file and what
the agent declares about itself (its name, its maker and, if it says, its mind), all shown only on
its card. From then on one background thread long-polls the door, as every adapter at the door
does, and keeps what it reads: the open turns, what became of each answer, and the permission.

Turns are answered from any thread, as fast as the agent's mind allows, within each turn's time.
Nothing waits on the agent: a world minute passes whether or not it answers, and a missed turn is
decided by the world's own routine.

The key is read from ``EXULANICA_AGENT_KEY`` unless given, and is never printed, logged or kept
anywhere but the one header of each request (:mod:`exulanica_agent.transport`).
"""

from __future__ import annotations

import collections
import json
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from importlib import resources
from typing import Any, Final

from exulanica_agent._version import VERSION
from exulanica_agent.happenings import (
    Happening,
    from_ended,
    from_grant,
    from_outcome,
    permission_summary,
)
from exulanica_agent.rules import world_rules
from exulanica_agent.transport import AgentError, Door, DoorRefusal, Opener
from exulanica_agent.turns import Answer, FrameRefused, Turn, turn_from_frame

__all__ = [
    "ENV_KEY",
    "ENV_MAKER",
    "ENV_MIND",
    "ENV_NAME",
    "ENV_URL",
    "MAPPING_FILE",
    "READS",
    "Body",
    "HelloRefused",
    "mapping",
]

ENV_URL: Final = "EXULANICA_URL"
ENV_KEY: Final = "EXULANICA_AGENT_KEY"
ENV_NAME: Final = "EXULANICA_AGENT_NAME"
ENV_MAKER: Final = "EXULANICA_AGENT_MAKER"
ENV_MIND: Final = "EXULANICA_AGENT_MIND"
#: The agents' mapping file, shipped inside this package: a deployment pins its digest.
MAPPING_FILE: Final = "outside-agents.v1.json"
#: What this adapter reads from the agent it carries; the mapping accounts for each.
READS: Final = ("action", "line", "declared name", "declared maker", "declared mind")
#: How many happenings a body keeps for anyone who asks what happened lately.
HAPPENINGS_KEPT: Final = 50
#: The longest a body waits before asking the door again after it could not be reached.
_BACKOFF_SECONDS: Final = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
#: How long a frames request may take beyond the door's hold.
_POLL_SLACK_SECONDS: Final = 10.0
_DECLARED_MAXIMA: Final = {"name": 40, "maker": 40, "mind": 60}
#: Words for the refusals an answer can meet, keyed by the door's codes.
_ANSWER_WORDS: Final = {
    "answer_too_late": "This turn is over: the world's own routine decided it. Wait for the next.",
    "unknown_reference": "This turn is not open to you: it is over or unknown. Wait for the next.",
    "answer_already_given": "This turn was already answered.",
    "answer_not_for_this_request": "That answer names another turn.",
    "answer_not_offered": "That is not one of the offered actions.",
    "line_not_offered": "This action says nothing: give no line.",
    "line_missing": "This action says something: give its line.",
    "grant_ended": "Your permission in this world has ended.",
    "unauthenticated": "The world does not accept this agent's key any more.",
}
#: Words for the refusals a hello can meet, so a developer reads what to do.
_HELLO_WORDS: Final = {
    "unauthenticated": "the world does not accept this agent key: check it, or ask the world's "
    "owner for a new one",
    "adapter_version_not_admitted": "this world's door does not admit this version of "
    "exulanica-agent: update it, or ask the world's operator which version it admits",
    "mapping_not_admitted": "this world's door admits another version of the agents' mapping: "
    "update exulanica-agent",
    "mapping_refused": "this world's door refused the agents' mapping",
    "declared_refused": "the world refused the agent's declared name, maker or mind",
    "grant_ended": "the permission this key opens has ended: ask the world's owner for a new one",
    "too_many_hellos": "this agent said hello too often: wait a minute and start it again",
    "bridge_not_admitted": "this world's door no longer admits outside agents",
}


#: Hello refusals a body says hello again after, once the door's wait has passed.
_HELLO_AGAIN: Final = frozenset({"too_many_hellos", "door_busy", "500", "502", "503", "504"})


class HelloRefused(AgentError):
    """The door refused a hello: its ``code``, words saying what to do, and how long to wait."""

    def __init__(self, code: str, words: str, retry_after_s: float | None) -> None:
        super().__init__(words)
        self.code = code
        self.retry_after_s = retry_after_s


def mapping() -> dict[str, Any]:
    """The agents' mapping file this library presents at hello, as a fresh object."""
    text = resources.files("exulanica_agent").joinpath(MAPPING_FILE).read_text(encoding="utf-8")
    return json.loads(text)


def _declared(name: str | None, maker: str | None, mind: str | None) -> dict[str, str]:
    declared = {"name": name, "maker": maker, "mind": mind}
    if not name or not maker:
        raise AgentError(
            "give the agent a name and a maker (shown on its card, as its own words): "
            f"name=, maker= or {ENV_NAME} and {ENV_MAKER}"
        )
    document = {}
    for key, value in declared.items():
        if value is None:
            continue
        if not isinstance(value, str) or not 1 <= len(value) <= _DECLARED_MAXIMA[key]:
            raise AgentError(f"a declared {key} is 1 to {_DECLARED_MAXIMA[key]} characters")
        document[key] = value
    return document


class Body:
    """One grant's channel, held for an agent: hello, the poll, its turns and what happened."""

    def __init__(
        self,
        door: Door,
        *,
        name: str,
        maker: str,
        mind: str | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._door = door
        self._declared = _declared(name, maker, mind)
        self._mapping = mapping()
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Condition()
        self._closing = threading.Event()
        self._thread: threading.Thread | None = None
        self._cursor: str | None = None
        self._hold_seconds = 15
        self._summary: dict[str, Any] | None = None
        self._ended: str | None = None
        self._open: dict[str, Turn] = {}
        self._given: set[str] = set()
        self._answered: dict[str, tuple[str, str | None]] = {}
        self._known: dict[str, Turn] = {}
        self._recent: collections.deque[Happening] = collections.deque(maxlen=HAPPENINGS_KEPT)
        self._unread: list[Happening] = []
        self._last_deadline_ms: int | None = None
        self._last_instruction: str | None = None
        self._line_maxima: set[int] = set()
        self._entered_at: float | None = None

    def __repr__(self) -> str:
        return f"Body(url={self._door.url!r}, name={self._declared['name']!r})"

    # -- connecting --------------------------------------------------------------------------

    @classmethod
    def connect(
        cls,
        url: str | None = None,
        key: str | None = None,
        *,
        name: str | None = None,
        maker: str | None = None,
        mind: str | None = None,
        opener: Opener | None = None,
        start: bool = True,
    ) -> Body:
        """A body on the grant ``key`` opens in the world at ``url``, said hello and polling.

        Each argument left out is read from the environment: ``EXULANICA_URL``,
        ``EXULANICA_AGENT_KEY``, ``EXULANICA_AGENT_NAME``, ``EXULANICA_AGENT_MAKER`` and
        ``EXULANICA_AGENT_MIND``.
        """
        url = url or os.environ.get(ENV_URL)
        key = key or os.environ.get(ENV_KEY)
        if not url:
            raise AgentError(f"the world's address is needed: url= or {ENV_URL}")
        if not key:
            raise AgentError(f"the agent's key is needed: key= or {ENV_KEY}")
        body = cls(
            Door(url, key, opener=opener),
            name=name or os.environ.get(ENV_NAME) or "",
            maker=maker or os.environ.get(ENV_MAKER) or "",
            mind=mind or os.environ.get(ENV_MIND) or None,
        )
        if start:
            body.start()
        return body

    def start(self) -> None:
        """Say hello, then start the poll; a hello the door refuses is raised with its words."""
        self._hello()
        thread = threading.Thread(target=self._poll, name="exulanica-agent-door", daemon=True)
        self._thread = thread
        thread.start()

    def close(self, wait_seconds: float = 0.0) -> None:
        """Stop polling; the current poll ends within the door's hold. With ``wait_seconds``,
        wait up to that long for it to end."""
        self._closing.set()
        with self._lock:
            self._lock.notify_all()
        thread = self._thread
        if wait_seconds > 0 and thread is not None and thread is not threading.current_thread():
            thread.join(wait_seconds)

    def __enter__(self) -> Body:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def _hello(self) -> None:
        body = {
            "adapter_version": VERSION,
            "mapping": self._mapping,
            "reads": list(READS),
            "declared": dict(self._declared),
        }
        try:
            answer = self._door.call("POST", "/door/channel/hello", body)
        except DoorRefusal as refusal:
            words = _HELLO_WORDS.get(refusal.code, "the world's door refused this agent")
            detail = f": {refusal.detail}" if refusal.detail else ""
            raise HelloRefused(
                refusal.code or str(refusal.status),
                f"{words} ({refusal.code or refusal.status}{detail})",
                refusal.retry_after_s,
            ) from refusal
        cursor = answer.get("cursor")
        grant = answer.get("grant")
        if not isinstance(cursor, str) or not isinstance(grant, Mapping):
            raise AgentError("the door's hello answer names no cursor or grant")
        hold = answer.get("hold_seconds")
        with self._lock:
            self._cursor = cursor
            if type(hold) is int and 1 <= hold <= 60:
                self._hold_seconds = hold
            scope = grant.get("scope")
            if isinstance(scope, Mapping):
                self._summary = permission_summary(scope, grant.get("expires_at"))

    # -- reading what the door says ----------------------------------------------------------

    def _poll(self) -> None:
        failures = 0
        while not self._closing.is_set():
            with self._lock:
                cursor = self._cursor
                hold = self._hold_seconds
            try:
                answer = self._door.call(
                    "GET",
                    "/door/channel/frames",
                    query=None if cursor is None else {"after": cursor},
                    timeout=hold + _POLL_SLACK_SECONDS,
                )
            except DoorRefusal as refusal:
                if not self._after_refusal(refusal):
                    return
                continue
            except AgentError:
                failures += 1
                self._pause(_BACKOFF_SECONDS[min(failures, len(_BACKOFF_SECONDS)) - 1])
                continue
            failures = 0
            self._take(answer)

    def _pause(self, seconds: float) -> None:
        self._closing.wait(seconds)

    def _after_refusal(self, refusal: DoorRefusal) -> bool:
        """Act on a refused poll; False once there is nothing more to read."""
        if refusal.status == 401 or refusal.code in ("grant_ended", "bridge_not_admitted"):
            self._end(refusal.code or "key_not_accepted")
            return False
        if refusal.code in ("hello_first", "invalid_cursor"):
            try:
                self._hello()
            except HelloRefused as again:
                if again.code not in _HELLO_AGAIN:
                    self._end(again.code)
                    return False
                self._pause(again.retry_after_s or 60.0)
            except AgentError:
                self._pause(_BACKOFF_SECONDS[-1])
            return True
        self._pause(refusal.retry_after_s or 1.0)
        return True

    def _end(self, reason: str) -> None:
        with self._lock:
            if self._ended is None:
                self._ended = reason
                if self._summary is not None:
                    self._summary = {**self._summary, "ended": reason}
            self._open.clear()
            self._known.clear()
            self._lock.notify_all()

    def _take(self, answer: Mapping[str, Any]) -> None:
        frames = answer.get("frames")
        cursor = answer.get("cursor")
        now = self._clock()
        with self._lock:
            for frame in frames if isinstance(frames, list) else []:
                if isinstance(frame, Mapping):
                    self._frame(frame, now)
            if isinstance(cursor, str):
                self._cursor = cursor
            self._lock.notify_all()

    def _note(self, happening: Happening) -> None:
        self._recent.append(happening)
        self._unread.append(happening)
        del self._unread[:-HAPPENINGS_KEPT]

    def _frame(self, frame: Mapping[str, Any], now: float) -> None:
        kind = frame.get("kind")
        if kind == "asked":
            try:
                turn = turn_from_frame(
                    frame, received_at=now, answer=self._answer, clock=self._clock
                )
            except FrameRefused as refused:
                self._note(Happening("turn_unreadable", f"A turn could not be read: {refused}."))
                return
            self._open[turn.turn] = turn
            self._known[turn.turn] = turn
            self._last_deadline_ms = turn.deadline_ms
            self._last_instruction = turn.instruction
            self._line_maxima.update(
                option.line_characters_maximum
                for option in turn.options
                if option.line_characters_maximum is not None
            )
        elif kind == "outcome":
            request_id = str(frame.get("request_id"))
            turn = self._open.pop(request_id, None) or self._known.get(request_id)
            self._note(
                from_outcome(
                    frame,
                    minute=None if turn is None else turn.minute,
                    thing=None if turn is None else turn.thing,
                    answered=self._answered.get(request_id),
                )
            )
            self._known.pop(request_id, None)
            self._answered.pop(request_id, None)
            self._given.discard(request_id)
        elif kind == "grant":
            scope = frame.get("scope")
            if isinstance(scope, Mapping):
                expires = scope.get("expires_at")
                summary = permission_summary(scope, expires if isinstance(expires, str) else None)
                if self._ended is not None:
                    summary["ended"] = self._ended
                self._summary = summary
                self._note(from_grant(scope, summary["ends_at"]))
        elif kind == "grant_ended":
            reason = frame.get("reason")
            self._note(from_ended(frame))
            self._ended = reason if isinstance(reason, str) else "ended"
            if self._summary is not None:
                self._summary = {**self._summary, "ended": self._ended}
            self._open.clear()

    # -- what a mind reads ---------------------------------------------------------------------

    @property
    def permission(self) -> dict[str, Any] | None:
        """What the agent may do here, as the door last said: its things, how many bodies of its
        own, whether they may speak, when it ends, and whether it has ended."""
        with self._lock:
            return None if self._summary is None else dict(self._summary)

    @property
    def declared(self) -> dict[str, str]:
        """What the agent declared about itself at hello: its name, its maker, and its mind if it
        said; shown only on its card."""
        return dict(self._declared)

    @property
    def ended(self) -> str | None:
        with self._lock:
            return self._ended

    def rules(self) -> str:
        """The world's rules for this agent, in words (:mod:`exulanica_agent.rules`)."""
        with self._lock:
            return world_rules(
                self._summary,
                deadline_ms=self._last_deadline_ms,
                line_maxima=sorted(self._line_maxima),
                instruction=self._last_instruction,
            )

    def turn(self, handle: str) -> Turn | None:
        """The open turn ``handle`` names, or None once the door said it is over, or for a handle
        this body never received. The door decides whether an answer is still in time."""
        with self._lock:
            return self._open.get(handle)

    def _waiting(self, *, fresh: bool) -> list[Turn]:
        turns = [
            turn
            for handle, turn in self._open.items()
            if turn.seconds_left > 0
            and handle not in self._answered
            and not (fresh and handle in self._given)
        ]
        return sorted(turns, key=lambda turn: (turn.seconds_left, turn.turn))

    def next_turn(self, wait_seconds: float = 15.0, *, fresh: bool = False) -> Turn | None:
        """The open, unanswered turn with the least time left, waiting up to ``wait_seconds`` for
        one; None when none came or the permission ended. With ``fresh``, a turn already handed
        out is not handed out again."""
        ends = self._clock() + max(0.0, wait_seconds)
        with self._lock:
            while True:
                waiting = self._waiting(fresh=fresh)
                if waiting:
                    self._given.add(waiting[0].turn)
                    return waiting[0]
                left = ends - self._clock()
                if left <= 0 or self._ended is not None or self._closing.is_set():
                    return None
                self._lock.wait(min(left, 1.0))

    def waiting(self) -> int:
        """How many open turns wait for an answer."""
        with self._lock:
            return len(self._waiting(fresh=False))

    def turns(self) -> Iterator[Turn]:
        """Every turn as it comes, each once, the least time left first, until the permission ends
        or the body is closed."""
        while True:
            turn = self.next_turn(self._hold_seconds, fresh=True)
            if turn is not None:
                yield turn
            elif self.ended is not None or self._closing.is_set():
                return

    def happened(self) -> list[Happening]:
        """What happened since this was last asked, oldest first."""
        with self._lock:
            unread, self._unread = self._unread, []
            return unread

    def recent(self) -> list[Happening]:
        """The last :data:`HAPPENINGS_KEPT` happenings, oldest first, whether read or not."""
        with self._lock:
            return list(self._recent)

    # -- acting ----------------------------------------------------------------------------------

    def _answer(self, turn: Turn, action: str, line: str | None) -> Answer:
        body: dict[str, Any] = {
            "request_id": turn.turn,
            "request_sha256": turn.request_sha256,
            "label": action,
        }
        if line is not None:
            body["line"] = line
        with self._lock:
            # Kept before sending: the host may record the turn, and its outcome arrive, before the
            # door's answer to this request returns, and the outcome must find what was answered.
            earlier = self._answered.get(turn.turn)
            self._answered[turn.turn] = (action, line)
        try:
            self._door.call("POST", "/door/channel/answers", body)
        except DoorRefusal as refusal:
            code = refusal.code or str(refusal.status)
            with self._lock:
                self._unanswer(turn.turn, earlier)
                if code in ("answer_too_late", "unknown_reference", "answer_already_given"):
                    self._open.pop(turn.turn, None)
            return Answer(False, code, _ANSWER_WORDS.get(code, refusal.detail or code))
        except AgentError as error:
            with self._lock:
                self._unanswer(turn.turn, earlier)
            return Answer(False, "no_connection", str(error))
        with self._lock:
            self._lock.notify_all()
        return Answer(True)

    def _unanswer(self, handle: str, earlier: tuple[str, str | None] | None) -> None:
        """Forget an answer the door did not store, keeping any earlier one it did."""
        if handle not in self._open:
            return
        if earlier is None:
            self._answered.pop(handle, None)
        else:
            self._answered[handle] = earlier

    def enter(self, look: str | None = None) -> Answer:
        """Bring the agent's own body in through the world's gate, when its permission allows a
        visitor: it arrives at the next world minute. At most once a minute."""
        now = self._clock()
        with self._lock:
            if self._entered_at is not None and now - self._entered_at < 60:
                return Answer(False, "too_soon", "Your body is already on its way. Wait a minute.")
            summary = self._summary
        if summary is not None and not summary.get("visitors_maximum"):
            return Answer(
                False,
                "no_visitors_allowed",
                "Your permission lets you decide for things here, not bring a body of your own.",
            )
        looks = [entry["look_key"] for entry in self._mapping["visitors"][0]["looks"]]
        if look is not None and look not in looks:
            return Answer(False, "unknown_look", "Choose one of: " + "; ".join(looks))
        body = {
            "arrival_id": str(uuid.uuid4()),
            "game_type": self._mapping["visitors"][0]["game_type"],
            "look_key": look or looks[0],
            "carried": [],
        }
        try:
            self._door.call("POST", "/door/channel/arrivals", body)
        except DoorRefusal as refusal:
            if refusal.status in (404, 405) and not refusal.code:
                return Answer(
                    False, "not_open_to_visitors", "This world's door does not take visitors yet."
                )
            return Answer(False, refusal.code or str(refusal.status), refusal.detail)
        except AgentError as error:
            return Answer(False, "no_connection", str(error))
        with self._lock:
            self._entered_at = now
        return Answer(True, words="Your body is on its way: it arrives at the next world minute.")
