"""A creature drafted from a person's words, as the database and the worker hold it (0184).

What is shown, against PostgreSQL, as the deployed writer (the runtime role), with the drafter's
replies scripted (no network, no key, no money):

*   a draft is queued with its job, played by the worker and kept in the workspace's own store; the
    draft names the kind it made by its document's digest alone, and once it ends neither the draft
    nor its job holds a word of the person's or of the drafted label;
*   a creature the checks refuse twice is refused by the check's code and the form's field, and a
    person reads the code's fixed sentence (an unbuilt movement in the grammar's own sentence),
    never the check's, which may quote the label; nothing is kept;
*   a drafter that does not answer fails the draft by name;
*   a draft is queued only for a workspace a worker here serves, one open at a time for one
    requester, and is read by its requester alone;
*   a draft queued and never taken, or its workspace no longer served, ends as failed with its
    words blanked; a worker that lost its claim ends nothing;
*   a workspace tombstone, written by the runtime role or by the owner, cancels the workspace's
    unfinished drafts with their words blanked in its own transaction, and nothing of another
    workspace or of another kind of tombstone; a draft asked once the tombstone is written, or while
    it is being written, is refused with no job written; a worker whose draft was cancelled while it
    drafted keeps nothing.
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from exulanica.api.services import Services
from exulanica.db.roles import RUNTIME_ROLE, provision_runtime_role
from exulanica.errors import TombstonedError
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.policy import HostedRequestRefused
from exulanica.models.spending import SpendingRefused
from exulanica.models.transport import HttpResponse
from exulanica.selection import creature_drafts as drafts
from exulanica.selection.creature_drafting import CHECK_SENTENCES, NOT_DRAFTED_SENTENCE
from exulanica.store.configured import local_content_stores
from exulanica.world.thing_store import ThingStore

from conftest import scratch_role_database
from creature_support import form_of
from model_fakes import FakeTransport, RecordingPolicy, chat_body

pytestmark = pytest.mark.postgres

WORDS = "a gentle horse that walks the hills"


@pytest.fixture
def served(repository, spine_schema, tmp_path):
    provision_runtime_role(repository.connection)
    repository.connection.commit()
    return (
        scratch_role_database(spine_schema[1], RUNTIME_ROLE),
        repository.workspace_id,
        local_content_stores(tmp_path / "data"),
    )


def _transport(form: dict | None = None) -> FakeTransport:
    """Every call answered with ``form``, or a refusal to serve when there is none."""
    transport = FakeTransport()
    manifest = load_manifest()
    binding = manifest[Role.CREATURE_DRAFTER]
    models = [binding.primary.model_id] + (
        [] if binding.fallback is None else [binding.fallback.model_id]
    )
    for model_id in models:
        transport.by_model[str(model_id)] = (
            HttpResponse(status_code=503, text="unavailable")
            if form is None
            else HttpResponse(
                status_code=200, text=json.dumps(chat_body(json.dumps(form), model=str(model_id)))
            )
        )
    return transport


def _worker(database, workspace_id, stores, transport, policy=None) -> drafts.CreatureDraftWorker:
    client = ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport,
        budget=BudgetGuard(),
        policy=RecordingPolicy(),
    )
    return drafts.CreatureDraftWorker(
        database,
        client=client,
        policy_for=lambda _workspace: RecordingPolicy() if policy is None else policy,
        looks_for=stores.looks.for_workspace,
        workspaces=lambda: [workspace_id],
    )


def _queue(connection, workspace_id, actor, words=WORDS) -> drafts.CreatureDraft:
    return drafts.create_draft(
        connection,
        workspace_id,
        offered_to={workspace_id},
        owner_actor_id=actor,
        words=words,
        sent=words,
        placeholders={},
    )


def _payload(connection, draft: drafts.CreatureDraft) -> dict:
    return connection.execute(
        "select payload from job where job_id=%s", (draft.job_id,)
    ).fetchone()["payload"]


def _kept_of(connection, draft: drafts.CreatureDraft) -> str:
    """Everything the draft's row and its job's row hold, as text."""
    rows = connection.execute(
        "select row_to_json(d)::text as draft, (select row_to_json(j)::text from job j "
        "where j.job_id = d.job_id) as job from creature_draft d where d.draft_id = %s",
        (draft.draft_id,),
    ).fetchone()
    return f"{rows['draft']} {rows['job']}"


def _words_held(text: str, *phrases: str) -> set[str]:
    """Each word of four letters or more of ``phrases`` that ``text`` holds."""
    words = {word for phrase in phrases for word in re.findall(r"[a-z]{4,}", phrase.lower())}
    return {word for word in words if word in text.lower()}


def test_a_draft_is_queued_played_and_kept_with_no_word_left_on_it(served):
    database, workspace_id, stores = served
    actor = uuid.uuid4()
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, actor)
        assert queued.status == "queued"
        assert _payload(connection, queued)["sent"] == WORDS
    form = form_of("horse", label="hill walker")
    worker = _worker(database, workspace_id, stores, _transport(form))
    assert worker.run_once(workspace_id) == "kept"
    assert worker.run_once(workspace_id) is None
    with database.session(workspace_id) as connection:
        kept = drafts.read_draft(connection, workspace_id, queued.draft_id, owner_actor_id=actor)
        assert kept is not None and kept.status == "kept" and kept.finished_at is not None
        assert kept.model_id == str(load_manifest()[Role.CREATURE_DRAFTER].primary.model_id)
        kind = ThingStore(connection, workspace_id, None).kind("hill_walker", 1)
        assert kind is not None and kind.label == "hill walker"
        # The draft names the kind by its document's digest alone.
        assert kept.kind_sha256 == kind.sha256
        # The words are gone from the job, and neither row holds the words or the label.
        assert _payload(connection, queued) == {"draft_id": str(queued.draft_id)}
        assert _words_held(_kept_of(connection, queued), WORDS, kind.label, kind.kind) == set()
        job = connection.execute(
            "select state from job where job_id=%s", (queued.job_id,)
        ).fetchone()
        assert job["state"] == "done"


def test_a_creature_the_checks_refuse_twice_is_refused_by_code_and_field(served):
    database, workspace_id, stores = served
    actor = uuid.uuid4()
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, actor, "a red dragon that circles the town")
    form = form_of("dragon", label="red wyrm", moves=["walking", "flight"])
    worker = _worker(database, workspace_id, stores, _transport(form))
    assert worker.run_once(workspace_id) == "refused"
    with database.session(workspace_id) as connection:
        refused = drafts.read_draft(connection, workspace_id, queued.draft_id)
        assert refused is not None and refused.status == "refused"
        assert (refused.refusal_code, refused.refusal_field) == (
            "creature_movement_unbuilt",
            "moves_flight",
        )
        assert refused.kind_sha256 is None
        assert (
            connection.execute("select count(*) as n from thing_kind_version").fetchone()["n"] == 0
        )
        assert _payload(connection, queued) == {"draft_id": str(queued.draft_id)}
    # A person reads the grammar's own sentence for the movement, not one the check built.
    assert drafts.refusal_sentence(refused.refusal_code, refused.refusal_field) == (
        "This world has no flying creatures yet."
    )


def test_a_refusal_quoting_the_label_keeps_only_its_code_and_field(served):
    # The name check's own sentence quotes the drafted label; the draft keeps its code and field,
    # and a person reads the code's fixed sentence.
    database, workspace_id, stores = served
    actor = uuid.uuid4()
    form = form_of("horse", label="hill walker")
    with database.session(workspace_id) as connection:
        _queue(connection, workspace_id, actor)
    assert _worker(database, workspace_id, stores, _transport(form)).run_once(workspace_id) == (
        "kept"
    )
    with database.session(workspace_id) as connection:
        again = _queue(connection, workspace_id, actor, "another gentle horse of the hills")
    assert _worker(database, workspace_id, stores, _transport(form)).run_once(workspace_id) == (
        "refused"
    )
    with database.session(workspace_id) as connection:
        refused = drafts.read_draft(connection, workspace_id, again.draft_id)
        assert refused is not None
        assert (refused.refusal_code, refused.refusal_field) == ("creature_name_taken", "label")
        assert _words_held(_kept_of(connection, again), "another gentle horse", "hill walker") == (
            set()
        )
    sentence = drafts.refusal_sentence("creature_name_taken", "label")
    assert sentence == CHECK_SENTENCES["creature_name_taken"] and "hill" not in sentence


def test_a_drafter_that_does_not_answer_fails_the_draft_by_name(served):
    database, workspace_id, stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4())
    assert _worker(database, workspace_id, stores, _transport()).run_once(workspace_id) == "failed"
    with database.session(workspace_id) as connection:
        failed = drafts.read_draft(connection, workspace_id, queued.draft_id)
        assert failed is not None
        assert (failed.status, failed.failure) == ("failed", "drafter_unavailable")


def test_a_draft_is_queued_only_where_served_one_at_a_time_and_read_by_its_requester(served):
    database, workspace_id, _stores = served
    actor, other = uuid.uuid4(), uuid.uuid4()
    with database.session(workspace_id) as connection:
        with pytest.raises(drafts.DraftNotOffered):
            drafts.create_draft(
                connection,
                workspace_id,
                offered_to=set(),
                owner_actor_id=actor,
                words=WORDS,
                sent=WORDS,
                placeholders={},
            )
        queued = _queue(connection, workspace_id, actor)
        with pytest.raises(drafts.DraftLimitReached):
            _queue(connection, workspace_id, actor)
        _queue(connection, workspace_id, other)
        assert (
            drafts.read_draft(connection, workspace_id, queued.draft_id, owner_actor_id=other)
            is None
        )
        assert drafts.read_draft(connection, workspace_id, queued.draft_id, owner_actor_id=actor)
    with database.session(uuid.uuid4()) as connection:
        assert connection.execute("select count(*) as n from creature_draft").fetchone()["n"] == 0


def test_drafts_no_worker_will_take_end_as_failed_with_their_words_blanked(served, repository):
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        stale = _queue(connection, workspace_id, uuid.uuid4())
        unserved = _queue(connection, workspace_id, uuid.uuid4())
    # The owner moves one job's clock back past the expiry; the runtime never writes created_at.
    repository.connection.execute(
        "update job set created_at = now() - make_interval(secs => %s) where job_id=%s",
        (drafts.QUEUED_EXPIRY_SECONDS + 60, stale.job_id),
    )
    repository.connection.commit()
    with database.session(workspace_id) as connection:
        assert drafts.expire_unclaimed(connection, workspace_id) == 1
        assert drafts.end_unserved(connection, workspace_id) == 1
        for draft, failure in ((stale, "expired"), (unserved, "not_served")):
            ended = drafts.read_draft(connection, workspace_id, draft.draft_id)
            assert ended is not None and (ended.status, ended.failure) == ("failed", failure)
            assert _payload(connection, draft) == {"draft_id": str(draft.draft_id)}
            assert _words_held(_kept_of(connection, draft), WORDS) == set()


class _Refuses:
    """The workspace's rules refusing the drafter's request as it leaves, with ``refusal``: a
    request the rules refuse, or the spending authority's refusal raised where it leaves."""

    def __init__(self, refusal: Exception) -> None:
        self.refusal = refusal

    def admit(self, _request):
        raise self.refusal


