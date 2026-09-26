"""Reaching the endpoint for a role: retry, failover, and the budget each attempt is charged to.

A caller never names a model. The manifest names models, a role resolves to a chain of them, and
this walks it. Three policies live here and nowhere else, each because of something measured:

*   **Fallback fires on a 404-class error and nothing else.** A withdrawn identifier is the one
    failure a different model can fix. A 429, a 500 or a timeout is the same model having a bad
    moment, and switching models in response would hide a platform incident behind a quality
    regression that nobody would ever attribute correctly.
*   **Retries are off by default.** The platform states plainly that Serverless AI "does not
    provide automatic retry, recovery, or redundancy mechanisms", so retries exist, but a caller
    whose operation is not idempotent gets exactly one request unless it asks otherwise.
*   **Every attempt is reserved against the budget separately**, so a retry storm is spend the
    guard can see rather than spend it discovers afterwards. **And every attempt that fails is
    recorded**, priced by whether it left: a timeout, a dropped connection or an error status is a
    row charged at its reservation with its cost stated unknown, and a connection never made is a
    row that cost nothing. Before this, a failed attempt reserved and recorded nothing, so a run of
    timeouts spent no budget and counted no calls.
*   **Each role waits for its own timeout**, read from the manifest, where it is derived from the
    longest latency measured for the role's primary. A caller may pass one explicit timeout for
    every role instead, as a lens budget does for the per-call timeout it reserves wall clock by.
*   **Each request goes to its model's provider**, at the provider's own endpoint with the
    provider's own credential, both the manifest's. A model a world chose is walked alone, with
    no fallback and the timeout its caller's contract gives: a choice names one model, and a
    withdrawn one is reported as withdrawn, never answered by another.

Split out of the client because these are decisions about the network, and the client's own job
is what a request means and whether a reply may be believed. A change to the retry policy should
not be a change to the module that decides whether a model's answer enters canonical state.
"""

from __future__ import annotations

import copy
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from exulanica.models.budget import BudgetGuard
from exulanica.models.errors import (
    ModelUnavailableError,
    NoFallbackError,
    ProviderRefused,
    TransportError,
)
from exulanica.models.manifest import Manifest, ModelSpec, Role
from exulanica.models.transport import HttpResponse, Transport
from exulanica.models.usage import CallUsage, usd_string

__all__ = ["ChainResponse", "ModelChain"]

#: Statuses worth issuing the identical request again for. Everything else the endpoint
#: understood and refused, and it will refuse it identically forever. 404 is absent on purpose:
#: a withdrawn identifier is answered by the fallback, never by asking again.
_RETRYABLE_STATUS: Final = frozenset({408, 409, 425, 429, 500, 502, 503, 504})

#: Provider phrasing for "that identifier does not exist". Some deprecations answer 400 rather
#: than 404, so the message is inspected as well as the status.
_NOT_FOUND_PHRASES: Final = (
    "does not exist",
    "not found",
    "unknown model",
    "no such model",
    "invalid model",
    "model_not_found",
)


@dataclass(frozen=True, slots=True)
class ChainResponse:
    """One body, and everything about how it was obtained.

    A named shape rather than a tuple because six positional values is five chances to read one
    in the wrong slot, and two of them are integers that mean different things.
    """

    body: dict[str, Any]
    spec: ModelSpec
    used_fallback: bool
    latency_s: float
    #: HTTP requests actually issued, retries and failover attempts included.
    attempts: int
    #: Every identifier tried, in order, including the ones that failed.
    tried: tuple[str, ...]
    #: What the answering attempt was reserved at: the most it can have cost. A reply whose usage
    #: omits a priced count is charged this rather than a count's default zero.
    reserved_usd: Decimal = Decimal(0)


