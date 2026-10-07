"""Speak raw MCP to the facade over stdio, as a 2026-07-28 client and as a 2025-era client.

A conformance check of the facade's MCP surface, run by hand where the ``mcp`` extra is installed
(the repository's test suite has no MCP library, so it tests the facade's tools without it):

    python3 bridges/agents/checks/mcp_stdio.py --python <a Python with exulanica-agent[mcp]>

It serves a stand-in door on a loopback port with one open turn, starts
``python -m exulanica_agent mcp`` twice, and speaks newline-delimited JSON-RPC to each: the first
as a modern client (every request carries its protocol version and capabilities in ``_meta``:
``server/discover``, ``tools/list``, ``tools/call``, ``resources/list``, ``prompts/list``), the
second as a legacy client (``initialize``, then ``tools/list`` and ``tools/call``). It prints one
JSON report and exits 0 only when every check holds. Standard library only; the key is a made-up
test value.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path
from typing import Any

AGENTS_ROOT = Path(__file__).resolve().parents[1]
KEY = "check-key-" + "k" * 33
REQUEST_ID = "3f1c7a52-0d4e-4b1a-9c55-2e7f6a8b9c0d"
MODERN = "2026-07-28"
LEGACY = "2025-06-18"
TOOLS = ["wait_for_turn", "act", "what_happened", "enter_world", "world_rules"]


def _asked() -> dict[str, Any]:
    labels = ["go to the bench", "wait a minute"]
    return {
        "kind": "asked",
        "ask_seq": 1,
        "request_id": REQUEST_ID,
        "request_sha256": "b" * 64,
        "subject_id": "person-4",
        "deadline_ms": 15000,
        "instruction": "You decide what one simulated person in a small world does next.",
        "choice_description": "Choose what the person does next.",
        "context": {"options": [{"label": label} for label in labels]},
        "messages": [
            {"role": "system", "content": "You decide what one simulated person does next."},
            {
                "role": "user",
                "content": "It is minute 41.\nWhat you can do now:\n- go to the bench\n"
                "- wait a minute\nChoose one by calling act.",
            },
        ],
        "act": {
            "type": "function",
            "function": {
                "name": "act",
                "description": "Choose what the person does next.",
                "parameters": {
                    "type": "object",
                    "properties": {"action": {"type": "string", "enum": labels}},
                    "required": ["action"],
                    "additionalProperties": False,
                },
            },
        },
        "minute": 41,
    }


class _Door:
    def __init__(self) -> None:
        self.answers: list[dict[str, Any]] = []
        self.sent = False
        self.lock = threading.Lock()

    def handle(self, method: str, path: str, body: Any, keyed: bool) -> tuple[int, dict]:
        if not keyed:
            return 401, {"code": "unauthenticated", "detail": "no key"}
        if (method, path) == ("POST", "/door/channel/hello"):
            scope = {"visitors_maximum": 0, "kinds": [], "things": ["person-4"], "gate": None}
            scope |= {"may_carry_in": False, "may_carry_out": False, "may_speak": True}
            grant = {"grant_id": "g", "scope": scope, "expires_at": "2026-10-07T02:00:00+00:00"}
            return 200, {"profile": "exulanica.door-frame/v1", "grant": grant, "cursor": "c0"}
        if (method, path) == ("GET", "/door/channel/frames"):
            with self.lock:
                frames = [] if self.sent else [_asked()]
                self.sent = True
            if not frames:
                threading.Event().wait(0.2)
            return 200, {"profile": "exulanica.door-frame/v1", "frames": frames, "cursor": "c1"}
        if (method, path) == ("POST", "/door/channel/answers"):
            self.answers.append(body)
            return 202, {"received": True, "answer_sha256": "a" * 64}
        return 404, {"code": "", "detail": "no such route"}


def _serve(door: _Door) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            keyed = self.headers.get("Authorization") == f"Bearer {KEY}"
            path = urllib.parse.urlsplit(self.path).path
            status, answer = door.handle(self.command, path, body, keyed)
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
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class _Session:
    """One facade process and the JSON-RPC conversation with it."""

    def __init__(self, python: str, url: str) -> None:
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "EXULANICA_URL": url,
            "EXULANICA_AGENT_KEY": KEY,
            "EXULANICA_AGENT_NAME": "Scout",
            "EXULANICA_AGENT_MAKER": "Check",
        }
        self.process = subprocess.Popen(
            [python, "-m", "exulanica_agent", "mcp"],
            cwd=AGENTS_ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.next_id = 0

    def send(self, method: str, params: dict | None = None, *, notify: bool = False) -> Any:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if not notify:
            self.next_id += 1
            message["id"] = self.next_id
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()
        if notify:
            return None
        while True:
            line = self.process.stdout.readline()
            if not line:
                raise RuntimeError("the facade closed its output")
            answer = json.loads(line)
            if answer.get("id") == self.next_id:
                return answer

    def close(self) -> str:
        assert self.process.stdin is not None
        self.process.stdin.close()
        try:
            _out, err = self.process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            _out, err = self.process.communicate()
        return err


def _meta() -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "exulanica-check", "version": "1"},
    }


def _modern(python: str, url: str, door: _Door) -> dict[str, Any]:
    session = _Session(python, url)
    checks: dict[str, Any] = {}
    try:
        discover = session.send("server/discover", {"_meta": _meta()})["result"]
        checks["discover_versions"] = discover.get("supportedVersions")
        checks["discover_names_server"] = discover.get("serverInfo", {}).get("name")
        listed = session.send("tools/list", {"_meta": _meta()})["result"]
        checks["tools"] = [tool["name"] for tool in listed["tools"]]
        checks["tools_cache"] = (listed.get("ttlMs"), listed.get("cacheScope"))
        waited = session.send(
            "tools/call",
            {"name": "wait_for_turn", "arguments": {"wait_seconds": 10}, "_meta": _meta()},
        )["result"]
        turn = waited["structuredContent"]["turn"]
        checks["turn"] = None if turn is None else turn["turn"]
        acted = session.send(
            "tools/call",
            {
                "name": "act",
                "arguments": {"turn": REQUEST_ID, "action": "wait a minute"},
                "_meta": _meta(),
            },
        )["result"]
        checks["act_received"] = acted.get("structuredContent", {}).get("received")
        refused = session.send(
            "tools/call",
            {"name": "act", "arguments": {"turn": "nope", "action": "x"}, "_meta": _meta()},
        )["result"]
        checks["act_refusal_is_error"] = refused.get("isError")
        unknown = session.send(
            "tools/call", {"name": "teleport", "arguments": {}, "_meta": _meta()}
        )
        checks["unknown_tool_error_code"] = unknown.get("error", {}).get("code")
        resources = session.send("resources/list", {"_meta": _meta()})["result"]
        checks["resources"] = [resource["uri"] for resource in resources["resources"]]
        prompts = session.send("prompts/list", {"_meta": _meta()})["result"]
        checks["prompts"] = [prompt["name"] for prompt in prompts["prompts"]]
        checks["result_type"] = waited.get("resultType")
    finally:
        checks["stderr_names_key"] = KEY in session.close()
    checks["door_answers"] = [answer["label"] for answer in door.answers]
    return checks


def _legacy(python: str, url: str) -> dict[str, Any]:
    session = _Session(python, url)
    checks: dict[str, Any] = {}
    try:
        initialized = session.send(
            "initialize",
            {
                "protocolVersion": LEGACY,
                "capabilities": {},
                "clientInfo": {"name": "exulanica-check-legacy", "version": "1"},
            },
        )["result"]
        checks["legacy_version"] = initialized.get("protocolVersion")
        session.send("notifications/initialized", notify=True)
        listed = session.send("tools/list", {})["result"]
        checks["legacy_tools"] = [tool["name"] for tool in listed["tools"]]
        rules = session.send("tools/call", {"name": "world_rules", "arguments": {}})["result"]
        checks["legacy_rules"] = "How turns work" in rules["structuredContent"]["rules"]
    finally:
        checks["legacy_stderr_names_key"] = KEY in session.close()
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--python", required=True, help="a Python with exulanica-agent[mcp]")
    arguments = parser.parse_args()
    door = _Door()
    server, url = _serve(door)
    try:
        report = {**_modern(arguments.python, url, door), **_legacy(arguments.python, url)}
    finally:
        server.shutdown()
    holds = {
        "server/discover lists 2026-07-28": MODERN in (report.get("discover_versions") or []),
        "the five tools in order (modern)": report.get("tools") == TOOLS,
        "the five tools in order (legacy)": report.get("legacy_tools") == TOOLS,
        "a turn is handed over": report.get("turn") == REQUEST_ID,
        "act reaches the door": report.get("door_answers") == ["wait a minute"],
        "a wrong turn is an error result": report.get("act_refusal_is_error") is True,
        "an unknown tool is a protocol error": report.get("unknown_tool_error_code") == -32602,
        "results carry resultType": report.get("result_type") == "complete",
        "a legacy client is served": report.get("legacy_version") == LEGACY,
        "rules over a legacy session": report.get("legacy_rules") is True,
        "the key never reaches stderr": not report.get("stderr_names_key")
        and not report.get("legacy_stderr_names_key"),
    }
    print(json.dumps({"report": report, "holds": holds}, indent=2, default=str))
    return 0 if all(holds.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
