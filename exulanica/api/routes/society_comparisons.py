"""The comparisons of the models that ran a world's people: read, planned and started.

``GET /world/versions/{version_id}/society/comparisons`` lists a version's comparisons, newest
first, each with its arms, the group they decide for and how far its runs got. ``GET
.../comparisons/{comparison_id}`` gives one comparison's scores, per seed and per arm, with
intervals, what each arm's model answered beside every score, who decides for everybody outside
the group, its registered differences and the server's verdict, which is the only source of the
words a page shows for it. Both name every model a decider asks by ``Manifest.model_name``, as the
People panel's read does. ``GET .../comparisons/{comparison_id}/runs/{run_id}`` returns what the
page draws of one completed run: the place, each person's minutes, who decides for each of them and
what every turn did. It serves the drawing the host stored once it replayed the run from its stored
requests and receipts and verified it (:mod:`exulanica.world.society_comparison_drawing`), under the
digest of the code reading it, and otherwise replays the run itself, with no model call, and holds
the replay to what the run recorded; either way it asks the inputs' rights before it answers. A
replay that differs from its record is refused by name (``run_replay_mismatch``), never shown.

None of these asks a model or writes anything. A comparison started from the application also
serves its start: the bound its owner stated, what its asks spent, and where it stands. No response
carries a run's seed. A comparison this code cannot read, one naming a binding, catalogs, a
definition or a score version it does not hold, or whose outcomes scored other people than its
group, is answered by name as a conflict (409), never as a server error.

``POST .../comparisons/plan`` answers what a start would, and writes nothing: the roles, groups,
models and development seeds this server offers a comparison of the version's society, with why a
model cannot be asked here, and, for a selection, the runs it plans, the most it can cost and what
one like it typically cost, or the refusal a start of it would meet. ``POST .../comparisons``
starts one (:mod:`exulanica.api.society_comparison_start`): in one transaction it defines the
comparison through the one definition path the local command defines by, frozen at the society's
newest input or at an earlier stored one the caller names (``input_seq``), reserves every run and
records the start with the bound its owner stated, at most the most it can cost. A host's
comparison worker plays it off the request path (:mod:`exulanica.api.society_comparison_worker`).
The comparison's id is the caller's, keyed within its workspace: the same start sent again is
answered with the start it made, and every refusal is named (``START_REFUSALS``). Where a durable
spending authority admits this host's calls, a new start that would ask a provider whose allowance
is spent, an arm's model or the model an owner chose for somebody outside the group, is refused as
admission would refuse that first ask, 429 ``budget_exceeded`` with its ``spending`` member, before
anything is defined (``Services.require_allowance``).

``POST .../comparisons/{comparison_id}/cancel`` cancels a comparison started from the application,
once (:mod:`exulanica.world.comparison_facts`): a start no host holds is closed by the cancellation
itself, every run left open failed as ``comparison_cancelled`` asking nothing, with what a host
whose lease ran out may have spent presumed as a takeover presumes it; a start a host is playing
is closed by that host before its next dispatch. A repeated cancel changes nothing, and a start
that already finished keeps its own closing. The reads serve the cancellation on the start, and
each unfinished run's progress: running while a host plays it under the start's live lease, else
queued.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from exulanica.api.capabilities import (
    AVAILABLE,
    Operation,
    Preview,
    Subjects,
    VersionContext,
    unavailable,
    unsupported,
)
from exulanica.api.decision_host import offered_providers
from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.api.society_comparison_runner import (
    CANCELLED,
    ComparisonArm,
    SocietyComparisonRunner,
)
from exulanica.api.society_comparison_start import (
    MODELS_MOST,
    START_REFUSALS,
    TYPICAL_FALLBACK,
    TYPICAL_RECORDS,
    ComparisonCost,
    ComparisonSelection,
    StartRefused,
    answers_per_minute,
    asked_providers,
    comparison_cost,
    definition_body,
    stopped_host_usd,
    typical_per_person_hour,
)
from exulanica.api.society_comparison_worker import CANCELLED_REASON
from exulanica.api.world_scope import WorldId
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import load_manifest
from exulanica.models.spending import SpendingRefused
from exulanica.world.comparison_facts import ComparisonFacts, run_progress
from exulanica.world.decision_roles import DecisionRole, RoleRefused, decision_roles
from exulanica.world.society import UnavailableSocietyInput, UnknownSociety
from exulanica.world.society_catalogs import load_comparison_catalogs
from exulanica.world.society_comparison import ReplayMismatch
from exulanica.world.society_comparison_drawing import (
    DrawingCorrupt,
    decode,
    drawing_sha256,
    with_names,
)
from exulanica.world.society_comparison_reading import (
    decided_maximum,
    decided_people,
    population_maximum,
    reading_refusal,
)
from exulanica.world.society_comparison_repository import (
    ComparisonConflict,
    SocietyComparisonRepository,
)
from exulanica.world.society_comparison_result import (
    ComparisonRefused,
    comparison_result,
    listing_document,
    protocol_value,
    replay_document,
    replay_profile,
    verified_replay,
)
from exulanica.world.society_comparison_start_repository import (
    ComparisonRunning,
    SocietyComparisonStarts,
    StartConflict,
    start_document,
)
from exulanica.world.society_engines import society_engine
from exulanica.world.society_model_choice_repository import SocietyModelChoiceRepository
from exulanica.world.society_person_label import person_label
from exulanica.world.society_repository import SocietyRepository
from exulanica.world.society_score import ScoreRefused
from exulanica.world.worlds import require_world

_LOG = logging.getLogger(__name__)
router = APIRouter(prefix="/world/versions/{version_id}/society/comparisons", tags=["society"])

__all__ = ["capability_operations", "router"]

#: A run that has no completed hour to draw, answered by name rather than as a missing run.
RUN_NOT_COMPLETED: Final = "run_not_completed"
PLAN_PROFILE: Final = "exulanica.society-comparison-plan/v1"
#: What prices a model's asks where this server has no client: the manifest's prices, no ceiling.
_ESTIMATOR: Final = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)
#: The most seeds one comparison names, migration 0113's bound on a definition.
_SEEDS_MOST: Final = 64
#: A bound in US dollars as the person states it: a positive decimal to the ledger's eight places.
_BOUND_PATTERN: Final = r"^[0-9]{1,6}(\.[0-9]{1,8})?$"


def _comparisons(
    connection: ScopedConnection, session: CurrentSession, request: Request, world_id: str
) -> SocietyComparisonRepository:
    require_world(connection, session.workspace_id, world_id)
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyComparisonRepository(
        SocietyRepository(
            connection,
            session.workspace_id,
            world_id=world_id,
            input_authorizer=(
                None if authorizer is None else lambda doc: authorizer(connection, session, doc)
            ),
        )
    )


def _starts(
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    comparison_ids: Sequence[uuid.UUID],
    comparisons: SocietyComparisonRepository,
) -> dict[uuid.UUID, dict[str, Any]]:
    """The start of each comparison started from the application, as the reads serve it, with
    its cancellation where it was cancelled."""
    starts = SocietyComparisonStarts(connection, session.workspace_id)
    rows = starts.read(world_id, comparison_ids)
    if not rows:
        return {}
    spent = comparisons.spending(list(rows))
    cancelled = ComparisonFacts(
        connection, session.workspace_id, world_id, "society"
    ).cancellations(list(rows))
    now = starts.now()
    return {
        comparison_id: start_document(
            row, spent.get(comparison_id, Decimal(0)), now, cancelled.get(comparison_id)
        )
        for comparison_id, row in rows.items()
    }


def _with_progress(
    document: dict[str, Any],
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    comparison_id: uuid.UUID,
) -> dict[str, Any]:
    """``document``'s runs, each unfinished one with where it stands: running while a host plays
    it under the start's live lease, else queued; a finished run states none, and so does a run
    not yet reserved, which has no id."""
    starts = SocietyComparisonStarts(connection, session.workspace_id)
    start = starts.read(world_id, [comparison_id]).get(comparison_id)
    facts = ComparisonFacts(connection, session.workspace_id, world_id, "society")
    begun = facts.run_starts(comparison_id)
    now = starts.now()
    for seed in document.get("seeds", ()):
        for run in seed["runs"].values():
            run["progress"] = (
                None
                if run["status"] in ("completed", "failed") or run["run_id"] is None
                else run_progress(start, begun.get(uuid.UUID(run["run_id"]), []), now)
            )
    return document


def _unreadable(exc: ComparisonRefused | ScoreRefused) -> JSONResponse:
    """A comparison this code cannot read, answered by the code it was refused with."""
    return JSONResponse(status_code=409, content={"code": exc.code, "detail": str(exc)})


def _unavailable(exc: UnavailableSocietyInput) -> JSONResponse:
    return JSONResponse(
        status_code=424, content={"code": "unavailable_society_input", "detail": str(exc)}
    )


@router.get("")
def society_comparisons(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    if comparisons.society._row(version_id) is None:
        raise UnknownSociety("society is unavailable")
    rows = comparisons.definitions(version_id)
    ids = [row["comparison_id"] for row in rows]
    counts = comparisons.run_counts(ids)
    starts = _starts(connection, session, world_id, ids, comparisons)
    try:
        return listing_document(rows, counts, model_name=load_manifest().model_name, starts=starts)
    except (ComparisonRefused, ScoreRefused) as exc:
        return _unreadable(exc)


@router.get("/plan")
def plan_society_comparison(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    role: Annotated[str | None, Query(min_length=1, max_length=63)] = None,
    group: Literal["everyone", "owner_choice", "named"] | None = None,
    choice_seq: Annotated[int | None, Query(ge=1)] = None,
    person: Annotated[list[uuid.UUID], Query(max_length=512)] = [],  # noqa: B006
    model: Annotated[list[str], Query(max_length=MODELS_MOST)] = [],  # noqa: B006
    control: bool = False,
    seeds: Annotated[int, Query(ge=1, le=_SEEDS_MOST)] = 1,
    input_seq: Annotated[int | None, Query(ge=1)] = None,
) -> Any:
    """What a start would do, writing nothing: the roles, groups, models and development seeds
    this server offers a comparison of the version's society, and, for the selection the query
    names (``model`` as ``<provider>/<model id>``, once or twice; ``person`` for a named group;
    ``input_seq`` for an earlier stored input to freeze), the runs it plans, the input it
    freezes, the most it can cost and what one like it typically cost, or the refusal a start of
    it would meet."""
    comparisons = _comparisons(connection, session, request, world_id)
    society = _society(comparisons, version_id)
    navigation = comparisons.navigation_profile(society)
    services = get_services(request)
    refusal = services.comparison_refusal(session.workspace_id)
    # A society whose engine takes no comparison is answered with the start's own refusal, and
    # none of its people are read: its state need not name them the way a compared one does.
    engine = str(society["engine_version"])
    compared = society_engine(engine).comparisons
    refused = (
        {"code": refusal, "detail": _HOST_DETAIL[refusal]}
        if refusal is not None
        else None
        if compared
        else {"code": "engine_takes_no_comparison", "detail": f"{engine} takes no comparison"}
    )
    running = SocietyComparisonStarts(connection, session.workspace_id).unfinished(world_id)
    catalogs = services.comparison_catalogs or load_comparison_catalogs()
    population = int(society["population_size"])
    document: dict[str, Any] = {
        "profile": PLAN_PROFILE,
        "refusal": refused,
        "running": None if running is None else str(running["comparison_id"]),
        "roles": _choices(services, connection, session, world_id, version_id, society, navigation)
        if compared
        else [],
        "seeds_available": len(services.comparison_seeds),
        "models_most": MODELS_MOST,
        "window_ticks": protocol_value(catalogs, "window_ticks"),
        "population": population,
        "population_most": population_maximum(catalogs),
        "decided_most": decided_maximum(catalogs, population),
        # Everybody a named group may be chosen from, by id and name, as the society's state
        # names them: a group of more people than one owner's choice holds is chosen from these.
        "people": sorted(
            (
                {"id": person["id"], "name": person_label(person)}
                for person in society["state"]["inhabitants"]
            ),
            key=lambda person: (person["name"], person["id"]),
        )
        if compared
        else [],
        "typical_record": TYPICAL_RECORDS.get(navigation, (TYPICAL_FALLBACK, ""))[0],
        "plan": None,
        "plan_refusal": None,
    }
    if role is None or group is None or not model:
        return document
    try:
        chosen = []
        for named in model:
            provider, _, model_id = named.partition("/")
            if not provider or not model_id:
                raise StartRefused("model_not_offered", f"{named!r} is not <provider>/<model id>")
            chosen.append(ChosenModel(provider=provider, model_id=model_id))
        prepared = _prepare(
            services,
            connection,
            session,
            world_id,
            version_id,
            society,
            role_key=role,
            group=ChosenGroup(kind=group, choice_seq=choice_seq, people=person or None),
            models=chosen,
            control=control,
            seed_count=seeds,
            navigation=navigation,
            input_seq=input_seq,
        )
    except StartRefused as exc:
        document["plan_refusal"] = {"code": exc.code, "detail": exc.detail}
    else:
        document["plan"] = {
            **prepared.cost.document(),
            "input_seq": prepared.input_seq,
            "minutes": _minutes(prepared, population, navigation),
        }
    return document


def _minutes(prepared: _Prepared, population: int, navigation: str | None) -> list[dict[str, Any]]:
    """For each model arm of a planned comparison, how many people its model decides for in one
    run and how many of a minute's asks the model can have answered by the decision contract's
    concurrency and deadline at its answer time measured on the society's kind of ground, else on
    the small square (``answers_per_minute`` in :mod:`exulanica.api.society_comparison_start`),
    None where it has no measured time. Where more
    people than that have a choice in one minute, the rest follow their routine."""
    contract = prepared.role.contract()
    decided = decided_people(prepared.body, population)
    manifest = load_manifest()
    return [
        {
            "arm": key,
            "model_id": arm["provider_config"]["model_id"],
            "name": manifest.model_name(arm["provider_config"]["model_id"]),
            "decided": decided[key],
            "answers_per_minute": answers_per_minute(
                contract, arm["provider_config"]["model_id"], navigation
            ),
        }
        for key, arm in sorted(prepared.body["arms"].items())
        if arm["provider_config"] is not None
    ]


@router.get("/{comparison_id}")
def society_comparison(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    row = comparisons.definition(version_id, comparison_id)
    start = _starts(connection, session, world_id, [comparison_id], comparisons).get(comparison_id)
    try:
        document = comparison_result(
            row,
            comparisons.runs(comparison_id),
            model_name=load_manifest().model_name,
            start=start,
        )
    except (ComparisonRefused, ScoreRefused) as exc:
        return _unreadable(exc)
    return _with_progress(document, connection, session, world_id, comparison_id)


@router.get("/{comparison_id}/runs/{run_id}")
def society_comparison_run(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    run_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    comparisons.definition(version_id, comparison_id)
    outcome = comparisons.outcome(run_id)
    try:
        plan, definition = comparisons.read_plan(comparison_id, run_id)
    except UnavailableSocietyInput as exc:
        return _unavailable(exc)
    except ComparisonRefused as exc:
        return _unreadable(exc)
    completed = outcome is not None and outcome["status"] == "completed"
    played = mismatch = drawn = None
    if completed:
        # The drawing the host stored once it verified the run, under the digest of the code
        # reading it; where there is none, the run is replayed and verified here.
        stored = comparisons.drawing(run_id, drawing_sha256(replay_profile(plan)))
        if stored is not None:
            try:
                drawn = decode(stored)
            except DrawingCorrupt:
                # Stored bytes that are not the drawing their digest names: the run is replayed
                # instead, and the rows stay as they are, appended and never changed.
                _LOG.error("A comparison run's stored drawing is not the drawing it names")
                drawn = None
        if drawn is None:
            try:
                played = verified_replay(plan, comparisons.stored(run_id), outcome)
            except ReplayMismatch as exc:
                mismatch = exc
    # The inputs' rights are asked after the drawing is found or the replay done, which takes
    # seconds for a town, and before anything drawn from them is answered, so a withdrawal made
    # while it replayed is seen, and a stored drawing is never served past one.
    try:
        comparisons.authorize_inputs(plan.inputs)
    except UnavailableSocietyInput as exc:
        return _unavailable(exc)
    if not completed:
        return JSONResponse(
            status_code=409,
            content={"code": RUN_NOT_COMPLETED, "detail": "this run has no completed hour"},
        )
    if drawn is not None:
        return with_names(drawn, load_manifest().model_name)
    if mismatch is not None:
        return JSONResponse(
            status_code=409, content={"code": mismatch.code, "detail": str(mismatch)}
        )
    assert played is not None
    return replay_document(
        plan,
        definition,
        outcome["arm"],
        outcome["seed_digest"],
        played,
        model_name=load_manifest().model_name,
    )


# -- a comparison planned and started from the application -------------------------------------


class ChosenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]


class ChosenGroup(BaseModel):
    """The people every arm decides for: everybody, the people one of the owner's choices named,
    or people named."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["everyone", "owner_choice", "named"]
    choice_seq: Annotated[int, Field(ge=1)] | None = None
    people: Annotated[list[uuid.UUID], Field(max_length=512)] | None = None


