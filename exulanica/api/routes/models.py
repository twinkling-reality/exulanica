"""Authenticated model discovery, workspace admission and explicitly bounded probe jobs.

The discovery GET reads shipped catalog facts and the caller's workspace records. Preflight
reads one identifier by the same rules. Neither read admits a model or starts a probe. Separate
writes add/remove models, prepare quotes and authorize async jobs; the worker alone asks models.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.models.errors import ModelError, ProviderRefused
from exulanica.models.manifest import load_manifest
from exulanica.models.provider_catalog import (
    MODEL_PATTERN,
    PROVIDER_PATTERN,
    ProviderPricesUnreadable,
)
from exulanica.models.spending import SpendingRefused
from exulanica.world.decision_roles import decision_roles
from exulanica.world.model_admission import add_model, prepare_probe, remove_model, start_probe
from exulanica.world.model_discovery import PREFLIGHT_PROFILE, discovery, model_preflight
from exulanica.world.model_probe_contract import case_book, replay_outcome, replay_terminal
from exulanica.world.model_probes import ModelProbeRefused, ModelProbeRepository
from exulanica.world.workspace_model_bindings import proven_bindings
from exulanica.world.workspace_models import WorkspaceModelRefused, WorkspaceModelRepository

router = APIRouter(prefix="/models", tags=["models"])
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


class ModelPreflightBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63, pattern=f"^{PROVIDER_PATTERN}$")]
    model_id: Annotated[str, Field(min_length=1, max_length=200, pattern=f"^{MODEL_PATTERN}$")]


class ModelRecordBody(ModelPreflightBody):
    request_id: uuid.UUID


class ProbeStartBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID
    definition_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    ceiling_usd: Annotated[str, Field(pattern=r"^[0-9]{1,4}(\.[0-9]{1,18})?$")]


def _answer(operation: Callable[[], Any], *, status: int = 200) -> JSONResponse:
    try:
        return JSONResponse(content=operation(), status_code=status, headers=_PRIVATE)
    except (ModelProbeRefused, WorkspaceModelRefused) as failure:
        code = failure.code
        return JSONResponse(
            content={"code": code},
            status_code=404 if code == "model_probe_not_found" else 409,
            headers=_PRIVATE,
        )
    except ProviderRefused as failure:
        return JSONResponse(content={"code": failure.reason}, status_code=409, headers=_PRIVATE)
    except SpendingRefused as failure:
        return JSONResponse(content={"code": failure.reason}, status_code=409, headers=_PRIVATE)
    except ProviderPricesUnreadable:
        return JSONResponse(
            content={"code": "model_prices_unreadable"}, status_code=409, headers=_PRIVATE
        )
    except ModelError:
        return JSONResponse(
            content={"code": "model_probe_provider_unavailable"}, status_code=409, headers=_PRIVATE
        )
    except ValueError:
        return JSONResponse(
            content={"code": "model_probe_contract_unavailable"}, status_code=409, headers=_PRIVATE
        )


@router.post("")
def admit_model(
    body: ModelRecordBody, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    return _answer(
        lambda: add_model(
            connection,
            session.workspace_id,
            session.actor,
            body.provider,
            body.model_id,
            body.request_id,
        )
    )


@router.post("/remove")
def remove_admitted_model(
    body: ModelRecordBody, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    return _answer(
        lambda: remove_model(
            connection,
            session.workspace_id,
            session.actor,
            body.provider,
            body.model_id,
            body.request_id,
        )
    )


@router.post("/probes/prepare")
def prepare_model_probe(
    body: ModelRecordBody, connection: ScopedConnection, session: CurrentSession, request: Request
) -> JSONResponse:
    services = get_services(request)
    return _answer(
        lambda: prepare_probe(
            connection,
            session.workspace_id,
            session.actor,
            body.provider,
            body.model_id,
            body.request_id,
            services.model_client,
        )
    )


@router.post("/probes/{probe_id}/start")
def start_model_probe(
    probe_id: uuid.UUID,
    body: ProbeStartBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
) -> JSONResponse:
    services = get_services(request)
    served = (
        services.runs_model_probe_worker
        and session.workspace_id in services.model_probe_workspaces
        and services.model_client is not None
    )
    return _answer(
        lambda: start_probe(
            connection,
            session.workspace_id,
            session.actor,
            probe_id,
            body.request_id,
            body.definition_sha256,
            Decimal(body.ceiling_usd),
            services.spending,
            served,
        ),
        status=202,
    )


@router.get("/probes/{probe_id}")
def read_model_probe(
    probe_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    return _answer(lambda: ModelProbeRepository(connection, session.workspace_id).view(probe_id))


@router.post("/probes/{probe_id}/replay")
def replay_model_probe(
    probe_id: uuid.UUID, connection: ReadOnlyConnection, session: CurrentSession
) -> JSONResponse:
    def replay() -> dict[str, Any]:
        found = ModelProbeRepository(connection, session.workspace_id).view(probe_id)
        return {
            "probe_id": str(probe_id),
            "replayed": (
                replay_outcome(found["definition"], found["receipts"])
                if found["outcome"] is None
                else replay_terminal(found["definition"], found["receipts"], found["outcome"])
            ),
            "execution_admitted": False,
        }

    return _answer(replay)


@router.post("/probes/{probe_id}/cancel")
def cancel_model_probe(
    probe_id: uuid.UUID, connection: ScopedConnection, session: CurrentSession, request: Request
) -> JSONResponse:
    def cancel() -> dict[str, Any]:
        repository = ModelProbeRepository(connection, session.workspace_id)
        repository.cancel(probe_id)
        start = repository.start_record(probe_id)
        spending = get_services(request).spending
        if start is not None and spending is not None:
            spending.close_bound(
                session.workspace_id, start["bound_id"], reason="The model probe was cancelled."
            )
            repository.bound_closed(probe_id)
        return repository.view(probe_id)

    return _answer(cancel)


@router.get("")
def discover_models(
    connection: ReadOnlyConnection, session: CurrentSession, request: Request
) -> Any:
    services = get_services(request)
    return JSONResponse(
        content=discovery(
            probe_served=services.model_probes_served(session.workspace_id),
            bindings={
                (b.spec.provider, b.spec.model_id): b
                for b in proven_bindings(
                    connection, session.workspace_id, case_book()[0]["engine"], load_manifest()
                )
            },
            execution_enabled=services.admits_workspace_models,
            manifest=load_manifest(),
            roles=tuple(decision_roles()),
            workspace=WorkspaceModelRepository(connection, session.workspace_id).listing(),
            provider_refusal=services.provider_refusal,
            host_refusal=lambda role: services.model_host_refusal(session.workspace_id, role),
        ),
        headers=_PRIVATE,
    )


@router.post("/preflight")
def preflight_model(
    body: ModelPreflightBody,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    request: Request,
) -> Any:
    services = get_services(request)
    found = model_preflight(
        body.provider,
        body.model_id,
        manifest=load_manifest(),
        roles=tuple(decision_roles()),
        workspace=WorkspaceModelRepository(connection, session.workspace_id).state(
            body.provider, body.model_id
        ),
        provider_refusal=services.provider_refusal(body.provider),
        host_refusal=lambda role: services.model_host_refusal(session.workspace_id, role),
        probe_served=services.model_probes_served(session.workspace_id),
        bindings={
            (b.spec.provider, b.spec.model_id): b
            for b in proven_bindings(
                connection, session.workspace_id, case_book()[0]["engine"], load_manifest()
            )
        },
        execution_enabled=services.admits_workspace_models,
    )
    return JSONResponse(content={"profile": PREFLIGHT_PROFILE, **found}, headers=_PRIVATE)


@router.get("/bindings/{binding_sha256}")
def read_model_binding(
    binding_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")],
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> JSONResponse:
    from exulanica.world.workspace_model_bindings import BindingSnapshotRepository

    document = BindingSnapshotRepository(connection, session.workspace_id).read(binding_sha256)
    return JSONResponse(
        content={"code": "model_binding_not_found"} if document is None else document,
        status_code=404 if document is None else 200,
        headers=_PRIVATE,
    )
