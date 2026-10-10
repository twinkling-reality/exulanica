"""Time a person's hand-over requests from the society's own state, during a take's hold.

    python3 scripts/demo/hold_requests.py --api <the stack's API address> --record <the world's
        record> --token-file <the owner's token file> --take <the take document> --say <file>
        --stop <file> [--after-departures 0] [--log <file>]

The take document's ``hold.requests`` names, as data, who gives what to whom and the words a
person would type: ``giver_kind``, ``thing_kind``, ``receiver_kind``, ``pick_words``,
``give_words`` and optionally ``receiver_pick_words``, ``reach_mm`` (7000), ``near_mm`` (6000),
``again_s`` (90) and ``times`` (2). Every few seconds this reads the society and writes one
request's words to ``--say`` (the take's driver types and confirms them, then removes the file)
only when the world could offer it:

- the giver's pick-up: the thing lies loose, the giver holds fewer than two things and stands
  within reach of it;
- else the receiver's own pick-up, where ``receiver_pick_words`` is given: the thing lies loose and
  a being of the receiver's kind that came in through a gate stands within reach of it;
- the give: the giver holds the thing and such a receiver stands near the giver.

The receiver's pick-up and the give wait until ``--after-departures`` visitors have left the world
(so a first visitor that is about to be sent home is not the one asked for). A request is written
again only ``again_s`` after its last writing and at most ``times`` times; nothing is written while
an earlier request is unread; it ends once such a receiver holds the thing, or ``--stop`` exists.
The token is read once and never written. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

DEFAULTS = {"reach_mm": 7000, "near_mm": 6000, "again_s": 90.0, "times": 2}


def _kind(entry: Mapping[str, Any]) -> Any:
    kind = entry.get("kind")
    return kind.get("kind") if isinstance(kind, dict) else kind


def choose(
    state: Mapping[str, Any],
    plan: Mapping[str, Any],
    asked: Mapping[str, list[float]],
    now: float,
    *,
    departures: int,
    after_departures: int,
) -> tuple[str, str] | None:
    """The request to write now, as (which, its words): ``pick``, ``receiver_pick`` or ``give``;
    ``("done", "")`` once a receiver past the departures holds the thing; None for nothing yet."""
    settings = {**DEFAULTS, **plan}
    people = state.get("inhabitants", [])
    things = state.get("things", [])
    giver = next(
        (p for p in people if _kind(p) == plan["giver_kind"] and p.get("came_by") == "placed"),
        None,
    )
    thing = next((t for t in things if _kind(t) == plan["thing_kind"]), None)
    receiver = next(
        (p for p in people if _kind(p) == plan["receiver_kind"] and p.get("came_by") != "placed"),
        None,
    )
    if giver is None or thing is None:
        return None
    past = departures >= after_departures
    if receiver is not None and thing.get("held_by") == receiver["id"]:
        return ("done", "") if past else None

    def may(which: str) -> bool:
        times = asked.get(which, [])
        return len(times) < settings["times"] and (
            not times or now - times[-1] >= settings["again_s"]
        )

    def apart(a: Any, b: Any) -> float | None:
        return math.dist(a, b) if a and b else None

    loose = thing.get("held_by") is None
    held = sum(1 for t in things if t.get("held_by") == giver["id"])
    reach = apart(giver.get("position_mm"), thing.get("position_mm"))
    if may("pick") and loose and held < 2 and reach is not None and reach <= settings["reach_mm"]:
        return "pick", plan["pick_words"]
    words = plan.get("receiver_pick_words")
    if words and may("receiver_pick") and loose and receiver is not None and past:
        reach = apart(receiver.get("position_mm"), thing.get("position_mm"))
        if reach is not None and reach <= settings["reach_mm"]:
            return "receiver_pick", words
        return None
    if may("give") and thing.get("held_by") == giver["id"] and receiver is not None and past:
        near = apart(giver.get("position_mm"), receiver.get("position_mm"))
        if near is not None and near <= settings["near_mm"]:
            return "give", plan["give_words"]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True)
    for name in ("--record", "--token-file", "--take", "--say", "--stop"):
        parser.add_argument(name, type=Path, required=True)
    parser.add_argument("--after-departures", type=int, default=0)
    parser.add_argument("--log", type=Path, default=None)
    args = parser.parse_args()
    plan = json.loads(args.take.read_text(encoding="utf-8"))["hold"]["requests"]
    record = json.loads(args.record.read_text(encoding="utf-8"))
    token = args.token_file.read_text(encoding="utf-8").strip()
    base = f"{args.api.rstrip('/')}/world/versions/{record['version_id']}/society"
    query = urllib.parse.urlencode({"world_id": record["world_id"]})

    def read(path: str, more: str = "") -> Any:
        request = urllib.request.Request(
            f"{base}{path}?{query}{more}", headers={"Authorization": "Bearer " + token}
        )
        with urllib.request.urlopen(request, timeout=30) as answer:
            return json.load(answer)

    def departures() -> int:
        count, before = 0, None
        while True:
            page = read("/events", f"&before={before}" if before else "")
            count += sum(1 for event in page["events"] if event["event_kind"] == "thing_departed")
            if not page.get("next"):
                return count
            before = str(page["next"])

    def say(line: str) -> None:
        text = f"{time.strftime('%H:%M:%S')} {line}"
        print(text, flush=True)
        if args.log:
            with args.log.open("a", encoding="utf-8") as out:
                out.write(text + "\n")

    asked: dict[str, list[float]] = {}
    while not args.stop.exists():
        time.sleep(4)
        if args.say.exists():
            continue
        try:
            state = read("")["state"]
            chosen = choose(
                state,
                plan,
                asked,
                time.monotonic(),
                departures=departures(),
                after_departures=args.after_departures,
            )
        except Exception as error:  # a read that fails is tried again next time
            say(f"state unread: {type(error).__name__}")
            continue
        if chosen is None:
            continue
        which, words = chosen
        if which == "done":
            say(f"the {plan['receiver_kind']} holds the {plan['thing_kind']}: nothing more to ask")
            break
        args.say.write_text(words + "\n", encoding="utf-8")
        asked.setdefault(which, []).append(time.monotonic())
        say(f"asked: {words} (minute {state.get('tick')})")
    say("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
