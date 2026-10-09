"""The scripted check of the Exulanica gate on a headless Luanti server: nobody at the keyboard.

    <checkout>/.venv/bin/python bridges/luanti/run/check.py [--port-base 19520]
        [--luanti-port 19529] [--minutes-speed 1] [--lives-s 20] [--keep-stack] [--scene FILE]
        [--against stack|fake] [--play NAME [--carry ITEMS] [--pictures]] [--invite]
        [--traveller-mind] [--scripted-model PLAN]
    <checkout>/.venv/bin/python bridges/luanti/run/check.py --api URL --token-file FILE
        --record FILE [--scene FILE] [--luanti-port 19529] [--minutes-speed 1] [--lives-s 20]
        [--play NAME [--carry ITEMS] [--pictures]] [--traveller-mind]

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
    world for ``--lives-s`` seconds (unless the world's minds lead it home first), and closes the
    gate once its player has left the game with the character away again.
4.  Reads the check's result and the mod's recording of every exchange, then the world's own
    records: the gate answered no ask (the world decides for a character that crossed), each ask
    about the character was decided by the world, no line said where the character was (the
    door's said frames) was told in the game, a mind the grant named decided for the character at
    least once (from the world's events), and the society replays with no game running.
5.  Writes the run's summary (no credential, no token) into the run folder and brings everything
    down (``--keep-stack`` leaves the stack up for a look in the browser).

``--against fake`` runs the same crossing against ``tools/fake_door.py`` instead, with no stack;
``--play NAME`` serves the world for a person to play in, and with ``--pictures`` the game's own
client plays one crossing there with nobody at the keyboard, walked by the director test mod, its
window alone captured at each moment (the README's "Pictures of a crossing").
``--scripted-model PLAN`` serves the stack's API with ``scripts/acceptance/scripted_model.py``
answering every model request from PLAN (``run/plans/``: the travellers' mind waits, or leaves),
with no provider, key or cost; the run keeps what it was asked and chose.

``--api URL --token-file FILE --record FILE`` joins a stack this check did not start, where a scene
was built for a take: it starts and stops no stack and builds nothing. That stack was started with
the ``luanti`` bridge declared (``tools/cross_once.py declare``). The world is the one the scene
builder's record names (``scripts/demo/build_scene.py --record``), its scene read from the scene
catalog at the record's digest, or from ``--scene`` when the catalog does not ship it; the society
the builder started (``--minds``) is read back, or, where the record names none, one is started over
the version. A paused society is played at ``--minutes-speed``; one already playing keeps its speed.
The world owner's token is read once from ``--token-file`` and stays in this process. The grant
this check issued is closed when it ends (revoking twice changes nothing); the stack keeps running.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shutil
import signal as signal_module
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


#: The mapping file the server loads and the deployment pins: the mod's default.
MAPPING_FILE = "luanti-minetest-game.v3.json"
SOCIETY_OF_THINGS = "exulanica-society/v7"


class Refused(SystemExit):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"check refused: {code}: {detail}")


def mapping_digest(name: str = MAPPING_FILE) -> str:
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical

    mapping = json.loads((MOD / "mapping" / name).read_text())
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


def build_scene(api: Api, folder: Path, token: str, scene: Path) -> dict[str, Any]:
    """``scene`` on a starter world, built through the public routes by the scene builder (without
    ``--minds``, so its beings keep their routines): the builder's record of what it placed."""
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
    return json.loads(record.read_text())


def scene_of_record(placed: dict[str, Any], scene: Path | None) -> Path:
    """The file of the scene a builder's record names: ``scene`` when given, else the scene
    catalog's, which the lock must name at the record's digest (read by the product's own scene
    reader). Either way the document's canonical digest is the record's."""
    sys.path.insert(0, str(CHECKOUT))
    from exulanica.canonical import sha256_of_canonical
    from exulanica.world.scenes import SCENES_DIRECTORY, SceneRefused, shipped_scene

    named = placed["scene"]
    if scene is None:
        try:
            shipped_scene(named["scene"], named["version"], named["sha256"])
        except SceneRefused:
            raise Refused(
                "scene",
                f"the scene catalog ships no {named['scene']} v{named['version']} at the "
                "record's digest; name its file with --scene",
            ) from None
        scene = SCENES_DIRECTORY / f"{named['scene']}.v{named['version']}.json"
    if sha256_of_canonical(json.loads(scene.read_text())).hex() != named["sha256"]:
        raise Refused("scene", f"{scene.name} is not the scene the record built")
    return scene


def crossing_world(api: Api, placed: dict[str, Any], scene: Path) -> dict[str, Any]:
    """The world a scene builder's record names, the gate travellers come through, and its society
    of things: the one the builder started (``--minds``), read back, or else one started over the
    version (asked again, the version's society is read back)."""
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
    words = json.loads(scene.read_text())["title"]
    if placed.get("entry_id"):
        # The words the world shows for itself: its saved world's title, which its owner may have
        # renamed; the scene's title is only what a builder first called it.
        words = api("GET", f"/world-entries/{placed['entry_id']}").get("title") or words
    world = {
        "version": placed["version_id"],
        "scope": {"world_id": placed["world_id"]},
        "region": placed["arrival"]["region_id"],
        "society": f"/world/versions/{placed['version_id']}/society",
        "gate": travellers.get("gate") or gates[0],
        "travellers": travellers,
        "words": words,
    }
    named = placed.get("society")
    if named:
        society = api("GET", world["society"], params=world["scope"])
        if society.get("society_id") != named["society_id"]:
            raise Refused(
                "society", f"the version's society is not {named['society_id']}, the record's"
            )
    else:
        society = api(
            "POST",
            world["society"],
            params=world["scope"],
            body={"region_id": world["region"], "profile": SOCIETY_OF_THINGS},
        )
    if society.get("profile") != SOCIETY_OF_THINGS:
        raise Refused("society", f"the version's society runs {society.get('profile')}")
    return world


