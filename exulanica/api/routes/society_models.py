"""Which model runs which people of a purposeful society: read, and chosen by the world's owner.

``GET /world/versions/{version_id}/society/models`` says what a person reading the People panel
needs: the models this server may ask for a person's decisions, each in plain words with whether
it can be asked here and why not; whether this host asks models for this world at all; each
person's current choice, with why its model is not asked here when it is not; each person's
latest decision and what its minute did; per model, how many decisions were asked, accepted and
applied, why the rest were not, and what they took and cost, over the society's latest
``DECISIONS_READ`` decisions; and who an outside program decides for, each with its latest
decision under its grant among those. ``GET .../models/history`` answers every choice made for the
version's people (``exulanica.society-model-history/v1``), newest first and bounded, each with
when it was recorded, whom it decides for and what (a model by its name, the routine, a person
playing, a program from outside), never who chose. ``POST`` at the same path records one choice,
for one person or a group, of a model the manifest offers a person's decisions or of their own
routine (no model). A choice is world data: append-only, with who made it; this host asking the
model is the host's own business, stated in the read, never a reason to refuse the choice.

Both serve the decision role that decides for a society's people, as the role registry states it
(:mod:`exulanica.world.decision_roles`): its offered models, its contract and its receipts. Neither
route asks a model. The host's playback asks, before a minute, for a workspace its environment
lists (``exulanica.api.decision_host``).
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from decimal import Decimal
from statistics import median_low
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.decision_admission import request_tokens_at_most
from exulanica.api.decision_host import HOST_REFUSALS, ask_bound_usd
from exulanica.api.dependencies import (
    CurrentSession,
    ScopedConnection,
    get_services,
    holds_as_guest,
)
from exulanica.api.runner_models import runner_model_name, runner_rows
from exulanica.api.services import Services
from exulanica.api.session_spending import bound_key
from exulanica.api.world_scope import WorldId
from exulanica.door.outside import outside_deciders
from exulanica.models.budget import BudgetGuard
from exulanica.models.local_runner import checked_ms
from exulanica.models.manifest import Manifest, load_manifest
from exulanica.models.model_cards import model_card
from exulanica.models.usage import USD_QUANTUM, usd_string
from exulanica.spending.status import SpendingRefusals
from exulanica.world.deciders import is_played
from exulanica.world.decision_measures import by_being, measures, nearest_rank
from exulanica.world.decision_roles import (
    DecisionContract,
    DecisionRole,
    RoleRefused,
    decision_roles,
)
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_control_repository import open_session_receipt
from exulanica.world.society_decision_repository import SocietyDecisionRepository
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import (
    ModelChoiceRefused,
    SocietyModelChoiceRepository,
)
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.trajectories import (
    build_trajectory_bundle,
    format_dpo_jsonl,
    format_openai_tool_jsonl,
    format_openenv_jsonl,
    format_trajectory_jsonl,
)
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/society", tags=["society"])

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
#: The decision requests an open run's own bounds admitted an attempt for: each attempt of a
#: person's decision is admitted under the run's bound of its provider as ``decision:<request>#n``
#: (``exulanica.api.session_spending``), so a receipt belongs to this run by its request alone.
_RUN_REQUESTS: Final = """
select distinct split_part(substr(x.request_key, 10), '#', 1) as request_id
  from spending_reservation x
  join spending_grant g on g.workspace_id = x.workspace_id and g.grant_id = x.bound_id
 where x.workspace_id = %(workspace)s and starts_with(g.bound_key, %(bound)s)
   and starts_with(x.request_key, 'decision:')
"""


_LOG = logging.getLogger(__name__)
#: Prices a model's stated most for one decision (``ask_bound_usd``); it admits and holds nothing.
_ESTIMATOR: Final = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)


def _spending(services: Services, connection: Any, workspace: uuid.UUID) -> SpendingRefusals | None:
    """The workspace's spending as the durable authority would answer its next attempts, read once
    on the request's connection under a savepoint, or None where nothing reads it or the read
    fails (admission still refuses each attempt)."""
    try:
        with connection.transaction():
            return services.spending_refusals(connection, workspace)
    except Exception as exc:
        # Never the exception's text, which may carry a connection string.
        _LOG.warning("the spending state could not be read: %s", type(exc).__qualname__)
        return None


def spend_here_usd(spending: SpendingRefusals | None, guest: bool) -> dict[str, str] | None:
    """What a guest has left for AI models here, by provider, as the host holds each attempt against
    it; None on a person's own install or where the spending read gave nothing. A guest's chooser
    sets a model whose stated most for one attempt is above it faint (U2)."""
    if not guest or spending is None:
        return None
    return {provider: format(usd, "f") for provider, usd in sorted(spending.available_usd.items())}


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


def _middle_cost(asked: list[dict[str, Any]]) -> dict[str, Any]:
    """The middle of a model's known decision costs here and how many there are (G2)."""
    costs = [Decimal(row["cost_usd"]) for row in asked if row["cost_known"]]
    return {
        "cost_median_usd": usd_string(median_low(costs)) if costs else None,
        "costs_counted": len(costs),
    }


