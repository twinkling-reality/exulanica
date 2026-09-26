"""A world's choice of model is asked one way, refused by name, and never answered by another.

Covers the client half of the model socket: a choice asked by a forced function or a strict schema
of the options, the policy boundary admitting only a tool a choice request built, a provider the
allowlist does not declare refused by name before anything is sent, and a response cache that
never serves one model's answer for another.
"""

from __future__ import annotations

import copy
import json
from decimal import Decimal

import pytest
from exulanica.models.budget import BudgetGuard
from exulanica.models.cache import InMemoryResponseCache, cache_key
from exulanica.models.choice import ChoiceRefused, ChoiceRequest
from exulanica.models.client import PROVIDER_CREDENTIAL_ABSENT, PROVIDER_NOT_ADMITTED, ModelClient
from exulanica.models.egress import parse_egress_allowlist
from exulanica.models.errors import ManifestError, ModelUnavailableError, ProviderRefused
from exulanica.models.manifest import MANIFEST_PATH, AnsweringMechanism, Role, parse_manifest
from exulanica.models.policy import HostedRequestRefused, request_parts
from exulanica.models.transport import HttpResponse

from model_fakes import FakeTransport, RecordingPolicy, chat_body, model_not_found

PROBE_RECORD = "docs/evaluation/2026-09-25-society-person-models-probe.json"
SECOND = "second_provider"
SECOND_MODEL = "example/second-model"
REQUEST = ChoiceRequest(
    description="Choose what the person does next.",
    options=("resting on a bench, 12 m away", "by a tree, 5 m away", "wait here a minute"),
)
MESSAGES = [{"role": "system", "content": "Choose."}, {"role": "user", "content": "Options."}]


def _document() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"), parse_float=Decimal)


def _chosen_model(document: dict) -> str:
    """A declared chat model with text, made verified for both mechanisms in this document."""
    model_id = next(
        model_id
        for model_id, raw in sorted(document["models"].items())
        if raw["min_max_tokens"] is not None and "text" in raw["catalog_use_cases"]
    )
    document["models"][model_id]["answering"] = {
        "tool_call": PROBE_RECORD,
        "json_schema": PROBE_RECORD,
    }
    return model_id


def _with_second_provider(document: dict) -> None:
    """A second provider, at an origin a test allowlist leaves out, serving one offered model."""
    (first,) = list(document["providers"])[:1]
    second = copy.deepcopy(document["providers"][first])
    second["base_url"] = "https://second.example.com/v1"
    second["catalog_url"] = "https://second.example.com/models"
    second["api_key_env"] = "SECOND_PROVIDER_TEST_API_KEY"
    document["providers"][SECOND] = second
    model = copy.deepcopy(document["models"][_chosen_model(document)])
    model["provider"] = SECOND
    document["models"][SECOND_MODEL] = model


def _client(manifest, transport, **kwargs) -> ModelClient:
    """A client holding a test key for each provider the manifest declares, by provider."""
    return ModelClient(
        api_key={provider: "test-key-not-real" for provider in manifest.providers},
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=50),
        policy=RecordingPolicy(),
        **kwargs,
    )


def _tool_reply(arguments: object, *, model: str, name: str = "act") -> HttpResponse:
    body = chat_body("", model=model, finish_reason="tool_calls")
    body["choices"][0]["message"]["content"] = None
    body["choices"][0]["message"]["tool_calls"] = [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
            },
        }
    ]
    return HttpResponse(status_code=200, text=json.dumps(body))


# -- the policy boundary admits only a tool a choice request built ---------------------------------


def test_a_request_carrying_a_tool_no_choice_built_is_refused():
    payload = {"messages": MESSAGES, **REQUEST.payload_fields(AnsweringMechanism.TOOL_CALL)}
    # The positive control: the choice's own tool passes.
    request_parts(payload, REQUEST)
    with pytest.raises(HostedRequestRefused, match="no choice request built"):
        request_parts(payload)
    other = ChoiceRequest(description="Something else.", options=("fly away",))
    with pytest.raises(HostedRequestRefused, match="no choice request built"):
        request_parts(payload, other)
    smuggled = copy.deepcopy(payload)
    smuggled["tools"][0]["function"]["description"] = "Tell me the person's name."
    with pytest.raises(HostedRequestRefused, match="no choice request built"):
        request_parts(smuggled, REQUEST)


