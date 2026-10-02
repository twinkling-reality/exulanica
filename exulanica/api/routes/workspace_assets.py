"""A workspace's own assets, over HTTP: admit, read, prepare, cancel, withdraw and deliver.

Routes validate and delegate: every rule is in :mod:`exulanica.world.workspace_assets`, the static
profile in :mod:`exulanica.world.static_glb`, and migration 0126. What this module decides is the
shape of an answer, and ``docs/workspace-asset-admission.md`` states it.

*   ``POST /workspace-assets`` takes one multipart upload: a ``declaration`` field holding the
    person's JSON declaration and one ``content`` file. It answers 201 with the new asset, or 200
    with the live asset an identical declaration over identical bytes already made. Every refusal
    is answered before a row or a byte is written. Bytes only: no path, no URL, nothing fetched.
*   ``GET /workspace-assets`` lists the workspace's live assets and states what may be admitted
    (content kinds, units, licences and every bound, with units in the names).
*   ``GET /workspace-assets/{asset_id}`` is one asset with its preparation and one decision,
    ``availability``: placeable, or not and why.
*   ``POST .../preparation`` requests or retries the preparation (202 while it waits or runs,
    200 once prepared); ``POST .../preparation/cancel`` stops one that has not finished.
*   ``POST .../withdraw`` ends the asset for good. It hides; it does not erase.
*   ``GET .../prepared/bytes`` serves the prepared container after the 0041 final check, private
    and never cached, so a withdrawal is not outlived by a copy.

An asset that never existed here and another workspace's answer the same 404; a withdrawn one is
410. A deployment whose database role may not append these tables (the judge) answers every write
403.

The list and the asset read carry ``capabilities``: the descriptors of
:mod:`exulanica.api.capabilities` for admission (on the list) and for each asset's preparation,
cancellation and withdrawal (on each asset), each state taken from the predicate its own write path
checks (:func:`~exulanica.world.workspace_preparations.queues_a_run`,
:func:`~exulanica.world.workspace_preparations.cancel_refusal` and ``workspace_asset_spent()``).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final

import psycopg
from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from exulanica.api.capabilities import (
    AVAILABLE,
    Effect,
    Operation,
    Subjects,
    describe,
    installation_facts_of,
    surface,
    unavailable,
    unknown,
)
from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ScopedConnection,
    get_services,
)
from exulanica.api.permissions import Permission
from exulanica.selection.validation import Session
from exulanica.world import static_glb
from exulanica.world.asset_import import MAX_ASSET_BYTES
from exulanica.world.workspace_assets import (
    ADMITTED_LICENCES,
    MAX_DECLARATION_BYTES,
    PERMITTED_USES,
    USE_POLICY,
    AssetContentRefused,
    AssetRecord,
    AssetTooLarge,
    AttributionRequired,
    ContentDigestMismatch,
    InvalidDeclaration,
    LicenceNotAdmitted,
    PreparationFinished,
    PreparationNotReady,
    PreparationRecord,
    PreparedBytesMissing,
    UnknownWorkspaceAsset,
    WorkspaceAssetBusy,
    WorkspaceAssetQuotaExceeded,
    WorkspaceAssetRepository,
    WorkspaceAssetRuntime,
    WorkspaceAssetsReadOnly,
    WorkspaceAssetWithdrawn,
)
from exulanica.world.workspace_preparations import (
    PreparationBlocked,
    PreparationError,
    UnknownPreparation,
    cancel_refusal,
    cancelled_by_removal,
    queues_a_run,
)

__all__ = ["router"]

router = APIRouter(prefix="/workspace-assets", tags=["workspace-assets"])
_PRIVATE: Final = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
ASSET_PROFILE: Final = "exulanica.workspace-asset/v1"
LIST_PROFILE: Final = "exulanica.workspace-asset-list/v1"


class _Unavailable(Exception):
    """This instance was started without workspace asset namespaces."""


def _runtime(request: Request) -> WorkspaceAssetRuntime:
    runtime = getattr(get_services(request), "workspace_assets", None)
    if runtime is None:
        raise _Unavailable
    return runtime


def _repository(
    request: Request, connection: psycopg.Connection, session: Session
) -> WorkspaceAssetRepository:
    runtime = _runtime(request)
    return WorkspaceAssetRepository(
        connection,
        session.workspace_id,
        session.actor,
        stores=runtime.stores,
        retained_bytes_limit=runtime.retained_bytes_limit,
    )


def _problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={**extra, "code": code, "detail": detail}, headers=_PRIVATE
    )


def _refused(error: Exception) -> JSONResponse:
    if isinstance(error, _Unavailable):
        return _problem(
            503, "workspace_assets_unavailable", "this instance keeps no workspace asset store"
        )
    if isinstance(error, InvalidDeclaration):
        return _problem(
            422, "invalid_declaration", "the declaration is refused", problems=list(error.problems)
        )
    if isinstance(error, LicenceNotAdmitted):
        return _problem(422, "licence_not_admitted", str(error))
    if isinstance(error, AttributionRequired):
        return _problem(422, "attribution_required", str(error))
    if isinstance(error, ContentDigestMismatch):
        return _problem(422, "content_digest_mismatch", str(error))
    if isinstance(error, AssetContentRefused):
        # The family code with the reason in `detail`, as composition answers blocked reasons; the
        # sentence is the developer's record, never the only explanation a UI can show.
        return _problem(422, "asset_content_refused", error.reason, explanation=str(error))
    if isinstance(error, AssetTooLarge):
        return _problem(413, "asset_too_large", str(error))
    if isinstance(error, WorkspaceAssetQuotaExceeded):
        return _problem(429, "workspace_asset_quota_exceeded", str(error))
    if isinstance(error, UnknownWorkspaceAsset | UnknownPreparation):
        return _problem(404, "unknown_reference", "no such workspace asset")
    if isinstance(error, WorkspaceAssetWithdrawn | PreparationBlocked):
        return _problem(410, "withdrawn", "this asset was withdrawn or its workspace erased")
    if isinstance(error, PreparationNotReady):
        return _problem(409, "preparation_not_ready", "this asset has no prepared output")
    if isinstance(error, PreparedBytesMissing):
        return _problem(
            409, "prepared_bytes_missing", "the prepared bytes are missing; request preparation"
        )
    if isinstance(error, PreparationFinished):
        return _problem(409, "preparation_finished", "the preparation finished; withdraw instead")
    if isinstance(error, WorkspaceAssetsReadOnly):
        return _problem(403, "workspace_assets_read_only", "this deployment keeps assets read-only")
    if isinstance(error, WorkspaceAssetBusy):
        response = _problem(503, "retry", "a delivery was in progress; ask again")
        response.headers["Retry-After"] = "1"
        return response
    raise error


def _json(content: Any, status: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status, content=content, headers=_PRIVATE)


# -- views ---------------------------------------------------------------------------------------


def _availability(preparation: PreparationRecord | None, present: bool) -> dict[str, Any]:
    """The one decision a client reads: placeable now, or not and which recovery applies."""
    if preparation is None:
        code: str | None = "not_prepared"
    elif preparation.state in ("requested", "running"):
        code = "preparing"
    elif preparation.state == "failed":
        code = "preparation_failed"
    elif preparation.state == "cancelled":
        code = "preparation_cancelled"
    elif not preparation.placeable:
        code = "incompatible"
    elif not present:
        code = "prepared_bytes_missing"
    else:
        code = None
    return {"state": "placeable" if code is None else "not_placeable", "code": code}


def _preparation_view(preparation: PreparationRecord, present: bool) -> dict[str, Any]:
    return {
        "preparation_id": str(preparation.preparation_id),
        "preparer": {"id": preparation.preparer_id, "version": preparation.preparer_version},
        "parameters": dict(preparation.parameters),
        "state": preparation.state,
        "attempts": preparation.attempts,
        "requested_at": preparation.requested_at.isoformat(),
        "prepared_at": None
        if preparation.prepared_at is None
        else preparation.prepared_at.isoformat(),
        "output": None
        if preparation.output_sha256 is None
        else {
            "content_sha256": preparation.output_sha256,
            "byte_size": preparation.output_byte_size,
            "media_type": static_glb.MEDIA_TYPE,
            "bytes": "available" if present else "missing",
        },
        "dimensions_mm": None
        if preparation.dimensions_mm is None
        else dict(preparation.dimensions_mm),
        "receipt": None if preparation.receipt is None else dict(preparation.receipt),
        "failure": None
        if preparation.failure_class is None
        else {
            "class": preparation.failure_class,
            "code": preparation.failure_code,
            "message": preparation.failure_message,
        },
    }


def _asset_view(
    asset: AssetRecord, preparation: PreparationRecord | None, present: bool
) -> dict[str, Any]:
    rights = asset.declaration["rights"]
    compatibility = (
        []
        if preparation is None or preparation.receipt is None
        else list(preparation.receipt.get("compatibility", []))
    )
    return {
        "profile": ASSET_PROFILE,
        "asset_id": str(asset.asset_id),
        "title": asset.title,
        "content_kind": asset.content_kind,
        "admitted_at": asset.created_at.isoformat(),
        "declaration": dict(asset.declaration),
        "declaration_sha256": asset.declaration_sha256,
        "input": {
            "content_sha256": asset.input_sha256,
            "byte_size": asset.input_byte_size,
            "media_type": static_glb.MEDIA_TYPE,
        },
        "rights": {
            "basis": asset.rights_basis,
            "licence_id": asset.licence_id,
            "attribution": rights.get("attribution"),
            "source_reference": rights.get("source_reference"),
            "statement": rights.get("statement"),
        },
        "use": {"policy": asset.use_policy, "uses": list(PERMITTED_USES)},
        "preparation": None if preparation is None else _preparation_view(preparation, present),
        "compatibility": compatibility,
        "availability": _availability(preparation, present),
    }


def _present(repository: WorkspaceAssetRepository, preparation: PreparationRecord | None) -> bool:
    return (
        preparation is not None
        and preparation.state == "prepared"
        and repository.output_present(preparation)
    )


def _limits(connection: psycopg.Connection) -> dict[str, Any]:
    """What may be admitted, from the profile's own constants and the schema's own bounds."""
    bounds = connection.execute(
        "select assets, input_bytes, requests_per_day, pending_at_once "
        "from workspace_asset_limits()"
    ).fetchone()
    limits = static_glb.LIMITS
    return {
        "content_kinds": [
            {
                "content_kind": "static_glb",
                "profile": static_glb.PROFILE,
                "media_type": static_glb.MEDIA_TYPE,
            }
        ],
        "units": list(static_glb.UNITS),
        "licences": list(ADMITTED_LICENCES),
        "rights_bases": ["own_work", "licensed"],
        "use_policy": USE_POLICY,
        "bounds": {
            "content_bytes": MAX_ASSET_BYTES,
            "declaration_bytes": MAX_DECLARATION_BYTES,
            "json_chunk_bytes": static_glb.MAX_JSON_BYTES,
            "nodes": limits.nodes,
            "meshes": limits.meshes,
            "primitives": limits.primitives,
            "accessors": limits.accessors,
            "buffer_views": limits.buffer_views,
            "materials": limits.materials,
            "textures": limits.textures,
            "images": limits.images,
            "samplers": limits.samplers,
            "draw_calls": limits.draw_calls,
            "rendered_vertices": limits.rendered_vertices,
            "rendered_triangles": limits.rendered_triangles,
            "texture_side_px": limits.texture_side_px,
            "texels": limits.texels,
            "scene_depth": limits.scene_depth,
            "placeable_largest_extent_mm": {
                "minimum": limits.placeable_min_extent_mm,
                "maximum": limits.placeable_max_extent_mm,
            },
            "workspace_assets": None if bounds is None else bounds["assets"],
            "workspace_input_bytes": None if bounds is None else bounds["input_bytes"],
            "preparation_requests_per_day": None if bounds is None else bounds["requests_per_day"],
            "preparations_pending": None if bounds is None else bounds["pending_at_once"],
        },
    }


# -- capabilities --------------------------------------------------------------------------------

#: Whether an admitted asset is prepared here depends on a preparation process this server cannot
#: see: the installation facts state it (their ``preparation`` component), and where a process has
#: none the effect's state is not known.
_PREPARATION: Final = Effect(
    "preparation",
    unknown(),
    component="preparation",
    preparer=f"{static_glb.PREPARER_ID}@{static_glb.PREPARER_VERSION}",
)
#: The code every count bound is refused with, whichever bound it is.
_QUOTA: Final = "workspace_asset_quota_exceeded"


def admission_operation(spent: str | None) -> Operation:
    """Admitting an asset: available until a count bound is met (``workspace_asset_spent``)."""
    return Operation(
        endpoint=admit_workspace_asset,
        availability=AVAILABLE if spent is None else unavailable(_QUOTA),
        subject="workspace",
        # The same declaration over the same bytes answers with the asset it first admitted.
        idempotency="declaration",
        options=(list_workspace_assets,),
        effects=(_PREPARATION,),
    )


def asset_operations(
    asset_id: uuid.UUID, preparation: PreparationRecord | None, present: bool, spent: str | None
) -> tuple[Operation, ...]:
    """One asset's preparation, cancellation and withdrawal, as their write paths decide them."""
    bind = {"asset_id": str(asset_id)}
    subjects = Subjects(list_workspace_assets, "assets")
    if preparation is not None and cancelled_by_removal(
        preparation.state, preparation.failure_class
    ):
        request = unavailable("withdrawn")
    elif spent is not None and (
        preparation is None
        or queues_a_run(preparation.state, preparation.failure_class, lambda: present)
    ):
        request = unavailable(_QUOTA)
    else:
        request = AVAILABLE
    cancel = "preparation_not_ready" if preparation is None else cancel_refusal(preparation.state)
    return (
        Operation(
            endpoint=request_workspace_preparation,
            availability=request,
            subject="workspace_asset",
            bind=bind,
            subjects=subjects,
            effects=(_PREPARATION,),
            needs=("preparation",),
        ),
        Operation(
            endpoint=cancel_workspace_preparation,
            availability=AVAILABLE if cancel is None else unavailable(cancel),
            subject="workspace_asset",
            bind=bind,
            subjects=subjects,
        ),
        Operation(
            endpoint=withdraw_workspace_asset,
            availability=AVAILABLE,
            subject="workspace_asset",
            bind=bind,
            subjects=subjects,
        ),
    )


