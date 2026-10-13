"""A selected world's subject, as read-only properties and offered actions."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from psycopg.pq import TransactionStatus

from exulanica.api.dependencies import CurrentSession, HeldPermissions, ScopedConnection
from exulanica.api.permissions import Requires, rule_for
from exulanica.api.routes.capabilities import version_capabilities_document, version_context
from exulanica.api.routes.society_control import repository as control_repository
from exulanica.api.routes.society_models import _people_role, _society
from exulanica.api.routes.world_models import _budget_read
from exulanica.api.subject_offer import SubjectOfferContext, subject_offer, subject_reference
from exulanica.api.thing_card import _card as read_card
from exulanica.api.world_scope import WorldId
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_presence import presence
from exulanica.world.workspace_lock import lock_workspace

router = APIRouter(tags=["world"])


@router.get(
    "/world/versions/{version_id}/subjects/{ref}",
    summary="A world, being or thing's properties and catalog actions, without performing them.",
)
def read_subject(
    version_id: uuid.UUID,
    ref: str,
    connection: ScopedConnection,
    session: CurrentSession,
    held: HeldPermissions,
    request: Request,
    world_id: WorldId,
) -> JSONResponse:
    def may_read(path: str) -> bool:
        rule = rule_for("GET", path)
        return isinstance(rule, Requires) and rule.permissions <= held

    try:
        idle = connection.info.transaction_status == TransactionStatus.IDLE
        with connection.transaction():
            # Final source authorization requires READ COMMITTED. The existing workspace
            # lock keeps version, society and choices coherent while their sources authorize.
            if idle:
                connection.execute("set transaction read only")
            lock_workspace(connection, session.workspace_id)
            context = version_context(version_id, connection, session, held, request, world_id)
            subject_type, ident = subject_reference(ref)
            cap = version_capabilities_document(
                version_id,
                connection=connection,
                session=session,
                held=held,
                request=request,
                world_id=world_id,
            )
            facts = {"society": "held" if context.society is not None else "absent"}
            read = {}
            card = play = control = budget = None
            placed_id = population = None
            role = _people_role()
            # The budget writer checks the registered person role and world version,
            # independently of whether a society has been brought in yet.
            budget_supported = role.subject == "person"
            if context.society is not None:
                society = _society(connection, session, request, world_id)
                if subject_type != "world":
                    assert ident is not None
                    # The card's own read returns its record. Reading the society a second
                    # time would reload input bytes under the card's final source barrier.
                    card, record = read_card(
                        connection,
                        context.services,
                        society,
                        workspace_id=session.workspace_id,
                        world_id=world_id,
                        version_id=version_id,
                        thing_id=ident,
                        reader=session.actor,
                    )
                    read = dict(card["society"])
                    placed_id = record.get("placed_id")
                    if subject_type == "being":
                        play = SocietyModelChoiceRepository(
                            connection,
                            session.workspace_id,
                            world_id=world_id,
                        ).preview_play(
                            version_id,
                            role,
                            subject=str(ident),
                            account_id=session.actor,
                        )
                else:
                    snapshot = society.snapshot(version_id)
                    state = snapshot["state"]
                    read = {
                        "tick": snapshot["current_tick"],
                        "state_sha256": snapshot["state_sha256"],
                    }
                    population = len(state["inhabitants"])
                    facts["presence"] = presence(state)
                    if may_read("/world/versions/{version_id}/society/control"):
                        control = control_repository(connection, session, request, world_id).read(
                            version_id, lock=False
                        )
                        facts["mode"] = control["mode"]
            if subject_type == "world" and may_read("/world/versions/{version_id}/models"):
                raw = _budget_read(
                    connection,
                    session.workspace_id,
                    world_id,
                    role,
                    None if context.engine is None else context.engine.engine,
                )
                if raw is not None:
                    safe = dict(raw["budget"])
                    setter = safe.pop("set_by", None)
                    safe["set_by_you"] = setter is not None and setter == str(session.actor)
                    budget = {"budget": safe, "hour_so_far": raw["hour_so_far"]}
            result = subject_offer(
                SubjectOfferContext(
                    capabilities=cap,
                    read=read,
                    facts=facts,
                    card=card,
                    placed_id=placed_id,
                    play=play,
                    control=control,
                    budget=budget,
                    population=population,
                    budget_supported=budget_supported,
                ),
                ref,
                held,
            )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    return JSONResponse(content=result, headers={"Cache-Control": "private, no-store"})