class ComparisonStartBody(BaseModel):
    """A comparison started: what it compares, its id (the caller's, keyed within its workspace)
    and the most its asks may spend, in US dollars."""

    model_config = ConfigDict(extra="forbid")
    comparison_id: uuid.UUID
    role: Annotated[str, Field(min_length=1, max_length=63)]
    group: ChosenGroup
    models: Annotated[list[ChosenModel], Field(min_length=1, max_length=MODELS_MOST)]
    control: bool = False
    seeds: Annotated[int, Field(ge=1, le=_SEEDS_MOST)]
    bound_usd: Annotated[str, Field(pattern=_BOUND_PATTERN)]
    #: An earlier stored input of the society to freeze; left out, its newest.
    input_seq: Annotated[int, Field(ge=1)] | None = None


#: What a host refusal says, where this server starts no comparison for the workspace.
_HOST_DETAIL: Final = {
    "comparisons_not_set_up": "this server holds no development seed to run a comparison on",
    "comparisons_not_played": "nothing plays the comparisons started on this server",
    "comparisons_not_run_here": "this server does not ask models for this workspace",
    "provider_credential_absent": "this server holds no key for the models' service",
}


def _start_refused(exc: StartRefused) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "detail": exc.detail})


def _society(comparisons: SocietyComparisonRepository, version_id: uuid.UUID) -> dict[str, Any]:
    row = comparisons.society._row(version_id)
    if row is None:
        raise UnknownSociety("society is unavailable")
    return row


