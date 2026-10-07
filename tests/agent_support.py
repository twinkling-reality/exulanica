"""A stand-in for a world's door and its asks, for the outside-agent library's tests.

The library in ``bridges/agents`` is outside the product and is loaded by its path. The fake door
answers the channel routes in the shapes the door contract states (hello, frames by
long-poll with an opaque cursor, answers, arrivals) and records every request. Asked frames are
built with the product's own person role, so the messages and the function a turn hands a mind are
the ones a model receives, not a copy of them.
"""

from __future__ import annotations

import http.server
import importlib
import io
import json
import sys
import threading
import urllib.error
import urllib.parse
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AGENTS_ROOT = ROOT / "bridges" / "agents"
PACKAGE = AGENTS_ROOT / "exulanica_agent"
KEY = "test-agent-key-" + "k" * 28
GRANT_ID = "6d2f9c2e-6c1b-4c55-9d7a-8e6f0a1b2c3d"

if str(AGENTS_ROOT) not in sys.path:
    sys.path.insert(0, str(AGENTS_ROOT))
# Loaded once its folder is on the path: the library is outside the product, never installed here.
agent = importlib.import_module("exulanica_agent")
transport = importlib.import_module("exulanica_agent.transport")
facade = importlib.import_module("exulanica_agent.facade")
AgentError = agent.AgentError
Body = agent.Body
DoorRefusal = agent.DoorRefusal
Door = transport.Door


def grant_view(*, things: list[str] | None = None, visitors: int = 0) -> dict[str, Any]:
    """A grant as the door's views state it (``exulanica/door/grants.py``, ``Grant.view``)."""
    return {
        "grant_id": GRANT_ID,
        "world_id": "world-1",
        "bridge": "agents",
        "grant_seq": 1,
        "state": "active",
        "scope": {
            "visitors_maximum": visitors,
            "kinds": ["agent"] if visitors else [],
            "things": sorted(things or []),
            "gate": None,
            "may_carry_in": False,
            "may_carry_out": False,
            "may_speak": True,
        },
        "expires_at": "2026-10-07T02:00:00.000000+00:00",
        "issued_at": "2026-10-07T00:00:00.000000+00:00",
    }


def person_ask(
    *,
    subject_id: str = "person-4",
    minute: int = 41,
    deadline_ms: int = 15_000,
    ask_seq: int = 1,
) -> dict[str, Any]:
    """An asked frame for one of a world's people, as a door that carries the model's own packet
    builds it: the person role's messages under the tool-call mechanism and its forced function."""
    from exulanica.models.manifest import AnsweringMechanism
    from exulanica.world.roles.person import person_role
    from exulanica.world.society_decision_contract import DecisionOption

    role = person_role()
    options = [
        DecisionOption("go to the bench", "go", "go", "bench-1", "rest", 12_000),
        DecisionOption("wait a minute", "wait", "wait", None, None, None),
        DecisionOption("stand where you are", "stand", "stand", None, None, None),
    ]
    context = {
        "profile": role.context_profile,
        "subject_id": subject_id,
        "branch_id": "branch-1",
        "tick": minute,
        "need_milli": 300,
        "rest_at_need_milli": 700,
        "doing": {"kind": "go", "status": "completed", "reason": "arrived"},
        "last_activity": None,
        "options": [option.as_record() for option in options],
    }
    request_id = str(uuid.uuid4())
    return {
        "kind": "asked",
        "ask_seq": ask_seq,
        "request_id": request_id,
        "request_sha256": uuid.uuid5(uuid.NAMESPACE_URL, request_id).hex * 2,
        "subject_id": subject_id,
        "deadline_ms": deadline_ms,
        "instruction": role.instruction,
        "choice_description": role.choice_description,
        "context": context,
        "messages": role.adapter.messages(role, context, AnsweringMechanism.TOOL_CALL),
        "act": role.choice(context).tool(),
        "minute": minute,
    }


def with_a_line(frame: dict[str, Any], label: str, maximum: int = 200) -> dict[str, Any]:
    """``frame`` with one more option that says something, as THINGS's engine with things (v7)
    states one: its record bounds the line, and the forced function gains a ``line`` argument."""
    frame = json.loads(json.dumps(frame))
    frame["context"]["options"].append(
        {"label": label, "kind": "say_all", "line_characters_maximum": maximum}
    )
    parameters = frame["act"]["function"]["parameters"]
    parameters["properties"]["action"]["enum"].append(label)
    parameters["properties"]["line"] = {"type": "string", "maxLength": maximum}
    return frame


