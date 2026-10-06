"""World kinds: the kinds of world a person can make worlds of, and a site world's drawing.

``GET /worlds/kinds`` is the library a person, a model choosing for them and an API client read:
the town (an adapter over the world specification's presets and values), every kind the product
ships, and the workspace's own kinds, each with its parameters, presets and parts in plain words.
``POST /worlds/kinds`` keeps a creator's kind in the workspace once both stages of its checks pass
(:mod:`exulanica.world.kinds.document`, :mod:`exulanica.world.kinds.samples`); a refusal names its
code, where in the document and why, and nothing is written. ``POST /worlds/kinds/{kind}/worlds``
makes a world of a kind with a preset and values held to the kind's parameters, as
``POST /worlds/generated`` makes a town: the town's own path for the town, the site grammar for
every other kind.

A site world is not baked: its page reads ``GET /world/versions/{version_id}/site``, the drawing
its records make (:func:`~exulanica.world.site_drawing.site_drawing`), served only to the world
whose snapshot names its receipt and named by its digest.

Nothing here generates a site on the request's thread. A kind's sample checks, a world's making
and a drawing's records all run in the kind worker (:mod:`exulanica.world.kinds.worker`), bounded
per job, per workspace and in all; work the worker does not finish in time, or cannot take, is
answered 503 ``kind_work_overran``, ``kind_work_busy`` or ``kind_work_unavailable`` with a
``Retry-After``, and finished checks and drawings are kept, so asking again reads them. The upload's
body is bounded before it is read (:data:`BODY_LIMITS`).
"""

from __future__ import annotations

import json
import math
import uuid
from collections.abc import Mapping
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import (
    CurrentSession,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
)
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
from exulanica.api.services import Services
from exulanica.api.world_scope import WorldId
from exulanica.world.composers import ComposedWorld, GeneratedWorldRefused, UnknownWorldComposer
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import generation_receipt, states_site
from exulanica.world.kinds.document import (
    KIND_CODES,
    KindDocument,
    KindRefused,
    KindValueRefused,
    read_kind,
)
from exulanica.world.kinds.library import shipped_kinds, town_adapter
from exulanica.world.kinds.repository import (
    KindCapReached,
    KindUnreadable,
    KindVersionExists,
    WorkspaceKinds,
)
from exulanica.world.kinds.samples import SiteRefused
from exulanica.world.kinds.worker import (
    CHECK_SECONDS,
    COMPOSE_SECONDS,
    DRAWING_SECONDS,
    JobOutcome,
    KindWorkWaiting,
    check_job,
    compose_job,
    drawing_job,
    kind_worker,
)
from exulanica.world.saved_entries import InvalidSavedWorldTitle, SavedWorldEntryRepository
from exulanica.world.world_recipes import (
    SpecificationRefused,
    UnknownWorldRecipe,
    specification_document,
)
from exulanica.world.worlds import (
    WorldLimitReached,
    WorldsReadOnly,
    require_world,
    require_world_registration,
)

__all__ = ["BODY_LIMITS", "router", "site_router"]

router = APIRouter(prefix="/worlds/kinds", tags=["world"])
site_router = APIRouter(prefix="/world", tags=["world"])

LIBRARY_PROFILE = "exulanica.world-kinds/v1"
#: The largest kind document a creator may upload: a kind of 48 parts and 12 zones in plain words
#: is a few tens of kilobytes (the fixture farm is under 9 KB), so 64 KB bounds a request without
#: refusing any kind the bounds catalog admits.
UPLOAD_BYTES_MAXIMUM = 65_536
#: The body a kind's upload may carry: the document's bound and its envelope of
#: ``{"document": ...}`` with room for whitespace.
UPLOAD_BODY_MAXIMUM = 2 * UPLOAD_BYTES_MAXIMUM
#: The body asking for a world of a kind may carry: a preset, a title of 200 characters and 64
#: values, a few kilobytes as JSON; 16 KB holds them with room.
CREATE_BODY_MAXIMUM = 16_384
#: The bodies these routes accept, refused before any of them is read (:mod:`exulanica.api.
#: body_limit`): the server-wide limit is sized for photographs, and a kind is a small document.
BODY_LIMITS: Final = (
    ("POST", "/worlds/kinds", UPLOAD_BODY_MAXIMUM),
    ("POST", "/worlds/kinds/{kind}/worlds", CREATE_BODY_MAXIMUM),
)
#: What an uploaded kind's provenance says, in place of anything the document carried.
UPLOADED_BY: Final = "an upload to its workspace"
_HEADERS = {"Cache-Control": "private, no-cache", "X-Content-Type-Options": "nosniff"}


