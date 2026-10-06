"""Reference requests, their jobs and our search records, on a migrated database (migration 0148).

What is checked is what the migration and the store promise: a request and its job are made
together, an idempotency key answers with the earlier request or refuses another body, a claim is
taken once, every write names its claim, a finished request never changes, a search record is never
changed, and the person's words leave the job's payload when it ends, however it ends.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid

import psycopg
import pytest
from exulanica.references import store
from psycopg.rows import tuple_row

pytestmark = pytest.mark.postgres

ACTOR = uuid.UUID("7c1a2b3c-4d5e-4f60-8a71-92b3c4d5e6f7")
DESCRIPTION = "a harbour town with whitewashed houses"
PROMPTS = "e" * 64


def _create(connection, workspace_id, **changes):
    arguments = dict(
        offered_to=(workspace_id,),
        owner_actor_id=ACTOR,
        purpose="kind",
        web=True,
        description=DESCRIPTION,
        withheld_words=["Rosalind", "Teague"],
        prompts_sha256=PROMPTS,
    )
    arguments.update(changes)
    return store.create_request(connection, workspace_id, **arguments)


def _payload(connection, job_id) -> dict:
    return (
        connection.cursor(row_factory=tuple_row)
        .execute("select payload from job where job_id=%s", (job_id,))
        .fetchone()[0]
    )


def _job(connection, job_id) -> tuple:
    return (
        connection.cursor(row_factory=tuple_row)
        .execute("select kind, state, claim_token from job where job_id=%s", (job_id,))
        .fetchone()
    )


def test_a_request_is_made_with_its_queued_job(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    request, made = _create(connection, workspace_id)
    assert made and request.status == "queued" and request.steps == ()
    assert _job(connection, request.job_id)[:2] == ("reference_bundle", "queued")
    assert _payload(connection, request.job_id) == {
        "reference_id": str(request.reference_id),
        "description": DESCRIPTION,
        "withheld_words": ["Rosalind", "Teague"],
    }
    assert store.read_request(connection, workspace_id, request.reference_id) == request


def test_an_idempotency_key_answers_with_the_earlier_request_or_refuses_another_body(
    repository,
) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    key, digest = uuid.uuid4(), hashlib.sha256(b"one body").hexdigest()
    first, made = _create(connection, workspace_id, request_id=key, request_sha256=digest)
    again, made_again = _create(connection, workspace_id, request_id=key, request_sha256=digest)
    assert made and not made_again and again.reference_id == first.reference_id
    with pytest.raises(store.RequestKeyReused):
        _create(
            connection,
            workspace_id,
            request_id=key,
            request_sha256=hashlib.sha256(b"another body").hexdigest(),
        )
    assert (
        connection.cursor(row_factory=tuple_row).execute("select count(*) from job").fetchone()[0]
        == 1
    )


def test_a_claim_is_taken_once_and_its_finish_blanks_the_words(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    request, _ = _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    assert claimed is not None and claimed.request.status == "running"
    assert claimed.description == DESCRIPTION
    assert claimed.withheld_words == ("Rosalind", "Teague")
    assert store.claim(connection, workspace_id, worker="test") is None
    steps = [{"step": "plan", "state": "done"}]
    assert store.record_steps(connection, claimed, steps)
    lookup = store.record_lookup(
        connection,
        claimed,
        source="tavily_search",
        aspect="buildings",
        query="whitewashed island houses",
        outcome="answered",
        credits=1,
        result_count=5,
        provider_request_id="123e4567-e89b-12d3-a456-426614174111",
    )
    assert isinstance(lookup, uuid.UUID)
    bundle = {"profile": "exulanica.reference-bundle/v1"}
    assert store.finish(
        connection, claimed, status="complete", steps=steps, bundle=bundle, bundle_sha256="a" * 64
    )
    finished = store.read_request(connection, workspace_id, request.reference_id)
    assert finished is not None and finished.status == "complete" and finished.finished
    assert finished.bundle == bundle
    assert _job(connection, request.job_id)[1:] == ("done", None)
    assert _payload(connection, request.job_id) == {"reference_id": str(request.reference_id)}


def test_a_finished_request_and_a_search_record_never_change(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    request, _ = _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    store.record_lookup(
        connection,
        claimed,
        source="tavily_search",
        aspect="buildings",
        query="stone quays",
        outcome="answered",
        credits=1,
        result_count=2,
        provider_request_id=None,
    )
    store.finish(connection, claimed, status="failed", steps=[], failure="read_refused")
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute(
            "update reference_request set status='running', finished_at=null, failure=null "
            "where reference_id=%s",
            (request.reference_id,),
        )
    with pytest.raises(psycopg.errors.CheckViolation):
        connection.execute("update reference_lookup set query='something else'")


def test_a_write_naming_a_lost_claim_changes_nothing(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    request, _ = _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    stale = dataclasses.replace(claimed, claim_token=uuid.uuid4())
    assert not store.record_steps(connection, stale, [{"step": "plan", "state": "done"}])
    assert not store.finish(connection, stale, status="cancelled", steps=[])
    assert store.read_request(connection, workspace_id, request.reference_id).status == "running"


def test_a_queued_request_cancels_at_once_and_a_running_one_is_asked(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    queued, _ = _create(connection, workspace_id)
    cancelled = store.request_cancel(connection, workspace_id, queued.reference_id)
    assert cancelled.status == "cancelled" and cancelled.cancel_requested_at is not None
    assert _job(connection, queued.job_id)[1] == "cancelled"
    assert _payload(connection, queued.job_id) == {"reference_id": str(queued.reference_id)}

    running, _ = _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    assert claimed.request.reference_id == running.reference_id
    assert not store.cancel_requested(connection, claimed)
    asked = store.request_cancel(connection, workspace_id, running.reference_id)
    assert asked.status == "running" and asked.cancel_requested_at is not None
    assert store.cancel_requested(connection, claimed)
    assert store.request_cancel(connection, workspace_id, uuid.uuid4()) is None


def test_a_job_stranded_every_claim_is_failed_with_its_words_blanked(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    request, _ = _create(connection, workspace_id)
    store.claim(connection, workspace_id, worker="test")
    connection.execute(
        "update job set attempts=%s, lease_expires_at=now() - interval '1 second' where job_id=%s",
        (store.MAXIMUM_CLAIMS, request.job_id),
    )
    assert store.claim(connection, workspace_id, worker="test") is None
    assert store.abandon_stranded(connection, workspace_id) == 1
    failed = store.read_request(connection, workspace_id, request.reference_id)
    assert (failed.status, failed.failure) == ("failed", "stranded")
    assert _payload(connection, request.job_id) == {"reference_id": str(request.reference_id)}


# Isolation is shown as the runtime role in tests/test_row_level_security.py: here every query runs
# as the owner, whom row-level security does not bind.


def test_no_request_is_queued_for_a_workspace_references_are_not_offered_to(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    with pytest.raises(store.RequestNotOffered):
        _create(connection, workspace_id, offered_to=(uuid.uuid4(),))
    count = connection.cursor(row_factory=tuple_row).execute("select count(*) from job")
    assert count.fetchone()[0] == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"description": "x" * (store.MAX_DESCRIPTION_CHARACTERS + 1)},
        {"description": ""},
        {"withheld_words": ["word"] * (store.MAX_WITHHELD_WORDS + 1)},
        {"withheld_words": ["w" * 65]},
    ],
)
def test_the_words_a_job_holds_are_bounded(repository, changes) -> None:
    with pytest.raises(ValueError):
        _create(repository.connection, repository.workspace_id, **changes)


def test_a_request_s_digest_is_cleared_when_it_ends(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    key, digest = uuid.uuid4(), hashlib.sha256(b"one body").hexdigest()
    first, _ = _create(connection, workspace_id, request_id=key, request_sha256=digest)
    claimed = store.claim(connection, workspace_id, worker="test")
    store.finish(connection, claimed, status="failed", steps=[], failure="read_refused")
    row = connection.cursor(row_factory=tuple_row).execute(
        "select request_id, request_sha256 from reference_request where reference_id=%s",
        (first.reference_id,),
    )
    assert row.fetchone() == (key, None)
    # Once it has ended the key answers with it, its body no longer kept to compare.
    again, made = _create(
        connection,
        workspace_id,
        request_id=key,
        request_sha256=hashlib.sha256(b"another body").hexdigest(),
    )
    assert not made and again.reference_id == first.reference_id


_BUNDLED = (
    "status='complete', finished_at=now(), bundle_sha256=repeat('a', 64), "
    'bundle=\'{"profile": "exulanica.reference-bundle/v1"}\'::jsonb'
)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (_BUNDLED, "from queued to running"),
        ("request_sha256=repeat('b', 64)", "only ever cleared"),
    ],
)
def test_a_queued_request_moves_only_as_its_life_allows(repository, change, message) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    made, _ = _create(
        connection,
        workspace_id,
        request_id=uuid.uuid4(),
        request_sha256=hashlib.sha256(b"body").hexdigest(),
    )
    with pytest.raises(psycopg.errors.CheckViolation, match=message):
        connection.execute(
            f"update reference_request set {change} where reference_id=%s", (made.reference_id,)
        )


def test_a_running_request_never_goes_back_and_a_stop_is_never_withdrawn(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    made, _ = _create(connection, workspace_id)
    store.claim(connection, workspace_id, worker="test")
    with pytest.raises(psycopg.errors.CheckViolation, match="from queued to running"):
        connection.execute(
            "update reference_request set status='queued' where reference_id=%s",
            (made.reference_id,),
        )
    store.request_cancel(connection, workspace_id, made.reference_id)
    with pytest.raises(psycopg.errors.CheckViolation, match="never withdrawn"):
        connection.execute(
            "update reference_request set cancel_requested_at=null where reference_id=%s",
            (made.reference_id,),
        )


def test_a_job_untaken_too_long_expires_with_its_words_blanked(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    made, _ = _create(
        connection,
        workspace_id,
        request_id=uuid.uuid4(),
        request_sha256=hashlib.sha256(b"body").hexdigest(),
    )
    assert store.expire_unclaimed(connection, workspace_id) == 0
    connection.execute(
        "update job set created_at = now() - make_interval(secs => %s) where job_id=%s",
        (store.QUEUED_EXPIRY_SECONDS + 1, made.job_id),
    )
    assert store.expire_unclaimed(connection, workspace_id) == 1
    expired = store.read_request(connection, workspace_id, made.reference_id)
    assert (expired.status, expired.failure) == ("failed", "expired")
    assert _payload(connection, made.job_id) == {"reference_id": str(made.reference_id)}
    digest = connection.cursor(row_factory=tuple_row).execute(
        "select request_sha256 from reference_request where reference_id=%s",
        (made.reference_id,),
    )
    assert digest.fetchone()[0] is None


def test_a_job_naming_no_request_is_failed_and_the_queue_moves_on(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    orphan = (
        connection.cursor(row_factory=tuple_row)
        .execute(
            "insert into job (workspace_id, kind, payload, priority) values (%s, %s, %s, 1) "
            "returning job_id",
            (
                workspace_id,
                store.JOB_KIND,
                psycopg.types.json.Jsonb(
                    {
                        "reference_id": str(uuid.uuid4()),
                        "description": "words",
                        "withheld_words": [],
                    }
                ),
            ),
        )
        .fetchone()[0]
    )
    made, _ = _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    assert claimed is not None and claimed.request.reference_id == made.reference_id
    state = connection.cursor(row_factory=tuple_row).execute(
        "select state, failure_class, payload from job where job_id=%s", (orphan,)
    )
    failed, why, payload = state.fetchone()
    assert (failed, why) == ("failed", "reference_request_missing")
    assert "description" not in payload


def test_a_claimed_request_s_repr_carries_none_of_the_words(repository) -> None:
    connection, workspace_id = repository.connection, repository.workspace_id
    _create(connection, workspace_id)
    claimed = store.claim(connection, workspace_id, worker="test")
    shown = repr(claimed)
    assert DESCRIPTION not in shown and "Rosalind" not in shown and "Teague" not in shown


def test_a_cancel_and_a_claim_together_lock_the_job_first_and_never_deadlock(ingest_spine) -> None:
    import threading

    repository, open_another = ingest_spine
    connection, workspace_id = repository.connection, repository.workspace_id
    made, _ = _create(connection, workspace_id)
    holder = open_another().connection
    failures: list[BaseException] = []
    with holder.transaction():
        # As a claim does: the job's row first.
        holder.execute("select 1 from job where job_id=%s for update", (made.job_id,))

        def cancel() -> None:
            try:
                store.request_cancel(open_another().connection, workspace_id, made.reference_id)
            except BaseException as failure:
                failures.append(failure)

        thread = threading.Thread(target=cancel)
        thread.start()
        thread.join(0.5)
        # The cancel waits on the job's row, so the request's row is still free to take.
        holder.execute(
            "select 1 from reference_request where reference_id=%s for update",
            (made.reference_id,),
        )
    thread.join(10)
    assert not thread.is_alive() and failures == []