def _run_spending(
    connection: ScopedConnection,
    workspace_id: uuid.UUID,
    society_id: uuid.UUID,
    decisions: list[dict[str, Any]],
    full: bool,
) -> dict[str, Any] | None:
    """What each person's model has spent in the society's open run (D9): among ``decisions``,
    the stored receipts whose request the run's own bounds admitted an attempt for, by person,
    with their known costs summed and how many costs are not known yet (``run_spending``); None
    while no run is open. A person with no such receipt has no entry, and nothing is estimated.
    Where the read holds as many decisions as it may (``full``) and the run asked for a request
    none of them is, the read did not reach all of the run's receipts and the figures may read
    low: ``run_spending_partial`` says so, so a page says "at least"."""
    opened = open_session_receipt(connection, workspace_id, society_id)
    if opened is None:
        return None
    rows = connection.execute(
        _RUN_REQUESTS,
        {"workspace": workspace_id, "bound": bound_key(opened["session_id"], "")},
    ).fetchall()
    requests = {str(row["request_id"]) for row in rows}
    held: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        if str(decision["request_id"]) in requests:
            held.setdefault(decision["subject_id"], []).append(decision)
    entries = [
        {
            "subject_id": subject_id,
            "decisions": len(receipts),
            "known_cost_usd": usd_string(
                sum((Decimal(row["cost_usd"]) for row in receipts if row["cost_known"]), Decimal(0))
            ),
            "costs_unknown": sum(1 for row in receipts if not row["cost_known"]),
        }
        for subject_id, receipts in sorted(held.items())
    ]
    reached = {str(decision["request_id"]) for decision in decisions}
    partial = full and not requests <= reached
    return {"run_spending": entries, **({"run_spending_partial": True} if partial else {})}


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
                    "p50": nearest_rank(latencies, 50),
                    "p95": nearest_rank(latencies, 95),
                    "longest": max(latencies) if latencies else None,
                },
                "cost_usd": usd_string(
                    sum((Decimal(row["cost_usd"]) for row in asked), Decimal(0))
                ),
                "cost_known": all(row["cost_known"] for row in asked),
                # The middle of the known costs of its decisions here, one of them (the lower of
                # two), and how many it is the middle of: "about $Y a decision" (G2).
                **_middle_cost(asked),
                # Counts, rates with their sample, timeouts, repetition, latency and cost basis,
                # added to the profile as an optional field (decision_measures).
                "measures": measures(rows),
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


#: The most choices one history read answers, and how many it answers unless asked.
HISTORY_MAXIMUM: Final = 500
HISTORY_DEFAULT: Final = 200


