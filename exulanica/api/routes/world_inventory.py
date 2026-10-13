"""Read-only overview of a saved world's covered semantic collections and model roles."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.world_models import world_models_document
from exulanica.api.society_making import SocietyHooks, society_repository
from exulanica.api.world_edit import ReadObjects
from exulanica.api.world_inventory import inventory_document
from exulanica.api.world_scope import WorldId
from exulanica.api.world_version_document import rendered_version
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety, served_snapshot

router = APIRouter(prefix="/world/versions/{version_id}/inventory", tags=["world"])


@router.get("")
def world_inventory(
    version_id: uuid.UUID,
    repository: ReadObjects,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    response: Response,
    world_id: WorldId,
) -> Any:
    """Enumerate saved identities; role membership does not grant model assignment or execution."""
    response.headers["Cache-Control"] = "private, no-store"
    version = rendered_version(
        repository,
        repository.version(version_id, with_availability=False),
        get_services(request).store,
    ).model_dump(mode="json")
    # Native society reads take row locks to hold their input-authorization barrier. Reuse
    # their ordinary scoped role; the authored projection above uses the SELECT-only role.
    models = world_models_document(version_id, connection, session, held, request, world_id)
    if isinstance(models, JSONResponse):
        models.headers["Cache-Control"] = "private, no-store"
        return models
    society = None
    unavailable = None
    try:
        # Keep the society's current-input and queued-input authorization as the last society
        # read. A withdrawal between the role read and this read must not expose its old view.
        society = served_snapshot(
            society_repository(
                connection, session, SocietyHooks.of_app(request.app), world_id
            ).snapshot(version_id)
        )
    except UnknownSociety:
        pass
    except UnavailableSocietyInput:
        unavailable = "unavailable_society_input"
    if society is None:
        models["roles"] = [
            {
                **role,
                "view": None,
                "available": False,
                "reason": unavailable or "society_unavailable",
            }
            if role["subject"] == "person"
            else role
            for role in models["roles"]
        ]
        for role in models["roles"]:
            if role["subject"] == "person" and role["capability"]["state"] == "available":
                role["capability"] = {
                    **role["capability"],
                    "state": "unavailable",
                    "code": unavailable or "society_unavailable",
                }
    return inventory_document(version, models, society, society_unavailable=unavailable)
