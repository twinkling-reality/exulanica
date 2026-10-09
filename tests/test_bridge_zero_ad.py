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
import urllib.error
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


#: Every published version of the mapping, oldest first.
MAPPINGS = sorted((ADAPTER / "mapping").glob("zero-ad-empires-ascendant.v*.json"))


def _mapping(version: int = 1) -> dict[str, Any]:
    named = ADAPTER / "mapping" / f"zero-ad-empires-ascendant.v{version}.json"
    return json.loads(named.read_text())


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


@pytest.mark.parametrize("published", MAPPINGS, ids=lambda path: path.name)
def test_every_published_mapping_and_its_reads_meet_the_door_s_checks(published):
    assert [path.name for path in MAPPINGS] == [
        "zero-ad-empires-ascendant.v1.json",
        "zero-ad-empires-ascendant.v2.json",
    ]
    reads = json.loads((ADAPTER / "mapping" / "reads.json").read_text())
    mapping = check_mapping(json.loads(published.read_text()))
    assert check_reads(mapping, reads)
    assert [visitor["kind"] for visitor in mapping["visitors"]] == [
        {"key": "traveller", "version": 2}
    ]
    assert mapping["items"] == []  # a 0 A.D. unit carries no item, so none crosses either way


def test_the_second_mapping_crosses_what_the_first_does_in_words_that_name_no_game():
    """A film or a demo names no game, and a visitor's card shows its manifest's words, which are
    its mapping's: version 2 crosses exactly what version 1 crosses, and only its words differ."""
    from test_door_names_no_game import GAME_NAMES

    first, second = _mapping(1), _mapping(2)
    assert GAME_NAMES.search(json.dumps(first)) is not None
    assert GAME_NAMES.search(json.dumps(second)) is None
    assert second["game"] == {"label": "another open-source game"}
    assert second["visitors"][0]["label"] == "a soldier from another open-source game"

    def crossings(mapping: dict[str, Any]) -> dict[str, Any]:
        """The mapping without its version and the words a person reads for its game and
        visitor."""
        kept = json.loads(json.dumps(mapping))
        for key in ("version", "game"):
            kept.pop(key)
        for visitor in kept["visitors"]:
            for key in ("label", "words"):
                visitor.pop(key)
        return kept

    assert crossings(second) == crossings(first)
    assert (first["version"], second["version"]) == (1, 2)


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


def _run_check() -> Any:
    """``run/check.py``, which declares the bridge for a stack and runs a crossing."""
    spec = importlib.util.spec_from_file_location("zero_ad_run_check", ADAPTER / "run" / "check.py")
    assert spec is not None and spec.loader is not None
    check = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(check)
    return check


def test_a_game_with_no_match_yet_answers_its_interface():
    """A game just started answers every route but /reset with 400 until a match starts: the check
    takes that as the game listening (a run against a freshly started game found it refused), and
    no answer, or another server's answer, as no game."""
    check = _run_check()
    rl = _module("rl")

    def answering(status: int):
        def opener(request, timeout):
            body = io.BytesIO(b"Game not running. Please create a scenario first.")
            raise urllib.error.HTTPError(request.full_url, status, "refused", {}, body)

        return opener

    def silent(request, timeout):
        raise urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))

    def game(opener) -> Any:
        return rl.RLInterface("http://127.0.0.1:19508", opener=opener)

    assert check.game_answers(game(answering(400)))
    assert not check.game_answers(game(answering(404)))
    assert not check.game_answers(game(silent))


def _admitted(declarations: Path) -> dict[str, Any]:
    """The bridges a stack started with ``declarations`` admits, read by the door's own setting
    reader once the launcher names the run's workspace where an entry says synthetic."""
    from exulanica.door.bridges import load_bridge_directory

    setting = json.dumps(
        [
            {**entry, "workspaces": ["6f1b9a52-4d1e-4c55-9e4b-0c8f0d2b7a11"]}
            if entry.get("workspaces") == "synthetic"
            else entry
            for entry in json.loads(declarations.read_text())
        ]
    )
    return dict(load_bridge_directory({"EXULANICA_DOOR_BRIDGES": setting}).bridges)


