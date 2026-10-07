"""Speak MCP to the facade over Streamable HTTP with the MCP SDK's own client.

Run with a Python that has ``exulanica-agent[mcp]`` (the SDK and its HTTP client):

    <that python> bridges/agents/checks/mcp_http.py --port <a free port on 127.0.0.1>

It serves a stand-in door with one open turn (the same as ``mcp_stdio.py``), starts
``python -m exulanica_agent mcp --http <port>``, and checks: the SDK's client, presenting the agent
key as its bearer credential, negotiates with the facade, lists the tools its grant offers in
order, receives the turn and answers it; a request with no key, or with another key, is refused
401; a request naming another host is refused before any tool runs. It prints one JSON report and
exits 0 only when every check holds. The key is a made-up test value.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp_stdio import AGENTS_ROOT, KEY, REQUEST_ID, TOOLS, _Door, _serve


def _post(url: str, headers: dict[str, str]) -> int:
    request = urllib.request.Request(
        url,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as answer:
            return answer.status
    except urllib.error.HTTPError as error:
        return error.code
    except urllib.error.URLError:
        return 0


async def _with_client(url: str) -> dict[str, Any]:
    import httpx2
    from mcp.client.client import Client
    from mcp.client.streamable_http import streamable_http_client

    checks: dict[str, Any] = {}
    http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {KEY}"}, timeout=30)
    async with http, Client(streamable_http_client(url, http_client=http)) as client:
        checks["negotiated"] = client.session.protocol_version
        listed = await client.list_tools()
        checks["tools"] = [tool.name for tool in listed.tools]
        waited = await client.call_tool("wait_for_turn", {"wait_seconds": 10})
        turn = (waited.structured_content or {}).get("turn")
        checks["turn"] = None if turn is None else turn["turn"]
        acted = await client.call_tool("act", {"turn": REQUEST_ID, "action": "go to the bench"})
        checks["act_received"] = (acted.structured_content or {}).get("received")
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", type=int, required=True)
    arguments = parser.parse_args()
    door = _Door()
    server, door_url = _serve(door)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "EXULANICA_URL": door_url,
        "EXULANICA_AGENT_KEY": KEY,
        "EXULANICA_AGENT_NAME": "Scout",
        "EXULANICA_AGENT_MAKER": "Check",
    }
    facade = subprocess.Popen(
        [sys.executable, "-m", "exulanica_agent", "mcp", "--http", str(arguments.port)],
        cwd=AGENTS_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    url = f"http://127.0.0.1:{arguments.port}/mcp"
    report: dict[str, Any] = {}
    try:
        for _ in range(150):
            if _post(url, {}) != 0 or facade.poll() is not None:
                break
            time.sleep(0.1)
        modern = {"MCP-Protocol-Version": "2026-07-28", "Accept": "application/json"}
        report["no_key"] = _post(url, modern)
        report["other_key"] = _post(url, {**modern, "Authorization": "Bearer someone-else"})
        report["other_host"] = _post(
            url, {**modern, "Authorization": f"Bearer {KEY}", "Host": "evil.example"}
        )
        report.update(asyncio.run(_with_client(url)))
    finally:
        facade.terminate()
        try:
            _out, err = facade.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            facade.kill()
            _out, err = facade.communicate()
        server.shutdown()
    report["stderr_names_key"] = KEY in err
    report["stderr_tail"] = err.strip().splitlines()[-3:]
    report["door_answers"] = [answer["label"] for answer in door.answers]
    holds = {
        "a request with no key is refused": report["no_key"] == 401,
        "a request with another key is refused": report["other_key"] == 401,
        "a request naming another host is refused": report["other_host"] in (400, 403, 421),
        "the SDK client negotiates": bool(report.get("negotiated")),
        "the grant's tools in order": report.get("tools") == TOOLS,
        "a turn is handed over": report.get("turn") == REQUEST_ID,
        "act reaches the door": report.get("door_answers") == ["go to the bench"],
        "the key never reaches stderr": not report["stderr_names_key"],
    }
    print(json.dumps({"report": report, "holds": holds}, indent=2, default=str))
    return 0 if all(holds.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
