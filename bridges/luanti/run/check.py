"""The scripted check of the Exulanica gate on a headless Luanti server: nobody at the keyboard.

    <checkout>/.venv/bin/python bridges/luanti/run/check.py [--port-base 19520]
        [--luanti-port 19529] [--minutes-speed 1] [--keep-stack] [--scene FILE]
        [--against stack|fake] [--play NAME [--carry ITEMS]]

What it does, in order, refusing by name at the first thing that is not as expected:

1.  Starts this checkout's stack on one port slot (``scripts/acceptance/launch.py up
    --society-playback --society-of-things --door-bridges``) with one door bridge declared,
    ``luanti``, unlisted and offered to the run's synthetic workspace, pinning this mod's mapping
    file by its digest and admitting the adapter's version from ``adapter.json``. The bridge's own
    credential is random and only its digest is declared; nothing in this check uses it.
2.  Builds a scene (``--scene``, the demo's by default) with ``scripts/demo/build_scene.py`` (no
    minds: every being keeps its routine and nothing calls a model), starts a society of things over
    it and plays it, then issues a grant that lets one traveller from Luanti in through the scene's
    gate, carrying things both ways, in the scene's own words for itself (its title), with a
    channel credential, which goes from the door's answer into the Luanti server's environment and
    nowhere else.
3.  Starts ``luanti --server`` from the unpacked install (``run/install.sh``) on a fresh flat world
    with ``exulanica_gate`` and the check mod ``exulanica_gate_check``, bound to 127.0.0.1 on the
    slot's UDP port, and waits for the check mod to stop the server. Meanwhile it acts as the
    world's owner, from the mod's recording: it sends the character home once it has lived in the
    world for a while, and closes the gate once its player has left the game with the character
    away again.
4.  Reads the check's result and the mod's recording of every exchange, then the world's own
    records: the gate answered no ask (the world decides for a character that crossed), each ask
    about the character was decided by the world, and the society replays with no game running.
5.  Writes the run's summary (no credential, no token) into the run folder and brings everything
    down (``--keep-stack`` leaves the stack up for a look in the browser).

``--against fake`` runs the same crossing against ``tools/fake_door.py`` instead, with no stack;
``--play NAME`` serves the world for a person to play in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
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
CHECK_MOD = BRIDGE / "check"
INSTALL = CHECKOUT / ".exulanica" / "luanti"
LAUNCH = CHECKOUT / "scripts" / "acceptance" / "launch.py"
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


#: The mapping file the server loads and the deployment pins: the game's newest.
MAPPING_FILE = "luanti-minetest-game.v2.json"
SOCIETY_OF_THINGS = "exulanica-society/v7"


class Refused(SystemExit):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"check refused: {code}: {detail}")


def mapping_digest() -> str:
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical

    mapping = json.loads((MOD / "mapping" / MAPPING_FILE).read_text())
    return sha256_of_canonical(mapping).hex()


class Api:
    """The stack's API as the synthetic owner. The token is read from the run's own file."""

    def __init__(self, base: str, token: str) -> None:
        self.base = base
        self._token = token

    def __call__(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> Any:
        url = self.base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {self._token}")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                status, text = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, text = error.code, error.read()
        if status not in expected:
            raise Refused("api", f"{method} {path} answered {status}: {text[:300]!r}")
        return json.loads(text or b"{}")


def launch(*arguments: str) -> str:
    done = subprocess.run(
        [sys.executable, str(LAUNCH), *arguments, "--worktree", str(CHECKOUT)],
        cwd=CHECKOUT,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise Refused("launch", (done.stdout + done.stderr)[-2000:])
    return done.stdout


def make_crossing_world(api: Api, folder: Path, token: str, scene: Path) -> dict[str, Any]:
    """``scene`` on a starter world, built through the public routes by the scene builder (without
    ``--minds``, so its beings keep their routines), and a society of things over it."""
    record = folder / "scene-build.json"
    built = subprocess.run(
        [
            sys.executable,
            str(BUILD_SCENE),
            str(scene),
            "--base-url",
            api.base,
            "--record",
            str(record),
        ],
        cwd=CHECKOUT,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "EXULANICA_TOKEN": token},
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        raise Refused("scene", (built.stdout + built.stderr)[-2000:])
    placed = json.loads(record.read_text())
    gates = [thing["thing_id"] for thing in placed["things"] if thing["kind"]["kind"] == "gate"]
    if not gates:
        raise Refused("scene", "the scene placed no gate for travellers to come through")
    # A scene may say which gate travellers come through and the mind the world gives them; the
    # scene builder copies that into its record and opens no gate itself.
    travellers = placed.get("travellers") or {}
    placed_ids = {thing["thing_id"] for thing in placed["things"]}
    if travellers.get("gate") and travellers["gate"] not in placed_ids:
        raise Refused(
            "scene", f"travellers come through {travellers['gate']}, which was not placed"
        )
    world = {
        "version": placed["version_id"],
        "scope": {"world_id": placed["world_id"]},
        "region": placed["arrival"]["region_id"],
        "society": f"/world/versions/{placed['version_id']}/society",
        "gate": travellers.get("gate") or gates[0],
        "travellers": travellers,
        "words": json.loads(scene.read_text())["title"],
    }
    started = api(
        "POST",
        world["society"],
        params=world["scope"],
        body={"region_id": world["region"], "profile": SOCIETY_OF_THINGS},
    )
    if started.get("profile") != SOCIETY_OF_THINGS:
        raise Refused("society", f"the version's society runs {started.get('profile')}")
    return world


def world_may_decide(api: Api) -> bool:
    """Whether this door's grants may say the world decides for their visitors: its published grant
    body names the field (``GET /openapi.json`` is public)."""
    schema = api("GET", "/openapi.json")
    body = schema.get("components", {}).get("schemas", {}).get("IssueBody", {})
    return "visitors_decided_by" in body.get("properties", {})


def opened_to_travellers(
    travellers: dict[str, Any], world_decides: bool, with_mind: bool
) -> dict[str, Any]:
    """What a grant adds for a scene that names its travellers, where the door lets the world decide
    for visitors: the world decides, and only with ``with_mind`` the mind the scene gives them (a
    model the manifest offers, whose calls are paid for), else the world's routine. Elsewhere the
    grant is as it was: the door names the bridge, and the world's routine settles its asks."""
    if not (travellers and world_decides):
        return {}
    opened: dict[str, Any] = {"visitors_decided_by": "world"}
    if with_mind and travellers.get("model"):
        opened["traveller"] = travellers["model"]
    return opened