def _by_the_worker(transport, policy=None):
    def end(served, _repository, _draft) -> None:
        database, workspace_id, stores = served
        worker = _worker(database, workspace_id, stores, transport, policy)
        assert worker.run_once(workspace_id) == "failed"

    return end


def _stranded(served, repository, draft) -> None:
    # Claimed as often as it may be, and its lease run out each time.
    repository.connection.execute(
        "update job set state='running', attempts=%s, claim_token=gen_random_uuid(), "
        "lease_expires_at=now() - interval '1 second' where job_id=%s",
        (drafts.MAXIMUM_CLAIMS, draft.job_id),
    )
    repository.connection.commit()
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        assert drafts.abandon_stranded(connection, workspace_id) == 1


def _swept_at_startup(served, _repository, _draft) -> None:
    # A process that knows the workspace by its tokens and serves it no creatures.
    database, workspace_id, _stores = served
    process = SimpleNamespace(
        creature_workspaces=(),
        tokens=SimpleNamespace(workspaces=(workspace_id,)),
        accounts=None,
        database=database,
        serves_creatures_to=lambda _workspace: False,
    )
    assert Services.sweep_creatures(process) == 1


def _orphaned(served, repository, draft) -> None:
    # A job whose payload lost its words names no draft the worker can play: it is failed by name.
    repository.connection.execute(
        "update job set payload = payload - 'sent' where job_id=%s", (draft.job_id,)
    )
    repository.connection.commit()
    database, workspace_id, stores = served
    assert _worker(database, workspace_id, stores, _transport()).run_once(workspace_id) is None


