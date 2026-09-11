"""Real PostgreSQL lexical and pgvector retrieval, with scripted model vectors only."""

from __future__ import annotations

import copy
import math
import uuid
from decimal import Decimal

import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.models.manifest import Role
from exulanica.models.results import EmbeddingResult
from exulanica.models.usage import CallUsage
from exulanica.selection import Intent, SelectionPlan, Session, execute, validate
from exulanica.selection.embeddings import QueryEmbedding, embed_capture
from exulanica.selection.packet import build_packet
from exulanica.store.local import LocalContentAddressedStore

from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo


def vector(x=1.0, y=0.0):
    return (x, y, *([0.0] * 4094))


@pytest.fixture
def corpus(repository, tmp_path, photo_dir):
    texts = {
        "snow": "People wear insulated coveralls on a snowy mountain slope.",
        "gear": "People wear insulated coveralls. People wear coveralls.",
        "volcano": "A volcanic crater with black rocks and steam.",
        "waterfall": "A waterfall beside a green valley.",
    }
    ids = {}
    for i, (name, text) in enumerate(texts.items()):
        payload = copy.deepcopy(DEFAULT_PAYLOAD)
        payload.update(scene_description=text, legible_text=[], proposed_place=None, objects=[])
        pipeline = PhotoIngestPipeline(
            repository,
            LocalContentAddressedStore(tmp_path / "blobs"),
            vision=CountingVisionModel(payload=payload),
        )
        result = ingest_observed(
            pipeline,
            repository,
            write_photo(photo_dir, f"{name}.jpg", when=f"2026:08:27 0{i}:00:00"),
        )
        assert result.error is None
        ids[name] = result.capture_id
    provision_workspace(repository.connection, repository.workspace_id)
    return ids


def run(repository, query, embedding=None, **kwargs):
    plan = SelectionPlan(intent=Intent.CAPTURES, semantic_query=query, **kwargs)
    session = Session(workspace_id=repository.workspace_id, actor=uuid.uuid4())
    return execute(
        repository.connection,
        validate(repository.connection, plan, session),
        query_embedding=embedding,
    )


def script(client, monkeypatch, value):
    calls = []
    model = client.manifest[Role.EMBEDDING].primary

    def embed(texts, **kwargs):
        calls.append((texts, kwargs))
        return EmbeddingResult(
            model.model_id,
            (value,),
            CallUsage.from_response(role=Role.EMBEDDING, spec=model, usage={"prompt_tokens": 20}),
            4096,
        )

    monkeypatch.setattr(client, "embed", embed)
    return calls


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("wearing", {"snow", "gear"}),
        ("people wearing", {"snow", "gear"}),
        ("snow mountain", {"snow"}),
        ("waterfall", {"waterfall"}),
        ("people wearing purple dinosaurs", {"snow", "gear"}),
        ("wearing purple dinosaurs", set()),
        ("wearing wearing purple dinosaurs", set()),
        ("the and what", set()),
        ("penguin submarine", set()),
        ("') | penguin & ! submarine", set()),
    ],
)
def test_english_stemming_or_and_unique_minimum_match(repository, corpus, query, expected):
    result = run(repository, query)
    assert {c.capture_id for c in result.captures} == {corpus[name] for name in expected}


def test_fusion_ranks_within_scope_and_preserves_packet_order(
    repository, corpus, client, monkeypatch
):
    for name, values in (
        ("snow", vector(0.95, math.sqrt(1 - 0.95**2))),
        ("gear", vector(0.70, math.sqrt(1 - 0.70**2))),
        ("volcano", vector()),
    ):
        script(client, monkeypatch, values)
        embed_capture(repository.connection, repository.workspace_id, corpus[name], client)
    query = QueryEmbedding(
        vector(), client.manifest[Role.EMBEDDING].primary.model_id, client.manifest.pipeline_version
    )
    lexical = run(repository, "people wearing")
    assert lexical.captures[0].capture_id == corpus["gear"]
    fused = run(repository, "people wearing", query)
    # Both modalities outrank semantic-only, despite the volcano's perfect cosine.
    assert [c.capture_id for c in fused.captures] == [
        corpus["gear"],
        corpus["snow"],
        corpus["volcano"],
    ]
    packet = build_packet(repository.connection, fused, workspace_id=repository.workspace_id)
    assert [i.capture_id for i in packet.items] == [c.capture_id for c in fused.captures]
    assert run(repository, "crater", query, limit=1).captures[0].capture_id == corpus["volcano"]


def test_vector_only_hit_and_low_similarity_abstention(repository, corpus, client, monkeypatch):
    script(client, monkeypatch, vector())
    embed_capture(repository.connection, repository.workspace_id, corpus["snow"], client)
    model = client.manifest[Role.EMBEDDING].primary.model_id
    assert run(repository, "winter clothing", QueryEmbedding(vector(), model, 3)).total_matched == 1
    assert run(repository, "penguin submarine", QueryEmbedding(vector(0, 1), model, 3)).is_empty
    assert run(repository, "winter clothing", QueryEmbedding(vector(), "other-model", 3)).is_empty
    assert run(repository, "winter clothing", QueryEmbedding(vector(), model, 99)).is_empty