def play(api: Api, world: dict[str, Any], speed: int) -> None:
    control = api("GET", world["society"] + "/control", params=world["scope"])
    api(
        "PUT",
        world["society"] + "/control",
        params=world["scope"],
        body={"base_revision": control["revision"], "mode": "playing", "speed": speed},
    )


def luanti_world(
    folder: Path,
    port: int,
    door_url: str,
    scenario: str = "crossing_door",
    *,
    player: str | None = None,
    carry: str | None = None,
) -> Path:
    """A fresh flat world and its server settings: a check world with the check mod, or, given a
    ``player``, a world for a person to play in, with the gate at the spawn and only that name let
    in, starting with ``carry`` (the game's own item words) in the hand when given."""
    world = folder / "world"
    world.mkdir(parents=True)
    mods = "load_mod_exulanica_gate = true\n"
    if player is None:
        mods += "load_mod_exulanica_gate_check = true\n"
    (world / "world.mt").write_text(
        "gameid = minetest_game\nbackend = sqlite3\nplayer_backend = sqlite3\n"
        "auth_backend = sqlite3\nmod_storage_backend = sqlite3\n" + mods
    )
    settings = [
        "bind_address = 127.0.0.1",
        "ipv6_server = false",
        f"port = {port}",
        "server_announce = false",
        "secure.http_mods = exulanica_gate",
        "disallow_empty_password = true",
        "mg_name = flat",
        "fixed_map_seed = 2026",
        "static_spawnpoint = (0, 10, 0)",
        f"exulanica_gate.door_url = {door_url}",
        f"exulanica_gate.mapping = {MAPPING_FILE}",
        "exulanica_gate.record_exchanges = true",
    ]
    if player is None:
        settings += [
            "exulanica_gate.world_words = The check's square",
            "exulanica_gate.check_mode = true",
            f"exulanica_gate_check.scenario = {scenario}",
        ]
    else:
        settings += [
            "exulanica_gate.gate_at_spawn = true",
            f"exulanica_gate.allowed_players = {player}",
            "enable_damage = false",
            "time_speed = 0",
            "world_start_time = 12000",
        ]
        if carry:
            settings += ["give_initial_stuff = true", f"initial_stuff = {carry}"]
    (folder / "server.conf").write_text("\n".join([*settings, ""]))
    return world