@pytest.mark.parametrize(
    ("end", "failure"),
    [
        (_by_the_worker(_transport()), "drafter_unavailable"),
        (
            _by_the_worker(
                _transport(form_of("horse", label="hill walker")),
                _Refuses(SpendingRefused("spending_not_granted")),
            ),
            "spending_refused",
        ),
        (
            _by_the_worker(
                _transport(form_of("horse", label="hill walker")),
                _Refuses(HostedRequestRefused("the workspace's rules refused the request")),
            ),
            "request_refused",
        ),
        (_stranded, "stranded"),
        (_swept_at_startup, "not_served"),
        (_orphaned, None),
    ],
    ids=["unavailable", "spending", "request", "stranded", "swept", "orphaned"],
)
def test_every_end_without_a_creature_blanks_its_job_s_words(served, repository, end, failure):
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        draft = _queue(connection, workspace_id, uuid.uuid4())
    end(served, repository, draft)
    with database.session(workspace_id) as connection:
        assert _payload(connection, draft) == {"draft_id": str(draft.draft_id)}
        assert _words_held(_kept_of(connection, draft), WORDS) == set()
        ended = drafts.read_draft(connection, workspace_id, draft.draft_id)
        assert ended is not None
        if failure is None:
            job = connection.execute(
                "select state, failure_class from job where job_id=%s", (draft.job_id,)
            ).fetchone()
            assert (job["state"], job["failure_class"]) == ("failed", "creature_draft_missing")
        else:
            assert (ended.status, ended.failure) == ("failed", failure)


