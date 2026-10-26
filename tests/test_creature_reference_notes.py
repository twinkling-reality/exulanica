"""Reference-conditioned creature drafts through the runtime writer, with scripted providers."""

from __future__ import annotations

import threading
import time
import uuid

import psycopg
import pytest
from exulanica.models.errors import TransportError
from exulanica.models.policy import HostedRequestRefused
from exulanica.models.spending import SpendingRefused, next_request_key
from exulanica.references import store as references
from exulanica.selection import creature_drafts as drafts
from exulanica.world.thing_store import ThingStore

from creature_support import form_of
from reference_fixtures import finished_reference, queued_reference
from test_creature_drafts_postgres import (
    WORDS,
    _payload,
    _Refuses,
    _transport,
    _worker,
)
from test_creature_drafts_postgres import (
    served as served,
)

pytestmark = pytest.mark.postgres


def _queue(connection, workspace, actor, reference_id):
    return drafts.create_draft(
        connection,
        workspace,
        offered_to={workspace},
        owner_actor_id=actor,
        words=WORDS,
        sent=WORDS,
        placeholders={},
        reference_id=reference_id,
    )


def _prepared(served, *, status="complete"):
    database, workspace, _stores = served
    actor = uuid.uuid4()
    with database.session(workspace) as connection:
        reference_id = finished_reference(
            connection,
            workspace,
            actor=actor,
            purpose="things",
            status=status,
        )
        reference = references.read_request(connection, workspace, reference_id)
        draft = _queue(connection, workspace, actor, reference_id)
    return draft, reference


def _withdraw(connection, workspace, reference_id):
    connection.execute(
        "update reference_request set status='withdrawn', bundle=null, bundle_sha256=null "
        "where workspace_id=%s and reference_id=%s",
        (workspace, reference_id),
    )


@pytest.mark.parametrize("status", ["complete", "partial"])
def test_finished_web_notes_reach_creature_and_persist_only_identity(served, status):
    database, workspace, stores = served
    queued, reference = _prepared(served, status=status)
    transport = _transport(form_of("horse", label="hill walker"))
    assert _worker(database, workspace, stores, transport).run_once(workspace) == "kept"
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_usage == {
            "state": "used",
            "code": None,
            "bundle_sha256": reference.bundle_sha256,
            "notes": 3,
            "basis": ["web_description"],
        }
        held = ThingStore(connection, workspace, None).kind_by_digest(draft.kind_sha256)
        assert reference.bundle_sha256 in held.document["origin"]["lineage"]["ingredients"]
        assert held.document["origin"]["by"]["prompt_version"] == "creature-drafting-5"
        assert _payload(connection, queued) == {"draft_id": str(queued.draft_id)}
        row = connection.execute(
            "select row_to_json(d)::text as document from creature_draft d where draft_id=%s",
            (queued.draft_id,),
        ).fetchone()["document"]
        assert "whitewashed" not in row and WORDS not in row
    messages = transport.requests[0]["payload"]["messages"]
    assert "whitewashed stone" not in messages[0]["content"]
    assert "whitewashed stone" in messages[1]["content"]


@pytest.mark.parametrize(
    ("case", "code"),
    [
        ("unknown", "reference_unknown"),
        ("foreign", "reference_unknown"),
        ("purpose", "reference_purpose_differs"),
        ("queued", "reference_not_finished"),
        ("withdrawn", "reference_withdrawn"),
    ],
)
def test_unusable_reference_is_uniformly_visible_fallback_to_v1(served, case, code):
    database, workspace, stores = served
    actor = uuid.uuid4()
    with database.session(workspace) as connection:
        if case == "unknown":
            reference_id = uuid.uuid4()
        elif case == "queued":
            reference_id = queued_reference(connection, workspace, actor=actor, purpose="things")
        else:
            reference_id = finished_reference(
                connection,
                workspace,
                actor=uuid.uuid4() if case == "foreign" else actor,
                purpose="kind" if case == "purpose" else "things",
            )
        if case == "withdrawn":
            _withdraw(connection, workspace, reference_id)
        queued = _queue(connection, workspace, actor, reference_id)
    transport = _transport(form_of("horse", label="hill walker"))
    assert _worker(database, workspace, stores, transport).run_once(workspace) == "kept"
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_usage == {
            "state": "not_used",
            "code": code,
            "bundle_sha256": None,
            "notes": 0,
            "basis": [],
        }
        held = ThingStore(connection, workspace, None).kind_by_digest(draft.kind_sha256)
        assert held.document["origin"]["by"]["prompt_version"] == "creature-drafting-3"
    assert "Reference notes" not in transport.requests[0]["payload"]["messages"][1]["content"]


