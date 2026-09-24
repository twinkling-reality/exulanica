"""The reviewed behaviour registry, read-only: the motion an authored object may be given.

A behaviour is a key, a version and parameters, and each parameter is an integer with inclusive
bounds, a choice over at least two values, or a toggle (``docs/world-objects-contract.md`` section
3). The registry is reviewed migration data, and every behaviour an edit names is validated against
it before anything is written. Serving it lets a client choose a behaviour and parameters the
server will accept by asking the server, rather than by carrying a copy of the registry that can
drift from it. The registry is the same for every world, so the route takes no world.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection
from exulanica.world.reviewed_catalog import ReviewedCatalog

router = APIRouter(prefix="/world", tags=["world"])


class IntegerParameterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["integer"]
    minimum: int
    maximum: int
    default: int


class ChoiceParameterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["choice"]
    choices: list[str]
    default: str


class ToggleParameterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["toggle"]
    default: bool


#: The three parameter kinds the registry may declare. A row naming another kind fails this view
#: rather than reaching a client as a parameter nothing can validate.
BehaviourParameterView = Annotated[
    IntegerParameterView | ChoiceParameterView | ToggleParameterView,
    Field(discriminator="kind"),
]


class ReviewedBehaviourView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    behaviour_key: str
    behaviour_version: int
    parameters: dict[str, BehaviourParameterView]


@router.get(
    "/behaviours",
    response_model=list[ReviewedBehaviourView],
    summary="The reviewed behaviours an object may be given, with each parameter's bounds.",
)
def reviewed_behaviours(
    connection: ReadOnlyConnection, _session: CurrentSession
) -> list[ReviewedBehaviourView]:
    registry = ReviewedCatalog(connection).behaviours()
    return [
        ReviewedBehaviourView(
            behaviour_key=key, behaviour_version=version, parameters=dict(parameters)
        )
        for (key, version), parameters in sorted(registry.items())
    ]
