"""Provider-specific refusals cannot introduce unrecordable decision reason words."""

import pytest
from exulanica.api.decision_host import _failure_reason
from exulanica.models.errors import ProviderRefused
from exulanica.world.decision_roles import GENERIC_REASONS


@pytest.mark.parametrize(
    "reason",
    ["provider_not_admitted", "provider_credential_absent", "provider_configuration_changed"],
)
def test_existing_provider_refusals_keep_their_recorded_reason(reason):
    failure = ProviderRefused("an arbitrary provider message", provider="fixture", reason=reason)
    assert _failure_reason(failure) == reason


@pytest.mark.parametrize(
    "reason",
    [
        "model_binding_identity_mismatch",
        "model_binding_scope_mismatch",
        "model_binding_stale_or_unavailable",
        "licence_not_admitted",
        "arbitrary untrusted failure words",
    ],
)
def test_unregistered_refusals_end_as_an_admitted_failed_call_without_provider_text(reason):
    failure = ProviderRefused(
        "private provider text must not enter the receipt", provider="fixture", reason=reason
    )
    recorded = _failure_reason(failure)
    assert recorded == "model_call_failed"
    assert recorded in GENERIC_REASONS
