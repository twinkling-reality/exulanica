"""Read-only numeric predicates over the current declared appearance of inventory entities."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlySessions,
    ScopedSessions,
    get_services,
)
from exulanica.api.routes.world_inventory import world_inventory
from exulanica.api.world_edit import object_read_repository
from exulanica.api.world_entity_query import (
    appearance_bytes,
    inspect_appearances,
    query_result,
    resolve_appearances,
)
from exulanica.api.world_scope import WorldId
from exulanica.world.appearance_colour import ColourInterval, ColourSwatch

router = APIRouter(prefix="/world/versions/{version_id}/inventory", tags=["world"])
Channel = Annotated[StrictInt, Field(ge=0, le=255)]
RGB = tuple[Channel, Channel, Channel]


class SwatchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["swatch"]
    srgb8: RGB

    def domain(self) -> ColourSwatch:
        return ColourSwatch(self.srgb8)


class IntervalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["interval"]
    lower: RGB
    upper: RGB

    @model_validator(mode="after")
    def ordered(self) -> IntervalBody:
        self.domain()
        return self

    def domain(self) -> ColourInterval:
        return ColourInterval(self.lower, self.upper)


class PredicateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["declared_base_colour"]
    quantifier: Literal["any_constant_primitive"]
    colour: Annotated[SwatchBody | IntervalBody, Field(discriminator="kind")]


class WorldEntityQueryBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["exulanica.world-entity-query/v1"]
    predicate: PredicateBody


@router.post("/query", response_model=None)
def query_world_entities(
    version_id: uuid.UUID,
    body: WorldEntityQueryBody,
    sessions: ScopedSessions,
    readonly: ReadOnlySessions,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    response: Response,
    world_id: WorldId,
) -> dict | JSONResponse:
    """Match actual constant base factors; reading performs no edit, worker or model call."""
    response.headers["Cache-Control"] = "private, no-store"
    services = get_services(request)

    def read() -> tuple[Any, Any]:
        # Independent short sessions release source-read locks before container storage I/O.
        # Repeat the same inventory authority after bytes, suppressing withdrawn society rows.
        with readonly() as authored, sessions() as connection:
            repository = object_read_repository(authored, session, services, world_id)
            inventory = world_inventory(
                version_id, repository, connection, session, held, request, response, world_id
            )
            if isinstance(inventory, JSONResponse):
                return inventory, None
            selected = resolve_appearances(connection, session.workspace_id, inventory)
            return inventory, selected

    inventory, selected = read()
    if isinstance(inventory, JSONResponse):
        return inventory
    assert selected is not None
    inspected = inspect_appearances(
        selected, lambda appearance: appearance_bytes(appearance, services, session.workspace_id)
    )
    final_inventory, final_selected = read()
    if isinstance(final_inventory, JSONResponse):
        return final_inventory
    assert final_selected is not None
    return query_result(
        final_inventory,
        selected,
        final_selected,
        inspected,
        body.predicate.colour.domain(),
        body.predicate.model_dump(mode="json"),
    )
