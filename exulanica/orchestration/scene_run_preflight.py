"""Read-only scene run planning. A plan is neither a lease nor permission to spend.

The live boundary checks the existing scene delivery policy twice. Local validation reuses
runner formats and checks exact bytes; it never prepares datasets, loads images, claims a job,
starts Docker, or repairs caches. Saved reports must be revalidated at execution time.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import uuid
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg

from exulanica.environment.scene_extraction import MAX_RECEIPT_BYTES, _verified
from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evaluation.reference_inputs import read_manifest as read_source_manifest
from exulanica.graph.asset_read_policy import (
    evaluation_time,
    final_check,
    scene_allowed,
    scene_inputs,
)
from exulanica.ingest.scene_splat import evaluation_bundle
from exulanica.reconstruction.gsplat_protocol import (
    CHECKPOINT_PROFILE,
    GSPLAT_REVISION,
    RUNNER_PROFILE,
    TRAINING_PROTOCOL,
)
from exulanica.reconstruction.gsplat_runner import dataset_digest, load_checkpoint, read_manifest
from exulanica.reconstruction.source_lineage import decoded_training_sources
from exulanica.reconstruction.splat import (
    _canonical,
    _digest_file,
    _quality,
    _verify_dataset_sources,
    _verify_pose_receipt,
    verify_masked_training_sources,
)
from exulanica.store.base import ContentAddressedStore

PROFILE = "exulanica.scene-run-preflight/v1"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(path: Path) -> dict[str, Any]:
    if path.stat().st_size > MAX_RECEIPT_BYTES:
        raise ValueError("receipt exceeds the read budget")
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("receipt must be an object")
    return value


def _no_links(path: Path) -> None:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("run paths must not traverse symbolic links")
    if path.is_dir() and any(p.is_symlink() for p in path.rglob("*")):
        raise ValueError("run artifacts must not contain symbolic links")


@dataclass(frozen=True)
class RunResources:
    """Explicit operator allowances and quote inputs, never measured requirements or prices."""

    provider: str
    quote_reference: str
    quote_checked_at: str
    gpu_hour_microusd: int
    storage_hour_microusd: int
    fixed_cost_microusd: int
    max_runtime_seconds: int
    min_vram_bytes: int
    host_ram_bytes: int
    scratch_budget_bytes: int

    def __post_init__(self) -> None:
        from datetime import datetime

        if any(
            not isinstance(v, str) or not v.strip()
            for v in (self.provider, self.quote_reference, self.quote_checked_at)
        ):
            raise ValueError("provider and dated quote reference are required")
        if datetime.fromisoformat(self.quote_checked_at.replace("Z", "+00:00")).utcoffset() is None:
            raise ValueError("quote time needs a UTC offset")
        for key, value in asdict(self).items():
            if key in {"provider", "quote_reference", "quote_checked_at"}:
                continue
            minimum = 0 if key.endswith("microusd") else 1
            if type(value) is not int or value < minimum:
                raise ValueError(f"{key} must be an explicit integer allowance")


def _report(scene_ref: str) -> dict[str, Any]:
    return {
        "profile": PROFILE,
        "producer": "scene-run-preflight/1",
        "scene_ref": scene_ref,
        "status": "blocked",
        "blockers": [],
        "reuse": [],
        "run": None,
        "execution_authorized": False,
        "allocation_authorized": False,
        "acceptance": {
            "heldout": "Exact source split frozen before reconstruction; no held-out RGB training.",
            "conditioning": TRAINING_PROTOCOL["geometry_conditioning"],
            "visual": [
                "Review every held-out reference/render pair and source-camera view.",
                "Inspect an orbit and unobserved directions for holes, smears and floaters.",
                "Verify authenticated delivery, withdrawal and browser display separately.",
            ],
            "accepted": False,
            "limits": "No inferred physical scale, complete surfaces, collision or navigability.",
        },
        "execution_gates": [
            "Re-run current source/rights/mask and exact stage checks in the "
            "existing scene worker.",
            "Queue an explicitly authorized exact-set job and claim its existing durable lease.",
            "Verify the pinned image, actual NVIDIA GPU/driver/runtime and available disk on host.",
            "Confirm current provider availability, quote and spending authorization.",
            "Enforce the declared wall-time budget outside the runner; iterations "
            "are not a timeout.",
        ],
        "recovery": [
            "Use the existing worker heartbeat and exact --job/--workspace scope.",
            "Resume only the complete source/manifest-bound optimizer checkpoint.",
            "On preemption preserve private scratch and checkpoint; do not publish either.",
            "On cleanup uncertainty retain scratch and reconcile owned containers before retry.",
            "After verified cleanup retain authorized receipts, then delete "
            "compute and private scratch.",
        ],
    }


def _block(report: dict[str, Any], stage: str, code: str, detail: str) -> dict[str, Any]:
    report["blockers"].append({"stage": stage, "code": code, "detail": detail})
    report["status"] = "blocked"
    return report


def _finish(report: dict[str, Any]) -> dict[str, Any]:
    report.pop("document_sha256", None)
    report["document_sha256"] = _sha(_canonical(report))
    return report


def _checkpoint(
    output: Path, identity: dict[str, str], max_iterations: int
) -> dict[str, Any] | None:
    directory = output / "checkpoints"
    pointer = directory / "latest.json"
    if not pointer.exists():
        if directory.exists() and any(directory.glob("*.pt")):
            raise ValueError("checkpoint exists without a committed pointer")
        return None
    value = _json(pointer)
    name = value.get("file")
    step = value.get("next_iteration")
    if (
        value.get("profile") != CHECKPOINT_PROFILE
        or value.get("identity") != identity
        or not isinstance(name, str)
        or Path(name).name != name
        or not name.endswith(".pt")
        or type(step) is not int
        or not 0 <= step <= max_iterations
    ):
        raise ValueError("checkpoint pointer has stale identity or invalid iteration")
    if _digest_file(directory / name) != value.get("sha256"):
        raise ValueError("checkpoint bytes do not match the committed pointer")
    # Existing weights-only CPU deserialization validates all optimizer/RNG/sampler state.
    # Missing optional Torch is a blocker, never a claim that pointer checks prove resumability.
    state = load_checkpoint(directory, identity=identity)
    if state is None or state["next_iteration"] != step:
        raise ValueError("checkpoint changed during validation")
    return {"kind": "checkpoint", "sha256": value["sha256"], "next_iteration": step}


def inspect_local_run(
    *,
    scene_ref: str,
    current_pose_sha256: str,
    current_pose_manifest_digest: str,
    current_sources: list[str],
    manifest_path: Path,
    dataset: Path,
    pose_receipt: Path,
    output: Path,
    source_manifest: Path | None = None,
    resources: RunResources | None = None,
) -> dict[str, Any]:
    """Pure local inspection over supplied bindings, without a claim of live authorization."""
    result = _report(scene_ref)
    stage = "input"
    try:
        for path in (manifest_path, dataset, pose_receipt, output):
            _no_links(path)
        manifest_path, dataset, pose_receipt, output = (
            p.absolute() for p in (manifest_path, dataset, pose_receipt, output)
        )
        if any(
            p.name == "evaluation" and p.parent.name == "docs" for p in (output, *output.parents)
        ):
            raise ValueError("run output cannot name immutable evaluation paths")
        if output == dataset or output.is_relative_to(dataset) or dataset.is_relative_to(output):
            raise ValueError("dataset and output must be separate non-nested directories")
        stage = "training"
        _json(manifest_path)
        manifest = read_manifest(manifest_path)
        if manifest.scene_ref != scene_ref:
            raise ValueError("training manifest belongs to another scene")
        result["bindings"] = {
            "manifest_digest": manifest.digest,
            "manifest_file_sha256": _digest_file(manifest_path),
            "pose_receipt_sha256": current_pose_sha256,
            "pose_manifest_digest": current_pose_manifest_digest,
            "source_sha256": sorted(current_sources),
            "heldout_source_sha256": list(manifest.heldout_source_sha256),
            "seed": TRAINING_PROTOCOL["seed"],
        }
        stage = "input"
        if sorted(manifest.source_sha256) != sorted(current_sources):
            raise ValueError("training sources differ from the current authorized pose inputs")
        _verify_dataset_sources(manifest, dataset)
        stage = "pose"
        if (
            _digest_file(pose_receipt) != current_pose_sha256
            or manifest.pose_manifest_digest != current_pose_manifest_digest
        ):
            raise ValueError("local pose receipt differs from the current scene")
        _verify_pose_receipt(manifest, pose_receipt, dataset)
        stage = "input_coverage"
        if source_manifest is None:
            raise ValueError("supply the frozen reference-input manifest with its held-out split")
        _no_links(source_manifest)
        _json(source_manifest)
        frozen = read_source_manifest(source_manifest)
        remap = {masked: original for _, original, masked in manifest.masked_source_remap}
        remap.update(
            {
                selected: original
                for original, selected, _ in decoded_training_sources(
                    manifest.decoded_source_lineage, manifest.masked_source_remap
                ).values()
            }
        )
        if {r["sha256"] for r in frozen["record"]["files"]} != {
            remap.get(sha, sha) for sha in manifest.source_sha256
        } or set(frozen["record"]["evaluation_split"]["heldout_sha256"]) != set(
            manifest.heldout_original_source_sha256
        ):
            raise ValueError("training source set or held-out split differs from frozen inputs")
        result["bindings"]["frozen_source_manifest_sha256"] = frozen["record_sha256"]
        pose = _json(pose_receipt)
        registered = pose["quality"].get("registered_images")
        heldout_names = {
            f["filename"]
            for f in pose["manifest"]["frames"]
            if f["sha256"] in manifest.heldout_source_sha256
        }
        if not isinstance(registered, list) or not heldout_names <= set(registered):
            raise ValueError("every declared held-out view needs a registered source pose")
        identity = {"manifest_digest": manifest.digest, "dataset_digest": dataset_digest(dataset)}
        result["bindings"].update(identity)
        result["reuse"].append({"kind": "accepted_pose_and_exact_dataset", **identity})
        stage = "mask"
        verify_masked_training_sources(manifest, dataset)
        stage = "checkpoint"
        if (output / "container-cleanup-required.json").exists():
            raise ValueError("owned container cleanup is unresolved; preserve private scratch")
        stage = "training"
        completed = all(
            (output / name).exists() for name in ("metrics.json", "runtime.json", "accepted.ply")
        )
        if completed:
            # Do not infer a reusable trained output merely from filenames or receipt presence.
            quality = _quality(manifest, output, delivery=None)
            for name in ("runtime.json", "metrics.json"):
                if _json(output / name).get("dataset_digest") != identity["dataset_digest"]:
                    raise ValueError("trained output lacks the exact current dataset binding")
            prepared = _json(output / "training" / "dataset.json")
            if (
                prepared.get("profile") != "exulanica.gsplat-prepared-dataset/v1"
                or prepared.get("source_dataset_digest") != identity["dataset_digest"]
                or prepared.get("protocol") != TRAINING_PROTOCOL["undistortion"]
                or type(prepared.get("rectified")) is not bool
            ):
                raise ValueError("prepared training data has a stale source or protocol binding")
            # Finished outputs need their bound evaluation companion, not every temporary
            # rectified training image. The bundle validator below checks retained references.
            evaluation_bundle(output)  # verifies split/reference/render companion bytes
            split = _json(output / "split.json")
            if (
                split.get("predeclared_heldout_source_sha256")
                != list(manifest.heldout_source_sha256)
                or split.get("manifest_digest") != manifest.digest
                or split.get("dataset_digest") != identity["dataset_digest"]
                or split.get("unregistered_heldout_source_sha256") != []
                or set(split.get("heldout", [])) != heldout_names
                or set(split.get("training", [])) != set(registered) - heldout_names
            ):
                raise ValueError("cached held-out split changed or includes unregistered views")
            views = _json(output / "metrics.json")["per_view"]
            if len(views) != len(manifest.heldout_source_sha256) or {
                v["source_sha256"] for v in views
            } != set(manifest.heldout_source_sha256):
                raise ValueError("metrics do not evaluate every declared held-out source")
            if quality.reasons:
                return _finish(
                    _block(result, stage, "quality_rejected", "; ".join(quality.reasons))
                )
            result["reuse"].append(
                {"kind": "trained_ply", "sha256": _digest_file(output / "accepted.ply")}
            )
            stage = "conversion"
            delivery = output / "scene.sog"
            receipt_path = output.parent / "receipt.json"
            if not delivery.is_file() or not receipt_path.is_file():
                return _finish(
                    _block(
                        result,
                        stage,
                        "delivery_incomplete",
                        "Reuse accepted training; finish pinned SOG conversion and "
                        "receipt before display.",
                    )
                )
            quality = _quality(manifest, output, delivery=delivery)
            receipt = _json(receipt_path)
            if (
                not quality.accepted
                or receipt.get("manifest_digest") != manifest.digest
                or receipt.get("quality_digest") != _sha(_canonical(quality.as_payload()))
            ):
                raise ValueError("delivery or quality receipt is stale or rejected")
            result["reuse"].append({"kind": "sog_delivery", "sha256": _digest_file(delivery)})
            return _finish(
                _block(
                    result,
                    "display",
                    "visual_acceptance_required",
                    "Training and conversion are reusable; visual and "
                    "authenticated browser acceptance remain separate.",
                )
            )
        stage = "checkpoint"
        resume = _checkpoint(output, identity, manifest.max_iterations)
        if resume:
            result["reuse"].append(resume)
        elif any(
            (output / name).exists() for name in ("metrics.json", "runtime.json", "accepted.ply")
        ):
            return _finish(
                _block(
                    result,
                    "training",
                    "incomplete_training",
                    "Partial training outputs have no validated resumable checkpoint.",
                )
            )
        stage = "tool"
        if manifest.gsplat_revision != GSPLAT_REVISION:
            raise ValueError("this runner cannot execute the requested gsplat revision")
        stage = "resources"
        if resources is None:
            raise ValueError(
                "supply dated GPU/storage/fixed cost inputs, hardware "
                "and wall-time/storage allowances"
            )
        if Decimal(str(manifest.usd_per_gpu_hour)) * 1_000_000 != resources.gpu_hour_microusd:
            raise ValueError(
                "GPU quote differs from the manifest cost binding; create a reviewed new manifest"
            )
        source_bytes = sum(p.stat().st_size for p in dataset.rglob("*") if p.is_file())
        retained_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        if resources.scratch_budget_bytes <= source_bytes + retained_bytes:
            raise ValueError("scratch allowance leaves no room beyond retained inputs/outputs")
        result["run"] = {
            "kind": "reviewable_specification_only",
            "manifest": manifest.as_payload(),
            "resources": asdict(resources),
            "resource_basis": "Caller-supplied allowances, not measured capacity "
            "or provider availability.",
            "input_bytes": source_bytes,
            "retained_output_bytes": retained_bytes,
            "cost_ceiling_microusd": resources.fixed_cost_microusd
            + (
                (resources.gpu_hour_microusd + resources.storage_hour_microusd)
                * resources.max_runtime_seconds
                + 3599
            )
            // 3600,
            "cost_limit": "Arithmetic under supplied rates/time only; include "
            "egress, taxes and minimum billing in fixed cost. Not a bill or enforced cap.",
            "gpu_count": 1,
            "requested_gpu": manifest.requested_gpu,
            "runtime": "Linux host with Docker daemon and NVIDIA Container "
            "Toolkit; pinned image must support the actual GPU/driver.",
            "managed_trainer_argv": [
                "python",
                "-m",
                "exulanica.reconstruction.gsplat_container",
                "train",
                "--profile",
                RUNNER_PROFILE,
                "--manifest",
                str(manifest_path),
                "--pose-receipt",
                str(pose_receipt),
                "--dataset",
                str(dataset),
                "--output",
                str(output),
                "--resume",
                "auto",
            ],
            "command_scope": "Trainer command inside an authorized scene-worker "
            "lease only; it does not acquire authority or enforce wall time.",
        }
        result["status"] = "plan_ready"
    except (
        ValueError,
        TypeError,
        KeyError,
        AttributeError,
        IndexError,
        OSError,
        ImportError,
        RuntimeError,
        EOFError,
        pickle.UnpicklingError,
    ) as exc:
        _block(result, stage, "invalid_or_missing_input", str(exc))
    return _finish(result)


def prepare_current_scene_run(
    connection: psycopg.Connection,
    store: ContentAddressedStore,
    *,
    workspace: uuid.UUID,
    scene: uuid.UUID,
    manifest_path: Path | None = None,
    dataset: Path | None = None,
    pose_receipt: Path | None = None,
    output: Path | None = None,
    source_manifest: Path | None = None,
    resources: RunResources | None = None,
) -> dict[str, Any]:
    """Inspect an existing published scene using an idle, workspace-scoped connection.

    No absent scene or failed intake is upgraded to authorized input. The worker remains the
    authority for new exact-set admission, current stage bindings, lease and execution.
    """
    result = _report(str(scene))
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read read only")
        buffered = scene_inputs(connection, workspace, scene, store)
        if not scene_allowed(connection, workspace, scene, buffered, evaluation_time(connection)):
            return _finish(
                _block(
                    result,
                    "rights",
                    "scene_unavailable",
                    "Current authorized scene inputs are unavailable; do not use "
                    "historical receipts as permission.",
                )
            )
        row, pose_manifest = buffered
        pose_sha = bytes(row["content_sha256"]).hex()
        try:
            pose_data = _verified(store, pose_sha, MAX_RECEIPT_BYTES)
            pose = json.loads(pose_data)
            quality = pose["quality"]
            if not isinstance(quality, dict):
                raise ValueError("pose quality must be an object")
        except (ValueError, KeyError, TypeError, OSError, BlobNotFoundError, IntegrityError):
            return _finish(
                _block(
                    result,
                    "pose",
                    "pose_receipt_unavailable",
                    "Current pose receipt is absent, corrupt or malformed.",
                )
            )
        if pose.get("quality_digest") != _sha(_canonical(quality)):
            return _finish(
                _block(
                    result,
                    "pose",
                    "invalid_quality_digest",
                    "Current pose quality bytes disagree with their binding.",
                )
            )
        frames = pose_manifest["frames"]
        result["bindings"] = {
            "workspace_ref": str(workspace),
            "scene_ref": str(scene),
            "current_job_ref": str(row["job_id"]),
            "pose_receipt_sha256": pose_sha,
            "pose_manifest_digest": pose["manifest_digest"],
            "source_sha256": sorted(f["sha256"] for f in frames),
        }
        if len(frames) < 3:
            _block(
                result,
                "input_coverage",
                "below_pose_backend_floor",
                "Current backend needs at least three views; count alone never "
                "establishes coverage.",
            )
        if quality.get("accepted") is not True:
            _block(
                result,
                "pose",
                "pose_not_accepted",
                "Current pose quality is not accepted. Inspect registration and "
                "overlap/parallax before requesting training.",
            )
            result["pose_quality"] = {
                k: quality[k]
                for k in ("registered_images", "registered_fraction", "reasons")
                if k in quality
            }
        if not result["blockers"]:
            if any(p is None for p in (manifest_path, dataset, pose_receipt, output)):
                _block(
                    result,
                    "training",
                    "run_inputs_missing",
                    "Supply exact build manifest, retained COLMAP dataset, current "
                    "pose receipt and private run output path.",
                )
            else:
                bindings = result["bindings"]
                result = inspect_local_run(
                    scene_ref=str(scene),
                    current_pose_sha256=pose_sha,
                    current_pose_manifest_digest=pose["manifest_digest"],
                    current_sources=bindings["source_sha256"],
                    manifest_path=manifest_path,
                    dataset=dataset,
                    pose_receipt=pose_receipt,
                    output=output,
                    resources=resources,
                    source_manifest=source_manifest,
                )
                result.setdefault("bindings", {}).update(bindings)
    with final_check(connection) as at:
        if not scene_allowed(connection, workspace, scene, buffered, at):
            # Do not return usable command/bindings if rights or source currency changed.
            return _finish(
                _block(
                    _report(str(scene)),
                    "rights",
                    "inputs_changed",
                    "Source permissions or bindings changed during preflight.",
                )
            )
    result["authorization_scope"] = (
        "Current scene-read policy only. Recheck execution rights, admission and stages in worker."
    )
    return _finish(result)
