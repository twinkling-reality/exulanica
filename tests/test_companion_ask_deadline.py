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
import dataclasses
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
    SOCIETY_ANSWER_PATH_CALLS,
    answer_bound_seconds,
    compose_answer,
    society_answer_bound_seconds,
)
from exulanica.selection.request_names import RequestNames
from exulanica.selection.society_question import composer_wait_seconds

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


def _sent(transport: FakeTransport) -> list[str]:
    """The model each request was sent to. Two roles may share a model, so a test names the role
    it expects and compares with that role's primary rather than reading a role back."""
    return [request["payload"]["model"] for request in transport.requests]


def _to(role: Role, count: int) -> list[str]:
    return [load_manifest()[role].primary.model_id] * count


def _reply(body) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(body))


def test_the_planner_sends_its_role_as_many_times_as_stated():
    refused = chat_body(json.dumps({"intent": "not an intent"}))
    client, transport = _api_client([_reply(refused)] * 5)
    with pytest.raises(SchemaViolationError):  # refused after its last repair
        propose_plan(client, "Which photographs show a boat?", (), names=RequestNames([]))
    assert _sent(transport) == _to(
        Role.STRUCTURED_EXTRACTION, dict(ANSWER_PATH_CALLS)[Role.STRUCTURED_EXTRACTION]
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
    assert _sent(transport) == _to(
        Role.REASONING_CHEAP, dict(ANSWER_PATH_CALLS)[Role.REASONING_CHEAP]
    )


def test_the_query_vector_is_one_embedding_request():
    body = {
        "object": "list",
        "data": [{"object": "embedding", "index": 0, "embedding": [1.0] + [0.0] * 4095}],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }
    client, transport = _api_client([_reply(body)])
    embed_query(client, "a boat in a harbour")
    assert _sent(transport) == _to(Role.EMBEDDING, dict(ANSWER_PATH_CALLS)[Role.EMBEDDING])


def test_every_role_the_answer_path_sends_is_counted_once():
    roles = [role for role, _ in ANSWER_PATH_CALLS]
    assert len(roles) == len(set(roles))
    assert set(roles) == {Role.STRUCTURED_EXTRACTION, Role.EMBEDDING, Role.REASONING_CHEAP}
    society = [role for role, _ in SOCIETY_ANSWER_PATH_CALLS]
    assert len(society) == len(set(society))
    assert set(society) == {Role.STRUCTURED_EXTRACTION, Role.ANSWER_COMPOSER}
    # The same planner asks either way, so it is counted the same on both paths.
    planner = Role.STRUCTURED_EXTRACTION
    assert dict(SOCIETY_ANSWER_PATH_CALLS)[planner] == dict(ANSWER_PATH_CALLS)[planner]


def test_the_society_composer_sends_its_role_as_many_times_as_stated():
    from exulanica.selection.calls import CallLog
    from exulanica.selection.society_question import SocietyLineChoice, compose_society_answer

    from test_society_question import _happened_packet

    unknown = SocietyLineChoice(lines=["ZZZZZZZZZZ"])
    client, transport = _api_client([_reply(chat_body(unknown.model_dump_json()))] * 5)
    attempts = dict(SOCIETY_ANSWER_PATH_CALLS)[Role.ANSWER_COMPOSER]
    chosen = compose_society_answer(
        client,
        "What happened in the square?",
        _happened_packet(),
        log=CallLog(),
        saved=(),
        max_tokens=1000,
        # The deadline held open, so a refused choice is asked for again.
        clock=lambda: 0.0,
    )
    assert chosen.rejections, "the composer's choice was not refused, so nothing drove a repair"
    assert _sent(transport) == _to(Role.ANSWER_COMPOSER, attempts)


def _with_timeouts(manifest, **seconds):
    roles = dict(manifest.roles)
    for name, timeout in seconds.items():
        role = Role(name)
        roles[role] = dataclasses.replace(roles[role], timeout_seconds=timeout)
    return dataclasses.replace(manifest, roles=roles)


def _client_for(manifest) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=manifest,
        transport=FakeTransport(),
        policy=RecordingPolicy(),
    )


def test_the_society_path_is_its_required_calls_and_the_composer_s_deadline():
    """The composer's calls share one deadline, so the society path is the planner's worst case
    and that deadline, whatever the composer role's timeout: a longer timeout does not move it."""
    manifest = load_manifest()
    for held in (manifest, _with_timeouts(manifest, answer_composer=1000)):
        client = _client_for(held)
        planner = dict(SOCIETY_ANSWER_PATH_CALLS)[Role.STRUCTURED_EXTRACTION]
        assert society_answer_bound_seconds(client) == (
            planner * client.worst_case_seconds(Role.STRUCTURED_EXTRACTION)
            + composer_wait_seconds(held)
        )
        assert society_answer_bound_seconds(client) < (
            planner * client.worst_case_seconds(Role.STRUCTURED_EXTRACTION)
            + client.worst_case_seconds(Role.ANSWER_COMPOSER)
        )


def test_the_bound_is_the_longer_path_and_the_society_path_is_inside_it():
    """Each path's sum is inside the bound, and the bound is one of them, not their total: with
    the photograph composer and the query vector made quick, the society path is the bound."""
    manifest = load_manifest()
    for held in (manifest, _with_timeouts(manifest, reasoning_cheap=1, embedding=1)):
        client = _client_for(held)
        paths = [
            sum(count * client.worst_case_seconds(role) for role, count in ANSWER_PATH_CALLS),
            society_answer_bound_seconds(client),
        ]
        assert answer_bound_seconds(client) == max(paths)
    assert paths[1] > paths[0], "the positive control: the society path is the longer one"
