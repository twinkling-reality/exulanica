"""Our record of a reference search keeps its query text for thirty days, then clears it.

A finished request's search records are written as the worker writes them, with the time each was
sent set back where a test needs an old one. The clear runs through the product's path, as a
non-superuser runtime role under row security calling the database's own function; the table's
trigger is also tried directly as the owner, which a restore or an operator writes as.
"""

from __future__ import annotations

import datetime as dt
import uuid

import psycopg
import psycopg.sql
import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.references import store
from psycopg.rows import tuple_row

from conftest import scratch_role_database
from reference_fixtures import finished_reference

pytestmark = pytest.mark.postgres

RUNTIME = "exulanica_reference_retention_suite"
READ_ONLY = "exulanica_reference_retention_ro_suite"
OLD = dt.timedelta(days=31)
YOUNG = dt.timedelta(days=29)


@pytest.fixture
def searched(repository, spine_schema):
    """A workspace with a finished request and two search records: one 31 days old, one 29."""
    _psycopg, scratch = spine_schema
    connection = repository.connection
    workspace_id = repository.workspace_id
    reference_id = finished_reference(connection, workspace_id)
    old = _record(connection, workspace_id, reference_id, "whitewashed towers on a cliff", OLD)
    young = _record(connection, workspace_id, reference_id, "rope bridges between towers", YOUNG)
    provision_runtime_role(connection, role=RUNTIME)
    provision_runtime_role(connection, role=READ_ONLY, read_only=True)
    connection.commit()
    return (
        repository,
        scratch_role_database(scratch, RUNTIME),
        scratch_role_database(scratch, READ_ONLY),
        old,
        young,
    )


def _record(connection, workspace_id, reference_id, query, age) -> uuid.UUID:
    lookup_id = uuid.uuid4()
    connection.execute(
        "insert into reference_lookup (workspace_id, lookup_id, reference_id, source, aspect, "
        "query, outcome, credits, result_count, provider_request_id, sent_at) values "
        "(%s, %s, %s, 'tavily_search', 'buildings', %s, 'answered', 1, 5, "
        "'123e4567-e89b-12d3-a456-426614174111', statement_timestamp() - %s)",
        (workspace_id, lookup_id, reference_id, query, age),
    )
    return lookup_id


def _row(connection, lookup_id) -> dict:
    row = connection.execute(
        "select to_jsonb(l) as row from reference_lookup l where lookup_id = %s", (lookup_id,)
    ).fetchone()
    return row["row"] if isinstance(row, dict) else row[0]


def test_old_query_text_is_cleared_as_the_runtime_and_the_rest_of_the_record_stays(searched):
    repository, runtime, _readonly, old, young = searched
    before = _row(repository.connection, old)
    with runtime.session(repository.workspace_id) as connection:
        who = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert who == {"rolsuper": False, "rolbypassrls": False}, who
        assert store.clear_old_queries(connection, repository.workspace_id) == 1
        assert store.clear_old_queries(connection, repository.workspace_id) == 0
    after = _row(repository.connection, old)
    assert (after["query"], before["query"]) == (None, "whitewashed towers on a cliff")
    assert after["query_cleared_at"] is not None
    kept = {key for key in before if key not in ("query", "query_cleared_at")}
    assert {key: after[key] for key in kept} == {key: before[key] for key in kept}
    assert _row(repository.connection, young)["query"] == "rope bridges between towers"


