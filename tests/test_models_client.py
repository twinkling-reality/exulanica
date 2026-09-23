"""Client behaviour: routing, fallback, the max_tokens floor, structured output, vision.

Every test here drives the real client through a scripted transport. Nothing reaches the network
and nothing spends credits.
"""

from __future__ import annotations

import json
import uuid

import pytest
from exulanica.models.client import ModelClient
from exulanica.models.errors import (
    AmbiguousStructuredOutputError,
    GuidedJsonForbiddenError,
    MaxTokensTooLowError,
    NoFallbackError,
    SchemaViolationError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.models.manifest import Role
from exulanica.models.messages import image_part
from exulanica.models.reasoning import split_reasoning
from exulanica.models.transport import HttpResponse
from pydantic import BaseModel, model_validator

from model_fakes import chat_body, model_not_found

MESSAGES = [{"role": "user", "content": "how many photographs are in this album"}]


def ok(body) -> HttpResponse:
    return HttpResponse(status_code=200, text=json.dumps(body))


# -- routing -------------------------------------------------------------------------------


def test_routing_sends_the_role_primary(client, manifest, transport):
    transport.default = ok(chat_body("seven"))
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")

    assert transport.models_called == [manifest[Role.REASONING_CHEAP].primary.model_id]
    assert result.model_id == manifest[Role.REASONING_CHEAP].primary.model_id
    assert result.used_fallback is False
    assert result.answer == "seven"


def test_each_role_routes_to_its_own_primary(client, manifest, transport):
    transport.default = ok(chat_body("x"))
    for role in (Role.REASONING_CHEAP, Role.REASONING_MID, Role.REASONING_HARD, Role.VISION):
        transport.requests.clear()
        client.chat(role, MESSAGES, prompt_version="v1", use_cache=False)
        assert transport.models_called == [manifest[role].primary.model_id]


def test_a_call_site_cannot_name_a_model(client):
    """There is no model parameter. Passing one through ``extra`` is overwritten by the chain."""
    with pytest.raises(TypeError):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1", model="whatever")


# -- fallback ------------------------------------------------------------------------------


def test_fallback_is_selected_on_404(client, manifest, transport):
    """The deprecation path, exercised here rather than first executed in production."""
    binding = manifest[Role.REASONING_CHEAP]
    transport.by_model = {
        binding.primary.model_id: model_not_found(binding.primary.model_id),
        binding.fallback.model_id: ok(chat_body("answered by the fallback")),
    }

    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")

    assert transport.models_called == [binding.primary.model_id, binding.fallback.model_id]
    assert result.model_id == binding.fallback.model_id
    assert result.used_fallback is True
    assert result.answer == "answered by the fallback"
    assert result.usage.used_fallback is True


def test_fallback_also_fires_on_a_400_that_says_the_model_is_gone(client, manifest, transport):
    """Not every withdrawal answers 404. The message is classified too."""
    binding = manifest[Role.VISION]
    transport.by_model = {
        binding.primary.model_id: model_not_found(binding.primary.model_id, status=400),
        binding.fallback.model_id: ok(chat_body("fallback saw it")),
    }
    result = client.chat(Role.VISION, MESSAGES, prompt_version="v1")
    assert result.model_id == binding.fallback.model_id


def test_a_500_does_not_trigger_a_fallback(client, manifest, transport):
    """A server error is the same model having a bad moment.

    Swapping models would hide a platform incident behind a quality regression that nobody
    would ever attribute correctly.
    """
    binding = manifest[Role.REASONING_CHEAP]
    transport.by_model = {
        binding.primary.model_id: HttpResponse(
            status_code=500, text='{"error":{"message":"upstream"}}'
        ),
        binding.fallback.model_id: ok(chat_body("should never be reached")),
    }
    with pytest.raises(TransportError, match="HTTP 500"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert transport.models_called == [binding.primary.model_id]


def test_a_429_does_not_trigger_a_fallback(client, manifest, transport):
    binding = manifest[Role.REASONING_CHEAP]
    transport.by_model = {
        binding.primary.model_id: HttpResponse(
            status_code=429, text='{"error":{"message":"slow down"}}'
        ),
    }
    with pytest.raises(TransportError, match="HTTP 429"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert transport.call_count == 1


def test_both_models_gone_raises_and_points_at_the_preflight(client, manifest, transport):
    binding = manifest[Role.REASONING_CHEAP]
    transport.by_model = {
        binding.primary.model_id: model_not_found(binding.primary.model_id),
        binding.fallback.model_id: model_not_found(binding.fallback.model_id),
    }
    with pytest.raises(NoFallbackError, match="preflight"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")


def test_embedding_role_refuses_to_substitute_a_different_model(client, manifest, transport):
    """A vector from another model is not a worse vector, it is a vector in a different space."""
    primary = manifest[Role.EMBEDDING].primary
    transport.by_model = {primary.model_id: model_not_found(primary.model_id)}
    with pytest.raises(NoFallbackError, match="no declared fallback"):
        client.embed(["a caption"])
    assert transport.call_count == 1


# -- the max_tokens floor --------------------------------------------------------------------


def test_max_tokens_below_the_floor_is_refused_before_any_request(client, manifest, transport):
    """The exact bug that produced a false negative in this project's own verification harness."""
    floor = manifest[Role.REASONING_CHEAP].min_max_tokens
    with pytest.raises(MaxTokensTooLowError) as exc:
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1", max_tokens=200)

    assert str(floor) in str(exc.value)
    assert "reasoning" in str(exc.value)
    assert transport.call_count == 0, "no money may be spent to discover a client-side error"


def test_max_tokens_at_the_floor_is_accepted(client, manifest, transport):
    transport.default = ok(chat_body("fine"))
    floor = manifest[Role.REASONING_CHEAP].min_max_tokens
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1", max_tokens=floor)
    assert transport.requests[0]["payload"]["max_tokens"] == floor


def test_default_max_tokens_clears_the_floor(client, manifest, transport):
    transport.default = ok(chat_body("fine"))
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    sent = transport.requests[0]["payload"]["max_tokens"]
    assert sent >= manifest[Role.REASONING_CHEAP].min_max_tokens


def test_truncation_with_no_answer_is_reported_as_a_parameter_bug(client, transport):
    transport.default = ok(
        chat_body("", finish_reason="length", completion_tokens=640, reasoning_tokens=640)
    )
    with pytest.raises(TruncatedResponseError, match="max_tokens"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")


def test_a_truncated_answer_is_never_salvaged(client, transport):
    transport.default = ok(chat_body('{"partial": "half a fac', finish_reason="length"))
    with pytest.raises(TruncatedResponseError):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")


def test_a_thought_that_never_closed_is_refused_even_when_the_provider_says_it_stopped(
    client, transport
):
    """An unterminated open tag means the limit landed mid-thought, so there is no answer at all.

    This is the case ``SplitContent.complete`` was written for and the case ``finish_reason``
    cannot see. The provider says ``stop``: as far as the endpoint is concerned the model
    finished normally. The content ends inside an open ``<think>``, so everything after the tag
    is scratch work and everything before it is a preamble. Returning that preamble as the
    answer is a caller inventing a fact out of throat clearing.
    """
    transport.default = ok(chat_body("Working through it. <think>the album has se"))
    with pytest.raises(TruncatedResponseError, match="never closed"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")


def test_a_thought_that_never_closed_and_left_nothing_behind_is_refused_too(client, transport):
    """The same body without the preamble, which would otherwise return an empty answer.

    Silently, and with ``finish_reason: "stop"`` to say nothing went wrong. An empty answer that
    a caller has to notice is a worse failure than a refusal it cannot miss.
    """
    transport.default = ok(chat_body("<think>the album has se"))
    with pytest.raises(TruncatedResponseError, match="never closed"):
        client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")


def test_a_thought_that_closed_properly_is_not_refused(client, transport):
    """The other side of the rule, so the refusal above cannot widen into every inline block.

    A closed block is the ordinary inline shape. The answer is the text outside it and the
    scratch work is kept but never returned as the answer.
    """
    transport.default = ok(chat_body("<think>counting them</think>seven"))
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert result.answer == "seven"
    assert result.reasoning == "counting them"


# -- guided_json is unreachable ----------------------------------------------------------------


def test_guided_json_is_refused(client, transport):
    with pytest.raises(GuidedJsonForbiddenError, match="silently ignored"):
        client.chat(
            Role.REASONING_CHEAP,
            MESSAGES,
            prompt_version="v1",
            extra={"guided_json": {"type": "object"}},
        )
    assert transport.call_count == 0


def test_guided_json_nested_in_extra_body_is_refused(client, transport):
    with pytest.raises(GuidedJsonForbiddenError):
        client.chat(
            Role.REASONING_CHEAP,
            MESSAGES,
            prompt_version="v1",
            extra={"extra_body": {"guided_json": {"type": "object"}}},
        )
    assert transport.call_count == 0


def test_json_object_response_format_is_refused(client, transport):
    """Valid JSON of an arbitrary shape is not a schema, and canonical state needs a schema."""
    with pytest.raises(GuidedJsonForbiddenError, match="json_object"):
        client.chat(
            Role.REASONING_CHEAP,
            MESSAGES,
            prompt_version="v1",
            response_format={"type": "json_object"},
        )
    assert transport.call_count == 0


def test_non_strict_json_schema_is_refused(client, transport):
    with pytest.raises(GuidedJsonForbiddenError):
        client.chat(
            Role.REASONING_CHEAP,
            MESSAGES,
            prompt_version="v1",
            response_format={"type": "json_schema", "json_schema": {"name": "x", "schema": {}}},
        )


# -- structured output ---------------------------------------------------------------------


class Sighting(BaseModel):
    subject: str
    count: int
    caption: str | None


def test_structured_output_returns_a_validated_instance(client, transport):
    transport.default = ok(
        chat_body('{"subject": "waterfall", "count": 2, "caption": null}')
    )
    result = client.structured(
        Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="extract-v3"
    )

    assert isinstance(result.value, Sighting)
    assert result.value.subject == "waterfall"
    assert result.value.count == 2
    assert result.value.caption is None


def test_structured_output_sends_strict_json_schema(client, transport):
    transport.default = ok(chat_body('{"subject": "a", "count": 1, "caption": null}'))
    client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")

    fmt = transport.requests[0]["payload"]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    schema = fmt["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == ["caption", "count", "subject"]
    assert "guided_json" not in json.dumps(transport.requests[0]["payload"])


def test_structured_output_rejects_a_body_that_does_not_validate(client, transport):
    transport.default = ok(chat_body('{"subject": "waterfall", "count": "two"}'))
    with pytest.raises(StructuredOutputError):
        client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")


class Tally(BaseModel):
    """Two rules the JSON Schema sent to the endpoint cannot carry, as ``SelectionPlan`` has."""

    kind: str
    note: str | None
    subjects: list[uuid.UUID]
    total: int

    @model_validator(mode="after")
    def _a_tally_carries_no_note(self) -> Tally:
        if self.kind == "tally" and self.note is not None:
            raise ValueError("a tally carries no note")
        return self


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (
            {"kind": "tally", "note": "n" * 400, "subjects": [], "total": 3},
            "<root>: Value error, a tally carries no note",
        ),
        (
            {"kind": "count", "note": "n" * 400, "subjects": ["not-an-id"], "total": 3},
            "subjects/0: Input should be a valid UUID",
        ),
    ],
)
def test_a_refusal_names_the_rule_and_quotes_the_answer_past_it(client, transport, answer, reason):
    """The endpoint enforces the JSON Schema. A model validator and a string format run only here.

    Measured on the Companion's planner: an answer passed the JSON Schema check and a model
    validator refused it, and the refusal kept a count of errors and the first 300 characters of
    a pretty-printed answer, which stopped before the refused field. The planner sends that
    refusal back to the model as its one repair, so the repair could not say what to fix.
    """
    transport.default = ok(chat_body(json.dumps(answer, indent=2)))
    with pytest.raises(StructuredOutputError) as refused:
        client.structured(Role.REASONING_CHEAP, MESSAGES, Tally, prompt_version="v1")
    message = str(refused.value)
    assert reason in message, message
    # The quoted answer reaches the field after the long one, 400 characters in.
    assert '"total": 3' in message, message


def test_structured_output_rejects_prose(client, transport):
    """What ``guided_json`` returns: HTTP 200 and a perfectly friendly sentence."""
    transport.default = ok(chat_body("I found two shapes in the photograph."))
    with pytest.raises(StructuredOutputError, match="not JSON"):
        client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")


def test_structured_output_survives_inline_reasoning(client, transport):
    """Scratch work wrapped around the JSON must not defeat validation."""
    transport.default = ok(
        chat_body(
            '<think>Counting the shapes now.</think>'
            '{"subject":"bar","count":1,"caption":null}'
        )
    )
    result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    assert result.value.count == 1
    assert result.call.reasoning == "Counting the shapes now."


def test_structured_output_survives_untagged_inline_reasoning(client, transport):
    """runtime-verification.md section 5: the thinking appears in content with no tag around it.

    Nothing strips it, because there is nothing to strip it by. ``json.loads`` over the whole
    body fails on exactly the models this project runs, so the object is found by a balanced-brace
    scan that respects string literals.
    """
    transport.default = ok(
        chat_body(
            "Let me count the shapes. There is one bar. I will answer now.\n"
            '{"subject":"bar","count":1,"caption":null}'
        )
    )
    result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    assert result.value.count == 1
    assert result.value.subject == "bar"


def test_a_brace_in_a_transcribed_string_does_not_defeat_the_scan(client, transport):
    """Transcribed signage will eventually contain a brace. A naive counter mis-parses it."""
    transport.default = ok(
        chat_body(
            "Thinking about the sign.\n"
            '{"subject":"sign","count":1,"caption":"reads {OPEN} today"}'
        )
    )
    result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    assert result.value.caption == "reads {OPEN} today"


# -- reasoning separation ---------------------------------------------------------------------


def test_reasoning_content_field_is_separated_from_the_answer(client, transport):
    transport.default = ok(
        chat_body("ORIMERA", reasoning_content="1. Analyse. 2. Output the word.")
    )
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert result.answer == "ORIMERA"
    assert result.reasoning == "1. Analyse. 2. Output the word."


def test_inline_think_block_is_stripped():
    split = split_reasoning("<think>weighing it up</think>The answer is seven.")
    assert split.answer == "The answer is seven."
    assert split.reasoning == "weighing it up"
    assert split.inline is True
    assert split.complete is True


def test_unterminated_think_block_is_not_an_answer():
    """Truncated mid-thought. There is no answer in this response, only a partial thought."""
    split = split_reasoning("<think>still weighing it u")
    assert split.empty_answer
    assert split.complete is False


def test_reasoning_is_never_mistaken_for_the_answer(client, transport):
    transport.default = ok(chat_body("<think>The user wants a count.</think>"))
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert result.answer == ""
    assert result.reasoning == "The user wants a count."


# -- vision --------------------------------------------------------------------------------


def test_vision_builds_an_image_url_content_part(client, manifest, transport):
    transport.default = ok(chat_body("a waterfall in winter"))
    result = client.vision(
        [b"\x89PNG-not-really"], "describe this", prompt_version="v1", media_type="image/png"
    )

    payload = transport.requests[0]["payload"]
    assert payload["model"] == manifest[Role.VISION].primary.model_id
    parts = payload["messages"][0]["content"]
    assert parts[0]["type"] == "image_url"
    assert parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert parts[1] == {"type": "text", "text": "describe this"}
    assert result.answer == "a waterfall in winter"


def test_single_photograph_needs_no_wrapping(client, transport):
    """Most users upload one or two photographs, so this is the primary path, not a fallback."""
    transport.default = ok(chat_body("one photo"))
    result = client.vision([b"bytes"], "what is here", prompt_version="v1")
    assert result.answer == "one photo"


def test_vision_can_return_structured_output(client, transport):
    transport.default = ok(chat_body('{"subject":"waterfall","count":1,"caption":"winter"}'))
    result = client.vision(
        [b"bytes"], "extract", prompt_version="v1", schema=Sighting
    )
    assert result.value.subject == "waterfall"


def test_image_part_accepts_a_url_unchanged():
    part = image_part("https://example.invalid/photo.jpg")
    assert part["image_url"]["url"] == "https://example.invalid/photo.jpg"


# -- credential hygiene -----------------------------------------------------------------------


def test_the_key_is_sent_as_a_bearer_header_and_never_appears_in_repr(client, transport):
    transport.default = ok(chat_body("x"))
    client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert transport.requests[0]["headers"]["Authorization"] == "Bearer test-key-not-real"
    assert "test-key-not-real" not in repr(client)


def test_the_key_never_reaches_the_cache(manifest, transport):
    from exulanica.models.cache import InMemoryResponseCache

    cache = InMemoryResponseCache()
    transport.default = ok(chat_body("x"))
    ModelClient(
        api_key="super-secret", manifest=manifest, transport=transport, cache=cache
    ).chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert "super-secret" not in json.dumps(cache.entries)


# -- the answer, not the scratch work ---------------------------------------------------------
#
# runtime-verification.md section 5: the reasoning models write their thinking inline in
# ``message.content`` and it cannot be switched off. The extractor used to take the first
# balanced object it found, so a draft object written while thinking about the schema was
# returned as the answer, validated cleanly, and persisted as an assertion. Every test in this
# block puts a real second object in the reasoning text, because a preamble with no braces in it
# proves nothing.


DECOY_THEN_ANSWER = (
    "The user wants JSON. Recalling the schema, a minimal example would be "
    '{"subject": "PLACEHOLDER FROM MY SCRATCH WORK", "count": 0, "caption": null}. '
    "But actually the photograph shows a waterfall, so my real answer is: "
    '{"subject": "waterfall", "count": 2, "caption": null}'
)


def test_structured_output_refuses_a_body_carrying_the_models_scratch_work(client, transport):
    """The measured defect: this used to return the placeholder, and it is schema-valid."""
    transport.default = ok(chat_body(DECOY_THEN_ANSWER))
    with pytest.raises(AmbiguousStructuredOutputError) as exc:
        client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")

    assert len(exc.value.candidates) == 2
    assert "PLACEHOLDER" not in json.dumps(exc.value.candidates[1])
    assert "PLACEHOLDER" in str(exc.value)


def test_the_placeholder_never_becomes_a_value(client, transport):
    """Stated as the invariant rather than as the mechanism, so a future heuristic cannot pass.

    Any implementation that returns a value here has chosen one of two objects on positional
    evidence alone. There is none in the body.
    """
    transport.default = ok(chat_body(DECOY_THEN_ANSWER))
    try:
        result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    except StructuredOutputError:
        return
    pytest.fail(f"a value was invented from an ambiguous body: {result.value!r}")


def test_a_decoy_written_after_the_answer_is_refused_too(client, transport):
    """"Take the last object" fixes the archived probe and breaks this one. Both are guesses."""
    transport.default = ok(
        chat_body(
            '{"subject": "waterfall", "count": 2, "caption": null}\n'
            "Wait, let me check the schema shape once more: something like "
            '{"subject": "EXAMPLE", "count": 0, "caption": null} is what it wants.'
        )
    )
    with pytest.raises(AmbiguousStructuredOutputError):
        client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")


def test_a_decoy_inside_a_delimited_think_block_is_stripped_and_the_answer_survives(
    client, transport
):
    """The refusal must not be over-broad. A tag is a reliable boundary and is used as one."""
    transport.default = ok(
        chat_body(
            "<think>An example would be "
            '{"subject": "PLACEHOLDER FROM MY SCRATCH WORK", "count": 0, "caption": null}'
            "</think>"
            '{"subject": "waterfall", "count": 2, "caption": null}'
        )
    )
    result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    assert result.value.subject == "waterfall"
    assert "PLACEHOLDER" in (result.call.reasoning or "")


def test_a_restated_identical_object_is_not_ambiguous(client, transport):
    obj = '{"subject": "waterfall", "count": 2, "caption": null}'
    transport.default = ok(chat_body(f"My answer is {obj}. To be explicit: {obj}"))
    result = client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")
    assert result.value.count == 2


# -- validating against the schema that was sent -----------------------------------------------
#
# ``response_format {json_schema, strict}`` is a request for enforcement, not evidence of it.
# ``guided_json`` was measured on this same platform being accepted, ignored, and answered with
# HTTP 200 and prose. A json_schema the endpoint quietly stopped honouring looks identical from
# the outside. So the reply is validated locally against the byte-identical schema that was sent.


HAND_WRITTEN_SCHEMA = {
    "type": "object",
    "properties": {"required_field": {"type": "string"}},
    "required": ["required_field"],
    "additionalProperties": False,
}


def hand_written_format():
    from exulanica.models.schema import response_format_for_schema

    return response_format_for_schema(HAND_WRITTEN_SCHEMA, "hand_written_v1")


def test_chat_refuses_an_unrelated_object_for_a_hand_written_schema(client, transport):
    """The caller that inherited unvalidated data.

    ``chat`` with a hand-written schema is how the vision path runs. Before this, a server
    answering ``{"totally": "unrelated"}`` for a schema requiring ``required_field`` was
    returned to the caller as a successful result.
    """
    transport.default = ok(chat_body('{"totally": "unrelated"}'))
    with pytest.raises(SchemaViolationError) as exc:
        client.chat(
            Role.VISION,
            MESSAGES,
            prompt_version="v1",
            response_format=hand_written_format(),
        )
    assert "hand_written_v1" in str(exc.value)
    assert any("required_field" in violation for violation in exc.value.errors)


def test_chat_returns_the_validated_payload_so_a_caller_need_not_reparse(client, transport):
    transport.default = ok(chat_body('{"required_field": "present"}'))
    result = client.chat(
        Role.VISION, MESSAGES, prompt_version="v1", response_format=hand_written_format()
    )
    assert result.payload == {"required_field": "present"}


def test_chat_without_a_schema_has_no_payload_and_is_not_validated(client, transport):
    """A prose call is still a prose call. Validation attaches to the schema, not to the client."""
    transport.default = ok(chat_body("a waterfall in winter"))
    result = client.chat(Role.REASONING_CHEAP, MESSAGES, prompt_version="v1")
    assert result.payload is None
    assert result.answer == "a waterfall in winter"


def test_chat_refuses_a_field_of_the_wrong_type(client, transport):
    transport.default = ok(chat_body('{"required_field": 7}'))
    with pytest.raises(SchemaViolationError):
        client.chat(
            Role.VISION, MESSAGES, prompt_version="v1", response_format=hand_written_format()
        )


def test_structured_output_refuses_a_key_the_schema_forbade(client, transport):
    """Pydantic ignores extra keys. The schema sent to the endpoint said additionalProperties
    false, and that is the promise this system made about what it would accept."""
    transport.default = ok(
        chat_body('{"subject": "a", "count": 1, "caption": null, "smuggled": "in"}')
    )
    assert Sighting.model_validate(
        {"subject": "a", "count": 1, "caption": None, "smuggled": "in"}
    ).subject == "a"
    with pytest.raises(SchemaViolationError):
        client.structured(Role.REASONING_CHEAP, MESSAGES, Sighting, prompt_version="v1")


def test_a_cached_reply_is_revalidated_on_the_way_out(manifest, transport):
    """A stored payload is not trusted because it was valid when it was stored.

    The schema can change under a cache entry. Revalidating on read means a stale payload fails
    the same way a fresh one would, rather than being the one route by which an unchecked object
    reaches a caller.
    """
    from exulanica.models.cache import InMemoryResponseCache

    cache = InMemoryResponseCache()
    transport.default = ok(chat_body('{"required_field": "present"}'))
    client = ModelClient(
        api_key="test-key-not-real", manifest=manifest, transport=transport, cache=cache
    )
    first = client.chat(
        Role.VISION, MESSAGES, prompt_version="v1", response_format=hand_written_format()
    )
    assert first.cache_hit is False

    second = client.chat(
        Role.VISION, MESSAGES, prompt_version="v1", response_format=hand_written_format()
    )
    assert second.cache_hit is True
    assert second.payload == {"required_field": "present"}
    assert transport.call_count == 1


def test_a_response_format_with_no_schema_is_refused_before_any_money_is_spent(client, transport):
    """The schema is what the reply is checked against, so a call without one buys nothing."""
    transport.default = ok(chat_body('{"anything": true}'))
    with pytest.raises(GuidedJsonForbiddenError, match="no schema"):
        client.chat(
            Role.VISION,
            MESSAGES,
            prompt_version="v1",
            response_format={"type": "json_schema", "json_schema": {"name": "x", "strict": True}},
        )
    assert transport.call_count == 0