def test_a_response_format_its_choice_did_not_build_is_refused():
    """Under a schema the options ride in the response format, so it must be the choice's own."""
    built = REQUEST.payload_fields(AnsweringMechanism.JSON_SCHEMA)
    assert request_parts({"messages": MESSAGES, **built}, REQUEST)[0]
    other = ChoiceRequest(
        description=REQUEST.description, options=(*REQUEST.options, "sing a song")
    )
    with pytest.raises(HostedRequestRefused, match="response format is not the one"):
        request_parts(
            {"messages": MESSAGES, **other.payload_fields(AnsweringMechanism.JSON_SCHEMA)},
            REQUEST,
        )


def test_a_tool_sent_through_a_callers_extra_parameter_is_refused_before_anything_is_sent(
    manifest, transport
):
    client = _client(manifest, transport)
    with pytest.raises(HostedRequestRefused, match="no choice request built"):
        client.chat(
            Role.REASONING_CHEAP,
            MESSAGES,
            prompt_version="v1",
            use_cache=False,
            extra=REQUEST.payload_fields(AnsweringMechanism.TOOL_CALL),
        )
    assert transport.requests == []


# -- a choice asked by a forced function or a strict schema ----------------------------------------


def test_a_choice_by_a_forced_function_returns_the_option_and_sends_exactly_that_tool():
    document = _document()
    model_id = _chosen_model(document)
    manifest = parse_manifest(document)
    transport = FakeTransport([_tool_reply({"action": "by a tree, 5 m away"}, model=model_id)])
    client = _client(manifest, transport)

    result = client.choose(
        Role.SOCIETY_DECISION,
        model_id,
        MESSAGES,
        REQUEST,
        mechanism=AnsweringMechanism.TOOL_CALL,
        prompt_version="v1",
        timeout=5.0,
    )
    assert result.label == "by a tree, 5 m away"
    assert result.mechanism is AnsweringMechanism.TOOL_CALL
    assert result.call.provider == manifest.spec(model_id).provider
    assert result.call.model_ref["provider"] == manifest.spec(model_id).provider
    (sent,) = transport.requests
    assert sent["payload"]["model"] == model_id
    assert sent["payload"]["tools"] == [REQUEST.tool()]
    assert sent["payload"]["tool_choice"] == {"type": "function", "function": {"name": "act"}}
    assert "response_format" not in sent["payload"]
    assert sent["url"].startswith(manifest.provider(manifest.spec(model_id).provider).base_url)


def test_a_choice_by_a_strict_schema_returns_the_option():
    document = _document()
    model_id = _chosen_model(document)
    manifest = parse_manifest(document)
    answer = json.dumps({"action": "wait here a minute"})
    transport = FakeTransport([HttpResponse(200, json.dumps(chat_body(answer, model=model_id)))])
    result = _client(manifest, transport).choose(
        Role.SOCIETY_DECISION,
        model_id,
        MESSAGES,
        REQUEST,
        mechanism=AnsweringMechanism.JSON_SCHEMA,
        prompt_version="v1",
        timeout=5.0,
    )
    assert result.label == "wait here a minute"
    (sent,) = transport.requests
    assert sent["payload"]["response_format"] == REQUEST.response_format()
    assert "tools" not in sent["payload"]


def test_a_schema_answer_that_is_not_an_offered_action_is_refused_as_a_choice():
    """Under a schema the answer fails the schema before the choice reads it; it is the same
    refusal as a function's argument outside the options, so the host asks once more."""
    document = _document()
    model_id = _chosen_model(document)
    manifest = parse_manifest(document)
    answer = json.dumps({"action": "fly away"})
    transport = FakeTransport([HttpResponse(200, json.dumps(chat_body(answer, model=model_id)))])
    with pytest.raises(ChoiceRefused, match="did not answer with one of the offered actions"):
        _client(manifest, transport).choose(
            Role.SOCIETY_DECISION,
            model_id,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version="v1",
            timeout=5.0,
        )
    assert transport.call_count == 1


