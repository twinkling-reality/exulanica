"""The vision boundary: the observation schema, and the vision role's use of the client.

Two measured facts drive most of this file:

*   ``response_format: {type: json_schema, strict: true}`` enforces a schema. A top-level
    ``guided_json`` parameter is **silently ignored** and returns prose with HTTP 200. A
    pipeline using it appears to work while enforcing nothing, so there is a test asserting
    that no request the vision stage sends can contain that key.
*   A reasoning model spends roughly 200 tokens before it writes anything, inline in
    ``message.content``, and it cannot be switched off. So there is a floor on ``max_tokens``,
    and the reader has to find the JSON object after the scratch work.

Scope: this file covers the vision stage. Generic client behaviour that is not vision specific
lives in ``tests/test_models_client.py`` and ``tests/test_models_cost.py`` and is not repeated
here.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest
from exulanica.ingest.vision import (
    OBSERVATION_SCHEMA,
    OBSERVATION_SCHEMA_NAME,
    Box,
    NebiusVisionModel,
    ObservationError,
    validate_observation,
)
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import (
    AmbiguousStructuredOutputError,
    ManifestError,
    MaxTokensTooLowError,
    SchemaViolationError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.schema import extract_json_object
from exulanica.models.transport import HttpResponse, HttpxTransport

from model_fakes import FakeTransport, chat_body, model_not_found

VALID = {
    "scene_description": "A waterfall in low winter light.",
    # Required from schema version 2 onward: people have their own field rather than being
    # filtered out of `objects`, which the model is told to keep them out of.
    "people": [],
    "objects": [{"label": "waterfall", "salience": "primary", "confidence": "high", "box": None}],
    "legible_text": [],
    "proposed_place": None,
}


# -- the schema -------------------------------------------------------------------------


def _walk(node: Any, path: str = "$") -> list[str]:
    problems: list[str] = []
    if isinstance(node, dict):
        types = node.get("type")
        types = types if isinstance(types, list) else [types]
        if "object" in types:
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false in strict mode")
            properties = set(node.get("properties", {}))
            required = set(node.get("required", []))
            if properties != required:
                problems.append(
                    f"{path}: strict mode requires every property: {properties ^ required}"
                )
        for key, value in node.items():
            problems.extend(_walk(value, f"{path}.{key}"))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            problems.extend(_walk(value, f"{path}[{index}]"))
    return problems


def test_the_observation_schema_is_legal_in_strict_mode():
    assert _walk(OBSERVATION_SCHEMA) == []


def test_the_schema_has_no_field_that_could_hold_a_person_name():
    """The system never proposes a real-world identity. There is nowhere to put one."""
    rendered = json.dumps(OBSERVATION_SCHEMA)
    assert "name" not in json.loads(rendered)["properties"]
    assert "identity" not in rendered and "who" not in rendered


def test_the_schema_asks_for_bands_not_percentages():
    text = json.dumps(OBSERVATION_SCHEMA)
    assert '"enum": ["low", "medium", "high"]' in text.replace("'", '"')
    assert "percentage" not in text or "Do not emit a percentage" in text


# -- validation -------------------------------------------------------------------------


def test_a_valid_payload_validates():
    assert validate_observation(VALID).scene_description.startswith("A waterfall")


@pytest.mark.parametrize(
    "mutation",
    [
        {"scene_description": ""},
        {"objects": [{"label": "x", "salience": "huge", "confidence": "high", "box": None}]},
        {"objects": [{"label": "x", "salience": "primary", "confidence": "0.9", "box": None}]},
        {"unexpected": "field"},
    ],
)
def test_an_invalid_payload_is_refused_rather_than_partially_accepted(mutation):
    with pytest.raises(ObservationError):
        validate_observation(VALID | mutation)


def test_prose_never_reaches_the_validator_as_a_partial_record():
    with pytest.raises(StructuredOutputError):
        extract_json_object("I had a look and it seems to be a waterfall, roughly.")


def test_a_box_outside_the_unit_square_is_clamped_and_says_so():
    clamped, changed = Box(x=0.9, y=0.1, w=0.4, h=0.2).clamped()
    assert changed is True
    assert clamped.x + clamped.w <= 1.0
    assert Box(x=0.0, y=0.0, w=0.0, h=0.5).is_degenerate


# -- the vision stage over the client ----------------------------------------------------


def _ok(content: str, **kwargs: Any) -> HttpResponse:
    """A 200 whose message.content is exactly ``content``."""
    return HttpResponse(status_code=200, text=json.dumps(chat_body(content, **kwargs)))


def _model(
    transport: FakeTransport, *, max_tokens: int | None = None, **client_kwargs: Any
) -> NebiusVisionModel:
    """The real vision stage over the real client over a scripted transport."""
    return NebiusVisionModel(
        ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            budget=BudgetGuard(ceiling_usd=Decimal("5.00"), max_calls=1000),
            **client_kwargs,
        ),
        max_tokens=max_tokens,
    )


def _observe(transport: FakeTransport, **kwargs: Any):
    return _model(transport, **kwargs).observe(image_bytes=b"\x89PNG", media_type="image/png")


def test_the_request_uses_json_schema_strict_and_can_never_carry_guided_json(transport):
    transport.default = _ok(json.dumps(VALID))
    _observe(transport)

    sent = transport.requests[0]["payload"]
    assert "guided_json" not in json.dumps(sent)
    assert sent["response_format"]["type"] == "json_schema"
    assert sent["response_format"]["json_schema"]["strict"] is True
    # The hand-written schema, sent verbatim. A generated one would carry $defs and anyOf.
    assert sent["response_format"]["json_schema"]["name"] == OBSERVATION_SCHEMA_NAME
    assert sent["response_format"]["json_schema"]["schema"] == OBSERVATION_SCHEMA


def test_the_photograph_is_sent_inline_and_never_as_a_fetchable_url(transport):
    """The corpus is private. A URL would mean publishing it somewhere the provider can reach."""
    transport.default = _ok(json.dumps(VALID))
    _observe(transport)

    parts = transport.requests[0]["payload"]["messages"][1]["content"]
    image = next(p for p in parts if p["type"] == "image_url")
    assert image["image_url"]["url"].startswith("data:image/png;base64,")


def test_max_tokens_has_a_floor_because_reasoning_tokens_cannot_be_switched_off(transport):
    """The exact bug that produced a false negative in this project's own verification harness."""
    floor = load_manifest()[Role.VISION].min_max_tokens
    transport.default = _ok(json.dumps(VALID))
    with pytest.raises(MaxTokensTooLowError, match="reasoning"):
        _observe(transport, max_tokens=floor - 1)
    assert transport.call_count == 0, "no money may be spent to discover a client-side error"


