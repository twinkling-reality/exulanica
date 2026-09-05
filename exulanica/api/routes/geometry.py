"""Reconstructed geometry: the route by which a derivative reaches a renderer.

**This is not the evidence route and it must never be mistaken for one.** Invariant 2 is that
reconstruction is never evidence: an ``evidence_span`` references ``blob``, artifacts do not live
there, and a point map has nothing a citation could point at. The two routes are separate
prefixes served by separate modules over separate tables for that reason, and
``tests/test_reconstruction_is_not_evidence.py`` asserts the separation from four directions.
What ``/evidence`` serves is what a historical claim resolves to. What this serves is a picture of
a place, whose quality "never participates in the truth guarantee".

Two routes, and the pairing is the whole design.

``GET /geometry`` is the **descriptor list**: which captures have geometry, what container it is
in, how many bytes it is, and the SHA-256 the bytes must hash to. ``GET /geometry/{artifact_id}``
is the bytes. ADR-0009 D10 requires "bytes in hand, a bearer in the header, and the content hash
verified against the descriptor that named it", and it is the descriptor that makes the third
clause possible: bytes fetched from a URL nobody vouched for are bytes a decoder has to trust.

**The ETag is a cache validator and is not what makes the bytes trustworthy.** It happens to be
the same SHA-256, because a content-addressed store has nothing better to offer as a strong
validator. A client that verified against it would be checking the response against itself. The
descriptor is what named the digest before the transfer began, and the client checks against
that; ``web/packages/app/src/geometry-api.ts`` says the same thing from the other side.

**Nothing is stored.** ``Cache-Control: no-store`` rather than the evidence route's
``private, max-age=3600``. A derivative in a browser's on-disk cache is a copy of the corpus in a
place the deletion path cannot reach, and this is the one route that hands one out.

**No range requests, deliberately, and this is the one byte route in this API that refuses one.**
The evidence route supports them because a citation deep link should not have to transfer a whole
photograph to show the top of it. Here the client cannot verify a fragment against a digest of
the whole, so a range would hand back exactly the bytes it has no way to check. A point map is a
few megabytes, which is what makes refusing affordable.

**Deletion reaches this route before the purger does.** A tombstone is authoritative from the
moment it commits and the bytes catch up later, so the read asks the database's own guard rather
than ``artifact.purged_at`` alone, and answers **410 Gone** rather than 404 for something the
user deleted. A client holding a descriptor from before a deletion learns that the region's
geometry is gone rather than that it was never there.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Final, Literal

from fastapi import APIRouter, Depends, Path, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, get_services
from exulanica.api.services import Services
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.graph.geometry import (
    GeometryDescriptor,
    GeometryState,
    point_map_descriptors,
    read_point_map,
)
from exulanica.graph.scene_geometry import read_scene_geometry

router = APIRouter(prefix="/geometry", tags=["geometry"])
scene_router = APIRouter(prefix="/scene-geometry", tags=["geometry"])

#: The container's own media type, in the vendor tree, unregistered with IANA and used here for
#: what RFC 6838 calls private use. It is named rather than left as ``application/octet-stream``
#: so that nothing between the store and the decoder can mistake a point map for an image, and so
#: that a proxy configured to transform images leaves it alone. The container VERSION is not in
#: it: that is the descriptor's ``container`` field, because ADR-0010 bumps the version and a
#: media type that moved with it would rewrite every ``Accept`` header for a header change.
POINT_MAP_MEDIA_TYPE: Final = "application/vnd.exulanica.point-map"


class GeometryReferenceView(BaseModel):
    """Where the bytes are and under what credential, in the shape ``source_media`` already uses.

    ``authorization`` is declared rather than implied, and the client checks it: a reference that
    did not say ``workspace-bearer`` is one the loader must not put a bearer token on, and saying
    so on the wire is what lets a client refuse rather than guess.
    """

    model_config = ConfigDict(extra="forbid")

    href: str
    authorization: Literal["workspace-bearer"]
    content_sha256: str
    byte_size: int


class GeometryView(BaseModel):
    """One capture's geometry. No rung: see :mod:`exulanica.graph.geometry` for why not."""

    model_config = ConfigDict(extra="forbid")

    capture_id: uuid.UUID
    artifact_id: uuid.UUID
    kind: str
    stage_key: str
    stage_version: int
    container: str | None
    state: Literal["available", "bytes_missing"]
    reason: str | None
    needs_repair: bool
    #: Null exactly when the state is not ``available``. A reference to bytes that are not there
    #: would be an invitation to fetch them.
    reference: GeometryReferenceView | None


