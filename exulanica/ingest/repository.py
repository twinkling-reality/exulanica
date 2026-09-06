"""The vocabulary the ingest path speaks to the database.

This class used to be the vocabulary *and* the SQL: 730 lines, every statement the photograph
path sends to the spine. The statements now live in :mod:`exulanica.ingest.spine`, one module per
table's worth of queries, and what is left here is the sentence each stage says. That division
is the whole of the change, and it is worth saying which half is which:

*   **A method here is a thing the ingest path does.** ``lock_stored_object``,
    ``refuse_ingest_if_tombstoned``, ``upsert_span``. The stages read as prose because these
    names are prose, and ``orimera/ingest/stages/writes.py`` declares this class as the complete
    surface a stage may reach for. A stage never sees a
    :class:`~exulanica.ingest.spine.scope.WorkspaceScope`, so that declaration stays exhaustive.
*   **A function in the spine is a table.** Which columns, which conflict clause, which guard
    the write goes through. A question about ``artifact`` is answered by opening one file.

**No caller lost its route in the move.** Every method with a call site is still here, and the
two names that went were counted first: ``span_address_columns`` and ``vision_payloads_by_blob``
had no caller anywhere in ``orimera/`` or ``tests/``, and this repository does not keep a path
for a caller that does not exist. ``count`` was renamed to ``rows_in_schema`` because it never
counted a workspace; see :mod:`exulanica.ingest.spine.counts`.

What the move did **not** change, because each of these is load bearing:

*   **The tombstone guard is a trigger inside the writing transaction.**
    ``tombstone_blocks_span()`` is called by ``tg_tombstone_guard_span`` and friends on the same
    row being written, and it is VOLATILE so it takes a fresh snapshot rather than reusing the
    statement's. The application check that remains, :meth:`refuse_ingest_if_tombstoned`, is not
    a duplicate of it: it runs **before any bytes reach the object store**, which is the one
    thing a trigger cannot do, because the store is not in the transaction.
*   **Row-level security is real.** Six of the ten tables the spine writes are in migration
    0001's FORCE list, keyed on ``current_workspace()``: ``capture``, ``evidence_span``,
    ``artifact``, ``occurrence``, ``derived_artifact`` and ``tombstone``. The four that are not
    are ``stage_registry``, ``blob``, ``media_track`` and ``clock_anchor``, none of which has a
    ``workspace_id`` column, because a stage's version and a container's dimensions are facts
    about a deployment and a file rather than about one person's corpus. The docstring this
    replaced listed three of those four and quietly dropped ``stage_registry``. The connection
    must still have declared a workspace, and
    :class:`~exulanica.ingest.spine.scope.WorkspaceScope` is now the only way a spine module can be
    handed one that has.
*   **``predicate.allows_kind`` is enforced by the database.** Assertions are delegated to
    :class:`~exulanica.epistemics.assertions.AssertionWriter` rather than reimplemented, because
    the identity path writes the ``kind='user'`` naming assertion too and two implementations of
    "insert an assertion" would be two places for the rule to drift.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from typing import Any

import psycopg

from exulanica.epistemics.assertions import AssertionWriter
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.ingest.spine import (
    artifacts,
    blobs,
    captures,
    counts,
    derived,
    inferences,
    occurrences,
    person_consent,
    privacy,
    reconstruction_jobs,
    reconstruction_scenes,
    spans,
    stage_registry,
    tombstones,
    tracks,
)
from exulanica.ingest.spine.artifacts import ArtifactRow
from exulanica.ingest.spine.captures import CaptureRow
from exulanica.ingest.spine.scope import WorkspaceScope

__all__ = ["IngestRepository"]


class IngestRepository:
    """Everything the ingest path reads and writes, in the words the ingest path uses."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        self._scope = WorkspaceScope(connection, workspace_id)
        self.workspace_id = workspace_id
        # The connection is now declared TWICE, here and inside AssertionWriter, and that is a
        # measured fact rather than a suspicion: AssertionWriter.__init__ calls set_workspace on
        # the same connection. Deleting either call therefore leaves the connection scoped, so
        # neither one can be shown to be load bearing by removing it and watching a test fail.
        # Both stay: the writer is constructed directly by orimera.identity on connections that
        # never see a repository, and the scope is what makes a spine module unreachable with an
        # undeclared connection. The rule that holds the second sentence is structural, not
        # behavioural; test_every_spine_function_takes_a_workspace_scope is where it lives.
        self._assertions = AssertionWriter(connection, workspace_id)

    @property
    def assertions(self) -> AssertionWriter:
        """The shared assertion writer, for callers that need more than ``insert_assertion``.

        ``tests/test_value_schema.py`` is that caller three times over: it drives ``insert``
        directly to probe the value-schema refusals, which ``insert_assertion`` does not expose a
        route to.
        """
        return self._assertions

    # No public handle onto the WorkspaceScope. One was offered and nothing wanted it: a spine
    # module is reached through the methods below, never by a caller assembling its own call, and
    # a property with no caller is surface to keep honest for nobody.

    @property
    def connection(self) -> psycopg.Connection:
        """The live connection. The ledger writes through it, inside the same transaction."""
        return self._scope.connection

    def register_stages(self, specs: Mapping[str, Any]) -> None:
        """Record the stage registry, so the ledger can be read without the source code."""
        stage_registry.register(self._scope, specs)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        """One stage's writes land together or not at all.

        This is half of the producer protocol: the artifact row, its assertions and its ledger
        event share a transaction, and every emitted row carries a deterministic emit key under
        a unique constraint. A worker that dies halfway and is retried produces the same keys,
        the conflicts absorb the duplicates, and the effect is exactly once on top of
        at-least-once execution.
        """
        with self._scope.connection.transaction():
            yield self._scope.connection

    # -- media layer --------------------------------------------------------------------

    def lock_stored_object(self, blob_id: BlobId) -> None:
        """Take the transaction lock over one stored object, keyed on its content hash.

        The same lock ``exulanica.deletion`` takes before it destroys an object, and both sides
        have to take it or neither is serialised. See :mod:`exulanica.ingest.spine.blobs` for the
        measured interleaving that made it necessary.
        """
        blobs.lock_stored_object(self._scope, blob_id)

    def locked_stored_objects(self, blob_ids: list[BlobId]) -> AbstractContextManager[None]:
        """Hold purge-compatible locks across a post-commit object-store flush."""
        return blobs.locked_stored_objects(self._scope, blob_ids)

    def upsert_blob(
        self, blob_id: BlobId, *, byte_size: int, media_type: str, storage_key: str
    ) -> bool:
        """Register bytes. Returns True when the database had not seen them before."""
        return blobs.upsert(
            self._scope,
            blob_id,
            byte_size=byte_size,
            media_type=media_type,
            storage_key=storage_key,
        )

    def live_capture_for_blob(self, blob_id: BlobId) -> CaptureRow | None:
        """The live capture this workspace holds for these bytes, or None."""
        return captures.live_for_blob(self._scope, blob_id)

    def capture(self, capture_id: uuid.UUID) -> CaptureRow | None:
        """One capture by id, deleted or not, or None when this workspace has no such row.

        Deliberately not filtered on ``deleted_at``; :func:`exulanica.ingest.spine.captures.by_id`
        carries the reason, which is that a lookup miss and a deletion lead to different run
        outcomes.
        """
        return captures.by_id(self._scope, capture_id)

    def insert_capture(
        self, blob_id: BlobId, *, device_id: str | None, started_at: str | None
    ) -> CaptureRow:
        """Register that this workspace holds these bytes."""
        return captures.insert(self._scope, blob_id, device_id=device_id, started_at=started_at)

    def upsert_image_track(
        self,
        blob_id: BlobId,
        *,
        coded_w: int,
        coded_h: int,
        disp_w: int,
        disp_h: int,
        rotation: int,
        codec: str,
        probe_json: dict[str, Any],
    ) -> uuid.UUID:
        """Register the single-sample ``img`` track a photograph is modelled as."""
        return tracks.upsert_image(
            self._scope,
            blob_id,
            coded_w=coded_w,
            coded_h=coded_h,
            disp_w=disp_w,
            disp_h=disp_h,
            rotation=rotation,
            codec=codec,
            probe_json=probe_json,
        )

    def insert_clock_anchor(
        self, track_id: uuid.UUID, *, utc_instant: str, source: str, uncertainty_ms: int
    ) -> None:
        """Pin ``t_ns = 0`` on this track to a wall-clock instant."""
        tracks.insert_clock_anchor(
            self._scope,
            track_id,
            utc_instant=utc_instant,
            source=source,
            uncertainty_ms=uncertainty_ms,
        )

    # -- the spine ----------------------------------------------------------------------

    def upsert_span(self, address: EvidenceAddress) -> uuid.UUID:
        """Persist an address, or return the id of the identical one already stored."""
        return spans.upsert(self._scope, address)

    def reconstruction_scene_members(
        self, scene_id: uuid.UUID, *, job_id: uuid.UUID | None = None
    ) -> list[reconstruction_scenes.ReconstructionSceneMemberRow]:
        """The photographs a reconstruction scene was run over, in its recorded order."""
        return reconstruction_scenes.members(self._scope, scene_id, job_id=job_id)

    def insert_completed_reconstruction_scene(
        self,
        *,
        scene_id: uuid.UUID,
        member_digest: bytes,
        scene_members: list[tuple[uuid.UUID, bool]],
        job_id: uuid.UUID | None = None,
    ) -> bool:
        """Record a completed scene and every registration outcome in one transaction."""
        return reconstruction_scenes.insert_completed(
            self._scope,
            scene_id=scene_id,
            member_digest=member_digest,
            scene_members=scene_members,
            job_id=job_id,
        )

    def enqueue_reconstruction_scene(
        self,
        *,
        capture_ids: list[uuid.UUID],
        selection_policy: dict[str, Any],
        privacy_admission_id: uuid.UUID,
        privacy_admission_digest: bytes,
        build_inputs: dict[str, Any] | None = None,
    ) -> tuple[uuid.UUID, bool]:
        """Queue one exact, policy-described capture set for pose recovery."""
        return reconstruction_jobs.enqueue(
            self._scope,
            capture_ids=capture_ids,
            selection_policy=selection_policy,
            privacy_admission_id=privacy_admission_id,
            privacy_admission_digest=privacy_admission_digest,
            build_inputs=build_inputs,
        )

    def claim_reconstruction_scene(
        self,
        *,
        worker: str,
        lease_seconds: float,
        job_ids: frozenset[uuid.UUID] | None = None,
    ) -> reconstruction_jobs.ClaimedSceneJob | None:
        """Claim the next pending scene build for this workspace, or one of the named jobs."""
        return reconstruction_jobs.claim(
            self._scope, worker=worker, lease_seconds=lease_seconds, job_ids=job_ids
        )

    def active_reconstruction_scratch_keys(self) -> frozenset[str]:
        """Scratch that a queued, held or retryable scene job may still resume."""
        return reconstruction_jobs.active_scratch_keys(self._scope)

    def expire_exhausted_reconstruction_scenes(self) -> int:
        """Terminalize final claims whose worker died after its lease expired."""
        return reconstruction_jobs.expire_exhausted(self._scope)

    def heartbeat_reconstruction_scene(
        self, *, job_id: uuid.UUID, claim_token: uuid.UUID, lease_seconds: float
    ) -> bool:
        """Renew a scene-build lease still owned by this claimant."""
        return reconstruction_jobs.heartbeat(
            self._scope,
            job_id=job_id,
            claim_token=claim_token,
            lease_seconds=lease_seconds,
        )

    def reconstruction_scene_cancelled_or_lost(
        self, *, job_id: uuid.UUID, claim_token: uuid.UUID
    ) -> bool:
        """Whether deletion or a reclaim means this worker must stop."""
        return reconstruction_jobs.cancelled_or_lost(
            self._scope, job_id=job_id, claim_token=claim_token
        )

    def complete_reconstruction_scene_job(
        self,
        *,
        job_id: uuid.UUID,
        claim_token: uuid.UUID,
        scratch_key: str,
        pose_manifest_digest: bytes,
        pose_receipt_artifact_id: uuid.UUID,
        placement_artifact_id: uuid.UUID,
        gate_artifact_id: uuid.UUID,
        rung_assertion_id: uuid.UUID,
    ) -> bool:
        """Close a scene job after its scene, receipts and assertion are durable."""
        return reconstruction_jobs.complete(
            self._scope,
            job_id=job_id,
            claim_token=claim_token,
            scratch_key=scratch_key,
            pose_manifest_digest=pose_manifest_digest,
            pose_receipt_artifact_id=pose_receipt_artifact_id,
            placement_artifact_id=placement_artifact_id,
            gate_artifact_id=gate_artifact_id,
            rung_assertion_id=rung_assertion_id,
        )

    def release_checkpointed_reconstruction_scene(
        self,
        *,
        job_id: uuid.UUID,
        claim_token: uuid.UUID,
        retry_delay_seconds: float,
    ) -> bool:
        """Release durable training progress without counting a graceful stop as failure."""
        return reconstruction_jobs.release_checkpointed(
            self._scope,
            job_id=job_id,
            claim_token=claim_token,
            retry_delay_seconds=retry_delay_seconds,
        )

    def fail_reconstruction_scene_job(
        self,
        *,
        job_id: uuid.UUID,
        claim_token: uuid.UUID,
        failure_class: str,
        failure_message: str,
        retry_delay_seconds: float,
    ) -> bool:
        """Release a failed scene build for bounded retry."""
        return reconstruction_jobs.fail(
            self._scope,
            job_id=job_id,
            claim_token=claim_token,
            failure_class=failure_class,
            failure_message=failure_message,
            retry_delay_seconds=retry_delay_seconds,
        )

    # -- reconstruction privacy ---------------------------------------------------------

    def insert_reconstruction_authorization(
        self, **values: Any
    ) -> privacy.ReconstructionAuthorizationRow:
        """Persist why exact capture bytes may be used for reconstruction."""
        return privacy.insert_authorization(self._scope, **values)

    def reconstruction_authorization(
        self, authorization_id: uuid.UUID
    ) -> privacy.ReconstructionAuthorizationRow | None:
        """Read one exact-source reconstruction authorization."""
        return privacy.authorization(self._scope, authorization_id)

    def insert_privacy_screening(self, **values: Any) -> privacy.PrivacyScreeningRow:
        """Persist one immutable fail-closed screening result."""
        return privacy.insert_screening(self._scope, **values)

    def privacy_screening(self, screening_id: uuid.UUID) -> privacy.PrivacyScreeningRow | None:
        """Read one screening and its corpus classification."""
        return privacy.screening(self._scope, screening_id)

    def privacy_screening_allows(self, capture_id: uuid.UUID, screening_id: uuid.UUID) -> bool:
        """Whether this exact current source remains eligible for geometry."""
        return privacy.screening_allows(self._scope, capture_id, screening_id)

    def latest_privacy_screening(self, capture_id: uuid.UUID) -> privacy.PrivacyScreeningRow | None:
        """Resolve the newest current eligible receipt for exact capture bytes."""
        return privacy.latest_screening(self._scope, capture_id)

    def insert_privacy_admission(self, **values: Any) -> privacy.PrivacyAdmissionRow:
        """Persist one decision over an exact ordered capture set."""
        return privacy.admit(self._scope, **values)

    def insert_person_subject(self, **values: Any) -> uuid.UUID:
        """Create a person, named or not, as somebody a decision can be about."""
        return person_consent.insert_subject(self._scope, **values)

    def next_person_region_sequence(self, **values: Any) -> int:
        """The next edit number for one region, allocated in the writing transaction."""
        return person_consent.next_region_sequence(self._scope, **values)

    def insert_person_region_edit(self, **values: Any) -> uuid.UUID:
        """Append one immutable edit to one region's history."""
        return person_consent.insert_region_edit(self._scope, **values)

    def current_person_regions(
        self, *, capture_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, list[person_consent.PersonRegionRow]]:
        """Every live region on these photographs, deleted ones excluded."""
        return person_consent.current_regions(self._scope, capture_ids=capture_ids)

    def next_person_consent_sequence(self, **values: Any) -> int:
        """The next number in one consent chain."""
        return person_consent.next_consent_sequence(self._scope, **values)

    def insert_person_consent(self, **values: Any) -> uuid.UUID:
        """Append one immutable consent transition."""
        return person_consent.insert_consent(self._scope, **values)

    def person_consent_transitions(
        self, *, subject_id: uuid.UUID
    ) -> list[person_consent.ConsentTransitionRow]:
        """The whole recorded chain for one person, for the caller to fold."""
        return person_consent.consent_transitions(self._scope, subject_id=subject_id)

    # -- tombstones ---------------------------------------------------------------------

    def insert_tombstone(
        self,
        *,
        scope: str,
        requested_by: uuid.UUID,
        capture_id: uuid.UUID | None = None,
        track_key: str | None = None,
        interval_ns: Sequence[tuple[int, int]] | None = None,
        entity_id: uuid.UUID | None = None,
        assertion_id: uuid.UUID | None = None,
        reason: str | None = None,
        blocklist_hash: bool = False,
    ) -> uuid.UUID:
        """Record a deletion request. ``scope`` is the tombstone's own scope column."""
        return tombstones.insert(
            self._scope,
            scope_name=scope,
            requested_by=requested_by,
            capture_id=capture_id,
            track_key=track_key,
            interval_ns=interval_ns,
            entity_id=entity_id,
            assertion_id=assertion_id,
            reason=reason,
            blocklist_hash=blocklist_hash,
        )

    def tombstone_blocks(
        self,
        blob_id: BlobId,
        track_key: str,
        t_start_ns: int,
        t_end_ns: int,
        *,
        assume_live_capture: bool = False,
    ) -> bool:
        """Ask the database the same question its own write guards ask."""
        return tombstones.blocks(
            self._scope,
            blob_id,
            track_key,
            t_start_ns,
            t_end_ns,
            assume_live_capture=assume_live_capture,
        )

    def refuse_ingest_if_tombstoned(self, address: EvidenceAddress) -> None:
        """The admission check an ingest runs before it writes a single byte anywhere.

        Ordering, not duplication: the trigger inside the writing transaction closes the race,
        and this keeps the object store clean when there is no race, which is every other time.
        """
        tombstones.refuse_ingest_if_tombstoned(self._scope, address)

    # -- derivatives --------------------------------------------------------------------

    def find_artifact(self, idempotency_key: str) -> ArtifactRow | None:
        """The live artifact under this identity key, or None."""
        return artifacts.find(self._scope, idempotency_key)

    def current_capture_artifacts(
        self, *, capture_ids: list[uuid.UUID], kind: str
    ) -> dict[uuid.UUID, artifacts.CaptureArtifactRow]:
        """Resolve current complete per-capture artifacts for a scene producer."""
        return artifacts.current_for_captures(self._scope, capture_ids=capture_ids, kind=kind)

    def exact_capture_artifacts(
        self,
        *,
        artifact_ids_by_capture: dict[uuid.UUID, uuid.UUID],
        kind: str,
    ) -> dict[uuid.UUID, artifacts.CaptureArtifactRow]:
        """Resolve the exact immutable per-capture artifacts bound into a scene job."""
        return artifacts.exact_for_captures(
            self._scope,
            artifact_ids_by_capture=artifact_ids_by_capture,
            kind=kind,
        )

    def insert_artifact(
        self,
        *,
        artifact_id: uuid.UUID,
        kind: str,
        source_blob: BlobId,
        stage_key: str,
        stage_version: int,
        params_digest: bytes,
        input_digest: bytes,
        idempotency_key: str,
        content_sha256: bytes,
        storage_key: str,
        byte_size: int,
        produced_by_event: uuid.UUID | None,
        privacy_screening_id: uuid.UUID | None = None,
        read_source_sha256: bytes | None = None,
    ) -> bool:
        """Insert a derivative. Returns False when another worker already produced it."""
        return artifacts.insert(
            self._scope,
            artifact_id=artifact_id,
            kind=kind,
            source_blob=source_blob,
            stage_key=stage_key,
            stage_version=stage_version,
            params_digest=params_digest,
            input_digest=input_digest,
            idempotency_key=idempotency_key,
            content_sha256=content_sha256,
            storage_key=storage_key,
            byte_size=byte_size,
            produced_by_event=produced_by_event,
            privacy_screening_id=privacy_screening_id,
            read_source_sha256=read_source_sha256,
        )

    def insert_scene_artifact(
        self,
        *,
        artifact_id: uuid.UUID,
        kind: str,
        scene_id: uuid.UUID,
        stage_key: str,
        stage_version: int,
        params_digest: bytes,
        input_digest: bytes,
        idempotency_key: str,
        content_sha256: bytes,
        storage_key: str,
        byte_size: int,
        produced_by_event: uuid.UUID | None,
    ) -> bool:
        """Insert an artifact whose subject is a reconstruction scene."""
        return artifacts.insert_scene(
            self._scope,
            artifact_id=artifact_id,
            kind=kind,
            scene_id=scene_id,
            stage_key=stage_key,
            stage_version=stage_version,
            params_digest=params_digest,
            input_digest=input_digest,
            idempotency_key=idempotency_key,
            content_sha256=content_sha256,
            storage_key=storage_key,
            byte_size=byte_size,
            produced_by_event=produced_by_event,
        )

    def mark_artifact_needs_repair(self, artifact_id: uuid.UUID) -> None:
        """Flag an artifact whose bytes are gone and cannot be reproduced."""
        artifacts.mark_needs_repair(self._scope, artifact_id)

    # -- epistemics ---------------------------------------------------------------------
    #
    # Delegated rather than reimplemented, and to orimera.epistemics rather than to the spine.
    # The identity path writes the kind='user' naming assertion that entity.display_name depends
    # on, and it must not reach through this class to do it: two implementations of "insert an
    # assertion" would be two places for the support-span rule and the allows-kind check to
    # drift.

    def predicate_id(self, key: str) -> int:
        """The vocabulary id for a predicate key."""
        return self._assertions.predicate_id(key)

    def insert_assertion(
        self,
        *,
        kind: str,
        predicate_key: str,
        subject_ref: dict[str, Any],
        emit_key: str,
        support_span_ids: Sequence[uuid.UUID],
        object_value: Any = None,
        object_ref: dict[str, Any] | None = None,
        produced_by_run: uuid.UUID | None = None,
        stated_by_user: uuid.UUID | None = None,
        external_source: dict[str, Any] | None = None,
        raw_score: float | None = None,
        valid_time: str | None = None,
    ) -> uuid.UUID | None:
        """Write one claim. Returns None when this ``emit_key`` was already emitted."""
        return self._assertions.insert(
            kind=kind,
            predicate_key=predicate_key,
            subject_ref=subject_ref,
            emit_key=emit_key,
            support_span_ids=support_span_ids,
            object_value=object_value,
            object_ref=object_ref,
            produced_by_run=produced_by_run,
            stated_by_user=stated_by_user,
            external_source=external_source,
            raw_score=raw_score,
            valid_time=valid_time,
        )

    def insert_occurrence(
        self,
        *,
        capture_id: uuid.UUID,
        occurrence_class: str,
        primary_span_id: uuid.UUID,
        span_ids: Sequence[uuid.UUID],
        presence: Sequence[tuple[int, int]],
        produced_by_run: uuid.UUID,
        detector_version: str,
        identity_key: bytes,
        emit_key: str,
        quality: dict[str, Any] | None = None,
    ) -> uuid.UUID | None:
        """Write a scene-local occurrence. It never carries a name, and there is no column for one.

        Promotion to an entity is a separate, user-driven event. Nothing reachable from here can
        create an entity or a link, which is what keeps a model's guess distinguishable from the
        user's knowledge.
        """
        return occurrences.insert(
            self._scope,
            capture_id=capture_id,
            occurrence_class=occurrence_class,
            primary_span_id=primary_span_id,
            span_ids=span_ids,
            presence=presence,
            produced_by_run=produced_by_run,
            detector_version=detector_version,
            identity_key=identity_key,
            emit_key=emit_key,
            quality=quality,
        )

    def upsert_derived_artifact(
        self,
        *,
        derived_id: uuid.UUID,
        kind: str,
        depends_on: list[dict[str, Any]],
        dep_index: list[str],
        source_ids: Sequence[uuid.UUID],
        payload: dict[str, Any],
    ) -> bool:
        """A derived object that records what it was computed from."""
        return derived.upsert(
            self._scope,
            derived_id=derived_id,
            kind=kind,
            depends_on=depends_on,
            dep_index=dep_index,
            source_ids=source_ids,
            payload=payload,
        )

    # -- reads used by scene grouping ---------------------------------------------------

    def captures_with_context(self) -> list[dict[str, Any]]:
        """Every live capture with its clock anchor and probe, ordered by wall clock."""
        return captures.with_context(self._scope)

    def place_inferences_for_captures(
        self, capture_ids: Sequence[uuid.UUID]
    ) -> list[dict[str, Any]]:
        """Active ``place_is`` inference assertions for these captures, with their support."""
        return inferences.place_is_for_captures(self._scope, capture_ids)

    def rows_in_schema(self, table: str) -> int:
        """Every row of ``table`` this connection can see. **Not workspace-scoped.**

        The name carries the whole of the warning; :mod:`exulanica.ingest.spine.counts` carries the
        measurement behind it.
        """
        return counts.rows_in_schema(self._scope, table)
