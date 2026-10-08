"""Run the NeMo Agent Toolkit example against a stand-in door and a stand-in mind.

    python3 bridges/agents/checks/nat_check.py --nat <a nat command> --facade-python <a Python
        with exulanica-agent[mcp]> [--live]

It serves the stand-in door of ``mcp_stdio.py`` (one open turn) and, unless ``--live``, a stand-in
mind speaking the OpenAI chat-completions API, which calls the toolkit's tools in a fixed order:
wait for a turn, answer it with the first action offered, then finish. It writes a copy of
``examples/nemo-agent-toolkit.yml`` that starts the facade with the given Python (instead of uvx)
and points the mind at the stand-in, runs ``nat run`` on it, and checks that the answer reached the
door as one offered action. With ``--live`` the mind is the example's own, Nemotron on Nebius Token
Factory: a local relay forwards each of the toolkit's requests there with the key from this
process's ``NEBIUS_API_KEY`` and counts calls and tokens, and the toolkit itself only ever holds a
stand-in key. Prints one JSON report; exits 0 only when every check holds. No key reaches it.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_stdio import AGENTS_ROOT, KEY, REQUEST_ID, _Door, _serve

EXAMPLE = AGENTS_ROOT / "examples" / "nemo-agent-toolkit.yml"
_TURN = re.compile(r"Turn ([0-9a-f-]{36})")
_OPTION = re.compile(r"^- (.+)$", re.MULTILINE)


class _Mind:
    """A stand-in for a chat-completions model: wait for a turn, answer it, finish."""

    def __init__(self) -> None:
        self.tool_names: list[str] = []
        self.calls: list[str] = []

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        tools = [tool["function"]["name"] for tool in request.get("tools") or []]
        self.tool_names = tools or self.tool_names
        wait = next((name for name in self.tool_names if name.endswith("wait_for_turn")), None)
        act = next((name for name in self.tool_names if name.endswith("__act")), None)
        messages = request.get("messages") or []
        # A ReAct agent hands a tool's result back as the newest message, whatever its role.
        last = str(messages[-1].get("content")) if messages else ""
        if not self.calls or (self.calls[-1] == wait and not _TURN.search(last)):
            return self._call(wait, {"wait_seconds": 10})
        if self.calls[-1] == wait:
            turn = _TURN.search(last)
            assert turn is not None
            options = _OPTION.findall(last.split("What you can do now:")[-1])
            return self._call(act, {"turn": turn.group(1), "action": options[0].strip()})
        return {"role": "assistant", "content": "I took my turn."}

    def _call(self, name: str | None, arguments: dict[str, Any]) -> dict[str, Any]:
        assert name is not None, "the toolkit offered no such tool"
        self.calls.append(name)
        call = {
            "id": f"call_{len(self.calls)}",
            "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }
        return {"role": "assistant", "content": None, "tool_calls": [call]}


class _Relay(_Mind):
    """The example's own mind, relayed: each request goes to Nebius Token Factory unchanged but for
    streaming, and its call and token counts are kept for the spending record."""

    URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"

    def __init__(self) -> None:
        super().__init__()
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def answer(self, request: dict[str, Any]) -> dict[str, Any]:
        import urllib.request

        self.tool_names = [t["function"]["name"] for t in request.get("tools") or []] or (
            self.tool_names
        )
        asked = {k: v for k, v in request.items() if k not in ("stream", "stream_options")}
        relayed = urllib.request.Request(
            self.URL,
            json.dumps(asked).encode(),
            {
                "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"],
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(relayed, timeout=120) as reply:
            body = json.load(reply)
        usage = body.get("usage") or {}
        self.prompt_tokens += int(usage.get("prompt_tokens") or 0)
        self.completion_tokens += int(usage.get("completion_tokens") or 0)
        message = body["choices"][0]["message"]
        self.calls += [call["function"]["name"] for call in message.get("tool_calls") or []] or [
            "(answer)"
        ]
        return {k: v for k, v in message.items() if k in ("role", "content", "tool_calls")}


def _serve_mind(mind: _Mind) -> tuple[http.server.ThreadingHTTPServer, str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            request = json.loads(self.rfile.read(length))
            message = mind.answer(request)
            if request.get("stream"):
                self._stream(request, message)
                return
            body = {
                "id": "chatcmpl-check",
                "object": "chat.completion",
                "created": 0,
                "model": request.get("model", "check"),
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if message.get("tool_calls") else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _stream(self, request: dict[str, Any], message: dict[str, Any]) -> None:
            """The same answer as server-sent chunks, as a streaming client asks for it."""
            delta: dict[str, Any] = {"role": "assistant"}
            if message.get("tool_calls"):
                delta["tool_calls"] = [
                    {"index": index, **call} for index, call in enumerate(message["tool_calls"])
                ]
            else:
                delta["content"] = message.get("content") or ""
            finish = "tool_calls" if message.get("tool_calls") else "stop"
            chunks = [
                {"index": 0, "delta": delta, "finish_reason": None},
                {"index": 0, "delta": {}, "finish_reason": finish},
            ]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for choice in chunks:
                chunk = {
                    "id": "chatcmpl-check",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": request.get("model", "check"),
                    "choices": [choice],
                }
                self.wfile.write(b"data: " + json.dumps(chunk).encode() + b"\n\n")
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def log_message(self, *_args: object) -> None:
            return None

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def _set_once(text: str, key: str, value: str) -> str:
    """``text`` with the one line setting ``key`` set to ``value``, written as a JSON string, which
    YAML reads back as written whatever marks a declared name holds."""
    if not value.isprintable():
        raise SystemExit(f"{key} holds a character that cannot be written on one line")
    line = re.compile(rf"^(\s+{re.escape(key)}:) .*$", re.MULTILINE)
    if len(line.findall(text)) != 1:
        raise SystemExit(f"the example does not set {key} on exactly one line")
    return line.sub(lambda found: f"{found.group(1)} {json.dumps(value)}", text)


def _config(
    facade_python: str,
    mind_url: str | None,
    folder: Path,
    *,
    mind: str | None = None,
    name: str | None = None,
    maker: str | None = None,
) -> Path:
    text = EXAMPLE.read_text(encoding="utf-8")
    start = text.index("      command: uvx")
    end = text.index("      env:")
    local = f"      command: {facade_python}\n      args: [-m, exulanica_agent, mcp]\n"
    text = text[:start] + local + text[end:]
    text = text.replace(
        "        EXULANICA_URL: ${EXULANICA_URL}\n",
        "        EXULANICA_URL: ${EXULANICA_URL}\n        PYTHONPATH: ${EXULANICA_AGENT_PATH}\n",
    )
    if mind_url is not None:
        text = text.replace("https://api.tokenfactory.nebius.com/v1", mind_url)
    if mind is not None:
        # The model the toolkit calls is the mind the agent declares.
        text = _set_once(text, "model_name", mind)
        text = _set_once(text, "EXULANICA_AGENT_MIND", mind)
    if name is not None:
        # The instructions call the agent by the name it declares.
        declared = re.findall(r"^\s+EXULANICA_AGENT_NAME: (.+)$", text, re.MULTILINE)
        called = f"named {declared[0]}." if len(declared) == 1 else ""
        if not called or text.count(called) != 1:
            raise SystemExit("the example's instructions do not call its agent by name once")
        text = _set_once(text.replace(called, f"named {name}."), "EXULANICA_AGENT_NAME", name)
    if maker is not None:
        text = _set_once(text, "EXULANICA_AGENT_MAKER", maker)
    path = folder / "agent.yml"
    path.write_text(text, encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--nat", required=True, help="the toolkit's nat command")
    parser.add_argument("--facade-python", required=True)
    parser.add_argument("--live", action="store_true", help="the example's own mind on Nebius")
    arguments = parser.parse_args()
    door = _Door()
    door_server, door_url = _serve(door)
    mind = _Relay() if arguments.live else _Mind()
    mind_server, mind_url = _serve_mind(mind)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "EXULANICA_URL": door_url,
        "EXULANICA_AGENT_PATH": str(AGENTS_ROOT),
        "NEBIUS_API_KEY": "relayed",
    }
    with tempfile.TemporaryDirectory() as folder:
        key_file = Path(folder) / "agent.key"
        key_file.write_text(KEY + "\n", encoding="utf-8")
        key_file.chmod(0o600)
        env["EXULANICA_AGENT_KEY_FILE"] = str(key_file)
        config = _config(arguments.facade_python, mind_url, Path(folder))
        run = subprocess.run(
            [arguments.nat, "run", "--config_file", str(config), "--input", "Take one turn."],
            env=env,
            capture_output=True,
            text=True,
            timeout=600,
        )
    door_server.shutdown()
    mind_server.shutdown()
    output = run.stdout + run.stderr
    secret = os.environ.get("NEBIUS_API_KEY", "")
    report = {
        "nat_exit": run.returncode,
        "mind": "Nemotron on Nebius Token Factory" if arguments.live else "stand-in",
        "tools_offered": mind.tool_names,
        "tools_called": mind.calls,
        "mind_tokens": [getattr(mind, "prompt_tokens", 0), getattr(mind, "completion_tokens", 0)],
        "door_answers": [answer["label"] for answer in door.answers],
        "door_answered_turn": [answer["request_id"] for answer in door.answers] == [REQUEST_ID],
        "output_names_a_key": KEY in output or (bool(secret) and secret in output),
        "output_tail": output.strip().splitlines()[-4:],
    }
    holds = {
        "nat run succeeds": run.returncode == 0,
        "the answer reached the door as one offered action": report["door_answers"]
        in (["go to the bench"], ["wait a minute"])
        and report["door_answered_turn"],
        "no key in the output": not report["output_names_a_key"],
    }
    if not arguments.live:
        # The stand-in grant lets no body in, so the facade offers every tool but enter_world.
        holds["the toolkit offered the four tools of a grant without a body"] = sorted(
            mind.tool_names
        ) == sorted(
            f"world__{name}" for name in ("wait_for_turn", "act", "what_happened", "world_rules")
        )
    print(json.dumps({"report": report, "holds": holds}, indent=2))
    return 0 if all(holds.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
