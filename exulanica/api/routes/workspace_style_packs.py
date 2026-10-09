"""A workspace's own style packs, over HTTP: upload, read, serve and withdraw.

Routes validate and delegate: what is admitted is :mod:`exulanica.world.style_pack_admission`,
what is kept is :mod:`exulanica.world.workspace_style_packs` and migration 0173, and the check that
reads each piece's colours is :mod:`exulanica.world.style_pack_checks`, off-request.
``docs/style-pack-contract.md`` section 11 states every answer.

*   ``POST /workspace-style-packs`` takes one multipart upload: a ``declaration`` field, a
    ``manifest`` field holding the manifest's canonical bytes, and one file part per path the
    manifest lists, named by that path. The route declares no form parameter and reads its own body,
    so the caller is authenticated, holds the upload permission and its workspace's upload share,
    and has had the attempt counted, before a byte of it is read; it holds no database connection
    while the body arrives. Anything but ``multipart/form-data`` is 415 before the parser runs; a
    body the parser refuses is 422 ``invalid_style_pack_body``. It answers 201 with the version, or
    200 with the one the same declaration over the same manifest already made.
*   ``GET /workspace-style-packs`` lists the workspace's versions and their checks.
*   ``GET /workspace-style-packs/{manifest_sha256}`` is one version: its state, its check's
    failure, and its manifest once ready.
*   ``GET .../{manifest_sha256}/files/{content_sha256}`` serves one file of a ready version, or of a
    workspace version in its base chain, after the 0041 final check, from a file of the request's
    own, holding no connection while it sends.
*   ``POST .../{manifest_sha256}/withdraw`` ends the version for good; 409 while a live version is
    drawn on it.

Every answer carries the workspace-content headers (:data:`CONTENT_HEADERS`), refusals included:
a creator's bytes are never sniffed, framed, cached or read by another origin. A version that never
existed here and another workspace's answer the same 404; a withdrawn one is 410. A deployment whose
role may not append these tables answers every write 403.
"""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Annotated, Any, Final, Literal

import psycopg
from fastapi import APIRouter, Path, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from python_multipart.exceptions import ParseError
from python_multipart.multipart import parse_options_header
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.formparsers import MultiPartException

from exulanica.api.dependencies import CurrentSession, ScopedSessions, get_services
from exulanica.selection.validation import Session
from exulanica.world import style_packs
from exulanica.world.committed_content import DIGEST
from exulanica.world.style_pack_admission import (
    MAX_DECLARATION_BYTES,
    MAX_MANIFEST_BYTES,
    StylePackAdmissionRefused,
    admit,
)
from exulanica.world.style_pack_library import style_pack_library
from exulanica.world.workspace_preparations import PreparationError, WorkspaceAssetBusy
from exulanica.world.workspace_style_packs import (
    AuthorizedPackFile,
    StylePackAttemptsExceeded,
    StylePackExists,
    StylePackGeneratedNotOffered,
    StylePackIsABase,
    StylePackNotCreator,
    StylePackNotReady,
    StylePackPublishLicenceNotHeld,
    StylePackQuotaExceeded,
    StylePackVersionExists,
    StylePackVersionRecord,
    StylePackWithdrawn,
    UnknownStylePack,
    WorkspaceStylePackError,
    WorkspaceStylePackRepository,
    WorkspaceStylePackRuntime,
    WorkspaceStylePacksReadOnly,
)

__all__ = ["BODY_LIMITS", "CONTENT_HEADERS", "UPLOADS_SETTING", "router"]

#: The setting that turns style pack uploads on for an installation: ``on``, or off when absent.
UPLOADS_SETTING: Final = "EXULANICA_WORKSPACE_STYLE_PACK_UPLOADS"

router = APIRouter(prefix="/workspace-style-packs", tags=["workspace-style-packs"])

