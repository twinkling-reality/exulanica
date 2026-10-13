"""A generated body's model pursuit persists and replays through the saved-world database.

Only provider answers are scripted. Kind admission, owner model choice, due scheduling,
request/receipt persistence, direct commands and history replay use their ordinary paths.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace

import exulanica.api.services as services_module
import pytest
from exulanica.api.routes import society_models
from exulanica.selection.creature_drafting import assembled_form
from exulanica.things.bodies import body_grammar
from exulanica.things.creatures import assemble_creature
from exulanica.world import saved_entries
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.society_decision_contract import person_role
from exulanica.world.society_planner import held_nodes, input_graph, open_ground
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from test_site_society_of_things_postgres import FARM, V7, _input, _place, _site, _step
from test_society_made_kinds import BY
from test_society_made_world import made as made
from test_society_model_follow import PursuitTransport
from test_society_person_decisions_postgres import _client, _host, _offered

pytestmark = pytest.mark.postgres


def _being(snapshot, placed="crawler"):
    return next(p for p in snapshot["state"]["inhabitants"] if p.get("placed_id") == placed)


@pytest.mark.parametrize("ending", ["model_stop", "owner_command"])
def test_generated_model_pursuit_survives_unasked_minutes_and_cold_replay(
    made, monkeypatch, ending
):
    api = made
    monkeypatch.setattr(saved_entries, "new_world_id", lambda _kind: FARM)
    entry, society, _records = _site(api, "farm", "fixture_farm", "small_farm")
    workspace = api.repository.workspace_id
    version = uuid.UUID(entry["authored_version_id"])
    services = replace(
        api.client.app.state.services, society_seed=lambda _workspace, _world: "7" * 64
    )
    api.client.app.state.services = services
    created = api.post(society, {"region_id": "region:generated", "profile": V7})
    assert created.status_code in (200, 201), created.text
    snapshot = created.json()
    document = _input(api, entry, 1)
    nodes = {n["node_id"]: n["position_mm"] for n in document["navigation"]["nodes"]}
    free = sorted(
        open_ground(document, snapshot["state"]["inhabitants"])[0],
        key=lambda node: (nodes[node], node),
    )

    def squared(a, b):
        return sum((x - y) ** 2 for x, y in zip(nodes[a], nodes[b], strict=True))

    # The farm's coarse yard cells are farther apart than follow's 2m reach. Choose a real
    # approach near its finer path nodes; never alter navigation or the follow bound.
    guide_node, _approach, actor_node = next(
        (target, near, actor)
        for target in free
        for near in free
        if 0 < squared(target, near) <= 2000**2
        for actor in free
        if actor != near and 6000**2 < squared(target, actor) <= 8000**2
    )
    for placed, walking, node in (("crawler", True, actor_node), ("guide", False, guide_node)):
        form = form_of("ten_legs", label=placed, moves=["walking"] if walking else [])
        form["weight_wait"], form["weight_stand"] = 1000, 0
        if not walking:
            form["can_stand"] = form["can_follow"] = False
        else:
            # The owner-command case uses an ordinary admitted destination action.
            form["can_rest"] = form["can_visit"] = True
        creature = assemble_creature(assembled_form(form, body_grammar()), by=BY)
        with api.database.session(workspace) as connection:
            ThingStore(connection, workspace, api.store).keep_creature(
                creature, created_by=api.actor
            )
        x, z = nodes[node]
        _place(api, entry, placed, {"source": "workspace", "sha256": creature.kind.sha256}, x, z)
    # Consume the normal source edit that adds the two admitted bodies to this saved society.
    snapshot = _step(api, entry, snapshot)
    assert "exulanica-ability/follow/v3" in snapshot["state"]["modules"]
    subject = _being(snapshot)["id"]
    guide = _being(snapshot, "guide")["id"]
    manifest, model_id = _offered()
    # The fixture's one verified shipped offering is shared by admission and execution.
    monkeypatch.setattr(services_module, "load_manifest", lambda: manifest)
    monkeypatch.setattr(society_models, "load_manifest", lambda: manifest)
    transport = PursuitTransport()
    client = _client(manifest, transport)
    services = replace(services, model_client=client, society_control_workspaces=(workspace,))
    api.client.app.state.services = services
    root = f"/world/versions/{version}/society"
    scope = f"?world_id={entry['world_id']}"
    chosen = api.post(
        f"/world/versions/{version}/models/society_decision" + scope,
        {
            "idempotency_key": str(uuid.uuid4()),
            "subjects": [subject],
            "model": {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        },
    )
    assert chosen.status_code == 200, chosen.text
    host = _host({"workspace": workspace}, client, services, manifest)

    def minute(before):
        claim = ControlClaim(
            workspace_id=workspace,
            world_id=entry["world_id"],
            society_id=uuid.UUID(before["society_id"]),
            version_id=version,
            token=uuid.uuid4(),
            revision=1,
            actor=api.actor,
        )
        host.before_minute(claim, time.monotonic() + LEASE_SECONDS)
        return _step(api, entry, before)

    before_position = _being(snapshot)["position_mm"]
    snapshot = minute(snapshot)
    assert _being(snapshot)["following"]["being"] == guide
    assert transport.call_count == 1
    unasked = 0
    for _ in range(12):
        due = person_role().adapter.due(snapshot["state"], subject)
        calls = transport.call_count
        snapshot = minute(snapshot)
        assert _being(snapshot)["following"]["being"] == guide
        if not due:
            unasked += 1
            assert transport.call_count == calls
        if unasked >= 2:
            break
    # New saved societies record 60m per minute: this short approach can complete in the
    # asked minute. Persistence through later unasked minutes is still a database invariant.
    assert unasked >= 2
    assert _being(snapshot)["position_mm"] != before_position

    if ending == "model_stop":
        transport.next_kind = "stop_following"
        for _ in range(20):
            snapshot = minute(snapshot)
            if "following" not in _being(snapshot):
                break
        else:
            pytest.fail("the model never reached its next ordinary choice point")
        reason = "chose_to_stop_following"
    else:
        for _ in range(30):
            current_input = _input(api, entry, snapshot["state"]["input_seq"])
            held = held_nodes(
                snapshot["state"]["inhabitants"], _being(snapshot), graph=input_graph(current_input)
            )
            owner_target = next(
                (
                    t
                    for t in current_input["targets"]
                    if t["enabled"]
                    and t["affordance"] in {"rest", "visit"}
                    and any(place not in held for place in t["place_node_ids"])
                ),
                None,
            )
            if owner_target is not None:
                break
            snapshot = minute(snapshot)
            assert _being(snapshot)["following"]["being"] == guide
        assert owner_target is not None, "no ordinary destination became available"
        command = api.post(
            root + "/actions" + scope,
            {
                "idempotency_key": str(uuid.uuid4()),
                "base_tick": snapshot["current_tick"],
                "base_state_sha256": snapshot["state_sha256"],
                "subject_id": subject,
                "intent": {"kind": "go_to", "target_id": owner_target["target_id"]},
            },
        )
        assert command.status_code == 200, command.text
        snapshot = minute(snapshot)
        assert "following" not in _being(snapshot)
        consumed = api.get(root + "/actions/" + command.json()["request"]["request_id"] + scope)
        assert consumed.status_code == 200, consumed.text
        assert consumed.json()["consumption"]["disposition"] == "applied"
        snapshot = minute(snapshot)
        assert "following" not in _being(snapshot)
        reason = "chose_otherwise"

    events = api.get(root + "/events" + scope).json()["events"]
    assert any(
        e["event_kind"] == "stopped_following" and e["document"]["reason"] == reason for e in events
    )
    applied = [
        e
        for e in events
        if e["event_kind"] == "decision_applied" and e["document"]["subject_id"] == subject
    ]
    first_event = min(applied, key=lambda event: event["tick"])
    first = api.get(root + "/decisions/" + first_event["document"]["request_id"] + scope)
    assert first.status_code == 200, first.text
    receipt = first.json()
    assert receipt["decision"]["proposal"]["option"]["kind"] == "follow"
    assert receipt["decision"]["proposal"]["option"]["addressee_id"] == guide
    assert (
        receipt["request"]["provider_config"]["contract"]
        == person_role().contract_for(V7).binding()
    )
    assert (
        receipt["request"]["context"]["being"]["summary"]
        == snapshot["state"]["kinds"][_being(snapshot)["kind"]["sha256"]]["summary"]
    )
    calls = transport.call_count
    # Discard execution services. Every GET opens a fresh database session/repository, and
    # replay reconstructs the history with no client available to supply missing decisions.
    api.client.app.state.services = replace(services, model_client=None)
    cold = api.get(society)
    assert cold.status_code == 200 and cold.json()["state_sha256"] == snapshot["state_sha256"]
    replay = api.get(root + "/replay" + scope)
    assert replay.status_code == 200, replay.text
    assert (
        replay.json()["replay_verified"]
        and replay.json()["state_sha256"] == snapshot["state_sha256"]
    )
    assert (
        api.get(root + "/decisions/" + first_event["document"]["request_id"] + scope).json()
        == receipt
    )
    assert transport.call_count == calls
