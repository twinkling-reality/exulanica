"""World projects: what a person chose to keep about their work in one world.

`docs/project-context.md` is the contract and :mod:`exulanica.world.project_context` the authority;
these routes validate and delegate. Every route takes the world it works in (``world_id``), and a
project in another world, another workspace's, a deleted one, another person's private one and an
id nobody minted all answer the same ``404 unknown_reference``.

The actor comes from the session and never from a body. Only a project's owner changes it;
another person of the workspace reads what the owner shares, and a change asked by them answers
``403 not_project_owner``. No route here asks a model, grants a permission or writes the
interaction policy: a preference kept here is what a person said they want.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ReadOnlyConnection, ScopedConnection
from exulanica.api.world_scope import WorldId
from exulanica.world.project_context import (
    LIST_DEFAULT,
    LIST_MAX,
    NOTE_MAX,
    TEXT_MAX,
    TITLE_MAX,
    ItemBasis,
    ItemKind,
    ItemOrigin,
    ItemStatus,
    ProjectContextError,
    ProjectContextRepository,
    Reuse,
    WithdrawalReason,
)
from exulanica.world.project_context import ItemView as DomainItem
from exulanica.world.project_context import ProjectView as DomainProject
from exulanica.world.project_context_assembly import (
    DEFAULT_MAX_BYTES,
    DEFAULT_MAX_ENTRIES,
    MAX_BYTES,
    MAX_ENTRIES,
    MIN_BYTES,
    Budget,
)
from exulanica.world.project_context_references import MAX_REFERENCES
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/projects", tags=["world"])

_SHA256 = r"^[0-9a-f]{64}$"
_WORLD = Annotated[str, Field(min_length=1, max_length=200)]
_Id = Annotated[uuid.UUID, Path()]
_Revision = Annotated[int, Field(ge=1)]


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    """The one failure shape this package answers with, copied as its neighbours copy it."""
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


# -- what a caller sends --------------------------------------------------------------------------


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProjectWorldEditReference(_Body):
    """An accepted edit, as the route that made it reported it."""

    kind: Literal["world_edit"]
    operation: str
    world_id: _WORLD
    version_id: uuid.UUID
    edit_id: uuid.UUID
    edit_seq: Annotated[int, Field(ge=1)]
    result_state_sha256: Annotated[str, Field(pattern=_SHA256)]


class ProjectStyleVersionReference(_Body):
    """An applied appearance: a style version, and the preview and proposal it came from."""

    kind: Literal["style_version"]
    operation: str
    world_id: _WORLD
    style_version_id: uuid.UUID
    preview_id: uuid.UUID | None
    proposal_id: uuid.UUID | None


class ProjectSocietyControlReference(_Body):
    """A control receipt: a configuration by its revision, a manual step by its tick and state."""

    kind: Literal["society_control"]
    operation: str
    world_id: _WORLD
    version_id: uuid.UUID
    revision: Annotated[int, Field(ge=1)]
    tick: Annotated[int, Field(ge=0)] | None
    state_sha256: Annotated[str, Field(pattern=_SHA256)] | None


class ProjectSocietyEventReference(_Body):
    """A simulated event, and the input, object and edit that explain it where the answer named
    them."""

    kind: Literal["society_event"]
    world_id: _WORLD
    version_id: uuid.UUID
    event_id: uuid.UUID
    tick: Annotated[int, Field(ge=1)]
    input_seq: Annotated[int, Field(ge=1)] | None
    object_id: Annotated[str, Field(min_length=1, max_length=200)] | None
    edit_seq: Annotated[int, Field(ge=1)] | None
    edit_id: uuid.UUID | None


class ProjectStylePreviewReference(_Body):
    """An appearance preview: unfinished work while it is open."""

    kind: Literal["style_preview"]
    world_id: _WORLD
    preview_id: uuid.UUID


class ProjectCompanionAnswerReference(_Body):
    """One of the caller's own remembered Companion answers. An item naming one is deleted with
    it."""

    kind: Literal["companion_answer"]
    answer_id: uuid.UUID


ProjectReferenceBody = Annotated[
    ProjectWorldEditReference
    | ProjectStyleVersionReference
    | ProjectSocietyControlReference
    | ProjectSocietyEventReference
    | ProjectStylePreviewReference
    | ProjectCompanionAnswerReference,
    Field(discriminator="kind"),
]


class ProjectBody(_Body):
    title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
    version_id: uuid.UUID
    idempotency_key: uuid.UUID | None = None


class ProjectUpdateBody(_Body):
    """The project's name and version as they should be; either may be what they already are."""

    base_revision: _Revision
    title: Annotated[str, Field(min_length=1, max_length=TITLE_MAX)]
    version_id: uuid.UUID


