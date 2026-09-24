"""The worlds a workspace holds, each with its kind, and the policy that says how many it may hold.

Every route that reads or changes a world requires a ``world_id``; this is where a caller learns
which ids there are. The list comes from the registry (:mod:`exulanica.world.worlds`), oldest
first, and never from a fixed id. The policy is returned beside it so a client can say how many
worlds of a kind the workspace may create without restating the number.

Read-only. A world is created by the path that builds it (an authored starter, or a composition
of personal sources), which is where the count policy is checked.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, JsonValue

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection
from exulanica.world.worlds import current_world_count_policy, workspace_worlds

router = APIRouter(prefix="/worlds", tags=["world"])


class WorldCountPolicyView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy_id: str
    version: int
    sha256: str
    #: The most worlds of each kind one workspace may hold; null where the policy sets no limit.
    limits: dict[str, int | None]


class WorldView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    world_id: str
    kind: str
    created_at: dt.datetime
    created_by: uuid.UUID | None
    provenance: dict[str, JsonValue]


class WorldsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    policy: WorldCountPolicyView
    worlds: list[WorldView]


@router.get(
    "",
    response_model=WorldsView,
    summary="Every world this workspace holds, with its kind, and how many of each it may hold.",
)
def worlds(connection: ReadOnlyConnection, session: CurrentSession) -> WorldsView:
    policy = current_world_count_policy()
    return WorldsView(
        policy=WorldCountPolicyView(
            policy_id=policy.policy_id,
            version=policy.version,
            sha256=policy.sha256,
            limits=dict(policy.limits),
        ),
        worlds=[
            WorldView(
                world_id=world.world_id,
                kind=world.kind,
                created_at=world.created_at,
                created_by=world.created_by,
                provenance=dict(world.provenance),
            )
            for world in workspace_worlds(connection, session.workspace_id)
        ],
    )
