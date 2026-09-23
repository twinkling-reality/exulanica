"""The Token Factory client. Routing by role, one structured-output mechanism, one fallback rule.

Everything here exists because of something that was measured, not assumed:

*   **Routing is by role.** A caller never names a model. The manifest names models; this client
    resolves a role to a chain and walks it.
*   **Fallback fires on a 404-class error and nothing else.** A withdrawn identifier is the one
    failure a different model can fix. A 429, a 500 or a timeout is the same model having a bad
    moment, and switching models in response would hide a platform incident behind a quality
    regression that nobody would ever attribute correctly. The fallback path is exercised by
    ``tests/test_models_client.py`` rather than first executed in production.
*   **``max_tokens`` has a floor.** The reasoning models spend 150 to 215 tokens thinking before
    writing anything, on every call, and it cannot be disabled. Under the floor, the endpoint
    returns HTTP 200 with ``finish_reason: "length"`` and an empty answer. That looks exactly
    like a model that cannot do the task and is not one: it already produced one false negative
    in this project's own verification harness. The floor is checked before the request, and a
    truncation that survives the check is raised as a parameter bug rather than salvaged.
*   **Structured output goes through ``response_format {type: json_schema, strict: true}`` and
    nowhere else.** A top-level ``guided_json`` is accepted and silently ignored: HTTP 200,
    prose body, no schema enforced. This client refuses to send it, and refuses any
    ``response_format`` it did not build, so naked prose cannot enter canonical state through it.
*   **Sending a schema is not the same as the schema being enforced, so the reply is validated
    locally against the exact schema that was sent.** ``guided_json`` proved on this very
    platform that a constraint parameter can be accepted, ignored, and answered with an HTTP 200
    that looks fine. Every reply to a request carrying a ``response_format`` comes back through
    ``ChatResult.payload`` already checked, so a caller with a hand-written schema gets the same
    guarantee ``structured`` gives rather than inheriting raw text.
*   **Reasoning text is separated from the answer, and an ambiguous answer is refused.** Both
    observed shapes are handled; see ``exulanica.models.reasoning``. Where the scratch work is
    untagged and contains a draft JSON object, there is nothing in the body identifying which
    object is the answer, and the call fails rather than guessing. See
    ``exulanica.models.schema.extract_json_object``.

*   **The endpoint is checked against the egress allowlist when the client is built.** A
    deployment whose ``EXULANICA_EGRESS_ALLOWLIST`` does not declare ``manifest.base_url`` fails
    here, at startup, instead of at its first question. The transport checks every call again;
    see :mod:`exulanica.models.egress` for what that does and does not cover.
*   **Every request passes the client's policies before anything else happens to it.** ``chat``
    (and so ``structured`` and ``vision``) and ``embed`` hand the request to each attached policy
    before the cache key is computed, and send exactly the text the policies return. A client with
    no policy refuses to send, by name. A policy is attached with :meth:`ModelClient.with_policy`
    by the code that knows whose data the request carries; policies only accumulate. See
    :mod:`exulanica.models.policy`.

The client holds a cache, a budget guard and a ledger. All three are optional collaborators with
inert defaults, so a caller gets no caching and generous limits unless it asks, and a test gets
exact ones.
"""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ValidationError

from exulanica.models.budget import BudgetGuard
from exulanica.models.cache import NullResponseCache, ResponseCache, cache_key
from exulanica.models.chain import ModelChain
from exulanica.models.credentials import api_key_from_env
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV, EgressConfigurationError, EgressRefused
from exulanica.models.errors import (
    GuidedJsonForbiddenError,
    MaxTokensTooLowError,
    StructuredOutputError,
)
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import Manifest, Role, load_manifest
from exulanica.models.messages import image_part, text_part
from exulanica.models.policy import (
    HostedRequest,
    HostedRequestPolicy,
    HostedRequestRefused,
    NoHostedRequestPolicy,
    admitted_payload,
    request_parts,
)
from exulanica.models.response import embedding_from_body, result_from_body
from exulanica.models.results import ChatResult, EmbeddingResult, StructuredResult
from exulanica.models.schema import (
    response_format_for,
)
from exulanica.models.transport import HttpxTransport, Transport
from exulanica.models.usage import CostLedger

__all__ = [
    "ChatResult",
    "EmbeddingResult",
    "ModelClient",
    "StructuredResult",
    "api_key_from_env",
    "image_part",
    "text_part",
]

T = TypeVar("T", bound=BaseModel)

_DEFAULT_TIMEOUT: Final = 180.0

