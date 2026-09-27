"""The person role through the deployed database stores and applies exactly what the role builds.

``tests/test_person_role_goldens.py`` pins the person role's bytes in memory. This file holds the
deployed path to those same bytes: the application runs as a provisioned runtime role over a saved
world, the owner chooses a model for everybody, and each minute the host's decision phase asks a
scripted model behind the real client, as playback does, and the steps route takes the minute.
Before each minute the test builds, from the stored state and input alone, every request the person
role would reserve, the receipt each scripted answer makes and the minute the engine then runs;
after it, the database must hold exactly those requests, those receipts (latencies aside, which
the host measures on its own clock) and that state, and the replay route must replay it all with
no call. A saved world's ids are drawn afresh for every test, so the bytes themselves are pinned
in memory, not here.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api.decision_host import DecisionHost
from exulanica.api.society_person_decisions import PersonAsk, ask_person
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import MANIFEST_PATH, parse_manifest
from exulanica.models.transport import HttpResponse
from exulanica.world.society import society_state_sha256
from exulanica.world.society_controls import LEASE_SECONDS, ControlClaim
from exulanica.world.society_decision_contract import (
    at_choice_point,
    decision_contract,
    person_role,
)
from exulanica.world.society_decisions import person_request, receipt_for
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_model_decisions import model_goal_policies
from exulanica.world.society_planner import advance_purposeful_society

import test_society_stay_requests_api as stays
from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_society_saved_world_api import OWNER, routes

saved_world = stays.saved_world
app = stays.app
pytestmark = pytest.mark.postgres

PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
MODEL_ID = "example/tool-model"
#: Minutes the host asks and the steps route takes, from the minute people are brought in.
MINUTES = 12


def _manifest():
    """The manifest with one example model verified by a forced function, at stated prices."""
    document = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)
    template = next(
        raw
        for _model_id, raw in sorted(document["models"].items())
        if raw.get("answering") and raw["min_max_tokens"] is not None
    )
    document["models"][MODEL_ID] = {
        **template,
        "description": "Example tool model, asked by a forced function",
        "input_usd_per_mtok": Decimal("0.10"),
        "output_usd_per_mtok": Decimal("0.40"),
        "context_window_tokens": 131072,
        "min_max_tokens": 64,
        "default_max_tokens": 512,
        "catalog_use_cases": ["text", "function_calling"],
        "answering": {"tool_call": PROBE_RECORD},
    }
    document["models"][MODEL_ID].pop("answering_order", None)
    return parse_manifest(document)


class _Scripted(FakeTransport):
    """A model that answers each ask by the offered label the offer's own labels pick."""

    def post_json(self, url, *, headers, payload, timeout):
        self.requests.append({"url": url, "headers": dict(headers), "payload": dict(payload)})
        enum = payload["tools"][0]["function"]["parameters"]["properties"]["action"]["enum"]
        pick = sorted(enum)[len(enum) // 2]
        body = chat_body(
            "", model=payload["model"], prompt_tokens=300, completion_tokens=40, reasoning_tokens=10
        )
        body["choices"][0]["finish_reason"] = "tool_calls"
        body["choices"][0]["message"]["content"] = None
        body["choices"][0]["message"]["tool_calls"] = [
            {
                "id": "call",
                "type": "function",
                "function": {"name": "act", "arguments": json.dumps({"action": pick})},
            }
        ]
        return HttpResponse(200, json.dumps(body))


def _client(manifest, transport) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("5"), max_calls=1000),
    )


def _host(world, services, manifest, transport) -> DecisionHost:
    def policy_for(workspace_id):
        return services.request_policy(
            workspace_id,
            lambda: services.readonly_database.session(workspace_id),
            released_places=no_place_released,
        )

    return DecisionHost(
        database=services.database,
        runtime=services.society_runtime,
        client=_client(manifest, transport),
        workspaces=frozenset({world["workspace"]}),
        policy_for=policy_for,
        manifest=manifest,
        manifest_sha256="a" * 64,
    )


def _claim(world, society_id) -> ControlClaim:
    return ControlClaim(
        workspace_id=world["workspace"],
        world_id=world["binding"].world_id,
        society_id=uuid.UUID(society_id),
        version_id=world["binding"].version_id,
        token=uuid.uuid4(),
        revision=1,
        actor=world["session"].actor,
    )


def _held(services, world, society_id) -> dict[str, Any]:
    """The society as stored: its state, seed and latest input, and every decision row."""
    scope = (world["workspace"], society_id)
    with services.database.session(world["workspace"]) as connection:
        row = connection.execute(
            "select state,state_sha256,seed from world_society where workspace_id=%s "
            "and society_id=%s",
            scope,
        ).fetchone()
        latest = connection.execute(
            "select document from world_society_input where workspace_id=%s and society_id=%s "
            "order by input_seq desc limit 1",
            scope,
        ).fetchone()
        requests = connection.execute(
            "select document from world_society_decision_request where workspace_id=%s "
            "and society_id=%s order by base_tick,subject_id",
            scope,
        ).fetchall()
        receipts = connection.execute(
            "select document from world_society_decision where workspace_id=%s "
            "and society_id=%s order by decision_seq",
            scope,
        ).fetchall()
        bound = connection.execute(
            "select tick,decision_seq,disposition from world_society_transition_decision "
            "where workspace_id=%s and society_id=%s order by decision_seq",
            scope,
        ).fetchall()
    return {
        "state": row["state"],
        "state_sha256": row["state_sha256"],
        "seed": row["seed"],
        "input": latest["document"],
        "requests": [value["document"] for value in requests],
        "receipts": [value["document"] for value in receipts],
        "bound": [(value["tick"], value["decision_seq"], value["disposition"]) for value in bound],
    }