class ProjectReuseBody(_Body):
    world_id: _WORLD
    project_id: uuid.UUID
    item_id: uuid.UUID


class ProjectItemBody(_Body):
    """One item in the caller's words, a suggestion to review, or a copy of their own item.

    ``basis`` says where the words come from: the caller's own statement, a suggestion the
    Companion drew (which must name the Companion answers it was drawn from and waits for review),
    a recorded outcome (a decision naming accepted records) or a simulated event. A copy names
    only ``reuse`` and takes everything else from the item it copies.
    """

    base_revision: _Revision
    kind: ItemKind | None = None
    basis: ItemBasis | None = None
    text: Annotated[str, Field(min_length=1, max_length=TEXT_MAX)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=NOTE_MAX)] | None = None
    references: Annotated[list[ProjectReferenceBody], Field(max_length=MAX_REFERENCES)] = Field(
        default_factory=list
    )
    reuse: ProjectReuseBody | None = None
    idempotency_key: uuid.UUID | None = None


class ProjectItemCorrectionBody(_Body):
    """The item as it should read. ``note`` says why; ``references`` replaces what it names."""

    base_revision: _Revision
    text: Annotated[str, Field(min_length=1, max_length=TEXT_MAX)] | None = None
    note: Annotated[str, Field(min_length=1, max_length=NOTE_MAX)] | None = None
    references: Annotated[list[ProjectReferenceBody], Field(max_length=MAX_REFERENCES)] | None = (
        None
    )


class ProjectItemReviewBody(_Body):
    base_revision: _Revision
    decision: Literal["accept", "reject"]


class ProjectItemResolveBody(_Body):
    base_revision: _Revision


class ProjectShareBody(_Body):
    base_revision: _Revision
    project: bool = False
    item_ids: Annotated[list[uuid.UUID], Field(max_length=500)] = Field(default_factory=list)


# -- what a caller receives -----------------------------------------------------------------------


class ProjectBindingView(_Body):
    version_id: uuid.UUID
    #: ``available``, or ``unavailable`` with ``code`` ``invalidated_source_version``.
    state: Literal["available", "unavailable"]
    code: str | None
    #: The version's state now, and as it was when the project was bound to it.
    state_sha256: str
    edit_seq: int
    bound_at: dt.datetime
    bound_state_sha256: str
    bound_edit_seq: int
    #: The world's saved entry and the version it opens now, which may differ from this one.
    entry_id: uuid.UUID | None
    entry_version_id: uuid.UUID | None


class ProjectView(_Body):
    project_id: uuid.UUID
    world_id: str
    title: str
    revision: int
    created_at: dt.datetime
    changed_at: dt.datetime
    owner_is_reader: bool
    share_id: uuid.UUID | None
    binding: ProjectBindingView
    #: Active items this reader may see, by kind, and how many are resolved or proposed.
    counts: dict[str, int]


class ProjectReferenceStateView(_Body):
    reference: dict[str, Any]
    #: ``available``, ``unavailable``, ``withdrawn``, ``missing`` or ``mismatch``, as the record's
    #: own authority reads now.
    state: str
    code: str | None
    detail: str | None


class ProjectReuseView(_Body):
    world_id: str
    project_id: uuid.UUID
    item_id: uuid.UUID


