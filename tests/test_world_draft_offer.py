"""Operation ceilings use fresh rates and all native alternatives, not historical call counts."""

import datetime as dt
from dataclasses import replace
from decimal import Decimal

import pytest
from exulanica.api.world_draft_offer import WorldDraftOfferRefused, operation_sheet, stages
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