@pytest.mark.parametrize(
    "refusal", [SpendingRefused("spending_not_granted"), HostedRequestRefused("not admitted")]
)
def test_pre_dispatch_refusal_does_not_claim_note_consumption(served, refusal):
    database, workspace, stores = served
    queued, _reference = _prepared(served)
    transport = _transport(form_of("horse", label="hill walker"))
    assert _worker(database, workspace, stores, transport, _Refuses(refusal)).run_once(
        workspace
    ) == ("failed")
    assert not transport.requests
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_usage["state"] == "not_used"
        assert draft.reference_usage["code"] == "reference_not_sent"


@pytest.mark.parametrize("reached", [False, None])
def test_transport_evidence_distinguishes_non_delivery_from_unknown(served, reached):
    database, workspace, stores = served
    queued, _reference = _prepared(served)
    transport = _transport()

    def unavailable(*args, **kwargs):
        raise TransportError("test connection", reached_provider=reached)

    transport.post_json = unavailable
    assert _worker(database, workspace, stores, transport).run_once(workspace) == "failed"
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_usage["state"] == ("not_used" if reached is False else "unknown")


@pytest.mark.parametrize("stop", ["withdraw", "erase", "reclaim"])
def test_authority_change_during_model_request_is_unblocked_and_discards_answer(served, stop):
    database, workspace, stores = served
    queued, reference = _prepared(served)
    entered, release = threading.Event(), threading.Event()
    transport = _transport(form_of("horse", label="hill walker"))
    original = transport.post_json

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    transport.post_json = blocked
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            _worker(database, workspace, stores, transport).run_once(workspace)
        )
    )
    worker.start()
    try:
        assert entered.wait(10)
        with database.session(workspace) as connection:
            connection.execute("set lock_timeout='2s'")
            if stop == "withdraw":
                _withdraw(connection, workspace, reference.reference_id)
            elif stop == "erase":
                connection.execute(
                    "insert into tombstone(workspace_id,scope,requested_by,reason) "
                    "values(%s,'workspace',%s,'test during generation')",
                    (workspace, uuid.uuid4()),
                )
            else:
                connection.execute(
                    "update job set lease_expires_at=now()-interval '1 second' where job_id=%s",
                    (queued.job_id,),
                )
                assert drafts.claim(connection, workspace, worker="replacement") is not None
    finally:
        release.set()
        worker.join(20)
    assert outcome == ["failed" if stop == "withdraw" else "lost"]
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        if stop == "withdraw":
            assert draft.failure == "reference_withdrawn"
            assert draft.reference_usage["state"] == "used"
        else:
            assert draft.status == ("cancelled" if stop == "erase" else "running")
            assert draft.reference_usage["state"] == "unknown"
        assert (
            connection.execute("select count(*) as n from thing_kind_version").fetchone()["n"] == 0
        )


