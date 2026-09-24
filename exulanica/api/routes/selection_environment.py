"""The NYC environment panel's route: one typed edit proposed, and no world state changed.

``POST /selection/environment`` reads the admitted NYC Open Data feature the panel selected and
the alternate version it would edit, and asks the environment drafter to choose one operation
from those the version allows. The proposal is returned for the panel to show; applying it is a
separate write.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.routes.selection import (
    AppearanceRefusalView,
    ExecutionView,
    _execution,
    _require_model,
)
from exulanica.environment import (
    EnvironmentOperationDenied,
    EnvironmentRepository,
    EnvironmentResourceWithdrawn,
    UnknownEnvironmentResource,
)
from exulanica.environment.feature_placement import nyc_instance_id, selected_feature_placement
from exulanica.environment.nyc_open_data import PROVIDER_KEY as NYC_OPEN_DATA_PROVIDER_KEY
from exulanica.selection.environment_proposal import (
    ENVIRONMENT_PROMPT_VERSION,
    EnvironmentOperation,
    propose_environment_operation,
)
from exulanica.world import (
    EnvironmentBindingDrift,
    EnvironmentCompositionDenied,
    EnvironmentSourceWithdrawn,
    InvalidatedSourceVersion,
    InvalidEnvironmentData,
    InvalidEnvironmentState,
    StaleObjectBase,
    UnavailableAsset,
    WorldObjectRepository,
)

router = APIRouter(prefix="/selection", tags=["selection"])


# The NYC environment panel is already an explicitly scoped editing surface. Its utterance goes
# directly to this closed operation chooser and never through the measured appearance classifier.


class EnvironmentTransformContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x_mm: StrictInt
    y_mm: StrictInt
    z_mm: StrictInt
    yaw_microradians: StrictInt = Field(ge=0, le=6_283_185)
    scale_milli: StrictInt = Field(ge=1, le=1_000_000)


class EnvironmentProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    utterance: Annotated[str, Field(min_length=1, max_length=1000)]
    version_id: uuid.UUID
    base_state_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    admission_id: uuid.UUID
    selected_feature_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    region_id: str = Field(min_length=1, max_length=500)
    transform: EnvironmentTransformContext
    origin_role: Literal["fictional", "personal"]


class PlaceEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["place_selected_feature"]
    version_id: uuid.UUID
    base_state_sha256: str
    instance_id: str
    admission_id: uuid.UUID
    render_asset_id: uuid.UUID
    publication_id: uuid.UUID
    feature_id: str
    render_batch_id: int
    source_anchor_frame_name: str
    source_anchor_coordinate_scale: int
    source_anchor_coordinates: tuple[int, ...] = Field(min_length=2, max_length=3)
    region_id: str
    transform: EnvironmentTransformContext
    origin_role: Literal["fictional", "personal"]
    model_id: str | None
    prompt_version: str


class RemoveEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["remove_selected_authored_instance"]
    version_id: uuid.UUID
    base_state_sha256: str
    instance_id: str
    model_id: str | None
    prompt_version: str


class UndoEnvironmentProposalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["undo_latest_version_edit"]
    version_id: uuid.UUID
    base_state_sha256: str
    model_id: str | None
    prompt_version: str


EnvironmentTypedProposalView = (
    PlaceEnvironmentProposalView | RemoveEnvironmentProposalView | UndoEnvironmentProposalView
)


class EnvironmentProposalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal: EnvironmentTypedProposalView | None
    refusal: AppearanceRefusalView | None
    execution: ExecutionView


def _has_reversible_edit(version: Any) -> bool:
    undone = {edit.undone_edit_id for edit in version.edits if edit.undone_edit_id is not None}
    return any(edit.kind != "undo" and edit.edit_id not in undone for edit in version.edits)


@router.post(
    "/environment",
    summary="Propose one typed NYC environment edit without changing world state.",
)
def environment_proposal(
    body: EnvironmentProposalRequest,
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> EnvironmentProposalResponse:
    client = _require_model(request, connection, session)
    empty_execution = _execution((), (), prompt_version=ENVIRONMENT_PROMPT_VERSION)
    if body.selected_feature_id is None:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="no_selected_feature", detail="select an NYC Open Data feature first"
            ),
            execution=empty_execution,
        )

    services = get_services(request)
    objects = WorldObjectRepository(connection, session.workspace_id, store=services.store)
    version = objects.version(body.version_id)
    if version.state_sha256 != body.base_state_sha256:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="stale_version",
                detail="the alternate version changed; reload it and request a fresh proposal",
            ),
            execution=empty_execution,
        )

    try:
        catalog = EnvironmentRepository(
            connection, session.workspace_id, services.store
        ).read_features(body.admission_id, feature_id=body.selected_feature_id)
    except UnknownEnvironmentResource as exc:
        raise HTTPException(status_code=404, detail="no such environment selection") from exc
    except EnvironmentResourceWithdrawn as exc:
        raise HTTPException(status_code=410, detail=str(exc)) from exc
    except EnvironmentOperationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if len(catalog.features) != 1:
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="no_selected_feature",
                detail="the selected feature is not in the current admitted publication",
            ),
            execution=empty_execution,
        )
    feature = catalog.features[0]
    provider_feature_id = feature.get("provider_feature_id")
    if (
        catalog.provider_key != NYC_OPEN_DATA_PROVIDER_KEY
        or not isinstance(provider_feature_id, str)
        or re.fullmatch(r"doitt_id:[1-9][0-9]*", provider_feature_id) is None
    ):
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="unsupported_source",
                detail="the selected feature is not from the admitted NYC Open Data source",
            ),
            execution=empty_execution,
        )
    instance_id = nyc_instance_id(provider_feature_id)
    bbox = feature.get("bbox")
    render_batch_id = feature.get("render_batch_id")
    frame_name = catalog.geographic_frame.get("name")
    if (
        not isinstance(bbox, list)
        or len(bbox) not in (4, 6)
        or any(isinstance(value, bool) or not isinstance(value, int) for value in bbox)
        or isinstance(render_batch_id, bool)
        or not isinstance(render_batch_id, int)
        or not isinstance(frame_name, str)
    ):
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code="unsupported", detail="the selected feature binding is malformed"
            ),
            execution=empty_execution,
        )
    placement = selected_feature_placement(
        catalog,
        instance_id=instance_id,
        feature_id=body.selected_feature_id,
        render_batch_id=render_batch_id,
        frame_name=frame_name,
        bbox=bbox,
        region_id=body.region_id,
        transform=(
            body.transform.x_mm,
            body.transform.y_mm,
            body.transform.z_mm,
            body.transform.yaw_microradians,
            body.transform.scale_milli,
        ),
        origin_role=body.origin_role,
    )
    selected_instance = next(
        (
            instance
            for instance in version.environment_instances
            if instance.instance_id == instance_id and not instance.removed
        ),
        None,
    )
    validated = None
    if selected_instance is None:
        try:
            validated = objects.validate_environment_placement(
                body.version_id,
                placement,
                base_state_sha256=body.base_state_sha256,
            )
        except (InvalidEnvironmentData, InvalidEnvironmentState) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (
            StaleObjectBase,
            InvalidatedSourceVersion,
            EnvironmentBindingDrift,
        ) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except EnvironmentSourceWithdrawn as exc:
            raise HTTPException(status_code=410, detail=str(exc)) from exc
        except EnvironmentCompositionDenied as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except UnavailableAsset as exc:
            raise HTTPException(status_code=424, detail=str(exc)) from exc
    operations = [
        (
            EnvironmentOperation.REMOVE_SELECTED_AUTHORED_INSTANCE
            if selected_instance is not None
            else EnvironmentOperation.PLACE_SELECTED_FEATURE
        )
    ]
    if _has_reversible_edit(version):
        operations.append(EnvironmentOperation.UNDO_LATEST_VERSION_EDIT)
    decision = propose_environment_operation(
        connection, client, body.utterance, session, operations
    )
    execution = _execution(decision.calls, (), prompt_version=ENVIRONMENT_PROMPT_VERSION)
    if decision.operation is None:
        assert decision.refusal is not None
        return EnvironmentProposalResponse(
            proposal=None,
            refusal=AppearanceRefusalView(
                code=decision.refusal.code.value, detail=decision.refusal.detail
            ),
            execution=execution,
        )
    common = {
        "version_id": body.version_id,
        "base_state_sha256": body.base_state_sha256,
        "model_id": decision.model_id,
        "prompt_version": ENVIRONMENT_PROMPT_VERSION,
    }
    if decision.operation is EnvironmentOperation.REMOVE_SELECTED_AUTHORED_INSTANCE:
        proposal: EnvironmentTypedProposalView = RemoveEnvironmentProposalView(
            operation=decision.operation.value, instance_id=instance_id, **common
        )
    elif decision.operation is EnvironmentOperation.UNDO_LATEST_VERSION_EDIT:
        proposal = UndoEnvironmentProposalView(operation=decision.operation.value, **common)
    else:
        assert validated is not None
        source = validated.source
        assert source.publication_id is not None
        assert source.selection.feature_id is not None
        assert source.selection.render_batch_id is not None
        proposal = PlaceEnvironmentProposalView(
            operation=decision.operation.value,
            instance_id=validated.instance_id,
            admission_id=source.admission_id,
            render_asset_id=source.render_asset_id,
            publication_id=source.publication_id,
            feature_id=source.selection.feature_id,
            render_batch_id=source.selection.render_batch_id,
            source_anchor_frame_name=source.anchor.frame_name,
            source_anchor_coordinate_scale=source.anchor.coordinate_scale,
            source_anchor_coordinates=source.anchor.coordinates,
            region_id=validated.region_id,
            transform=EnvironmentTransformContext(
                x_mm=validated.transform.x_mm,
                y_mm=validated.transform.y_mm,
                z_mm=validated.transform.z_mm,
                yaw_microradians=validated.transform.yaw_microradians,
                scale_milli=validated.transform.scale_milli,
            ),
            origin_role=validated.origin.role,
            **common,
        )
    return EnvironmentProposalResponse(proposal=proposal, refusal=None, execution=execution)