def door_offers(api: Api) -> dict[str, bool]:
    """What this door offers that a crossing may use, from its published routes (``GET
    /openapi.json`` is public): whether a grant may say the world decides for its visitors (the
    grant body names the field), and whether a gate may call its visitors home (``POST
    /door/channel/home``)."""
    schema = api("GET", "/openapi.json")
    body = schema.get("components", {}).get("schemas", {}).get("IssueBody", {})
    return {
        "world_decides": "visitors_decided_by" in body.get("properties", {}),
        "calls_home": "/door/channel/home" in schema.get("paths", {}),
    }


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


def play(api: Api, world: dict[str, Any], speed: int) -> dict[str, Any]:
    """Play the world's society at ``speed`` unless it is playing already: a society someone else
    plays keeps its speed. Says which."""
    control = api("GET", world["society"] + "/control", params=world["scope"])
    if control["mode"] == "playing":
        return {"speed": control["speed"], "played_by_this_check": False}
    api(
        "PUT",
        world["society"] + "/control",
        params=world["scope"],
        body={"base_revision": control["revision"], "mode": "playing", "speed": speed},
    )
    return {"speed": speed, "played_by_this_check": True}


def scripted_record(run_dir: Path, folder: Path) -> dict[str, Any]:
    """What a scripted model was asked and chose in a run (the model, the rule and the option,
    never a header or a body), from the launcher's record of the run, which its run directory keeps
    once the stack is down; the call log is copied into the run folder."""
    try:
        scripted = json.loads((run_dir / "state.json").read_text())["scripted_model"]
    except (OSError, KeyError, ValueError):
        return {"read": False}
    asked = Path(scripted["log"])
    calls = asked.read_text().splitlines() if asked.exists() else []
    if calls:
        shutil.copy(asked, folder / "scripted-model-calls.jsonl")
    return {"plan_sha256": scripted["plan_sha256"], "calls": len(calls)}


#: The most pages of the world's events (256 events a page) read back for the characters' decisions.
EVENT_PAGES_MAXIMUM = 200


def character_decisions(api: Api, world: dict[str, Any], characters: set[str]) -> dict[str, Any]:
    """Who decided for the characters that crossed, from the world's own events: every decision a
    mind was asked for about one of them, counted by who was asked (``origin``) and what the
    minute did with it (``disposition``), with the reasons a decision was not applied. Read newest
    first, back to the last character's arrival."""
    counts: dict[str, int] = {}
    reasons: dict[str, int] = {}
    unseen = set(characters)
    before = None
    for _ in range(EVENT_PAGES_MAXIMUM):
        params = dict(world["scope"]) | ({"before": before} if before else {})
        page = api("GET", world["society"] + "/events", params=params)
        for event in page.get("events", []):
            subject = str(event.get("subject_id"))
            if subject not in characters:
                continue
            if event.get("event_kind") == "thing_arrived":
                unseen.discard(subject)
            if event.get("event_kind") != "decision_applied":
                continue
            document = event.get("document") or {}
            key = f"{document.get('origin')} {document.get('disposition')}"
            counts[key] = counts.get(key, 0) + 1
            if document.get("disposition") != "applied":
                reason = str(document.get("reason"))
                reasons[reason] = reasons.get(reason, 0) + 1
        before = page.get("next")
        if not before or not unseen:
            break
    return {"counts": counts, "not_applied": reasons}


def world_things_held(api: Api, world: dict[str, Any], character: str) -> list[str]:
    """The kinds of the world's own things (placed by its author) the character holds now, from
    the society's current state; what it brought in is not among them."""
    state = api("GET", world["society"], params=world["scope"]).get("state") or {}
    return sorted(
        str((thing.get("kind") or {}).get("kind"))
        for thing in state.get("things", [])
        if thing.get("held_by") == character and thing.get("placed_id")
    )


def close_grant(api: Api, grant_id: str) -> bool:
    """End the grant this check issued, in a world it did not build: revoking twice changes
    nothing. False when the stack did not answer."""
    try:
        api("POST", f"/door/grants/{grant_id}/revoke", expected=(200,))
    except (Refused, OSError):
        return False
    return True


