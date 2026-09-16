"""Offline, provider-neutral preflight for task-specific model comparisons.

The preflight binds bytes, authority receipts, immutable candidate revisions, the existing
pipeline interface, a symmetric scoring protocol, and a bounded execution environment.  It
does not load a model, contact a provider, allocate compute, or turn an input-rights receipt
into execution authority.  Every planned run starts as explicitly unavailable, and result
inspection keeps comparison claims unavailable until every frozen run slot has a complete,
byte-verifiable success record.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.ingest.stages.segmentation import local_model_roles
from exulanica.models.manifest import MANIFEST_PATH, Role, load_manifest_from

__all__ = [
    "PREFLIGHT_PROFILE",
    "REQUEST_PROFILE",
    "RESULT_PROFILE",
    "SUPPORTED_TASKS",
    "inspect_request",
    "inspect_results",
    "read_preflight",
]

REQUEST_PROFILE: Final = "exulanica.model-evaluation-request/v1"
PREFLIGHT_PROFILE: Final = "exulanica.model-evaluation-preflight/v1"
RESULT_PROFILE: Final = "exulanica.model-evaluation-result/v1"

SUPPORTED_TASKS: Final = {
    "scene_geometry": "exulanica.reconstruction.depth.DepthModel.predict",
    "mask": "exulanica.ingest.stages.segmentation.ObjectSegmenter.segment",
    "grounded_detection": "exulanica.ingest.stages.segmentation.ObjectSegmenter.detect",
    "character_fitting": "scripts.parametric_character.preview_server.Builder.generate",
}
AUTHORITY_RECHECKS: Final = {
    "scene_read_policy": "exulanica.graph.asset_read_policy.scene_allowed",
    "privacy_screening": "exulanica.ingest.privacy.require_privacy_screening",
    "reference_inputs": "exulanica.evaluation.reference_inputs.verify_inputs",
    "character_preparation": "scripts.parametric_character.inputs.verify_inputs",
}
_LOCAL_ROLE_TASKS: Final = {
    "object_segmentation": frozenset({"mask"}),
    "open_vocabulary_detection": frozenset({"grounded_detection"}),
}

_SHA256 = re.compile(r"[0-9a-f]{64}")
_GIT_REVISION = re.compile(r"[0-9a-f]{40}")
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_IMAGE = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")
_RESULT_STATES = frozenset({"succeeded", "failed", "unavailable"})


class InvalidRequest(ValueError):
    """A request is malformed or its local bytes disagree with their binding."""


class UnavailableRequest(ValueError):
    """A well-shaped request lacks an authority, immutable revision, or sufficient budget."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise InvalidRequest(f"{field} must be lowercase SHA-256 hex")
    return value


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise InvalidRequest(f"{field} must be a stable lowercase identifier")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise InvalidRequest(f"{field} must be non-empty trimmed text")
    return value


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise InvalidRequest(f"{field} must be an integer of at least {minimum}")
    return value


def _time(value: object, field: str) -> dt.datetime:
    if not isinstance(value, str):
        raise InvalidRequest(f"{field} must be an offset timestamp")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidRequest(f"{field} must be an offset timestamp") from exc
    if parsed.utcoffset() is None:
        raise InvalidRequest(f"{field} must be an offset timestamp")
    return parsed


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidRequest(f"{field} must be an object")
    return value


def _array(value: object, field: str) -> Sequence[Any]:
    if not isinstance(value, list):
        raise InvalidRequest(f"{field} must be an array")
    return value


def _keys(
    value: Mapping[str, Any], *, required: Iterable[str], optional: Iterable[str] = (), field: str
) -> None:
    required_set, optional_set = set(required), set(optional)
    missing = required_set - set(value)
    extra = set(value) - required_set - optional_set
    if missing or extra:
        detail = []
        if missing:
            detail.append("missing " + ", ".join(sorted(missing)))
        if extra:
            detail.append("unexpected " + ", ".join(sorted(extra)))
        raise InvalidRequest(f"{field} has " + "; ".join(detail))


def _relative(value: object, field: str) -> str:
    text = _text(value, field)
    path = PurePosixPath(text)
    if (
        path.as_posix() != text
        or path.is_absolute()
        or text == "."
        or ".." in path.parts
        or "\\" in text
    ):
        raise InvalidRequest(f"{field} must be a normalized relative path")
    return text


def _local_file(root: Path, relative: str, field: str) -> Path:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise InvalidRequest(f"{field} must name an existing regular file")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or any(
        part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(root)
    ):
        raise InvalidRequest(f"{field} must not escape through a symbolic link")
    return resolved


def _revision(value: object, field: str) -> dict[str, str]:
    revision = _object(value, field)
    _keys(revision, required=("kind", "value"), field=field)
    kind = revision["kind"]
    raw = revision["value"]
    if kind == "git_commit":
        if not isinstance(raw, str) or not _GIT_REVISION.fullmatch(raw):
            raise UnavailableRequest(f"{field} needs an exact lowercase Git commit")
    elif kind == "artifact_sha256":
        _sha(raw, field + ".value")
    else:
        raise UnavailableRequest(
            f"{field} must be a git_commit or artifact_sha256; mutable or unavailable "
            "revisions cannot support a comparison"
        )
    return {"kind": kind, "value": raw}


