"""The film take's tools: the rules a live take is held to, checked with no server and no model.

*   the stop rule's guard counts each being's provider failures in a row across the batches of
    events it reads, counts no event twice, and stops at the third; any other decision ends a row;
*   a person's hand-over requests are written only when the world could offer them: the giver's
    pick-up within reach of the loose thing, the receiver's own pick-up where the giver is out of
    reach, the give once the giver holds it and the receiver is near, the last two only past the
    departures before the run's first visitor has left, none again before its wait or past its
    count;
*   an outside agent's allocation is what its run records sum to, in the runs' own order, and the
    provider errors in a row are those after its last answered call; a call is refused when one as
    dear as the dearest so far would pass the dollars; a run keeps each tool its mind called with
    the arguments it gave, or its words;
*   the film's take documents name a scene, a game mapping, an agents' bridge entry and a mind the
    tree holds, and move the viewer by keys the driver accepts; the take in a made town says the
    town in words, stands before its sentence and names the scene laid out for a town, and the
    opening alone ends at a mark the driver makes.
"""

from __future__ import annotations

import importlib.util
import json
import re
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


def test_an_agent_call_is_refused_when_one_as_dear_as_the_dearest_would_pass_the_dollars():
    runs = _tool("agent_toolkit_run")

    def may(calls: int, spent: str, dearest: str) -> bool:
        bound = {"max_calls": 5, "max_usd": Decimal("0.010")}
        return runs.may_call(calls, Decimal(spent), Decimal(dearest), **bound)

    assert may(0, "0", "0")
    assert may(4, "0.006", "0.004")
    # Room for the dollars spent, none for another call as dear as the dearest so far.
    assert not may(4, "0.007", "0.004")
    assert not may(1, "0.010", "0")
    assert not may(5, "0.001", "0.001")


def test_a_run_keeps_what_its_mind_called_and_said():
    runs = _tool("agent_toolkit_run")
    said = {"turn": "t-7", "action": "say something to everyone near", "line": "Hello everyone!"}
    called = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"function": {"name": "world__act", "arguments": json.dumps(said)}},
            {"function": {"name": "world__wait_for_turn", "arguments": "not json"}},
        ],
    }
    assert runs.answers_of(called, "2026-10-09T23:27:02+00:00") == [
        {"at": "2026-10-09T23:27:02+00:00", "tool": "world__act", "arguments": said},
        {
            "at": "2026-10-09T23:27:02+00:00",
            "tool": "world__wait_for_turn",
            "arguments": {"unread": "not json"},
        },
    ]
    words = {"role": "assistant", "content": "I took my turns."}
    assert runs.answers_of(words, "t") == [{"at": "t", "words": "I took my turns."}]
    assert runs.answers_of({"role": "assistant", "content": None}, "t") == []


def test_the_film_take_documents_name_what_the_tree_holds():
    manifest = json.loads((ROOT / "exulanica/models/models.manifest.json").read_text())
    driver = (DEMO / "film_take.mjs").read_text()
    for name in ("three-strangers-film.take.json", "three-strangers-in-town.take.json"):
        take = json.loads((DEMO / "takes" / name).read_text())
        assert take["profile"] == "exulanica.film-take/v1"
        assert (ROOT / take["scene"]).is_file()
        mapping = ROOT / "bridges/luanti/mod/exulanica_gate/mapping"
        assert (mapping / take["doors"]["game"]["mapping"]).is_file()
        assert json.loads((ROOT / take["doors"]["agents"]).read_text())["bridge"] == "agents"
        agent = take["hold"]["agent"]
        assert agent["mind"] in manifest["models"]
        assert "enter" in agent["task"].lower()
        assert Decimal(agent["max_usd"]) > 0 and agent["max_calls"] > 0
        for held in [*take["frame"], *take.get("stand", [])]:
            assert f"{held['key']}:" in driver and held["ms"] > 0


def test_a_take_in_a_made_town_says_the_town_and_stands_before_its_sentence():
    town = json.loads((DEMO / "takes/three-strangers-in-town.take.json").read_text())
    # A town of the person's own words, the scene laid out for a generated town, and a step
    # before the sentence: in a town a thing asked for lands ahead of where the person stands.
    assert town["world"]["describe"].strip() and town["stand"]
    scene = json.loads((ROOT / town["scene"]).read_text())
    assert scene["ground"]["kind"] == "generated" and scene["engine"] == "exulanica-society/v7"
    # The opening alone: a town from words, ended at a mark the driver makes before the story.
    opening = json.loads((DEMO / "takes/a-town-from-words.take.json").read_text())
    assert opening["profile"] == town["profile"] and opening["world"]["describe"].strip()
    assert opening["world"]["describe"] != town["world"]["describe"]
    driver = (DEMO / "film_take.mjs").read_text()
    assert f"'{opening['until']}'" in driver and f"mark('{opening['until']}')" in driver
    assert set(opening) == {"profile", "title", "world", "stand", "until"}


def test_the_driver_and_its_page_file_name_the_same_words_and_selectors():
    # The app's words and selectors live in one file so a changed interface is re-pointed there:
    # the driver uses nothing the file lacks, and the file holds nothing the driver stopped using.
    page = json.loads((DEMO / "film_page.json").read_text())
    assert page["profile"] == "exulanica.film-page/v1"
    driver = (DEMO / "film_take.mjs").read_text()
    for part in ("words", "selectors"):
        used = set(re.findall(rf"\b{part}\.([a-z_]+)", driver))
        assert used == set(page[part]), (part, used ^ set(page[part]))
    for value in page["words"].values():
        assert value and all(
            isinstance(word, str) and word
            for word in ([value] if isinstance(value, str) else value)
        )
    # No word of the app is left in the driver's own element lookups.
    assert not re.search(r"(?:button|buttonStarting|anyWords|shownWords)\('", driver)
