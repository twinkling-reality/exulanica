"""The photograph ingest pipeline: a file on disk to persisted, provenance-tracked observations.

Four stages, each one idempotent by construction and each one a module in ``stages/``:

    intake     hash the bytes, read EXIF, normalise orientation, register the capture, the
               single-sample img track, the wall-clock anchor and the whole-image span, and
               emit the capture-supported assertions
    rendition  a 768 px display-space JPEG with no EXIF, the only pixels a model ever sees
    vision     one structured call, producing model inferences that each carry an evidence
               address and are filed as inference and never as anything else
    depth      one optional point-map prediction, producing a derived reconstruction artifact

Scene grouping runs once over the corpus after these per-capture stages, from the worker or
directory command, and produces proposals rather than pretending to be a fifth capture stage.

This module sequences them and owns the two things they share: the transaction whose object
store writes land after it commits, and the artifact writer. What a stage is allowed to reach
for is ``stages.writes.StageWrites``, which this class satisfies; it holds several other things
a stage has no business touching, and the Protocol is where that line is drawn.

Re-running is free. Every derivative is keyed by ``(source blob, stage, stage version, params,
input digest, run-time binding)``, so a second run over the same directory resolves each stage
from its artifact row and makes **zero** model calls. That is a cost control first and a
correctness control second: without it, "re-run everything" means paying for every vision call
again, every time. It cuts the other way too, and has to: the vision stage's params carry the
prompt's own digest and its binding carries the resolved model identifier, so editing the
prompt or swapping the model does reprocess, which is the failure this key is most likely to
hide.

Nothing reaches the object store until the tombstone guard has passed and the transaction that
passed it has committed. The store is not in the transaction, so a byte written early is a byte
a rollback cannot take back, and for purged content that means resurrection.

The epistemic split is enforced at the data layer, not by care here. ``predicate.allows_kind``
refuses a caption filed as a capture-supported fact and refuses any name at all from a model.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from PIL import Image

from exulanica.canonical import sha256_digest
from exulanica.consent.regions import PersonDetector
from exulanica.errors import BlobNotFoundError, TombstonedError
from exulanica.evidence import EvidenceAddress
from exulanica.evidence.blob import BlobId
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.committed_store import committed_writes as flush_committed_writes
from exulanica.ingest.decode import UNREADABLE, open_upright
from exulanica.ingest.exif import ExifFacts
from exulanica.ingest.ledger import Ledger, StageRecorder
from exulanica.ingest.masking import mask_image
from exulanica.ingest.person_receipts import consent_state_digest, region_set_digest
from exulanica.ingest.person_state import region_state_for_capture
from exulanica.ingest.report import IngestOutcome, IngestReport
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.stages import (
    STAGES,
    StageSpec,
    artifact_id_for,
    pipeline_digest,
)
from exulanica.ingest.stages import depth as depth_stage
from exulanica.ingest.stages import intake as intake_stage
from exulanica.ingest.stages import masked_source as masked_source_stage
from exulanica.ingest.stages import person_regions as person_regions_stage
from exulanica.ingest.stages import rendition as rendition_stage
from exulanica.ingest.stages import vision as vision_stage
from exulanica.ingest.stages.writes import StageResult
from exulanica.ingest.vision import VisionModel
from exulanica.models.errors import (
    ModelUnavailableError,
    NoFallbackError,
    StructuredOutputError,
    TransportError,
    TruncatedResponseError,
)
from exulanica.reconstruction import DepthModel
from exulanica.store.base import ContentAddressedStore

__all__ = ["SUPPORTED_SUFFIXES", "PhotoIngestPipeline"]

SUPPORTED_SUFFIXES: Final = frozenset({".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff"})


@dataclass(frozen=True, slots=True)
class _Prepared:
    """What intake produced and what the derivative stages need to run from it.

    Reassembled from the database and the store when the two halves run in different processes,
    which is the property that lets the queue hold a capture id: every field here is either a
    content address, an identifier, or something recomputed from the original bytes.
    """

    blob_id: BlobId
    capture_id: uuid.UUID
    image_span_id: uuid.UUID
    intake: StageResult
    upright: Image.Image
    facts: ExifFacts


class PhotoIngestPipeline:
    """Ingest photographs into the evidence spine.

    ``vision`` is optional. With no vision model the pipeline still produces a complete
    capture-supported record: hash, EXIF, orientation, timing, position, dimensions, the track,
    the span and the assertions. The vision stage is then reported as not run rather than
    faked, and a later run with a model configured completes it.
    """

    def __init__(
        self,
        repository: IngestRepository,
        store: ContentAddressedStore,
        *,
        vision: VisionModel | None = None,
        depth: DepthModel | None = None,
        detector: PersonDetector | None = None,
    ) -> None:
        self._repository = repository
        self._store = store
        self._vision = vision
        self._depth = depth
        # Not a binding. `person_regions` declares no model_role, so `_require_binding`
        # refuses a run-time binding for it; the detector it was given is pinned in the
        # stage parameters instead and the stage refuses one that does not match.
        self._detector = detector
        # The run-time half of every stage's identity, resolved once. For the vision stage that
        # is the identifier the model role points at right now: it is not in the registry
        # because it does not live in the source, and it is in the key because swapping it
        # changes what the stage produces.
        self._bindings: dict[str, dict[str, str]] = {}
        if vision is not None:
            self._bindings["vision"] = {"model_id": vision.model_id}
        if depth is not None:
            # The resolved model is in the key for the same reason the vision model is: swapping
            # the weights changes what the stage produces, and a corpus keyed as though nothing
            # had changed would never reprocess.
            self._bindings["depth"] = {"model_id": depth.model_id}
        repository.register_stages(STAGES)

    @property
    def pipeline_digest(self) -> str:
        """This pipeline's version, prompt text and resolved models, as one short digest."""
        return pipeline_digest(self._bindings)

    # -- what a stage is given ------------------------------------------------------------

    @property
    def repository(self) -> IngestRepository:
        return self._repository

    @property
    def store(self) -> ContentAddressedStore:
        return self._store

    def _binding_for(self, spec: StageSpec) -> dict[str, str] | None:
        return self._bindings.get(spec.key)

    @contextmanager
    def committed_writes(self) -> Iterator[list[bytes]]:
        """A database transaction whose object-store writes happen **after** it commits.

        The store is not transactional and cannot be enrolled in one, so a payload written
        inside a transaction survives that transaction's rollback. Two consequences, one of
        them serious:

        *   A tombstoned import is cancelled and its rows roll back, and the purged bytes are
            back on disk. Deletion that a retry undoes is not deletion.
        *   An ordinary stage failure leaves an orphan object nothing references.

        Deferring the write past the commit inverts the failure mode into the recoverable one:
        a crash in the window between commit and flush leaves a row whose bytes are missing,
        which ``persist_artifact`` and the rendition stage already detect and heal by
        recomputing. No compensating cleanup is needed, because nothing was written that would
        need cleaning up; ordering genuinely is sufficient here, which is why it is done by
        ordering.

        ``tests/test_ingest_persistence.py`` walks the whole ingest package, recursively, and
        asserts the shared helper this delegates to is the only function that writes to the store.
        """
        with flush_committed_writes(self._repository, self._store) as pending:
            yield pending

    def persist_artifact(
        self,
        *,
        spec: StageSpec,
        blob_id: BlobId,
        key: str,
        input_digest: bytes,
        payload: bytes,
        recorder: StageRecorder,
        outcome: IngestOutcome,
        pending: list[bytes],
        produced_by_event: uuid.UUID | None = None,
        privacy_screening_id: uuid.UUID | None = None,
        read_source_sha256: bytes | None = None,
    ) -> StageResult:
        """Queue bytes, insert the artifact row, and report reuse honestly.

        Bytes go on ``pending`` rather than into the store, and reach the store only once the
        surrounding transaction has committed. See ``committed_writes``.

        The two hashes are kept apart on purpose. ``idempotency_key`` is what the output should
        be, computed before running. ``content_sha256`` is what it turned out to be. When a
        deterministic stage produces different content under the same key, that is worth an
        event rather than a silent overwrite, and the existing artifact is kept: mutating it
        would break every citation and every replay that already points at it.

        This is also the single place a stage is recorded as run or reused. A stage that
        appends to ``outcome`` itself as well as calling this is how "depth+depth" reached the
        command line summary.
        """
        content_hash = sha256_digest(payload)
        existing = self._repository.find_artifact(key)
        if existing is not None:
            stored = existing.content_sha256 or content_hash
            if existing.content_sha256 is not None and existing.content_sha256 != content_hash:
                # Same key, different bytes. For a stage declared deterministic that is a fault
                # worth an event; for a sampled one it is expected. Either way the stored
                # artifact wins, because citations and replays already point at it.
                if spec.deterministic:
                    recorder.record_nondeterminism(existing.content_sha256, content_hash)
                if not self._store.exists(BlobId(stored)):
                    # The bytes are gone and this run cannot reproduce them. Flag it rather
                    # than repointing the row at the new bytes: the identity key names the old
                    # content, and redefining what it names would silently invalidate every
                    # citation and replay that used it.
                    self._repository.mark_artifact_needs_repair(existing.artifact_id)
            elif not self._store.exists(BlobId(stored)):
                # The row survived but the bytes did not, and the recompute matched. Heal
                # rather than fail: the artifact identity is unchanged, so nothing downstream
                # has to be told.
                pending.append(payload)
            outcome.stages_reused.append(spec.key)
            return StageResult(
                artifact_id=existing.artifact_id,
                content_sha256=stored,
                idempotency_key=key,
                reused=True,
            )
        pending.append(payload)
        artifact_id = artifact_id_for(key)
        self._repository.insert_artifact(
            artifact_id=artifact_id,
            kind=spec.output_kind,
            source_blob=blob_id,
            stage_key=spec.key,
            stage_version=spec.version,
            params_digest=spec.params_digest,
            input_digest=input_digest,
            idempotency_key=key,
            content_sha256=content_hash,
            storage_key=self._store.key_for(BlobId(content_hash)),
            byte_size=len(payload),
            produced_by_event=produced_by_event,
            privacy_screening_id=privacy_screening_id,
            # The exact bytes this stage read, which is not always the capture's own bytes. A
            # point map over a photograph containing somebody who has not consented must name the
            # masked derivative here, and migration 0037's trigger refuses the row if it does not.
            read_source_sha256=read_source_sha256,
        )
        recorder.record_output(artifact_id)
        outcome.stages_run.append(spec.key)
        return StageResult(
            artifact_id=artifact_id,
            content_sha256=content_hash,
            idempotency_key=key,
            reused=False,
        )

    # -- directory ----------------------------------------------------------------------

    def ingest_directory(
        self,
        directory: str | Path,
        *,
        recursive: bool = True,
        limit: int | None = None,
        batch: IntakeBatch | None = None,
    ) -> IngestReport:
        """Ingest every supported image under ``directory``. Safe to run repeatedly.

        ``batch`` is a watched intake to run inside, and this method JOINS it rather than owning
        it. The distinction is not tidiness. A batch's terminal event is what tells the interface
        the work is over and lets a client stop listening, so it has to come after all of the
        work; and this method is not all of the work, because continuity search runs over the
        whole corpus once the photographs are in. A pipeline that closed the batch it opened
        would emit "finished" and then carry on emitting stages into a stream nobody was reading.

        What it does own is the declaration of size, because it is what walks the directory. The
        order matters: the batch exists before the walk so a client can subscribe to something
        that honestly reports no total, and the total is written once, from what the walk found,
        rather than accumulated as it goes. A denominator that grows is one that moves under a
        fraction somebody is already reading.
        """
        report = IngestReport(pipeline_digest=self.pipeline_digest)
        report.batch_id = batch.batch_id if batch else None

        paths = list(_iter_images(Path(directory), recursive=recursive))
        if limit is not None:
            paths = paths[:limit]
        if batch is not None:
            batch.declare_size(len(paths))

        for path in paths:
            report.outcomes.append(self.ingest_file(path, batch_id=report.batch_id))
        return report

    # -- one photograph, in one piece or in two -------------------------------------------

    def ingest_file(self, path: str | Path, *, batch_id: uuid.UUID | None = None) -> IngestOutcome:
        """Ingest one photograph, every stage, in this thread. Never raises for a bad file."""
        source = Path(path)
        outcome = IngestOutcome(path=source)
        with self._recorded_run(outcome, batch_id=batch_id) as ledger:
            prepared = self._intake(source.read_bytes(), ledger, outcome)
            self._derivatives(prepared, ledger, outcome, privacy_screening_id=None)
        return outcome

    def ingest_intake(
        self, data: bytes, *, filename: str, batch_id: uuid.UUID | None = None
    ) -> IngestOutcome:
        """Run the intake stage alone, from bytes already in hand. The request thread's half.

        **Why this exists as its own entry point**, because the alternative looks cheaper and
        is not. An upload has to put the bytes somewhere before the pipeline hashes them, and
        anywhere outside the content-addressed store is outside every tombstone guard and
        outside the purger: a deletion arriving while a file sits in a spool directory or in a
        queue payload cascades to rows and to store objects and reaches neither. Invariant 8
        says deletion cascades, so the staging window has to collapse rather than be swept.

        It collapses to one request because intake is cheap: a hash, an EXIF read, an
        orientation transform and a handful of rows, tens of milliseconds on an ordinary
        photograph. What is expensive is the vision stage, which is a model call, and that is
        what :meth:`ingest_derivatives` does from a capture id afterwards.

        **The store write still happens after the transaction that ran the tombstone guard
        commits**, because this goes through the same ``committed_writes`` every other caller
        does. Writing to the store on arrival, which is the obvious way to put uploaded bytes
        somewhere guarded, would undo exactly that: the rows of a refused import roll back and
        the purged bytes stay on disk. ``tests/test_ingest_persistence.py`` is what holds it.

        ``filename`` is what the client called the file, and it is carried for the report and
        for nothing else. It never reaches an evidence address, which is a content hash, a
        track key and a time interval, and never a name a client chose.
        """
        outcome = IngestOutcome(path=Path(filename))
        with self._recorded_run(outcome, batch_id=batch_id) as ledger:
            self._intake(data, ledger, outcome)
        return outcome

    def ingest_derivatives(
        self,
        capture_id: uuid.UUID,
        *,
        batch_id: uuid.UUID | None = None,
        delivery_job_id: uuid.UUID | None = None,
        delivery_claim_token: uuid.UUID | None = None,
        privacy_screening_id: uuid.UUID | None = None,
    ) -> IngestOutcome:
        """Run rendition, vision and depth for a capture whose intake has already committed.

        The worker's half, and the reason the queue can hold an identifier rather than bytes.
        The bytes are read back out of the content-addressed store, which is the one place a
        deletion reaches, so nothing is staged anywhere in between.

        A capture the user deleted between the two halves is refused here and the run is
        **cancelled rather than failed**, because nothing went wrong. Migration 0011 refuses the
        derivative rows independently, so a tombstone landing after this check still stops the
        artifact and, through ``committed_writes``, the bytes with it. This check is the one
        that makes the ordinary case ordinary: it costs one indexed read and it means the worker
        does not decode a photograph it is not allowed to keep.
        """
        outcome = IngestOutcome(path=Path(str(capture_id)))
        outcome.capture_id = capture_id
        with self._recorded_run(
            outcome,
            batch_id=batch_id,
            delivery_job_id=delivery_job_id,
            delivery_claim_token=delivery_claim_token,
        ) as ledger:
            capture = self._repository.capture(capture_id)
            if capture is None:
                raise LookupError(f"this workspace has no capture {capture_id}")
            if capture.deleted_at is not None:
                # Cancelled, not failed, and the type is what makes that true: `_recorded_run`
                # branches on it. A deletion recorded as a failure is a run something retries,
                # against content the user asked to have removed.
                raise TombstonedError(
                    f"capture {capture_id} was deleted before its derivative stages ran"
                )
            blob_id = capture.blob_id
            outcome.blob_id = blob_id
            self._repository.refuse_ingest_if_tombstoned(EvidenceAddress.photograph(blob_id))
            ledger.attach_capture(capture_id)

            intake = self._repository.find_artifact(intake_stage.key_for(blob_id))
            if intake is None or intake.content_sha256 is None:
                ledger.missing(
                    STAGES["intake"],
                    reason=(
                        f"capture {capture_id} has no committed intake artifact, so derivative "
                        "processing cannot begin"
                    ),
                    input_blob=blob_id,
                )
                raise LookupError(
                    f"capture {capture_id} has no committed intake artifact, so there is nothing "
                    "to derive from. Ingest the photograph rather than resuming it."
                )
            upright, facts = _decode(self._store.get(blob_id))
            if privacy_screening_id is None and self._depth is not None:
                screening = self._repository.latest_privacy_screening(capture_id)
                privacy_screening_id = screening.screening_id if screening else None
            self._derivatives(
                _Prepared(
                    blob_id=blob_id,
                    capture_id=capture_id,
                    image_span_id=self._repository.upsert_span(EvidenceAddress.photograph(blob_id)),
                    intake=StageResult(
                        artifact_id=intake.artifact_id,
                        content_sha256=intake.content_sha256,
                        idempotency_key=intake.idempotency_key,
                        reused=True,
                    ),
                    upright=upright,
                    facts=facts,
                ),
                ledger,
                outcome,
                privacy_screening_id=privacy_screening_id,
            )
        return outcome

    @contextmanager
    def _recorded_run(
        self,
        outcome: IngestOutcome,
        *,
        batch_id: uuid.UUID | None,
        delivery_job_id: uuid.UUID | None = None,
        delivery_claim_token: uuid.UUID | None = None,
    ) -> Iterator[Ledger]:
        """Open a run, and close it with what happened rather than with what was attempted.

        The three outcomes are not interchangeable. ``cancelled`` is a tombstone: the user
        deleted something and the pipeline stopped, which is the system working. ``failed`` is
        anything else. ``succeeded`` is neither. A run recorded as failed when it was cancelled
        would put a deletion in the same bucket as a corrupt file, and the retry policy for
        those two is opposite: a tombstoned address is terminal and is never retried.
        """
        ledger = Ledger.start_run(
            self._repository,
            trigger="ingest",
            pipeline_digest=self.pipeline_digest,
            batch_id=batch_id,
            delivery_job_id=delivery_job_id,
            delivery_claim_token=delivery_claim_token,
        )
        outcome.run_id = ledger.run_id
        try:
            yield ledger
        except TombstonedError as exc:
            outcome.error = f"tombstoned: {exc}"
            outcome.failure_class = "cancelled"
            outcome.tombstoned = True
            ledger.finish("cancelled")
        except Exception as exc:
            outcome.error = f"{type(exc).__name__}: {exc}"
            outcome.failure_class = type(exc).__name__
            outcome.missing = isinstance(exc, (BlobNotFoundError, LookupError))
            outcome.unavailable = isinstance(exc, (ModelUnavailableError, NoFallbackError))
            outcome.retryable = _retryable(exc)
            ledger.finish("failed")
        else:
            ledger.finish("succeeded")

    def _intake(self, data: bytes, ledger: Ledger, outcome: IngestOutcome) -> _Prepared:
        blob_id = BlobId.of_bytes(data)
        outcome.blob_id = blob_id
        # First, before the decode, before the object store, before a single row: is this
        # content allowed in at all? A tombstone discovered further down cancels the run and
        # rolls the rows back, but the store is not in that transaction, so bytes written
        # before the check would survive the cancellation and purged content would be back on
        # disk. Nothing below this line writes anything the check has not already permitted.
        self._repository.refuse_ingest_if_tombstoned(EvidenceAddress.photograph(blob_id))
        upright, facts = _decode(data)

        intake, capture_id, image_span_id = intake_stage.run(
            self, blob_id, data, upright.size, facts, ledger, outcome
        )
        ledger.attach_capture(capture_id)
        outcome.capture_id = capture_id
        return _Prepared(
            blob_id=blob_id,
            capture_id=capture_id,
            image_span_id=image_span_id,
            intake=intake,
            upright=upright,
            facts=facts,
        )

    def _derivatives(
        self,
        prepared: _Prepared,
        ledger: Ledger,
        outcome: IngestOutcome,
        *,
        privacy_screening_id: uuid.UUID | None,
    ) -> None:
        rendition = rendition_stage.run(
            self, prepared.blob_id, prepared.upright, prepared.intake, ledger, outcome
        )
        vision = vision_stage.run(
            self,
            self._vision,
            self._binding_for(STAGES["vision"]),
            prepared.blob_id,
            rendition,
            prepared.capture_id,
            prepared.image_span_id,
            prepared.facts,
            ledger,
            outcome,
            privacy_screening_id,
        )
        # Between vision and depth, and in this order for a reason. The region stage reads the
        # observation vision stored and writes one `detected` row per proposed person, which is
        # what arms the database guard: until a region row exists, `capture_requires_masking` is
        # false for that photograph and the trigger below has nothing to refuse. The masking stage
        # then fills every region whose person has not consented to their likeness, and depth
        # reads the result. Ordering these after depth would produce the mask a frame too late.
        person_regions_stage.run(
            self,
            self._detector,
            prepared.blob_id,
            prepared.upright,
            prepared.capture_id,
            prepared.intake,
            vision,
            ledger,
            outcome,
        )
        masked, masked_image, consent_digests = self._masked_source(prepared, ledger, outcome)
        # After vision, and from the UPRIGHT source rather than from the rendition. The rendition
        # is 768px and exists so a model can look at something small; depth is the geometry the
        # photograph will be walked through and is worth the full frame the size parameter allows.
        depth_stage.run(
            self,
            self._depth,
            self._binding_for(STAGES["depth"]),
            prepared.blob_id,
            prepared.upright,
            prepared.capture_id,
            prepared.image_span_id,
            prepared.intake,
            ledger,
            outcome,
            privacy_screening_id,
            masked=masked,
            masked_image=masked_image,
            consent_digests=consent_digests,
        )

    def _masked_source(
        self, prepared: _Prepared, ledger: Ledger, outcome: IngestOutcome
    ) -> tuple[StageResult | None, Image.Image | None, tuple[bytes, ...]]:
        """Produce the masked derivative for one photograph, or nothing when nobody is hidden.

        Returns the digests as well as the image, because they are what puts the consent state
        into the depth stage's key. A photograph where everybody has consented produces no
        derivative and no digests, so it keys and reconstructs exactly as it did before any of
        this existed.
        """
        state = region_state_for_capture(self._repository, prepared.capture_id)
        if not state.outlines:
            return None, None, ()
        digests = (
            region_set_digest(
                capture_id=prepared.capture_id,
                source_sha256=prepared.blob_id.hex,
                regions=state.outlines,
            ),
            consent_state_digest(
                capture_id=prepared.capture_id,
                source_sha256=prepared.blob_id.hex,
                resolved=state.resolved,
            ),
        )
        masked = masked_source_stage.run(
            self,
            prepared.blob_id,
            prepared.upright,
            prepared.capture_id,
            state.outlines,
            state.resolved,
            state.subjects,
            prepared.intake,
            ledger,
            outcome,
        )
        if masked is None:
            return None, None, digests
        hidden = masked_source_stage.hidden_outlines(state.outlines, state.resolved)
        image = mask_image(
            prepared.upright,
            hidden,
            dilation_millionths=int(STAGES["masked_source"].params["dilation_millionths"]),
        )
        return masked, image, digests


def _decode(data: bytes) -> tuple[Image.Image, ExifFacts]:
    """The pipeline's own refusal wording over :func:`exulanica.ingest.decode.open_upright`."""
    try:
        return open_upright(data)
    except UNREADABLE as exc:
        raise ValueError(f"not a readable image: {exc}") from exc


def _retryable(exc: Exception) -> bool:
    """Whether running the same reviewed stage later can plausibly change the outcome.

    Retry only failures whose types carry that meaning. Configuration, missing input, budget
    refusal, integrity failure and programmer errors are terminal; treating every exception as
    transient is an automated spend loop disguised as resilience.
    """
    if isinstance(exc, TransportError):
        return exc.retryable
    return isinstance(exc, (StructuredOutputError, TruncatedResponseError))


def _iter_images(directory: Path, *, recursive: bool) -> Iterator[Path]:
    """Every supported image under ``directory``, in a deterministic order."""
    if not directory.is_dir():
        raise NotADirectoryError(str(directory))
    paths: Iterable[Path] = directory.rglob("*") if recursive else directory.glob("*")
    for path in sorted(paths):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            yield path
