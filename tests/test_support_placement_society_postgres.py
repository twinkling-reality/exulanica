"""Fresh support-bound occupancy never disappears from an available society by accident."""

from __future__ import annotations

import dataclasses
import json
import os
import uuid
from pathlib import Path

import pytest
from exulanica.api.world_edit import (
    BaseStateBody,
    bound_edit,
    object_problem_code,
    writing_repository,
)
from exulanica.selection.validation import Session
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.objects import ObjectOrigin, Transform
from exulanica.world.placed_things import UNSCALED_MILLI, ThingPlacement, named_kind
from exulanica.world.society_engines import CREATES_HOLDING_THINGS
from exulanica.world.society_input_policy import OFF_GROUND

from test_society_made_world import made as imported_made  # noqa: F401
from test_support_placement_postgres import request_body, supported_world

pytestmark = pytest.mark.postgres


@pytest.fixture(name="made")
def _made(request):
    api = request.getfixturevalue("imported_made")
    api.client.app.state.services = dataclasses.replace(
        api.client.app.state.services,
        societies_of_things=True,
    )
    return api


def latest_input(api, entry):
    with api.database.session(api.repository.workspace_id) as connection:
        return connection.execute(
            "select i.document from world_society_input i join world_society s "
            "using(workspace_id,society_id) where s.workspace_id=%s and s.world_id=%s "
            "and s.version_id=%s order by i.input_seq desc limit 1",
            (api.repository.workspace_id, entry["world_id"], entry["authored_version_id"]),
        ).fetchone()["document"]


#: A lantern stood where the supported bench is, on its deck's height.
LANTERN_POSE = {"x_mm": 55000, "y_mm": 150, "z_mm": -8000, "yaw_microradians": 0}


def stood_unchecked(api, entry, base_state_sha256):
    """The lantern stood on the supported bench by a writer the ground's rule does not hold, a
    scene's arrangement (``exulanica/api/scene_dressing.py``), through the same society observer
    every authored edit reaches: the version it wrote, or the code its refusal answers with."""
    services = api.client.app.state.services
    observer = api.client.app.state.society_authored_edit
    session = Session(workspace_id=api.repository.workspace_id, actor=api.actor)
    with api.database.session(api.repository.workspace_id) as connection:
        repository = writing_repository(connection, session, services, observer, entry["world_id"])
        version_id = uuid.UUID(entry["authored_version_id"])
        placement = ThingPlacement(
            thing_id="thing:collision",
            kind=named_kind("lantern", 1),
            region_id="region:generated",
            transform=Transform(
                LANTERN_POSE["x_mm"], LANTERN_POSE["y_mm"], LANTERN_POSE["z_mm"], 0, UNSCALED_MILLI
            ),
            origin=ObjectOrigin("authored", "fictional"),
        )
        try:
            return bound_edit(
                repository,
                version_id,
                BaseStateBody(base_state_sha256=base_state_sha256),
                lambda: repository.add_thing(
                    version_id,
                    placement,
                    base_state_sha256=base_state_sha256,
                    actor=api.actor,
                    landing=None,
                ),
            ), None
        except Exception as exc:
            answer = object_problem_code(exc)
            if answer is None:
                raise
            return None, answer[1]