def luanti_world(
    folder: Path,
    port: int,
    door_url: str,
    scenario: str = "crossing_door",
    *,
    player: str | None = None,
    carry: str | None = None,
    lives_s: float = 20.0,
    calls_home: bool = False,
    mapping: str = MAPPING_FILE,
    call_home_on_signal: bool = False,
    director: bool = False,
) -> Path:
    """A fresh flat world and its server settings: a check world with the check mod (told how long
    the world's owner lets a character live in the world, ``lives_s``, and whether the door lets
    a gate call its visitors home, ``calls_home``), or, given a ``player``, a world for a person to
    play in, with the gate at the spawn and only that name let in, starting with ``carry`` (the
    game's own item words) in the hand when given. With ``director`` the player's world also loads
    the director (``check/exulanica_gate_director``), which walks that player for a pictured run."""
    world = folder / "world"
    world.mkdir(parents=True)
    mods = "load_mod_exulanica_gate = true\n"
    if player is None:
        mods += "load_mod_exulanica_gate_check = true\n"
    elif director:
        mods += "load_mod_exulanica_gate_director = true\n"
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
        f"exulanica_gate.mapping = {mapping}",
        "exulanica_gate.record_exchanges = true",
    ]
    if player is None:
        settings += [
            "exulanica_gate.world_words = The check's square",
            "exulanica_gate.check_mode = true",
            f"exulanica_gate_check.scenario = {scenario}",
            f"exulanica_gate_check.lives_s = {round(lives_s)}",
            f"exulanica_gate_check.home_route = {'true' if calls_home else 'false'}",
            "exulanica_gate_check.call_home_on_signal = "
            + ("true" if call_home_on_signal else "false"),
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
        if director:
            settings += [f"exulanica_gate_director.player = {player}"]
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


def run_luanti(folder: Path, world: Path, port: int, credential: str | None, limit_s: int) -> int:
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


def lines_kept_in_the_world(exchanges: list[dict[str, Any]], told: list[str]) -> dict[str, int]:
    """How many lines said where the character was reached the gate (the door's said frames, read
    from the mod's recording of every poll), and how many of those the player was told in the game:
    the world's lines are seen in Exulanica, so the second must be 0."""
    said = []
    for entry in exchanges:
        if not (
            entry.get("exchange")
            and str(entry.get("path", "")).startswith("/door/channel/frames")
            and entry.get("status") == 200
        ):
            continue
        for frame in json.loads(entry.get("response_text") or "{}").get("frames", []):
            if frame.get("kind") == "said" and isinstance(frame.get("line"), str):
                said.append(frame["line"])
    return {
        "said_frames": len(said),
        "told_in_the_game": sum(1 for line in said if any(line in text for text in told)),
    }


def crossing_timings(exchanges: list[dict[str, Any]]) -> dict[str, Any]:
    """How long the first crossing's steps took, by the gate mod's own clock (its recording's
    ``t_ms``): from the walk-in (the arrival sent) to the world's answer and to the character's
    placing (the arrived frame read), the character's life in the world (to the departed frame),
    and the delivery report's answer; and how long the door took to answer the arrival itself.
    A step the run never reached is left out."""
    marks: dict[str, int] = {}
    for entry in exchanges:
        if "mark" in entry and entry["mark"] not in marks:
            marks[entry["mark"]] = int(entry["t_ms"])
    posted = next(
        (
            entry
            for entry in exchanges
            if entry.get("exchange") and entry.get("path") == "/door/channel/arrivals"
        ),
        None,
    )
    steps = (
        ("walk_in_to_answer_ms", "arrival_sent", None),
        ("walk_in_to_placed_ms", "arrival_sent", "arrived"),
        ("placed_to_departed_ms", "arrived", "departed"),
        ("departed_to_delivered_ms", "departed", "delivered"),
    )
    timings: dict[str, Any] = {}
    for name, start, end in steps:
        if start not in marks:
            continue
        if end is None:
            if posted is not None:
                timings[name] = int(posted["t_ms"]) - marks[start]
        elif end in marks:
            timings[name] = marks[end] - marks[start]
    if posted is not None and posted.get("ms") is not None:
        timings["arrival_request_ms"] = int(posted["ms"])
    return timings


#: How long after the called-home crossing's arrival the check calls home anyway, with
#: ``--call-home-when-holding``, when the character has taken hold of nothing of the world.
CALL_HOME_LIMIT_S = 150.0


#: How long a character lives in the world before its owner sends it home, at 1x, unless
#: ``--lives-s`` says otherwise: two world minutes and a little more, so the world has asked about
#: it and decided at least once.
LIVES_S = 20.0


def act_as_owner(
    api: Api,
    grant_id: str,
    recorded: Path,
    server: subprocess.Popen,
    limit_s: int,
    lives_s: float = LIVES_S,
    closes_after: int = 2,
    *,
    holding: Any = None,
    signal: Path | None = None,
    signal_limit_s: float = CALL_HOME_LIMIT_S,
) -> dict[str, Any]:
    """Wait for the check's server to stop, acting meanwhile as the world's owner, each act once,
    from the mod's recording: send the character home once it has lived in the world for
    ``lives_s``, unless it has left by itself (where minds decide for it), and close the gate a
    few seconds after its ``closes_after``-th arrival (by then its player has left the game; 0:
    never). Given ``signal``, write it once the character of the second crossing (the one its
    player calls home) holds a thing of the world, as ``holding`` reads it, or ``signal_limit_s``
    after it arrived: the check mod calls it home then."""
    acts: dict[str, Any] = {}
    held_read_at = 0.0
    arrivals: list[tuple[float, str | None]] = []
    departed: set[str | None] = set()
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
        departed |= {mark.get("subject") for mark in marks if mark["mark"] == "departed"}
        now = time.monotonic()
        if arrivals and not {"sent_home", "left_by_itself"} & acts.keys():
            arrived_at, character = arrivals[0]
            lived = {"thing_id": character, "after_arrival_s": round(now - arrived_at, 1)}
            if character in departed:
                acts["left_by_itself"] = lived
            elif now - arrived_at >= lives_s:
                # 404: it left between the recording's last read and this call.
                sent = api(
                    "POST",
                    f"/door/grants/{grant_id}/send-away",
                    body={"thing_id": character},
                    expected=(202, 404),
                )
                acts["sent_home" if "sent_away" in sent else "left_by_itself"] = lived
        if signal is not None and len(arrivals) >= 2 and "call_home_signal" not in acts:
            arrived_at, character = arrivals[1]
            if now - held_read_at >= 2:
                held_read_at = now
                held = holding(character) if holding and character else []
                if held or now - arrived_at >= signal_limit_s:
                    signal.parent.mkdir(parents=True, exist_ok=True)
                    signal.write_text("call home\n")
                    acts["call_home_signal"] = {
                        "holding": held,
                        "after_arrival_s": round(now - arrived_at, 1),
                    }
        if closes_after and len(arrivals) >= closes_after and "revoked" not in acts:
            arrived_at = arrivals[closes_after - 1][0]
            if now - arrived_at >= 5:
                api("POST", f"/door/grants/{grant_id}/revoke", expected=(200,))
                acts["revoked"] = {"after_arrival_s": round(now - arrived_at, 1)}
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
            mapping=arguments.mapping,
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
    exchanges = [json.loads(line) for line in (folder / "exchanges.jsonl").read_text().splitlines()]
    summary["lines"] = lines_kept_in_the_world(
        exchanges, summary.get("check", {}).get("told") or []
    )
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
        "the character was called home once": sum(
            1 for entry in sent if entry["route"] == "/door/channel/home"
        )
        == 1,
        # The stand-in door says two lines when the sword is given.
        "the lines said where the character was reached the gate, and none was told in the game": (
            summary["lines"]["said_frames"] >= 2 and summary["lines"]["told_in_the_game"] == 0
        ),
    }
    return summary


