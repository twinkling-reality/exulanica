"""Which model runs which people of a purposeful society: read, and chosen by the world's owner.

``GET /world/versions/{version_id}/society/models`` says what a person reading the People panel
needs: the models this server may ask for a person's decisions, each in plain words with whether
it can be asked here and why not; whether this host asks models for this world at all; each
person's current choice, with why its model is not asked here when it is not; each person's
latest decision and what its minute did; per model, how many decisions were asked, accepted and
applied, why the rest were not, and what they took and cost, over the society's latest
``DECISIONS_READ`` decisions; and who an outside program decides for, each with its latest
decision under its grant among those. ``POST`` at the same path records one choice, for one
person or a group, of a model the manifest offers a person's decisions or of their own routine (no
model). A choice is world data: append-only, with who made it; this host asking the model is the
host's own business, stated in the read, never a reason to refuse the choice.

Both serve the decision role that decides for a society's people, as the role registry states it
(:mod:`exulanica.world.decision_roles`): its offered models, its contract and its receipts. Neither
route asks a model. The host's playback asks, before a minute, for a workspace its environment
lists (``exulanica.api.decision_host``).
"""

from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.decision_host import HOST_REFUSALS
from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.api.world_scope import WorldId
from exulanica.door.outside import outside_deciders
from exulanica.models.manifest import load_manifest
from exulanica.models.usage import usd_string
from exulanica.world.deciders import is_played
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleRefused,
    decision_roles,
)
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society/models", tags=["society"])

__all__ = [
    "CHOICE_CONFLICTS",
    "HOST_REFUSALS",
    "PROFILE",
    "offered_models",
    "router",
    "society_models_view",
]

PROFILE: Final = "exulanica.society-models/v1"
#: How many of a society's latest person decisions one read counts, so a read never grows with
#: the world's age: at the contract's hourly bound, some hours of a world's decisions.
DECISIONS_READ: Final = 2000
#: A refusal of a choice answered with 409 rather than 422: the society or the key, not the body.
#: ``/world/versions/{version_id}/models/{role_key}`` answers a choice of any role by this too. A
#: choice naming a being a person plays is refused whole (``being_played``), as the play routes
#: refuse it.
CHOICE_CONFLICTS: Final = frozenset(
    {"engine_takes_no_model_choice", "choice_key_reused", "decided_from_outside", "being_played"}
)
#: What the People panel shows: a society's people, so these routes serve the role that decides
#: for them, as its registry entry names what it decides for.
SUBJECT: Final = "person"
#: What an outside entry says of its subject's latest decision by the program its grant opens to.
OUTSIDE_LATEST: Final = ("decision_seq", "base_tick", "consumed_tick", "status", "reason")


def _people_role() -> DecisionRole:
    """The one registered role deciding for a society's people, or a refusal by name, which both
    routes answer as a named problem (:func:`_role_refused`)."""
    found = [role for role in decision_roles() if role.subject == SUBJECT]
    if len(found) != 1:
        raise RoleRefused(
            "role_not_registered", f"the registry states {len(found)} roles deciding for people"
        )
    return found[0]


def _role_refused(exc: RoleRefused) -> JSONResponse:
    """A registry that states no one role deciding for people: this server takes no choice of a
    model for anybody's people, said by name as an engine that takes none is (409)."""
    return JSONResponse(status_code=409, content={"code": exc.code, "detail": exc.detail})


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