def test_the_runtime_cannot_change_a_search_record_itself(searched):
    repository, runtime, _readonly, old, _young = searched
    with (
        runtime.session(repository.workspace_id) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        connection.execute("update reference_lookup set query = null where lookup_id = %s", (old,))


def test_a_role_without_the_grant_cannot_clear(searched):
    repository, _runtime, readonly, _old, _young = searched
    with (
        readonly.session(repository.workspace_id) as connection,
        pytest.raises(psycopg.errors.InsufficientPrivilege),
    ):
        store.clear_old_queries(connection, repository.workspace_id)


def test_a_session_of_one_workspace_cannot_clear_another_s(searched):
    repository, runtime, _readonly, old, _young = searched
    with (
        runtime.session(uuid.uuid4()) as connection,
        pytest.raises(psycopg.Error, match="workspace"),
    ):
        store.clear_old_queries(connection, repository.workspace_id)
    assert _row(repository.connection, old)["query"] is not None


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ("query = null", "kept until"),
        ("query = 'something else'", "appended and never changed"),
        ("query = null, credits = 2", "appended and never changed"),
        ("query = null, query_cleared_at = now() - interval '1 day'", "kept until"),
    ],
)
def test_the_table_allows_only_an_old_query_cleared(searched, change, words):
    repository, _runtime, _readonly, _old, young = searched
    with pytest.raises(psycopg.errors.CheckViolation, match=words):
        repository.connection.execute(
            f"update reference_lookup set {change} where lookup_id = %s", (young,)
        )
    repository.connection.rollback()


def test_an_old_query_cleared_beside_another_change_is_refused(searched):
    """The one change allowed on an old row is the clear alone: anything else beside it is refused
    and the row is left as it was."""
    repository, _runtime, _readonly, old, _young = searched
    connection = repository.connection
    before = _row(connection, old)
    with pytest.raises(psycopg.errors.CheckViolation, match="appended and never changed"):
        connection.execute(
            "update reference_lookup set query = null, credits = 2 where lookup_id = %s", (old,)
        )
    connection.rollback()
    assert _row(connection, old) == before


def test_a_cleared_query_stays_cleared_and_its_time_is_the_database_s(searched):
    repository, _runtime, _readonly, old, _young = searched
    connection = repository.connection
    connection.execute(
        "update reference_lookup set query = null, "
        "query_cleared_at = timestamptz '2000-01-01' where lookup_id = %s",
        (old,),
    )
    cleared = _row(connection, old)["query_cleared_at"]
    assert not cleared.startswith("2000-")
    with pytest.raises(psycopg.errors.CheckViolation, match="appended and never changed"):
        connection.execute(
            "update reference_lookup set query = 'back again' where lookup_id = %s", (old,)
        )
    connection.rollback()


def test_a_search_is_recorded_with_its_query(searched):
    repository, _runtime, _readonly, _old, _young = searched
    connection = repository.connection
    reference_id = connection.execute(
        "select reference_id from reference_request limit 1"
    ).fetchone()["reference_id"]
    for query, cleared in ((None, None), ("a quay", "now()"), (None, "now()")):
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "insert into reference_lookup (workspace_id, reference_id, source, aspect, query, "
                "outcome, credits, result_count, query_cleared_at) values (%s, %s, "
                f"'tavily_search', 'buildings', %s, 'answered', 1, 5, {cleared or 'null'})",
                (repository.workspace_id, reference_id, query),
            )
        connection.rollback()


def test_the_retention_is_one_figure(searched):
    repository = searched[0]
    exact = (
        repository.connection.cursor(row_factory=tuple_row)
        .execute(
            "select reference_lookup_query_retention()::text = '720:00:00', "
            "reference_lookup_query_retention()"
        )
        .fetchone()
    )
    # Hours, not days or a month, compared as text (PostgreSQL holds '30 days' equal to '720
    # hours'): a session's time zone and its daylight saving never move the cutoff.
    assert exact[0] is True
    assert exact[1] == dt.timedelta(days=store.QUERY_RETENTION_DAYS) == dt.timedelta(days=30)