class KindParameterView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    #: A number's range, or none for a value chosen among keys.
    minimum: int | None
    maximum: int | None
    step: int | None
    #: A key's choices, or none for a number.
    choices: list[str] | None
    reason: str


class KindPresetView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    values: dict[str, int | str]


class KindPartView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    description: str
    form: str
    roles: list[str]
    #: The look role a style pack dresses: ``family.leaf``.
    look: str


class KindZoneView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str


class KindView(BaseModel):
    """One kind of world a person can make, in words: what it holds, what a person may change."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    version: int
    sha256: str
    #: ``shipped`` for a kind the product ships, ``workspace`` for one kept in this workspace.
    source: Literal["shipped", "workspace"]
    label: str
    summary: str
    origin: str
    generator: dict[str, str | int]
    parameters: list[KindParameterView]
    presets: list[KindPresetView]
    parts: list[KindPartView]
    zones: list[KindZoneView]


class KindRefusalView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    meaning: str


class KindLibraryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["exulanica.world-kinds/v1"]
    kinds: list[KindView]
    refusals: list[KindRefusalView]


class UploadKindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A world kind document (``exulanica.world-kind/v1``) whose origin is ``uploaded``.
    document: dict[str, Any]


class UploadedKindView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: KindView
    #: The report its sample worlds passed (``exulanica.world-kind-validation/v1``).
    validation: dict[str, Any]


class CreateKindWorldBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: A version of the kind; the latest the library holds when none is named.
    version: Annotated[int, Field(ge=1, le=9999)] | None = None
    preset: Annotated[str, Field(min_length=1, max_length=100)]
    title: Annotated[str, Field(min_length=1, max_length=200)]
    #: Values for any of the kind's parameters, each held to its range by the kind's gate, which
    #: refuses by name, so they are taken as the JSON sent.
    values: Annotated[dict[str, Any] | None, Field(max_length=64)] = None


def _echo(value: object) -> object:
    """A refused value said back only as JSON can say it: text, a whole or finite number, or its
    words (a NaN or an infinity a client sent is answered, never a 500)."""
    if value is None or isinstance(value, (bool, str, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    return repr(value)[:200]


def _problem(
    status: int, code: str, detail: str, *, headers: dict[str, str] | None = None, **extra: Any
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=sayable({"code": code, "detail": detail, **extra}),
        headers=headers,
    )


def _waiting(outcome: JobOutcome, *, kept: bool) -> JSONResponse:
    """A job the kind worker did not answer: 503 with its code, its words and when to ask again."""
    waiting = KindWorkWaiting(outcome.status, kept=kept, reason=outcome.reason)
    return _problem(
        503, waiting.code, str(waiting), headers={"Retry-After": str(waiting.retry_seconds)}
    )


def _kind_view(kind: KindDocument, source: Literal["shipped", "workspace"]) -> KindView:
    return KindView(
        kind=kind.kind,
        version=kind.version,
        sha256=kind.sha256,
        source=source,
        label=kind.label,
        summary=kind.summary,
        origin=kind.origin,
        generator={"key": "site-plan", "version": 1},
        parameters=[
            KindParameterView(
                key=p.key,
                label=p.label,
                minimum=p.minimum,
                maximum=p.maximum,
                step=p.step,
                choices=None,
                reason=p.reason,
            )
            for p in kind.parameters
        ],
        presets=[
            KindPresetView(key=key, label=label, values=dict(values))
            for key, label, values in kind.presets
        ],
        parts=[
            KindPartView(
                key=part.key,
                label=part.label,
                description=part.description,
                form=part.form,
                roles=list(part.roles),
                look=part.look.role,
            )
            for part in kind.parts.values()
        ],
        zones=[KindZoneView(key=zone.key, label=zone.label) for zone in kind.zones],
    )


def _town_view() -> KindView:
    """The town in the library's words: its adapter's parts, and the specification's adjustable
    values and presets as the specification itself serves them."""
    town = town_adapter()
    served = specification_document()
    parameters = []
    for value in served["values"]:
        if not value["adjustable"]:
            continue
        choice = value["kind"] == "choice"
        parameters.append(
            KindParameterView(
                key=value["key"],
                label=value["label"],
                minimum=None if choice else value["minimum"],
                maximum=None if choice else value["maximum"],
                step=None if choice else value["step"],
                choices=list(value["choices"]) if choice else None,
                reason=value["reason"],
            )
        )
    document = town.document
    return KindView(
        kind=town.kind,
        version=town.version,
        sha256=town.sha256,
        source="shipped",
        label=str(document["label"]),
        summary=str(document["summary"]),
        origin=str(document["origin"]),
        generator=dict(document["generator"]),
        parameters=parameters,
        presets=[
            KindPresetView(key=preset["key"], label=preset["label"], values=dict(preset["values"]))
            for preset in served["presets"]
        ],
        parts=[KindPartView(**part) for part in document["parts"]],
        zones=[],
    )


@router.get("", summary="The kinds of world a person can make worlds of.")
def library(connection: ReadOnlyConnection, session: CurrentSession) -> KindLibraryView:
    """The town, the shipped kinds and the workspace's own kinds, each in plain words."""
    kinds = [_town_view()]
    kinds.extend(_kind_view(kind, "shipped") for kind in shipped_kinds())
    kinds.extend(
        _kind_view(stored.kind, "workspace")
        for stored in WorkspaceKinds(connection, session.workspace_id).every_latest()
    )
    return KindLibraryView(
        profile=LIBRARY_PROFILE,
        kinds=kinds,
        refusals=[KindRefusalView(code=code, meaning=meaning) for code, meaning in KIND_CODES],
    )