def _unmeasured(receipt: dict[str, Any]) -> dict[str, Any]:
    """A receipt with the latencies its host measured on its own clock left out."""
    held = copy.deepcopy(receipt)
    held.pop("document_sha256")
    if held["provider"] is not None:
        held["provider"]["latency_ms"] = None
        for call in held["provider"]["calls"]:
            call["latency_ms"] = None
    return held


@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_the_host_stores_and_the_minute_applies_exactly_what_the_person_role_builds(app):
    world, client = app
    services = client.app.state.services
    manifest = _manifest()
    spec = manifest.spec(MODEL_ID)
    contract = decision_contract()
    mechanism = contract.mechanism_for(spec)
    assert mechanism is not None
    snapshot = stays._inhabited(world, client)
    society_id = snapshot["society_id"]
    people = [person["id"] for person in snapshot["state"]["inhabitants"]]
    with services.database.session(world["workspace"]) as connection:
        choice = SocietyModelChoiceRepository(
            connection, world["workspace"], world_id=world["binding"].world_id
        ).record_choice(
            world["binding"].version_id,
            person_role(),
            request_id=uuid.uuid4(),
            subjects=people,
            model={"provider": spec.provider, "model_id": MODEL_ID},
            chosen_by=world["session"].actor,
            manifest=manifest,
            contract=contract,
        )
    host = _host(world, services, manifest, _Scripted())
    # The same answers, asked in memory of the same model through a client of its own.
    asking = _client(manifest, _Scripted()).with_policy(RecordingPolicy())
    config = {
        "provider": spec.provider,
        "model_id": MODEL_ID,
        "mechanism": mechanism.value,
        "choice_seq": choice["choice_seq"],
        "manifest_sha256": "a" * 64,
        "prompt_version": person_role().prompt_version,
        "contract": contract.binding(),
        "deadline_ms": contract.value("decision_deadline_ms"),
    }
    asked_total = 0
    applied_total = 0
    for _ in range(MINUTES):
        before = _held(services, world, society_id)
        state, document = before["state"], before["input"]
        expected = []
        for person in sorted(state["inhabitants"], key=lambda p: p["id"]):
            if not at_choice_point(person):
                continue
            request, _status = person_request(
                state,
                document,
                person["id"],
                request_id=uuid.uuid5(
                    uuid.UUID(society_id), f"person-decision:{person['id']}:{state['tick']}"
                ),
                contract=contract,
                seed=before["seed"],
                provider_config=config,
            )
            if request is not None:
                expected.append(request)
        assert host.before_minute(_claim(world, society_id), time.monotonic() + LEASE_SECONDS)
        asked = _held(services, world, society_id)
        fresh = [r for r in asked["requests"] if r["base_tick"] == state["tick"]]
        assert fresh == sorted(expected, key=lambda r: r["subject_id"])
        # Each receipt is the one the same scripted answer makes of its request, in order.
        receipts = asked["receipts"][len(before["receipts"]) :]
        by_request = {r["request_id"]: r for r in fresh}
        assert [r["request_id"] for r in receipts] == [r["request_id"] for r in expected]
        for sequence, receipt in enumerate(receipts, len(before["receipts"]) + 1):
            request = by_request[receipt["request_id"]]
            answer = ask_person(asking, PersonAsk(request, spec, mechanism), contract, 1e18)
            assert _unmeasured(receipt) == _unmeasured(receipt_for(request, sequence, answer))
        # The minute the steps route runs is the one the engine runs over those receipts.
        policies, decided = model_goal_policies(state, document, receipts, {})
        after, _events = advance_purposeful_society(
            state, before["seed"], [document], goal_policy=policies
        )
        snapshot = stays._step(world, client, snapshot)
        stepped = _held(services, world, society_id)
        assert stepped["state_sha256"] == society_state_sha256(after)
        assert stepped["bound"][len(before["bound"]) :] == [
            (after["tick"], d.decision_seq, d.disposition) for d in decided
        ]
        asked_total += len(receipts)
        applied_total += sum(1 for d in decided if d.disposition == "applied")
    # The run exercised what it holds: people asked and choices applied, then all replayed.
    assert asked_total and applied_total
    scope, _, society = routes(world)
    replayed = client.get(society + "/replay", headers=OWNER, params=scope)
    assert replayed.status_code == 200, replayed.text
    assert replayed.json()["replay_verified"] is True
