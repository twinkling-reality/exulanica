"""A saved world's registered decision roles, offered models and owner choices.

The read names every role the registry serves, including people and traffic signals. A signal's
target effective second and first sealed model-controlled second are separate, so a pending choice
cannot be presented as a light a model already runs. Choosing never asks a model; the background
traffic controller owns that work. The person-specific society route remains available to its
existing callers.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.routes.society_models import society_models
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.decision_roles import DecisionRole, RoleRefused, decision_roles
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.traffic_episodes import TrafficRefused
from exulanica.world.traffic_host import saved_world_roads, traffic_clock
from exulanica.world.traffic_signal_repository import SignalChoiceRefused, TrafficSignalRepository
from exulanica.world.worlds import require_world

__all__ = ["PROFILE", "router"]

PROFILE: Final = "exulanica.world-models/v1"
router = APIRouter(prefix="/world/versions/{version_id}/models", tags=["world"])


class ChosenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]


class RoleChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    subjects: Annotated[list[str], Field(min_length=1, max_length=512)]
    model: ChosenModel | None


def _version(
    connection: ScopedConnection, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> dict[str, Any] | None:
    return connection.execute(
        "select source_snapshot_id from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()


def _signal_role(
    role: DecisionRole,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str,
    version_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> dict[str, Any]:
    contract = role.contract()
    manifest = load_manifest()
    services = get_services(request)
    controller = getattr(request.app.state, "traffic_signal_controller", None)
    if controller is None:
        return {
            "key": role.key,
            "subject": role.subject,
            "label": "Traffic lights",
            "available": False,
            "reason": "traffic_controller_unavailable",
            "subjects": [],
            "models": [],
            "choices": [],
        }
    try:
        value = saved_world_roads(connection, session.workspace_id, world_id, snapshot_id)
        subjects = [
            {**signal, "label": f"High street crossing {index}"}
            for index, signal in enumerate(controller.signals(value), 1)
        ]
        availability = None
    except (
        InvalidStructuralData,
        TrafficRefused,
        UnsupportedNetworkError,
        SignalChoiceRefused,
    ) as exc:
        # A world without roads still has the registered role; its subjects are unavailable by
        # the traffic compiler's named refusal, without concealing the People role beside it.
        subjects = []
        availability = getattr(exc, "code", "roads_unavailable")
    repository = TrafficSignalRepository(connection, session.workspace_id, world_id, version_id)
    latest = repository.current_choices()
    active = repository.activations()
    now = traffic_clock()
    effective = repository.choices_at(now)
    choices = []
    for signal_id, choice in sorted(latest.items()):
        model = choice["model"]
        target = choice["effective_second"]
        activated = active.get(choice["choice_seq"])
        running = effective.get(signal_id)
        running_active = None if running is None else active.get(running["choice_seq"])
        running_model = (
            None
            if running is None
            or running["model"] is None
            or running_active is None
            or running_active > now
            else {
                **running["model"],
                "name": manifest.model_name(running["model"]["model_id"]),
            }
        )
        if target > now:
            status = "pending"
        elif model is None:
            status = "fixed"
        elif activated is None or activated > now:
            status = "preparing"
        else:
            status = "active"
        choices.append(
            {
                "subject_id": signal_id,
                "choice_seq": choice["choice_seq"],
                "model": None
                if model is None
                else {
                    **model,
                    "name": manifest.model_name(model["model_id"]),
                },
                "effective_second": target,
                "active_second": activated,
                "running_model": running_model,
                "running_choice_seq": None if running_model is None else running["choice_seq"],
                "status": status,
                "refusal": None
                if model is None
                else services.choice_refusal(role, model, connection, session.workspace_id),
            }
        )
    models = []
    for spec in manifest.offered_models(role.chosen):
        mechanism = contract.mechanism_for(spec)
        if mechanism is None:
            continue
        models.append(
            {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "name": manifest.model_name(spec.model_id),
                "description": spec.description,
                "mechanism": mechanism.value,
                "refusal": services.provider_refusal(spec.provider),
            }
        )
    return {
        "key": role.key,
        "subject": role.subject,
        "label": "Traffic lights",
        "available": availability is None,
        "reason": availability,
        "host_refusal": services.model_host_refusal(session.workspace_id, role),
        "subjects": subjects,
        "models": models,
        "choices": choices,
        "model_subjects_maximum": contract.value(role.subjects_bound),
        "timing": {
            "segment_seconds": 60,
            "target_preparation_seconds": 60,
        },
    }


@router.get("")
def world_models(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    require_world(connection, session.workspace_id, world_id)
    version = _version(connection, session.workspace_id, world_id, version_id)
    if version is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "world version"}
        )
    roles = []
    for role in decision_roles():
        if role.subject == "signal":
            roles.append(
                _signal_role(
                    role,
                    connection,
                    session,
                    request,
                    world_id,
                    version_id,
                    version["source_snapshot_id"],
                )
            )
        elif role.subject == "person":
            exists = connection.execute(
                "select 1 from world_society where workspace_id=%s and world_id=%s "
                "and version_id=%s limit 1",
                (session.workspace_id, world_id, version_id),
            ).fetchone()
            person = (
                society_models(version_id, connection, session, request, world_id)
                if exists is not None
                else None
            )
            roles.append(
                {
                    "key": role.key,
                    "subject": role.subject,
                    "label": "People",
                    "available": isinstance(person, dict),
                    "reason": None if person else "society_unavailable",
                    "view": person if isinstance(person, dict) else None,
                }
            )
    return {
        "profile": PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        "clock_second": traffic_clock(),
        "roles": roles,
    }


@router.post("/{role_key}")
def choose_world_model(
    role_key: str,
    version_id: uuid.UUID,
    body: RoleChoiceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    require_world(connection, session.workspace_id, world_id)
    version = _version(connection, session.workspace_id, world_id, version_id)
    if version is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "world version"}
        )
    try:
        role = decision_roles().role(role_key)
    except RoleRefused as exc:
        return JSONResponse(status_code=404, content={"code": exc.code, "detail": str(exc)})
    model = None if body.model is None else body.model.model_dump()
    if role.subject == "person":
        try:
            subjects = [str(uuid.UUID(value)) for value in body.subjects]
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={"code": "person_id_invalid", "detail": "A person id is a UUID."},
            )
        repository = SocietyModelChoiceRepository(
            connection, session.workspace_id, world_id=world_id
        )
        try:
            return repository.record_choice(
                version_id,
                role,
                request_id=body.idempotency_key,
                subjects=subjects,
                model=model,
                chosen_by=session.actor,
                manifest=load_manifest(),
                contract=role.contract(),
            )
        except ModelChoiceRefused as exc:
            return JSONResponse(status_code=409, content={"code": exc.code, "detail": exc.detail})
    if role.subject == "signal":
        if len(body.subjects) != 1:
            return JSONResponse(
                status_code=422,
                content={"code": "one_signal_per_choice", "detail": "Choose one traffic light."},
            )
        controller = getattr(request.app.state, "traffic_signal_controller", None)
        if controller is None:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "traffic_controller_unavailable",
                    "detail": "Traffic preparation is unavailable.",
                },
            )
        try:
            value = saved_world_roads(
                connection, session.workspace_id, world_id, version["source_snapshot_id"]
            )
            signals = controller.signals(value)
            repository = TrafficSignalRepository(
                connection, session.workspace_id, world_id, version_id
            )
            return repository.record_choice(
                role,
                load_manifest(),
                request_id=body.idempotency_key,
                signal_id=body.subjects[0],
                known_signals=[row["signal_id"] for row in signals],
                model=model,
                chosen_by=session.actor,
            )
        except SignalChoiceRefused as exc:
            return JSONResponse(
                status_code=503 if exc.code == "traffic_worker_unavailable" else 409,
                content={"code": exc.code, "detail": exc.code},
            )
        except (InvalidStructuralData, TrafficRefused, UnsupportedNetworkError) as exc:
            return JSONResponse(
                status_code=409,
                content={"code": "roads_unavailable", "detail": type(exc).__name__},
            )
    return JSONResponse(
        status_code=409,
        content={"code": "role_subject_unsupported", "detail": role.subject},
    )