@router.post(
    "",
    response_model=UploadedKindView,
    status_code=201,
    summary="Keep a creator's world kind in this workspace once its checks pass.",
    responses={422: {"description": "Refused by name; nothing was written."}},
)
def upload_kind(
    body: UploadKindBody, connection: ScopedConnection, session: CurrentSession
) -> UploadedKindView | JSONResponse:
    """Read the kind, build its sample worlds and keep it when every one passes.

    A body over :data:`UPLOAD_BODY_MAXIMUM` is refused 413 before it is read; a document larger
    than :data:`UPLOAD_BYTES_MAXIMUM`, one whose origin is not ``uploaded``, and any refusal of
    either stage answer 422 with the refusal's code, where and why (stage B's with its report so
    far); a version or a document the workspace already holds, and a workspace already keeping as
    many kind versions as it may, answer 409, before any sample world is built. Stage B runs in the
    kind worker (:mod:`exulanica.world.kinds.worker`), never on the request's thread: checks the
    worker does not finish within its limit, or cannot take, answer 503 ``kind_work_overran``,
    ``kind_work_busy`` or ``kind_work_unavailable`` with a ``Retry-After``, and finished checks
    are kept, so sending the same kind again reads them.
    """
    if len(json.dumps(body.document)) > UPLOAD_BYTES_MAXIMUM:
        return _problem(
            422, "kind_document_invalid", f"a kind is at most {UPLOAD_BYTES_MAXIMUM} bytes"
        )
    # Who uploaded it is the row's own column (``created_by``), not words the document carries:
    # the document, and every receipt of a world made from it, names no person and no account.
    document = {**body.document, "provenance": {"by": UPLOADED_BY}}
    try:
        kind = read_kind(document)
        if kind.origin != "uploaded":
            raise KindRefused(
                "kind_document_invalid", "an uploaded kind's origin is uploaded", "origin"
            )
    except KindRefused as exc:
        return _problem(422, exc.code, exc.detail, where=exc.where)
    stored = WorkspaceKinds(connection, session.workspace_id)
    try:
        # Before the worker builds anything; the append asks again under the workspace's lock.
        stored.refuse_before_checks(kind)
    except (KindVersionExists, KindCapReached) as exc:
        return _problem(409, exc.code, str(exc))
    worker = kind_worker()
    # Kept by the workspace with the document: two workspaces sending one document are told nothing
    # of each other's checks.
    outcome = worker.run(
        f"check:{session.workspace_id}:{kind.sha256}",
        CHECK_SECONDS,
        check_job,
        dict(kind.document),
        workspace=str(session.workspace_id),
        kept=worker.checks,
    )
    if outcome.status != "done" or outcome.value is None:
        return _waiting(outcome, kept=True)
    answer = outcome.value
    if answer["status"] == "refused":
        extra: dict[str, Any] = {"where": answer["where"]}
        if answer["report"] is not None:
            extra["report"] = answer["report"]
        return _problem(422, answer["code"], answer["detail"], **extra)
    report = answer["report"]
    try:
        kept = stored.append(kind, report, created_by=session.actor)
    except (KindVersionExists, KindCapReached) as exc:
        return _problem(409, exc.code, str(exc))
    return UploadedKindView(kind=_kind_view(kept.kind, "workspace"), validation=dict(report))


