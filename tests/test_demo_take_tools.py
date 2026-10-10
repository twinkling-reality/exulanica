"""The film take's tools: the rules a live take is held to, checked with no server and no model.

*   the stop rule's guard counts each being's provider failures in a row across the batches of
    events it reads, counts no event twice, and stops at the third; any other decision ends a row;
*   a person's hand-over requests are written only when the world could offer them: the giver's
    pick-up within reach of the loose thing, the receiver's own pick-up where the giver is out of
    reach, the give once the giver holds it and the receiver is near, the last two only past the
    departures before the run's first visitor has left, none again before its wait or past its
    count;
*   an outside agent's allocation is what its run records sum to, in the runs' own order, and the
    provider errors in a row are those after its last answered call;
*   the film's take document names a scene, a game mapping, an agents' bridge entry and a mind the
    tree holds, and frames by keys the driver accepts.
"""

from __future__ import annotations

import importlib.util
import json
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "scripts/demo"
FILM_TAKE = DEMO / "takes/three-strangers-film.take.json"


def _tool(name: str):
    spec = importlib.util.spec_from_file_location(name, DEMO / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _decision(subject: str, tick: int, reason: str, order: int = 0) -> dict:
    return {
        "event_id": f"{subject}-{tick}-{order}",
        "event_kind": "decision_applied",
        "subject_id": subject,
        "tick": tick,
        "document": {"reason": reason, "order": order},
    }


def test_a_third_provider_failure_in_a_row_stops_the_run_and_another_decision_ends_a_row():
    guard = _tool("provider_failure_guard")
    streaks = guard.Streaks(limit=3)
    first = [
        _decision("knight", 1, "model_timed_out"),
        _decision("knight", 3, "model_call_failed"),
        _decision("spirit", 3, "model_timed_out", order=1),
        _decision("knight", 5, "validated_choice"),
        _decision("knight", 7, "model_timed_out"),
        {"event_id": "walk", "event_kind": "route_progressed", "subject_id": "knight", "tick": 8},
    ]
    assert streaks.feed(first) is None
    assert streaks.rows == {"knight": [(7, "model_timed_out")], "spirit": [(3, "model_timed_out")]}
    # The next read overlaps the last one: what was seen is not counted again.
    second = [
        *first[-2:],
        _decision("knight", 9, "model_unavailable"),
        _decision("spirit", 9, "answer_not_offered", order=1),
    ]
    assert streaks.feed(second) is None
    assert streaks.rows["spirit"] == []
    tripped = streaks.feed([_decision("knight", 11, "model_call_failed")])
    assert tripped == (
        "knight",
        [(7, "model_timed_out"), (9, "model_unavailable"), (11, "model_call_failed")],
    )


def _state(*, knight_at, sword_at, sword_held_by=None, traveller_at=None, knight_holds=0) -> dict:
    people = [
        {"id": "k", "kind": {"kind": "knight"}, "came_by": "placed", "position_mm": knight_at}
    ]
    if traveller_at is not None:
        people.append(
            {
                "id": "t",
                "kind": {"kind": "traveller"},
                "came_by": "crossed",
                "position_mm": traveller_at,
            }
        )
    things = [
        {"id": "s", "kind": {"kind": "sword"}, "held_by": sword_held_by, "position_mm": sword_at}
    ]
    things += [
        {"id": f"x{n}", "kind": {"kind": "lantern"}, "held_by": "k"} for n in range(knight_holds)
    ]
    return {"inhabitants": people, "things": things}


def test_a_request_is_written_only_when_the_world_could_offer_it():
    requests = _tool("hold_requests")
    plan = json.loads(FILM_TAKE.read_text())["hold"]["requests"]

    def choose(state, asked=None, now=1000.0, departures=1, after=1):
        return requests.choose(
            state, plan, asked or {}, now, departures=departures, after_departures=after
        )

    near = _state(knight_at=[0, 0], sword_at=[3000, 0])
    assert choose(near) == ("pick", plan["pick_words"])
    assert choose(_state(knight_at=[0, 0], sword_at=[3000, 0], knight_holds=2)) is None
    far = _state(knight_at=[20000, 0], sword_at=[0, 0], traveller_at=[2000, 0])
    assert choose(far) == ("receiver_pick", plan["receiver_pick_words"])
    # The first visitor of a run is about to be sent home: it is not the one asked.
    assert choose(far, departures=0, after=1) is None
    assert choose(_state(knight_at=[20000, 0], sword_at=[0, 0], traveller_at=[9000, 0])) is None
    holding = _state(knight_at=[0, 0], sword_at=[0, 0], sword_held_by="k", traveller_at=[4000, 0])
    assert choose(holding) == ("give", plan["give_words"])
    assert choose(holding, departures=0, after=1) is None
    apart = _state(knight_at=[0, 0], sword_at=[0, 0], sword_held_by="k", traveller_at=[9000, 0])
    assert choose(apart) is None
    taken = _state(knight_at=[0, 0], sword_at=[0, 0], sword_held_by="t", traveller_at=[4000, 0])
    assert choose(taken) == ("done", "")
    assert choose(taken, departures=0, after=1) is None
    # Not again before its wait, and not a third time.
    assert choose(near, asked={"pick": [950.0]}) is None
    assert choose(near, asked={"pick": [900.0]}) == ("pick", plan["pick_words"])
    assert choose(near, asked={"pick": [100.0, 200.0]}) is None


def test_an_agent_allocation_is_what_its_run_records_sum_to_in_their_own_order(tmp_path):
    runs = _tool("agent_toolkit_run")
    assert runs.used(tmp_path) == (0, Decimal(0), 0)

    def record(number: int, calls: int, usd: str, outcomes: list[str]) -> None:
        body = {"calls": calls, "usd": usd, "outcomes": outcomes}
        (tmp_path / f"agent-run-{number}.json").write_text(json.dumps(body))

    record(2, 3, "0.002", ["ok", "URLError", "TimeoutError"])
    record(10, 1, "0.001", ["HTTPError"])
    record(1, 9, "0.0036", ["ok"] * 9)
    assert runs.used(tmp_path) == (13, Decimal("0.0066"), 3)
    # A call the bound refused is no provider error, and an answered call ends the row.
    record(11, 2, "0.0004", ["ok", runs.REFUSED])
    assert runs.used(tmp_path) == (15, Decimal("0.0070"), 0)


def test_the_film_take_document_names_what_the_tree_holds():
    take = json.loads(FILM_TAKE.read_text())
    assert take["profile"] == "exulanica.film-take/v1"
    assert (ROOT / take["scene"]).is_file()
    mapping = ROOT / "bridges/luanti/mod/exulanica_gate/mapping" / take["doors"]["game"]["mapping"]
    assert mapping.is_file()
    assert json.loads((ROOT / take["doors"]["agents"]).read_text())["bridge"] == "agents"
    manifest = json.loads((ROOT / "exulanica/models/models.manifest.json").read_text())
    agent = take["hold"]["agent"]
    assert agent["mind"] in manifest["models"]
    assert "enter" in agent["task"].lower()
    assert Decimal(agent["max_usd"]) > 0 and agent["max_calls"] > 0
    driver = (DEMO / "film_take.mjs").read_text()
    for held in take["frame"]:
        assert f"{held['key']}:" in driver and held["ms"] > 0