class ProjectItemView(_Body):
    item_id: uuid.UUID
    project_id: uuid.UUID
    project_revision: int
    kind: ItemKind
    basis: ItemBasis
    origin: ItemOrigin
    status: ItemStatus
    revision: int
    created_at: dt.datetime
    changed_at: dt.datetime
    recorded_at: dt.datetime
    reviewed_at: dt.datetime | None
    resolved_at: dt.datetime | None
    text: str | None
    note: str | None
    references: list[ProjectReferenceStateView]
    hidden_references: int
    share_id: uuid.UUID | None
    owner_is_reader: bool
    source_answer_ids: list[uuid.UUID]
    reused_from: ProjectReuseView | None


class ProjectItemRevisionView(_Body):
    revision: int
    basis: ItemBasis
    origin: ItemOrigin
    text: str | None
    note: str | None
    references: list[dict[str, Any]]
    recorded_at: dt.datetime


class ProjectRevisionView(_Body):
    project_revision: int


class ProjectItemReviewView(_Body):
    """The project's revision after a decision, and the accepted item; null for a rejection,
    whose words are erased."""

    project_revision: int
    item: ProjectItemView | None


class ProjectShareView(_Body):
    share_id: uuid.UUID
    item_id: uuid.UUID | None
    shared_at: dt.datetime


class ProjectSharesView(_Body):
    project_revision: int
    shares: list[ProjectShareView]


class ProjectAuditRevisionView(_Body):
    basis: ItemBasis
    origin: ItemOrigin
    recorded_at: dt.datetime


class ProjectAuditItemView(_Body):
    item_id: uuid.UUID
    kind: ItemKind
    status: ItemStatus
    created_at: dt.datetime
    reviewed_at: dt.datetime | None
    resolved_at: dt.datetime | None
    withdrawn_at: dt.datetime | None
    withdrawn_reason: WithdrawalReason | None
    revisions: list[ProjectAuditRevisionView]


class ProjectAuditBindingView(_Body):
    binding_seq: int
    version_id: uuid.UUID
    bound_at: dt.datetime


class ProjectAuditShareView(_Body):
    share_id: uuid.UUID
    item_id: uuid.UUID | None
    shared_at: dt.datetime
    withdrawn_at: dt.datetime | None


class ProjectAuditView(_Body):
    """What remains when the words are gone: ids, kinds, instants and reasons, never content."""

    project_id: uuid.UUID
    world_id: str
    created_at: dt.datetime
    withdrawn_at: dt.datetime | None
    withdrawn_by_tombstone: bool
    revision: int
    bindings: list[ProjectAuditBindingView]
    items: list[ProjectAuditItemView]
    shares: list[ProjectAuditShareView]


class ProjectContextEntryView(_Body):
    item_id: uuid.UUID
    revision: int
    kind: ItemKind
    basis: ItemBasis
    origin: ItemOrigin
    written_by_reader: bool
    recorded_at: dt.datetime
    text: str | None
    note: str | None
    references: list[ProjectReferenceStateView]


class ProjectContextBudgetView(_Body):
    max_entries: int
    max_bytes: int
    used_entries: int
    used_bytes: int


class ProjectContextView(_Body):
    """The bounded context this reader may hand onward, assembled from current rows."""

    profile: str
    project: ProjectView
    budget: ProjectContextBudgetView
    entries: list[ProjectContextEntryView]
    #: Candidates left out and why: ``over_budget``, ``reference_unavailable``,
    #: ``pending_review``, ``resolved``.
    omitted: dict[str, int]
    #: Covers the project's revision and each entry's item and revision, and no words.
    assembly_sha256: str


# -- repositories -------------------------------------------------------------------------------


def _authorizer(request: Request, connection: Any, session: CurrentSession) -> Any:
    authorize = getattr(request.app.state, "society_input_authorizer", None)
    return None if authorize is None else lambda document: authorize(connection, session, document)


def read_projects(
    request: Request, connection: ReadOnlyConnection, session: CurrentSession, world_id: WorldId
) -> ProjectContextRepository:
    require_world(connection, session.workspace_id, world_id)
    return ProjectContextRepository(
        connection,
        session.workspace_id,
        session.actor,
        world_id,
        input_authorizer=_authorizer(request, connection, session),
    )


