"""Authenticated PG18 evidence; graph and provider transport are explicitly synthetic fixtures."""

import json
import uuid
from dataclasses import replace

import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_decisions import SocietyDecisionProvider
from exulanica.world.society_repository import SocietyRepository

import test_world_objects_api as object_helpers
from conftest import scratch_role_database
from model_fakes import chat_body
from social_society_fixtures import add_social_marker, social_input
from society_fixtures import SEED, edited, seal
from test_society_purposeful_postgres import step

objects_api = object_helpers.objects_api
pytestmark = pytest.mark.postgres


@pytest.fixture
def social(objects_api, repository, spine_schema):
    api = objects_api
    _, scratch = spine_schema
    runtime_role = "exulanica_social_suite"
    provision_runtime_role(repository.connection, role=runtime_role)
    repository.connection.commit()
    database = scratch_role_database(scratch, runtime_role)
    with database.session(repository.workspace_id) as connection:
        role = connection.execute(
            "select r.rolsuper,r.rolbypassrls from pg_roles r where rolname=current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}
        assert not connection.execute(
            "select exists(select 1 from pg_class c join pg_namespace n on n.oid=c.relnamespace "
            "where n.nspname=current_schema() and c.relowner=(select oid from pg_roles "
            "where rolname=current_user)) as owns"
        ).fetchone()["owns"]
    api.client.app.state.services = replace(
        api.client.app.state.services,
        database=database,
        readonly_database=database,
    )
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place),
    )
    repository.connection.commit()
    version = uuid.UUID(api.version()["version_id"])
    initial = social_input(version)
    rights = {"withdrawn": False}

    def authorize(document):
        if rights["withdrawn"] and document["availability"] == "available":
            raise UnavailableSocietyInput("fixture dependency withdrawn")

    api.client.app.state.society_initial_input = lambda *_args: initial
    api.client.app.state.society_input_authorizer = lambda _conn, _session, doc: authorize(doc)
    route = f"/world/versions/{version}/society"
    response = api.post(
        route,
        {
            "place_id": str(place),
            "region_id": "region-a",
            "seed": SEED,
            "profile": "exulanica-society/v3",
        },
    )
    assert response.status_code == 200, response.text
    repo = SocietyRepository(
        repository.connection, repository.workspace_id, input_authorizer=authorize
    )
    changed = add_social_marker(initial)
    repo.record_input(version, changed)
    repo.connection.commit()
    for _ in range(4):
        state = step(api, route)
    subject = state["state"]["social"]["cast_ids"][1]
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "subject_id": subject,
        "base_tick": state["current_tick"],
        "base_state_sha256": state["state_sha256"],
    }
    return api, repo, version, route, changed, rights, body


def provider_for(client, transport, manifest):
    model = manifest[Role.REASONING_CHEAP].primary.model_id
    transport.responses.append(
        HttpResponse(
            status_code=200,
            text=json.dumps(
                chat_body(
                    json.dumps({"kind": "choose_goal", "target_id": "authored:new-marker:visit"}),
                    model=model,
                )
            ),
        )
    )
    return SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64)


def test_authenticated_recorded_model_choice_retry_reload_replay(
    social, client, transport, manifest
):
    api, repo, _version, route, _, _, body = social
    adapter = provider_for(client, transport, manifest)
    api.client.app.state.society_decision_provider = adapter
    response = api.post(route + "/decisions", body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["decision"]["status"] == "accepted"
    assert result["request"]["context"]["own_beliefs"][0]["origin"] == "communication"
    assert result["request"]["context"]["own_observations"] == []
    assert api.post(route + "/decisions", body).json() == result
    assert len(transport.requests) == 1
    lookup = route + "/decisions/" + body["idempotency_key"]
    assert api.get(lookup).json() == result
    assert api.stranger_get(lookup).status_code == 404
    assert api.stranger_post(route + "/decisions", body).status_code == 404
    assert api.client.post(route + "/decisions", json=body).status_code == 401
    assert (
        api.post(route + "/decisions", body | {"idempotency_key": str(uuid.uuid4())}).status_code
        == 409
    )
    chosen = step(api, route)
    person = next(p for p in chosen["state"]["inhabitants"] if p["id"] == body["subject_id"])
    assert person["goal"]["reason"] == "remembered_target_selected"
    assert person["target"]["target_id"] == "authored:new-marker:visit"
    completed = step(api, route)
    api.client.app.state.society_decision_provider = None
    assert api.get(route).json() == completed
    replay = api.get(route + "/replay")
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]
    assert replay.json()["state_sha256"] == completed["state_sha256"]
    assert len(transport.requests) == 1
    bindings = repo.connection.execute(
        "select tick,disposition from world_society_transition_decision where society_id=%s",
        (uuid.UUID(completed["society_id"]),),
    ).fetchall()
    assert bindings == [{"tick": 5, "disposition": "applied"}]
    events = api.get(route + "/events?limit=256").json()["events"]
    assert any(e["event_kind"] == "decision_applied" for e in events)
    assert len(completed["state"]["inhabitants"]) == 128


