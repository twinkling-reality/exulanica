"""A stand-in door that plays one traveller's visit, for building the gate's crossing side early.

    python3 bridges/luanti/tools/fake_door.py --port 19525 --log FILE [--minute-s 2]

It is not the door. It serves the channel routes a bridge uses (hello, frames by long-poll,
answers, arrivals, delivered, gone) with the frame shapes agreed with lane BRIDGE for crossings,
keeps everything in memory, checks almost nothing, and plays a short script: the grant lets one
traveller in and things be carried both ways; an arrival is placed at the next minute; the
traveller is asked every minute with the options a visitor would be offered (one of them a walk
whose distance changes every minute); with ``--refuse-look`` an arrival in that look is refused
``look_not_shipped``, as a door refuses a look its library does not hold; a line said to the
knight is answered by a scripted knight,
who then gives the traveller a sword; choosing to leave departs the traveller carrying what it
holds, and the departure repeats in every poll until it is reported delivered. A traveller whose
player is gone departs two minutes later carrying nothing. Every body a bridge sends is appended
to the log as one JSON line, headers never.

Standard library only; listens on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

NAMESPACE = uuid.UUID("6f1b9a52-4d1e-4c55-9e4b-0c8f0d2b7a11")
KNIGHT = str(uuid.uuid5(NAMESPACE, "knight"))
WELL = str(uuid.uuid5(NAMESPACE, "well"))
SWORD = str(uuid.uuid5(NAMESPACE, "sword"))
GRANT = str(uuid.uuid5(NAMESPACE, "grant"))
KINDS = {"default:torch": "lantern", "default:sword_steel": "sword"}
GAME_ITEMS = {"lantern": "default:torch", "sword": "default:sword_steel"}


class Visit:
    """The script's state, guarded by one lock."""

    def __init__(self, minute_s: float, log: str) -> None:
        self.lock = threading.Condition()
        self.minute_s = minute_s
        self.log_path = log
        self.frames: list[dict[str, Any]] = []
        self.minute = 0
        self.ask_seq = 0
        self.open_ask: dict[str, Any] | None = None
        self.answers: dict[str, dict[str, Any]] = {}
        self.pending_arrival: dict[str, Any] | None = None
        self.arrivals: dict[str, str] = {}
        self.visitor: dict[str, Any] | None = None
        self.departures: dict[str, dict[str, Any]] = {}
        self.delivered: set[str] = set()
        self.knight_replies = 0
        self.gone_at: int | None = None
        self.refused_looks: set[str] = set()

    def log(self, route: str, body: Any) -> None:
        with open(self.log_path, "a") as file:
            file.write(
                json.dumps({"t": round(time.time(), 3), "route": route, "body": body}) + "\n"
            )

    def add(self, frame: dict[str, Any]) -> None:
        self.frames.append(frame)
        self.lock.notify_all()

    # -- the minute --------------------------------------------------------------------------

    def options(self) -> list[dict[str, Any]]:
        visitor = self.visitor
        held = visitor["held"]
        offered = [
            {"label": "wait here a minute", "kind": "wait", "action": "wait"},
            {
                "label": "say something to the knight (person 2), 3 m away",
                "kind": "say_to",
                "action": "say",
                "target_id": KNIGHT,
                "line_characters_maximum": 200,
            },
            {
                "label": "say something to everyone near you",
                "kind": "say_all",
                "action": "say",
                "line_characters_maximum": 200,
            },
            {
                "label": f"walk to the well ({max(1, 14 - self.minute)} m)",
                "kind": "target",
                "action": "go",
                "target_id": WELL,
                "walk_mm": max(1, 14 - self.minute) * 1000,
            },
        ]
        for thing in held:
            if thing["kind"] == "lantern":
                offered.append(
                    {
                        "label": "give the lantern to the knight (person 2)",
                        "kind": "give",
                        "action": "give",
                        "target_id": KNIGHT,
                        "thing_id": thing["thing_id"],
                    }
                )
        offered.append({"label": "leave through the gate", "kind": "leave", "action": "leave"})
        return offered

    def tick(self) -> None:
        with self.lock:
            self.minute += 1
            self.close_ask()
            if self.pending_arrival is not None:
                self.place(self.pending_arrival)
                self.pending_arrival = None
            visitor = self.visitor
            if visitor is None:
                return
            if self.gone_at is not None and self.minute - self.gone_at >= 2:
                self.depart("decider_lost", carrying=False)
                return
            if visitor.get("knight_due"):
                visitor["knight_due"] = False
                self.knight_replies += 1
                self.add(
                    {
                        "kind": "said",
                        "tick": self.minute,
                        "speaker": {
                            "id": KNIGHT,
                            "label": "the knight (person 2)",
                            "mind": {"ai": True, "words": "a scripted stand-in"},
                        },
                        "to": visitor["thing_id"],
                        "line": "A sword is no small thing, traveller. Take this one.",
                    }
                )
                visitor["held"].append({"thing_id": SWORD, "kind": "sword"})
                self.add(
                    {
                        "kind": "happened",
                        "tick": self.minute,
                        "event": "given",
                        "words": "the knight (person 2) gave you a sword",
                    }
                )
            if self.gone_at is None:
                self.ask()

    def place(self, arrival: dict[str, Any]) -> None:
        thing_id = str(uuid.uuid5(NAMESPACE, "arrival:" + arrival["arrival_id"]))
        carried = []
        for index, item in enumerate(arrival["carried"]):
            carried.append(
                {
                    "thing_id": str(uuid.uuid5(NAMESPACE, f"{thing_id}:{index}")),
                    "game_item": item["game_item"],
                }
            )
        self.visitor = {
            "thing_id": thing_id,
            "held": [
                {"thing_id": entry["thing_id"], "kind": KINDS[entry["game_item"]]}
                for entry in carried
                if entry["game_item"] in KINDS
            ],
        }
        self.arrivals[arrival["arrival_id"]] = thing_id
        self.add(
            {
                "kind": "arrived",
                "tick": self.minute,
                "arrival_id": arrival["arrival_id"],
                "thing_id": thing_id,
                "carried": carried,
            }
        )

    def ask(self) -> None:
        self.ask_seq += 1
        request_id = str(uuid.uuid4())
        context = {"tick": self.minute, "options": self.options()}
        self.open_ask = {
            "request_id": request_id,
            "ask_seq": self.ask_seq,
            "context": context,
            "asked_at": time.monotonic(),
        }
        self.add(
            {
                "kind": "asked",
                "ask_seq": self.ask_seq,
                "request_id": request_id,
                "request_sha256": hashlib.sha256(request_id.encode()).hexdigest(),
                "subject_id": self.visitor["thing_id"],
                "deadline_ms": 3000,
                "instruction": "Choose what this traveller does next.",
                "choice_description": "One of the options offered.",
                "context": context,
                "idle_label": "wait here a minute",
            }
        )

    def close_ask(self) -> None:
        ask = self.open_ask
        if ask is None:
            return
        self.open_ask = None
        answer = self.answers.get(ask["request_id"])
        if answer is None:
            self.add(
                {
                    "kind": "outcome",
                    "ask_seq": ask["ask_seq"],
                    "request_id": ask["request_id"],
                    "status": "unavailable",
                    "reason": "no_answer_in_time",
                }
            )
            return
        self.add(
            {
                "kind": "outcome",
                "ask_seq": ask["ask_seq"],
                "request_id": ask["request_id"],
                "status": "accepted",
                "reason": "validated_choice",
            }
        )
        option = next(o for o in ask["context"]["options"] if o["label"] == answer["label"])
        visitor = self.visitor
        if option["action"] == "say":
            self.add(
                {
                    "kind": "said",
                    "tick": self.minute,
                    "speaker": {
                        "id": visitor["thing_id"],
                        "label": "the traveller from Luanti (person 9)",
                        "mind": {"ai": False, "words": "a player in Luanti"},
                    },
                    "to": option.get("target_id"),
                    "line": answer["line"],
                }
            )
            if option.get("target_id") == KNIGHT and self.knight_replies == 0:
                visitor["knight_due"] = True
        elif option["action"] == "give":
            visitor["held"] = [t for t in visitor["held"] if t["thing_id"] != option["thing_id"]]
            self.add(
                {
                    "kind": "happened",
                    "tick": self.minute,
                    "event": "given",
                    "words": "you gave the lantern to the knight (person 2)",
                }
            )
        elif option["action"] == "leave":
            self.depart("chose_to_leave", carrying=True)

    def depart(self, why: str, *, carrying: bool) -> None:
        visitor = self.visitor
        departure_id = str(uuid.uuid4())
        carried = []
        if carrying:
            carried = [
                {
                    "thing_id": thing["thing_id"],
                    "kind": thing["kind"],
                    "game_item": GAME_ITEMS[thing["kind"]],
                }
                for thing in visitor["held"]
            ]
        self.departures[departure_id] = {
            "kind": "departed",
            "tick": self.minute,
            "departure_id": departure_id,
            "thing_id": visitor["thing_id"],
            "why": why,
            "carried": carried,
        }
        self.visitor = None
        self.lock.notify_all()

    def waiting(self, after: int) -> list[dict[str, Any]]:
        frames = list(self.frames[after:])
        frames += [frame for key, frame in self.departures.items() if key not in self.delivered]
        return frames


