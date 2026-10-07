"""A guest's allowance is a step of the authority's ledger, with the operator's figures alone.

Migration 0139: ``spending_set_guest_policy`` (an administrator's) states what every guest
workspace is granted under an authority; ``spending_grant_guest`` (the runtime role's, through
``DurableSpending.grant_guest``) grants a workspace exactly that, once, and returns the witness
advance the runtime writes under the authority's witness lock. Each test names a way it could go
wrong: a caller choosing the figures, a second grant on top of the first, a guest allowance added
to a workspace that already holds one, the witness left behind the ledger (which would suspend the
authority for every workspace), or a role other than the runtime's calling it.
"""

from __future__ import annotations

import datetime as dt
import threading
import time
import uuid
from decimal import Decimal

import pytest
from exulanica.db.account_roles import provision_account_role
from exulanica.db.roles import provision_runtime_role
from exulanica.models.spending import SpendingRefused
from psycopg.types.json import Jsonb

from spending_support import PROVIDER, RUNTIME_ROLE
from spending_support import bench as bench

pytestmark = pytest.mark.postgres

#: The policy every test sets, written out here rather than read from the code under test.
POLICY_USD = Decimal("0.05000000")
POLICY_CALLS = 200
POLICY_DAYS = 7


def _policy(
    bench, authority: uuid.UUID, *, usd: Decimal = POLICY_USD, per_day: int = 1_000
) -> uuid.UUID:
    return bench.operator.set_guest_policy(
        authority,
        ceiling_usd=usd,
        max_calls=POLICY_CALLS,
        valid_for_days=POLICY_DAYS,
        grants_per_day=per_day,
        operator="test-operator",
        reason="a test guest policy",
    )


def _grants(bench, workspace: uuid.UUID) -> list[dict]:
    return bench.query(
        "select * from spending_grant where workspace_id = %s and parent_grant_id is null",
        workspace,
    )


def test_no_policy_grants_nothing(bench):
    bench.issue(ceiling="1.00")
    workspace = uuid.uuid4()
    assert bench.durable().grant_guest(workspace, provider=PROVIDER) is None
    assert _grants(bench, workspace) == []


def test_a_guest_is_granted_the_policy_s_figures_once_on_the_ledger(bench):
    authority = bench.issue(ceiling="1.00", calls=10_000)
    policy = _policy(bench, authority)
    workspace = uuid.uuid4()
    before = len(bench.events(authority))
    started = dt.datetime.now(dt.UTC)
    grant = bench.durable().grant_guest(workspace, provider=PROVIDER)
    (row,) = _grants(bench, workspace)
    assert row["grant_id"] == grant
    assert (row["ceiling_usd"], row["max_calls"]) == (POLICY_USD, POLICY_CALLS)
    validity = row["valid_until"] - started
    assert dt.timedelta(days=POLICY_DAYS) - dt.timedelta(minutes=5) < validity
    assert validity <= dt.timedelta(days=POLICY_DAYS) + dt.timedelta(minutes=5)
    events = bench.events(authority)
    assert len(events) == before + 1
    assert events[-1]["kind"] == "granted"
    assert events[-1]["body"]["basis"] == "guest_policy"
    assert events[-1]["body"]["policy_id"] == str(policy)
    # Asked again: the same grant, and nothing on the ledger.
    assert bench.durable().grant_guest(workspace, provider=PROVIDER) == grant
    assert len(bench.events(authority)) == before + 1
    assert len(_grants(bench, workspace)) == 1


def test_a_workspace_holding_another_grant_is_refused_and_keeps_only_that(bench):
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority)
    workspace = uuid.uuid4()
    operator_grant = bench.grant(authority, workspace, ceiling="0.50")
    with pytest.raises(SpendingRefused) as refused:
        bench.durable().grant_guest(workspace, provider=PROVIDER)
    assert refused.value.reason == "spending_not_granted"
    assert refused.value.detail == "workspace_holds_a_grant"
    assert [row["grant_id"] for row in _grants(bench, workspace)] == [operator_grant]


