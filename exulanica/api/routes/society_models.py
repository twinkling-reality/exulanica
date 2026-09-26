"""Which model runs which people of a purposeful society: read, and chosen by the world's owner.

``GET /world/versions/{version_id}/society/models`` says what a person reading the People panel
needs: the models this server may ask for a person's decisions, each in plain words with whether
it can be asked here and why not; whether this host asks models for this world at all; each
person's current choice, with why its model is not asked here when it is not; each person's
latest decision and what its minute did; and, per model, how many decisions were asked, accepted
and applied, why the rest were not, and what they took and cost, over the society's latest
``DECISIONS_READ`` decisions. ``POST`` at the same path records one choice, for one person or a
group, of a model the manifest offers a person's decisions or of their own routine (no model). A
choice is world data: append-only, with who made it; this host asking the model is the host's own
business, stated in the read, never a reason to refuse the choice.

Neither route asks a model. The host's playback asks, before a minute, for a workspace its
environment lists (``exulanica.api.society_person_decisions``).
"""

from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.society_person_decisions import HOST_REFUSALS
from exulanica.api.world_scope import WorldId
from exulanica.models.manifest import Role, load_manifest
from exulanica.models.usage import usd_string
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_contract import decision_contract
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/models", tags=["society"])

__all__ = ["HOST_REFUSALS", "PROFILE", "router"]

PROFILE: Final = "exulanica.society-models/v1"
#: How many of a society's latest person decisions one read counts, so a read never grows with
#: the world's age: at the contract's hourly bound, some hours of a world's decisions.
DECISIONS_READ: Final = 2000
#: A refusal the route answers with 409 rather than 422: the society or the key, not the body.
_CONFLICTS: Final = frozenset({"engine_takes_no_model_choice", "choice_key_reused"})


class ChosenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]


class ModelChoiceBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: uuid.UUID
    #: The people this choice is for: one person, or a group.
    people: Annotated[list[uuid.UUID], Field(min_length=1, max_length=512)]
    #: The model that decides for them, or null for their own routine.
    model: ChosenModel | None


def _society(
    connection: ScopedConnection, session: CurrentSession, request: Request, world_id: str
) -> SocietyRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyRepository(
        connection,
        session.workspace_id,
        world_id=world_id,
        input_authorizer=(
            None if authorizer is None else lambda doc: authorizer(connection, session, doc)
        ),
    )


def _nearest_rank(values: list[int], share: int) -> int | None:
    """The value at ``share`` percent of ``values`` by nearest rank, or None for none."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, -(-share * len(ordered) // 100) - 1)]


def _not_acted_on(decision: dict[str, Any]) -> str | None:
    """Why a settled decision was not acted on: the receipt's reason when the model was not
    followed, and the routine decided; or the minute's when it was followed and could not be
    acted on, or a person's own request or another decision came first. None when acted on or not
    yet taken up."""
    if decision["disposition"] in (None, "applied"):
        return None
    if decision["status"] != "accepted":
        return decision["reason"]
    return decision["disposition_reason"]


def _by_model(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What each model's decisions came to, the numbers a comparison of models reads."""
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for decision in decisions:
        grouped.setdefault((decision["provider"], decision["model_id"]), []).append(decision)
    summaries = []
    for (provider, model_id), rows in sorted(grouped.items()):
        asked = [row for row in rows if row["asked_model"]]
        latencies = [row["latency_ms"] for row in asked if row["latency_ms"] is not None]
        summaries.append(
            {
                "provider": provider,
                "model_id": model_id,
                "decisions": len(rows),
                "asked": len(asked),
                "accepted": sum(1 for row in rows if row["status"] == "accepted"),
                "applied": sum(1 for row in rows if row["disposition"] == "applied"),
                "by_reason": dict(sorted(Counter(row["reason"] for row in rows).items())),
                "by_disposition": dict(
                    sorted(Counter(row["disposition"] or "pending" for row in rows).items())
                ),
                "not_acted_on": dict(
                    sorted(
                        Counter(
                            reason for row in rows if (reason := _not_acted_on(row)) is not None
                        ).items()
                    )
                ),
                "latency_ms": {
                    "p50": _nearest_rank(latencies, 50),
                    "p95": _nearest_rank(latencies, 95),
                    "longest": max(latencies) if latencies else None,
                },
                "cost_usd": usd_string(
                    sum((Decimal(row["cost_usd"]) for row in asked), Decimal(0))
                ),
                "cost_known": all(row["cost_known"] for row in asked),
            }
        )
    return summaries


