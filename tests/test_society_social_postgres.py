"""The retired social engine: nothing new is made with it, and what was stored still replays.

``exulanica-society/v3`` is not creatable (the engine table), and its explicitly requested model
proposals (``POST .../society/decisions``) are refused by name: a model decides for a person only
as the world's owner chose. A v3 society stored before that, with a proposal it recorded, still
reads, advances and replays byte for byte. Authenticated PG18 evidence; the provider transport is
a synthetic fixture, and the stored society is planted by the write its creation made.
"""

import json
import uuid
from dataclasses import replace

import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_decisions import SocietyDecisionProvider
from exulanica.world.society_repository import SocietyRepository

import test_world_objects_api as object_helpers
from conftest import scratch_role_database
from model_fakes import chat_body
from retired_society_support import plant_retired_society
from social_society_fixtures import add_social_marker, social_input
from society_fixtures import SEED
from test_society_purposeful_postgres import step

SOCIAL = "exulanica-society/v3"

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
    repo = SocietyRepository(
        repository.connection,
        repository.workspace_id,
        world_id=api.world_id,
        input_authorizer=authorize,
    )
    # Stored as its creation stored it, before the engine was retired.
    plant_retired_society(
        repo,
        version,
        place_id=place,
        region_id="region-a",
        seed=SEED,
        actor=api.actor,
        profile=SOCIAL,
        initial_input=initial,
    )
    repo.connection.commit()
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


def _answered(api, repo, version, body, client, transport, manifest) -> dict:
    """A proposal the retired route recorded: reserved, asked of a model under the workspace's
    policy with no place's name released, and finished, as its runtime did each step."""
    decisions = SocietyDecisionRepository(repo)
    provider = provider_for(client, transport, manifest)
    services = api.client.app.state.services
    workspace = repo.workspace_id
    provider = replace(
        provider,
        client=provider.client.with_policy(
            services.request_policy(
                workspace,
                lambda: services.readonly_database.session(workspace),
                released_places=no_place_released,
            )
        ),
    )
    request_id = uuid.UUID(body["idempotency_key"])
    with repo.connection.transaction():
        reservation, fresh = decisions.prepare(
            version,
            request_id=request_id,
            subject_id=uuid.UUID(body["subject_id"]),
            base_tick=body["base_tick"],
            base_state_sha256=body["base_state_sha256"],
            provider_config=provider.configuration,
        )
    assert fresh
    result = provider.propose(reservation["request"]["context"])
    with repo.connection.transaction():
        finished = decisions.finish(version, request_id, result)
    repo.connection.commit()
    return finished


def test_a_v3_society_is_refused_by_name_and_nothing_is_written(objects_api, repository):
    api = objects_api
    place = uuid.uuid4()
    repository.connection.execute(
        "insert into place(workspace_id,place_id) values(%s,%s)",
        (repository.workspace_id, place),
    )
    repository.connection.commit()
    version = api.version()["version_id"]
    api.client.app.state.society_initial_input = lambda *_args: social_input(uuid.UUID(version))
    api.client.app.state.society_input_authorizer = lambda *_args: None
    route = api.in_world(f"/world/versions/{version}/society")
    refused = api.post(route, {"place_id": str(place), "region_id": "region-a", "profile": SOCIAL})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "society_engine_retired"
    assert (
        repository.connection.execute(
            "select count(*) as n from world_society where workspace_id=%s",
            (repository.workspace_id,),
        ).fetchone()["n"]
        == 0
    )
    # The control: the engine the table creates with is made through the same request.
    made = api.post(
        route, {"place_id": str(place), "region_id": "region-a", "profile": SOCIAL[:-1] + "2"}
    )
    assert made.status_code == 200, made.text


def test_a_model_proposal_is_refused_by_name_and_nothing_is_reserved(social):
    api, repo, _version, route, _changed, _rights, body = social
    refused = api.post(api.in_world(route + "/decisions"), body)
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "society_proposals_retired"
    assert api.stranger_post(api.in_world(route + "/decisions"), body).status_code == 404
    assert api.client.post(api.in_world(route + "/decisions"), json=body).status_code == 401
    assert (
        repo.connection.execute(
            "select count(*) as n from world_society_decision_request where workspace_id=%s",
            (repo.workspace_id,),
        ).fetchone()["n"]
        == 0
    )


def test_a_stored_v3_proposal_reads_advances_and_replays(social, client, transport, manifest):
    api, repo, version, route, _changed, _rights, body = social
    recorded = _answered(api, repo, version, body, client, transport, manifest)
    assert recorded["decision"]["status"] == "accepted"
    lookup = api.in_world(route + "/decisions/" + body["idempotency_key"])
    read = api.get(lookup)
    assert read.status_code == 200, read.text
    assert read.json() == recorded
    assert api.stranger_get(lookup).status_code == 404
    chosen = step(api, route)
    person = next(p for p in chosen["state"]["inhabitants"] if p["id"] == body["subject_id"])
    assert person["goal"]["reason"] == "remembered_target_selected"
    assert person["target"]["target_id"] == "authored:new-marker:visit"
    completed = step(api, route)
    assert api.get(api.in_world(route)).json() == completed
    replay = api.get(api.in_world(route + "/replay"))
    assert replay.status_code == 200, replay.text
    assert replay.json()["replay_verified"]
    assert replay.json()["state_sha256"] == completed["state_sha256"]
    assert len(transport.requests) == 1
    bindings = repo.connection.execute(
        "select tick,disposition from world_society_transition_decision where society_id=%s",
        (uuid.UUID(completed["society_id"]),),
    ).fetchall()
    assert bindings == [{"tick": 5, "disposition": "applied"}]
    events = api.get(api.in_world(route + "/events?limit=256")).json()["events"]
    assert any(e["event_kind"] == "decision_applied" for e in events)
    assert len(completed["state"]["inhabitants"]) == 128
