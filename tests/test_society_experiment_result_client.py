"""Independent GET-only consumption of compact society experiment results."""

from __future__ import annotations

import ast
import gzip
import hashlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from exulanica.world import society_experiments as experiments
from exulanica.world.society_experiment_repository import SocietyExperimentRepository

from test_society_experiments_api import (
    READER_TOKEN,
    WRITE_ONLY_TOKEN,
    _definition_body,
    _headers,
    experiment_api,
)
from test_society_runtime import runtime_world

pytestmark = pytest.mark.postgres
__all__ = ["experiment_api", "runtime_world"]

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "society_experiment_result_client.py"


def _consumer() -> Any:
    spec = importlib.util.spec_from_file_location("society_experiment_result_client", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_consumer_imports_only_standard_library_and_httpx():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert "exulanica" not in imported
    assert imported - set(sys.stdlib_module_names) == {"httpx"}


class RecordingHTTP:
    def __init__(self, client, token=READER_TOKEN):
        self.client = client
        self.token = token
        self.calls: list[tuple[str, str]] = []

    def stream(self, method: str, path: str, *, headers: dict[str, str]):
        self.calls.append((method, path))
        return self.client.stream(method, path, headers={**headers, **_headers(self.token)})


def _prepare_completed(case):
    client = case["client"]
    version_id = case["world"]["binding"].version_id
    route = f"/world/versions/{version_id}/society/experiments"
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    assert (
        client.post(
            route,
            headers=_headers(),
            json=_definition_body(case, experiment_id),
        ).status_code
        == 200
    )
    seed = experiments.DEVELOPMENT_SEEDS[4]
    assert (
        client.post(
            f"{route}/{experiment_id}/attempts",
            headers=_headers(),
            json={"attempt_id": str(attempt_id), "seed_sha256": seed},
        ).status_code
        == 200
    )
    repo = SocietyExperimentRepository(
        case["world"]["connection"],
        case["world"]["workspace"],
        input_authorizer=lambda document: case["world"]["runtime"].authorize(
            case["world"]["connection"], case["world"]["session"], document
        ),
    )
    definition = repo.definition(experiment_id)["document"]
    checkpoint = experiments.prepare_checkpoint(definition, seed, case["baseline"])
    repo.save_checkpoint(attempt_id, checkpoint)
    result, evidence = experiments.execute_pair(
        definition, checkpoint, case["baseline"], case["treatment"]
    )
    assert evidence is not None
    repo.complete_attempt(attempt_id, evidence, result)
    return version_id, experiment_id, attempt_id, result, evidence


def test_private_http_completed_fixture_matches_independent_raw_counts_and_uses_get_only(
    experiment_api,
):
    case = experiment_api
    version_id, experiment_id, attempt_id, result, evidence = _prepare_completed(case)
    http = RecordingHTTP(case["client"])
    outcome = _consumer().read_experiment_result(
        http,
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )
    assert outcome.status == "valid"
    assert http.calls == [
        ("GET", f"/world/versions/{version_id}/society/experiments/{experiment_id}"),
        (
            "GET",
            f"/world/versions/{version_id}/society/experiments/{experiment_id}/attempts/"
            f"{attempt_id}",
        ),
    ]
    threshold = 500
    for label in ("baseline", "treatment"):
        states = evidence["arms"][label]["states"]
        expected_numerator = sum(
            person["needs"]["fatigue"] >= threshold
            for state in states
            for person in state["inhabitants"]
        )
        expected_denominator = len(states) * len(states[0]["inhabitants"])
        consumed = outcome.metrics["arms"][label]["high_fatigue_person_minutes"]
        assert consumed["numerator"] == expected_numerator
        assert consumed["denominator"] == expected_denominator == 9
    assert outcome.metrics["comparison"]["direction"] == "left_minus_right"
    assert outcome.result_sha256 == result["document_sha256"]


def test_private_http_incomplete_failed_denied_and_withdrawn_outcomes(experiment_api):
    case = experiment_api
    client = case["client"]
    version_id = case["world"]["binding"].version_id
    route = f"/world/versions/{version_id}/society/experiments"
    experiment_id, attempt_id = uuid.uuid4(), uuid.uuid4()
    assert (
        client.post(
            route, headers=_headers(), json=_definition_body(case, experiment_id)
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{route}/{experiment_id}/attempts",
            headers=_headers(),
            json={
                "attempt_id": str(attempt_id),
                "seed_sha256": experiments.DEVELOPMENT_SEEDS[5],
            },
        ).status_code
        == 200
    )
    consumer = _consumer()
    incomplete = consumer.read_experiment_result(
        RecordingHTTP(client),
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )
    assert incomplete.status == "incomplete" and incomplete.metrics is None

    repo = SocietyExperimentRepository(
        case["world"]["connection"],
        case["world"]["workspace"],
        input_authorizer=lambda document: case["world"]["runtime"].authorize(
            case["world"]["connection"], case["world"]["session"], document
        ),
    )
    repo.fail_attempt(attempt_id, code="operator_aborted", detail="independent consumer fixture")
    failed = consumer.read_experiment_result(
        RecordingHTTP(client),
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )
    assert failed.status == "failed"
    assert failed.failure["code"] == "operator_aborted"

    denied = consumer.read_experiment_result(
        RecordingHTTP(client, WRITE_ONLY_TOKEN),
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )
    assert denied.status == "unavailable" and denied.problem["code"] == "unknown_reference"

    source = case["world"]["binding"].sources[0]
    case["world"]["admissions"].withdraw("source", source.admission_id)
    withdrawn = consumer.read_experiment_result(
        RecordingHTTP(client),
        version_id=version_id,
        experiment_id=experiment_id,
        attempt_id=attempt_id,
    )
    assert withdrawn.status == "unavailable"
    assert withdrawn.problem["code"] == "unavailable_society_input"


def _sha(document: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            document,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


VERSION_ID = uuid.UUID("0199a6f0-0000-7000-8000-000000000001")
EXPERIMENT_ID = uuid.UUID("0199a6f0-0000-7000-8000-000000000002")
ATTEMPT_ID = uuid.UUID("0199a6f0-0000-7000-8000-000000000003")
DEFINITION_SHA = "1" * 64
CHECKPOINT_SHA = "2" * 64
EVIDENCE_SHA = "3" * 64
SEED_SHA = "4" * 64


def _definition() -> dict[str, Any]:
    return {
        "record_status": "recorded",
        "experiment_id": str(EXPERIMENT_ID),
        "source_society_id": "0199a6f0-0000-7000-8000-000000000004",
        "world_id": "atlas:default",
        "version_id": str(VERSION_ID),
        "definition_sha256": DEFINITION_SHA,
        "baseline_input_seq": 1,
        "baseline_input_sha256": "5" * 64,
        "treatment_input_seq": 2,
        "treatment_input_sha256": "6" * 64,
        "intervention": {"kind": "add_rest_amenity", "target_id": "authored:rest"},
        "population": 3,
        "warmup_ticks": 2,
        "followup_ticks": 3,
        "created_at": "2026-09-19T12:00:00+00:00",
    }


def _ratio(numerator=1, denominator=9):
    return {"numerator": numerator, "denominator": denominator}


def _arm() -> dict[str, Any]:
    return {
        "population": 3,
        "followup_ticks": 3,
        "high_fatigue_person_minutes": _ratio(),
        "completed_rest_activities": _ratio(),
        "fatigue_milli": {
            "observations": 9,
            "median_nearest_rank": 400,
            "p95_nearest_rank": 600,
        },
        "focus_rest_occupancy": {"availability": "not_present"},
        "all_rest_occupancy": _ratio(),
        "travel_mm_per_inhabitant": _ratio(100, 3),
        "safety": {
            "stationary_collisions": 0,
            "over_capacity_destination_ticks": 0,
            "transition_refusals": 0,
            "minimum_distinct_positions": 3,
        },
        "evidence": {
            "state_count": 3,
            "event_count": 1,
            "final_state_sha256": "7" * 64,
            "events_sha256": "8" * 64,
            "arm_evidence_sha256": "9" * 64,
        },
    }


def _valid_result() -> dict[str, Any]:
    result = {
        "profile": "exulanica.society-experiment-result/v1",
        "status": "valid",
        "definition_sha256": DEFINITION_SHA,
        "checkpoint_sha256": CHECKPOINT_SHA,
        "seed_sha256": SEED_SHA,
        "invalid_pairs": [],
        "arms": {"baseline": _arm(), "treatment": _arm()},
        "comparison": {
            "direction": "left_minus_right",
            "high_fatigue_fraction": _ratio(0, 1),
            "high_fatigue_relative_change": {
                "availability": "unavailable",
                "reason": "right arm has zero high-fatigue minutes",
            },
            "completed_rest_rate": _ratio(0, 1),
            "all_rest_occupancy_fraction": _ratio(0, 1),
            "travel_mm_per_inhabitant": _ratio(0, 1),
            "fatigue_median_milli": _ratio(0, 1),
            "fatigue_p95_milli": _ratio(0, 1),
        },
        "unsupported_metrics": [],
    }
    result["document_sha256"] = _sha(result)
    return result


def _attempt(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "reservation_status": "reserved",
        "status": "completed",
        "experiment_id": str(EXPERIMENT_ID),
        "attempt_id": str(ATTEMPT_ID),
        "phase": "development",
        "seed_sha256": SEED_SHA,
        "definition_sha256": DEFINITION_SHA,
        "checkpoint_sha256": CHECKPOINT_SHA,
        "evidence_sha256": EVIDENCE_SHA,
        "result_sha256": result["document_sha256"],
        "failure_sha256": None,
        "result": result,
        "failure": None,
        "created_at": "2026-09-19T12:00:00+00:00",
        "terminal_recorded_at": "2026-09-19T12:01:00+00:00",
    }


def _scripted(definition: dict[str, Any], attempt: dict[str, Any]):
    def serve(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(f"/attempts/{ATTEMPT_ID}"):
            return httpx.Response(200, json=attempt)
        return httpx.Response(200, json=definition)

    return httpx.Client(base_url="http://experiment", transport=httpx.MockTransport(serve))


def test_scripted_invalid_pair_and_zero_or_absent_denominators_remain_unavailable_metrics():
    consumer = _consumer()
    invalid = {
        "profile": "exulanica.society-experiment-result/v1",
        "status": "invalid_pair",
        "definition_sha256": DEFINITION_SHA,
        "checkpoint_sha256": CHECKPOINT_SHA,
        "seed_sha256": SEED_SHA,
        "invalid_pairs": [{"code": "intervention_unreachable", "detail": "no route"}],
        "arms": None,
        "comparison": None,
        "unsupported_metrics": [],
    }
    invalid["document_sha256"] = _sha(invalid)
    with _scripted(_definition(), _attempt(invalid)) as http:
        outcome = consumer.read_experiment_result(
            http,
            version_id=VERSION_ID,
            experiment_id=EXPERIMENT_ID,
            attempt_id=ATTEMPT_ID,
        )
    assert outcome.status == "invalid_pair"
    assert outcome.invalid_pairs[0]["code"] == "intervention_unreachable"

    result = _valid_result()
    result["arms"]["baseline"]["high_fatigue_person_minutes"] = {
        "numerator": 0,
        "denominator": 0,
    }
    del result["arms"]["treatment"]["completed_rest_activities"]["denominator"]
    result["document_sha256"] = _sha(
        {key: value for key, value in result.items() if key != "document_sha256"}
    )
    with _scripted(_definition(), _attempt(result)) as http:
        outcome = consumer.read_experiment_result(
            http,
            version_id=VERSION_ID,
            experiment_id=EXPERIMENT_ID,
            attempt_id=ATTEMPT_ID,
        )
    assert outcome.status == "valid"
    baseline = outcome.metrics["arms"]["baseline"]["high_fatigue_person_minutes"]
    treatment = outcome.metrics["arms"]["treatment"]["completed_rest_activities"]
    assert baseline == {
        "availability": "unavailable",
        "reason": "raw denominator is zero",
        "numerator": 0,
        "denominator": 0,
    }
    assert treatment == {
        "availability": "unavailable",
        "reason": "raw denominator is absent",
        "numerator": 1,
    }


@pytest.mark.parametrize("mutation", ["identity", "digest", "negative", "direction"])
def test_mismatched_or_malformed_success_responses_refuse(mutation):
    consumer = _consumer()
    definition = _definition()
    result = _valid_result()
    attempt = _attempt(result)
    if mutation == "identity":
        definition["experiment_id"] = str(uuid.uuid4())
    elif mutation == "digest":
        result["arms"]["baseline"]["all_rest_occupancy"]["numerator"] += 1
    elif mutation == "negative":
        result["arms"]["baseline"]["all_rest_occupancy"]["denominator"] = -1
        result["document_sha256"] = _sha(
            {key: value for key, value in result.items() if key != "document_sha256"}
        )
        attempt["result_sha256"] = result["document_sha256"]
    else:
        result["comparison"]["direction"] = "baseline_minus_treatment"
        result["document_sha256"] = _sha(
            {key: value for key, value in result.items() if key != "document_sha256"}
        )
        attempt["result_sha256"] = result["document_sha256"]
    with (
        _scripted(definition, attempt) as http,
        pytest.raises(consumer.MalformedExperimentResponse),
    ):
        consumer.read_experiment_result(
            http,
            version_id=VERSION_ID,
            experiment_id=EXPERIMENT_ID,
            attempt_id=ATTEMPT_ID,
        )


class ChunkStream(httpx.SyncByteStream):
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.yielded = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk

    def close(self):
        self.closed = True


def test_streaming_limit_stops_before_buffering_the_rest_and_closes_response():
    consumer = _consumer()
    stream = ChunkStream([b"a" * consumer.STREAM_CHUNK for _ in range(6)])

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, stream=stream)

    with (
        httpx.Client(base_url="http://experiment", transport=httpx.MockTransport(serve)) as http,
        pytest.raises(consumer.MalformedExperimentResponse, match="byte limit"),
    ):
        consumer.read_experiment_result(
            http,
            version_id=VERSION_ID,
            experiment_id=EXPERIMENT_ID,
            attempt_id=ATTEMPT_ID,
        )
    assert stream.yielded == 5
    assert stream.closed


def test_compressed_lazy_response_is_closed_without_consuming_body_chunks():
    consumer = _consumer()
    payload = b'{"padding":"' + b"a" * consumer.DEFINITION_LIMIT + b'"}'
    compressed = gzip.compress(payload)
    assert len(compressed) < consumer.DEFINITION_LIMIT
    stream = ChunkStream([compressed])

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(
            200,
            stream=stream,
            headers={
                "Content-Encoding": "gzip",
                "Content-Length": str(len(compressed)),
            },
        )

    with (
        httpx.Client(base_url="http://experiment", transport=httpx.MockTransport(serve)) as http,
        pytest.raises(consumer.MalformedExperimentResponse, match="compressed"),
    ):
        consumer.read_experiment_result(
            http,
            version_id=VERSION_ID,
            experiment_id=EXPERIMENT_ID,
            attempt_id=ATTEMPT_ID,
        )
    assert stream.yielded == 0
    assert stream.closed
