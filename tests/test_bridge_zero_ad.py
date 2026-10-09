"""The 0 A.D. gate in ``bridges/zero_ad``: its mapping meets the door's checks, its client speaks
the game's interface as the engine reads it, and its loop sends a soldier through the door and
brings it back.

The adapter is outside the product and is loaded here by its path, never imported by the product.
Fakes stand in for the game and the door, so no test needs the game installed.
"""

from __future__ import annotations

import importlib
import importlib.util
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from exulanica.door.mapping import check_mapping, check_reads

ADAPTER = Path(__file__).resolve().parents[1] / "bridges" / "zero_ad"
HOPLITE = "units/athen/infantry_spearman_b"


def _module(name: str) -> Any:
    package = "exulanica_zero_ad"
    if package not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            package,
            ADAPTER / package / "__init__.py",
            submodule_search_locations=[str(ADAPTER / package)],
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[package] = module
        spec.loader.exec_module(module)
    return importlib.import_module(f"{package}.{name}")


def _mapping() -> dict[str, Any]:
    return json.loads((ADAPTER / "mapping" / "zero-ad-empires-ascendant.v1.json").read_text())


class _Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _Game:
    """A match: its entities by id, and the code evaluated in it, run as the game would."""

    def __init__(self, entities: dict[str, dict[str, Any]]) -> None:
        self.entities = entities
        self.evaluated: list[str] = []
        self.next_id = 1000

    def step(self, commands=()) -> dict[str, Any]:
        return {"entities": {key: dict(value) for key, value in self.entities.items()}}

    def evaluate(self, code: str) -> Any:
        self.evaluated.append(code)
        if destroyed := re.search(r"Engine\.DestroyEntity\((\d+)\)", code):
            return self.entities.pop(destroyed[1], None) is not None
        added = re.search(
            r'AddEntity\("([^"]+)"\).*JumpTo\(([-\d.]+), ([-\d.]+)\).*SetOwner\((\d+)\)', code
        )
        assert added, code
        self.next_id += 1
        self.entities[str(self.next_id)] = {
            "template": added[1],
            "position": [float(added[2]), float(added[3])],
            "owner": int(added[4]),
        }
        return self.next_id


class _Refused(Exception):
    def __init__(self, status: int) -> None:
        super().__init__(status)
        self.status = status


class _Door:
    """A grant's channel: the arrivals it was sent and the answers it was given."""

    def __init__(self) -> None:
        self.cursor: str | None = None
        self.arrivals: list[tuple[str, str, str, list]] = []
        self.answers: list[tuple[str, str]] = []
        self.failing: Exception | None = None

    def arrive(self, arrival_id, game_type, look_key, carried):
        self.arrivals.append((arrival_id, game_type, look_key, carried))
        if self.failing is not None:
            raise self.failing
        return {"arrival_id": arrival_id, "thing_id": f"thing-{arrival_id}"}

    def answer(self, frame, label):
        self.answers.append((frame["request_id"], label))


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _bridge(game, door, *, journal=None, clock=None):
    gate = _module("gate").Gate(x=500.0, z=500.0, radius=10.0, player=1)
    return _module("bridge").Bridge(
        game, door, gate, _mapping(), "cc0-traveller", journal=journal, clock=clock or _Clock()
    )


def _on_gate(owner: int = 1, template: str = HOPLITE) -> dict[str, Any]:
    return {"template": template, "owner": owner, "position": [503.0, 498.0]}


def test_the_mapping_and_its_reads_meet_the_door_s_checks():
    reads = json.loads((ADAPTER / "mapping" / "reads.json").read_text())
    mapping = check_mapping(_mapping())
    assert check_reads(mapping, reads)
    assert [visitor["kind"] for visitor in mapping["visitors"]] == [
        {"key": "traveller", "version": 2}
    ]
    assert mapping["items"] == []  # a 0 A.D. unit carries no item, so none crosses either way


def test_the_interface_client_posts_each_route_as_the_engine_reads_it():
    sent: list[tuple[str, str]] = []
    answers = [b'{"entities": {}}', b'{"entities": {}}', b"1001"]

    def opener(request, timeout):
        sent.append((request.full_url, request.data.decode()))
        return _Answer(answers.pop(0))

    rl = _module("rl")
    game = rl.RLInterface("http://127.0.0.1:19508", opener=opener)
    game.reset({"settings": {}}, player_id=1)
    game.step([(1, {"type": "walk", "entities": [7], "x": 1, "z": 2, "queued": False})])
    assert game.evaluate("1001") == 1001
    assert sent == [
        ("http://127.0.0.1:19508/reset?playerID=1", '{"settings": {}}'),
        (
            "http://127.0.0.1:19508/step",
            '1;{"type":"walk","entities":[7],"x":1,"z":2,"queued":false}',
        ),
        ("http://127.0.0.1:19508/evaluate", "1001"),
    ]
    with pytest.raises(ValueError, match="this machine only"):
        rl.RLInterface("http://192.0.2.7:6000")


