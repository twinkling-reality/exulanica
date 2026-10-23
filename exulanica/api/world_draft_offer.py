"""A world draft's operation ceiling, derived from its stages and fresh provider metadata.

Prices are inputs, not an operation estimate. Each request is priced at the most it can hold: its
role's request envelope of input (:mod:`exulanica.models.request_envelopes`, the bytes the chain
refuses a request beyond, never more than the model's context window) and its answer limit. The
sum is served as a reservation ceiling, never as expected or invoiced spend: the worst case the
draft's calls can reach, not every model's whole context.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from decimal import ROUND_CEILING, Decimal
from typing import Any

from exulanica.errors import CanonicalisationError
from exulanica.models.manifest import Manifest, Role
from exulanica.models.provider_catalog import ProviderPrice
from exulanica.models.request_envelopes import request_bytes_at_most
from exulanica.models.usage import USD_QUANTUM
from exulanica.selection import (
    kind_drafting,
    look_choosing,
    setting_choosing,
    tool_choosing,
    world_drafting,
)
from exulanica.world.model_probe_contract import seal
from exulanica.world.world_draft_contract import QUOTE_PROFILE
from exulanica.world.world_tools import world_tools

PROFILE = QUOTE_PROFILE
PRICE_SECONDS = 60


class WorldDraftOfferRefused(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def stages() -> dict[str, tuple[tuple[Role, int], ...]]:
    """Both actual tool paths, with their native schema-repair limits."""
    common = ((tool_choosing.CHOOSER_ROLE, tool_choosing.ATTEMPTS),)
    optional = (
        (look_choosing.CHOOSER_ROLE, look_choosing.ATTEMPTS),
        (setting_choosing.CHOOSER_ROLE, setting_choosing.ATTEMPTS),
    )
    drafts = {
        "kind": (kind_drafting.DRAFTER_ROLE, kind_drafting.DRAFT_ATTEMPTS),
        "specification": (world_drafting.DRAFTER_ROLE, world_drafting.DRAFT_ATTEMPTS),
    }
    return {
        tool: (*common, drafts[tool], *optional)
        for tool in sorted({t.drafter for t in world_tools()})
    }


def calls_at_most(manifest: Manifest, maximum_wire_attempts: Callable[[Role], int]) -> int:
    """The most dispatches one draft can make, counted as :func:`operation_sheet` counts them and
    with no prices needed: each stage's schema attempts times its wire attempts (every fallback and
    retry), summed along each tool's path for each provider, the larger path for each provider,
    then the providers summed."""
    most: dict[str, int] = {}
    for path in stages().values():
        along: dict[str, int] = {}
        for role, repairs in path:
            provider = manifest[role].provider
            along[provider] = along.get(provider, 0) + repairs * maximum_wire_attempts(role)
        for provider, calls in along.items():
            most[provider] = max(most.get(provider, 0), calls)
    return sum(most.values())


def operation_sheet(
    manifest: Manifest,
    prices: Mapping[tuple[str, str], ProviderPrice],
    read_at: Mapping[str, dt.datetime],
    maximum_wire_attempts: Callable[[Role], int],
    *,
    now: dt.datetime,
) -> dict[str, Any]:
    """A finite envelope for every native path, including retries and fallbacks, and its largest
    step: ``step_usd_at_most``, the dearest single dispatch's worst case, overall and for each
    provider, the least a draft's bound must leave for it to send anything.

    Each per-model reservation prices the stage's request envelope of input (its role's, never
    more than the model's current context; a role with none is priced at that whole context) plus
    the actual stage output bound. The stage states the envelope (``request_bytes_at_most``), which
    the draft's chain refuses any request beyond. Separate provider ceilings sum to the accepted
    total; switching paths or providers cannot obtain another copy of that total after a restart.
    """
    if now.tzinfo is None:
        raise WorldDraftOfferRefused("world_draft_price_unavailable")
    paths = []
    rates: dict[tuple[str, str], dict[str, Any]] = {}
    provider_caps: dict[str, Decimal] = {}
    provider_calls: dict[str, int] = {}
    # The dearest single dispatch each provider can be sent: what one step of the draft holds.
    provider_steps: dict[str, Decimal] = {}
    for tool, stages_ in stages().items():
        path_caps: dict[str, Decimal] = {}
        path_calls: dict[str, int] = {}
        entries = []
        for role, repairs in stages_:
            binding = manifest[role]
            answer = (
                binding.default_max_tokens
                if binding.max_tokens is None
                else binding.max_tokens.value
            )
            if answer < binding.min_max_tokens:
                raise WorldDraftOfferRefused("world_draft_output_limit_unavailable")
            wire = maximum_wire_attempts(role)
            if type(wire) is not int or wire < len(binding.chain):
                raise WorldDraftOfferRefused("world_draft_attempt_limit_unavailable")
            envelope = request_bytes_at_most(role)
            inputs = []
            costs = []
            for spec in binding.chain:
                key = (spec.provider, spec.model_id)
                price, at = prices.get(key), read_at.get(spec.provider)
                if (
                    price is None
                    or at is None
                    or at.tzinfo is None
                    or not 0 <= (now - at).total_seconds() < PRICE_SECONDS
                ):
                    raise WorldDraftOfferRefused("world_draft_price_unavailable")
                if (
                    price.model_id != spec.model_id
                    or type(price.context_window_tokens) is not int
                    or min(spec.context_window_tokens, price.context_window_tokens) <= answer
                    or not price.response_sha256
                    or any(
                        not amount.is_finite() or amount < 0
                        for amount in (price.input_usd_per_mtok, price.output_usd_per_mtok)
                    )
                ):
                    raise WorldDraftOfferRefused("world_draft_price_unavailable")
                context = min(spec.context_window_tokens, price.context_window_tokens)
                most_in = context if envelope is None else min(envelope, context)
                cost = (
                    (
                        Decimal(most_in) * price.input_usd_per_mtok
                        + Decimal(answer) * price.output_usd_per_mtok
                    )
                    / Decimal(1_000_000)
                ).quantize(USD_QUANTUM, rounding=ROUND_CEILING)
                inputs.append(most_in)
                costs.append(cost)
                rates[key] = dict(
                    provider=spec.provider,
                    model_id=spec.model_id,
                    input_usd_per_mtok=str(price.input_usd_per_mtok),
                    output_usd_per_mtok=str(price.output_usd_per_mtok),
                    input_tokens_at_most=min(
                        spec.context_window_tokens, price.context_window_tokens
                    ),
                    metadata_context_window_tokens=price.context_window_tokens,
                    rate_response_sha256=price.response_sha256,
                    rate_read_at=at.isoformat(),
                )
            count = repairs * wire
            cost = max(costs) * count
            provider = binding.provider
            provider_steps[provider] = max(provider_steps.get(provider, Decimal(0)), max(costs))
            path_caps[provider] = path_caps.get(provider, Decimal(0)) + cost
            path_calls[provider] = path_calls.get(provider, 0) + count
            entries.append(
                dict(
                    role=str(role),
                    schema_attempts_at_most=repairs,
                    wire_attempts_per_request_at_most=wire,
                    dispatches_at_most=count,
                    request_bytes_at_most=min(inputs) if envelope is None else envelope,
                    answer_tokens_at_most=answer,
                    models=[
                        dict(provider=s.provider, model_id=s.model_id, reservation_usd=str(c))
                        for s, c in zip(binding.chain, costs, strict=True)
                    ],
                    ceiling_usd=str(cost),
                )
            )
        paths.append(dict(tool=tool, stages=entries))
        for provider, cap in path_caps.items():
            provider_caps[provider] = max(provider_caps.get(provider, Decimal(0)), cap)
            provider_calls[provider] = max(provider_calls.get(provider, 0), path_calls[provider])
    total = sum(provider_caps.values(), Decimal(0))
    if total <= 0 or not total.is_finite():
        raise WorldDraftOfferRefused("world_draft_price_unavailable")
    return seal(
        dict(
            profile=PROFILE,
            pipeline_version=manifest.pipeline_version,
            basis="request_envelope_ceiling",
            estimate_is_expected_spend=False,
            read_at=now.isoformat(),
            expires_at=min(
                at + dt.timedelta(seconds=PRICE_SECONDS) for at in read_at.values()
            ).isoformat(),
            maximum_usd=str(total),
            step_usd_at_most=str(max(provider_steps.values())),
            calls_at_most=sum(provider_calls.values()),
            providers=[
                dict(
                    provider=p,
                    ceiling_usd=str(provider_caps[p]),
                    max_calls=provider_calls[p],
                    step_usd_at_most=str(provider_steps[p]),
                )
                for p in sorted(provider_caps)
            ],
            prices=[rates[k] for k in sorted(rates)],
            paths=paths,
        )
    )


def read_operation_sheet(client: Any) -> dict[str, Any]:
    """Metadata-only rate reads through the admitted client; no model is asked."""
    providers = {client.manifest[role].provider for rows in stages().values() for role, _ in rows}
    prices = {}
    at = {}
    try:
        for provider in sorted(providers):
            quoted = client.provider_prices(provider)
            at[provider] = dt.datetime.now(dt.UTC)
            prices.update({(provider, key): price for key, price in quoted.items()})
        return operation_sheet(
            client.manifest, prices, at, client.maximum_wire_attempts, now=dt.datetime.now(dt.UTC)
        )
    except WorldDraftOfferRefused:
        raise
    except Exception as failed:
        raise WorldDraftOfferRefused("world_draft_price_unavailable") from failed


def confirm_operation(client: Any, offered: Mapping[str, Any] | None) -> dict[str, Any]:
    """Recheck a sheet's exact economic/configuration terms, without moving its expiry."""
    if offered is None:
        return read_operation_sheet(client)
    now = dt.datetime.now(dt.UTC)
    try:
        if offered.get("profile") != PROFILE or seal(dict(offered))[
            "document_sha256"
        ] != offered.get("document_sha256"):
            raise WorldDraftOfferRefused("world_draft_operation_changed")
        started = dt.datetime.fromisoformat(offered["read_at"])
        ends = dt.datetime.fromisoformat(offered["expires_at"])
        if (
            started.tzinfo is None
            or started > now
            or ends > started + dt.timedelta(seconds=PRICE_SECONDS)
        ):
            raise WorldDraftOfferRefused("world_draft_operation_changed")
        if now >= ends:
            raise WorldDraftOfferRefused("world_draft_price_expired")
        fresh = read_operation_sheet(client)

        def economic(q: Mapping[str, Any]) -> dict[str, Any]:
            return {
                k: v
                for k, v in q.items()
                if k not in {"read_at", "expires_at", "document_sha256", "prices"}
            }

        if economic(fresh) != economic(offered):
            raise WorldDraftOfferRefused("world_draft_operation_changed")
        old_rates = [{k: v for k, v in p.items() if k != "rate_read_at"} for p in offered["prices"]]
        new_rates = [{k: v for k, v in p.items() if k != "rate_read_at"} for p in fresh["prices"]]
        if old_rates != new_rates:
            raise WorldDraftOfferRefused("world_draft_operation_changed")
    except (KeyError, TypeError, ValueError, CanonicalisationError) as failed:
        if isinstance(failed, WorldDraftOfferRefused):
            raise
        raise WorldDraftOfferRefused("world_draft_operation_changed") from failed
    return dict(offered)