def _with_latest(
    outside: list[dict[str, Any]], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Each outside entry, in its order, with its subject's latest receipt among ``decisions``
    whose decider is the entry's own grant (``latest``), or None when none of them is. A turn the
    program left without a usable answer has such a receipt, with the outside reason the routine
    decided for; another grant's receipts, or another subject's, are never an entry's."""
    held: dict[tuple[str, str], dict[str, Any]] = {}
    for decision in decisions:  # in decision order, so the last one kept is the latest
        decider = decision["decider"]
        if decider["kind"] == "external":
            held[(decision["subject_id"], decider["grant_id"])] = decision
    return [
        {
            **entry,
            "latest": None
            if (decision := held.get((entry["subject_id"], entry["grant_id"]))) is None
            else {key: decision[key] for key in OUTSIDE_LATEST},
        }
        for entry in outside
    ]


def _played(choice: dict[str, Any], session: CurrentSession) -> dict[str, Any]:
    """What a read says of a person playing a being: that a person plays it, and whether it is
    the reader (``played_by_you``); never which account, nor who chose."""
    return {
        "decider": {"kind": "person"},
        "chosen_by": None,
        "played_by_you": choice["decider"]["account_id"] == str(session.actor),
    }


@router.get("")
def society_models(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    try:
        return society_models_view(version_id, connection, session, request, world_id)
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    except RoleRefused as exc:
        return _role_refused(exc)


def offered_models(
    role: DecisionRole, services: Services, contract: DecisionContract | None = None
) -> list[dict[str, Any]]:
    """Every model the manifest offers ``role`` that ``contract`` can ask (the role's own where
    none is given), each in the words a read names it by and with why this process asks nothing
    its provider serves, if it asks nothing. The world's own models read names every role's models
    this way; a society's read names them under the contract its engine is asked under."""
    manifest = load_manifest()
    contract = role.contract() if contract is None else contract
    models = []
    for spec in manifest.offered_models(role.chosen):
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
    return models


def society_models_view(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: str,
) -> dict[str, Any]:
    """What the read answers, or the refusal it answers by name: :class:`UnavailableSocietyInput`
    when the society's inputs may not be read now, :class:`RoleRefused` when the registry states
    no one role deciding for people. The world's own models read serves the same view."""
    society = _society(connection, session, request, world_id)
    role = _people_role()
    snapshot = society.snapshot(version_id)
    engine = society_engine(snapshot["profile"])
    manifest = load_manifest()
    contract = role.contract()
    repository = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    # Each person a choice decides for, with where it comes from: their own choice, or the group
    # choice of the gate a visitor came through (within the bound of the contract the society's
    # engine is asked under, as the host reads it).
    asked = role.contract(role.terms(snapshot["profile"]).versions)
    choices = repository.deciding(version_id, role, asked)
    travellers = repository.traveller_choices(version_id, role)
    decisions = (
        SocietyDecisionRepository(society).role_decisions(
            role, version_id, latest=DECISIONS_READ, authorized=snapshot
        )
        if engine.owner_model_choice
        else []
    )
    services = get_services(request)
    refusals: dict[tuple[str, str], str | None] = {}

    def refusal(model: dict[str, str]) -> str | None:
        """Each chosen model's refusal, judged once for however many people it runs."""
        key = (model["provider"], model["model_id"])
        if key not in refusals:
            refusals[key] = services.choice_refusal(
                role, model, connection, session.workspace_id, snapshot["profile"]
            )
        return refusals[key]

    models = offered_models(role, services, asked)
    # What models decided: an outside program's decisions name no model, and are read by its own
    # door's routes, not summarised here among the models'.
    asked_models = [decision for decision in decisions if decision["decider"]["kind"] == "model"]
    latest: dict[str, dict[str, Any]] = {}
    for decision in asked_models:
        latest[decision["subject_id"]] = decision
    return {
        "profile": PROFILE,
        "society_id": str(snapshot["society_id"]),
        "engine": snapshot["profile"],
        "takes_model_choices": engine.owner_model_choice,
        "host_refusal": services.model_host_refusal(
            session.workspace_id, role, snapshot["profile"]
        ),
        "contract": {
            **contract.binding(),
            "model_people_maximum": contract.value(role.subjects_bound),
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
            | (_played(choice, session) if is_played(choice["decider"]) else {})
            for subject, choice in sorted(choices.items())
        ],
        # The mind each gate's travellers get when their arrival says the world decides for them.
        "travellers": [
            {
                "grant_id": grant_id,
                "choice_seq": choice["choice_seq"],
                "decider": choice["decider"],
                "model": None
                if choice["model"] is None
                else {**choice["model"], "name": manifest.model_name(choice["model"]["model_id"])},
            }
            for grant_id, choice in sorted(travellers.items())
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
            for summary in _by_model(asked_models)
        ],
        "decisions_read": {"counted": len(decisions), "maximum": DECISIONS_READ},
        # Every subject an outside program decides for now under a grant that stands, the world's
        # own people a grant names (came "run") and the visitors that crossed in ("crossed"), with
        # what the grant view says of its program and the subject's latest decision under that
        # grant among the decisions read. Added to this profile as optional fields: a reader that
        # predates them reads everything else unchanged, and absent means nobody.
        "outside": _with_latest(
            outside_deciders(
                connection,
                session.workspace_id,
                state=snapshot["state"],
                choices=choices,
                bridges=None if services.door is None else services.door.bridges,
            ),
            decisions,
        ),
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
        role = _people_role()
    except RoleRefused as exc:
        return _role_refused(exc)
    try:
        return repository.record_choice(
            version_id,
            role,
            request_id=body.idempotency_key,
            subjects=[str(person) for person in body.people],
            model=None if body.model is None else body.model.model_dump(),
            chosen_by=session.actor,
            manifest=load_manifest(),
            # The contract the society's engine asks its people under: a model it cannot ask, as
            # one not offered for the lines a society of things says, is refused here.
            contract=role.contract(role.terms(repository.engine(version_id)).versions),
        )
    except ModelChoiceRefused as exc:
        return JSONResponse(
            status_code=409 if exc.code in CHOICE_CONFLICTS else 422,
            content={"code": exc.code, "detail": exc.detail},
        )