VERSION_PROFILE: Final = "exulanica.workspace-style-pack/v1"
LIST_PROFILE: Final = "exulanica.workspace-style-pack-list/v1"
#: Every answer about a workspace's own content, refusals included: never sniffed into another
#: type, never framed or run as a page, never kept by a cache, never read by another origin.
CONTENT_HEADERS: Final[Mapping[str, str]] = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; sandbox",
    "Content-Disposition": "attachment",
    "Cache-Control": "private, no-store",
    "Cross-Origin-Resource-Policy": "same-origin",
}
#: At most this many files, as the manifest's own bound.
MAX_FILE_PARTS: Final = style_packs.MAX_FILES
#: The most an upload's body may hold: every file, the manifest and the declaration at their
#: bounds, and the multipart framing around them. Refused before any of it is read.
UPLOAD_BODY_MAXIMUM: Final = (
    style_packs.MAX_TOTAL_BYTES + MAX_MANIFEST_BYTES + MAX_DECLARATION_BYTES + 1024 * 1024
)
BODY_LIMITS: Final = (("POST", "/workspace-style-packs", UPLOAD_BODY_MAXIMUM),)
_UPLOAD_FORM: Final[dict[str, Any]] = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["declaration", "manifest"],
                    "properties": {
                        "declaration": {"type": "string", "maxLength": MAX_DECLARATION_BYTES},
                        "manifest": {"type": "string", "maxLength": MAX_MANIFEST_BYTES},
                    },
                    "additionalProperties": {
                        "type": "string",
                        "contentMediaType": "application/octet-stream",
                    },
                }
            }
        },
    }
}
_DIGEST_PATH = Annotated[str, Path(pattern=f"^{DIGEST.pattern}$")]


class _Unavailable(Exception):
    """This instance was started without style pack namespaces."""


def _runtime(request: Request) -> WorkspaceStylePackRuntime:
    runtime = getattr(get_services(request), "workspace_style_packs", None)
    if runtime is None:
        raise _Unavailable
    return runtime


def _repository(
    request: Request, connection: psycopg.Connection, session: Session
) -> WorkspaceStylePackRepository:
    runtime = _runtime(request)
    return WorkspaceStylePackRepository(
        connection,
        session.workspace_id,
        session.actor,
        stores=runtime.stores,
        retained_bytes_limit=runtime.retained_bytes_limit,
        installation_bytes_limit=runtime.installation_bytes_limit,
        generated_pieces=runtime.generated_pieces,
    )


def _problem(status: int, code: str, detail: str, **extra: Any) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={**extra, "code": code, "detail": detail},
        headers=dict(CONTENT_HEADERS),
    )


def _refused(error: Exception) -> JSONResponse:
    if isinstance(error, _Unavailable):
        return _problem(503, "style_packs_unavailable", "this instance keeps no style pack store")
    if isinstance(error, StylePackAdmissionRefused):
        extra = {} if error.path is None else {"path": error.path}
        return _problem(422, error.code, error.detail, **extra)
    if isinstance(error, StylePackAttemptsExceeded):
        return _problem(429, "style_pack_quota_exceeded", str(error), bound=error.bound)
    if isinstance(error, StylePackQuotaExceeded):
        return _problem(429, "style_pack_quota_exceeded", str(error))
    if isinstance(error, StylePackVersionExists):
        return _problem(
            409, "style_pack_version_exists", str(error), held=error.held_manifest_sha256
        )
    if isinstance(error, StylePackExists):
        return _problem(409, "style_pack_exists", str(error))
    if isinstance(error, StylePackNotCreator):
        return _problem(403, "style_pack_not_creator", str(error))
    if isinstance(error, StylePackPublishLicenceNotHeld):
        return _problem(422, "publish_licence_not_held", str(error))
    if isinstance(error, StylePackGeneratedNotOffered):
        return _problem(422, "publish_generated_look", str(error))
    if isinstance(error, StylePackIsABase):
        return _problem(409, "style_pack_is_a_base", str(error))
    if isinstance(error, UnknownStylePack):
        return _problem(404, "unknown_reference", "no such style pack version")
    if isinstance(error, StylePackWithdrawn):
        return _problem(410, "withdrawn", "this style pack was withdrawn or its workspace erased")
    if isinstance(error, StylePackNotReady):
        return _problem(409, "style_pack_not_ready", str(error))
    if isinstance(error, WorkspaceStylePacksReadOnly):
        return _problem(
            403, "workspace_style_packs_read_only", "this deployment keeps style packs read-only"
        )
    if isinstance(error, WorkspaceAssetBusy):
        response = _problem(503, "retry", "a delivery or a deletion was in progress; ask again")
        response.headers["Retry-After"] = "1"
        return response
    raise error


