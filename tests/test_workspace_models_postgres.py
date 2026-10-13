"""The models a workspace added: the appended record (migration 0193), on PostgreSQL.

The repository's rules and the table's own, each by sending it: a fact follows the facts before
it, a request records once, a cut probe is no verdict, rows are appended in order and never
changed, one workspace does not read another's, and a workspace's erasure takes its rows (and
its worlds' budgets for their minds, migration 0190's table) with it. The world these tests
stand in is the shared saved world of the stay requests' ``app`` fixture; nothing here depends
on who lives in it, and no model is asked.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from exulanica.world.minds_budget import MindsBudgetRepository
from exulanica.world.workspace_models import (
    ADDED,
    PROBE_NOT_FINISHED,
    PROBED,
    REMOVED,
    WorkspaceModelRefused,
    WorkspaceModelRepository,
)

import test_society_person_decisions_postgres as decisions
import test_society_stay_requests_api as stays

saved_world = stays.saved_world
app = stays.app

MIGRATION = (
    Path(__file__).resolve().parents[1] / "exulanica/migrations/0193_a_workspace_s_models.sql"
)
PROVIDER = "nebius_token_factory"
MODEL = "someone/New-Model-9B"
STATED = {
    "stated": {"type": "text2text", "use_cases": ["text"], "licence_stated": "Apache 2.0 License"},
    "price": {"input_usd_per_mtok": "0.4", "output_usd_per_mtok": "1.2"},
}
PASSED = {"verified": True, "mechanisms": {"json_schema": {"asked": 6, "answered": 6}}}
FAILED = {"verified": False, "mechanisms": {"json_schema": {"asked": 6, "answered": 2}}}


def _repository(app):
    world, client = app
    services = decisions._services(client)
    return world, services


def _record(app, kind, facts, *, key=None, model=MODEL):
    world, services = _repository(app)
    with services.database.session(world["workspace"]) as connection, connection.transaction():
        return WorkspaceModelRepository(connection, world["workspace"]).record(
            PROVIDER,
            model,
            request_id=key or uuid.uuid4(),
            kind=kind,
            facts=facts,
            recorded_by=world["session"].actor,
        )


def _refused(app, kind, facts, **more) -> str:
    with pytest.raises(WorkspaceModelRefused) as refused:
        _record(app, kind, facts, **more)
    return refused.value.code


def _rows(app) -> list[dict]:
    world, _services = _repository(app)
    return (
        world["connection"]
        .execute(
            "select model_id, model_seq, kind from workspace_model order by model_id, model_seq"
        )
        .fetchall()
    )


def test_a_model_is_added_tried_and_removed_one_appended_fact_at_a_time(app):
    world, services = _repository(app)
    # Nothing is known of a model nobody added, and it can be neither tried nor removed.
    with services.database.session(world["workspace"]) as connection:
        assert (
            WorkspaceModelRepository(connection, world["workspace"]).state(PROVIDER, MODEL) is None
        )
    assert _refused(app, PROBED, PASSED) == "model_not_added"
    assert _refused(app, REMOVED, {"reason": "by_a_person"}) == "model_not_added"
    assert _rows(app) == []

    added = _record(app, ADDED, STATED)
    assert (added.kind, added.model_seq, added.verified, added.verdict) == (ADDED, 1, False, None)
    assert added.added == STATED
    # A probe that was cut is no verdict: the model is not verified by it, nor refused by it.
    cut = _record(app, PROBE_NOT_FINISHED, {"reason": "allowance_spent", "asked": 3})
    assert (cut.kind, cut.model_seq, cut.verified, cut.verdict) == (
        PROBE_NOT_FINISHED,
        2,
        False,
        None,
    )
    failed = _record(app, PROBED, FAILED)
    assert (failed.verified, failed.verdict) == (False, FAILED)
    passed = _record(app, PROBED, PASSED)
    assert (passed.kind, passed.model_seq, passed.verified, passed.verdict) == (
        PROBED,
        4,
        True,
        PASSED,
    )
    # A later cut probe leaves the newest finished verdict standing.
    again = _record(app, PROBE_NOT_FINISHED, {"reason": "process_restarted", "asked": 1})
    assert (again.verified, again.verdict) == (True, PASSED)

    removed = _record(app, REMOVED, {"reason": "by_a_person"})
    assert (removed.kind, removed.removed, removed.verified) == (REMOVED, True, False)
    assert _refused(app, PROBED, PASSED) == "model_removed"
    assert _refused(app, REMOVED, {"reason": "by_a_person"}) == "model_removed"
    # Added again, it is a model not yet tried: the earlier verdict was of the earlier adding.
    back = _record(app, ADDED, STATED)
    assert (back.kind, back.model_seq, back.verified, back.verdict) == (ADDED, 7, False, None)
    assert [row["kind"] for row in _rows(app)] == [
        ADDED,
        PROBE_NOT_FINISHED,
        PROBED,
        PROBED,
        PROBE_NOT_FINISHED,
        REMOVED,
        ADDED,
    ]
    assert [row["model_seq"] for row in _rows(app)] == [1, 2, 3, 4, 5, 6, 7]
    # What a read serves of it names no account.
    served = back.view()
    assert "recorded_by" not in served and str(world["session"].actor) not in str(served)
    assert (served["state"], served["verified"], served["added"]) == (ADDED, False, STATED)


def test_a_request_records_once_and_its_key_names_one_fact(app):
    key = uuid.uuid4()
    first = _record(app, ADDED, STATED, key=key)
    # Asked again, the same request answers the state it left and appends nothing.
    again = _record(app, ADDED, STATED, key=key)
    assert again == first and len(_rows(app)) == 1
    # The key with another fact, or other facts, is refused by name.
    assert _refused(app, REMOVED, {"reason": "by_a_person"}, key=key) == "model_key_reused"
    assert _refused(app, ADDED, {**STATED, "price": None}, key=key) == "model_key_reused"
    # The same key under another model is that model's own request.
    other = _record(app, ADDED, STATED, key=key, model="someone/Another-Model")
    assert (other.model_id, other.model_seq) == ("someone/Another-Model", 1)
    assert len(_rows(app)) == 2


def test_a_request_replays_its_original_state_after_later_facts(app):
    key = uuid.uuid4()
    facts = {**STATED, "mechanisms": ("json_schema", "tool_call")}
    first = _record(app, ADDED, facts, key=key)
    _record(app, PROBED, PASSED)
    _record(app, REMOVED, {"reason": "by_a_person"})
    assert _record(app, ADDED, facts, key=key) == first
    assert len(_rows(app)) == 3


def test_a_probe_cannot_verify_a_later_adding_of_the_model(app):
    first = _record(app, ADDED, STATED)
    facts = {**PASSED, "added_seq": first.added_seq, "added_sha256": first.added_sha256}
    assert _record(app, PROBED, facts).verified
    _record(app, REMOVED, {"reason": "by_a_person"})
    back = _record(app, ADDED, STATED)
    assert _refused(app, PROBED, facts) == "model_probe_stale"
    assert _refused(app, PROBE_NOT_FINISHED, facts) == "model_probe_stale"
    assert not back.verified
    assert _record(
        app, PROBED, {**facts, "added_seq": back.added_seq, "added_sha256": back.added_sha256}
    ).verified


def test_the_workspace_s_models_are_listed_in_the_order_each_was_first_added(app):
    world, services = _repository(app)
    _record(app, ADDED, STATED, model="b/second")
    _record(app, ADDED, STATED, model="a/first-by-name-added-later")
    _record(app, PROBED, PASSED, model="b/second")
    with services.database.session(world["workspace"]) as connection:
        listed = WorkspaceModelRepository(connection, world["workspace"]).listing()
    assert [(model.model_id, model.verified) for model in listed] == [
        ("b/second", True),
        ("a/first-by-name-added-later", False),
    ]


def test_a_row_is_appended_in_order_and_never_changed_or_removed(app):
    world, _services = _repository(app)
    _record(app, ADDED, STATED)
    connection = world["connection"]
    for statement in (
        "update workspace_model set kind = 'removed'",
        "update workspace_model set model_seq = model_seq",
        "delete from workspace_model",
    ):
        with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
            connection.execute(statement)
    # A row out of order is refused by the table itself, whoever writes it. The row is whole in
    # every other way (its document says the same sequence and request), so only the order of it
    # is refused: the same row at the next sequence is taken.
    skipping = (
        "insert into workspace_model(workspace_id,provider,model_id,model_seq,request_id,kind,"
        "document,document_sha256,recorded_by) select workspace_id,provider,model_id,%(seq)s,"
        "%(request)s,kind,document || jsonb_build_object('model_seq',%(seq)s::bigint,"
        "'request_id',%(request)s::text),document_sha256,recorded_by from workspace_model "
        "where model_seq=1"
    )
    out_of_order = pytest.raises(psycopg.errors.CheckViolation, match="appended in order")
    with out_of_order, connection.transaction():
        connection.execute(skipping, {"seq": 5, "request": uuid.uuid4()})
    assert [(row["model_seq"], row["kind"]) for row in _rows(app)] == [(1, ADDED)]
    with connection.transaction():
        connection.execute(skipping, {"seq": 2, "request": uuid.uuid4()})
    assert [(row["model_seq"], row["kind"]) for row in _rows(app)] == [(1, ADDED), (2, ADDED)]


def test_another_workspace_reads_none_of_it(app):
    world, services = _repository(app)
    _record(app, ADDED, STATED)
    elsewhere = uuid.uuid4()
    with services.database.session(elsewhere) as connection:
        repository = WorkspaceModelRepository(connection, elsewhere)
        assert repository.state(PROVIDER, MODEL) is None and repository.listing() == []
        # Asked for this workspace's rows by its own id, the other session still reads none.
        assert WorkspaceModelRepository(connection, world["workspace"]).listing() == []


# -- what the table itself refuses, whoever writes the row ----------------------------------------

_WHOLE_ROW = (
    "insert into workspace_model(workspace_id,provider,model_id,model_seq,request_id,kind,"
    "document,document_sha256,recorded_by) values(%(workspace)s,%(provider)s,%(model)s,%(seq)s,"
    "%(request)s,%(kind)s,%(document)s::jsonb,%(sha)s,%(by)s)"
)


def _whole(world, *, model, seq=1, kind=ADDED, facts=None, workspace=None, says=None) -> dict:
    """A row whole in every way (its document says what its columns say), but for what the
    caller changes (``says``: what its document says otherwise): so a refusal is of that one
    thing."""
    request, by, sha = uuid.uuid4(), world["session"].actor, "a" * 64
    stated = {
        "profile": "exulanica.workspace-model/v1",
        "provider": PROVIDER,
        "model_id": model,
        "model_seq": seq,
        "request_id": str(request),
        "kind": kind,
        "facts": STATED if facts is None else facts,
        "recorded_by": str(by),
        "document_sha256": sha,
        **(says or {}),
    }
    return {
        "workspace": workspace or world["workspace"],
        "provider": PROVIDER,
        "model": model,
        "seq": seq,
        "request": request,
        "kind": kind,
        "document": json.dumps(stated),
        "sha": sha,
        "by": by,
    }


def _table_refuses(app, row: dict, said: str) -> None:
    world, services = _repository(app)
    refused = pytest.raises(psycopg.Error, match=said)
    with refused, services.database.session(world["workspace"]) as connection:
        connection.execute(_WHOLE_ROW, row)


def test_the_table_refuses_what_is_no_fact_about_this_workspace_s_model(app):
    world, services = _repository(app)
    # The control: a whole row is taken, so each refusal below is of the one thing changed.
    with services.database.session(world["workspace"]) as connection:
        connection.execute(_WHOLE_ROW, _whole(world, model="a/taken"))
    assert [(row["model_id"], row["kind"]) for row in _rows(app)] == [("a/taken", ADDED)]
    # A kind outside the four, of a model that was added (so it is the kind that is refused).
    _table_refuses(app, _whole(world, model="a/taken", seq=2, kind="approved"), "kind_check")
    # A document that disagrees with its columns: another model, another sequence, another kind.
    for changed in ({"model_id": "a/other"}, {"model_seq": 2}, {"kind": PROBED}):
        _table_refuses(
            app, _whole(world, model="a/document", says=changed), "workspace_model_document"
        )
    # A row written for another workspace than the session's.
    _table_refuses(app, _whole(world, model="a/elsewhere", workspace=uuid.uuid4()), "workspace")
    # A document past the bound of 64 KiB.
    _table_refuses(
        app, _whole(world, model="a/large", facts={"stated": "x" * 70_000}), "document_check"
    )
    assert [row["model_id"] for row in _rows(app)] == ["a/taken"]


def test_the_table_holds_the_order_of_the_facts_whoever_writes_them(app):
    """The repository refuses a try of a model nobody added by name; the table refuses the row
    itself, so no writer can leave a history a reader cannot read."""
    world, services = _repository(app)
    order = "only after it was added"
    # The first fact about a model is that it was added.
    for kind in (PROBED, PROBE_NOT_FINISHED, REMOVED):
        _table_refuses(app, _whole(world, model="a/first", kind=kind, facts={}), order)
    # After it was removed, the next is that it was added again.
    _record(app, ADDED, STATED, model="a/gone")
    _record(app, REMOVED, {"reason": "by_a_person"}, model="a/gone")
    for kind in (PROBED, PROBE_NOT_FINISHED, REMOVED):
        _table_refuses(app, _whole(world, model="a/gone", seq=3, kind=kind, facts={}), order)
    with services.database.session(world["workspace"]) as connection:
        connection.execute(_WHOLE_ROW, _whole(world, model="a/gone", seq=3))
    assert [row["kind"] for row in _rows(app)] == [ADDED, REMOVED, ADDED]


# -- erased with its workspace --------------------------------------------------------------------


def _held(world, workspace) -> dict[str, int]:
    """How many rows of each of the two tables a workspace holds, read past row security."""
    return {
        table: world["connection"]
        .execute(f"select count(*) as n from {table} where workspace_id=%s", (workspace,))
        .fetchone()["n"]
        for table in ("workspace_model", "world_minds_budget")
    }


def _tombstone(services, world, workspace) -> None:
    with services.database.session(workspace) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'the workspace is erased')",
            (workspace, world["session"].actor),
        )


def test_a_workspace_s_erasure_takes_its_models_and_its_worlds_budgets_and_nobody_else_s(app):
    world, services = _repository(app)
    here, elsewhere = world["workspace"], uuid.uuid4()
    # This workspace holds two facts about a model and a budget set for its world's minds; each
    # row names the account that asked.
    _record(app, ADDED, STATED)
    _record(app, PROBED, PASSED)
    with services.database.session(here) as connection:
        MindsBudgetRepository(connection, here, world_id=world["binding"].world_id).record(
            decisions.person_role(),
            request_id=uuid.uuid4(),
            usd_per_hour="0.500000",
            decisions_per_hour=300,
            set_by=world["session"].actor,
        )
    # Another workspace holds a fact of its own.
    with services.database.session(elsewhere) as connection, connection.transaction():
        WorkspaceModelRepository(connection, elsewhere).record(
            PROVIDER,
            MODEL,
            request_id=uuid.uuid4(),
            kind=ADDED,
            facts=STATED,
            recorded_by=world["session"].actor,
        )
    assert _held(world, here) == {"workspace_model": 2, "world_minds_budget": 1}
    assert _held(world, elsewhere) == {"workspace_model": 1, "world_minds_budget": 0}

    # The runtime role deletes no row of either, in its own workspace.
    for table in ("workspace_model", "world_minds_budget"):
        with pytest.raises(psycopg.Error), services.database.session(here) as connection:
            connection.execute(f"delete from {table} where workspace_id=%s", (here,))
    # A tombstone is its own workspace's: the other workspace's erasure takes the other's rows
    # and leaves these.
    _tombstone(services, world, elsewhere)
    assert _held(world, elsewhere) == {"workspace_model": 0, "world_minds_budget": 0}
    assert _held(world, here) == {"workspace_model": 2, "world_minds_budget": 1}
    # And one written for another workspace than the session's is refused, erasing nothing.
    with pytest.raises(psycopg.Error), services.database.session(elsewhere) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, requested_by, reason) "
            "values (%s, 'workspace', %s, 'not this session''s workspace')",
            (here, world["session"].actor),
        )
    assert _held(world, here) == {"workspace_model": 2, "world_minds_budget": 1}
    # A tombstone of another scope, of this workspace, erases neither table's rows.
    with services.database.session(here) as connection:
        connection.execute(
            "insert into tombstone (workspace_id, scope, capture_id, requested_by, reason) "
            "values (%s, 'capture', %s, %s, 'one capture is erased')",
            (here, uuid.uuid4(), world["session"].actor),
        )
    assert _held(world, here) == {"workspace_model": 2, "world_minds_budget": 1}
    # This workspace erased: its facts about its models and its worlds' budgets are gone.
    _tombstone(services, world, here)
    assert _held(world, here) == {"workspace_model": 0, "world_minds_budget": 0}


def test_a_workspace_erased_before_the_migration_loses_its_budgets_when_it_runs(app):
    """The migration's own one-off statement, run as it stands in the file, over a workspace
    whose tombstone was written while nothing yet erased a budget (its trigger held off, as
    before the migration), and over one that was never erased."""
    world, services = _repository(app)
    here, admin = world["workspace"], world["connection"]
    text = MIGRATION.read_text(encoding="utf-8")
    one_off = text[text.index("-- (one-off: begin)") : text.index("-- (one-off: end)")]
    assert "delete from world_minds_budget" in one_off and one_off.count("delete from") == 1
    with services.database.session(here) as connection:
        MindsBudgetRepository(connection, here, world_id=world["binding"].world_id).record(
            decisions.person_role(),
            request_id=uuid.uuid4(),
            usd_per_hour="0.500000",
            decisions_per_hour=300,
            set_by=world["session"].actor,
        )
    # Simulate the pre-0193 budget boundary on this isolated schema. The later world
    # erasure trigger would otherwise erase the same budget before the historical one-off.
    triggers = ("tg_tombstone_erases_models_and_minds_budgets", "tg_world_erases_on_tombstone")
    with admin.transaction():
        for trigger in triggers:
            admin.execute(f"alter table tombstone disable trigger {trigger}")
    try:
        # Another workspace was erased: the statement leaves this one's budget.
        _tombstone(services, world, uuid.uuid4())
        with admin.transaction():
            admin.execute(one_off)
        assert _held(world, here)["world_minds_budget"] == 1
        # This workspace was erased with nothing reaching its budget, as before the migration.
        _tombstone(services, world, here)
        assert _held(world, here)["world_minds_budget"] == 1
        with admin.transaction():
            admin.execute(one_off)
    finally:
        with admin.transaction():
            for trigger in triggers:
                admin.execute(f"alter table tombstone enable trigger {trigger}")
    assert _held(world, here)["world_minds_budget"] == 0
    # The statement leaves the table as it found it: guarded, and read by its own workspace only.
    with pytest.raises(psycopg.Error), services.database.session(uuid.uuid4()) as connection:
        connection.execute("delete from world_minds_budget")
    forced = admin.execute(
        "select relname, relforcerowsecurity as forced from pg_class "
        "where relname in ('tombstone', 'world_minds_budget') and relnamespace = "
        "(select relnamespace from pg_class where oid = 'workspace_model'::regclass) "
        "order by relname"
    ).fetchall()
    assert [(row["relname"], row["forced"]) for row in forced] == [
        ("tombstone", True),
        ("world_minds_budget", True),
    ]


def test_a_world_s_minds_budget_cannot_be_deleted_by_a_non_definer_writer(app):
    world, services = _repository(app)
    here, admin = world["workspace"], world["connection"]
    with services.database.session(here) as connection:
        MindsBudgetRepository(connection, here, world_id=world["binding"].world_id).record(
            decisions.person_role(),
            request_id=uuid.uuid4(),
            usd_per_hour="0.500000",
            decisions_per_hour=300,
            set_by=world["session"].actor,
        )
    assert _held(world, here)["world_minds_budget"] == 1
    # The fixture owner can issue DELETE, so refusal must come from the append-only guard,
    # independently of the runtime role's lack of DELETE privileges.
    assert admin.execute("select current_user as role").fetchone()["role"] != "exulanica_definer"
    with (
        pytest.raises(psycopg.errors.CheckViolation, match="appended and never changed"),
        admin.transaction(),
    ):
        admin.execute("delete from world_minds_budget where workspace_id=%s", (here,))
    assert _held(world, here)["world_minds_budget"] == 1
