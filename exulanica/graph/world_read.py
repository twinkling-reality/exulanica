"""The World Read API bundle: what a generative world model may condition on, and nothing else.

Roadmap Phase 10 capability 1. A generative world model of 2026 is stateless imagination: it dreams
a plausible world for a session and cannot say which of its pixels are real. This bundle is the
memory it lacks, in the one form it can consume: for one reconstructed scene, the posed views with
their recovered calibration, the geometry that was actually built from those photographs, the slice
of the durable region graph the scene sits in, the rung labels that say how much of it was earned,
and the consent state that says who may see it.

Four decisions are load-bearing and are the reason this module exists rather than a serialiser.

**Numbers are decimal strings.** ``exulanica.canonical`` refuses floats in a digest input outright,
because IEEE 754 has no canonical decimal rendering that every JSON writer agrees on, and this
bundle's whole value is that a recipient can recompute its digest in another language and get the
same answer. The existing precedent in this repository is a fixed-precision decimal string
(``exulanica.evaluation.synthetic_multiview._decimal_matrix``), and that is what is used here, at a
precision the bundle states about itself rather than leaving the reader to count digits. Integers
that are counts stay integers.

**Geometry is not evidence.** Every geometry entry carries the tier that produced it and no support
spans. That is invariant 2 in the shape a machine can check: a consumer looking for the bytes
behind a claim will not find a point map offered as one. The evidence path is separate and goes
through ``/evidence/{span_id}``, which is what the click-to-evidence work builds on.

**The scene is the address, and that is a limitation, not a design.** The roadmap says "for an
entity, a place and a time". A ``place`` that persists across captures is Phase 10 capability 3 and
does not exist yet, so v1 addresses a reconstruction scene, which is a set of photographs of one
place at one capture. The bundle says so in its own ``addressing`` block rather than implying more.

**Consent is asked once, through one function.** See :mod:`exulanica.graph.read_consent`. While no
per-person layer exists, the bundle is ``internal_only`` and says what that basis does not
establish.

**Two digests, not one.** ``recorded_sha256`` covers the observed world alone; ``bundle_sha256``
covers the whole response including anything a model has since generated. A generation cites the
first, so filing it does not change the thing it cited and two models can read the same observed
world and both say so. A recipient verifying the payload in front of it checks the second.

The recorded digest's input is the keys named in ``recorded_keys``, listed in the bundle rather than
described, because a recipient who has to infer which keys were excluded is a recipient who cannot
check the digest. That was measured, not anticipated: the first version excluded ``generated`` by
description and a recomputation over the real bowl scene disagreed, because the wire bundle also
carries ``recorded_sha256`` itself.

The scene read here is the same ``reconstruction_scene_rows`` that builds the graph payload Atlas
draws. That is deliberate rather than incidental: a bundle
assembled from its own queries would eventually disagree with the world on screen about which
photographs registered or which geometry is available, and the disagreement would be invisible from
either side.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.graph.payload import (
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGeometryReferenceRow,
)
from exulanica.graph.read_consent import consent_for_captures, person_consent_state, release_state
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.wire_numbers import (
    NUMBER_DECIMALS,
    NUMBER_ENCODING,
)
from exulanica.graph.wire_numbers import (
    decimal_string as _decimal,
)
from exulanica.graph.wire_numbers import (
    decimal_strings as _decimals,
)
from exulanica.store import ContentAddressedStore
from exulanica.world import DEFAULT_WORLD_ID, WorldStructureRepository

__all__ = [
    "NUMBER_DECIMALS",
    "WORLD_READ_PROFILE",
    "world_read_bundle",
]

WORLD_READ_PROFILE: Final = "exulanica.world-read-bundle/v1"


_REGION_SLOTS: Final = """
select ts.region_id,
       ts.slot_key,
       ts.evidence_span_id,
       ts.missing_reason,
       c.capture_id
  from world_topology_source ts
  left join evidence_span es
    on es.workspace_id = ts.workspace_id
   and es.span_id = ts.evidence_span_id
  left join capture c
    on c.workspace_id = ts.workspace_id
   and c.blob_sha256 = es.blob_sha256
   and c.deleted_at is null
 where ts.workspace_id = %s
   and ts.world_id = %s
   and ts.topology_digest = %s
 order by ts.region_id nulls last, ts.slot_key
