"""A comparison's start meets the durable spending authority before anything is defined.

Each ask of a comparison goes to its arm's model's provider alone: ``ModelClient.choose`` walks one
model, and ``ModelChain.walk`` falls back only on ``ModelUnavailableError``. So where a durable
authority admits the host's calls, a start an arm of which names a provider whose allowance is
spent could only fail its runs. It is refused at once, as admission refuses the arm's first ask:
429 ``budget_exceeded`` with the authority's ``spending`` member, and nothing is defined, reserved
or asked. The version's capability read says so before any start: the start is unavailable by the
authority's reason, and each model choice's ``decisions`` effect names it. With allowance left both
starts are available, and start. A capability read asks for the workspace's allowance once, and in
a process no durable authority admits, never. Shown for comparisons of a world's people and of a
town's signals. A comparison of people also asks, in every arm, the model an owner chose for
somebody outside its group, so its start is refused by that model's provider too; the manifest
offers one provider, so that is shown on a definition naming two.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid
from decimal import Decimal
from typing import Any

import pytest
from exulanica.api import services as services_module
from exulanica.api.society_comparison_start import asked_providers
from exulanica.models.spending import SpendingRefused
from exulanica.spending import (
    DURABLE,
    DurableSpending,
    FileSpendingWitness,
    SpendingOperator,
    holder_label,
)
from exulanica.spending.status import SpendingRefusals
from fastapi import FastAPI

import personal_world_support as personal
import test_signal_comparison_postgres as signals
import test_society_comparison_start_postgres as people
import test_society_stay_requests_api as stays
from spending_support import PROVIDER, reported_usage, spending_request
from test_signal_comparison_postgres import _presets_try_every_candidate, town
from test_society_comparison_start_postgres import saved_world, started
from tests_support_api import scratch_database

__all__ = ["_presets_try_every_candidate", "saved_world", "started", "town"]

START_PEOPLE = "POST /world/versions/{version_id}/society/comparisons"
START_SIGNALS = "POST /world/versions/{version_id}/traffic/comparisons"
CHOOSE = "POST /world/versions/{version_id}/models/{role_key}"
#: What admission answers an attempt of a workspace whose grant's one call is committed.
SPENT = {
    "reason": "spending_limit_reached",
    "scope": "workspace",
    "detail": "calls",
    "limit": "1",
    "committed": "1",
    "requested": "1",
    "retry": "never",
}
#: The calls a grant holds where a start must start: more than either comparison here can make at
#: most (two seeds of the town's signals can make 2080), which the start's durable bound of the
#: provider is opened with, so a grant must hold them.
ROOMY_CALLS = 10_000


@dataclasses.dataclass
class Allowance:
    """A durable authority the application spends through, and one workspace's grant under it."""

    durable: DurableSpending
    operator: SpendingOperator
    authority: uuid.UUID
    workspace: uuid.UUID

    def grant(self, calls: int) -> None:
        self.operator.grant(
            self.authority,
            self.workspace,
            ceiling_usd=Decimal("1"),
            max_calls=calls,
            valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=29),
            operator="test-operator",
            reason="a test grant",
        )

    def spend(self) -> None:
        """One attempt admitted, sent and settled, as a model call of the workspace's is."""
        gate = self.durable.for_workspace(self.workspace)
        ticket = gate.admit(spending_request())
        gate.dispatch(ticket)
        gate.settle(ticket, reported_usage(str(ticket.usd)))

    def reservations(self) -> int:
        with self.operator.database.unscoped() as connection:
            row = connection.execute(
                "select count(*) as n from spending_reservation where workspace_id = %s",
                (self.workspace,),
            ).fetchone()
        return int(row["n"])


