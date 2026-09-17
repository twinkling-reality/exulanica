"""Caption text about a personal photograph reaches the embedding model only under a model right.

The vision model writes a caption about what a photograph shows, and the caption pass sends that
text to the hosted embedding model. The operator's decision is that text derived from a personal
photograph counts: it leaves only under a current right naming the embedding role's whole chain
and its endpoint, asked after the text is read and immediately before it is sent, and a refusal
is recorded rather than failed.

The transport, or the scripted ``embed`` standing in for it, is the witness in every test here,
because a gate that raised after the request had gone would pass a test that only read the error.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.epistemics.caption_embeddings import (
    SEARCHABLE_PREDICATES,
    SOURCE_SQL,
    CaptionEmbeddingPass,
    embed_capture,
)
from exulanica.errors import PrivacyAdmissionError
from exulanica.ingest import derivative_queue
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.model_rights import ModelHandoff, grant_model_right
from exulanica.ingest.personal_admission import role_handoff
from exulanica.ingest.worker import DerivativeWorker
from exulanica.models.manifest import Role
from exulanica.models.transport import HttpResponse
from psycopg.pq import TransactionStatus

from test_companion_matching import corpus as corpus
from test_companion_matching import script, unchecked, vector
from test_intake_upload import upload as upload
from test_personal_admission_route import batch, post

# -- the pass itself, over the synthetic corpus ---------------------------------------------------


def _held_locks(connection) -> int:
    return connection.execute(
        "select count(*) as n from pg_locks where pid=pg_backend_pid() and locktype='advisory'"
    ).fetchone()["n"]


def test_the_text_is_read_before_the_check_and_sent_only_after_it(
    repository, corpus, client, monkeypatch
):
    connection = repository.connection
    order = []
    sent = script(client, monkeypatch, vector())
    scripted = client.embed

    def embed(texts, **kwargs):
        # No transaction is open while the model runs, and this capture stays locked.
        assert connection.info.transaction_status == TransactionStatus.IDLE
        assert _held_locks(connection) == 1
        order.append("send")
        return scripted(texts, **kwargs)

    monkeypatch.setattr(client, "embed", embed)

    def before_send(handoff):
        assert connection.info.transaction_status == TransactionStatus.IDLE
        order.append(handoff)

    result = embed_capture(
        connection, repository.workspace_id, corpus["snow"], client, before_send=before_send
    )
    assert result is not None
    assert order == [ModelHandoff.hosted(client.manifest, Role.EMBEDDING), "send"]
    assert len(sent) == 1
    assert _held_locks(connection) == 0


def test_a_refusal_sends_nothing_stores_nothing_and_releases_the_capture(
    repository, corpus, client, monkeypatch
):
    connection = repository.connection
    sent = script(client, monkeypatch, vector())

    def refuse(handoff):
        raise PrivacyAdmissionError("no model right lets this model process this photograph")

    with pytest.raises(PrivacyAdmissionError, match="no model right"):
        embed_capture(
            connection, repository.workspace_id, corpus["snow"], client, before_send=refuse
        )
    assert sent == []
    assert connection.execute("select count(*) as n from embedding").fetchone()["n"] == 0
    assert _held_locks(connection) == 0
    assert (
        embed_capture(
            connection, repository.workspace_id, corpus["snow"], client, before_send=unchecked
        )
        is not None
    )
    assert len(sent) == 1


def test_text_that_changed_while_the_model_ran_is_not_stored(
    repository, corpus, client, monkeypatch
):
    connection = repository.connection
    capture = corpus["snow"]
    sent = script(client, monkeypatch, vector())
    scripted = client.embed

    def embed(texts, **kwargs):
        connection.execute(
            "update assertion set status='retracted' where workspace_id=%s "
            "and subject_ref->>'id'=%s",
            (repository.workspace_id, str(capture)),
        )
        return scripted(texts, **kwargs)

    monkeypatch.setattr(client, "embed", embed)
    result = embed_capture(
        connection, repository.workspace_id, capture, client, before_send=unchecked
    )
    # The request went, so its cost is reported; the vector for text that is gone is not kept.
    assert result is not None
    assert len(sent) == 1
    assert connection.execute("select count(*) as n from embedding").fetchone()["n"] == 0


def test_the_pass_needs_a_check_and_an_idle_connection_before_it_reads(
    repository, corpus, client, monkeypatch
):
    connection = repository.connection
    sent = script(client, monkeypatch, vector())
    with pytest.raises(TypeError, match="before_send"):
        embed_capture(connection, repository.workspace_id, corpus["snow"], client, before_send=None)
    with pytest.raises(ValueError, match="idle connection"), connection.transaction():
        embed_capture(
            connection, repository.workspace_id, corpus["snow"], client, before_send=unchecked
        )
    assert sent == []


def test_the_worker_pass_states_the_embedding_chain_of_its_own_client(client):
    stated = CaptionEmbeddingPass(client).model_handoff
    assert stated == ModelHandoff.hosted(client.manifest, Role.EMBEDDING)
    assert [identity.model_id for identity in stated.identities] == [
        spec.model_id for spec in client.manifest[Role.EMBEDDING].chain
    ]


# -- the worker, over personal photographs admitted through the API ----------------------------


def _embedding_requests(transport) -> list[dict]:
    return [request for request in transport.requests if request["url"].endswith("/embeddings")]


def _scripted_transport(client, transport) -> None:
    transport.by_model[client.manifest[Role.EMBEDDING].primary.model_id] = HttpResponse(
        status_code=200,
        text=json.dumps({"data": [{"embedding": vector()}], "usage": {"prompt_tokens": 20}}),
    )


def _worker(upload, embedding_pass) -> DerivativeWorker:
    return DerivativeWorker(
        upload.database,
        upload.store,
        frozenset({upload.workspace_id}),
        vision=upload.vision,
        embedding_pass=embedding_pass,
        name="caption-right-test",
    )


def _admitted(upload, roles: list[str], count: int = 1) -> dict:
    body = batch(upload, count=count)
    until = body["authority"]["valid_until"]
    body["model_rights"] = [{"role": role, "valid_until": until} for role in roles]
    response = post(upload, "/personal-admission", body)
    assert response.status_code == 202, response.text
    provision_workspace(upload.repository.connection, upload.workspace_id)
    return response.json()


def _caption_text(upload, capture_id) -> str | None:
    row = upload.repository.connection.execute(
        "select body from (" + SOURCE_SQL + ") source where capture_id=%s",
        (upload.workspace_id, list(SEARCHABLE_PREDICATES), capture_id),
    ).fetchone()
    return None if row is None else row["body"]


def _events(upload, capture_id) -> list[dict]:
    return upload.rows(
        "select event_type, message from derivative_job_event "
        "where capture_id=%s and event_type like 'capture_%%' and event_type<>'capture_started' "
        "order by occurred_at, event_id",
        capture_id,
    )


def test_no_caption_text_reaches_the_transport_without_an_embedding_right(
    upload, client, transport
):
    _scripted_transport(client, transport)
    receipt = _admitted(upload, ["vision"])["receipts"][0]
    capture_id = uuid.UUID(receipt["capture_id"])
    outcomes = _worker(upload, CaptionEmbeddingPass(client)).drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    # The photograph was described, so there was text to send, and none of it was sent.
    assert upload.vision.calls == 1
    assert _caption_text(upload, capture_id)
    assert _embedding_requests(transport) == []
    assert upload.rows("select embedding_id from embedding") == []
    # Upload and admission each queue the capture, so it is delivered twice; both say why.
    events = _events(upload, capture_id)
    embedding_model = client.manifest[Role.EMBEDDING].primary.model_id
    assert events
    for event in events:
        assert event["event_type"] == "capture_succeeded"
        assert "caption text was not sent to the embedding model" in event["message"]
        assert (
            f"none names nebius_token_factory embedding model {embedding_model}"
            in (event["message"])
        )

    # The account holder grants the embedding role; the next pass sends the text once.
    authorization = upload.rows(
        "select authorization_id, authorized_by from capture_reconstruction_authorization "
        "where capture_id=%s",
        capture_id,
    )[0]
    handoff = role_handoff("embedding", client.manifest)
    for identity in handoff.identities:
        grant_model_right(
            upload.repository,
            capture_id=capture_id,
            authorization_id=authorization["authorization_id"],
            identity=identity,
            destination=handoff.destination,
            granted_by=authorization["authorized_by"],
            purpose="Find my photographs by what they show",
            valid_until=dt.datetime.fromisoformat(receipt["model_rights"][0]["valid_until"]),
        )
    again = IntakeBatch.open(upload.repository, label="caption right test")
    again.declare_size(1)
    derivative_queue.enqueue(
        upload.repository.connection,
        upload.workspace_id,
        batch_id=again.batch_id,
        capture_ids=[capture_id],
    )
    outcomes = _worker(upload, CaptionEmbeddingPass(client)).drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    (request,) = _embedding_requests(transport)
    assert request["payload"]["input"] == [_caption_text(upload, capture_id)]
    assert len(upload.rows("select embedding_id from embedding")) == 1
    assert _events(upload, capture_id)[-1]["message"] is None


def test_an_admission_grants_the_embedding_role_with_vision_in_one_step(upload, client, transport):
    _scripted_transport(client, transport)
    admitted = _admitted(upload, ["vision", "embedding"], count=2)
    embedding = ModelHandoff.hosted(client.manifest, Role.EMBEDDING)
    for receipt in admitted["receipts"]:
        granted = [right["model"] for right in receipt["model_rights"]]
        assert [identity.as_record() for identity in embedding.identities] == [
            model for model in granted if model["role"] == "embedding"
        ]
    outcomes = _worker(upload, CaptionEmbeddingPass(client)).drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    assert upload.vision.calls == 2
    assert len(_embedding_requests(transport)) == 2
    assert len(upload.rows("select embedding_id from embedding")) == 2
    for receipt in admitted["receipts"]:
        assert {event["message"] for event in _events(upload, receipt["capture_id"])} == {None}


def test_a_pass_that_states_no_model_is_not_run_for_a_personal_photograph(
    upload, client, monkeypatch
):
    """Even with both rights granted: nothing can match a right to a pass that names no model."""
    receipt = _admitted(upload, ["vision", "embedding"])["receipts"][0]
    sent = script(client, monkeypatch, vector())
    called = []

    def undeclared(connection, workspace, capture, *, before_send):
        called.append(capture)
        return embed_capture(connection, workspace, capture, client, before_send=before_send)

    outcomes = _worker(upload, undeclared).drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    assert called == []
    assert sent == []
    events = _events(upload, receipt["capture_id"])
    assert events
    assert all("does not state which model" in event["message"] for event in events)


def test_a_capture_with_no_screening_sends_no_caption_text(upload, client, monkeypatch):
    receipt = _admitted(upload, ["vision", "embedding"])["receipts"][0]
    capture_id = uuid.UUID(receipt["capture_id"])
    outcomes = _worker(upload, None).drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    assert _caption_text(upload, capture_id)
    sent = script(client, monkeypatch, vector())
    worker = _worker(upload, CaptionEmbeddingPass(client))
    embedded, withheld = worker._embed_captions(upload.repository, capture_id, None)
    assert embedded is None
    assert "no privacy screening receipt" in withheld
    assert sent == []
