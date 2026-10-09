"""The 0 A.D. gate end to end: a soldier of a running match walks onto the gate, crosses into a
world on this checkout's stack, lives there as the world decides, leaves, and is back on the gate.

    <checkout>/.venv/bin/python bridges/zero_ad/run/check.py [--port-base 19500]
        [--game http://127.0.0.1:19508] [--match FILE] [--minutes-speed 1] [--lives-s 60]
        [--limit-s 900] [--look cc0-hoplite] [--scripted-model PLAN [--traveller-mind]]
        [--keep-stack]
    <checkout>/.venv/bin/python bridges/zero_ad/run/check.py --declare OUT [--label WORDS]
        [--game-words WORDS]
    <checkout>/.venv/bin/python bridges/zero_ad/run/check.py --api URL --token-file FILE
        --record FILE [--scene FILE] [--game http://127.0.0.1:19508] [--lives-s 60]
        [--traveller-mind]

The game runs first, on this machine, with its interface on (``pyrogenesis
--rl-interface=127.0.0.1:19508``). What this does, refusing by name at the first thing that is not
as expected:

1.  Starts this checkout's stack on one port slot (``scripts/acceptance/launch.py up
    --society-playback --society-of-things --door-bridges``) with one door bridge declared,
    ``zero-ad``, unlisted and offered to the run's synthetic workspace, pinning this adapter's
    mapping by its digest and admitting its version. The bridge's own credential is random and only
    its digest is declared; nothing here uses it.
2.  Builds the demo's scene on a starter world with ``scripts/demo/build_scene.py`` (no minds),
    plays its society of things, and issues a grant letting one hoplite in through the scene's
    gate, carrying nothing either way, with a channel credential that stays in this process. The
    stack, the scene and the grant are made as the Luanti check makes them
    (``bridges/luanti/run/check.py``, whose helpers this loads by its path), so both games cross
    into the same world.
3.  Starts the match (``--match``), stands the standard (the Athenian rally point flag) on a spot
    beside the first hoplite of the gate's player, and walks that hoplite onto it with a walk order
    of its own; a person may give the order in the window instead. Then runs the adapter's loop at
    its pace (``exulanica_zero_ad.bridge``): the hoplite on the gate is sent across and leaves the
    match, and the door's frames put it back on the gate when it departs.
4.  Acts as the world's owner: sends the visitor home once it has lived in the world for
    ``--lives-s`` seconds, unless its mind leads it home first; once the soldier is back in the
    match, revokes the grant, and stops once the adapter reads that the grant ended.
5.  Reads the world's records: the visitor arrived and departed, wears the look the mapping names
    (the version's look read), was decided for by the world, and its society replays with no game
    running; and the match's: the soldier left it at the gate and a hoplite of its owner stands on
    the gate again. Writes the run's summary and every exchange with the door and the game (no
    credential, no token) into ``.exulanica/zero-ad-checks/<time>/`` and brings the stack down
    (``--keep-stack`` leaves it up for a look in the browser).

``--declare OUT`` writes the bridge into the door bridge declarations a stack someone else starts
reads (``launch.py up --door-bridges OUT``) and stops: beside the bridges OUT already declares, so
one stack lets several games in (the Luanti tool's ``declare`` writes its file anew, so it goes
first), and in place of an earlier entry of this bridge. The bridge is declared in neutral words
(``--label`` and ``--game-words``, by default "another open-source game", each one line of 1 to 80
characters as the door takes them), since a film or a demo names no game.
``--api URL --token-file FILE --record FILE [--scene FILE]`` joins a stack this check did not start,
where a scene was built for a take: it starts and stops no stack and builds nothing, crosses into
the world the scene builder's record names, reads the owner's token once into this process, and
closes the grant it issued when it ends; the stack keeps running. The summary keeps the words the
stack shows for the bridge.

``--scripted-model PLAN`` serves the stack's API with ``scripts/acceptance/scripted_model.py``
answering every model request from PLAN (``run/plans/``), with no provider, key or cost; with
``--traveller-mind`` the soldier's mind is asked of it. Without them the world's routine decides.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
ZERO_AD = HERE.parents[1]
CHECKOUT = HERE.parents[3]
sys.path.insert(0, str(ZERO_AD))
sys.path.insert(0, str(HERE.parents[2] / "door_client"))
sys.path.insert(0, str(CHECKOUT))

from door_client import DoorClient  # noqa: E402
from exulanica_zero_ad import ADAPTER_VERSION  # noqa: E402
from exulanica_zero_ad.bridge import Bridge  # noqa: E402
from exulanica_zero_ad.gate import Gate, game_type, place_marker, template  # noqa: E402
from exulanica_zero_ad.rl import GameRefused, RLInterface  # noqa: E402

MAPPING = ZERO_AD / "mapping" / "zero-ad-empires-ascendant.v1.json"
READS = ZERO_AD / "mapping" / "reads.json"
MATCH = ZERO_AD / "matches" / "greek-acropolis-athenians.json"
#: The standard stood on the gate: the Athenians' rally point flag, a marker the game itself draws.
MARKER = "special/rallypoints/athen"
#: The adapter's pace: one turn of the match every 200 ms.
STEP_SECONDS = 0.2
#: Where the hoplite first walks from the spot the gate then stands on, in the game's metres, in
#: the order tried, and how far it must end from it; the gate's radius; and how many steps a unit
#: stands still before its walk counts as ended.
GATE_OFFSETS = ((15.0, 0.0), (-15.0, 0.0), (0.0, 15.0), (0.0, -15.0))
AWAY_METRES_MINIMUM = 8.0
GATE_RADIUS = 4.0
STILL_STEPS = 5
#: How long the hoplite may take to reach the gate before the check says it did not.
WALK_LIMIT_S = 60.0
#: How often the stack is started before the check gives up when its tile worker cannot reach its
#: database in time, as a heavily loaded machine sometimes makes it.
LAUNCH_ATTEMPTS = 3


#: The words a world shows for where this bridge's visitors came from, unless the operator names
#: others: a film or a demo names no game.
NEUTRAL_WORDS = "another open-source game"
#: A bridge's label or game as the door takes them: one line of 1 to 80 characters.
WORDS = re.compile(r"[^\x00-\x1f\x7f]{1,80}")


def plain_words(text: str, what: str) -> str:
    """``text`` as the door takes a bridge's ``what`` (its label or game), or a refusal."""
    words = text.strip()
    if not WORDS.fullmatch(words):
        raise SystemExit(f"a bridge's {what} is one line of 1 to 80 characters")
    return words