def test_a_worker_clears_old_queries_once_an_hour(searched, monkeypatch):
    from decimal import Decimal

    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.references import worker as worker_module
    from exulanica.references.worker import QUERY_CLEAR_SECONDS, ReferenceWorker

    from model_fakes import FakeTransport, RecordingPolicy
    from test_reference_worker import _Database, _Gate, _Spending

    repository = searched[0]
    cleared: list[uuid.UUID] = []
    real = store.clear_old_queries

    def counted(connection, workspace_id):
        cleared.append(workspace_id)
        return real(connection, workspace_id)

    monkeypatch.setattr(worker_module.store, "clear_old_queries", counted)
    now = [1000.0]
    worker = ReferenceWorker(
        _Database(repository),
        client=ModelClient(
            api_key="test-key-not-real",
            transport=FakeTransport(),
            budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=5),
            policy=RecordingPolicy(),
        ),
        policy_for=lambda workspace: RecordingPolicy(),
        spending=_Spending(_Gate()),
        adapter_for=lambda source: pytest.fail("no source is asked"),
        workspaces=lambda: (repository.workspace_id,),
        clear_clock=lambda: now[0],
    )
    assert worker.run_once(repository.workspace_id) is None
    assert worker.run_once(repository.workspace_id) is None
    now[0] += QUERY_CLEAR_SECONDS - 1
    assert worker.run_once(repository.workspace_id) is None
    assert cleared == [repository.workspace_id]
    now[0] += 1
    worker.run_once(repository.workspace_id)
    assert cleared == [repository.workspace_id] * 2
    assert QUERY_CLEAR_SECONDS == 3600.0


def test_the_reference_routes_and_startup_clear_old_queries(searched, monkeypatch):
    import dataclasses

    from exulanica.api.routes import references as references_route
    from exulanica.api.services import Services

    repository = searched[0]
    cleared: list[uuid.UUID] = []
    monkeypatch.setattr(
        references_route.store, "clear_old_queries", lambda c, w: cleared.append(w) or 0
    )
    services = Services(
        database=_Owner(repository),
        readonly_database=_Owner(repository),
        store=None,
        tokens=None,
        executor_shares_the_write_role=True,
        model_client=None,
        reference_workspaces=(repository.workspace_id,),
    )
    references_route._sweep(services, repository.workspace_id)
    dataclasses.replace(services).sweep_references()
    assert cleared == [repository.workspace_id] * 2


class _AnyWorkspace:
    """The owner's connection as a Database whose sessions open for any workspace (the owner is
    not bound by row security), for a sweep over workspaces the test names."""

    def __init__(self, repository) -> None:
        self._repository = repository

    def session(self, workspace_id):
        import contextlib

        @contextlib.contextmanager
        def opened():
            yield self._repository.connection

        return opened()


class _Owner:
    """The owner's connection as a Database whose sessions are this test's workspace's."""

    def __init__(self, repository) -> None:
        self._repository = repository

    def session(self, workspace_id):
        import contextlib

        @contextlib.contextmanager
        def opened():
            assert workspace_id == self._repository.workspace_id
            yield self._repository.connection

        return opened()


def test_the_function_holds_to_its_workspace_even_when_row_security_does_not(searched):
    """A restore that loads a dump without owners hands a definer back to the migrating superuser
    (0161), which row security does not bind; the function's own workspace condition still holds."""
    from exulanica.db.migrate import provision_workspace
    from exulanica.db.session import set_workspace

    repository = searched[0]
    connection = repository.connection
    elsewhere = uuid.uuid4()
    set_workspace(connection, elsewhere)
    provision_workspace(connection, elsewhere)
    try:
        theirs = _record(
            connection, elsewhere, finished_reference(connection, elsewhere), "a far quay", OLD
        )
    finally:
        set_workspace(connection, repository.workspace_id)
    superuser = connection.execute("select current_user as who").fetchone()["who"]
    assert connection.execute(
        "select rolsuper from pg_roles where rolname = current_user"
    ).fetchone()["rolsuper"]
    connection.execute(
        psycopg.sql.SQL("alter function reference_lookup_clear_queries(uuid) owner to {}").format(
            psycopg.sql.Identifier(superuser)
        )
    )
    try:
        assert store.clear_old_queries(connection, repository.workspace_id) == 1
    finally:
        connection.execute(
            "alter function reference_lookup_clear_queries(uuid) owner to exulanica_definer"
        )
    set_workspace(connection, elsewhere)
    try:
        assert _row(connection, theirs)["query"] == "a far quay"
    finally:
        set_workspace(connection, repository.workspace_id)


