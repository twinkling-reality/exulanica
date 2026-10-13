"""Native kind jobs keep identity, shared admission and publication authority across holders.

All database state and provider responses are isolated fixtures. Historical process-local
holder tests are not treated as proof of shared authority.
"""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from exulanica.selection.kind_drafting import kind_drafting_prompt
from exulanica.world.kind_draft_jobs import KindDraftRepository
from exulanica.world.kinds.document import read_kind
from exulanica.world.kinds.repository import WorkspaceKinds
from exulanica.world.kinds.samples import check_samples
from exulanica.world.world_draft_jobs import WorldDraftRepository

from spending_support import bench as bench
from test_kind_drafts_postgres import (  # noqa: F401
    _named_alias,
    saved_named,
)
from test_kind_drafts_postgres import (
    drafts as drafts,
)
from test_world_draft_jobs_postgres import submit as submit_world
from test_world_kinds_postgres import _uploaded

pytestmark = pytest.mark.postgres
WORDS = "A small farm with private native draft sentinel words"


def submit_kind(repo, actor, *, maximum=12, words=WORDS):
    return repo.submit(
        actor=actor,
        description=words,
        guest=False,
        starts_maximum=maximum,
        workspace_maximum=1,
        deadline_seconds=600,
        manifest_sha256="a" * 64,
        prompt_version=kind_drafting_prompt().prompt_version,
    )


def checked_kind():
    document = _uploaded("farm")
    document["origin"] = "drafted"
    document["provenance"] = {
        "role": "kind_drafter",
        "model": "private/scripted",
        "prompt_version": "private/v1",
        "prompt_sha256": "b" * 64,
        "words_sha256": "c" * 64,
    }
    kind = read_kind(document)
    return kind, check_samples(kind)


def claim_kind(bench, workspace, actor):
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        ident = submit_kind(repo, actor)
        claimed = repo.claim("private-kind-worker")
        assert claimed is not None and claimed.draft_id == ident
    return claimed


def test_native_identity_and_requester_scope_survive_a_fresh_repository(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with bench.runtime.session(workspace) as connection:
        ident = submit_kind(KindDraftRepository(connection, workspace), actor)
    with bench.runtime.session(workspace) as connection:
        restarted = KindDraftRepository(connection, workspace)
        assert restarted.get(actor, ident)["description"] == WORDS
        assert ident in {row["draft_id"] for row in restarted.listing(actor)}
        assert restarted.get(uuid.uuid4(), ident) is None
        assert restarted.listing(uuid.uuid4()) == []
    other = uuid.uuid4()
    with bench.runtime.session(other) as connection:
        assert KindDraftRepository(connection, other).get(actor, ident) is None
        assert connection.execute("select 1 from kind_draft_input").fetchall() == []
    assert bench.query("select payload from job where kind='kind_draft'") == [
        {"payload": {"draft_id": str(ident)}}
    ]


@pytest.mark.parametrize("first", ["kind", "world"])
def test_busy_workspace_is_shared_by_both_draft_purposes(bench, first):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    with bench.runtime.session(workspace) as connection:
        if first == "kind":
            submit_kind(KindDraftRepository(connection, workspace), actor)
        else:
            submit_world(WorldDraftRepository(connection, workspace), actor, uuid.uuid4())
    with bench.runtime.session(workspace) as connection:
        with pytest.raises(ValueError, match="kind_draft_busy"):
            if first == "kind":
                submit_world(WorldDraftRepository(connection, workspace), actor, uuid.uuid4())
            else:
                submit_kind(KindDraftRepository(connection, workspace), actor)
        assert connection.execute("select count(*) as n from job").fetchone()["n"] == 1


def test_cross_purpose_actor_quota_serializes_independent_workspaces(bench):
    actor = uuid.uuid4()
    ready = Barrier(2)

    def start(purpose):
        workspace = uuid.uuid4()
        with bench.runtime.session(workspace) as connection:
            ready.wait(timeout=10)
            try:
                if purpose == "kind":
                    submit_kind(KindDraftRepository(connection, workspace), actor, maximum=1)
                else:
                    submit_world(
                        WorldDraftRepository(connection, workspace), actor, uuid.uuid4(), maximum=1
                    )
            except ValueError as refused:
                assert str(refused) == "kind_draft_limit"
                assert connection.execute("select 1 from job").fetchall() == []
                return "refused"
            return "accepted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(start, ("kind", "world")))
    assert sorted(outcomes) == ["accepted", "refused"]


def test_checked_kind_and_outcome_commit_together_and_cannot_publish_twice(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    claimed = claim_kind(bench, workspace, actor)
    kind, report = checked_kind()
    # An outer transaction failure must remove both publication and terminalization.
    with (
        pytest.raises(RuntimeError, match="private rollback"),
        bench.runtime.session(workspace) as connection,
        connection.transaction(),
    ):
        KindDraftRepository(connection, workspace).publish(
            claimed, kind, report, calls=[], model_id="private/scripted"
        )
        raise RuntimeError("private rollback")
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        assert WorkspaceKinds(connection, workspace).version(kind.kind, kind.version) is None
        assert repo.get(actor, claimed.draft_id)["outcome"] is None
        repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        result = repo.get(actor, claimed.draft_id)
        assert result["outcome"] is not None and result["description"] is None
        assert (
            WorkspaceKinds(connection, workspace).version(kind.kind, kind.version).kind.sha256
            == kind.sha256
        )
        assert connection.execute("select 1 from kind_draft_input").fetchall() == []
        with pytest.raises(ValueError):
            repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
        assert (
            connection.execute("select count(*) as n from world_kind_version").fetchone()["n"] == 1
        )
        assert repo.get(actor, claimed.draft_id)["outcome"] == result["outcome"]


def test_workspace_erasure_fences_late_publication_and_forgets_request_words(bench):
    workspace, actor = uuid.uuid4(), uuid.uuid4()
    claimed = claim_kind(bench, workspace, actor)
    kind, report = checked_kind()
    with bench.runtime.session(workspace) as connection:
        connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by,reason) "
            "values(%s,'workspace',%s,%s)",
            (workspace, actor, "Private native kind cancellation"),
        )
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        assert repo.get(actor, claimed.draft_id) is None
        with pytest.raises(ValueError):
            repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
        for table in (
            "kind_draft_input",
            "kind_draft_attempt",
            "kind_draft_outcome",
            "world_kind_version",
        ):
            assert connection.execute(f"select 1 from {table}").fetchall() == []
        row = connection.execute(
            "select state,claim_token,payload from job where job_id=%s", (claimed.job_id,)
        ).fetchone()
        assert row["state"] == "cancelled" and row["claim_token"] is None
        assert WORDS not in str(row["payload"])