def _view(record: StylePackVersionRecord, *, manifest: bool) -> dict[str, Any]:
    document: dict[str, Any] = {
        "profile": VERSION_PROFILE,
        "manifest_sha256": record.manifest_sha256,
        "pack_id": record.pack_id,
        "version": record.version,
        "state": record.state,
        "withdrawn": record.withdrawn,
        "ready": record.ready,
        "failure": (
            None
            if record.failure_class is None
            else {"class": record.failure_class, "message": record.failure_message}
        ),
        "rights_basis": record.rights_basis,
        "licence_id": record.licence_id,
        "base": (
            None
            if record.base is None
            else {
                "source": record.base.source,
                "pack_id": record.base.pack_id,
                "version": record.base.version,
                "manifest_sha256": record.base.manifest_sha256,
            }
        ),
        "file_count": record.file_count,
        "file_bytes": record.file_byte_size,
        "preview_sha256": record.preview_sha256,
        "created_at": record.created_at.isoformat(),
    }
    if manifest:
        document["manifest"] = (
            json.loads(record.manifest_canonical)
            if record.ready and record.manifest_canonical is not None
            else None
        )
    return document


def _base_resolver(repository: WorkspaceStylePackRepository) -> Callable[[Mapping[str, Any]], str]:
    library = style_pack_library()

    def resolve(base: Mapping[str, Any]) -> str:
        pack_id, version, digest = base["pack_id"], base["version"], base["manifest_sha256"]
        if library.holds(pack_id, version, digest):
            return "library"
        if not pack_id.startswith("exulanica."):
            try:
                held = repository.version(digest)
            except UnknownStylePack:
                held = None
            if (
                held is not None
                and (held.pack_id, held.version) == (pack_id, version)
                and repository.wearable(digest)
            ):
                return "workspace"
        raise StylePackAdmissionRefused(
            "style_pack_base_unavailable",
            "a pack is drawn on a library version or on one of this workspace's own that may be "
            "worn now, named by its id, version and digest",
            path="base",
        )

    return resolve


# -- routes --------------------------------------------------------------------------------------


@router.post("", status_code=201, openapi_extra=_UPLOAD_FORM)
async def admit_workspace_style_pack(
    request: Request, session: CurrentSession, sessions: ScopedSessions
) -> JSONResponse:
    # Off unless the installation turns uploads on (UPLOADS_SETTING), its switch for every pack
    # upload. A browser session reached here only with its account's creator grant (the floor).
    try:
        if not _runtime(request).uploads:
            return _problem(
                503,
                "style_pack_uploads_off",
                f"this installation takes no style pack uploads; {UPLOADS_SETTING} turns them on",
            )
    except _Unavailable as error:
        return _refused(error)
    # The attempt is counted before the body is read, on a connection of its own.
    try:
        await run_in_threadpool(_count_attempt, request, session, sessions)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    content_type, options = parse_options_header(request.headers.get("content-type", ""))
    if content_type != b"multipart/form-data" or not options.get(b"boundary"):
        return _problem(415, "unsupported_media_type", "an upload is one multipart/form-data body")
    try:
        form = await request.form(
            max_files=MAX_FILE_PARTS, max_fields=2, max_part_size=MAX_MANIFEST_BYTES
        )
    except (MultiPartException, ParseError):
        return _problem(422, "invalid_style_pack_body", "the multipart body is refused")
    except HTTPException as error:
        # Inside an app, Starlette answers its own parser's limits with a 400; any other answer
        # passes on as it is.
        if error.status_code != 400:
            raise
        return _problem(422, "invalid_style_pack_body", "the multipart body is refused")
    try:
        items = form.multi_items()
        names = [name for name, _ in items]
        declaration = form.get("declaration")
        manifest = form.get("manifest")
        if (
            len(set(names)) != len(names)
            or not isinstance(declaration, str)
            or not isinstance(manifest, str)
        ):
            return _problem(
                422,
                "invalid_style_pack_body",
                "a body is one declaration field, one manifest field and one file per path",
            )
        files = {name: value for name, value in items if name not in ("declaration", "manifest")}
        if not all(isinstance(value, UploadFile) for value in files.values()):
            return _problem(
                422, "invalid_style_pack_body", "every part but the two fields is a file"
            )
        return await run_in_threadpool(
            _admit,
            request,
            session,
            sessions,
            declaration.encode("utf-8"),
            manifest.encode("utf-8"),
            files,  # type: ignore[arg-type]
        )
    finally:
        await form.close()


def _count_attempt(
    request: Request,
    session: Session,
    sessions: Callable[[], AbstractContextManager[psycopg.Connection]],
) -> None:
    runtime = _runtime(request)
    with sessions() as connection:
        _repository(request, connection, session).count_attempt(
            workspace_limit=runtime.workspace_day_attempts,
            installation_limit=runtime.installation_day_attempts,
        )