class ModelChain:
    """The endpoint, reached by role rather than by model identifier."""

    def __init__(
        self,
        *,
        manifest: Manifest,
        transport: Transport,
        api_keys: Mapping[str, str],
        budget: BudgetGuard,
        timeout: float | None,
        max_attempts: int,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if timeout is not None and not timeout > 0:
            raise ValueError(f"an explicit timeout must be positive, got {timeout!r}")
        self._manifest = manifest
        self._transport = transport
        # Each provider's credential, by provider key. A provider with none here is refused by
        # name before anything is sent to it.
        self._api_keys = dict(api_keys)
        self._budget = budget
        self._timeout = timeout
        self._max_attempts = max_attempts
        self._sleep = sleep

    def __repr__(self) -> str:
        # No credential, not even a prefix of one. A truncated key in a traceback is still a leak.
        return f"ModelChain(providers={sorted(self._manifest.providers)!r})"

    def with_budget(self, budget: BudgetGuard) -> ModelChain:
        """This chain, reserving and recording every attempt against ``budget`` instead."""
        bound = copy.copy(self)
        bound._budget = budget
        return bound

    def _headers(self, spec: ModelSpec) -> dict[str, str]:
        key = self._api_keys.get(spec.provider)
        if key is None:
            variable = self._manifest.provider(spec.provider).api_key_env
            raise ProviderRefused(
                f"no credential for provider {spec.provider}: {variable} is not set, so nothing "
                f"is sent to {spec.model_id}",
                provider=spec.provider,
                reason="provider_credential_absent",
            )
        return {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @staticmethod
    def _is_model_missing(response: HttpResponse) -> bool:
        """404-class: this identifier does not exist. The only trigger for a fallback."""
        if response.status_code == 404:
            return True
        if response.status_code in (400, 422):
            message = response.error_message().lower()
            return "model" in message and any(p in message for p in _NOT_FOUND_PHRASES)
        return False

    def timeout_seconds(self, role: Role) -> float:
        """How long one request for ``role`` may take: the explicit timeout, else the manifest's."""
        if self._timeout is not None:
            return self._timeout
        return float(self._manifest[role].timeout_seconds)

    def _post(
        self, path: str, payload: Mapping[str, Any], spec: ModelSpec, *, timeout: float
    ) -> dict[str, Any]:
        url = f"{self._manifest.provider(spec.provider).base_url}{path}"
        response = self._transport.post_json(
            url, headers=self._headers(spec), payload=payload, timeout=timeout
        )
        if self._is_model_missing(response):
            raise ModelUnavailableError(
                f"{spec.model_id} is not available: HTTP {response.status_code}. "
                f"{response.error_message()[:200]}",
                model_id=spec.model_id,
                status_code=response.status_code,
            )
        if not response.ok:
            raise TransportError(
                f"HTTP {response.status_code} from {path} for {spec.model_id}: "
                f"{response.error_message()[:300]}",
                retryable=response.status_code in _RETRYABLE_STATUS,
                reached_provider=True,
            )
        try:
            body = response.json_body()
        except TransportError as exc:
            raise TransportError(str(exc), retryable=exc.retryable, reached_provider=True) from exc
        if not isinstance(body, dict):
            raise TransportError(
                f"{path} returned a {type(body).__name__}, expected an object",
                retryable=False,
                reached_provider=True,
            )
        return body

    def worst_case_seconds(self, role: Role) -> float:
        """The longest one :meth:`walk` of this role can take, from this chain's own numbers.

        A caller outside the models package cannot compute this and must not guess it: it is the
        product of the manifest's chain length, the transport timeout and the retry count, and
        two of those three are constructor arguments that differ between the API's client and
        the ingest CLI's. :mod:`exulanica.ingest.worker` needs it to decide how long a claimant may
        be silent before its silence means something.

        The arithmetic follows :meth:`walk` exactly. A ``ModelUnavailableError`` is not retried,
        so every model before the last costs one request; the last one costs a full retry budget,
        because a retry exhaustion raises out of ``walk`` rather than falling through to a
        fallback. Backoff is added for the gaps between those retries, at its ceiling rather than
        its jittered value.

        **It bounds the wall clock** through :class:`~exulanica.models.transport.HttpxTransport`,
        which ends every request at its timeout however the response stalls, name resolution
        included. A transport that does not enforce a deadline, such as a test double, is bounded
        only by what it does.
        """
        chain = self._manifest[role].chain
        timeout = self.timeout_seconds(role)
        return (len(chain) - 1 + self._max_attempts) * timeout + self._backoff_ceiling()

    def _backoff_ceiling(self) -> float:
        """The unjittered sum of the sleeps between ``max_attempts`` requests to one model."""
        return sum(min(8.0, 0.5 * (2 ** (attempt - 1))) for attempt in range(1, self._max_attempts))

    def _backoff(self, attempt: int) -> None:
        """Exponential with jitter.

        Jitter matters even for a single client. A corpus pass is one call per photograph, and
        synchronised retries after a rate limit are how a rate limit becomes an outage.
        """
        delay = min(8.0, 0.5 * (2 ** (attempt - 1)))
        self._sleep(delay * (0.5 + random.random() / 2))

    def _post_with_retries(
        self,
        path: str,
        payload: Mapping[str, Any],
        spec: ModelSpec,
        *,
        role: Role,
        prompt_chars: int,
        extra_prompt_tokens: int,
        max_tokens: int,
        used_fallback: bool,
        timeout: float,
        keep_usd: Decimal = Decimal(0),
        keep_calls: int = 0,
    ) -> tuple[dict[str, Any], int, Decimal]:
        """One model, up to ``max_attempts`` requests. Returns the body, requests issued, and the
        answering attempt's reservation.

        Only a retryable status or a failed connection is retried. A ``ModelUnavailableError`` is
        never retried here: the same withdrawn identifier will be withdrawn again, and the answer
        to it is the fallback, one level up. Each attempt is reserved against the budget
        separately, so a retry storm is spend the guard can see, and each one that fails is
        recorded against it, so the storm is also spend the ledger shows.
        """
        for attempt in range(1, self._max_attempts + 1):
            reserved = self._budget.reserve(
                spec,
                role=role,
                prompt_chars=prompt_chars,
                max_tokens=max_tokens,
                extra_prompt_tokens=extra_prompt_tokens,
                **(
                    {"keep_usd": keep_usd, "keep_calls": keep_calls}
                    if keep_usd or keep_calls
                    else {}
                ),
            )
            started = time.monotonic()
            try:
                return self._post(path, payload, spec, timeout=timeout), attempt, reserved
            except ModelUnavailableError as exc:
                self._record_failure(
                    role, spec, exc, reserved, started, used_fallback, reached_provider=True
                )
                raise
            except TransportError as exc:
                usage = self._record_failure(
                    role, spec, exc, reserved, started, used_fallback, exc.reached_provider
                )
                if not exc.retryable or attempt == self._max_attempts:
                    raise _with_cost(exc, usage, attempt) from exc
                self._backoff(attempt)
            except BaseException:
                # Refused before it left (a credential, an allowlist): nothing to record, and
                # the reservation it held is given back.
                self._budget.release(reserved)
                raise
        raise AssertionError("unreachable: the last attempt either returns or raises")

    def _record_failure(
        self,
        role: Role,
        spec: ModelSpec,
        exc: Exception,
        reserved: Decimal,
        started: float,
        used_fallback: bool,
        reached_provider: bool | None,
    ) -> CallUsage:
        return self._budget.record(
            CallUsage.failed(
                role=role,
                spec=spec,
                reached_provider=reached_provider,
                timed_out=bool(getattr(exc, "timed_out", False)),
                failure=str(exc)[:300],
                usd_bound=reserved,
                used_fallback=used_fallback,
                latency_s=time.monotonic() - started,
            ),
            released=reserved,
        )

    def walk(
        self,
        role: Role,
        path: str,
        payload: Mapping[str, Any],
        *,
        prompt_chars: int,
        extra_prompt_tokens: int,
        max_tokens: int,
    ) -> ChainResponse:
        """Try the primary, then the fallback. Returns the body and which model served it."""
        binding = self._manifest[role]
        timeout = self.timeout_seconds(role)
        failures: list[str] = []
        tried: list[str] = []
        attempts = 0
        for index, spec in enumerate(binding.chain):
            tried.append(spec.model_id)
            started = time.monotonic()
            try:
                body, made, reserved = self._post_with_retries(
                    path,
                    {**payload, "model": spec.model_id},
                    spec,
                    role=role,
                    prompt_chars=prompt_chars,
                    extra_prompt_tokens=extra_prompt_tokens,
                    max_tokens=max_tokens,
                    used_fallback=index > 0,
                    timeout=timeout,
                )
            except ModelUnavailableError as exc:
                # Not retried, so exactly one request was issued against this identifier.
                attempts += 1
                failures.append(str(exc))
                continue
            return ChainResponse(
                body=body,
                spec=spec,
                used_fallback=index > 0,
                latency_s=time.monotonic() - started,
                attempts=attempts + made,
                tried=tuple(tried),
                reserved_usd=reserved,
            )

        detail = "; ".join(failures)
        if binding.fallback is None:
            raise NoFallbackError(
                f"role {role} has no declared fallback and its only model is unavailable. "
                f"{binding.rationale} Original failure: {detail}"
            )
        raise NoFallbackError(
            f"role {role}: every model in the chain is unavailable. This is what a deprecation "
            f"round looks like. Run the preflight against the live catalog. Failures: {detail}"
        )

    def walk_one(
        self,
        role: Role,
        spec: ModelSpec,
        path: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
        prompt_chars: int,
        extra_prompt_tokens: int,
        max_tokens: int,
        keep_usd: Decimal = Decimal(0),
        keep_calls: int = 0,
    ) -> ChainResponse:
        """Reach one model a world chose, with no fallback, waiting at most ``timeout`` seconds.

        An explicit timeout this chain was built with bounds it as well. A withdrawn model raises
        :class:`ModelUnavailableError` to the caller, whose contract decides what happens next.
        ``keep_usd`` and ``keep_calls`` are the part of the process's budget the call must leave.
        """
        if not timeout > 0:
            raise ValueError(f"a chosen model's timeout must be positive, got {timeout!r}")
        bound = timeout if self._timeout is None else min(timeout, self._timeout)
        started = time.monotonic()
        body, made, reserved = self._post_with_retries(
            path,
            {**payload, "model": spec.model_id},
            spec,
            role=role,
            prompt_chars=prompt_chars,
            extra_prompt_tokens=extra_prompt_tokens,
            max_tokens=max_tokens,
            used_fallback=False,
            timeout=bound,
            keep_usd=keep_usd,
            keep_calls=keep_calls,
        )
        return ChainResponse(
            body=body,
            spec=spec,
            used_fallback=False,
            latency_s=time.monotonic() - started,
            attempts=made,
            tried=(spec.model_id,),
            reserved_usd=reserved,
        )


def _with_cost(exc: TransportError, usage: CallUsage, attempts: int) -> TransportError:
    """The same failure, saying what the ledger charged for it, so a refusal carries its cost."""
    if usage.usd_known:
        cost = f"it cost nothing: the request never reached {usage.model_id}"
    else:
        cost = (
            f"its cost is unknown, since the provider may bill a request it received, so this "
            f"process charged the most it can have cost, ${usd_string(usage.usd)}, to its budget"
        )
    return TransportError(
        f"{exc} ({attempts} attempt{'s' if attempts != 1 else ''}; for the last, {cost})",
        retryable=exc.retryable,
        timed_out=exc.timed_out,
        reached_provider=exc.reached_provider,
    )
