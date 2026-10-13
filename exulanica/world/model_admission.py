"""Model admission and prepared probes, separate from paid job execution."""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import asdict
from decimal import Decimal
from typing import Any

import psycopg

from exulanica.models import provider_catalog
from exulanica.models.client import ModelClient
from exulanica.models.manifest import load_manifest
from exulanica.spending.ledger import DurableSpending
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_probe_contract import prepare_definition, validate_definition
from exulanica.world.model_probes import ModelProbeRefused, ModelProbeRepository
from exulanica.world.workspace_lock import lock_workspace
from exulanica.world.workspace_models import ADDED, REMOVED, WorkspaceModelRepository


def eligible(provider: str, model_id: str) -> provider_catalog.ProviderModel:
    if provider not in load_manifest().providers:
        raise ModelProbeRefused("provider_not_admitted")
    stated = provider_catalog.provider_model(provider, model_id)
    if stated is None:
        raise ModelProbeRefused("model_not_listed")
    if provider_catalog.licence_class(provider, model_id) != provider_catalog.ACCEPTED:
        raise ModelProbeRefused("licence_not_admitted")
    if not any(
        provider_catalog.decision_capable(stated, role.chosen.required_use_cases)
        for role in decision_roles()
    ):
        raise ModelProbeRefused("model_not_for_decisions")
    return stated


def add_model(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    provider: str,
    model_id: str,
    request_id: uuid.UUID,
) -> dict[str, Any]:
    stated = eligible(provider, model_id)
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        if connection.execute(
            "select 1 from tombstone where workspace_id=%s and scope='workspace'", (workspace_id,)
        ).fetchone():
            raise ModelProbeRefused("workspace_erased")
        return (
            WorkspaceModelRepository(connection, workspace_id)
            .record(
                provider,
                model_id,
                request_id=request_id,
                kind=ADDED,
                recorded_by=actor,
                facts={
                    "stated": asdict(stated),
                    "catalog_sha256": provider_catalog.catalog_sha256(),
                },
            )
            .view()
        )


def remove_model(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    provider: str,
    model_id: str,
    request_id: uuid.UUID,
) -> dict[str, Any]:
    with connection.transaction():
        lock_workspace(connection, workspace_id)
        return (
            WorkspaceModelRepository(connection, workspace_id)
            .record(
                provider,
                model_id,
                request_id=request_id,
                kind=REMOVED,
                recorded_by=actor,
                facts={"reason": "by_a_person"},
            )
            .view()
        )


def prepare_probe(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    provider: str,
    model_id: str,
    request_id: uuid.UUID,
    client: ModelClient | None,
) -> dict[str, Any]:
    repository = ModelProbeRepository(connection, workspace_id)
    prior = repository.by_request(request_id)
    if prior is not None:
        if (
            prior["provider"] != provider
            or prior["model_id"] != model_id
            or prior["recorded_by"] != actor
        ):
            raise ModelProbeRefused("model_probe_key_reused")
        return repository.view(prior["probe_id"])
    stated = eligible(provider, model_id)
    if client is None:
        raise ModelProbeRefused("model_probe_provider_unavailable")
    state = WorkspaceModelRepository(connection, workspace_id).state(provider, model_id)
    if state is None or state.removed:
        raise ModelProbeRefused("model_not_added")
    price = client.provider_prices(provider).get(model_id)
    if price is None:
        raise ModelProbeRefused("model_price_unavailable")
    definition = prepare_definition(
        stated,
        price,
        added_seq=state.added_seq,
        added_sha256=state.added_sha256,
        catalog_sha256=provider_catalog.catalog_sha256(),
        price_read_at=dt.datetime.now(dt.UTC).isoformat(),
    )
    probe_id = repository.prepare(definition, request_id=request_id, actor=actor)
    return repository.view(probe_id)


def start_probe(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    probe_id: uuid.UUID,
    request_id: uuid.UUID,
    definition_sha256: str,
    ceiling_usd: Decimal,
    spending: DurableSpending | None,
    served: bool,
) -> dict[str, Any]:
    repository = ModelProbeRepository(connection, workspace_id)
    row = repository.get(probe_id)
    prior = repository.start_record(probe_id)
    if prior is not None:
        if (
            prior["request_id"] != request_id
            or prior["recorded_by"] != actor
            or prior["definition_sha256"] != definition_sha256
            or prior["ceiling_usd"] != ceiling_usd
        ):
            raise ModelProbeRefused("model_probe_key_reused")
        return repository.view(probe_id)
    if not served:
        raise ModelProbeRefused("model_probe_not_served_here")
    if spending is None:
        raise ModelProbeRefused("spending_scope_missing")
    definition = row["definition"]
    validate_definition(definition)
    eligible(definition["provider"], definition["model_id"])
    if definition_sha256 != row["definition_sha256"]:
        raise ModelProbeRefused("model_probe_definition_changed")
    if not repository.current(definition):
        raise ModelProbeRefused("model_probe_stale")
    if (
        not ceiling_usd.is_finite()
        or not 0 < ceiling_usd <= 1000
        or ceiling_usd < Decimal(definition["operation_estimate"]["ceiling_usd"])
    ):
        raise ModelProbeRefused("model_probe_bound_too_small")
    read_at = dt.datetime.fromisoformat(definition["price"]["read_at"])
    valid_until = read_at + dt.timedelta(hours=1)
    now = dt.datetime.now(dt.UTC)
    if not now <= valid_until or read_at > now + dt.timedelta(minutes=1):
        raise ModelProbeRefused("model_probe_price_expired")
    bound_id = spending.open_bound(
        workspace_id,
        provider=definition["provider"],
        key=f"model-probe:{probe_id}",
        ceiling_usd=ceiling_usd,
        max_calls=definition["operation_estimate"]["max_calls"],
        valid_until=valid_until,
        reason="The workspace starts its fixed synthetic decision-role probe.",
    )
    repository.start(
        probe_id,
        request_id=request_id,
        actor=actor,
        definition_sha256=definition_sha256,
        bound_id=bound_id,
        ceiling_usd=ceiling_usd,
    )
    return repository.view(probe_id)