def test_the_default_max_tokens_clears_the_vision_chain_floor(transport):
    """The floor is the strictest in the chain, so a fallback cannot start truncating quietly."""
    transport.default = _ok(json.dumps(VALID))
    _observe(transport)
    assert transport.requests[0]["payload"]["max_tokens"] >= (
        load_manifest()[Role.VISION].min_max_tokens
    )


def test_the_json_object_is_found_after_untagged_inline_reasoning_text(transport):
    """runtime-verification.md section 5: the thinking appears in message.content, untagged."""
    preamble = "Let me think. The image shows water. I will now answer.\n"
    transport.default = _ok(preamble + json.dumps(VALID))
    result = _observe(transport)
    assert result.payload["scene_description"] == VALID["scene_description"]
    assert result.observation.scene_description == VALID["scene_description"]


def test_the_models_scratch_work_is_refused_rather_than_persisted_as_an_observation(transport):
    """The verified defect, at the boundary where it would have written a memory.

    Runtime measurement recorded Nemotron drafting an example object while reasoning about the
    schema, inline
    and untagged in ``message.content``, before writing its real answer. Taking the first object
    returned the draft; it satisfies the schema, so nothing downstream objected, and
    "PLACEHOLDER FROM MY SCRATCH WORK" was stored as what a photograph shows.

    There is no evidence in the body saying which object is the answer, so the stage fails.
    """
    decoy = VALID | {"scene_description": "PLACEHOLDER FROM MY SCRATCH WORK"}
    transport.default = _ok(
        "The user wants JSON matching the observation schema. A minimal example would be "
        + json.dumps(decoy)
        + ". But the photograph actually shows a waterfall, so my real answer is: "
        + json.dumps(VALID)
    )
    with pytest.raises(AmbiguousStructuredOutputError) as exc:
        _observe(transport)

    assert len(exc.value.candidates) == 2
    assert exc.value.candidates[0]["scene_description"] == "PLACEHOLDER FROM MY SCRATCH WORK"
    assert exc.value.candidates[1] == VALID