def start_luanti(
    folder: Path,
    world: Path,
    port: int,
    credential: str | None,
    *,
    bridge_credential: str | None = None,
    invite: str | None = None,
) -> subprocess.Popen:
    """``luanti --server`` on ``world``, its secrets in its environment and nowhere else: a grant's
    channel credential, or the bridge's own credential with an invite code the check mod types."""
    binary = INSTALL / "app" / "luanti.app" / "Contents" / "MacOS" / "luanti"
    if not binary.exists():
        raise Refused("luanti-missing", f"{binary} (run bridges/luanti/run/install.sh first)")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LUANTI_USER_PATH": str(INSTALL / "user"),
        "LUANTI_GAME_PATH": str(INSTALL / "games"),
        "LUANTI_MOD_PATH": f"{BRIDGE / 'mod'}:{CHECK_MOD}",
    }
    if credential:
        environment["EXULANICA_GATE_CHANNEL_CREDENTIAL"] = credential
    if bridge_credential:
        environment["EXULANICA_GATE_BRIDGE_CREDENTIAL"] = bridge_credential
    if invite:
        environment["EXULANICA_GATE_CHECK_INVITE"] = invite
    output = open(folder / "server.out", "w")  # noqa: SIM115 - the server writes to it until it stops
    return subprocess.Popen(
        [
            str(binary),
            "--server",
            "--world",
            str(world),
            "--gameid",
            "minetest_game",
            "--port",
            str(port),
            "--config",
            str(folder / "server.conf"),
            "--logfile",
            str(folder / "server.log"),
        ],
        env=environment,
        stdout=output,
        stderr=subprocess.STDOUT,
    )


def run_luanti(folder: Path, world: Path, port: int, credential: str, limit_s: int) -> int:
    """``luanti --server`` on ``world`` until it stops, at most ``limit_s`` seconds."""
    server = start_luanti(folder, world, port, credential)
    try:
        return server.wait(timeout=limit_s)
    except subprocess.TimeoutExpired:
        server.terminate()
        server.wait(timeout=30)
        raise Refused("luanti-timeout", f"the check did not finish in {limit_s} s") from None


def read_marks(recorded: Path, start: int) -> tuple[list[dict[str, Any]], int]:
    """The marks the mod recorded from line ``start`` on, and the line the next read starts at.
    Text after the last newline is a line still being written, left for the next read."""
    if not recorded.exists():
        return [], start
    lines = recorded.read_text().split("\n")[:-1]
    marks = [json.loads(line) for line in lines[start:]]
    return [mark for mark in marks if "mark" in mark], len(lines)


#: How long a character lives in the world before its owner sends it home, at 1x: two world minutes
#: and a little more, so the world has asked about it and decided at least once.
LIVES_S = 20.0


def act_as_owner(
    api: Api, grant_id: str, recorded: Path, server: subprocess.Popen, limit_s: int
) -> dict[str, Any]:
    """Wait for the check's server to stop, acting meanwhile as the world's owner, each act once,
    from the mod's recording: send the character home once it has lived in the world for
    ``LIVES_S``, and close the gate a few seconds after it has crossed again (by then its player
    has left the game)."""
    acts: dict[str, Any] = {}
    arrivals: list[tuple[float, str | None]] = []
    start = 0
    ends = time.monotonic() + limit_s
    while server.poll() is None:
        if time.monotonic() > ends:
            server.terminate()
            server.wait(timeout=30)
            raise Refused("luanti-timeout", f"the check did not finish in {limit_s} s")
        marks, start = read_marks(recorded, start)
        arrivals += [
            (time.monotonic(), mark.get("subject")) for mark in marks if mark["mark"] == "arrived"
        ]
        now = time.monotonic()
        if arrivals and "sent_home" not in acts and now - arrivals[0][0] >= LIVES_S:
            api(
                "POST",
                f"/door/grants/{grant_id}/send-away",
                body={"thing_id": arrivals[0][1]},
                expected=(202,),
            )
            acts["sent_home"] = {
                "thing_id": arrivals[0][1],
                "after_arrival_s": round(now - arrivals[0][0], 1),
            }
        if len(arrivals) > 1 and "revoked" not in acts and now - arrivals[1][0] >= 5:
            api("POST", f"/door/grants/{grant_id}/revoke", expected=(200,))
            acts["revoked"] = {"after_arrival_s": round(now - arrivals[1][0], 1)}
        time.sleep(0.5)
    return acts


