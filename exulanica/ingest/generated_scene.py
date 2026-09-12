"""Recording what a world model generated for a scene, in the tier below every recorded rung.

Roadmap Phase 10 capability 2, the write half. This does not run a model. It records what one
produced, together with the receipt that says which model, from which prompt, conditioned on
exactly which bytes. That distinction is the design: the platform does not want to become the
place generative models run, it wants to be the place their output is honestly filed.

Two structural facts do most of the work here, and both are inherited rather than invented.

**The artifact subject.** ``artifact`` requires exactly one subject: a source blob or a scene
(migration 0024's ``an_artifact_names_one_subject``). Generated content has no source blob, so it
is scene-subject. That has a consequence worth stating plainly rather than discovering later:
this records generation *around an existing scene*. Generating for a place with no scene at all
would need a subject that does not exist yet, and it is not attempted.

**Deletion reaches it for free.** ``tg_record_person_dependencies_from_artifact`` branches on
``scene_id is not null`` generically, so a generated artifact records its per-person dependencies
like any other; ``tg_tombstone_guard_artifact`` refuses the insert when a tombstone blocks the
scene. Nothing here re-implements either, which is why the insert goes through the ordinary
``insert_scene_artifact`` rather than a writer of its own.

What this module does add is a refusal. :func:`record_generated_scene` reads the current World Read
bundle for the scene and refuses a receipt whose ``world-read-bundle`` conditioning digest does not
match it. Without that check the conditioning digest is a number the caller chose, and the tier's
one substantive claim, that the model was shown this real place, would be unfalsifiable.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from exulanica.errors import EpistemicViolation
from exulanica.evidence.blob import BlobId
from exulanica.ingest.committed_store import committed_writes
from exulanica.ingest.ledger import Ledger
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.scene_reconstruction import _scene_key
from exulanica.ingest.stages import artifact_id_for, stage
from exulanica.reconstruction.generated import (
    GENERATED_SCENE_STAGE,
    GeneratedSceneReceipt,
    generation_input_digest,
)
from exulanica.store import ContentAddressedStore

__all__ = ["GeneratedSceneRecord", "record_generated_scene"]


@dataclass(frozen=True, slots=True)
class GeneratedSceneRecord:
    """What was written, addressed the way every other artifact in this system is."""

    artifact_id: uuid.UUID
    scene_id: uuid.UUID
    receipt_sha256: str
    inserted: bool


def record_generated_scene(
    repository: IngestRepository,
    store: ContentAddressedStore,
    *,
    scene_id: uuid.UUID,
    receipt: GeneratedSceneReceipt,
    expected_recorded_sha256: str,
) -> GeneratedSceneRecord:
    """Record one generated scene, or refuse.

    ``expected_recorded_sha256`` is the ``recorded_sha256`` of the World Read bundle as this
    process reads it now: the digest over the observed world alone, without any generation. A
    receipt naming a different one is refused rather than stored with a note, because a generated
    surface whose conditioning nobody can reproduce is exactly the artifact this tier exists to
    make impossible to file quietly.

    The recorded digest rather than the whole-bundle digest, because the whole bundle contains the
    generations already filed. Citing that would mean filing a generation changed the thing it
    cited, so the same generation could never be re-filed and two models could never say they read
    the same observed world.
    """
    if receipt.bundle_sha256 != expected_recorded_sha256:
        raise EpistemicViolation(
            "the generation names a world-read bundle that is not this scene's recorded world. "
            f"The receipt says {receipt.bundle_sha256}, the scene reads as "
            f"{expected_recorded_sha256}. A conditioning digest nobody can reproduce is not "
            "provenance."
        )

    spec = stage(GENERATED_SCENE_STAGE)
    input_digest = generation_input_digest(receipt)
    payload = receipt.canonical_bytes()
    content_id = BlobId.of_bytes(payload)

    # Imported rather than reimplemented, and the first version proves why. It copied
    # `_scene_key`'s construction by hand and got the length prefix wrong: four bytes where the
    # original uses eight. Nothing collided, because this stage is the only user of its own key
    # space, so the divergence would have sat there indefinitely under a comment claiming the two
    # were identical on purpose. A private name reached across two modules of one package is a
    # smaller cost than a second copy of a frozen digest construction.
    key = _scene_key(scene_id, spec.key, input_digest)
    existing_artifact = repository.find_artifact(key)
    artifact_id = (
        existing_artifact.artifact_id
        if existing_artifact is not None
        else artifact_id_for(key, workspace_id=repository.workspace_id)
    )

    # "manual" rather than a new trigger value: `pipeline_run.trigger` is a closed CHECK set
    # (ingest, reprocess, repair, manual) and widening it is a migration. Manual is also the
    # honest reading. This run was started by an authenticated caller filing something a model
    # produced elsewhere, not by the pipeline reprocessing its own corpus.
    ledger = Ledger.start_run(repository, trigger="manual")
    try:
        with (
            ledger.stage(spec) as recorder,
            repository.locked_stored_objects([content_id]),
            committed_writes(repository, store) as pending,
        ):
            inserted = repository.insert_scene_artifact(
                artifact_id=artifact_id,
                kind=spec.output_kind,
                scene_id=scene_id,
                stage_key=spec.key,
                stage_version=spec.version,
                params_digest=spec.params_digest,
                input_digest=input_digest,
                idempotency_key=key,
                content_sha256=content_id.digest,
                storage_key=store.key_for(content_id),
                byte_size=len(payload),
                produced_by_event=recorder.stage_started_event,
            )
            if inserted:
                pending.append(payload)
                recorder.record_output(artifact_id)
    except BaseException:
        ledger.finish("failed")
        raise
    ledger.finish("succeeded")
    return GeneratedSceneRecord(
        artifact_id=artifact_id,
        scene_id=scene_id,
        receipt_sha256=content_id.hex,
        inserted=inserted,
    )