def test_a_reply_the_sent_schema_forbids_is_refused_even_though_pydantic_would_coerce_it(
    transport,
):
    """The schema is enforced locally, against the exact bytes the request carried.

    ``is_signage`` is declared boolean in ``OBSERVATION_SCHEMA``. Pydantic would coerce the
    string ``"true"`` to ``True`` and hand back a clean observation, so without the local check
    a server that ignored the schema would go unnoticed here. ``guided_json`` was measured being
    ignored on this platform; there is no reason to assume ``json_schema`` never will be.
    """
    coercible = VALID | {
        "legible_text": [
            {"text": "OPEN", "is_signage": "true", "confidence": "high", "box": None}
        ]
    }
    assert validate_observation(coercible).legible_text[0].is_signage is True

    transport.default = _ok(json.dumps(coercible))
    with pytest.raises(SchemaViolationError) as exc:
        _observe(transport)
    assert OBSERVATION_SCHEMA_NAME in str(exc.value)


def test_the_observation_payload_is_the_one_the_client_already_validated(transport):
    """The stage reads ``call.payload`` rather than parsing ``call.answer`` a second time."""
    transport.default = _ok("Thinking about the water.\n" + json.dumps(VALID))
    result = _observe(transport)
    assert result.payload == VALID


def test_a_brace_inside_a_transcribed_string_does_not_confuse_the_parser():
    """OCR text will eventually contain a brace. A naive brace counter mis-parses it."""
    payload = VALID | {"scene_description": "A sign reading {OPEN} today"}
    parsed = extract_json_object("thinking...\n" + json.dumps(payload))
    assert parsed["scene_description"] == "A sign reading {OPEN} today"


def test_a_truncated_response_is_refused_and_never_salvaged(transport):
    transport.default = _ok('{"scene_desc', finish_reason="length")
    with pytest.raises(TruncatedResponseError, match="max_tokens"):
        _observe(transport)


def test_a_rate_limit_is_retried_with_backoff_and_then_succeeds(transport):
    """The platform states plainly that it provides no automatic retry of its own."""
    slept: list[float] = []
    transport.responses = [
        HttpResponse(status_code=429, text='{"error":{"message":"slow down"}}'),
        HttpResponse(status_code=429, text='{"error":{"message":"slow down"}}'),
        _ok(json.dumps(VALID)),
    ]
    result = _observe(transport, max_attempts=3, sleep=slept.append)

    assert transport.call_count == 3
    assert result.attempts == 3
    # Exponential, and jittered rather than fixed: a corpus pass is one call per photograph and
    # synchronised retries are how a rate limit becomes an outage. The bases are 0.5s and 1.0s,
    # each multiplied by a jitter factor in [0.5, 1.0), so the two windows do not overlap and a
    # constant backoff cannot pass this by luck.
    assert len(slept) == 2
    assert 0.25 <= slept[0] < 0.5
    assert 0.5 <= slept[1] < 1.0


def test_a_refusal_the_endpoint_understood_is_not_retried(transport):
    """A 403 will be refused identically forever. Asking again is spend with no information."""
    transport.default = HttpResponse(status_code=403, text='{"error":{"message":"no"}}')
    with pytest.raises(TransportError, match="HTTP 403"):
        _observe(transport, max_attempts=3)
    assert transport.call_count == 1


