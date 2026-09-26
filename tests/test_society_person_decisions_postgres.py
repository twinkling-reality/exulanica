"""A saved world's people run by chosen models, as the deployed database and the host take them.

The application connects as a provisioned runtime role; the owner's choices are recorded through
the choice repository over that role's session, and the host's decision phase
(:class:`~exulanica.api.society_person_decisions.PersonDecisionHost`) asks a scripted model behind
the real client, as playback asks before a minute. The minute is then taken through the steps
route, and replay through the replay route. What is shown:

*   a chosen person at a choice point is asked, the receipt names the model and the call, and the
    minute applies the choice with the model's own reason and records what the receipt did;
*   replay regenerates the same history with no model call;
*   the world's hour of decisions is a bound, a provider the process refuses is named, and a
    workspace the host does not list is never asked for, each on a receipt or by asking nothing;
*   a choice names people of this society and a model the manifest offers, or is refused by name;
*   only a caller who may ask models changes whose model runs a person, which in a browser is the
    workspace's owner, while reading which model runs whom takes a world read alone.
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
import uuid
from collections import Counter
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from exulanica.api.authorisation import load_token_directory
from exulanica.api.society_control_worker import SocietyControlWorker
from exulanica.api.society_person_decisions import (
    PersonDecisionHost,
    ask_bound_usd,
    host_refusal,
    model_refusal,
    smallest_ask_usd,
)
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.identity import IdentityRepository, rename_entity
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest, parse_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.inhabitant_words import inhabitant_words_catalog
from exulanica.selection.society_question import EVENT_LINES
from exulanica.world.society import SocietyBytesNotRead
from exulanica.world.society_controls import LEASE_SECONDS, MAX_CATCHUP_TICKS, ControlClaim
from exulanica.world.society_decision_contract import (
    CHOICE_DESCRIPTION,
    at_choice_point,
    decision_contract,
)
from exulanica.world.society_decision_repository import (
    UNANSWERED_WINDOW_TICKS,
    SocietyDecisionRepository,
)
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_repository import SocietyRepository
from psycopg.types.json import Jsonb

import test_society_stay_requests_api as stays
from model_fakes import FakeTransport, chat_body
from test_society_saved_world_api import OWNER, TOKEN, routes
from tests_support_api import EVERY_PERMISSION

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres
PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"


def _offered():
    """The manifest with one declared chat model verified to answer by a forced function."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    model_id = next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )
    document["models"][model_id]["answering"] = {"tool_call": PROBE_RECORD}
    return parse_manifest(document), model_id


class _Chooser(FakeTransport):
    """A scripted model that picks the first offered place to go every time it is asked."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        body = chat_body("", model=payload["model"], finish_reason="tool_calls")
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "c",
                "type": "function",
                "function": {
                    "name": "act",
                    "arguments": json.dumps({"action": next(a for a in enum if " m away" in a)}),
                },
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _unoffered(manifest) -> str:
    """A declared model the manifest offers no person's decisions."""
    offered = {spec.model_id for spec in manifest.offered_models(Role.SOCIETY_DECISION)}
    return next(model_id for model_id in sorted(manifest.models) if model_id not in offered)


def _client(manifest, transport) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100),
    )


def _host(world, client, services, manifest, *, listed=True) -> PersonDecisionHost:
    def policy_for(workspace_id):
        return services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        )

    return PersonDecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=client,
        workspaces=frozenset({world["workspace"]} if listed else set()),
        policy_for=policy_for,
        manifest=manifest,
        manifest_sha256="a" * 64,
    )


def _claim(world, snapshot) -> ControlClaim:
    return ControlClaim(
        workspace_id=world["workspace"],
        world_id=world["binding"].world_id,
        society_id=uuid.UUID(snapshot["society_id"]),
        version_id=world["binding"].version_id,
        token=uuid.uuid4(),
        revision=1,
        actor=world["session"].actor,
    )


def _choose(services, world, people, model, *, manifest, key=None) -> dict[str, Any]:
    with services.database.session(world["workspace"]) as connection:
        return SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_choice(
            world["binding"].version_id,
            request_id=key or uuid.uuid4(),
            people=people,
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=decision_contract(),
        )


def _requests(services, world, snapshot) -> int:
    """How many person decision requests the society holds."""
    with services.database.session(world["workspace"]) as connection:
        return connection.execute(
            "select count(*) as n from world_society_decision_request where workspace_id=%s "
            "and society_id=%s",
            (world["workspace"], snapshot["society_id"]),
        ).fetchone()["n"]


def _decisions(services, world, snapshot) -> list[dict]:
    with services.database.session(world["workspace"]) as connection:
        return [
            row["document"]
            for row in connection.execute(
                "select document from world_society_decision where workspace_id=%s "
                "and society_id=%s order by decision_seq",
                (world["workspace"], snapshot["society_id"]),
            ).fetchall()
        ]


def _choosing(world, client, services, manifest, model_id, transport):
    """The square with people brought in, stepped until somebody is at a choice point."""
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, _client(manifest, transport), services, manifest)
    for _ in range(30):
        assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        if _decisions(services, world, snapshot):
            return snapshot, host
        snapshot = stays._step(world, client, snapshot)
    raise AssertionError("nobody in the square reached a choice point in thirty minutes")


def _services(client):
    return client.app.state.services


