"""The joint reconstruction that admits one scene to a place, or refuses and says why.

``docs/place-identity.md`` opens with the constraint that shapes this whole module: **retained
receipts alone cannot align two captures.** No learned feature descriptors are persisted, and
COLMAP point ids are global within one reconstruction and mean nothing across two, so there is
no post-hoc computation over stored artifacts that could relate two scenes' frames. The
correspondences come from a **reconstruction over the union of both capture sets**, which
recovers every camera a second time in one shared frame. What is fitted, twice, is the
similarity between each scene's own recovered frame and that joint frame.

**This is a callable build and not a leased queue, deliberately.** The design note gives the
reason: no joint reconstruction has ever run here, so a fourth copy of the claim, lease,
heartbeat and reclaim machinery would be scheduling logic with no executed instance to validate
it, and the failure modes it exists to survive, a worker dying mid-COLMAP and a lease expiring
during a forty-five minute job, are exactly the ones a stub cannot exercise. What is given up is
real and is named there: until the queue exists, a joint run is an operator action rather than
something a read of an unbuilt place can trigger. The executor is injected for the same reason
the pose path injects one, so this is exercisable against the double the reconstruction tests
already use.

**Three things this build must never do, each of which it would be easy to do.**

*Route the joint run through the ``scene_pose`` stage.* ``exulanica/reconstruction/pose.py``
appends "joint reconstruction has no measured metric scale" to its reasons whenever a manifest
declares more than one capture set and carries no metric scale, so every successful joint run
would arrive looking like a quality failure. What this build reads from that machinery is
``jointly_coregistered``, which is the recorded fact that both declared capture sets landed in
one connected model, and which is dead code today only because the ingest layer stamps one
constant capture set on every frame. Here each frame is stamped with its ORIGIN scene, so that
check finally decides something.

*Turn a refusal into an exception.* ``place-alignment-not-connected``,
``place-alignment-insufficient-correspondences`` and ``place-alignment-inconsistent`` are
measured outcomes. Each writes a ``place_alignment`` row carrying its reason and no
``place_version``, and the caller gets a result rather than a traceback. The scene processor
catches every exception and files it as a job failure with ``failure_class`` set to the
exception's class name, which is the right shape for a crash and the wrong shape entirely for a
verdict the world is supposed to be able to read back.

*Promote the joint model.* It is a third frame that no scene is addressed in and that nothing
else in the system can resolve, so it stays a build intermediate. Its digest goes in the receipt
so the fit stays checkable, exactly as Phase 3C treats a training intermediate.

**The frame is the anchor's own.** A place's shared frame is its anchor scene's recovered frame,
so the anchor's transform is identity, its ``frame_hops`` is 0 and no alignment admitted it. A
joint run yields ``joint_from_candidate`` and ``joint_from_against``, so

    place_from_candidate = place_from_against . inverse(joint_from_against) . joint_from_candidate

and ``frame_hops`` is one more than the version it was measured against. When that version is
the anchor, ``place_from_against`` is identity and the candidate is one hop out. A scene
admitted against a non-anchor version is two, and that column is what stops a reader taking a
composed transform for a measured one.

**No metres, ever.** Both frames are recovered COLMAP frames. Two captures sharing one frame is
a statement about their consistency with each other and about nothing physical, and
``physically_validated`` is false in every receipt this module can write.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from exulanica.canonical import sha256_of_canonical
from exulanica.errors import TombstonedError
from exulanica.evidence.blob import BlobId
from exulanica.evidence.scene import scene_member_digest
from exulanica.ingest.committed_store import committed_writes
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.reconstruction_scratch import (
    ScratchSource,
    active_scene_scratch,
    cleanup_scene_scratch,
    scene_scratch_key,
    stage_scene_sources,
)
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.spine import places
from exulanica.ingest.spine.scope import WorkspaceScope
from exulanica.ingest.stages import STAGES, artifact_id_for, input_digest_of, stage
from exulanica.reconstruction.place_alignment import (
    PLACE_ALIGNMENT_POLICY,
    PlaceAlignmentResult,
    PlaceCorrespondence,
    fit_place_alignment,
)
from exulanica.reconstruction.pose import (
    CommandExecutor,
    PoseBuildManifest,
    PoseQuality,
    SourceFrame,
    run_colmap_pose_job,
)
from exulanica.reconstruction.pycolmap_executor import PYCOLMAP_EXECUTABLE
from exulanica.store import ContentAddressedStore

__all__ = [
    "PLACE_ALIGNMENT_RECEIPT_PROFILE",
    "PLACE_ALIGNMENT_STAGE",
    "PlaceAlignmentOutcome",
    "PlaceAlignmentUnavailable",
    "build_place_alignment",
    "establish_place",
]

#: The receipt this build writes, and the only profile its readers accept.
PLACE_ALIGNMENT_RECEIPT_PROFILE = "exulanica.place-alignment-receipt/v1"

PLACE_ALIGNMENT_STAGE = "place_alignment"

_POSE_RECEIPT_PROFILE = "exulanica.colmap-pose-receipt/v2"

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/tiff": ".tif",
}

#: Row-major, and the anchor's transform to its own place frame is exactly this and nothing
#: fitted. The anchor is the frame; a fitted identity would be a measurement of a tautology.
_IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)


class PlaceAlignmentUnavailable(RuntimeError):
    """A precondition of the build is absent, so nothing was measured and nothing is claimed.

    Distinct from a refusal on purpose. A refusal is a verdict about two capture sets that were
    both reconstructed and could not be reconciled; this is the build saying it never got as far
    as a measurement, because a scene retained no pose receipt, because the place has no anchor,
    or because the candidate already belongs to another place. Writing one of the fitter's three
    reasons here would file "nothing was measured" as "the geometry disagreed".
    """


@dataclass(frozen=True, slots=True)
class PlaceAlignmentOutcome:
    """What one joint reconstruction decided, and where the receipt for it lives."""

    place_id: uuid.UUID
    candidate_scene_id: uuid.UUID
    against_scene_id: uuid.UUID
    alignment_id: uuid.UUID
    receipt_artifact_id: uuid.UUID
    accepted: bool
    reason: str | None
    #: The candidate's hops from the anchor when it was admitted. None on a refusal, because a
    #: refused candidate has no version and therefore no distance from a frame it never joined.
    frame_hops: int | None
    #: True when this call found the verdict already recorded and ran no reconstruction.
    reused: bool


def establish_place(
    repository: IngestRepository,
    *,
    place_id: uuid.UUID,
    anchor_scene_id: uuid.UUID,
) -> bool:
    """Create a place and bind the scene whose recovered frame it adopts. False if already so.

    Creating a place writes nothing to the anchor scene, which is the forward-migration rule
    ``docs/place-identity.md`` states: adding a place never rewrites a scene. The anchor version
    carries ``frame_hops`` 0 and no admitting alignment, because its transform is identity by
    construction rather than by measurement, and 0038's
    ``only_the_anchor_arrives_unmeasured`` is the half of that rule the database keeps.
    """
    scope = _scope(repository)
    if places.version_of_scene(scope, anchor_scene_id) is not None:
        raise PlaceAlignmentUnavailable(
            f"scene {anchor_scene_id} already belongs to a place; a scene belongs to at most one"
        )
    if not places.scene_members(scope, anchor_scene_id):
        raise PlaceAlignmentUnavailable(f"scene {anchor_scene_id} has no members to anchor a place")
    started_at = places.earliest_capture_time(scope, anchor_scene_id)
    with repository.transaction():
        places.insert_place(scope, place_id=place_id)
        return places.insert_version(
            scope,
            place_id=place_id,
            scene_id=anchor_scene_id,
            ordinal=places.next_ordinal(scope, place_id=place_id),
            ordered_by_utc=started_at,
            ordered_by_basis="capture_exif" if started_at is not None else "unavailable",
            frame_hops=0,
            admitted_by_alignment_id=None,
        )


def build_place_alignment(
    repository: IngestRepository,
    store: ContentAddressedStore,
    *,
    place_id: uuid.UUID,
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
    scratch_root: Path,
    code_revision: str,
    execution_image: str,
    colmap_version: str,
    executor: CommandExecutor,
    executable: str = PYCOLMAP_EXECUTABLE,
) -> PlaceAlignmentOutcome:
    """Jointly reconstruct two scenes and admit the candidate to the place, or refuse.

    ``repository`` rather than a bare scope, because the one ordering boundary between database
    rows and object-store bytes is :func:`exulanica.ingest.committed_store.committed_writes` and
    it takes one. The place tables are reached through
    :mod:`exulanica.ingest.spine.places` on a scope built from the same connection: the
    repository's method surface is the vocabulary the ingest STAGES speak, and widening it for a
    build that runs outside the pipeline, for a queue that does not exist yet, would be surface
    kept honest for nobody.

    Returns a :class:`PlaceAlignmentOutcome` for every measured result, refusals included.
    Raises :class:`PlaceAlignmentUnavailable` only when there was no measurement to report.
    """
    if candidate_scene_id == against_scene_id:
        # One scene reconstructed with itself fits perfectly and measures nothing, which is the
        # shape of a bug that would read as the best alignment in the table. 0038 refuses the
        # row; this refuses the run, before an hour of matching.
        raise PlaceAlignmentUnavailable("a place alignment is between two scenes, not one twice")

    scope = _scope(repository)
    spec = stage(PLACE_ALIGNMENT_STAGE)
    candidate_members = places.scene_members(scope, candidate_scene_id)
    against_members = places.scene_members(scope, against_scene_id)
    for scene_id, members in (
        (candidate_scene_id, candidate_members),
        (against_scene_id, against_members),
    ):
        if not members:
            raise PlaceAlignmentUnavailable(f"scene {scene_id} has no members to reconstruct")
        if places.scene_blocked(scope, scene_id):
            raise TombstonedError(f"scene {scene_id} was withdrawn")

    shared = {member.capture_id for member in candidate_members} & {
        member.capture_id for member in against_members
    }
    if shared:
        # The union would name one photograph twice, and the manifest refuses that outright. It
        # is also unanswerable on its own terms: one capture cannot be stamped with two origin
        # capture sets, so the connectivity check below would have nothing to decide.
        raise PlaceAlignmentUnavailable(
            f"{len(shared)} photographs belong to both scenes, so their union is not two sets"
        )

    union_member_digest = scene_member_digest(
        [member.capture_id for member in (*candidate_members, *against_members)]
    )
    policy_digest = sha256_of_canonical(PLACE_ALIGNMENT_POLICY)

    existing = places.find_alignment(
        scope,
        place_id=place_id,
        candidate_scene_id=candidate_scene_id,
        against_scene_id=against_scene_id,
        union_member_digest=union_member_digest,
        policy_digest=policy_digest,
    )
    if existing is not None:
        return _already_decided(scope, store, existing)

    against_version = places.version(scope, place_id=place_id, scene_id=against_scene_id)
    if against_version is None:
        raise PlaceAlignmentUnavailable(
            f"scene {against_scene_id} is not a version of place {place_id}, so there is no "
            "measured chain from it back to the anchor's frame"
        )
    bound = places.version_of_scene(scope, candidate_scene_id)
    if bound is not None:
        raise PlaceAlignmentUnavailable(
            f"scene {candidate_scene_id} already belongs to place {bound.place_id}"
        )

    candidate_receipt = _pose_receipt(scope, store, candidate_scene_id)
    against_receipt = _pose_receipt(scope, store, against_scene_id)

    candidate_frames, candidate_sources = _joint_frames(
        candidate_scene_id, candidate_members, candidate_scene_id, against_scene_id
    )
    against_frames, against_sources = _joint_frames(
        against_scene_id, against_members, candidate_scene_id, against_scene_id
    )
    frames = tuple(sorted((*candidate_frames, *against_frames), key=lambda item: item.filename))

    input_digest = input_digest_of([candidate_receipt.digest, against_receipt.digest])
    key = _place_alignment_key(
        place_id=place_id,
        candidate_scene_id=candidate_scene_id,
        against_scene_id=against_scene_id,
        union_member_digest=union_member_digest,
        stage_key=spec.key,
        stage_version=spec.version,
        params_digest=spec.params_digest,
        input_digest=input_digest,
    )
    existing_artifact = repository.find_artifact(key)
    receipt_artifact_id = (
        existing_artifact.artifact_id
        if existing_artifact is not None
        else artifact_id_for(key, workspace_id=repository.workspace_id)
    )

    manifest = PoseBuildManifest(
        scene_ref=f"place:{place_id}",
        code_revision=code_revision,
        colmap_version=colmap_version,
        execution_image=execution_image,
        frames=frames,
        # No quality thresholds, and this is a statement rather than an omission. The scene_pose
        # policy was calibrated against single-occasion captures to decide whether a SCENE is
        # publishable geometry, and the joint model here is never published: it is a build
        # intermediate whose only job is to place both capture sets in one frame. The
        # measurement that gates this build is the held-out residual inside
        # `fit_place_alignment`, and borrowing a threshold calibrated for another question would
        # be a policy claim nobody made.
        min_registered_fraction=None,
        max_mean_reprojection_error_px=None,
        min_camera_translation_units=None,
    )

    repository.register_stages(STAGES)
    ledger = Ledger.start_run(repository, trigger="manual")
    scratch_key = scene_scratch_key(repository.workspace_id, receipt_artifact_id)
    try:
        with (
            ledger.stage(
                spec,
                input_artifact_ids=[candidate_receipt.artifact_id, against_receipt.artifact_id],
            ) as recorder,
            active_scene_scratch(scratch_root, scratch_key) as job_directory,
        ):
            quality = _run_joint_reconstruction(
                scope,
                manifest,
                job_directory=job_directory,
                sources=(*candidate_sources, *against_sources),
                store=store,
                executable=executable,
                executor=executor,
                candidate_scene_id=candidate_scene_id,
                against_scene_id=against_scene_id,
            )
            outcome = _decide_and_record(
                repository,
                scope,
                store,
                quality=quality,
                place_id=place_id,
                candidate=_SceneSide(candidate_scene_id, candidate_receipt, candidate_frames),
                against=_SceneSide(against_scene_id, against_receipt, against_frames),
                against_version=against_version,
                union_member_digest=union_member_digest,
                policy_digest=policy_digest,
                frames=frames,
                receipt_artifact_id=receipt_artifact_id,
                idempotency_key=key,
                input_digest=input_digest,
                recorder_event=recorder.stage_started_event,
            )
            recorder.record_output(receipt_artifact_id)
    except BaseException:
        ledger.finish("failed")
        raise
    finally:
        # The union's original photographs were copied here. They leave with the run: there is
        # no lease to resume under, so a retained checkpoint would be sensitive bytes kept for a
        # process that is not coming back.
        cleanup_scene_scratch(scratch_root, scratch_key)
    ledger.finish("succeeded")
    return outcome


# -- the pieces -------------------------------------------------------------------------


def _scope(repository: IngestRepository) -> WorkspaceScope:
    """The declared-workspace handle the place tables are reached through.

    ``IngestRepository`` offers no public handle onto its own scope, by design, so this builds
    one over the same connection. It is not a way around the declaration: ``WorkspaceScope`` has
    no constructor that skips ``set_workspace``, so what comes out is scoped either way.
    """
    return WorkspaceScope(repository.connection, repository.workspace_id)


@dataclass(frozen=True, slots=True)
class _PoseReceipt:
    artifact_id: uuid.UUID
    digest: bytes
    #: capture_ref -> the camera centre this scene's own reconstruction recovered for it.
    centres: dict[str, tuple[float, float, float]]


@dataclass(frozen=True, slots=True)
class _SceneSide:
    scene_id: uuid.UUID
    receipt: _PoseReceipt
    frames: tuple[SourceFrame, ...]


def _pose_receipt(
    scope: WorkspaceScope, store: ContentAddressedStore, scene_id: uuid.UUID
) -> _PoseReceipt:
    """Read one scene's retained pose receipt and take its recovered camera centres.

    Both halves of every correspondence's scene side come from this one document: the receipt
    carries its exact build manifest, which maps an image name back to the ``capture_ref`` it was
    staged from, and ``camera_centre_xyz`` per registered photograph. Neither is recomputed here,
    because a recomputation would be a second answer to a question the receipt already answered
    under a digest.
    """
    row = places.retained_pose_receipt(scope, scene_id)
    if row is None:
        raise PlaceAlignmentUnavailable(
            f"scene {scene_id} has no retained pose receipt, so it contributes no camera "
            "correspondences and cannot be aligned to a place"
        )
    payload = store.get(BlobId(row.content_sha256))
    if len(payload) != row.byte_size:
        raise PlaceAlignmentUnavailable(
            f"the pose receipt of scene {scene_id} disagrees in size with its artifact row"
        )
    receipt = json.loads(payload)
    if receipt.get("profile") != _POSE_RECEIPT_PROFILE:
        raise PlaceAlignmentUnavailable(
            f"the pose receipt of scene {scene_id} carries an unsupported profile"
        )
    frames = receipt["manifest"]["frames"]
    quality = receipt["quality"]
    ref_by_name = {frame["filename"]: frame["capture_ref"] for frame in frames}
    registered = set(quality["registered_images"])
    centres: dict[str, tuple[float, float, float]] = {}
    for camera in quality["cameras"]:
        name = camera["image_name"]
        if name not in registered or name not in ref_by_name:
            continue
        centre = camera["camera_centre_xyz"]
        centres[ref_by_name[name]] = (float(centre[0]), float(centre[1]), float(centre[2]))
    return _PoseReceipt(row.artifact_id, row.content_sha256, centres)


def _joint_frames(
    scene_id: uuid.UUID,
    members: list[places.PlaceSceneMember],
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
) -> tuple[tuple[SourceFrame, ...], tuple[ScratchSource, ...]]:
    """One scene's photographs as frames of the JOINT manifest, stamped with their origin.

    ``capture_set`` is the scene the photograph came from, and that is the whole leverage of
    this build. ``pose.py`` already models several declared capture sets and already refuses a
    run whose sets do not all land in one connected model; the ingest layer stamps one constant
    on every frame, so that machinery has never decided anything. Here it decides whether two
    captures are of one place.

    Filenames are prefixed by the scene's position in the sorted pair rather than by the scene
    id, because two scenes number their own members from zero and the union has to keep them
    apart, while the manifest requires plain basenames. Sorting the pair rather than using the
    caller's argument order keeps the prefix a property of the two scenes.
    """
    order = sorted((candidate_scene_id, against_scene_id))
    side = order.index(scene_id)
    frames: list[SourceFrame] = []
    sources: list[ScratchSource] = []
    for member in members:
        extension = _EXTENSIONS.get(member.media_type)
        if extension is None:
            raise PlaceAlignmentUnavailable(
                f"a joint reconstruction does not support source media type {member.media_type!r}"
            )
        filename = f"{side}-{member.ordinal:06d}{extension}"
        frames.append(
            SourceFrame(
                capture_ref=str(member.capture_id),
                filename=filename,
                sha256=member.blob_id.hex,
                capture_set=str(scene_id),
            )
        )
        sources.append(ScratchSource(filename, member.blob_id))
    return tuple(frames), tuple(sources)


def _place_alignment_key(
    *,
    place_id: uuid.UUID,
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
    union_member_digest: bytes,
    stage_key: str,
    stage_version: int,
    params_digest: bytes,
    input_digest: bytes,
) -> str:
    """The receipt's identity key, with every field LENGTH-PREFIXED before it is hashed.

    Unframed concatenation of variable-length fields is not injective, and this repository has
    already paid for that once: version 1 of ``idempotency_key`` concatenated a stage key and a
    version so that ``("vision", 11)`` and ``("vision1", 1)`` hashed identically, and two stages
    could share one artifact row. Three uuids in a row look safe because uuids are fixed width,
    and that is exactly the reasoning ``exulanica/evidence/scene.py`` records as insufficient:
    injectivity that depends on every future field staying fixed width is injectivity waiting
    for the field that is not.
    """
    hasher = hashlib.sha256()
    for part in (
        b"exulanica/place-alignment-artifact-key",
        b"1",
        place_id.bytes,
        candidate_scene_id.bytes,
        against_scene_id.bytes,
        union_member_digest,
        stage_key.encode("utf-8"),
        str(stage_version).encode("ascii"),
        params_digest,
        input_digest,
    ):
        hasher.update(len(part).to_bytes(8, "big"))
        hasher.update(part)
    return hasher.hexdigest()


def _run_joint_reconstruction(
    scope: WorkspaceScope,
    manifest: PoseBuildManifest,
    *,
    job_directory: Path,
    sources: tuple[ScratchSource, ...],
    store: ContentAddressedStore,
    executable: str,
    executor: CommandExecutor,
    candidate_scene_id: uuid.UUID,
    against_scene_id: uuid.UUID,
) -> PoseQuality:
    source_directory = stage_scene_sources(store, job_directory, sources)

    def cancelled() -> bool:
        return places.scene_blocked(scope, candidate_scene_id) or places.scene_blocked(
            scope, against_scene_id
        )

    result = run_colmap_pose_job(
        manifest,
        source_dir=source_directory,
        jobs_root=job_directory / "joint",
        executable=executable,
        executor=executor,
        cancellation_check=cancelled,
    )
    if result.status == "cancelled":
        raise TombstonedError(
            result.failure_reason or "a source photograph was withdrawn during the joint run"
        )
    if result.status == "failed" or result.quality is None:
        # COLMAP did not finish, so nothing was measured. This is not one of the three refusals:
        # a crashed matcher is silent about whether the two captures share a place.
        raise PlaceAlignmentUnavailable(
            result.failure_reason or "the joint reconstruction produced no quality receipt"
        )
    return result.quality


def _decide_and_record(
    repository: IngestRepository,
    scope: WorkspaceScope,
    store: ContentAddressedStore,
    *,
    quality: PoseQuality,
    place_id: uuid.UUID,
    candidate: _SceneSide,
    against: _SceneSide,
    against_version: places.PlaceVersionRow,
    union_member_digest: bytes,
    policy_digest: bytes,
    frames: tuple[SourceFrame, ...],
    receipt_artifact_id: uuid.UUID,
    idempotency_key: str,
    input_digest: bytes,
    recorder_event: uuid.UUID,
) -> PlaceAlignmentOutcome:
    """Fit both scenes against the joint frame, compose, and write the verdict either way."""
    joint_centres = {
        camera.image_name: tuple(float(value) for value in camera.camera_centre_xyz)
        for camera in quality.cameras
    }
    # `jointly_coregistered` is the joint run's own verdict that BOTH declared capture sets have
    # registered images in one connected model. It is passed to the fitter as a separate input
    # rather than inferred from the residuals, because two disconnected components can each be
    # internally consistent and produce a flattering fit over whichever cameras are present.
    connected = quality.jointly_coregistered
    candidate_fit = _fit(candidate, joint_centres, connected=connected)
    against_fit = _fit(against, joint_centres, connected=connected)

    place_from_against, against_scale = _place_from_against(
        scope, store, place_id=place_id, version=against_version
    )
    frame_hops = against_version.frame_hops + 1

    reason = candidate_fit.reason or against_fit.reason
    accepted = candidate_fit.accepted and against_fit.accepted
    place_from_candidate: tuple[float, ...] | None = None
    candidate_units_to_place_units: float | None = None
    if accepted:
        assert candidate_fit.joint_from_scene_row_major is not None
        assert against_fit.joint_from_scene_row_major is not None
        assert candidate_fit.scene_units_to_joint_units is not None
        assert against_fit.scene_units_to_joint_units is not None
        place_from_candidate = _multiply(
            place_from_against,
            _multiply(
                _inverse_similarity(against_fit.joint_from_scene_row_major),
                candidate_fit.joint_from_scene_row_major,
            ),
        )
        # The composed scale, stated rather than re-extracted from the matrix above. Every
        # factor is a similarity, so the scales multiply: the candidate's own units reach the
        # joint frame, the inverse takes them into the against scene's units, and the against
        # scene's place transform takes them the rest of the way.
        candidate_units_to_place_units = (
            against_scale
            * candidate_fit.scene_units_to_joint_units
            / against_fit.scene_units_to_joint_units
        )

    payload = {
        "profile": PLACE_ALIGNMENT_RECEIPT_PROFILE,
        "place_id": str(place_id),
        "candidate_scene_id": str(candidate.scene_id),
        "against_scene_id": str(against.scene_id),
        "policy": PLACE_ALIGNMENT_POLICY,
        "policy_sha256": policy_digest.hex(),
        "union": {
            "member_digest": union_member_digest.hex(),
            "frames": [frame.as_payload() for frame in frames],
        },
        "joint_model_sha256": _joint_model_digest(quality),
        "fits": {
            "candidate": _fit_block(candidate_fit),
            "against": _fit_block(against_fit),
        },
        "place_from_candidate_row_major": (
            None if place_from_candidate is None else list(place_from_candidate)
        ),
        "candidate_units_to_place_units": candidate_units_to_place_units,
        "frame_hops": frame_hops,
        "accepted": accepted,
        "reason": reason,
        # Both frames are recovered COLMAP frames. Nothing here is metric and no later reader may
        # read it as such; the field is written on every receipt so its absence can never be
        # mistaken for a claim.
        "physically_validated": False,
    }
    receipt_bytes = _receipt_bytes(payload)
    content_id = BlobId.of_bytes(receipt_bytes)
    # Derived from the receipt's own identity key rather than allocated, so a run that wrote the
    # artifact and died before the verdict row writes the same alignment id on its retry instead
    # of a second one beside the first.
    alignment_id = uuid.uuid5(receipt_artifact_id, "exulanica/place-alignment-row")

    spec = stage(PLACE_ALIGNMENT_STAGE)
    started_at = places.earliest_capture_time(scope, candidate.scene_id)
    with committed_writes(repository, store) as pending:
        inserted = places.insert_place_artifact(
            scope,
            artifact_id=receipt_artifact_id,
            kind=spec.output_kind,
            place_id=place_id,
            stage_key=spec.key,
            stage_version=spec.version,
            params_digest=spec.params_digest,
            input_digest=input_digest,
            idempotency_key=idempotency_key,
            content_sha256=content_id.digest,
            storage_key=store.key_for(content_id),
            byte_size=len(receipt_bytes),
            produced_by_event=recorder_event,
        )
        if not inserted and places.artifact_content_sha256(scope, receipt_artifact_id) != (
            content_id.digest
        ):
            # A receipt under this identity key already exists and says something else. The row
            # is never rewritten to point at the new bytes: the key names the old content, and
            # quietly redefining what it names would make the transform every later composition
            # reads wrong without saying so.
            raise ValueError("an existing place alignment receipt disagrees with recomputed bytes")
        places.insert_alignment(
            scope,
            alignment_id=alignment_id,
            place_id=place_id,
            candidate_scene_id=candidate.scene_id,
            against_scene_id=against.scene_id,
            union_member_digest=union_member_digest,
            policy_digest=policy_digest,
            joint_model_sha256=_joint_model_bytes(quality),
            accepted=accepted,
            reason=reason,
            receipt_artifact_id=receipt_artifact_id,
        )
        if accepted:
            places.insert_version(
                scope,
                place_id=place_id,
                scene_id=candidate.scene_id,
                # One past the highest ordinal the place holds. `place_version` is append-only,
                # so an already-bound version cannot be renumbered to make room for an older
                # capture arriving later; the ordinal is therefore bind order, and
                # `ordered_by_utc` beside it is the recorded capture time a reader compares.
                # Binding in capture order makes the two agree, which is the ordinary case.
                ordinal=places.next_ordinal(scope, place_id=place_id),
                ordered_by_utc=started_at,
                ordered_by_basis="capture_exif" if started_at is not None else "unavailable",
                frame_hops=frame_hops,
                admitted_by_alignment_id=alignment_id,
            )
        pending.append(receipt_bytes)

    return PlaceAlignmentOutcome(
        place_id=place_id,
        candidate_scene_id=candidate.scene_id,
        against_scene_id=against.scene_id,
        alignment_id=alignment_id,
        receipt_artifact_id=receipt_artifact_id,
        accepted=accepted,
        reason=reason,
        frame_hops=frame_hops if accepted else None,
        reused=False,
    )


def _fit(
    side: _SceneSide,
    joint_centres: dict[str, tuple[float, ...]],
    *,
    connected: bool,
) -> PlaceAlignmentResult:
    """One scene's cameras, located twice, fitted into the joint frame.

    A photograph contributes a correspondence only when BOTH reconstructions recovered it. A
    photograph the joint run failed to register has no joint position, and inventing one from
    its neighbours would be manufacturing the measurement the residual exists to test.
    """
    correspondences = [
        PlaceCorrespondence(
            capture_ref=frame.capture_ref,
            scene_xyz=side.receipt.centres[frame.capture_ref],
            joint_xyz=joint_centres[frame.filename],  # type: ignore[arg-type]
        )
        for frame in side.frames
        if frame.capture_ref in side.receipt.centres and frame.filename in joint_centres
    ]
    return fit_place_alignment(correspondences, connected=connected)


def _fit_block(result: PlaceAlignmentResult) -> dict[str, Any]:
    return {
        "accepted": result.accepted,
        "reason": result.reason,
        "joint_from_scene_row_major": (
            None
            if result.joint_from_scene_row_major is None
            else list(result.joint_from_scene_row_major)
        ),
        "scene_units_to_joint_units": result.scene_units_to_joint_units,
        "diagnostics": result.diagnostics,
        "training_count": result.diagnostics.get("training_correspondences"),
        "validation_count": result.diagnostics.get("validation_correspondences"),
    }


def _place_from_against(
    scope: WorkspaceScope,
    store: ContentAddressedStore,
    *,
    place_id: uuid.UUID,
    version: places.PlaceVersionRow,
) -> tuple[tuple[float, ...], float]:
    """The transform taking the against scene's frame into the place's, and its scale.

    Identity for the anchor, because the place's frame IS the anchor's recovered frame. For any
    other version it is read back off the receipt that admitted it, because ``place_version``
    records no transform on purpose: 0038 keeps measured numbers in digest-bound artifacts
    rather than in columns nothing recomputes. Reading it here is what makes a two-hop
    composition a composition of two measurements rather than of one measurement and a guess.
    """
    if version.frame_hops == 0:
        return _IDENTITY, 1.0
    if version.admitted_by_alignment_id is None:
        raise PlaceAlignmentUnavailable(
            f"version {version.scene_id} of place {place_id} has hops and no admitting alignment"
        )
    admitting = places.alignment(scope, version.admitted_by_alignment_id)
    if admitting is None or not admitting.accepted:
        raise PlaceAlignmentUnavailable(
            f"the alignment that admitted scene {version.scene_id} is missing or refused"
        )
    digest = places.artifact_content_sha256(scope, admitting.receipt_artifact_id)
    if digest is None:
        raise PlaceAlignmentUnavailable(
            f"the receipt that admitted scene {version.scene_id} is no longer readable"
        )
    receipt = json.loads(store.get(BlobId(digest)))
    if receipt.get("profile") != PLACE_ALIGNMENT_RECEIPT_PROFILE:
        raise PlaceAlignmentUnavailable(
            "an admitting place-alignment receipt carries a foreign profile"
        )
    matrix = receipt.get("place_from_candidate_row_major")
    scale = receipt.get("candidate_units_to_place_units")
    if not isinstance(matrix, list) or len(matrix) != 16 or scale is None:
        raise PlaceAlignmentUnavailable(
            f"the receipt that admitted scene {version.scene_id} carries no place transform"
        )
    return tuple(float(value) for value in matrix), float(scale)


def _already_decided(
    scope: WorkspaceScope,
    store: ContentAddressedStore,
    existing: places.PlaceAlignmentRow,
) -> PlaceAlignmentOutcome:
    """Report the verdict already on record, without running a second reconstruction.

    0038's unique key over (workspace, place, candidate, against, union member digest, policy
    digest) says one build over one union under one policy has one answer. Re-running would
    spend forty-five minutes to reach a row the database would refuse to write, and the second
    run's numbers would differ from the first's in the last digits, which would look like a
    disagreement about the world rather than about a mapper's threading.
    """
    digest = places.artifact_content_sha256(scope, existing.receipt_artifact_id)
    if digest is None or not store.exists(BlobId(digest)):
        # The row names bytes the store no longer holds. Said out loud rather than absorbed: the
        # receipt is the only place the fitted transform lives, and re-deriving it needs the
        # joint run this call has just declined to repeat.
        raise PlaceAlignmentUnavailable(
            f"place alignment {existing.alignment_id} names a receipt whose bytes are absent"
        )
    version = places.version(
        scope, place_id=existing.place_id, scene_id=existing.candidate_scene_id
    )
    return PlaceAlignmentOutcome(
        place_id=existing.place_id,
        candidate_scene_id=existing.candidate_scene_id,
        against_scene_id=existing.against_scene_id,
        alignment_id=existing.alignment_id,
        receipt_artifact_id=existing.receipt_artifact_id,
        accepted=existing.accepted,
        reason=existing.reason,
        frame_hops=None if version is None else version.frame_hops,
        reused=True,
    )


def _receipt_bytes(payload: dict[str, Any]) -> bytes:
    """Sorted keys, no whitespace, trailing newline: exactly what ``pose.py`` writes.

    Not ``canonical_json``, which refuses floats outright. That rule guards DIGEST INPUTS, and a
    receipt is an artifact whose own content hash is taken over whatever bytes it holds; the
    pose receipt already carries ordinary JSON numbers for the same reason. The read seam that
    publishes any of this to a client converts to fixed-precision decimal strings through
    ``exulanica/graph/wire_numbers.py``, the way every other graph payload does.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _joint_model_digest(quality: PoseQuality) -> str | None:
    digest = _joint_model_bytes(quality)
    return None if digest is None else digest.hex()


