"""Workspace isolation, exercised as a role that cannot bypass it.

Every other PostgreSQL test in this suite connects as the database owner, who on a default
installation is also a superuser, and PostgreSQL states plainly that "superusers and roles with
the BYPASSRLS attribute always bypass the row security system". So those tests prove the
trigger guards, which fire for superusers too, and prove nothing at all about row-level
security. This file is the one that connects as a role which cannot bypass it.

Two distinct guarantees are checked, because they fail in different ways:

*   A **write** that names another workspace is refused by ``assert_workspace_context()`` inside
    a trigger. That is what the other tests cover.
*   A **read** of another workspace's rows is prevented only by the policy. There is no trigger
    on SELECT and there cannot be one. If the policy is inert, the read succeeds silently and
    nothing anywhere reports a problem.

A third guarantee joined them when the identity repository was split over its eight tables:
that the repository DECLARES the workspace on the connection it was handed. That one is only
visible here for the mirror-image reason. On an owner connection the predicate inside each
statement scopes the read by itself, so removing the declaration changes nothing; with the
policy in force, removing it makes every read empty and every write refused.

The partition case is the one that was actually broken. ``embedding`` is partitioned by
workspace, migration 0001 enables FORCE row-level security on the parent, and the comment there
used to claim partitions inherit it. They do not: a query naming a partition directly is
governed by that partition's own policies, so a partition created without any was readable by
every workspace while the parent reported a correct zero.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest
from exulanica.db.migrate import provision_workspace
from exulanica.db.roles import (
    EXECUTOR_ROLE,
    RUNTIME_ROLE,
    RuntimeRoleUnsafe,
    assert_runtime_role,
    provision_runtime_role,
)
from exulanica.db.session import Database
from exulanica.env import env_get
from exulanica.identity import IdentityRepository
from psycopg.rows import dict_row

from pg_harness import migrated_schema

pytestmark = pytest.mark.postgres

#: Suffixed, because **a role is a CLUSTER object** and the harness's "the database name must
#: contain test" guard does not reach one. Under the deployment's own names, every run of this
#: file rewrote the grants on the developer's live `exulanica_app` and `exulanica_ro` in the same
#: cluster the `orimera` database lives in. `tests/test_purge.py` moved for that reason and this
#: file follows it. The privilege set under test does not change: `provision_runtime_role` takes
#: the role name as an argument and composes every grant and revoke from it, so the suffix moves
#: the identifier and nothing else.
_APP_ROLE = f"{RUNTIME_ROLE}_suite"
_EXECUTOR_ROLE = f"{EXECUTOR_ROLE}_suite"

WIDE_VECTOR = "[" + ",".join(["0.5"] * 4096) + "]"


@pytest.fixture(scope="module")
def isolated():
    """A migrated schema holding one row per table for workspace A, and both runtime roles.

    The roles are the deployment's, under suffixed names. A role is a CLUSTER object and the
    harness's "the database name must contain test" guard does not reach one, so provisioning
    `exulanica_app` and `exulanica_ro` here rewrote the grants on the developer's live roles, in the
    same cluster the `orimera` database lives in. That is what the suffix is for, and
    `tests/test_purge.py` carries the same one.

    It costs nothing that matters: `provision_runtime_role` takes the role name as an argument
    and composes every grant, revoke and default privilege from it, so what these roles hold is
    what a deployment's hold. The one thing the suffix does not inherit is
    `grant_workspace_partition`, which names the real roles; the per-workspace partitions are
    created after this call, so the ALTER DEFAULT PRIVILEGES issued above is what reaches them,
    and `test_naming_the_partition_directly_does_not_escape_the_policy` fails on a permission
    error rather than passing quietly if that ever stops being true.

    They are created without a password: local connections here authenticate by trust, and a
    password on a role only this suite ever connects as would be a credential nobody asked for.
    """
    with migrated_schema() as (_psycopg, admin):
        admin.row_factory = dict_row
        scratch = admin.execute("select current_schema()").fetchone()["current_schema"]
        provision_runtime_role(admin, role=_APP_ROLE)
        provision_runtime_role(admin, role=_EXECUTOR_ROLE, read_only=True)

        workspace_a, workspace_b = uuid.uuid4(), uuid.uuid4()
        for workspace in (workspace_a, workspace_b):
            admin.execute(
                "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
            )
            provision_workspace(admin, workspace)

        admin.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace_a),)
        )
        digest = bytes(range(32))
        admin.execute(
            "insert into blob (blob_sha256, byte_size, media_type) values (%s, 1, 'image/jpeg')",
            (digest,),
        )
        admin.execute(
            "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
            (workspace_a, digest),
        )
        span = admin.execute(
            "insert into evidence_span (workspace_id, blob_sha256, track_key, t_start_ns, "
            "t_end_ns, modality, span_digest) values (%s, %s, 'img', 0, 1, 'still_image', %s) "
            "returning span_id",
            (workspace_a, digest, bytes(32)),
        ).fetchone()["span_id"]
        admin.execute(
            "insert into embedding (workspace_id, family, ref_type, ref_id, model_ref, "
            "pipeline_version, dims, v) values (%s, 'text_chunk', 'span', %s, 'm', 1, 4096, %s)",
            (workspace_a, span, WIDE_VECTOR),
        )
        # A place is the durable plane 0038 added, and it is the newest workspace-keyed table, so
        # it is the one whose isolation is least likely to be covered by habit.
        admin.execute("insert into place (workspace_id) values (%s)", (workspace_a,))
        admin.commit()
        yield Isolated(scratch, workspace_a, workspace_b)


class Isolated:
    def __init__(self, scratch: str, workspace_a: uuid.UUID, workspace_b: uuid.UUID) -> None:
        self.scratch = scratch
        self.workspace_a = workspace_a
        self.workspace_b = workspace_b
        self._open: list[psycopg.Connection] = []

    def _dsn(self, role: str) -> str:
        base = env_get("TEST_DATABASE_URL")
        assert base is not None
        separator = "&" if "?" in base else "?"
        return f"{base}{separator}user={role}"

    def connect(self, role: str, workspace: uuid.UUID) -> psycopg.Connection:
        connection = psycopg.connect(self._dsn(role), autocommit=True, row_factory=dict_row)
        connection.execute(f'set search_path to "{self.scratch}", public')
        connection.execute(
            "select set_config('exulanica.workspace_id', %s, false)", (str(workspace),)
        )
        self._open.append(connection)
        return connection

    def partition_of(self, workspace: uuid.UUID) -> str:
        return f"embedding_ws_{workspace.hex}"

    def close(self) -> None:
        for connection in self._open:
            connection.close()
        self._open.clear()


@pytest.fixture
def scoped(isolated):
    yield isolated
    isolated.close()


def _count(connection: psycopg.Connection, table: str) -> int:
    return connection.execute(f'select count(*) as n from "{table}"').fetchone()["n"]


def test_the_runtime_roles_cannot_bypass_row_level_security(scoped):
    """If either role is a superuser or holds BYPASSRLS, every other test here is vacuous."""
    for role in (_APP_ROLE, _EXECUTOR_ROLE):
        connection = scoped.connect(role, scoped.workspace_a)
        row = connection.execute(
            "select r.rolsuper, r.rolbypassrls, current_user as who from pg_roles r "
            "where r.rolname = current_user"
        ).fetchone()
        assert row["who"] == role
        assert row["rolsuper"] is False, role
        assert row["rolbypassrls"] is False, role


def test_runtime_startup_accepts_the_non_owner_application_role(scoped):
    connection = scoped.connect(_APP_ROLE, scoped.workspace_a)
    assert_runtime_role(connection)


def test_runtime_startup_refuses_the_bootstrap_owner(scoped):
    base = env_get("TEST_DATABASE_URL")
    assert base is not None
    connection = psycopg.connect(base, autocommit=True, row_factory=dict_row)
    scoped._open.append(connection)
    connection.execute(f'set search_path to "{scoped.scratch}", public')
    with pytest.raises(RuntimeRoleUnsafe, match="must connect as a non-owner"):
        assert_runtime_role(connection)


def test_delivery_replay_cannot_name_a_job_from_another_workspace(scoped):
    """The event's RLS key and referenced job must describe the same authorization boundary."""
    from tests_support_api import scratch_database

    with scratch_database(scoped.scratch).session(scoped.workspace_a) as connection:
        job_id = connection.execute(
            "insert into job (workspace_id, kind, payload) values (%s, 'derivatives', '{}') "
            "returning job_id",
            (scoped.workspace_a,),
        ).fetchone()["job_id"]
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(
                "insert into derivative_job_event "
                "(workspace_id, job_id, worker_id, event_type) "
                "values (%s, %s, 'boundary-probe', 'claim_acquired')",
                (scoped.workspace_b, job_id),
            )


