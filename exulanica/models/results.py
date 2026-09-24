"""What a completed call returns.

Three frozen dataclasses, and several of their fields exist because of something that was
measured rather than because a result object usually carries them. ``attempts`` is zero on a
cache hit and that zero is what makes "nothing recomputed, nothing billed" checkable. ``tried``
records every identifier attempted in order, so a silent failover during a deprecation round is
visible in the Assembly Replay rather than inferred from a changed answer.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Generic, TypeVar

from pydantic import BaseModel

from exulanica.models.manifest import PROVIDER, Role
from exulanica.models.usage import CallUsage

__all__ = ["NO_MODEL_IN_RESPONSE", "ChatResult", "EmbeddingResult", "StructuredResult"]

#: Why a result names no served model: the response body carried no ``model`` field. The one
#: reason there is, named so a record can say it rather than leave a bare null.
NO_MODEL_IN_RESPONSE: Final = "response_names_no_model"

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True, slots=True)
class ChatResult:
    """One completed chat call, with everything the ledger and the caller need."""

    role: Role
    model_id: str
    served_model_id: str
    answer: str
    reasoning: str | None
    finish_reason: str
    usage: CallUsage
    raw: Mapping[str, Any]
    cache_hit: bool
    used_fallback: bool
    endpoint: str = ""
    #: HTTP requests actually issued, retries and failover attempts included. Zero on a cache
    #: hit, and that zero is the point: the ledger shows a stage that cost no request.
    attempts: int = 0
    #: Every identifier tried, in order, including the ones that failed. A silent failover is
    #: visible in the Assembly Replay only because this is recorded rather than inferred.
    tried: tuple[str, ...] = ()
    #: The parsed answer, already validated against the exact schema the request sent. Present
    #: whenever a ``response_format`` was sent and ``None`` otherwise, so a caller that reads it
    #: is reading data the client checked rather than data it merely relayed. A caller with a
    #: hand-written schema, such as the vision path, gets the same guarantee ``structured``
    #: gives without re-parsing the answer itself.
    payload: Mapping[str, Any] | None = None

    @property
    def model_ref(self) -> dict[str, str]:
        """Provider, identifier, endpoint: the shape ``pipeline_event.model_ref`` stores.

        ``revision`` is deliberately absent. Token Factory exposes no per-model revision for
        serverless endpoints, and a field invented here would be a fact the ledger cannot
        support.
        """
        return {"provider": PROVIDER, "model_id": self.model_id, "endpoint": self.endpoint}


@dataclass(frozen=True, slots=True)
class StructuredResult(Generic[T]):
    """A validated instance plus the call that produced it.

    The call is kept because the ledger needs it and because a disputed extraction has to be
    traceable to the response that produced it, not merely to the value that survived it.
    """

    value: T
    call: ChatResult


@dataclass(frozen=True, slots=True)
class EmbeddingResult:
    """One completed embedding call: the vectors, what they cost, and who served them.

    ``model_id`` is the identifier the chain sent. ``served_model_id`` is the one the response body
    named, read off the wire and never filled from the request: when the body names none it is
    ``None`` and ``served_model_unavailable`` says why, so a record never presents the
    configuration as an observation.
    """

    model_id: str
    vectors: tuple[tuple[float, ...], ...]
    usage: CallUsage
    dimensions: int
    served_model_id: str | None = None
    served_model_unavailable: str | None = NO_MODEL_IN_RESPONSE
    #: HTTP requests issued, retries and failover included. Zero on a cache hit; ``None`` only
    #: when whoever built the result did not say, which the client never does.
    attempts: int | None = None
    tried: tuple[str, ...] = ()
    used_fallback: bool = False
