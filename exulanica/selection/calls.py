"""The model calls one request made, as each response reported it, and each attempt it paid for.

A question records its planner, query-vector and composer calls, and a proposal records its
classifier and drafter calls. Each record is read off the response rather than off the
configuration, so it names the model that answered, including when a fallback did. An attempt
that returned no result, because it timed out, failed, or came back and was refused, is recorded
from the cost ledger's row for it, with its outcome and whether its cost is known.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Final

from exulanica.models.manifest import Role
from exulanica.models.results import NO_MODEL_IN_RESPONSE, ChatResult, EmbeddingResult
from exulanica.models.usage import CallOutcome, CallUsage, CostBasis, usd_string

__all__ = [
    "RESULT_NOT_RETURNED",
    "AttemptOutcome",
    "CallCost",
    "CallLog",
    "CallsOnFailure",
    "ModelCall",
    "noted_calls",
]


class AttemptOutcome(StrEnum):
    """How one attempt ended, as the execution record says it."""

    #: A reply came back and the workflow received it as a result.
    COMPLETED = "completed"
    #: The role's timeout passed before a whole reply arrived.
    TIMED_OUT = "timed_out"
    #: An error status, a dropped connection, a withdrawn model, or a connection never made.
    FAILED = "failed"
    #: A reply came back and the client refused it, as truncated or as outside the schema.
    REPLY_REFUSED = "reply_refused"


class CallCost(StrEnum):
    """Whether an attempt's cost is known, as the execution record says it."""

    KNOWN = "known"
    #: The request was sent and no usage came back that prices it; the provider may bill it.
    UNKNOWN = "unknown"
    #: The connection was never made, so no request reached the provider and it cost nothing.
    NOT_SENT = "not_sent"


#: The ledger's cost basis, as the record says it. A cache hit's zero is known.
_COST: Final = MappingProxyType(
    {
        CostBasis.REPORTED: CallCost.KNOWN,
        CostBasis.CACHED: CallCost.KNOWN,
        CostBasis.NOT_SENT: CallCost.NOT_SENT,
        CostBasis.UNKNOWN: CallCost.UNKNOWN,
    }
)

#: The ledger's outcome of an attempt that returned no result, as the record says it. A completed
#: row with no result is a reply the client refused after the ledger recorded it.
_UNRETURNED: Final = MappingProxyType(
    {
        CallOutcome.COMPLETED: AttemptOutcome.REPLY_REFUSED,
        CallOutcome.TIMED_OUT: AttemptOutcome.TIMED_OUT,
        CallOutcome.FAILED: AttemptOutcome.FAILED,
    }
)

#: Why ``served_model`` is null for an attempt that returned no result to the workflow: no body
#: reached it that could name a model.
RESULT_NOT_RETURNED: Final = "result_not_returned"


def _cost(basis: CostBasis) -> CallCost:
    try:
        return _COST[basis]
    except KeyError:
        raise ValueError(f"the execution record has no words for cost basis {basis!r}") from None


def _unreturned(outcome: CallOutcome) -> AttemptOutcome:
    try:
        return _UNRETURNED[outcome]
    except KeyError:
        raise ValueError(f"the execution record has no words for outcome {outcome!r}") from None


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
    #: Why ``served_model`` is null, by name, when it is: the response body named no model, or
    #: :data:`RESULT_NOT_RETURNED`. ``None`` whenever ``served_model`` is present.
    served_model_unavailable: str | None = None
    #: How the attempt ended. Every entry of a result the workflow received is ``completed``.
    outcome: AttemptOutcome = field(kw_only=True)
    #: Whether ``usd`` is the attempt's known cost. ``unknown`` leaves ``usd`` null: the ledger
    #: charges the attempt's reservation, the most it can have cost, and this record says only
    #: that the cost is not known.
    cost_basis: CallCost = field(kw_only=True)

    @classmethod
    def from_attempt(cls, usage: CallUsage) -> ModelCall:
        """An attempt that returned no result to the workflow, from its ledger row.

        Never the failure's text, which is the provider's or the transport's wording. The token
        counts are the ones a reply reported, only where its cost is known from them.
        """
        cost = _cost(usage.cost_basis)
        reported = usage.cost_basis is CostBasis.REPORTED
        return cls(
            role=str(usage.role),
            requested_model=usage.model_id,
            served_model=None,
            served_model_unavailable=RESULT_NOT_RETURNED,
            used_fallback=usage.used_fallback,
            attempts=0 if usage.cache_hit else 1,
            latency_ms=round(usage.latency_s * 1000),
            prompt_tokens=usage.prompt_tokens if reported else None,
            completion_tokens=usage.completion_tokens if reported else None,
            reasoning_tokens=None,
            usd=None if cost is CallCost.UNKNOWN else usd_string(usage.usd),
            outcome=_unreturned(usage.outcome),
            cost_basis=cost,
        )

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
            outcome=AttemptOutcome.COMPLETED,
            cost_basis=_cost(call.usage.cost_basis),
        )


