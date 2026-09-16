"""Local projection failures, with instrumented geometry and pinned legacy replay vectors."""

from copy import deepcopy
from dataclasses import replace

import pytest
from exulanica.world.objects import ObjectBehaviour, Transform
from exulanica.world.society import society_state_sha256
from exulanica.world.society_composition import build_society_input
from exulanica.world.society_input_policy import LOCAL_COMPOSITION, LOCAL_INPUT, UNREACHABLE
from exulanica.world.society_planner import (
    advance_purposeful_society,
    initial_purposeful_society,
    input_sha256,
    ordered_events_document,
    validate_society_input,
)
from exulanica.world.society_social import advance_social_society, initial_social_society

from society_fixtures import SEED, SOCIETY
from test_society_composition import GeometryProbe, arguments, obj, version


def compose(held, seq=1, local=True, **changes):
    args = arguments(held)
    args.update(input_seq=seq, **changes)
    if local:
        args["composition_profile"] = LOCAL_COMPOSITION
    return build_society_input(**args)


def distant(**changes):
    return obj(
        object_id="object:far-marker", transform=Transform(1000000, 0, 0, 0, 1000), **changes
    )


def test_only_unreachable_reviewed_activity_is_excluded_and_reason_is_input_bound():
    held = version((distant(), obj()))
    doc = compose(held)
    assert doc["profile"] == LOCAL_INPUT and doc["availability"] == "available"
    assert doc["navigation"]["nodes"] and doc["navigation"]["edges"]
    assert any(t["origin"] == "district" for t in doc["targets"])
    assert any(t["object_id"] == obj().object_id for t in doc["targets"])
    assert doc["unavailable_affordances"] == [
        {
            "target_id": f"authored:{held.version_id}:object:far-marker:rest",
            "subject_id": f"authored:{held.version_id}:object:far-marker",
            "object_id": "object:far-marker",
            "version_id": str(held.version_id),
            "affordance": "rest",
            "reason": UNREACHABLE,
        }
    ]
    assert any(
        r["kind"] == "authored_object" and r["identity"].endswith(":object:far-marker")
        for r in doc["dependency_refs"]
    )
    assert any(
        r["kind"] == "society_composition_policy" and r["identity"] == LOCAL_COMPOSITION
        for r in doc["dependency_refs"]
    )
    assert doc == compose(held)
    assert held.objects[0].transform.x_mm == 1000000
    tampered = deepcopy(doc)
    tampered["unavailable_affordances"][0]["reason"] = "invented"
    with pytest.raises(ValueError):
        validate_society_input(tampered)


def test_unreachable_solid_object_still_prunes_its_verified_collision_segments():
    obstacle = distant(key="cc0.marker-cube")
    probe = GeometryProbe(block_edge=True)
    doc = compose(
        version((obstacle, obj())), supports=probe.supports, segment_blocked=probe.blocked
    )
    assert doc["availability"] == "available"
    assert "ab" not in {e["edge_id"] for e in doc["navigation"]["edges"]}
    assert doc["unavailable_affordances"][0]["object_id"] == obstacle.object_id
    assert any(t["object_id"] == obj().object_id for t in doc["targets"])
    assert probe.calls


@pytest.mark.parametrize(
    "changes",
    [
        {"asset_sha256": "e" * 64},
        {"transform": Transform(False, 0, 0, 0, 1000)},
        {"region_id": "unknown"},
        {"transform": Transform(0, 1, 0, 0, 1000)},
        {"transform": Transform(0, 0, 0, 1, 1000)},
        {"transform": Transform(0, 0, 0, 0, 2000)},
        {"behaviour": ObjectBehaviour("motion.bounded-path", 1, {})},
    ],
)
def test_unknown_or_unsupported_obstacle_still_invalidates_whole_projection(changes):
    bad = replace(distant(), **changes)
    doc = compose(version((bad, obj())))
    assert doc["availability"] == "unavailable"
    assert doc["navigation"]["nodes"] == doc["targets"] == doc["unavailable_affordances"] == []


@pytest.mark.parametrize(
    "changes",
    [
        {"registration": None},
        {"availability": "unavailable", "unavailable_reason": "source_withdrawn"},
    ],
)
def test_unknown_frame_and_withdrawal_never_become_local_failures(changes):
    doc = compose(version((distant(),)), **changes)
    assert doc["availability"] == "unavailable"
    assert doc["navigation"]["edges"] == doc["unavailable_affordances"] == []


