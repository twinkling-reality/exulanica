"""An unverified probe request never bypasses durable spending or catalog eligibility."""

import pytest
from exulanica.models import provider_catalog
from exulanica.models.errors import ProviderRefused
from exulanica.models.manifest import AnsweringMechanism
from exulanica.models.spending import SpendingRefused
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_probe_contract import candidate_spec, case_book

from test_model_probe_contract import definition


def _ask(client):
    found = definition()
    book, _ = case_book()
    role = decision_roles().role(book["role"])
    context = book["cases"][0]
    return client.probe_choice(
        candidate_spec(found),
        role.chosen,
        role.adapter.messages(role, context, AnsweringMechanism.JSON_SCHEMA),
        role.choice(context),
        mechanism=AnsweringMechanism.JSON_SCHEMA,
        prompt_version=found["prompt_version"],
        timeout=found["deadline_ms"] / 1000,
        max_tokens=found["answer_tokens"],
    )


def test_a_process_only_client_cannot_send_a_probe(client, transport):
    with pytest.raises(SpendingRefused) as refused:
        _ask(client)
    assert refused.value.reason == "spending_scope_missing"
    assert transport.call_count == 0


def test_catalog_eligibility_is_rechecked_before_the_candidate_is_asked(
    client, transport, monkeypatch
):
    monkeypatch.setattr(
        provider_catalog, "licence_class", lambda *args: provider_catalog.CONDITIONAL
    )
    with pytest.raises(ProviderRefused) as refused:
        _ask(client)
    assert refused.value.reason == "licence_not_admitted"
    assert transport.call_count == 0
