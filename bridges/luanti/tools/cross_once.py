"""Make one Luanti character cross into a running stack's world, as the gate mod does, with no game.

    <checkout>/.venv/bin/python bridges/luanti/tools/cross_once.py declare OUT [--label WORDS]
        [--game WORDS] [--mapping NAME]
    <checkout>/.venv/bin/python bridges/luanti/tools/cross_once.py cross --api URL --token-file FILE
        [--scene FILE] [--look KEY] [--carry ITEM] [--stay-s 120] [--mapping NAME]

``declare`` writes the door bridge declaration a stack is started with (``launch.py up
--door-bridges OUT``): the bridge ``luanti``, run by a server, unlisted, offered to the stack's
synthetic workspaces, pinning every published version of this mod's mapping by its digest (the one
``--mapping`` names first) and admitting the adapter's version. Its label and game are the words a
world shows for where a visitor came from (``--label`` and ``--game``, the owner's choice; by
default the game's own names). Its own credential is random and only its digest is written.

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
MAPPING_FILE = "luanti-minetest-game.v3.json"
#: The words a declaration gives the bridge by default: the game's own names.
LABEL = "Luanti"
GAME = "Luanti (Minetest Game)"
BUILD_SCENE = CHECKOUT / "scripts" / "demo" / "build_scene.py"
#: The scene a check builds unless ``--scene`` names another: the demo's, at the newest version the
#: scene catalog's lock names.
DEMO_SCENE_KEY = "three-strangers"


def newest_demo_scene() -> Path:
    """The demo's scene file at the newest version the scene catalog's lock names that dresses a
    starter world, read and checked against the lock by the product's own scene reader."""
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.world.scenes import SCENES_DIRECTORY, read_scene_lock, shipped_scene

    locked = read_scene_lock()
    versions = sorted(
        (version for scene, version in locked if scene == DEMO_SCENE_KEY), reverse=True
    )
    for version in versions:
        # The scene builder makes a starter world when given no saved one, so the check builds the
        # newest version that dresses a starter; a version for a generated world needs its entry.
        if (
            shipped_scene(DEMO_SCENE_KEY, version, locked[(DEMO_SCENE_KEY, version)]).ground
            == "starter"
        ):
            return SCENES_DIRECTORY / f"{DEMO_SCENE_KEY}.v{version}.json"
    raise SystemExit(f"the scene catalog's lock names no {DEMO_SCENE_KEY} that dresses a starter")


SOCIETY_OF_THINGS = "exulanica-society/v7"


def _mapping(name: str = MAPPING_FILE) -> tuple[str, dict[str, Any]]:
    if "/" in name or not (MOD / "mapping" / name).is_file():
        raise SystemExit(f"no published mapping file is named {name}")
    text = (MOD / "mapping" / name).read_text()
    return text, json.loads(text)


def _plain_words(text: str, what: str) -> str:
    """``text`` as the door takes a bridge's label or game: one line of 1 to 80 characters."""
    words = text.strip()
    if not 1 <= len(words) <= 80 or any(ord(character) < 32 for character in words):
        raise SystemExit(f"a bridge's {what} is one line of 1 to 80 characters")
    return words


def _adapter() -> dict[str, Any]:
    return json.loads((MOD / "adapter.json").read_text())


def _digest(mapping: dict[str, Any]) -> str:
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical

    return sha256_of_canonical(mapping).hex()


def declare(
    out: Path, *, mapping_file: str = MAPPING_FILE, label: str = LABEL, game: str = GAME
) -> None:
    """The declaration pins every published version of the mapping, the one ``mapping_file`` names
    (the one a crossing says hello with) first, so a server or a check pinned to another version is
    let in as well. ``label`` and ``game`` are the words a world shows for where its visitors came
    from."""
    _, mapping = _mapping(mapping_file)
    others = sorted(
        (path for path in (MOD / "mapping").glob("*.json") if path.name != mapping_file),
        reverse=True,
    )
    pinned = [_digest(mapping)] + [_digest(json.loads(path.read_text())) for path in others]
    entry = {
        "bridge": "luanti",
        "label": _plain_words(label, "label"),
        "game": _plain_words(game, "game"),
        "run_by": "server",
        "ai": False,
        "credential_sha256": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
        "mapping_sha256": pinned,
        "adapter_versions": [_adapter()["adapter_version"]],
        "listed": False,
        "workspaces": "synthetic",
    }
    out.write_text(json.dumps([entry], indent=2) + "\n")
    print(
        f"{out}: bridge luanti ({entry['label']}), mapping {entry['mapping_sha256'][0][:16]}..., "
        f"adapter {entry['adapter_versions'][0]}"
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


def opened_to_travellers(travellers: dict[str, Any], base: str, with_mind: bool) -> dict[str, Any]:
    """The grant's additions for a scene that names its travellers, as run/check.py makes them: the
    world decides where the door's published grant body offers it, with the scene's mind only when
    asked for."""
    if not travellers:
        return {}
    with urllib.request.urlopen(base + "/openapi.json", timeout=60) as response:
        schema = json.loads(response.read())
    body = schema.get("components", {}).get("schemas", {}).get("IssueBody", {})
    if "visitors_decided_by" not in body.get("properties", {}):
        return {}
    opened: dict[str, Any] = {"visitors_decided_by": "world"}
    if with_mind and travellers.get("model"):
        opened["traveller"] = travellers["model"]
    return opened


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
    travellers = placed.get("travellers") or {}
    gate = travellers.get("gate") or next(
        thing["thing_id"] for thing in placed["things"] if thing["kind"]["kind"] == "gate"
    )
    if gate not in {thing["thing_id"] for thing in placed["things"]}:
        raise SystemExit(f"travellers come through {gate}, which the scene did not place")
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
            # A scene that names its travellers has the world decide for them where this door lets
            # it; their paid mind only when asked for.
            **opened_to_travellers(travellers, base, arguments.traveller_mind),
        },
    )
    del token
    credential = issued["channel_credential"]["credential"]
    mapping_text, mapping = _mapping(arguments.mapping)
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
    declaring.add_argument(
        "--label",
        default=LABEL,
        help="the bridge's name as a world shows it (default: %(default)s)",
    )
    declaring.add_argument(
        "--game", default=GAME, help="the game as a world shows it (default: %(default)s)"
    )
    declaring.add_argument(
        "--mapping",
        default=MAPPING_FILE,
        help="the mapping file pinned first (default: %(default)s)",
    )
    crossing = commands.add_parser("cross", help="make one character cross into a running stack")
    crossing.add_argument("--api", required=True, help="the stack's API, http://127.0.0.1:PORT")
    crossing.add_argument("--token-file", type=Path, required=True)
    crossing.add_argument("--scene", type=Path, default=None)
    crossing.add_argument(
        "--traveller-mind",
        action="store_true",
        help="give the traveller the mind the scene names (paid calls: only under an allocation)",
    )
    crossing.add_argument("--look", default="cc0-traveller")
    crossing.add_argument("--carry", default="default:torch")
    crossing.add_argument("--stay-s", type=int, default=120)
    crossing.add_argument(
        "--mapping",
        default=MAPPING_FILE,
        help="the mapping file to say hello with (default: %(default)s)",
    )
    arguments = parser.parse_args(argv)
    if arguments.command == "cross":
        arguments.scene = arguments.scene or newest_demo_scene()
    if arguments.command == "declare":
        declare(
            arguments.out,
            mapping_file=arguments.mapping,
            label=arguments.label,
            game=arguments.game,
        )
    else:
        cross(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
