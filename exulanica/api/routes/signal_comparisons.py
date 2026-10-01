"""The comparisons of the models that decide a town's signals: read, planned, started, replayed
and cancelled.

A signal comparison plays episodes of a saved town's traffic, one per seed and arm, its group of
signals decided by the plan's fixed timing or by a model asked at every choice point the traffic
step offers (:mod:`exulanica.world.signal_comparison`). It reads the version's roads and nothing
else of the live world, which it never writes: not its traffic, its signal choices or its sealed
minutes.

``GET /world/versions/{version_id}/traffic/comparisons`` lists a version's signal comparisons,
newest first, each with how far its runs got and its start. ``GET .../comparisons/{comparison_id}``
gives one comparison per seed and arm: each run's measure (the mean delay per entry at the group's
signalled junctions), its integer terms and trips, what its model answered, by status and reason,
what it cost and how long each ask took, the registered differences and the verdict, which
development seeds never get. ``GET .../comparisons/{comparison_id}/runs/{run_id}`` gives one run's
outcome and every choice point's receipt. ``GET .../runs/{run_id}/replay`` plays a completed run
again from what it stored, asking no model, and answers whether it reproduced its record; a replay
that differs is refused by name (``run_replay_mismatch``). It plays the whole episode in the
request, so its cost grows with the episode and the run's choice points. None of these asks a
model, writes anything or returns a run's seed.

``GET .../comparisons/plan`` answers what a start would, and writes nothing: the town's signals,
the models offered with why one cannot be asked here, the development seeds this server holds and,
for a selection, the runs it plans and the most it can cost, or the refusal a start of it would
meet. It plays no episode. ``POST .../comparisons`` starts one
(:mod:`exulanica.api.signal_comparison_start`): in one transaction it defines the comparison over
the version's roads as they are, reserves every run and records the start with the bound its owner
stated, at most the most it can cost. A host's comparison worker plays it off the request path, as
it plays a comparison of people. The comparison's id is the caller's, keyed within its workspace:
the same start sent again is answered with the start it made.

``POST .../comparisons/{comparison_id}/cancel`` cancels a started comparison once, as a comparison
of people is cancelled (:mod:`exulanica.world.comparison_facts`): a start no host holds closes now,
its open runs failed as ``comparison_cancelled`` asking nothing, with what a host whose lease ran
out may have spent presumed; a host playing one stops before its next ask. The reads serve the
cancellation on the start and each unfinished run's progress.

Refusals, each by name: an id this workspace does not hold is 404 ``unknown_reference``; roads the
version does not state are 404 ``roads_not_stated``; roads traffic cannot drive are 409
``roads_unavailable`` or ``roads_world_too_large``; a world whose receipt no longer generates its
records is 409 by the reader's name; a start's own refusals are ``START_REFUSALS``.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Final

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
)
from exulanica.api.dependencies import CurrentSession, ScopedConnection, get_services
from exulanica.api.services import Services
from exulanica.api.signal_comparison_runner import SignalComparisonRunner
from exulanica.api.signal_comparison_start import (
    START_REFUSALS,
    SignalComparisonCost,
    SignalStartRefused,
    points_most,
    signal_comparison_cost,
    stopped_signal_host_usd,
)
from exulanica.api.society_comparison_runner import CANCELLED, ComparisonArm
from exulanica.api.society_comparison_worker import CANCELLED_REASON
from exulanica.api.traffic_answer import refusal_status
from exulanica.api.world_scope import WorldId
from exulanica.models.budget import BudgetGuard
from exulanica.models.manifest import load_manifest
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.world.comparison_facts import ComparisonFacts, run_progress
from exulanica.world.decision_roles import DecisionRole
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.generated_worlds import unreadable_reason
from exulanica.world.role_decisions import ReplayMismatch
from exulanica.world.signal_comparison_repository import (
    SignalComparisonConflict,
    SignalComparisonRefused,
    SignalComparisonRepository,
    UnknownSignalComparison,
)
from exulanica.world.signal_comparison_result import comparison_result, listing_document
from exulanica.world.society_comparison_start_repository import (
    ComparisonRunning,
    SocietyComparisonStarts,
    StartConflict,
    start_document,
)
from exulanica.world.traffic_episodes import TrafficRefused, compute_signal_catalog, wire
from exulanica.world.worlds import require_world

router = APIRouter(prefix="/world/versions/{version_id}/traffic/comparisons", tags=["world"])

__all__ = ["capability_operations", "router"]

PLAN_PROFILE: Final = "exulanica.signal-comparison-plan/v1"
RUN_PROFILE: Final = "exulanica.signal-comparison-run-read/v1"
REPLAY_PROFILE: Final = "exulanica.signal-comparison-replay/v1"
#: The kind of comparison these routes start, claim and cancel.
_KIND: Final = "signal"
#: The most models one comparison compares, beside the plan's fixed timing.
MODELS_MOST: Final = 2
#: The most signals a named group holds, migration 0132's bound on a definition.
_GROUP_MOST: Final = 64
#: What prices a model's asks where this server has no client: the manifest's prices, no ceiling.
_ESTIMATOR: Final = BudgetGuard(ceiling_usd=Decimal(0), max_calls=0)
#: A bound in US dollars as the person states it: a positive decimal to the ledger's eight places.
_BOUND_PATTERN: Final = r"^[0-9]{1,6}(\.[0-9]{1,8})?$"
#: What a host refusal says, where this server starts no signal comparison for the workspace.
_HOST_DETAIL: Final = {
    "comparisons_not_played": "nothing plays the comparisons started on this server",
    "comparisons_not_run_here": "this server does not ask models for this workspace",
    "provider_credential_absent": "this server holds no key for the models' service",
}


def _problem(status: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"code": code, "detail": detail})


def _roads_refused(error: Exception) -> JSONResponse:
    """Roads the version does not state or traffic cannot read, answered as the traffic read
    answers them."""
    if isinstance(error, TrafficRefused):
        return _problem(refusal_status(error), error.code, error.detail)
    if isinstance(error, UnsupportedNetworkError):
        return _problem(409, "roads_unavailable", str(error))
    assert isinstance(error, InvalidStructuralData)
    return _problem(409, unreadable_reason(error), str(error))


_ROADS_ERRORS: Final = (TrafficRefused, UnsupportedNetworkError, InvalidStructuralData)


def _repository(
    connection: ScopedConnection, session: CurrentSession, world_id: str
) -> SignalComparisonRepository:
    require_world(connection, session.workspace_id, world_id)
    return SignalComparisonRepository(connection, session.workspace_id, world_id)


def _starts(
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    comparison_ids: Sequence[uuid.UUID],
    repository: SignalComparisonRepository,
) -> dict[uuid.UUID, dict[str, Any]]:
    """The start of each comparison, as the reads serve it, with its cancellation if it has one."""
    starts = SocietyComparisonStarts(connection, session.workspace_id, _KIND)
    rows = starts.read(world_id, comparison_ids)
    if not rows:
        return {}
    spent = repository.spending(list(rows))
    cancelled = ComparisonFacts(connection, session.workspace_id, world_id, _KIND).cancellations(
        list(rows)
    )
    now = starts.now()
    return {
        comparison_id: start_document(
            row, spent.get(comparison_id, Decimal(0)), now, cancelled.get(comparison_id)
        )
        for comparison_id, row in rows.items()
    }


def _listing(
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    repository: SignalComparisonRepository,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    ids = [row["comparison_id"] for row in rows]
    return listing_document(
        rows,
        repository.run_counts(ids),
        starts=_starts(connection, session, world_id, ids, repository),
    )


@router.get("")
def signal_comparisons(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    repository = _repository(connection, session, world_id)
    repository.snapshot_of(version_id)
    return _listing(connection, session, world_id, repository, repository.definitions(version_id))


# -- a comparison planned and started -----------------------------------------------------------


class ChosenModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Annotated[str, Field(min_length=1, max_length=63)]
    model_id: Annotated[str, Field(min_length=1, max_length=200)]


SignalId = Annotated[str, Field(min_length=1, max_length=500)]


class SignalComparisonStartBody(BaseModel):
    """A signal comparison started: the models it compares with the plan's fixed timing, its id
    (the caller's, keyed within its workspace), the signals its arms decide for (every signal of
    the town where none is named) and the most its asks may spend, in US dollars."""

    model_config = ConfigDict(extra="forbid")
    comparison_id: uuid.UUID
    models: Annotated[list[ChosenModel], Field(min_length=1, max_length=MODELS_MOST)]
    control: bool = False
    seeds: Annotated[int, Field(ge=1, le=64)]
    signals: Annotated[list[SignalId], Field(min_length=1, max_length=_GROUP_MOST)] | None = None
    bound_usd: Annotated[str, Field(pattern=_BOUND_PATTERN)]


class _Prepared:
    """A selection held to this server and the town's roads, and what it would define."""

    def __init__(
        self,
        runner: SignalComparisonRunner,
        seeds: tuple[str, ...],
        body: dict[str, Any],
        cost: SignalComparisonCost,
    ) -> None:
        self.runner, self.seeds, self.body, self.cost = runner, seeds, body, cost