def _reported(usage: Mapping[str, Any], key: str) -> int | None:
    """A count the provider actually reported, or ``None``. Never a substituted zero."""
    value = usage.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


class CallLog:
    """The calls one question made, in order, and every attempt it paid for.

    A recorder passed down rather than a return value threaded back, which is the shape
    :class:`~exulanica.models.usage.CostLedger` already uses in this codebase, and it keeps
    :func:`propose_plan` returning a plan and :func:`compose_answer` returning an answer. The
    ``/selection/plan`` route passes none and is unchanged.

    **Per question, never per process.** ``ModelClient`` holds a ledger of every call the process
    made, which is the right scope for a cost report and the wrong one here: the API builds one
    client and FastAPI runs a synchronous route in a threadpool, so two questions answered at
    once would interleave in that ledger and neither could be attributed. A log created inside
    :func:`answer_question` cannot, and it hears each attempt through :meth:`attempt`, which a
    client copy made for this question alone calls (``ModelClient.with_attempts``); the process
    ledger is never read to reconstruct it.

    **Every attempt the question paid for, or may have.** The ledger records a reply before the
    client decides whether to believe it, so a reply refused as truncated or as outside the
    schema is heard here and never reaches :meth:`record`; it is listed as ``reply_refused``. An
    attempt that timed out or failed, a withdrawn primary before its fallback among them, is
    listed with its outcome and whether its cost is known. A result the workflow receives replaces
    its attempt with the record the response gives. A request a policy or the budget refused
    before it left was never an attempt and is not listed. A composer answer refused by
    :func:`~exulanica.selection.answer.validate_answer` IS ``completed``, because it came back.
    """

    __slots__ = ("_entries", "_rejections")

    def __init__(self) -> None:
        self._entries: list[ModelCall | CallUsage] = []
        self._rejections: tuple[str, ...] = ()

    def rejected(self, reasons: tuple[str, ...]) -> None:
        """Keep the validator's latest reasons for refusing a reply, for a request that then fails.

        A request that completes reports its rejections with its answer; one a later error ends
        has no answer, so its record carries them instead (:meth:`on_failure`).
        """
        self._rejections = tuple(reasons)

    def attempt(self, usage: CallUsage) -> None:
        """Hear one attempt as the ledger records it, before any result is made from it."""
        self._entries.append(usage)

    def _received(self, usage: CallUsage, call: ModelCall) -> None:
        """Replace the attempt a result was made from with the result's record, in its place."""
        for index in range(len(self._entries) - 1, -1, -1):
            if self._entries[index] is usage:
                self._entries[index] = call
                return
        # A result from a client this log did not observe, as a test double hands back.
        self._entries.append(call)

    def record(self, call: ChatResult) -> ChatResult:
        """Note one completed call and hand it straight back, so a call site stays one line."""
        self._received(call.usage, ModelCall.from_result(call))
        return call

    def record_embedding(self, result: EmbeddingResult, latency_ms: int) -> None:
        """Record one query-vector call as the response reported it.

        The served model is the one the response body named, and when it named none the record
        says so by :data:`~exulanica.models.results.NO_MODEL_IN_RESPONSE` rather than filling in
        the requested one. ``latency_ms`` is measured by the caller around the whole call. The
        cost is left null when the provider's report did not price it, as a chat call's is.
        """
        usage = result.usage
        self._received(
            usage,
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
                outcome=AttemptOutcome.COMPLETED,
                cost_basis=_cost(usage.cost_basis),
            ),
        )

    @property
    def calls(self) -> tuple[ModelCall, ...]:
        return tuple(
            entry if isinstance(entry, ModelCall) else ModelCall.from_attempt(entry)
            for entry in self._entries
        )

    def on_failure(self, prompt_version: str) -> CallsOnFailure:
        """What this log holds, for the error that ends its request (:func:`noted_calls`)."""
        return CallsOnFailure(
            calls=self.calls, prompt_version=prompt_version, rejections=self._rejections
        )


@dataclass(frozen=True, slots=True)
class CallsOnFailure:
    """The calls a request made before a model error ended it, carried on that error.

    The request's answer never exists, so its execution record travels with the error to the
    boundary that turns it into a problem body.
    """

    calls: tuple[ModelCall, ...]
    prompt_version: str
    #: The validator's reasons for refusing a reply before the failure, or none.
    rejections: tuple[str, ...] = ()

    def note(self, failure: BaseException) -> None:
        setattr(failure, _NOTED, self)


_NOTED: Final = "exulanica_calls_on_failure"


def noted_calls(failure: BaseException) -> CallsOnFailure | None:
    """The calls noted on ``failure`` by the request it ended, or None when none were."""
    noted = getattr(failure, _NOTED, None)
    return noted if isinstance(noted, CallsOnFailure) else None