def test_the_witness_moves_with_the_ledger_and_a_skipped_witness_suspends(bench):
    """Through DurableSpending the witness is written with the step, so a later step agrees. The
    control calls the function itself and drops its witness advance: the next step finds the
    ledger ahead of the witness and suspends the authority, for everybody."""
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority)
    durable = bench.durable()
    durable.grant_guest(uuid.uuid4(), provider=PROVIDER)
    durable.grant_guest(uuid.uuid4(), provider=PROVIDER)
    assert bench.state(authority)["suspended_reason"] is None

    skipped = uuid.uuid4()
    with bench.witness.hold(authority) as held:
        document = held.document
    with bench.runtime.session(skipped) as connection, connection.transaction():
        answer = connection.execute(
            "select spending_grant_guest(%s, %s, %s, %s, %s) as document",
            (skipped, PROVIDER, authority, "test:1:abcd", Jsonb(document)),
        ).fetchone()["document"]
    assert answer["outcome"] == "granted" and answer["witness"]
    with pytest.raises(SpendingRefused) as refused:
        durable.grant_guest(uuid.uuid4(), provider=PROVIDER)
    assert refused.value.reason == "spending_suspended"
    assert bench.state(authority)["suspended_reason"] == "witness_behind"


def test_only_the_runtime_role_may_call_the_grant(bench, repository):
    connection = repository.connection
    reader = "guest_ro_" + uuid.uuid4().hex[:12]
    accounts = "guest_accounts_" + uuid.uuid4().hex[:12]
    signature = "spending_grant_guest(uuid,text,uuid,text,jsonb)"
    try:
        provision_runtime_role(connection, role=reader, read_only=True)
        provision_account_role(connection, role=accounts)
        held = {
            role: connection.execute(
                "select has_function_privilege(%s, %s, 'EXECUTE') ok", (role, signature)
            ).fetchone()["ok"]
            for role in (RUNTIME_ROLE, reader, accounts)
        }
        public = connection.execute(
            "select exists (select 1 from pg_proc p, "
            "lateral aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a "
            "where p.oid = %s::regprocedure and a.grantee = 0) public",
            (signature,),
        ).fetchone()["public"]
        policy_readers = connection.execute(
            "select bool_or(has_table_privilege(r, 'spending_guest_policy', "
            "'SELECT,INSERT,UPDATE,DELETE')) any from unnest(%s::text[]) r",
            ([RUNTIME_ROLE, reader, accounts],),
        ).fetchone()["any"]
    finally:
        connection.rollback()
    assert held == {RUNTIME_ROLE: True, reader: False, accounts: False}
    assert public is False
    assert policy_readers is False


def test_a_policy_grants_its_day_s_number_of_guests_and_no_more(bench):
    """The database bounds a day's guest grants, whatever process asks for them: a third guest
    under a policy that grants two a day is refused, and a grant already made is answered."""
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority, per_day=2)
    durable = bench.durable()
    first, second = uuid.uuid4(), uuid.uuid4()
    granted = durable.grant_guest(first, provider=PROVIDER)
    durable.grant_guest(second, provider=PROVIDER)
    with pytest.raises(SpendingRefused) as refused:
        durable.grant_guest(uuid.uuid4(), provider=PROVIDER)
    assert (refused.value.reason, refused.value.detail) == (
        "spending_not_granted",
        "guest_grants_exhausted",
    )
    # A guest already granted is answered again, at no cost to the day's count.
    assert durable.grant_guest(first, provider=PROVIDER) == granted


def test_a_withdrawn_policy_grants_nothing_until_another_is_set(bench):
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority)
    assert bench.operator.withdraw_guest_policy(
        authority, operator="test-operator", reason="abuse"
    ) == ("withdrawn")
    workspace = uuid.uuid4()
    assert bench.durable().grant_guest(workspace, provider=PROVIDER) is None
    assert _grants(bench, workspace) == []
    (ended,) = bench.query(
        "select ended_as from spending_guest_policy where authority_id = %s", authority
    )
    assert ended["ended_as"] == "withdrawn"
    _policy(bench, authority)
    assert bench.durable().grant_guest(workspace, provider=PROVIDER) is not None


def test_a_policy_set_before_a_reauthorization_is_set_again_before_it_grants(bench):
    """A restore can bring back a policy the operator had replaced or withdrawn; its
    reconciliation, and any reauthorization, leave every earlier policy granting nothing until the
    operator states it again, which status shows."""
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority)
    bench.operator.reauthorize(
        authority,
        ceiling_usd=Decimal("1.00"),
        max_calls=10_000,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        operator="test-operator",
        reason="a restore was reconciled",
    )
    (shown,) = [p for p in bench.operator.guest_policies() if p["authority_id"] == str(authority)]
    assert shown["needs_restating"] is True
    with pytest.raises(SpendingRefused) as refused:
        bench.durable().grant_guest(uuid.uuid4(), provider=PROVIDER)
    assert refused.value.detail == "guest_policy_needs_restating"
    _policy(bench, authority)
    (shown,) = [p for p in bench.operator.guest_policies() if p["authority_id"] == str(authority)]
    assert shown["needs_restating"] is False
    assert bench.durable().grant_guest(uuid.uuid4(), provider=PROVIDER) is not None