def test_a_rate_limit_is_not_retried_when_retries_were_not_asked_for(transport):
    """Off by default: one request per call unless the caller opted in."""
    transport.default = HttpResponse(status_code=429, text='{"error":{"message":"slow down"}}')
    with pytest.raises(TransportError, match="HTTP 429"):
        _observe(transport)
    assert transport.call_count == 1


def test_a_withdrawn_primary_fails_over_to_the_declared_fallback(transport):
    """The deprecation path, exercised here rather than first executed in production."""
    binding = load_manifest()[Role.VISION]
    transport.by_model = {
        binding.primary.model_id: model_not_found(binding.primary.model_id),
        binding.fallback.model_id: _ok(json.dumps(VALID)),
    }
    result = _observe(transport)
    assert result.model_id == binding.fallback.model_id
    assert result.tried == (binding.primary.model_id, binding.fallback.model_id)
    assert result.attempts == 2


def test_a_schema_violation_is_not_retried_on_the_fallback_model(transport):
    """A withdrawal is the only thing a different model fixes, so it is the only fallback trigger.

    A primary that answered prose will answer prose again, and paying the dearer fallback to find
    that out is spend for no new information. It fails, loudly, after exactly one request.
    """
    transport.default = _ok("no JSON here, sorry")
    with pytest.raises(StructuredOutputError):
        _observe(transport)
    assert transport.call_count == 1


def test_a_connection_failure_is_typed_as_a_retryable_transport_error():
    """Every httpx failure mode collapses to one type: the caller's decision is the same."""

    class RefusingClient:
        def post(self, *args: Any, **kwargs: Any) -> Any:
            raise OSError("no route to host")

    with pytest.raises(TransportError, match="no route to host") as exc:
        HttpxTransport(client=RefusingClient()).post_json(
            "https://example.invalid/v1/chat/completions",
            headers={},
            payload={},
            timeout=1.0,
        )
    assert exc.value.retryable is True


def test_the_vision_model_reports_usage_and_the_model_that_actually_ran(transport):
    binding = load_manifest()[Role.VISION]
    transport.default = _ok(
        json.dumps(VALID), prompt_tokens=772, completion_tokens=210, reasoning_tokens=0
    )
    result = _observe(transport)

    assert result.cost["input_tokens"] == 772
    assert result.cost["output_tokens"] == 210
    expected = binding.primary.cost_usd(prompt_tokens=772, completion_tokens=210)
    assert Decimal(result.cost["usd_estimate"]) == expected.quantize(Decimal("0.00000001"))
    assert result.model_ref == {
        "provider": "nebius_token_factory",
        "model_id": binding.primary.model_id,
        "endpoint": load_manifest().base_url,
    }


def test_the_vision_stage_does_not_write_a_response_cache_entry(transport):
    """The prompt carries a per-request nonce, so no two requests digest the same.

    An entry per photograph that can never be read is disk spent on nothing, and worse, it is a
    cache that looks like it is working. Idempotency for ingest is the pipeline's, keyed by
    source hash plus stage version.
    """
    from exulanica.models.cache import InMemoryResponseCache

    cache = InMemoryResponseCache()
    transport.default = _ok(json.dumps(VALID))
    NebiusVisionModel(
        ModelClient(
            api_key="test-key-not-real",
            manifest=load_manifest(),
            transport=transport,
            cache=cache,
            budget=BudgetGuard(ceiling_usd=Decimal("5.00"), max_calls=1000),
        )
    ).observe(image_bytes=b"\x89PNG", media_type="image/png")
    assert len(cache) == 0


# -- the manifest, as the vision role sees it --------------------------------------------


def test_the_vision_price_is_an_exact_decimal_and_an_undeclared_id_is_an_error():
    manifest = load_manifest()
    spec = manifest[Role.VISION].primary
    assert spec.cost_usd(prompt_tokens=1_000_000, completion_tokens=0) == Decimal("0.3")
    assert manifest[Role.VISION].fallback.cost_usd(
        prompt_tokens=1_000_000, completion_tokens=0
    ) == Decimal("0.658")
    with pytest.raises(ManifestError, match="not declared"):
        manifest.spec("who/knows")