@router.get(
    "/models/history",
    summary="Every model choice made for the version's people, newest first, with when.",
)
def society_model_history(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    limit: Annotated[int, Query(ge=1, le=HISTORY_MAXIMUM)] = HISTORY_DEFAULT,
    before: Annotated[int | None, Query(ge=1)] = None,
) -> Any:
    try:
        role = _people_role()
    except RoleRefused as exc:
        return _role_refused(exc)
    repository = SocietyModelChoiceRepository(connection, session.workspace_id, world_id=world_id)
    manifest = load_manifest()
    services = get_services(request)
    views = [
        view
        for view in reversed(repository.history(version_id, role))
        if before is None or view["choice_seq"] < before
    ]
    shown = views[:limit]
    return JSONResponse(
        content={
            "profile": "exulanica.society-model-history/v1",
            "version_id": str(version_id),
            "choices": [
                {
                    "choice_seq": view["choice_seq"],
                    "recorded_at": view["recorded_at"].isoformat(),
                    "subjects": list(view.get(role.choice_subjects) or []),
                    # What decides, never which account or grant chose or plays.
                    "decider": {"kind": view["decider"]["kind"]},
                    "model": None
                    if view["model"] is None
                    else {
                        "provider": view["model"]["provider"],
                        "model_id": view["model"]["model_id"],
                        # A model a person's runner held is named by its kept check.
                        "name": runner_model_name(services, view["model"]["model_id"])
                        or manifest.model_name(view["model"]["model_id"]),
                    },
                    "ended": bool(view.get("ended", False)),
                }
                for view in shown
            ],
            "more": len(views) > len(shown),
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/models")
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


@router.get(
    "/trajectories",
    summary="Export verified world decision trajectories and counterfactual pairs.",
)
def society_trajectories(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    format: Annotated[Literal["json", "jsonl", "openai", "openenv", "dpo"] | None, Query()] = None,
    kind: Annotated[Literal["all", "sft", "dpo"] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=DECISIONS_READ)] = DECISIONS_READ,
    subject_id: Annotated[uuid.UUID | None, Query()] = None,
    request_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Any:
    try:
        role = _people_role()
        society = _society(connection, session, request, world_id)
        bundle = build_trajectory_bundle(
            society,
            version_id,
            role=role,
            limit=limit,
            subject_id=subject_id,
            request_id=request_id,
        )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
        )
    except RoleRefused as exc:
        return _role_refused(exc)

    payload = bundle.to_dict()
    if kind == "sft":
        payload["dpo_pairs"] = []
    elif kind == "dpo":
        payload["sft_records"] = []

    if format == "jsonl":
        return Response(
            content=format_trajectory_jsonl(payload),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "private, no-store"},
        )
    if format == "openai":
        return Response(
            content=format_openai_tool_jsonl(payload["sft_records"]),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "private, no-store"},
        )
    if format == "openenv":
        return Response(
            content=format_openenv_jsonl(
                payload["sft_records"],
                world_id=world_id,
                version_id=str(version_id),
            ),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "private, no-store"},
        )
    if format == "dpo":
        return Response(
            content=format_dpo_jsonl(payload["dpo_pairs"]),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "private, no-store"},
        )
    return JSONResponse(
        content=payload,
        headers={"Cache-Control": "private, no-store"},
    )


