"""Errors raised by the model client, the manifest and the preflight.

Kept separate from ``exulanica.errors``, which is about the evidence spine and the object store.
Every class here inherits ``ExulanicaError`` so a caller can still catch the whole package with
one except clause.

Several of these are control-flow relevant rather than decorative:

*   ``ModelUnavailableError`` is what triggers the fallback. Nothing else does.
*   ``BudgetExceededError`` must not be retried; retrying is the runaway loop it exists to stop.
*   ``TruncatedResponseError`` names a configuration mistake, not a model failure, and says so,
    because the opposite reading has already cost this project one wrong conclusion.
"""

from __future__ import annotations

from exulanica.errors import ExulanicaError

__all__ = [
    "AmbiguousStructuredOutputError",
    "BudgetExceededError",
    "GuidedJsonForbiddenError",
    "ManifestError",
    "MaxTokensTooLowError",
    "ModelError",
    "ModelUnavailableError",
    "NoFallbackError",
    "PreflightError",
    "SchemaViolationError",
    "StructuredOutputError",
    "TransportError",
    "TruncatedResponseError",
]


class ModelError(ExulanicaError):
    """Base class for everything raised by ``exulanica.models``."""


class ManifestError(ModelError, ValueError):
    """The model manifest is missing, malformed, or does not bind a role the code needs."""


class PreflightError(ModelError):
    """A manifest identifier is absent from the live catalog, or no longer fits its role.

    Raised by the preflight so a deprecation is a loud build failure rather than a quiet 404 in
    production weeks later.
    """


class TransportError(ModelError):
    """The HTTP call did not complete. Network, DNS, timeout, rate limit, or a 5xx.

    ``retryable`` says whether issuing the identical request again could plausibly succeed. It
    defaults to True because a connection that failed is the common case and it is transient. A
    caller that opted into retries consults it; a caller that did not sees the same exception it
    always saw, so the flag adds a capability rather than changing a behaviour.

    A response the endpoint understood and refused is not this: a 4xx that is not a rate limit
    will be refused identically forever, and retrying it is spend with no new information.

    ``timed_out`` says the role's timeout passed before a whole response arrived.
    ``reached_provider`` is what the ledger prices the attempt by: ``False`` when the request never
    left (the connection was not made), ``True`` when the provider answered with a status, and
    ``None`` when it was sent and nothing whole came back, which is the case where the provider may
    bill for work nobody received.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = True,
        timed_out: bool = False,
        reached_provider: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.timed_out = timed_out
        self.reached_provider = reached_provider


class ModelUnavailableError(ModelError):
    """The endpoint says this identifier does not exist. The one trigger for a fallback.

    Deliberately narrow. A 500, a 429 or a timeout is not this: those are the same model having
    a bad moment, and switching models in response would hide a platform incident behind a
    quality regression.
    """

    def __init__(self, message: str, *, model_id: str, status_code: int) -> None:
        super().__init__(message)
        self.model_id = model_id
        self.status_code = status_code


class NoFallbackError(ModelError):
    """The primary is unavailable and the role has no declared fallback left to try."""


class MaxTokensTooLowError(ModelError, ValueError):
    """``max_tokens`` sits under the role's reasoning floor, so the answer would be empty."""


class GuidedJsonForbiddenError(ModelError, ValueError):
    """A caller tried to constrain output with ``guided_json``.

    The parameter is accepted and silently ignored by this endpoint: HTTP 200, prose body, no
    schema enforced. A pipeline using it appears to work while enforcing nothing, which is the
    exact shape of failure the "naked prose never enters canonical state" rule exists to stop.
    """


class StructuredOutputError(ModelError):
    """The model returned a body that is not valid JSON, or does not validate against the schema."""


class AmbiguousStructuredOutputError(StructuredOutputError):
    """The body carried more than one candidate JSON object and none of them is identifiable.

    The reasoning models write scratch work inline in ``message.content`` with no delimiter, and
    scratch work about a JSON schema routinely contains a draft object. When the scratch work is
    tagged it is stripped before extraction and this never arises. When it is not, there is no
    evidence in the body saying which object is the answer: "the first" and "the last" are both
    guesses, and a wrong guess writes the model's placeholder into canonical state as a fact.

    Refusing is the correct answer. A refused call is a visible failure that costs one retry; a
    guessed one is an invented memory that nobody ever attributes to the parser.

    ``candidates`` holds the distinct objects found, so a caller logging the failure can show
    what the model actually produced without re-parsing the body.
    """

    def __init__(self, message: str, *, candidates: tuple[dict[str, object], ...] = ()) -> None:
        super().__init__(message)
        self.candidates = candidates


class SchemaViolationError(StructuredOutputError):
    """Valid JSON that does not satisfy the exact schema the request sent.

    Distinct from its parent because the two failures send a reader to different places. "Not
    JSON at all" means the schema was not enforced end to end, which is the ``guided_json``
    shape and a platform problem. "JSON of the wrong shape" means the endpoint accepted the
    schema and returned something else anyway, which is what an unenforced ``strict: true``
    looks like from the outside.
    """

    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors


class TruncatedResponseError(ModelError):
    """The token limit landed inside the response, so what came back is not a whole answer.

    Three shapes, and the third is the one the provider does not report. ``finish_reason:
    "length"`` with nothing written is a ``max_tokens`` that does not clear the reasoning
    overhead. ``finish_reason: "length"`` with a partial answer is never salvaged, because half
    a result that happens to parse is a plausible fact with a piece missing. And a body that
    opens a reasoning block and never closes it was cut mid-thought while the endpoint reported
    an ordinary stop: ``finish_reason`` cannot see that one, and
    ``exulanica.models.reasoning.SplitContent.complete`` is what does.
    """


class BudgetExceededError(ModelError):
    """The configured spend or call ceiling would be crossed by this call, so it did not happen."""

    def __init__(self, message: str, *, spent_usd: object, ceiling_usd: object) -> None:
        super().__init__(message)
        self.spent_usd = spent_usd
        self.ceiling_usd = ceiling_usd