def _durable(app: FastAPI, spine_schema, tmp_path, workspace: uuid.UUID) -> Allowance:
    """The application's services spending through a durable authority for the comparisons'
    provider, as a deployment composes them (``build_services``)."""
    services = app.state.services
    witness = FileSpendingWitness(tmp_path / "spending-witness", lock_timeout_s=5.0)
    durable = DurableSpending(services.database, witness, holder=holder_label("comparison-start"))
    app.state.services = dataclasses.replace(
        services,
        model_client=services.model_client.with_spending_source(durable),
        spending_mode=DURABLE,
        spending=durable,
    )
    _psycopg, scratch = spine_schema
    operator = SpendingOperator(scratch_database(scratch), witness)
    authority = operator.issue(
        provider=PROVIDER,
        ceiling_usd=Decimal("1"),
        max_calls=100_000,
        valid_until=dt.datetime.now(dt.UTC) + dt.timedelta(days=30),
        operator="test-operator",
        reason="a test authority",
    )
    return Allowance(durable, operator, authority, workspace)


def _reads(monkeypatch) -> list[uuid.UUID]:
    """Every workspace whose allowance the application reads from now on, in order."""
    read = services_module.read_spending_refusals
    seen: list[uuid.UUID] = []

    def counted(connection, workspace_id, **kwargs):
        seen.append(workspace_id)
        return read(connection, workspace_id, **kwargs)

    monkeypatch.setattr(services_module, "read_spending_refusals", counted)
    return seen


def _operation(document: dict[str, Any], operation: str) -> dict[str, Any]:
    (found,) = [row for row in document["operations"] if row["operation"] == operation]
    return found


def _decisions(document: dict[str, Any]) -> list[tuple[str, str | None]]:
    """The ``decisions`` effect of every model choice the read says can be made now."""
    found = [
        (effect["state"], effect["code"])
        for row in document["operations"]
        if row["operation"] == CHOOSE and row["state"] == "available"
        for effect in row["effects"]
        if effect["on"] == "decisions"
    ]
    assert found, "no model choice can be made here"
    return found


def _people_capabilities(held: dict[str, Any]) -> dict[str, Any]:
    world = held["world"]
    read = held["client"].get(
        f"/world/versions/{world['binding'].version_id}/capabilities",
        headers=people.OWNER,
        params=people._scope(world),
    )
    assert read.status_code == 200, read.text
    return read.json()


def _signal_capabilities(held: dict[str, Any]) -> dict[str, Any]:
    entry = held["entry"]
    read = held["api"].get(
        f"/world/versions/{entry['authored_version_id']}/capabilities?world_id={entry['world_id']}",
        token=personal.OWNER_TOKEN,
    )
    assert read.status_code == 200, read.text
    return read.json()


def _signal_counts(held: dict[str, Any]) -> dict[str, int]:
    return {
        table: signals._count(held, table)
        for table in ("signal_comparison", "signal_comparison_run", "signal_comparison_start")
    }


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_of_people_meets_a_spent_allowance_before_anything_is_defined(
    started, spine_schema, tmp_path, monkeypatch
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=1)
    allowance.spend()
    reads = _reads(monkeypatch)
    document = _people_capabilities(started)
    assert reads == [world["workspace"]], "a capability read asks for the allowance once"
    start = _operation(document, START_PEOPLE)
    assert (start["state"], start["code"]) == ("unavailable", SPENT["reason"])
    assert set(_decisions(document)) == {("unavailable", SPENT["reason"])}

    refused = people._start(started, people._body())
    assert refused.status_code == 429, refused.text
    assert refused.json()["code"] == "budget_exceeded"
    assert refused.json()["spending"] == SPENT
    assert people._counts(world) == {
        "society_comparison": 0,
        "society_comparison_run": 0,
        "society_comparison_start": 0,
    }
    assert allowance.reservations() == 1, "the start reserved nothing of the allowance"
    assert started["transport"].requests == []


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_start_of_people_with_allowance_left_is_available_and_starts(
    started, spine_schema, tmp_path
):
    world = started["world"]
    stays._inhabited(world, started["client"])
    allowance = _durable(started["client"].app, spine_schema, tmp_path, world["workspace"])
    allowance.grant(calls=ROOMY_CALLS)
    document = _people_capabilities(started)
    start = _operation(document, START_PEOPLE)
    assert (start["state"], start["code"]) == ("available", None)
    assert set(_decisions(document)) == {("available", None)}
    begun = people._start(started, people._body())
    assert begun.status_code == 201, begun.text
    assert people._counts(world)["society_comparison_start"] == 1