def test_a_worker_that_lost_its_claim_ends_nothing(served):
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4())
        claimed = drafts.claim(connection, workspace_id, worker="test")
        assert claimed is not None and claimed.draft.draft_id == queued.draft_id
        stolen = type(claimed)(
            workspace_id=claimed.workspace_id,
            job_id=claimed.job_id,
            claim_token=uuid.uuid4(),
            attempts=claimed.attempts,
            draft=claimed.draft,
            sent=claimed.sent,
            placeholders=claimed.placeholders,
        )
        assert drafts.finish(connection, stolen, status="failed", failure="test") is False
        assert drafts.read_draft(connection, workspace_id, queued.draft_id).status == "running"
        assert drafts.finish(connection, claimed, status="failed", failure="test") is True


def test_a_draft_starts_when_first_taken_and_is_listed_for_its_requester(served):
    database, workspace_id, _stores = served
    actor = uuid.uuid4()
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, actor)
        assert queued.started_at is None
        claimed = drafts.claim(connection, workspace_id, worker="test")
        assert claimed is not None and claimed.draft.started_at is not None
        listed = drafts.list_drafts(connection, workspace_id, owner_actor_id=actor)
        assert [draft.draft_id for draft in listed] == [queued.draft_id]
        assert drafts.list_drafts(connection, workspace_id, owner_actor_id=uuid.uuid4()) == ()


def test_a_refusal_outside_the_closed_list_is_carried_under_the_drafter_s_code(served, monkeypatch):
    database, workspace_id, stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4(), "a red dragon")
    listed = tuple(code for code in drafts.refusal_codes() if code != "creature_movement_unbuilt")
    monkeypatch.setattr(drafts, "refusal_codes", lambda: listed)
    form = form_of("dragon", label="red wyrm", moves=["walking", "flight"])
    assert _worker(database, workspace_id, stores, _transport(form)).run_once(workspace_id) == (
        "refused"
    )
    with database.session(workspace_id) as connection:
        refused = drafts.read_draft(connection, workspace_id, queued.draft_id)
        assert refused is not None
        assert (refused.refusal_code, refused.refusal_field) == ("creature_not_drafted", None)
    assert drafts.refusal_sentence("creature_not_drafted") == NOT_DRAFTED_SENTENCE


def test_the_draft_table_refuses_a_sentence_where_a_code_or_field_belongs(served):
    # The table itself holds a refusal to a code and a field name: a sentence is refused.
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4())
        claimed = drafts.claim(connection, workspace_id, worker="test")
        assert claimed is not None
    for refusal, constraint in (
        (("a kind of thing named hill walker already exists here", None), "refusal_code"),
        (("creature_name_taken", "the label hill walker"), "refusal_field"),
    ):
        with (
            database.session(workspace_id) as connection,
            pytest.raises(psycopg.errors.CheckViolation, match=f"creature_draft_{constraint}"),
        ):
            drafts.finish(connection, claimed, status="refused", refusal=refusal)
    with database.session(workspace_id) as connection:
        assert drafts.read_draft(connection, workspace_id, queued.draft_id).status == "running"


