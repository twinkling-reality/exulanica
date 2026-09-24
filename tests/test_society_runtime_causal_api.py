"""Authenticated causal behavior on admitted A geometry, real edits, and durable v2 receipts."""

import json
from copy import deepcopy

import pytest
from exulanica.environment.district_geometry import DistrictGeometry
from exulanica.world.assets import reviewed_assets
from exulanica.world.society_planner import advance_purposeful_society, ordered_events_document
from fastapi.testclient import TestClient
from scripts.prepare_living_world_preview import PreviewScenario, _registry, assert_supported_motion

import test_society_runtime_api as helpers
from test_society_runtime import BASE

registered_world = helpers.runtime_world
runtime_app = helpers.runtime_app
pytestmark = pytest.mark.postgres


@pytest.fixture
def runtime_world(registered_world):
    # Extend the existing reviewed host configuration before runtime_app serializes it.
    # Actual source admissions, reviewed asset store, auth, Services and hooks are unchanged.
    registered_world["registry"].update(_registry())
    return registered_world


def test_authenticated_causal_use_interruption_restore_and_fresh_services_replay(runtime_app):
    w, make_app = runtime_app
    scenario = PreviewScenario()
    add, remove, restore = scenario.edit_ticks
    binding = w["binding"]
    scope = {"world_id": binding.world_id}
    version_route = f"/world/versions/{binding.version_id}"
    route = version_route + "/society"
    owner = helpers.OWNER_HEADERS
    seed = "7a" * 32
    asset = next(a for a in reviewed_assets() if a.asset_key == scenario.asset_key)
    geometry = DistrictGeometry(json.loads(BASE.read_bytes()))
    snapshots = []
    controls = []
    expected_events = []
    http_events = {}
    object_digest = w["version"].state_sha256

    with TestClient(make_app()) as client:
        response = client.post(
            route,
            headers=owner,
            params=scope,
            json={
                "place_id": str(binding.place_id),
                "region_id": binding.region_id,
                "seed": seed,
                "profile": "exulanica-society/v2",
            },
        )
        assert response.status_code == 200, response.text
        snapshot = response.json()
        snapshots.append(snapshot)
        initial_input = helpers.input_history(w)[0]
        node = next(
            n for n in initial_input["navigation"]["nodes"] if n["node_id"] == scenario.node_id
        )
        expected = deepcopy(snapshot["state"])
        control = deepcopy(expected)
        controls.append(control)
        for tick in range(1, scenario.final_tick + 1):
            if tick == add:
                response = client.post(
                    version_route + "/objects",
                    headers=owner,
                    params=scope,
                    json={
                        "base_state_sha256": object_digest,
                        "object_id": scenario.object_id,
                        "asset_sha256": asset.content_sha256,
                        "region_id": binding.region_id,
                        "origin_role": "fictional",
                        "transform": {
                            "x_mm": node["position_mm"][0] + scenario.offset_mm[0],
                            "y_mm": 0,
                            "z_mm": node["position_mm"][1] + scenario.offset_mm[1],
                            "yaw_microradians": 0,
                            "scale_milli": 1000,
                        },
                    },
                )
                assert response.status_code == 201, response.text
                object_digest = response.json()["state_sha256"]
            elif tick in (remove, restore):
                suffix = f"/{scenario.object_id}/remove" if tick == remove else "/undo"
                response = client.post(
                    version_route + "/objects" + suffix,
                    headers=owner,
                    params=scope,
                    json={"base_state_sha256": object_digest},
                )
                assert response.status_code == 200, response.text
                object_digest = response.json()["state_sha256"]
            old_snapshot = snapshot
            response = client.post(
                route + "/steps",
                headers=owner,
                params=scope,
                json={
                    "base_tick": snapshot["current_tick"],
                    "base_state_sha256": snapshot["state_sha256"],
                },
            )
            assert response.status_code == 200, response.text
            snapshot = response.json()
            snapshots.append(snapshot)
            inputs = helpers.input_history(w)
            expected, events = advance_purposeful_society(
                expected, seed, inputs[expected["input_seq"] - 1 : snapshot["input_seq"]]
            )
            expected_events.extend(ordered_events_document(events))
            assert snapshot["state"] == expected
            assert_supported_motion(expected, geometry)
            control, _ = advance_purposeful_society(control, seed, [initial_input])
            controls.append(control)
            if tick < add:
                assert expected == control
            response = client.get(route + "/events", headers=owner, params=scope)
            assert response.status_code == 200, response.text
            http_events.update({e["event_id"]: e for e in response.json()["events"]})
            if tick == remove:
                # Stale writes cannot erase the action interrupted by the removal.
                assert (
                    client.post(
                        route + "/steps",
                        headers=owner,
                        params=scope,
                        json={
                            "base_tick": old_snapshot["current_tick"],
                            "base_state_sha256": old_snapshot["state_sha256"],
                        },
                    ).status_code
                    == 409
                )

        inputs = helpers.input_history(w)
        assert [i["authored_state"]["edit_seq"] for i in inputs] == [0, 1, 2, 3]
        assert (
            inputs[1]["authored_state"]["delta_sha256"]
            == inputs[3]["authored_state"]["delta_sha256"]
        )
        assert any(
            r["kind"] == "reviewed_asset" and r["sha256"] == asset.content_sha256
            for r in inputs[1]["dependency_refs"]
        )
        rows = (
            w["connection"]
            .execute(
                "select event_id,event_kind,document,document_sha256 from world_society_event "
                "where workspace_id=%s and society_id=%s "
                "order by tick,(document->>'order')::integer,event_id",
                (w["workspace"], snapshot["society_id"]),
            )
            .fetchall()
        )
        assert [
            (str(r["event_id"]), r["event_kind"], r["document"], r["document_sha256"]) for r in rows
        ] == [
            (e["event_id"], e["event_kind"], e["document"], e["document_sha256"])
            for e in expected_events
        ]
        target_events = [
            e
            for e in expected_events
            if (e["document"].get("target") or {}).get("object_id") == scenario.object_id
        ]
        used = {
            e["subject_id"]
            for e in target_events
            if e["event_kind"] == "action_completed" and e["tick"] < remove
        }
        active = {
            p["id"]
            for p in snapshots[remove - 1]["state"]["inhabitants"]
            if (p.get("target") or {}).get("object_id") == scenario.object_id
            and p["action"]["status"] == "active"
        }
        interrupted = {
            e["subject_id"]
            for e in target_events
            if e["tick"] == remove and e["document"]["reason"] == "target_disabled_or_removed"
        }
        reused = {
            e["subject_id"]
            for e in target_events
            if e["event_kind"] == "action_completed" and e["tick"] > restore
        }
        witnesses = sorted(used & active & interrupted & reused)
        assert witnesses, (
            "no persisted witness for completed use, active interruption and restored use"
        )
        witness = witnesses[0]
        witness_events = [e for e in target_events if e["subject_id"] == witness]
        assert any(
            e["event_kind"] == "goal_selected" and e["document"]["reason"] == "visit_place"
            for e in witness_events
        )
        assert any(
            e["document"]["reason"] == "arrived_at_access_node"
            and len(e["document"]["motion_path_mm"]) > 1
            for e in witness_events
        )
        assert all(e["event_id"] in http_events for e in witness_events)
        assert not any(
            e["event_kind"] == "action_completed" and remove <= e["tick"] < restore
            for e in target_events
        )
        assert any(
            next(p for p in s["state"]["inhabitants"] if p["id"] == witness)["position_mm"]
            != next(p for p in c["inhabitants"] if p["id"] == witness)["position_mm"]
            for s, c in zip(snapshots, controls, strict=True)
        )
        saved_events = client.get(route + "/events", headers=owner, params=scope).json()
        response = client.get(route + "/replay", headers=owner, params=scope)
        assert response.status_code == 200, response.text
        replay = response.json()
        assert replay["replay_verified"] and replay["state_sha256"] == snapshot["state_sha256"]

    # Actual new Services + SocietyRuntime from the same persisted host configuration.
    with TestClient(make_app()) as reloaded:
        for suffix, expected_result in (
            ("", snapshot),
            ("/events", saved_events),
            ("/replay", replay),
        ):
            response = reloaded.get(route + suffix, headers=owner, params=scope)
            assert response.status_code == 200, response.text
            assert response.json() == expected_result
            stranger = reloaded.get(route + suffix, headers=helpers.STRANGER_HEADERS, params=scope)
            assert stranger.status_code == 404
            assert reloaded.get(route + suffix, params=scope).status_code == 401
        # The interrupted/complete explanations are durable event documents, not new narration.
        restored_rows = (
            w["connection"]
            .execute(
                "select event_id,document from world_society_event where workspace_id=%s "
                "and society_id=%s and subject_id=%s order by tick,(document->>'order')::integer",
                (w["workspace"], snapshot["society_id"], witness),
            )
            .fetchall()
        )
        restored = {str(r["event_id"]): r["document"] for r in restored_rows}
        for event in witness_events:
            assert restored[event["event_id"]] == event["document"]
