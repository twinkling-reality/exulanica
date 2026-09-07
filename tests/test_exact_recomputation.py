"""What "recomputed from the remaining data" is allowed to mean.

`docs/domain-and-evidence-model.md` section 6 bans the words "unlearning", "forgetting" and "the
model has forgotten", and offers this instead: *removed from retrieval and from future training,
with every derived artifact recomputed from the remaining data*, adding that because there are no
trained weights the recomputation is "exact by construction".

The last clause is the one that needs a boundary, and ADR-0017 draws it. **Two of the eight stages
call a model, and a model-produced artifact is not bit-reproducible.** Sampled generation differs
run to run by design, and a neural forward pass differs across accelerators and library versions.
An exact-recomputation claim that covered them would be false in the ordinary case rather than in
an exotic one.

These tests hold the boundary in three places: the registry cannot declare a model stage
deterministic, the pipeline does not file a model stage's difference as a fault, and the sentence
in the document names the same stages the code does.
"""

from __future__ import annotations

import dataclasses
import re
from pathlib import Path

import pytest
from exulanica.ingest.stages import STAGES, StageSpec

_DOC = Path(__file__).resolve().parents[1] / "docs" / "domain-and-evidence-model.md"

#: The sentence in section 6 that names them, matched loosely enough to survive rewording and
#: tightly enough that deleting the sentence fails rather than passing vacuously.
_MARKER = "Stages that are not exactly recomputable, and therefore excluded from that claim:"


def test_a_stage_that_calls_a_model_cannot_declare_itself_deterministic():
    """The rule, enforced where a new stage is written rather than where it is reviewed."""
    with pytest.raises(ValueError, match="not bit-reproducible"):
        StageSpec(
            key="hopeful",
            version=1,
            output_kind="caption",
            deterministic=True,
            model_role="vision",
        )


def test_every_model_backed_stage_is_declared_non_deterministic():
    backed = {key: spec for key, spec in STAGES.items() if spec.model_role is not None}
    assert backed, "no stage calls a model, which would make this file meaningless"
    for key, spec in backed.items():
        assert spec.deterministic is False, key


def test_the_document_names_exactly_the_stages_the_registry_excludes():
    """A doc that drifts from the registry is how a false claim gets published.

    The claim is public-facing: it is the sentence the product is allowed to say about deletion.
    So the list is derived from the registry here rather than trusted, and adding a model-backed
    stage without amending the sentence fails.
    """
    text = _DOC.read_text(encoding="utf-8")
    assert _MARKER in text, "the exact-recomputation boundary sentence is gone from section 6"
    sentence = text.split(_MARKER, 1)[1].split("\n\n", 1)[0]
    # Intersected with the registry so that prose around the list (`model_role`, `false`) is not
    # read as a stage name, while naming the wrong stage, or omitting one, still fails.
    named = set(re.findall(r"`([a-z_]+)`", sentence)) & set(STAGES)
    excluded = {key for key, spec in STAGES.items() if not spec.deterministic}
    assert named == excluded, (
        f"document names {sorted(named)}, registry excludes {sorted(excluded)}"
    )


def test_a_model_stage_that_produces_different_bytes_is_not_reported_as_a_fault(
    tmp_path, photo_dir, repository
):
    """The other half of the deterministic-stage test in test_ingest_persistence.py.

    A resampling filter that changed its output is a fault. A vision model that wrote a different
    sentence is Tuesday. Filing the second as the first would bury the first.
    """
    from exulanica.ingest.pipeline import PhotoIngestPipeline
    from exulanica.store.local import LocalContentAddressedStore

    from conftest import DEFAULT_PAYLOAD, CountingVisionModel, ingest_observed, write_photo

    path = write_photo(photo_dir, "a.jpg")
    store = LocalContentAddressedStore(tmp_path / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=CountingVisionModel())
    first = ingest_observed(pipeline, repository, path)
    assert first.error is None

    stored = repository.connection.execute(
        "select content_sha256 from artifact where stage_key = 'vision'"
    ).fetchone()
    original = bytes(stored["content_sha256"])

    payload = dict(DEFAULT_PAYLOAD)
    payload["caption"] = "a different sentence entirely"
    second_pipeline = PhotoIngestPipeline(
        repository, store, vision=CountingVisionModel(payload=payload)
    )
    from exulanica.evidence.blob import BlobId
    from exulanica.store.base import PurgeAuthorization, privileged_purger

    privileged_purger(
        store,
        PurgeAuthorization(tombstone_id="t", actor="test", reason="force a recompute"),
    ).purge(BlobId(original))

    second = ingest_observed(second_pipeline, repository, path)
    assert second.error is None

    events = repository.connection.execute(
        "select type from pipeline_event where run_id = %s", (second.run_id,)
    ).fetchall()
    assert not [e for e in events if e["type"] == "nondeterminism_detected"], (
        "a sampled generation was filed as a fault, which is how a real fault gets ignored"
    )


def test_the_flag_is_a_claim_about_events_not_a_proof_of_reproduction():
    """`scene_pose` is the case that makes the distinction necessary rather than pedantic.

    It fixes COLMAP's `random_seed`, which is why a differing pose is worth an event. It also
    runs RANSAC across threads, and `exulanica/reconstruction/pycolmap_executor.py` says in as
    many words that the residual variation has not been measured. So the stage is declared
    deterministic and is not yet known to be exactly recomputable, and those are different
    statements about it.
    """
    pose = STAGES["scene_pose"]
    assert pose.deterministic is True
    assert pose.model_role is None
    executor = (
        Path(__file__).resolve().parents[1]
        / "exulanica"
        / "reconstruction"
        / "pycolmap_executor.py"
    ).read_text(encoding="utf-8")
    assert "RANSAC threading still admits variation" in executor
    assert "has not been measured" in executor


def test_replacing_a_stage_keeps_the_rule():
    """`dataclasses.replace` is the ordinary way a stage gets varied, so it must check too."""
    with pytest.raises(ValueError, match="not bit-reproducible"):
        dataclasses.replace(STAGES["vision"], deterministic=True)
