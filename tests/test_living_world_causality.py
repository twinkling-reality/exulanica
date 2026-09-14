"""Real district geometry + pure production policy, never authenticated DB evidence."""

import json
from copy import deepcopy

import pytest
from exulanica.canonical import canonical_json
from exulanica.world.assets import reviewed_assets
from scripts.prepare_living_world_preview import (
    DEFAULT_BASE,
    PreviewScenario,
    generate_causal_preview,
    verify_preview,
    write_preview,
)


@pytest.fixture(scope="module")
def proof():
    return generate_causal_preview(DEFAULT_BASE.read_bytes())


def test_same_inhabitant_uses_loses_and_uses_restored_authored_affordance(proof):
    edited, control = proof["treatment"], proof["no_edit"]
    assert edited["inputs"][0] == control["inputs"][0]
    assert edited["frames"][:5] == control["frames"][:5]
    assert [i["authored_state"]["edit_seq"] for i in edited["inputs"]] == [0, 1, 2, 3]
    assert len(control["inputs"]) == 1
    events = proof["evidence"]["witness_events"]
    assert len({e["subject_id"] for e in events}) == 1
    assert any(
        e["event_kind"] == "goal_selected" and e["document"]["reason"] == "visit_place"
        for e in events
    )
    assert any(
        e["event_kind"] == "route_progressed"
        and e["document"]["reason"] == "arrived_at_access_node"
        and len(e["document"]["motion_path_mm"]) > 1
        for e in events
    )
    assert any(e["event_kind"] == "action_completed" and e["tick"] < 10 for e in events)
    assert any(
        e["event_kind"] == "replanned"
        and e["tick"] == 10
        and e["document"]["reason"] == "target_disabled_or_removed"
        for e in events
    )
    assert any(e["event_kind"] == "action_completed" and e["tick"] > 13 for e in events)
    assert not any(e["event_kind"] == "action_completed" and 10 <= e["tick"] < 13 for e in events)
    assert proof["evidence"]["active_actions_interrupted"] > 0
    interrupted = next(row for row in proof["evidence"]["comparisons"] if row["tick"] == 9)
    assert interrupted["treatment"]["action"]["status"] == "active"
    assert interrupted["treatment"]["target"]["object_id"] == proof["scenario"]["object_id"]
    assert any(
        row["treatment"]["position_mm"] != row["no_edit"]["position_mm"]
        for row in proof["evidence"]["comparisons"]
    )
    for frame in edited["frames"][10:13]:
        assert frame["authored_objects"] == []
        assert all(
            (p.get("target") or {}).get("object_id") != proof["scenario"]["object_id"]
            for p in frame["snapshot"]["state"]["inhabitants"]
        )
    assert edited["frames"][5]["authored_objects"] == edited["frames"][13]["authored_objects"]


def test_source_asset_branch_seed_and_version_receipts_remain_explicit(proof):
    edited = proof["treatment"]
    asset = next(a for a in reviewed_assets() if a.asset_key == proof["scenario"]["asset_key"])
    document = edited["inputs"][1]
    refs = document["dependency_refs"]
    assert any(ref["sha256"] == asset.content_sha256 for ref in refs)
    assert any(ref["kind"] == "fixture_source" for ref in refs)
    assert any(ref["kind"] == "society_affordance_registry" for ref in refs)
    assert any(
        ref["kind"] == "fixture_generator"
        and ref["identity"] == "exulanica.living-world-preview-generator/v2"
        for ref in refs
    )
    target = next(
        t for t in document["targets"] if t["object_id"] == proof["scenario"]["object_id"]
    )
    assert target["affordance"] == "visit" and target["duration_ticks"] == 1
    for event in proof["evidence"]["witness_events"]:
        receipt = event["document"]
        assert receipt["target"]["version_id"] == target["version_id"]
        assert receipt["branch_id"] == target["version_id"]
        assert receipt["seed_sha256"] == edited["frames"][0]["snapshot"]["seed"]
        assert (
            receipt["input_sha256"] == edited["inputs"][receipt["input_seq"] - 1]["document_sha256"]
        )
    assert all(len(f["snapshot"]["state"]["inhabitants"]) == 128 for f in edited["frames"])


def test_saved_and_reopened_histories_replay_exactly_including_events(proof, tmp_path):
    path = tmp_path / "causal.json"
    write_preview(proof, path)
    reopened = json.loads(path.read_bytes())
    assert canonical_json(reopened) == canonical_json(proof)
    for name in ("treatment", "no_edit"):
        verify_preview(reopened[name], DEFAULT_BASE.read_bytes())
    # Current restored geometry cannot replace the historical remove receipt.
    altered = deepcopy(reopened["treatment"])
    altered["inputs"][2] = deepcopy(altered["inputs"][3])
    with pytest.raises(ValueError):
        verify_preview(altered, DEFAULT_BASE.read_bytes())
    altered = deepcopy(reopened["treatment"])
    altered["events"][0]["document"]["reason"] = "invented biography"
    with pytest.raises(ValueError, match="event replay mismatch"):
        verify_preview(altered, DEFAULT_BASE.read_bytes())


def test_regeneration_is_exact_and_counterfactual_is_not_authored_animation(proof):
    assert canonical_json(generate_causal_preview(DEFAULT_BASE.read_bytes())) == canonical_json(
        proof
    )


def test_unproductive_rest_scenario_cannot_claim_a_causal_witness():
    scenario = PreviewScenario(
        asset_key="cc0.marker-plate",
        object_id="object:preview-rest-pad",
        node_id="nyc-flatiron-owned-v1/walk:48000:132000",
        offset_mm=(0, 0),
        edit_ticks=(5, 9, 13),
    )
    with pytest.raises(ValueError, match="lacks a witness"):
        generate_causal_preview(DEFAULT_BASE.read_bytes(), scenario=scenario)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"edit_ticks": (5, 4, 13)},
        {"final_tick": 101},
        {"offset_mm": (1.2, 0)},
        {"final_tick": True},
    ],
)
def test_scenario_parameters_are_bounded(kwargs):
    with pytest.raises(ValueError, match="invalid bounded"):
        PreviewScenario(**kwargs)
