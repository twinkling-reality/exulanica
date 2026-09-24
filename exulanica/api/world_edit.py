"""What every authored-world edit shares: bodies, repositories, problems and one transaction.

The authored-world routes (:mod:`~exulanica.api.routes.world_versions`,
:mod:`~exulanica.api.routes.world_environments`, :mod:`~exulanica.api.routes.world_objects` and
:mod:`~exulanica.api.routes.world_compositions`) are one surface split by subject, and this is the
part they have in common. It is a separate surface from the style routes for a reason worth
stating where the code is. The style routes adapt an existing frontend recipe, so they accept
camelCase aliases alongside snake_case. This surface has no prior client, ``world_read.py`` and
``world_write.py`` accept snake_case only, and the graph-client fixtures are snake_case. Inventing
a second casing for a contract nobody has generated against yet would be inventing the problem the
aliases exist to solve.

Domain failures here are mapped locally, by :data:`OBJECT_PROBLEMS`, rather than through an
``app.py`` exception handler, following ``world_write.py``. Registering these routers therefore
adds no global handler, and the response shape is the same ``{code, detail}`` every other route
returns.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated, Final, Literal, Protocol

from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, model_validator

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.services import Services
from exulanica.api.world_scope import WorldId
from exulanica.api.world_version_document import AlternateVersionView, rendered_version
from exulanica.world import (
    MAX_SCALE_MILLI,
    MAX_YAW_MICRORADIANS,
    AlternateVersion,
    CompositionBlocked,
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSelection,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    InvalidObjectData,
    InvalidObjectState,
    InvalidStructuralData,
    ObjectBehaviour,
    SavedWorldEntryRepository,
    SourceAnchor,
    StaleObjectBase,
    StaleSavedWorldEntry,
    StaleStructuralBase,
    Transform,
    WorldObjectRepository,
)
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.worlds import require_world


class SavedEntryAdvanceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entry_id: uuid.UUID
    base_revision: int = Field(ge=1)
    authored_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authored_edit_seq: int = Field(ge=0)


class TransformBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: StrictInt throughout. A float here would be refused by the canonical encoder later with a
    #: message about digests; refusing it at the transport edge names the field instead.
    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=MAX_YAW_MICRORADIANS)
    scale_milli: StrictInt = Field(ge=1, le=MAX_SCALE_MILLI)

    def domain(self) -> Transform:
        return Transform(self.x_mm, self.y_mm, self.z_mm, self.yaw_microradians, self.scale_milli)


class BehaviourBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behaviour_key: str = Field(max_length=200)
    behaviour_version: StrictInt = Field(ge=1)
    parameters: dict[str, JsonValue]

    def domain(self) -> ObjectBehaviour:
        return ObjectBehaviour(self.behaviour_key, self.behaviour_version, self.parameters)


class SourceAnchorBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    frame_name: str = Field(min_length=1, max_length=200)
    coordinate_scale: StrictInt = Field(gt=0)
    coordinates: tuple[StrictInt, ...] = Field(min_length=2, max_length=3)

    def domain(self) -> SourceAnchor:
        return SourceAnchor(self.frame_name, self.coordinate_scale, self.coordinates)


class EnvironmentSelectionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["whole_asset", "feature"]
    feature_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    render_batch_id: StrictInt | None = Field(default=None, ge=0, le=2_147_483_647)

    @model_validator(mode="after")
    def complete(self) -> EnvironmentSelectionBody:
        if self.kind == "feature" and (self.feature_id is None or self.render_batch_id is None):
            raise ValueError("feature selection requires feature_id and render_batch_id")
        if self.kind == "whole_asset" and (
            self.feature_id is not None or self.render_batch_id is not None
        ):
            raise ValueError("whole-asset selection cannot name a feature or render batch")
        return self

    def domain(self) -> EnvironmentSelection:
        return EnvironmentSelection(self.kind, self.feature_id, self.render_batch_id)


class EntryBoundEditBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    saved_entry: SavedEntryAdvanceBody | None = None


class MoveObjectBody(EntryBoundEditBody):
    transform: TransformBody


class BaseStateBody(EntryBoundEditBody):
    pass


def object_read_repository(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    world_id: WorldId,
) -> WorldObjectRepository:
    require_world(connection, session.workspace_id, world_id)
    return WorldObjectRepository(
        connection, session.workspace_id, world_id=world_id, store=services.store
    )


def object_write_repository(
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    request: Request,
    world_id: WorldId,
) -> WorldObjectRepository:
    require_world(connection, session.workspace_id, world_id)
    observer = getattr(request.app.state, "society_authored_edit", None)
    return WorldObjectRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        store=services.store,
        on_edit=(
            None
            if observer is None
            else lambda version_id: observer(connection, session, version_id)
        ),
    )


ReadObjects = Annotated[WorldObjectRepository, Depends(object_read_repository)]
WriteObjects = Annotated[WorldObjectRepository, Depends(object_write_repository)]

#: The domain failures this surface maps itself, and the code each one answers with. Reused
#: classes are absent on purpose: `UnknownWorldResource` and `UnavailableAsset` already have
#: application-wide handlers and must keep answering identically here.
OBJECT_PROBLEMS: Final[tuple[tuple[type[Exception], int, str], ...]] = (
    (InvalidEnvironmentData, 422, "invalid_environment_data"),
    (InvalidEnvironmentState, 409, "invalid_environment_state"),
    (EnvironmentBindingDrift, 409, "environment_binding_drift"),
    (EnvironmentSourceWithdrawn, 410, "withdrawn"),
    (EnvironmentCompositionDenied, 403, "operation_denied"),
    #: The body's detail is exactly the blocked_reason code: clients keep only code and detail.
    (CompositionBlocked, 409, "composition_blocked"),
    (InvalidObjectData, 422, "invalid_object_data"),
    (InvalidStructuralData, 422, "invalid_structural_data"),
    (StaleStructuralBase, 409, "stale_structural_base"),
    (StaleObjectBase, 409, "stale_object_base"),
    (StaleSavedWorldEntry, 409, "stale_saved_world_entry"),
    (InvalidObjectState, 409, "invalid_object_state"),
    (InvalidatedSourceVersion, 409, "invalidated_source_version"),
    #: The society input hook refusing an accepted edit inside its transaction. The code and
    #: status are the ones the society routes answer for the same refusal.
    (UnavailableSocietyInput, 424, "unavailable_society_input"),
)


def object_problem(exc: Exception) -> JSONResponse | None:
    for kind, status, code in OBJECT_PROBLEMS:
        if isinstance(exc, kind):
            return JSONResponse(status_code=status, content={"code": code, "detail": str(exc)})
    return None


class EntryBoundEdit(Protocol):
    """What every authored edit body carries: the base it was made against, and optionally the
    saved world whose resume point advances with it."""

    base_state_sha256: str
    saved_entry: SavedEntryAdvanceBody | None


def commit_edit(
    request: Request,
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    body: EntryBoundEdit,
    operation: Callable[[], AlternateVersion],
) -> Response | AlternateVersionView:
    """Run one mutation and answer with the whole version, or with this surface's problem shape.

    The whole version rather than the changed object, because the caller needs the new
    ``state_sha256`` to make its next edit and a second round trip to fetch it is a second chance
    for another writer to move the base first. The saved entry, the version and the base come from
    ``version_id`` and ``body`` here rather than from every caller, so no route can bind a saved
    world to a different base than the one its edit names.
    """
    saved_entry = body.saved_entry
    try:
        with repository.connection.transaction():
            entries = SavedWorldEntryRepository(repository.connection, repository.workspace_id)
            if saved_entry is not None:
                entries.lock_authored_advance_base(
                    saved_entry.entry_id,
                    base_revision=saved_entry.base_revision,
                    world_id=repository.world_id,
                    authored_version_id=version_id,
                    authored_state_sha256=saved_entry.authored_state_sha256,
                    authored_edit_seq=saved_entry.authored_edit_seq,
                    mutation_base_state_sha256=body.base_state_sha256,
                )
            version = operation()
            if saved_entry is not None:
                entries.advance_authored_locked(
                    saved_entry.entry_id,
                    base_revision=saved_entry.base_revision,
                    world_id=repository.world_id,
                    authored_version_id=version.version_id,
                    result_state_sha256=version.state_sha256,
                    result_edit_seq=version.edit_seq,
                )
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem
    return rendered_version(repository, version, get_services(request).store)