class FakeDoor:
    """The channel routes of one grant, answered in the door contract's shapes. Every request is
    recorded with its method, path, query, body and whether it carried the key."""

    def __init__(self, *, grant: dict[str, Any] | None = None, hold_seconds: int = 1) -> None:
        self.grant = grant or grant_view(things=["person-4"])
        self.hold_seconds = hold_seconds
        self.requests: list[dict[str, Any]] = []
        self.refusals: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        #: Called with an answer's body before the door replies to it, as the host might record
        #: the turn while the reply is still on its way.
        self.on_answer: Callable[[Any], None] | None = None
        self._frames: list[dict[str, Any]] = []
        self._served = 0
        self._lock = threading.Condition()

    def push(self, *frames: dict[str, Any]) -> None:
        with self._lock:
            self._frames.extend(frames)
            self._lock.notify_all()

    def delivered(self) -> bool:
        """Whether every frame pushed so far has been sent in a poll's answer."""
        with self._lock:
            return self._served >= len(self._frames)

    def refuse(self, path: str, status: int, code: str, **extra: Any) -> None:
        """Answer the next request to ``path`` with a refusal in the door's problem shape."""
        detail = extra.pop("detail", f"refused: {code}")
        self.refusals.setdefault(path, []).append(
            (status, {**extra, "code": code, "detail": detail})
        )

    def requests_to(self, path: str) -> list[dict[str, Any]]:
        return [request for request in self.requests if request["path"] == path]

    def handle(
        self, method: str, path: str, query: dict[str, str], authorization: str | None, body: Any
    ) -> tuple[int, dict[str, Any]]:
        self.requests.append(
            {
                "method": method,
                "path": path,
                "query": query,
                "keyed": authorization == f"Bearer {KEY}",
                "body": body,
            }
        )
        queued = self.refusals.get(path)
        if queued:
            return queued.pop(0)
        if (method, path) == ("POST", "/door/channel/hello"):
            return 200, {
                "profile": "exulanica.door-frame/v1",
                "grant": self.grant,
                "hold_seconds": self.hold_seconds,
                "cursor": "c0",
            }
        if (method, path) == ("GET", "/door/channel/frames"):
            with self._lock:
                if self._served >= len(self._frames):
                    self._lock.wait(0.05)
                frames = self._frames[self._served :]
                self._served = len(self._frames)
            return 200, {
                "profile": "exulanica.door-frame/v1",
                "frames": frames,
                "cursor": f"c{self._served}",
            }
        if (method, path) == ("POST", "/door/channel/answers"):
            if self.on_answer is not None:
                self.on_answer(body)
            return 202, {"received": True, "answer_sha256": "a" * 64}
        if (method, path) == ("POST", "/door/channel/arrivals"):
            return 202, {"received": True}
        return 404, {"code": "", "detail": "no such route"}

    def opener(self, request: Any, timeout: float) -> Any:
        """The library's opener: one request in, an answer or an HTTPError out."""
        parsed = urllib.parse.urlsplit(request.full_url)
        query = dict(urllib.parse.parse_qsl(parsed.query))
        body = None if request.data is None else json.loads(request.data)
        status, answer = self.handle(
            request.get_method(),
            parsed.path,
            query,
            request.get_header("Authorization"),
            body,
        )
        data = json.dumps(answer).encode()
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "refused", {}, io.BytesIO(data))
        return _Answer(data)


class _Answer(io.BytesIO):
    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@contextmanager
def served(door: FakeDoor) -> Iterator[str]:
    """``door`` served over HTTP on a loopback port, for code that opens its own connections; the
    address it answers on."""

    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self) -> None:
            parsed = urllib.parse.urlsplit(self.path)
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            status, answer = door.handle(
                self.command,
                parsed.path,
                dict(urllib.parse.parse_qsl(parsed.query)),
                self.headers.get("Authorization"),
                body,
            )
            data = json.dumps(answer).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = _answer
        do_POST = _answer

        def log_message(self, *_args: object) -> None:
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
