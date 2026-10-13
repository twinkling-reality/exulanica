"""Prepared model probes exercise actual choice and line rules; replay trusts receipts."""

import copy
import datetime as dt
from decimal import Decimal

import pytest
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.provider_catalog import ProviderPrice, catalog_sha256, provider_model
from exulanica.world.model_probe_contract import (
    RECEIPT_PROFILE,
    answer_valid,
    case_book,
    prepare_definition,
    probe_requests,
    replay_outcome,
    seal,
    validate_definition,
)


def definition():
    spec = load_manifest()[Role.REASONING_MID].primary
    stated = provider_model(spec.provider, spec.model_id)
    assert stated is not None
    price = ProviderPrice(spec.model_id, Decimal("0.1"), Decimal("0.3"), 32000, "a" * 64)
    return prepare_definition(
        stated,
        price,
        added_seq=1,
        added_sha256="b" * 64,
        catalog_sha256=catalog_sha256(),
        price_read_at=dt.datetime.now(dt.UTC).isoformat(),
    )


def successful_receipts(found):
    book, _ = case_book()
    receipts = []
    for request in probe_requests(found):
        context = book["cases"][request["case_index"]]
        answer = {"action": context["options"][0]["label"]}
        if request["takes_line"]:
            answer["line"] = "Let us see what lies ahead."
        assert answer_valid(found, request["case_seq"], answer)
        receipts.append(
            seal(
                {
                    "profile": RECEIPT_PROFILE,
                    "request": request,
                    "answer": answer,
                    "outcome": "answered",
                    "reason": None,
                    "calls": [
                        {
                            "provider": found["provider"],
                            "role": found["role"],
                            "requested_model": found["model_id"],
                            "served_model": found["model_id"],
                            "outcome": "completed",
                            "used_fallback": False,
                            "attempts": 1,
                            "latency_ms": 1,
                        }
                    ],
                }
            )
        )
    return receipts


def test_preparation_separates_stored_rates_from_the_exact_operation_and_binds_messages():
    found = definition()
    assert found["operation_estimate"]["max_calls"] == 44
    assert (
        Decimal(found["operation_estimate"]["ceiling_usd"])
        == (Decimal(32000) * Decimal("0.1") + Decimal(2048) * Decimal("0.3")) * 44 / 1_000_000
    )
    assert found["operation_estimate"]["inference_verified"] is False
    changed = seal({**found, "messages_sha256": "c" * 64})
    with pytest.raises(ValueError, match="contract_changed"):
        validate_definition(changed)


def test_completion_is_replayed_from_each_answer_and_actual_served_identity():
    found = definition()
    receipts = successful_receipts(found)
    outcome = replay_outcome(found, receipts)
    assert outcome["finished"] and outcome["verified"]
    assert all(value["answers_lines"] for value in outcome["mechanisms"].values())
    for receipt in receipts:
        receipt["calls"][0]["served_model"] = "another/variant"
        seal(receipt)
    refused = replay_outcome(found, receipts)
    assert not refused["finished"] and not refused["verified"]


def test_partial_probe_and_infrastructure_failure_give_no_verdict():
    found = definition()
    receipts = successful_receipts(found)
    assert not replay_outcome(found, receipts[:-1])["verified"]
    receipts[-1] = seal({**receipts[-1], "outcome": "unavailable", "answer": None})
    assert not replay_outcome(found, receipts)["finished"]


def test_receipts_cannot_be_reordered_duplicated_or_changed_without_detection():
    found = definition()
    receipts = successful_receipts(found)
    for bad in (
        [receipts[1], receipts[0], *receipts[2:]],
        [receipts[0], *receipts],
        [{**receipts[0], "answer": None}, *receipts[1:]],
    ):
        with pytest.raises(ValueError, match="receipt_mismatch"):
            replay_outcome(found, bad)


def test_line_cases_require_real_speech_and_refuse_missing_or_invented_actions():
    found = definition()
    book, _ = case_book()
    case_seq = book["plain_cases"] + 1
    answer = successful_receipts(found)[case_seq - 1]["answer"]
    assert answer_valid(found, case_seq, answer)
    assert not answer_valid(found, case_seq, {"action": answer["action"], "line": None})
    assert not answer_valid(found, case_seq, {"action": "wait", "line": None})
    invalid = copy.deepcopy(answer)
    invalid["line"] = "First line.\nSecond line."
    assert not answer_valid(found, case_seq, invalid)