class _Prepared:
    """A selection held to this server and the world's records, and what it would define."""

    def __init__(
        self,
        runner: SocietyComparisonRunner,
        role: DecisionRole,
        seeds: tuple[str, ...],
        body: dict[str, Any],
        cost: ComparisonCost,
        input_seq: int,
    ) -> None:
        self.runner, self.role, self.seeds, self.body, self.cost = runner, role, seeds, body, cost
        #: The society's input a start of it freezes.
        self.input_seq = input_seq


def _prepare(
    services: Services,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    version_id: uuid.UUID,
    society: dict[str, Any],
    *,
    role_key: str,
    group: ChosenGroup,
    models: Sequence[ChosenModel],
    control: bool,
    seed_count: int,
    navigation: str | None,
    input_seq: int | None = None,
) -> _Prepared:
    """What a start of this selection would define, through the one definition path, or the
    refusal it would meet (:class:`StartRefused`); reads only."""
    refusal = services.comparison_refusal(session.workspace_id)
    if refusal is not None:
        raise StartRefused(refusal, _HOST_DETAIL[refusal])
    try:
        role = decision_roles().role(role_key)
    except RoleRefused as exc:
        raise StartRefused("role_not_registered", exc.detail) from exc
    runner = services.comparison_runner(session.workspace_id, world_id, session.actor)
    if runner is None:
        raise StartRefused("comparisons_not_run_here", "this server runs no society")
    runner = dataclasses.replace(runner, decision_role=role)
    engine = str(society["engine_version"])
    if not society_engine(engine).comparisons:
        raise StartRefused("engine_takes_no_comparison", f"{engine} takes no comparison")
    if not role.hosted_by(engine):
        raise StartRefused("role_not_hosted", f"{engine} hosts no {role.key} decisions")
    population = int(society["population_size"])
    refused = reading_refusal(runner.catalogs, population)
    if refused is not None:
        raise StartRefused(*refused)
    arms = [ComparisonArm(model.provider, model.model_id) for model in models]
    if len(set(arms)) != len(arms):
        raise StartRefused("model_named_twice", "a comparison runs a model twice only as control")
    for arm in arms:
        try:
            runner._model(arm, None)
        except ValueError as exc:
            raise StartRefused("model_not_offered", str(exc)) from exc
        refused = services.choice_refusal(
            role,
            {"provider": arm.provider, "model_id": arm.model_id},
            connection,
            session.workspace_id,
        )
        if refused is not None:
            raise StartRefused("model_not_askable_here", f"{arm.model_id}: {refused}")
    if not 1 <= seed_count <= len(services.comparison_seeds):
        raise StartRefused(
            "seeds_out_of_range",
            f"this server holds {len(services.comparison_seeds)} development seeds",
        )
    newest = SocietyRepository(connection, session.workspace_id, world_id=world_id)._chain(society)
    if input_seq is not None and not 1 <= input_seq <= newest:
        raise StartRefused("input_not_in_society", f"this society holds inputs 1 to {newest}")
    here = {person["id"] for person in society["state"]["inhabitants"]}
    people: tuple[str, ...] | None = None
    if group.kind == "named":
        people = tuple(sorted({str(person) for person in group.people or ()}))
        if not people:
            raise StartRefused("group_empty", "a group names somebody")
        if not set(people) <= here:
            raise StartRefused("group_person_unknown", "the group names somebody not here")
    elif not here:
        raise StartRefused("group_empty", "this world holds nobody to decide for")
    if (group.kind == "owner_choice") != (group.choice_seq is not None):
        raise StartRefused("choice_unknown", "a group of an owner's choice names that choice")
    selection = ComparisonSelection(
        models=tuple(arms),
        control=control,
        group=group.kind,
        seed_count=seed_count,
        choice_seq=group.choice_seq if group.kind == "owner_choice" else None,
        people=people,
    )
    seeds = services.comparison_seeds[:seed_count]
    try:
        body = definition_body(runner, version_id, selection, seeds, connection=connection)
    except ComparisonRefused as exc:
        if exc.code in START_REFUSALS:
            raise StartRefused(exc.code, str(exc)) from exc
        raise
    refused = reading_refusal(runner.catalogs, population, body)
    if refused is not None:
        raise StartRefused(*refused)
    client = services.model_client
    cost = comparison_cost(
        body,
        population,
        role,
        client.budget if client is not None else _ESTIMATOR,
        load_manifest(),
        at_once=protocol_value(runner.catalogs, "runs_at_once"),
        navigation_profile=navigation,
    )
    return _Prepared(runner, role, seeds, body, cost, newest if input_seq is None else input_seq)