def test_embed_once_and_tombstone_queues_vector_for_purge(repository, corpus, client, monkeypatch):
    calls = script(client, monkeypatch, vector())
    capture = corpus["snow"]
    assert (
        embed_capture(repository.connection, repository.workspace_id, capture, client) is not None
    )
    assert embed_capture(repository.connection, repository.workspace_id, capture, client) is None
    assert len(calls) == 1
    assert calls[0][1]["role"] is Role.EMBEDDING
    assert calls[0][1]["use_cache"] is False
    assert calls[0][0] == ["People wear insulated coveralls on a snowy mountain slope."]
    before = run(repository, "snow")
    repository.insert_tombstone(scope="capture", capture_id=capture, requested_by=uuid.uuid4())
    assert embed_capture(repository.connection, repository.workspace_id, capture, client) is None
    assert len(calls) == 1
    assert run(repository, "snow").is_empty
    assert build_packet(
        repository.connection, before, workspace_id=repository.workspace_id
    ).is_empty
    row = repository.connection.execute(
        "select count(*) as n from purge_job where workspace_id=%s and target_kind='embedding'",
        (repository.workspace_id,),
    ).fetchone()
    assert row["n"] == 1


def test_permission_filter_excluded_photo_cannot_be_cited(repository, corpus, client, monkeypatch):
    from exulanica.selection.answer import render_deterministic_answer, validate_answer
    from exulanica.selection.plan import CaptureWindow

    script(client, monkeypatch, vector())
    for capture in corpus.values():
        embed_capture(repository.connection, repository.workspace_id, capture, client)
    embedding = QueryEmbedding(
        vector(), client.manifest[Role.EMBEDDING].primary.model_id, client.manifest.pipeline_version
    )
    # Even perfect vectors cannot escape the validated time scope.
    result = run(
        repository,
        "winter clothing",
        embedding,
        time=[CaptureWindow(start="2026-08-27T00:00:00Z", end="2026-08-27T01:00:00Z")],
    )
    assert {c.capture_id for c in result.captures} == {corpus["snow"]}
    packet = build_packet(repository.connection, result, workspace_id=repository.workspace_id)
    answer = validate_answer(render_deterministic_answer(packet), packet)
    assert answer.clauses
    assert {i.capture_id for i in packet.items} == {corpus["snow"]}
    # A session in another tenant sees no candidates even using the same vector.
    other = Session(workspace_id=uuid.uuid4(), actor=uuid.uuid4())
    result = execute(
        repository.connection,
        validate(
            repository.connection,
            SelectionPlan(intent=Intent.CAPTURES, semantic_query="people"),
            other,
        ),
        query_embedding=embedding,
    )
    assert result.is_empty


@pytest.mark.parametrize(
    "values", [vector(0, 0), (1.0,), vector(float("nan")), vector(float("inf"))]
)
def test_invalid_query_vectors_are_refused(values):
    with pytest.raises(ValueError):
        QueryEmbedding(values, "scripted", 3)


def test_ask_records_query_vector_cost_before_composition(
    repository,
    corpus,
    client,
    transport,
    monkeypatch,
):
    import json

    from exulanica.models.transport import HttpResponse
    from exulanica.selection.question import answer_question

    from model_fakes import chat_body

    calls = script(client, monkeypatch, vector())
    embed_capture(repository.connection, repository.workspace_id, corpus["snow"], client)
    transport.default = HttpResponse(
        status_code=200,
        text=json.dumps(
            chat_body(
                json.dumps(
                    {
                        "clauses": [
                            {
                                "text": "Some photographs match.",
                                "type": "meta",
                                "citations": [],
                                "value_refs": [],
                            }
                        ],
                    }
                )
            )
        ),
    )
    result = answer_question(
        repository.connection,
        client,
        "Which photos show winter clothing?",
        Session(workspace_id=repository.workspace_id, actor=uuid.uuid4()),
        plan=SelectionPlan(intent=Intent.CAPTURES, semantic_query="winter clothing"),
    )
    assert len(calls) == 2
    assert calls[1][0] == ["winter clothing"]
    assert [call.role for call in result.calls] == ["embedding", "reasoning_cheap"]
    call = result.calls[0]
    assert call.prompt_tokens == 20
    assert Decimal(call.usd) == Decimal("0.00000020")
    assert call.attempts is None and call.served_model is None
    assert call.latency_ms >= 0
    assert result.result.captures[0].capture_id == corpus["snow"]


def test_inactive_assertion_cannot_match_through_its_old_vector(
    repository,
    corpus,
    client,
    monkeypatch,
):
    script(client, monkeypatch, vector())
    capture = corpus["snow"]
    embed_capture(repository.connection, repository.workspace_id, capture, client)
    repository.connection.execute(
        "update assertion set status='retracted' where workspace_id=%s and subject_ref->>'id'=%s",
        (repository.workspace_id, str(capture)),
    )
    query = QueryEmbedding(
        vector(), client.manifest[Role.EMBEDDING].primary.model_id, client.manifest.pipeline_version
    )
    assert run(repository, "winter clothing", query).is_empty