@pytest.mark.parametrize("social", [False, True])
def test_move_unreachable_restore_replays_historical_inputs_and_affected_reasons(social):
    held = version((obj(),))
    initial = compose(held, local=False)
    moved = compose(
        version((replace(obj(), transform=Transform(1000000, 0, 0, 0, 1000)),), edit_seq=1), seq=2
    )
    restored = compose(replace(held, edit_seq=2), seq=3)
    init = initial_social_society if social else initial_purposeful_society
    advance = advance_social_society if social else advance_purposeful_society
    original = init(SOCIETY, SEED, initial)
    first, first_events, *_ = advance(original, SEED, [initial])
    affected = {
        p["id"]
        for p in first["inhabitants"]
        if (p["target"] or {}).get("object_id") == obj().object_id
    }
    assert affected
    second, events, *_ = advance(first, SEED, [initial, moved])
    assert any(
        e.kind == "replanned"
        and e.document["reason"] == UNREACHABLE
        and str(e.subject_id) in affected
        for e in events
    )
    assert all(p["action"]["reason"] != "input_unavailable" for p in second["inhabitants"])
    assert all(p["action"]["status"] != "blocked" for p in second["inhabitants"])
    control, *_ = advance(first, SEED, [initial])
    expected = {p["id"]: p for p in control["inhabitants"]}
    for person in second["inhabitants"]:
        if person["id"] not in affected:
            for field in ("goal", "action", "position_mm", "need_milli"):
                assert person[field] == expected[person["id"]][field]
    third, restored_events, *_ = advance(second, SEED, [moved, restored])
    again = init(SOCIETY, SEED, deepcopy(initial))
    for inputs, expected, expected_events in [
        ([initial], first, first_events),
        ([initial, moved], second, events),
        ([moved, restored], third, restored_events),
    ]:
        again, produced, *_ = advance(again, SEED, deepcopy(inputs))
        assert again == expected
        assert ordered_events_document(produced) == ordered_events_document(expected_events)
    assert len(third["inhabitants"]) == 128
    assert restored["unavailable_affordances"] == []
    assert initial["authored_state"]["delta_sha256"] == restored["authored_state"]["delta_sha256"]


def test_legacy_projection_and_v2_v3_state_event_bytes_are_unchanged():
    document = compose(version((obj(),)), local=False)
    assert (
        document["document_sha256"]
        == "2de683b0f30462726c969fbb2a98d3ba3182fb5fe67a24d16181fcea7882a5b0"
    )
    assert "unavailable_affordances" not in document
    for init, advance, expected_state, expected_events in [
        (
            initial_purposeful_society,
            advance_purposeful_society,
            "9ca6a18e89e15eb78b023245e7ccfe2a4777f2a317ff61309768baac40ad0168",
            "0992715d86b883d9d6ad3d7715c769fbaac4d70a9b76688ae2450ec2096d48dd",
        ),
        (
            initial_social_society,
            advance_social_society,
            "ee0cbc97632ca81dccbc9fdf3edf14a77b984bd171c3e61dcc87704fc9265ef3",
            "828f4fe5e9514d2a7df3b79b0462a7f7e15f9cac84e137b301a55931f4ac8183",
        ),
    ]:
        result, events, *_ = advance(init(SOCIETY, SEED, document), SEED, [document])
        assert society_state_sha256(result) == expected_state
        assert society_state_sha256(ordered_events_document(events)) == expected_events
    old_unreachable = compose(
        version((obj(transform=Transform(1000000, 0, 0, 0, 1000)),), edit_seq=1), local=False
    )
    assert (
        old_unreachable["document_sha256"]
        == "134ac038df32282e78b7f87dcde8f3704669da78a39a496023d142a5db8c130a"
    )
    assert old_unreachable["availability"] == "unavailable"


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown_node",
        "cross_branch",
        "duplicate",
        "wrong_reason",
        "available_overlap",
        "global_unavailable",
    ],
)
def test_local_failure_schema_is_strict_and_does_not_admit_a_navigation_target(mutation):
    doc = compose(version((distant(), obj())))
    local = doc["unavailable_affordances"][0]
    if mutation == "unknown_node":
        local["node_id"] = "invented"
    elif mutation == "cross_branch":
        local["version_id"] = "00000000-0000-0000-0000-000000000000"
    elif mutation == "duplicate":
        doc["unavailable_affordances"].append(deepcopy(local))
    elif mutation == "wrong_reason":
        local["reason"] = "unknown_collision"
    elif mutation == "available_overlap":
        local.update(
            {
                k: doc["targets"][-1][k]
                for k in ("target_id", "subject_id", "object_id", "version_id", "affordance")
            }
        )
    else:
        doc.update(availability="unavailable", unavailable_reason="source_withdrawn")
    doc["document_sha256"] = input_sha256(doc)
    with pytest.raises(ValueError):
        validate_society_input(doc)


def test_no_surviving_navigation_remains_globally_unavailable():
    probe = GeometryProbe()
    doc = compose(
        version((distant(key="cc0.marker-cube"),)),
        supports=probe.supports,
        segment_blocked=lambda *_args: True,
    )
    assert doc["availability"] == "unavailable"
    assert doc["unavailable_reason"] == "authored_obstacles_block_navigation"
    assert doc["unavailable_affordances"] == doc["navigation"]["nodes"] == []