class Handler(BaseHTTPRequestHandler):
    visit: Visit

    def _answer(self, status: int, document: dict[str, Any]) -> None:
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> Any:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def log_message(self, *_arguments: Any) -> None:
        return

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path != "/door/channel/frames":
            self._answer(404, {"code": "unknown_reference", "detail": "no such route here"})
            return
        after = int((parse_qs(url.query).get("after") or ["0"])[0])
        visit = self.visit
        ends = time.monotonic() + 3
        with visit.lock:
            while not visit.waiting(after) and time.monotonic() < ends:
                visit.lock.wait(timeout=max(0.0, ends - time.monotonic()))
            frames = visit.waiting(after)
            cursor = len(visit.frames)
        self._answer(
            200, {"profile": "exulanica.door-frame/v1", "frames": frames, "cursor": str(cursor)}
        )

    def do_POST(self) -> None:
        url = urlparse(self.path)
        body = self._body()
        visit = self.visit
        visit.log(url.path, body)
        with visit.lock:
            if url.path == "/door/channel/hello":
                self._answer(
                    200,
                    {
                        "profile": "exulanica.door-frame/v1",
                        "grant": {
                            "grant_id": GRANT,
                            "world_id": "fake-world",
                            "bridge": "luanti",
                            "grant_seq": 1,
                            "state": "standing",
                            "scope": {
                                "visitors_maximum": 1,
                                "kinds": ["visitor"],
                                "things": [],
                                "may_carry_in": True,
                                "may_carry_out": True,
                                "may_speak": True,
                            },
                        },
                        "hold_seconds": 3,
                        "world_words": "The Crossroads",
                        "cursor": str(len(visit.frames)),
                    },
                )
            elif url.path == "/door/channel/arrivals":
                if set(body) != {"arrival_id", "game_type", "look_key", "carried"}:
                    self._answer(422, {"code": "invalid_arrival", "detail": "closed body"})
                    return
                if body["look_key"] in visit.refused_looks:
                    self._answer(422, {"code": "look_not_shipped", "detail": "not in the library"})
                    return
                if body["arrival_id"] not in visit.arrivals and visit.visitor is None:
                    visit.pending_arrival = body
                self._answer(202, {"received": True})
            elif url.path == "/door/channel/answers":
                ask = visit.open_ask
                if ask is None or ask["request_id"] != body.get("request_id"):
                    self._answer(409, {"code": "answer_too_late", "detail": "decided"})
                    return
                visit.answers[body["request_id"]] = body
                self._answer(202, {"received": True})
            elif url.path.startswith("/door/channel/departures/"):
                visit.delivered.add(url.path.split("/")[4])
                self._answer(202, {"received": True})
            elif url.path == "/door/channel/gone":
                visit.gone_at = visit.minute
                self._answer(202, {"received": True})
            else:
                self._answer(404, {"code": "unknown_reference", "detail": "no such route here"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--log", required=True)
    parser.add_argument("--minute-s", type=float, default=2.0)
    parser.add_argument(
        "--refuse-look", action="append", default=[], help="a look key arrivals are refused in"
    )
    arguments = parser.parse_args(argv)
    visit = Visit(arguments.minute_s, arguments.log)
    visit.refused_looks = set(arguments.refuse_look)
    Handler.visit = visit

    def minutes() -> None:
        while True:
            time.sleep(visit.minute_s)
            visit.tick()

    threading.Thread(target=minutes, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", arguments.port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