@pytest.mark.postgres
@pytest.mark.parametrize("saved_world", [2], indirect=True)
def test_a_process_no_durable_authority_admits_reads_no_allowance(started, monkeypatch):
    reads = _reads(monkeypatch)
    document = _people_capabilities(started)
    assert _operation(document, START_PEOPLE)["code"] != SPENT["reason"]
    world = started["world"]
    models = started["client"].get(
        f"/world/versions/{world['binding'].version_id}/models",
        headers=people.OWNER,
        params=people._scope(world),
    )
    assert models.status_code == 200, models.text
    assert reads == []


@pytest.mark.postgres
def test_a_start_of_signals_meets_a_spent_allowance_before_anything_is_defined(
    town, spine_schema, tmp_path, monkeypatch
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=1)
    allowance.spend()
    reads = _reads(monkeypatch)
    document = _signal_capabilities(town)
    assert reads == [workspace], "a capability read asks for the allowance once"
    start = _operation(document, START_SIGNALS)
    assert (start["state"], start["code"]) == ("unavailable", SPENT["reason"])
    assert set(_decisions(document)) == {("unavailable", SPENT["reason"])}
    entry = town["entry"]
    models = town["api"].get(
        f"/world/versions/{entry['authored_version_id']}/models?world_id={entry['world_id']}"
    )
    assert models.status_code == 200, models.text
    assert reads == [workspace, workspace], "the models read asks for it once"

    refused = signals._start(town, signals._body())
    assert refused.status_code == 429, refused.text
    assert refused.json()["code"] == "budget_exceeded"
    assert refused.json()["spending"] == SPENT
    assert _signal_counts(town) == {
        "signal_comparison": 0,
        "signal_comparison_run": 0,
        "signal_comparison_start": 0,
    }
    assert allowance.reservations() == 1, "the start reserved nothing of the allowance"
    assert town["transport"].requests == []


@pytest.mark.postgres
def test_a_start_of_signals_with_allowance_left_is_available_and_starts(
    town, spine_schema, tmp_path
):
    workspace = town["repository"].workspace_id
    allowance = _durable(town["api"].client.app, spine_schema, tmp_path, workspace)
    allowance.grant(calls=ROOMY_CALLS)
    document = _signal_capabilities(town)
    start = _operation(document, START_SIGNALS)
    assert (start["state"], start["code"]) == ("available", None)
    assert set(_decisions(document)) == {("available", None)}
    begun = signals._start(town, signals._body())
    assert begun.status_code == 201, begun.text
    assert _signal_counts(town)["signal_comparison_start"] == 1


def test_a_start_is_refused_by_any_provider_it_asks_and_a_role_by_every_one():
    spent = SpendingRefused("spending_limit_reached", scope="workspace")
    refusals = SpendingRefusals({"spent": spent, "left": None})
    # An owner chose a model of the spent provider for somebody outside the group; the arm's
    # provider has allowance left. Every arm would ask both, so the start is refused.
    body = {
        "arms": {
            "routine": {"provider_config": None},
            "model_a": {"provider_config": {"provider": "left", "model_id": "a"}},
        },
        "others": [
            {"provider_config": {"provider": "spent", "model_id": "b"}},
            {"provider_config": None},
        ],
    }
    assert asked_providers(body) == ("left", "spent")
    assert refusals.first(asked_providers(body)) is spent
    assert refusals.first(["left"]) is None
    # A descriptor says no start can run only once every provider a role can ask is spent.
    assert refusals.every(["spent", "left"]) is None
    assert refusals.every(["spent"]) is spent
    assert refusals.every([]) is None
