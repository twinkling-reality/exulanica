"""The page waits for an answer at least as long as the server may take to write one.

``answer_bound_seconds`` in ``exulanica/selection/question.py`` is the server's bound on one
answer's model calls: each call site of the answer path, as ``ANSWER_PATH_CALLS`` states it, times
what the client says one call to its role can take at worst. The page's deadline,
``ASK_TIMEOUT_MS`` in ``web/packages/app/src/companion-ask-api.ts``, must be at least that bound
plus the page's allowance for an ordinary read, ``PACKET_TIMEOUT_MS`` beside it. A deadline must
exist before the first request, so the page states it and this test holds it to the server's.

The other half is that ``ANSWER_PATH_CALLS`` is true: each call site is driven to its worst case
here, through the real functions over a scripted transport, and the roles and counts it sends must
be the ones stated.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from pathlib import Path

import pytest
from exulanica.api import services as services_module
from exulanica.models.client import ModelClient
from exulanica.models.errors import SchemaViolationError
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.transport import HttpResponse
from exulanica.selection.answer import Answer, AnswerClause, ClauseType
from exulanica.selection.embeddings import embed_query
from exulanica.selection.planner import propose_plan
from exulanica.selection.question import (
    ANSWER_PATH_CALLS,
    answer_bound_seconds,
    compose_answer,
)
from exulanica.selection.request_names import RequestNames

from model_fakes import FakeTransport, RecordingPolicy, chat_body
from test_selection_request_goldens import _packet

ASK_API = Path(__file__).resolve().parents[1] / "web/packages/app/src/companion-ask-api.ts"


def _milliseconds(name: str) -> int:
    found = re.search(rf"^const {name} = ([0-9_]+);$", ASK_API.read_text(), re.MULTILINE)
    assert found is not None, f"{ASK_API.name} states no {name}"
    return int(found.group(1).replace("_", ""))


def _api_client(responses=()) -> tuple[ModelClient, FakeTransport]:
    """A client configured as the API configures its own: the manifest's timeouts, one attempt."""
    transport = FakeTransport(list(responses))
    return ModelClient(
        api_key="test-key-not-real", transport=transport, policy=RecordingPolicy()
    ), transport


def test_the_api_builds_its_client_with_the_defaults_the_bound_is_read_from():
    """``build_services`` calls ``ModelClient()`` with no arguments: no set timeout, one try."""
    source = inspect.getsource(services_module.build_services)
    calls = [
        node
        for node in ast.walk(ast.parse(source.lstrip()))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ModelClient"
    ]
    assert calls, "build_services builds no ModelClient, so the bound reads the wrong client"
    assert all(not call.args and not call.keywords for call in calls)


def test_the_page_waits_at_least_the_answer_bound_and_its_read_allowance():
    client, _ = _api_client()
    bound_ms = answer_bound_seconds(client) * 1000
    assert bound_ms > 0
    assert _milliseconds("ASK_TIMEOUT_MS") >= bound_ms + _milliseconds("PACKET_TIMEOUT_MS")


def _roles_sent(transport: FakeTransport) -> list[Role]:
    manifest = load_manifest()
    by_model = {spec.model_id: role for role in Role for spec in manifest[role].chain}
    return [by_model[request["payload"]["model"]] for request in transport.requests]


def _reply(body) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(body))


def test_the_planner_sends_its_role_as_many_times_as_stated():
    refused = chat_body(json.dumps({"intent": "not an intent"}))
    client, transport = _api_client([_reply(refused)] * 5)
    with pytest.raises(SchemaViolationError):  # refused after its last repair
        propose_plan(client, "Which photographs show a boat?", (), names=RequestNames([]))
    assert (
        _roles_sent(transport)
        == [Role.STRUCTURED_EXTRACTION] * dict(ANSWER_PATH_CALLS)[Role.STRUCTURED_EXTRACTION]
    )


def test_the_composer_sends_its_role_as_many_times_as_stated():
    invented = Answer(
        clauses=[
            AnswerClause(
                text="This photograph was taken there.",
                type=ClauseType.HISTORICAL,
                citations=["ZZZZZZZZZZ"],
            )
        ]
    )
    client, transport = _api_client([_reply(chat_body(invented.model_dump_json()))] * 5)
    _, deterministic, _ = compose_answer(client, "Where was this?", _packet())
    assert deterministic, "the composer was not driven to its last repair"
    assert (
        _roles_sent(transport)
        == [Role.REASONING_CHEAP] * dict(ANSWER_PATH_CALLS)[Role.REASONING_CHEAP]
    )


def test_the_query_vector_is_one_embedding_request():
    body = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] + [0.0] * 4095}],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }
    client, transport = _api_client([_reply(body)])
    embed_query(client, "a boat in a harbour")
    assert _roles_sent(transport) == [Role.EMBEDDING] * dict(ANSWER_PATH_CALLS)[Role.EMBEDDING]


def test_every_role_the_answer_path_sends_is_counted_once():
    roles = [role for role, _ in ANSWER_PATH_CALLS]
    assert len(roles) == len(set(roles))
    assert set(roles) == {Role.STRUCTURED_EXTRACTION, Role.EMBEDDING, Role.REASONING_CHEAP}
