"""Offline measurement controls. Scripted outputs establish no model or vision quality."""

from __future__ import annotations

import copy
import json
import uuid
from dataclasses import replace

import pytest
from exulanica.evidence import BlobId, EvidenceAddress
from exulanica.models.transport import HttpResponse
from exulanica.selection import Answer, AnswerClause, SelectionPlan, Session
from exulanica.selection.packet import EvidenceItem, EvidencePacket, ValueReference
from exulanica.selection.question import CallLog, answer_question, compose_answer
from scripts.measure_companion_acceptance import (
    digest,
    frozen_input,
    request_totals,
    score_comparison,
    score_observation,
    verify_input,
)

from model_fakes import chat_body


def test_freeze_binds_actual_captions_digests_dates_and_holdouts():
    frozen = frozen_input()
    record = verify_input(frozen)
    assert len(record["corpus"]) == 3
    assert len(record["questions"]) == 12
    assert sum(q["split"] == "holdout" for q in record["questions"]) == 4
    assert all("helmet" in c["text"] for c in record["corpus"])
    assert all(c["captured_at"].startswith("2025-12-02") for c in record["corpus"])
    assert {q["kind"] for q in record["questions"]} >= {
        "visual",
        "count",
        "date",
        "missing_place",
        "missing_identity",
    }
    tampered = copy.deepcopy(frozen)
    tampered["record"]["questions"][0]["expected_capture_ids"] = []
    tampered["record_sha256"] = digest(tampered["record"])
    with pytest.raises(ValueError, match="fixed questions"):
        verify_input(tampered)


def observation(frozen, key="mountain", arm="lexical"):
    record = frozen["record"]
    uri = EvidenceAddress.photograph(BlobId.from_hex(record["corpus"][0]["source_sha256"])).to_uri()
    return {
        "question_id": key,
        "arm": arm,
        "input_sha256": frozen["record_sha256"],
        "corpus_sha256": record["corpus_sha256"],
        "response_kind": "scripted",
        "status": 200,
        "body": {
            "selection": {"captures": [{"capture_id": c["capture_id"]} for c in record["corpus"]]},
            "answer": {
                "clauses": [
                    {
                        "text": "Snow-covered mountains.",
                        "type": "historical",
                        "citations": ["TOKEN"],
                    }
                ]
            },
            "citations": {"TOKEN": uri},
        },
    }


def test_retrieval_success_is_not_answer_correctness_or_citation_access():
    frozen = frozen_input()
    result = score_comparison(frozen, [observation(frozen)])
    row = result["rows"][0]
    assert row["lexical"]["retrieval_coverage"] == {"k": 3, "n": 3}
    assert row["lexical"]["answer_correct"] is None
    assert row["lexical"]["citations_accessible"] is None
    assert row["fused"]["executed"] is False
    assert result["live_quality_passed"] is False
    assert len(result["rows"]) == 12  # missing and heldout results cannot disappear


def test_every_failure_survives_including_wrong_answers_with_valid_citations():
    frozen = frozen_input()
    obs = observation(frozen)
    obs["body"]["selection"]["captures"] = []
    obs["human_review"] = {"correct": False, "rationale": "Answer invents a mountain name."}
    obs["citation_probes"] = {obs["body"]["citations"]["TOKEN"]: 410}
    row = score_comparison(frozen, [obs])["rows"][0]["lexical"]
    assert row["retrieval_coverage"] == {"k": 0, "n": 3}
    assert row["failures"] == [
        "answer_incorrect",
        "citation_inaccessible",
        "retrieval_missed_support",
    ]


@pytest.mark.parametrize("change", ["duplicate", "corpus", "input", "kind", "question"])
def test_comparison_rejects_unfair_or_unlabelled_observations(change):
    frozen = frozen_input()
    obs = observation(frozen)
    rows = [obs]
    if change == "duplicate":
        rows.append(obs)
    elif change == "question":
        obs["question_id"] = "not-frozen"
    else:
        obs[
            {"corpus": "corpus_sha256", "input": "input_sha256", "kind": "response_kind"}[change]
        ] = "x"
    with pytest.raises(ValueError):
        score_comparison(frozen, rows)


