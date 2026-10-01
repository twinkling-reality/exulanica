"""A signal request left at a point the green could not reach no longer stalls its minute's seal.

A worker once offered a thirteenth choice point after twelve kept extensions (the policy's
maximum); the controller recorded an answer there, and every later seal of that minute refused
``segment_decisions_changed``, because the traffic never stopped at that second and its choices
never name it. The case is the one the role-comparisons lane reproduced (generated small town 0,
episode 0: keeps at 302 to 313, the unreachable point at 314). A world that already holds such a
request now seals: an answered one is kept as it is and bound apart from the minute's choices, an
unanswered one is finished with the role's ``green_not_eligible``.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from exulanica.canonical import canonical_json
from exulanica.models.manifest import load_manifest
from exulanica.world.decision_roles import decision_roles
from exulanica.world.role_decisions import seal
from exulanica.world.traffic_signal_repository import TrafficSignalRepository

import test_society_stay_requests_api as stays

app = stays.app
saved_world = stays.saved_world
pytestmark = pytest.mark.postgres

OBSERVATION = {
    "active_near": 1,
    "other_near": 0,
    "active_queue": 1,
    "other_queue": 0,
    "active_wait_seconds": 3,
    "other_wait_seconds": 0,
    "near_vehicle_count": 1,
    "green_elapsed_seconds": 24,
}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("answered", [True, False])
def test_a_request_at_a_point_the_green_could_not_reach_is_bound_apart_and_the_minute_seals(
    app, answered
):
    world, client = app
    services = client.app.state.services
    role = decision_roles().deciding_for("signal")
    manifest = load_manifest()
    spec = next(
        spec
        for spec in manifest.offered_models(role.chosen)
        if role.contract().mechanism_for(spec) is not None
    )
    mechanism = role.contract().mechanism_for(spec)
    assert mechanism is not None
    version = world["binding"].version_id
    workspace = world["workspace"]
    world_id = world["binding"].world_id
    signal = "signal:kept-twelve-times"
    with services.database.session(workspace) as connection:
        repository = TrafficSignalRepository(connection, workspace, world_id, version)
        chosen = repository.record_choice(
            role,
            manifest,
            request_id=uuid.uuid4(),
            signal_id=signal,
            known_signals=[signal],
            model={"provider": spec.provider, "model_id": spec.model_id},
            chosen_by=world["session"].actor,
        )
        first = chosen["effective_second"] + 24
        episode, local = divmod(first, 1200)
        target = local // 60
        requests = []
        # Twelve kept extensions, then the point the green had no extension left for.
        for offset in range(13):
            point = first + offset
            reservation = repository.reserve_point(
                role,
                roads_version="a" * 64,
                episode=episode,
                segment=target,
                choice=repository.current_choices()[signal],
                choice_second=point,
                state_sha256=f"{offset:064x}",
                observation={**OBSERVATION, "green_elapsed_seconds": 24 + offset},
                manifest_sha256="c" * 64,
                mechanism=mechanism.value,
            )
            assert reservation is not None
            request = reservation["request"]
            requests.append(request)
            if offset == 12 and not answered:
                continue
            keep = next(o for o in request["context"]["options"] if o["kind"] == "keep")
            repository.record_result(
                role,
                uuid.UUID(request["request_id"]),
                {
                    "status": "accepted",
                    "reason": "validated_choice",
                    "proposal": {"label": keep["label"], "option": keep},
                    "provider": None,
                },
            )
    with services.database.session(workspace) as connection:
        repository = TrafficSignalRepository(connection, workspace, world_id, version)
        for segment in range(target + 1):
            local_start = segment * 60
            absolute_start = episode * 1200 + local_start
            generations = {
                name: row["choice_seq"]
                for name, row in repository.choices_at(absolute_start).items()
            }
            # The traffic recorded the twelve keeps it applied; it never stopped at the thirteenth.
            choices = (
                {signal: {str(local + offset): "keep" for offset in range(12)}}
                if segment == target
                else {}
            )
            continuation = seal(
                {
                    "profile": "exulanica.traffic-continuation/v1",
                    "input_sha256": "d" * 64,
                    "episode": episode,
                    "next_second": local_start + 60,
                    "state": {"second": local_start + 59},
                    "signal_choices": choices,
                    "initial_signal_cursors": {},
                }
            )
            sealed = repository.seal_segment(
                role=role,
                roads_version="a" * 64,
                input_sha256="d" * 64,
                episode=episode,
                segment=segment,
                states=[{"second": second} for second in range(local_start, local_start + 60)],
                continuation=continuation,
                selected_generations=generations,
            )
        unreachable = uuid.UUID(requests[12]["request_id"])
        receipt = repository.decision_for(unreachable)
        assert receipt is not None
        if answered:
            # Its answer stays what the model said; it moved no light.
            assert (receipt["status"], receipt["proposal"]["option"]["kind"]) == (
                "accepted",
                "keep",
            )
        else:
            assert (receipt["status"], receipt["reason"]) == ("unavailable", "green_not_eligible")
        assert sealed["segment"] == target
        assert sealed["active_second"] == first and sealed["choice_seq"] == chosen["choice_seq"]
        rows = connection.execute(
            "select r.request_id,r.document_sha256 as request_sha,"
            "d.document_sha256 as decision_sha "
            "from world_traffic_signal_decision_request r join world_traffic_signal_decision d "
            "using(workspace_id,world_id,version_id,request_id) where r.workspace_id=%s "
            "and r.version_id=%s order by r.choice_second",
            (workspace, version),
        ).fetchall()
        applied = [[row["request_sha"], row["decision_sha"]] for row in rows[:12]]
        apart = [[rows[12]["request_sha"], rows[12]["decision_sha"]]]
        expected = hashlib.sha256(
            canonical_json(
                {
                    "choices": {signal: {str(local + offset): "keep" for offset in range(12)}},
                    "requests": applied,
                    "not_applied": apart,
                }
            )
        ).hexdigest()
        assert sealed["decisions_sha256"] == expected