def take_census(arguments: argparse.Namespace) -> int:
    """The check mod's census on a fresh world with no door and no credential: the game's craft
    items and tools, each with its type, inventory picture, groups and stack size, copied into the
    run folder (ignored, never committed: it names the game's own pictures)."""
    folder = CHECKOUT / ".exulanica" / "luanti-checks" / time.strftime("%Y%m%d-%H%M%S-census")
    folder.mkdir(parents=True)
    world = luanti_world(folder, arguments.luanti_port, "http://127.0.0.1:1", "census")
    exit_code = run_luanti(folder, world, arguments.luanti_port, None, 120)
    written = world / "exulanica_gate_check" / "census.json"
    if not written.exists():
        raise Refused("census", f"no census written; see {folder}/server.log")
    shutil.copy(written, folder / "census.json")
    items = json.loads(written.read_text())["items"]
    print(
        json.dumps(
            {
                "run_folder": str(folder),
                "luanti_exit": exit_code,
                "items": len(items),
                "by_type": {
                    kind: sum(1 for item in items if item["type"] == kind)
                    for kind in sorted({item["type"] for item in items})
                },
            },
            indent=2,
        )
    )
    return 0


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
        folder,
        arguments.luanti_port,
        api.base,
        player=arguments.play,
        carry=arguments.carry,
        mapping=arguments.mapping,
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


# A pictured run -----------------------------------------------------------------------------------

#: What the pictured run's player starts holding unless ``--carry`` says otherwise: the game's
#: torches, one of which crosses as the mapping's lantern.
PICTURES_CARRY = "default:torch 5"
#: The size the client draws the game at, in the window's points: width and height.
SCREEN = (1280, 720)
#: The client's settings for a pictured run: a window of a fixed size that keeps drawing while
#: another window has the focus, no sound, and nothing remembered from the run.
CLIENT_SETTINGS = (
    f"screen_w = {SCREEN[0]}",
    f"screen_h = {SCREEN[1]}",
    "fullscreen = false",
    "autosave_screensize = false",
    "pause_on_lost_focus = false",
    "fps_max_unfocused = 30",
    "mute_sound = true",
    "show_debug = false",
)
#: Lists the windows of one process (its id the first argument) as JSON: id, layer and size. Only
#: that process's windows leave the script.
WINDOWS_OF = """
ObjC.import('CoreGraphics');
function run(argv) {
  const pid = Number(argv[0]);
  const listed = ObjC.castRefToObject(
    $.CGWindowListCopyWindowInfo($.kCGWindowListOptionAll, $.kCGNullWindowID));
  const found = [];
  for (let index = 0; index < listed.count; index++) {
    const window = listed.objectAtIndex(index);
    if (ObjC.unwrap(window.objectForKey('kCGWindowOwnerPID')) !== pid) continue;
    const bounds = ObjC.deepUnwrap(window.objectForKey('kCGWindowBounds'));
    found.push({id: ObjC.unwrap(window.objectForKey('kCGWindowNumber')),
      layer: ObjC.unwrap(window.objectForKey('kCGWindowLayer')),
      width: bounds.Width, height: bounds.Height});
  }
  return JSON.stringify(found);
}
"""


class Director:
    """The director mod's two files in its world folder: the commands this run writes (the whole
    list, replaced at once, so the mod never reads half a line) and the answers the mod appends,
    with when its player joined and left."""

    def __init__(self, world: Path) -> None:
        self.folder = world / "exulanica_gate_director"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.commands: list[str] = []

    def answers(self) -> list[dict[str, Any]]:
        done = self.folder / "done.jsonl"
        if not done.exists():
            return []
        # Text after the last newline is a line still being written.
        return [json.loads(line) for line in done.read_text().split("\n")[:-1]]

    def wait_event(self, event: str, limit_s: float) -> dict[str, Any]:
        ends = time.monotonic() + limit_s
        while time.monotonic() < ends:
            for answer in self.answers():
                if answer.get("event") == event:
                    return answer
            time.sleep(0.25)
        raise Refused("director", f"its player never {event} in {limit_s:.0f} s")

    def act(self, act: str, limit_s: float = 15, **fields: Any) -> dict[str, Any]:
        """Ask for one act and wait for its answer."""
        number = len(self.commands) + 1
        self.commands.append(json.dumps({"n": number, "act": act, **fields}))
        written = self.folder / "commands.jsonl.new"
        written.write_text("\n".join(self.commands) + "\n")
        written.replace(self.folder / "commands.jsonl")
        ends = time.monotonic() + limit_s
        while time.monotonic() < ends:
            for answer in self.answers():
                if answer.get("n") == number:
                    return answer
            time.sleep(0.1)
        raise Refused("director", f"no answer to {act} in {limit_s:.0f} s")

    def told(self) -> list[str]:
        told = self.folder / "told.jsonl"
        if not told.exists():
            return []
        return [json.loads(line)["told"] for line in told.read_text().split("\n")[:-1]]