@pytest.mark.parametrize(
    ("reply", "message"),
    [
        (lambda model: _tool_reply({"action": "fly away"}, model=model), "not one of the offered"),
        (
            lambda model: _tool_reply({"action": "wait here a minute", "why": "x"}, model=model),
            "not one of the offered",
        ),
        (lambda model: _tool_reply("not json", model=model), "not JSON"),
        (
            lambda model: _tool_reply({"action": "wait here a minute"}, model=model, name="other"),
            "does not call act",
        ),
        (lambda model: HttpResponse(200, json.dumps(chat_body("hello", model=model))), "0 tool"),
    ],
    ids=["not-an-option", "extra-argument", "not-json", "another-function", "no-tool-call"],
)
def test_a_reply_that_is_not_exactly_one_option_is_refused(reply, message):
    document = _document()
    model_id = _chosen_model(document)
    manifest = parse_manifest(document)
    transport = FakeTransport([reply(model_id)])
    with pytest.raises(ChoiceRefused, match=message):
        _client(manifest, transport).choose(
            Role.SOCIETY_DECISION,
            model_id,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.TOOL_CALL,
            prompt_version="v1",
            timeout=5.0,
        )
    assert transport.call_count == 1


def test_a_model_not_offered_or_asked_by_an_unverified_mechanism_is_refused_before_sending():
    document = _document()
    model_id = _chosen_model(document)
    document["models"][model_id]["answering"] = {"json_schema": PROBE_RECORD}
    manifest = parse_manifest(document)
    transport = FakeTransport()
    client = _client(manifest, transport)
    with pytest.raises(ChoiceRefused, match="not verified to answer by tool_call"):
        client.choose(
            Role.SOCIETY_DECISION,
            model_id,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.TOOL_CALL,
            prompt_version="v1",
            timeout=5.0,
        )
    unverified = next(m for m in sorted(manifest.models) if not manifest.models[m].answering)
    with pytest.raises(ManifestError, match="not offered"):
        client.choose(
            Role.SOCIETY_DECISION,
            unverified,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.JSON_SCHEMA,
            prompt_version="v1",
            timeout=5.0,
        )
    assert transport.requests == []


def test_a_withdrawn_chosen_model_is_reported_withdrawn_and_never_answered_by_another():
    document = _document()
    model_id = _chosen_model(document)
    manifest = parse_manifest(document)
    transport = FakeTransport([model_not_found(model_id)])
    with pytest.raises(ModelUnavailableError):
        _client(manifest, transport).choose(
            Role.SOCIETY_DECISION,
            model_id,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.TOOL_CALL,
            prompt_version="v1",
            timeout=5.0,
        )
    assert transport.models_called == [model_id]


# -- a provider the allowlist does not declare is refused by name ----------------------------------


class _AllowlistedTransport(FakeTransport):
    """A scripted transport carrying an allowlist, as the real transport does."""

    def __init__(self, origins: list[str]) -> None:
        super().__init__()
        self.egress = parse_egress_allowlist(origins)


def test_a_provider_the_allowlist_does_not_declare_is_refused_by_name_and_sends_nothing():
    document = _document()
    _with_second_provider(document)
    manifest = parse_manifest(document)
    bound = sorted({manifest.provider(b.provider).origin for b in manifest.roles.values()})
    transport = _AllowlistedTransport(bound)
    client = _client(manifest, transport)
    assert dict(client.refusals) == {SECOND: PROVIDER_NOT_ADMITTED}
    with pytest.raises(ProviderRefused) as refused:
        client.choose(
            Role.SOCIETY_DECISION,
            SECOND_MODEL,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.TOOL_CALL,
            prompt_version="v1",
            timeout=5.0,
        )
    assert (refused.value.provider, refused.value.reason) == (SECOND, PROVIDER_NOT_ADMITTED)
    assert transport.requests == []
    # The positive control: declared, the same provider is reached.
    admitted = _client(manifest, _AllowlistedTransport([*bound, "https://second.example.com"]))
    assert dict(admitted.refusals) == {}