def _callers(client, world, *, listed: bool) -> dict[str, tuple[dict[str, str], str]]:
    """Callers holding less than the owner, given to the running application with its owner.

    Each by name, with the headers it sends and the actor it acts as. ``listed`` puts the world's
    workspace among those the host plays and asks models for. The application has started by
    then, so no playback thread starts with it.
    """
    grants = {
        TOKEN: ("owner", str(world["workspace"]), EVERY_PERMISSION),
        "society-models-reader-token-long-enough": (
            "reader",
            str(world["workspace"]),
            ["world.read"],
        ),
        "society-models-keeper-token-long-enough": (
            "keeper",
            str(world["workspace"]),
            ["world.read", "world.write"],
        ),
        "society-models-stranger-token-long-enough": (
            "stranger",
            str(uuid.uuid4()),
            EVERY_PERMISSION,
        ),
    }
    directory = {
        token: {
            "workspace_id": workspace,
            "actor": str(world["session"].actor if name == "owner" else uuid.uuid4()),
            "permissions": list(permissions),
        }
        for token, (name, workspace, permissions) in grants.items()
    }
    client.app.state.services = dataclasses.replace(
        _services(client),
        tokens=load_token_directory({"EXULANICA_API_TOKENS": json.dumps(directory)}),
        society_control_workspaces=(world["workspace"],) if listed else (),
    )
    return {
        name: ({"Authorization": f"Bearer {token}"}, directory[token]["actor"])
        for token, (name, _, _) in grants.items()
    }


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_chosen_person_is_asked_and_the_minute_applies_the_choice_and_replays_it(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot, _ = _choosing(world, client, services, manifest, model_id, transport)
    receipts = _decisions(services, world, snapshot)
    assert receipts and transport.call_count == len(receipts)
    for receipt in receipts:
        assert receipt["profile"] == "exulanica.society-decision/v2"
        assert (receipt["status"], receipt["reason"]) == ("accepted", "validated_choice")
        assert receipt["provider"]["model_id"] == model_id
        assert receipt["provider"]["provider"] == manifest.spec(model_id).provider
        assert [c["outcome"] for c in receipt["provider"]["calls"]] == ["completed"]
    after = stays._step(world, client, snapshot)
    scope, _, society = routes(world)
    events = client.get(society + "/events", headers=OWNER, params=scope).json()["events"]
    applied = [
        e
        for e in events
        if e["event_kind"] == "decision_applied" and e["tick"] == after["current_tick"]
    ]
    assert {e["document"]["decision_seq"] for e in applied} == {r["decision_seq"] for r in receipts}
    moved = [e for e in applied if e["document"]["disposition"] == "applied"]
    assert moved, "no receipt applied, so the minute showed nothing about the model's choice"
    for event in moved:
        person = next(
            p for p in after["state"]["inhabitants"] if p["id"] == event["document"]["subject_id"]
        )
        assert person["goal"]["reason"] == "chosen_by_their_model"
        assert event["document"]["model"]["model_id"] == model_id
        # The event names its receipt by the request id the decisions route reads it by.
        read = client.get(
            society + "/decisions/" + event["document"]["request_id"], headers=OWNER, params=scope
        )
        assert read.status_code == 200, read.text
        decision = read.json()["decision"]
        assert decision["decision_seq"] == event["document"]["decision_seq"]
        assert decision["document_sha256"] == event["document"]["decision_sha256"]
        assert decision["provider"]["model_id"] == model_id
    # What the models route reads back is what a comparison of models counts, by model.
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    [summary] = read.json()["by_model"]
    assert (summary["model_id"], summary["decisions"], summary["asked"], summary["accepted"]) == (
        model_id,
        len(receipts),
        len(receipts),
        len(receipts),
    )
    assert summary["applied"] == len(moved)
    assert summary["by_reason"] == {"validated_choice": len(receipts)}
    # Every decision the minute did not act on is counted once, by the minute's own reason.
    not_acted = [e for e in applied if e["document"]["disposition"] != "applied"]
    assert summary["not_acted_on"] == dict(Counter(e["document"]["reason"] for e in not_acted))
    assert summary["latency_ms"]["p50"] is not None and summary["cost_known"] is True
    latest = {entry["subject_id"]: entry for entry in read.json()["latest"]}
    assert {event["document"]["subject_id"] for event in moved} <= set(latest)
    # Replay regenerates the same history from what was stored, and asks no model: the only
    # model this world was ever asked through is the scripted one, and it hears nothing more.
    asked = transport.call_count
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
    assert transport.call_count == asked


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_what_happened_in_a_model_run_world_says_the_model_chose_and_no_receipt_takes_a_line(app):
    """The Companion's lines about what happened are the people's own events. What a decision
    receipt did has no words, and the goal the model chose already says who chose it."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot, _ = _choosing(world, client, services, manifest, model_id, _Chooser())
    after = stays._step(world, client, snapshot)
    scope, _, society = routes(world)
    latest = client.get(
        society + "/events", headers=OWNER, params={**scope, "limit": EVENT_LINES}
    ).json()["events"]
    receipts = {e["event_id"] for e in latest if e["event_kind"] == "decision_applied"}
    # A positive control: the receipts' events are among the latest the Companion reads.
    assert receipts, [e["event_kind"] for e in latest]
    response = client.post(
        "/selection/ask",
        headers=OWNER,
        params=scope,
        json={
            "question": "what happened?",
            "plan": {"intent": "society", "society": {"scope": "world", "aspect": "recent"}},
            "society_context": {
                "version_id": str(world["binding"].version_id),
                "inhabitant_id": None,
            },
        },
    )
    assert response.status_code == 200, response.text
    views = response.json()["simulation"]
    assert views and not {view["event_id"] for view in views.values()} & receipts
    catalog = inhabitant_words_catalog()
    unworded = catalog.words("line", "outcome_unknown").split("(")[0].strip()
    assert not [view["line"] for view in views.values() if unworded in view["line"]]
    chose = catalog.reason("chosen_by_their_model")
    assert any(
        chose in view["line"] and view["tick"] == after["current_tick"] for view in views.values()
    ), [view["line"] for view in views.values()]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_an_exact_retry_of_a_choice_is_answered_before_anything_else_is_checked(app, monkeypatch):
    import exulanica.world.society_model_choice_repository as repository

    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    key = uuid.uuid4()
    first = _choose(services, world, people, model, manifest=manifest, key=key)
    # Whatever would refuse a new choice now, the one already recorded is its retry's answer.
    monkeypatch.setattr(repository, "PURPOSEFUL_PROFILE", "exulanica-society/another")
    assert _choose(services, world, people, model, manifest=manifest, key=key) == first
    with pytest.raises(ModelChoiceRefused) as refused:
        _choose(services, world, people, model, manifest=manifest)
    assert refused.value.code == "engine_takes_no_model_choice"


#: Each call's reservation where the spend bound is tested, so an ask's bound is known: two calls.
_CALL_USD = Decimal("0.001")


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize(
    ("bound", "limit", "reason"),
    [
        ("decisions_per_world_hour_maximum", 1, "world_hour_decisions_spent"),
        # Room for one ask's bound (two calls at _CALL_USD) and not for two.
        ("spend_per_world_hour_microusd", 3000, "world_hour_spend_spent"),
    ],
    ids=["decisions", "spend"],
)
def test_each_world_hour_bound_is_named_on_each_receipt_past_it_and_asks_nothing_more(
    app, monkeypatch, bound, limit, reason
):
    """Past a bound of its hour a world asks no model, and each receipt says which bound.

    Everybody is at a choice point in the first minute. A bound of one decision admits the first
    ask; a spend bound with room for one ask's bound admits one, because each ask the host admits
    adds its bound to what the hour has spent before the next person is weighed, in the same minute.
    """
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    import exulanica.api.society_person_decisions as host_module

    contract = decision_contract()
    bounded = dataclasses.replace(contract, policy={**contract.policy, bound: limit})
    monkeypatch.setattr(host_module, "decision_contract", lambda: bounded)
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    model_client = _client(manifest, transport)
    monkeypatch.setattr(model_client.budget, "estimate_usd", lambda *args, **kwargs: _CALL_USD)
    host = _host(world, model_client, services, manifest)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipts = _decisions(services, world, snapshot)
    asked = [r for r in receipts if r["provider"] is not None]
    spent = [r for r in receipts if r["reason"] == reason]
    assert len(asked) == 1 and transport.call_count == 1
    assert len(spent) == len(receipts) - 1 >= 1
    assert all(r["status"] == "unavailable" and r["provider"] is None for r in spent)
    assert {r["base_tick"] for r in receipts} == {snapshot["current_tick"]}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_provider_the_host_does_not_admit_is_asked_for_nothing_and_nothing_is_written(app):
    """A refusal of the whole provider holds every minute, so the host reserves nothing for it
    and writes no receipt; the models route names the refusal instead."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    transport.egress = parse_egress_allowlist(["https://somewhere-else.example.com"])
    # A client whose allowlist admits no provider: built only because no role is bound here.
    manifest = dataclasses.replace(manifest, roles={})
    refused = _client(manifest, transport)
    assert set(refused.refusals.values()) == {"provider_not_admitted"}
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, refused, services, manifest)
    for _ in range(5):
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert _decisions(services, world, snapshot) == [] and transport.requests == []
    assert _requests(services, world, snapshot) == 0
    assert model_refusal(refused, manifest, decision_contract(), model) == "provider_not_admitted"


