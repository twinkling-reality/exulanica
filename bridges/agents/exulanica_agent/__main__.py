"""``exulanica-agent``: serve an agent's turns over MCP, check a key, or let an agent in.

``exulanica-agent mcp [--http PORT]``
    The MCP facade, for an MCP client to start: over stdio by default, or Streamable HTTP on
    127.0.0.1. Reads ``EXULANICA_URL``, ``EXULANICA_AGENT_KEY`` (or the file
    ``EXULANICA_AGENT_KEY_FILE`` names), ``EXULANICA_AGENT_NAME``, ``EXULANICA_AGENT_MAKER`` and
    ``EXULANICA_AGENT_MIND``.
``exulanica-agent check``
    Says hello with the same settings and prints what the agent may do here and the world's rules;
    a way to see a setup works before starting a mind.
``exulanica-agent grant --world <id> --version <id> [--thing <id>] [--visitors 1] --key-file <f>``
    For a world's owner, with an API token that may issue grants (``EXULANICA_TOKEN``): issues a
    grant for the agents' door, deciding for the world's things it names in that version or
    bringing bodies of the agent's own into it, through the gate ``--gate <id>`` names or else one
    of the version's gates, and writes the agent key, shown once, to a new file only its owner may
    read. The key is never printed.
``exulanica-agent key --grant <id> --key-file <f>``
    For a world's owner: a new agent key for a grant, written the same way. A grant has one key at
    a time, so the earlier key stops working at once, and an agent still holding it reads why.

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

from exulanica_agent.body import ENV_URL, Body, agent_key
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
    grant.add_argument("--version", help="the world version its things are in, or it arrives in")
    grant.add_argument("--visitors", type=int, default=0, help="bodies of its own, 0 to 4")
    grant.add_argument("--gate", help="the gate its bodies come through, by its placed id")
    grant.add_argument("--minutes", type=int, default=120, help="how long, at most 1440")
    grant.add_argument("--quiet", action="store_true", help="its things may not speak")
    grant.add_argument("--key-file", required=True, type=Path, help="a new file for the key")
    key = commands.add_parser("key", help="a new agent key for a grant, ending the earlier one")
    key.add_argument("--grant", required=True, help="the grant's id")
    key.add_argument("--key-file", required=True, type=Path, help="a new file for the key")
    return parser


def _owner_door(key_file: Path) -> Door | None:
    """The door as the world's owner, or None after saying which setting is missing."""
    url, token = os.environ.get(ENV_URL), os.environ.get(ENV_TOKEN)
    if not url or not token:
        print(f"set {ENV_URL} and {ENV_TOKEN} (an owner's API token)", file=sys.stderr)
        return None
    if key_file.exists():
        print(f"{key_file} exists; the key goes into a new file", file=sys.stderr)
        return None
    return Door(url, token)


def _write_key(key_file: Path, key: object) -> bool:
    """The key the world showed once, into a new file only its owner may read; never printed."""
    if not isinstance(key, str):
        print("the world showed no key", file=sys.stderr)
        return False
    descriptor = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(key + "\n")
    return True


def _owner_call(
    door: Door, path: str, body: dict[str, object] | None, **query: str
) -> dict[str, object]:
    """The door's answer to an owner's request, or an empty answer after printing why not."""
    try:
        return door.call("POST", path, body, query=query or None)
    except DoorRefusal as refusal:
        print(f"refused: {refusal.code or refusal.status}: {refusal.detail}", file=sys.stderr)
    except AgentError as error:
        print(str(error), file=sys.stderr)
    return {}


def _grant(arguments: argparse.Namespace) -> int:
    door = _owner_door(arguments.key_file)
    if door is None:
        return 2
    if (arguments.thing or arguments.visitors) and not arguments.version:
        print(
            "naming things or bringing bodies needs --version, the world version they are in",
            file=sys.stderr,
        )
        return 2
    if arguments.gate and not arguments.visitors:
        print("--gate is where bodies come in: it needs --visitors", file=sys.stderr)
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
    if arguments.gate:
        body["gate"] = arguments.gate
    answer = _owner_call(door, "/door/grants", body, world_id=arguments.world)
    if not answer:
        return 1
    credential = answer.get("channel_credential")
    key = credential.get("credential") if isinstance(credential, dict) else None
    if not _write_key(arguments.key_file, key):
        return 1
    grant = answer.get("grant")
    grant = grant if isinstance(grant, dict) else {}
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


def _new_key(arguments: argparse.Namespace) -> int:
    try:
        grant_id = str(uuid.UUID(arguments.grant))
    except ValueError:
        print("--grant takes a grant's id", file=sys.stderr)
        return 2
    door = _owner_door(arguments.key_file)
    if door is None:
        return 2
    answer = _owner_call(door, f"/door/grants/{grant_id}/channel-credentials", None)
    if not answer or not _write_key(arguments.key_file, answer.get("credential")):
        return 1
    print(
        json.dumps(
            {
                "grant_id": grant_id,
                "expires_at": answer.get("expires_at"),
                "key_file": str(arguments.key_file),
                "earlier_key": "ended",
            }
        )
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "grant":
        return _grant(arguments)
    if arguments.command == "key":
        return _new_key(arguments)
    try:
        key = agent_key()
        body = Body.connect(key=key)
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
            assert key is not None  # Body.connect refused a missing key
            serve_http(body, key, arguments.http)
        else:
            serve_stdio(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