def test_terminal_refusal_keeps_codes_but_forgets_original_words(bench):
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from exulanica.api.kind_draft_worker import _Recorder
    from exulanica.api.kind_drafts import KindDraft, KindDrafts

    workspace, actor = uuid.uuid4(), uuid.uuid4()
    claimed = claim_kind(bench, workspace, actor)
    holder = KindDrafts()
    draft = KindDraft(claimed.draft_id, workspace, actor, WORDS, datetime.now(UTC), holder.clock())
    _Recorder(SimpleNamespace(database=bench.runtime, holder=holder, client=None), claimed).finish(
        draft,
        refusal={"code": "kind_draft_failed", "detail": WORDS, "where": WORDS},
        calls=[],
        model_id=WORDS,
    )
    assert draft.description == "" and draft.state == "refused"
    with bench.runtime.session(workspace) as connection:
        result = KindDraftRepository(connection, workspace).get(actor, claimed.draft_id)
        assert result["description"] is None
        assert result["outcome"]["refusal"]["code"] == "kind_draft_failed"
        assert result["outcome"]["model_id"] is None
        assert connection.execute("select 1 from kind_draft_input").fetchall() == []
        for table in ("kind_draft_start", "kind_draft_attempt", "kind_draft_outcome", "job"):
            rows = connection.execute(f"select to_jsonb(t) as row from {table} t").fetchall()
            assert WORDS not in str(rows)