def _moved(manifest, model_id):
    """``manifest`` with ``model_id`` served by a second provider, as a later manifest may have
    it; no role is bound, so no chain constrains where it moves."""
    spec = manifest.spec(model_id)
    second = dataclasses.replace(
        manifest.provider(spec.provider),
        provider_id="second_provider",
        base_url="https://second.example.com/v1",
        api_key_env="SECOND_PROVIDER_TEST_API_KEY",
        catalog_url="https://second.example.com/models",
    )
    return dataclasses.replace(
        manifest,
        roles={},
        providers={**manifest.providers, "second_provider": second},
        models={**manifest.models, model_id: dataclasses.replace(spec, provider="second_provider")},
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_choice_whose_model_moved_to_another_provider_is_sent_nothing_and_named(app, monkeypatch):
    """A choice names the provider that served its model when it was made. Once the manifest
    serves the model from another, nothing is sent for it, before any request is built, and
    nothing is written; the models route names the refusal for each person it chose for."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    moved = _moved(manifest, model_id)
    transport = _Chooser()
    keys = {provider: "test-key-not-real" for provider in moved.providers}
    moved_client = ModelClient(
        api_key=keys,
        manifest=moved,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=100),
    )
    # The positive control: the moved model is askable here, from its new provider.
    assert moved_client.refusals == {}
    assert model_refusal(moved_client, moved, decision_contract(), model) == "provider_changed"
    host = _host(world, moved_client, services, moved)
    for _ in range(3):
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert _requests(services, world, snapshot) == 0 and transport.requests == []
    import exulanica.api.services as services_module

    client.app.state.services = dataclasses.replace(services, model_client=moved_client)
    monkeypatch.setattr(services_module, "load_manifest", lambda: moved)
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert {choice["refusal"] for choice in read.json()["choices"]} == {"provider_changed"}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_workspace_the_host_does_not_list_is_never_asked_for(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    host = _host(world, _client(manifest, transport), services, manifest, listed=False)
    for _ in range(10):
        assert (
            host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS) is False
        )
        snapshot = stays._step(world, client, snapshot)
    assert _decisions(services, world, snapshot) == [] and transport.requests == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_choice_names_this_societys_people_and_an_offered_model_or_is_refused(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    refusals = {
        "person_not_in_this_world": ([str(uuid.uuid4())], model),
        "model_not_declared": (people[:1], {"provider": model["provider"], "model_id": "no/such"}),
        "model_not_offered": (
            people[:1],
            {
                "provider": model["provider"],
                "model_id": _unoffered(manifest),
            },
        ),
    }
    for code, (who, what) in refusals.items():
        with pytest.raises(ModelChoiceRefused) as refused:
            _choose(services, world, who, what, manifest=manifest)
        assert refused.value.code == code
    key = uuid.uuid4()
    first = _choose(services, world, people[:2], model, manifest=manifest, key=key)
    again = _choose(services, world, people[:2], model, manifest=manifest, key=key)
    assert first == again and first["choice_seq"] == 1
    with pytest.raises(ModelChoiceRefused) as reused:
        _choose(services, world, people[:1], model, manifest=manifest, key=key)
    assert reused.value.code == "choice_key_reused"
    routine = _choose(services, world, people[:1], None, manifest=manifest)
    with services.database.session(world["workspace"]) as connection:
        current = SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).current(world["binding"].version_id)
        assert current[people[0]]["model"] is None
        assert current[people[1]]["model"] == model
        assert current[people[0]]["choice_seq"] == routine["choice_seq"] == 2
        # A recorded choice is never rewritten: the runtime holds no UPDATE on the table
        # (INSERT_ONLY_TABLES), and a role that does, the schema's owner, meets 0110's trigger.
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            connection.execute(
                "update world_society_model_choice set chosen_by=chosen_by "
                "where workspace_id=%s and world_id=%s",
                (world["workspace"], world["binding"].world_id),
            )
    owner = world["connection"]
    with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), owner.transaction():
        owner.execute(
            "update world_society_model_choice set chosen_by=chosen_by "
            "where workspace_id=%s and world_id=%s",
            (world["workspace"], world["binding"].world_id),
        )
    contract = decision_contract()
    tight = dataclasses.replace(contract, policy={**contract.policy, "model_people_maximum": 1})
    with (
        services.database.session(world["workspace"]) as connection,
        pytest.raises(ModelChoiceRefused) as crowded,
    ):
        SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_choice(
            world["binding"].version_id,
            request_id=uuid.uuid4(),
            people=people[2:4],
            model=model,
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=tight,
        )
    assert crowded.value.code == "too_many_model_people"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_only_a_caller_who_may_ask_models_changes_whose_model_runs_a_person(app, monkeypatch):
    """A choice commits the world's host to asking a model, so it takes a world write and a model
    invocation, which in a browser only the workspace's owner holds; reading it takes a world read.
    """
    world, client = app
    manifest, model_id = _offered()
    import exulanica.api.routes.society_models as route_module

    monkeypatch.setattr(route_module, "load_manifest", lambda: manifest)
    snapshot = stays._inhabited(world, client)
    callers = _callers(client, world, listed=True)
    scope, _, society = routes(world)
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])[:2]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    body = {"idempotency_key": str(uuid.uuid4()), "people": people, "model": model}
    # An id-addressed route answers a refused permission as it answers an id nobody holds, so
    # which permission was missing is read from the refusal ledger rather than the status.
    for caller in ("reader", "keeper", "stranger"):
        refused = client.post(
            society + "/models", headers=callers[caller][0], params=scope, json=body
        )
        assert (refused.status_code, refused.json()["code"]) == (404, "unknown_reference")
    with _services(client).database.session(world["workspace"]) as connection:
        missing = {
            row["actor"]: row["missing_permissions"]
            for row in connection.execute(
                "select actor::text, missing_permissions from route_permission_refusal "
                "where route_path = %s",
                ("/world/versions/{version_id}/society/models",),
            ).fetchall()
        }
    assert missing == {
        callers["reader"][1]: ["model.invoke", "world.write"],
        callers["keeper"][1]: ["model.invoke"],
    }
    before = client.get(society + "/models", headers=callers["reader"][0], params=scope)
    assert before.status_code == 200, before.text
    assert before.json()["choices"] == []
    chosen = client.post(society + "/models", headers=callers["owner"][0], params=scope, json=body)
    assert chosen.status_code == 200, chosen.text
    assert chosen.json()["chosen_by"] == str(world["session"].actor)
    after = client.get(society + "/models", headers=callers["reader"][0], params=scope).json()
    assert after["takes_model_choices"] is True
    assert [(c["subject_id"], c["model"]) for c in after["choices"]] == [(p, model) for p in people]
    offered = {entry["model_id"]: entry for entry in after["models"]}
    assert offered[model_id]["mechanism"] == "tool_call"
    # This process has no model client, so it says so for the host and for every provider.
    assert after["host_refusal"] == "provider_credential_absent"
    assert offered[model_id]["refusal"] == "provider_credential_absent"
    callers = _callers(client, world, listed=False)
    unlisted = client.get(society + "/models", headers=callers["owner"][0], params=scope).json()
    assert unlisted["host_refusal"] == "models_not_run_here"


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_route_names_each_refused_choice(app, monkeypatch):
    world, client = app
    manifest, model_id = _offered()
    import exulanica.api.routes.society_models as route_module

    monkeypatch.setattr(route_module, "load_manifest", lambda: manifest)
    snapshot = stays._inhabited(world, client)
    scope, _, society = routes(world)
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    provider = manifest.spec(model_id).provider
    model = {"provider": provider, "model_id": model_id}
    unoffered = _unoffered(manifest)

    def choose(key, who, what):
        return client.post(
            society + "/models",
            headers=OWNER,
            params=scope,
            json={"idempotency_key": str(key), "people": who, "model": what},
        )

    key = uuid.uuid4()
    for who, what, status, code in (
        ([str(uuid.uuid4())], model, 422, "person_not_in_this_world"),
        ([people[0], people[0]], model, 422, "person_named_twice"),
        (people[:1], {"provider": provider, "model_id": unoffered}, 422, "model_not_offered"),
        (people[:1], {"provider": "elsewhere", "model_id": model_id}, 422, "model_not_declared"),
    ):
        refused = choose(uuid.uuid4(), who, what)
        assert (refused.status_code, refused.json()["code"]) == (status, code), refused.text
    assert choose(key, people[:1], model).status_code == 200
    assert choose(key, people[:1], model).json()["choice_seq"] == 1
    reused = choose(key, people[:2], model)
    assert (reused.status_code, reused.json()["code"]) == (409, "choice_key_reused")
    # An exact retry is answered with what it recorded, even once its model is no longer offered.
    no_longer = dataclasses.replace(
        manifest,
        models={
            m: (dataclasses.replace(s, answering={}) if m == model_id else s)
            for m, s in manifest.models.items()
        },
    )
    monkeypatch.setattr(route_module, "load_manifest", lambda: no_longer)
    again = choose(key, people[:1], model)
    assert (again.status_code, again.json()["choice_seq"]) == (200, 1), again.text
    assert choose(uuid.uuid4(), people[:1], model).json()["code"] == "model_not_offered"


# -- the playback worker's decision phase ----------------------------------------------------------


class _Hook:
    """A decision phase that answers as it is told, or fails, and keeps what it was given."""

    def __init__(self, *, answer: bool = True, fails: bool = False) -> None:
        self.answer, self.fails = answer, fails
        self.calls: list[tuple[ControlClaim, float]] = []

    def __call__(self, claim: ControlClaim, lease_ends: float) -> bool:
        self.calls.append((claim, lease_ends))
        if self.fails:
            raise RuntimeError("the decision phase failed")
        return self.answer


def _playing_overdue(world, client) -> None:
    """The world saved as playing, with its next minute due long enough ago to run several."""
    scope, _, society = routes(world)
    control = client.get(society + "/control", headers=OWNER, params=scope).json()
    if control["mode"] != "playing":
        played = client.put(
            society + "/control",
            headers=OWNER,
            params=scope,
            json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
        )
        assert played.status_code == 200, played.text
    world["connection"].execute(
        "update world_society_control set next_due_at=clock_timestamp()-interval '1 minute' "
        "where workspace_id=%s",
        (world["workspace"],),
    )
    world["connection"].commit()


def _worker(services, world, hook) -> SocietyControlWorker:
    return SocietyControlWorker(
        services.database,
        runtime=services.society_runtime,
        workspaces=[world["workspace"]],
        before_minute=hook,
    )


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize(
    ("answer", "fails", "ticks"),
    [(True, False, 1), (False, False, MAX_CATCHUP_TICKS), (True, True, 1)],
    ids=["asked", "asked-nobody", "failed"],
)
def test_the_worker_asks_before_a_claimed_minute_and_runs_one_when_it_asked(
    app, answer, fails, ticks
):
    """A claim asks the decision phase first, with its lease; a minute that asked runs alone, so
    the next claim asks again; one that asked nobody catches up as it would; a failed phase is
    the routine deciding, one minute."""
    world, client = app
    stays._inhabited(world, client)
    _playing_overdue(world, client)
    hook = _Hook(answer=answer, fails=fails)
    started = time.monotonic()
    result = _worker(_services(client), world, hook).run_once(world["workspace"])
    assert result is not None and result["receipt"]["executed_ticks"] == ticks
    ((claim, lease_ends),) = hook.calls
    assert claim.version_id == world["binding"].version_id
    assert started < lease_ends <= time.monotonic() + LEASE_SECONDS


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_receipts_asked_before_a_claimed_minute_are_consumed_by_that_minute(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, _client(manifest, transport), services, manifest)
    _playing_overdue(world, client)
    result = _worker(services, world, host.before_minute).run_once(world["workspace"])
    assert result is not None and result["receipt"]["executed_ticks"] == 1
    receipts = _decisions(services, world, snapshot)
    assert receipts and {r["base_tick"] for r in receipts} == {snapshot["current_tick"]}
    with services.database.session(world["workspace"]) as connection:
        consumed = connection.execute(
            "select distinct tick from world_society_transition_decision "
            "where workspace_id=%s and society_id=%s",
            (world["workspace"], snapshot["society_id"]),
        ).fetchall()
    assert {row["tick"] for row in consumed} == {snapshot["current_tick"] + 1}


# -- a request left open, and a world sent away while a model is asked -----------------------------


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_request_left_unanswered_is_closed_by_name_after_its_minute_ran_with_the_routine(app):
    """A host stopped between reserving and recording leaves a request with no receipt: its
    minute runs with the routine deciding, and the host's next minute closes it by name."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    contract = decision_contract()
    with services.database.session(world["workspace"]) as connection:
        decisions = SocietyDecisionRepository(
            SocietyRepository(
                connection,
                world["workspace"],
                world_id=world["binding"].world_id,
                input_authorizer=lambda doc: services.society_runtime.authorize(
                    connection, world["session"], doc
                ),
            )
        )
        with connection.transaction():
            reserved, fresh = decisions.prepare_person(
                world["binding"].version_id,
                request_id=uuid.uuid4(),
                subject_id=uuid.UUID(people[0]),
                base_tick=snapshot["current_tick"],
                base_state_sha256=snapshot["state_sha256"],
                contract=contract,
                provider_config={
                    "provider": model["provider"],
                    "model_id": model_id,
                    "mechanism": "tool_call",
                    "choice_seq": 1,
                    "manifest_sha256": "a" * 64,
                    "prompt_version": "society-person-choice/v1",
                    "contract": contract.binding(),
                    "deadline_ms": contract.value("decision_deadline_ms"),
                },
            )
    assert fresh and reserved["request"] is not None
    after = stays._step(world, client, snapshot)
    person = next(p for p in after["state"]["inhabitants"] if p["id"] == people[0])
    assert (person["goal"] or {}).get("reason") != "chosen_by_their_model"
    host = _host(world, _client(manifest, transport), services, manifest)
    host.before_minute(_claim(world, after), time.monotonic() + LEASE_SECONDS)
    closed = [r for r in _decisions(services, world, after) if r["subject_id"] == people[0]]
    assert (closed[0]["status"], closed[0]["reason"]) == ("unavailable", "unanswered_in_its_minute")
    stays._step(world, client, after)
    scope, _, society = routes(world)
    replayed = client.get(society + "/replay", headers=OWNER, params=scope).json()
    assert replayed["replay_verified"] is True


class _SendingAway(_Chooser):
    """A model that, while it is asked, has the world's owner try to send everyone away."""

    def __init__(self, attempt) -> None:
        super().__init__()
        self.attempt = attempt
        self.answers: list[tuple[int, str]] = []
        self.first = threading.Lock()

    def post_json(self, url, *, headers, payload, timeout):
        # People are asked at once; the owner tries once, while the first of them is asked.
        with self.first:
            if not self.answers:
                response = self.attempt()
                self.answers.append((response.status_code, response.json().get("code")))
        return super().post_json(url, headers=headers, payload=payload, timeout=timeout)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_sending_everyone_away_waits_while_a_model_decides_and_the_clock_keeps_running(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    scope, _, society = routes(world)

    def away(current):
        return client.post(
            society + "/presence",
            headers=OWNER,
            params=scope,
            json={
                "idempotency_key": str(uuid.uuid4()),
                "presence": "away",
                "base_tick": current["current_tick"],
                "base_state_sha256": current["state_sha256"],
            },
        )

    transport = _SendingAway(lambda: away(snapshot))
    host = _host(world, _client(manifest, transport), services, manifest)
    _playing_overdue(world, client)
    result = _worker(services, world, host.before_minute).run_once(world["workspace"])
    assert transport.answers == [(409, "a_request_is_waiting")]
    assert result is not None and result["receipt"]["executed_ticks"] == 1
    after = client.get(society, headers=OWNER, params=scope).json()
    assert after["current_tick"] == snapshot["current_tick"] + 1
    # Once the minute consumed every receipt, the same request is taken.
    sent = away(after)
    assert sent.status_code == 200, sent.text
    replayed = client.get(society + "/replay", headers=OWNER, params=scope).json()
    assert replayed["replay_verified"] is True


# -- a host that can ask nobody --------------------------------------------------------------------


def _guard_for(cause: str, smallest: Decimal) -> BudgetGuard | None:
    if cause == "no_client":
        return None
    if cause == "budget_dollars":
        return BudgetGuard(ceiling_usd=smallest / 2, max_calls=100)
    if cause == "budget_calls":
        return BudgetGuard(ceiling_usd=Decimal(1), max_calls=0)
    # Room for an ask in the whole budget, and none in the half people's decisions may spend.
    return BudgetGuard(ceiling_usd=smallest * Decimal("1.5"), max_calls=100)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize(
    ("cause", "refusal", "note"),
    [
        ("no_client", "provider_credential_absent", "no model credential"),
        ("budget_dollars", "process_budget_spent", "has spent its model budget"),
        ("budget_calls", "process_budget_spent", "has spent its model budget"),
        ("share", "process_share_spent", "is down to the part its decision contract keeps"),
    ],
    ids=["no-client", "dollars", "calls", "share"],
)
def test_a_host_that_can_ask_nobody_reserves_nothing_writes_nothing_and_says_why(
    app, cause, refusal, note
):
    world, client = app
    services = _services(client)
    manifest = load_manifest()
    contract = decision_contract()
    spec = manifest.offered_models(Role.SOCIETY_DECISION)[0]
    probe = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    smallest = smallest_ask_usd(probe, manifest, contract)
    guard = _guard_for(cause, smallest)
    transport = _Chooser()
    model_client = (
        None
        if guard is None
        else ModelClient(
            api_key="test-key-not-real", manifest=manifest, transport=transport, budget=guard
        )
    )
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": spec.provider, "model_id": spec.model_id},
        manifest=manifest,
    )
    host = _host(world, model_client, services, manifest)
    for _ in range(3):
        assert not host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert _requests(services, world, snapshot) == 0 and transport.requests == []
    listed = dataclasses.replace(
        services, model_client=model_client, society_control_workspaces=(world["workspace"],)
    )
    assert listed.model_host_refusal(world["workspace"]) == refusal
    # What the page reads and what an operator reads say the same thing.
    client.app.state.services = listed
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert read.json()["host_refusal"] == refusal
    warnings = client.get("/readyz").json()["warnings"]
    assert any(note in warning for warning in warnings), warnings
    if cause != "no_client":
        # Said only where a playback host asks models for people: for listed workspaces, never
        # for a host that plays what account discovery finds alone.
        for discovery in (False, True):
            client.app.state.services = dataclasses.replace(
                listed, society_control_workspaces=(), runs_society_control_worker=discovery
            )
            unhosted = client.get("/readyz").json()["warnings"]
            assert not any(note in warning for warning in unhosted), (discovery, unhosted)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("refusal", ["process_budget_spent", "process_share_spent"])
def test_a_person_whose_model_no_longer_fits_the_budget_is_asked_nothing_and_told_why(app, refusal):
    """What is left may fit an ask of the cheapest offered model and not of the one a person was
    given. The host still asks for others, reserves nothing for that person, and the models route
    says why for their choice; the budget never refills, so this holds until a restart."""
    world, client = app
    services = _services(client)
    manifest = load_manifest()
    contract = decision_contract()
    probe = BudgetGuard(ceiling_usd=Decimal(1), max_calls=100)
    offered = [
        spec
        for spec in manifest.offered_models(Role.SOCIETY_DECISION)
        if contract.mechanism_for(spec) is not None
    ]
    dearest = max(offered, key=lambda spec: ask_bound_usd(probe, spec, contract))
    need = ask_bound_usd(probe, dearest, contract)
    cheapest = smallest_ask_usd(probe, manifest, contract)
    # The positive control: the model given needs more than twice the cheapest ask, so a ceiling
    # can fit the cheapest ask in the share and not the model given.
    assert cheapest is not None and 2 * cheapest < need
    ceiling = (2 * cheapest + need) / 2 if refusal == "process_budget_spent" else need * 3 / 2
    model_client = ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=(transport := _Chooser()),
        budget=BudgetGuard(ceiling_usd=ceiling, max_calls=100),
    )
    assert host_refusal(model_client, manifest, contract) is None
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": dearest.provider, "model_id": dearest.model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, model_client, services, manifest)
    for _ in range(3):
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert _requests(services, world, snapshot) == 0 and transport.requests == []
    client.app.state.services = dataclasses.replace(
        services, model_client=model_client, society_control_workspaces=(world["workspace"],)
    )
    scope, _, society = routes(world)
    read = client.get(society + "/models", headers=OWNER, params=scope)
    assert read.status_code == 200, read.text
    assert read.json()["host_refusal"] is None
    assert {choice["refusal"] for choice in read.json()["choices"]} == {refusal}


