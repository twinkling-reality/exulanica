"""The answer's execution block says why a call names no served model, instead of a bare null.

``ModelCall`` records the served model from the response body and, when the body named none,
the reason by name (:data:`exulanica.models.results.NO_MODEL_IN_RESPONSE`). The API builds its
view field by field, so a reason the view drops would leave clients a null they could read as
the requested model; these hold the view to the record.
"""

from __future__ import annotations

from exulanica.api.routes.selection import _execution
from exulanica.models.results import NO_MODEL_IN_RESPONSE
from exulanica.selection.calls import AttemptOutcome, CallCost, ModelCall


def _call(*, served_model: str | None, served_model_unavailable: str | None) -> ModelCall:
    return ModelCall(
        role="embedding",
        requested_model="requested/model",
        served_model=served_model,
        used_fallback=False,
        attempts=1,
        latency_ms=12,
        prompt_tokens=3,
        completion_tokens=0,
        reasoning_tokens=None,
        usd="0.00000002",
        served_model_unavailable=served_model_unavailable,
        outcome=AttemptOutcome.COMPLETED,
        cost_basis=CallCost.KNOWN,
    )


def test_a_call_whose_response_named_no_model_says_why_in_the_execution_block():
    view = _execution(
        (_call(served_model=None, served_model_unavailable=NO_MODEL_IN_RESPONSE),), ()
    )

    (call,) = view.model_dump()["calls"]
    assert call["served_model"] is None
    assert call["served_model_unavailable"] == NO_MODEL_IN_RESPONSE


def test_a_call_whose_response_named_its_model_carries_no_reason():
    view = _execution((_call(served_model="served/model", served_model_unavailable=None),), ())

    (call,) = view.model_dump()["calls"]
    assert call["served_model"] == "served/model"
    assert call["served_model_unavailable"] is None