def test_a_grant_racing_a_replacement_takes_the_policy_that_stands_after_it(bench):
    """The grant locks the authority's state before it reads the policy. Here the operator's
    replacement holds that lock while a grant waits on it; the grant then takes the replacement's
    figures, not the replaced one's."""
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority, usd=Decimal("0.05"))
    workspace, granted, failed = uuid.uuid4(), [], []

    def grant() -> None:
        try:
            granted.append(bench.durable().grant_guest(workspace, provider=PROVIDER))
        except Exception as exc:  # reported below
            failed.append(exc)

    with bench.admin.unscoped() as connection:
        connection.execute(
            "select 1 from spending_authority_state where authority_id = %s for update",
            (authority,),
        )
        waiting = threading.Thread(target=grant)
        waiting.start()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            # A row lock's waiter waits on the holder's transaction id; this server runs this test
            # alone, so any lock not granted is the grant's.
            blocked = connection.execute(
                "select count(*) as n from pg_locks where not granted"
            ).fetchone()["n"]
            if blocked:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the grant never waited on the authority's state")
        connection.execute(
            "select spending_set_guest_policy(%s, %s, %s, make_interval(days => %s), %s, %s, %s)",
            (
                authority,
                Decimal("0.02"),
                POLICY_CALLS,
                POLICY_DAYS,
                1_000,
                "test-operator",
                "the replacement",
            ),
        )
    waiting.join(timeout=30)
    assert not failed, failed
    (row,) = _grants(bench, workspace)
    assert row["ceiling_usd"] == Decimal("0.02000000")


def test_a_grant_under_another_authority_does_not_refuse_this_one(bench):
    """A workspace is refused a guest allowance only where it already holds a grant under the same
    authority; one under another authority (another provider's, or a retired one) is not added
    to, and does not stand in the way."""
    other = bench.issue(ceiling="1.00", calls=10_000)
    workspace = uuid.uuid4()
    elsewhere = bench.grant(other, workspace, ceiling="0.50")
    bench.operator.revoke(other, operator="test-operator", reason="retired")
    authority = bench.issue(ceiling="1.00", calls=10_000)
    _policy(bench, authority)
    granted = bench.durable().grant_guest(workspace, provider=PROVIDER)
    assert granted is not None
    assert {row["grant_id"] for row in _grants(bench, workspace)} == {elsewhere, granted}


@pytest.mark.parametrize(
    "function",
    [
        "spending_grant_guest",
        "spending_guest_policy_authority",
        "spending_set_guest_policy",
        "spending_withdraw_guest_policy",
    ],
)
def test_every_name_a_guest_spending_body_uses_is_qualified(function, spine_schema):
    """Every relation and function the body names carries its schema (or pg_catalog), so no
    object on a search path, the pinned one included, can stand in for one of them."""
    import re

    from psycopg.rows import dict_row

    from pg_harness import open_scratch_connection

    psycopg_module, scratch = spine_schema
    admin = open_scratch_connection(psycopg_module, scratch)
    admin.row_factory = dict_row
    try:
        row = admin.execute(
            "select p.prosrc from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            "where n.nspname = %s and p.proname = %s",
            (scratch, function),
        ).fetchone()
    finally:
        admin.close()
    body = re.sub(r"--[^\n]*", "", row["prosrc"])
    body = re.sub(r"'[^']*'", "''", body)  # string literals name nothing
    relations = re.findall(
        r"\b(?<!distinct )(?:from|insert\s+into|update|join)\s+([A-Za-z_\"][\w.\"]*)",
        body,
        re.I,
    )
    assert relations, "the body names no relation"
    for name in relations:
        assert name.startswith((f'"{scratch}".', f"{scratch}.")), name
    calls = re.findall(r"([A-Za-z_][\w.\"]*)\s*\(", body)
    words = {"if", "values", "and", "or", "not", "in", "insert", "returns", "exists", "least"}
    unqualified = [name for name in calls if "." not in name and name.lower() not in words]
    assert unqualified == [], unqualified