"""


def _reference(reference: SceneGeometryReferenceRow | None) -> dict[str, Any] | None:
    if reference is None:
        return None
    return {
        "href": reference.href,
        "authorization": reference.authorization,
        "content_sha256": reference.content_sha256,
        "byte_size": reference.byte_size,
    }


def _view(member: ReconstructionSceneMemberRow, consent: dict[str, Any]) -> dict[str, Any]:
    """One posed view: where the camera stood and what it saw through.

    A member with no recovered camera still appears, carrying ``camera: null`` and its exclusion
    reason. Dropping it would let a consumer count the views it received and conclude the scene had
    that many photographs, which is the arithmetic every honest-fallback rule in this codebase
    exists to prevent.
    """
    camera: dict[str, Any] | None = None
    if member.recovered_camera is not None:
        calibration = member.recovered_camera.calibration
        camera = {
            "scene_from_camera_row_major": _decimals(
                member.recovered_camera.scene_from_camera_row_major
            ),
            "projection": member.recovered_camera.projection,
            "calibration": {
                "model": calibration.model,
                "width": calibration.width,
                "height": calibration.height,
                "fx": _decimal(calibration.fx),
                "fy": _decimal(calibration.fy),
                "cx": _decimal(calibration.cx),
                "cy": _decimal(calibration.cy),
                "parameters": _decimals(calibration.parameters),
            },
        }
    return {
        "capture_id": str(member.capture_id),
        "ordinal": member.ordinal,
        "registered": member.registered,
        "camera": camera,
        "exclusion_reason": member.exclusion_reason,
        "consent": consent,
    }


def _geometry(scene: ReconstructionSceneRow) -> list[dict[str, Any]]:
    """Every buildable geometry entry for the scene, each labelled with the tier that made it.

    ``tier`` is ``recorded`` throughout, because every entry here descends from photographs through
    reviewed deterministic or model stages that are bound to those exact bytes. Content a model
    imagined is not in this list at all: it is the bundle's separate ``generated`` key, for the
    same reason the graph payload keeps ``generated_geometry`` apart from ``trained_geometry``. A
    consumer must write code that reads a field whose name says what it is before it can condition
    on imagination, and a consumer that ignores the new key sees exactly the recorded world.
    ``tier`` stays on every entry so that an entry separated from its list still says what it is.
    """
    entries: list[dict[str, Any]] = []
    for member in scene.members:
        placement = member.placement
        if placement is None:
            continue
        entries.append(
            {
                "kind": "point_map",
                "tier": "recorded",
                "capture_id": str(member.capture_id),
                "artifact_id": str(placement.artifact_id),
                "content_sha256": placement.content_sha256,
                "container": placement.container,
                "scene_from_local_row_major": _decimals(placement.scene_from_opm_row_major),
                "local_units_to_scene_units": _decimal(placement.local_units_to_scene_units),
                "scale_status": placement.scale_status,
                "state": placement.state,
                "reference": _reference(placement.reference),
            }
        )
    trained = scene.trained_geometry
    if trained is not None:
        entries.append(
            {
                "kind": "trained_geometry",
                "tier": "recorded",
                "capture_id": None,
                "artifact_id": str(trained.artifact_id),
                "content_sha256": trained.content_sha256,
                "container": trained.container,
                "scene_from_local_row_major": _decimals(trained.scene_from_asset_row_major),
                "bounds": {
                    "min": _decimals(trained.bounds["min"]),
                    "max": _decimals(trained.bounds["max"]),
                },
                "state": trained.state,
                "reference": _reference(trained.reference),
                "quality": {
                    "heldout_views": trained.quality.heldout_views,
                    "psnr": _decimal(trained.quality.psnr),
                    "ssim": _decimal(trained.quality.ssim),
                    "lpips": _decimal(trained.quality.lpips),
                    "coverage_fraction": _decimal(trained.quality.coverage_fraction),
                    "floaters_fraction": _decimal(trained.quality.floaters_fraction),
                    "iterations_completed": trained.quality.iterations_completed,
                    "gpu": trained.quality.gpu,
                },
            }
        )
    return entries


def _generated(scene: ReconstructionSceneRow) -> list[dict[str, Any]]:
    """What a model imagined for this scene, in its own list and never in ``geometry``.

    Each entry carries the model, its version, the prompt digest and the exact conditioning
    digests it received, so a recipient can recompute the bundle the model actually read and check
    the claim rather than accept it. ``seam`` is the sentence a viewer is shown.

    An entry whose receipt did not verify appears with ``state: invalid`` and its reason rather
    than being dropped, because a dropped generation looks identical to no generation, and the one
    thing a reader must be able to trust is that an empty list means nothing was generated.
    """
    return [
        {
            "tier": "generated",
            "artifact_id": str(row.artifact_id),
            "receipt_sha256": row.receipt_sha256,
            "state": row.state,
            "state_reason": row.state_reason,
            "model": None if row.model is None else row.model.model_dump(),
            "prompt_sha256": row.prompt_sha256,
            "conditioning": list(row.conditioning),
            "world_read_bundle_sha256": row.world_read_bundle_sha256,
            "container": row.container,
            "content_sha256": row.content_sha256,
            "byte_size": row.byte_size,
            "seam": row.seam,
            "epistemics": {
                "citable": False,
                "promotes_rung": False,
                "is_evidence": False,
            },
        }
        for row in scene.generated_geometry
    ]


def _region_graph(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    capture_ids: set[uuid.UUID],
    *,
    world_id: str,
) -> dict[str, Any]:
    """The slice of the durable region graph this scene's photographs occupy.

    Regions are a real server concept, held by the structural authority in
    ``exulanica.world.structure_repository`` as an immutable snapshot with its own digests. The
    slice is derived by joining topology source slots to captures through their evidence spans,
    which is the same authority the world itself composes from.

    When no structure has been committed, this returns an explicit ``unavailable`` state rather
    than an empty region list. An empty list would read as "this scene belongs to no region", which
    is a claim; "no structural snapshot exists in this workspace" is the fact.
    """
    repository = WorldStructureRepository(connection, workspace, world_id=world_id)
    snapshot = repository.effective_current()
    if snapshot is None:
        return {
            "state": "unavailable",
            "reason": (
                "no current structural snapshot exists in this workspace, so no region owns "
                "these photographs yet"
            ),
            "world_id": world_id,
            "regions": [],
        }

    topology_digest = snapshot.digests.topology_sha256
    rows = connection.execute(_REGION_SLOTS, (workspace, world_id, topology_digest)).fetchall()

    declared = [
        str(region["region_id"])
        for region in snapshot.candidate.topology.get("regions", [])
        if isinstance(region, dict) and isinstance(region.get("region_id"), str)
    ]
    by_region: dict[str, dict[str, Any]] = {
        region_id: {"region_id": region_id, "member_capture_ids": [], "unresolved_slots": 0}
        for region_id in declared
    }
    for row in rows:
        region_id = row["region_id"]
        if region_id is None or region_id not in by_region:
            continue
        capture_id = row["capture_id"]
        if capture_id is None:
            by_region[region_id]["unresolved_slots"] += 1
        elif capture_id in capture_ids:
            by_region[region_id]["member_capture_ids"].append(str(capture_id))

    regions = []
    for region_id in sorted(by_region):
        entry = by_region[region_id]
        entry["member_capture_ids"] = sorted(set(entry["member_capture_ids"]))
        entry["holds_this_scene"] = bool(entry["member_capture_ids"])
        regions.append(entry)

    return {
        "state": "available",
        "world_id": world_id,
        "snapshot_id": str(snapshot.snapshot_id),
        "revision": snapshot.revision,
        "topology_sha256": topology_digest,
        "layout_sha256": snapshot.digests.layout_sha256,
        "placement_sha256": snapshot.digests.placement_sha256,
        "neighborhood_sha256": snapshot.digests.neighborhood_sha256,
        "snapshot_sha256": snapshot.digests.snapshot_sha256,
        "regions": regions,
    }


def _scene_block(scene: ReconstructionSceneRow) -> dict[str, Any]:
    return {
        "scene_id": str(scene.scene_id),
        "member_digest": scene.member_digest,
        "pose_receipt_sha256": scene.pose_receipt_sha256,
        "placement_receipt_sha256": scene.placement_receipt_sha256,
        "gate_digest": scene.gate_digest,
        "member_count": scene.member_count,
        "registered_member_count": scene.registered_member_count,
        "receipt_state": scene.receipt_state,
        "placement_state": scene.placement_state,
        "rendering_substrate": scene.rendering_substrate,
    }


def _rungs(scene: ReconstructionSceneRow) -> dict[str, Any]:
    """The ladder labels, kept exactly as the graph reports them.

    ``recorded`` is the durable claim from the gate's receipt chain. ``displayed`` is what can
    actually be drawn right now, which is lower whenever bytes are missing. They are separate keys
    because collapsing them is how a system claims a rung it did not earn.
    """
    return {
        "recorded": scene.recorded_rung,
        "recorded_reasons": list(scene.recorded_reasons),
        "displayed": scene.displayed_rung,
        "display_reasons": list(scene.display_reasons),
        "ladder": (
            "4 source-first photographs, 3 posed point maps, 2 corridor, 1 splat with "
            "independently validated scale and coverage; a lower number is a stronger claim"
        ),
    }


def world_read_bundle(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene_id: uuid.UUID,
    store: ContentAddressedStore | None,
    *,
    world_id: str = DEFAULT_WORLD_ID,
) -> dict[str, Any] | None:
    """Assemble the digest-bound read bundle for one scene, or ``None`` if it is not readable.

    ``None`` covers both "no such scene" and "a scene in another workspace", because the route
    above turns both into the same 404: the surface is not an existence oracle.
    """
    scenes = [
        row
        for row in reconstruction_scene_rows(connection, workspace, store)
        if row.scene_id == scene_id
    ]
    if not scenes:
        return None
    scene = scenes[0]

    capture_ids = [member.capture_id for member in scene.members]
    consent = consent_for_captures(connection, workspace, capture_ids)

    bundle: dict[str, Any] = {
        "profile": WORLD_READ_PROFILE,
        "number_encoding": NUMBER_ENCODING,
        "addressing": {
            "by": "reconstruction_scene",
            "scene_id": str(scene.scene_id),
            "limitation": (
                "a scene is one set of photographs of one place at one capture. Addressing by a "
                "place that persists across captures and by time is Phase 10 capability 3 and is "
                "not implemented; this bundle does not claim it"
            ),
        },
        "scene": _scene_block(scene),
        "rungs": _rungs(scene),
        "views": [_view(member, consent[str(member.capture_id)]) for member in scene.members],
        "geometry": _geometry(scene),
        "generated": _generated(scene),
        "region_graph": _region_graph(
            connection,
            workspace,
            {member.capture_id for member in scene.members},
            world_id=world_id,
        ),
        "consent": {
            "basis": "human-screening-receipt",
            "person_consent": person_consent_state(),
            "per_capture": consent,
        },
        "release": release_state(),
        "epistemics": {
            "evidence": (
                "original capture bytes, reached through /evidence/{span_id}. Nothing in this "
                "bundle is evidence"
            ),
            "geometry_is_derived": (
                "every geometry entry is a derivative of the photographs, produced by a reviewed "
                "stage bound to their exact bytes. It visualises what was observed; it does not "
                "support a claim"
            ),
            "physical_scale": (
                "unvalidated. Scene units are the recovered COLMAP frame, not metres, and no "
                "independent physical reference has been associated with these points"
            ),
        },
    }
    # Two digests, and the difference is the whole point. `recorded_sha256` covers the observed
    # world alone, so it is the digest a generation is conditioned on: filing a generation must not
    # change the thing that generation cited, and two models must be able to read the same observed
    # world and each say so. `bundle_sha256` covers the whole response, including generations,
    # which is what a recipient verifying this exact payload checks.
    #
    # The covered keys are LISTED rather than described as "everything except the generated list".
    # MEASURED 2026-09-06 against the retained bowl scene: a recipient recomputing the recorded
    # digest by removing `generated` got a different answer, because the wire bundle also carries
    # `recorded_sha256` itself, which was not an input to its own hash. A self-referential digest
    # whose input a recipient has to infer is a digest they cannot check. Naming the keys makes the
    # recipe exact and makes adding a key to the recorded world a deliberate edit here.
    bundle["recorded_keys"] = sorted(key for key in bundle if key != "generated")
    bundle["recorded_sha256"] = sha256_of_canonical(
        {key: bundle[key] for key in bundle["recorded_keys"]}
    ).hex()
    return {
        "profile": WORLD_READ_PROFILE,
        "bundle": bundle,
        "bundle_sha256": sha256_of_canonical(bundle).hex(),
    }


def bundle_bytes(envelope: dict[str, Any]) -> bytes:
    """The exact canonical bytes a recipient must hash to reproduce ``bundle_sha256``.

    Exported so the route and any test hash the same thing the builder did, rather than each
    re-deriving a serialisation and agreeing by luck.
    """
    return canonical_json(envelope["bundle"])
