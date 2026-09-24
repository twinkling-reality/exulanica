"""Decision orchestration: short scoped transactions around a connection-free model call."""

from __future__ import annotations

import uuid
from dataclasses import replace

import psycopg
from fastapi import Request

from exulanica.api.dependencies import get_services
from exulanica.epistemics.hosted_requests import no_place_released
from exulanica.selection.validation import Session
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_decisions import SocietyDecisionProvider
from exulanica.world.society_repository import SocietyRepository


def request_decision(
    request: Request,
    session: Session,
    version_id: uuid.UUID,
    *,
    world_id: str = DEFAULT_WORLD_ID,
    request_id: uuid.UUID,
    subject_id: uuid.UUID,
    base_tick: int,
    base_state_sha256: str,
) -> dict:
    services = get_services(request)
    provider = getattr(request.app.state, "society_decision_provider", None)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)

    def repository(connection: psycopg.Connection) -> SocietyDecisionRepository:
        return SocietyDecisionRepository(
            SocietyRepository(
                connection,
                session.workspace_id,
                world_id=world_id,
                input_authorizer=None
                if authorizer is None
                else lambda doc: authorizer(connection, session, doc),
            )
        )

    with services.database.session(session.workspace_id) as connection, connection.transaction():
        reservation, fresh = repository(connection).prepare(
            version_id,
            request_id=request_id,
            subject_id=subject_id,
            base_tick=base_tick,
            base_state_sha256=base_state_sha256,
            provider_config=None if provider is None else provider.configuration,
        )
    if not fresh:
        return reservation
    # No connection or advisory/asset lock from the preparation phase survives here.
    if provider is None:
        result = {
            "status": "unavailable",
            "reason": "provider_not_configured",
            "proposal": None,
            "provider": None,
        }
    else:
        if isinstance(provider, SocietyDecisionProvider):
            # The workspace's rules go with the request; its policy opens its own short read-only
            # session as the request leaves, so the call itself still holds no connection. A
            # society decision releases no place's name: no use offers one, and a grant for the
            # Companion's roles describes the Companion's requests.
            provider = replace(
                provider,
                client=provider.client.with_policy(
                    services.request_policy(
                        session.workspace_id,
                        lambda: services.readonly_database.session(session.workspace_id),
                        released_places=no_place_released,
                    )
                ),
            )
        try:
            result = provider.propose(reservation["request"]["context"])
        except Exception:
            # Retain the reservation and a bounded failure receipt, never an exception string
            # that may contain private request bytes or credentials.
            result = {
                "status": "unavailable",
                "reason": "provider_adapter_failed",
                "proposal": None,
                "provider": None,
            }
    with services.database.session(session.workspace_id) as connection, connection.transaction():
        completed = repository(connection).finish(version_id, request_id, result)
    if completed["decision"]["reason"] == "decision_sources_unavailable":
        raise UnavailableSocietyInput("decision sources became unavailable during inference")
    return completed
