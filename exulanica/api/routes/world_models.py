"""A saved world's registered decision roles, offered models and owner choices.

The read names every role the registry serves, including people and traffic signals. A signal's
target effective second and first sealed model-controlled second are separate, so a pending choice
cannot be presented as a light a model already runs. Choosing never asks a model; the background
traffic controller owns that work. The person-specific society route remains available to its
existing callers.

Every role carries the same declared semantics beside its own fields: whether its owner may choose
a model for its subjects now (``capability``, the descriptor of this route's ``POST`` bound to the
role), why this host asks no chosen model (``host_refusal``), how many of its subjects models may
run at once (``model_subjects_maximum``) and the contract a new choice records (``contract``). Each
role's host is named in code (:mod:`exulanica.api.role_hosts`); a registered role no host serves is
listed as unsupported, and a choice of any role is refused with the status its code has everywhere.

``host_refusal`` is this process's own refusal, by ``HOST_REFUSALS``. Where a durable spending
authority admits this process's calls, the descriptor's ``decisions`` effect also names the
authority's refusal once the allowance of every provider the role's models are served by is spent
(``Services.spending_refusals``): every ask would then be refused before anything is sent.

The role that decides for people also carries the world's budget for its minds (``budget``: US
dollars and decisions in any hour of real time, and whether a person set it or it is the policy
catalog's figures) and what the world has asked in the hour just past (``hour_so_far``), which is
what the host weighs before each ask. ``POST {role_key}/budget`` sets the budget: one appended
record naming who set it (:mod:`exulanica.world.minds_budget`). It asks no model and spends
nothing; it bounds what playing the world may then spend.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.capabilities import (
    AVAILABLE,
    Availability,
    Effect,
    Operation,
    describe,
    installation_facts_of,
    surface,
    unavailable,
    unsupported,
)
from exulanica.api.decision_host import offered_providers, world_hour
from exulanica.api.dependencies import (
    CurrentSession,
    HeldPermissions,
    ScopedConnection,
    get_services,
)
from exulanica.api.role_hosts import (
    ROLE_HOSTS,
    ROLE_SUBJECT_UNSUPPORTED,
    RoleChoiceRefused,
    RoleContext,
    choice_status,
    version_engine,
)
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.spending.status import SpendingRefusals
from exulanica.world.decision_roles import DecisionRole, RoleRefused, decision_roles
from exulanica.world.minds_budget import (
    DECISIONS_MAXIMUM,
    MindsBudgetRefused,
    MindsBudgetRepository,
)
from exulanica.world.traffic_host import traffic_clock
from exulanica.world.worlds import require_world

__all__ = ["BUDGET_NOT_FOR_THIS_ROLE", "BUDGET_PROFILE", "PROFILE", "role_operations", "router"]

PROFILE: Final = "exulanica.world-models/v1"
BUDGET_PROFILE: Final = "exulanica.world-minds-budget-read/v1"
#: A budget is set for the role whose host weighs it before each ask: the one that decides for
#: people. Another role's asks are bounded by its own contract's figures.
BUDGET_NOT_FOR_THIS_ROLE: Final = "budget_not_for_this_role"
router = APIRouter(prefix="/world/versions/{version_id}/models", tags=["world"])


class ChosenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]


class RoleChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    subjects: Annotated[list[str], Field(min_length=1, max_length=512)]
    model: ChosenModel | None


class MindsBudgetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    #: US dollars in any hour of real time, as a decimal with at most six decimals.
    usd_per_hour: Annotated[
        str, Field(min_length=1, max_length=13, pattern=r"^[0-9]{1,6}(\.[0-9]{1,6})?$")
    ]
    #: Model decisions in any hour of real time.
    decisions_per_hour: Annotated[int, Field(ge=0, le=DECISIONS_MAXIMUM)]


def _version(
    connection: ScopedConnection, workspace_id: uuid.UUID, world_id: str, version_id: uuid.UUID
) -> dict[str, Any] | None:
    return connection.execute(
        "select source_snapshot_id from world_alternate_version where workspace_id=%s "
        "and world_id=%s and version_id=%s",
        (workspace_id, world_id, version_id),
    ).fetchone()


def _budget_read(
    connection: ScopedConnection,
    workspace_id: uuid.UUID,
    world_id: str,
    role: DecisionRole,
    engine: str | None,
) -> dict[str, Any] | None:
    """The world's budget for ``role``'s minds and what the world asked in the hour just past, as
    the host weighs them; None for a role whose asks no budget bounds."""
    if role.subject != "person":
        return None
    hosting = _hosting(engine, role)
    contract = role.contract() if hosting is None else role.contract(role.terms(hosting).versions)
    budget = MindsBudgetRepository(connection, workspace_id, world_id=world_id).current(
        role, contract
    )
    asked, spent = world_hour(connection, workspace_id, world_id, role)
    return {
        "budget": budget.view(),
        "hour_so_far": {"decisions": asked, "usd": str(spent.quantize(Decimal("0.000001")))},
    }


def _spent(role: DecisionRole, spending: SpendingRefusals | None) -> SpendingRefused | None:
    """The durable authority's refusal of every ask for ``role``, once the allowance of every
    provider its models are served by is spent; None while one has allowance left, or in a
    process no durable authority admits."""
    if spending is None:
        return None
    return spending.every(offered_providers(role, load_manifest(), role.contract()))


def _operation(
    context: RoleContext,
    role: DecisionRole,
    state: Availability,
    host_refusal: str | None,
    spent: SpendingRefused | None,
) -> Operation:
    """The choice of ``role``'s model as a capability read names it: this route's ``POST``."""
    host = ROLE_HOSTS.get(role.subject)
    # A choice is recorded whether or not this host asks the model; which it does is said here:
    # this process's own refusal first, as a call meets its fuse before the durable authority.
    if host_refusal is not None:
        decisions = unavailable(host_refusal)
    elif spent is not None:
        decisions = unavailable(spent.reason)
    else:
        decisions = AVAILABLE
    return Operation(
        endpoint=choose_world_model,
        availability=state,
        subject=role.subject,
        bind={"version_id": str(context.version_id), "role_key": role.key},
        subjects=None if host is None else host.subjects(role, world_models),
        idempotency="idempotency_key",
        options=(world_models,),
        effects=() if state.state != "available" else (Effect("decisions", decisions),),
    )


def role_operations(
    context: RoleContext, *, spending: SpendingRefusals | None = None
) -> list[Operation]:
    """Each registered role's model choice, as a world's capability read lists it; ``spending``
    is what the read found of the workspace's durable allowance
    (``Services.spending_refusals``)."""
    services = get_services(context.request)
    engine = version_engine(context)
    found = []
    for role in decision_roles():
        host = ROLE_HOSTS.get(role.subject)
        state = (
            unsupported(ROLE_SUBJECT_UNSUPPORTED)
            if host is None
            else host.availability(context, role)
        )
        found.append(
            _operation(
                context,
                role,
                state,
                services.model_host_refusal(
                    context.session.workspace_id, role, _hosting(engine, role)
                ),
                _spent(role, spending),
            )
        )
    return found


@router.get("")
def world_models(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    world_id: WorldId,
) -> Any:
    require_world(connection, session.workspace_id, world_id)
    version = _version(connection, session.workspace_id, world_id, version_id)
    if version is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "world version"}
        )
    context = RoleContext(
        connection, session, request, world_id, version_id, version["source_snapshot_id"]
    )
    services = get_services(request)
    routes = surface(request.app)
    spending = services.spending_refusals(connection, session.workspace_id)
    facts = installation_facts_of(services)
    engine = version_engine(context)
    roles = []
    for role in decision_roles():
        host = ROLE_HOSTS.get(role.subject)
        host_refusal = services.model_host_refusal(
            session.workspace_id, role, _hosting(engine, role)
        )
        if host is None:
            state = unsupported(ROLE_SUBJECT_UNSUPPORTED)
            fields: dict[str, Any] = {"available": False, "reason": ROLE_SUBJECT_UNSUPPORTED}
        else:
            read = host.read(context, role)
            state, fields = read.availability, dict(read.fields)
        roles.append(
            {
                "key": role.key,
                "subject": role.subject,
                **fields,
                "host_refusal": host_refusal,
                "model_subjects_maximum": role.contract().value(role.subjects_bound),
                "contract": role.contract().binding(),
                **(_budget_read(connection, session.workspace_id, world_id, role, engine) or {}),
                "capability": describe(
                    _operation(context, role, state, host_refusal, _spent(role, spending)),
                    routes,
                    held,
                    facts,
                ),
            }
        )
    return {
        "profile": PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        "clock_second": traffic_clock(),
        "roles": roles,
    }


@router.post("/{role_key}")
def choose_world_model(
    role_key: str,
    version_id: uuid.UUID,
    body: RoleChoiceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    require_world(connection, session.workspace_id, world_id)
    version = _version(connection, session.workspace_id, world_id, version_id)
    if version is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "world version"}
        )
    try:
        role = decision_roles().role(role_key)
    except RoleRefused as exc:
        return JSONResponse(status_code=404, content={"code": exc.code, "detail": str(exc)})
    host = ROLE_HOSTS.get(role.subject)
    if host is None:
        return JSONResponse(
            status_code=409,
            content={"code": ROLE_SUBJECT_UNSUPPORTED, "detail": role.subject},
        )
    context = RoleContext(
        connection, session, request, world_id, version_id, version["source_snapshot_id"]
    )
    try:
        return host.record_choice(
            context,
            role,
            request_id=body.idempotency_key,
            subjects=body.subjects,
            model=None if body.model is None else body.model.model_dump(),
        )
    except RoleChoiceRefused as exc:
        return JSONResponse(
            status_code=choice_status(exc.code), content={"code": exc.code, "detail": exc.detail}
        )


def _hosting(engine: str | None, role: DecisionRole) -> str | None:
    """The version's society ``engine`` where it asks ``role``'s subjects, so their budget is judged
    under the contract it asks them under; else None (the role's own contract)."""
    return engine if engine is not None and role.hosted_by(engine) else None


@router.post("/{role_key}/budget")
def set_world_minds_budget(
    role_key: str,
    version_id: uuid.UUID,
    body: MindsBudgetBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """Set what this world may spend on the model minds of its beings, in any hour of real time.

    One appended record of the world, naming who set it; the newest is the budget, and the same
    request asked again answers the record it made. It asks no model and spends nothing. The
    process's own budget, a deployment's allowance and the spending authority's grants still
    bound every call, so a budget only lowers what the host allows.
    """
    require_world(connection, session.workspace_id, world_id)
    version = _version(connection, session.workspace_id, world_id, version_id)
    if version is None:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": "world version"}
        )
    try:
        role = decision_roles().role(role_key)
    except RoleRefused as exc:
        return JSONResponse(status_code=404, content={"code": exc.code, "detail": str(exc)})
    if role.subject != "person":
        return JSONResponse(
            status_code=409,
            content={"code": BUDGET_NOT_FOR_THIS_ROLE, "detail": role.subject},
        )
    try:
        MindsBudgetRepository(connection, session.workspace_id, world_id=world_id).record(
            role,
            request_id=body.idempotency_key,
            usd_per_hour=body.usd_per_hour,
            decisions_per_hour=body.decisions_per_hour,
            set_by=session.actor,
        )
    except MindsBudgetRefused as exc:
        return JSONResponse(
            status_code=409 if exc.code == "budget_key_reused" else 422,
            content={"code": exc.code, "detail": exc.detail},
        )
    context = RoleContext(
        connection, session, request, world_id, version_id, version["source_snapshot_id"]
    )
    read = _budget_read(connection, session.workspace_id, world_id, role, version_engine(context))
    return {
        "profile": BUDGET_PROFILE,
        "world_id": world_id,
        "version_id": str(version_id),
        "role_key": role.key,
        **(read or {}),
    }
