"""The society of things' replay measurement composes both its grounds with every thing usable,
plays runs that say lines and act with hands and replay byte for byte, and holds a run to the
pre-registration that fixed its design, script and tree."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from exulanica.world.scenes import shipped_scenes
from exulanica.world.society_comparison import replay

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import measure_things_comparison_replay as measure

HEAD = "a" * 40


@pytest.fixture(name="clean_tree")
def _clean_tree(monkeypatch):
    """The script's view of its tree: a clean checkout at :data:`HEAD`."""
    source = {"head": HEAD, "changed_paths": [], "drawing_code_sha256": measure.CODE_SHA256}
    monkeypatch.setattr(measure, "_source", lambda: dict(source))
    return source


def test_both_grounds_compose_their_scene_and_holdables_with_the_hands_module_on():
    for graph, scene in (
        (measure.compose_square(), measure.SQUARE_SCENE),
        (measure.compose_town(), measure.TOWN_SCENE),
    ):
        placed = {thing["thing_id"] for thing in graph["things"]}
        expected = {thing["thing_id"] for thing in shipped_scenes()[scene].document["things"]}
        assert expected <= placed
        assert len(placed - expected) == measure.HOLDABLES
        assert "exulanica-ability/hands/v2" in graph["document"]["modules"]


def test_the_town_is_measured_at_its_own_residents_and_the_stated_populations_below_them():
    graph = measure.compose_town()
    own = graph["document"]["population"]["size"]
    assert graph["populations"][-1] == own
    assert graph["populations"][:-1] == [p for p in measure.TOWN_POPULATIONS if p < own]


def test_a_scripted_run_says_lines_and_acts_with_hands_and_replays_byte_for_byte():
    graph = measure.compose_square()
    decided, plan = measure._plans(graph, 8, 30)[-1]
    played = measure.play(plan, measure._Acting())
    assert decided == len(played.start["inhabitants"]) and plan.group is None
    kinds = {event.kind for event in played.events}
    assert {"said", "picked_up"} <= kinds
    again = replay(
        plan,
        list(zip(played.requests, played.receipts, strict=True)),
        minute_digests=played.minute_digests,
    )
    assert (again.states, again.events, again.receipts) == (
        played.states,
        played.events,
        played.receipts,
    )


def _preregistered(tmp_path: Path) -> Path:
    path = tmp_path / "preregistration.json"
    assert measure.preregister(path) == 0
    return path


def test_a_run_is_held_to_the_pre_registration_that_fixed_its_design(tmp_path, clean_tree):
    path = _preregistered(tmp_path)
    assert measure._registered(path)["record"]["design"]["holdables"]["count"] == measure.HOLDABLES


@pytest.mark.parametrize(
    "change",
    ["head", "dirty", "script", "design", "digest", "record"],
)
def test_a_pre_registration_its_run_does_not_match_is_refused(
    tmp_path, clean_tree, monkeypatch, change
):
    path = _preregistered(tmp_path)
    if change == "head":
        clean_tree["head"] = "b" * 40
    elif change == "dirty":
        clean_tree["changed_paths"] = ["scripts/measure_things_comparison_replay.py"]
    elif change == "script":
        monkeypatch.setattr(
            measure, "_bound_files", lambda: {"script_sha256": "0" * 64, "reads": {}}
        )
    elif change == "design":
        monkeypatch.setattr(measure, "STATED_GROUPS", (4,))
    elif change == "digest":
        monkeypatch.setattr(measure, "CODE_SHA256", "0" * 64)
    else:
        wrapped = json.loads(path.read_text(encoding="utf-8"))
        wrapped["record"]["design"]["seed"] = "8" * 64
        path.write_text(json.dumps(wrapped), encoding="utf-8")
    with pytest.raises(SystemExit, match="refused"):
        measure._registered(path)


def test_a_pre_registration_is_refused_on_a_tree_that_is_not_clean(tmp_path, clean_tree):
    clean_tree["changed_paths"] = ["docs/society-experiments.md"]
    with pytest.raises(SystemExit, match="not clean"):
        measure.preregister(tmp_path / "preregistration.json")
