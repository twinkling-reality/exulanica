"""The World Write API: where a world model's output is filed, below every recorded rung.

Roadmap Phase 10 capability 2. The counterpart to ``/world-read``, and deliberately a different
prefix rather than a verb on the same one: reading the real world and writing an imagined one are
not two halves of one resource, and a client that acquired write access by holding a read path
would be the first step to the two tiers sharing a code path.

The route accepts a generation's **receipt**, not its bytes. What is stored is the provenance:
which model, at which version, from which prompt digest, conditioned on exactly which digests, and
the seam where the record stops. The generated payload itself stays with whoever generated it until
the proof lens exists to draw it under a label, because a generated surface a viewer cannot tell
from a photographed one is the failure this product exists to avoid, and shipping the bytes before
the label would be exactly that.

One refusal is the substance of the route. The receipt must name this scene's current
``recorded_sha256``: the World Read bundle's digest over the observed world alone. A caller that
supplies any other digest is refused, so the sentence "this was conditioned on the real place" is
something a recipient can recompute rather than something the caller asserted. The recorded digest
rather than the whole bundle's, because the whole bundle already contains previous generations, and
citing it would mean filing a generation changed the thing it cited.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.errors import CanonicalisationError, EpistemicViolation
from exulanica.graph.world_read import world_read_bundle
from exulanica.ingest.generated_scene import record_generated_scene
from exulanica.ingest.repository import IngestRepository
from exulanica.reconstruction.generated import (
    CONDITIONING_ROLES,
    GENERATED_CONTAINERS,
    ConditioningDigest,
    GeneratedSceneReceipt,
    GenerationModel,
)

router = APIRouter(prefix="/world-write", tags=["world-write"])


class GenerationModelBody(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    provider: str
    model_id: str
    model_version: str


class ConditioningBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    sha256: str


class GeneratedSceneBody(BaseModel):
    """One generation, as its producer describes it.

    Every field is required. There is no partial generation: a receipt missing its model, its
    prompt digest, its conditioning or its seam describes an artifact nobody can place, and the
    tier's only value is that a generated surface can always be placed.
    """

    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    model: GenerationModelBody
    prompt_sha256: str
    conditioning: list[ConditioningBody] = Field(min_length=1)
    container: str
    content_sha256: str
    byte_size: int
    seam: str


class GeneratedSceneView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: uuid.UUID
    scene_id: uuid.UUID
    receipt_sha256: str
    tier: str
    already_recorded: bool
    world_read_bundle_sha256: str


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


@router.post(
    "/scenes/{scene_id}/generated",
    summary="File what a world model imagined, in the tier below every recorded rung.",
)
def record_generation(
    scene_id: Annotated[uuid.UUID, Path()],
    body: GeneratedSceneBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> JSONResponse:
    try:
        envelope = world_read_bundle(connection, session.workspace_id, scene_id, services.store)
    except CanonicalisationError as error:
        # No generation may be filed against a scene whose own conditioning digest cannot be
        # computed: the receipt would name a bundle nobody can reproduce.
        return _problem(424, "unreadable_scene", str(error))
    if envelope is None:
        # The same 404 the read route gives, for the same reason: a caller who cannot read a scene
        # must not learn from a write attempt that it exists.
        return _problem(404, "unknown_reference", "no such scene")

    try:
        receipt = GeneratedSceneReceipt(
            model=GenerationModel(
                provider=body.model.provider,
                model_id=body.model.model_id,
                model_version=body.model.model_version,
            ),
            prompt_sha256=body.prompt_sha256,
            conditioning=tuple(
                ConditioningDigest(role=item.role, sha256=item.sha256) for item in body.conditioning
            ),
            container=body.container,
            content_sha256=body.content_sha256,
            byte_size=body.byte_size,
            seam=body.seam,
        )
    except ValueError as error:
        return _problem(
            422,
            "invalid_generation",
            f"{error} Conditioning roles are {list(CONDITIONING_ROLES)}; containers are "
            f"{list(GENERATED_CONTAINERS)}.",
        )

    repository = IngestRepository(connection, session.workspace_id)
    try:
        record = record_generated_scene(
            repository,
            services.store,
            scene_id=scene_id,
            receipt=receipt,
            expected_recorded_sha256=envelope["bundle"]["recorded_sha256"],
        )
    except EpistemicViolation as error:
        return _problem(409, "conditioning_does_not_verify", str(error))

    return JSONResponse(
        status_code=201 if record.inserted else 200,
        content=GeneratedSceneView(
            artifact_id=record.artifact_id,
            scene_id=record.scene_id,
            receipt_sha256=record.receipt_sha256,
            tier="generated",
            already_recorded=not record.inserted,
            world_read_bundle_sha256=receipt.bundle_sha256,
        ).model_dump(mode="json"),
    )