@pytest.mark.parametrize("table", ["capture", "evidence_span", "embedding", "place"])
def test_a_workspace_reads_its_own_rows_and_no_other_workspace_sees_them(scoped, table):
    """A policy that refused everything would pass the isolation half of this on its own."""
    mine = scoped.connect(_APP_ROLE, scoped.workspace_a)
    theirs = scoped.connect(_APP_ROLE, scoped.workspace_b)
    assert _count(mine, table) == 1
    assert _count(theirs, table) == 0


def test_naming_the_partition_directly_does_not_escape_the_policy(scoped):
    """The defect. The parent reported a correct zero while the partition handed the rows over.

    ``embedding`` is the table the privacy analysis is about, so this is the worst place in the
    schema for a read to leak, and the leak needed nothing but a different spelling of the table
    name.
    """
    partition = scoped.partition_of(scoped.workspace_a)
    theirs = scoped.connect(_APP_ROLE, scoped.workspace_b)
    assert _count(theirs, "embedding") == 0
    assert _count(theirs, partition) == 0

    mine = scoped.connect(_APP_ROLE, scoped.workspace_a)
    assert _count(mine, partition) == 1


def test_every_per_workspace_partition_carries_its_own_forced_policy(scoped):
    """Structural, so a partition created by some future path cannot quietly omit it."""
    admin = scoped.connect(_APP_ROLE, scoped.workspace_a)
    partitions = admin.execute(
        "select c.relname, c.relrowsecurity, c.relforcerowsecurity "
        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
        "where n.nspname = %s and c.relkind = 'r' and c.relname like 'embedding_ws_%%'",
        (scoped.scratch,),
    ).fetchall()
    assert len(partitions) == 2, partitions
    for row in partitions:
        assert row["relrowsecurity"], row["relname"]
        assert row["relforcerowsecurity"], row["relname"]
        policies = admin.execute(
            "select policyname from pg_policies where schemaname = %s and tablename = %s",
            (scoped.scratch, row["relname"]),
        ).fetchall()
        assert [p["policyname"] for p in policies] == ["ws_isolation"], row["relname"]