class _WorkerComposer:
    """Composes one identity's world of a kind in the kind worker for one workspace, and keeps the
    drawing of the last world it made, which is the world saved when the making succeeds."""

    def __init__(self, workspace: uuid.UUID) -> None:
        self.workspace = str(workspace)
        self.drawn: tuple[str, dict[str, Any]] | None = None

    def __call__(
        self, kind: KindDocument, values: Mapping[str, int], world_id: str
    ) -> ComposedWorld:
        outcome = kind_worker().run(
            f"compose:{kind.sha256}:{world_id}:{json.dumps(dict(values), sort_keys=True)}",
            COMPOSE_SECONDS,
            compose_job,
            dict(kind.document),
            dict(values),
            world_id,
            workspace=self.workspace,
        )
        if outcome.status != "done" or outcome.value is None:
            raise KindWorkWaiting(outcome.status, kept=False, reason=outcome.reason)
        answer = outcome.value
        if answer["status"] == "refused":
            raise SiteRefused(answer["code"], answer["refusals"])
        composed: ComposedWorld = answer["composed"]
        self.drawn = (
            composed.receipt_sha256,
            {"status": "done", "body": answer["body"], "sha256": answer["sha256"]},
        )
        return composed


def _find_kind(
    connection: Any, workspace_id: uuid.UUID, key: str, version: int | None
) -> KindDocument | None:
    stored = WorkspaceKinds(connection, workspace_id)
    found = stored.version(key, version) if version is not None else stored.latest(key)
    if found is not None:
        return found.kind
    shipped = [kind for kind in shipped_kinds() if kind.kind == key]
    if version is not None:
        shipped = [kind for kind in shipped if kind.version == version]
    return max(shipped, key=lambda kind: kind.version) if shipped else None