def _admit(
    request: Request,
    session: Session,
    sessions: Callable[[], AbstractContextManager[psycopg.Connection]],
    declaration: bytes,
    manifest: bytes,
    files: Mapping[str, UploadFile],
) -> JSONResponse:
    contents = {
        name: upload.file.read(style_packs.MAX_TOTAL_BYTES + 1) for name, upload in files.items()
    }
    with sessions() as connection:
        try:
            runtime = _runtime(request)
            repository = _repository(request, connection, session)
            admitted = admit(
                declaration,
                manifest,
                contents,
                context=runtime.context,
                budgets=runtime.budgets.families,
                lod1_share_permille=runtime.budgets.lod1_share_permille,
                resolve_base=_base_resolver(repository),
            )
            record, created = repository.record(admitted)
        except (PreparationError, _Unavailable) as error:
            return _refused(error)
    return JSONResponse(
        status_code=201 if created else 200,
        content=_view(record, manifest=False),
        headers=dict(CONTENT_HEADERS),
    )


@router.get("", summary="This workspace's own style pack versions and their checks.")
def list_workspace_style_packs(
    request: Request, sessions: ScopedSessions, session: CurrentSession
) -> JSONResponse:
    try:
        with sessions() as connection:
            records = _repository(request, connection, session).versions()
    except (WorkspaceStylePackError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(
        content={
            "profile": LIST_PROFILE,
            "versions": [_view(record, manifest=False) for record in records],
        },
        headers=dict(CONTENT_HEADERS),
    )


@router.get("/{manifest_sha256}", summary="One version of a workspace style pack, and its check.")
def read_workspace_style_pack(
    manifest_sha256: _DIGEST_PATH,
    request: Request,
    sessions: ScopedSessions,
    session: CurrentSession,
) -> JSONResponse:
    try:
        with sessions() as connection:
            record = _repository(request, connection, session).version(manifest_sha256)
    except (WorkspaceStylePackError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(content=_view(record, manifest=True), headers=dict(CONTENT_HEADERS))


class _PackFileResponse(StreamingResponse):
    """A checked file's bytes, streamed from the delivery's own file, closed when it ends."""

    def __init__(self, output: AuthorizedPackFile) -> None:
        self._output = output
        super().__init__(
            output.chunks(),
            media_type=output.media_type,
            headers={**CONTENT_HEADERS, "Content-Length": str(output.byte_size)},
        )

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._output.close()


@router.get(
    "/{manifest_sha256}/files/{content_sha256}",
    summary="One file of a ready workspace style pack version, after the final read check.",
    responses={200: {"content": {"model/gltf-binary": {}, "image/png": {}}}},
)
def read_workspace_style_pack_file(
    manifest_sha256: _DIGEST_PATH,
    content_sha256: _DIGEST_PATH,
    request: Request,
    sessions: ScopedSessions,
    session: CurrentSession,
) -> Response:
    # Authorized on a connection of its own, closed before the first byte is sent.
    try:
        with sessions() as connection:
            output = _repository(request, connection, session).read_file(
                manifest_sha256, content_sha256
            )
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return _PackFileResponse(output)


@router.post(
    "/{manifest_sha256}/withdraw",
    summary="Withdraw a version of a workspace style pack for good.",
)
def withdraw_workspace_style_pack(
    manifest_sha256: _DIGEST_PATH,
    request: Request,
    sessions: ScopedSessions,
    session: CurrentSession,
) -> JSONResponse:
    try:
        with sessions() as connection:
            repository = _repository(request, connection, session)
            withdrew = repository.withdraw(manifest_sha256)
            record = repository.version(manifest_sha256)
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(
        content={**_view(record, manifest=False), "withdrew": withdrew},
        headers=dict(CONTENT_HEADERS),
    )


#: Archives one process builds at once.
ARCHIVES_PER_PROCESS: Final = 2


class ArchiveSlots:
    """How many archives one process builds at once, and one workspace at once (one).

    Each archive in flight holds up to one pack's bytes on the request's temporary disk until its
    response ends, so the process bounds them itself: past ``limit`` the answer is 503
    ``capacity_exhausted`` and past a workspace's one 429 ``workspace_capacity_exhausted``, each
    with ``capacity`` ``archives``, before anything is read. The deployment's disk term is
    ``limit`` times 64 MiB (``docs/deployment.md`` section 5.4).
    """

    def __init__(self, limit: int = ARCHIVES_PER_PROCESS) -> None:
        self.limit = limit
        self._lock = threading.Lock()
        self._held: dict[uuid.UUID, int] = {}

    def take(self, workspace_id: uuid.UUID) -> str | None:
        """None when a slot was taken, else the refusal's code."""
        with self._lock:
            if self._held.get(workspace_id):
                return "workspace_capacity_exhausted"
            if sum(self._held.values()) >= self.limit:
                return "capacity_exhausted"
            self._held[workspace_id] = 1
            return None

    def give_back(self, workspace_id: uuid.UUID) -> None:
        with self._lock:
            self._held.pop(workspace_id, None)


_ARCHIVES: Final = ArchiveSlots()


class _ArchiveResponse(_PackFileResponse):
    """An archive's bytes, and its slot given back when the response ends however it ends."""

    def __init__(self, output: AuthorizedPackFile, release: Callable[[], None]) -> None:
        self._release = release
        super().__init__(output)
        self.headers["Content-Disposition"] = "attachment; filename=style-pack.tar"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


@router.get(
    "/{manifest_sha256}/archive",
    summary="A ready workspace style pack version as one uncompressed tar archive.",
    responses={200: {"content": {"application/x-tar": {}}}},
)
def read_workspace_style_pack_archive(
    manifest_sha256: _DIGEST_PATH,
    request: Request,
    sessions: ScopedSessions,
    session: CurrentSession,
) -> Response:
    refusal = _ARCHIVES.take(session.workspace_id)
    if refusal is not None:
        response = _problem(
            503 if refusal == "capacity_exhausted" else 429,
            refusal,
            "archives are being built; ask again shortly",
            capacity="archives",
            retry_after_seconds=10,
        )
        response.headers["Retry-After"] = "10"
        return response
    try:
        with sessions() as connection:
            output = _repository(request, connection, session).write_archive(manifest_sha256)
    except (PreparationError, _Unavailable) as error:
        _ARCHIVES.give_back(session.workspace_id)
        return _refused(error)
    except BaseException:
        _ARCHIVES.give_back(session.workspace_id)
        raise
    return _ArchiveResponse(output, lambda: _ARCHIVES.give_back(session.workspace_id))


class PublishRequest(BaseModel):
    """What a creator grants the project for a version to join the shared library."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    licence_id: Literal["CC0-1.0", "CC-BY-4.0"]
    attribution: Annotated[str, Field(min_length=1, max_length=400)] | None = None
    statement: Annotated[str, Field(min_length=1, max_length=2000)]


@router.post(
    "/{manifest_sha256}/publish-request",
    status_code=201,
    summary="Ask for a ready version of your own style pack to join the shared library.",
)
def request_workspace_style_pack_publication(
    manifest_sha256: _DIGEST_PATH,
    body: PublishRequest,
    request: Request,
    sessions: ScopedSessions,
    session: CurrentSession,
) -> JSONResponse:
    for text in (body.attribution, body.statement):
        if text is not None and not style_packs.is_plain_text(text, 2000):
            return _problem(422, "invalid_publish_request", "trimmed plain text")
    if (body.licence_id == "CC-BY-4.0") != (body.attribution is not None):
        return _problem(
            422, "invalid_publish_request", "CC-BY-4.0 states its attribution and CC0-1.0 none"
        )
    try:
        with sessions() as connection:
            request_id = _repository(request, connection, session).request_publish(
                manifest_sha256,
                licence_id=body.licence_id,
                attribution=body.attribution,
                statement=body.statement,
            )
    except (PreparationError, _Unavailable) as error:
        return _refused(error)
    return JSONResponse(
        status_code=201,
        content={"request_id": str(request_id), "manifest_sha256": manifest_sha256},
        headers=dict(CONTENT_HEADERS),
    )


def workspace_listing(
    request: Request, connection: psycopg.Connection, session: Session
) -> list[dict[str, Any]]:
    """This workspace's ready versions, for ``GET /world/style-packs``, each with ``source``."""
    try:
        repository = _repository(request, connection, session)
    except _Unavailable:
        return []
    # Wearable, not only ready: a version is worn only while its whole base chain may be.
    return [
        {**_view(record, manifest=False), "source": "workspace"}
        for record in repository.versions()
        if record.ready and repository.wearable(record.manifest_sha256)
    ]
