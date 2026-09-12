"""Durable caption-vector deletion through real PostgreSQL and the least-privilege purger.

Models are scripted. Every database is a harness-owned schema, including the upgrade case.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.db.session import set_workspace
from exulanica.deletion import queue
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.selection.embeddings import embed_capture

from test_companion_matching import run, script, vector
from test_derivative_reclaim import queued as queued
from test_purge import _APP_PASSWORD, _APP_ROLE, _PURGE_PASSWORD, _PURGE_ROLE
from test_purge import purged as purged


@pytest.fixture
def indexed(purged, client, monkeypatch):
    connection = purged.repository.connection
    provision_workspace(connection, purged.workspace_id)
    capture = purged.rows("select capture_id from capture")[0]["capture_id"]
    calls = script(client, monkeypatch, vector())
    embed_capture(connection, purged.workspace_id, capture, client)
    embedding = dict(purged.rows("select * from embedding")[0])
    return purged, capture, embedding, calls


@pytest.mark.postgres
def test_lifecycle_guard_refuses_a_function_from_a_later_search_path_schema(client, monkeypatch):
    from exulanica.migrations import migrations

    import pg_harness

    available = list(migrations())
    with pg_harness.migrated_schema() as (_, newer):
        newer_schema = newer.execute("select current_schema()").fetchone()[0]
        with monkeypatch.context() as patch:
            patch.setattr(
                pg_harness, "migrations", lambda: iter(m for m in available if m.version < "0044")
            )
            with pg_harness.migrated_schema() as (_, older):
                older_schema = older.execute("select current_schema()").fetchone()[0]
                older.execute(
                    psycopg.sql.SQL("set search_path to {}, {}, public").format(
                        psycopg.sql.Identifier(older_schema), psycopg.sql.Identifier(newer_schema)
                    )
                )
                # The unqualified lookup really can see the newer schema's lifecycle guard.
                assert older.execute(
                    "select to_regprocedure('caption_vector_purge_is_authorized(uuid,uuid,uuid)')"
                ).fetchone()[0] is not None
                older.row_factory = psycopg.rows.dict_row
                calls = script(client, monkeypatch, vector())
                with pytest.raises(RuntimeError, match="0044"):
                    embed_capture(older, uuid.uuid4(), uuid.uuid4(), client)
                assert calls == []


def _reinsert(connection, row, *, embedding_id=None):
    connection.execute(
        "insert into embedding (workspace_id,embedding_id,family,ref_type,ref_id,model_ref,"
        "pipeline_version,dims,v) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            row["workspace_id"],
            embedding_id or row["embedding_id"],
            row["family"],
            row["ref_type"],
            row["ref_id"],
            row["model_ref"],
            row["pipeline_version"],
            row["dims"],
            row["v"],
        ),
    )


@pytest.mark.parametrize("scope", ["capture", "workspace"])
def test_vectors_are_enqueued_atomically_and_physically_purged(indexed, client, scope):
    fixture, capture, embedding, calls = indexed
    connection = fixture.repository.connection
    before = run(fixture.repository, "red")
    assert before.total_matched == 1
    with connection.transaction():
        tombstone = fixture.repository.insert_tombstone(
            scope=scope,
            capture_id=capture if scope == "capture" else None,
            requested_by=uuid.uuid4(),
        )
        targets = fixture.rows(
            "select target_ref from purge_job where tombstone_id=%s and target_kind='embedding'",
            tombstone,
        )
        assert [row["target_ref"] for row in targets] == [str(embedding["embedding_id"])]
        assert not queue.is_purge_complete(connection, tombstone)
    assert run(fixture.repository, "red").is_empty
    assert embed_capture(connection, fixture.workspace_id, capture, client) is None
    assert len(calls) == 1
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        _reinsert(connection, embedding, embedding_id=uuid.uuid4())
    outcome = fixture.worker().drain()
    assert outcome.role == _PURGE_ROLE and outcome.failed == 0
    assert fixture.rows("select embedding_id from embedding") == []
    assert queue.is_purge_complete(connection, tombstone)
    assert fixture.rows("select purge_completed_at from tombstone")[0]["purge_completed_at"]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        _reinsert(connection, embedding)


def test_rolling_back_deletion_rolls_back_vector_targets(indexed):
    fixture, capture, _, _ = indexed
    with pytest.raises(RuntimeError, match="rollback"), fixture.repository.connection.transaction():
        fixture.tombstone_the_capture(capture)
        assert fixture.rows("select embedding_id from tombstone_embedding_target")
        raise RuntimeError("rollback")
    assert fixture.rows("select embedding_id from tombstone_embedding_target") == []
    assert fixture.rows("select purge_id from purge_job") == []
    assert len(fixture.rows("select embedding_id from embedding")) == 1


def test_failed_vector_delete_retries_and_cannot_report_completion(indexed, monkeypatch):
    fixture, capture, _embedding, _ = indexed
    tombstone = fixture.tombstone_the_capture(capture)
    worker = fixture.worker()
    destroy = worker._destroy

    def fail_vectors(connection, target, outcome):
        if target.target_kind == "embedding":
            raise OSError("scripted transient vector-store failure")
        return destroy(connection, target, outcome)

    monkeypatch.setattr(worker, "_destroy", fail_vectors)
    assert worker.drain().failed == 1
    assert not queue.is_purge_complete(fixture.repository.connection, tombstone)
    # A lying done marker is not proof of deletion either.
    fixture.repository.connection.execute(
        "update purge_job set state='done' where target_kind='embedding'"
    )
    assert not queue.is_purge_complete(fixture.repository.connection, tombstone)
    fixture.repository.connection.execute(
        "update purge_job set state='failed', attempted_at=now()-interval '1 hour' "
        "where target_kind='embedding'"
    )
    monkeypatch.setattr(worker, "_destroy", destroy)
    assert worker.drain().destroyed == 1
    assert queue.is_purge_complete(fixture.repository.connection, tombstone)
    # Reclaimed after deletion but before its completion marker: an authorized idempotent retry.
    fixture.repository.connection.execute(
        "update purge_job set state='running', attempted_at=now()-interval '1 hour' "
        "where target_kind='embedding'"
    )
    assert worker.drain().already_absent == 1
    assert fixture.rows("select embedding_id from embedding") == []


def test_shared_source_bytes_do_not_keep_deleted_tenant_vectors(indexed):
    fixture, capture, embedding, _ = indexed
    connection = fixture.repository.connection
    other = uuid.uuid4()
    blob = BlobId(bytes(fixture.rows("select blob_sha256 from capture")[0]["blob_sha256"]))
    connection.execute(
        "insert into capture (workspace_id,blob_sha256) values (%s,%s)", (other, blob.digest)
    )
    provision_workspace(connection, other)
    set_workspace(connection, other)
    address = EvidenceAddress.photograph(blob)
    other_span = connection.execute(
        "insert into evidence_span (workspace_id,blob_sha256,track_key,t_start_ns,t_end_ns,"
        "modality,span_digest) values (%s,%s,'img',0,1,'still_image',%s) returning span_id",
        (other, blob.digest, address.span_digest),
    ).fetchone()["span_id"]
    other_row = {**embedding, "workspace_id": other, "ref_id": other_span}
    _reinsert(connection, other_row, embedding_id=uuid.uuid4())
    set_workspace(connection, fixture.workspace_id)
    tombstone = fixture.tombstone_the_capture(capture)
    outcome = fixture.worker().drain()
    assert outcome.failed == 0 and outcome.skipped >= 1
    assert fixture.store.exists(blob)
    assert fixture.rows("select workspace_id from embedding") == [{"workspace_id": other}]
    assert not queue.is_purge_complete(connection, tombstone)  # shared bytes remain on disk


def test_forged_vector_targets_and_cross_tenant_authorization_are_refused(indexed):
    fixture, capture, embedding, _ = indexed
    tombstone = fixture.tombstone_the_capture(capture)
    with (
        fixture.database(role=_APP_ROLE, password=_APP_PASSWORD).session(
            fixture.workspace_id
        ) as app,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        app.execute(
            "insert into tombstone_embedding_target values (%s,%s,%s)",
            (fixture.workspace_id, tombstone, uuid.uuid4()),
        )
    with fixture.database(role=_PURGE_ROLE, password=_PURGE_PASSWORD).session(
        fixture.workspace_id
    ) as purge:
        assert purge.execute("select current_user as role").fetchone()["role"] == _PURGE_ROLE
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            purge.execute("select * from evidence_span")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            purge.execute("select * from tombstone_embedding_target")
        assert not purge.execute(
            "select caption_vector_purge_is_authorized(%s,%s,%s) as allowed",
            (uuid.uuid4(), tombstone, embedding["embedding_id"]),
        ).fetchone()["allowed"]


@pytest.mark.postgres
@pytest.mark.parametrize("scope", ["capture", "workspace"])
def test_upgrade_enqueues_old_orphans_and_reopens_false_completion(
    monkeypatch,
    tmp_path,
    client,
    scope,
):
    from exulanica.db.roles import provision_purge_role, provision_runtime_role
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.ingest.repository import IngestRepository
    from exulanica.migrations import migrations
    from exulanica.store.local import LocalContentAddressedStore

    import pg_harness
    from conftest import photo_bytes
    from test_purge import Purged

    all_migrations = list(migrations())
    lifecycle = next(m for m in all_migrations if m.version == "0044")
    with monkeypatch.context() as patch:
        patch.setattr(
            pg_harness, "migrations", lambda: iter(m for m in all_migrations if m.version < "0044")
        )
        with pg_harness.migrated_schema() as (pg, connection):
            connection.autocommit = True
            workspace = uuid.uuid4()
            repository = IngestRepository(connection, workspace)
            store = LocalContentAddressedStore(tmp_path / "store")
            result = PhotoIngestPipeline(repository, store).ingest_intake(
                photo_bytes(), filename="synthetic.jpg"
            )
            assert result.error is None
            provision_workspace(connection, workspace)
            calls = script(client, monkeypatch, vector())
            with pytest.raises(RuntimeError, match="0044"):
                embed_capture(connection, workspace, result.capture_id, client)
            assert calls == []
            span = connection.execute("select span_id from evidence_span").fetchone()["span_id"]
            _reinsert(
                connection,
                {
                    "workspace_id": workspace,
                    "embedding_id": uuid.uuid4(),
                    "family": "companion_text:pre-0044",
                    "ref_type": "span",
                    "ref_id": span,
                    "model_ref": "scripted-caption-vector",
                    "pipeline_version": 3,
                    "dims": 4096,
                    "v": "[" + ",".join(str(x) for x in vector()) + "]",
                },
            )
            tombstone = repository.insert_tombstone(
                scope=scope,
                capture_id=result.capture_id if scope == "capture" else None,
                requested_by=uuid.uuid4(),
            )
            assert (
                connection.execute(
                    "select 1 from purge_job where target_kind='embedding'"
                ).fetchone()
                is None
            )
            connection.execute("update tombstone set purge_completed_at=now()")
            connection.execute(lifecycle.sql)
            assert (
                connection.execute(
                    "select count(*) as n from purge_job where target_kind='embedding'"
                ).fetchone()["n"]
                == 1
            )
            assert (
                connection.execute("select purge_completed_at from tombstone").fetchone()[
                    "purge_completed_at"
                ]
                is None
            )
            assert not queue.is_purge_complete(connection, tombstone)
            provision_runtime_role(connection, role=_APP_ROLE, password=_APP_PASSWORD)
            provision_purge_role(connection, role=_PURGE_ROLE, password=_PURGE_PASSWORD)
            scratch = connection.execute("select current_schema() as name").fetchone()["name"]
            fixture = Purged(repository, store, scratch, pg, tmp_path)
            assert fixture.worker().drain().failed == 0
            assert connection.execute("select 1 from embedding").fetchone() is None
            assert queue.is_purge_complete(connection, tombstone)


@pytest.mark.parametrize("vector_first", [True, False])
def test_tombstone_and_vector_commit_order_cannot_leave_an_orphan(indexed, vector_first):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep

    fixture, capture, embedding, _ = indexed
    connection = fixture.repository.connection
    vector_id = uuid.uuid4()
    started = Event()
    contender_pid = []

    def contender():
        with fixture.database().session(fixture.workspace_id) as other:
            contender_pid.append(other.info.backend_pid)
            started.set()
            if vector_first:
                from exulanica.ingest.repository import IngestRepository

                return IngestRepository(other, fixture.workspace_id).insert_tombstone(
                    scope="capture", capture_id=capture, requested_by=uuid.uuid4()
                )
            try:
                _reinsert(other, embedding, embedding_id=vector_id)
            except psycopg.errors.IntegrityConstraintViolation:
                return "refused"
            return "inserted"

    with ThreadPoolExecutor(max_workers=1) as pool:
        with connection.transaction():
            if vector_first:
                _reinsert(connection, embedding, embedding_id=vector_id)
            else:
                fixture.tombstone_the_capture(capture)
            future = pool.submit(contender)
            assert started.wait(5)
            deadline = monotonic() + 5
            while not connection.execute(
                "select 1 from pg_locks where pid=%s and locktype='advisory' and not granted",
                (contender_pid[0],),
            ).fetchone():
                assert not future.done(), "the competing write bypassed the lifecycle lock"
                assert monotonic() < deadline, "the competing write never reached the lock"
                sleep(0.01)
            # The held transaction owns the lifecycle lock. The other statement must finish
            # only after it commits; the assertions below verify both final commit orders.
        result = future.result(timeout=10)
    if vector_first:
        targets = fixture.rows(
            "select embedding_id from tombstone_embedding_target where tombstone_id=%s", result
        )
        assert {row["embedding_id"] for row in targets} == {embedding["embedding_id"], vector_id}
    else:
        assert result == "refused"
    assert fixture.worker().drain().failed == 0
    assert fixture.rows("select embedding_id from embedding") == []


@pytest.mark.parametrize("enabled", [False, True])
def test_api_services_use_the_configured_client_or_remain_model_disabled(
    queued,
    client,
    transport,
    enabled,
):
    import json

    from exulanica.api.authorisation import TokenDirectory
    from exulanica.api.services import Services
    from exulanica.models.manifest import Role
    from exulanica.models.transport import HttpResponse
    from exulanica.selection.validation import Session

    from conftest import DEFAULT_PAYLOAD
    from model_fakes import chat_body

    provision_workspace(queued.connection, queued.workspace_id)
    vision = client.manifest[Role.VISION].primary.model_id
    embedding = client.manifest[Role.EMBEDDING].primary.model_id
    transport.by_model[vision] = HttpResponse(
        status_code=200,
        text=json.dumps(chat_body(json.dumps({**DEFAULT_PAYLOAD, "people": []}), model=vision)),
    )
    transport.by_model[embedding] = HttpResponse(
        status_code=200,
        text=json.dumps(
            {
                "data": [{"embedding": vector()}],
                "usage": {"prompt_tokens": 20},
            }
        ),
    )
    services = Services(
        database=queued.database,
        readonly_database=queued.database,
        store=queued.store,
        tokens=TokenDirectory({"scripted": Session(queued.workspace_id, uuid.uuid4())}),
        executor_shares_the_write_role=True,
        model_client=client if enabled else None,
        runs_derivative_worker=True,
    )
    worker = services.build_derivative_worker()
    assert worker is not None
    if enabled:
        assert worker._embedding_pass.keywords["client"] is client
    else:
        assert worker._embedding_pass is None
    outcomes = worker.drain()
    assert all(not outcome.errors for outcome in outcomes), outcomes
    expected = len(queued.capture_ids) if enabled else 0
    assert transport.models_called.count(embedding) == expected
    assert (
        queued.connection.execute("select count(*) as n from embedding").fetchone()["n"] == expected
    )
    if enabled:
        assert client.ledger.total_usd > 0  # scripted usage goes through the configured budget
    else:
        assert transport.requests == []
