"""Real provider adapter/ModelClient boundary with scripted transport, no live inference."""

import json

import pytest
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from exulanica.world.society_decisions import SocietyDecisionProvider
from exulanica.world.society_social import decision_context

from model_fakes import chat_body
from test_society_social import learned_state


def test_real_model_client_receives_only_bounded_agent_context_and_records_provenance(
    client, transport, manifest
):
    _, document, states, _ = learned_state()
    state = states[-1]
    receiver = state["social"]["cast_ids"][1]
    context = decision_context(state, document, receiver)
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
    adapter = SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64)
    result = adapter.propose(context)
    assert result["status"] == "accepted"
    assert result["provider"]["served_model_id"] == model
    assert result["provider"]["attempts"] == 1
    assert result["provider"]["prompt_tokens"] == 100
    assert result["provider"]["manifest_sha256"] == "a" * 64
    assert result["provider"]["cache_hit"] is False
    assert len(transport.requests) == 1
    payload = transport.requests[0]["payload"]
    assert payload["model"] == model
    assert payload["response_format"]["type"] == "json_schema"
    assert json.loads(payload["messages"][1]["content"]) == context
    assert "agents" not in json.loads(payload["messages"][1]["content"])


def test_provider_invalid_schema_is_a_recordable_rejection_not_canned_conversation(
    client, transport
):
    transport.responses.append(
        HttpResponse(
            status_code=200,
            text=json.dumps(
                chat_body(json.dumps({"kind": "conversation", "dialogue": "invented"}))
            ),
        )
    )
    result = SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64).propose(
        {"own_beliefs": []}
    )
    assert result == {
        "status": "rejected",
        "reason": "provider_schema_invalid",
        "proposal": None,
        "provider": None,
    }


def test_provider_transport_failure_and_context_limit_remain_explicit(client, transport):
    transport.responses.append(
        HttpResponse(status_code=503, text='{"error":{"message":"unavailable"}}')
    )
    adapter = SocietyDecisionProvider(client, Role.REASONING_CHEAP, "a" * 64)
    assert adapter.propose({"own_beliefs": []})["status"] == "unavailable"
    assert adapter.propose({"text": "x" * 65000})["reason"] == "context_limit_exceeded"
    assert len(transport.requests) == 1
    with pytest.raises(ValueError):
        SocietyDecisionProvider(client, Role.EMBEDDING, "a" * 64)
