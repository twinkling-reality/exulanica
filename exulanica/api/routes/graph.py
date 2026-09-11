"""The entity graph, as one snapshot at one state version.

The payload and the reads that build it are ``exulanica.graph``, one layer down, because eight SQL
statements is not what this package means by "routes validate and delegate". What is left here
is the route: take the workspace off the session, return the snapshot.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.services import Services
from exulanica.graph import GraphPayload, read_snapshot
from exulanica.graph.asset_read_policy import (
    evaluation_time,
    final_check,
    scene_allowed,
    scene_inputs,
)
from exulanica.graph.payload import ReconstructionSceneRow

router = APIRouter(prefix="/graph", tags=["graph"])


def withhold_scene_geometry(scene: ReconstructionSceneRow) -> ReconstructionSceneRow:
    """A denied scene keeps its review identity and loses every piece of geometry it carried.

    Three member fields carry geometry: a measured placement, an unposed point map offered when
    nothing was placed, and a recovered camera. All three go, together with the trained scene.
    """
    return scene.model_copy(
        update={
            "members": [
                member.model_copy(
                    update={"placement": None, "unposed_point_map": None, "recovered_camera": None}
                )
                for member in scene.members
            ],
            "trained_geometry": None,
            "placement_state": "unavailable",
            "rendering_substrate": "source_photographs",
            "displayed_rung": 4,
            "display_reasons": ["Current permission or persisted geometry lineage is unavailable."],
        }
    )


@router.get("", summary="The entity graph, as one snapshot at one state version.")
def snapshot(
    response: Response,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> GraphPayload:
    response.headers["Cache-Control"] = "private, no-store"
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        payload = read_snapshot(connection, session.workspace_id, services.store)
        buffered = {
            scene.scene_id: scene_inputs(
                connection, session.workspace_id, scene.scene_id, services.store
            )
            for scene in payload.reconstruction_scenes
        }
        at = evaluation_time(connection)
        allowed = {
            key
            for key, value in buffered.items()
            if scene_allowed(connection, session.workspace_id, key, value, at)
        }
    # Scene rows embed recovered camera/placement geometry. Reauthorize those buffered
    # dependencies after the snapshot; denied rows retain review identity but no geometry.
    with final_check(connection) as at:
        allowed = {
            key
            for key in allowed
            if scene_allowed(connection, session.workspace_id, key, buffered[key], at)
        }
    scenes = [
        scene if scene.scene_id in allowed else withhold_scene_geometry(scene)
        for scene in payload.reconstruction_scenes
    ]
    return payload.model_copy(update={"reconstruction_scenes": scenes})