def _signals(repository: SignalComparisonRepository, version_id: uuid.UUID) -> list[dict]:
    """The signals the version's roads place, by identity."""
    roads = repository.roads(version_id)
    return sorted(compute_signal_catalog(wire(roads)), key=lambda row: row["signal_id"])


def _prepare(
    services: Services,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: str,
    signals: Sequence[Mapping[str, Any]],
    *,
    models: Sequence[ChosenModel],
    control: bool,
    seed_count: int,
    group: Sequence[str] | None,
) -> _Prepared:
    """What a start of this selection would define, or the refusal it would meet
    (:class:`SignalStartRefused`); reads only."""
    refusal = services.signal_comparison_refusal(session.workspace_id)
    if refusal is not None:
        raise SignalStartRefused(refusal, _HOST_DETAIL[refusal])
    runner = services.signal_comparison_runner(session.workspace_id, world_id, session.actor)
    known = {row["signal_id"] for row in signals}
    if not known:
        raise SignalStartRefused("signals_absent", "these roads place no signal")
    if group is not None:
        if not group:
            raise SignalStartRefused("group_empty", "a group names a signal")
        if not set(group) <= known:
            raise SignalStartRefused("signal_not_in_world", "the group names a signal not here")
    arms = [ComparisonArm(model.provider, model.model_id) for model in models]
    if len(set(arms)) != len(arms):
        raise SignalStartRefused(
            "model_named_twice", "a comparison runs a model twice only as control"
        )
    for arm in arms:
        try:
            runner.model_arm(arm, "candidate")
        except SignalComparisonRefused as exc:
            raise SignalStartRefused("model_not_offered", exc.detail) from exc
        refused = services.choice_refusal(
            runner.role,
            {"provider": arm.provider, "model_id": arm.model_id},
            connection,
            session.workspace_id,
        )
        if refused is not None:
            raise SignalStartRefused("model_not_askable_here", f"{arm.model_id}: {refused}")
    seeds = runner.catalogs.development_seeds()
    most = min(len(seeds), runner.catalogs.value("seeds_most"))
    if not 1 <= seed_count <= most:
        raise SignalStartRefused(
            "seeds_out_of_range", f"this server holds {most} development seeds for signals"
        )
    chosen = seeds[:seed_count]
    body = runner.body(arms, chosen, control=control, group=group)
    client = services.model_client
    cost = signal_comparison_cost(
        body,
        len(known) if group is None else len(set(group)),
        runner.role,
        client.budget if client is not None else _ESTIMATOR,
        load_manifest(),
    )
    return _Prepared(runner, chosen, body, cost)


