"""Uploads and decodes at their bounds: refused by name, retriable, and leaving nothing behind.

*   A part whose decode waited out its turn is refused as ``busy`` and nothing of it was written.
*   A workspace whose earlier uploads are still being processed, up to its bound, is answered 429
    ``derivative_queue_full`` before a batch is opened.
*   A read that decodes a photograph answers 503 ``capacity_exhausted`` for ``decodes`` when its
    decode waited out its turn.
"""

from __future__ import annotations

import contextlib
import threading
import uuid

import pytest
from exulanica.corpus import decode
from exulanica.corpus.decode import decode_counts, decoding
from fastapi.testclient import TestClient

from capacity_support import FIRST_TOKEN, SECOND_TOKEN, serve
from conftest import photo_bytes

pytestmark = pytest.mark.postgres

_OWNER = {"Authorization": f"Bearer {FIRST_TOKEN}"}


@pytest.fixture
def served(tmp_path, repository, spine_schema, monkeypatch):
    return serve(tmp_path, repository, spine_schema, monkeypatch)


@pytest.fixture
def one_turn(monkeypatch):
    """A way to hold the process's decode turns from another thread, with a short wait to take one.

    The application sets the decode limit when it is built, so a test builds it first and holds
    the turns afterwards. The limit is restored when the test ends.
    """
    before = decode_counts()["limit"]
    monkeypatch.setattr(decode._BOUND, "_wait_seconds", 0.2)
    stack = contextlib.ExitStack()

    def hold() -> None:
        release, holding = threading.Event(), threading.Event()

        def run() -> None:
            with decoding():
                holding.set()
                release.wait(10)

        holder = threading.Thread(target=run)
        holder.start()
        assert holding.wait(5)
        stack.callback(holder.join, 5)
        stack.callback(release.set)

    yield hold
    stack.close()
    decode.configure_decode_concurrency(before)


def _rows(served, sql: str, *params):
    return served.repository.connection.execute(sql, params).fetchall()


