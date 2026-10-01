"""The durable spending authority over the harness's throwaway schema, as the tests drive it.

The runtime connects as a provisioned role that owns nothing and cannot bypass row-level
security, as a deployment's API and worker do; the operator connects as the harness's own user,
an administrative complete view. Each bench has its own witness directory.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from exulanica.db.roles import provision_runtime_role
from exulanica.db.session import Database
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.spending import SpendingRequest, next_request_key
from exulanica.models.transport import HttpResponse
from exulanica.models.usage import CallUsage, CostBasis
from exulanica.spending.ledger import DurableSpending, holder_label
from exulanica.spending.operator import SpendingOperator
from exulanica.spending.witness import FileSpendingWitness

from conftest import scratch_role_database
from model_fakes import FakeTransport, chat_body
from tests_support_api import scratch_database

__all__ = [
    "MESSAGES",
    "PROVIDER",
    "ROLE",
    "RUNTIME_ROLE",
    "SpendingBench",
    "WorkspacePolicy",
    "bench",
    "no_usage_body",
    "one_reservation",
    "reported_usage",
    "spending_client",
    "spending_request",
]

RUNTIME_ROLE = "exulanica_spending_suite"
PROVIDER = next(iter(load_manifest().providers))
ROLE = Role.REASONING_CHEAP
MESSAGES = [{"role": "user", "content": "how much is left?"}]


class WorkspacePolicy:
    """What the client reads of a workspace's policy: its workspace, and texts left as they are."""

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id

    def admit(self, request):
        return request.texts


def one_reservation() -> Decimal:
    """What one ``ROLE`` call of ``MESSAGES`` reserves at the manifest's default answer bound."""
    manifest = load_manifest()
    return BudgetGuard(ceiling_usd=Decimal(1), max_calls=1).estimate_usd(
        manifest[ROLE].primary,
        prompt_chars=sum(len(str(message)) for message in MESSAGES),
        max_tokens=manifest[ROLE].default_max_tokens,
    )


def spending_request(key: str | None = None, usd: Decimal | None = None) -> SpendingRequest:
    """One ``ROLE`` attempt, as a client asks for its admission."""
    return SpendingRequest(
        provider=PROVIDER,
        model_id="test/model",
        role=str(ROLE),
        usd=one_reservation() if usd is None else usd,
        key=next_request_key() if key is None else key,
    )


def reported_usage(usd: str, basis: CostBasis = CostBasis.REPORTED) -> CallUsage:
    """What an attempt cost, as its settlement reports it."""
    return CallUsage(
        role=str(ROLE),
        model_id="test/model",
        provider=PROVIDER,
        prompt_tokens=10,
        completion_tokens=20,
        reasoning_tokens=0,
        cached_prompt_tokens=0,
        usd=Decimal(usd),
        cost_basis=basis,
    )


def no_usage_body() -> HttpResponse:
    """A whole answer with no usage: its cost is unknown, so its whole reservation stays held."""
    body = chat_body()
    del body["usage"]
    return HttpResponse(status_code=200, text=json.dumps(body))


def spending_client(
    durable: DurableSpending, transport: FakeTransport | None = None, *, max_attempts: int = 1
) -> ModelClient:
    return ModelClient(
        api_key="test-key-not-real",
        manifest=load_manifest(),
        transport=transport if transport is not None else FakeTransport(),
        budget=BudgetGuard(ceiling_usd=Decimal(100), max_calls=100_000),
        max_attempts=max_attempts,
        sleep=lambda _seconds: None,
        spending=durable,
    )


