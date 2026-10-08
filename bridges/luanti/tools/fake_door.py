"""A stand-in door that plays the world's side of characters' visits, for checking the gate early.

    python3 bridges/luanti/tools/fake_door.py --port 19525 --log FILE [--minute-s 2]

It is not the door. It serves the channel routes a bridge uses (hello, frames by long-poll,
answers, arrivals, delivered, gone, home) with the frame shapes the door's protocol states for
crossings, keeps everything in memory and plays a short script, a world minute every
``--minute-s`` seconds: the grant lets one traveller in and things be carried both ways; an arrival
is placed at the next minute; the world asks about the character every minute it is there (the gate
leaves those asks to the world, so any answer is counted); on its first visit someone gives it a
sword, and after three minutes it chooses to leave carrying what it holds; on a later visit it
leaves after two minutes; a character its player calls home leaves at the next minute, as one its
world's owner sends home. A departure repeats in every poll until it is reported delivered. With
``--refuse-look`` an arrival in that look is refused ``look_not_shipped``, as a door refuses a look
its library does not hold. Every body a bridge sends is appended to the log as one JSON line,
headers never.

Standard library only; listens on 127.0.0.1.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

NAMESPACE = uuid.UUID("6f1b9a52-4d1e-4c55-9e4b-0c8f0d2b7a11")
SWORD = str(uuid.uuid5(NAMESPACE, "sword"))
GRANT = str(uuid.uuid5(NAMESPACE, "grant"))
KINDS = {"default:torch": "lantern", "default:sword_steel": "sword"}
GAME_ITEMS = {"lantern": "default:torch", "sword": "default:sword_steel"}
#: Minutes a character stays on its first visit and on any later one.
FIRST_STAY, LATER_STAY = 3, 2


class Visit:
    """The script's state, guarded by one lock."""

    def __init__(self, minute_s: float, log: str) -> None:
        self.lock = threading.Condition()
        self.minute_s = minute_s
        self.log_path = log
        self.frames: list[dict[str, Any]] = []
        self.minute = 0
        self.ask_seq = 0
        self.visits = 0
        self.pending_arrival: dict[str, Any] | None = None
        self.arrivals: dict[str, str] = {}
        self.visitor: dict[str, Any] | None = None
        self.departures: dict[str, dict[str, Any]] = {}
        self.delivered: set[str] = set()
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

    def tick(self) -> None:
        with self.lock:
            self.minute += 1
            if self.pending_arrival is not None:
                self.place(self.pending_arrival)
                self.pending_arrival = None
                return
            visitor = self.visitor
            if visitor is None:
                return
            if visitor.get("called_home"):
                self.depart("sent_home")
                return
            stayed = self.minute - visitor["arrived_at"]
            if visitor["first"] and stayed == 2:
                visitor["held"].append({"thing_id": SWORD, "kind": "sword"})
            if stayed >= (FIRST_STAY if visitor["first"] else LATER_STAY):
                self.depart("chose_to_leave")
                return
            self.ask()

    def place(self, arrival: dict[str, Any]) -> None:
        thing_id = str(uuid.uuid5(NAMESPACE, "arrival:" + arrival["arrival_id"]))
        carried = [
            {
                "thing_id": str(uuid.uuid5(NAMESPACE, f"{thing_id}:{index}")),
                "game_item": item["game_item"],
            }
            for index, item in enumerate(arrival["carried"])
        ]
        self.visits += 1
        self.visitor = {
            "thing_id": thing_id,
            "first": self.visits == 1,
            "arrived_at": self.minute,
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
        """An ask about the character, as the door sends one while its bridge is named its
        decider; the gate leaves it to the world."""
        self.ask_seq += 1
        options = [
            {"label": "wait here a minute", "kind": "wait", "action": "wait"},
            {"label": "leave this world", "kind": "leave", "action": "leave"},
        ]
        self.add(
            {
                "kind": "asked",
                "ask_seq": self.ask_seq,
                "request_id": str(uuid.uuid4()),
                "request_sha256": "0" * 64,
                "subject_id": self.visitor["thing_id"] if self.visitor else None,
                "base_tick": self.minute,
                "deadline_ms": 3000,
                "instruction": "Choose what this traveller does next.",
                "choice_description": "One of the options offered.",
                "context": {"tick": self.minute, "options": options},
                "messages": [],
                "act": {},
                "idle_label": options[0]["label"],
            }
        )

    def call_home(self, thing_id: str) -> tuple[int, dict[str, Any]]:
        """A player calls the character home: it departs at the next minute (why ``sent_home``, as
        the owner's send-away), the call answered once as recorded and again as not."""
        visitor = self.visitor
        if visitor is None or visitor["thing_id"] != thing_id:
            return 404, {"code": "unknown_reference", "detail": "no visitor of that id here"}
        departure_id = str(uuid.uuid5(NAMESPACE, f"departure:{thing_id}:sent_home"))
        recorded = not visitor.get("called_home")
        visitor["called_home"] = True
        return 202, {"departure_id": departure_id, "recorded": recorded}

    def depart(self, why: str) -> None:
        visitor = self.visitor
        departure_id = str(uuid.uuid5(NAMESPACE, f"departure:{visitor['thing_id']}:{why}"))
        self.departures[departure_id] = {
            "kind": "departed",
            "tick": self.minute,
            "departure_id": departure_id,
            "thing_id": visitor["thing_id"],
            "why": why,
            "carried": [
                {
                    "thing_id": thing["thing_id"],
                    "kind": thing["kind"],
                    "game_item": GAME_ITEMS[thing["kind"]],
                }
                for thing in visitor["held"]
            ],
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
            # As the door answers a route it does not have.
            self._answer(404, {"detail": "Not Found"})
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
                                "world_words": "The Crossroads",
                            },
                        },
                        "hold_seconds": 3,
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
                thing_id = str(uuid.uuid5(NAMESPACE, "arrival:" + body["arrival_id"]))
                self._answer(201, {"arrival_id": body["arrival_id"], "thing_id": thing_id})
            elif url.path.startswith("/door/channel/departures/"):
                visit.delivered.add(url.path.split("/")[4])
                self._answer(202, {"received": True})
            elif url.path == "/door/channel/home":
                if set(body) != {"thing_id"}:
                    self._answer(422, {"code": "invalid_home", "detail": "closed body"})
                    return
                self._answer(*visit.call_home(body["thing_id"]))
            elif url.path in ("/door/channel/answers", "/door/channel/gone"):
                # Counted in the log; the gate sends neither.
                self._answer(202, {"received": True})
            else:
                # As the door answers a route it does not have.
                self._answer(404, {"detail": "Not Found"})


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
