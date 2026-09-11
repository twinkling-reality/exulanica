"""The segments lifted into one reconstruction scene, under the geometry asset-read policy.

A sibling of the graph's scene row rather than a field on it. The scene row is already the
largest thing a graph read builds, its shape is pinned by the browser's read model, and a
segment list for a 210 member scene is thousands of voxels a client wants only when it opens that
scene. One request per scene, then, with the same permission the geometry beside it has.

**The same policy as geometry, applied the same way.** The read runs in a repeatable-read
snapshot; ``scene_inputs`` buffers the pose manifest and ``scene_allowed`` authorises the scene at
the snapshot's evaluation time; and then, under ``final_check``, both are asked again together
with ``asset_artifact_live`` for every artifact the answer rests on. A scene whose geometry the
graph would withhold gets its segments withheld here, with the same reason. The segments are
voxels in the scene's own frame, and a client that could read them where it could not read the
geometry would be reading the geometry.

**Nothing is stored.** ``Cache-Control: private, no-store``, as the graph snapshot answers: a
person segment is where somebody's body is, and a browser cache is a place a withdrawal cannot
reach.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.services import Services
from exulanica.graph.asset_read_policy import (
    evaluation_time,
    final_check,
    scene_allowed,
    scene_inputs,
)
from exulanica.graph.reconstruction_scenes import (
    SceneSegmentsRead,
    scene_segments_artifacts_live,
    scene_segments_read,
)

router = APIRouter(prefix="/scene-segments", tags=["geometry"])

#: The wire version. Fields may be added; none may be renamed, retyped or removed, which the
#: published fixture in ``web/packages/graph-client/test/fixtures/scene-segments.json`` and its
#: test hold.
SCHEMA_VERSION = 1

_WITHHELD = "Current permission or persisted geometry lineage is unavailable."


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SegmentRegionView(_Strict):
    """One region a segment rests on, in one member photograph."""

    capture_id: uuid.UUID
    kind: Literal["object_mask", "person_region"]
    #: The mask's own evidence span, for click-to-evidence. Null for a person region, whose
    #: outline is not evidence.
    span_id: uuid.UUID | None
    #: The person region's key, for the review flow. Null for an object mask.
    region_key: str | None
    samples: int


class SegmentSamplesView(_Strict):
    point_map: int
    gaussian: int


class SegmentVotesView(_Strict):
    views: int
    min: int
    median: int
    max: int
    fraction_min_millionths: int
    fraction_median_millionths: int


class SegmentBoundsView(_Strict):
    min: list[int]
    max: list[int]


class SceneSegmentView(_Strict):
    segment_id: str
    kind: Literal["object", "person"]
    #: A common noun from a detector's label set, for an object. Always null for a person.
    label: str | None
    #: The person subject, for a person. Always null for an object.
    subject_id: uuid.UUID | None
    #: Present only when a naming receipt is held and no withdrawal stands.
    display_name: str | None
    voxel_count: int
    #: Occupied cells ``[i, j, k]`` of the grid whose edge is ``grid.voxel_size_microunits``
    #: millionths of a scene unit; cell ``i`` spans ``[i, i + 1)`` edges along x.
    voxels: list[list[int]]
    bounds_microunits: SegmentBoundsView
    centroid_microunits: list[int]
    samples: SegmentSamplesView
    votes: SegmentVotesView
    regions: list[SegmentRegionView]
    #: The vision stage's occurrences of this object, which the naming flow can name. Empty for a
    #: segment whose masks were prompted by the local detector.
    occurrence_ids: list[uuid.UUID]


class SceneSegmentsArtifactView(_Strict):
    artifact_id: uuid.UUID
    content_sha256: str
    byte_size: int


class SceneSegmentsGridView(_Strict):
    frame: Literal["scene"]
    voxel_size_microunits: int


class SceneSegmentsView(_Strict):
    schema_version: Literal[1]
    scene_id: uuid.UUID
    state: Literal["available", "stale", "absent", "unavailable"]
    reason: str | None
    artifact: SceneSegmentsArtifactView | None
    pose_receipt_sha256: str | None
    placement_receipt_sha256: str | None
    gate_receipt_sha256: str | None
    grid: SceneSegmentsGridView | None
    policy: dict[str, Any] | None
    segments: list[SceneSegmentView]
    #: How many segments a live check or the asset-read policy took back. Counted here so a client
    #: that drew none cannot report that there were none.
    withheld_segment_count: int
    stale_inputs: list[str]


@router.get(
    "/{scene_id}",
    response_model=SceneSegmentsView,
    summary="The entities lifted into one scene, as voxels, under the geometry read policy.",
)
def scene_segments(
    scene_id: Annotated[uuid.UUID, Path()],
    response: Response,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Any:
    response.headers["Cache-Control"] = "private, no-store"
    workspace = session.workspace_id
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        read = scene_segments_read(connection, workspace, scene_id, services.store)
        if read is None:
            return JSONResponse(
                status_code=404,
                content={"code": "unknown_reference", "detail": "no such scene"},
                headers={"Cache-Control": "private, no-store"},
            )
        allowed = False
        buffered = None
        if read.state == "available":
            buffered = scene_inputs(connection, workspace, scene_id, services.store)
            at = evaluation_time(connection)
            allowed = scene_allowed(
                connection, workspace, scene_id, buffered, at
            ) and scene_segments_artifacts_live(connection, workspace, read, at)
    if allowed:
        with final_check(connection) as at:
            allowed = scene_allowed(
                connection, workspace, scene_id, buffered, at
            ) and scene_segments_artifacts_live(connection, workspace, read, at)
    if read.state == "available" and not allowed:
        read = read.withheld(_WITHHELD)
    return _view(read)


def _view(read: SceneSegmentsRead) -> SceneSegmentsView:
    return SceneSegmentsView(
        schema_version=SCHEMA_VERSION,
        scene_id=read.scene_id,
        state=read.state,
        reason=read.reason,
        artifact=(
            None
            if read.artifact_id is None
            else SceneSegmentsArtifactView(
                artifact_id=read.artifact_id,
                content_sha256=str(read.content_sha256),
                byte_size=int(read.byte_size or 0),
            )
        ),
        pose_receipt_sha256=read.pose_receipt_sha256,
        placement_receipt_sha256=read.placement_receipt_sha256,
        gate_receipt_sha256=read.gate_receipt_sha256,
        grid=(
            None
            if read.voxel_size_microunits is None
            else SceneSegmentsGridView(
                frame="scene", voxel_size_microunits=read.voxel_size_microunits
            )
        ),
        policy=read.policy,
        segments=[SceneSegmentView(**segment) for segment in read.segments],
        withheld_segment_count=read.withheld_segment_count,
        stale_inputs=list(read.stale_inputs),
    )