#: A payload naming any of these is refused before it reaches the network. ``guided_json`` and
#: its relatives are the silent-failure family: accepted, ignored, HTTP 200, prose returned.
_FORBIDDEN_PARAMS: Final = frozenset(
    {"guided_json", "guided_regex", "guided_choice", "guided_grammar"}
)

#: How much of a refused answer its refusal quotes. A caller that repairs sends the refusal back to
#: the model, so it must reach past the field that failed. It used to stop at 300 characters, which
#: on the planner's pretty-printed plan fell before ``semantic_query``, the field that was refused.
_ANSWER_EXCERPT_CHARS: Final = 1000

#: How many of a refusal's reasons it names, the same bound the JSON Schema check uses.
_MAX_REFUSAL_REASONS: Final = 8


def _refusal_reasons(exc: ValidationError) -> str:
    """Each reason a schema refused an answer, with where it applies, in the schema's own words.

    A rule the JSON Schema cannot express, such as a Pydantic model validator, is checked only
    here, after the endpoint has accepted the answer. Its message is the one statement of which
    rule was broken, so a refusal without it names nothing to fix.
    """
    errors = exc.errors(include_url=False)
    return "; ".join(
        f"{'/'.join(str(part) for part in error['loc']) or '<root>'}: {error['msg']}"
        for error in errors[:_MAX_REFUSAL_REASONS]
    )


