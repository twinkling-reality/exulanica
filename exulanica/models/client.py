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

*   **Every provider's endpoint is checked against the egress allowlist when the client is
    built.** A deployment whose ``EXULANICA_EGRESS_ALLOWLIST`` does not declare the origin of a
    provider serving a manifest-bound role fails here, at startup, instead of at its first
    question. Any other provider the allowlist does not declare, or whose credential is not set,
    is refused by name at every call to it (:attr:`ModelClient.refusals`), never skipped. The
    transport checks every call again; see :mod:`exulanica.models.egress` for what that does and
    does not cover.
*   **A world's choice of model is asked one way only.** :meth:`ModelClient.choose` asks the
    model a world chose for a chosen role to pick one option of a
    :class:`~exulanica.models.choice.ChoiceRequest`, by a mechanism the model's manifest entry
    names as verified, with no fallback and no cache: a choice is an event in the world, asked
    each time it happens.
*   **Every request passes the client's policies before anything else happens to it.** ``chat``
    (and so ``structured`` and ``vision``) and ``embed`` hand the request to each attached policy
    before the cache key is computed, and send exactly the text the policies return. A client with
    no policy refuses to send, by name. A policy is attached with :meth:`ModelClient.with_policy`
    by the code that knows whose data the request carries; policies only accumulate. See
    :mod:`exulanica.models.policy`.

*   **Each role's request is bounded by the role's own timeout**, which the manifest derives
    from the longest latency measured for the role's primary. ``timeout`` overrides it for every
    role, for a caller that reserves wall clock by a timeout of its own; the default is the
    manifest's, and no other number stands in for it.

