"""The adapter's loop: a 0 A.D. match on one side, an Exulanica world's door on the other.

Each step it advances the match one turn and looks at the gate. A unit of the gate's player standing
on it, of a type the mapping lets cross, is sent through the door as an arrival; once the door takes
it, the unit is taken out of the match. The door's frames are read by long poll on a thread of their
own: when one of the adapter's visitors departs, the same kind of unit is put back on the gate for
its owner; when an arrival is refused, or the grant ends, every unit that is away comes back.

The adapter decides nothing for a visitor: the world does. Were a grant to hand a visitor's choices
to this program, each ask is answered with the option that changes nothing.

A soldier put back on the gate crosses again only once it has stepped off it and onto it again,
so one that came home is not sent straight back.

What is away is kept in a journal file of the operator's, beside the door's cursor, so a restart
brings back whoever departed meanwhile.
"""

from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .gate import Gate, Unit, at_gate, bring_back, game_type, remove, template

__all__ = ["Away", "Bridge"]

#: How long the adapter leaves a unit the door refused before sending it again.
REFUSED_PAUSE_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class Away:
    """A unit that crossed: the arrival and thing it is in the world, and what brings it back."""

    arrival_id: str
    thing_id: str
    template: str
    owner: int


class Bridge:
    """One match, one grant's channel and one gate."""

    def __init__(
        self,
        game: Any,
        door: Any,
        gate: Gate,
        mapping: Mapping[str, Any],
        look_key: str,
        *,
        journal: Path | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.game = game
        self.door = door
        self.gate = gate
        self.look_key = look_key
        self.crossing = frozenset(template(v["game_type"]) for v in mapping["visitors"])
        self.journal = journal
        self.clock = clock
        self.away: dict[str, Away] = {}
        self.refused: dict[int, float] = {}
        self.pending: dict[int, str] = {}
        self.returned: set[int] = set()
        self.frames: queue.Queue[list[dict[str, Any]]] = queue.Queue()
        self.ended = False
        self._load()

    # -- the journal -------------------------------------------------------------------------

    def _load(self) -> None:
        if self.journal is None or not self.journal.exists():
            return
        kept = json.loads(self.journal.read_text(encoding="utf-8"))
        self.door.cursor = kept.get("cursor")
        self.away = {entry["thing_id"]: Away(**entry) for entry in kept.get("away", [])}
        self.returned = {int(entity) for entity in kept.get("returned", [])}

    def _save(self) -> None:
        if self.journal is None:
            return
        kept = {
            "cursor": self.door.cursor,
            "away": [asdict(a) for a in self.away.values()],
            "returned": sorted(self.returned),
        }
        written = self.journal.with_suffix(".writing")
        written.write_text(json.dumps(kept, indent=1), encoding="utf-8")
        written.replace(self.journal)

    # -- the match's side --------------------------------------------------------------------

    def cross(self, unit: Unit) -> Away | None:
        """Send ``unit`` through the door; take it out of the match once the door takes it.
        None when the door refuses it, or does not answer: the unit stays and is not sent again
        for a while. An arrival whose answer was lost is sent again under its own id, which the
        door answers as the same arrival, so a unit never crosses twice."""
        arrival_id = self.pending.setdefault(unit.entity, str(uuid.uuid4()))
        try:
            answer = self.door.arrive(arrival_id, game_type(unit.template), self.look_key, [])
        except Exception as error:
            if 400 <= int(getattr(error, "status", 0)) < 500:
                self.pending.pop(unit.entity, None)  # refused by name: a new arrival next time
            self.refused[unit.entity] = self.clock()
            return None
        self.pending.pop(unit.entity, None)
        away = Away(arrival_id, str(answer["thing_id"]), unit.template, unit.owner)
        self.game.evaluate(remove(unit))
        self.away[away.thing_id] = away
        self._save()
        return away

    def step(self) -> list[Away]:
        """Advance the match one turn and send every unit standing on the gate; what crossed."""
        state = self.game.step()
        now = self.clock()
        on_gate = at_gate(state, self.gate, self.crossing)
        # A soldier put back on the gate stays until it has stepped off it.
        self.returned &= {unit.entity for unit in on_gate}
        crossed = []
        for unit in on_gate:
            if unit.entity in self.returned:
                continue
            if now - self.refused.get(unit.entity, -REFUSED_PAUSE_SECONDS) < REFUSED_PAUSE_SECONDS:
                continue
            away = self.cross(unit)
            if away is not None:
                crossed.append(away)
        return crossed

    def _bring_back(self, away: Away) -> None:
        made = self.game.evaluate(bring_back(away.template, away.owner, self.gate))
        if isinstance(made, int):
            self.returned.add(made)
        self.away.pop(away.thing_id, None)

    # -- the door's side ---------------------------------------------------------------------

    def handle(self, frames: Iterable[Mapping[str, Any]]) -> None:
        """Act on the door's frames: bring back who departed or was refused, answer an ask with
        the option that changes nothing, and bring everyone back at the grant's end."""
        for frame in frames:
            kind = frame.get("kind")
            if kind == "departed":
                away = self.away.get(str(frame.get("thing_id")))
                if away is not None:
                    self._bring_back(away)
            elif kind == "arrival_refused":
                refused = [a for a in self.away.values() if a.arrival_id == frame.get("arrival_id")]
                for away in refused:
                    self._bring_back(away)
            elif kind == "asked" and frame.get("idle_label") is not None:
                self.door.answer(frame, frame["idle_label"])
            elif kind == "grant_ended":
                for away in list(self.away.values()):
                    self._bring_back(away)
                self.ended = True
        self._save()

    def poll(self, stop: threading.Event) -> None:
        """Read the door's frames by long poll until ``stop``, handing each batch to the loop."""
        while not stop.is_set() and not self.ended:
            try:
                self.frames.put(self.door.frames())
            except Exception:
                stop.wait(1.0)

    def drain(self) -> None:
        """Act on every batch of frames read since the last step."""
        while True:
            try:
                batch = self.frames.get_nowait()
            except queue.Empty:
                return
            self.handle(batch)