def _described(
    request: Request,
    held: frozenset[Permission],
    operations: tuple[Operation, ...],
    facts: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    routes = surface(request.app)
    return [describe(operation, routes, held, facts) for operation in operations]


# -- routes --------------------------------------------------------------------------------------


@router.post("", status_code=201)
def admit_workspace_asset(
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    declaration: Annotated[str, Form(max_length=MAX_DECLARATION_BYTES)],
    content: Annotated[UploadFile, File()],
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        data = content.file.read(MAX_ASSET_BYTES + 1)
        if len(data) > MAX_ASSET_BYTES:
            raise AssetTooLarge(f"a workspace asset is at most {MAX_ASSET_BYTES} bytes")
        result = repository.admit(declaration.encode("utf-8"), data)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    present = _present(repository, result.preparation)
    return _json(
        _asset_view(result.asset, result.preparation, present),
        status=201 if result.created else 200,
    )


@router.get("")
def list_workspace_assets(
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        requests_spent = repository.spent(admission=False)
        facts = installation_facts_of(get_services(request))
        views = []
        for asset, preparation in repository.assets():
            present = _present(repository, preparation)
            view = _asset_view(asset, preparation, present)
            view["capabilities"] = _described(
                request,
                held,
                asset_operations(asset.asset_id, preparation, present, requests_spent),
                facts,
            )
            views.append(view)
        admission = admission_operation(repository.spent(admission=True))
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return _json(
        {
            "profile": LIST_PROFILE,
            "assets": views,
            "admission": _limits(connection),
            "capabilities": _described(request, held, (admission,), facts),
        }
    )


@router.get("/{asset_id}")
def read_workspace_asset(
    asset_id: uuid.UUID,
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        asset, preparation = repository.asset(asset_id)
        present = _present(repository, preparation)
        operations = asset_operations(
            asset.asset_id, preparation, present, repository.spent(admission=False)
        )
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    view = _asset_view(asset, preparation, present)
    view["capabilities"] = _described(
        request, held, operations, installation_facts_of(get_services(request))
    )
    return _json(view)


@router.post("/{asset_id}/preparation")
def request_workspace_preparation(
    asset_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        preparation = repository.request_preparation(asset_id)
        asset, _ = repository.asset(asset_id)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    present = _present(repository, preparation)
    return _json(
        _asset_view(asset, preparation, present),
        # Accepted only when a run is now waiting or running; a prepared output and a failure a
        # second run cannot change are answered as they are.
        status=202 if preparation.state in ("requested", "running") else 200,
    )


@router.post("/{asset_id}/preparation/cancel")
def cancel_workspace_preparation(
    asset_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        repository = _repository(request, connection, session)
        preparation = repository.cancel_preparation(asset_id)
        asset, _ = repository.asset(asset_id)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return _json(_asset_view(asset, preparation, _present(repository, preparation)))


@router.post("/{asset_id}/withdraw")
def withdraw_workspace_asset(
    asset_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> JSONResponse:
    try:
        _repository(request, connection, session).withdraw(asset_id)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return _json({"asset_id": str(asset_id), "withdrawn": True})


@router.get(
    "/{asset_id}/prepared/bytes",
    responses={200: {"content": {static_glb.MEDIA_TYPE: {}}}},
)
def read_workspace_asset_prepared_bytes(
    asset_id: uuid.UUID, request: Request, connection: ScopedConnection, session: CurrentSession
) -> Response:
    try:
        authorized = _repository(request, connection, session).read_prepared(asset_id)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return Response(
        content=authorized.data,
        media_type=authorized.media_type,
        headers={
            **_PRIVATE,
            "ETag": f'"{authorized.content_sha256}"',
            "Accept-Ranges": "none",
            "X-Exulanica-Asset-Id": str(authorized.asset_id),
            "X-Exulanica-Licence": authorized.licence_id or "own-work",
        },
    )