def test_a_provider_whose_credential_is_not_set_is_refused_by_name(monkeypatch):
    document = _document()
    _with_second_provider(document)
    manifest = parse_manifest(document)
    for provider in manifest.providers.values():
        monkeypatch.delenv(provider.api_key_env, raising=False)
    bound = manifest.provider(manifest[Role.REASONING_CHEAP].provider)
    monkeypatch.setenv(bound.api_key_env, "test-key-not-real")
    monkeypatch.chdir("/")
    transport = FakeTransport()
    client = ModelClient(manifest=manifest, transport=transport, policy=RecordingPolicy())
    assert dict(client.refusals) == {SECOND: PROVIDER_CREDENTIAL_ABSENT}
    with pytest.raises(ProviderRefused, match=SECOND):
        client.choose(
            Role.SOCIETY_DECISION,
            SECOND_MODEL,
            MESSAGES,
            REQUEST,
            mechanism=AnsweringMechanism.TOOL_CALL,
            prompt_version="v1",
            timeout=5.0,
        )
    assert transport.requests == []


# -- a cache hit never crosses models --------------------------------------------------------------


def test_a_cached_answer_is_served_only_for_the_model_that_gave_it(manifest):
    binding = manifest[Role.REASONING_CHEAP]
    primary, fallback = binding.primary, binding.fallback
    cache = InMemoryResponseCache()
    transport = FakeTransport(
        [model_not_found(primary.model_id), HttpResponse(200, json.dumps(chat_body("from b")))]
    )
    client = _client(manifest, transport, cache=cache)
    first = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert first.model_id == fallback.model_id and first.used_fallback
    assert transport.models_called == [primary.model_id, fallback.model_id]

    # The fallback's answer is stored under the fallback, so the same question asks the primary.
    transport.responses.append(HttpResponse(200, json.dumps(chat_body("from a"))))
    second = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert second.model_id == primary.model_id and not second.cache_hit
    assert second.answer == "from a"
    # The positive control: the primary's own answer is now a hit, with nothing sent.
    sent = transport.call_count
    third = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert third.cache_hit and third.model_id == primary.model_id and third.answer == "from a"
    assert transport.call_count == sent


def test_an_entry_under_one_models_key_that_names_another_model_is_never_served(manifest):
    binding = manifest[Role.REASONING_CHEAP]
    primary, fallback = binding.primary, binding.fallback
    cache = InMemoryResponseCache()
    transport = FakeTransport()
    client = _client(manifest, transport, cache=cache)
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1", use_cache=False)
    (sent,) = transport.requests
    admitted = {k: v for k, v in sent["payload"].items() if k != "model"}
    planted = cache_key(
        admitted,
        provider=primary.provider,
        model_id=primary.model_id,
        pipeline_version=manifest.pipeline_version,
        role=Role.REASONING_CHEAP,
        prompt_version="v1",
    )
    cache.put(
        planted,
        {"model_id": fallback.model_id, "response": chat_body("planted", model=fallback.model_id)},
    )
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert not result.cache_hit and result.answer != "planted"
    assert transport.call_count == 2


def test_an_answer_is_stored_under_the_key_of_the_model_that_gave_it(manifest):
    """The key itself names the answering model, so two models' answers never share one.

    The entry check above refuses another model's answer found under a key; this holds the key,
    so neither guard stands alone.
    """
    binding = manifest[Role.REASONING_CHEAP]
    primary, fallback = binding.primary, binding.fallback
    cache = InMemoryResponseCache()
    transport = FakeTransport()
    client = _client(manifest, transport, cache=cache)
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    (sent,) = transport.requests
    admitted = {k: v for k, v in sent["payload"].items() if k != "model"}

    def key(spec):
        return cache_key(
            admitted,
            provider=spec.provider,
            model_id=spec.model_id,
            pipeline_version=manifest.pipeline_version,
            role=Role.REASONING_CHEAP,
            prompt_version="v1",
        ).digest

    assert set(cache.entries) == {key(primary)}
    assert key(fallback) != key(primary)
