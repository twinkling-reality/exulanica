"""Turning a response body into a result a caller may believe.

Separated from the client because these are the checks that decide whether a reply enters
canonical state, and the client's other job is reaching the network. The four refusals here are
each the answer to something measured:

*   ``finish_reason: "length"`` with nothing written is a ``max_tokens`` that does not clear the
    reasoning overhead. It reads exactly like a model that cannot do the task and is not one; it
    produced one false negative in this project's own verification harness.
*   ``finish_reason: "length"`` with a partial answer is never salvaged. Half a result that
    happens to parse is a plausible fact with a piece missing.
*   A reasoning block that was opened and never closed was cut mid-thought while the endpoint
    reported an ordinary stop. ``finish_reason`` cannot see that one.
*   A reply is validated locally against the byte-identical schema that was sent, because
    sending a schema is a request and not a guarantee. ``guided_json`` proved on this platform
    that a constraint parameter can be accepted, ignored, and answered with an HTTP 200 that
    looks fine.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from exulanica.models.budget import BudgetGuard
from exulanica.models.choice import ChoiceRequest
from exulanica.models.errors import (
    ModelError,
    SchemaViolationError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.models.manifest import ModelSpec, Role
from exulanica.models.reasoning import SplitContent, split_message
from exulanica.models.results import NO_MODEL_IN_RESPONSE, ChatResult, EmbeddingResult
from exulanica.models.schema import (
    AmbiguousStructuredOutputError,
    extract_json_object,
    validate_against_schema,
)
from exulanica.models.usage import CallUsage

__all__ = ["checked_payload", "embedding_from_body", "result_from_body"]


def _record_attempt(
    budget: BudgetGuard,
    *,
    role: Role,
    spec: ModelSpec,
    body: Any,
    cache_hit: bool,
    used_fallback: bool,
    latency_s: float,
    usd_bound: Decimal | None,
) -> CallUsage:
    """Record a call that came back, before anything in its body is read or believed.

    A body or a ``usage`` that is not an object reports nothing, so the call is charged its
    reservation (``usd_bound``) as a call of unknown cost, and the reservation is given back.
    """
    reported = body.get("usage") if isinstance(body, Mapping) else None
    usage = CallUsage.from_response(
        role=role,
        spec=spec,
        usage=reported if isinstance(reported, Mapping) else None,
        cache_hit=cache_hit,
        used_fallback=used_fallback,
        latency_s=latency_s,
        usd_bound=usd_bound,
    )
    return budget.record(usage, released=usd_bound)


def _is_vector_row(row: Any) -> bool:
    vector = row.get("embedding") if isinstance(row, Mapping) else None
    return isinstance(vector, list) and all(
        isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector
    )


def result_from_body(
    *,
    role: Role,
    spec: ModelSpec,
    body: Mapping[str, Any],
    budget: BudgetGuard,
    endpoint: str,
    cache_hit: bool,
    used_fallback: bool,
    latency_s: float,
    attempts: int,
    tried: tuple[str, ...],
    response_format: Mapping[str, Any] | None = None,
    usd_bound: Decimal | None = None,
    choice_request: ChoiceRequest | None = None,
) -> ChatResult:
    """A completed call's result, once its reply is whole and, where one was asked for, checked.

    ``choice_request`` is the choice a request asked for by its function: the reply's one tool
    call is read, and its payload is the option it chose, or the reply is refused.
    """
    # Recorded before anything about the reply is believed, a reply with no choices included: the
    # request reached the provider and came back, so it may be billed, and the ledger, the budget
    # and a request's own record must each see it.
    usage = _record_attempt(
        budget,
        role=role,
        spec=spec,
        body=body,
        cache_hit=cache_hit,
        used_fallback=used_fallback,
        latency_s=latency_s,
        usd_bound=usd_bound,
    )
    if not isinstance(body, Mapping):
        raise TransportError(
            f"{spec.model_id} returned a body that is not an object", retryable=False
        )

    choices = body.get("choices") or []
    if not choices:
        raise TransportError(f"{spec.model_id} returned no choices", retryable=False)
    choice = choices[0]
    message = choice.get("message") or {}
    finish_reason = str(choice.get("finish_reason") or "")
    split: SplitContent = split_message(message)

    if finish_reason == "length" and split.empty_answer:
        raise TruncatedResponseError(
            f"{spec.model_id} stopped on the token limit before producing any answer "
            f"({usage.reasoning_tokens} reasoning tokens spent, "
            f"{usage.completion_tokens} completion tokens). This is a max_tokens setting "
            "that does not clear the reasoning overhead, not a model that cannot do the "
            "task. Raise max_tokens."
        )
    if finish_reason == "length":
        raise TruncatedResponseError(
            f"{spec.model_id} truncated the answer on the token limit. A partial answer is "
            "never salvaged: half a result that happens to parse is a plausible fact with a "
            "piece missing. Raise max_tokens and retry."
        )
    if not split.complete:
        # The case finish_reason cannot see. A body that opens a reasoning block and never
        # closes it was cut mid-thought, and the endpoint has been observed reporting that
        # as an ordinary stop. Everything after the open tag is scratch work and everything
        # before it is a preamble, so there is no answer here to salvage or to return empty.
        raise TruncatedResponseError(
            f"{spec.model_id} opened a reasoning block and never closed it, so the answer "
            f"was cut mid-thought whatever finish_reason claims (it said {finish_reason!r}). "
            "Everything after the open tag is scratch work and everything before it is a "
            "preamble, so there is no answer in this response. Raise max_tokens and retry."
        )

    if choice_request is not None:
        payload: dict[str, Any] | None = {
            choice_request.argument: choice_request.answer_from_tool_call(message)
        }
    else:
        payload = (
            None
            if response_format is None
            else checked_payload(split.answer, response_format, spec.model_id)
        )

    return ChatResult(
        role=role,
        model_id=spec.model_id,
        provider=spec.provider,
        served_model_id=str(body.get("model") or spec.model_id),
        answer=split.answer,
        reasoning=split.reasoning,
        finish_reason=finish_reason,
        usage=usage,
        raw=body,
        cache_hit=cache_hit,
        used_fallback=used_fallback,
        endpoint=endpoint,
        attempts=attempts,
        tried=tried,
        payload=payload,
    )


def checked_payload(
    answer: str, response_format: Mapping[str, Any], model_id: str
) -> dict[str, Any]:
    """Parse the answer and validate it against the schema this request actually sent.

    Two separate guarantees, and both are wanted. ``extract_json_object`` refuses a body
    that carries more than one candidate object rather than guessing which one was the
    answer; ``validate_against_schema`` then checks the winner against the byte-identical
    schema in ``response_format``, because a request for enforcement is not proof of it.
    ``guided_json`` was measured being accepted and ignored on this platform, and a
    ``json_schema`` the endpoint quietly stopped honouring would look exactly the same from
    the outside: HTTP 200, a plausible object, the wrong shape.

    The parse failure and the shape failure are raised separately on purpose. "Not JSON at
    all" and "JSON of the wrong shape" send a reader to different places, and one message
    covering both sends them to the wrong one.
    """
    declared = response_format.get("json_schema") or {}
    schema = declared.get("schema")
    name = str(declared.get("name") or "response")
    try:
        parsed = extract_json_object(answer)
    except (AmbiguousStructuredOutputError, SchemaViolationError):
        # Both already say precisely what went wrong. Rewrapping either as "not JSON and
        # contains no JSON object" would be false of a body that parsed perfectly, and it
        # would send a reader looking for a transport fault instead of a shape one.
        raise
    except StructuredOutputError as exc:
        raise StructuredOutputError(
            f"{model_id} returned text that is not JSON and contains no JSON object, even "
            "though response_format was json_schema strict. That is what an unenforced "
            f"schema looks like. Answer was {answer[:300]!r}"
        ) from exc
    if not isinstance(schema, Mapping):
        # response_format is only ever built by exulanica.models.schema and only ever accepted
        # by _build_payload after it has checked the type and the strict flag, so this is
        # unreachable from a supported call site. It is still raised rather than skipped:
        # silently returning unvalidated data is the defect this method exists to close.
        raise StructuredOutputError(
            f"{model_id} was sent a response_format carrying no schema, so its reply cannot "
            "be validated locally. Build response_format with exulanica.models.schema."
        )
    return validate_against_schema(parsed, schema, name=name)


def embedding_from_body(
    role: Role,
    spec: ModelSpec,
    body: Mapping[str, Any],
    *,
    budget: BudgetGuard,
    cache_hit: bool,
    used_fallback: bool = False,
    latency_s: float = 0.0,
    attempts: int = 0,
    tried: tuple[str, ...] = (),
    usd_bound: Decimal | None = None,
) -> EmbeddingResult:
    # Recorded before a vector is read, as a chat reply is: a malformed row is the provider's
    # answer to a request it may bill.
    usage = _record_attempt(
        budget,
        role=role,
        spec=spec,
        body=body,
        cache_hit=cache_hit,
        used_fallback=used_fallback,
        latency_s=latency_s,
        usd_bound=usd_bound,
    )
    rows = body.get("data") if isinstance(body, Mapping) else None
    if not isinstance(rows, list) or not all(_is_vector_row(row) for row in rows):
        raise TransportError(
            f"{spec.model_id} returned embeddings that are not a list of number vectors",
            retryable=False,
        )
    vectors = tuple(tuple(float(x) for x in row["embedding"]) for row in rows)
    dimensions = len(vectors[0]) if vectors else 0
    expected = spec.embedding_dimensions
    if expected is not None and vectors and dimensions != expected:
        raise ModelError(
            f"{spec.model_id} returned {dimensions}-dimensional vectors, manifest declares "
            f"{expected}. Storing these alongside existing vectors would corrupt the index."
        )
    echoed = body.get("model")
    served = echoed if isinstance(echoed, str) and echoed else None
    return EmbeddingResult(
        model_id=spec.model_id,
        vectors=vectors,
        usage=usage,
        dimensions=dimensions,
        served_model_id=served,
        served_model_unavailable=None if served is not None else NO_MODEL_IN_RESPONSE,
        attempts=attempts,
        tried=tried or (spec.model_id,),
        used_fallback=used_fallback,
    )