def test_a_soldier_on_the_gate_crosses_and_is_back_on_it_when_it_departs():
    game = _Game(
        {
            "10": _on_gate(),
            "11": _on_gate(owner=2),
            "12": {**_on_gate(), "position": [900.0, 900.0]},
            "13": _on_gate(template="units/athen/cavalry_javelineer_b"),
        }
    )
    door = _Door()
    bridge = _bridge(game, door)
    [away] = bridge.step()
    # Only the gate player's soldier of a type the mapping names, standing on the gate, crossed.
    assert [(game_type, look, carried) for _id, game_type, look, carried in door.arrivals] == [
        ("units:athen:infantry_spearman_b", "cc0-traveller", [])
    ]
    assert sorted(game.entities) == ["11", "12", "13"]
    bridge.handle([{"kind": "departed", "thing_id": away.thing_id, "why": "chose_to_leave"}])
    [back] = [e for key, e in game.entities.items() if key not in ("11", "12", "13")]
    assert back == {"template": HOPLITE, "position": [500.0, 500.0], "owner": 1}
    assert bridge.away == {}


def test_a_soldier_put_back_on_the_gate_crosses_again_only_once_it_has_stepped_off_it():
    game = _Game({"10": _on_gate()})
    door = _Door()
    bridge = _bridge(game, door)
    [away] = bridge.step()
    bridge.handle([{"kind": "departed", "thing_id": away.thing_id, "why": "chose_to_leave"}])
    [back] = list(game.entities)
    assert bridge.step() == [] and len(door.arrivals) == 1  # home on the gate, it stays
    game.entities[back]["position"] = [530.0, 530.0]  # it walks off the gate
    assert bridge.step() == []
    game.entities[back]["position"] = [501.0, 501.0]  # and onto it again
    [again] = bridge.step()
    assert len(door.arrivals) == 2 and again.thing_id != away.thing_id


def test_a_refused_soldier_stays_and_a_lost_answer_is_sent_again_as_the_same_arrival():
    game = _Game({"10": _on_gate()})
    door = _Door()
    clock = _Clock()
    bridge = _bridge(game, door, clock=clock)
    door.failing = OSError("no answer")
    assert bridge.step() == [] and "10" in game.entities
    assert bridge.step() == [] and len(door.arrivals) == 1  # it waits before sending it again
    clock.now += 31
    door.failing = None
    [away] = bridge.step()
    first, second = door.arrivals
    assert first[0] == second[0] == away.arrival_id  # the same arrival, so it crosses once
    game.entities["20"] = _on_gate()
    door.failing = _Refused(409)
    assert bridge.step() == [] and "20" in game.entities
    clock.now += 31
    bridge.step()
    assert door.arrivals[-1][0] != door.arrivals[-2][0]  # refused by name: a new arrival


def test_a_refused_arrival_and_the_grant_s_end_bring_every_soldier_back():
    game = _Game({"10": _on_gate(), "11": _on_gate()})
    door = _Door()
    bridge = _bridge(game, door)
    first, second = bridge.step()
    bridge.handle([{"kind": "arrival_refused", "arrival_id": first.arrival_id, "reason": "x"}])
    assert list(bridge.away) == [second.thing_id]
    bridge.handle([{"kind": "asked", "request_id": "r", "idle_label": "wait here a minute"}])
    assert door.answers == [("r", "wait here a minute")]  # it decides nothing
    bridge.handle([{"kind": "grant_ended", "reason": "revoked"}])
    assert bridge.ended and bridge.away == {}
    assert sorted(e["template"] for e in game.entities.values()) == [HOPLITE, HOPLITE]


def test_a_restart_brings_back_a_soldier_that_departed_while_the_adapter_was_down(tmp_path):
    journal = tmp_path / "gate.json"
    game = _Game({"10": _on_gate()})
    door = _Door()
    door.cursor = "c1"
    [away] = _bridge(game, door, journal=journal).step()
    restarted = _Door()
    restarted.cursor = "from-a-new-hello"
    bridge = _bridge(game, restarted, journal=journal)
    assert restarted.cursor == "c1" and list(bridge.away) == [away.thing_id]
    bridge.handle([{"kind": "departed", "thing_id": away.thing_id, "why": "sent_home"}])
    assert [e["template"] for e in game.entities.values()] == [HOPLITE]
