"""Run the adapter against a running 0 A.D. and an Exulanica door.

    EXULANICA_DOOR_CREDENTIAL=<the grant's channel credential> \
    python -m exulanica_zero_ad --door https://door.example --match match.json \
        --gate 512,512,12 --journal ~/zero-ad-gate.json

The credential is read from the environment only, never from the command line or a file here. The
game is reached on this machine only; start it first with ``--rl-interface=127.0.0.1:<port>``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

from . import ADAPTER_VERSION
from .bridge import Bridge
from .gate import Gate, place_marker
from .rl import RLInterface

HERE = Path(__file__).resolve().parent
MAPPING = HERE.parent / "mapping" / "zero-ad-empires-ascendant.v1.json"
#: One turn of the match each step: the game's own turn length with a window.
STEP_SECONDS = 0.2


def _door_client() -> type:
    sys.path.insert(0, str(HERE.parents[1] / "door_client"))
    from door_client import DoorClient

    return DoorClient


def _gate(text: str, player: int) -> Gate:
    x, z, radius = (float(part) for part in text.split(","))
    return Gate(x=x, z=z, radius=radius, player=player)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="exulanica_zero_ad", description=__doc__.splitlines()[0])
    parser.add_argument("--door", required=True, help="the door: HTTPS, or HTTP to this machine")
    parser.add_argument("--game", default="http://127.0.0.1:19508", help="the game's interface")
    parser.add_argument("--match", type=Path, required=True, help="the match's settings, JSON")
    parser.add_argument("--player", type=int, default=1, help="whose units cross")
    parser.add_argument("--gate", required=True, help="x,z,radius of the gate on the match's map")
    parser.add_argument("--marker", help="the template of the standard stood on the gate")
    parser.add_argument("--look", default="cc0-hoplite", help="the look key a soldier crosses in")
    parser.add_argument("--journal", type=Path, required=True, help="where what is away is kept")
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    args = parser.parse_args(argv)
    credential = os.environ.get("EXULANICA_DOOR_CREDENTIAL", "")
    if not credential:
        parser.error("set EXULANICA_DOOR_CREDENTIAL to the grant's channel credential")
    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    reads = json.loads((args.mapping.parent / "reads.json").read_text(encoding="utf-8"))
    gate = _gate(args.gate, args.player)
    game = RLInterface(args.game)
    door = _door_client()(args.door, credential)
    door.hello(ADAPTER_VERSION, mapping, reads)
    # The journal's cursor, when there is one, reads on from before a restart, so a soldier that
    # departed while the adapter was down is still brought back; the hello's would skip it.
    bridge = Bridge(game, door, gate, mapping, args.look, journal=args.journal)
    game.reset(json.loads(args.match.read_text(encoding="utf-8")), player_id=args.player)
    if args.marker:
        game.evaluate(place_marker(args.marker, gate))
    stop = threading.Event()
    threading.Thread(target=bridge.poll, args=(stop,), daemon=True).start()
    try:
        while not bridge.ended:
            started = time.monotonic()
            bridge.drain()
            bridge.step()
            time.sleep(max(0.0, STEP_SECONDS - (time.monotonic() - started)))
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
