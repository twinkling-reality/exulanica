"""The Companion's routes serve each model's name beside its identifier, by the one rule.

A person reads a model by ``Manifest.model_name``; the page prints what the route serves and
never derives a name from an identifier. A fresh answer's calls and a remembered answer both
carry the names, and an identifier the manifest no longer declares is its own name.
"""

from __future__ import annotations

import uuid

from exulanica.api.routes.companion import _model_name
from exulanica.api.routes.selection import _execution
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection.calls import AttemptOutcome, CallCost, ModelCall


def _call(requested: str, served: str | None) -> ModelCall:
    return ModelCall(
        role="reasoning_cheap",
        requested_model=requested,
        served_model=served,
        used_fallback=served is not None and served != requested,
        attempts=1,
        latency_ms=12,
        prompt_tokens=3,
        completion_tokens=5,
        reasoning_tokens=None,
        usd="0.00000002",
        served_model_unavailable=None,
        outcome=AttemptOutcome.COMPLETED,
        cost_basis=CallCost.KNOWN,
    )


def test_a_fresh_answer_s_calls_name_both_models_as_the_manifest_does():
    manifest = load_manifest()
    binding = manifest[Role.REASONING_CHEAP]
    primary, fallback = binding.primary.model_id, binding.chain[-1].model_id
    (call,) = _execution((_call(primary, fallback),), ()).model_dump()["calls"]
    assert call["requested_model_name"] == manifest.model_name(primary)
    assert call["served_model_name"] == manifest.model_name(fallback)
    assert call["requested_model_name"] != primary


def test_a_call_that_names_no_served_model_has_no_served_name():
    primary = load_manifest()[Role.REASONING_CHEAP].primary.model_id
    (call,) = _execution((_call(primary, None),), ()).model_dump()["calls"]
    assert call["served_model_name"] is None


def test_a_remembered_answer_names_its_models_and_a_withdrawn_one_by_its_identifier():
    manifest = load_manifest()
    primary = manifest[Role.STRUCTURED_EXTRACTION].primary.model_id
    assert _model_name(primary) == manifest.model_name(primary)
    withdrawn = f"withdrawn/{uuid.uuid4()}"
    assert _model_name(withdrawn) == withdrawn
    assert _model_name(None) is None