class ModelClient:
    """Role-routed access to the OpenAI-compatible endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        manifest: Manifest | None = None,
        transport: Transport | None = None,
        cache: ResponseCache | None = None,
        budget: BudgetGuard | None = None,
        timeout: float = _DEFAULT_TIMEOUT,
        max_attempts: int = 1,
        sleep: Callable[[float], None] = time.sleep,
        policy: HostedRequestPolicy | None = None,
    ) -> None:
        # No policy means nothing is sent: every sending method refuses by name until one is
        # attached, here or with `with_policy` where the workspace is known.
        self._policies: tuple[HostedRequestPolicy, ...] = () if policy is None else (policy,)
        self._manifest = manifest or load_manifest()
        self._cache: ResponseCache = cache if cache is not None else NullResponseCache()
        self._budget = budget if budget is not None else BudgetGuard()
        network = transport if transport is not None else HttpxTransport()
        # Checked before the credential is read, so a misconfigured deployment is told about its
        # allowlist rather than about a key it may not need yet. A transport that carries no
        # allowlist is a test double that reaches no network; HttpxTransport always carries one
        # when it built its own client.
        egress = getattr(network, "egress", None)
        if egress is not None:
            try:
                egress.require(self._manifest.base_url)
            except EgressRefused as exc:
                raise EgressConfigurationError(
                    f"the model endpoint {self._manifest.base_url} is not declared in "
                    f"{EGRESS_ALLOWLIST_ENV}, so this client could never reach it. Declare it, or "
                    "do not start a model client in this deployment."
                ) from exc
        # The credential is read here and handed to the chain, which is the only thing that
        # needs it. It is not kept on this object: a client that does not hold a key cannot leak
        # one through a repr, a traceback or a cache entry.
        self._chain = ModelChain(
            manifest=self._manifest,
            transport=network,
            api_key=api_key or api_key_from_env(self._manifest.api_key_env),
            budget=self._budget,
            timeout=timeout,
            max_attempts=max_attempts,
            sleep=sleep,
        )

    # -- introspection ---------------------------------------------------------------------

    @property
    def manifest(self) -> Manifest:
        return self._manifest

    @property
    def budget(self) -> BudgetGuard:
        return self._budget

    @property
    def ledger(self) -> CostLedger:
        return self._budget.ledger

    def __repr__(self) -> str:
        # No credential, not even a prefix of one. A truncated key in a traceback is still a leak.
        return (
            f"ModelClient(base_url={self._manifest.base_url!r}, "
            f"pipeline_version={self._manifest.pipeline_version})"
        )

    # -- policy ------------------------------------------------------------------------------

    def with_policy(self, policy: HostedRequestPolicy) -> ModelClient:
        """This client with ``policy`` added after the ones it already has.

        The copy shares the manifest, the cache, the budget and the chain, so a request it sends
        is counted and cached exactly as one sent by this client. Policies only accumulate: every
        policy attached before still applies, so attaching one can never loosen what an earlier
        attachment decided.
        """
        if not callable(getattr(policy, "admit", None)):
            raise TypeError("a hosted-request policy has an admit method")
        bound = copy.copy(self)
        bound._policies = (*self._policies, policy)
        return bound

    def _admit(
        self, role: Role, payload: dict[str, Any], photographs: Iterable[uuid.UUID]
    ) -> dict[str, Any]:
        """The one point every hosted request passes, before the cache key and before the chain.

        Each policy judges the request as the one before it left it, and the payload that goes on
        carries exactly the texts the last one returned.
        """
        if not self._policies:
            raise NoHostedRequestPolicy(
                f"this client has no hosted-request policy, so it sends nothing to the {role} "
                "role. Attach the workspace's policy with with_policy() where the workspace is "
                "known, or BenchmarkInputs to a client whose inputs carry no account holder's data."
            )
        declared = frozenset(photographs)
        if not all(isinstance(capture, uuid.UUID) for capture in declared):
            raise TypeError("a request declares its photographs by capture id")
        texts, instructions, images = request_parts(payload)
        handoff = ModelHandoff.hosted(self._manifest, role)
        for policy in self._policies:
            admitted = tuple(
                policy.admit(
                    HostedRequest(
                        role=role,
                        handoff=handoff,
                        texts=texts,
                        instructions=instructions,
                        photographs=declared,
                        images=images,
                    )
                )
            )
            if len(admitted) != len(texts):
                raise HostedRequestRefused(
                    f"a policy returned {len(admitted)} texts for a request carrying {len(texts)}"
                )
            texts = admitted
        return admitted_payload(payload, texts)

    def worst_case_seconds(self, role: Role) -> float:
        """The longest one call for this role can take on THIS client, timeouts and retries in.

        Asked by anything that has to decide how long a caller may be silent before the silence
        means something. It is a question about this client rather than about the role, because
        the timeout and the retry count are constructor arguments: the API builds
        ``ModelClient()`` with the defaults and ``exulanica-ingest`` builds one with
        ``max_attempts=3``, and a caller that typed a constant would be right for one of them.
        """
        return self._chain.worst_case_seconds(role)

    # -- request construction --------------------------------------------------------------

    @staticmethod
    def _reject_forbidden(extra: Mapping[str, Any] | None) -> None:
        """Refuse a silently-ignored constraint parameter, wherever it is nested."""

        def scan(node: Any, path: str) -> None:
            if isinstance(node, Mapping):
                for key, value in node.items():
                    if str(key) in _FORBIDDEN_PARAMS:
                        raise GuidedJsonForbiddenError(
                            f"{path}.{key} is accepted by this endpoint and silently ignored: it "
                            "returns HTTP 200 with prose and enforces no schema. Use "
                            "ModelClient.structured, which sends response_format json_schema "
                            "strict, the only mechanism measured to work."
                        )
                    scan(value, f"{path}.{key}")

        scan(extra or {}, "extra")

    def _resolve_max_tokens(self, role: Role, max_tokens: int | None) -> int:
        binding = self._manifest[role]
        floor = binding.min_max_tokens
        if max_tokens is None:
            return binding.default_max_tokens
        if max_tokens < floor:
            raise MaxTokensTooLowError(
                f"max_tokens={max_tokens} is below the floor of {floor} for role {role}. The "
                "models on this chain spend roughly 150 to 215 tokens reasoning before writing "
                "any answer and that cannot be disabled, so a smaller budget returns HTTP 200 "
                'with finish_reason "length" and an empty answer. That reads as a model failure '
                "and is not one."
            )
        return max_tokens

    def _build_payload(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        max_tokens: int,
        temperature: float,
        response_format: Mapping[str, Any] | None,
        extra: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        self._reject_forbidden(extra)
        if response_format is not None:
            kind = response_format.get("type")
            strict = (response_format.get("json_schema") or {}).get("strict")
            if kind != "json_schema" or strict is not True:
                raise GuidedJsonForbiddenError(
                    f"response_format type={kind!r} strict={strict!r} is refused. Only "
                    "{'type': 'json_schema', ..., 'strict': True} enforces a schema on this "
                    "endpoint; json_object returns valid JSON of an arbitrary shape, which is "
                    "not a schema, and canonical state may only be written from a validated one."
                )
            if not isinstance((response_format.get("json_schema") or {}).get("schema"), Mapping):
                # Refused here rather than after the reply arrives, because the schema is what
                # the reply is validated against locally. Without it the call would spend money
                # to produce a payload nothing could check.
                raise GuidedJsonForbiddenError(
                    "response_format carries no schema. The schema is not only sent, it is what "
                    "the reply is validated against locally, so a response_format without one "
                    "would buy an answer that nothing can check. Build it with "
                    "exulanica.models.schema.response_format_for or response_format_for_schema."
                )
        payload: dict[str, Any] = {
            "messages": [dict(m) for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if response_format is not None:
            payload["response_format"] = dict(response_format)
        if extra:
            payload.update(dict(extra))
        return payload

    # -- chat ------------------------------------------------------------------------------

    def chat(
        self,
        role: Role | str,
        messages: Sequence[Mapping[str, Any]],
        *,
        prompt_version: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        response_format: Mapping[str, Any] | None = None,
        extra: Mapping[str, Any] | None = None,
        image_prompt_tokens: int = 0,
        use_cache: bool = True,
        photographs: Iterable[uuid.UUID] = (),
    ) -> ChatResult:
        """One chat completion, routed by role.

        ``prompt_version`` is required rather than defaulted. It is part of the cache key, and a
        default would mean editing a prompt and silently getting the previous prompt's answers,
        which is a full afternoon of confusion for the sake of one keyword argument.

        ``photographs`` names every capture whose bytes or derived text the messages carry. The
        client's policies decide whether they may go; see :mod:`exulanica.models.policy`.
        """
        role = Role(role)
        resolved_max = self._resolve_max_tokens(role, max_tokens)
        payload = self._admit(
            role,
            self._build_payload(
                messages=messages,
                max_tokens=resolved_max,
                temperature=temperature,
                response_format=response_format,
                extra=extra,
            ),
            photographs,
        )

        key = cache_key(
            payload,
            pipeline_version=self._manifest.pipeline_version,
            role=role,
            prompt_version=prompt_version,
        )
        if use_cache:
            cached = self._cache.get(key)
            if cached is not None:
                served = self._manifest.spec(cached["model_id"])
                return result_from_body(
                    role=role,
                    budget=self._budget,
                    endpoint=self._manifest.base_url,
                    spec=served,
                    body=cached["response"],
                    cache_hit=True,
                    used_fallback=bool(cached.get("used_fallback", False)),
                    latency_s=0.0,
                    # A cache hit issued no request. Zero attempts is the honest number and it
                    # is what makes "nothing recomputed, nothing billed" checkable.
                    attempts=0,
                    tried=(served.model_id,),
                    # Revalidated on the way out of the cache, not trusted because it was
                    # validated on the way in. The schema can change under a stored entry, and a
                    # cached payload that no longer satisfies the current schema must fail the
                    # same way a fresh one would.
                    response_format=response_format,
                )

        prompt_chars = sum(len(str(m)) for m in payload["messages"])
        served = self._chain.walk(
            role,
            "/chat/completions",
            payload,
            prompt_chars=prompt_chars,
            extra_prompt_tokens=image_prompt_tokens,
            max_tokens=resolved_max,
        )
        result = result_from_body(
            role=role,
            budget=self._budget,
            endpoint=self._manifest.base_url,
            spec=served.spec,
            body=served.body,
            cache_hit=False,
            used_fallback=served.used_fallback,
            latency_s=served.latency_s,
            attempts=served.attempts,
            tried=served.tried,
            response_format=response_format,
        )
        if use_cache:
            # Only the response is cached. Headers carry the credential and never go to disk.
            self._cache.put(
                key,
                {
                    "model_id": served.spec.model_id,
                    "role": str(role),
                    "pipeline_version": self._manifest.pipeline_version,
                    "prompt_version": prompt_version,
                    "used_fallback": served.used_fallback,
                    "response": served.body,
                },
            )
        return result

    # -- structured output ------------------------------------------------------------------

    def structured(
        self,
        role: Role | str,
        messages: Sequence[Mapping[str, Any]],
        schema: type[T],
        *,
        prompt_version: str,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        extra: Mapping[str, Any] | None = None,
        image_prompt_tokens: int = 0,
        use_cache: bool = True,
        photographs: Iterable[uuid.UUID] = (),
    ) -> StructuredResult[T]:
        """The only path by which model output may become canonical state.

        Returns a validated instance of ``schema`` or raises. There is no partial success and no
        best-effort parse: a body that does not validate is a failure, because a half-parsed
        object is a fact with a piece missing rather than a smaller fact.
        """
        role = Role(role)
        spec = self._manifest[role].primary
        if not spec.supports_json_schema:
            raise StructuredOutputError(
                f"role {role} is not a structured-output role; its primary model is not declared "
                "to support json_schema in the manifest."
            )
        call = self.chat(
            role,
            messages,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            temperature=temperature,
            response_format=response_format_for(schema),
            extra=extra,
            image_prompt_tokens=image_prompt_tokens,
            use_cache=use_cache,
            photographs=photographs,
        )
        # ``chat`` has already refused a body carrying more than one candidate object and
        # validated the survivor against the exact schema it sent, so ``call.payload`` is
        # checked data rather than relayed data. Pydantic then runs over the same payload. The
        # two are not redundant: the JSON Schema check is the one the endpoint was asked to
        # enforce, including additionalProperties false, which Pydantic ignores by default; the
        # Pydantic check is the one this codebase's types depend on. Both are wanted.
        parsed = call.payload
        if parsed is None:  # pragma: no cover - structured always sends a response_format
            raise StructuredOutputError(
                f"{call.model_id} produced no validated payload for {schema.__name__}."
            )
        try:
            value = schema.model_validate(parsed)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"{call.model_id} returned JSON that passed the json_schema check and that "
                f"{schema.__name__} refuses, in {exc.error_count()} place(s): "
                f"{_refusal_reasons(exc)}. Answer was {call.answer[:_ANSWER_EXCERPT_CHARS]!r}"
            ) from exc
        return StructuredResult(value=value, call=call)

    # -- vision ------------------------------------------------------------------------------

    def vision(
        self,
        images: Sequence[bytes | str | Mapping[str, Any]],
        instruction: str,
        *,
        prompt_version: str,
        role: Role | str = Role.VISION,
        schema: type[T] | None = None,
        media_type: str = "image/jpeg",
        system: str | None = None,
        max_tokens: int | None = None,
        image_prompt_tokens: int | None = None,
        use_cache: bool = True,
        photographs: Iterable[uuid.UUID] = (),
    ) -> ChatResult | StructuredResult[T]:
        """One call over one or more photographs.

        The single-photograph path is the primary experience, not a degenerate case of a batch,
        so a bare ``bytes`` is accepted directly and needs no wrapping. ``photographs`` names the
        captures the images are, for the client's policies.

        Nothing here trusts the catalog's ``type`` field. The primary vision model is typed
        ``text2text`` and was runtime-verified to accept an ``image_url`` part and describe the
        image correctly; the preflight asserts on ``use_cases`` for the same reason.
        """
        role = Role(role)
        parts: list[dict[str, Any]] = []
        for image in images:
            if isinstance(image, Mapping):
                parts.append(dict(image))
            else:
                parts.append(image_part(image, media_type=media_type))
        parts.append(text_part(instruction))

        messages: list[dict[str, Any]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": parts})

        # 772 prompt tokens was measured for a 768px image. Used only to size the budget
        # reservation, never for accounting, which reads the reported usage.
        estimated = 800 * len(images) if image_prompt_tokens is None else image_prompt_tokens

        if schema is None:
            return self.chat(
                role,
                messages,
                prompt_version=prompt_version,
                max_tokens=max_tokens,
                image_prompt_tokens=estimated,
                use_cache=use_cache,
                photographs=photographs,
            )
        return self.structured(
            role,
            messages,
            schema,
            prompt_version=prompt_version,
            max_tokens=max_tokens,
            image_prompt_tokens=estimated,
            use_cache=use_cache,
            photographs=photographs,
        )

    # -- embeddings ---------------------------------------------------------------------------

    def embed(
        self,
        texts: Sequence[str],
        *,
        role: Role | str = Role.EMBEDDING,
        prompt_version: str = "embed-v1",
        use_cache: bool = True,
        photographs: Iterable[uuid.UUID] = (),
    ) -> EmbeddingResult:
        """Embed one or more strings.

        This role has no same-tier fallback: it is the only embedding-typed model in the catalog.
        When it is unavailable the client raises rather than substituting a text model, because a
        vector from a different model is not a worse vector, it is a vector in a different space,
        and mixing spaces silently poisons every stored embedding and every retrieval built on
        them.

        ``photographs`` names every capture whose derived text is among ``texts``, for the
        client's policies, which also decide what of each text leaves.
        """
        role = Role(role)
        payload = self._admit(role, {"input": list(texts)}, photographs)
        key = cache_key(
            payload,
            pipeline_version=self._manifest.pipeline_version,
            role=role,
            prompt_version=prompt_version,
        )
        cached = self._cache.get(key) if use_cache else None
        if cached is not None:
            spec = self._manifest.spec(cached["model_id"])
            return embedding_from_body(
                role, spec, cached["response"], budget=self._budget, cache_hit=True
            )

        served = self._chain.walk(
            role,
            "/embeddings",
            payload,
            prompt_chars=sum(len(t) for t in payload["input"]),
            extra_prompt_tokens=0,
            max_tokens=0,
        )
        if use_cache:
            self._cache.put(
                key,
                {
                    "model_id": served.spec.model_id,
                    "role": str(role),
                    "pipeline_version": self._manifest.pipeline_version,
                    "prompt_version": prompt_version,
                    "response": served.body,
                },
            )
        return embedding_from_body(
            role, served.spec, served.body, budget=self._budget, cache_hit=False
        )