def test_second_keep_check_waits_for_withdrawal_and_leaves_only_inventoried_bytes(
    served,
    repository,
    monkeypatch,
):
    database, workspace, stores = served
    queued, reference = _prepared(served)
    written, release = threading.Event(), threading.Event()
    original = ThingStore._store

    class PausedStore:
        def __init__(self, actual):
            self.actual = actual

        def __getattr__(self, name):
            return getattr(self.actual, name)

        def put_bytes(self, data):
            result = self.actual.put_bytes(data)
            written.set()
            assert release.wait(10)
            return result

    monkeypatch.setattr(ThingStore, "_store", lambda self: PausedStore(original(self)))
    outcome = []
    worker = threading.Thread(
        target=lambda: outcome.append(
            _worker(
                database,
                workspace,
                stores,
                _transport(form_of("horse", label="hill walker")),
            ).run_once(workspace)
        )
    )
    worker.start()
    try:
        assert written.wait(10)
        with database.session(workspace) as stopping, stopping.transaction():
            _withdraw(stopping, workspace, reference.reference_id)
            release.set()
            # The final keep must wait for this uncommitted withdrawal, not read old notes.
            deadline = time.monotonic() + 10
            blocked = False
            while time.monotonic() < deadline:
                blocked = bool(
                    repository.connection.execute(
                        "select exists(select 1 from pg_locks "
                        "where locktype='transactionid' and not granted) as waiting"
                    ).fetchone()["waiting"]
                )
                repository.connection.commit()
                if blocked:
                    break
                time.sleep(0.02)
            assert blocked
    finally:
        release.set()
        worker.join(20)
    assert outcome == ["failed"]
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.failure == "reference_withdrawn" and draft.reference_usage["state"] == "used"
        assert (
            connection.execute("select count(*) as n from thing_kind_version").fetchone()["n"] == 0
        )
        inventory = connection.execute("select * from look_object").fetchall()
        assert len(inventory) == 1
        # The normal workspace erasure must reach the recorded container even without a look row.
        connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by,reason) "
            "values(%s,'workspace',%s,'test interrupted keep')",
            (workspace, uuid.uuid4()),
        )
        assert (
            connection.execute(
                "select count(*) as n from purge_job where target_kind='look'"
            ).fetchone()["n"]
            > 0
        )


def test_reclaim_keeps_reference_identity_and_spending_key_without_downgrading_delivery(
    served,
    repository,
    monkeypatch,
):
    database, workspace, stores = served
    queued, reference = _prepared(served)
    keys = []
    original = drafts.draft_creature

    def crash_before_result(*args, **kwargs):
        kwargs["before_attempt"]()
        keys.append(next_request_key())
        raise RuntimeError("simulated process exit after possible dispatch")

    monkeypatch.setattr(drafts, "draft_creature", crash_before_result)
    with pytest.raises(RuntimeError, match="simulated"):
        _worker(database, workspace, stores, _transport()).run_once(workspace)
    repository.connection.execute(
        "update job set lease_expires_at=now()-interval '1 second' where job_id=%s",
        (queued.job_id,),
    )
    repository.connection.commit()

    def duplicate_refused(*args, **kwargs):
        kwargs["before_attempt"]()
        keys.append(next_request_key())
        raise SpendingRefused("duplicate_request_unknown")

    monkeypatch.setattr(drafts, "draft_creature", duplicate_refused)
    assert _worker(database, workspace, stores, _transport()).run_once(workspace) == "failed"
    assert keys == [f"creature:{queued.job_id}#1"] * 2
    with database.session(workspace) as connection:
        draft = drafts.read_draft(connection, workspace, queued.draft_id)
        assert draft.reference_id == reference.reference_id
        assert draft.reference_usage["state"] == "unknown"
        assert _payload(connection, queued) == {"draft_id": str(queued.draft_id)}
    monkeypatch.setattr(drafts, "draft_creature", original)


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {"state": "used"},
        {"state": "not_used", "code": None, "bundle_sha256": None, "notes": 0, "basis": []},
    ],
)
def test_runtime_cannot_store_an_incomplete_use_record(served, bad):
    from psycopg.types.json import Jsonb

    database, workspace, _stores = served
    queued, _reference = _prepared(served)
    with (
        database.session(workspace) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
        connection.transaction(),
    ):
        connection.execute(
            "update creature_draft set reference_usage=%s where draft_id=%s",
            (Jsonb(bad), queued.draft_id),
        )
