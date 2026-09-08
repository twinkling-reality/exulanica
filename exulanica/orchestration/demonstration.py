"""One evidence-to-package frontier demonstration, with no synthetic progress.

This module deliberately composes existing public boundaries instead of growing alternate ones:
the ingest ledger supplies formation, Selection supplies the answer, the reviewed world
repositories own spatial and style authority, and the WMP projector owns export.  The receipt is
therefore a directory of facts those systems produced, not a second ledger that claims work ran.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import psycopg
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.evidence import BlobId
from exulanica.graph import read_snapshot
from exulanica.ingest.batch import IntakeBatch
from exulanica.ingest.continuity import run_continuity
from exulanica.ingest.formation import project_formation
from exulanica.ingest.pipeline import PhotoIngestPipeline
from exulanica.ingest.report import IngestOutcome, IngestReport
from exulanica.ingest.repository import IngestRepository
from exulanica.ingest.vision import VisionModel
from exulanica.orchestration.manifest import BuildManifest
from exulanica.orchestration.preflight import validate_layout
from exulanica.reconstruction import DepthModel
from exulanica.selection import (
    Intent,
    SelectionPlan,
    Session,
    build_packet,
    execute,
    render_deterministic_answer,
    validate,
    validate_answer,
)
from exulanica.store.local import LocalContentAddressedStore
from exulanica.store.resolve import address_from_span_row, resolve_original_bytes
from exulanica.world import (
    ProposalOrigin,
    ProposalProvenance,
    SpatialCandidate,
    StaleStructuralBase,
    StaleStyleVersion,
    StyleProposal,
    StyleReference,
    StyleScope,
    WorldStructureRepository,
    WorldStyleRepository,
)
from exulanica.world.structure import validate_candidate
from exulanica.world_package import diff_packages, project_world_package

__all__ = ["FrontierDemonstrationError", "run_frontier_demonstration"]


class FrontierDemonstrationError(RuntimeError):
    """A named mandatory gate stopped the demonstration."""

    def __init__(self, gate: str, detail: str) -> None:
        super().__init__(f"{gate}: {detail}")
        self.gate = gate
        self.detail = detail


@dataclass(frozen=True, slots=True)
class _SourceState:
    path: str
    ordinal: int
    capture_id: uuid.UUID
    span_id: uuid.UUID
    blob_sha256: str
    rung: int
    rung_state: str


def run_frontier_demonstration(
    connection: psycopg.Connection,
    *,
    manifest: BuildManifest,
    photo_dir: Path,
    data_dir: Path,
    output: Path,
    private_key: Ed25519PrivateKey,
    confirm_source_deletion: bool,
    vision: VisionModel | None = None,
    depth: DepthModel | None = None,
) -> dict[str, Any]:
    """Run every Phase 8 gate and return the canonical receipt document.

    ``vision`` and ``depth`` are dependency-injection seams for acceptance tests.  Production
    callers must make them agree with the manifest; an unavailable stage is represented by
    ``None`` only when the manifest says unavailable.
    """
    try:
        validate_layout(photo_dir, data_dir, output)
    except ValueError as exc:
        raise FrontierDemonstrationError("output_boundary", str(exc)) from exc
    if output.exists():
        raise FrontierDemonstrationError("output_boundary", f"output already exists: {output}")
    if not confirm_source_deletion:
        raise FrontierDemonstrationError(
            "source_deletion_confirmation_required",
            "step 10 creates a durable capture tombstone; rerun with explicit confirmation",
        )
    if manifest.pipeline.vision == "configured" and vision is None:
        raise FrontierDemonstrationError(
            "vision_configuration", "manifest requires configured vision but no model is loaded"
        )
    if manifest.pipeline.vision == "unavailable" and vision is not None:
        raise FrontierDemonstrationError(
            "vision_configuration", "manifest declares vision unavailable but a model was supplied"
        )
    if manifest.pipeline.depth == "moge" and depth is None:
        raise FrontierDemonstrationError(
            "depth_configuration", "manifest requires MoGe but no depth model is loaded"
        )
    if manifest.pipeline.depth == "unavailable" and depth is not None:
        raise FrontierDemonstrationError(
            "depth_configuration", "manifest declares depth unavailable but a model was supplied"
        )
    paths = manifest.validate_photo_directory(photo_dir)

    repository = IngestRepository(connection, manifest.workspace_id)
    screenings = _authorized_screenings(repository, manifest, vision=vision, depth=depth)
    output.mkdir(parents=True)
    store = LocalContentAddressedStore(data_dir / "blobs")
    pipeline = PhotoIngestPipeline(repository, store, vision=vision, depth=depth)

    first_ingest = _ingest_pass(
        pipeline,
        repository,
        paths,
        photo_root=photo_dir,
        label="frontier:initial",
        screenings=screenings,
    )
    _require_ingest(first_ingest, "initial_ingest")
    initial_sources = _source_states(connection, manifest, include_deleted=False)
    if len(initial_sources) != len(manifest.sources):
        raise FrontierDemonstrationError(
            "source_resolution", "the live capture set does not match the authorized manifest"
        )
    evidence = _open_exact_evidence(connection, manifest, store, initial_sources[0])
    semantic = _semantic_and_supported_answer(connection, manifest)
    initial_world = _apply_world(
        connection, manifest, initial_sources, demonstrate_stale_rejection=True
    )
    adaptation = _adapt_world(connection, manifest)

    initial_evaluation = _evaluation_document(
        manifest,
        stage="initial",
        ingest=first_ingest,
        evidence=evidence,
        semantic=semantic,
        world=initial_world,
        adaptation=adaptation,
    )
    initial_evaluation_path = output / "evaluation-initial.json"
    _write_canonical(initial_evaluation_path, initial_evaluation)
    initial_package = project_world_package(
        connection,
        workspace_id=manifest.workspace_id,
        actor=manifest.actor_id,
        output=output / "package-initial",
        private_key=private_key,
        world_id=manifest.world_id,
        evaluation_reports=(initial_evaluation_path,),
    )
    initial_verification = _verify_clean_process(initial_package.output)

    repeat_ingest = _ingest_pass(
        pipeline,
        repository,
        paths,
        photo_root=photo_dir,
        label="frontier:repeat",
        screenings=screenings,
    )
    _require_ingest(repeat_ingest, "repeat_ingest")
    if repeat_ingest["model_calls"] != 0 or repeat_ingest["stages_run"]:
        raise FrontierDemonstrationError(
            "idempotency_reuse",
            "the repeat pass recomputed a stage or made a model call instead of reusing artifacts",
        )
    repeated_sources = _source_states(connection, manifest, include_deleted=False)
    repeat_world = _apply_world(
        connection, manifest, repeated_sources, demonstrate_stale_rejection=False
    )
    repeat_evaluation = _evaluation_document(
        manifest,
        stage="repeat",
        ingest=repeat_ingest,
        evidence=evidence,
        semantic=_semantic_and_supported_answer(connection, manifest),
        world=repeat_world,
        adaptation={"state": "reused", "build_reference": _build_reference(manifest)},
    )
    repeat_evaluation_path = output / "evaluation-repeat.json"
    _write_canonical(repeat_evaluation_path, repeat_evaluation)
    repeat_package = project_world_package(
        connection,
        workspace_id=manifest.workspace_id,
        actor=manifest.actor_id,
        output=output / "package-repeat",
        private_key=private_key,
        world_id=manifest.world_id,
        parent_merkle_root_sha256=initial_package.merkle_root_sha256,
        evaluation_reports=(repeat_evaluation_path,),
    )
    repeat_verification = _verify_clean_process(repeat_package.output)
    repeat_diff = diff_packages(initial_package.output, repeat_package.output)

    deleted_source = next(
        source for source in initial_sources if source.path == manifest.deletion_path
    )
    tombstone_id = repository.insert_tombstone(
        scope="capture",
        requested_by=manifest.actor_id,
        capture_id=deleted_source.capture_id,
        reason="authorized frontier demonstration source removal",
        blocklist_hash=False,
    )
    remaining_sources = _source_states(connection, manifest, include_deleted=False)
    if len(remaining_sources) != len(initial_sources) - 1:
        raise FrontierDemonstrationError(
            "source_deletion", "the tombstone did not remove exactly one live capture"
        )
    deletion_world = _apply_world(
        connection, manifest, remaining_sources, demonstrate_stale_rejection=False
    )
    deletion_semantic = _semantic_and_supported_answer(connection, manifest)
    deletion_evaluation = _evaluation_document(
        manifest,
        stage="after-deletion",
        ingest={
            "state": "not-rerun-after-deletion",
            "reason": "reingest would contradict the authorized capture tombstone",
        },
        evidence={
            "state": "fallback",
            "reason": "one source was deleted; surviving citations remain exact",
        },
        semantic=deletion_semantic,
        world=deletion_world,
        adaptation={"state": "preserved-reviewed-version"},
    )
    deletion_evaluation_path = output / "evaluation-after-deletion.json"
    _write_canonical(deletion_evaluation_path, deletion_evaluation)
    deletion_package = project_world_package(
        connection,
        workspace_id=manifest.workspace_id,
        actor=manifest.actor_id,
        output=output / "package-after-deletion",
        private_key=private_key,
        world_id=manifest.world_id,
        parent_merkle_root_sha256=repeat_package.merkle_root_sha256,
        evaluation_reports=(deletion_evaluation_path,),
    )
    deletion_verification = _verify_clean_process(deletion_package.output)
    deletion_diff = diff_packages(repeat_package.output, deletion_package.output)
    if not deletion_diff.changed:
        raise FrontierDemonstrationError(
            "deletion_package_diff", "source deletion did not change the package Merkle root"
        )

    terminal_fallbacks = _terminal_fallbacks(manifest, initial_sources)
    receipt: dict[str, Any] = {
        "profile": "exulanica-frontier-demonstration-receipt-v1",
        "status": "passed-with-declared-fallbacks" if terminal_fallbacks else "passed",
        "build_manifest": {
            "profile": manifest.profile,
            "canonical_sha256": manifest.canonical_sha256,
            "workspace_id": str(manifest.workspace_id),
            "world_id": manifest.world_id,
            "source_count": len(manifest.sources),
        },
        "formation": first_ingest,
        "evidence": evidence,
        "semantic_graph_and_answer": semantic,
        "world": initial_world,
        "adaptation": adaptation,
        "packages": {
            "initial": _package_receipt(initial_package.as_dict(), initial_verification),
            "repeat": _package_receipt(repeat_package.as_dict(), repeat_verification),
            "after_deletion": _package_receipt(deletion_package.as_dict(), deletion_verification),
        },
        "repeat": {
            "ingest": repeat_ingest,
            "world": repeat_world,
            "package_diff": repeat_diff.as_dict(),
            "root_change_reason": (
                "the package includes new reuse ledger events, evaluation state, and parent lineage"
            ),
        },
        "deletion": {
            "capture_id": str(deleted_source.capture_id),
            "manifest_path": deleted_source.path,
            "original_photo_file_deleted": False,
            "tombstone_id": str(tombstone_id),
            "remaining_regions": len(remaining_sources),
            "world": deletion_world,
            "package_diff": deletion_diff.as_dict(),
            "fallback": "deleted region omitted; surviving source-first regions remain available",
        },
        "precomputed_artifacts": [
            {
                "artifact_id": value.artifact_id,
                "bytes": value.bytes,
                "kind": value.kind,
                "producer": value.producer,
                "sha256": value.sha256,
                "state": "disclosed-not-consumed",
            }
            for value in manifest.precomputed_artifacts
        ],
        "terminal_fallbacks": terminal_fallbacks,
        "evaluation_reports": [
            initial_evaluation_path.name,
            repeat_evaluation_path.name,
            deletion_evaluation_path.name,
        ],
    }
    _write_canonical(output / "frontier-receipt.json", receipt)
    return receipt


def _authorized_screenings(
    repository: IngestRepository,
    manifest: BuildManifest,
    *,
    vision: VisionModel | None,
    depth: DepthModel | None,
) -> dict[uuid.UUID, uuid.UUID]:
    """Read existing authority before the first write; never infer it from a directory.

    Observation-only receipts are intentionally accepted for vision without geometry. The
    ordinary latest-screening helper filters for geometry and would hide those receipts.
    """
    if vision is None and depth is None:
        return {}
    permission = (
        "privacy_screening_allows_capture"
        if depth is not None
        else "privacy_screening_allows_observation"
    )
    result = {}
    for source in manifest.sources:
        capture = repository.live_capture_for_blob(BlobId(bytes.fromhex(source.sha256)))
        row = (
            None
            if capture is None
            else repository.connection.execute(
                "select screening_id from reconstruction_privacy_screening "
                "where workspace_id=%s and capture_id=%s and "
                + permission
                + "(workspace_id,capture_id,screening_id) "
                "order by screened_at desc,screening_id desc limit 1",
                (repository.workspace_id, capture.capture_id),
            ).fetchone()
        )
        if row is None:
            raise FrontierDemonstrationError(
                "privacy_authorization",
                f"Authorize and screen {source.path} through the existing intake/privacy "
                "workflow in this workspace before running configured models. "
                "The demonstration never creates screening receipts for supplied photographs.",
            )
        result[capture.capture_id] = row["screening_id"]
    return result


def _ingest_one(
    pipeline: PhotoIngestPipeline,
    repository: IngestRepository,
    path: Path,
    batch_id: uuid.UUID,
    screenings: Mapping[uuid.UUID, uuid.UUID],
) -> Any:
    """Reuse independently recorded authority; source bytes never establish their own consent."""
    intake = pipeline.ingest_intake(path.read_bytes(), filename=path.name, batch_id=batch_id)
    if intake.capture_id is None:
        return intake
    outcome = pipeline.ingest_derivatives(
        intake.capture_id,
        batch_id=batch_id,
        privacy_screening_id=screenings.get(intake.capture_id),
    )
    # `ingest_derivatives` names its outcome by capture id, because it is reached from a queue
    # that holds identifiers rather than paths. This pass came from a file and the receipt reports
    # a path relative to the photograph root, so the caller's own name is put back.
    outcome.path = path
    # One photograph is now two calls, and the receipt describes the photograph. Without this
    # merge the repeat pass reports intake as neither run nor reused, because the reuse happened
    # in the call whose outcome was discarded, and the demonstration would claim a stage vanished
    # rather than that it was satisfied from an existing row.
    for source, target in (
        (intake.stages_run, outcome.stages_run),
        (intake.stages_reused, outcome.stages_reused),
        (intake.stages_skipped, outcome.stages_skipped),
        (intake.stages_unavailable, outcome.stages_unavailable),
    ):
        for stage_key in source:
            if stage_key not in target:
                target.insert(0, stage_key)
    return outcome


def _ingest_pass(
    pipeline: PhotoIngestPipeline,
    repository: IngestRepository,
    paths: tuple[Path, ...],
    *,
    photo_root: Path,
    label: str,
    screenings: Mapping[uuid.UUID, uuid.UUID],
) -> dict[str, Any]:
    batch = IntakeBatch.open(repository, label=label)
    batch.declare_size(len(paths))
    report = IngestReport(pipeline_digest=pipeline.pipeline_digest, batch_id=batch.batch_id)
    for path in paths:
        report.outcomes.append(_ingest_one(pipeline, repository, path, batch.batch_id, screenings))
    continuity = run_continuity(repository, batch_id=batch.batch_id)
    batch.close(
        IntakeBatch.outcome_for(
            succeeded=len(report.outcomes) - len(report.failed), failed=len(report.failed)
        )
    )
    formation = [
        event.as_payload()
        for event in project_formation(
            repository.connection, repository.workspace_id, batch.batch_id
        )
    ]
    return {
        "batch_id": str(batch.batch_id),
        "pipeline_digest": report.pipeline_digest,
        "outcomes": [_outcome(value, photo_root) for value in report.outcomes],
        "stages_run": sorted({stage for item in report.outcomes for stage in item.stages_run}),
        "stages_reused": sorted(
            {stage for item in report.outcomes for stage in item.stages_reused}
        ),
        "stages_skipped": sorted(
            {stage for item in report.outcomes for stage in item.stages_skipped}
        ),
        "stages_unavailable": sorted(
            {stage for item in report.outcomes for stage in item.stages_unavailable}
        ),
        "model_calls": report.model_calls,
        "failed": len(report.failed),
        "formation_events": formation,
        "continuity": {
            "scene_groups": len(continuity.scenes.groups),
            "place_proposals": len(continuity.scenes.proposals),
            "ungrouped": continuity.scenes.ungrouped,
            "identity_questions": len(continuity.proposals.surfaced),
        },
    }


def _outcome(value: IngestOutcome, photo_root: Path) -> dict[str, Any]:
    return {
        "path": value.path.relative_to(photo_root).as_posix(),
        "capture_id": None if value.capture_id is None else str(value.capture_id),
        "blob_sha256": None if value.blob_id is None else value.blob_id.hex,
        "run_id": None if value.run_id is None else str(value.run_id),
        "stages_run": list(value.stages_run),
        "stages_reused": list(value.stages_reused),
        "stages_skipped": list(value.stages_skipped),
        "stages_unavailable": list(value.stages_unavailable),
        "model_calls": value.model_calls,
        "cost_usd": str(value.usd_estimate),
        "error": value.error,
        "failure_class": value.failure_class,
        "missing": value.missing,
        "unavailable": value.unavailable,
        "tombstoned": value.tombstoned,
    }


def _require_ingest(value: dict[str, Any], gate: str) -> None:
    if value["failed"]:
        raise FrontierDemonstrationError(gate, f"{value['failed']} source(s) failed")


def _source_states(
    connection: psycopg.Connection, manifest: BuildManifest, *, include_deleted: bool
) -> tuple[_SourceState, ...]:
    states: list[_SourceState] = []
    for ordinal, source in enumerate(manifest.sources):
        row = connection.execute(
            "select c.capture_id,s.span_id from capture c join evidence_span s "
            "on s.workspace_id=c.workspace_id and s.blob_sha256=c.blob_sha256 "
            "and s.modality='still_image' where c.workspace_id=%s and c.blob_sha256=%s "
            + ("" if include_deleted else "and c.deleted_at is null ")
            + "order by s.span_id limit 1",
            (manifest.workspace_id, bytes.fromhex(source.sha256)),
        ).fetchone()
        if row is None:
            continue
        rung_row = connection.execute(
            "select a.object_value from assertion a join predicate p using(predicate_id) "
            "where a.workspace_id=%s and p.key='reconstruction_rung_is' "
            "and a.status='active' and a.subject_ref->>'type'='capture' "
            "and a.subject_ref->>'id'=%s order by a.asserted_at desc,a.assertion_id desc limit 1",
            (manifest.workspace_id, str(row["capture_id"])),
        ).fetchone()
        rung = 4 if rung_row is None else int(rung_row["object_value"]["rung"])
        states.append(
            _SourceState(
                path=source.path,
                ordinal=ordinal,
                capture_id=row["capture_id"],
                span_id=row["span_id"],
                blob_sha256=source.sha256,
                rung=rung,
                rung_state=(
                    "fallback-no-reconstruction" if rung_row is None else "measured-assertion"
                ),
            )
        )
    return tuple(states)


def _open_exact_evidence(
    connection: psycopg.Connection,
    manifest: BuildManifest,
    store: LocalContentAddressedStore,
    source: _SourceState,
) -> dict[str, Any]:
    row = connection.execute(
        "select * from evidence_span where workspace_id=%s and span_id=%s",
        (manifest.workspace_id, source.span_id),
    ).fetchone()
    if row is None:
        raise FrontierDemonstrationError("evidence_resolution", "authorized span is absent")
    address = address_from_span_row(row)
    data = resolve_original_bytes(address, store)
    if hashlib.sha256(data).hexdigest() != source.blob_sha256:
        raise FrontierDemonstrationError("evidence_resolution", "resolved bytes changed digest")
    events = connection.execute(
        "select pe.event_id,pe.seq,pe.type,pe.stage_key,pe.stage_version,pe.model_ref,"
        "pe.params_digest,pe.input_artifact_ids,pe.output_artifact_ids,pr.run_id,pr.status "
        "from pipeline_event pe join pipeline_run pr using(run_id) "
        "where pr.workspace_id=%s and pr.capture_id=%s order by pr.run_id,pe.seq",
        (manifest.workspace_id, source.capture_id),
    ).fetchall()
    return {
        "state": "opened-and-hash-verified",
        "capture_id": str(source.capture_id),
        "span_id": str(source.span_id),
        "span_digest": address.span_digest_hex,
        "uri": address.to_uri(),
        "blob_sha256": address.blob_id.hex,
        "resolved_bytes": len(data),
        "provenance_events": [
            {
                "event_id": str(value["event_id"]),
                "run_id": str(value["run_id"]),
                "sequence": value["seq"],
                "type": str(value["type"]),
                "stage_key": value["stage_key"],
                "stage_version": value["stage_version"],
                "model_ref": value["model_ref"],
                "params_sha256": _hex(value["params_digest"]),
                "input_artifact_ids": [str(item) for item in value["input_artifact_ids"]],
                "output_artifact_ids": [str(item) for item in value["output_artifact_ids"]],
                "run_status": value["status"],
            }
            for value in events
        ],
    }


def _semantic_and_supported_answer(
    connection: psycopg.Connection, manifest: BuildManifest
) -> dict[str, Any]:
    graph = read_snapshot(connection, manifest.workspace_id)
    plan = SelectionPlan(intent=Intent.CAPTURES)
    selected = execute(
        connection,
        validate(
            connection,
            plan,
            Session(workspace_id=manifest.workspace_id, actor=manifest.actor_id),
        ),
    )
    packet = build_packet(connection, selected, workspace_id=manifest.workspace_id)
    answer = validate_answer(render_deterministic_answer(packet), packet)
    return {
        "state": "supported-and-validated",
        "graph": graph.model_dump(mode="json"),
        "selection": {
            "intent": str(selected.intent),
            "total_matched": selected.total_matched,
            "capture_ids": [str(value.capture_id) for value in selected.captures],
        },
        "packet": {
            "citable": packet.citable,
            "item_count": len(packet.items),
            "citation_uris": [value.uri for value in packet.items],
        },
        "answer": answer.model_dump(mode="json"),
    }


def _candidate_for(
    connection: psycopg.Connection,
    manifest: BuildManifest,
    sources: tuple[_SourceState, ...],
) -> SpatialCandidate:
    if not sources:
        raise FrontierDemonstrationError("world_composition", "no live source remains")
    graph = read_snapshot(connection, manifest.workspace_id).model_dump(mode="json")
    graph_sha256 = sha256_of_canonical(graph).hex()
    artifacts = connection.execute(
        "select a.artifact_id,a.kind,a.stage_key,a.stage_version,a.params_digest,a.input_digest,"
        "a.content_sha256,a.byte_size,a.needs_repair from artifact a join capture c "
        "on c.workspace_id=a.workspace_id and c.blob_sha256=a.source_blob_sha256 "
        "where a.workspace_id=%s and c.deleted_at is null order by a.artifact_id",
        (manifest.workspace_id,),
    ).fetchall()
    reconstruction_sha256 = sha256_of_canonical(
        [
            {
                "artifact_id": str(value["artifact_id"]),
                "kind": value["kind"],
                "stage_key": value["stage_key"],
                "stage_version": value["stage_version"],
                "params_sha256": _hex(value["params_digest"]),
                "input_sha256": _hex(value["input_digest"]),
                "content_sha256": _hex(value["content_sha256"]),
                "bytes": value["byte_size"],
                "needs_repair": value["needs_repair"],
            }
            for value in artifacts
        ]
    ).hex()

    region_data: list[dict[str, Any]] = []
    for source in sources:
        suffix = hashlib.sha256(f"{source.path}\0{source.blob_sha256}".encode()).hexdigest()[:20]
        region_data.append(
            {
                "source": source,
                "region_id": f"region-{suffix}",
                "element_id": f"element:region-{suffix}:root",
                "destination_id": f"destination:region-{suffix}",
            }
        )
    by_region = sorted(region_data, key=lambda value: value["region_id"])
    elements = []
    for value in by_region:
        source = value["source"]
        module = f"region.rung-{source.rung}"
        elements.append(
            {
                "element_id": value["element_id"],
                "owner": {"kind": "region", "id": value["region_id"]},
                "module": {"key": module, "version": 1, "requested_key": module},
                "lineage": {
                    "recipe_key": "region.source-first",
                    "recipe_version": 1,
                    "slot_key": "root",
                },
                "collision": {"kind": "circle", "radius_mm": 1_000},
                "evidence": {"kind": "span", "span_id": str(source.span_id)},
                "attachment": None,
                "streaming_key": f"world-asset:{module}@1",
            }
        )
    destinations = sorted(
        [
            {
                "destination_id": value["destination_id"],
                "region_id": value["region_id"],
                "required": True,
            }
            for value in region_data
        ],
        key=lambda value: value["destination_id"],
    )
    in_source_order = sorted(region_data, key=lambda value: value["source"].ordinal)
    edges = sorted(
        [
            {
                "from": left["destination_id"],
                "to": right["destination_id"],
                "kind": "field",
                "max_slope_millidegrees": 0,
            }
            for left, right in pairwise(in_source_order)
        ],
        key=lambda value: (value["from"], value["to"], value["kind"]),
    )
    topology = {
        "schema_version": 1,
        "world_id": manifest.world_id,
        "regions": [{"region_id": value["region_id"]} for value in by_region],
        "elements": elements,
        "navigation": {
            "agent_radius_mm": 300,
            "maximum_slope_millidegrees": 15_000,
            "destinations": destinations,
            "edges": edges,
        },
        "dependencies": [],
    }
    layout = {
        "schema_version": 1,
        "layout_version": 1,
        "regions": [
            {"region_id": value["region_id"], "creation_ordinal": value["source"].ordinal}
            for value in in_source_order
        ],
    }
    placement_elements = sorted(
        [
            {
                "element_id": value["element_id"],
                "x_mm": value["source"].ordinal * 10_000,
                "y_mm": 0,
                "z_mm": 0,
                "yaw_microradians": 0,
                "scale_milli": 1_000,
            }
            for value in region_data
        ],
        key=lambda value: value["element_id"],
    )
    destination_placements = sorted(
        [
            {
                "destination_id": value["destination_id"],
                "x_mm": value["source"].ordinal * 10_000,
                "y_mm": 1_600,
                "z_mm": 0,
            }
            for value in region_data
        ],
        key=lambda value: value["destination_id"],
    )
    placement = {
        "schema_version": 1,
        "coordinate_unit": "millimetre",
        "elements": placement_elements,
        "destinations": destination_placements,
    }
    neighborhood = {
        "schema_version": 1,
        "neighborhood_version": 1,
        "layout_version": 1,
        "neighborhoods": [
            {
                "neighborhood_id": "neighborhood:0",
                "region_ids": sorted(value["region_id"] for value in region_data),
            }
        ],
    }
    return SpatialCandidate(
        graph_sha256,
        reconstruction_sha256,
        topology,
        layout,
        placement,
        neighborhood,
        composer_key="frontier-world-composer",
        composer_version=1,
    )


def _apply_world(
    connection: psycopg.Connection,
    manifest: BuildManifest,
    sources: tuple[_SourceState, ...],
    *,
    demonstrate_stale_rejection: bool,
) -> dict[str, Any]:
    candidate = _candidate_for(connection, manifest, sources)
    digests = validate_candidate(candidate)
    repository = WorldStructureRepository(
        connection, manifest.workspace_id, world_id=manifest.world_id
    )
    current = repository.current()
    if current is not None and current.digests.snapshot_sha256 == digests.snapshot_sha256:
        snapshot = current
        state = "reused"
        stale = "previously-demonstrated" if not demonstrate_stale_rejection else "not-needed"
    else:
        preview = repository.preview(candidate, proposed_by=manifest.actor_id)
        stale_preview = (
            repository.preview(candidate, proposed_by=manifest.actor_id)
            if demonstrate_stale_rejection
            else None
        )
        snapshot = repository.apply(
            preview.preview_id,
            base_snapshot_id=preview.base_snapshot_id,
            base_graph_sha256=preview.base_graph_sha256,
            base_reconstruction_sha256=preview.base_reconstruction_sha256,
            committed_by=manifest.actor_id,
        )
        state = "applied"
        stale = "not-requested"
        if stale_preview is not None:
            try:
                repository.apply(
                    stale_preview.preview_id,
                    base_snapshot_id=stale_preview.base_snapshot_id,
                    base_graph_sha256=stale_preview.base_graph_sha256,
                    base_reconstruction_sha256=stale_preview.base_reconstruction_sha256,
                    committed_by=manifest.actor_id,
                )
            except StaleStructuralBase:
                stale = "rejected"
            else:  # pragma: no cover - a broken compare-and-swap contract
                raise FrontierDemonstrationError(
                    "structural_stale_rejection", "two previews from one base both became current"
                )
    return {
        "state": state,
        "snapshot_id": str(snapshot.snapshot_id),
        "snapshot_sha256": snapshot.digests.snapshot_sha256,
        "graph_sha256": snapshot.candidate.graph_sha256,
        "reconstruction_sha256": snapshot.candidate.reconstruction_sha256,
        "stale_preview": stale,
        "regions": [
            {
                "capture_id": str(source.capture_id),
                "manifest_path": source.path,
                "rung": source.rung,
                "rung_state": source.rung_state,
            }
            for source in sources
        ],
    }


def _adapt_world(connection: psycopg.Connection, manifest: BuildManifest) -> dict[str, Any]:
    repository = WorldStyleRepository(connection, manifest.workspace_id, world_id=manifest.world_id)
    reference = _build_reference(manifest)
    existing = [
        value
        for value in repository.versions()
        if value.rollback_target_version_id is not None
        and value.provenance is not None
        and value.provenance.origin_reference == reference
    ]
    if existing:
        return {
            "state": "reused",
            "build_reference": reference,
            "rollback_version_id": str(existing[-1].version_id),
        }
    initial = repository.current()
    proposal_provenance = ProposalProvenance(
        ProposalOrigin.COMPANION,
        manifest.actor_id,
        manifest.adaptation.origin_reference,
    )
    rollback_provenance = ProposalProvenance(ProposalOrigin.USER, manifest.actor_id, reference)

    draft = repository.preview(
        _style_proposal(manifest, initial, proposal_provenance, parameters={})
    )
    refined = repository.preview(
        _style_proposal(
            manifest,
            initial,
            proposal_provenance,
            parameters=manifest.adaptation.parameters,
            refines_proposal_id=draft.proposal.proposal_id,
        )
    )
    stale = repository.preview(
        _style_proposal(
            manifest,
            initial,
            proposal_provenance,
            parameters=manifest.adaptation.parameters,
            refines_proposal_id=draft.proposal.proposal_id,
        )
    )
    repository.discard(draft.preview_id, discarded_by=manifest.actor_id)
    applied = repository.apply(
        refined.preview_id,
        base_style_version_id=initial.version_id,
        base_topology_digest=initial.topology_digest,
        applied_by=manifest.actor_id,
    )
    try:
        repository.apply(
            stale.preview_id,
            base_style_version_id=initial.version_id,
            base_topology_digest=initial.topology_digest,
            applied_by=manifest.actor_id,
        )
    except StaleStyleVersion:
        stale_state = "rejected"
    else:  # pragma: no cover - a broken compare-and-swap contract
        raise FrontierDemonstrationError(
            "style_stale_rejection", "two previews from one style base both became current"
        )
    rolled_back = repository.rollback(
        initial.version_id,
        base_style_version_id=applied.version_id,
        base_topology_digest=applied.topology_digest,
        provenance=rollback_provenance,
    )
    draft_record = repository.proposal(draft.proposal.proposal_id)
    refined_record = repository.proposal(refined.proposal.proposal_id)
    stale_record = repository.proposal(stale.proposal.proposal_id)
    return {
        "state": "completed",
        "build_reference": reference,
        "conversational_proposal_id": str(draft.proposal.proposal_id),
        "discard_preview_id": str(draft.preview_id),
        "discard_status": draft_record.status,
        "refinement_proposal_id": str(refined.proposal.proposal_id),
        "refines_proposal_id": str(refined_record.proposal.refines_proposal_id),
        "refinement_status": refined_record.status,
        "applied_version_id": str(applied.version_id),
        "stale_preview": stale_state,
        "stale_proposal_status": stale_record.status,
        "rollback_version_id": str(rolled_back.version_id),
        "rollback_target_version_id": str(initial.version_id),
        "current_semantics_restored": (
            rolled_back.global_style == initial.global_style
            and rolled_back.region_styles == initial.region_styles
        ),
        "proposal_provenance": {
            "origin": proposal_provenance.origin.value,
            "origin_reference": proposal_provenance.origin_reference,
            "model_id": manifest.adaptation.model_id,
            "prompt_version": manifest.adaptation.prompt_version,
            "reference_ids": list(manifest.adaptation.reference_ids),
        },
        "recipe_binding": dict(refined_record.recipe_binding),
        "capability_mapping": dict(refined_record.capability_mapping),
    }


def _style_proposal(
    manifest: BuildManifest,
    current: Any,
    provenance: ProposalProvenance,
    *,
    parameters: Mapping[str, bool | int | str],
    refines_proposal_id: uuid.UUID | None = None,
) -> StyleProposal:
    return StyleProposal(
        proposal_id=uuid.uuid4(),
        provenance=provenance,
        scope=StyleScope("global"),
        base_style_version_id=current.version_id,
        base_topology_digest=current.topology_digest,
        profile=StyleReference(
            manifest.adaptation.profile_id,
            manifest.adaptation.profile_version,
            parameters,
        ),
        reference_ids=manifest.adaptation.reference_ids,
        model_id=manifest.adaptation.model_id,
        prompt_version=manifest.adaptation.prompt_version,
        refines_proposal_id=refines_proposal_id,
    )


def _build_reference(manifest: BuildManifest) -> str:
    return f"frontier-build:{manifest.canonical_sha256}"


def _evaluation_document(
    manifest: BuildManifest,
    *,
    stage: str,
    ingest: dict[str, Any],
    evidence: dict[str, Any],
    semantic: dict[str, Any],
    world: dict[str, Any],
    adaptation: dict[str, Any],
) -> dict[str, Any]:
    return {
        "profile": "exulanica-frontier-demonstration-evaluation-v1",
        "stage": stage,
        "build_manifest_sha256": manifest.canonical_sha256,
        "operational_gates": {
            "ingest": ingest.get("state", "passed" if not ingest.get("failed") else "failed"),
            "evidence": evidence.get("state", "unavailable"),
            "semantic_answer": semantic["state"],
            "world": world["state"],
            "adaptation": adaptation["state"],
        },
        "formation": {
            "model_calls": ingest.get("model_calls"),
            "stages_run": ingest.get("stages_run", []),
            "stages_reused": ingest.get("stages_reused", []),
            "stages_skipped": ingest.get("stages_skipped", []),
            "stages_unavailable": ingest.get("stages_unavailable", []),
        },
        "world_regions": world["regions"],
        "corpus_metrics": {
            "state": "unavailable",
            "reason": (
                "this command has no consented OGC-1 labels or blind split and does not "
                "fabricate them"
            ),
        },
    }


def _verify_clean_process(package: Path) -> dict[str, Any]:
    environment = {
        key: value
        for key, value in os.environ.items()
        if "DATABASE_URL" not in key and key not in {"PGPASSWORD", "PGSERVICE"}
    }
    result = subprocess.run(
        [sys.executable, "-m", "exulanica.world_package.cli", "verify", str(package)],
        cwd=package.parent,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise FrontierDemonstrationError(
            "clean_process_verification", result.stderr.strip() or "verifier returned nonzero"
        )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FrontierDemonstrationError(
            "clean_process_verification", "verifier did not emit JSON"
        ) from exc
    return {
        "state": "verified",
        "database_environment_removed": True,
        "report": report,
    }


def _package_receipt(projection: dict[str, Any], verification: dict[str, Any]) -> dict[str, Any]:
    return {"projection": projection, "clean_process_verification": verification}


def _terminal_fallbacks(
    manifest: BuildManifest, sources: tuple[_SourceState, ...]
) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    if manifest.pipeline.vision == "unavailable":
        values.append(
            {
                "gate": "vision",
                "state": "unavailable",
                "fallback": "capture-supported facts and deterministic supported answer",
            }
        )
    if manifest.pipeline.depth == "unavailable":
        values.append(
            {
                "gate": "reconstruction",
                "state": "unavailable",
                "fallback": "source-first rung 4",
            }
        )
    if not manifest.precomputed_artifacts:
        values.append(
            {
                "gate": "precomputed-artifacts",
                "state": "none-declared",
                "fallback": "no precomputed work was consumed",
            }
        )
    if any(value.rung_state == "fallback-no-reconstruction" for value in sources):
        values.append(
            {
                "gate": "region-rung",
                "state": "fallback",
                "fallback": "one or more regions entered at source-first rung 4",
            }
        )
    return values


def _write_canonical(path: Path, value: Any) -> None:
    path.write_bytes(canonical_json(value))


def _hex(value: Any) -> str | None:
    return None if value is None else bytes(value).hex()