class _Changing:
    """A workspace's rules that would replace a word wherever it stands, as a saved name's is,
    keeping every text they were shown."""

    def __init__(self, word: str) -> None:
        self.word = word
        self.shown: list[str] = []
        #: How many times the choice's description and labels were judged before an ask.
        self.judged = 0

    def admit(self, request):
        self.shown.extend(request.texts)
        self.judged += request.texts[:1] == (CHOICE_DESCRIPTION,)
        return [text.replace(self.word, "[place A]") for text in request.texts]


def _offered_labels(transport) -> list[str]:
    return [
        label
        for request in transport.requests
        for label in request["payload"]["tools"][0]["function"]["parameters"]["properties"][
            "action"
        ]["enum"]
    ]


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_place_the_workspace_rules_would_change_is_left_out_and_the_rest_asked(app):
    """A saved name that matches a place's words would refuse the whole ask, every minute. The
    place is left out of the offer instead, and the person chooses among the rest."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    rules = _Changing("visiting")
    host = dataclasses.replace(
        _host(world, _client(manifest, transport), services, manifest),
        policy_for=lambda workspace_id: rules,
    )
    minutes = []
    for _ in range(4):
        judged, reserved = rules.judged, _requests(services, world, snapshot)
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        minutes.append((rules.judged - judged, _requests(services, world, snapshot) - reserved))
        snapshot = stays._step(world, client, snapshot)
    # One judgement a minute for the one chosen model, however many people it asked for.
    assert all(judged == 1 for judged, reserved in minutes if reserved), minutes
    assert any(reserved > 1 for _, reserved in minutes), minutes
    # The positive control: places to visit were there to be left out.
    assert any(text.startswith("visiting, ") for text in rules.shown)
    offered = _offered_labels(transport)
    assert offered and not any("visiting" in label for label in offered)
    receipts = _decisions(services, world, snapshot)
    assert receipts and all(r["reason"] != "request_refused" for r in receipts)
    assert any(r["status"] == "accepted" for r in receipts)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_left_no_place_by_the_workspace_rules_is_asked_nothing_and_nothing_is_written(
    app,
):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    # Every place's words would change; waiting alone is no choice to ask a model for.
    rules = _Changing(" m away")
    host = dataclasses.replace(
        _host(world, _client(manifest, transport), services, manifest),
        policy_for=lambda workspace_id: rules,
    )
    for _ in range(3):
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert rules.shown, "nobody was at a choice point, so the rules were never asked"
    assert _requests(services, world, snapshot) == 0 and transport.requests == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_saved_name_sharing_a_word_with_the_question_asks_nobody_and_is_named(app, monkeypatch):
    """A saved name's part may be a word of the question every person is asked ("the" of "Joe the
    Plumber"), which the rules would change, so every ask would be refused as it left. The host
    asks nobody and writes nothing, and the models route names why for each choice."""
    import exulanica.api.services as services_module

    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    monkeypatch.setattr(services_module, "load_manifest", lambda: manifest)
    transport = _Chooser()
    model_client = _client(manifest, transport)
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    client.app.state.services = dataclasses.replace(
        services, model_client=model_client, society_control_workspaces=(world["workspace"],)
    )
    scope, _, society = routes(world)

    def refusals() -> set[str | None]:
        read = client.get(society + "/models", headers=OWNER, params=scope)
        assert read.status_code == 200, read.text
        return {choice["refusal"] for choice in read.json()["choices"]}

    # The positive control: with no such name, the choices are asked.
    assert refusals() == {None}
    connection = world["connection"]
    identity = IdentityRepository(connection, world["workspace"])
    rename_entity(
        identity,
        AssertionWriter(connection, world["workspace"]),
        entity_id=identity.entities.create(entity_class="person"),
        display_name="Joe the Plumber",
        actor=world["session"].actor,
    )
    connection.commit()
    host = _host(world, model_client, services, manifest)
    for _ in range(3):
        host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
        snapshot = stays._step(world, client, snapshot)
    assert _requests(services, world, snapshot) == 0 and transport.requests == []
    assert refusals() == {"question_changed_by_rules"}


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_person_left_one_option_is_asked_nothing_and_nothing_is_written(app):
    """A request offers two options at least. One left is nothing to ask, as no place left is,
    and never a refusal inside the reservation that would leave everybody else unasked."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    subject = next(p["id"] for p in snapshot["state"]["inhabitants"] if at_choice_point(p))
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, [subject], model, manifest=manifest)
    contract = decision_contract()

    def places(options):
        return [option for option in options if option.kind == "target"]

    with services.database.session(world["workspace"]) as connection:
        decisions = SocietyDecisionRepository(
            SocietyRepository(
                connection,
                world["workspace"],
                world_id=world["binding"].world_id,
                input_authorizer=lambda doc: services.society_runtime.authorize(
                    connection, world["session"], doc
                ),
            )
        )

        def prepare(offer):
            with connection.transaction():
                return decisions.prepare_person(
                    world["binding"].version_id,
                    request_id=uuid.uuid4(),
                    subject_id=uuid.UUID(subject),
                    base_tick=snapshot["current_tick"],
                    base_state_sha256=snapshot["state_sha256"],
                    contract=contract,
                    provider_config={
                        "provider": model["provider"],
                        "model_id": model_id,
                        "mechanism": "tool_call",
                        "choice_seq": 1,
                        "manifest_sha256": "a" * 64,
                        "prompt_version": "society-person-choice/v1",
                        "contract": contract.binding(),
                        "deadline_ms": contract.value("decision_deadline_ms"),
                    },
                    offer=offer,
                )

        alone = prepare(lambda options: places(options)[:1])
        assert alone == ({"request": None, "decision": None, "status": "nothing_to_choose"}, False)
        assert _requests(services, world, snapshot) == 0
        # The positive control: the same place with waiting beside it is a choice to ask.
        reserved, fresh = prepare(
            lambda options: [*places(options)[:1], *(o for o in options if o.kind == "wait")]
        )
    assert fresh and len(reserved["request"]["context"]["options"]) == 2


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_request_older_than_the_window_is_left_unanswered_and_harms_nothing(app):
    """The host reads only the last few minutes' unanswered requests, so the read does not grow
    with the world's age. An older one stays as it is: nothing replays or waits on it."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = sorted(person["id"] for person in snapshot["state"]["inhabitants"])
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    contract = decision_contract()
    with services.database.session(world["workspace"]) as connection:
        decisions = SocietyDecisionRepository(
            SocietyRepository(
                connection,
                world["workspace"],
                world_id=world["binding"].world_id,
                input_authorizer=lambda doc: services.society_runtime.authorize(
                    connection, world["session"], doc
                ),
            )
        )
        with connection.transaction():
            reserved, fresh = decisions.prepare_person(
                world["binding"].version_id,
                request_id=uuid.uuid4(),
                subject_id=uuid.UUID(people[0]),
                base_tick=snapshot["current_tick"],
                base_state_sha256=snapshot["state_sha256"],
                contract=contract,
                provider_config={
                    "provider": model["provider"],
                    "model_id": model_id,
                    "mechanism": "tool_call",
                    "choice_seq": 1,
                    "manifest_sha256": "a" * 64,
                    "prompt_version": "society-person-choice/v1",
                    "contract": contract.binding(),
                    "deadline_ms": contract.value("decision_deadline_ms"),
                },
            )
    assert fresh and reserved["request"] is not None
    orphan = reserved["request"]["request_id"]
    for _ in range(UNANSWERED_WINDOW_TICKS + 1):
        snapshot = stays._step(world, client, snapshot)
    with services.database.session(world["workspace"]) as connection:
        repository = SocietyDecisionRepository(
            SocietyRepository(connection, world["workspace"], world_id=world["binding"].world_id)
        )
        assert repository.unanswered_person_requests(world["binding"].version_id) == []
    host = _host(world, _client(manifest, _Chooser()), services, manifest)
    host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    assert orphan not in {r["request_id"] for r in _decisions(services, world, snapshot)}
    after = stays._step(world, client, snapshot)
    scope, _, society = routes(world)
    assert client.get(society + "/replay", headers=OWNER, params=scope).json()["replay_verified"]
    sent = client.post(
        society + "/presence",
        headers=OWNER,
        params=scope,
        json={
            "idempotency_key": str(uuid.uuid4()),
            "presence": "away",
            "base_tick": after["current_tick"],
            "base_state_sha256": after["state_sha256"],
        },
    )
    assert sent.status_code == 200, sent.text


@pytest.mark.parametrize("saved_world", [2], indirect=True)
@pytest.mark.parametrize("where", ["prepare_person", "finish"])
def test_a_race_with_the_asset_read_lock_is_asked_once_more_and_nothing_is_lost(
    app, monkeypatch, where
):
    """Reading an input's stored bytes and taking the asset read lock can race. The step that
    met it rolled back and holds nothing, so it is asked once more: every person asked is asked
    once, and every request gets its receipt."""
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    _choose(
        services,
        world,
        people,
        {"provider": manifest.spec(model_id).provider, "model_id": model_id},
        manifest=manifest,
    )
    original = getattr(SocietyDecisionRepository, where)
    raced: list[str] = []

    def racing(self, *args, **kwargs):
        if not raced:
            raced.append(where)
            raise SocietyBytesNotRead("stored bytes were not read before the lock; ask again")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(SocietyDecisionRepository, where, racing)
    host = _host(world, _client(manifest, transport), services, manifest)
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipts = _decisions(services, world, snapshot)
    assert raced == [where] and receipts
    assert _requests(services, world, snapshot) == len(receipts)
    assert transport.call_count == sum(1 for r in receipts if r["provider"] is not None)


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_minute_whose_lease_leaves_no_time_to_ask_reserves_nothing(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    transport = _Chooser()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, _client(manifest, transport), services, manifest)
    contract = decision_contract()
    # A lease that ends before the minute's room to commit: no ask could end in time.
    commit_room = LEASE_SECONDS - contract.value("decision_deadline_ms") / 1000
    assert host.before_minute(_claim(world, snapshot), time.monotonic() + commit_room - 1)
    assert _requests(services, world, snapshot) == 0 and transport.requests == []


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_society_records_only_the_decision_receipts_of_its_own_engine(app):
    world, client = app
    services = _services(client)
    manifest, model_id = _offered()
    snapshot = stays._inhabited(world, client)
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    model = {"provider": manifest.spec(model_id).provider, "model_id": model_id}
    _choose(services, world, people, model, manifest=manifest)
    host = _host(world, _client(manifest, _Chooser()), services, manifest)
    host.before_minute(_claim(world, snapshot), time.monotonic() + LEASE_SECONDS)
    receipt = _decisions(services, world, snapshot)[0]
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="receipts of its own engine"),
        services.database.session(world["workspace"]) as connection,
    ):
        count = connection.execute(
            "select count(*) as n from world_society_decision where workspace_id=%s "
            "and society_id=%s",
            (world["workspace"], snapshot["society_id"]),
        ).fetchone()["n"]
        forged = {**receipt, "profile": "exulanica.society-decision/v1"}
        connection.execute(
            "insert into world_society_decision(workspace_id,society_id,decision_seq,request_id,"
            "document,document_sha256) values(%s,%s,%s,%s,%s,%s)",
            (
                world["workspace"],
                snapshot["society_id"],
                count + 1,
                receipt["request_id"],
                Jsonb(forged),
                receipt["document_sha256"],
            ),
        )
