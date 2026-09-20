"""Read one society experiment result through its public GET surface.

This example imports no Exulanica implementation. A caller supplies an HTTP client that already
has its base URL, authentication and timeout policy configured::

    outcome = read_experiment_result(
        http,
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )

The client performs two identity-encoded GET requests. It never prepares, reserves, executes or
finalizes work and never fetches checkpoint or execution evidence. A ``valid`` outcome contains
exact raw metric numerators and denominators, not an interpretation of benefit or statistical
significance. The byte ceiling applies when the supplied client and transport preserve lazy
streaming; work an upstream client already buffered happened outside this consumer's boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal, Protocol

import httpx

DEFINITION_LIMIT = 64 * 1024
ATTEMPT_LIMIT = 3 * 1024 * 1024
STREAM_CHUNK = 16 * 1024
RESULT_PROFILE = "exulanica.society-experiment-result/v1"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")

OutcomeStatus = Literal["valid", "invalid_pair", "incomplete", "failed", "unavailable"]


class ExperimentClientError(Exception):
    """The external read could not produce a trustworthy result."""


class ClientRefused(ExperimentClientError):
    """The server refused a request in a way that is not a scoped unavailable result."""


class MalformedExperimentResponse(ExperimentClientError):
    """A successful response did not satisfy the public experiment contract."""


class HTTPClient(Protocol):
    def stream(
        self, method: str, path: str, *, headers: Mapping[str, str]
    ) -> AbstractContextManager[httpx.Response]: ...


@dataclass(frozen=True, slots=True)
class ExperimentOutcome:
    """Validated compact outcome. Nested records are read-only mappings and tuples."""

    status: OutcomeStatus
    version_id: uuid.UUID
    experiment_id: uuid.UUID
    attempt_id: uuid.UUID
    definition_sha256: str | None = None
    seed_sha256: str | None = None
    checkpoint_sha256: str | None = None
    evidence_sha256: str | None = None
    result_sha256: str | None = None
    metrics: Mapping[str, Any] | None = None
    invalid_pairs: tuple[Mapping[str, Any], ...] = ()
    failure: Mapping[str, Any] | None = None
    problem: Mapping[str, Any] | None = None


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _identifier(value: uuid.UUID | str, name: str) -> uuid.UUID:
    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(value)
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{name} must be a UUID") from exc
    return parsed


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MalformedExperimentResponse(f"duplicate JSON field {key!r}")
        result[key] = value
    return result


def _json(content: bytes, headers: Mapping[str, str], *, limit: int) -> dict[str, Any]:
    declared = headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > limit:
                raise MalformedExperimentResponse("experiment response exceeds its byte limit")
        except ValueError as exc:
            raise MalformedExperimentResponse("invalid Content-Length") from exc
    try:
        body = json.loads(content.decode("utf-8"), object_pairs_hook=_object_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MalformedExperimentResponse("experiment response is not UTF-8 JSON") from exc
    if not isinstance(body, dict):
        raise MalformedExperimentResponse("experiment response must be a JSON object")
    return body


def _get(http: HTTPClient, path: str, *, limit: int) -> tuple[dict[str, Any], bool]:
    with http.stream("GET", path, headers={"Accept-Encoding": "identity"}) as response:
        content_encoding = response.headers.get("content-encoding", "identity").strip().lower()
        if content_encoding not in ("", "identity"):
            raise MalformedExperimentResponse("compressed experiment responses are unsupported")
        declared = response.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > limit:
                    raise MalformedExperimentResponse("experiment response exceeds its byte limit")
            except ValueError as exc:
                raise MalformedExperimentResponse("invalid Content-Length") from exc
        collected = bytearray()
        for chunk in response.iter_bytes(chunk_size=STREAM_CHUNK):
            if len(collected) + len(chunk) > limit:
                raise MalformedExperimentResponse("experiment response exceeds its byte limit")
            collected.extend(chunk)
        status_code = response.status_code
        headers = dict(response.headers)
    body = _json(bytes(collected), headers, limit=limit)
    if status_code == 200:
        return body, True
    if status_code in (404, 424):
        if set(body) != {"code", "detail"} or not all(
            isinstance(body[key], str) and body[key] for key in ("code", "detail")
        ):
            raise MalformedExperimentResponse("unavailable response has no bounded problem")
        return body, False
    raise ClientRefused(f"GET {path} answered {status_code}: {body}")


def _fields(value: dict[str, Any], expected: set[str], name: str) -> None:
    if set(value) != expected:
        raise MalformedExperimentResponse(f"{name} fields do not match the public contract")


def _digest(value: Any, name: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise MalformedExperimentResponse(f"{name} is not a lowercase SHA-256 digest")
    return value


def _uuid_field(value: Any, expected: uuid.UUID, name: str) -> None:
    if not isinstance(value, str):
        raise MalformedExperimentResponse(f"{name} is not a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise MalformedExperimentResponse(f"{name} is not a UUID string") from exc
    if parsed != expected or str(parsed) != value:
        raise MalformedExperimentResponse(f"{name} does not match the requested identity")


def _strict_int(value: Any, name: str, *, positive: bool = False) -> int:
    if type(value) is not int or (positive and value < 1):
        qualifier = "positive " if positive else ""
        raise MalformedExperimentResponse(f"{name} is not a {qualifier}integer")
    return value


def _canonical_check(value: Any, path: str = "$") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str | int):
        return
    if isinstance(value, float):
        raise MalformedExperimentResponse(f"float in digest input at {path}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise MalformedExperimentResponse(f"non-string digest key at {path}")
            _canonical_check(item, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _canonical_check(item, f"{path}[{index}]")
        return
    raise MalformedExperimentResponse(f"unsupported digest value at {path}")


def _canonical_sha256(value: dict[str, Any]) -> str:
    _canonical_check(value)
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_definition(
    body: dict[str, Any], version_id: uuid.UUID, experiment_id: uuid.UUID
) -> tuple[str, int, int]:
    _fields(
        body,
        {
            "record_status",
            "experiment_id",
            "source_society_id",
            "world_id",
            "version_id",
            "definition_sha256",
            "baseline_input_seq",
            "baseline_input_sha256",
            "treatment_input_seq",
            "treatment_input_sha256",
            "intervention",
            "population",
            "warmup_ticks",
            "followup_ticks",
            "created_at",
        },
        "definition",
    )
    if body["record_status"] != "recorded":
        raise MalformedExperimentResponse("definition is not a recorded immutable resource")
    _uuid_field(body["experiment_id"], experiment_id, "definition experiment_id")
    _uuid_field(body["version_id"], version_id, "definition version_id")
    try:
        _identifier(body["source_society_id"], "source_society_id")
    except ValueError as exc:
        raise MalformedExperimentResponse("definition source_society_id is not a UUID") from exc
    if not isinstance(body["world_id"], str) or not body["world_id"]:
        raise MalformedExperimentResponse("definition world_id is empty")
    definition_sha256 = _digest(body["definition_sha256"], "definition_sha256")
    baseline_seq = _strict_int(body["baseline_input_seq"], "baseline_input_seq", positive=True)
    treatment_seq = _strict_int(body["treatment_input_seq"], "treatment_input_seq", positive=True)
    baseline_sha = _digest(body["baseline_input_sha256"], "baseline_input_sha256")
    treatment_sha = _digest(body["treatment_input_sha256"], "treatment_input_sha256")
    population = _strict_int(body["population"], "population", positive=True)
    warmup_ticks = _strict_int(body["warmup_ticks"], "warmup_ticks", positive=True)
    followup_ticks = _strict_int(body["followup_ticks"], "followup_ticks", positive=True)
    if (
        population > 256
        or warmup_ticks > 1_440
        or followup_ticks > 1_440
        or population * (warmup_ticks + 2 * followup_ticks) > 500_000
    ):
        raise MalformedExperimentResponse("definition exceeds the public workload bounds")
    intervention = body["intervention"]
    if not isinstance(intervention, dict) or set(intervention) != {"kind", "target_id"}:
        raise MalformedExperimentResponse("definition intervention is malformed")
    if intervention["kind"] == "noop":
        if intervention["target_id"] is not None or baseline_seq != treatment_seq:
            raise MalformedExperimentResponse("no-op definition does not bind one exact input")
        if baseline_sha != treatment_sha:
            raise MalformedExperimentResponse("no-op definition changed the input digest")
    elif intervention["kind"] == "add_rest_amenity":
        if (
            not isinstance(intervention["target_id"], str)
            or not intervention["target_id"]
            or treatment_seq != baseline_seq + 1
            or baseline_sha == treatment_sha
        ):
            raise MalformedExperimentResponse("rest-amenity definition binding is malformed")
    else:
        raise MalformedExperimentResponse("definition intervention profile is unsupported")
    if not isinstance(body["created_at"], str) or not body["created_at"]:
        raise MalformedExperimentResponse("definition created_at is missing")
    assert definition_sha256 is not None
    return definition_sha256, population, followup_ticks


def _ratio(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {"availability": "unavailable", "reason": "raw denominator is absent"}
    if not isinstance(value, dict):
        raise MalformedExperimentResponse(f"{name} is not a ratio object")
    numerator = value.get("numerator")
    denominator = value.get("denominator")
    if type(numerator) is not int:
        raise MalformedExperimentResponse(f"{name} numerator is not an integer")
    if denominator is None:
        return {
            "availability": "unavailable",
            "reason": "raw denominator is absent",
            "numerator": numerator,
        }
    if type(denominator) is not int or denominator < 0:
        raise MalformedExperimentResponse(f"{name} denominator is not a non-negative integer")
    if denominator == 0:
        return {
            "availability": "unavailable",
            "reason": "raw denominator is zero",
            "numerator": numerator,
            "denominator": denominator,
        }
    if "scaled_by" in value:
        _strict_int(value["scaled_by"], f"{name}.scaled_by", positive=True)
        _strict_int(value.get("scaled_floor"), f"{name}.scaled_floor")
    return value


def _ratio_or_unavailable(value: Any, name: str) -> dict[str, Any]:
    if isinstance(value, dict) and value.get("availability") in {"unavailable", "not_present"}:
        if "reason" in value and not isinstance(value["reason"], str):
            raise MalformedExperimentResponse(f"{name} unavailable reason is not text")
        return value
    return _ratio(value, name)


def _validate_metrics(
    result: dict[str, Any], *, expected_population: int, expected_followup_ticks: int
) -> Mapping[str, Any]:
    arms = deepcopy(result["arms"])
    comparison = deepcopy(result["comparison"])
    if not isinstance(arms, dict) or set(arms) != {"baseline", "treatment"}:
        raise MalformedExperimentResponse("valid result does not contain both arms")
    for label in ("baseline", "treatment"):
        arm = arms[label]
        if not isinstance(arm, dict):
            raise MalformedExperimentResponse(f"{label} arm metrics are malformed")
        _fields(
            arm,
            {
                "population",
                "followup_ticks",
                "high_fatigue_person_minutes",
                "completed_rest_activities",
                "fatigue_milli",
                "focus_rest_occupancy",
                "all_rest_occupancy",
                "travel_mm_per_inhabitant",
                "safety",
                "evidence",
            },
            f"{label} arm",
        )
        if (
            _strict_int(arm["population"], f"{label}.population", positive=True)
            != expected_population
            or _strict_int(arm["followup_ticks"], f"{label}.followup_ticks", positive=True)
            != expected_followup_ticks
        ):
            raise MalformedExperimentResponse(f"{label} population or follow-up binding mismatch")
        for metric in (
            "high_fatigue_person_minutes",
            "completed_rest_activities",
            "all_rest_occupancy",
            "travel_mm_per_inhabitant",
        ):
            arm[metric] = _ratio(arm.get(metric), f"{label}.{metric}")
        arm["focus_rest_occupancy"] = _ratio_or_unavailable(
            arm.get("focus_rest_occupancy"), f"{label}.focus_rest_occupancy"
        )
        fatigue = arm["fatigue_milli"]
        if not isinstance(fatigue, dict) or set(fatigue) != {
            "observations",
            "median_nearest_rank",
            "p95_nearest_rank",
        }:
            raise MalformedExperimentResponse(f"{label}.fatigue_milli is malformed")
        _strict_int(fatigue["observations"], f"{label}.fatigue observations", positive=True)
        _strict_int(fatigue["median_nearest_rank"], f"{label}.fatigue median")
        _strict_int(fatigue["p95_nearest_rank"], f"{label}.fatigue p95")
        safety = arm["safety"]
        if not isinstance(safety, dict) or set(safety) != {
            "stationary_collisions",
            "over_capacity_destination_ticks",
            "transition_refusals",
            "minimum_distinct_positions",
        }:
            raise MalformedExperimentResponse(f"{label}.safety is malformed")
        for name, value in safety.items():
            if _strict_int(value, f"{label}.safety.{name}") < 0:
                raise MalformedExperimentResponse(f"{label}.safety.{name} is negative")
        evidence = arm["evidence"]
        if not isinstance(evidence, dict) or set(evidence) != {
            "state_count",
            "event_count",
            "final_state_sha256",
            "events_sha256",
            "arm_evidence_sha256",
        }:
            raise MalformedExperimentResponse(f"{label}.evidence summary is malformed")
        _strict_int(evidence["state_count"], f"{label}.state_count", positive=True)
        if _strict_int(evidence["event_count"], f"{label}.event_count") < 0:
            raise MalformedExperimentResponse(f"{label}.event_count is negative")
        for name in ("final_state_sha256", "events_sha256", "arm_evidence_sha256"):
            _digest(evidence[name], f"{label}.{name}")
    if not isinstance(comparison, dict) or comparison.get("direction") != "left_minus_right":
        raise MalformedExperimentResponse("comparison direction is not treatment minus baseline")
    if set(comparison) != {
        "direction",
        "high_fatigue_fraction",
        "high_fatigue_relative_change",
        "completed_rest_rate",
        "all_rest_occupancy_fraction",
        "travel_mm_per_inhabitant",
        "fatigue_median_milli",
        "fatigue_p95_milli",
    }:
        raise MalformedExperimentResponse("comparison fields do not match the public contract")
    for metric in (
        "high_fatigue_fraction",
        "completed_rest_rate",
        "all_rest_occupancy_fraction",
        "travel_mm_per_inhabitant",
        "fatigue_median_milli",
        "fatigue_p95_milli",
    ):
        comparison[metric] = _ratio(comparison.get(metric), f"comparison.{metric}")
    comparison["high_fatigue_relative_change"] = _ratio_or_unavailable(
        comparison.get("high_fatigue_relative_change"),
        "comparison.high_fatigue_relative_change",
    )
    return _freeze(
        {
            "arms": arms,
            "comparison": comparison,
            "unsupported_metrics": result["unsupported_metrics"],
        }
    )


def _validate_result(
    result: Any,
    *,
    definition_sha256: str,
    checkpoint_sha256: str,
    seed_sha256: str,
    result_sha256: str,
    expected_population: int,
    expected_followup_ticks: int,
) -> tuple[str, Mapping[str, Any] | None, tuple[Mapping[str, Any], ...]]:
    if not isinstance(result, dict):
        raise MalformedExperimentResponse("completed attempt has no result object")
    _fields(
        result,
        {
            "profile",
            "status",
            "definition_sha256",
            "checkpoint_sha256",
            "seed_sha256",
            "invalid_pairs",
            "arms",
            "comparison",
            "unsupported_metrics",
            "document_sha256",
        },
        "result",
    )
    if result["profile"] != RESULT_PROFILE:
        raise MalformedExperimentResponse("result profile is unsupported")
    for name, expected in (
        ("definition_sha256", definition_sha256),
        ("checkpoint_sha256", checkpoint_sha256),
        ("seed_sha256", seed_sha256),
        ("document_sha256", result_sha256),
    ):
        if _digest(result[name], f"result {name}") != expected:
            raise MalformedExperimentResponse(f"result {name} binding mismatch")
    canonical = {key: value for key, value in result.items() if key != "document_sha256"}
    if _canonical_sha256(canonical) != result_sha256:
        raise MalformedExperimentResponse("result canonical digest mismatch")
    if not isinstance(result["unsupported_metrics"], list):
        raise MalformedExperimentResponse("unsupported metrics must be a list")
    for metric in result["unsupported_metrics"]:
        if (
            not isinstance(metric, dict)
            or set(metric) != {"metric", "reason"}
            or not all(isinstance(metric[key], str) and metric[key] for key in metric)
        ):
            raise MalformedExperimentResponse("unsupported metric declaration is malformed")
    if result["status"] == "valid":
        if result["invalid_pairs"] != []:
            raise MalformedExperimentResponse("valid result carries invalid-pair reasons")
        return (
            "valid",
            _validate_metrics(
                result,
                expected_population=expected_population,
                expected_followup_ticks=expected_followup_ticks,
            ),
            (),
        )
    if result["status"] == "invalid_pair":
        invalid = result["invalid_pairs"]
        if (
            not isinstance(invalid, list)
            or not invalid
            or result["arms"] is not None
            or result["comparison"] is not None
        ):
            raise MalformedExperimentResponse("invalid-pair result shape is malformed")
        for reason in invalid:
            if (
                not isinstance(reason, dict)
                or set(reason) != {"code", "detail"}
                or not all(isinstance(reason[key], str) and reason[key] for key in reason)
            ):
                raise MalformedExperimentResponse("invalid-pair reason is malformed")
        return "invalid_pair", None, tuple(_freeze(reason) for reason in invalid)
    raise MalformedExperimentResponse("result status is unsupported")


def read_experiment_result(
    http: HTTPClient,
    *,
    version_id: uuid.UUID | str,
    experiment_id: uuid.UUID | str,
    attempt_id: uuid.UUID | str,
) -> ExperimentOutcome:
    """Read, bind and validate one compact attempt without interpreting its causal meaning."""
    version = _identifier(version_id, "version_id")
    experiment = _identifier(experiment_id, "experiment_id")
    attempt = _identifier(attempt_id, "attempt_id")
    root = f"/world/versions/{version}/society/experiments/{experiment}"
    definition_body, available = _get(http, root, limit=DEFINITION_LIMIT)
    if not available:
        return ExperimentOutcome(
            "unavailable", version, experiment, attempt, problem=_freeze(definition_body)
        )
    definition_sha256, expected_population, expected_followup_ticks = _validate_definition(
        definition_body, version, experiment
    )

    attempt_body, available = _get(http, f"{root}/attempts/{attempt}", limit=ATTEMPT_LIMIT)
    if not available:
        return ExperimentOutcome(
            "unavailable",
            version,
            experiment,
            attempt,
            definition_sha256=definition_sha256,
            problem=_freeze(attempt_body),
        )
    _fields(
        attempt_body,
        {
            "reservation_status",
            "status",
            "experiment_id",
            "attempt_id",
            "phase",
            "seed_sha256",
            "definition_sha256",
            "checkpoint_sha256",
            "evidence_sha256",
            "result_sha256",
            "failure_sha256",
            "result",
            "failure",
            "created_at",
            "terminal_recorded_at",
        },
        "attempt",
    )
    if attempt_body["reservation_status"] != "reserved" or attempt_body["phase"] != "development":
        raise MalformedExperimentResponse("attempt is not a reserved development record")
    _uuid_field(attempt_body["experiment_id"], experiment, "attempt experiment_id")
    _uuid_field(attempt_body["attempt_id"], attempt, "attempt attempt_id")
    if _digest(attempt_body["definition_sha256"], "attempt definition_sha256") != definition_sha256:
        raise MalformedExperimentResponse("attempt definition digest binding mismatch")
    seed_sha256 = _digest(attempt_body["seed_sha256"], "attempt seed_sha256")
    checkpoint_sha256 = _digest(
        attempt_body["checkpoint_sha256"], "attempt checkpoint_sha256", optional=True
    )
    evidence_sha256 = _digest(
        attempt_body["evidence_sha256"], "attempt evidence_sha256", optional=True
    )
    result_sha256 = _digest(attempt_body["result_sha256"], "attempt result_sha256", optional=True)
    failure_sha256 = _digest(
        attempt_body["failure_sha256"], "attempt failure_sha256", optional=True
    )
    if not isinstance(attempt_body["created_at"], str) or not attempt_body["created_at"]:
        raise MalformedExperimentResponse("attempt created_at is missing")
    status = attempt_body["status"]
    common = dict(
        version_id=version,
        experiment_id=experiment,
        attempt_id=attempt,
        definition_sha256=definition_sha256,
        seed_sha256=seed_sha256,
        checkpoint_sha256=checkpoint_sha256,
        evidence_sha256=evidence_sha256,
        result_sha256=result_sha256,
    )
    if status == "incomplete":
        if any(
            value is not None
            for value in (
                evidence_sha256,
                result_sha256,
                failure_sha256,
                attempt_body["result"],
                attempt_body["failure"],
                attempt_body["terminal_recorded_at"],
            )
        ):
            raise MalformedExperimentResponse("incomplete attempt carries terminal material")
        return ExperimentOutcome("incomplete", **common)
    if status == "failed":
        failure = attempt_body["failure"]
        if (
            evidence_sha256 is not None
            or result_sha256 is not None
            or attempt_body["result"] is not None
            or failure_sha256 is None
            or not isinstance(failure, dict)
            or set(failure) != {"code", "detail", "document_sha256"}
            or _digest(failure["document_sha256"], "failure document_sha256") != failure_sha256
            or not isinstance(failure["code"], str)
            or not failure["code"]
            or not isinstance(failure["detail"], str)
            or not failure["detail"]
            or not isinstance(attempt_body["terminal_recorded_at"], str)
            or not attempt_body["terminal_recorded_at"]
        ):
            raise MalformedExperimentResponse("failed attempt shape is malformed")
        return ExperimentOutcome("failed", **common, failure=_freeze(failure))
    if status != "completed":
        raise MalformedExperimentResponse("attempt status is unsupported")
    if (
        checkpoint_sha256 is None
        or evidence_sha256 is None
        or result_sha256 is None
        or failure_sha256 is not None
        or attempt_body["failure"] is not None
        or not isinstance(attempt_body["terminal_recorded_at"], str)
    ):
        raise MalformedExperimentResponse("completed attempt binding is incomplete")
    assert seed_sha256 is not None
    result_status, metrics, invalid_pairs = _validate_result(
        attempt_body["result"],
        definition_sha256=definition_sha256,
        checkpoint_sha256=checkpoint_sha256,
        seed_sha256=seed_sha256,
        result_sha256=result_sha256,
        expected_population=expected_population,
        expected_followup_ticks=expected_followup_ticks,
    )
    return ExperimentOutcome(
        result_status,
        **common,
        metrics=metrics,
        invalid_pairs=invalid_pairs,
    )