@router.post(
    "/{kind}/worlds",
    response_model=SavedWorldEntryView,
    status_code=201,
    summary="Make a world of a kind and save it as yours.",
    responses={409: {"description": "Refused by name; nothing was written."}},
)
def create_kind_world(
    kind: str,
    body: CreateKindWorldBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> SavedWorldEntryView | JSONResponse:
    """Make a world of ``kind`` with a preset and values, for a new identity, and save its entry.

    The town is made as ``POST /worlds/generated`` makes it, from its preset through the same gate
    and composer, so it is the same world. Every other kind is made by the site grammar from the
    kind the workspace holds or the product ships (the latest version unless one is named). An
    unknown kind or preset answers 404; a value the kind does not offer 422, naming the key, the
    value and the range; a title empty once trimmed 422; a kind none of whose candidates makes a
    world people can live in, for any identity drawn, 409 with every refusal; a workspace already
    holding as many generated worlds as the count policy allows 409; a deployment whose database
    role cannot register a world 403 ``worlds_read_only``. Nothing is written when any is refused.
    """
    try:
        require_world_registration(connection)
    except WorldsReadOnly as exc:
        return _problem(403, exc.code, str(exc))
    entries = SavedWorldEntryRepository(connection, session.workspace_id, services.store)
    try:
        if kind == town_adapter().kind and body.version in (None, town_adapter().version):
            created = entries.create_generated(
                title=body.title,
                recipe_key=body.preset,
                created_by=session.actor,
                values=body.values,
            )
        else:
            found = _find_kind(connection, session.workspace_id, kind, body.version)
            if found is None:
                return _problem(404, "unknown_world_kind", f"no world kind is named {kind!r}")
            values = found.values(body.preset, body.values)
            composer = _WorkerComposer(session.workspace_id)
            created = entries.create_from_kind(
                title=body.title,
                kind=found,
                values=values,
                created_by=session.actor,
                compose=composer,
            )
            if composer.drawn is not None:
                # The page reads the new world's drawing next: it is kept, made with the world.
                worker = kind_worker()
                worker.drawings.put(f"drawing:{composer.drawn[0]}", composer.drawn[1])
    except UnknownWorldRecipe as exc:
        return _problem(404, exc.code, str(exc))
    except KindValueRefused as exc:
        status = 404 if exc.code == "unknown_world_recipe" else 422
        return _problem(status, exc.code, exc.detail, key=exc.key, value=_echo(exc.value))
    except KindUnreadable as exc:
        return _problem(409, exc.code, str(exc))
    except SpecificationRefused as exc:
        return JSONResponse(status_code=422, content=sayable(exc.document()))
    except InvalidSavedWorldTitle as exc:
        return _problem(422, "invalid_saved_world_entry", str(exc))
    except SiteRefused as exc:
        return _problem(409, exc.code, str(exc), refusals=list(exc.refusals))
    except KindWorkWaiting as exc:
        return _problem(503, exc.code, str(exc), headers={"Retry-After": str(exc.retry_seconds)})
    except (GeneratedWorldRefused, UnknownWorldComposer, WorldLimitReached) as exc:
        return _problem(409, exc.code, str(exc))
    return _view(created)


@site_router.get(
    "/versions/{version_id}/site",
    summary="A site world's drawing, for the world whose snapshot names its receipt.",
)
def read_site_drawing(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """The drawing a site world's records make, generated again from the receipt the version's own
    snapshot names, in the kind worker, and served with its digest as its entity tag. A drawing the
    worker does not finish in time, or cannot take, answers 503 ``kind_work_*`` with a
    ``Retry-After``; a finished one is kept, so asking again reads it."""
    require_world(connection, session.workspace_id, world_id)
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select source_snapshot_id from world_alternate_version where workspace_id=%s "
            "and world_id=%s and version_id=%s",
            (session.workspace_id, world_id, version_id),
        ).fetchone()
    if row is None:
        return _problem(404, "unknown_reference", "no such world version")
    snapshot_id = row["source_snapshot_id"]
    try:
        if not states_site(connection, session.workspace_id, world_id, snapshot_id):
            return _problem(404, "unknown_reference", "this world is not made from a world kind")
        digest, receipt = generation_receipt(
            connection, session.workspace_id, world_id, snapshot_id
        )
    except InvalidStructuralData as exc:
        return _problem(409, "generated_world_unreadable", str(exc))
    worker = kind_worker()
    outcome = worker.run(
        f"drawing:{digest}",
        DRAWING_SECONDS,
        drawing_job,
        world_id,
        dict(receipt),
        digest,
        workspace=str(session.workspace_id),
        kept=worker.drawings,
    )
    if outcome.status != "done" or outcome.value is None:
        return _waiting(outcome, kept=True)
    answer = outcome.value
    if answer["status"] == "refused":
        return _problem(409, "generated_world_unreadable", answer["detail"])
    return Response(
        content=answer["body"],
        media_type="application/json",
        headers={**_HEADERS, "ETag": f'"{answer["sha256"]}"'},
    )
