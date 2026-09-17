from contextlib import suppress
from copy import deepcopy

import pytest
from exulanica.world.society import society_state_sha256
from exulanica.world.society_legacy import initial_society
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    validate_society_input,
)

from society_fixtures import SEED, SOCIETY, edited, seal, society_input


def test_population_identity_purposeful_routes_and_timed_actions():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    assert [p["id"] for p in state["inhabitants"]] == [
        p["id"] for p in initial_society(SOCIETY, SEED)["inhabitants"]
    ]
    before = deepcopy(state)
    all_events = []
    for _ in range(8):
        state, events = advance_purposeful_society(state, SEED, [doc])
        all_events.extend(events)
        for person in state["inhabitants"]:
            assert len(person["memory"]) <= 16
            assert all(x == 40000 or z == 0 for x, z in person["motion_path_mm"])
            assert person["motion_path_mm"][-1] == person["position_mm"]
    assert before["tick"] == 0
    completed = [e for e in all_events if e.kind == "action_completed"]
    assert len({e.subject_id for e in completed}) > 24
    assert {e.document["target"]["affordance"] for e in completed} == {"rest", "visit"}
    assert len(state["inhabitants"]) == 128
    assert all(e.object_id is None and e.document["synthetic"] for e in all_events)
    assert any(len(e.document["motion_path_mm"]) == 3 for e in all_events)
    for event in completed:
        start = next(
            e
            for e in reversed(all_events[: all_events.index(event)])
            if e.subject_id == event.subject_id and e.document["outcome"] == "action_started"
        )
        assert event.tick - start.tick == event.document["target"]["duration_ticks"]


def test_move_disable_add_and_undo_react_without_rewriting_history():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    state, first = advance_purposeful_society(state, SEED, [doc])
    saved = deepcopy(state)
    moved = edited(doc)
    moved["targets"][0]["node_id"] = "a"
    seal(moved)
    disabled = edited(moved)
    disabled["targets"][0]["enabled"] = False
    seal(disabled)
    restored = edited(disabled)
    restored["targets"][0] = deepcopy(doc["targets"][0])
    seal(restored)
    changed, events = advance_purposeful_society(state, SEED, [doc, moved, disabled, restored])
    assert state == saved
    assert changed["input_seq"] == 4
    assert any(e.kind == "replanned" and e.document["input_seq"] == 2 for e in events)
    again, replay_events = advance_purposeful_society(saved, SEED, [doc, moved, disabled, restored])
    assert again == changed and replay_events == events
    assert first != events
    assert all(e.document["input_seq"] <= 4 for e in events)


def test_disabled_targets_block_then_added_target_wakes_population():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    disabled = edited(doc)
    for target in disabled["targets"]:
        target["enabled"] = False
    seal(disabled)
    blocked, events = advance_purposeful_society(state, SEED, [doc, disabled])
    assert all(p["action"]["status"] == "blocked" for p in blocked["inhabitants"])
    same, repeated = advance_purposeful_society(blocked, SEED, [disabled])
    assert not repeated
    added = edited(disabled)
    new = deepcopy(doc["targets"][0])
    new["target_id"] = "authored:new-bench:rest"
    new["object_id"] = "object:new-bench"
    new["subject_id"] = "authored:new-bench"
    added["targets"].append(new)
    added["targets"].sort(key=lambda t: t["target_id"])
    seal(added)
    resumed, events = advance_purposeful_society(same, SEED, [disabled, added])
    assert any(e.kind == "goal_selected" for e in events)
    assert all(p["goal"]["target_id"] == new["target_id"] for p in resumed["inhabitants"])


def test_removed_edge_blocks_mid_edge_position_without_snap_and_restore_resumes():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    state, _ = advance_purposeful_society(state, SEED, [doc])
    mid = next(p for p in state["inhabitants"] if p["location"]["edge"])
    changed = edited(doc)
    changed["navigation"]["edges"] = changed["navigation"]["edges"][:1]
    seal(changed)
    blocked, _events = advance_purposeful_society(state, SEED, [doc, changed])
    person = next(p for p in blocked["inhabitants"] if p["id"] == mid["id"])
    assert person["position_mm"] == mid["position_mm"]
    assert person["action"]["reason"] == "current_position_invalidated"
    assert person["motion_path_mm"] == [mid["position_mm"]]
    restored = edited(changed)
    restored["navigation"] = deepcopy(doc["navigation"])
    seal(restored)
    resumed, _ = advance_purposeful_society(blocked, SEED, [changed, restored])
    assert (
        next(p for p in resumed["inhabitants"] if p["id"] == mid["id"])["action"]["status"]
        == "active"
    )


def test_disconnected_target_is_not_selected_and_unavailable_input_pauses():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    changed = edited(doc)
    for t in changed["targets"]:
        t["node_id"] = "d"
    seal(changed)
    blocked, _ = advance_purposeful_society(state, SEED, [doc, changed])
    assert all(p["action"]["reason"] == "no_reachable_affordance" for p in blocked["inhabitants"])
    unavailable = edited(changed)
    unavailable.update(availability="unavailable", unavailable_reason="source_withdrawn")
    seal(unavailable)
    paused, events = advance_purposeful_society(blocked, SEED, [changed, unavailable])
    assert all(p["action"]["reason"] == "source_withdrawn" for p in paused["inhabitants"])
    assert all(len(p["motion_path_mm"]) == 1 for p in paused["inhabitants"])
    assert events


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(profile="unknown"),
        lambda d: d.update(input_seq=True),
        lambda d: d["navigation"]["edges"][0].update(length_mm=1),
        lambda d: d["navigation"]["nodes"][0].update(position_mm=[0.0, 0]),
        lambda d: d["targets"][0].update(affordance="repair"),
        lambda d: d["targets"][0].update(version_id="00000000-0000-0000-0000-000000000000"),
        lambda d: d["targets"][0].update(enabled=1),
        lambda d: d["frame"].update(name="unregistered"),
    ],
)
def test_malformed_input_fails_closed(mutation):
    doc = society_input()
    mutation(doc)
    with suppress(ValueError, TypeError):
        seal(doc)
    with pytest.raises(ValueError):
        validate_society_input(doc)


def test_wrong_seed_missing_or_reordered_input_history_refused():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    next_doc = seal(edited(doc))
    with pytest.raises(ValueError, match="seed"):
        advance_purposeful_society(state, "ab" * 32, [doc])
    with pytest.raises(ValueError, match="binding"):
        advance_purposeful_society(state, SEED, [next_doc])
    with pytest.raises(ValueError, match="gap"):
        advance_purposeful_society(state, SEED, [doc, seal(edited(next_doc))])
    replay = initial_purposeful_society(SOCIETY, SEED, doc)
    assert society_state_sha256(state) == society_state_sha256(replay)


def test_disabling_rest_cancels_active_timer_before_completion():
    doc = society_input()
    state = initial_purposeful_society(SOCIETY, SEED, doc)
    state, _ = advance_purposeful_society(state, SEED, [doc])
    resting = {p["id"] for p in state["inhabitants"] if p["action"]["kind"] == "rest"}
    assert resting
    disabled = edited(doc)
    disabled["targets"][0]["enabled"] = False
    seal(disabled)
    after, events = advance_purposeful_society(state, SEED, [doc, disabled])
    assert not any(e.kind == "action_completed" and str(e.subject_id) in resting for e in events)
    assert any(
        e.kind == "replanned" and e.document["reason"] == "target_disabled_or_removed"
        for e in events
    )
    assert all(p["action"]["kind"] != "rest" for p in after["inhabitants"])