def declaration(
    mapping_sha256: str, *, label: str = NEUTRAL_WORDS, game: str = NEUTRAL_WORDS
) -> dict[str, Any]:
    """The door bridge entry a stack is started with for this adapter (``launch.py up
    --door-bridges``): run by a server, unlisted, offered to the stack's synthetic workspaces,
    pinning the mapping by ``mapping_sha256`` and admitting the adapter's version, shown in
    ``label`` and ``game`` words. Its own credential is random and only its digest is written."""
    return {
        "bridge": "zero-ad",
        "label": plain_words(label, "label"),
        "game": plain_words(game, "game"),
        "run_by": "server",
        "ai": False,
        "credential_sha256": hashlib.sha256(secrets.token_urlsafe(32).encode()).hexdigest(),
        "mapping_sha256": [mapping_sha256],
        "adapter_versions": [ADAPTER_VERSION],
        "listed": False,
        "workspaces": "synthetic",
    }


def declare(out: Path, entry: dict[str, Any]) -> int:
    """Write ``entry`` into the door bridge declarations at ``out``, one file for every game a
    stack lets in: beside the bridges ``out`` already declares, and in place of an earlier entry
    of the same bridge (the door refuses a bridge declared twice). How many the file declares."""
    declared: Any = []
    if out.exists():
        try:
            declared = json.loads(out.read_text())
        except ValueError:
            declared = None
        if not isinstance(declared, list) or not all(isinstance(e, dict) for e in declared):
            raise SystemExit(f"{out} is not a list of door bridge declarations")
    kept = [other for other in declared if other.get("bridge") != entry["bridge"]]
    out.write_text(json.dumps([*kept, entry], indent=2) + "\n")
    return len(kept) + 1


