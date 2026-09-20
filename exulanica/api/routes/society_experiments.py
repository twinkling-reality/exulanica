"""Authenticated preparation and compact reads for controlled society experiments."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from exulanica.api.dependencies import CurrentSession, ScopedConnection
from exulanica.world import society_experiments as experiments
from exulanica.world.society import UnavailableSocietyInput
from exulanica.world.society_experiment_repository import (
    ExperimentConflict,
    ExperimentResourceLimit,
    SocietyExperimentRepository,
    UnknownExperiment,
)

router = APIRouter(prefix="/world/versions/{version_id}/society/experiments", tags=["society"])

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
TargetIdentity = Annotated[str, Field(min_length=1, max_length=1_000)]


class NoopIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["noop"]


class RestAmenityIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kind: Literal["add_rest_amenity"]
    target_id: TargetIdentity


Intervention = Annotated[NoopIntervention | RestAmenityIntervention, Field(discriminator="kind")]


class PrepareExperimentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    experiment_id: uuid.UUID
    baseline_input_seq: Annotated[StrictInt, Field(ge=1)]
    treatment_input_seq: Annotated[StrictInt, Field(ge=1)]
    intervention: Intervention
    population: Annotated[StrictInt, Field(ge=1, le=256)]
    warmup_ticks: Annotated[StrictInt, Field(ge=1, le=1_440)]
    followup_ticks: Annotated[StrictInt, Field(ge=1, le=1_440)]


class ReserveAttemptBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attempt_id: uuid.UUID
    seed_sha256: Digest


class InterventionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["noop", "add_rest_amenity"]
    target_id: str | None = None


class ExperimentDefinitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    record_status: Literal["recorded"]
    experiment_id: uuid.UUID
    source_society_id: uuid.UUID
    world_id: str
    version_id: uuid.UUID
    definition_sha256: Digest
    baseline_input_seq: int
    baseline_input_sha256: Digest
    treatment_input_seq: int
    treatment_input_sha256: Digest
    intervention: InterventionSummary
    population: int
    warmup_ticks: int
    followup_ticks: int
    created_at: dt.datetime


class Ratio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    numerator: int
    denominator: int
    scaled_by: int | None = None
    scaled_floor: int | None = None


class UnavailableRatio(BaseModel):
    model_config = ConfigDict(extra="forbid")
    availability: Literal["unavailable", "not_present"]
    reason: str | None = None


class FatigueSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observations: int
    median_nearest_rank: int
    p95_nearest_rank: int


class SafetySummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stationary_collisions: int
    over_capacity_destination_ticks: int
    transition_refusals: int
    minimum_distinct_positions: int


class ArmEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_count: int
    event_count: int
    final_state_sha256: Digest
    events_sha256: Digest
    arm_evidence_sha256: Digest


class ArmMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    population: int
    followup_ticks: int
    high_fatigue_person_minutes: Ratio
    completed_rest_activities: Ratio
    fatigue_milli: FatigueSummary
    focus_rest_occupancy: Ratio | UnavailableRatio
    all_rest_occupancy: Ratio
    travel_mm_per_inhabitant: Ratio
    safety: SafetySummary
    evidence: ArmEvidenceSummary


class ArmPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline: ArmMetrics
    treatment: ArmMetrics


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    direction: Literal["left_minus_right"]
    high_fatigue_fraction: Ratio
    high_fatigue_relative_change: Ratio | UnavailableRatio
    completed_rest_rate: Ratio
    all_rest_occupancy_fraction: Ratio
    travel_mm_per_inhabitant: Ratio
    fatigue_median_milli: Ratio
    fatigue_p95_milli: Ratio


class InvalidPair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    detail: str


class UnsupportedMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    reason: str


class CompactResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile: Literal["exulanica.society-experiment-result/v1"]
    status: Literal["valid", "invalid_pair"]
    definition_sha256: Digest
    checkpoint_sha256: Digest
    seed_sha256: Digest
    invalid_pairs: list[InvalidPair]
    arms: ArmPair | None
    comparison: Comparison | None
    unsupported_metrics: list[UnsupportedMetric]
    document_sha256: Digest


class FailureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    detail: str
    document_sha256: Digest


class AttemptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reservation_status: Literal["reserved"]
    status: Literal["incomplete", "completed", "failed"]
    experiment_id: uuid.UUID
    attempt_id: uuid.UUID
    phase: Literal["development"]
    seed_sha256: Digest
    definition_sha256: Digest
    checkpoint_sha256: Digest | None
    evidence_sha256: Digest | None
    result_sha256: Digest | None
    failure_sha256: Digest | None
    result: CompactResult | None
    failure: FailureSummary | None
    created_at: dt.datetime
    terminal_recorded_at: dt.datetime | None


def _repository(
    connection: ScopedConnection, session: CurrentSession, request: Request
) -> SocietyExperimentRepository:
    authorizer = getattr(request.app.state, "society_input_authorizer", None)
    return SocietyExperimentRepository(
        connection,
        session.workspace_id,
        input_authorizer=(
            None
            if authorizer is None
            else lambda document: authorizer(connection, session, document)
        ),
    )


def _call(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except UnknownExperiment as exc:
        return JSONResponse(
            status_code=404, content={"code": "unknown_reference", "detail": str(exc)}
        )
    except UnavailableSocietyInput as exc:
        return JSONResponse(
            status_code=424,
            content={"code": "unavailable_society_input", "detail": str(exc)},
        )
    except ExperimentConflict as exc:
        return JSONResponse(
            status_code=409, content={"code": "experiment_conflict", "detail": str(exc)}
        )
    except (ExperimentResourceLimit, experiments.ExperimentIntegrityError, ValueError) as exc:
        return JSONResponse(
            status_code=422, content={"code": "invalid_experiment", "detail": str(exc)}
        )


def _definition_response(row: dict[str, Any]) -> dict[str, Any]:
    document = row["document"]
    intervention = document["intervention"]
    is_noop = intervention["profile"] == experiments.NOOP_PROFILE
    return {
        "record_status": "recorded",
        "experiment_id": row["experiment_id"],
        "source_society_id": row["source_society_id"],
        "world_id": row["world_id"],
        "version_id": row["authored_version_id"],
        "definition_sha256": row["document_sha256"],
        "baseline_input_seq": row["baseline_input_seq"],
        "baseline_input_sha256": row["baseline_input_sha256"],
        "treatment_input_seq": row["treatment_input_seq"],
        "treatment_input_sha256": row["treatment_input_sha256"],
        "intervention": {
            "kind": "noop" if is_noop else "add_rest_amenity",
            "target_id": None if is_noop else intervention["target"]["target_id"],
        },
        "population": document["population"],
        "warmup_ticks": document["warmup_ticks"],
        "followup_ticks": document["followup_ticks"],
        "created_at": row["created_at"],
    }


def _attempt_response(row: dict[str, Any]) -> dict[str, Any]:
    outcome = row["outcome"]
    failure = None if outcome is None else outcome["failure"]
    return {
        "reservation_status": "reserved",
        "status": row["status"],
        "experiment_id": row["experiment_id"],
        "attempt_id": row["attempt_id"],
        "phase": row["phase"],
        "seed_sha256": row["seed_sha256"],
        "definition_sha256": row["definition_sha256"],
        "checkpoint_sha256": row["checkpoint_sha256"],
        "evidence_sha256": None if outcome is None else outcome["evidence_sha256"],
        "result_sha256": None if outcome is None else outcome["result_sha256"],
        "failure_sha256": None if outcome is None else outcome["failure_sha256"],
        "result": None if outcome is None else outcome["result"],
        "failure": (
            None
            if failure is None
            else {
                "code": failure["code"],
                "detail": failure["detail"],
                "document_sha256": failure["document_sha256"],
            }
        ),
        "created_at": row["created_at"],
        "terminal_recorded_at": None if outcome is None else outcome["recorded_at"],
    }


@router.post("", response_model=ExperimentDefinitionResponse)
def prepare_experiment(
    version_id: uuid.UUID,
    body: PrepareExperimentBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
) -> Any:
    intervention = body.intervention
    return _call(
        lambda: _definition_response(
            _repository(connection, session, request).prepare_definition(
                version_id,
                body.experiment_id,
                baseline_input_seq=body.baseline_input_seq,
                treatment_input_seq=body.treatment_input_seq,
                intervention=intervention.kind,
                target_id=(
                    intervention.target_id
                    if isinstance(intervention, RestAmenityIntervention)
                    else None
                ),
                population=body.population,
                warmup_ticks=body.warmup_ticks,
                followup_ticks=body.followup_ticks,
                actor=session.actor,
            )
        )
    )


@router.get("/{experiment_id}", response_model=ExperimentDefinitionResponse)
def read_experiment(
    version_id: uuid.UUID,
    experiment_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
) -> Any:
    return _call(
        lambda: _definition_response(
            _repository(connection, session, request).definition_for_version(
                version_id, experiment_id
            )
        )
    )


@router.post(
    "/{experiment_id}/attempts",
    response_model=AttemptResponse,
    response_model_exclude_unset=True,
)
def reserve_attempt(
    version_id: uuid.UUID,
    experiment_id: uuid.UUID,
    body: ReserveAttemptBody,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
) -> Any:
    repo = _repository(connection, session, request)

    def reserve() -> dict[str, Any]:
        repo.start_attempt_for_version(
            version_id,
            experiment_id,
            body.attempt_id,
            body.seed_sha256,
            actor=session.actor,
        )
        return _attempt_response(repo.attempt_summary(version_id, experiment_id, body.attempt_id))

    return _call(reserve)


@router.get(
    "/{experiment_id}/attempts/{attempt_id}",
    response_model=AttemptResponse,
    response_model_exclude_unset=True,
)
def read_attempt(
    version_id: uuid.UUID,
    experiment_id: uuid.UUID,
    attempt_id: uuid.UUID,
    connection: ScopedConnection,
    session: CurrentSession,
    request: Request,
) -> Any:
    return _call(
        lambda: _attempt_response(
            _repository(connection, session, request).attempt_summary(
                version_id, experiment_id, attempt_id
            )
        )
    )
