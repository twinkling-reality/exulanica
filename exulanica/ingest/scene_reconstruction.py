"""Turn one leased capture set into an atomic, receipt-gated reconstruction scene."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from contextlib import ExitStack, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from exulanica.canonical import canonical_json
from exulanica.errors import BlobNotFoundError, TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.ingest.committed_store import committed_writes
from exulanica.ingest.ledger import Ledger, StageRecorder
from exulanica.ingest.masked_inputs import apply_masked_sources
from exulanica.ingest.reconstruction_scratch import (
    ScratchBusy,
    ScratchSource,
    active_scene_scratch,
    cleanup_scene_scratch,
    stage_scene_sources,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scene_projection import (
    SCENE_PROJECTION_STAGE,
    build_scene_projection,
    projection_point_map_inputs,
    validate_scene_projection,
)
from exulanica.ingest.scene_rung import record_scene_rung
from exulanica.ingest.scene_segments import (
    SCENE_SEGMENTS_STAGE,
    ValidatedBuild,
    publish_scene_segments,
)
from exulanica.ingest.scene_splat import (
    ContainerCleanupUnconfirmed,
    SceneSplatRequest,
    cancellable_executor,
    evaluation_bundle,
    gaussian_ply_bounds,
    receipt_bytes,
    stage_training_dataset,
    training_dataset_directory,
)
from exulanica.ingest.spine.reconstruction_jobs import MAX_SCENE_CLAIMS, ClaimedSceneJob
from exulanica.ingest.stages import (
    STAGES,
    artifact_id_for,
    input_digest_of,
    scene_pose_quality_thresholds,
    stage,
)
from exulanica.reconstruction.placement import (
    PointMapInput,
    build_placement_record,
    validate_placement_record,
)
from exulanica.reconstruction.pose import (
    CommandExecutor,
    PoseBuildManifest,
    SourceFrame,
    run_colmap_pose_job,
)
from exulanica.reconstruction.pycolmap_executor import (
    PYCOLMAP_EXECUTABLE,
    PycolmapExecutor,
    pycolmap_version,
)
from exulanica.reconstruction.scene_gate import (
    SceneGateDecision,
    SceneGateInputs,
    SceneReceipt,
    decide_scene_rung,
)
from exulanica.reconstruction.splat import run_gsplat_job
from exulanica.store import ContentAddressedStore

__all__ = [
    "SceneBuildOutcome",
    "SceneReconstructionProcessor",
]

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/tiff": ".tif",
}


class _SplatCheckpointed(RuntimeError):
    pass


class _ClaimLost(RuntimeError):
    pass


class _ProjectionRefused(RuntimeError):
    """A projection could not be built. Fails its own stage and nothing else.

    Raised into an open `scene_projection` stage and immediately suppressed, so the ledger
    writes `stage_failed` naming the cause and the scene still publishes its receipts.
    """


@dataclass(frozen=True, slots=True)
class SceneBuildOutcome:
    job_id: uuid.UUID
    scene_id: uuid.UUID
    status: Literal["succeeded", "failed", "cancelled", "busy", "checkpointed"]
    rung: int | None = None
    registered_member_count: int = 0
    message: str | None = None


@dataclass(frozen=True, slots=True)
class _TrainedGaussians:
    """The accepted training output a delivery was compressed from, for the segment lift."""

    ply: Path
    delivery_sha256: str


@dataclass(frozen=True, slots=True)
class _PendingArtifact:
    kind: str
    key: str
    artifact_id: uuid.UUID
    input_digest: bytes
    payload: bytes
    content_id: BlobId
    storage_key: str
    byte_size: int


def _scene_key(scene_id: uuid.UUID, stage_key: str, input_digest: bytes) -> str:
    spec = stage(stage_key)
    hasher = hashlib.sha256()
    for part in (
        b"exulanica/scene-artifact-key",
        b"1",
        scene_id.bytes,
        stage_key.encode("utf-8"),
        str(spec.version).encode("ascii"),
        spec.params_digest,
        input_digest,
    ):
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)
    return hasher.hexdigest()


def _filename(member_index: int, media_type: str) -> str:
    extension = _EXTENSIONS.get(media_type)
    if extension is None:
        raise ValueError(f"pose recovery does not support source media type {media_type!r}")
    return f"{member_index:06d}{extension}"


class SceneReconstructionProcessor:
    """The ingest-owned publication boundary around geometry-only reconstruction."""

    def __init__(
        self,
        repository: IngestRepository,
        store: ContentAddressedStore,
        scratch_root: Path,
        *,
        code_revision: str,
        execution_image: str,
        colmap_version: str | None = None,
        executor: CommandExecutor | None = None,
        retry_delay_seconds: float = 30.0,
        external_cancellation: Callable[[], bool] | None = None,
        stop_requested: Callable[[], bool] | None = None,
        splat_executor: CommandExecutor | None = None,
        compressor_gpu: str = "cpu",
    ) -> None:
        self._repository = repository
        self._store = store
        self._scratch_root = scratch_root
        self._code_revision = code_revision
        self._execution_image = execution_image
        self._colmap_version = colmap_version
        self._executor = executor
        self._retry_delay_seconds = retry_delay_seconds
        self._external_cancellation = external_cancellation
        self._stop_requested = stop_requested or (lambda: False)
        self._splat_executor = splat_executor
        self._compressor_gpu = compressor_gpu

    def process(self, claimed: ClaimedSceneJob) -> SceneBuildOutcome:
        """Run or resume one claim, flush guarded bytes, then publish the scene."""
        if claimed.scratch_key is None:
            raise ValueError("a reconstruction job has no deterministic scratch key")
        ledger = Ledger.start_run(self._repository, trigger="reprocess")
        self._repository.register_stages(STAGES)
        should_cleanup = False
        try:
            with active_scene_scratch(self._scratch_root, claimed.scratch_key) as job_directory:
                outcome = self._process_locked(claimed, job_directory, ledger)
                should_cleanup = outcome.status in {"succeeded", "failed", "cancelled"}
        except ScratchBusy as error:
            self._repository.fail_reconstruction_scene_job(
                job_id=claimed.job_id,
                claim_token=claimed.claim_token,
                failure_class="scratch_busy",
                failure_message=str(error),
                retry_delay_seconds=self._retry_delay_seconds,
            )
            ledger.finish("failed")
            return SceneBuildOutcome(
                claimed.job_id,
                claimed.scene_id,
                "busy",
                message=str(error),
            )
        except ContainerCleanupUnconfirmed as error:
            self._repository.fail_reconstruction_scene_job(
                job_id=claimed.job_id,
                claim_token=claimed.claim_token,
                failure_class="container_cleanup_unconfirmed",
                failure_message=str(error),
                retry_delay_seconds=self._retry_delay_seconds,
            )
            ledger.finish("failed")
            return SceneBuildOutcome(claimed.job_id, claimed.scene_id, "failed", message=str(error))
        except _SplatCheckpointed as error:
            released = self._repository.release_checkpointed_reconstruction_scene(
                job_id=claimed.job_id,
                claim_token=claimed.claim_token,
                retry_delay_seconds=self._retry_delay_seconds,
            )
            should_cleanup = not released
            ledger.finish("failed" if released else "cancelled")
            return SceneBuildOutcome(
                claimed.job_id,
                claimed.scene_id,
                "checkpointed" if released else "cancelled",
                message=str(error),
            )
        except TombstonedError as error:
            ledger.finish("cancelled")
            should_cleanup = True
            return SceneBuildOutcome(
                claimed.job_id,
                claimed.scene_id,
                "cancelled",
                message=str(error),
            )
        except Exception as error:
            self._repository.fail_reconstruction_scene_job(
                job_id=claimed.job_id,
                claim_token=claimed.claim_token,
                failure_class=type(error).__name__,
                failure_message=str(error),
                retry_delay_seconds=self._retry_delay_seconds,
            )
            ledger.finish("failed")
            should_cleanup = (
                claimed.build_inputs.get("splat_training") is None
                or claimed.attempts >= MAX_SCENE_CLAIMS
            )
            return SceneBuildOutcome(
                claimed.job_id,
                claimed.scene_id,
                "failed",
                message=str(error),
            )
        finally:
            if should_cleanup:
                cleanup_scene_scratch(self._scratch_root, claimed.scratch_key)
        ledger.finish(outcome.status)
        return outcome

    def _process_locked(
        self,
        claimed: ClaimedSceneJob,
        job_directory: Path,
        ledger: Ledger,
    ) -> SceneBuildOutcome:
        with ExitStack() as stack:
            outcome, build, trained = self._process_stages(claimed, job_directory, ledger, stack)
        # After every stage of the build has closed, the training stages in `stack` included, so
        # none of them is timed as though the lift were part of it.
        self._lift_segments(claimed, ledger, build, trained)
        return outcome

    def _process_stages(
        self,
        claimed: ClaimedSceneJob,
        job_directory: Path,
        ledger: Ledger,
        stack: ExitStack,
    ) -> tuple[SceneBuildOutcome, ValidatedBuild, _TrainedGaussians | None]:
        """Build, gate and publish the scene. Returns only once it is published."""
        self._verify_build_inputs(claimed)
        manifest, sources = self._manifest(claimed)
        source_directory = stage_scene_sources(self._store, job_directory, sources)
        pose_spec = stage("scene_pose")
        with ledger.stage(pose_spec) as pose_recorder:
            result = run_colmap_pose_job(
                manifest,
                source_dir=source_directory,
                jobs_root=job_directory / "pose",
                executable=PYCOLMAP_EXECUTABLE,
                executor=self._executor or PycolmapExecutor(),
                cancellation_check=lambda: self._cancelled(claimed),
            )
            if result.status == "cancelled":
                raise TombstonedError(
                    result.failure_reason or "the scene claim was cancelled during pose recovery"
                )
            if result.status == "failed" or result.quality is None:
                message = result.failure_reason or "pose recovery produced no quality receipt"
                raise RuntimeError(message)
            pose_bytes = (result.job_directory / "receipt.json").read_bytes()
            pose_artifact = self._pending(
                claimed.scene_id,
                pose_spec.key,
                pose_bytes,
                input_digest_of(
                    [
                        bytes.fromhex(manifest.digest),
                        claimed.build_input_digest,
                        claimed.job_id.bytes,
                    ]
                ),
            )

            point_maps = self._point_maps(claimed)
            placement_spec = stage("scene_placement")
            with ledger.stage(
                placement_spec, input_artifact_ids=[pose_artifact.artifact_id]
            ) as placement_recorder:
                member_refs = [str(member.capture_id) for member in claimed.members]
                placement = build_placement_record(
                    scene_ref=str(claimed.scene_id),
                    pose_receipt=pose_bytes,
                    member_capture_refs=member_refs,
                    point_maps=point_maps,
                )
                placement_bytes = placement.to_bytes()
                validate_placement_record(
                    placement_bytes,
                    expected_scene_ref=str(claimed.scene_id),
                    pose_receipt=pose_bytes,
                    member_capture_refs=member_refs,
                    point_maps=point_maps,
                )
                placement_input = input_digest_of(
                    [pose_artifact.content_id.digest]
                    + [bytes.fromhex(point_map.content_sha256) for point_map in point_maps.values()]
                )
                placement_artifact = self._pending(
                    claimed.scene_id,
                    placement_spec.key,
                    placement_bytes,
                    placement_input,
                )

                registered_names = set(result.quality.registered_images)
                registered_count = len(registered_names)
                pose_receipt = SceneReceipt(
                    kind="pose",
                    sha256=pose_artifact.content_id.hex,
                    accepted=result.quality.accepted,
                    reasons=result.quality.reasons,
                )
                placement_receipt = SceneReceipt(
                    kind="placement",
                    sha256=placement_artifact.content_id.hex,
                    accepted=bool(placement.placed),
                    reasons=(
                        ()
                        if placement.placed
                        else ("no registered member has a verified point-map artifact",)
                    ),
                )
                extras: tuple[tuple[_PendingArtifact, StageRecorder], ...] = ()
                splat_receipt = None
                trained: _TrainedGaussians | None = None
                if claimed.build_inputs.get("splat_training") is not None:
                    extras, splat_receipt, trained = self._train_splat(
                        claimed,
                        manifest,
                        source_directory,
                        result.job_directory,
                        ledger,
                        stack,
                        pose_artifact,
                    )
                decision = decide_scene_rung(
                    SceneGateInputs(
                        pose=pose_receipt,
                        placement=placement_receipt,
                        registered_member_count=registered_count,
                        member_count=len(claimed.members),
                        splat=splat_receipt,
                    )
                )
                gate_spec = stage("scene_gate")
                with ledger.stage(
                    gate_spec,
                    input_artifact_ids=[
                        pose_artifact.artifact_id,
                        placement_artifact.artifact_id,
                        *(artifact.artifact_id for artifact, _ in extras),
                    ],
                ) as gate_recorder:
                    gate_bytes = decision.to_bytes()
                    gate_artifact = self._pending(
                        claimed.scene_id,
                        gate_spec.key,
                        gate_bytes,
                        input_digest_of(
                            [
                                pose_artifact.content_id.digest,
                                placement_artifact.content_id.digest,
                                *(artifact.content_id.digest for artifact, _ in extras),
                            ]
                        ),
                    )
                    registrations = [
                        (
                            member.capture_id,
                            _filename(member.ordinal, member.media_type) in registered_names,
                        )
                        for member in claimed.members
                    ]
                    # The projection is written last because it binds all three receipts, and
                    # inside the gate stage because `_accept` needs every recorder still open.
                    #
                    # A projection that cannot be built does NOT take the scene down with it.
                    # `build_scene_projection` transcribes a placement this worker has already
                    # validated against this pose receipt and these point maps, so it should
                    # never raise on real output, and every guard it applies is one
                    # `_validate_matrix` and `_calibration` have already made. But if it ever did,
                    # failing the job here would discard a completed pose, placement and gate,
                    # set `should_cleanup` on a non-splat scene and destroy the scratch, and the
                    # retry would be deterministic: three full COLMAP runs, measured in tens of
                    # minutes on 210 photographs, to end with no scene at all. The pre-change
                    # behaviour in that situation was a published scene with a slow cold read.
                    #
                    # `_verify_build_inputs` was moved to the top of this function for exactly
                    # this reason, so a refusal would not cost thirty minutes of matching. It
                    # would be strange to add a new refusal at the very end of the same pipeline.
                    #
                    # The failure is not silent: the stage is opened either way, so a refusal is
                    # written as `stage_failed` on `scene_projection` naming its error class and
                    # message, and `scripts/backfill_scene_projections.py` can fill the artifact
                    # in afterwards.
                    projection_spec = stage(SCENE_PROJECTION_STAGE)
                    published = (
                        (pose_artifact, pose_recorder),
                        (placement_artifact, placement_recorder),
                        (gate_artifact, gate_recorder),
                        *extras,
                    )
                    try:
                        projection_bytes = build_scene_projection(
                            scene_ref=str(claimed.scene_id),
                            pose_receipt=pose_bytes,
                            pose_receipt_sha256=pose_artifact.content_id.hex,
                            placement_receipt_sha256=placement_artifact.content_id.hex,
                            gate_receipt_sha256=gate_artifact.content_id.hex,
                            member_capture_refs=member_refs,
                            placement=placement,
                        )
                        # Checked here rather than trusted, so that the bytes a reader will
                        # refuse are never published in the first place.
                        validate_scene_projection(
                            projection_bytes,
                            expected_scene_ref=str(claimed.scene_id),
                            pose_receipt_sha256=pose_artifact.content_id.hex,
                            placement_receipt_sha256=placement_artifact.content_id.hex,
                            gate_receipt_sha256=gate_artifact.content_id.hex,
                            member_capture_refs=member_refs,
                            point_map_inputs=projection_point_map_inputs(placement),
                        )
                    except (KeyError, TypeError, ValueError) as error:
                        with (
                            suppress(_ProjectionRefused),
                            ledger.stage(
                                projection_spec,
                                input_artifact_ids=[
                                    pose_artifact.artifact_id,
                                    placement_artifact.artifact_id,
                                    gate_artifact.artifact_id,
                                ],
                            ),
                        ):
                            raise _ProjectionRefused(str(error)) from error
                        self._accept(claimed, manifest, decision, registrations, published, ledger)
                    else:
                        with ledger.stage(
                            projection_spec,
                            input_artifact_ids=[
                                pose_artifact.artifact_id,
                                placement_artifact.artifact_id,
                                gate_artifact.artifact_id,
                            ],
                        ) as projection_recorder:
                            projection_artifact = self._pending(
                                claimed.scene_id,
                                projection_spec.key,
                                projection_bytes,
                                input_digest_of(
                                    [
                                        pose_artifact.content_id.digest,
                                        placement_artifact.content_id.digest,
                                        gate_artifact.content_id.digest,
                                    ]
                                ),
                            )
                            self._accept(
                                claimed,
                                manifest,
                                decision,
                                registrations,
                                (
                                    *published,
                                    (projection_artifact, projection_recorder),
                                ),
                                ledger,
                            )
        outcome = SceneBuildOutcome(
            claimed.job_id,
            claimed.scene_id,
            "succeeded",
            rung=decision.rung,
            registered_member_count=registered_count,
        )
        build = ValidatedBuild(
            job_id=claimed.job_id,
            pose_receipt=pose_bytes,
            placement_receipt=placement_bytes,
            placement=placement,
            point_maps={
                capture_ref: item.content
                for capture_ref, item in point_maps.items()
                if item.content is not None
            },
        )
        return outcome, build, trained

    def _lift_segments(
        self,
        claimed: ClaimedSceneJob,
        ledger: Ledger,
        build: ValidatedBuild,
        trained: _TrainedGaussians | None = None,
    ) -> None:
        """Lift what the members' photographs found into the scene just published. Never raises.

        After publication rather than inside it, and never able to take the scene down, for the
        reason the projection gives in `_process_stages` and more strongly: segments are an overlay
        on a scene that is complete without them, and a lift can refuse for reasons that have
        nothing to do with this build, a mask artifact whose bytes were lost among them. Whatever
        it refuses is on its own `scene_segments` stage in this run, `stage_failed` or
        `stage_skipped` with the reason, and `scenes_due_segments` or the command can lift the
        scene again later. It reuses the placement this worker validated a moment ago rather than
        validating it a second time, which is most of what a lift costs.

        When the build trained a delivery that was accepted, the lift also samples the accepted
        Gaussians the delivery was compressed from, still in this job's scratch. They are one
        surface where the posed point maps are one guess per photograph, so segments lifted over
        them follow what a trained scene draws. MEASURED 2026-09-11 on the volcanic point maps:
        voxels from the stacked per-photograph maps reached 25 per cent of the rock as its own
        photographs outline it (``docs/scene-segments.md`` section 8).

        A worker asked to stop skips it, so that shutting down never waits on an overlay.
        """
        # Every Exception, not only the refusals the projection names. This runs after the
        # publication commit, and anything that escaped would reach `process`, which would report
        # a published scene as failed and try to fail a job that has already succeeded. A failure
        # inside the lift's stage has already been written as `stage_failed` by the time it lands
        # here; one before that stage opens is a database that cannot record it either.
        with suppress(Exception):
            if self._stop_requested():
                ledger.skipped(
                    stage(SCENE_SEGMENTS_STAGE),
                    reason="the worker was asked to stop before the scene was lifted",
                )
                return
            gaussian_ply = None if trained is None else trained.ply.read_bytes()
            publish_scene_segments(
                self._repository,
                self._store,
                claimed.scene_id,
                ledger=ledger,
                validated=build,
                gaussian_ply=gaussian_ply,
                gaussian_source=(
                    None
                    if trained is None or gaussian_ply is None
                    else {
                        "ply_sha256": hashlib.sha256(gaussian_ply).hexdigest(),
                        "delivery_sha256": trained.delivery_sha256,
                        "basis": "accepted training output the delivery was compressed from",
                    }
                ),
            )

    def _train_splat(
        self,
        claimed: ClaimedSceneJob,
        pose: PoseBuildManifest,
        sources: Path,
        pose_directory: Path,
        ledger: Ledger,
        stack: ExitStack,
        pose_artifact: _PendingArtifact,
    ) -> tuple[
        tuple[tuple[_PendingArtifact, StageRecorder], ...],
        SceneReceipt,
        _TrainedGaussians | None,
    ]:
        request = SceneSplatRequest.from_payload(claimed.build_inputs["splat_training"])
        manifest = request.manifest(pose)
        training_input = input_digest_of(
            [bytes.fromhex(manifest.digest), claimed.build_input_digest, claimed.job_id.bytes]
        )
        dataset = stage_training_dataset(
            sources, pose_directory / "sparse", training_dataset_directory(pose_directory)
        )
        recorder = stack.enter_context(
            ledger.stage(
                stage("scene_splat_training"), input_artifact_ids=[pose_artifact.artifact_id]
            )
        )
        result = run_gsplat_job(
            manifest,
            dataset_dir=dataset,
            pose_receipt=pose_directory / "receipt.json",
            jobs_root=pose_directory.parent.parent / "splat",
            compressor_gpu=self._compressor_gpu,
            executor=self._splat_executor
            or cancellable_executor(lambda: self._cancelled(claimed), self._stop_requested),
        )
        if self._cancelled(claimed):
            raise TombstonedError("scene was withdrawn before training publication")
        for member in claimed.members:
            self._store.get(member.blob_id)  # Reverify original bytes after an expensive run.
        if result.status == "checkpointed":
            raise _SplatCheckpointed("Gaussian training saved a checkpoint; retry this exact job")
        if result.status != "completed" or result.quality is None:
            raise RuntimeError(result.reason or "Gaussian training failed")
        quality = result.quality
        # Quality acceptance is appearance consistency, not a physical-scale/rung claim.
        publication: dict[str, object] = {
            "profile": "exulanica.scene-splat-publication/v1",
            "scene_ref": str(claimed.scene_id),
            "pose_receipt_sha256": pose_artifact.content_id.hex,
            "manifest": manifest.as_payload(),
            "manifest_digest": manifest.digest,
            "quality": quality.as_payload(),
            "delivery": None,
        }
        outputs: list[tuple[_PendingArtifact, StageRecorder]] = []
        trained: _TrainedGaussians | None = None
        evaluation_bytes = evaluation_bundle(result.job_directory / "output")
        evaluation_recorder = stack.enter_context(
            ledger.stage(
                stage("scene_splat_evaluation"), input_artifact_ids=[pose_artifact.artifact_id]
            )
        )
        evaluation = self._pending(
            claimed.scene_id,
            "scene_splat_evaluation",
            evaluation_bytes,
            hashlib.sha256(evaluation_bytes).digest(),
        )
        outputs.append((evaluation, evaluation_recorder))
        publication["evaluation"] = {
            "artifact_id": str(evaluation.artifact_id),
            "content_sha256": evaluation.content_id.hex,
            "byte_size": evaluation.byte_size,
            "container": "zip-stored/1",
        }
        if quality.accepted:
            content = (result.job_directory / "output" / "scene.sog").read_bytes()
            if hashlib.sha256(content).hexdigest() != quality.delivery_sha256:
                raise ValueError("trained delivery bytes changed before publication")
            delivery_recorder = stack.enter_context(
                ledger.stage(
                    stage("scene_splat_delivery"), input_artifact_ids=[pose_artifact.artifact_id]
                )
            )
            delivery = self._pending(
                claimed.scene_id, "scene_splat_delivery", content, training_input
            )
            outputs.append((delivery, delivery_recorder))
            publication["delivery"] = {
                "artifact_id": str(delivery.artifact_id),
                "content_sha256": delivery.content_id.hex,
                "byte_size": delivery.byte_size,
                "container": "sog/1",
                "scene_from_asset_row_major": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                "bounds": gaussian_ply_bounds(
                    (result.job_directory / "output" / "accepted.ply").read_bytes()
                ),
                "bounds_convention": "axis-aligned-three-sigma-Gaussian-support",
            }
            # Identity above, so the accepted Gaussians are already in the scene frame the
            # segment lift samples in; a delivery with any other transform would need it here.
            trained = _TrainedGaussians(
                result.job_directory / "output" / "accepted.ply", delivery.content_id.hex
            )
        training_receipt = self._pending(
            claimed.scene_id,
            "scene_splat_training",
            receipt_bytes(publication),
            training_input,
        )
        outputs.append((training_receipt, recorder))
        return (
            tuple(outputs),
            SceneReceipt(
                kind="splat",
                sha256=training_receipt.content_id.hex,
                accepted=quality.accepted,
                reasons=quality.reasons,
            ),
            trained,
        )

    def _manifest(
        self, claimed: ClaimedSceneJob
    ) -> tuple[PoseBuildManifest, tuple[ScratchSource, ...]]:
        # Reconstruction reads the masked derivative wherever this job declared one, so a person
        # who never consented is already neutral fill by the time COLMAP sees a pixel. Rebound
        # here and nowhere else: `claimed.members` elsewhere in this class is the deletion and
        # tombstone boundary and must keep naming the original capture bytes.
        claimed = apply_masked_sources(self._repository, claimed)
        capture_set = str(
            claimed.selection_policy.get("source", {}).get("group_key", claimed.scene_id)
            if isinstance(claimed.selection_policy.get("source"), dict)
            else claimed.scene_id
        )
        frames: list[SourceFrame] = []
        sources: list[ScratchSource] = []
        for member in claimed.members:
            filename = _filename(member.ordinal, member.media_type)
            frames.append(
                SourceFrame(
                    capture_ref=str(member.capture_id),
                    filename=filename,
                    sha256=member.blob_id.hex,
                    capture_set=capture_set,
                )
            )
            sources.append(ScratchSource(filename, member.blob_id))
        thresholds = scene_pose_quality_thresholds(stage("scene_pose"))
        manifest = PoseBuildManifest(
            scene_ref=str(claimed.scene_id),
            code_revision=self._code_revision,
            colmap_version=self._colmap_version or pycolmap_version(),
            execution_image=self._execution_image,
            frames=tuple(frames),
            min_registered_fraction=thresholds.min_registered_fraction,
            max_mean_reprojection_error_px=thresholds.max_mean_reprojection_error_px,
            min_camera_translation_units=thresholds.min_camera_translation_units,
        )
        return manifest, tuple(sources)

    def _verify_build_inputs(self, claimed: ClaimedSceneJob) -> list[object]:
        """Refuse a job whose exact build inputs cannot run under the current stage rules.

        Called before any stage executes. MEASURED 2026-09-05: this check used to live after
        pose recovery, and a retryable job queued under an earlier stage version spent thirty
        minutes of COLMAP matching on 210 photographs before being refused as stale. The refusal
        is the same; it now costs nothing.
        """
        if hashlib.sha256(canonical_json(claimed.build_inputs)).digest() != (
            claimed.build_input_digest
        ):
            raise ValueError("the scene job build-input digest does not reproduce")
        if claimed.build_inputs.get("profile") != "exulanica.reconstruction-scene-build-input/v1":
            raise ValueError("the scene job does not declare supported exact build inputs")
        raw_point_maps = claimed.build_inputs.get("point_maps")
        raw_stages = claimed.build_inputs.get("stages")
        if not isinstance(raw_point_maps, list) or not isinstance(raw_stages, list):
            raise ValueError("the scene build input record is malformed")
        expected_stages = [
            {
                "key": key,
                "version": stage(key).version,
                "params_sha256": stage(key).params_digest.hex(),
            }
            for key in (
                ("scene_pose", "scene_placement", "scene_gate")
                + (
                    ("scene_splat_training", "scene_splat_delivery", "scene_splat_evaluation")
                    if claimed.build_inputs.get("splat_training") is not None
                    else ()
                )
            )
        ]
        if raw_stages != expected_stages:
            raise ValueError("the scene job stage bindings are no longer current")
        return raw_point_maps

    def _point_maps(self, claimed: ClaimedSceneJob) -> dict[str, PointMapInput]:
        raw_point_maps = self._verify_build_inputs(claimed)
        expected_capture_refs = [str(member.capture_id) for member in claimed.members]
        if [item.get("capture_ref") for item in raw_point_maps if isinstance(item, dict)] != (
            expected_capture_refs
        ):
            raise ValueError("the scene job must bind one point map for every ordered member")
        declared: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
        try:
            for item in raw_point_maps:
                if not isinstance(item, dict):
                    raise ValueError
                capture_id = uuid.UUID(item["capture_ref"])
                artifact_id = uuid.UUID(item["artifact_ref"])
                digest = item["content_sha256"]
                if not isinstance(digest, str) or len(bytes.fromhex(digest)) != 32:
                    raise ValueError
                declared[capture_id] = (artifact_id, digest)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("the scene job point-map bindings are malformed") from error
        rows = self._repository.exact_capture_artifacts(
            artifact_ids_by_capture={
                capture_id: artifact_id for capture_id, (artifact_id, _digest) in declared.items()
            },
            kind="point_map",
        )
        if len(rows) != len(claimed.members):
            raise ValueError("an exact point-map build input is no longer available")
        usable: dict[str, PointMapInput] = {}
        for member in claimed.members:
            capture_id = member.capture_id
            row = rows[capture_id]
            artifact_id, digest = declared[capture_id]
            if row.artifact_id != artifact_id or row.content_sha256.hex() != digest:
                raise ValueError("an exact point-map build input disagrees with its artifact row")
            if row.storage_key != self._store.key_for(BlobId(row.content_sha256)):
                raise ValueError("an exact point-map build input has a non-canonical storage key")
            content = self._store.get(BlobId(row.content_sha256))
            usable[str(capture_id)] = PointMapInput(
                capture_ref=str(capture_id),
                artifact_ref=str(row.artifact_id),
                content_sha256=row.content_sha256.hex(),
                content=content,
            )
        return usable

    def _pending(
        self,
        scene_id: uuid.UUID,
        stage_key: str,
        payload: bytes,
        input_digest: bytes,
    ) -> _PendingArtifact:
        spec = stage(stage_key)
        key = _scene_key(scene_id, spec.key, input_digest)
        content_id = BlobId.of_bytes(payload)
        return _PendingArtifact(
            kind=spec.output_kind,
            key=key,
            artifact_id=artifact_id_for(key),
            input_digest=input_digest,
            payload=payload,
            content_id=content_id,
            storage_key=self._store.key_for(content_id),
            byte_size=len(payload),
        )

    def _accept(
        self,
        claimed: ClaimedSceneJob,
        manifest: PoseBuildManifest,
        decision: SceneGateDecision,
        registrations: list[tuple[uuid.UUID, bool]],
        artifacts: tuple[tuple[_PendingArtifact, StageRecorder], ...],
        ledger: Ledger,
    ) -> None:
        if self._cancelled(claimed):
            raise TombstonedError("a member was deleted before scene acceptance")
        pending_artifacts = [pending for pending, _recorder in artifacts]
        with self._repository.locked_stored_objects(
            [pending.content_id for pending in pending_artifacts]
        ):
            # First commit the tombstone-guarded rows, then flush their bytes. The session locks
            # remain held across both operations, so a purger cannot mark an absent object gone
            # and then have this worker recreate it after deletion.
            with committed_writes(self._repository, self._store) as pending_payloads:
                if self._cancelled(claimed):
                    raise TombstonedError("a member was deleted before scene preparation")
                self._repository.insert_completed_reconstruction_scene(
                    scene_id=claimed.scene_id,
                    member_digest=claimed.member_digest,
                    scene_members=registrations,
                    job_id=claimed.job_id,
                )
                for pending, recorder in artifacts:
                    spec = stage(recorder.spec.key)
                    inserted = self._repository.insert_scene_artifact(
                        artifact_id=pending.artifact_id,
                        kind=pending.kind,
                        scene_id=claimed.scene_id,
                        stage_key=spec.key,
                        stage_version=spec.version,
                        params_digest=spec.params_digest,
                        input_digest=pending.input_digest,
                        idempotency_key=pending.key,
                        content_sha256=pending.content_id.digest,
                        storage_key=pending.storage_key,
                        byte_size=pending.byte_size,
                        produced_by_event=recorder.stage_started_event,
                    )
                    if inserted:
                        recorder.record_output(pending.artifact_id)
                    else:
                        existing = self._repository.find_artifact(pending.key)
                        if (
                            existing is None
                            or existing.artifact_id != pending.artifact_id
                            or existing.content_sha256 != pending.content_id.digest
                            or existing.byte_size != pending.byte_size
                        ):
                            raise ValueError(
                                "an existing scene artifact disagrees with recomputed bytes"
                            )
                        recorder.output_artifact_ids.append(pending.artifact_id)
                    pending_payloads.append(pending.payload)

            # The public assertion and succeeded transition are the publication point. A crash
            # after the prepare commit is safely retryable because neither becomes visible here.
            if self._cancelled(claimed):
                raise TombstonedError("a member was deleted before scene publication")
            with self._repository.transaction():
                rung_assertion_id = record_scene_rung(
                    self._repository,
                    scene_id=claimed.scene_id,
                    job_id=claimed.job_id,
                    run_id=ledger.run_id,
                    decision=decision,
                    return_existing=True,
                )
                assert rung_assertion_id is not None
                if not self._repository.complete_reconstruction_scene_job(
                    job_id=claimed.job_id,
                    claim_token=claimed.claim_token,
                    scratch_key=claimed.scratch_key or "",
                    pose_manifest_digest=bytes.fromhex(manifest.digest),
                    pose_receipt_artifact_id=artifacts[0][0].artifact_id,
                    placement_artifact_id=artifacts[1][0].artifact_id,
                    gate_artifact_id=artifacts[2][0].artifact_id,
                    rung_assertion_id=rung_assertion_id,
                ):
                    raise _ClaimLost("the scene claim was cancelled or reclaimed before commit")

    def _cancelled(self, claimed: ClaimedSceneJob) -> bool:
        cancelled = bool(
            (self._external_cancellation is not None and self._external_cancellation())
            or self._repository.reconstruction_scene_cancelled_or_lost(
                job_id=claimed.job_id,
                claim_token=claimed.claim_token,
            )
        )
        if not cancelled and any(
            not self._store.exists(member.blob_id) for member in claimed.members
        ):
            raise BlobNotFoundError("an exact scene source is absent from the authoritative store")
        return cancelled