@pytest.mark.parametrize(
    ("status", "named", "constraint"),
    [
        ("kept", {}, "creature_draft_kept_names_its_kind"),
        ("refused", {}, "creature_draft_refusal_named"),
        ("failed", {}, "creature_draft_failure_named"),
        (
            "failed",
            {"kind_sha256": "a" * 64, "failure": "expired"},
            "creature_draft_kept_names_its_kind",
        ),
    ],
)
def test_each_end_names_exactly_what_it_must(served, status, named, constraint):
    # A kept draft names a kind and nothing else does; a refused one a code; a failed one a code.
    database, workspace_id, _stores = served
    with database.session(workspace_id) as connection:
        _queue(connection, workspace_id, uuid.uuid4())
        claimed = drafts.claim(connection, workspace_id, worker="test")
        assert claimed is not None
    with (
        database.session(workspace_id) as connection,
        pytest.raises(psycopg.errors.CheckViolation, match=constraint),
    ):
        drafts.finish(connection, claimed, status=status, **named)


def test_only_a_field_of_the_form_is_kept_as_a_refusal_s_field():
    # A check that names one field of the drafter's form is kept by that field; a place the form has
    # no one field for (the whole creature, several fields) is kept as none.
    assert drafts.refusal_field("moves_flight") == "moves_flight"
    assert drafts.refusal_field("label") == "label"
    for where in (
        "the whole creature",
        "the weight_ fields",
        "length_mm, width_mm, height_mm and span_mm",
    ):
        assert drafts.refusal_field(where) is None


def test_a_refusal_at_no_one_field_keeps_its_code_alone(served, monkeypatch):
    # A check that refused the whole creature names no field of the form; the drafter's outcome is
    # scripted here, as a form that reaches such a check is rare.
    from exulanica.selection import creature_drafting

    database, workspace_id, stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4())
    check = ("body_too_many_bones", "the whole creature", "this body has 130 bones")
    outcome = creature_drafting.CreatureDraftOutcome(
        creature=None,
        refusal=creature_drafting.CreatureDraftRefusal(
            creature_drafting.CreatureDraftRefusalCode.NOT_DRAFTED, NOT_DRAFTED_SENTENCE, check
        ),
        model_id=None,
        calls=(),
        attempts=("check:body_too_many_bones", "check:body_too_many_bones"),
    )
    monkeypatch.setattr(drafts, "draft_creature", lambda *_args, **_named: outcome)
    assert _worker(database, workspace_id, stores, _transport()).run_once(workspace_id) == "refused"
    with database.session(workspace_id) as connection:
        refused = drafts.read_draft(connection, workspace_id, queued.draft_id)
        assert refused is not None
        assert (refused.refusal_code, refused.refusal_field) == ("body_too_many_bones", None)


def _tombstone(writer, database, repository, workspace_id, scope="workspace", **named) -> None:
    """A tombstone of ``workspace_id``, written by the runtime role or by the owner."""
    if writer == "runtime":
        with database.session(workspace_id) as connection:
            connection.execute(
                "insert into tombstone (workspace_id, scope, assertion_id, requested_by, reason) "
                "values (%s, %s, %s, %s, 'the person left')",
                (workspace_id, scope, named.get("assertion_id"), uuid.uuid4()),
            )
    else:
        repository.insert_tombstone(
            scope=scope, requested_by=uuid.uuid4(), reason="the person left", **named
        )
        repository.connection.commit()


def _ended_as(repository, draft: drafts.CreatureDraft) -> dict:
    return repository.connection.execute(
        "select d.status, d.failure, d.finished_at, j.state, j.payload from creature_draft d "
        "join job j on j.job_id = d.job_id where d.draft_id = %s",
        (draft.draft_id,),
    ).fetchone()


