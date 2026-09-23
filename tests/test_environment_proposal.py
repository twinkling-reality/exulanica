from __future__ import annotations

import json

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.schema import strict_json_schema
from exulanica.models.transport import HttpResponse
from exulanica.selection.environment_proposal import (
    EnvironmentOperation,
    EnvironmentRefusalCode,
    _draft_model,
    draft_environment_operation,
)

from conftest import TEST_CEILING_USD, TEST_MAX_CALLS
from model_fakes import FakeTransport, RecordingPolicy, chat_body


def _reply(value: object) -> HttpResponse:
    return HttpResponse(
        status_code=200,
        text=json.dumps(chat_body(json.dumps(value))),
    )


def _client(*responses: HttpResponse) -> tuple[ModelClient, FakeTransport]:
    transport = FakeTransport(list(responses))
    return (
        ModelClient(
            api_key="test-key-not-real",
            transport=transport,
            budget=BudgetGuard(ceiling_usd=TEST_CEILING_USD, max_calls=TEST_MAX_CALLS),
            policy=RecordingPolicy(),
        ),
        transport,
    )


def test_model_output_contains_only_the_closed_operation_enum() -> None:
    schema = strict_json_schema(
        _draft_model(
            (
                EnvironmentOperation.PLACE_SELECTED_FEATURE,
                EnvironmentOperation.UNDO_LATEST_VERSION_EDIT,
            )
        )
    )

    assert set(schema["properties"]) == {"operation"}
    value, null = schema["properties"]["operation"]["anyOf"]
    assert value["enum"] == ["place_selected_feature", "undo_latest_version_edit"]
    assert null == {"type": "null"}
    rendered = json.dumps(schema).lower()
    for forbidden in (
        "admission_id",
        "publication_id",
        "feature_id",
        "render_batch_id",
        "instance_id",
        "region_id",
        "source_anchor",
        "origin_role",
        "geometry",
    ):
        assert forbidden not in rendered


def test_unoffered_operation_is_malformed_twice_and_refuses() -> None:
    wrong = _reply({"operation": "remove_selected_authored_instance"})
    client, transport = _client(wrong, wrong)

    decision = draft_environment_operation(
        client,
        "move this building",
        (EnvironmentOperation.PLACE_SELECTED_FEATURE,),
    )

    assert decision.operation is None
    assert decision.refusal is not None
    assert decision.refusal.code is EnvironmentRefusalCode.NOT_DRAFTED
    assert transport.call_count == 2


def test_supported_null_reply_refuses_without_guessing() -> None:
    client, transport = _client(_reply({"operation": None}))

    decision = draft_environment_operation(
        client,
        "move it a little left",
        (
            EnvironmentOperation.PLACE_SELECTED_FEATURE,
            EnvironmentOperation.UNDO_LATEST_VERSION_EDIT,
        ),
    )

    assert decision.operation is None
    assert decision.refusal is not None
    assert decision.refusal.code is EnvironmentRefusalCode.UNSUPPORTED
    assert transport.call_count == 1


def test_proposal_decision_has_no_writer_or_authoritative_payload_field() -> None:
    client, _ = _client(_reply({"operation": "place_selected_feature"}))

    decision = draft_environment_operation(
        client,
        "place this building",
        (EnvironmentOperation.PLACE_SELECTED_FEATURE,),
    )

    assert decision.operation is EnvironmentOperation.PLACE_SELECTED_FEATURE
    assert set(decision.__dataclass_fields__) == {"operation", "refusal", "model_id", "calls"}