def _choices(
    services: Services,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    version_id: uuid.UUID,
    society: dict[str, Any],
    navigation: str | None,
) -> list[dict[str, Any]]:
    """Each role a comparison of this society may ask, with the groups and the models it offers:
    everybody and each of the owner's choices whose people are all still here, newest first, and
    every model the manifest offers the role, with why this server cannot ask it, if it cannot,
    and what it typically cost, on the society's kind of ground where that was measured."""
    manifest = load_manifest()
    names = {person["id"]: person_label(person) for person in society["state"]["inhabitants"]}
    typical = typical_per_person_hour(navigation)
    roles = []
    for role in decision_roles().hosted_by(str(society["engine_version"])):
        history = SocietyModelChoiceRepository(
            connection, session.workspace_id, world_id=world_id
        ).history(version_id, role)
        groups: list[dict[str, Any]] = [
            {
                "kind": "everyone",
                "choice_seq": None,
                "size": len(names),
                "people": None,
                "model": None,
            }
        ]
        for choice in reversed(history):
            if choice["people"] and set(choice["people"]) <= set(names):
                model = choice["model"]
                groups.append(
                    {
                        "kind": "owner_choice",
                        "choice_seq": choice["choice_seq"],
                        "size": len(choice["people"]),
                        "people": [
                            {"id": person, "name": names[person]}
                            for person in sorted(choice["people"])
                        ],
                        "model": None
                        if model is None
                        else {**model, "name": manifest.model_name(model["model_id"])},
                    }
                )
        contract = role.contract()
        models = [
            {
                "provider": spec.provider,
                "model_id": spec.model_id,
                "name": manifest.model_name(spec.model_id),
                "description": spec.description,
                "refusal": services.choice_refusal(
                    role,
                    {"provider": spec.provider, "model_id": spec.model_id},
                    connection,
                    session.workspace_id,
                ),
                "typical_usd_per_person_hour": None
                if spec.model_id not in typical
                else format(typical[spec.model_id], "f"),
            }
            for spec in manifest.offered_models(role.chosen)
            if contract.mechanism_for(spec) is not None
        ]
        # What this process's budget has left is not served here: it reflects every workspace's
        # spend, so only a caller who may start one learns it, when a start's bound exceeds it.
        roles.append(
            {
                "key": role.key,
                "subject": role.subject,
                "groups": groups,
                "models": models,
            }
        )
    return roles