@pytest.mark.parametrize("unknown_model_echo", [False, True])
def test_a_second_api_reads_running_and_finished_native_jobs_without_a_model(
    drafts, unknown_model_echo
):
    import json
    from dataclasses import replace

    from exulanica.api.app import create_app
    from exulanica.api.kind_drafts import KindDrafts
    from fastapi.testclient import TestClient

    from test_kind_drafts_postgres import (
        NEIGHBOUR_TOKEN,
        OTHER_TOKEN,
        TOKEN,
        _ended,
        _farm,
        _read,
        _reply,
        _start,
    )

    factory, transport = drafts
    transport.release.clear()
    reply = _reply(_farm())
    raw = json.loads(reply.text)
    if unknown_model_echo:
        raw["model"] = WORDS
    transport.responses.append(replace(reply, text=json.dumps(raw)))
    with factory() as creator:
        started = _start(creator, WORDS)
        assert started.status_code == 202, started.text
        ident = started.json()["draft_id"]
        try:
            assert transport.arrived.wait(10), "the scripted request never started"
            services = replace(
                creator.app.state.services, kind_drafts=KindDrafts(), model_client=None
            )
            with TestClient(create_app(services, verify=False)) as reader:
                pending = _read(reader, ident)
                assert pending.status_code == 200 and pending.json()["description"] == WORDS
                for token in (NEIGHBOUR_TOKEN, OTHER_TOKEN):
                    assert _read(reader, ident, token).status_code == 404
                transport.release.set()
                finished = _ended(creator, ident)
                assert finished["state"] == ("refused" if unknown_model_echo else "ready"), finished
                if unknown_model_echo:
                    assert finished["refusal"]["code"] == "kind_draft_model_failed"
                    assert finished["model_id"] is None and finished["kind"] is None
                asked = len(transport.requests)
                same = _read(reader, ident)
                assert same.status_code == 200, same.text
                assert same.json()["kind"] == finished["kind"]
                assert same.json()["description"] == ""
                listed = reader.get(
                    "/worlds/kinds/drafts", headers={"Authorization": f"Bearer {TOKEN}"}
                )
                assert ident in {row["draft_id"] for row in listed.json()["drafts"]}
                assert len(transport.requests) == asked
                session = services.tokens.session_for(TOKEN)
                with services.database.session(session.workspace_id) as connection:
                    stored = KindDraftRepository(connection, session.workspace_id).get(
                        session.actor, uuid.UUID(ident)
                    )
                    assert stored["outcome"]["calls"], "the real scripted call must be recorded"
                    if unknown_model_echo:
                        call = stored["outcome"]["calls"][0]
                        assert call["served_model"] is None
                        assert call["served_model_unavailable"] == "reported_model_not_admitted"
                        assert (
                            connection.execute("select 1 from world_kind_version").fetchall() == []
                        )
                    for table in (
                        "kind_draft_start",
                        "kind_draft_input",
                        "kind_draft_attempt",
                        "kind_draft_outcome",
                        "job",
                    ):
                        rows = connection.execute(
                            f"select to_jsonb(t) as row from {table} t"
                        ).fetchall()
                        assert WORDS not in str(rows)
        finally:
            transport.release.set()
    # Both original holder and reader have stopped. A fresh process-equivalent app still reads.
    with TestClient(
        create_app(replace(services, kind_drafts=KindDrafts()), verify=False)
    ) as reader:
        assert _read(reader, ident).json()["kind"] == finished["kind"]
        assert _read(reader, ident).json()["state"] == finished["state"]
        assert len(transport.requests) == asked


def test_fresh_app_discovers_never_claimed_work_without_a_process_local_notification(drafts):
    from exulanica.api.world_draft_worker import manifest_sha256

    from test_kind_drafts_postgres import TOKEN, _ended, _farm, _reply

    factory, transport = drafts
    # Admission committed before any worker existed. No holder or notification survives.
    original = factory()
    services = original.app.state.services
    session = services.tokens.session_for(TOKEN)
    with services.database.session(session.workspace_id) as connection:
        repo = KindDraftRepository(connection, session.workspace_id)
        ident = repo.submit(
            actor=session.actor,
            description=WORDS,
            guest=False,
            starts_maximum=12,
            workspace_maximum=1,
            deadline_seconds=600,
            manifest_sha256=manifest_sha256(services.model_client),
            prompt_version=kind_drafting_prompt().prompt_version,
        )
        assert repo.get(session.actor, ident)["state"] == "queued"
    original.close()
    transport.responses.append(_reply(_farm()))
    with factory() as restarted:
        assert restarted.app.state.services.kind_drafts is not services.kind_drafts
        assert transport.arrived.wait(10), "startup did not discover the queued native draft"
        finished = _ended(restarted, str(ident))
        assert finished["state"] == "ready", finished
        assert finished["description"] == ""
        assert len(transport.requests) == 1
    with services.database.session(session.workspace_id) as connection:
        row = KindDraftRepository(connection, session.workspace_id).get(session.actor, ident)
        assert row["outcome"]["kind"] == finished["kind"]["kind"]
        assert (
            connection.execute(
                "select attempts from job where job_id=%s", (row["job_id"],)
            ).fetchone()["attempts"]
            == 1
        )