def against_fake_door(arguments: argparse.Namespace, folder: Path) -> dict[str, Any]:
    """The crossing scenario against ``tools/fake_door.py``: no stack, no database."""
    log = folder / "fake-door.jsonl"
    door = subprocess.Popen(
        [
            sys.executable,
            str(BRIDGE / "tools" / "fake_door.py"),
            "--port",
            str(arguments.fake_door_port),
            "--log",
            str(log),
            "--refuse-look",
            "default-skin",
        ],
        cwd=CHECKOUT,
    )
    try:
        time.sleep(1)
        luanti = luanti_world(
            folder,
            arguments.luanti_port,
            f"http://127.0.0.1:{arguments.fake_door_port}",
            "crossing",
        )
        exit_code = run_luanti(
            folder, luanti, arguments.luanti_port, secrets.token_urlsafe(32), arguments.limit_s
        )
    finally:
        door.terminate()
        door.wait(timeout=10)
    summary: dict[str, Any] = {"luanti_exit": exit_code, "against": "fake door"}
    result_file = luanti / "exulanica_gate_check" / "result.json"
    if result_file.exists():
        summary["check"] = json.loads(result_file.read_text())
    shutil.copy(luanti / "exulanica_gate" / "exchanges.jsonl", folder / "exchanges.jsonl")
    sent = [json.loads(line) for line in log.read_text().splitlines()]
    arrivals = [entry["body"] for entry in sent if entry["route"] == "/door/channel/arrivals"]
    delivered = [entry["body"] for entry in sent if entry["route"].endswith("/delivered")]
    summary["door_saw"] = {
        "answers": sum(1 for entry in sent if entry["route"] == "/door/channel/answers"),
        "arrivals": arrivals,
        "delivered": delivered,
        "gone": sum(1 for entry in sent if entry["route"] == "/door/channel/gone"),
    }
    summary["door_checks"] = {
        "the gate answered no ask about the character": summary["door_saw"]["answers"] == 0,
        "nothing was sent when the player left": summary["door_saw"]["gone"] == 0,
        "one torch was sent as carried": bool(arrivals)
        and all(
            body["carried"] == [{"game_item": "default:torch", "count": 1}] for body in arrivals
        ),
        "the own look was asked for first, then the free look when refused": [
            body["look_key"] for body in arrivals
        ][:2]
        == ["default-skin", "cc0-traveller"],
        "the delivery was reported with both things": bool(delivered)
        and len(delivered[0]["delivered"]) == 2,
    }
    return summary