def test_missing_identity_can_retrieve_all_photos_but_must_not_assert_a_name():
    frozen = frozen_input()
    obs = observation(frozen, "identity")
    q = next(q for q in frozen["record"]["questions"] if q["id"] == "identity")
    score = score_observation(q, obs, frozen["record"]["corpus"])
    assert score["retrieval_coverage"] is None
    assert "unsupported_historical_claim" in score["failures"]
    obs["body"]["answer"]["clauses"] = [{"text": "I cannot determine their names.", "type": "meta"}]
    score = score_observation(q, obs, frozen["record"]["corpus"])
    assert score["answer_correct"] is None  # actual human review, never agent self-attestation


def test_missing_provider_usage_never_becomes_zero_cost():
    assert request_totals([])["cost_usd"] == "0"
    totals = request_totals(
        [
            {"latency_ms": 20, "prompt_tokens": 10, "completion_tokens": 2, "cost_usd": "0.01"},
            {"latency_ms": 30, "prompt_tokens": None, "completion_tokens": None, "cost_usd": None},
        ]
    )
    assert totals == {
        "request_count": 2,
        "latency_ms": 50,
        "prompt_tokens": None,
        "completion_tokens": None,
        "cost_usd": None,
    }


@pytest.fixture
def retained_packet():
    c = frozen_input()["record"]["corpus"][0]
    item = EvidenceItem(
        token="ABCDE23456",
        span_id=uuid.UUID(int=21),
        assertion_id=uuid.UUID(c["assertion_id"]),
        address=EvidenceAddress.photograph(BlobId.from_hex(c["source_sha256"])),
        capture_id=uuid.UUID(c["capture_id"]),
        captured_at=c["captured_at"],
        text=c["text"],
        trust="capture_supported",
    )
    return EvidencePacket(
        items=(item,),
        values=(ValueReference("capture_count", "1", "count"),),
        total_matched=1,
        citable=True,
    )


def test_missing_model_echo_and_usage_remain_null(client, transport, retained_packet):
    body = chat_body(
        Answer(clauses=[AnswerClause(text="No name is supplied.", type="meta")]).model_dump_json()
    )
    body.pop("model", None)
    body.pop("usage", None)
    transport.responses.append(HttpResponse(status_code=200, text=json.dumps(body)))
    log = CallLog()
    compose_answer(client, "What is the mountain called?", retained_packet, log=log)
    assert len(log.calls) == 1
    assert log.calls[0].requested_model
    assert log.calls[0].served_model is None
    assert log.calls[0].prompt_tokens is None
    assert log.calls[0].usd is None


