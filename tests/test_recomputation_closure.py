"""Exemplar deletion reproduces canonical live content, not its append-only history."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path

import pytest
from exulanica.canonical import canonical_json
from exulanica.corpus.photograph import compose, encode_jpeg
from exulanica.corpus.plan import build_plan
from exulanica.epistemics.assertions import AssertionWriter
from exulanica.errors import IntegrityError
from exulanica.evidence.blob import BlobId
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.identity.decisions import confirm_link, name_occurrence
from exulanica.identity.match_context import MATCH_CONTEXT_KIND, refresh_match_context
from exulanica.identity.repository import IdentityRepository
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.scenes import run_scene_grouping
from exulanica.store.base import PurgeAuthorization, privileged_purger
from exulanica.store.local import LocalContentAddressedStore

from conftest import CountingVisionModel


def _canonical(value):
    # Graph rows carry UUIDs. Their exact string form is stable; no clocks are stripped from
    # payloads, and no floating value is rounded to make a comparison pass.
    return canonical_json(json.loads(json.dumps(value, default=str)))


def _index_row(repository):
    return repository.connection.execute(
        "select derived_id, payload, depends_on, dep_index, source_ids from derived_artifact "
        "where workspace_id=%s and kind=%s and not stale",
        (repository.workspace_id, MATCH_CONTEXT_KIND),
    ).fetchone()


def test_deleted_exemplar_reproduces_remaining_canonical_context_and_image_bytes(
    repository, tmp_path,
):
    """Baseline is built with two sources BEFORE a third exemplar exists.

    The later deletion must reproduce that independent remaining-source baseline. A second
    refresh must reuse it. A scripted detector supplies object occurrences only; its bytes are
    retained inputs, and no claim of reproducing vision/depth follows from this test.
    """
    plans = build_plan(seed=20260905, frames_per_trip=3)[:3]
    store = LocalContentAddressedStore(tmp_path / "objects")
    detector = CountingVisionModel(payload={
        "scene_description": "Synthetic scene with a satchel.",
        "objects": [{"label": "satchel", "salience": "primary", "confidence": "high",
                     "box": {"x": 0.1, "y": 0.1, "w": 0.3, "h": 0.3}}],
        "legible_text": [], "proposed_place": None,
    })
    pipeline = PhotoIngestPipeline(repository, store, vision=detector)
    identity = IdentityRepository(repository.connection, repository.workspace_id)
    actor = uuid.uuid4()
    paths, captures, source_digests = [], [], []
    entity_id = None
    baseline_index = baseline_groups = baseline_rows = None
    baseline_bytes = {}
    for index, plan in enumerate(plans):
        path = tmp_path / plan.filename
        data = encode_jpeg(plan, compose(plan))
        path.write_bytes(data)
        paths.append(path)
        source_digests.append(hashlib.sha256(data).hexdigest())
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None, outcome.error
        captures.append(outcome.capture_id)
        occurrence = repository.connection.execute(
            "select occurrence_id from occurrence where capture_id=%s and class='object'",
            (outcome.capture_id,),
        ).fetchone()["occurrence_id"]
        if entity_id is None:
            entity_id = name_occurrence(
                identity, AssertionWriter(repository.connection, repository.workspace_id),
                occurrence_id=occurrence, display_name="Synthetic satchel", actor=actor,
            ).entity_id
        else:
            confirm_link(identity, occurrence_id=occurrence, entity_id=entity_id, actor=actor)
        refresh_match_context(identity)
        run_scene_grouping(repository)
        if index == 1:
            baseline_index = _canonical(_index_row(repository)["payload"])
            baseline_rows = _index_row(repository)
            baseline_groups = _canonical([
                row.model_dump(mode="json") for row in scene_group_rows(repository.connection,
                                                       repository.workspace_id)
            ])
            for row in repository.connection.execute(
                "select content_sha256 from artifact where stage_key in ('intake','rendition')"
            ).fetchall():
                blob = BlobId(bytes(row["content_sha256"]))
                baseline_bytes[blob.hex] = store.get(blob)

    expanded = _index_row(repository)
    assert len(expanded["payload"]["anchors"]) == 3
    assert _canonical(expanded["payload"]) != baseline_index
    tombstone_id = repository.insert_tombstone(
        scope="capture", capture_id=captures[-1], requested_by=actor,
        reason="X-8 synthetic exemplar deletion",
    )
    calls_before = detector.calls
    actual = _canonical(refresh_match_context(identity))
    rebuilt = _index_row(repository)
    assert len(rebuilt["payload"]["anchors"]) == 2
    assert actual == baseline_index
    assert _canonical(rebuilt["depends_on"]) == _canonical(baseline_rows["depends_on"])
    assert rebuilt["dep_index"] == baseline_rows["dep_index"]
    assert rebuilt["source_ids"] == baseline_rows["source_ids"]
    assert f"capture:{captures[-1]}" not in rebuilt["dep_index"]
    assert repository.connection.execute(
        "select stale from derived_artifact where derived_id=%s", (expanded["derived_id"],),
    ).fetchone()["stale"] is True
    refresh_match_context(identity)
    assert _index_row(repository)["derived_id"] == rebuilt["derived_id"]

    # Force actual deterministic stage execution; an idempotent cache hit is not reproduction.
    purger = privileged_purger(store, PurgeAuthorization(
        tombstone_id=str(tombstone_id), actor="synthetic experiment",
        reason="evict deterministic test artifacts to force byte recomputation",
    ))
    assert baseline_bytes, "no deterministic artifact bytes were captured"
    for digest in baseline_bytes:
        blob = BlobId.from_hex(digest)
        assert purger.purge(blob)
        assert not store.exists(blob), "recomputation must not read a cached artifact"
    for path in paths[:2]:
        outcome = pipeline.ingest_file(path)
        assert outcome.error is None, outcome.error
    for digest, expected in baseline_bytes.items():
        assert store.get(BlobId.from_hex(digest)) == expected
    assert detector.calls == calls_before, "recomputation called the scripted model again"

    run_scene_grouping(repository)
    actual_groups = _canonical([
        row.model_dump(mode="json")
        for row in scene_group_rows(repository.connection, repository.workspace_id)
    ])
    repository.connection.execute(
        "update derived_artifact set payload=jsonb_set(payload,'{anchors}','[]'::jsonb) "
        "where derived_id=%s", (rebuilt["derived_id"],),
    )
    with pytest.raises(IntegrityError, match="canonical key"):
        refresh_match_context(identity)
    record = {
        "profile": "exulanica.exemplar-recomputation-observation/v1",
        "corpus_class": "synthetic",
        "corpus": {"generator_seed": 20260905, "frames_per_trip": 3,
                   "selected_trip": plans[0].trip_key, "source_sha256": source_digests},
        "model_source": "CountingVisionModel scripted satchel observations, not model accuracy",
        "remaining_source_count": 2,
        "canonical_exemplar_payload_sha256": hashlib.sha256(actual).hexdigest(),
        "canonical_exemplar_payload_identical": actual == baseline_index,
        "baseline_exemplar_payload": json.loads(baseline_index),
        "rebuilt_exemplar_payload": json.loads(actual),
        "dependency_set_identical": rebuilt["dep_index"] == baseline_rows["dep_index"],
        "stored_payload_tampering_refused": True,
        "historical_generation_identical": rebuilt["derived_id"] == baseline_rows["derived_id"],
        "baseline_generation_id": str(baseline_rows["derived_id"]),
        "rebuilt_generation_id": str(rebuilt["derived_id"]),
        "deterministic_artifact_sha256": sorted(baseline_bytes),
        "intake_and_rendition_bytes_identical": True,
        "scene_group_projection_identical": actual_groups == baseline_groups,
        "scene_groups_before": json.loads(baseline_groups),
        "scene_groups_after": json.loads(actual_groups),
        "vision_or_depth_exactness_claim": False,
        "model_calls_during_recomputation": detector.calls - calls_before,
    }
    output = os.environ.get("EXULANICA_RECOMPUTATION_OBSERVATION")
    if output:
        Path(output).write_text(json.dumps(record, indent=2) + "\n")