def test_reservation_commits_before_inference_retry_pending_and_edit_makes_result_stale(
    social, client, transport, manifest
):
    api, repo, version, route, changed, _, body = social
    adapter = provider_for(client, transport, manifest)
    calls = []

    class DuringInference:
        configuration = adapter.configuration

        def propose(self, context):
            # The second connection can obtain both locks. This would fail immediately if
            # provider execution retained the request's transaction or row lock.
            with repo.connection.transaction():
                assert repo.connection.execute(
                    "select pg_try_advisory_xact_lock(hashtextextended(%s,880024)) as acquired",
                    (str(repo.workspace_id),),
                ).fetchone()["acquired"]
                repo.connection.execute(
                    "select society_id from world_society where workspace_id=%s "
                    "and version_id=%s for update nowait",
                    (repo.workspace_id, version),
                ).fetchone()
            pending = api.post(route + "/decisions", body)
            assert pending.status_code == 200, pending.text
            assert pending.json()["status"] == "in_progress"
            assert pending.json()["decision"] is None
            calls.append(context)
            removed = edited(changed)
            removed["targets"] = [t for t in removed["targets"] if t["origin"] == "district"]
            repo.record_input(version, seal(removed))
            repo.connection.commit()
            return adapter.propose(context)

    api.client.app.state.society_decision_provider = DuringInference()
    response = api.post(route + "/decisions", body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(calls) == len(transport.requests) == 1
    assert result["decision"]["status"] == "stale"
    assert result["decision"]["reason"] == "decision_context_changed"
    state = step(api, route)
    assert state["state"]["social"]["last_decision_seq"] == 1
    assert api.get(route + "/replay").json()["replay_verified"]
    assert api.post(route + "/decisions", body).json() == result


def test_withdrawal_during_inference_records_unavailable_without_returning_context(
    social, client, transport, manifest
):
    api, repo, version, route, changed, rights, body = social
    adapter = provider_for(client, transport, manifest)

    class WithdrawingProvider:
        configuration = adapter.configuration

        def propose(self, context):
            rights["withdrawn"] = True
            return adapter.propose(context)

    api.client.app.state.society_decision_provider = WithdrawingProvider()
    response = api.post(route + "/decisions", body)
    assert response.status_code == 424, response.text
    assert "own_beliefs" not in response.text
    assert api.get(route + "/decisions/" + body["idempotency_key"]).status_code == 424
    receipt = repo.connection.execute(
        "select document from world_society_decision where request_id=%s",
        (uuid.UUID(body["idempotency_key"]),),
    ).fetchone()["document"]
    assert receipt["status"] == "unavailable" and receipt["proposal"] is None
    assert receipt["provider"] is None
    unavailable = edited(changed)
    unavailable.update(availability="unavailable", unavailable_reason="source_withdrawn")
    repo.record_input(version, seal(unavailable))
    repo.connection.commit()
    response = api.post(
        route + "/steps", {key: body[key] for key in ("base_tick", "base_state_sha256")}
    )
    assert response.status_code == 200, response.text
    assert all(
        not agent["beliefs"] and not agent["observations"]
        for agent in response.json()["state"]["social"]["agents"].values()
    )
    assert api.get(route).status_code == 200
    assert api.get(route + "/replay").status_code == 424


def test_unavailable_provider_durable_pending_and_branch_scoped_requests(social):
    api, repo, version, route, _, _, body = social
    api.client.app.state.society_decision_provider = None
    response = api.post(route + "/decisions", body)
    assert response.status_code == 200, response.text
    assert response.json()["decision"]["reason"] == "provider_not_configured"
    step(api, route)
    state = api.get(route).json()
    pending_id = uuid.uuid4()
    with repo.connection.transaction():
        prepared, fresh = SocietyDecisionRepository(repo).prepare(
            version,
            request_id=pending_id,
            subject_id=uuid.UUID(body["subject_id"]),
            base_tick=state["current_tick"],
            base_state_sha256=state["state_sha256"],
            provider_config=None,
        )
    assert fresh
    retry = body | {
        "idempotency_key": str(pending_id),
        "base_tick": state["current_tick"],
        "base_state_sha256": state["state_sha256"],
    }
    assert api.post(route + "/decisions", retry).json() == prepared
    other_version = api.version("Separate branch")
    other_route = f"/world/versions/{other_version['version_id']}/society"
    assert api.get(other_route + "/decisions/" + str(pending_id)).status_code == 404
    assert api.post(route + "/decisions", retry | {"base_tick": 0}).status_code == 409
    assert api.get(route + "/replay").json()["replay_verified"]


def test_unknown_model_target_is_recorded_rejected_and_state_change_during_call_is_stale(
    social,
    client,
    transport,
    manifest,
):
    api, _repo, _version, route, _, _, body = social
    model = manifest[Role.REASONING_CHEAP].primary.model_id
    transport.responses.append(
        HttpResponse(
            status_code=200,
            text=json.dumps(
                chat_body(
                    json.dumps({"kind": "choose_goal", "target_id": "invented-private-place"}),
                    model=model,
                )
            ),
        )
    )
    adapter = SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64)
    api.client.app.state.society_decision_provider = adapter
    result = api.post(route + "/decisions", body).json()
    assert result["decision"]["status"] == "rejected"
    assert result["decision"]["reason"] == "target_not_known_to_agent"
    state = step(api, route)
    next_body = body | {
        "idempotency_key": str(uuid.uuid4()),
        "base_tick": state["current_tick"],
        "base_state_sha256": state["state_sha256"],
    }
    adapter = provider_for(client, transport, manifest)

    class AdvancingProvider:
        configuration = adapter.configuration

        def propose(self, context):
            step(api, route)
            return adapter.propose(context)

    api.client.app.state.society_decision_provider = AdvancingProvider()
    result = api.post(route + "/decisions", next_body)
    assert result.status_code == 200, result.text
    assert result.json()["decision"]["status"] == "stale"
    state = step(api, route)
    assert state["state"]["social"]["last_decision_seq"] == 2
    assert api.get(route + "/replay").json()["replay_verified"]
