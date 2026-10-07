"""``exulanica-agent``: serve an agent's turns over MCP, check a key, or let an agent in.

``exulanica-agent mcp [--http PORT]``
    The MCP facade, for an MCP client to start: over stdio by default, or Streamable HTTP on
    127.0.0.1. Reads ``EXULANICA_URL``, ``EXULANICA_AGENT_KEY``, ``EXULANICA_AGENT_NAME``,
    ``EXULANICA_AGENT_MAKER`` and ``EXULANICA_AGENT_MIND``.
``exulanica-agent check``
    Says hello with the same settings and prints what the agent may do here and the world's rules;
    a way to see a setup works before starting a mind.
``exulanica-agent grant --world <id> [--thing <id> --version <id>] [--visitors 1] --key-file <f>``
    For a world's owner, with an API token that may issue grants (``EXULANICA_TOKEN``): issues a
    grant for the agents' door and writes the agent key, shown once, to a new file only its owner
    may read. The key is never printed.

Exit codes: 0 when it worked, 1 when the world refused (with its words), 2 for a missing setting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

from exulanica_agent.body import ENV_KEY, ENV_URL, Body
from exulanica_agent.transport import AgentError, Door, DoorRefusal

#: The bridge key a deployment admits outside agents under.
AGENTS_BRIDGE = "agents"
ENV_TOKEN = "EXULANICA_TOKEN"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="exulanica-agent", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("mcp", help="serve the agent's turns as MCP tools")
    serve.add_argument("--http", type=int, metavar="PORT", help="Streamable HTTP on 127.0.0.1")
    commands.add_parser("check", help="say hello and print what the agent may do here")
    grant = commands.add_parser("grant", help="let an agent into a world you own")
    grant.add_argument("--world", required=True, help="the world's id")
    grant.add_argument("--thing", action="append", default=[], help="a thing it decides for")
    grant.add_argument("--version", help="the world version the named things are in")
    grant.add_argument("--visitors", type=int, default=0, help="bodies of its own, 0 to 4")
    grant.add_argument("--minutes", type=int, default=120, help="how long, at most 1440")
    grant.add_argument("--quiet", action="store_true", help="its things may not speak")
    grant.add_argument("--key-file", required=True, type=Path, help="a new file for the key")
    return parser


def _grant(arguments: argparse.Namespace) -> int:
    url, token = os.environ.get(ENV_URL), os.environ.get(ENV_TOKEN)
    if not url or not token:
        print(f"set {ENV_URL} and {ENV_TOKEN} (an owner's API token)", file=sys.stderr)
        return 2
    if arguments.key_file.exists():
        print(f"{arguments.key_file} exists; the key goes into a new file", file=sys.stderr)
        return 2
    if arguments.thing and not arguments.version:
        print("naming things needs --version, the world version they are in", file=sys.stderr)
        return 2
    body: dict[str, object] = {
        "idempotency_key": f"exulanica-agent:{uuid.uuid4()}",
        "bridge": AGENTS_BRIDGE,
        "visitors_maximum": arguments.visitors,
        "kinds": ["agent"] if arguments.visitors else [],
        "things": arguments.thing,
        "may_speak": not arguments.quiet,
        "minutes": arguments.minutes,
        "channel_credential": True,
    }
    if arguments.version:
        body["version_id"] = arguments.version
    try:
        answer = Door(url, token).call(
            "POST", "/door/grants", body, query={"world_id": arguments.world}
        )
    except DoorRefusal as refusal:
        print(f"refused: {refusal.code or refusal.status}: {refusal.detail}", file=sys.stderr)
        return 1
    except AgentError as error:
        print(str(error), file=sys.stderr)
        return 1
    credential = answer.get("channel_credential") or {}
    key = credential.get("credential") if isinstance(credential, dict) else None
    if not isinstance(key, str):
        print("the world issued the grant but showed no key", file=sys.stderr)
        return 1
    descriptor = os.open(arguments.key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")
    grant = answer.get("grant") or {}
    print(
        json.dumps(
            {
                "grant_id": grant.get("grant_id"),
                "expires_at": grant.get("expires_at"),
                "key_file": str(arguments.key_file),
            }
        )
    )
    return 0


def _key_from_file() -> None:
    """Accept ``EXULANICA_AGENT_KEY_FILE`` in place of the key itself."""
    path = os.environ.get(ENV_KEY + "_FILE")
    if path and not os.environ.get(ENV_KEY):
        os.environ[ENV_KEY] = Path(path).read_text(encoding="utf-8").strip()


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "grant":
        return _grant(arguments)
    _key_from_file()
    try:
        body = Body.connect()
    except AgentError as error:
        print(str(error), file=sys.stderr)
        return 2 if "needed" in str(error) or "give the agent" in str(error) else 1
    with body:
        if arguments.command == "check":
            print(json.dumps({"permission": body.permission, "declared": body.declared}, indent=2))
            print(body.rules())
            return 0
        from exulanica_agent.mcp_server import serve_http, serve_stdio

        if arguments.http:
            serve_http(body, os.environ[ENV_KEY], arguments.http)
        else:
            serve_stdio(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
