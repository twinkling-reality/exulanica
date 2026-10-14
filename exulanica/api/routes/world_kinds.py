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

``POST /worlds/kinds/drafts`` asks a model to draft a kind of world from a person's words and
answers at once with a draft the page polls at ``GET /worlds/kinds/drafts/{draft_id}``: the job
(:mod:`exulanica.api.kind_drafts`) drafts, checks and keeps the kind, and no route waits on it.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Final, Literal

import psycopg
from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ReadOnlyConnection,
    ScopedConnection,
    get_services,
    holds_as_guest,
    owns_workspace,
)
from exulanica.api.kind_drafts import (
    KIND_DRAFT_CODES,
    KINDS_FROM_PEOPLE_NOT_OFFERED,
    KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL,
    KindDraft,
    KindDraftCapacity,
    KindDrafts,
    allowance_refusal,
    draft_deadline_seconds,
)
from exulanica.api.permissions import Permission
from exulanica.api.routes.selection import ExecutionView, ModelNotConfigured, _execution
from exulanica.api.routes.world_entries import SavedWorldEntryView, _view
from exulanica.api.sayable import sayable
from exulanica.api.services import Services
from exulanica.api.world_draft_worker import manifest_sha256
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.selection.calls import AttemptOutcome, CallCost, ModelCall
from exulanica.selection.kind_drafting import kind_drafting_prompt
from exulanica.selection.world_drafting import sendable
from exulanica.world import draft_admission
from exulanica.world.composers import GeneratedWorldRefused, UnknownWorldComposer
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import generation_receipt, states_site
from exulanica.world.kind_draft_jobs import KindDraftRepository
from exulanica.world.kinds.document import (
    KIND_CODES,
    KindDocument,
    KindRefused,
    KindValueRefused,
    read_kind,
)
from exulanica.world.kinds.erasure import KindErasureRefused, erase_kind, removal_preview
from exulanica.world.kinds.library import shipped_kinds, town_adapter
from exulanica.world.kinds.repository import (
    KindCapReached,
    KindUnreadable,
    KindVersionExists,
    WorkspaceKinds,
    forget_kind,
)
from exulanica.world.kinds.samples import SiteRefused
from exulanica.world.kinds.worker import (
    CHECK_SECONDS,
    DRAWING_SECONDS,
    JobOutcome,
    KindWorkWaiting,
    WorkerComposer,
    check_job,
    check_key,
    drawing_job,
    drawing_key,
    kind_worker,
)
from exulanica.world.saved_entries import InvalidSavedWorldTitle, SavedWorldEntryRepository
from exulanica.world.world_draft_jobs import WorldDraftRefused
from exulanica.world.world_recipes import (
    SpecificationRefused,
    UnknownWorldRecipe,
    specification_document,
)
from exulanica.world.worlds import (
    TileBudgetReached,
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
#: The body asking for a draft may carry: a description of at most the drafter's 1,000 characters,
#: at most four bytes each as UTF-8, with its envelope.
DRAFT_BODY_MAXIMUM = 16_384
#: How often the page asks after a draft, in seconds: a first brief takes 20 s or more.
DRAFT_POLL_SECONDS: Final = 3
#: The bodies these routes accept, refused before any of them is read (:mod:`exulanica.api.
#: body_limit`): the server-wide limit is sized for photographs, and a kind is a small document.
BODY_LIMITS: Final = (
    ("POST", "/worlds/kinds", UPLOAD_BODY_MAXIMUM),
    ("POST", "/worlds/kinds/{kind}/worlds", CREATE_BODY_MAXIMUM),
    ("POST", "/worlds/kinds/drafts", DRAFT_BODY_MAXIMUM),
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


class KindDraftingView(BaseModel):
    """Whether this caller may draft a kind of place here, read before anything is typed: the page
    shows no field the server would refuse for this caller and workspace. ``code`` says why not,
    from ``refusals``, the closed list of every code a draft's routes and its job answer with. The
    server's own capacity changes from moment to moment, so a start that was offered may still be
    refused ``kind_draft_capacity``."""

    model_config = ConfigDict(extra="forbid")

    offered: bool
    code: str | None
    refusals: list[KindRefusalView]


class KindLibraryView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: Literal["exulanica.world-kinds/v1"]
    kinds: list[KindView]
    refusals: list[KindRefusalView]
    #: Optional within the profile: a reader that predates it reads the rest as before.
    drafting: KindDraftingView | None = None


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
    #: Explicit bounded support authoring; absent retains the historical composer/drawing.
    support: dict[str, Any] | None = None
    #: The land the site is laid out on (``exulanica.landform/v1``); absent makes the level site
    #: every earlier world is, byte for byte.
    land: dict[str, Any] | None = None


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


def _drafting(
    services: Services,
    held: frozenset[Permission],
    connection: Any,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    guest: bool,
) -> KindDraftingView:
    """Whether a draft would be taken from this caller, by the codes the draft route answers, in
    the order it asks them."""
    code: str | None = None
    if not services.kinds_from_people:
        code = KINDS_FROM_PEOPLE_NOT_OFFERED
    elif not {Permission.WORLD_WRITE, Permission.MODEL_INVOKE} <= held:
        code = "not_authorised"
    elif services.model_client is None:
        code = ModelNotConfigured.code
    elif (
        allowance_refusal(
            services.spending_refusals(connection, workspace_id), services.model_client
        )
        is not None
    ):
        code = "budget_exceeded"
    else:
        try:
            WorkspaceKinds(connection, workspace_id).refuse_when_full()
        except KindCapReached as exc:
            code = exc.code
        else:
            holder = services.kind_drafts
            maximum = holder._budget(holder.starts_per_hour, "starts_an_hour", guest=guest)
            admitted = draft_admission.allowance(connection, workspace_id, actor, maximum)
            if admitted["running_count"] >= holder._budget(
                holder.per_workspace, "workspace_drafts_at_once"
            ):
                code = "kind_draft_busy"
            elif admitted["left"] == 0:
                code = "kind_draft_limit"
    return KindDraftingView(
        offered=code is None,
        code=code,
        refusals=[KindRefusalView(code=c, meaning=m) for c, m in KIND_DRAFT_CODES],
    )


@router.get("", summary="The kinds of world a person can make worlds of.")
def library(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    held: HeldPermissions,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> KindLibraryView:
    """The town, the shipped kinds and the workspace's own kinds, each in plain words, and whether
    this caller may draft a new kind of place here."""
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
        drafting=_drafting(services, held, connection, session.workspace_id, session.actor, guest),
    )


@router.post(
    "",
    response_model=UploadedKindView,
    status_code=201,
    summary="Keep a creator's world kind in this workspace once its checks pass.",
    responses={422: {"description": "Refused by name; nothing was written."}},
)
def upload_kind(
    body: UploadKindBody,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> UploadedKindView | JSONResponse:
    """Read the kind, build its sample worlds and keep it when every one passes.

    A server whose deployment has not turned kinds from people on
    (``EXULANICA_KINDS_FROM_PEOPLE``) answers 403 ``kinds_from_people_not_offered`` for a document
    it would otherwise keep, before any sample world is built and before anything is written: a
    kept kind is a person's own document, and no removal reaches its row. A body that is no kind
    is refused 422 for itself first, as on any server.
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
    if not services.kinds_from_people:
        # Only a document that would otherwise be kept is refused by the setting: a body that is
        # no kind is answered as it always was, so the setting says nothing a caller did not
        # already send. Before any sample world is built and before anything is written.
        return _problem(403, KINDS_FROM_PEOPLE_NOT_OFFERED, KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL)
    stored = WorkspaceKinds(connection, session.workspace_id)
    try:
        # Before the worker builds anything; the append asks again under the workspace's lock.
        stored.refuse_before_checks(kind)
    except (KindVersionExists, KindCapReached, KindErasureRefused) as exc:
        if isinstance(exc, KindErasureRefused):
            forget_kind(kind.sha256)
            kind_worker().forget_kind(str(session.workspace_id), kind.sha256)
        return _problem(409, exc.code, str(exc))
    worker = kind_worker()
    # Kept by the workspace with the document: two workspaces sending one document are told nothing
    # of each other's checks.
    outcome = worker.run(
        check_key(str(session.workspace_id), kind.sha256),
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
    except (KindVersionExists, KindCapReached, KindErasureRefused) as exc:
        if isinstance(exc, KindErasureRefused):
            forget_kind(kind.sha256)
            kind_worker().forget_kind(str(session.workspace_id), kind.sha256)
        return _problem(409, exc.code, str(exc))
    return UploadedKindView(kind=_kind_view(kept.kind, "workspace"), validation=dict(report))


class DraftKindBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: Annotated[
        str, Field(min_length=1, max_length=kind_drafting_prompt().description_characters_maximum)
    ]

    @field_validator("description")
    @classmethod
    def _says_something(cls, value: str) -> str:
        # A description of nothing but spaces would still cost a paid call.
        if not value.strip():
            raise ValueError("a description says in words what kind of place is wanted")
        return value


class KindDraftRefusalView(BaseModel):
    code: str
    detail: str
    check: str | None = None
    where: str | None = None
    #: For ``budget_exceeded`` from the durable authority: the problem's ``spending`` member.
    spending: dict[str, str] | None = None


class KindDraftView(BaseModel):
    draft_id: uuid.UUID
    state: Literal["drafting", "ready", "refused"]
    description: str
    started_at: datetime
    elapsed_seconds: int
    poll_after_seconds: int | None
    deadline_seconds: int
    kind: KindView | None
    refusal: KindDraftRefusalView | None
    model_id: str | None
    model_name: str | None
    prompt_version: str
    execution: ExecutionView | None


def _draft_view(
    draft: KindDraft,
    connection: Any,
    workspace_id: uuid.UUID,
    now: float,
    holder: KindDrafts | None = None,
) -> KindDraftView:
    kind = None
    if draft.kind is not None and draft.version is not None:
        kinds = WorkspaceKinds(connection, workspace_id)
        stored = kinds.version(draft.kind, draft.version) if draft.state == "ready" else None
        # An identified draft may still be between append and finish in another process.
        # Ordinary absence before append is not erasure; its retirement record is definitive.
        erased = (
            stored is None
            if draft.state == "ready"
            else kinds.version_erased(draft.kind, draft.version)
        )
        if erased:
            if holder is not None:
                holder.erase_kind(workspace_id, draft.kind, draft.version)
            KindDrafts._erase_content(draft)
        elif stored is not None:
            kind = _kind_view(stored.kind, "workspace")
    prompt = kind_drafting_prompt()
    ended = draft.state != "drafting"
    return KindDraftView(
        draft_id=draft.draft_id,
        state=draft.state,
        description=draft.description,
        started_at=draft.started_at,
        elapsed_seconds=round((draft.changed if ended else now) - draft.started),
        poll_after_seconds=None if ended else DRAFT_POLL_SECONDS,
        deadline_seconds=math.ceil(
            draft_deadline_seconds() if draft.deadline is None else draft.deadline
        ),
        kind=kind,
        refusal=None if draft.refusal is None else KindDraftRefusalView(**draft.refusal),
        model_id=draft.model_id,
        model_name=None if draft.model_id is None else load_manifest().model_name(draft.model_id),
        prompt_version=prompt.prompt_version,
        execution=_execution(draft.calls, (), prompt_version=prompt.prompt_version)
        if draft.calls
        else None,
    )


def _durable_kind_view(row: dict, connection: Any) -> KindDraftView:
    now = datetime.now(UTC)
    end = row["completed_at"] or now
    doc = row["outcome"] or {}
    draft = KindDraft(
        draft_id=row["draft_id"],
        workspace_id=row["workspace_id"],
        actor=row["actor_id"],
        description=row["description"] or "",
        started_at=row["started_at"],
        started=0,
        changed=(end - row["started_at"]).total_seconds(),
        deadline=row["deadline_seconds"],
        state="drafting" if row["state"] in ("queued", "running") else doc.get("state", "refused"),
        kind=doc.get("kind"),
        version=doc.get("version"),
        refusal=doc.get("refusal"),
        model_id=doc.get("model_id"),
        calls=tuple(
            ModelCall(
                **dict(
                    call,
                    outcome=AttemptOutcome(call["outcome"]),
                    cost_basis=CallCost(call["cost_basis"]),
                )
            )
            for call in doc.get("calls", ())
        ),
    )
    view = _draft_view(
        draft, connection, row["workspace_id"], (now - row["started_at"]).total_seconds()
    )
    return view.model_copy(
        update={
            "prompt_version": row["prompt_version"],
            "execution": _execution(draft.calls, (), prompt_version=row["prompt_version"])
            if draft.calls
            else None,
        }
    )


@router.post(
    "/drafts",
    response_model=KindDraftView,
    status_code=202,
    summary="Draft a kind of world from a description, as a job the page polls.",
)
def start_kind_draft(
    body: DraftKindBody,
    connection: ReadOnlyConnection,
    scoped: ScopedConnection,
    request: Request,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> KindDraftView | JSONResponse:
    """Admit the words and start the draft; answer at once, never waiting on the model.

    403 ``kinds_from_people_not_offered`` on a server whose deployment has not turned kinds from
    people on (``EXULANICA_KINDS_FROM_PEOPLE``), before anything is read;
    503 without a model credential; 429 ``budget_exceeded`` with its ``spending`` member when the
    workspace's allowance for the drafting model admits no attempt (spent, or below what one
    reserves); 409 ``kind_cap_reached`` when the
    workspace keeps as many kinds as it may, each before anything is spent; 409
    ``kind_draft_busy`` while a draft runs in this workspace, with its ``draft_id`` when the caller
    started it; 429 ``kind_draft_limit`` with a ``Retry-After`` when the caller has started as many
    drafts this hour as one person may; 503 ``kind_draft_capacity`` with a ``Retry-After`` when
    the server runs as many drafts as it may. Saved names are replaced before the job starts, and
    the workspace's rules, releasing no place's name, are applied again as each request leaves.
    """
    workspace_id = session.workspace_id
    if not services.kinds_from_people:
        return _problem(403, KINDS_FROM_PEOPLE_NOT_OFFERED, KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL)
    if services.model_client is None:
        raise ModelNotConfigured()
    # An allowance that admits no attempt answers as every model route's does (429
    # budget_exceeded), not as a draft: spent, or below what one attempt reserves.
    spent = allowance_refusal(
        services.spending_refusals(connection, workspace_id), services.model_client
    )
    if spent is not None:
        raise spent
    try:
        WorkspaceKinds(connection, workspace_id).refuse_when_full()
    except KindCapReached as exc:
        return _problem(409, exc.code, str(exc))
    sendable(connection, workspace_id, body.description)
    holder = services.kind_drafts
    repo = KindDraftRepository(scoped, workspace_id)
    try:
        maximum = holder._budget(holder.starts_per_hour, "starts_an_hour", guest=guest)
        workspace_maximum = holder._budget(holder.per_workspace, "workspace_drafts_at_once")
        available = draft_admission.allowance(scoped, workspace_id, session.actor, maximum)
        if available["running_count"] >= workspace_maximum:
            raise WorldDraftRefused("kind_draft_busy")
        if available["left"] == 0:
            raise WorldDraftRefused("kind_draft_limit", available["retry_after_seconds"])
        with holder.execution_slot():
            ident = repo.submit(
                actor=session.actor,
                description=body.description,
                guest=guest,
                starts_maximum=holder._budget(
                    holder.starts_per_hour, "starts_an_hour", guest=guest
                ),
                workspace_maximum=holder._budget(holder.per_workspace, "workspace_drafts_at_once"),
                deadline_seconds=math.ceil(draft_deadline_seconds(services.model_client)),
                manifest_sha256=manifest_sha256(services.model_client),
                prompt_version=kind_drafting_prompt().prompt_version,
            )
    except WorldDraftRefused as failed:
        if failed.code == "kind_draft_busy":
            busy = draft_admission.allowance(scoped, workspace_id, session.actor, 1)["running"]
            extra: dict[str, Any] = (
                {"draft_id": str(busy["draft_id"])}
                if busy and busy["actor_id"] == session.actor and busy["purpose"] == "kind"
                else {}
            )
            return _problem(409, failed.code, "A draft is already running here.", **extra)
        if failed.code == "kind_draft_limit":
            return _problem(
                429,
                failed.code,
                "As many drafts as one person may start in an hour were started. Try again later.",
                headers={"Retry-After": str(failed.retry_after_seconds or 60)},
            )
        return _problem(409, "kind_draft_failed", "The draft could not be started.")
    except KindCapReached as failed:
        return _problem(409, failed.code, str(failed))
    except KindDraftCapacity:
        return _problem(
            503,
            "kind_draft_capacity",
            "The server is drafting as many kinds as it may. Try again in a moment.",
            headers={"Retry-After": "30"},
        )
    worker = getattr(request.app.state, "kind_draft_worker", None)
    if worker is not None:
        worker.notify(workspace_id)
    row = repo.get(session.actor, ident)
    assert row is not None
    return _durable_kind_view(row, scoped)


class KindDraftListView(BaseModel):
    drafts: list[KindDraftView]


@router.get(
    "/drafts",
    response_model=KindDraftListView,
    summary="The kinds of place this caller is drafting or drafted lately, newest first.",
)
def list_kind_drafts(
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> KindDraftListView:
    """The caller's drafts this server still holds in this workspace, newest first, so a reload,
    a second tab or a return finds a draft still running without starting another."""
    return KindDraftListView(
        drafts=[
            _durable_kind_view(row, connection)
            for row in KindDraftRepository(connection, session.workspace_id).listing(session.actor)
        ]
    )


@router.get(
    "/drafts/{draft_id}",
    response_model=KindDraftView,
    summary="A kind's draft: drafting, ready with the kept kind, or refused by name.",
)
def read_kind_draft(
    draft_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> KindDraftView | JSONResponse:
    """The requester's retained draft, including after another process takes over."""
    row = KindDraftRepository(connection, session.workspace_id).get(session.actor, draft_id)
    if row is None:
        return _problem(404, "kind_draft_unknown", "You have no draft with this id.")
    return _durable_kind_view(row, connection)


def _erasure_refused(exc: KindErasureRefused) -> JSONResponse:
    status = {"unknown_world_kind": 404, "world_kind_erased": 410, "world_kind_not_yours": 403}.get(
        exc.code, 409
    )
    return _problem(status, exc.code, exc.detail)


@router.get("/versions/{document_sha256}/removal", response_model=None)
def kind_removal_preview(
    document_sha256: Annotated[str, Path(pattern="^[0-9a-f]{64}$")],
    request: Request,
    connection: ReadOnlyConnection,
    session: CurrentSession,
) -> dict | JSONResponse:
    try:
        return removal_preview(
            connection,
            session.workspace_id,
            document_sha256,
            actor=session.actor,
            by_owner=owns_workspace(request, session),
        )
    except KindErasureRefused as exc:
        return _erasure_refused(exc)


@router.delete("/versions/{document_sha256}", status_code=204)
def remove_kept_kind(
    document_sha256: Annotated[str, Path(pattern="^[0-9a-f]{64}$")],
    request: Request,
    connection: ScopedConnection,
    session: CurrentSession,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    try:
        with connection.transaction():
            kind, version = erase_kind(
                connection,
                session.workspace_id,
                document_sha256,
                erased_by=session.actor,
                by_owner=owns_workspace(request, session),
            )
    except KindErasureRefused as exc:
        return _erasure_refused(exc)
    forget_kind(document_sha256)
    kind_worker().forget_kind(str(session.workspace_id), document_sha256)
    if services.kind_drafts is not None:
        services.kind_drafts.erase_kind(session.workspace_id, kind, version)
    return Response(status_code=204)


def _kept_kind(
    connection: Any, workspace_id: uuid.UUID, key: str, version: int | None
) -> KindDocument | None:
    """The kind the workspace keeps under ``key``: a person's own document."""
    stored = WorkspaceKinds(connection, workspace_id)
    found = stored.version(key, version) if version is not None else stored.latest(key)
    return None if found is None else found.kind


def _find_kind(
    connection: Any, workspace_id: uuid.UUID, key: str, version: int | None
) -> KindDocument | None:
    kept = _kept_kind(connection, workspace_id, key, version)
    if kept is not None:
        return kept
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
    guest: Annotated[bool, Depends(holds_as_guest)],
) -> SavedWorldEntryView | JSONResponse:
    """Make a world of ``kind`` with a preset and values, for a new identity, and save its entry.

    The town is made as ``POST /worlds/generated`` makes it, from its preset through the same gate
    and composer, so it is the same world. Every other kind is made by the site grammar from the
    kind the workspace holds or the product ships (the latest version unless one is named). An
    unknown kind or preset answers 404; a value the kind does not offer 422, naming the key, the
    value and the range; a title empty once trimmed 422; a land document the landform catalog
    refuses 422, naming its path (``landform_*``), and land asked of the town or with a support
    declaration 422 ``landform_not_served``; a kind none of whose candidates makes a world people
    can live in, for any identity drawn (on land: none whose layout the land can take), 409 with
    every refusal; a workspace already
    holding as many generated worlds as the count policy allows 409; a deployment whose database
    role cannot register a world 403 ``worlds_read_only``. Nothing is written when any is refused.

    A world's receipt carries its kind's whole document, so a world of a kind the workspace keeps
    copies a person's document once more. A server whose deployment has not turned kinds from
    people on (``EXULANICA_KINDS_FROM_PEOPLE``) makes worlds of shipped kinds and the town only,
    and answers 403 ``kinds_from_people_not_offered`` for a kind the workspace keeps.
    """
    try:
        from exulanica.grammar.landform import LandformRefused
        from exulanica.world.support_surfaces import SupportRefused

        require_world_registration(connection)
    except WorldsReadOnly as exc:
        return _problem(403, exc.code, str(exc))
    entries = SavedWorldEntryRepository(
        connection, session.workspace_id, services.store, guest=guest
    )
    used_kind: KindDocument | None = None
    try:
        if kind == town_adapter().kind and body.version in (None, town_adapter().version):
            if body.support is not None:
                return _problem(
                    422, "support_network_invalid", "Support authoring is served for site worlds."
                )
            if body.land is not None:
                return _problem(
                    422,
                    "landform_not_served",
                    "Land is served for site worlds; a town is laid out on level ground.",
                    path="land",
                )
            created = entries.create_generated(
                title=body.title,
                recipe_key=body.preset,
                created_by=session.actor,
                values=body.values,
            )
        else:
            if (
                not services.kinds_from_people
                and _kept_kind(connection, session.workspace_id, kind, body.version) is not None
            ):
                # The workspace's own kind is read before a shipped one of the same key, so it is
                # refused by name here and never passed over for the shipped one.
                return _problem(
                    403, KINDS_FROM_PEOPLE_NOT_OFFERED, KINDS_FROM_PEOPLE_NOT_OFFERED_DETAIL
                )
            found = _find_kind(connection, session.workspace_id, kind, body.version)
            if found is None:
                return _problem(404, "unknown_world_kind", f"no world kind is named {kind!r}")
            used_kind = found
            values = found.values(body.preset, body.values)
            composer = WorkerComposer(session.workspace_id, support=body.support, land=body.land)
            created = entries.create_from_kind(
                title=body.title,
                kind=found,
                values=values,
                created_by=session.actor,
                compose=composer,
            )
            # The drawing the page reads next and the place its people walk, made with the world.
            composer.keep()
    except KindErasureRefused as exc:
        return _erasure_refused(exc)
    except psycopg.errors.CheckViolation as exc:
        if exc.diag.constraint_name == "world_kind_erased":
            if used_kind is not None:
                forget_kind(used_kind.sha256)
                kind_worker().forget_kind(str(session.workspace_id), used_kind.sha256)
            return _erasure_refused(KindErasureRefused("world_kind_erased"))
        raise
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
    except SupportRefused as exc:
        return _problem(422, exc.code, exc.detail, where=exc.where)
    except LandformRefused as exc:
        return _problem(422, exc.code, exc.detail, path=exc.path)
    except TileBudgetReached as exc:
        return _problem(409, exc.code, str(exc), returns_at=exc.returns_at.isoformat())
    except (GeneratedWorldRefused, UnknownWorldComposer, WorldLimitReached) as exc:
        return _problem(409, exc.code, str(exc))
    return _view(created, societies_of_things=services.societies_of_things)


@site_router.get(
    "/versions/{version_id}/site",
    summary="A site world's drawing, for the world whose snapshot names its receipt.",
)
def read_site_drawing(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
    services: Annotated[Services, Depends(get_services)],
) -> Response:
    """Serve the version's exact drawing after worker/cache and final current-source checks."""
    from exulanica.api.world_edit import object_problem
    from exulanica.db.read_check import final_read_check
    from exulanica.world.composers.site_plan import receipt_terrain
    from exulanica.world.errors import StaleObjectBase
    from exulanica.world.kinds.worker import TerrainDressingWorkerCompiler
    from exulanica.world.object_repository import WorldObjectRepository
    from exulanica.world.reviewed_catalog import ReviewedCatalog
    from exulanica.world.terrain_authoring import TerrainAuthoringRefused
    from exulanica.world.terrain_dressing_authority import (
        require_terrain_dressing_current,
        resolve_terrain_dressing,
    )

    try:
        require_world(connection, session.workspace_id, world_id)
        repository = WorldObjectRepository(
            connection, session.workspace_id, world_id=world_id, store=services.store
        )
        initial = repository.edit_base_row(version_id)
        snapshot_id = initial["source_snapshot_id"]
        if not states_site(connection, session.workspace_id, world_id, snapshot_id):
            return _problem(404, "unknown_reference", "this world is not made from a world kind")
        digest, receipt = generation_receipt(
            connection, session.workspace_id, world_id, snapshot_id
        )
        dressed = receipt["composer"] == {"key": "site-plan", "version": 4}
        resolved = None
        if dressed:
            repository.require_edit_base(initial, initial["state_sha256"])
            resolved = resolve_terrain_dressing(
                ReviewedCatalog(connection),
                services.store,
                receipt_terrain(receipt),
                compile_coverage=TerrainDressingWorkerCompiler(session.workspace_id),
            )
        worker = kind_worker()
        outcome = worker.run(
            drawing_key(str(session.workspace_id), digest),
            DRAWING_SECONDS,
            drawing_job,
            str(session.workspace_id),
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
        if resolved is not None:
            with final_read_check(connection, not_idle="dressed drawing requires an idle read"):
                require_world(connection, session.workspace_id, world_id)
                final = repository.edit_base_row(version_id)
                repository.require_edit_base(final, initial["state_sha256"])
                if (
                    final["source_snapshot_id"] != snapshot_id
                    or final["edit_seq"] != initial["edit_seq"]
                ):
                    raise StaleObjectBase("terrain drawing source changed while it was read")
                final_digest, _ = generation_receipt(
                    connection, session.workspace_id, world_id, snapshot_id
                )
                if final_digest != digest:
                    raise StaleObjectBase("terrain drawing receipt changed while it was read")
                require_terrain_dressing_current(ReviewedCatalog(connection), resolved)
    except KindWorkWaiting as exc:
        return _problem(503, exc.code, str(exc), headers={"Retry-After": str(exc.retry_seconds)})
    except (InvalidStructuralData, TerrainAuthoringRefused) as exc:
        return _problem(409, "generated_world_unreadable", str(exc))
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem
    return Response(
        content=answer["body"],
        media_type="application/json",
        headers={**_HEADERS, "ETag": f'"{answer["sha256"]}"'},
    )


def _site_land_document(
    version_id: uuid.UUID,
    connection: Any,
    session: Any,
    world_id: str,
    pick: str,
) -> Response:
    """Serve one of a site world's land documents (``pick`` is ``backdrop`` or ``x,y`` for a
    chunk), made with its drawing in the kind worker and kept beside it, by the digest the drawing
    names."""
    from exulanica.api.world_edit import object_problem
    from exulanica.world.composers.site_plan import LAND_COMPOSER_VERSION
    from exulanica.world.object_repository import WorldObjectRepository

    try:
        require_world(connection, session.workspace_id, world_id)
        repository = WorldObjectRepository(connection, session.workspace_id, world_id=world_id)
        snapshot_id = repository.edit_base_row(version_id)["source_snapshot_id"]
        if not states_site(connection, session.workspace_id, world_id, snapshot_id):
            return _problem(404, "unknown_reference", "this world is not made from a world kind")
        digest, receipt = generation_receipt(
            connection, session.workspace_id, world_id, snapshot_id
        )
        if receipt["composer"] != {"key": "site-plan", "version": LAND_COMPOSER_VERSION}:
            return _problem(404, "land_unavailable", "this world stands on level ground")
        worker = kind_worker()
        outcome = worker.run(
            drawing_key(str(session.workspace_id), digest),
            DRAWING_SECONDS,
            drawing_job,
            str(session.workspace_id),
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
        land = answer["land"]
        found = land["backdrop"] if pick == "backdrop" else land["chunks"].get(pick)
        if found is None:
            return _problem(404, "land_chunk_unavailable", f"this world's land has no chunk {pick}")
    except KindWorkWaiting as exc:
        return _problem(503, exc.code, str(exc), headers={"Retry-After": str(exc.retry_seconds)})
    except InvalidStructuralData as exc:
        return _problem(409, "generated_world_unreadable", str(exc))
    except Exception as exc:
        problem = object_problem(exc)
        if problem is None:
            raise
        return problem
    return Response(
        content=found["body"].encode("utf-8"),
        media_type="application/json",
        headers={**_HEADERS, "ETag": f'"{found["sha256"]}"'},
    )


@site_router.get(
    "/versions/{version_id}/land/chunks/{chunk_x}/{chunk_y}",
    summary="One 128 m chunk of a site world's land, by its place on the city's tile grid.",
)
def read_site_land_chunk(
    version_id: uuid.UUID,
    chunk_x: Annotated[int, Path(ge=-4096, le=4096)],
    chunk_y: Annotated[int, Path(ge=-4096, le=4096)],
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """Serve one chunk of a site world's graded land (``exulanica.landform-chunk/v1``), held to the
    digest its drawing (``exulanica.site-drawing/v5``) names. A level world answers 404
    ``land_unavailable``; a chunk the land does not hold 404 ``land_chunk_unavailable``."""
    return _site_land_document(version_id, connection, session, world_id, f"{chunk_x},{chunk_y}")


@site_router.get(
    "/versions/{version_id}/land/backdrop",
    summary="A site world's land drawn to the horizon, never walked.",
)
def read_site_land_backdrop(
    version_id: uuid.UUID,
    connection: ReadOnlyConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Response:
    """Serve a site world's backdrop (``exulanica.landform-backdrop/v1``), held to the digest its
    drawing names. A level world answers 404 ``land_unavailable``."""
    return _site_land_document(version_id, connection, session, world_id, "backdrop")