@dataclass
class SpendingBench:
    scratch: str
    admin: Database
    runtime: Database
    witness_dir: Path
    witness: FileSpendingWitness
    operator: SpendingOperator

    def durable(self, label: str = "test", *, witnessed: bool = True) -> DurableSpending:
        return DurableSpending(
            self.runtime, self.witness if witnessed else None, holder=holder_label(label)
        )

    def issue(
        self,
        *,
        ceiling: str | Decimal = "0.01",
        calls: int = 1000,
        until: dt.datetime | None = None,
        witnessed: bool = True,
        dispatch_seconds: int = 60,
    ) -> uuid.UUID:
        return self.operator.issue(
            provider=PROVIDER,
            ceiling_usd=Decimal(ceiling),
            max_calls=calls,
            valid_until=until or dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
            dispatch_seconds=dispatch_seconds,
            witnessed=witnessed,
            operator="test-operator",
            reason="a test authority",
        )

    def grant(
        self,
        authority: uuid.UUID,
        workspace: uuid.UUID,
        *,
        ceiling: str | Decimal = "0.01",
        calls: int = 1000,
        until: dt.datetime | None = None,
    ) -> uuid.UUID:
        return self.operator.grant(
            authority,
            workspace,
            ceiling_usd=Decimal(ceiling),
            max_calls=calls,
            valid_until=until or dt.datetime.now(dt.UTC) + dt.timedelta(days=29),
            operator="test-operator",
            reason="a test grant",
        )

    def query(self, statement: str, *parameters: Any) -> list[dict[str, Any]]:
        with self.admin.unscoped() as connection:
            return connection.execute(statement, parameters).fetchall()

    def state(self, authority: uuid.UUID) -> dict[str, Any]:
        (row,) = self.query(
            "select * from spending_authority_state where authority_id = %s", authority
        )
        return row

    def grant_state(self, workspace: uuid.UUID, grant: uuid.UUID) -> dict[str, Any]:
        (row,) = self.query(
            "select * from spending_grant_state where workspace_id = %s and grant_id = %s",
            workspace,
            grant,
        )
        return row

    def reservations(self, workspace: uuid.UUID) -> list[dict[str, Any]]:
        return self.query(
            "select * from spending_reservation where workspace_id = %s order by admitted_at",
            workspace,
        )

    def events(self, authority: uuid.UUID) -> list[dict[str, Any]]:
        return self.query(
            "select * from spending_event where authority_id = %s order by sequence", authority
        )

    def committed_over_time(self, authority: uuid.UUID) -> list[Decimal]:
        """The authority's committed liability after each event, replayed from the ledger alone."""
        committed = Decimal(0)
        path = []
        for event in self.events(authority):
            body = event["body"]
            if event["kind"] == "admitted":
                committed += Decimal(body["usd"])
                committed -= sum(
                    (self._reserved(uuid.UUID(expired)) for expired in body.get("expired", ())),
                    Decimal(0),
                )
            elif event["kind"] in ("settled", "released", "reconciled"):
                if event["kind"] == "reconciled":
                    committed += Decimal(body["usd"]) - Decimal(body["previous_liability"])
                else:
                    committed += Decimal(body["delta"])
            elif event["kind"] == "expired":
                committed -= sum(
                    (self._reserved(uuid.UUID(expired)) for expired in body["expired"]),
                    Decimal(0),
                )
            elif event["kind"] == "restore_reconciled":
                committed += Decimal(body["carried_usd"])
            path.append(committed)
        return path

    def _reserved(self, reservation: uuid.UUID) -> Decimal:
        (row,) = self.query(
            "select reserved_usd from spending_reservation where reservation_id = %s", reservation
        )
        return Decimal(row["reserved_usd"])


@pytest.fixture
def bench(repository, spine_schema, tmp_path) -> SpendingBench:
    _psycopg, scratch = spine_schema
    provision_runtime_role(repository.connection, role=RUNTIME_ROLE)
    runtime = scratch_role_database(scratch, RUNTIME_ROLE)
    with runtime.session(uuid.uuid4()) as connection:
        role = connection.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user"
        ).fetchone()
        assert role == {"rolsuper": False, "rolbypassrls": False}, role
    admin = scratch_database(scratch)
    witness_dir = tmp_path / "spending-witness"
    witness = FileSpendingWitness(witness_dir, lock_timeout_s=5.0)
    return SpendingBench(
        scratch=scratch,
        admin=admin,
        runtime=runtime,
        witness_dir=witness_dir,
        witness=witness,
        operator=SpendingOperator(admin, witness),
    )