def _offered(
    services: Services,
    connection: ScopedConnection,
    session: CurrentSession,
    role: DecisionRole,
) -> list[dict[str, Any]]:
    """Every model the manifest offers a signal's decisions, with why this server cannot ask it,
    if it cannot."""
    manifest = load_manifest()
    contract = role.contract()
    return [
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
        }
        for spec in manifest.offered_models(role.chosen)
        if contract.mechanism_for(spec) is not None
    ]


@router.get("/plan")
def plan_signal_comparison(
    version_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    model: Annotated[list[str], Query(max_length=MODELS_MOST)] = [],  # noqa: B006
    control: bool = False,
    seeds: Annotated[int, Query(ge=1, le=64)] = 1,
    signal: Annotated[list[str], Query(max_length=_GROUP_MOST)] = [],  # noqa: B006
) -> Any:
    """What a start would do, writing nothing and playing no episode: the town's signals, the
    models offered for a signal's decisions, the development seeds this server holds and, for the
    selection the query names (``model`` as ``<provider>/<model id>``, once or twice; ``signal``
    for a named group, every signal where none is named), the runs it plans and the most it can
    cost, or the refusal a start of it would meet."""
    repository = _repository(connection, session, world_id)
    services = get_services(request)
    try:
        signals = _signals(repository, version_id)
    except _ROADS_ERRORS as error:
        return _roads_refused(error)
    refusal = services.signal_comparison_refusal(session.workspace_id)
    running = SocietyComparisonStarts(connection, session.workspace_id, _KIND).unfinished(world_id)
    runner = services.signal_comparison_runner(session.workspace_id, world_id, session.actor)
    document: dict[str, Any] = {
        "profile": PLAN_PROFILE,
        "refusal": None if refusal is None else {"code": refusal, "detail": _HOST_DETAIL[refusal]},
        "running": None if running is None else str(running["comparison_id"]),
        "signals": signals,
        "models": _offered(services, connection, session, runner.role),
        "models_most": MODELS_MOST,
        "seeds_available": len(runner.catalogs.development_seeds()),
        "seeds_most": runner.catalogs.value("seeds_most"),
        "points_most_per_signal": points_most(),
        "plan": None,
        "plan_refusal": None,
    }
    if not model:
        return document
    try:
        chosen = []
        for named in model:
            provider, _, model_id = named.partition("/")
            if not provider or not model_id:
                raise SignalStartRefused(
                    "model_not_offered", f"{named!r} is not <provider>/<model id>"
                )
            chosen.append(ChosenModel(provider=provider, model_id=model_id))
        prepared = _prepare(
            services,
            connection,
            session,
            world_id,
            signals,
            models=chosen,
            control=control,
            seed_count=seeds,
            group=signal or None,
        )
    except SignalStartRefused as exc:
        document["plan_refusal"] = {"code": exc.code, "detail": exc.detail}
    else:
        document["plan"] = prepared.cost.document()
    return document


