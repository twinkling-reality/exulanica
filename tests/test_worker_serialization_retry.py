"""A write the database defers goes back to the queue instead of failing the job.

Migration 0041 refuses a guarded write outright with SQLSTATE 40001, "asset delivery in progress;
retry mutation", while any reader holds the asset read lock. Measured in the rehearsal of the
personal path: a derivative job failed for good 0.17 s after its claim while the page read
assets. These tests hold the real lock through ``final_read_check`` on a second connection while
the real worker drains, so each refusal comes from the trigger itself.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

from exulanica.db.read_check import final_read_check
from exulanica.ingest import derivative_queue
from exulanica.ingest import worker as worker_module
from exulanica.ingest.worker import DerivativeWorker

from test_intake_upload import upload as upload


@contextmanager
def reading_assets(upload):
    """A reader holding the asset read lock, as a delivery does, for the length of the block."""
    with (
        upload.database.session(upload.workspace_id) as reader,
        final_read_check(reader, not_idle="a test reader holds the asset read lock"),
    ):
        yield


def _drain(upload):
    return DerivativeWorker(
        upload.database, upload.store, frozenset({upload.workspace_id}), name="serialization"
    ).drain()


def _due_now(upload) -> None:
    """Bring a scheduled retry forward, so the test waits on nothing but the work."""
    upload.repository.connection.execute("update job set run_after = now() where state = 'queued'")


def _job(upload) -> dict:
    (row,) = upload.rows("select job_id, state, attempts, failure_class, last_error from job")
    return row


def _events(upload, job_id: uuid.UUID) -> list[dict]:
    return upload.rows(
        "select event_type, failure_class, message from derivative_job_event "
        "where job_id = %s order by occurred_at, event_id",
        job_id,
    )


def test_a_refusal_as_the_job_begins_is_retried_and_the_job_then_succeeds(upload):
    """The rehearsal's case: the pipeline registers its stages, a guarded write, at the claim."""
    assert upload.one().status_code == 202
    with reading_assets(upload):
        first = _drain(upload)
    assert [outcome.retry_scheduled for outcome in first] == [True]
    job = _job(upload)
    assert (job["state"], job["attempts"], job["failure_class"]) == (
        "queued",
        1,
        "SerializationFailure",
    )
    events = _events(upload, job["job_id"])
    assert [event["event_type"] for event in events] == ["claim_acquired", "retry_scheduled"]
    assert "asset delivery in progress; retry mutation" in events[-1]["message"]

    _due_now(upload)
    assert [outcome.errors for outcome in _drain(upload)] == [[]]
    assert _job(upload)["state"] == "done"
    assert _events(upload, job["job_id"])[-1]["event_type"] == "job_succeeded"


def test_a_refusal_inside_a_capture_is_retried(upload, monkeypatch):
    """A reader that takes the lock after the claim refuses the capture's own writes."""
    assert upload.one().status_code == 202
    real = worker_module.PhotoIngestPipeline.ingest_derivatives
    refused = []

    def while_a_reader_holds_the_lock(self, capture_id, **kwargs):
        if refused:
            return real(self, capture_id, **kwargs)
        refused.append(capture_id)
        with reading_assets(upload):
            return real(self, capture_id, **kwargs)

    monkeypatch.setattr(
        worker_module.PhotoIngestPipeline, "ingest_derivatives", while_a_reader_holds_the_lock
    )
    first = _drain(upload)
    assert [outcome.retry_scheduled for outcome in first] == [True]
    job = _job(upload)
    events = _events(upload, job["job_id"])
    failed = [event for event in events if event["event_type"] == "capture_failed"]
    assert [event["failure_class"] for event in failed] == ["SerializationFailure"]
    assert "retry mutation" in failed[0]["message"]
    assert events[-1]["event_type"] == "retry_scheduled"

    _due_now(upload)
    assert [outcome.errors for outcome in _drain(upload)] == [[]]
    assert _job(upload)["state"] == "done"


def test_a_job_that_keeps_being_refused_fails_with_its_reason(upload):
    assert upload.one().status_code == 202
    with reading_assets(upload):
        for _ in range(derivative_queue.MAX_CLAIMS):
            _due_now(upload)
            _drain(upload)
    job = _job(upload)
    assert (job["state"], job["attempts"]) == ("failed", derivative_queue.MAX_CLAIMS)
    assert job["failure_class"] == "retry_exhausted"
    assert "retry mutation" in job["last_error"]
    assert f"retry budget exhausted after {derivative_queue.MAX_CLAIMS}" in job["last_error"]
    kinds = [event["event_type"] for event in _events(upload, job["job_id"])]
    assert kinds.count("retry_scheduled") == derivative_queue.MAX_CLAIMS - 1
    assert kinds[-1] == "job_failed"