def resolve_projects(
    request: Request, connection: ScopedConnection, session: CurrentSession, world_id: WorldId
) -> ProjectContextRepository:
    """For reads that resolve what items name: a society's authorization reads as its own reads
    do, on the runtime's connection."""
    require_world(connection, session.workspace_id, world_id)
    return ProjectContextRepository(
        connection,
        session.workspace_id,
        session.actor,
        world_id,
        input_authorizer=_authorizer(request, connection, session),
    )


ReadProjects = Annotated[ProjectContextRepository, Depends(read_projects)]
ResolveProjects = Annotated[ProjectContextRepository, Depends(resolve_projects)]
WriteProjects = Annotated[ProjectContextRepository, Depends(resolve_projects)]


# -- routes ---------------------------------------------------------------------------------------


@router.get(
    "",
    response_model=list[ProjectView],
    summary="This world's projects the caller owns or that are shared with them.",
)
def list_projects(
    repository: ReadProjects,
    limit: Annotated[int, Query(ge=1, le=LIST_MAX)] = LIST_DEFAULT,
) -> list[ProjectView] | JSONResponse:
    try:
        return [_project(p) for p in repository.projects(limit=limit)]
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.post(
    "",
    response_model=ProjectView,
    status_code=201,
    summary="Start a project bound to a version of this world. An exact retry of a key is 200.",
)
def create_project(
    body: ProjectBody, repository: WriteProjects, response: Response
) -> ProjectView | JSONResponse:
    try:
        project, created = repository.create_project(
            title=body.title, version_id=body.version_id, idempotency_key=body.idempotency_key
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    response.status_code = 201 if created else 200
    return _project(project)


@router.get(
    "/{project_id}",
    response_model=ProjectView,
    summary="One project: its binding as the version reads now, and what the caller may see.",
)
def read_project(project_id: _Id, repository: ReadProjects) -> ProjectView | JSONResponse:
    try:
        return _project(repository.project(project_id))
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.put(
    "/{project_id}",
    response_model=ProjectView,
    summary="Rename the project, or bind it to another version of this world.",
)
def update_project(
    project_id: _Id, body: ProjectUpdateBody, repository: WriteProjects
) -> ProjectView | JSONResponse:
    try:
        return _project(
            repository.update_project(
                project_id,
                base_revision=body.base_revision,
                title=body.title,
                version_id=body.version_id,
            )
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.delete(
    "/{project_id}",
    status_code=204,
    summary="Delete the project, every item's words and every share, for good.",
)
def delete_project(project_id: _Id, repository: WriteProjects) -> Response:
    try:
        repository.delete_project(project_id)
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return Response(status_code=204)


@router.get(
    "/{project_id}/audit",
    response_model=ProjectAuditView,
    summary="The owner's non-content record of a project, kept after its words are deleted.",
)
def project_audit(project_id: _Id, repository: ReadProjects) -> ProjectAuditView | JSONResponse:
    try:
        audit = repository.audit(project_id)
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return ProjectAuditView(
        project_id=audit.project_id,
        world_id=audit.world_id,
        created_at=audit.created_at,
        withdrawn_at=audit.withdrawn_at,
        withdrawn_by_tombstone=audit.withdrawn_by_tombstone,
        revision=audit.revision,
        bindings=[
            ProjectAuditBindingView(binding_seq=seq, version_id=version, bound_at=at)
            for seq, version, at in audit.bindings
        ],
        items=[
            ProjectAuditItemView(
                item_id=item.item_id,
                kind=item.kind,
                status=item.status,
                created_at=item.created_at,
                reviewed_at=item.reviewed_at,
                resolved_at=item.resolved_at,
                withdrawn_at=item.withdrawn_at,
                withdrawn_reason=item.withdrawn_reason,
                revisions=[
                    ProjectAuditRevisionView(basis=basis, origin=origin, recorded_at=at)
                    for basis, origin, at in item.revisions
                ],
            )
            for item in audit.items
        ],
        shares=[
            ProjectAuditShareView(
                share_id=share, item_id=item, shared_at=shared, withdrawn_at=stopped
            )
            for share, item, shared, stopped in audit.shares
        ],
    )


@router.get(
    "/{project_id}/items",
    response_model=list[ProjectItemView],
    summary="The items the caller may see, with what each names as its authority reads now.",
)
def list_items(
    project_id: _Id,
    repository: ResolveProjects,
    status: Annotated[list[Literal["proposed", "active", "resolved"]] | None, Query()] = None,
) -> list[ProjectItemView] | JSONResponse:
    try:
        items = repository.items(
            project_id,
            statuses=None if status is None else frozenset(ItemStatus(s) for s in status),
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return [_item(item) for item in items]


@router.post(
    "/{project_id}/items",
    response_model=ProjectItemView,
    status_code=201,
    summary="Keep an item, or copy one of the caller's own. An exact retry of a key is 200.",
)
def add_item(
    project_id: _Id, body: ProjectItemBody, repository: WriteProjects, response: Response
) -> ProjectItemView | JSONResponse:
    try:
        item, created = repository.add_item(
            project_id,
            base_revision=body.base_revision,
            kind=body.kind,
            basis=body.basis,
            text=body.text,
            note=body.note,
            references=[r.model_dump(mode="json") for r in body.references],
            reuse=None
            if body.reuse is None
            else Reuse(body.reuse.world_id, body.reuse.project_id, body.reuse.item_id),
            idempotency_key=body.idempotency_key,
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    response.status_code = 201 if created else 200
    return _item(item)


@router.get(
    "/{project_id}/items/{item_id}/history",
    response_model=list[ProjectItemRevisionView],
    summary="Every revision of one of the owner's items, with its words: its correction history.",
)
def item_history(
    project_id: _Id, item_id: _Id, repository: ReadProjects
) -> list[ProjectItemRevisionView] | JSONResponse:
    try:
        revisions = repository.history(project_id, item_id)
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return [
        ProjectItemRevisionView(
            revision=r.revision,
            basis=r.basis,
            origin=r.origin,
            text=r.text,
            note=r.note,
            references=[dict(reference) for reference in r.references],
            recorded_at=r.recorded_at,
        )
        for r in revisions
    ]


@router.post(
    "/{project_id}/items/{item_id}/corrections",
    response_model=ProjectItemView,
    status_code=201,
    summary="Correct an item. The earlier words stay in its history until it is deleted.",
)
def correct_item(
    project_id: _Id, item_id: _Id, body: ProjectItemCorrectionBody, repository: WriteProjects
) -> ProjectItemView | JSONResponse:
    try:
        item = repository.correct_item(
            project_id,
            item_id,
            base_revision=body.base_revision,
            text=body.text,
            note=body.note,
            references=None
            if body.references is None
            else [r.model_dump(mode="json") for r in body.references],
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return _item(item)


@router.post(
    "/{project_id}/items/{item_id}/review",
    response_model=ProjectItemReviewView,
    summary="Accept a suggestion into the context, or reject it and erase its words.",
)
def review_item(
    project_id: _Id, item_id: _Id, body: ProjectItemReviewBody, repository: WriteProjects
) -> ProjectItemReviewView | JSONResponse:
    try:
        revision, item = repository.review_item(
            project_id, item_id, base_revision=body.base_revision, accept=body.decision == "accept"
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return ProjectItemReviewView(
        project_revision=revision, item=None if item is None else _item(item)
    )


@router.post(
    "/{project_id}/items/{item_id}/resolve",
    response_model=ProjectItemView,
    summary="Close a goal, question or task that is done. It leaves the context.",
)
def resolve_item(
    project_id: _Id, item_id: _Id, body: ProjectItemResolveBody, repository: WriteProjects
) -> ProjectItemView | JSONResponse:
    try:
        return _item(repository.resolve_item(project_id, item_id, base_revision=body.base_revision))
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.delete(
    "/{project_id}/items/{item_id}",
    response_model=ProjectRevisionView,
    summary="Delete one item and every copy of it, erasing their words.",
)
def delete_item(
    project_id: _Id, item_id: _Id, repository: WriteProjects
) -> ProjectRevisionView | JSONResponse:
    try:
        return ProjectRevisionView(project_revision=repository.delete_item(project_id, item_id))
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.post(
    "/{project_id}/shares",
    response_model=ProjectSharesView,
    summary="Share the project, or listed items of it, with the other people of this workspace.",
)
def share(
    project_id: _Id, body: ProjectShareBody, repository: WriteProjects
) -> ProjectSharesView | JSONResponse:
    try:
        revision, shares = repository.share(
            project_id,
            base_revision=body.base_revision,
            project=body.project,
            item_ids=body.item_ids,
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    return ProjectSharesView(
        project_revision=revision,
        shares=[
            ProjectShareView(share_id=s.share_id, item_id=s.item_id, shared_at=s.shared_at)
            for s in shares
        ],
    )


@router.delete(
    "/{project_id}/shares/{share_id}",
    response_model=ProjectRevisionView,
    summary="Stop one share. The next read by anyone else no longer shows what it opened.",
)
def stop_share(
    project_id: _Id, share_id: _Id, repository: WriteProjects
) -> ProjectRevisionView | JSONResponse:
    try:
        return ProjectRevisionView(project_revision=repository.stop_share(project_id, share_id))
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))


@router.get(
    "/{project_id}/context",
    response_model=ProjectContextView,
    summary="The bounded context the caller may hand onward, assembled now; nothing is stored.",
)
def project_context(
    project_id: _Id,
    repository: ResolveProjects,
    max_entries: Annotated[int, Query(ge=1, le=MAX_ENTRIES)] = DEFAULT_MAX_ENTRIES,
    max_bytes: Annotated[int, Query(ge=MIN_BYTES, le=MAX_BYTES)] = DEFAULT_MAX_BYTES,
) -> ProjectContextView | JSONResponse:
    try:
        view = repository.context(
            project_id, budget=Budget(max_entries=max_entries, max_bytes=max_bytes)
        )
    except ProjectContextError as exc:
        return _problem(exc.status, exc.code, str(exc))
    assembly = view.assembly
    return ProjectContextView(
        profile=assembly.profile,
        project=_project(view.project),
        budget=ProjectContextBudgetView(
            max_entries=assembly.budget.max_entries,
            max_bytes=assembly.budget.max_bytes,
            used_entries=len(assembly.entries),
            used_bytes=assembly.used_bytes,
        ),
        entries=[ProjectContextEntryView.model_validate(dict(entry)) for entry in assembly.entries],
        omitted=dict(assembly.omitted),
        assembly_sha256=assembly.assembly_sha256,
    )


def _project(project: DomainProject) -> ProjectView:
    binding = project.binding
    return ProjectView(
        project_id=project.project_id,
        world_id=project.world_id,
        title=project.title,
        revision=project.revision,
        created_at=project.created_at,
        changed_at=project.changed_at,
        owner_is_reader=project.owner_is_reader,
        share_id=project.share_id,
        binding=ProjectBindingView(
            version_id=binding.version_id,
            state="available" if binding.state == "available" else "unavailable",
            code=binding.code,
            state_sha256=binding.state_sha256,
            edit_seq=binding.edit_seq,
            bound_at=binding.bound_at,
            bound_state_sha256=binding.bound_state_sha256,
            bound_edit_seq=binding.bound_edit_seq,
            entry_id=binding.entry_id,
            entry_version_id=binding.entry_version_id,
        ),
        counts=dict(project.counts),
    )


def _item(item: DomainItem) -> ProjectItemView:
    return ProjectItemView(
        item_id=item.item_id,
        project_id=item.project_id,
        project_revision=item.project_revision,
        kind=item.kind,
        basis=item.basis,
        origin=item.origin,
        status=item.status,
        revision=item.revision,
        created_at=item.created_at,
        changed_at=item.changed_at,
        recorded_at=item.recorded_at,
        reviewed_at=item.reviewed_at,
        resolved_at=item.resolved_at,
        text=item.text,
        note=item.note,
        references=[
            ProjectReferenceStateView(
                reference=dict(r.reference), state=r.state, code=r.code, detail=r.detail
            )
            for r in item.references
        ],
        hidden_references=item.hidden_references,
        share_id=item.share_id,
        owner_is_reader=item.owner_is_reader,
        source_answer_ids=list(item.source_answer_ids),
        reused_from=None
        if item.reused_from is None
        else ProjectReuseView(
            world_id=item.reused_from.world_id,
            project_id=item.reused_from.project_id,
            item_id=item.reused_from.item_id,
        ),
    )
