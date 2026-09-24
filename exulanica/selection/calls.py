"""The model calls one request made, as each response reported it.

A question records its planner, query-vector and composer calls, and a proposal records its
classifier and drafter calls. Each record is read off the response rather than off the
configuration, so it names the model that answered, including when a fallback did.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from exulanica.models.manifest import Role
from exulanica.models.results import NO_MODEL_IN_RESPONSE, ChatResult, EmbeddingResult
from exulanica.models.usage import usd_string

__all__ = ["CallLog", "ModelCall"]


@dataclass(frozen=True, slots=True)
class ModelCall:
    """One model call this question actually made, as the response reported it.

    Every field is read off the response rather than off the configuration, and the distinction
    is the whole reason this exists. ``docs/product-direction.md`` requires the memory gate to
    "record the executed model, task, latency and output", and adds that "Nemotron use must be
    functional in that interaction if claimed, with the actual executed variant recorded rather
    than inferred from configuration". A manifest says which model a role asks for. Only the
    response says which one answered, and the two differ exactly when the fallback fired, which
    is the case a configuration-derived record would report wrongly and silently.

    ``requested_model`` is the identifier the chain sent; ``served_model`` is the one the body
    echoed back. ``used_fallback`` says the primary was withdrawn and the next model in the
    chain answered.

    The token counts are ``None`` when the provider's ``usage`` object did not carry them, not
    zero. A zero is a measurement and an absence is not, and :class:`CallUsage` already
    coalesces a missing count to zero for accounting, which is right for a bill and wrong for a
    record of what was observed. These are read from the raw body for that reason.

    ``attempts`` is zero exactly when the response came from the client's cache, which is the
    convention :mod:`exulanica.models.results` already established; ``latency_ms`` is then zero
    because no request was issued rather than because one was fast. The API builds its
    ``ModelClient`` with no cache, so on this route the count is at least one.
    """

    role: str
    #: The identifier the chain sent. A manifest fact, restated here so the pair can be compared.
    requested_model: str
    #: The identifier the response body echoed. The executed variant, and the only one recorded.
    served_model: str | None
    used_fallback: bool
    #: HTTP requests issued for this call, retries and failover included. Zero means the cache.
    attempts: int | None
    #: Whole milliseconds. Integer because a record with floats in it is a record that changes
    #: under a JSON round trip, and every evaluation record in this repository refuses them.
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None
    reasoning_tokens: int | None
    usd: str | None = None
    #: Why ``served_model`` is null, by name, when it is: the response body named no model.
    #: ``None`` whenever ``served_model`` is present.
    served_model_unavailable: str | None = None

    @classmethod
    def from_result(cls, call: ChatResult) -> ModelCall:
        usage = call.raw.get("usage")
        usage = usage if isinstance(usage, Mapping) else {}
        details = usage.get("completion_tokens_details")
        details = details if isinstance(details, Mapping) else {}
        echoed = call.raw.get("model")
        # ChatResult fills an absent echo with the requested model for compatibility.
        # Measurement must read the wire, otherwise a missing observation looks verified.
        served = echoed if isinstance(echoed, str) and echoed else None
        return cls(
            role=str(call.role),
            requested_model=call.model_id,
            served_model=served,
            served_model_unavailable=None if served is not None else NO_MODEL_IN_RESPONSE,
            used_fallback=call.used_fallback,
            attempts=call.attempts,
            latency_ms=round(call.usage.latency_s * 1000),
            prompt_tokens=_reported(usage, "prompt_tokens"),
            completion_tokens=_reported(usage, "completion_tokens"),
            reasoning_tokens=_reported(details, "reasoning_tokens"),
            usd=(
                usd_string(call.usage.usd)
                if _reported(usage, "prompt_tokens") is not None
                and _reported(usage, "completion_tokens") is not None
                else None
            ),
        )


def _reported(usage: Mapping[str, Any], key: str) -> int | None:
    """A count the provider actually reported, or ``None``. Never a substituted zero."""
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class CallLog:
    """The calls one question made, in order.

    A recorder passed down rather than a return value threaded back, which is the shape
    :class:`~exulanica.models.usage.CostLedger` already uses in this codebase, and it keeps
    :func:`propose_plan` returning a plan and :func:`compose_answer` returning an answer. The
    ``/selection/plan`` route passes none and is unchanged.

    **Per question, never per process.** ``ModelClient`` holds a ledger of every call the process
    made, which is the right scope for a cost report and the wrong one here: the API builds one
    client and FastAPI runs a synchronous route in a threadpool, so two questions answered at
    once would interleave in that ledger and neither could be attributed. A log created inside
    :func:`answer_question` cannot.

    **It records the calls that returned a result, and no others.** A call the endpoint answered
    with a body that does not satisfy the schema, or one it truncated, raises out of
    ``ModelClient.structured`` before any :class:`ChatResult` reaches this module, and
    ``exulanica.models`` is not this module's to change. So such an attempt is absent from the
    list rather than represented by an entry with invented fields; ``AnsweredQuestion.rejections``
    and ``repaired`` are what say that a discarded attempt happened. A composer answer refused by
    :func:`~exulanica.selection.answer.validate_answer` IS recorded, because that one came back.
    """

    __slots__ = ("_calls",)

    def __init__(self) -> None:
        self._calls: list[ModelCall] = []

    def record(self, call: ChatResult) -> ChatResult:
        """Note one completed call and hand it straight back, so a call site stays one line."""
        self._calls.append(ModelCall.from_result(call))
        return call

    def record_embedding(self, result: EmbeddingResult, latency_ms: int) -> None:
        """Record one query-vector call as the response reported it.

        The served model is the one the response body named, and when it named none the record
        says so by :data:`~exulanica.models.results.NO_MODEL_IN_RESPONSE` rather than filling in
        the requested one. ``latency_ms`` is measured by the caller around the whole call. The
        cost is left null when the provider's report did not price it, as a chat call's is.
        """
        usage = result.usage
        self._calls.append(
            ModelCall(
                role=str(Role.EMBEDDING),
                requested_model=result.model_id,
                served_model=result.served_model_id,
                used_fallback=result.used_fallback,
                attempts=result.attempts,
                latency_ms=latency_ms,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                reasoning_tokens=None,
                usd=usd_string(usage.usd) if usage.usd_known else None,
                served_model_unavailable=result.served_model_unavailable,
            )
        )

    @property
    def calls(self) -> tuple[ModelCall, ...]:
        return tuple(self._calls)