def test_the_runtime_role_may_read_the_vocabulary_and_may_not_edit_it(scoped):
    """Defect R3. allows_kind is what stops a model filing a name, and it is workspace-global.

    A runtime role that can widen it disarms invariant 4 for every workspace at once, which is
    why this is a privilege question rather than a policy one: `predicate` carries no
    workspace_id, so there is no policy that could scope it.
    """
    connection = scoped.connect(_APP_ROLE, scoped.workspace_a)
    assert connection.execute("select count(*) as n from predicate").fetchone()["n"] > 0
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute(
            "update predicate set allows_kind = array['user','inference']::assertion_kind[] "
            "where key = 'name_is'"
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute(
            "insert into predicate (key, value_schema, allows_kind, writes_a_name) "
            "values ('nickname_is', '{\"type\":\"string\"}', "
            "array['inference']::assertion_kind[], false)"
        )


@pytest.mark.parametrize("table", ["capture", "evidence_span", "assertion", "occurrence"])
def test_no_runtime_role_may_delete_anything(scoped, table):
    """Deletion is a tombstone, a purge job and a separately authorised purger.

    A role that can DELETE can erase the record of what it erased, which is the one thing the
    whole deletion design exists to prevent.
    """
    for role in (_APP_ROLE, _EXECUTOR_ROLE):
        connection = scoped.connect(role, scoped.workspace_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
            connection.execute(f"delete from {table}")


def test_the_executor_role_cannot_write_at_all(scoped):
    """The Selection executor runs a plan derived from model output. It holds SELECT and nothing
    else, so whatever happens upstream of it cannot become a write."""
    connection = scoped.connect(_EXECUTOR_ROLE, scoped.workspace_a)
    assert _count(connection, "capture") == 1
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute(
            "insert into capture (workspace_id, blob_sha256) values (%s, %s)",
            (scoped.workspace_a, bytes([7]) * 32),
        )
    with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
        connection.execute("update capture set device_id = 'edited'")


def test_a_session_with_no_workspace_declared_reads_nothing(scoped):
    """current_workspace() is NULL, `workspace_id = NULL` is NULL, and NULL is not true.

    This is the direction row-level security has to fail in. The alternative, a policy that
    treats an unset context as "no filter", would make every forgotten set_config a full
    cross-tenant read.
    """
    connection = psycopg.connect(scoped._dsn(_APP_ROLE), autocommit=True, row_factory=dict_row)
    scoped._open.append(connection)
    connection.execute(f'set search_path to "{scoped.scratch}", public')
    assert connection.execute("select current_workspace() as w").fetchone()["w"] is None
    for table in ("capture", "evidence_span", "embedding", "assertion"):
        assert _count(connection, table) == 0, table


def test_an_identity_repository_declares_the_workspace_on_a_connection_that_has_not(scoped):
    """The one line in ``IdentityRepository.__init__`` that no other test in the suite can see.

    Everywhere else the repository is built on an owner connection, and the owner is a superuser,
    so the ``where workspace_id = %s`` predicate inside each statement does all the scoping by
    itself: delete ``set_workspace`` from the constructor and nothing changes anywhere. Here the
    policy is in force. A session that has declared no workspace fails its WITH CHECK on every
    insert and reads nothing at all, so the constructor declaring one is the only reason the
    write below lands and the read below finds it.

    The converse test is ``test_identity.py::test_no_identity_read_crosses_a_workspace_boundary``,
    which has to be run as the owner: with the policy in force a dropped predicate is invisible
    by construction, because ``ws_isolation`` has already filtered to ``current_workspace()``.
    """
    connection = psycopg.connect(scoped._dsn(_APP_ROLE), autocommit=True, row_factory=dict_row)
    scoped._open.append(connection)
    connection.execute(f'set search_path to "{scoped.scratch}", public')
    assert connection.execute("select current_workspace() as w").fetchone()["w"] is None

    mine = IdentityRepository(connection, scoped.workspace_a)
    entity_id = mine.entities.create(entity_class="person")
    event_id = mine.events.record(
        "entity_created", actor=uuid.uuid4(), payload={"entity_id": str(entity_id)}
    )
    assert mine.entities.by_id(entity_id) is not None
    assert mine.events.by_id(event_id) is not None

    # And the policy is doing its own half: a repository for the other workspace, on a fresh
    # connection, cannot see either row however it spells the query.
    other = psycopg.connect(scoped._dsn(_APP_ROLE), autocommit=True, row_factory=dict_row)
    scoped._open.append(other)
    other.execute(f'set search_path to "{scoped.scratch}", public')
    theirs = IdentityRepository(other, scoped.workspace_b)
    assert theirs.entities.by_id(entity_id) is None
    assert theirs.events.by_id(event_id) is None
    assert _count(other, "entity") == 0


def test_unscoped_reads_nothing_even_straight_after_a_scoped_session(scoped):
    """The first bullet of ``Database.unscoped``'s docstring, asserted as ``exulanica_app``.

    It says that as a role row-level security reaches, a caller that wanted workspace data and
    reached for this gets an empty result rather than another workspace's rows. The role is half
    of that sentence and the sibling test below holds the other half. This one is also true
    because every session in this codebase is its own backend: ``psycopg.connect`` per call, no
    pool anywhere. It is the sentence a naive pool falsifies, and that was measured rather than
    reasoned about.
    ``psycopg_pool``'s default reset does nothing when the transaction status is IDLE, and under
    the autocommit ``session()`` deliberately chooses every returned connection IS idle, so
    nothing is reset: probed as a non-superuser against these same forced policies, a borrower
    that declared no workspace read the previous borrower's rows, and ``assert_workspace_context``
    PASSED for a workspace it had never named.

    So this asserts both halves in one run: the backends differ, and the unscoped one sees
    nothing. A pool without ``reset all`` on return turns the first assertion false and the
    second into a cross-tenant read.
    """
    from tests_support_api import scratch_database

    base = scratch_database(scoped.scratch).url
    database = Database(url=f"{base}&user={_APP_ROLE}")

    with database.session(scoped.workspace_a) as scoped_connection:
        scoped_pid = scoped_connection.execute("select pg_backend_pid() as pid").fetchone()["pid"]
        assert _count(scoped_connection, "capture") == 1

    with database.unscoped() as bare:
        assert bare.execute("select pg_backend_pid() as pid").fetchone()["pid"] != scoped_pid, (
            "unscoped() reused the scoped session's backend, so this deployment has grown a "
            "pool and the workspace setting travels with it"
        )
        assert bare.execute("select current_workspace() as w").fetchone()["w"] is None
        for table in ("capture", "evidence_span", "embedding", "assertion"):
            assert _count(bare, table) == 0, table


def test_unscoped_hides_nothing_from_a_role_row_level_security_does_not_reach(scoped):
    """The second bullet, and the reason the first one has to name a role.

    ``Database.unscoped`` opens a connection and declines to declare a workspace. That is all it
    does. Whether the fifty workspace-keyed forced tables then read empty is a property of
    the ROLE:
    PostgreSQL
    bypasses row security outright for a superuser or a role holding BYPASSRLS, and ``force row
    level security`` does not reach either, so the same method on the same schema hands the owner
    the row it hands ``exulanica_app`` nothing of. The docstring used to say "every table under
    row-level security is invisible through this connection" with no role attached, and that
    sentence was false for the owner.

    This remains worth measuring after the deployment fix because the bootstrap owner still exists
    for migrations and maintenance. ``compose.yaml`` no longer hands it to runtime services, and
    startup rejects it if configuration drifts; this test holds the database fact that makes both
    safeguards necessary.

    Skipped rather than asserted when the owner is an ordinary role, because then there is
    nothing to show: it is subject to FORCE row-level security like any other and the test above
    already covers that case.
    """
    from tests_support_api import scratch_database

    with scratch_database(scoped.scratch).unscoped() as bare:
        who = bare.execute(
            "select current_user as who, rolsuper, rolbypassrls from pg_roles "
            "where rolname = current_user"
        ).fetchone()
        if not (who["rolsuper"] or who["rolbypassrls"]):
            pytest.skip(f"the owner {who['who']} is subject to row-level security")
        assert bare.execute("select current_workspace() as w").fetchone()["w"] is None
        assert _count(bare, "capture") == 1, (
            f"{who['who']} has rolsuper={who['rolsuper']} rolbypassrls={who['rolbypassrls']} "
            "and should read straight through ws_isolation"
        )