def test_a_search_is_never_recorded_as_sent_later(searched):
    repository = searched[0]
    connection = repository.connection
    reference_id = connection.execute(
        "select reference_id from reference_request limit 1"
    ).fetchone()["reference_id"]
    with pytest.raises(psycopg.errors.CheckViolation, match="when it was sent"):
        _record(connection, repository.workspace_id, reference_id, "a later quay", -YOUNG)
    connection.rollback()


def test_the_check_alone_refuses_a_cleared_record_that_keeps_its_query(searched):
    """With user triggers off, as a seed load runs, the restated check is the only wall."""
    repository = searched[0]
    connection = repository.connection
    reference_id = connection.execute(
        "select reference_id from reference_request limit 1"
    ).fetchone()["reference_id"]
    with connection.transaction():
        connection.execute("set local session_replication_role = replica")
        with (
            pytest.raises(psycopg.errors.CheckViolation, match="reference_lookup_query_check"),
            connection.transaction(),
        ):
            connection.execute(
                "insert into reference_lookup (workspace_id, reference_id, source, aspect, query, "
                "outcome, credits, result_count, query_cleared_at) values (%s, %s, "
                "'tavily_search', 'buildings', 'kept words', 'answered', 1, 5, now())",
                (repository.workspace_id, reference_id),
            )
        raise psycopg.Rollback()


def test_the_migration_grants_the_runtime_role_named_exulanica_app(searched):
    """The migration grants EXECUTE itself where exulanica_app exists, as 0149 grants door_prune,
    so a database migrated without provisioning afterwards can still clear."""
    import pathlib
    import re

    repository = searched[0]
    connection = repository.connection
    migration = next(
        pathlib.Path(__file__)
        .parents[1]
        .glob("exulanica/migrations/*_a_search_s_words_are_cleared_after_thirty_days.sql")
    )
    block = re.search(r"do \$runtime\$.*?end \$runtime\$;", migration.read_text(), re.S)
    assert block is not None
    with connection.transaction():
        existed = connection.execute(
            "select 1 from pg_roles where rolname = 'exulanica_app'"
        ).fetchone()
        if existed is None:
            connection.execute("create role exulanica_app nologin")
        connection.execute(
            "revoke all on function reference_lookup_clear_queries(uuid) from exulanica_app"
        )
        connection.execute(block.group(0))
        granted = connection.execute(
            "select has_function_privilege('exulanica_app', "
            "'reference_lookup_clear_queries(uuid)', 'EXECUTE') as granted"
        ).fetchone()["granted"]
        assert granted is True
        raise psycopg.Rollback()


def test_a_failed_clear_never_fails_the_routes_or_startup_and_names_its_class(
    searched, monkeypatch, caplog
):
    import dataclasses
    import logging

    from exulanica.api.routes import references as references_route
    from exulanica.api.services import Services

    repository = searched[0]
    # A second workspace this process knows, sorted after a failing first one, so a sweep that
    # stopped at the first failure would never reach it.
    first, second = sorted((repository.workspace_id, uuid.uuid4()))
    tried: list[uuid.UUID] = []

    def refused_first(connection, workspace_id):
        tried.append(workspace_id)
        if workspace_id == first:
            raise psycopg.errors.InsufficientPrivilege("permission denied for function")
        return 0

    monkeypatch.setattr(store, "clear_old_queries", refused_first)
    services = Services(
        database=_AnyWorkspace(repository),
        readonly_database=_AnyWorkspace(repository),
        store=None,
        tokens=None,
        executor_shares_the_write_role=True,
        model_client=None,
        reference_workspaces=(first, second),
    )
    with caplog.at_level(logging.WARNING):
        references_route._sweep(services, first)
        assert dataclasses.replace(services).sweep_references() == 0
    assert tried == [first, first, second]
    failures = [getattr(record, "failure", None) for record in caplog.records]
    assert failures == ["InsufficientPrivilege", "InsufficientPrivilege"]