def test_a_part_that_waited_out_its_decode_turn_is_busy_and_left_nothing(served, one_turn):
    app = served.app(decodes=1)
    one_turn()
    response = TestClient(app).post(
        "/intake", files=[("files", ("a.jpg", photo_bytes(), "image/jpeg"))], headers=_OWNER
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["accepted"] == []
    assert [(part["filename"], part["reason"]) for part in body["refused"]] == [("a.jpg", "busy")]
    assert body["queued_job_id"] is None
    # No capture, no run: the turn is taken before the pipeline opens one.
    assert _rows(served, "select capture_id from capture") == []
    assert (
        _rows(
            served,
            "select run_id from pipeline_run where batch_id = %s",
            uuid.UUID(body["batch_id"]),
        )
        == []
    )


def test_an_upload_past_its_workspace_queue_bound_is_refused_before_a_batch(served):
    app = served.app(intake_queued_jobs=1)
    client = TestClient(app)
    first = served.upload(app)
    assert first["queued_job_id"] is not None
    batches = len(_rows(served, "select batch_id from intake_batch"))
    refused = client.post(
        "/intake",
        files=[("files", ("b.jpg", photo_bytes(size=(170, 100)), "image/jpeg"))],
        headers=_OWNER,
    )
    assert refused.status_code == 429
    assert refused.json()["code"] == "derivative_queue_full"
    assert refused.headers["retry-after"] == str(refused.json()["retry_after_seconds"])
    assert len(_rows(served, "select batch_id from intake_batch")) == batches
    # Once the earlier upload is processed the same upload is accepted.
    served.drain()
    assert served.upload(app)["queued_job_id"] is not None


def test_a_read_whose_decode_waited_out_its_turn_answers_503_for_decodes(served, one_turn):
    app = served.app(decodes=1)
    served.upload(app)
    span = _rows(
        served, "select span_id from evidence_span where modality = 'still_image' limit 1"
    )[0]["span_id"]
    client = TestClient(app)
    assert client.get(f"/evidence/{span}/region", headers=_OWNER).status_code == 200
    one_turn()
    refused = client.get(f"/evidence/{span}/region", headers=_OWNER)
    assert refused.status_code == 503
    assert refused.json()["code"] == "capacity_exhausted"
    assert refused.json()["capacity"] == "decodes"
    assert refused.headers["retry-after"] == "5"


def test_a_job_reads_as_queued_then_done_and_an_unknown_or_foreign_job_is_not_found(served):
    app = served.app()
    client = TestClient(app)
    job = served.upload(app, count=2)["queued_job_id"]
    queued = client.get(f"/operations/derivative-jobs/{job}", headers=_OWNER)
    assert queued.status_code == 200
    assert (queued.json()["state"], queued.json()["progress"]) == (
        "queued",
        {"completed": 0, "total": 2},
    )
    served.drain()
    done = client.get(f"/operations/derivative-jobs/{job}", headers=_OWNER).json()
    assert (done["state"], done["progress"]["completed"]) == ("done", 2)
    assert done["completed_at"] is not None
    unknown = client.get(f"/operations/derivative-jobs/{uuid.uuid4()}", headers=_OWNER)
    foreign = client.get(
        f"/operations/derivative-jobs/{job}", headers={"Authorization": f"Bearer {SECOND_TOKEN}"}
    )
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.json() == foreign.json()
    assert unknown.json() == {"code": "unknown_reference", "detail": "derivative job not found"}


def test_a_batch_whose_every_photograph_was_withdrawn_closes_cancelled(served):
    app = served.app()
    body = served.upload(app, count=2)
    for part in body["accepted"]:
        capture = uuid.UUID(part["capture_id"])
        served.repository.connection.execute(
            "update capture set deleted_at = now() where capture_id = %s", (capture,)
        )
        served.repository.insert_tombstone(
            scope="capture",
            capture_id=capture,
            requested_by=uuid.uuid4(),
            reason="withdrawn while its derivatives were queued",
        )
    served.drain()
    batch = uuid.UUID(body["batch_id"])
    assert (
        _rows(served, "select status from intake_batch where batch_id = %s", batch)[0]["status"]
        == "cancelled"
    )
    stream = TestClient(app).get(f"/formation/{batch}", headers=_OWNER)
    terminal = [
        __import__("json").loads(line[len("data: ") :])
        for line in stream.text.splitlines()
        if line.startswith("data: ")
    ][-1]
    assert terminal["eventId"] == f"batch:{batch}:cancelled"
    assert terminal["outcome"]["reason"] == "cancelled"
    assert terminal["outcome"]["photographsAvailable"] == 0


def test_an_upload_that_meets_a_held_asset_read_lock_is_busy_and_writes_nothing(served):
    """The stage registration is a guarded write: while a read check holds the lock it is retried,
    then answered 409 busy before a batch exists; once the lock is free the same upload is taken."""
    import psycopg

    app = served.app()
    client = TestClient(app)
    part = [("files", ("a.jpg", photo_bytes(), "image/jpeg"))]
    with psycopg.connect(served.database.url) as reader, reader.transaction():
        reader.execute("select asset_read_lock()")
        held = client.post("/intake", files=part, headers=_OWNER)
    assert held.status_code == 409, held.text
    assert held.json()["code"] == "busy"
    assert held.headers["retry-after"] == "1"
    assert _rows(served, "select batch_id from intake_batch") == []
    free = client.post("/intake", files=part, headers=_OWNER)
    assert free.status_code == 202, free.text
    assert len(free.json()["accepted"]) == 1


def test_a_part_whose_write_met_a_read_check_is_busy_not_failed(served, monkeypatch):
    import psycopg
    from exulanica.ingest.stages import intake as intake_stage

    def refused(*_args, **_kwargs):
        raise psycopg.errors.SerializationFailure("asset delivery in progress; retry mutation")

    app = served.app()
    monkeypatch.setattr(intake_stage, "run", refused)
    response = TestClient(app).post(
        "/intake", files=[("files", ("a.jpg", photo_bytes(), "image/jpeg"))], headers=_OWNER
    )
    assert response.status_code == 202, response.text
    assert [(p["filename"], p["reason"]) for p in response.json()["refused"]] == [("a.jpg", "busy")]


def test_a_stage_registration_that_meets_a_read_check_twice_is_retried_and_admitted(
    served, monkeypatch
):
    import psycopg
    from exulanica.ingest.repository import IngestRepository

    original = IngestRepository.register_stages
    attempts: list[int] = []

    def flaky(self, specs):
        attempts.append(1)
        if len(attempts) < 3:
            raise psycopg.errors.SerializationFailure("asset delivery in progress; retry mutation")
        return original(self, specs)

    monkeypatch.setattr(IngestRepository, "register_stages", flaky)
    response = TestClient(served.app()).post(
        "/intake", files=[("files", ("a.jpg", photo_bytes(), "image/jpeg"))], headers=_OWNER
    )
    assert response.status_code == 202, response.text
    assert len(attempts) == 3