@router.post("", status_code=201)
def start_signal_comparison(
    version_id: uuid.UUID,
    body: SignalComparisonStartBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
    response: Response,
) -> Any:
    repository = _repository(connection, session, world_id)
    services = get_services(request)
    starts = SocietyComparisonStarts(connection, session.workspace_id, _KIND)
    existing = starts.read(world_id, [body.comparison_id]).get(body.comparison_id)
    try:
        if existing is None and (running := starts.unfinished(world_id)) is not None:
            raise SignalStartRefused(
                "comparison_running",
                f"comparison {running['comparison_id']} of this world has not finished",
            )
        prepared = _prepare(
            services,
            connection,
            session,
            world_id,
            _signals(repository, version_id),
            models=body.models,
            control=body.control,
            seed_count=body.seeds,
            group=body.signals,
        )
        try:
            bound = Decimal(body.bound_usd)
        except InvalidOperation as exc:  # pragma: no cover - the pattern admits decimals only
            raise SignalStartRefused("bound_out_of_range", "a bound is a decimal") from exc
        if not Decimal(0) < bound <= prepared.cost.most_usd:
            raise SignalStartRefused(
                "bound_out_of_range",
                f"a bound above $0 and at most ${prepared.cost.most_usd}, the most it can cost",
            )
        role = prepared.runner.role
        room = services.comparison_room(role)
        if existing is None and room is not None and bound > room:
            raise SignalStartRefused(
                "bound_over_budget",
                f"this server's model budget has ${room} left for comparisons",
            )
        calls = services.comparison_call_room(role)
        if existing is None and calls is not None and prepared.cost.calls > calls:
            raise SignalStartRefused(
                "calls_over_budget",
                f"this server's model budget has {calls} calls left for comparisons, and this "
                f"one can make {prepared.cost.calls}",
            )
        with connection.transaction():
            prepared.runner.define(
                version_id,
                comparison_id=body.comparison_id,
                body=prepared.body,
                connection=connection,
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
    except SignalStartRefused as exc:
        return _problem(exc.status, exc.code, exc.detail)
    except ComparisonRunning as exc:
        return _problem(
            409, "comparison_running", f"comparison {exc.comparison_id} has not finished"
        )
    except (SignalComparisonConflict, StartConflict) as exc:
        return _problem(409, "comparison_conflict", str(exc))
    except SignalComparisonRefused as exc:
        return _problem(START_REFUSALS.get(exc.code, 409), exc.code, exc.detail)
    except _ROADS_ERRORS as error:
        return _roads_refused(error)
    if existing is not None:
        response.status_code = 200
    return _listing(
        connection,
        session,
        world_id,
        repository,
        [repository.definition(version_id, body.comparison_id)],
    )


# -- one comparison and its runs -----------------------------------------------------------------


@router.get("/{comparison_id}")
def signal_comparison(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    repository = _repository(connection, session, world_id)
    row = repository.definition(version_id, comparison_id)
    start = _starts(connection, session, world_id, [comparison_id], repository).get(comparison_id)
    document = comparison_result(
        row, repository.runs(comparison_id), model_name=load_manifest().model_name, start=start
    )
    starts = SocietyComparisonStarts(connection, session.workspace_id, _KIND)
    held = starts.read(world_id, [comparison_id]).get(comparison_id)
    begun = ComparisonFacts(connection, session.workspace_id, world_id, _KIND).run_starts(
        comparison_id
    )
    now = starts.now()
    for seed in document["seeds"]:
        for run in seed["runs"].values():
            run["progress"] = (
                None
                if run["status"] in ("completed", "failed")
                else run_progress(held, begun.get(uuid.UUID(run["run_id"]), []), now)
            )
    return document


def _receipt(request: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    """One choice point as a run read serves it: where and when, what the signal saw, what was
    answered and what the ask cost."""
    provider = receipt["provider"]
    proposal = receipt["proposal"]
    return {
        "decision_seq": receipt["decision_seq"],
        "request_id": str(request["request_id"]),
        "signal_id": request["subject_id"],
        "choice_second": request["context"]["choice_second"],
        "observation": request["context"]["observation"],
        "status": receipt["status"],
        "reason": receipt["reason"],
        "chose": None if proposal is None else proposal["option"]["kind"],
        "provider": None
        if provider is None
        else {
            "model_id": provider["model_id"],
            "cost_usd": provider["cost_usd"],
            "cost_known": provider["cost_known"],
            "latency_ms": provider["latency_ms"],
        },
    }


@router.get("/{comparison_id}/runs/{run_id}")
def signal_comparison_run(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    run_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    world_id: WorldId,
) -> Any:
    """One run's outcome and every choice point's receipt, as recorded; no replay."""
    repository = _repository(connection, session, world_id)
    repository.definition(version_id, comparison_id)
    found = [row for row in repository.runs(comparison_id) if row["run_id"] == run_id]
    if not found:
        raise UnknownSignalComparison("run is unavailable")
    (run,) = found
    outcome = run["outcome"]
    return {
        "profile": RUN_PROFILE,
        "comparison_id": str(comparison_id),
        "run_id": str(run_id),
        "arm": run["arm"],
        "seed_digest": run["seed_digest"],
        "status": "incomplete" if outcome is None else outcome["status"],
        "outcome": outcome,
        "receipts": [_receipt(request, receipt) for request, receipt in repository.stored(run_id)],
    }


@router.get("/{comparison_id}/runs/{run_id}/replay")
def replay_signal_comparison_run(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    run_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """A completed run played again from what it stored, asking no model, held to its record."""
    repository = _repository(connection, session, world_id)
    repository.definition(version_id, comparison_id)
    if run_id not in {row["run_id"] for row in repository.runs(comparison_id)}:
        raise UnknownSignalComparison("run is unavailable")
    runner = get_services(request).signal_comparison_runner(
        session.workspace_id, world_id, session.actor
    )
    try:
        played = runner.replay(comparison_id, run_id)
    except ReplayMismatch as exc:
        return _problem(409, exc.code, str(exc))
    except SignalComparisonRefused as exc:
        return _problem(409, exc.code, exc.detail)
    except _ROADS_ERRORS as error:
        return _roads_refused(error)
    return {
        "profile": REPLAY_PROFILE,
        "comparison_id": str(comparison_id),
        "run_id": str(run_id),
        "reproduced": True,
        "model_calls": 0,
        "points": len(played.receipts),
        "continuation_sha256": played.continuation_sha256,
        "receipts_sha256": played.receipts_sha256,
        "terms": played.terms,
    }


@router.post("/{comparison_id}/cancel")
def cancel_signal_comparison(
    version_id: uuid.UUID,
    comparison_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
    world_id: WorldId,
) -> Any:
    """Cancel a signal comparison started from the application, once, as a comparison of people
    is cancelled: a start no host holds closes now, its open runs failed as
    ``comparison_cancelled`` asking nothing, with what a host whose lease ran out may have spent
    presumed; a host playing it stops before its next ask. A repeated cancel changes nothing, and
    a finished start keeps its own closing. Answers the comparison as the listing states it."""
    repository = _repository(connection, session, world_id)
    row = repository.definition(version_id, comparison_id)
    services = get_services(request)
    starts = SocietyComparisonStarts(connection, session.workspace_id, _KIND)
    with connection.transaction():
        start = starts.lock(world_id, comparison_id)
        if start is None:
            return _problem(
                409,
                "comparison_not_started",
                "only a comparison started from the application is cancelled",
            )
        if start["finished_at"] is None:
            ComparisonFacts(connection, session.workspace_id, world_id, _KIND).cancel(
                comparison_id, session.actor
            )
        held = start["lease_token"] is not None and start["lease_expires_at"] > starts.now()
        if start["finished_at"] is None and not held:
            runner = services.signal_comparison_runner(
                session.workspace_id, world_id, session.actor
            )
            open_runs = repository.open_runs(comparison_id)
            presumed = Decimal(0)
            if start["lease_token"] is not None:
                client = services.model_client
                presumed = stopped_signal_host_usd(
                    row["document"],
                    runner.role,
                    client.budget if client is not None else _ESTIMATOR,
                    load_manifest(),
                    open_runs,
                )
            runner.fail_open(
                comparison_id,
                {run["run_id"]: CANCELLED for run in open_runs},
                connection=connection,
            )
            starts.close_unclaimed(
                world_id, comparison_id, closed_reason=CANCELLED_REASON, presumed_usd=presumed
            )
    return _listing(
        connection,
        session,
        world_id,
        repository,
        [repository.definition(version_id, comparison_id)],
    )


# -- a world's capability read --------------------------------------------------------------------


def capability_operations(context: VersionContext) -> list[Operation]:
    """Starting a comparison of the models that decide the town's signals, and cancelling one, as a
    world's capability read lists them.

    A start is refused in the order the start route refuses before it reads its selection: a start
    of the world that has not finished, roads the version does not state or traffic cannot read
    (by the codes the traffic read answers them with; a network the compiler refuses is found by
    the start itself, which this read does not compile), and this server's own refusal
    (``Services.signal_comparison_refusal``). The plan read is its preview and lists what a start
    may name. A cancel acts on a comparison the listing names and is available while a start of
    the world has not finished, else ``comparison_not_started``; it holds ``model.invoke`` only so
    that whoever may start a paid comparison may stop it, and calls no model.
    """
    roads = None
    try:
        context.roads()
    except TrafficRefused as exc:
        roads = unavailable(exc.code)
    except InvalidStructuralData as exc:
        roads = unavailable(unreadable_reason(exc))
    # A version that states no roads never held a comparison of them: its snapshot is fixed.
    running = (
        None
        if roads is not None and roads.code == "roads_not_stated"
        else SocietyComparisonStarts(
            context.connection, context.session.workspace_id, _KIND
        ).unfinished(context.world_id)
    )
    if running is not None:
        state = unavailable("comparison_running")
    elif roads is not None:
        state = roads
    elif refusal := context.services.signal_comparison_refusal(context.session.workspace_id):
        state = unavailable(refusal)
    else:
        state = AVAILABLE
    return [
        Operation(
            endpoint=start_signal_comparison,
            availability=state,
            subject="version",
            bind=context.bind,
            idempotency="comparison_id",
            preview=Preview(plan_signal_comparison, required=False),
            options=(plan_signal_comparison,),
        ),
        Operation(
            endpoint=cancel_signal_comparison,
            availability=AVAILABLE
            if running is not None
            else unavailable("comparison_not_started"),
            subject="comparison",
            bind=context.bind,
            subjects=Subjects(signal_comparisons, "comparisons"),
            spends=False,
        ),
    ]