@router.post("", status_code=201)
def start_society_comparison(
    version_id: uuid.UUID,
    body: ComparisonStartBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    response: Response,
) -> Any:
    comparisons = _comparisons(connection, session, request, world_id)
    society = _society(comparisons, version_id)
    services = get_services(request)
    starts = SocietyComparisonStarts(connection, session.workspace_id)
    existing = starts.read(world_id, [body.comparison_id]).get(body.comparison_id)
    try:
        if existing is None and (running := starts.unfinished(world_id)) is not None:
            raise StartRefused(
                "comparison_running",
                f"comparison {running['comparison_id']} of this world has not finished",
            )
        prepared = _prepare(
            services,
            connection,
            session,
            world_id,
            version_id,
            society,
            role_key=body.role,
            group=body.group,
            models=body.models,
            control=body.control,
            seed_count=body.seeds,
            navigation=comparisons.navigation_profile(society),
            input_seq=body.input_seq,
        )
        try:
            bound = Decimal(body.bound_usd)
        except InvalidOperation as exc:  # pragma: no cover - the pattern admits decimals only
            raise StartRefused("bound_out_of_range", "a bound is a decimal") from exc
        if not Decimal(0) < bound <= prepared.cost.most_usd:
            raise StartRefused(
                "bound_out_of_range",
                f"a bound above $0 and at most ${prepared.cost.most_usd}, the most it can cost",
            )
        room = services.comparison_room(prepared.role)
        if existing is None and room is not None and bound > room:
            raise StartRefused(
                "bound_over_budget",
                f"this server's model budget has ${room} left for comparisons",
            )
        calls = services.comparison_call_room(prepared.role)
        if existing is None and calls is not None and prepared.cost.calls > calls:
            raise StartRefused(
                "calls_over_budget",
                f"this server's model budget has {calls} calls left for comparisons, and this "
                f"one can make {prepared.cost.calls}",
            )
        if existing is None:
            # Each model the definition asks, an arm's or an outside person's owner's choice,
            # asks its own provider alone: refused here as admission would refuse that first ask,
            # before anything is defined.
            services.require_allowance(
                connection, session.workspace_id, asked_providers(prepared.body)
            )
        with connection.transaction():
            prepared.runner.define(
                version_id,
                comparison_id=body.comparison_id,
                body=prepared.body,
                connection=connection,
                input_seq=prepared.input_seq,
            )
            prepared.runner.reserve_all(body.comparison_id, prepared.seeds, connection=connection)
            starts.record(
                world_id,
                body.comparison_id,
                requested_by=session.actor,
                bound_usd=bound,
                bound_calls=prepared.cost.calls,
                runs_planned=prepared.cost.runs,
            )
    except StartRefused as exc:
        return _start_refused(exc)
    except ComparisonRunning as exc:
        return _start_refused(
            StartRefused("comparison_running", f"comparison {exc.comparison_id} has not finished")
        )
    except (ComparisonConflict, StartConflict) as exc:
        return _start_refused(StartRefused("comparison_conflict", str(exc)))
    except ComparisonRefused as exc:
        return JSONResponse(
            status_code=START_REFUSALS.get(exc.code, 409),
            content={"code": exc.code, "detail": str(exc)},
        )
    except UnavailableSocietyInput as exc:
        # The input it would freeze lost its rights: answered as every society read answers one.
        return _unavailable(exc)
    if existing is not None:
        response.status_code = 200
    row = comparisons.definition(version_id, body.comparison_id)
    ids = [body.comparison_id]
    return listing_document(
        [row],
        comparisons.run_counts(ids),
        model_name=load_manifest().model_name,
        starts=_starts(connection, session, world_id, ids, comparisons),
    )