def _joint_model_bytes(quality: PoseQuality) -> bytes | None:
    """A digest over the connected joint model's own files, or None when there was none.

    The model itself is not retained. It is a third frame that no scene is addressed in, and
    promoting it to citable geometry would put a place's history in a frame nothing else can
    resolve. The digest keeps the fit checkable against a re-run without keeping the frame.
    """
    if quality.connected_model is None:
        return None
    prefix = f"{quality.connected_model}/"
    entries = [
        {"path": path, "sha256": digest, "byte_length": size}
        for path, digest, size in quality.artifact_inventory
        if path.startswith(prefix)
    ]
    return sha256_of_canonical(entries) if entries else None


def _multiply(left: tuple[float, ...], right: tuple[float, ...]) -> tuple[float, ...]:
    return tuple(
        sum(left[row * 4 + k] * right[k * 4 + column] for k in range(4))
        for row in range(4)
        for column in range(4)
    )


def _inverse_similarity(matrix: tuple[float, ...]) -> tuple[float, ...]:
    """Invert a similarity exactly, refusing anything that is not one.

    ``fit_place_alignment`` only ever returns a positive scale times a proper rotation, with a
    reflection guard on the way, so the inverse is ``R^T / s`` and never needs a general 4x4
    solve. The check is not ceremony: a general inverse would happily invert a sheared matrix
    and hand back a transform that deforms the world, which is the exact failure the fitter
    refuses an affine to avoid. If this ever fires, something upstream stopped returning a
    similarity, and that is a defect rather than a measurement.
    """
    linear = [[matrix[row * 4 + column] for column in range(3)] for row in range(3)]
    translation = [matrix[row * 4 + 3] for row in range(3)]
    scale_squared = sum(value * value for value in linear[0])
    if scale_squared <= 0:
        raise ValueError("a place alignment transform has no positive scale")
    for row in range(3):
        if not math.isclose(
            sum(value * value for value in linear[row]), scale_squared, rel_tol=1e-9
        ):
            raise ValueError("a place alignment transform is not a uniform-scale similarity")
        for other in range(row + 1, 3):
            dot = sum(linear[row][k] * linear[other][k] for k in range(3))
            if abs(dot) > scale_squared * 1e-9:
                raise ValueError("a place alignment transform is not a uniform-scale similarity")
    inverse_linear = [
        [linear[column][row] / scale_squared for column in range(3)] for row in range(3)
    ]
    inverse_translation = [
        -sum(inverse_linear[row][k] * translation[k] for k in range(3)) for row in range(3)
    ]
    return (
        *inverse_linear[0],
        inverse_translation[0],
        *inverse_linear[1],
        inverse_translation[1],
        *inverse_linear[2],
        inverse_translation[2],
        0.0,
        0.0,
        0.0,
        1.0,
    )