def test_a_failed_clear_never_stops_the_worker_s_claim_and_is_tried_a_minute_later(
    searched, monkeypatch, caplog
):
    import logging

    from exulanica.references import worker as worker_module

    repository = searched[0]
    tried: list[uuid.UUID] = []
    claims: list[uuid.UUID] = []

    def refused(connection, workspace_id):
        tried.append(workspace_id)
        raise psycopg.errors.UndefinedFunction(
            "function reference_lookup_clear_queries does not exist"
        )

    def counted_claim(connection, workspace_id, *, worker):
        claims.append(workspace_id)
        return None

    monkeypatch.setattr(store, "clear_old_queries", refused)
    monkeypatch.setattr(worker_module.store, "claim", counted_claim)
    now = [1000.0]
    worker = _worker(repository, clear_clock=lambda: now[0])
    with caplog.at_level(logging.WARNING):
        assert worker.run_once(repository.workspace_id) is None
        # The next pass, a second later: claimed again, the clear not tried again yet.
        now[0] += 1
        assert worker.run_once(repository.workspace_id) is None
        # A minute after the failure (59 s after the last pass), it is tried again, not in an hour.
        now[0] += 59
        assert worker.run_once(repository.workspace_id) is None
    assert claims == [repository.workspace_id] * 3
    assert tried == [repository.workspace_id] * 2
    # Logged once while it keeps failing, with its class.
    failures = [getattr(record, "failure", None) for record in caplog.records]
    assert failures == ["UndefinedFunction"]
    assert worker_module.QUERY_CLEAR_RETRY_SECONDS == 60.0


def test_a_runtime_role_refused_the_clear_still_claims_in_the_same_session(searched):
    """The real refusal, not a stub: the runtime role without EXECUTE is refused, and its session
    (autocommit, as the product opens it) still claims a queued request afterwards."""
    from reference_fixtures import queued_reference

    repository, runtime, _readonly, old, _young = searched
    owner = repository.connection
    reference_id = queued_reference(owner, repository.workspace_id)
    function = "reference_lookup_clear_queries(uuid)"
    owner.execute(
        psycopg.sql.SQL("revoke execute on function {} from {}").format(
            psycopg.sql.SQL(function), psycopg.sql.Identifier(RUNTIME)
        )
    )
    owner.commit()
    try:
        with runtime.session(repository.workspace_id) as connection:
            cleared = store.try_clear_old_queries(connection, repository.workspace_id)
            claimed = store.claim(connection, repository.workspace_id, worker="retention-test")
        assert cleared == store.ClearFailed("InsufficientPrivilege")
        assert claimed is not None and claimed.request.reference_id == reference_id
        assert _row(owner, old)["query"] is not None
    finally:
        owner.execute(
            psycopg.sql.SQL("grant execute on function {} to {}").format(
                psycopg.sql.SQL(function), psycopg.sql.Identifier(RUNTIME)
            )
        )
        owner.commit()


def _worker(repository, **changes):
    from decimal import Decimal

    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.references.worker import ReferenceWorker

    from model_fakes import FakeTransport, RecordingPolicy
    from test_reference_worker import _Database, _Gate, _Spending

    return ReferenceWorker(
        _Database(repository),
        client=ModelClient(
            api_key="test-key-not-real",
            transport=FakeTransport(),
            budget=BudgetGuard(ceiling_usd=Decimal("1.00"), max_calls=5),
            policy=RecordingPolicy(),
        ),
        policy_for=lambda workspace: RecordingPolicy(),
        spending=_Spending(_Gate()),
        adapter_for=lambda source: pytest.fail("no source is asked"),
        workspaces=lambda: (repository.workspace_id,),
        **changes,
    )