def _authority(raw: object, *, root: Path, prepared_at: dt.datetime, field: str) -> dict[str, Any]:
    authority = _object(raw, field)
    _keys(
        authority,
        required=("state", "basis", "scope", "recheck", "checked_at", "valid_until"),
        optional=("receipt_path", "receipt_sha256"),
        field=field,
    )
    state = authority["state"]
    if state not in {"authorized", "unavailable"}:
        raise InvalidRequest(f"{field}.state must be authorized or unavailable")
    result: dict[str, Any] = {
        "state": state,
        "basis": _text(authority["basis"], field + ".basis"),
        "scope": _text(authority["scope"], field + ".scope"),
        "recheck": authority["recheck"],
        "checked_at": _text(authority["checked_at"], field + ".checked_at"),
        "valid_until": authority["valid_until"],
    }
    checked_at = _time(result["checked_at"], field + ".checked_at")
    if result["recheck"] not in AUTHORITY_RECHECKS:
        raise InvalidRequest(f"{field}.recheck must name an existing authority boundary")
    result["recheck_interface"] = AUTHORITY_RECHECKS[result["recheck"]]
    if checked_at > prepared_at:
        raise InvalidRequest(f"{field}.checked_at is after prepared_at")
    if state == "unavailable":
        if "receipt_path" in authority or "receipt_sha256" in authority:
            raise InvalidRequest(f"{field} cannot attach an authorization receipt when unavailable")
        raise UnavailableRequest(f"{field} is explicitly unavailable")
    if "receipt_path" not in authority or "receipt_sha256" not in authority:
        raise UnavailableRequest(f"{field} needs exact authorization receipt bytes")
    receipt_relative = _relative(authority["receipt_path"], field + ".receipt_path")
    receipt = _local_file(root, receipt_relative, field + ".receipt_path")
    receipt_sha = _sha(authority["receipt_sha256"], field + ".receipt_sha256")
    if _digest_file(receipt) != receipt_sha:
        raise InvalidRequest(f"{field} authorization receipt bytes changed")
    valid_until = authority["valid_until"]
    if valid_until is not None:
        expires = _time(valid_until, field + ".valid_until")
        if prepared_at >= expires:
            raise UnavailableRequest(f"{field} expired before prepared_at")
    result.update(receipt_path=receipt_relative, receipt_sha256=receipt_sha)
    return result