@pytest.mark.parametrize("mutation", ["deleted", "withdrawn", "caption_changed", "count_changed"])
def test_evidence_changed_while_composing_cannot_support_final_answer(
    monkeypatch, retained_packet, mutation
):
    from exulanica.selection import question as module

    original = retained_packet
    if mutation in ("deleted", "withdrawn"):
        current = replace(original, items=(), values=(), total_matched=0)
    elif mutation == "caption_changed":
        current = replace(original, items=(replace(original.items[0], text=""),))
    else:
        current = replace(original, values=(ValueReference("capture_count", "2", "count"),))
    packets = iter([original, current])
    monkeypatch.setattr(module, "validate", lambda *a, **k: object())
    monkeypatch.setattr(module, "execute", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_packet", lambda *a, **k: next(packets))
    answer = Answer(
        clauses=[
            AnswerClause(
                text="The people hold helmets.",
                type="historical",
                citations=[original.items[0].token],
            )
        ]
    )
    monkeypatch.setattr(module, "compose_answer", lambda *a, **k: (answer, False, ()))
    result = answer_question(
        None,
        None,
        "What do they hold?",
        Session(workspace_id=uuid.UUID(int=1), actor=uuid.UUID(int=2)),
        plan=SelectionPlan(intent="captures"),
    )
    assert result.abstention is not None
    assert all(c.type == "meta" and not c.citations for c in result.answer.clauses)
    assert result.packet is None
    assert result.result is None
    assert result.rejections


def test_fresh_packet_random_tokens_do_not_invalidate_unchanged_answer(
    monkeypatch, retained_packet
):
    from exulanica.selection import question as module

    packets = iter(
        [
            retained_packet,
            replace(
                retained_packet, items=(replace(retained_packet.items[0], token="ZYXWV98765"),)
            ),
        ]
    )
    monkeypatch.setattr(module, "validate", lambda *a, **k: object())
    monkeypatch.setattr(module, "execute", lambda *a, **k: None)
    monkeypatch.setattr(module, "build_packet", lambda *a, **k: next(packets))
    answer = Answer(
        clauses=[
            AnswerClause(
                text="Helmets are held.",
                type="historical",
                citations=[retained_packet.items[0].token],
            )
        ]
    )
    monkeypatch.setattr(module, "compose_answer", lambda *a, **k: (answer, False, ()))
    result = answer_question(
        None,
        None,
        "What do they hold?",
        Session(workspace_id=uuid.UUID(int=1), actor=uuid.UUID(int=2)),
        plan=SelectionPlan(intent="captures"),
    )
    assert result.answer == answer
    assert result.abstention is None
    assert result.packet.items[0].token == retained_packet.items[0].token


def test_fused_regressions_are_explicit_even_when_both_arms_return_answers():
    frozen = frozen_input()
    lexical, fused = observation(frozen), observation(frozen, arm="fused")
    lexical["human_review"] = {"correct": True, "rationale": "scripted control verdict"}
    fused["human_review"] = {"correct": False, "rationale": "scripted control verdict"}
    fused["body"]["selection"]["captures"].pop()
    row = score_comparison(frozen, [lexical, fused])["rows"][0]
    assert row["fused_regressions"] == ["retrieval_coverage", "answer_correct"]


def recorder(transport, manifest, **changes):
    from decimal import Decimal

    from exulanica.models.budget import BudgetGuard
    from scripts.measure_companion_acceptance import RequestRecorder

    cap = {
        "run_id": "scripted-offline-control",
        "authorization_reference": "test fixture only",
        "input_sha256": frozen_input()["record_sha256"],
        "max_requests": 2,
        "max_usd": "1",
        "models": [manifest.roles["reasoning_cheap"].primary.model_id],
    }
    cap.update(changes)
    return RequestRecorder(
        transport, manifest, frozen_input(), cap, BudgetGuard(ceiling_usd=Decimal("1"), max_calls=2)
    )


def test_attempt_recorder_preserves_failures_missing_echo_and_usage(transport, manifest):
    from exulanica.models.errors import BudgetExceededError

    measured = recorder(transport, manifest)
    model = measured.cap["models"][0]
    transport.responses.extend(
        [
            HttpResponse(
                status_code=200,
                text=json.dumps({"usage": {"prompt_tokens": 12, "completion_tokens": 4}}),
            ),
            HttpResponse(status_code=503, text="service unavailable"),
        ]
    )
    for _ in range(2):
        measured.post_json(
            "not-a-live-url",
            headers={"Authorization": "private-test-value"},
            payload={"model": model, "max_tokens": 100},
            timeout=1,
        )
    assert len(measured.requests) == 2
    assert measured.requests[0]["served_model"] is None
    assert measured.requests[0]["cost_usd"] is not None
    assert measured.requests[1]["cost_usd"] is None
    assert measured.requests[1]["status"] == 503
    assert "private-test-value" not in json.dumps(measured.requests)
    with pytest.raises(BudgetExceededError):
        measured.post_json("", headers={}, payload={"model": model}, timeout=1)
    assert len(transport.requests) == 2


def test_recorder_refuses_wrong_corpus_model_and_mismatched_budget(transport, manifest):
    from exulanica.models.errors import BudgetExceededError

    with pytest.raises(ValueError, match="frozen corpus"):
        recorder(transport, manifest, input_sha256="f" * 64)
    with pytest.raises(ValueError, match="BudgetGuard"):
        recorder(transport, manifest, max_usd="2")
    measured = recorder(transport, manifest)
    with pytest.raises(BudgetExceededError, match="model outside"):
        measured.post_json("", headers={}, payload={"model": "not-authorized"}, timeout=1)
    assert transport.requests == []


def test_recorder_stops_after_unknown_spend_and_records_transport_failure(transport, manifest):
    from exulanica.models.errors import BudgetExceededError, TransportError

    measured = recorder(transport, manifest)
    transport.responses.append(TransportError("scripted disconnection"))
    payload = {"model": measured.cap["models"][0]}
    with pytest.raises(TransportError):
        measured.post_json("", headers={}, payload=payload, timeout=1)
    assert measured.requests[0]["error_type"] == "TransportError"
    with pytest.raises(BudgetExceededError, match="unavailable"):
        measured.post_json("", headers={}, payload=payload, timeout=1)
    assert len(transport.requests) == 1


def test_paired_executor_controls_use_same_plan_and_real_retained_caption_text(
    repository, photo_dir, tmp_path, client, monkeypatch
):
    """Generated photo bytes + retained caption text + scripted vectors: mechanics only."""
    from exulanica.db.migrate import provision_workspace
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.models.manifest import Role
    from exulanica.models.results import EmbeddingResult
    from exulanica.models.usage import CallUsage
    from exulanica.selection.embeddings import QueryEmbedding, embed_capture
    from exulanica.store.local import LocalContentAddressedStore
    from scripts.measure_companion_acceptance import compare_retrieval

    from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo

    provision_workspace(repository.connection, repository.workspace_id)
    unit_vector = (1.0, *([0.0] * 4095))
    spec = client.manifest[Role.EMBEDDING].primary
    monkeypatch.setattr(
        client,
        "embed",
        lambda *a, **kw: EmbeddingResult(
            spec.model_id,
            (unit_vector,),
            CallUsage.from_response(role=Role.EMBEDDING, spec=spec, usage={"prompt_tokens": 20}),
            4096,
        ),
    )
    expected = set()
    for number, caption in enumerate(frozen_input()["record"]["corpus"]):
        payload = copy.deepcopy(DEFAULT_PAYLOAD)
        payload.update(
            scene_description=caption["text"], objects=[], legible_text=[], proposed_place=None
        )
        pipeline = PhotoIngestPipeline(
            repository,
            LocalContentAddressedStore(tmp_path / "blobs"),
            vision=CountingVisionModel(payload=payload),
        )
        result = ingest_observed(
            pipeline,
            repository,
            write_photo(
                photo_dir,
                f"control-{number}.jpg",
                when=f"2025:12:02 13:43:3{number}",
            ),
        )
        assert result.error is None
        expected.add(str(result.capture_id))
        embed_capture(repository.connection, repository.workspace_id, result.capture_id, client)
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())
    vector = QueryEmbedding(unit_vector, spec.model_id, client.manifest.pipeline_version)
    plan = SelectionPlan(intent="captures", semantic_query="cold weather clothing")
    arms = compare_retrieval(repository.connection, session, plan, query_embedding=vector)
    assert arms["lexical"]["capture_ids"] == []
    assert set(arms["fused"]["citable_capture_ids"]) == expected
    # An orthogonal scripted vector does not magically establish relevance.
    negative = replace(vector, vector=(0.0, 1.0, *([0.0] * 4094)))
    arms = compare_retrieval(repository.connection, session, plan, query_embedding=negative)
    assert arms["fused"]["capture_ids"] == []
