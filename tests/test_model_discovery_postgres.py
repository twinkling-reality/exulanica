"""Discovery over the deployed workspace boundary, with no model or network configured."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import replace

import pytest
from exulanica.models.manifest import load_manifest
from exulanica.world.workspace_models import WorkspaceModelRepository

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays
from test_society_saved_world_api import TOKEN

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_discovery_serves_shipped_bindings_and_preflight_without_writes_or_model_calls(
    app, monkeypatch
):
    from exulanica.models.transport import HttpxTransport

    def unexpected(*args, **kwargs):
        raise AssertionError("discovery and preflight must not send a request or append a fact")

    monkeypatch.setattr(HttpxTransport, "get_json", unexpected)
    monkeypatch.setattr(HttpxTransport, "post_json", unexpected)
    monkeypatch.setattr(WorkspaceModelRepository, "record", unexpected)
    world, client = app
    services = decisions._services(client)
    assert services.model_client is None
    first = client.get("/models", headers=_headers())
    assert first.status_code == 200, first.text
    assert first.headers["cache-control"] == "private, no-store"
    listing = first.json()
    assert listing["profile"] == "exulanica.model-discovery/v1"
    spec = next(spec for spec in load_manifest().models.values() if spec.answering)
    offered = next(model for model in listing["models"] if model["model_id"] == spec.model_id)
    assert offered["execution"]["offered_roles"]
    assert offered["runtime"]["provider_refusal"] == "provider_credential_absent"
    assert offered["workspace"] is None
    flight = client.post(
        "/models/preflight",
        json={"provider": spec.provider, "model_id": spec.model_id},
        headers=_headers(),
    )
    assert flight.status_code == 200, flight.text
    assert flight.json() == {"profile": "exulanica.model-admission-preflight/v1", **offered}
    assert client.get("/models", headers=_headers()).json() == listing
    with services.database.session(world["workspace"]) as connection:
        assert WorkspaceModelRepository(connection, world["workspace"]).listing() == []
    assert (
        client.post(
            "/models",
            json={"provider": spec.provider, "model_id": spec.model_id},
            headers=_headers(),
        ).status_code
        == 422
    )


def test_discovery_reads_only_its_workspace_and_does_not_trust_recorded_licence(app, monkeypatch):
    world, client = app
    services = decisions._services(client)
    spec = next(spec for spec in load_manifest().models.values() if spec.answering)
    with services.database.session(world["workspace"]) as connection:
        WorkspaceModelRepository(connection, world["workspace"]).record(
            spec.provider,
            spec.model_id,
            request_id=uuid.uuid4(),
            kind="added",
            facts={"licence_class": "accepted"},
            recorded_by=world["session"].actor,
        )
    from exulanica.models import provider_catalog

    monkeypatch.setattr(provider_catalog, "licence_class", lambda *args: "conditional")
    own = client.get("/models", headers=_headers())
    model = next(model for model in own.json()["models"] if model["model_id"] == spec.model_id)
    assert model["workspace"]["state"] == "added"
    assert model["licence_class"] == "conditional"
    assert model["execution"]["offered_roles"] == []
    callers = decisions._callers(client, world, listed=False)
    foreign = client.get("/models", headers=callers["stranger"][0])
    assert foreign.status_code == 200, foreign.text
    assert all(model["workspace"] is None for model in foreign.json()["models"])
    flight = client.post(
        "/models/preflight",
        json={"provider": spec.provider, "model_id": spec.model_id},
        headers=callers["stranger"][0],
    )
    assert flight.status_code == 200
    assert flight.json()["workspace"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"provider": "unknown", "model_id": "<script>"},
        {"provider": "unknown", "model_id": "maker/Model", "verified": True},
        {"provider": "unknown", "model_id": "maker/Model", "workspace_id": str(uuid.uuid4())},
    ],
)
def test_preflight_rejects_hostile_ids_and_client_authority(app, body):
    _, client = app
    assert client.post("/models/preflight", json=body, headers=_headers()).status_code == 422


def test_only_world_read_is_needed_but_anonymous_or_insufficient_grants_are_refused(
    app, monkeypatch
):
    world, client = app
    callers = decisions._callers(client, world, listed=False)
    spec = next(iter(load_manifest().models.values()))
    body = {"provider": spec.provider, "model_id": spec.model_id}
    for path, call in [
        ("/models", lambda h: client.get("/models", headers=h)),
        ("/models/preflight", lambda h: client.post("/models/preflight", json=body, headers=h)),
    ]:
        assert call({}).status_code == 401, path
        assert call(_headers("bad-token")).status_code == 401, path
        assert call(callers["reader"][0]).status_code == 200, path
        services = decisions._services(client)
        reader_key = hashlib.sha256(b"society-models-reader-token-long-enough").hexdigest()
        client.app.state.services = replace(
            services,
            tokens=replace(
                services.tokens,
                permissions={**services.tokens.permissions, reader_key: frozenset()},
            ),
        )
        assert call(callers["reader"][0]).status_code == 403, path
        client.app.state.services = services


def test_shipped_model_reaches_an_inhabitant_receipt_and_exact_replay(app):
    """Use the unchanged shipped binding through real HTTP choice/receipt/replay operations."""
    import json
    import time

    from exulanica.models.manifest import MANIFEST_PATH, Role
    from exulanica.models.transport import HttpResponse
    from exulanica.world.society_controls import LEASE_SECONDS

    from model_fakes import FakeTransport, chat_body
    from test_society_saved_world_api import OWNER, routes

    class Choosing(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):
            self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
            tool = payload.get("tools")
            schema = (
                tool[0]["function"]["parameters"]
                if tool
                else payload["response_format"]["json_schema"]["schema"]
            )
            action = next(
                label for label in schema["properties"]["action"]["enum"] if " m away" in label
            )
            if tool:
                body = chat_body("", model=payload["model"], finish_reason="tool_calls")
                body["choices"][0]["message"]["tool_calls"] = [
                    {
                        "id": "fixture-choice",
                        "type": "function",
                        "function": {"name": "act", "arguments": json.dumps({"action": action})},
                    }
                ]
            else:
                body = chat_body(json.dumps({"action": action}), model=payload["model"])
            return HttpResponse(200, json.dumps(body))

    world, client = app
    services = decisions._services(client)
    manifest = load_manifest()
    spec = manifest.roles[Role.REASONING_MID].primary
    scope, _, society = routes(world)
    snapshot = stays._inhabited(world, client)
    subject = snapshot["state"]["inhabitants"][0]["id"]
    discovered = next(
        model
        for model in client.get("/models", headers=OWNER).json()["models"]
        if model["model_id"] == spec.model_id
    )
    assert discovered["eligibility"]["eligible"]
    assert "society_decision" in discovered["execution"]["offered_roles"]
    chosen = client.post(
        society + "/models",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "people": [subject],
            "model": {"provider": spec.provider, "model_id": spec.model_id},
        },
    )
    assert chosen.status_code == 200, chosen.text
    transport = Choosing()
    host = decisions._host(world, decisions._client(manifest, transport), services, manifest)
    host = replace(host, manifest_sha256=hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest())
    for _ in range(30):
        assert host.before_minute(
            decisions._claim(world, snapshot), time.monotonic() + LEASE_SECONDS
        )
        if decisions._decisions(services, world, snapshot):
            break
        snapshot = stays._step(world, client, snapshot)
    else:
        raise AssertionError("the chosen inhabitant reached no model decision")
    after = stays._step(world, client, snapshot)
    events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    applied = next(
        event
        for event in events
        if event["event_kind"] == "decision_applied"
        and event["document"]["subject_id"] == subject
        and event["document"]["disposition"] == "applied"
    )
    bound = client.get(
        society + "/decisions/" + applied["document"]["request_id"], headers=OWNER, params=scope
    ).json()
    assert bound["request"]["subject_id"] == bound["decision"]["subject_id"] == subject
    assert bound["request"]["provider_config"]["manifest_sha256"] == host.manifest_sha256
    assert bound["decision"]["provider"]["served_model_id"] == spec.model_id
    assert bound["decision"]["status"] == "accepted"
    assert (
        next(person for person in after["state"]["inhabitants"] if person["id"] == subject)["goal"][
            "reason"
        ]
        == "chosen_by_their_model"
    )
    calls = transport.call_count
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"]
    assert replayed.json()["state_sha256"] == after["state_sha256"]
    assert transport.call_count == calls