def test_the_run_declares_its_bridge_in_words_that_name_no_game(tmp_path):
    """A film or a demo names no game: by default the bridge is declared in neutral words, which the
    door's own setting reader admits as what a world shows for where its visitors came from."""
    from exulanica.canonical import sha256_of_canonical

    from test_door_names_no_game import GAME_NAMES

    out = tmp_path / "bridges.json"
    assert _run_check().main(["--declare", str(out)]) == 0
    [entry] = json.loads(out.read_text())
    assert (entry["label"], entry["game"]) == (
        "another open-source game",
        "another open-source game",
    )
    assert GAME_NAMES.search(entry["label"] + " " + entry["game"]) is None
    bridge = _admitted(out)["zero-ad"]
    assert (bridge.label, bridge.game) == (entry["label"], entry["game"])
    digests = [sha256_of_canonical(json.loads(path.read_text())).hex() for path in MAPPINGS]
    assert bridge.mapping_sha256 == set(digests)
    # Version 1, which a crossing says hello with unless another is chosen, is pinned first.
    assert entry["mapping_sha256"][0] == digests[0]


def test_a_declaration_pins_every_published_mapping_the_chosen_one_first(tmp_path):
    """Every published version stays let in, whichever a crossing says hello with."""
    from exulanica.canonical import sha256_of_canonical

    out = tmp_path / "bridges.json"
    chosen = "zero-ad-empires-ascendant.v2.json"
    assert _run_check().main(["--declare", str(out), "--mapping", chosen]) == 0
    [entry] = json.loads(out.read_text())
    digests = {
        path.name: sha256_of_canonical(json.loads(path.read_text())).hex() for path in MAPPINGS
    }
    assert entry["mapping_sha256"][0] == digests[chosen]
    assert sorted(entry["mapping_sha256"]) == sorted(digests.values())
    with pytest.raises(SystemExit):
        _run_check().main(["--declare", str(out), "--mapping", "reads.json"])


def test_a_declaration_joins_the_file_another_game_declared_first(tmp_path):
    """One stack lets both games in: the bridge is written beside the bridges the file declares
    (the Luanti tool writes its file anew, so it goes first), and declaring it again replaces its
    entry, since the door refuses a bridge declared twice."""
    spec = importlib.util.spec_from_file_location(
        "luanti_cross_once", ADAPTER.parent / "luanti" / "tools" / "cross_once.py"
    )
    assert spec is not None and spec.loader is not None
    luanti = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(luanti)
    out = tmp_path / "bridges.json"
    luanti.declare(out, label="an open-source block game", game="an open-source block game")
    [declared_first] = json.loads(out.read_text())
    check = _run_check()
    assert check.main(["--declare", str(out)]) == 0
    assert check.main(["--declare", str(out), "--label", "a strategy game"]) == 0
    declared = json.loads(out.read_text())
    assert [entry["bridge"] for entry in declared] == ["luanti", "zero-ad"]
    assert declared[0] == declared_first
    admitted = _admitted(out)
    assert sorted(admitted) == ["luanti", "zero-ad"]
    assert admitted["zero-ad"].label == "a strategy game"


@pytest.mark.parametrize(
    ("option", "words"), [("--label", ""), ("--label", "two\nlines"), ("--game-words", "x" * 81)]
)
def test_a_declared_label_or_game_is_one_line_of_1_to_80_characters(tmp_path, option, words):
    """The door takes a bridge's label and game as one line of 1 to 80 characters: other words
    are refused before anything is written."""
    out = tmp_path / "bridges.json"
    with pytest.raises(SystemExit, match="one line of 1 to 80 characters"):
        _run_check().main(["--declare", str(out), option, words])
    assert not out.exists()
