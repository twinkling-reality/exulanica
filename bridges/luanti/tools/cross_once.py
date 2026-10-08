"""Make one Luanti character cross into a running stack's world, as the gate mod does, with no game.

    <checkout>/.venv/bin/python bridges/luanti/tools/cross_once.py declare OUT
    <checkout>/.venv/bin/python bridges/luanti/tools/cross_once.py cross --api URL --token-file FILE
        [--scene FILE] [--look KEY] [--carry ITEM] [--stay-s 120]

``declare`` writes the door bridge declaration a stack is started with (``launch.py up
--door-bridges OUT``): the bridge ``luanti``, run by a server, unlisted, offered to the stack's
synthetic workspaces, pinning this mod's mapping file by its digest and admitting the adapter's
version. Its own credential is random and only its digest is written.

``cross`` builds a scene in that stack (``scripts/demo/build_scene.py``, no minds), starts a
society of things over it and plays it, opens the scene's gate to one traveller from Luanti with a
channel credential, says hello with the adapter's version, mapping and reads exactly as the mod
does, and sends one arrival: the look the mod would ask for (the free look by default) carrying one
unit of a game item. It then reads frames until the world places the character, prints where to
look (world, version, the character's thing id), and keeps the channel read for ``--stay-s``
seconds, answering nothing, as the mod does; the world decides for the character. The token and
the channel credential stay in this process; nothing secret is printed or written.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
BRIDGE = HERE.parents[1]
CHECKOUT = HERE.parents[3]
MOD = BRIDGE / "mod" / "exulanica_gate"
MAPPING_FILE = "luanti-minetest-game.v2.json"
BUILD_SCENE = CHECKOUT / "scripts" / "demo" / "build_scene.py"
DEMO_SCENE = CHECKOUT / "scripts" / "demo" / "scenes" / "three-strangers.v2.json"
SOCIETY_OF_THINGS = "exulanica-society/v7"


def _mapping() -> tuple[str, dict[str, Any]]:
    text = (MOD / "mapping" / MAPPING_FILE).read_text()
    return text, json.loads(text)


def _adapter() -> dict[str, Any]:
    return json.loads((MOD / "adapter.json").read_text())


def _digest(mapping: dict[str, Any]) -> str:
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical

    return sha256_of_canonical(mapping).hex()


def declare(out: Path) -> None:
    _, mapping = _mapping()
    entry = {
        "bridge": "luanti",
        "label": "Luanti",
        "game": "Luanti (Minetest Game)",
        "run_by": "server",
        "ai": False,
        "credential_sha256": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        "mapping_sha256": [_digest(mapping)],
        "adapter_versions": [_adapter()["adapter_version"]],
        "listed": False,
        "workspaces": "synthetic",
    }
    out.write_text(json.dumps([entry], indent=2) + "\n")
    print(
        f"{out}: bridge luanti, mapping {entry['mapping_sha256'][0][:16]}..., adapter "
        f"{entry['adapter_versions'][0]}"
    )


def _call(
    base: str,
    method: str,
    path: str,
    secret: str,
    *,
    params: dict[str, str] | None = None,
    body: Any = None,
    raw: bytes | None = None,
    expected: tuple[int, ...] = (200, 201, 202),
) -> Any:
    url = base + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = raw if raw is not None else (None if body is None else json.dumps(body).encode())
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {secret}")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, text = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, text = error.code, error.read()
    if status not in expected:
        raise SystemExit(f"{method} {path} answered {status}: {text[:300]!r}")
    return json.loads(text or b"{}")


def cross(arguments: argparse.Namespace) -> None:
    base = arguments.api.rstrip("/")
    token = arguments.token_file.read_text().strip()
    record = Path(os.environ.get("TMPDIR", "/tmp")) / f"cross-once-{uuid.uuid4().hex}.json"
    built = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCENE),
            str(arguments.scene),
            "--base-url",
            base,
            "--record",
            str(record),
        ],
        cwd=CHECKOUT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "EXULANICA_TOKEN": token},
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        raise SystemExit("the scene was not built: " + (built.stdout + built.stderr)[-1500:])
    placed = json.loads(record.read_text())
    record.unlink()
    scope = {"world_id": placed["world_id"]}
    society = f"/world/versions/{placed['version_id']}/society"
    gate = next(thing["thing_id"] for thing in placed["things"] if thing["kind"]["kind"] == "gate")
    _call(
        base,
        "POST",
        society,
        token,
        params=scope,
        body={"region_id": placed["arrival"]["region_id"], "profile": SOCIETY_OF_THINGS},
    )
    control = _call(base, "GET", society + "/control", token, params=scope)
    _call(
        base,
        "PUT",
        society + "/control",
        token,
        params=scope,
        body={"base_revision": control["revision"], "mode": "playing", "speed": 1},
    )
    issued = _call(
        base,
        "POST",
        "/door/grants",
        token,
        params=scope,
        body={
            "idempotency_key": str(uuid.uuid4()),
            "bridge": "luanti",
            "version_id": placed["version_id"],
            "minutes": 60,
            "channel_credential": True,
            "visitors_maximum": 1,
            "kinds": ["player"],
            "gate": gate,
            "may_carry_in": True,
            "may_carry_out": True,
            "world_words": json.loads(arguments.scene.read_text())["title"],
        },
    )
    del token
    credential = issued["channel_credential"]["credential"]
    mapping_text, mapping = _mapping()
    adapter = _adapter()
    reads = list(adapter["reads"]) + [item["game_item"] for item in mapping["items"]]
    # The hello the mod sends: the mapping file's own text inside the body.
    hello = (
        '{"adapter_version":'
        + json.dumps(adapter["adapter_version"])
        + ',"mapping":'
        + mapping_text
        + ',"reads":'
        + json.dumps(reads)
        + "}"
    ).encode()
    said = _call(base, "POST", "/door/channel/hello", credential, raw=hello)
    cursor = said["cursor"]
    arrival_id = str(uuid.uuid4())
    _call(
        base,
        "POST",
        "/door/channel/arrivals",
        credential,
        body={
            "arrival_id": arrival_id,
            "game_type": "player",
            "look_key": arguments.look,
            "carried": [{"game_item": arguments.carry, "count": 1}] if arguments.carry else [],
        },
    )
    thing_id = None
    ends = time.monotonic() + max(arguments.stay_s, 60)
    while time.monotonic() < ends:
        read = _call(
            base,
            "GET",
            "/door/channel/frames",
            credential,
            params={"after": cursor},
            expected=(200, 410),
        )
        cursor = read.get("cursor", cursor)
        for frame in read.get("frames", []):
            if frame.get("kind") == "arrived" and frame.get("arrival_id") == arrival_id:
                thing_id = frame["thing_id"]
                where = {
                    "world_id": placed["world_id"],
                    "version_id": placed["version_id"],
                    "character": thing_id,
                    "look_key": arguments.look,
                }
                print(json.dumps(where, indent=2), flush=True)
                ends = time.monotonic() + arguments.stay_s
            elif frame.get("kind") == "arrival_refused" and frame.get("arrival_id") == arrival_id:
                raise SystemExit(f"the world refused the arrival: {frame.get('reason')}")
            elif frame.get("kind") == "departed" and frame.get("thing_id") == thing_id:
                print(f"the character left: {frame.get('why')}", flush=True)
                return
    if thing_id is None:
        raise SystemExit("the world did not place the character in time")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    declaring = commands.add_parser("declare", help="write the bridge declaration for a stack")
    declaring.add_argument("out", type=Path)
    crossing = commands.add_parser("cross", help="make one character cross into a running stack")
    crossing.add_argument("--api", required=True, help="the stack's API, http://127.0.0.1:PORT")
    crossing.add_argument("--token-file", type=Path, required=True)
    crossing.add_argument("--scene", type=Path, default=DEMO_SCENE)
    crossing.add_argument("--look", default="cc0-traveller")
    crossing.add_argument("--carry", default="default:torch")
    crossing.add_argument("--stay-s", type=int, default=120)
    arguments = parser.parse_args(argv)
    if arguments.command == "declare":
        declare(arguments.out)
    else:
        cross(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
