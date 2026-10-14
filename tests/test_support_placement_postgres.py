"""Normal support placement persists affinity, history and source identity under existing roles."""

from __future__ import annotations

import copy
import json
import os
import uuid
from pathlib import Path

import pytest
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world import WorldObjectRepository
from exulanica.world.authored_delta import canonical_delta_document
from exulanica.world.world_erasure import erase_world

from personal_world_support import STRANGER_TOKEN
from test_society_made_world import PILLAR
from test_society_made_world import made as imported_made  # noqa: F401
from test_support_site import authoring, context
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made(request):
    return request.getfixturevalue("imported_made")


def supported_world(api):
    response = api.post("/worlds/kinds", {"document": _uploaded("farm")})
    assert response.status_code == 201, response.text
    support = authoring(context()["base_place"])
    # A declared deck roomy enough for the actual rigid bench, away from its actor corridor.
    support["surfaces"][0]["rect_mm"] = [50000, -10340, 58000, -4340]
    response = api.post(
        "/worlds/kinds/fixture_farm/worlds",
        {"preset": "small_farm", "title": "Supported things", "support": support},
    )
    assert response.status_code == 201, response.text
    entry = response.json()
    prefix = f"/world/versions/{entry['authored_version_id']}"
    scope = f"?world_id={entry['world_id']}"
    drawing = api.get(prefix + "/site" + scope).json()
    version = api.get(prefix + scope).json()
    return entry, prefix, scope, drawing, version


def request_body(entry, drawing, version, **changes):
    kind = shipped_thing_kinds()[("bench", 2)]
    return {
        "base_state_sha256": version["state_sha256"],
        "thing_id": "thing:supported-bench",
        "kind": kind.reference(),
        "region_id": "region:generated",
        "position_mm": [55000, -8000],
        "yaw_microradians": 0,
        "origin_role": "fictional",
        "support": {
            "profile": "exulanica.support-reference/v1",
            "world_id": entry["world_id"],
            "source_snapshot_id": entry["source_snapshot_id"],
            "receipt_sha256": drawing["receipt_sha256"],
            "network_sha256": drawing["support"]["network"]["document_sha256"],
            "region_id": "region:generated",
            "surface_id": "deck",
        },
        **changes,
    }