def test_stale_claim_cannot_append_even_below_the_repository_precheck(bench):
    import psycopg

    workspace, actor = uuid.uuid4(), uuid.uuid4()
    claimed = claim_kind(bench, workspace, actor)
    kind, report = checked_kind()
    with bench.runtime.session(workspace) as connection:
        connection.execute(
            "update job set claim_token=%s where job_id=%s", (uuid.uuid4(), claimed.job_id)
        )
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        with pytest.raises(ValueError, match="kind_draft_lease_lost"):
            repo.publish(claimed, kind, report, calls=[], model_id="private/scripted")
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(
                "select set_config('exulanica.kind_draft_claim',%s,true)",
                (str(claimed.claim_token),),
            )
            WorkspaceKinds(connection, workspace).append(kind, report, created_by=actor)
        assert connection.execute("select 1 from world_kind_version").fetchall() == []
        assert connection.execute("select 1 from kind_draft_outcome").fetchall() == []


@pytest.mark.parametrize("durable_spending", [False, True])
def test_an_expired_running_claim_is_refused_without_a_second_provider_attempt(
    bench, durable_spending
):
    from exulanica.api.kind_draft_worker import KindDraftWorker
    from exulanica.api.kind_drafts import KindDrafts
    from exulanica.api.world_draft_worker import manifest_sha256

    from model_fakes import FakeTransport
    from spending_support import WorkspacePolicy, spending_client

    workspace, actor = uuid.uuid4(), uuid.uuid4()
    transport = FakeTransport()
    spending = bench.durable("native-expired") if durable_spending else None
    client = spending_client(spending, transport)
    with bench.runtime.session(workspace) as connection:
        repo = KindDraftRepository(connection, workspace)
        ident = repo.submit(
            actor=actor,
            description=WORDS,
            guest=False,
            starts_maximum=12,
            workspace_maximum=1,
            deadline_seconds=600,
            manifest_sha256=manifest_sha256(client),
            prompt_version=kind_drafting_prompt().prompt_version,
        )
        original = repo.claim("former-kind-worker")
        assert original is not None
        connection.execute(
            "update job set lease_expires_at=clock_timestamp()-interval '1 second' where job_id=%s",
            (original.job_id,),
        )
    worker = KindDraftWorker(
        bench.runtime,
        client=client,
        spending=spending,
        holder=KindDrafts(),
        policy_for=lambda scope: WorkspacePolicy(scope),
        workspaces=lambda: (workspace,),
    )
    assert worker.run_once(workspace)
    with bench.runtime.session(workspace) as connection:
        row = KindDraftRepository(connection, workspace).get(actor, ident)
        assert row["state"] == "failed"
        assert row["outcome"]["refusal"]["code"] == "kind_draft_failed"
        assert row["description"] is None
        assert connection.execute("select 1 from kind_draft_input").fetchall() == []
        assert connection.execute("select 1 from world_kind_version").fetchall() == []
    assert not worker.run_once(workspace)
    assert transport.requests == []
    assert bench.query("select 1 from spending_reservation") == []


@pytest.mark.parametrize("first", ["cancel", "dispatch"])
def test_native_dispatch_guard_and_cancellation_preserve_real_liability(bench, first):
    from types import SimpleNamespace

    from exulanica.api.kind_draft_worker import KindDraftSpending
    from exulanica.models.spending import SpendingRefused

    from spending_support import reported_usage, spending_request

    workspace, actor = uuid.uuid4(), uuid.uuid4()
    claimed = claim_kind(bench, workspace, actor)
    authority = bench.issue(ceiling="1")
    bench.grant(authority, workspace, ceiling="1")
    gate = KindDraftSpending(SimpleNamespace(spending=bench.durable("native-fence")), claimed)
    ticket = gate.admit(spending_request(key=f"kind-draft:{claimed.draft_id}:private-dispatch"))
    if first == "dispatch":
        gate.dispatch(ticket)
    with bench.runtime.session(workspace) as connection:
        connection.execute(
            "insert into tombstone(workspace_id,scope,requested_by,reason) "
            "values(%s,'workspace',%s,'Private native dispatch cancellation')",
            (workspace, actor),
        )
    if first == "cancel":
        with pytest.raises(SpendingRefused):
            gate.dispatch(ticket)
        assert bench.query("select state from spending_reservation") == [{"state": "admitted"}]
        gate.release(ticket)
    else:
        gate.settle(ticket, reported_usage(str(ticket.usd)))
        row = bench.query("select state,settled_usd from spending_reservation")[0]
        assert row["state"] == "settled" and row["settled_usd"] == ticket.usd
    assert bench.query("select 1 from kind_draft_attempt") == []
    assert bench.query("select 1 from kind_draft_outcome") == []
    assert bench.query("select 1 from kind_draft_input") == []
