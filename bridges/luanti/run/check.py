"""The scripted check of the Exulanica gate on a headless Luanti server: nobody at the keyboard.

    <checkout>/.venv/bin/python bridges/luanti/run/check.py [--port-base 19520]
        [--luanti-port 19529] [--minutes-speed 1] [--keep-stack]

What it does, in order, refusing by name at the first thing that is not as expected:

1.  Starts this checkout's stack on one port slot (``scripts/acceptance/launch.py up
    --society-playback --door-bridges``) with one door bridge declared, ``luanti``, unlisted and
    offered to the run's synthetic workspace, pinning this mod's mapping file by its digest and
    admitting the adapter's version from ``adapter.json``. The bridge's own credential is random
    and only its digest is declared; nothing in this check uses it.
2.  Makes a starter world with the small square, brings its people in and plays it.
3.  Issues a grant naming one of its people, with a channel credential: the credential goes from
    the door's answer into the Luanti server's environment and nowhere else.
4.  Starts ``luanti --server`` from the unpacked install (``run/install.sh``) on a fresh flat
    world with ``exulanica_gate`` and the check mod ``exulanica_gate_check``, bound to 127.0.0.1 on
    the slot's UDP port, and waits for the check mod to stop the server.
5.  Reads the check's result and the mod's recording of every exchange, then the world's own
    records: each ask the mod answered has a receipt that names the bridge, and the society
    replays with no game running.
6.  Writes the run's summary (no credential, no token) into the run folder and brings everything
    down (``--keep-stack`` leaves the stack up for a look in the browser).
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
HALF_TURN_MICRORADIANS = 3_141_593
FULL_TURN_MICRORADIANS = 6_283_185


class Refused(SystemExit):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"check refused: {code}: {detail}")


def mapping_digest() -> str:
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical

    mapping = json.loads((MOD / "mapping" / "luanti-minetest-game.v1.json").read_text())
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


def make_world(api: Api) -> dict[str, Any]:
    """A starter world with the small square before where a person arrives, its people in."""
    entry = api("POST", "/world-entries/starter", body={"title": "Luanti gate check"})
    region = entry["authored_scene"]["region"]
    world = {
        "version": entry["authored_version_id"],
        "scope": {"world_id": entry["world_id"]},
        "region": region["region_id"],
    }
    route = f"/world/versions/{world['version']}"
    base = api("GET", route, params=world["scope"])["state_sha256"]
    spawn = region["spawn"]
    body = {
        "base_state_sha256": base,
        "arrangement_key": "small_square",
        "arrangement_version": 1,
        "viewer": {
            "x_mm": spawn["x_mm"],
            "z_mm": spawn["z_mm"],
            "yaw_microradians": (spawn["yaw_microradians"] + HALF_TURN_MICRORADIANS)
            % FULL_TURN_MICRORADIANS,
        },
        "origin_role": "fictional",
    }
    api("POST", route + "/arrangements/apply", params=world["scope"], body=body)
    society = route + "/society"
    api(
        "POST",
        society,
        params=world["scope"],
        body={"region_id": world["region"], "profile": "exulanica-society/v2"},
    )
    world["society"] = society
    return world


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
    scenario: str = "named_thing",
    *,
    player: str | None = None,
) -> Path:
    """A fresh flat world and its server settings: a check world with the check mod, or, given a
    ``player``, a world for a person to play in, with the gate at the spawn and only that name let
    in."""
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
    (folder / "server.conf").write_text("\n".join([*settings, ""]))
    return world


def start_luanti(folder: Path, world: Path, port: int, credential: str) -> subprocess.Popen:
    """``luanti --server`` on ``world``, its credential in its environment and nowhere else."""
    binary = INSTALL / "app" / "luanti.app" / "Contents" / "MacOS" / "luanti"
    if not binary.exists():
        raise Refused("luanti-missing", f"{binary} (run bridges/luanti/run/install.sh first)")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LUANTI_USER_PATH": str(INSTALL / "user"),
        "LUANTI_GAME_PATH": str(INSTALL / "games"),
        "LUANTI_MOD_PATH": f"{BRIDGE / 'mod'}:{CHECK_MOD}",
        "EXULANICA_GATE_CHANNEL_CREDENTIAL": credential,
    }
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
    binary = INSTALL / "app" / "luanti.app" / "Contents" / "MacOS" / "luanti"
    if not binary.exists():
        raise Refused("luanti-missing", f"{binary} (run bridges/luanti/run/install.sh first)")
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": os.environ.get("HOME", ""),
        "LUANTI_USER_PATH": str(INSTALL / "user"),
        "LUANTI_GAME_PATH": str(INSTALL / "games"),
        "LUANTI_MOD_PATH": f"{BRIDGE / 'mod'}:{CHECK_MOD}",
        "EXULANICA_GATE_CHANNEL_CREDENTIAL": credential,
    }
    with open(folder / "server.out", "w") as output:
        process = subprocess.Popen(
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
        try:
            return process.wait(timeout=limit_s)
        except subprocess.TimeoutExpired:
            process.terminate()
            process.wait(timeout=30)
            raise Refused("luanti-timeout", f"the check did not finish in {limit_s} s") from None


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
    lines = [
        entry["body"].get("line")
        for entry in sent
        if entry["route"] == "/door/channel/answers" and entry["body"].get("line")
    ]
    arrivals = [entry["body"] for entry in sent if entry["route"] == "/door/channel/arrivals"]
    delivered = [entry["body"] for entry in sent if entry["route"].endswith("/delivered")]
    summary["door_saw"] = {
        "lines": lines,
        "arrivals": arrivals,
        "delivered": delivered,
        "gone": sum(1 for entry in sent if entry["route"] == "/door/channel/gone"),
    }
    summary["door_checks"] = {
        "no player name reached the door": bool(lines)
        and all("Bob" not in line and "bob" not in line for line in lines),
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
    luanti = luanti_world(folder, arguments.luanti_port, api.base, player=arguments.play)
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
    arguments = parser.parse_args(argv)
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
    folder = CHECKOUT / ".exulanica" / "luanti-checks" / time.strftime("%Y%m%d-%H%M%S")
    folder.mkdir(parents=True)
    bridges = [
        {
            "bridge": "luanti",
            "label": "Luanti",
            "game": "Luanti (Minetest Game)",
            "run_by": "server",
            "ai": False,
            "credential_sha256": hashlib.sha256(secrets.token_bytes(32)).hexdigest(),
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
    )
    state = json.loads(started[: started.rindex("}") + 1])
    try:
        api = Api(
            f"http://127.0.0.1:{state['ports']['api']}",
            (Path(state["run_dir"]) / "token").read_text().strip(),
        )
        world = make_world(api)
        play(api, world, arguments.minutes_speed)
        society = api("GET", world["society"], params=world["scope"])
        people = sorted(person["id"] for person in society["state"]["inhabitants"])
        if not people:
            raise Refused("no-people", "the square brought nobody in")
        person = people[0]
        issued = api(
            "POST",
            "/door/grants",
            params=world["scope"],
            body={
                "idempotency_key": str(uuid.uuid4()),
                "bridge": "luanti",
                "things": [person],
                "version_id": world["version"],
                "minutes": 60,
                "channel_credential": True,
            },
        )
        credential = issued["channel_credential"]["credential"]
        summary["grant_id"] = issued["grant"]["grant_id"]
        summary["person"] = person
        if arguments.play:
            play_until_stopped(arguments, folder, api, world, credential, summary)
            return 0
        luanti = luanti_world(folder, arguments.luanti_port, api.base)
        exit_code = run_luanti(folder, luanti, arguments.luanti_port, credential, arguments.limit_s)
        del credential
        summary["luanti_exit"] = exit_code
        result_file = luanti / "exulanica_gate_check" / "result.json"
        if not result_file.exists():
            raise Refused("no-result", f"the check mod wrote no result; see {folder}/server.log")
        result = json.loads(result_file.read_text())
        summary["check"] = result
        recorded = luanti / "exulanica_gate" / "exchanges.jsonl"
        shutil.copy(recorded, folder / "exchanges.jsonl")
        world_side = []
        answered = [
            json.loads(line)
            for line in recorded.read_text().splitlines()
            if '"mark":"answered"' in line
        ]
        for mark in answered:
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
                    "what": mark["what"],
                    "status": receipt.get("status"),
                    "reason": receipt.get("reason"),
                    "label": (receipt.get("proposal") or {}).get("label"),
                    "provider_kind": provider.get("kind"),
                    "bridge": provider.get("bridge"),
                    "adapter_version": provider.get("adapter_version"),
                    "latency_ms": provider.get("latency_ms"),
                }
            )
        summary["receipts"] = world_side
        replay = api("GET", world["society"] + "/replay", params=world["scope"])
        summary["replay_verified"] = replay.get("replay_verified")
    finally:
        if not arguments.keep_stack:
            launch("down")
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    checks = summary.get("check", {}).get("checks", [])
    failed = [entry for entry in checks if not entry["ok"]]
    receipts_ok = all(
        entry["provider_kind"] == "external" and entry["bridge"] == "luanti"
        for entry in summary.get("receipts", [])
        if entry["status"] == "accepted"
    )
    print(
        json.dumps(
            {
                "run_folder": str(folder),
                "checks": len(checks),
                "failed": [entry["check"] for entry in failed],
                "receipts": len(summary.get("receipts", [])),
                "receipts_name_the_bridge": receipts_ok,
                "replay_verified": summary.get("replay_verified"),
            },
            indent=2,
        )
    )
    return 0 if checks and not failed and receipts_ok and summary.get("replay_verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())