def offered_models(
    role: DecisionRole,
    services: Services,
    contract: DecisionContract | None = None,
    *,
    manifest: Manifest | None = None,
) -> list[dict[str, Any]]:
    """Every model the manifest offers ``role`` that ``contract`` can ask (the role's own where
    none is given), each in the words a read names it by, with what its maker says of it (its
    card, or ``None``: :mod:`exulanica.models.model_cards`) and with why this process asks nothing
    its provider serves, if it asks nothing. A model served from this computer, which costs
    nothing, comes first; the rest keep the manifest's order. The world's own models read names
    every role's models this way; a society's read names them under the contract its engine is
    asked under."""
    manifest = load_manifest() if manifest is None else manifest
    contract = role.contract() if contract is None else contract
    attempts = contract.value("answer_attempts_maximum")
    models = []
    for spec in manifest.offered_models(role.chosen):
        mechanism = contract.mechanism_for(spec)
        if mechanism is None:
            continue
        card = model_card(spec.model_id)
        # The check kept for a model a person's own runner holds, read only for such a model.
        checks = None if spec.served_as is None else services.local_checks
        kept = None if checks is None else checks.kept(spec.model_id)
        most = ask_bound_usd(role, _ESTIMATOR, spec, contract)
        models.append(
            {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "name": manifest.model_name(spec.model_id),
                "description": spec.description,
                "provider_description": manifest.provider(spec.provider).description,
                # A model its provider serves from this computer, which bills nothing and is sent
                # no credential: the model list words it "On this computer · Free".
                "on_this_computer": manifest.provider(spec.provider).on_this_computer,
                "mechanism": mechanism.value,
                "usd_per_mtok": {
                    "input": str(spec.input_usd_per_mtok),
                    "output": str(spec.output_usd_per_mtok),
                },
                # How much it reads at once, as its manifest entry states it (G2's "Reads").
                "context_window_tokens": spec.context_window_tokens,
                "refusal": services.provider_refusal(spec.provider),
                "source": "shipped_manifest"
                if spec.model_id in load_manifest().models
                else "this_computer_check"
                if spec.served_as is not None
                else "workspace_probe",
                "fresh_rates_required": spec.model_id not in load_manifest().models
                and spec.served_as is None,
                "card": None if card is None else card.served(),
                # The most one decision with it may cost: every attempt the contract allows, each at
                # the role's request envelope and the model's answer bound (E1); and one attempt's,
                # which a guest's chooser and asking again fade a model at (U2).
                "decision_most_usd": format(most, "f"),
                "attempt_most_usd": format((most / attempts).quantize(USD_QUANTUM), "f"),
            }
            # A model a person's own runner holds, as the runner states it: its family and size,
            # the name it serves it by now, and the licence it states, quoted and never classed.
            | (
                {}
                if spec.served_as is None
                else {
                    "runner": {
                        "family": None if kept is None else kept.get("family"),
                        "size": None if kept is None else kept.get("parameter_size"),
                        "served_as": spec.served_as,
                        "licence": None if kept is None else kept.get("licence"),
                        # How long its check's slowest case took to answer, which its row tells.
                        "checked_ms": checked_ms(kept),
                    }
                }
            )
        )
    # Free first: what this computer serves before what a provider bills, each in its order.
    return sorted(models, key=lambda model: not model["on_this_computer"])


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
    services = get_services(request)
    manifest = services.workspace_choice_manifest(
        connection, session.workspace_id, snapshot["profile"]
    )
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

    models = offered_models(role, services, asked, manifest=manifest)

    def name_of(model_id: str) -> str:
        """The name a person reads for a model the read mentions: the manifest's, or for a model
        a person's runner held, the one its kept check gives, whether or not it still holds it."""
        if model_id not in manifest.models:
            return runner_model_name(services, model_id) or manifest.model_name(model_id)
        return manifest.model_name(model_id)

    # What models decided: an outside program's decisions name no model, and are read by its own
    # door's routes, not summarised here among the models'.
    asked_models = [decision for decision in decisions if decision["decider"]["kind"] == "model"]
    latest: dict[str, dict[str, Any]] = {}
    for decision in asked_models:
        latest[decision["subject_id"]] = decision
    spending = _spending(services, connection, session.workspace_id)
    here = spend_here_usd(spending, holds_as_guest(request))
    run = _run_spending(
        connection,
        session.workspace_id,
        snapshot["society_id"],
        asked_models,
        full=len(decisions) >= DECISIONS_READ,
    )
    return {
        "profile": PROFILE,
        "society_id": str(snapshot["society_id"]),
        "engine": snapshot["profile"],
        "takes_model_choices": engine.owner_model_choice,
        # Whether a person's recorded decisions may be asked again of another model here (an
        # optional field: a read without it is a server that asks them); a page offers Compare
        # by it.
        "asks_again": services.asks_again,
        "host_refusal": services.model_host_refusal(
            session.workspace_id, role, snapshot["profile"], spending=spending
        ),
        "contract": {
            **contract.binding(),
            "model_people_maximum": contract.value(role.subjects_bound),
            # The largest request a decision here may send, in tokens, as its reserve counts it;
            # a model's context window is read against it (G2). None where no envelope is stated.
            "request_tokens_at_most": request_tokens_at_most(role, asked),
        },
        "models": models,
        # Every model a person's own runner serves beside the manifest's, able (also offered in
        # ``models``), being checked, or not able and why; an optional field, empty where nothing
        # is checked here.
        "runner_models": runner_rows(services, snapshot["profile"]),
        # A guest's page only: what they have left for AI models here, by provider (U2); an
        # optional field, absent on a person's own install.
        **({} if here is None else {"spend_here_usd": here}),
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
                else {**choice["model"], "name": name_of(choice["model"]["model_id"])},
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
                else {**choice["model"], "name": name_of(choice["model"]["model_id"])},
            }
            for grant_id, choice in sorted(travellers.items())
        ],
        "latest": [
            {
                key: decision[key]
                for key in (
                    "request_id",
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
            | {"name": name_of(decision["model_id"])}
            for _, decision in sorted(latest.items())
        ],
        "by_model": [
            {**summary, "name": name_of(summary["model_id"])} for summary in _by_model(asked_models)
        ],
        # The same measures for each being under each model, added as an optional field: what a
        # page says of how a being is doing is read here, never recomputed.
        "by_being": [
            {**entry, "name": name_of(entry["model_id"])} for entry in by_being(asked_models)
        ],
        # What each person's model has spent in the open run, from its stored receipts, an
        # optional field absent while no run is open (D9): a page says it beside the run's time,
        # "at least" where the read did not reach all of the run's receipts.
        **({} if run is None else run),
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


@router.post("/models")
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
            manifest=get_services(request).workspace_choice_manifest(
                connection, session.workspace_id, repository.engine(version_id)
            ),
            # The contract the society's engine asks its people under: a model it cannot ask, as
            # one not offered for the lines a society of things says, is refused here.
            contract=role.contract(role.terms(repository.engine(version_id)).versions),
        )
    except ModelChoiceRefused as exc:
        return JSONResponse(
            status_code=409 if exc.code in CHOICE_CONFLICTS else 422,
            content={"code": exc.code, "detail": exc.detail},
        )