class Client:
    """The game's own client for a pictured run: started with ``open -g``, so it takes the focus
    from nobody at this Mac; found again by the settings file in its run folder, which no other
    process names; quit when the run ends."""

    def __init__(self, folder: Path, port: int, name: str, password: Path) -> None:
        self.settings = folder / "client.conf"
        self.settings.write_text("\n".join([*CLIENT_SETTINGS, ""]))
        app = INSTALL / "app" / "luanti.app"
        self.binary = str(app / "Contents" / "MacOS" / "luanti")
        subprocess.run(
            [
                "open",
                "-g",
                "-n",
                "-a",
                str(app),
                "--env",
                f"LUANTI_USER_PATH={INSTALL / 'user'}",
                "--args",
                "--go",
                "--address",
                "127.0.0.1",
                "--port",
                str(port),
                "--name",
                name,
                "--password-file",
                str(password),
                "--config",
                str(self.settings),
                "--logfile",
                str(folder / "client.log"),
            ],
            check=True,
            capture_output=True,
        )
        self.pid = self._find(limit_s=30)

    def _ours(self, pid: int | None = None) -> list[int]:
        listed = subprocess.run(
            ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
        ).stdout
        found = []
        for line in listed.splitlines():
            number, _, command = line.strip().partition(" ")
            if command.startswith(self.binary) and str(self.settings) in command:
                found.append(int(number))
        return [number for number in found if pid is None or number == pid]

    def _find(self, limit_s: float) -> int:
        ends = time.monotonic() + limit_s
        while time.monotonic() < ends:
            found = self._ours()
            if found:
                return found[0]
            time.sleep(0.5)
        raise Refused("client", f"the client did not start in {limit_s:.0f} s")

    def window(self, limit_s: float) -> int:
        """The client's game window: its largest window on the normal layer."""
        ends = time.monotonic() + limit_s
        while time.monotonic() < ends:
            listed = subprocess.run(
                ["osascript", "-l", "JavaScript", "-e", WINDOWS_OF, str(self.pid)],
                capture_output=True,
                text=True,
                check=False,
            )
            windows = json.loads(listed.stdout or "[]") if listed.returncode == 0 else []
            drawn = [
                window
                for window in windows
                if window["layer"] == 0 and window["width"] >= 640 and window["height"] >= 360
            ]
            if drawn:
                return max(drawn, key=lambda window: window["width"] * window["height"])["id"]
            time.sleep(1)
        raise Refused("client", f"the client showed no game window in {limit_s:.0f} s")

    def capture(self, window: int, path: Path) -> None:
        """That one window's picture, without its shadow and without a sound, cut to what the game
        draws: the title bar above it is the system's, and names the client."""
        from PIL import Image

        whole = path.with_name(path.stem + ".window.png")
        subprocess.run(["screencapture", "-x", "-o", f"-l{window}", str(whole)], check=True)
        if not whole.exists() or whole.stat().st_size == 0:
            raise Refused("picture", f"screencapture wrote no picture to {whole.name}")
        with Image.open(whole) as image:
            drawn = round(image.width * SCREEN[1] / SCREEN[0])
            image.crop((0, image.height - drawn, image.width, image.height)).save(path)
        whole.unlink()

    def quit(self) -> str:
        """Ask the client to quit, and make sure it has: it is this run's own process, found by its
        settings file."""
        if not self._ours(self.pid):
            return "gone before the end"
        os.kill(self.pid, signal_module.SIGTERM)
        ends = time.monotonic() + 20
        while time.monotonic() < ends:
            if not self._ours(self.pid):
                return "quit"
            time.sleep(0.5)
        os.kill(self.pid, signal_module.SIGKILL)
        return "killed after 20 s"


class Recording:
    """The gate mod's recording of a run, read on as it grows."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.start = 0
        self.marks: list[dict[str, Any]] = []

    def first(self, name: str) -> dict[str, Any] | None:
        marks, self.start = read_marks(self.path, self.start)
        self.marks += marks
        return next((mark for mark in self.marks if mark["mark"] == name), None)

    def wait(self, name: str, limit_s: float) -> dict[str, Any] | None:
        ends = time.monotonic() + limit_s
        while time.monotonic() < ends:
            found = self.first(name)
            if found:
                return found
            time.sleep(0.5)
        return None


def wait_for_home(
    recording: Recording,
    director: Director,
    holding: Any,
    character: str,
    arrived_at: float,
    arguments: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Wait for the character to come home, the player calling it home with ``/comehome`` when it
    has kept a thing of the world for ``--leave-wait-s`` without leaving, or has held nothing for
    ``--call-home-limit-s`` after it arrived. Returns the departure the gate recorded and what the
    run did meanwhile."""
    acts: dict[str, Any] = {}
    held_since = None
    read_at = 0.0
    ends = time.monotonic() + arguments.limit_s
    while True:
        departed = recording.first("departed")
        now = time.monotonic()
        if departed:
            return departed, acts
        if now > ends:
            raise Refused("pictures", f"the character was not home {arguments.limit_s} s on")
        if "called_home" not in acts and now - read_at >= 2:
            read_at = now
            held = holding(character)
            if held and held_since is None:
                held_since = now
                acts["held"] = {"kinds": held, "after_arrival_s": round(now - arrived_at, 1)}
            waited = held_since is not None and now - held_since >= arguments.leave_wait_s
            empty = held_since is None and now - arrived_at >= arguments.call_home_limit_s
            if waited or empty:
                called = director.act("command", name="comehome")
                acts["called_home"] = {
                    "after_arrival_s": round(now - arrived_at, 1),
                    "holding": held,
                    "answered": called.get("detail"),
                }
        time.sleep(0.5)


