"""Model access: one manifest, one client, one structured-output mechanism.

Callers name a role. No provider identifier appears anywhere in this package's Python source;
they live in ``models.manifest.json``, and ``tests/test_models_manifest.py`` fails if one leaks into
code. Nothing here can reach the ``guided_json`` parameter, which this endpoint accepts, ignores,
and answers with prose and an HTTP 200.
"""

from __future__ import annotations

from exulanica.models.budget import DEFAULT_CEILING_USD, DEFAULT_MAX_CALLS, BudgetGuard
from exulanica.models.cache import (
    CacheKey,
    FileResponseCache,
    InMemoryResponseCache,
    NullResponseCache,
    ResponseCache,
    cache_key,
    request_digest,
)
from exulanica.models.chain import ChainResponse, ModelChain
from exulanica.models.client import ModelClient
from exulanica.models.credentials import api_key_from_env
from exulanica.models.errors import (
    AmbiguousStructuredOutputError,
    BudgetExceededError,
    GuidedJsonForbiddenError,
    ManifestError,
    MaxTokensTooLowError,
    ModelError,
    ModelUnavailableError,
    NoFallbackError,
    PreflightError,
    SchemaViolationError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.models.manifest import (
    Manifest,
    ModelSpec,
    Provider,
    Role,
    RoleBinding,
    load_manifest,
)
from exulanica.models.messages import image_part, text_part
from exulanica.models.preflight import PreflightReport, run_preflight
from exulanica.models.reasoning import SplitContent, split_message, split_reasoning
from exulanica.models.results import ChatResult, EmbeddingResult, StructuredResult
from exulanica.models.schema import (
    extract_json_object,
    json_object_candidates,
    response_format_for,
    response_format_for_schema,
    strict_json_schema,
    validate_against_schema,
)
from exulanica.models.transport import HttpResponse, HttpxTransport, Transport
from exulanica.models.usage import CallUsage, CostLedger

__all__ = [
    "DEFAULT_CEILING_USD",
    "DEFAULT_MAX_CALLS",
    "AmbiguousStructuredOutputError",
    "BudgetExceededError",
    "BudgetGuard",
    "CacheKey",
    "CallUsage",
    "ChainResponse",
    "ChatResult",
    "CostLedger",
    "EmbeddingResult",
    "FileResponseCache",
    "GuidedJsonForbiddenError",
    "HttpResponse",
    "HttpxTransport",
    "InMemoryResponseCache",
    "Manifest",
    "ManifestError",
    "MaxTokensTooLowError",
    "ModelChain",
    "ModelClient",
    "ModelError",
    "ModelSpec",
    "ModelUnavailableError",
    "NoFallbackError",
    "NullResponseCache",
    "PreflightError",
    "PreflightReport",
    "Provider",
    "ResponseCache",
    "Role",
    "RoleBinding",
    "SchemaViolationError",
    "SplitContent",
    "StructuredOutputError",
    "StructuredResult",
    "Transport",
    "TransportError",
    "TruncatedResponseError",
    "api_key_from_env",
    "cache_key",
    "extract_json_object",
    "image_part",
    "json_object_candidates",
    "load_manifest",
    "request_digest",
    "response_format_for",
    "response_format_for_schema",
    "run_preflight",
    "split_message",
    "split_reasoning",
    "strict_json_schema",
    "text_part",
    "validate_against_schema",
]