@pytest.mark.parametrize("writer", ["runtime", "owner"])
def test_a_workspace_tombstone_cancels_its_unfinished_drafts_and_blanks_their_words(
    served, repository, writer
):
    database, workspace_id, _stores = served
    elsewhere = uuid.uuid4()
    with database.session(workspace_id) as connection:
        ended = _queue(connection, workspace_id, uuid.uuid4(), "a horse that ended")
        claimed = drafts.claim(connection, workspace_id, worker="test")
        assert claimed is not None
        assert drafts.finish(connection, claimed, status="failed", failure="expired")
        running = _queue(connection, workspace_id, uuid.uuid4(), "a horse being drafted")
        assert drafts.claim(connection, workspace_id, worker="test") is not None
        queued = _queue(connection, workspace_id, uuid.uuid4(), "a horse still waiting")
    with database.session(elsewhere) as connection:
        other = drafts.create_draft(
            connection,
            elsewhere,
            offered_to={elsewhere},
            owner_actor_id=uuid.uuid4(),
            words=WORDS,
            sent=WORDS,
            placeholders={},
        )
    # Another kind of tombstone ends no draft.
    _tombstone(
        writer, database, repository, workspace_id, scope="assertion", assertion_id=uuid.uuid4()
    )
    assert _ended_as(repository, queued)["status"] == "queued"
    _tombstone(writer, database, repository, workspace_id)
    for draft, words in ((running, "a horse being drafted"), (queued, "a horse still waiting")):
        row = _ended_as(repository, draft)
        assert (row["status"], row["failure"], row["state"]) == (
            "cancelled",
            "workspace_deleted",
            "cancelled",
        )
        assert row["finished_at"] is not None
        assert row["payload"] == {"draft_id": str(draft.draft_id)}
        assert _words_held(_kept_of(repository.connection, draft), words) == set()
    row = _ended_as(repository, ended)
    assert (row["status"], row["failure"], row["state"]) == ("failed", "expired", "failed")
    with database.session(elsewhere) as connection:
        kept = drafts.read_draft(connection, elsewhere, other.draft_id)
        assert kept is not None and kept.status == "queued"
        assert _payload(connection, other)["sent"] == WORDS


def test_a_draft_asked_after_its_workspace_s_tombstone_is_refused_and_queues_nothing(
    served, repository
):
    database, workspace_id, _stores = served
    _tombstone("runtime", database, repository, workspace_id)
    with database.session(workspace_id) as connection, pytest.raises(TombstonedError):
        _queue(connection, workspace_id, uuid.uuid4())
    held = repository.connection.execute(
        "select (select count(*) from job where workspace_id=%s and kind=%s) as jobs, "
        "(select count(*) from creature_draft where workspace_id=%s) as drafts",
        (workspace_id, drafts.JOB_KIND, workspace_id),
    ).fetchone()
    assert (held["jobs"], held["drafts"]) == (0, 0)


def test_a_draft_asked_while_its_workspace_s_tombstone_is_written_waits_and_is_refused(
    served, repository
):
    database, workspace_id, _stores = served
    outcome: list[str] = []

    def ask() -> None:
        with database.session(workspace_id) as connection:
            try:
                _queue(connection, workspace_id, uuid.uuid4())
            except TombstonedError:
                outcome.append("refused")
            else:
                outcome.append("queued")

    asking = threading.Thread(target=ask)
    with database.session(workspace_id) as erasing, erasing.transaction():
        erasing.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the person left')",
            (workspace_id, uuid.uuid4()),
        )
        asking.start()
        # The draft waits on the workspace's lock, which the tombstone's transaction holds.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not outcome:
            waiting = repository.connection.execute(
                "select count(*) as n from pg_locks where locktype='advisory' and not granted"
            ).fetchone()["n"]
            repository.connection.commit()
            if waiting:
                break
            time.sleep(0.05)
    asking.join(timeout=60)
    assert outcome == ["refused"]
    held = repository.connection.execute(
        "select count(*) as n from job where workspace_id=%s and kind=%s",
        (workspace_id, drafts.JOB_KIND),
    ).fetchone()
    assert held["n"] == 0


def test_a_worker_whose_draft_was_cancelled_while_it_drafted_keeps_nothing(
    served, repository, monkeypatch
):
    database, workspace_id, stores = served
    with database.session(workspace_id) as connection:
        queued = _queue(connection, workspace_id, uuid.uuid4())
    drafting = drafts.draft_creature

    def cancelled_while_drafting(*args, **named):
        # The job is cancelled while the model answers, as a workspace's tombstone cancels it.
        repository.connection.execute(
            "update job set state='cancelled', claim_token=null, lease_expires_at=null, "
            "completed_at=now() where job_id=%s",
            (queued.job_id,),
        )
        repository.connection.commit()
        return drafting(*args, **named)

    monkeypatch.setattr(drafts, "draft_creature", cancelled_while_drafting)
    form = form_of("horse", label="hill walker")
    assert _worker(database, workspace_id, stores, _transport(form)).run_once(workspace_id) == (
        "lost"
    )
    with database.session(workspace_id) as connection:
        assert (
            connection.execute("select count(*) as n from thing_kind_version").fetchone()["n"] == 0
        )
