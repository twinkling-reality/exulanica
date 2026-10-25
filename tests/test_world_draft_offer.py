"""Operation ceilings use fresh rates and all native alternatives, not historical call counts."""

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest
from exulanica.api.world_draft_offer import (
    WorldDraftOfferRefused,
    calls_at_most,
    confirm_operation,
    operation_sheet,
    read_operation_sheet,
    stages,
)
from exulanica.models.manifest import load_manifest
from exulanica.models.provider_catalog import ProviderPrice

NOW = dt.datetime(2026, 10, 11, tzinfo=dt.UTC)


def inputs():
    manifest = load_manifest()
    models = {s for rows in stages().values() for r, _ in rows for s in manifest[r].chain}
    prices = {
        (s.provider, s.model_id): ProviderPrice(
            s.model_id,
            s.input_usd_per_mtok * 2,
            s.output_usd_per_mtok * 2,
            s.context_window_tokens,
            "f" * 64,
        )
        for s in models
    }
    at = {s.provider: NOW for s in models}

    def wire(role):
        return len(manifest[role].chain) * 3

    return manifest, prices, at, wire


def test_full_operation_includes_actual_repairs_fallbacks_and_alternative_tool_paths():
    manifest, prices, at, wire = inputs()
    sheet = operation_sheet(manifest, prices, at, wire, now=NOW)
    assert sheet["estimate_is_expected_spend"] is False
    assert sheet["maximum_usd"] == str(
        sum((Decimal(p["ceiling_usd"]) for p in sheet["providers"]), Decimal(0))
    )
    assert sheet["calls_at_most"] == sum(p["max_calls"] for p in sheet["providers"])
    assert {p["tool"] for p in sheet["paths"]} == set(stages())
    for path in sheet["paths"]:
        for entry, (role, repairs) in zip(path["stages"], stages()[path["tool"]], strict=True):
            assert entry["dispatches_at_most"] == repairs * wire(role)
            assert len(entry["models"]) == len(manifest[role].chain)
    for rate in sheet["prices"]:
        price = prices[rate["provider"], rate["model_id"]]
        assert Decimal(rate["input_usd_per_mtok"]) == price.input_usd_per_mtok
        assert (
            Decimal(rate["input_usd_per_mtok"])
            != manifest.spec(rate["model_id"]).input_usd_per_mtok
        )
        assert rate["rate_response_sha256"] == "f" * 64


def test_the_sheet_states_its_largest_step_overall_and_for_each_provider():
    """One step of a draft is one dispatch: the dearest model of any stage at its worst case. A
    bound that leaves less than a provider's step can send nothing to it."""
    manifest, prices, at, wire = inputs()
    sheet = operation_sheet(manifest, prices, at, wire, now=NOW)
    dearest: dict[str, Decimal] = {}
    for path in sheet["paths"]:
        for entry in path["stages"]:
            for model in entry["models"]:
                each = Decimal(model["reservation_usd"])
                dearest[model["provider"]] = max(dearest.get(model["provider"], each), each)
    for provider in sheet["providers"]:
        step = Decimal(provider["step_usd_at_most"])
        assert step == dearest[provider["provider"]]
        assert 0 < step < Decimal(provider["ceiling_usd"])
    assert Decimal(sheet["step_usd_at_most"]) == max(dearest.values())


@pytest.mark.parametrize("attempts", [1, 3])
def test_the_most_calls_without_prices_are_the_sheet_s_own(attempts):
    """A person is told the same most calls whether or not the server could read prices: every
    schema repair, every wire attempt and every fallback, counted as the sheet counts them."""
    manifest, prices, at, _ = inputs()

    def wire(role):
        return len(manifest[role].chain) * attempts

    sheet = operation_sheet(manifest, prices, at, wire, now=NOW)
    assert calls_at_most(manifest, wire) == sheet["calls_at_most"]
    # Fallbacks count: where a role holds one, the figure is more than the schema attempts along
    # the longest path, which is all the offer used to count when it could read no prices.
    assert any(len(manifest[role].chain) > 1 for path in stages().values() for role, _ in path)
    longest = max(sum(repairs for _, repairs in path) for path in stages().values())
    assert calls_at_most(manifest, wire) > longest


@pytest.mark.parametrize("change", ["missing", "stale", "future", "nan", "context"])
def test_an_unpriced_or_unsafe_operation_is_refused_instead_of_quoted_zero(change):
    manifest, prices, at, wire = inputs()
    key = next(iter(prices))
    if change == "missing":
        del prices[key]
    elif change == "stale":
        at[key[0]] = NOW - dt.timedelta(seconds=60)
    elif change == "future":
        at[key[0]] = NOW + dt.timedelta(seconds=1)
    elif change == "nan":
        prices[key] = replace(prices[key], input_usd_per_mtok=Decimal("NaN"))
    else:
        prices[key] = replace(prices[key], context_window_tokens=1)
    with pytest.raises(WorldDraftOfferRefused, match="price_unavailable"):
        operation_sheet(manifest, prices, at, wire, now=NOW)


class _RatesRead:
    """A client whose every rate read answers the same prices from a list whose raw text differs,
    as Nebius's does: each model's "created" moves with the clock, and so does the text's digest."""

    def __init__(self, scale: Decimal = Decimal(1)) -> None:
        self.manifest = load_manifest()
        self.scale = scale
        self.reads = 0

    def maximum_wire_attempts(self, role):
        return len(self.manifest[role].chain) * 3

    def provider_prices(self, provider):
        self.reads += 1
        return {
            s.model_id: ProviderPrice(
                s.model_id,
                s.input_usd_per_mtok * self.scale,
                s.output_usd_per_mtok,
                s.context_window_tokens,
                f"{self.reads:064x}",
            )
            for rows in stages().values()
            for role, _ in rows
            for s in self.manifest[role].chain
            if s.provider == provider
        }


def test_a_second_read_of_the_same_rates_confirms_though_the_list_text_moved():
    client = _RatesRead()
    offered = read_operation_sheet(client)
    # Read again at the start: the same prices, a list whose raw text (and digest) differs.
    assert confirm_operation(client, offered) == offered
    # A rate that did change is still refused before anything is sent.
    client.scale = Decimal(2)
    with pytest.raises(WorldDraftOfferRefused) as refused:
        confirm_operation(client, offered)
    assert refused.value.code == "world_draft_operation_changed"