def play_until_stopped(
    arguments: argparse.Namespace,
    folder: Path,
    api: Api,
    world: dict[str, Any],
    credential: str,
    summary: dict[str, Any],
) -> dict[str, Any]:
    """Serve a world for a person (``--play NAME``) until ``<run folder>/stop`` exists or the
    limit passes. The player's password for this throwaway server is written, readable by this
    user only, to ``<run folder>/player-password``, for the client to read once."""
    luanti = luanti_world(
        folder, arguments.luanti_port, api.base, player=arguments.play, carry=arguments.carry
    )
    password = folder / "player-password"
    password.write_text(secrets.token_urlsafe(18))
    password.chmod(0o600)
    server = start_luanti(folder, luanti, arguments.luanti_port, credential)
    playing = {
        "run_folder": str(folder),
        "player": arguments.play,
        "world_id": world["scope"]["world_id"],
        "version_id": world["version"],
        "luanti": f"127.0.0.1:{arguments.luanti_port}",
        "password_file": str(password),
        "stop_file": str(folder / "stop"),
    }
    (folder / "playing.json").write_text(json.dumps(playing, indent=2) + "\n")
    print(json.dumps(playing, indent=2), flush=True)
    ends = time.monotonic() + arguments.limit_s
    try:
        while time.monotonic() < ends and not (folder / "stop").exists() and server.poll() is None:
            time.sleep(1)
    finally:
        server.terminate()
        server.wait(timeout=30)
        password.unlink(missing_ok=True)
    summary["played"] = playing
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port-base", type=int, default=19520)
    parser.add_argument("--luanti-port", type=int, default=19529)
    parser.add_argument("--minutes-speed", type=int, default=1)
    parser.add_argument("--limit-s", type=int, default=1500)
    parser.add_argument("--keep-stack", action="store_true")
    parser.add_argument("--against", choices=("stack", "fake"), default="stack")
    parser.add_argument("--fake-door-port", type=int, default=19525)
    parser.add_argument("--play", metavar="NAME", help="serve a world for a person to play in")
    parser.add_argument(
        "--carry",
        metavar="ITEMS",
        help="with --play: what the person starts holding, as the game names its items",
    )
    parser.add_argument("--scene", type=Path, default=None, help="the scene to build")
    parser.add_argument(
        "--invite",
        action="store_true",
        help="open the gate by an invite the check mod types into /cross, not a server credential",
    )
    parser.add_argument(
        "--traveller-mind",
        action="store_true",
        help="give travellers the mind the scene names (its model calls are paid for: only under "
        "an allocation)",
    )
    arguments = parser.parse_args(argv)
    arguments.scene = arguments.scene or newest_demo_scene()
    if arguments.against == "fake":
        folder = CHECKOUT / ".exulanica" / "luanti-checks" / time.strftime("%Y%m%d-%H%M%S-fake")
        folder.mkdir(parents=True)
        summary = against_fake_door(arguments, folder)
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        checks = summary.get("check", {}).get("checks", [])
        failed = [entry["check"] for entry in checks if not entry["ok"]] + [
            name for name, ok in summary["door_checks"].items() if not ok
        ]
        print(
            json.dumps(
                {"run_folder": str(folder), "checks": len(checks), "failed": failed}, indent=2
            )
        )
        return 0 if checks and not failed else 1

    adapter = json.loads((MOD / "adapter.json").read_text())
    # The bridge's own credential redeems invites; only its digest is declared, and the credential
    # reaches the Luanti server's environment alone, and only in an invite check.
    bridge_credential = secrets.token_urlsafe(32)
    folder = CHECKOUT / ".exulanica" / "luanti-checks" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    bridges = [
        {
            "bridge": "luanti",
            "label": "Luanti",
            "game": "Luanti (Minetest Game)",
            "run_by": "server",
            "ai": False,
            "credential_sha256": hashlib.sha256(bridge_credential.encode()).hexdigest(),
            "mapping_sha256": [mapping_digest()],
            "adapter_versions": [adapter["adapter_version"]],
            "listed": False,
            "workspaces": "synthetic",
        }
    ]
    declared = folder / "door-bridges.json"
    declared.write_text(json.dumps(bridges))
    summary: dict[str, Any] = {
        "profile": "exulanica-gate.check-run/v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "adapter_version": adapter["adapter_version"],
        "mapping_sha256": bridges[0]["mapping_sha256"][0],
    }
    started = launch(
        "up",
        "--port-base",
        str(arguments.port_base),
        "--society-playback",
        "--no-derivative-worker",
        "--door-bridges",
        str(declared),
        "--society-of-things",
    )
    state = json.loads(started[: started.rindex("}") + 1])
    try:
        token = (Path(state["run_dir"]) / "token").read_text().strip()
        api = Api(f"http://127.0.0.1:{state['ports']['api']}", token)
        world = make_crossing_world(api, folder, token, arguments.scene)
        from exulanica.canonical import sha256_of_canonical

        summary["scene"] = {
            "file": arguments.scene.name,
            # The digest a scene lock names: the document's canonical form, not its file's bytes.
            "sha256": sha256_of_canonical(json.loads(arguments.scene.read_text())).hex(),
            "travellers": world["travellers"],
        }
        play(api, world, arguments.minutes_speed)
        grant = {
            "visitors_maximum": 1,
            "kinds": ["player"],
            "gate": world["gate"],
            "may_carry_in": True,
            "may_carry_out": True,
            "world_words": world["words"],
            **opened_to_travellers(
                world["travellers"], world_may_decide(api), arguments.traveller_mind
            ),
        }
        del token
        issued = api(
            "POST",
            "/door/grants",
            params=world["scope"],
            body={
                "idempotency_key": str(uuid.uuid4()),
                "bridge": "luanti",
                "version_id": world["version"],
                "minutes": 60,
                "channel_credential": not arguments.invite,
                **grant,
            },
        )
        credential = None if arguments.invite else issued["channel_credential"]["credential"]
        invite = None
        if arguments.invite:
            invite = api(
                "POST", f"/door/grants/{issued['grant']['grant_id']}/invites", expected=(201,)
            )["code"]
        summary["grant_id"] = issued["grant"]["grant_id"]
        if arguments.play:
            if arguments.invite:
                # A person types the code their world shows them; this check shows none.
                raise Refused(
                    "invite-play", "--play serves a gate opened by the server's credential"
                )
            play_until_stopped(arguments, folder, api, world, credential, summary)
            return 0
        luanti = luanti_world(
            folder,
            arguments.luanti_port,
            api.base,
            "crossing_invite" if arguments.invite else "crossing_door",
        )
        recorded = luanti / "exulanica_gate" / "exchanges.jsonl"
        server = start_luanti(
            folder,
            luanti,
            arguments.luanti_port,
            credential,
            bridge_credential=bridge_credential if arguments.invite else None,
            invite=invite,
        )
        del credential, invite, bridge_credential
        summary["owner_acts"] = act_as_owner(
            api, summary["grant_id"], recorded, server, arguments.limit_s
        )
        exit_code = server.returncode
        summary["luanti_exit"] = exit_code
        result_file = luanti / "exulanica_gate_check" / "result.json"
        if not result_file.exists():
            raise Refused("no-result", f"the check mod wrote no result; see {folder}/server.log")
        result = json.loads(result_file.read_text())
        summary["check"] = result
        shutil.copy(recorded, folder / "exchanges.jsonl")
        exchanges = [json.loads(line) for line in recorded.read_text().splitlines()]
        summary["answers_posted"] = sum(
            1 for entry in exchanges if entry.get("path") == "/door/channel/answers"
        )
        # Each ask about the character the gate left to the world, as the world recorded it.
        world_side = []
        for mark in exchanges:
            if mark.get("mark") != "frame_ignored" or mark.get("kind") != "asked":
                continue
            read = api(
                "GET",
                f"{world['society']}/decisions/{mark['request']}",
                params=world["scope"],
            )
            receipt = read.get("receipt") or read.get("decision") or {}
            provider = receipt.get("provider") or {}
            world_side.append(
                {
                    "request": mark["request"],
                    "status": receipt.get("status"),
                    "reason": receipt.get("reason"),
                    "label": (receipt.get("proposal") or {}).get("label"),
                    "provider_kind": provider.get("kind"),
                    "bridge": provider.get("bridge"),
                }
            )
        summary["receipts"] = world_side
        replay = api("GET", world["society"] + "/replay", params=world["scope"])
        summary["replay_verified"] = replay.get("replay_verified")
        ended = api("GET", f"/door/grants/{summary['grant_id']}")["grant"]
        summary["grant_at_the_end"] = {key: ended.get(key) for key in ("state", "ended_reason")}
    finally:
        if not arguments.keep_stack:
            launch("down")
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    checks = summary.get("check", {}).get("checks", [])
    failed = [entry for entry in checks if not entry["ok"]]
    # The gate decided nothing: it posted no answer, and no ask about the character was settled by
    # an answer from it.
    world_decided = summary.get("answers_posted") == 0 and not any(
        entry["status"] == "accepted" and entry["provider_kind"] == "external"
        for entry in summary.get("receipts", [])
    )
    print(
        json.dumps(
            {
                "run_folder": str(folder),
                "checks": len(checks),
                "failed": [entry["check"] for entry in failed],
                "asks_left_to_the_world": len(summary.get("receipts", [])),
                "the_world_decided": world_decided,
                "replay_verified": summary.get("replay_verified"),
            },
            indent=2,
        )
    )
    return 0 if checks and not failed and world_decided and summary.get("replay_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