def _input_artifacts(
    raw: object, *, root: Path, prepared_at: dt.datetime
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    artifacts: list[dict[str, Any]] = []
    indexed: dict[str, dict[str, Any]] = {}
    for index, item_raw in enumerate(_array(raw, "input_artifacts")):
        field = f"input_artifacts[{index}]"
        item = _object(item_raw, field)
        _keys(
            item,
            required=("artifact_id", "kind", "path", "sha256", "bytes", "authority"),
            field=field,
        )
        artifact_id = _identifier(item["artifact_id"], field + ".artifact_id")
        if artifact_id in indexed:
            raise InvalidRequest("input artifact ids must be unique")
        relative = _relative(item["path"], field + ".path")
        path = _local_file(root, relative, field + ".path")
        expected_sha = _sha(item["sha256"], field + ".sha256")
        expected_bytes = _integer(item["bytes"], field + ".bytes", minimum=1)
        if path.stat().st_size != expected_bytes or _digest_file(path) != expected_sha:
            raise InvalidRequest(f"{field} bytes changed")
        normalized = {
            "artifact_id": artifact_id,
            "kind": _identifier(item["kind"], field + ".kind"),
            "path": relative,
            "sha256": expected_sha,
            "bytes": expected_bytes,
            "authority": _authority(
                item["authority"], root=root, prepared_at=prepared_at, field=field + ".authority"
            ),
        }
        artifacts.append(normalized)
        indexed[artifact_id] = normalized
    if not artifacts:
        raise InvalidRequest("input_artifacts must not be empty")
    artifacts.sort(key=lambda item: item["artifact_id"])
    return artifacts, indexed


def _candidate(
    raw: object,
    *,
    index: int,
    hosted_manifest: Any,
    local_roles: Mapping[str, Any],
) -> dict[str, Any]:
    field = f"candidates[{index}]"
    item = _object(raw, field)
    _keys(
        item,
        required=(
            "candidate_id",
            "model_id",
            "revision",
            "license",
            "task_kinds",
            "selection",
        ),
        field=field,
    )
    candidate_id = _identifier(item["candidate_id"], field + ".candidate_id")
    model_id = _text(item["model_id"], field + ".model_id")
    revision = _revision(item["revision"], field + ".revision")
    licence = _text(item["license"], field + ".license")
    task_kinds = sorted(
        _text(value, field + ".task_kinds")
        for value in _array(item["task_kinds"], field + ".task_kinds")
    )
    if (
        not task_kinds
        or len(set(task_kinds)) != len(task_kinds)
        or any(kind not in SUPPORTED_TASKS for kind in task_kinds)
    ):
        raise InvalidRequest(f"{field}.task_kinds must name unique existing interfaces")
    selection = _object(item["selection"], field + ".selection")
    kind = selection.get("kind")
    if kind == "manifest_local_role":
        _keys(selection, required=("kind", "role", "position"), field=field + ".selection")
        role = _text(selection["role"], field + ".selection.role")
        position = selection["position"]
        if role not in local_roles or position not in {"primary", "fallback"}:
            raise InvalidRequest(f"{field}.selection does not resolve through local_roles")
        pin = getattr(local_roles[role], position)
        if pin is None:
            raise UnavailableRequest(f"{field}.selection names an unavailable manifest fallback")
        if not set(task_kinds) <= _LOCAL_ROLE_TASKS.get(role, frozenset()):
            raise InvalidRequest(f"{field}.task_kinds exceed the local role interface")
        if (
            model_id != pin.repo_id
            or licence != pin.license
            or revision != {"kind": "git_commit", "value": pin.revision}
        ):
            raise InvalidRequest(f"{field} differs from its local manifest role binding")
        normalized_selection = {
            "kind": kind,
            "role": role,
            "position": position,
            "production_selected": True,
        }
    elif kind == "manifest_hosted_role":
        _keys(selection, required=("kind", "role", "position"), field=field + ".selection")
        try:
            binding = hosted_manifest[Role(selection["role"])]
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidRequest(f"{field}.selection does not resolve through roles") from exc
        position = selection["position"]
        if position not in {"primary", "fallback"}:
            raise InvalidRequest(f"{field}.selection.position must be primary or fallback")
        spec = getattr(binding, position)
        if spec is None or spec.model_id != model_id or spec.catalog_license != licence:
            raise InvalidRequest(f"{field} differs from its hosted manifest role binding")
        # The existing selection contract intentionally exposes no hosted model revision.
        # A caller-supplied commit would be fabricated, so this remains an explicit unavailable
        # result instead of silently treating the service identifier as a revision.
        raise UnavailableRequest(
            f"{field} is hosted through a service that exposes no immutable model revision"
        )
    elif kind == "evaluation_only":
        _keys(selection, required=("kind", "source"), field=field + ".selection")
        normalized_selection = {
            "kind": kind,
            "source": _text(selection["source"], field + ".selection.source"),
            "production_selected": False,
            "promotion_requires_model_manifest_review": True,
        }
    else:
        raise InvalidRequest(
            f"{field}.selection.kind must be manifest_local_role, manifest_hosted_role, "
            "or evaluation_only"
        )
    return {
        "candidate_id": candidate_id,
        "model_id": model_id,
        "revision": revision,
        "license": licence,
        "task_kinds": task_kinds,
        "selection": normalized_selection,
    }


def _candidates(
    raw: object, *, hosted_manifest: Any, local_roles: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates = [
        _candidate(item, index=index, hosted_manifest=hosted_manifest, local_roles=local_roles)
        for index, item in enumerate(_array(raw, "candidates"))
    ]
    indexed = {item["candidate_id"]: item for item in candidates}
    if len(candidates) < 2 or len(indexed) != len(candidates):
        raise InvalidRequest("candidates need at least two unique entries")
    candidates.sort(key=lambda item: item["candidate_id"])
    return candidates, indexed


def _metric(raw: object, field: str) -> dict[str, Any]:
    item = _object(raw, field)
    _keys(
        item,
        required=("key", "unit", "direction", "aggregation", "acceptance"),
        field=field,
    )
    direction = item["direction"]
    if direction not in {"higher", "lower"}:
        raise InvalidRequest(f"{field}.direction must be higher or lower")
    if item["aggregation"] != "median_and_range":
        raise InvalidRequest(f"{field}.aggregation must be median_and_range")
    acceptance = item["acceptance"]
    normalized_acceptance = None
    if acceptance is not None:
        rule = _object(acceptance, field + ".acceptance")
        _keys(rule, required=("operator", "value"), field=field + ".acceptance")
        expected = "gte" if direction == "higher" else "lte"
        if rule["operator"] != expected:
            raise InvalidRequest(f"{field}.acceptance operator disagrees with direction")
        normalized_acceptance = {
            "operator": expected,
            "value": _integer(rule["value"], field + ".acceptance.value"),
        }
    return {
        "key": _identifier(item["key"], field + ".key"),
        "unit": _identifier(item["unit"], field + ".unit"),
        "direction": direction,
        "aggregation": "median_and_range",
        "acceptance": normalized_acceptance,
    }


def _rubric(raw: object, field: str) -> dict[str, Any]:
    item = _object(raw, field)
    _keys(
        item,
        required=("scale_min", "scale_max", "minimum", "blinded", "protocol", "dimensions"),
        field=field,
    )
    scale_min = _integer(item["scale_min"], field + ".scale_min")
    scale_max = _integer(item["scale_max"], field + ".scale_max", minimum=scale_min + 1)
    minimum = _integer(item["minimum"], field + ".minimum", minimum=scale_min)
    if minimum > scale_max:
        raise InvalidRequest(f"{field}.minimum exceeds scale_max")
    if item["blinded"] is not True:
        raise InvalidRequest(f"{field}.blinded must be true for a symmetric comparison")
    dimensions = []
    for index, raw_dimension in enumerate(_array(item["dimensions"], field + ".dimensions")):
        dimension = _object(raw_dimension, f"{field}.dimensions[{index}]")
        _keys(
            dimension,
            required=("key", "prompt"),
            field=f"{field}.dimensions[{index}]",
        )
        dimensions.append(
            {
                "key": _identifier(dimension["key"], f"{field}.dimensions[{index}].key"),
                "prompt": _text(dimension["prompt"], f"{field}.dimensions[{index}].prompt"),
            }
        )
    if not dimensions or len({item["key"] for item in dimensions}) != len(dimensions):
        raise InvalidRequest(f"{field}.dimensions must be non-empty and unique")
    return {
        "scale_min": scale_min,
        "scale_max": scale_max,
        "minimum": minimum,
        "blinded": True,
        "reviewer": "named_human_required",
        "protocol": _text(item["protocol"], field + ".protocol"),
        "dimensions": dimensions,
    }


def _tasks(
    raw: object,
    *,
    candidates: Mapping[str, dict[str, Any]],
    artifacts: Mapping[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tasks: list[dict[str, Any]] = []
    slots: list[dict[str, Any]] = []
    task_ids: set[str] = set()
    for index, task_raw in enumerate(_array(raw, "tasks")):
        field = f"tasks[{index}]"
        item = _object(task_raw, field)
        _keys(
            item,
            required=(
                "task_id",
                "kind",
                "candidate_ids",
                "input_artifact_ids",
                "runs_per_candidate",
                "metrics",
                "rubric",
                "output_kinds",
            ),
            field=field,
        )
        task_id = _identifier(item["task_id"], field + ".task_id")
        if task_id in task_ids:
            raise InvalidRequest("task ids must be unique")
        task_ids.add(task_id)
        kind = item["kind"]
        if kind not in SUPPORTED_TASKS:
            raise InvalidRequest(f"{field}.kind is not an existing evaluation interface")
        candidate_ids = sorted(
            _identifier(value, field + ".candidate_ids")
            for value in _array(item["candidate_ids"], field + ".candidate_ids")
        )
        if (
            len(candidate_ids) < 2
            or len(set(candidate_ids)) != len(candidate_ids)
            or any(candidate_id not in candidates for candidate_id in candidate_ids)
            or any(
                kind not in candidates[candidate_id]["task_kinds"] for candidate_id in candidate_ids
            )
        ):
            raise InvalidRequest(
                f"{field} needs at least two unique candidates declared for its interface"
            )
        input_ids = sorted(
            _identifier(value, field + ".input_artifact_ids")
            for value in _array(item["input_artifact_ids"], field + ".input_artifact_ids")
        )
        if (
            not input_ids
            or len(set(input_ids)) != len(input_ids)
            or any(artifact_id not in artifacts for artifact_id in input_ids)
        ):
            raise InvalidRequest(f"{field} must name unique declared input artifacts")
        runs = _integer(item["runs_per_candidate"], field + ".runs_per_candidate", minimum=3)
        metrics = [
            _metric(metric, f"{field}.metrics[{metric_index}]")
            for metric_index, metric in enumerate(_array(item["metrics"], field + ".metrics"))
        ]
        if not metrics or len({metric["key"] for metric in metrics}) != len(metrics):
            raise InvalidRequest(f"{field}.metrics must be non-empty and unique")
        output_kinds = sorted(
            _identifier(value, field + ".output_kinds")
            for value in _array(item["output_kinds"], field + ".output_kinds")
        )
        if not output_kinds or len(set(output_kinds)) != len(output_kinds):
            raise InvalidRequest(f"{field}.output_kinds must be non-empty and unique")
        normalized = {
            "task_id": task_id,
            "kind": kind,
            "interface": SUPPORTED_TASKS[kind],
            "candidate_ids": candidate_ids,
            "input_artifact_ids": input_ids,
            "runs_per_candidate": runs,
            "metrics": metrics,
            "rubric": _rubric(item["rubric"], field + ".rubric"),
            "output_kinds": output_kinds,
            "comparison_rule": (
                "Apply identical inputs, limits, metric definitions and blinded rubric to every "
                "candidate. Report median and range; no weights or preferred candidate are frozen."
            ),
        }
        tasks.append(normalized)
        for candidate_id in candidate_ids:
            for run_index in range(1, runs + 1):
                slot_id = f"{task_id}.{candidate_id}.run-{run_index:02d}"
                slots.append(
                    {
                        "slot_id": slot_id,
                        "task_id": task_id,
                        "candidate_id": candidate_id,
                        "run_index": run_index,
                        "result": {
                            "status": "unavailable",
                            "reason": {
                                "code": "not_executed",
                                "detail": (
                                    "No authorized result has been supplied for this frozen slot."
                                ),
                            },
                        },
                    }
                )
    if not tasks:
        raise InvalidRequest("tasks must not be empty")
    tasks.sort(key=lambda item: item["task_id"])
    slots.sort(key=lambda item: item["slot_id"])
    return tasks, slots


def _budget(raw: object, *, slots: int, accelerator_count: int) -> dict[str, int]:
    field = "runtime_budget"
    item = _object(raw, field)
    required = (
        "max_wall_seconds_per_run",
        "max_total_gpu_seconds",
        "max_total_cost_microusd",
        "max_output_bytes_per_run",
        "scratch_bytes",
        "max_parallel_runs",
    )
    _keys(item, required=required, field=field)
    normalized = {key: _integer(item[key], field + "." + key, minimum=1) for key in required}
    if normalized["max_parallel_runs"] > slots:
        raise InvalidRequest("runtime_budget.max_parallel_runs exceeds the frozen run count")
    required_gpu_seconds = slots * normalized["max_wall_seconds_per_run"] * accelerator_count
    if normalized["max_total_gpu_seconds"] < required_gpu_seconds:
        raise UnavailableRequest(
            "runtime budget cannot cover every frozen run at its per-run wall-time ceiling"
        )
    normalized["planned_run_slots"] = slots
    normalized["planned_gpu_seconds_ceiling"] = required_gpu_seconds
    return normalized


def _environment(raw: object) -> tuple[dict[str, Any], int]:
    field = "execution_environment"
    item = _object(raw, field)
    _keys(item, required=("provider", "hardware", "runtime"), field=field)
    provider = _object(item["provider"], field + ".provider")
    _keys(
        provider,
        required=("name", "service", "region", "quote_reference", "quote_checked_at"),
        field=field + ".provider",
    )
    normalized_provider = {
        key: _text(provider[key], field + ".provider." + key)
        for key in ("name", "service", "region", "quote_reference", "quote_checked_at")
    }
    _time(normalized_provider["quote_checked_at"], field + ".provider.quote_checked_at")
    hardware = _object(item["hardware"], field + ".hardware")
    _keys(
        hardware,
        required=(
            "accelerator_vendor",
            "accelerator_model",
            "accelerator_count",
            "min_vram_bytes",
            "min_host_ram_bytes",
        ),
        field=field + ".hardware",
    )
    count = _integer(
        hardware["accelerator_count"], field + ".hardware.accelerator_count", minimum=1
    )
    normalized_hardware = {
        "accelerator_vendor": _text(
            hardware["accelerator_vendor"], field + ".hardware.accelerator_vendor"
        ),
        "accelerator_model": _text(
            hardware["accelerator_model"], field + ".hardware.accelerator_model"
        ),
        "accelerator_count": count,
        "min_vram_bytes": _integer(
            hardware["min_vram_bytes"], field + ".hardware.min_vram_bytes", minimum=1
        ),
        "min_host_ram_bytes": _integer(
            hardware["min_host_ram_bytes"],
            field + ".hardware.min_host_ram_bytes",
            minimum=1,
        ),
    }
    runtime = _object(item["runtime"], field + ".runtime")
    _keys(
        runtime,
        required=("execution_image", "driver", "framework", "entrypoint_revision"),
        field=field + ".runtime",
    )
    image = _text(runtime["execution_image"], field + ".runtime.execution_image")
    if not _IMAGE.fullmatch(image):
        raise UnavailableRequest(
            "execution_environment.runtime.execution_image must be digest-pinned"
        )
    normalized_runtime = {
        "execution_image": image,
        "driver": _text(runtime["driver"], field + ".runtime.driver"),
        "framework": _text(runtime["framework"], field + ".runtime.framework"),
        "entrypoint_revision": _revision(
            runtime["entrypoint_revision"], field + ".runtime.entrypoint_revision"
        ),
    }
    return {
        "provider": normalized_provider,
        "hardware": normalized_hardware,
        "runtime": normalized_runtime,
    }, count


def _output(raw: object) -> dict[str, Any]:
    field = "output"
    item = _object(raw, field)
    _keys(item, required=("root",), field=field)
    root = _relative(item["root"], field + ".root")
    parts = PurePosixPath(root).parts
    if any(parts[index : index + 2] == ("docs", "evaluation") for index in range(len(parts) - 1)):
        raise InvalidRequest("output cannot target immutable docs/evaluation")
    return {
        "root": root,
        "lineage_profile": RESULT_PROFILE,
        "publication_authorized": False,
    }


def _base(evaluation_id: str | None = None) -> dict[str, Any]:
    return {
        "profile": PREFLIGHT_PROFILE,
        "evaluation_id": evaluation_id,
        "status": "failed",
        "blockers": [],
        "allocation_authorized": False,
        "execution_authorized": False,
        "publication_authorized": False,
        "comparison": {
            "status": "unavailable",
            "claimable": False,
            "winner": None,
            "reason": "Frozen run slots do not yet contain complete authorized results.",
        },
        "authority_interpretation": (
            "This report binds caller-supplied receipt bytes and existing recheck interfaces; "
            "it does not establish input, allocation, execution or publication authority."
        ),
        "result_slots": [],
        "execution_gates": [
            "Recheck every input authority through its existing live boundary at execution time.",
            "Supply distinct, byte-verifiable allocation and execution authorization receipts.",
            "Verify the actual provider, accelerator, driver, runtime image and candidate "
            "revision.",
            "Enforce per-run wall time, aggregate GPU time, cost, scratch and output byte "
            "ceilings.",
            "Run candidates only through the task interface frozen in this plan.",
            "Retain failed and unavailable outcomes; do not drop them from the comparison set.",
        ],
    }


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    report.pop("document_sha256", None)
    report["document_sha256"] = _digest(canonical_json(report))
    return report


def inspect_request(
    request: Mapping[str, Any],
    *,
    source_root: Path,
    manifest_path: Path = MANIFEST_PATH,
) -> dict[str, Any]:
    """Build a deterministic, read-only preflight report from local request and artifact bytes."""
    evaluation_id = request.get("evaluation_id") if isinstance(request, Mapping) else None
    report = _base(evaluation_id if isinstance(evaluation_id, str) else None)
    try:
        if source_root.is_symlink():
            raise InvalidRequest("source_root must not be a symbolic link")
        root = source_root.resolve(strict=True)
        if not root.is_dir():
            raise InvalidRequest("source_root must be an existing directory")
        _keys(
            request,
            required=(
                "profile",
                "evaluation_id",
                "prepared_at",
                "candidates",
                "input_artifacts",
                "tasks",
                "runtime_budget",
                "execution_environment",
                "output",
            ),
            field="request",
        )
        if request["profile"] != REQUEST_PROFILE:
            raise InvalidRequest(f"request.profile must be {REQUEST_PROFILE}")
        evaluation_id = _identifier(request["evaluation_id"], "evaluation_id")
        prepared_text = _text(request["prepared_at"], "prepared_at")
        prepared_at = _time(prepared_text, "prepared_at")
        if manifest_path.is_symlink():
            raise InvalidRequest("model manifest must not be a symbolic link")
        manifest = manifest_path.resolve(strict=True)
        if not manifest.is_file():
            raise InvalidRequest("model manifest must be a regular file")
        hosted = load_manifest_from(manifest)
        manifest_document = json.loads(manifest.read_bytes())
        local = local_model_roles(manifest_document)
        artifacts, artifact_index = _input_artifacts(
            request["input_artifacts"], root=root, prepared_at=prepared_at
        )
        candidates, candidate_index = _candidates(
            request["candidates"], hosted_manifest=hosted, local_roles=local
        )
        tasks, slots = _tasks(
            request["tasks"], candidates=candidate_index, artifacts=artifact_index
        )
        environment, accelerator_count = _environment(request["execution_environment"])
        budget = _budget(
            request["runtime_budget"], slots=len(slots), accelerator_count=accelerator_count
        )
        report.update(
            evaluation_id=evaluation_id,
            status="ready",
            request_sha256=_digest(canonical_json(request)),
            prepared_at=prepared_text,
            model_manifest={
                "path": manifest.name,
                "sha256": _digest_file(manifest),
                "pipeline_version": hosted.pipeline_version,
            },
            candidates=candidates,
            input_artifacts=artifacts,
            tasks=tasks,
            runtime_budget=budget,
            execution_environment=environment,
            execution_environment_sha256=_digest(canonical_json(environment)),
            output=_output(request["output"]),
            result_slots=slots,
        )
    except UnavailableRequest as exc:
        report["status"] = "unavailable"
        report["blockers"].append(
            {"state": "unavailable", "code": "precondition_unavailable", "detail": str(exc)}
        )
    except (InvalidRequest, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        report["status"] = "failed"
        report["blockers"].append(
            {"state": "failed", "code": "invalid_or_changed_input", "detail": str(exc)}
        )
    return _finish(report)


def read_preflight(value: Mapping[str, Any]) -> dict[str, Any]:
    """Verify a preflight's self-digest before any result is interpreted against it."""
    if not isinstance(value, Mapping):
        raise InvalidRequest("preflight must be an object")
    result = dict(value)
    supplied = _sha(result.pop("document_sha256", None), "document_sha256")
    if result.get("profile") != PREFLIGHT_PROFILE or _digest(canonical_json(result)) != supplied:
        raise InvalidRequest("preflight profile or document digest does not verify")
    if any(
        result.get(key) is not False
        for key in ("allocation_authorized", "execution_authorized", "publication_authorized")
    ):
        raise InvalidRequest(
            "preflight cannot grant allocation, execution or publication authority"
        )
    comparison = _object(result.get("comparison"), "comparison")
    if comparison.get("claimable") is not False or comparison.get("winner") is not None:
        raise InvalidRequest("preflight cannot make a comparison claim or choose a winner")
    if result.get("status") == "ready":
        for field in ("candidates", "input_artifacts", "tasks", "result_slots"):
            if not isinstance(result.get(field), list) or not result[field]:
                raise InvalidRequest(f"ready preflight requires non-empty {field}")
        for slot in result["result_slots"]:
            if (
                not isinstance(slot, Mapping)
                or not isinstance(slot.get("result"), Mapping)
                or slot["result"].get("status") != "unavailable"
            ):
                raise InvalidRequest("every preflight run slot must start unavailable")
    result["document_sha256"] = supplied
    return result


def _sample(values: Sequence[int]) -> dict[str, int]:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        numerator, denominator = ordered[middle], 1
    else:
        numerator, denominator = ordered[middle - 1] + ordered[middle], 2
    return {
        "observations": len(ordered),
        "median_numerator": numerator,
        "median_denominator": denominator,
        "range_min": ordered[0],
        "range_max": ordered[-1],
    }


def _accepted(sample: Mapping[str, int], rule: Mapping[str, Any] | None) -> bool | None:
    if rule is None:
        return None
    measured = sample["median_numerator"]
    threshold = rule["value"] * sample["median_denominator"]
    return measured >= threshold if rule["operator"] == "gte" else measured <= threshold


def _result_receipt(root: Path, raw: object, field: str) -> dict[str, str]:
    item = _object(raw, field)
    _keys(item, required=("path", "sha256"), field=field)
    relative = _relative(item["path"], field + ".path")
    path = _local_file(root, relative, field + ".path")
    expected = _sha(item["sha256"], field + ".sha256")
    if _digest_file(path) != expected:
        raise InvalidRequest(f"{field} receipt bytes changed")
    return {"path": relative, "sha256": expected}


def _successful_result(
    record: Mapping[str, Any],
    *,
    slot: Mapping[str, Any],
    task: Mapping[str, Any],
    candidate: Mapping[str, Any],
    plan: Mapping[str, Any],
    root: Path,
) -> dict[str, Any]:
    required = (
        "profile",
        "plan_sha256",
        "slot_id",
        "candidate_id",
        "candidate_revision",
        "task_id",
        "run_index",
        "status",
        "input_artifacts",
        "execution_environment_sha256",
        "authorization",
        "runtime",
        "outputs",
        "measurement_receipt",
        "metrics",
        "rubric",
        "failure",
    )
    _keys(record, required=required, field=f"result {slot['slot_id']}")
    if record["profile"] != RESULT_PROFILE or record["status"] != "succeeded":
        raise InvalidRequest("successful result profile or status changed")
    expected = {
        "plan_sha256": plan["document_sha256"],
        "slot_id": slot["slot_id"],
        "candidate_id": candidate["candidate_id"],
        "candidate_revision": candidate["revision"],
        "task_id": task["task_id"],
        "run_index": slot["run_index"],
        "execution_environment_sha256": plan["execution_environment_sha256"],
    }
    if any(record[key] != value for key, value in expected.items()):
        raise InvalidRequest("successful result differs from its frozen slot binding")
    if record["failure"] is not None:
        raise InvalidRequest("successful result cannot carry a failure")
    frozen_inputs = [
        {
            "artifact_id": item["artifact_id"],
            "sha256": item["sha256"],
            "authority_receipt_sha256": item["authority"]["receipt_sha256"],
        }
        for item in plan["input_artifacts"]
        if item["artifact_id"] in task["input_artifact_ids"]
    ]
    if record["input_artifacts"] != frozen_inputs:
        raise InvalidRequest("successful result input lineage differs from the frozen task")
    authorization = _object(record["authorization"], "result.authorization")
    _keys(
        authorization,
        required=("input_rechecks", "allocation_receipt", "execution_receipt"),
        field="result.authorization",
    )
    input_rechecks = []
    expected_rechecks = {
        item["artifact_id"]: item["authority"]
        for item in plan["input_artifacts"]
        if item["artifact_id"] in task["input_artifact_ids"]
    }
    for index, raw_recheck in enumerate(
        _array(authorization["input_rechecks"], "result.authorization.input_rechecks")
    ):
        field = f"result.authorization.input_rechecks[{index}]"
        recheck = _object(raw_recheck, field)
        _keys(
            recheck,
            required=("artifact_id", "boundary", "checked_at", "receipt"),
            field=field,
        )
        artifact_id = _identifier(recheck["artifact_id"], field + ".artifact_id")
        if artifact_id not in expected_rechecks:
            raise InvalidRequest(f"{field} names an input outside the frozen task")
        boundary = recheck["boundary"]
        if boundary != expected_rechecks[artifact_id]["recheck"]:
            raise InvalidRequest(f"{field} did not use the frozen authority boundary")
        checked_at = _text(recheck["checked_at"], field + ".checked_at")
        if _time(checked_at, field + ".checked_at") < _time(plan["prepared_at"], "prepared_at"):
            raise InvalidRequest(f"{field} predates the frozen preflight")
        input_rechecks.append(
            {
                "artifact_id": artifact_id,
                "boundary": boundary,
                "recheck_interface": AUTHORITY_RECHECKS[boundary],
                "checked_at": checked_at,
                "receipt": _result_receipt(root, recheck["receipt"], field + ".receipt"),
            }
        )
    if len(input_rechecks) != len(expected_rechecks) or {
        item["artifact_id"] for item in input_rechecks
    } != set(expected_rechecks):
        raise InvalidRequest("successful result must recheck every frozen input exactly once")
    input_rechecks.sort(key=lambda item: item["artifact_id"])
    normalized_authorization = {
        "input_rechecks": input_rechecks,
        "allocation_receipt": _result_receipt(
            root, authorization["allocation_receipt"], "result.authorization.allocation_receipt"
        ),
        "execution_receipt": _result_receipt(
            root, authorization["execution_receipt"], "result.authorization.execution_receipt"
        ),
    }
    if (
        normalized_authorization["allocation_receipt"]["sha256"]
        == normalized_authorization["execution_receipt"]["sha256"]
    ):
        raise InvalidRequest("allocation and execution authorization receipts must be distinct")
    runtime = _object(record["runtime"], "result.runtime")
    _keys(
        runtime,
        required=("wall_seconds", "gpu_seconds", "cost_microusd"),
        field="result.runtime",
    )
    normalized_runtime = {key: _integer(runtime[key], "result.runtime." + key) for key in runtime}
    budget = plan["runtime_budget"]
    count = plan["execution_environment"]["hardware"]["accelerator_count"]
    if normalized_runtime["wall_seconds"] > budget["max_wall_seconds_per_run"]:
        raise InvalidRequest("successful result exceeded its wall-time budget")
    if normalized_runtime["gpu_seconds"] > normalized_runtime["wall_seconds"] * count:
        raise InvalidRequest("successful result reports impossible GPU time")
    if normalized_runtime["cost_microusd"] > budget["max_total_cost_microusd"]:
        raise InvalidRequest("successful result exceeded the total cost ceiling")
    outputs = []
    seen_kinds: set[str] = set()
    total_bytes = 0
    for index, output_raw in enumerate(_array(record["outputs"], "result.outputs")):
        field = f"result.outputs[{index}]"
        output = _object(output_raw, field)
        _keys(output, required=("kind", "path", "sha256", "bytes"), field=field)
        kind = _identifier(output["kind"], field + ".kind")
        relative = _relative(output["path"], field + ".path")
        path = _local_file(root, relative, field + ".path")
        sha = _sha(output["sha256"], field + ".sha256")
        byte_count = _integer(output["bytes"], field + ".bytes", minimum=1)
        if path.stat().st_size != byte_count or _digest_file(path) != sha:
            raise InvalidRequest(f"{field} bytes changed")
        seen_kinds.add(kind)
        total_bytes += byte_count
        outputs.append({"kind": kind, "path": relative, "sha256": sha, "bytes": byte_count})
    if seen_kinds != set(task["output_kinds"]) or len(outputs) != len(seen_kinds):
        raise InvalidRequest("successful result outputs differ from the frozen output kinds")
    if total_bytes > budget["max_output_bytes_per_run"]:
        raise InvalidRequest("successful result exceeded its output byte budget")
    measurement_receipt = _result_receipt(
        root, record["measurement_receipt"], "result.measurement_receipt"
    )
    metrics = _object(record["metrics"], "result.metrics")
    metric_keys = {item["key"] for item in task["metrics"]}
    if set(metrics) != metric_keys:
        raise InvalidRequest("successful result metrics differ from the frozen rubric")
    normalized_metrics = {
        key: _integer(value, "result.metrics." + key) for key, value in metrics.items()
    }
    rubric = _object(record["rubric"], "result.rubric")
    _keys(
        rubric,
        required=("reviewer", "reviewed_at", "scores", "notes"),
        field="result.rubric",
    )
    reviewer = _text(rubric["reviewer"], "result.rubric.reviewer")
    reviewed_at = _text(rubric["reviewed_at"], "result.rubric.reviewed_at")
    _time(reviewed_at, "result.rubric.reviewed_at")
    notes = _result_receipt(root, rubric["notes"], "result.rubric.notes")
    scores = _object(rubric["scores"], "result.rubric.scores")
    dimensions = {item["key"] for item in task["rubric"]["dimensions"]}
    if set(scores) != dimensions:
        raise InvalidRequest("successful result rubric dimensions differ from the frozen rubric")
    normalized_scores = {
        key: _integer(value, "result.rubric.scores." + key) for key, value in scores.items()
    }
    low, high = task["rubric"]["scale_min"], task["rubric"]["scale_max"]
    if any(not low <= score <= high for score in normalized_scores.values()):
        raise InvalidRequest("successful result rubric score is outside the frozen scale")
    return {
        **expected,
        "profile": RESULT_PROFILE,
        "status": "succeeded",
        "input_artifacts": frozen_inputs,
        "authorization": normalized_authorization,
        "runtime": normalized_runtime,
        "outputs": outputs,
        "measurement_receipt": measurement_receipt,
        "metrics": normalized_metrics,
        "rubric": {
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "scores": normalized_scores,
            "notes": notes,
        },
        "failure": None,
    }


def _non_success_result(
    record: Mapping[str, Any], *, slot: Mapping[str, Any], plan: Mapping[str, Any]
) -> dict[str, Any]:
    required = ("profile", "plan_sha256", "slot_id", "status", "failure")
    _keys(record, required=required, field=f"result {slot['slot_id']}")
    status = record["status"]
    if (
        record["profile"] != RESULT_PROFILE
        or record["plan_sha256"] != plan["document_sha256"]
        or record["slot_id"] != slot["slot_id"]
        or status not in _RESULT_STATES - {"succeeded"}
    ):
        raise InvalidRequest("non-success result differs from its frozen slot binding")
    failure = _object(record["failure"], "result.failure")
    _keys(failure, required=("stage", "code", "detail"), field="result.failure")
    return {
        "profile": RESULT_PROFILE,
        "plan_sha256": plan["document_sha256"],
        "slot_id": slot["slot_id"],
        "status": status,
        "failure": {
            "stage": _identifier(failure["stage"], "result.failure.stage"),
            "code": _identifier(failure["code"], "result.failure.code"),
            "detail": _text(failure["detail"], "result.failure.detail"),
        },
    }


def inspect_results(
    preflight: Mapping[str, Any],
    results: Sequence[Mapping[str, Any]],
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    """Verify result lineage and say whether a symmetric comparison may be reported.

    The function deliberately does not rank candidates.  A complete result set makes the
    frozen measurements claimable; choosing a winner remains a separate reviewed decision.
    """
    plan = read_preflight(preflight)
    report = {
        "profile": "exulanica.model-evaluation-comparison-readiness/v1",
        "plan_sha256": plan["document_sha256"],
        "status": "unavailable",
        "claimable": False,
        "winner": None,
        "results": [],
        "blockers": [],
    }
    if plan.get("status") != "ready":
        report["blockers"].append(
            {"code": "preflight_not_ready", "detail": "The frozen preflight is not ready."}
        )
        return _finish(report)
    root = artifact_root.resolve(strict=True)
    if not root.is_dir():
        raise InvalidRequest("artifact_root must be an existing directory")
    slots = {item["slot_id"]: item for item in plan["result_slots"]}
    tasks = {item["task_id"]: item for item in plan["tasks"]}
    candidates = {item["candidate_id"]: item for item in plan["candidates"]}
    supplied: dict[str, Mapping[str, Any]] = {}
    for result in results:
        if not isinstance(result, Mapping):
            raise InvalidRequest("every result must be an object")
        slot_id = result.get("slot_id")
        if not isinstance(slot_id, str) or slot_id not in slots or slot_id in supplied:
            raise InvalidRequest("results must name each frozen slot at most once")
        supplied[slot_id] = result
    total_gpu_seconds = 0
    total_cost = 0
    for slot_id, slot in sorted(slots.items()):
        raw = supplied.get(slot_id)
        if raw is None:
            report["results"].append({**slot, "source": "frozen_unavailable_default"})
            report["blockers"].append(
                {"code": "result_unavailable", "slot_id": slot_id, "detail": "not_executed"}
            )
            continue
        if raw.get("status") == "succeeded":
            task = tasks[slot["task_id"]]
            candidate = candidates[slot["candidate_id"]]
            normalized = _successful_result(
                raw, slot=slot, task=task, candidate=candidate, plan=plan, root=root
            )
            total_gpu_seconds += normalized["runtime"]["gpu_seconds"]
            total_cost += normalized["runtime"]["cost_microusd"]
        else:
            normalized = _non_success_result(raw, slot=slot, plan=plan)
            report["blockers"].append(
                {
                    "code": "result_" + normalized["status"],
                    "slot_id": slot_id,
                    "detail": normalized["failure"]["code"],
                }
            )
        report["results"].append(normalized)
    budget = plan["runtime_budget"]
    if total_gpu_seconds > budget["max_total_gpu_seconds"]:
        report["blockers"].append(
            {"code": "aggregate_gpu_budget_exceeded", "detail": str(total_gpu_seconds)}
        )
    if total_cost > budget["max_total_cost_microusd"]:
        report["blockers"].append(
            {"code": "aggregate_cost_budget_exceeded", "detail": str(total_cost)}
        )
    report["observed_totals"] = {
        "gpu_seconds": total_gpu_seconds,
        "cost_microusd": total_cost,
    }
    if not report["blockers"]:
        report["status"] = "complete"
        report["claimable"] = True
        completed = {item["slot_id"]: item for item in report["results"]}
        comparisons = []
        for task in plan["tasks"]:
            candidate_summaries = []
            for candidate_id in task["candidate_ids"]:
                runs = [
                    completed[slot["slot_id"]]
                    for slot in plan["result_slots"]
                    if slot["task_id"] == task["task_id"] and slot["candidate_id"] == candidate_id
                ]
                metric_summaries = []
                for metric in task["metrics"]:
                    sample = _sample([run["metrics"][metric["key"]] for run in runs])
                    metric_summaries.append(
                        {
                            **metric,
                            "sample": sample,
                            "accepted": _accepted(sample, metric["acceptance"]),
                        }
                    )
                rubric_summaries = []
                for dimension in task["rubric"]["dimensions"]:
                    sample = _sample([run["rubric"]["scores"][dimension["key"]] for run in runs])
                    rubric_summaries.append(
                        {
                            "key": dimension["key"],
                            "sample": sample,
                            "accepted": _accepted(
                                sample,
                                {"operator": "gte", "value": task["rubric"]["minimum"]},
                            ),
                        }
                    )
                decided_metrics = [
                    metric["accepted"]
                    for metric in metric_summaries
                    if metric["accepted"] is not None
                ]
                candidate_summaries.append(
                    {
                        "candidate_id": candidate_id,
                        "revision": candidates[candidate_id]["revision"],
                        "runs": len(runs),
                        "metrics": metric_summaries,
                        "rubric": rubric_summaries,
                        "accepted": all(decided_metrics)
                        and all(dimension["accepted"] for dimension in rubric_summaries),
                    }
                )
            comparisons.append(
                {
                    "task_id": task["task_id"],
                    "reporting": "exact_median_and_range_by_candidate",
                    "candidates": candidate_summaries,
                }
            )
        report["comparison"] = {
            "tasks": comparisons,
            "winner": None,
            "selection": "requires a separate reviewed decision; preflight assigns no weights",
            "claimable_scope": (
                "Frozen measurements and named failures only; not input rights, production "
                "selection, promotion or general model quality."
            ),
        }
    return _finish(report)