def game_answers(game: RLInterface) -> bool:
    """Whether the game answers its interface. Until a match starts, the game answers every route
    but ``/reset`` with 400, which still says it is listening."""
    try:
        game.evaluate("1")
    except GameRefused as refused:
        cause = refused.__cause__
        return isinstance(cause, urllib.error.HTTPError) and cause.code == 400
    return True


def luanti_helpers() -> Any:
    """The Luanti check's stack, scene and grant helpers, loaded by their path."""
    path = HERE.parents[2] / "luanti" / "run" / "check.py"
    spec = importlib.util.spec_from_file_location("luanti_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class Recorder:
    """Every exchange with the door and the game, and the run's marks, each with its time since the
    run started: no credential, token or header is ever written."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.marks: list[dict[str, Any]] = []

    def write(self, entry: dict[str, Any]) -> None:
        entry = {"t_s": round(time.monotonic() - self.started, 3), **entry}
        with self.lock, self.path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(entry, sort_keys=True) + "\n")

    def mark(self, name: str, **fields: Any) -> None:
        entry = {"mark": name, **fields}
        self.marks.append({"t_s": round(time.monotonic() - self.started, 3), **entry})
        self.write(entry)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """No redirect is followed, as the door client's own opener follows none."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class RecordedDoorOpener:
    """The door client's opener, recording each exchange's method, path, status and time, and the
    body of an arrival or a call home (neither holds a credential)."""

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.opener = urllib.request.build_opener(_NoRedirect)

    def __call__(self, request: Any, timeout: float) -> Any:
        path = urllib.parse.urlsplit(request.full_url).path
        began = time.monotonic()
        body = None
        if request.data and path in ("/door/channel/arrivals", "/door/channel/home"):
            body = json.loads(request.data)
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            self.recorder.write(
                {
                    "door": path,
                    "method": request.get_method(),
                    "status": error.code,
                    "ms": round((time.monotonic() - began) * 1000),
                    **({"request": body} if body else {}),
                }
            )
            raise
        self.recorder.write(
            {
                "door": path,
                "method": request.get_method(),
                "status": response.status,
                "ms": round((time.monotonic() - began) * 1000),
                **({"request": body} if body else {}),
            }
        )
        return response


class RecordedGame:
    """The game's interface, recording each route's call: the commands a step sends, the head of the
    code an evaluation runs and its answer, and the time each took."""

    def __init__(self, game: RLInterface, recorder: Recorder) -> None:
        self.game = game
        self.recorder = recorder
        self.state: dict[str, Any] = {}

    def reset(self, settings: dict[str, Any], *, player_id: int = 1) -> dict[str, Any]:
        began = time.monotonic()
        self.state = self.game.reset(settings, player_id=player_id)
        self.recorder.write(
            {
                "game": "reset",
                "ms": round((time.monotonic() - began) * 1000),
                "map": settings["map"],
            }
        )
        return self.state

    def step(self, commands: Any = ()) -> dict[str, Any]:
        self.state = self.game.step(commands)
        if commands:
            self.recorder.write({"game": "step", "commands": [c for _p, c in commands]})
        return self.state

    def evaluate(self, code: str) -> Any:
        began = time.monotonic()
        answer = self.game.evaluate(code)
        self.recorder.write(
            {
                "game": "evaluate",
                "code": code[:160],
                "answer": answer,
                "ms": round((time.monotonic() - began) * 1000),
            }
        )
        return answer


def xz(entity: dict[str, Any]) -> tuple[float, float] | None:
    position = entity.get("position")
    if not isinstance(position, list) or len(position) < 2:
        return None
    return float(position[0]), float(position[-1])


def units(state: dict[str, Any], owner: int, name: str) -> dict[int, tuple[float, float]]:
    """The units of ``name`` that ``owner`` has, by entity id, with where each stands."""
    found = {}
    for key, entity in (state.get("entities") or {}).items():
        if not isinstance(entity, dict) or entity.get("owner") != owner:
            continue
        where = xz(entity)
        if entity.get("template") == name and where is not None:
            found[int(key)] = where
    return found


def walk_away(
    played: RecordedGame,
    player: int,
    name: str,
    walker: int,
    stood: tuple[float, float],
) -> tuple[float, float] | None:
    """Walk ``walker`` away from where it stood, trying each of :data:`GATE_OFFSETS` until it ends
    at least :data:`AWAY_METRES_MINIMUM` from its spot, stepping the match at the adapter's pace;
    where it ends, or None where it could not or left the match."""
    for dx, dz in GATE_OFFSETS:
        target = {"type": "walk", "entities": [walker], "x": stood[0] + dx, "z": stood[1] + dz}
        played.step([(player, {**target, "queued": False})])
        last, still = stood, 0
        ends = time.monotonic() + WALK_LIMIT_S
        while time.monotonic() < ends and still < STILL_STEPS:
            time.sleep(STEP_SECONDS)
            where = units(played.step(), player, name).get(walker)
            if where is None:
                return None
            still = still + 1 if math.dist(where, last) < 0.05 else 0
            last = where
        if math.dist(last, stood) >= AWAY_METRES_MINIMUM:
            return last
    return None


class CheckBridge(Bridge):
    """The adapter's loop, with every frame it acts on recorded as a mark."""

    recorder: Recorder

    def handle(self, frames: Any) -> None:
        frames = list(frames)
        for frame in frames:
            kind = frame.get("kind")
            if kind in ("arrived", "arrival_refused", "departed", "grant_ended"):
                self.recorder.mark(
                    f"frame_{kind}",
                    thing_id=frame.get("thing_id"),
                    arrival_id=frame.get("arrival_id"),
                    why=frame.get("why") or frame.get("reason"),
                )
        before = set(self.away)
        super().handle(frames)
        for thing_id in before - set(self.away):
            self.recorder.mark("brought_back", thing_id=thing_id)


def start_stack(
    luanti: Any, arguments: argparse.Namespace, declared: Path, recorder: Recorder
) -> dict[str, Any]:
    """This checkout's stack on the run's port slot with the bridges ``declared``: the launcher's
    state. It is started again where its tile worker could not reach its database in time, as a
    heavily loaded machine sometimes makes it."""
    scripted = (
        ["--scripted-model", str(arguments.scripted_model.resolve())]
        if arguments.scripted_model
        else []
    )
    for attempt in range(1, LAUNCH_ATTEMPTS + 1):
        try:
            started = luanti.launch(
                "up",
                "--port-base",
                str(arguments.port_base),
                "--society-playback",
                "--no-derivative-worker",
                "--door-bridges",
                str(declared),
                "--society-of-things",
                *scripted,
            )
            return json.loads(started[: started.rindex("}") + 1])
        except luanti.Refused as refused:
            # A start that failed part way may leave its database and state behind: bring them
            # down, and start again where the tile worker could not reach its database in time.
            luanti.subprocess.run(
                [sys.executable, str(luanti.LAUNCH), "down", "--worktree", str(CHECKOUT)],
                cwd=CHECKOUT,
                capture_output=True,
                check=False,
            )
            if "tile-worker-startup" not in str(refused) or attempt == LAUNCH_ATTEMPTS:
                raise
            recorder.mark("stack_started_again", after=str(refused)[:160])
    raise AssertionError("every start either returned or raised")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port-base", type=int, default=19500)
    parser.add_argument("--game", default="http://127.0.0.1:19508")
    parser.add_argument("--match", type=Path, default=MATCH)
    parser.add_argument("--player", type=int, default=1)
    parser.add_argument("--look", default="cc0-hoplite")
    parser.add_argument("--minutes-speed", type=int, default=1)
    parser.add_argument("--lives-s", type=float, default=60.0)
    parser.add_argument("--limit-s", type=float, default=900.0)
    parser.add_argument("--keep-stack", action="store_true")
    parser.add_argument("--scripted-model", type=Path, metavar="PLAN")
    parser.add_argument("--traveller-mind", action="store_true")
    parser.add_argument(
        "--declare",
        type=Path,
        metavar="OUT",
        help="write the bridge into the door bridge declarations a stack starts with, and stop",
    )
    parser.add_argument("--label", default=NEUTRAL_WORDS, help="the bridge's declared label")
    parser.add_argument("--game-words", default=NEUTRAL_WORDS, help="the bridge's declared game")
    parser.add_argument(
        "--api",
        metavar="URL",
        help="join a stack this check did not start, with --token-file and --record",
    )
    parser.add_argument("--token-file", type=Path, help="with --api: the owner's token, read once")
    parser.add_argument(
        "--record", type=Path, help="with --api: the scene builder's record of the world"
    )
    parser.add_argument("--scene", type=Path, help="with --api: the file of the record's scene")
    arguments = parser.parse_args(argv)
    joined = arguments.api is not None
    if [arguments.token_file is not None, arguments.record is not None] != [joined, joined]:
        parser.error("--api, --token-file and --record go together")
    if joined and (arguments.keep_stack or arguments.scripted_model):
        parser.error("--api joins a running stack: no --keep-stack or --scripted-model")
    if arguments.scene is not None and not joined:
        parser.error("--scene names the scene of a joined stack's record: it goes with --api")
    luanti = luanti_helpers()
    Refused, Api = luanti.Refused, luanti.Api
    from exulanica.canonical import sha256_of_canonical

    mapping = json.loads(MAPPING.read_text())
    reads = json.loads(READS.read_text())
    mapping_sha256 = sha256_of_canonical(mapping).hex()
    [visitor] = mapping["visitors"]
    soldier = template(visitor["game_type"])
    looks = {look["look_key"]: look["look"] for look in visitor["looks"]}
    if arguments.look not in looks:
        parser.error(f"--look names no look the mapping offers: {sorted(looks)}")
    entry = declaration(mapping_sha256, label=arguments.label, game=arguments.game_words)
    if arguments.declare:
        count = declare(arguments.declare, entry)
        print(
            f"{arguments.declare}: bridge zero-ad ({entry['label']}), mapping "
            f"{mapping_sha256[:16]}..., adapter {ADAPTER_VERSION}; {count} declared in the file"
        )
        return 0
    game = RLInterface(arguments.game)
    if not game_answers(game):
        raise Refused("game", f"the game at {arguments.game} does not answer its interface")
    folder = (
        CHECKOUT
        / ".exulanica"
        / "zero-ad-checks"
        / time.strftime("%Y%m%d-%H%M%S-joined" if joined else "%Y%m%d-%H%M%S")
    )
    folder.mkdir(parents=True)
    recorder = Recorder(folder / "exchanges.jsonl")
    summary: dict[str, Any] = {
        "profile": "exulanica-zero-ad.check-run/v1",
        "started_at": now(),
        "adapter_version": ADAPTER_VERSION,
        "mapping_sha256": mapping_sha256,
        "look_key": arguments.look,
        "look": looks[arguments.look],
        "match": arguments.match.name,
        "lives_s": arguments.lives_s,
    }
    state: dict[str, Any] | None = None
    if not joined:
        # The stack this check starts reads the bridge from here; a joined stack read its own.
        declared = folder / "door-bridges.json"
        declared.write_text(json.dumps([entry]))
        state = start_stack(luanti, arguments, declared, recorder)
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, **seen: Any) -> None:
        checks.append({"check": name, "ok": bool(ok), **seen})

    stop = threading.Event()
    try:
        if joined:
            # A stack someone else started for a take: its world is the one the scene builder's
            # record names, and the owner's token is read once into this process.
            api = Api(arguments.api.rstrip("/"), arguments.token_file.read_text().strip())
            recorded = arguments.record.read_bytes()
            summary["stack"] = {
                "api": api.base,
                "started_by_this_check": False,
                "record": str(arguments.record),
                "record_sha256": hashlib.sha256(recorded).hexdigest(),
            }
            placed = json.loads(recorded)
            scene = luanti.scene_of_record(placed, arguments.scene)
        else:
            assert state is not None
            token = (Path(state["run_dir"]) / "token").read_text().strip()
            api = Api(f"http://127.0.0.1:{state['ports']['api']}", token)
            summary["stack"] = {"api": api.base, "started_by_this_check": True}
            scene = luanti.newest_demo_scene()
            placed = luanti.build_scene(api, folder, token, scene)
            del token
        offered = {bridge["bridge"]: bridge for bridge in api("GET", "/door/bridges")["bridges"]}
        if "zero-ad" not in offered:
            raise Refused("bridge", "the stack offers this workspace no zero-ad bridge")
        # The words the world shows for where the visitor came from, as the stack declared them.
        summary["bridge"] = {key: offered["zero-ad"].get(key) for key in ("label", "game")}
        world = luanti.crossing_world(api, placed, scene)
        summary["scene"] = {
            "file": scene.name,
            "sha256": sha256_of_canonical(json.loads(scene.read_text())).hex(),
            "travellers": world["travellers"],
            "gate": world["gate"],
        }
        summary["playback"] = luanti.play(api, world, arguments.minutes_speed)
        offers = luanti.door_offers(api)
        grant = {
            "visitors_maximum": 1,
            "kinds": [visitor["game_type"]],
            "gate": world["gate"],
            "may_carry_in": False,
            "may_carry_out": False,
            "world_words": world["words"],
            **luanti.opened_to_travellers(
                world["travellers"], offers["world_decides"], arguments.traveller_mind
            ),
        }
        issued = api(
            "POST",
            "/door/grants",
            params=world["scope"],
            body={
                "idempotency_key": str(uuid.uuid4()),
                "bridge": "zero-ad",
                "version_id": world["version"],
                "minutes": 60,
                "channel_credential": True,
                **grant,
            },
        )
        grant_id = issued["grant"]["grant_id"]
        summary["grant_id"] = grant_id
        summary["traveller_mind"] = grant.get("traveller")
        door = DoorClient(
            api.base,
            issued["channel_credential"]["credential"],
            opener=RecordedDoorOpener(recorder),
        )
        del issued
        door.hello(ADAPTER_VERSION, mapping, reads)
        recorder.mark("hello")

        played = RecordedGame(game, recorder)
        first = played.reset(json.loads(arguments.match.read_text()), player_id=arguments.player)
        hoplites = units(first, arguments.player, soldier)
        if not hoplites:
            raise Refused("match", f"player {arguments.player} has no {soldier} at the start")
        walker = min(hoplites)
        # The gate stands where the hoplite stood at the start, a spot a unit can surely reach: the
        # hoplite first walks away from it, so it then walks back onto the standard.
        stood = hoplites[walker]
        away_at = walk_away(played, arguments.player, soldier, walker, stood)
        if away_at is None:
            raise Refused("match", "the hoplite could not walk away from where it stood")
        recorder.mark("walked_away", entity=walker, metres=round(math.dist(stood, away_at), 1))
        gate = Gate(x=stood[0], z=stood[1], radius=GATE_RADIUS, player=arguments.player)
        others = units(played.state, arguments.player, soldier)
        near = [key for key, where in others.items() if key != walker and gate.holds(*where)]
        if near:
            raise Refused("match", f"other hoplites stand where the gate goes: {near}")
        summary["gate_in_the_match"] = {"x": gate.x, "z": gate.z, "radius": gate.radius}
        summary["marker"] = played.evaluate(place_marker(MARKER, gate))
        bridge = CheckBridge(
            played, door, gate, mapping, arguments.look, journal=folder / "journal.json"
        )
        bridge.recorder = recorder
        walk = {"type": "walk", "entities": [walker], "x": gate.x, "z": gate.z, "queued": False}
        played.step([(arguments.player, walk)])
        recorder.mark("walk_ordered", entity=walker, soldier=game_type(soldier))
        threading.Thread(target=bridge.poll, args=(stop,), daemon=True).start()

        arrived_at = None
        thing_id = None
        crossings = 0
        sent_home = False
        revoked = False
        ends = time.monotonic() + arguments.limit_s
        walk_ends = time.monotonic() + WALK_LIMIT_S
        while not bridge.ended:
            began = time.monotonic()
            if began > ends:
                raise Refused("timeout", f"the crossing did not end in {arguments.limit_s} s")
            bridge.drain()
            if bridge.ended:
                break
            for away in bridge.step():
                crossings += 1
                thing_id = thing_id or away.thing_id
                recorder.mark("crossed", thing_id=away.thing_id)
            if thing_id is None and began > walk_ends:
                raise Refused("walk", f"the hoplite did not reach the gate in {WALK_LIMIT_S} s")
            marks = {mark["mark"] for mark in recorder.marks}
            if "frame_arrived" in marks and arrived_at is None:
                arrived_at = time.monotonic()
            departed = "frame_departed" in marks
            lived = time.monotonic() - arrived_at if arrived_at else 0.0
            if arrived_at and not departed and not sent_home and lived >= arguments.lives_s:
                sent = api(
                    "POST",
                    f"/door/grants/{grant_id}/send-away",
                    body={"thing_id": thing_id},
                    expected=(202, 404),
                )
                sent_home = True
                recorder.mark("owner_sent_home", answered=sorted(sent))
            if "brought_back" in marks and not revoked:
                api("POST", f"/door/grants/{grant_id}/revoke", expected=(200,))
                revoked = True
                recorder.mark("owner_revoked")
            time.sleep(max(0.0, STEP_SECONDS - (time.monotonic() - began)))
        stop.set()
        recorder.mark("adapter_read_the_grant_ended")

        marks = recorder.marks
        named = {mark["mark"] for mark in marks}
        departed_why = next(
            (mark.get("why") for mark in marks if mark["mark"] == "frame_departed"), None
        )
        check("the hoplite crossed at the gate, once", crossings == 1, crossings=crossings)
        check("the world took the arrival", "frame_arrived" in named)
        check(
            "the visitor left the world",
            "frame_departed" in named,
            why=departed_why,
            sent_home_by_the_owner=sent_home,
        )
        check("the soldier is back in the match", "brought_back" in named)
        after = played.step()
        back = units(after, arguments.player, soldier)
        on_gate = sorted(key for key, where in back.items() if gate.holds(*where))
        check(
            "a hoplite of its owner stands on the gate",
            bool(on_gate) and walker not in back,
            on_gate=on_gate,
            the_one_that_left_is_gone=walker not in back,
        )
        looks_read = api(
            "GET", f"/world/versions/{world['version']}/thing-looks", params=world["scope"]
        )
        worn = [
            entry
            for entry in looks_read.get("looks", [])
            if entry["thing_id"] == thing_id and entry.get("chosen_by") == "crossing"
        ]
        summary["look_worn"] = worn[0]["look"] if worn else None
        check(
            "the visitor wore the mapping's look",
            bool(worn) and worn[0]["look"] == looks[arguments.look],
            worn=summary["look_worn"],
        )
        summary["character_decisions"] = luanti.character_decisions(api, world, {str(thing_id)})
        decided = summary["character_decisions"]["counts"]
        check(
            "the world decided for the visitor",
            any(key.endswith(" applied") for key in decided),
            counts=decided,
        )
        replay = api("GET", world["society"] + "/replay", params=world["scope"])
        summary["replay_verified"] = replay.get("replay_verified")
        check("the society replays with no game running", replay.get("replay_verified") is True)
        ended = api("GET", f"/door/grants/{grant_id}")["grant"]
        summary["grant_at_the_end"] = {key: ended.get(key) for key in ("state", "ended_reason")}
        summary["marks"] = marks
    finally:
        stop.set()
        if joined:
            # Nothing of the run stays open in a world it did not build; the stack keeps running.
            if "grant_id" in summary:
                summary["grant_closed"] = luanti.close_grant(api, summary["grant_id"])
        elif not arguments.keep_stack:
            luanti.launch("down")
            if arguments.scripted_model and state is not None:
                summary["scripted_model"] = luanti.scripted_record(Path(state["run_dir"]), folder)
        summary["checks"] = checks
        summary["ended_at"] = now()
        (folder / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    failed = [entry["check"] for entry in checks if not entry["ok"]]
    print(
        json.dumps(
            {
                "run_folder": str(folder),
                "checks": len(checks),
                "failed": failed,
                "marks": [(mark["t_s"], mark["mark"]) for mark in summary.get("marks", [])],
            },
            indent=2,
        )
    )
    return 0 if checks and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