def test_normal_supported_add_reopen_move_undo_branch_and_remove(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(entry, drawing, initial)
    preview = api.post(prefix + "/things/on-support/preview" + scope, body)
    assert preview.status_code == 200, preview.text
    assert api.get(prefix + scope).json() == initial  # Preview writes no state or edit.
    placed = api.post(prefix + "/things/on-support" + scope, body)
    assert placed.status_code == 201, placed.text
    saved = placed.json()
    assert saved["schema_version"] == 6
    [thing] = saved["things"]
    assert thing["profile"] == "exulanica.placed-thing/v2"
    assert thing["support"] == body["support"] and thing["transform"]["y_mm"] == 150
    assert preview.json()["placement"] == thing
    assert api.get(prefix + scope).json() == saved
    assert (
        api.get(prefix + "/things/thing:supported-bench/support" + scope).json()["availability"]
        == "available"
    )
    stale = copy.deepcopy(body)
    stale["thing_id"] = "thing:stale"
    refused = api.post(prefix + "/things/on-support" + scope, stale)
    assert refused.status_code == 409 and refused.json()["code"] == "stale_object_base"
    assert api.get(prefix + scope).json() == saved
    foreign = api.get(prefix + scope, token=STRANGER_TOKEN)
    assert foreign.status_code == 404
    with api.database.session(api.repository.workspace_id) as connection:
        repository = WorldObjectRepository(
            connection, api.repository.workspace_id, world_id=entry["world_id"], store=api.store
        )
        held = repository.version(uuid.UUID(entry["authored_version_id"]))
        delta = canonical_delta_document(
            objects=held.objects,
            element_overrides=held.element_overrides,
            environment_instances=held.environment_instances,
            point_map_instances=held.point_map_instances,
            things=held.things,
        )
        assert delta["schema_version"] == 5 and delta["things"] == saved["things"]
        history = connection.execute(
            "select after_document from world_alternate_version_edit "
            "where workspace_id=%s and world_id=%s and version_id=%s and kind='add_thing'",
            (api.repository.workspace_id, entry["world_id"], held.version_id),
        ).fetchone()
        assert history["after_document"] == thing
    branch = api.post(
        "/world/versions" + scope,
        {"parent_version_id": entry["authored_version_id"], "title": "Same source branch"},
    )
    assert branch.status_code == 201, branch.text
    assert branch.json()["things"] == saved["things"]
    moved = api.post(
        prefix + "/things/thing:supported-bench/move" + scope,
        {
            "base_state_sha256": saved["state_sha256"],
            # A freeform move onto open ground, as the farm's ground takes it, clears its support.
            "pose": {"x_mm": 45000, "y_mm": 0, "z_mm": -7000, "yaw_microradians": 123456},
        },
    )
    assert moved.status_code == 200, moved.text
    assert "support" not in moved.json()["things"][0] and moved.json()["schema_version"] == 5
    undone = api.post(
        prefix + "/things/undo" + scope, {"base_state_sha256": moved.json()["state_sha256"]}
    )
    assert undone.status_code == 200, undone.text
    assert (
        undone.json()["things"] == saved["things"]
        and undone.json()["state_sha256"] == saved["state_sha256"]
    )
    removed = api.post(
        prefix + "/things/thing:supported-bench/remove" + scope,
        {"base_state_sha256": undone.json()["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    assert (
        removed.json()["things"][0]["removed"]
        and removed.json()["things"][0]["support"] == body["support"]
    )
    restored = api.post(
        prefix + "/things/undo" + scope, {"base_state_sha256": removed.json()["state_sha256"]}
    )
    assert restored.status_code == 200 and restored.json()["things"] == saved["things"]
    evidence_path = os.environ.get("EXULANICA_SUPPORT_PLACEMENT_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(
            json.dumps(
                {
                    "origin": "normal API, authored source; no model/browser evidence",
                    "entry": entry,
                    "drawing": drawing,
                    "request": body,
                    "preview": preview.json(),
                    "saved": saved,
                    "branch": branch.json(),
                    "moved": moved.json(),
                    "undo": undone.json(),
                    "removed": removed.json(),
                    "restored": restored.json(),
                },
                indent=2,
            )
            + "\n"
        )


def test_bad_source_clearance_other_things_and_world_removal_are_explicit(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(entry, drawing, initial)
    bad = copy.deepcopy(body)
    bad["support"]["network_sha256"] = "0" * 64
    refused = api.post(prefix + "/things/on-support" + scope, bad)
    assert refused.status_code == 422, refused.text
    assert api.get(prefix + scope).json() == initial
    bad = {**body, "position_mm": [51000, -5340]}
    assert api.post(prefix + "/things/on-support" + scope, bad).status_code == 422
    placed = api.post(prefix + "/things/on-support" + scope, body)
    assert placed.status_code == 201, placed.text
    overlap = request_body(entry, drawing, placed.json(), thing_id="thing:overlap")
    refused = api.post(prefix + "/things/on-support" + scope, overlap)
    assert refused.status_code == 422 and "obstructions" in refused.json()["detail"]
    assert api.get(prefix + scope).json() == placed.json()
    with api.database.session(api.repository.workspace_id) as connection:
        erase_world(connection, api.repository.workspace_id, entry["world_id"], erased_by=api.actor)
        assert not connection.execute(
            "select 1 from world_alternate_thing where workspace_id=%s and world_id=%s",
            (api.repository.workspace_id, entry["world_id"]),
        ).fetchone()
    assert api.get(prefix + "/things/thing:supported-bench/support" + scope).status_code == 410
    assert api.post(prefix + "/things/on-support" + scope, body).status_code == 410


def test_general_mesh_edits_remain_finite_transforms_and_unknown_clearance_is_explicit(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    placed = api.post(prefix + "/things/on-support" + scope, request_body(entry, drawing, initial))
    assert placed.status_code == 201, placed.text
    binding = placed.json()["things"][0]["support"]
    added = api.post(
        prefix + "/objects" + scope,
        {
            "base_state_sha256": placed.json()["state_sha256"],
            "object_id": "object:unproxied",
            "asset_sha256": PILLAR.content_sha256,
            "region_id": "region:generated",
            "origin_role": "fictional",
            "transform": {
                "x_mm": 6000,
                "y_mm": 5000,
                "z_mm": 6000,
                "yaw_microradians": 123456,
                "scale_milli": 1000,
            },
        },
    )
    assert added.status_code == 201, added.text
    moved = api.post(
        prefix + "/objects/object:unproxied/move" + scope,
        {
            "base_state_sha256": added.json()["state_sha256"],
            "transform": {
                "x_mm": 7000,
                "y_mm": 10000,
                "z_mm": 7000,
                "yaw_microradians": 98765,
                "scale_milli": 1200,
            },
        },
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["things"][0]["support"] == binding
    availability = api.get(prefix + "/things/thing:supported-bench/support" + scope).json()
    assert availability["availability"] == "unavailable" and availability["where"] == "obstructions"
    removed = api.post(
        prefix + "/objects/object:unproxied/remove" + scope,
        {"base_state_sha256": moved.json()["state_sha256"]},
    )
    assert removed.status_code == 200, removed.text
    assert (
        api.get(prefix + "/things/thing:supported-bench/support" + scope).json()["availability"]
        == "available"
    )