@router.get(
    "",
    response_model=list[GeometryView],
    summary="Which captures have reconstructed geometry, and the digest of each.",
)
def geometry(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> list[GeometryView]:
    """The descriptor list, in the presentation order :func:`point_map_descriptors` documents.

    Keyed by capture. An island is a client decision (ADR-0005) and the graph payload ships no
    island id, so this ships none either: the client puts capture ids through the same
    ``islandOf`` its occurrences went through, and geometry lands in the same regions the anchors
    did. A server that grouped them here would be answering a question it was deliberately kept
    out of.
    """
    return [
        _view(descriptor)
        for descriptor in point_map_descriptors(connection, session.workspace_id, services.store)
    ]


@router.get(
    "/{artifact_id}",
    summary="The bytes of one reconstructed point map. Never a citation target.",
    responses={200: {"content": {POINT_MAP_MEDIA_TYPE: {}}}},
)
def point_map(
    artifact_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        found = read_point_map(connection, session.workspace_id, artifact_id, services.store)
    except BlobNotFoundError:
        # NOT the application's own BlobNotFoundError handler, which answers "no such evidence".
        # A point map is not evidence and saying it is here would undo, in a message, the
        # separation this whole module exists to keep. 424 rather than 404 because this branch is
        # reachable only by a caller whose own workspace holds the row: the read is scoped, so a
        # stranger got the 404 above and never learns that anything exists. It is the same code
        # ``/world/source-media`` answers for the same fact, which is what makes the two readable
        # together.
        return _problem(
            424,
            "unavailable_asset",
            "the artifact row for this geometry survived and its stored object did not",
        )
    if found is None:
        return _problem(404, "unknown_reference", "no such geometry")
    return Response(
        content=found.payload,
        media_type=POINT_MAP_MEDIA_TYPE,
        headers={
            # A strong validator that IS the content hash, which is what a content-addressed
            # store has to offer and no more. See the module docstring: this is not the digest
            # the client verifies against.
            "ETag": f'"{found.content_sha256}"',
            # NOT the evidence route's `private, max-age=3600`, and the difference is the
            # whole of the reasoning rather than a stricter setting for its own sake. `private`
            # keeps a shared cache out; it does nothing about the browser's own on-disk cache,
            # which is equally a place the purge queue cannot enumerate, let alone clear. The
            # evidence route can afford an hour there because it serves an original the user
            # still holds and a citation deep link is what the product's guarantee resolves to.
            # This serves a derivative the user holds no second copy of, and a stale entry would
            # let a reload redraw a deleted region's geometry for an hour after the tombstone
            # committed, past every check above. What `no-store` costs is one fetch per page
            # load: the client holds the decoded map for the life of the tab and hands it back
            # to the next mount rather than asking again.
            "Cache-Control": "no-store",
            # A container, not an image and not a script. Nothing here should ever be sniffed.
            "X-Content-Type-Options": "nosniff",
            # Stated rather than left to be inferred from a missing header. See the docstring.
            "Accept-Ranges": "none",
        },
    )


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    """The application's own failure shape, built here rather than raised through a handler.

    ``app.py`` answers every failure with ``{code, detail}`` and the client branches on the code:
    ``toApiError`` reads ``body.code`` and falls back to a synthetic ``http_404`` when it is
    absent, which is what a bare ``HTTPException`` produces. Neither of the two facts below is a
    domain error worth a class of its own, and inventing one to reach a handler would put a type
    in the taxonomy to satisfy a serialiser. So the shape is written out, and it is the shape
    every other route in this API returns.
    """
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _view(descriptor: GeometryDescriptor) -> GeometryView:
    reference = None
    if descriptor.state is GeometryState.AVAILABLE:
        reference = GeometryReferenceView(
            href=descriptor.href,
            authorization="workspace-bearer",
            content_sha256=descriptor.content_sha256,
            byte_size=descriptor.byte_size,
        )
    return GeometryView(
        capture_id=descriptor.capture_id,
        artifact_id=descriptor.artifact_id,
        kind=descriptor.kind,
        stage_key=descriptor.stage_key,
        stage_version=descriptor.stage_version,
        container=descriptor.container,
        state=descriptor.state.value,
        reason=descriptor.reason,
        needs_repair=descriptor.needs_repair,
        reference=reference,
    )


@scene_router.get("/{artifact_id}", summary="Exact trained scene bytes, never a citation target.")
def trained_scene(
    artifact_id: Annotated[uuid.UUID, Path()],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        found = read_scene_geometry(connection, session.workspace_id, artifact_id, services.store)
    except (BlobNotFoundError, IntegrityError, ValueError):
        return _problem(424, "unavailable_asset", "trained scene bytes are unavailable or corrupt")
    if found is None:
        return _problem(404, "unknown_reference", "no such scene geometry")
    return Response(
        content=found.payload,
        media_type="application/octet-stream",
        headers={
            "ETag": f'"{found.content_sha256}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Accept-Ranges": "none",
        },
    )