def test_a_person_s_lantern_on_the_supported_bench_is_refused_by_the_ground_first(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    placed = api.post(prefix + "/things/on-support" + scope, request_body(entry, drawing, initial))
    assert placed.status_code == 201, placed.text
    assert CREATES_HOLDING_THINGS is not None
    created = api.post(
        prefix + "/society" + scope,
        {"region_id": "region:generated", "profile": CREATES_HOLDING_THINGS.engine},
    )
    assert created.status_code in (200, 201), created.text
    first = latest_input(api, entry)
    base = api.get(prefix + scope).json()

    asked = api.post(
        prefix + "/things" + scope,
        {
            "base_state_sha256": base["state_sha256"],
            "thing_id": "thing:collision",
            "kind": shipped_thing_kinds()[("lantern", 1)].reference(),
            "region_id": "region:generated",
            "pose": LANTERN_POSE,
            "origin_role": "fictional",
        },
    )

    assert asked.status_code == 422, asked.text
    assert asked.json()["code"] == "thing_landing_blocked"
    assert asked.json()["where"]["part"] == "thing"
    assert api.get(prefix + scope).json() == base
    assert latest_input(api, entry) == first


def test_bounded_projection_records_actual_unsupported_offer_and_observer_checks_overlap(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(entry, drawing, initial)
    placed = api.post(prefix + "/things/on-support" + scope, body)
    assert placed.status_code == 201, placed.text
    availability = api.get(prefix + "/things/thing:supported-bench/support" + scope).json()
    assert availability["society"]["availability"] == "omitted"
    assert CREATES_HOLDING_THINGS is not None
    created = api.post(
        prefix + "/society" + scope,
        {"region_id": "region:generated", "profile": CREATES_HOLDING_THINGS.engine},
    )
    assert created.status_code in (200, 201), created.text
    first = latest_input(api, entry)
    assert first["availability"] == "available"
    assert body["thing_id"] not in {t["placed_id"] for t in first["things"]}
    records = [r for r in first["unavailable_affordances"] if r["object_id"] == body["thing_id"]]
    assert records and records[0]["reason"] == OFF_GROUND
    assert any(
        ref["kind"] == "placed_thing" and ref["identity"].endswith(body["thing_id"])
        for ref in first["dependency_refs"]
    )
    base = api.get(prefix + scope).json()
    # A person's placing there is refused by the ground's rule first (the test above); a writer
    # that rule does not hold still reaches the observer, which must either refuse and roll it
    # back, or persist an explicitly unavailable input; it may not hide the collision.
    written, refused = stood_unchecked(api, entry, base["state_sha256"])
    if refused is not None:
        overlap_input = latest_input(api, entry)
        assert refused == "unavailable_society_input"
        assert api.get(prefix + scope).json() == base
        assert latest_input(api, entry) == first
    else:
        after = latest_input(api, entry)
        overlap_input = after
        assert after["availability"] == "unavailable"
        assert after["unavailable_reason"] == "supported_thing_clearance_unavailable"
        assert (
            api.get(prefix + "/things/thing:supported-bench/support" + scope).json()["availability"]
            == "unavailable"
        )
        undone = api.post(
            prefix + "/things/undo" + scope, {"base_state_sha256": written.state_sha256}
        )
        assert undone.status_code == 200, undone.text
        assert latest_input(api, entry)["availability"] == "available"
    replay = api.get(prefix + "/society/replay" + scope)
    assert replay.status_code == 200 and replay.json()["replay_verified"], replay.text
    evidence_path = os.environ.get("EXULANICA_SUPPORT_OBSERVER_EVIDENCE")
    if evidence_path:
        Path(evidence_path).write_text(
            json.dumps(
                {
                    "origin": "actual isolated API observer; no model/browser claim",
                    "entry": entry,
                    "first_input": first,
                    "overlap_refused": refused,
                    "overlap_state_sha256": None if written is None else written.state_sha256,
                    "overlap_input": overlap_input,
                    "final_input": latest_input(api, entry),
                    "replay": replay.json(),
                },
                indent=2,
            )
            + "\n"
        )


def test_no_truthful_closed_activity_record_is_explicitly_unavailable(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(
        entry, drawing, initial, kind=shipped_thing_kinds()[("lantern", 1)].reference()
    )
    placed = api.post(prefix + "/things/on-support" + scope, body)
    assert placed.status_code == 201, placed.text
    availability = api.get(prefix + "/things/thing:supported-bench/support" + scope).json()
    assert availability["availability"] == "available"
    assert availability["society"]["reason"] == "supported_thing_projection_unavailable"
    assert CREATES_HOLDING_THINGS is not None
    created = api.post(
        prefix + "/society" + scope,
        {"region_id": "region:generated", "profile": CREATES_HOLDING_THINGS.engine},
    )
    assert created.status_code == 422, created.text
    assert created.json()["code"] == "invalid_society_state"
    assert created.json()["detail"] == "initial district unavailable"


def test_ground_supported_rest_offer_is_valid_geometry_but_not_falsely_off_ground(made):
    api = made
    entry, prefix, scope, drawing, initial = supported_world(api)
    body = request_body(entry, drawing, initial, position_mm=[2000, -122000])
    body["support"]["surface_id"] = "base-ground"
    placed = api.post(prefix + "/things/on-support" + scope, body)
    assert placed.status_code == 201, placed.text
    assert placed.json()["things"][0]["transform"]["y_mm"] == 0
    assert api.get(prefix + scope).json() == placed.json()
    response = api.get(prefix + "/things/thing:supported-bench/support" + scope)
    assert response.status_code == 200, response.text
    availability = response.json()
    assert availability["availability"] == "available"
    assert availability["society"] == {
        "availability": "unavailable",
        "reason": "supported_thing_projection_unavailable",
        "unavailable_affordances": [],
    }
    assert CREATES_HOLDING_THINGS is not None
    created = api.post(
        prefix + "/society" + scope,
        {"region_id": "region:generated", "profile": CREATES_HOLDING_THINGS.engine},
    )
    assert created.status_code == 422 and created.json()["code"] == "invalid_society_state"