def pictured_run(
    arguments: argparse.Namespace,
    folder: Path,
    api: Api,
    world: dict[str, Any],
    credential: str,
    holding: Any,
    summary: dict[str, Any],
) -> Path:
    """One crossing played by the game's own client with nobody at the keyboard: the director
    walks the player into the gate holding torches, the character lives in the world until it
    comes home (by its own choice, or called home as ``wait_for_home`` says), and the player takes
    what came home into the hand and opens the inventory. The client's window alone is captured at
    each moment into ``<run folder>/pictures``. The run's result, in the check mod's result's
    shape, is the summary's ``check`` from the start, so a run refused part way says how far it
    got. Returns the world."""
    carry = arguments.carry or PICTURES_CARRY
    luanti = luanti_world(
        folder,
        arguments.luanti_port,
        api.base,
        player=arguments.play,
        carry=carry,
        mapping=arguments.mapping,
        director=True,
    )
    recording = Recording(luanti / "exulanica_gate" / "exchanges.jsonl")
    password = folder / "player-password"
    password.write_text(secrets.token_urlsafe(18))
    password.chmod(0o600)
    director = Director(luanti)
    pictures = folder / "pictures"
    pictures.mkdir()
    checks: list[dict[str, Any]] = []
    taken: list[dict[str, Any]] = []
    result: dict[str, Any] = {
        "profile": "exulanica-gate.pictured-run/v1",
        "checks": checks,
        "pictures": taken,
    }
    summary["check"] = result
    started = time.monotonic()

    def verdict(name: str, ok: Any, detail: Any = None) -> None:
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            raise Refused("pictures", f"{name}: {detail}")

    server = start_luanti(folder, luanti, arguments.luanti_port, credential)
    client = None
    try:
        client = Client(folder, arguments.luanti_port, arguments.play, password)
        director.wait_event("joined", 90)
        verdict("the client joined as the player", True)
        window = client.window(limit_s=30)

        def take(moment: str) -> None:
            path = pictures / f"{len(taken) + 1}-{moment}.png"
            client.capture(window, path)
            taken.append(
                {
                    "moment": moment,
                    "file": path.name,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "bytes": path.stat().st_size,
                    "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                    "run_s": round(time.monotonic() - started, 1),
                }
            )

        director.act("hold")
        stood = director.act("stand", distance=3.5, pitch_deg=4)
        verdict("the player stood before the gate", stood["ok"], stood.get("detail"))
        # The client draws the blocks around its new place.
        time.sleep(4)
        take("before-the-gate")
        walked = director.act("walk_in", limit_s=25, speed=4)
        verdict(
            "the player walked into the light and the gate put them through",
            walked["ok"],
            walked.get("detail"),
        )
        director.act("look_back", distance=3.5, pitch_deg=4)
        time.sleep(1)
        take("crossing")
        arrived = recording.wait("arrived", limit_s=180)
        verdict("the character arrived in the world", arrived, "no arrived frame in 180 s")
        arrived_at = time.monotonic()
        time.sleep(1.5)
        take("away")
        departed, acts = wait_for_home(
            recording, director, holding, str(arrived["subject"]), arrived_at, arguments
        )
        result["owner_acts"] = acts
        result["came_home"] = {"delivered": departed.get("delivered"), "why": departed.get("why")}
        time.sleep(1.5)
        brought = [str(item) for item in departed.get("delivered") or []]
        # What the world gave: whatever came home that the player did not start with.
        started_with = {stuff.split()[0] for stuff in carry.split(",") if stuff.strip()}
        given = [item for item in brought if item not in started_with]
        if given:
            director.act("wield", item=given[0])
            time.sleep(1)
        take("home")
        director.act("inventory")
        time.sleep(1.5)
        take("inventory")
        director.act("close")
        contents = director.act("contents").get("contents") or []
        held_now = {entry["item"] for entry in contents}
        # A character may come home with nothing (it gave away what it carried); came_home says so.
        verdict(
            "what came home is in the player's inventory",
            set(brought) <= held_now,
            {"brought": brought, "inventory": sorted(held_now)},
        )
        director.act("release")
    finally:
        if client is not None:
            result["client"] = client.quit()
        server.terminate()
        server.wait(timeout=30)
        result["luanti_exit"] = server.returncode
        password.unlink(missing_ok=True)
        result["told"] = director.told()
    return luanti


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
    parser.add_argument(
        "--pictures",
        action="store_true",
        help="with --play NAME: the game's client joins as NAME, started in the background, and "
        "a director walks it through the gate and back with nobody at the keyboard; only that "
        "window is captured, at each moment, into the run folder's pictures (macOS)",
    )
    parser.add_argument(
        "--leave-wait-s",
        type=float,
        default=240.0,
        help="with --pictures: how long the character may keep a thing of the world without "
        "leaving before its player calls it home",
    )
    parser.add_argument(
        "--scene",
        type=Path,
        default=None,
        help="the scene to build; with --api, the file of the scene the record names, where the "
        "scene catalog does not ship it",
    )
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
    parser.add_argument(
        "--lives-s",
        type=float,
        default=LIVES_S,
        help="how long the world's owner lets the character live in the world before sending it "
        "home, unless the world's minds lead it home first",
    )
    parser.add_argument(
        "--scripted-model",
        metavar="PLAN",
        type=Path,
        help="serve the stack's API with a scripted model answering from PLAN (no provider, no "
        "key, no cost): with --traveller-mind, the travellers' mind is asked of it",
    )
    parser.add_argument(
        "--call-home-when-holding",
        action="store_true",
        help="the check's player calls its character home only once it holds a thing of the world "
        "(read from the society's state), or after --call-home-limit-s",
    )
    parser.add_argument(
        "--call-home-limit-s",
        type=float,
        default=CALL_HOME_LIMIT_S,
        help="with --call-home-when-holding: when to call home anyway, in seconds after it arrived",
    )
    parser.add_argument(
        "--mapping",
        default=MAPPING_FILE,
        help="the published mapping version the server loads and the deployment pins, by its file "
        f"name in mod/exulanica_gate/mapping (default: {MAPPING_FILE}, the mod's default)",
    )
    parser.add_argument(
        "--census",
        action="store_true",
        help="list the game's items (craft items and tools), for choosing by hand which may cross "
        "as themselves; starts no stack and no gate",
    )
    parser.add_argument(
        "--api",
        metavar="URL",
        help="join a stack this check did not start, at its API's address, with --token-file and "
        "--record; it is left running",
    )
    parser.add_argument(
        "--token-file", type=Path, help="with --api: the world owner's token, read once"
    )
    parser.add_argument(
        "--record",
        type=Path,
        help="with --api: the scene builder's record of the world to cross into",
    )
    arguments = parser.parse_args(argv)
    if "/" in arguments.mapping or not (MOD / "mapping" / arguments.mapping).is_file():
        parser.error(f"--mapping names no published mapping file: {arguments.mapping}")
    joined = arguments.api is not None
    if [arguments.token_file is not None, arguments.record is not None] != [joined, joined]:
        parser.error("--api, --token-file and --record go together")
    if joined and (
        arguments.against == "fake"
        or arguments.keep_stack
        or arguments.invite
        or arguments.scripted_model
    ):
        # An invite is redeemed with the bridge's own credential, which whoever declared the bridge
        # on that stack holds; the stack's model is whoever started it.
        parser.error(
            "--api joins a running stack: no --against fake, --keep-stack, --invite or "
            "--scripted-model"
        )
    if arguments.pictures and (not arguments.play or arguments.invite):
        parser.error("--pictures plays a --play NAME world opened by the server's credential")
    if arguments.census:
        return take_census(arguments)
    if not joined:
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
    folder = (
        CHECKOUT
        / ".exulanica"
        / "luanti-checks"
        / time.strftime("%Y%m%d-%H%M%S-joined" if joined else "%Y%m%d-%H%M%S")
    )
    folder.mkdir(parents=True)
    summary: dict[str, Any] = {
        "profile": "exulanica-gate.check-run/v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "adapter_version": adapter["adapter_version"],
        "mapping_file": arguments.mapping,
        "mapping_sha256": mapping_digest(arguments.mapping),
    }
    bridge_credential = None
    if joined:
        api = Api(arguments.api.rstrip("/"), arguments.token_file.read_text().strip())
        summary["stack"] = {
            "api": api.base,
            "started_by_this_check": False,
            "record": str(arguments.record),
        }
    else:
        # The bridge's own credential redeems invites; only its digest is declared, and the
        # credential reaches the Luanti server's environment alone, and only in an invite check.
        bridge_credential = secrets.token_urlsafe(32)
        bridges = [
            {
                "bridge": "luanti",
                "label": "Luanti",
                "game": "Luanti (Minetest Game)",
                "run_by": "server",
                "ai": False,
                "credential_sha256": hashlib.sha256(bridge_credential.encode()).hexdigest(),
                "mapping_sha256": [summary["mapping_sha256"]],
                "adapter_versions": [adapter["adapter_version"]],
                "listed": False,
                "workspaces": "synthetic",
            }
        ]
        declared = folder / "door-bridges.json"
        declared.write_text(json.dumps(bridges))
        scripted_api = (
            ["--scripted-model", str(arguments.scripted_model.resolve())]
            if arguments.scripted_model
            else []
        )
        try:
            started = launch(
                "up",
                "--port-base",
                str(arguments.port_base),
                "--society-playback",
                "--no-derivative-worker",
                "--door-bridges",
                str(declared),
                "--society-of-things",
                *scripted_api,
            )
        except Refused:
            # A start that failed part way (an API that never answered) may leave its database and
            # state behind: bring them down before saying so.
            subprocess.run(
                [sys.executable, str(LAUNCH), "down", "--worktree", str(CHECKOUT)],
                cwd=CHECKOUT,
                capture_output=True,
                check=False,
            )
            raise
        state = json.loads(started[: started.rindex("}") + 1])
    try:
        if joined:
            placed = json.loads(arguments.record.read_text())
            scene = scene_of_record(placed, arguments.scene)
        else:
            token = (Path(state["run_dir"]) / "token").read_text().strip()
            api = Api(f"http://127.0.0.1:{state['ports']['api']}", token)
            summary["stack"] = {"api": api.base, "started_by_this_check": True}
            placed = build_scene(api, folder, token, arguments.scene)
            del token
            scene = arguments.scene
        offered = [bridge["bridge"] for bridge in api("GET", "/door/bridges")["bridges"]]
        if "luanti" not in offered:
            raise Refused(
                "bridge",
                "the stack offers this workspace no luanti bridge: start it with --door-bridges "
                "and the file tools/cross_once.py declare writes",
            )
        world = crossing_world(api, placed, scene)
        from exulanica.canonical import sha256_of_canonical

        summary["scene"] = {
            "file": scene.name,
            # The digest a scene lock names: the document's canonical form, not its file's bytes.
            "sha256": sha256_of_canonical(json.loads(scene.read_text())).hex(),
            "travellers": world["travellers"],
        }
        summary["playback"] = play(api, world, arguments.minutes_speed)
        offers = door_offers(api)
        summary["door_offers"] = offers
        grant = {
            "visitors_maximum": 1,
            "kinds": ["player"],
            "gate": world["gate"],
            "may_carry_in": True,
            "may_carry_out": True,
            "world_words": world["words"],
            **opened_to_travellers(
                world["travellers"], offers["world_decides"], arguments.traveller_mind
            ),
        }
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
        # The mind the grant gave travellers, a model the manifest offers, or None for the routine.
        summary["traveller_mind"] = grant.get("traveller")
        if arguments.play and not arguments.pictures:
            if arguments.invite:
                # A person types the code their world shows them; this check shows none.
                raise Refused(
                    "invite-play", "--play serves a gate opened by the server's credential"
                )
            play_until_stopped(arguments, folder, api, world, credential, summary)
            return 0

        def holding(character: str) -> list[str]:
            return world_things_held(api, world, character)

        if arguments.pictures:
            if not offers["calls_home"]:
                raise Refused(
                    "call-home", "this door publishes no home route to call a character by"
                )
            luanti = pictured_run(arguments, folder, api, world, credential, holding, summary)
            del credential, invite, bridge_credential
            result = summary["check"]
            summary["owner_acts"] = result.get("owner_acts", {})
            summary["luanti_exit"] = result.get("luanti_exit")
            recorded = luanti / "exulanica_gate" / "exchanges.jsonl"
        else:
            luanti = luanti_world(
                folder,
                arguments.luanti_port,
                api.base,
                "crossing_invite" if arguments.invite else "crossing_door",
                lives_s=arguments.lives_s,
                calls_home=offers["calls_home"],
                mapping=arguments.mapping,
                call_home_on_signal=arguments.call_home_when_holding,
            )
            if arguments.call_home_when_holding and not offers["calls_home"]:
                raise Refused(
                    "call-home", "this door publishes no home route to call a character by"
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
            # The gate closes a few seconds after the last crossing the check mod plays, the one
            # whose player leaves the game; an invite's check plays none such.
            closes_after = 0 if arguments.invite else (3 if offers["calls_home"] else 2)
            # The file the check mod waits for before its player calls the character home.
            signal = None
            if arguments.call_home_when_holding:
                signal = luanti / "exulanica_gate_check" / "call_home"
            summary["owner_acts"] = act_as_owner(
                api,
                summary["grant_id"],
                recorded,
                server,
                arguments.limit_s,
                arguments.lives_s,
                closes_after,
                holding=holding,
                signal=signal,
                signal_limit_s=arguments.call_home_limit_s,
            )
            exit_code = server.returncode
            summary["luanti_exit"] = exit_code
            result_file = luanti / "exulanica_gate_check" / "result.json"
            if not result_file.exists():
                raise Refused(
                    "no-result", f"the check mod wrote no result; see {folder}/server.log"
                )
            result = json.loads(result_file.read_text())
            summary["check"] = result
        shutil.copy(recorded, folder / "exchanges.jsonl")
        exchanges = [json.loads(line) for line in recorded.read_text().splitlines()]
        summary["timings"] = crossing_timings(exchanges)
        summary["answers_posted"] = sum(
            1 for entry in exchanges if entry.get("path") == "/door/channel/answers"
        )
        summary["home_calls"] = sum(
            1 for entry in exchanges if entry.get("path") == "/door/channel/home"
        )
        summary["lines"] = lines_kept_in_the_world(exchanges, result.get("told") or [])
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
        characters = {
            str(mark["subject"])
            for mark in exchanges
            if mark.get("mark") == "arrived" and mark.get("subject")
        }
        summary["character_decisions"] = character_decisions(api, world, characters)
        replay = api("GET", world["society"] + "/replay", params=world["scope"])
        summary["replay_verified"] = replay.get("replay_verified")
        ended = api("GET", f"/door/grants/{summary['grant_id']}")["grant"]
        summary["grant_at_the_end"] = {key: ended.get(key) for key in ("state", "ended_reason")}
    finally:
        if joined:
            # Nothing of the run stays open in a world it did not build; the stack keeps running.
            if "grant_id" in summary:
                summary["grant_closed"] = close_grant(api, summary["grant_id"])
        elif not arguments.keep_stack:
            launch("down")
            if arguments.scripted_model:
                summary["scripted_model"] = scripted_record(Path(state["run_dir"]), folder)
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    checks = summary.get("check", {}).get("checks", [])
    failed = [entry for entry in checks if not entry["ok"]]
    # The gate decided nothing: it posted no answer, and no ask about the character was settled by
    # an answer from it.
    world_decided = summary.get("answers_posted") == 0 and not any(
        entry["status"] == "accepted" and entry["provider_kind"] == "external"
        for entry in summary.get("receipts", [])
    )
    lines = summary.get("lines", {})
    # Where the grant named a mind for travellers, that mind decided for the character at least
    # once: asking it is not enough, since a minute may refuse what it answered.
    decided = summary.get("character_decisions", {}).get("counts", {})
    mind_decided = not summary.get("traveller_mind") or decided.get("model applied", 0) > 0
    print(
        json.dumps(
            {
                "run_folder": str(folder),
                "checks": len(checks),
                "failed": [entry["check"] for entry in failed],
                "asks_left_to_the_world": len(summary.get("receipts", [])),
                "the_world_decided": world_decided,
                "came_home": summary.get("check", {}).get("came_home"),
                "called_home": summary.get("check", {}).get("called_home"),
                "lines": lines,
                "character_decisions": summary.get("character_decisions"),
                "mind_decided": mind_decided,
                "replay_verified": summary.get("replay_verified"),
            },
            indent=2,
        )
    )
    kept = lines.get("told_in_the_game") == 0
    return (
        0
        if checks
        and not failed
        and world_decided
        and kept
        and mind_decided
        and summary.get("replay_verified")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