@router.post("/{comparison_id}/cancel")
def cancel_society_comparison(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """Cancel a comparison started from the application, once. A start no host holds closes now:
    every run left open fails as ``comparison_cancelled``, asking nothing, and what a host whose
    lease ran out may have spent is presumed as a takeover presumes it. A start a host is playing
    is closed by that host before its next dispatch. A repeated cancel changes nothing, and a
    finished start keeps its own closing. Answers the comparison as the listing states it."""
    comparisons = _comparisons(connection, session, request, world_id)
    row = comparisons.definition(version_id, comparison_id)
    services = get_services(request)
    starts = SocietyComparisonStarts(connection, session.workspace_id)
    with connection.transaction():
        start = starts.lock(world_id, comparison_id)
        if start is None:
            return JSONResponse(
                status_code=409,
                content={
                    "code": "comparison_not_started",
                    "detail": "only a comparison started from the application is cancelled",
                },
            )
        if start["finished_at"] is None:
            ComparisonFacts(connection, session.workspace_id, world_id, "society").cancel(
                comparison_id, session.actor
            )
        held = start["lease_token"] is not None and start["lease_expires_at"] > starts.now()
        if start["finished_at"] is None and not held:
            definition = row["document"]
            open_runs = comparisons.open_runs(comparison_id)
            presumed = Decimal(0)
            if start["lease_token"] is not None:
                client = services.model_client
                presumed = stopped_host_usd(
                    definition,
                    services.comparison_catalogs or load_comparison_catalogs(),
                    None if client is None else client.budget,
                    load_manifest(),
                    open_runs,
                )
            for run in open_runs:
                comparisons.finish(
                    comparison_id,
                    run["run_id"],
                    SocietyComparisonRunner._failed(
                        definition, run["arm"], run["seed_digest"], CANCELLED
                    ),
                )
            starts.close_unclaimed(
                world_id, comparison_id, closed_reason=CANCELLED_REASON, presumed_usd=presumed
            )
    ids = [comparison_id]
    return listing_document(
        [comparisons.definition(version_id, comparison_id)],
        comparisons.run_counts(ids),
        model_name=load_manifest().model_name,
        starts=_starts(connection, session, world_id, ids, comparisons),
    )


# -- a world's capability read --------------------------------------------------------------------


def _spent(context: VersionContext, engine: str) -> SpendingRefused | None:
    """The durable authority's refusal of every start of a society on ``engine``: the allowance
    of every provider the roles it hosts can ask is spent. None while one has allowance left, or
    in a process no durable authority admits."""
    spending = context.spending()
    if spending is None:
        return None
    manifest = load_manifest()
    return spending.every(
        provider
        for role in decision_roles().hosted_by(engine)
        for provider in offered_providers(role, manifest, role.contract())
    )


def capability_operations(context: VersionContext) -> list[Operation]:
    """Starting a comparison of the version's society, and cancelling one started from the
    application, as a world's capability read lists them.

    A start is refused in the order a start refuses before it reads its body: a version with no
    society, a comparison of the world that has not finished, this server's own refusal
    (``Services.comparison_refusal``), and an engine that takes no comparison. Where a durable
    spending authority admits this server's calls, it is also unavailable by the authority's
    reason once the allowance of every provider the engine's roles can ask is spent: every start
    would then be refused (``Services.require_allowance``). The plan read is its preview and lists
    what a start may name. A cancel acts on a comparison the listing names and is available while a
    start of the world has not finished, else ``comparison_not_started``. It holds ``model.invoke``
    only so that whoever may start a paid comparison may stop it, and calls no model, so it is
    described as spending nothing, and no allowance is read for it.
    """
    running = (
        None
        if context.society is None
        else SocietyComparisonStarts(context.connection, context.session.workspace_id).unfinished(
            context.world_id
        )
    )
    if context.society is None:
        state = unavailable("society_unavailable")
    elif running is not None:
        state = unavailable("comparison_running")
    elif (refusal := context.services.comparison_refusal(context.session.workspace_id)) is not None:
        state = unavailable(refusal)
    elif not society_engine(str(context.society["engine_version"])).comparisons:
        state = unsupported("engine_takes_no_comparison")
    elif (spent := _spent(context, str(context.society["engine_version"]))) is not None:
        state = unavailable(spent.reason)
    else:
        state = AVAILABLE
    return [
        Operation(
            endpoint=start_society_comparison,
            availability=state,
            subject="version",
            bind=context.bind,
            idempotency="comparison_id",
            preview=Preview(plan_society_comparison, required=False),
            options=(plan_society_comparison,),
        ),
        Operation(
            endpoint=cancel_society_comparison,
            availability=AVAILABLE
            if running is not None
            else unavailable("comparison_not_started"),
            subject="comparison",
            bind=context.bind,
            subjects=Subjects(society_comparisons, "comparisons"),
            spends=False,
        ),
    ]