@router.get("")
def society_models(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    try:
        society = _society(connection, session, request, world_id)
        snapshot = society.snapshot(version_id)
        engine = society_engine(snapshot["profile"])
        choices = SocietyModelChoiceRepository(
            connection, session.workspace_id, world_id=world_id
        ).current(version_id)
        decisions = (
            SocietyDecisionRepository(society).person_decisions(version_id, latest=DECISIONS_READ)
            if engine.model_decisions and snapshot["profile"] == "exulanica-society/v2"
            else []
        )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    manifest = load_manifest()
    contract = decision_contract()
    services = get_services(request)
    refusals: dict[tuple[str, str], str | None] = {}

    def refusal(model: dict[str, str]) -> str | None:
        """Each chosen model's refusal, judged once for however many people it runs."""
        key = (model["provider"], model["model_id"])
        if key not in refusals:
            refusals[key] = services.choice_refusal(model, connection, session.workspace_id)
        return refusals[key]

    models = []
    for spec in manifest.offered_models(Role.SOCIETY_DECISION):
        mechanism = contract.mechanism_for(spec)
        if mechanism is None:
            continue
        models.append(
            {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "name": manifest.model_name(spec.model_id),
                "description": spec.description,
                "provider_description": manifest.provider(spec.provider).description,
                "mechanism": mechanism.value,
                "usd_per_mtok": {
                    "input": str(spec.input_usd_per_mtok),
                    "output": str(spec.output_usd_per_mtok),
                },
                "refusal": services.provider_refusal(spec.provider),
            }
        )
    latest: dict[str, dict[str, Any]] = {}
    for decision in decisions:
        latest[decision["subject_id"]] = decision
    return {
        "profile": PROFILE,
        "society_id": str(snapshot["society_id"]),
        "engine": snapshot["profile"],
        "takes_model_choices": snapshot["profile"] == "exulanica-society/v2",
        "host_refusal": services.model_host_refusal(session.workspace_id),
        "contract": {
            **contract.binding(),
            "model_people_maximum": contract.value("model_people_maximum"),
        },
        "models": models,
        # Each choice with why its model is not asked here, when it is not: the page says the
        # routine decides for now, and why, rather than naming a model nobody asks.
        # Every model the read mentions carries the name Manifest.model_name gives it, the one the
        # Companion uses too, so a model no longer offered is not called by its identifier here and
        # by its name there.
        "choices": [
            {
                "subject_id": subject,
                **choice,
                "model": None
                if choice["model"] is None
                else {**choice["model"], "name": manifest.model_name(choice["model"]["model_id"])},
                "refusal": None if choice["model"] is None else refusal(choice["model"]),
            }
            for subject, choice in sorted(choices.items())
        ],
        "latest": [
            {
                key: decision[key]
                for key in (
                    "subject_id",
                    "decision_seq",
                    "base_tick",
                    "consumed_tick",
                    "provider",
                    "model_id",
                    "status",
                    "reason",
                    "disposition",
                    "disposition_reason",
                    "chose",
                )
            }
            | {"name": manifest.model_name(decision["model_id"])}
            for _, decision in sorted(latest.items())
        ],
        "by_model": [
            {**summary, "name": manifest.model_name(summary["model_id"])}
            for summary in _by_model(decisions)
        ],
        "decisions_read": {"counted": len(decisions), "maximum": DECISIONS_READ},
    }


@router.post("")
def choose_society_model(
    version_id: uuid.UUID,
    body: ModelChoiceBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    require_world(connection, session.workspace_id, world_id)
    repository = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    try:
        return repository.record_choice(
            version_id,
            request_id=body.idempotency_key,
            people=[str(person) for person in body.people],
            model=None if body.model is None else body.model.model_dump(),
            chosen_by=session.actor,
            manifest=load_manifest(),
            contract=decision_contract(),
        )
    except ModelChoiceRefused as exc:
        return JSONResponse(
            status_code=409 if exc.code in _CONFLICTS else 422,
            content={"code": exc.code, "detail": exc.detail},
        )