The client holds a cache, a budget guard and a ledger. All three are optional collaborators with
inert defaults, so a caller gets no caching and generous limits unless it asks, and a test gets
exact ones.
"""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final, TypeVar

from pydantic import BaseModel, ValidationError

from exulanica.models.budget import BudgetGuard
from exulanica.models.cache import CacheKey, NullResponseCache, ResponseCache, cache_key
from exulanica.models.chain import ModelChain
from exulanica.models.choice import ChoiceRefused, ChoiceRequest
from exulanica.models.credentials import api_key_from_env
from exulanica.models.egress import EGRESS_ALLOWLIST_ENV, EgressConfigurationError, EgressRefused
from exulanica.models.errors import (
    GuidedJsonForbiddenError,
    MaxTokensTooLowError,
    ModelError,
    ProviderRefused,
    StructuredOutputError,
)
from exulanica.models.handoff import ModelHandoff
from exulanica.models.manifest import AnsweringMechanism, Manifest, ModelSpec, Role, load_manifest
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
from exulanica.models.results import ChatResult, ChoiceResult, EmbeddingResult, StructuredResult
from exulanica.models.schema import (
    response_format_for,
)
from exulanica.models.transport import HttpxTransport, Transport
from exulanica.models.usage import CallUsage, CostLedger

__all__ = [
    "PROVIDER_CREDENTIAL_ABSENT",
    "PROVIDER_NOT_ADMITTED",
    "ChatResult",
    "ChoiceResult",
    "EmbeddingResult",
    "ModelClient",
    "StructuredResult",
    "api_key_from_env",
    "image_part",
    "text_part",
]

T = TypeVar("T", bound=BaseModel)

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

#: Why a provider is refused by this client, by name: the deployment's allowlist does not declare
#: its origin, or the variable the manifest names for its credential is not set.
PROVIDER_NOT_ADMITTED: Final = "provider_not_admitted"
PROVIDER_CREDENTIAL_ABSENT: Final = "provider_credential_absent"


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
        api_key: str | Mapping[str, str] | None = None,
        manifest: Manifest | None = None,
        transport: Transport | None = None,
        cache: ResponseCache | None = None,
        budget: BudgetGuard | None = None,
        timeout: float | None = None,
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
        #: What every attempt is reserved and recorded through: the guard itself, or the guard
        #: with one request's observers after it (``with_attempts``).
        self._recorder: BudgetGuard = self._budget
        network = transport if transport is not None else HttpxTransport()
        # Checked before any credential is read, so a misconfigured deployment is told about its
        # allowlist rather than about a key it may not need yet. A transport that carries no
        # allowlist is a test double that reaches no network; HttpxTransport always carries one
        # when it built its own client. A provider serving a role the manifest binds must be
        # declared; any other is refused by name at each call, never quietly left out.
        egress = getattr(network, "egress", None)
        bound = {binding.provider for binding in self._manifest.roles.values()}
        self._refusals: dict[str, str] = {}
        for provider in sorted(self._manifest.providers.values(), key=lambda p: p.provider_id):
            if egress is None:
                continue
            try:
                egress.require(provider.base_url)
            except EgressRefused as exc:
                if provider.provider_id in bound:
                    raise EgressConfigurationError(
                        f"the model endpoint {provider.base_url} of provider "
                        f"{provider.provider_id} is not declared in {EGRESS_ALLOWLIST_ENV}, so "
                        "this client could never reach it. Declare it, or do not start a model "
                        "client in this deployment."
                    ) from exc
                self._refusals[provider.provider_id] = PROVIDER_NOT_ADMITTED
        # Each credential is read here and handed to the chain, which is the only thing that
        # needs them. None is kept on this object: a client that does not hold a key cannot leak
        # one through a repr, a traceback or a cache entry. ``api_key`` is one key only for a
        # manifest with one provider; with several, it names each provider's key, so no provider
        # is ever sent another's.
        if isinstance(api_key, str) and len(self._manifest.providers) > 1:
            raise ValueError(
                "a manifest with several providers is given each provider's key by provider, "
                "never one key for all of them"
            )
        keys: dict[str, str] = {}
        for provider in self._manifest.providers.values():
            if provider.provider_id in self._refusals:
                continue
            given = api_key.get(provider.provider_id) if isinstance(api_key, Mapping) else api_key
            try:
                keys[provider.provider_id] = given or api_key_from_env(provider.api_key_env)
            except ModelError:
                if provider.provider_id in bound:
                    raise
                self._refusals[provider.provider_id] = PROVIDER_CREDENTIAL_ABSENT
        self._chain = ModelChain(
            manifest=self._manifest,
            transport=network,
            api_keys=keys,
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

    @property
    def refusals(self) -> Mapping[str, str]:
        """Each provider this client refuses, by key, and why, by name."""
        return MappingProxyType(dict(self._refusals))

    def __repr__(self) -> str:
        # No credential, not even a prefix of one. A truncated key in a traceback is still a leak.
        return (
            f"ModelClient(providers={sorted(self._manifest.providers)!r}, "
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

    def with_attempts(self, observe: Callable[[CallUsage], object]) -> ModelClient:
        """This client, handing ``observe`` every attempt it makes as its budget guard records it.

        For one request's own record of what it paid for: each completed reply, each attempt that
        timed out or failed, and each reply that came back and was then refused as truncated or
        off-schema, which the ledger records before the refusal is raised. The copy shares the
        manifest, the cache, the policies and the budget guard itself, whatever kind of guard it
        is, so it sends exactly what this client would, reserved and counted exactly as it would
        be, and a client with no policy still refuses to send. A request refused before it left,
        by a policy or by the budget, is never an attempt, so ``observe`` is not called for it.
        Only requests sent through the returned copy reach ``observe``, so two requests in flight
        at once, each through its own copy, are never mixed up, whatever else the process sends.
        """
        recorder = _ObservedBudget(self._recorder, observe)
        bound = copy.copy(self)
        bound._recorder = recorder
        bound._chain = self._chain.with_budget(recorder)
        return bound

    def unchanged_by_policies(
        self, role: Role | str, model_id: str, texts: Sequence[str]
    ) -> tuple[bool, ...]:
        """Which of ``texts`` every policy of this client would let leave exactly as it is.

        Asked of the options of a choice before it is built, for ``model_id`` chosen in ``role``,
        so that an option a policy would change is left out of the offer, rather than the whole
        request refused when it is sent (``_admit``). Sends nothing and records nothing; a client
        with no policy refuses as it would to send.
        """
        role = Role(role)
        if not self._policies:
            raise NoHostedRequestPolicy(
                f"this client has no hosted-request policy, so it sends nothing to the {role} role"
            )
        handoff = ModelHandoff.chosen(self._manifest, role, model_id)
        admitted = tuple(texts)
        for policy in self._policies:
            admitted = tuple(
                policy.admit(
                    HostedRequest(
                        role=role,
                        handoff=handoff,
                        texts=admitted,
                        instructions=(),
                        photographs=frozenset(),
                        images=0,
                    )
                )
            )
            if len(admitted) != len(texts):
                raise HostedRequestRefused(
                    f"a policy returned {len(admitted)} texts for a request carrying {len(texts)}"
                )
        return tuple(after == before for after, before in zip(admitted, texts, strict=True))

    def _admit(
        self,
        role: Role,
        payload: dict[str, Any],
        photographs: Iterable[uuid.UUID],
        placeholders: Mapping[uuid.UUID, str] | None = None,
        *,
        handoff: ModelHandoff | None = None,
        choice: ChoiceRequest | None = None,
    ) -> dict[str, Any]:
        """The one point every hosted request passes, before the cache key and before the chain.

        Each policy judges the request as the one before it left it, and the payload that goes on
        carries exactly the texts the last one returned. A choice's options ride in the request's
        function or schema, where no text can be replaced, so each option and the choice's
        description are shown to every policy as texts, the description as an instruction too,
        and the request is refused unless every policy returns them exactly as they came. The
        function's name and its argument's are fixed values (``CHOICE_FUNCTION``,
        ``CHOICE_ARGUMENT``), no caller's text, so no policy is shown them.
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
        record = MappingProxyType(dict(placeholders or {}))
        if not all(
            isinstance(entity, uuid.UUID) and isinstance(label, str)
            for entity, label in record.items()
        ):
            raise TypeError("a request's placeholders map an entity id to its placeholder")
        texts, instructions, images = request_parts(payload, choice)
        carried: tuple[str, ...] = ()
        if choice is not None:
            # Everything a caller wrote that leaves in the request's function or schema: the
            # choice's options and its description.
            carried = (*choice.options, choice.description)
            texts = (*texts, *carried)
            instructions = (*instructions, choice.description)
        if handoff is None:
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
                        placeholders=record,
                    )
                )
            )
            if len(admitted) != len(texts):
                raise HostedRequestRefused(
                    f"a policy returned {len(admitted)} texts for a request carrying {len(texts)}"
                )
            texts = admitted
        if carried:
            if texts[len(texts) - len(carried) :] != carried:
                raise HostedRequestRefused(
                    "a policy would change an option or the description of the choice, and a "
                    "choice is sent exactly as it is offered or not at all"
                )
            texts = texts[: len(texts) - len(carried)]
        return admitted_payload(payload, texts)

    def worst_case_seconds(self, role: Role) -> float:
        """The longest one call for this role can take on THIS client, timeouts and retries in.

        Asked by anything that has to decide how long a caller may be silent before the silence
        means something. It is a question about this client rather than about the role alone,
        because the retry count and any explicit timeout are constructor arguments: the API builds
        ``ModelClient()`` with the manifest's timeouts and one attempt and ``exulanica-ingest``
        builds one with ``max_attempts=3``, and a caller that typed a constant would be right for
        one of them.
        """
        return self._chain.worst_case_seconds(role)

    # -- providers and the cache ---------------------------------------------------------------

    def _endpoint(self, spec: ModelSpec) -> str:
        """The endpoint of the provider serving ``spec``, as results record it."""
        return self._manifest.provider(spec.provider).base_url

    def _key(
        self, payload: Mapping[str, Any], spec: ModelSpec, role: Role, prompt_version: str
    ) -> CacheKey:
        return cache_key(
            payload,
            provider=spec.provider,
            model_id=spec.model_id,
            pipeline_version=self._manifest.pipeline_version,
            role=role,
            prompt_version=prompt_version,
        )

    def _cached(
        self, payload: Mapping[str, Any], addressed: ModelSpec, role: Role, prompt_version: str
    ) -> dict[str, Any] | None:
        """The stored answer of the model a call addresses, never another model's.

        Looked up under the addressed model's key, and refused when the entry records another
        model, so no path serves one model's answer for another.
        """
        cached = self._cache.get(self._key(payload, addressed, role, prompt_version))
        if cached is None or cached.get("model_id") != addressed.model_id:
            return None
        return cached

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
        placeholders: Mapping[uuid.UUID, str] | None = None,
    ) -> ChatResult:
        """One chat completion, routed by role.

        ``prompt_version`` is required rather than defaulted. It is part of the cache key, and a
        default would mean editing a prompt and silently getting the previous prompt's answers,
        which is a full afternoon of confusion for the sake of one keyword argument.

        ``photographs`` names every capture whose bytes or derived text the messages carry. The
        client's policies decide whether they may go; see :mod:`exulanica.models.policy`.
        ``placeholders`` is the placeholder the caller already gave each entity the messages may
        name, which a policy writes for a name it withholds.
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
            placeholders,
        )

        addressed = self._manifest[role].primary
        if use_cache:
            cached = self._cached(payload, addressed, role, prompt_version)
            if cached is not None:
                served = self._manifest.spec(cached["model_id"])
                return result_from_body(
                    role=role,
                    budget=self._recorder,
                    endpoint=self._endpoint(served),
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
            budget=self._recorder,
            endpoint=self._endpoint(served.spec),
            spec=served.spec,
            body=served.body,
            cache_hit=False,
            used_fallback=served.used_fallback,
            latency_s=served.latency_s,
            attempts=served.attempts,
            tried=served.tried,
            response_format=response_format,
            usd_bound=served.reserved_usd,
        )
        if use_cache:
            # Only the response is cached, under the model that gave it. Headers carry the
            # credential and never go to disk.
            self._cache.put(
                self._key(payload, served.spec, role, prompt_version),
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
        placeholders: Mapping[uuid.UUID, str] | None = None,
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
            placeholders=placeholders,
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

    # -- a world's choice ------------------------------------------------------------------------

    def choose(
        self,
        role: Role | str,
        model_id: str,
        messages: Sequence[Mapping[str, Any]],
        request: ChoiceRequest,
        *,
        mechanism: AnsweringMechanism,
        prompt_version: str,
        timeout: float,
        max_tokens: int | None = None,
        temperature: float = 0.0,
        keep_usd: Decimal = Decimal(0),
        keep_calls: int = 0,
    ) -> ChoiceResult:
        """One option of ``request``, picked by the model a world chose for a chosen role.

        The model must be one the manifest offers the role, asked by a mechanism its entry names
        as verified, at a provider this client admits and holds a credential for; anything else is
        refused by name before a request is built. There is no fallback, because a choice names
        one model, and no cache, because a choice is an event asked each time it happens. The
        reply must be exactly one of the options, or :class:`ChoiceRefused` says why it is not.
        ``timeout`` bounds the wait, as the caller's contract gives it, and ``keep_usd`` and
        ``keep_calls`` are the part of this process's budget the ask must leave for other work.
        """
        role = Role(role)
        spec = self._manifest.offered(role, model_id)
        if mechanism not in spec.answering:
            raise ChoiceRefused(
                f"{model_id} is not verified to answer by {mechanism}; its manifest entry names "
                f"{sorted(str(m) for m in spec.answering)}"
            )
        refusal = self._refusals.get(spec.provider)
        if refusal is not None:
            raise ProviderRefused(
                f"provider {spec.provider} is refused by this process ({refusal}), so nothing is "
                f"sent to {model_id}",
                provider=spec.provider,
                reason=refusal,
            )
        floor = spec.min_max_tokens or 0
        resolved = floor if max_tokens is None else max_tokens
        if resolved < floor:
            raise MaxTokensTooLowError(
                f"max_tokens={resolved} is below {model_id}'s floor of {floor}; it would return "
                "HTTP 200 with an empty answer, which reads as a model failure and is not one."
            )
        response_format = (
            request.response_format() if mechanism is AnsweringMechanism.JSON_SCHEMA else None
        )
        built = self._build_payload(
            messages=messages,
            max_tokens=resolved,
            temperature=temperature,
            response_format=response_format,
            extra=None,
        )
        if mechanism is AnsweringMechanism.TOOL_CALL:
            built.update(request.payload_fields(mechanism))
        admitted = self._admit(
            role,
            built,
            (),
            handoff=ModelHandoff.chosen(self._manifest, role, model_id),
            choice=request,
        )
        served = self._chain.walk_one(
            role,
            spec,
            "/chat/completions",
            admitted,
            timeout=timeout,
            prompt_chars=sum(len(str(m)) for m in admitted["messages"]),
            extra_prompt_tokens=0,
            max_tokens=resolved,
            keep_usd=keep_usd,
            keep_calls=keep_calls,
        )
        try:
            result = result_from_body(
                role=role,
                budget=self._recorder,
                endpoint=self._endpoint(spec),
                spec=served.spec,
                body=served.body,
                cache_hit=False,
                used_fallback=False,
                latency_s=served.latency_s,
                attempts=served.attempts,
                tried=served.tried,
                response_format=response_format,
                usd_bound=served.reserved_usd,
                choice_request=request if mechanism is AnsweringMechanism.TOOL_CALL else None,
            )
        except StructuredOutputError as exc:
            # Under a schema, an answer outside the enum fails the schema before the choice reads
            # it; it is the same refusal as a function's argument outside it, and is named so.
            if mechanism is AnsweringMechanism.JSON_SCHEMA and not isinstance(exc, ChoiceRefused):
                raise ChoiceRefused(
                    f"{model_id} did not answer with one of the offered actions"
                ) from exc
            raise
        if result.payload is None:  # pragma: no cover - both mechanisms return a checked payload
            raise ChoiceRefused(f"{model_id} returned no answer to the choice")
        return ChoiceResult(label=request.answer(result.payload), mechanism=mechanism, call=result)

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
        addressed = self._manifest[role].primary
        cached = self._cached(payload, addressed, role, prompt_version) if use_cache else None
        if cached is not None:
            spec = self._manifest.spec(cached["model_id"])
            return embedding_from_body(
                role,
                spec,
                cached["response"],
                budget=self._recorder,
                cache_hit=True,
                used_fallback=bool(cached.get("used_fallback", False)),
                attempts=0,
                tried=(spec.model_id,),
            )

        served = self._chain.walk(
            role,
            "/embeddings",
            payload,
            prompt_chars=sum(len(t) for t in payload["input"]),
            extra_prompt_tokens=0,
            max_tokens=0,
        )
        # Recorded, and checked, before it is cached: a cache that cannot be written must not
        # keep the call's reservation or the call out of the ledger, and only a whole answer is
        # stored.
        result = embedding_from_body(
            role,
            served.spec,
            served.body,
            budget=self._recorder,
            cache_hit=False,
            used_fallback=served.used_fallback,
            latency_s=served.latency_s,
            attempts=served.attempts,
            tried=served.tried,
            usd_bound=served.reserved_usd,
        )
        if use_cache:
            self._cache.put(
                self._key(payload, served.spec, role, prompt_version),
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


class _ObservedBudget(BudgetGuard):
    """A budget guard, and one request's observer told of each attempt after the guard records it.

    Not a second guard: every reservation and record goes to ``guard`` itself, whatever its kind
    (a lens guard keeps its own counters outside the ledger), and the observer only hears what the
    guard recorded. The chain and the response path ask a guard for ``reserve`` and ``record``;
    anything else asked of this wrapper is answered by the guard it wraps.
    """

    def __init__(self, guard: BudgetGuard, observe: Callable[[CallUsage], object]) -> None:
        # Deliberately not BudgetGuard.__init__: this holds no ceiling and no ledger of its own.
        self._guard = guard
        self._observe = observe

    def __getattr__(self, name: str) -> Any:
        # Asked only for what this instance does not hold. Before `_guard` is set (a copy, a
        # deepcopy or an unpickle builds the instance first), there is nothing to ask, and asking
        # `self._guard` here would ask this method again, without end.
        try:
            guard = object.__getattribute__(self, "_guard")
        except AttributeError:
            raise AttributeError(name) from None
        return getattr(guard, name)

    def __copy__(self) -> _ObservedBudget:
        # The same guard, observed the same way: a copy of the guard would be a second ceiling.
        return _ObservedBudget(self._guard, self._observe)

    def reserve(self, *args: Any, **kwargs: Any) -> Decimal:
        return self._guard.reserve(*args, **kwargs)

    def release(self, reserved: Decimal) -> None:
        self._guard.release(reserved)

    def record(self, usage: CallUsage, *, released: Decimal | None = None) -> CallUsage:
        recorded = self._guard.record(usage, released=released)
        self._observe(usage)
        return recorded
