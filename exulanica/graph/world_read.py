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

**Two addresses now, and a scene is still one of them.** The roadmap says "for an entity, a place
and a time". A place that persists across captures exists as of ``docs/place-identity.md`` and
:mod:`exulanica.graph.places`, so this bundle answers to two addresses: a reconstruction scene,
which is one set of photographs of one place at one capture, and a place with a time, which
resolves to the version of that place in force at that time and puts that scene's bundle in place.
The scene address is unchanged in meaning, because a scene is still a real thing after it joins a
place and its receipts are bound to inputs no place can be part of. What is still unaddressable is
an **entity**: nothing routes from a person or an object to a bundle, and the ``addressing`` block
says that rather than leaving a reader to find it out.

**Consent is asked once, through one function.** See :mod:`exulanica.graph.read_consent`.
The bundle remains ``internal_only``: recorded presentation receipts and source lineage do
not authenticate redistribution authority.

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

import datetime as dt
import uuid
from dataclasses import asdict
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.graph.payload import (
    ReconstructionSceneMemberRow,
    ReconstructionSceneRow,
    SceneGeometryReferenceRow,
)
from exulanica.graph.places import (
    PlaceHistory,
    PlaceVersion,
    SceneMembership,
    place_history,
    scene_place_membership,
)
from exulanica.graph.read_consent import (
    consent_for_captures,
    person_consent_state,
    release_state,
    scene_consent_basis,
)
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
from exulanica.graph.world_read_evidence import recorded_evidence
from exulanica.graph.world_read_views import descriptor
from exulanica.store import ContentAddressedStore
from exulanica.world import DEFAULT_WORLD_ID, WorldStructureRepository

__all__ = [
    "NUMBER_DECIMALS",
    "WORLD_READ_PROFILE",
    "place_read_bundle",
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


#: What a bundle can be addressed by, carried in every bundle rather than described only here. A
#: recipient holding one response and no documentation has to be able to ask for the next thing.
_ADDRESSES: Final = (
    "a reconstruction scene by its id, and a place by its id with a time, which resolves to the "
    "version of that place in force at that time. A scene is one set of photographs of one place "
    "at one capture; a place is an ordered series of those scenes sharing the anchor's frame"
)

#: And what it cannot be addressed by. The roadmap asks for an entity, a place and a time, so this
#: names the one of the three that has no route: there is nothing to follow from a person or an
#: object to a bundle. Stated as the residue rather than as a general disclaimer, because a reader
#: who has to infer what is missing infers wrongly.
_NOT_ADDRESSABLE: Final = (
    "an entity. Nothing routes from a person or an object to a bundle, so a caller holding an "
    "entity id has no address here and this bundle does not claim one"
)


def _instant(value: dt.datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _membership_block(membership: SceneMembership | None) -> dict[str, Any]:
    """What a scene-addressed bundle says about the place its scene belongs to.

    The three states are distinct facts and none of them may be spelled as the absence of another.
    ``none`` is a scene bound to no place, which is the ordinary case. ``member`` is a scene in a
    readable place, and carries the address a caller needs to ask for the place itself.
    ``unavailable`` is a scene whose place has no readable shared frame, which is what a withdrawn
    anchor leaves behind: the scene is exactly as readable as it was before it joined, and its
    place is not.
    """
    if membership is None:
        return {
            "state": "none",
            "place_id": None,
            "version_ordinal": None,
            "version_count": None,
            "undated_version_count": None,
            "frame_hops": None,
            "reason": "this scene is bound to no place, which is the ordinary case for a scene",
        }
    if membership.blocked:
        return {
            "state": "unavailable",
            "place_id": str(membership.place_id),
            "version_ordinal": None,
            "version_count": None,
            "undated_version_count": None,
            "frame_hops": None,
            "reason": (
                "this scene belongs to a place with no readable shared frame, because the place "
                "has no anchor or its anchor's photographs were withdrawn. This scene is "
                "unaffected: a place is a join and never a merge"
            ),
        }
    return {
        "state": "member",
        "place_id": str(membership.place_id),
        "version_ordinal": membership.ordinal,
        "version_count": membership.version_count,
        "undated_version_count": membership.undated_version_count,
        "frame_hops": membership.frame_hops,
        "reason": None,
    }


def _version_block(version: PlaceVersion, resolved: PlaceVersion | None) -> dict[str, Any]:
    transform = version.transform
    return {
        "scene_id": str(version.scene_id),
        "ordinal": version.ordinal,
        "ordered_by_utc": _instant(version.ordered_by_utc),
        "ordered_by_basis": version.ordered_by_basis,
        "frame_hops": version.frame_hops,
        "admitted_by_alignment_id": (
            None
            if version.admitted_by_alignment_id is None
            else str(version.admitted_by_alignment_id)
        ),
        "is_resolved": resolved is not None and version.scene_id == resolved.scene_id,
        "place_from_scene": {
            "state": transform.state,
            "row_major": transform.place_from_scene_row_major,
            "scene_units_to_place_units": transform.scene_units_to_place_units,
            "receipt_sha256": transform.receipt_sha256,
            "reason": transform.reason,
        },
    }


def _place_block(history: PlaceHistory, resolved: PlaceVersion | None) -> dict[str, Any]:
    """The place itself: its versions in capture order, and the joins that were refused.

    Every version is listed, including the ones this address did not resolve to, because the
    question a place answers is what changed, and a history that showed only the version in force
    could not be asked it. What is deliberately NOT here is each version's rung, receipts, views
    and geometry: a place does not average its versions, and building every member scene to answer
    for one is the cost ``reconstruction_scenes.reconstruction_scene_rows`` takes a scene filter to
    avoid. The other versions are addressed as scenes, which is what the scene address is for.
    """
    return {
        "place_id": str(history.place_id),
        "anchor_scene_id": str(history.anchor.scene_id),
        "position": asdict(history.position),
        "version_count": len(history.versions),
        "undated_version_count": history.undated_versions,
        "frame": (
            "every transform here takes a scene's own recovered frame into the anchor scene's "
            "recovered frame, which is this place's frame. The anchor's own transform is identity "
            "by construction and nothing measured it"
        ),
        "frame_hops": (
            "0 is the anchor, 1 is a frame one joint reconstruction measured against the anchor, "
            "and n is a frame composed through n of them. A composed transform is not a measured "
            "one, and this is the field that says which one a reader is holding"
        ),
        "physical_scale": (
            "unvalidated, and a shared frame does not change that. Two captures sharing one "
            "recovered frame is a statement about their consistency with each other and about "
            "nothing physical; no alignment here is physically validated"
        ),
        "versions": [_version_block(version, resolved) for version in history.versions],
        "refused_alignments": [
            {
                "alignment_id": str(refusal.alignment_id),
                "candidate_scene_id": str(refusal.candidate_scene_id),
                "against_scene_id": str(refusal.against_scene_id),
                "reason": refusal.reason,
                "receipt_sha256": refusal.receipt_sha256,
                # Repeated on every entry rather than stated once above it, for the reason
                # `tier` is repeated on every geometry entry: an entry separated from its list
                # still has to say what it is.
                "means": (
                    "a joint reconstruction over these two capture sets ran and did not reconcile "
                    "their frames. They are of related places whose frames could not be joined, "
                    "which is a recorded result and not a build that failed to happen"
                ),
            }
            for refusal in history.refused_alignments
        ],
        "omitted": (
            "each version's own rung, receipts, views and geometry are read by addressing that "
            "version's scene. Only the resolved version's are in this bundle, because a place "
            "does not average its versions and this read does not build the ones nobody asked for"
        ),
    }


def _resolution(at: dt.datetime | None) -> str:
    if at is None:
        return (
            "no time was requested, so the latest dated version answers. This read consults no "
            "clock: the answer moves only when a version is bound"
        )
    return (
        "the latest version at or before the requested time. A time between two versions resolves "
        "to the earlier one, because that capture was the latest record of this place at that "
        "moment and rounding forward would answer with photographs that did not exist yet"
    )


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
    scenes = reconstruction_scene_rows(connection, workspace, store, scene_id=scene_id)
    if not scenes:
        return None
    scene = scenes[0]
    # Binding this scene into a place changes this block, and therefore this bundle's digest,
    # while nothing about the scene itself moves. That is correct rather than unfortunate: the
    # digest covers what this read says, a bind is a write, and a recipient re-reading after one
    # is entitled to see the answer change. It is not a clock, which is the property that matters:
    # no unwritten fact can move it.
    addressing = {
        "by": "reconstruction_scene",
        "scene_id": str(scene.scene_id),
        "at": None,
        "place": _membership_block(scene_place_membership(connection, workspace, scene.scene_id)),
        "addresses": _ADDRESSES,
        "not_addressable": _NOT_ADDRESSABLE,
    }
    return _assemble(connection, workspace, scene, store, addressing, None, world_id=world_id)


def place_read_bundle(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    place_id: uuid.UUID,
    store: ContentAddressedStore | None,
    *,
    at: dt.datetime | None = None,
    world_id: str = DEFAULT_WORLD_ID,
) -> dict[str, Any] | None:
    """The bundle for the version of one place in force at one time, or ``None`` if unreadable.

    ``None`` covers a place that does not exist, one in another workspace, one whose anchor was
    withdrawn and one that has no anchor yet, for the same reason the scene read collapses its
    own absences: the surface is not an existence oracle. The route separates those cases only
    among ids it has already established belong to the asking workspace.

    A place that exists and has no version at or before ``at`` is **not** one of those cases. It
    answers with an unresolved bundle: the place, its versions and their times, and an explicit
    statement that nothing was recorded of it that early. A 404 there would say the place does not
    exist, which is false, and an empty bundle with the ordinary keys would read as a place with
    nothing in it, which is worse.
    """
    history = place_history(connection, workspace, place_id, store)
    if history is None:
        return None
    resolved = history.at(at)
    if resolved is None:
        return _unresolved(
            history,
            at,
            state="no_version_at_that_time",
            reason=(
                "this place has no version at or before the requested time. It exists and is "
                "readable; nothing was recorded of it that early"
            ),
        )
    scenes = reconstruction_scene_rows(connection, workspace, store, scene_id=resolved.scene_id)
    if not scenes:
        # The version is bound and its photographs are live, and the scene still carries no
        # readable claim: `reconstruction_scene_rows` requires an active rung assertion. Saying so
        # is the honest answer. Falling through to a 404 would report the place as absent, and
        # substituting the neighbouring version would answer a question nobody asked.
        return _unresolved(
            history,
            at,
            state="version_not_readable",
            reason=(
                "the version in force at that time carries no readable scene claim, so this read "
                "has nothing to put in place. The place and its other versions are unaffected"
            ),
        )
    addressing = {
        "by": "place_at_time",
        "scene_id": str(resolved.scene_id),
        "at": _instant(at),
        "place": {
            "state": "resolved",
            "place_id": str(history.place_id),
            "version_ordinal": resolved.ordinal,
            "version_count": len(history.versions),
            "undated_version_count": history.undated_versions,
            "frame_hops": resolved.frame_hops,
            "ordered_by_utc": _instant(resolved.ordered_by_utc),
            "ordered_by_basis": resolved.ordered_by_basis,
            "reason": _resolution(at),
        },
        "addresses": _ADDRESSES,
        "not_addressable": _NOT_ADDRESSABLE,
    }
    return _assemble(
        connection,
        workspace,
        scenes[0],
        store,
        addressing,
        _place_block(history, resolved),
        world_id=world_id,
    )


def _unresolved(
    history: PlaceHistory,
    at: dt.datetime | None,
    *,
    state: str,
    reason: str,
) -> dict[str, Any]:
    """A readable place with no bundle to put in place, said out loud.

    This bundle deliberately carries no ``scene``, ``views`` or ``geometry`` key at all. A
    consumer that reaches for one gets a KeyError rather than an empty list, which is the
    difference between an answer a reader can misread as a place with nothing in it and one they
    cannot. What it does carry is the place: every version, with its time, so the caller can see
    what it could have asked for.
    """
    dated = [version.ordered_by_utc for version in history.versions if version.ordered_by_utc]
    bundle: dict[str, Any] = {
        "profile": WORLD_READ_PROFILE,
        "number_encoding": NUMBER_ENCODING,
        "addressing": {
            "by": "place_at_time",
            "scene_id": None,
            "at": _instant(at),
            "place": {
                "state": state,
                "place_id": str(history.place_id),
                "version_ordinal": None,
                "version_count": len(history.versions),
                "undated_version_count": history.undated_versions,
                "frame_hops": None,
                "ordered_by_utc": None,
                "ordered_by_basis": None,
                "reason": reason,
            },
            "addresses": _ADDRESSES,
            "not_addressable": _NOT_ADDRESSABLE,
        },
        "unresolved": {
            "state": state,
            "reason": reason,
            "requested_at": _instant(at),
            "earliest_version_utc": _instant(min(dated)) if dated else None,
            "latest_version_utc": _instant(max(dated)) if dated else None,
            "what_this_is_not": (
                "not a missing place, not a place in another workspace and not a place with "
                "nothing in it. This response carries no scene, no views and no geometry because "
                "there is none to carry at this address"
            ),
        },
        "place": _place_block(history, None),
    }
    return _seal(bundle)


def _assemble(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    scene: ReconstructionSceneRow,
    store: ContentAddressedStore | None,
    addressing: dict[str, Any],
    place: dict[str, Any] | None,
    *,
    world_id: str,
) -> dict[str, Any]:
    """One scene's bundle under whichever address reached it.

    The two addresses share this body exactly, and that is the point of extracting it: a place
    addressed at a time and the scene it resolved to must not be able to disagree about the world,
    which is the same argument the module docstring makes for reading scenes through
    ``reconstruction_scene_rows`` rather than through queries of this module's own.
    """
    capture_ids = [member.capture_id for member in scene.members]
    consent = consent_for_captures(connection, workspace, capture_ids)

    bundle: dict[str, Any] = {
        "profile": WORLD_READ_PROFILE,
        "number_encoding": NUMBER_ENCODING,
        "addressing": addressing,
        "scene": _scene_block(scene),
        "recipient_evidence": recorded_evidence(
            connection, workspace, scene.scene_id, capture_ids, store
        ),
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
            # Both of these describe the photographs rather than the build. The scene-level answer
            # is the weakest of its members, so a scene is `recorded` only when every photograph in
            # it has been screened; anything else would let one unexamined frame hide behind five
            # examined ones.
            "basis": scene_consent_basis(consent),
            "person_consent": person_consent_state(consent),
            "per_capture": consent,
        },
        # Folded from the per-capture records directly above rather than from the scene row or a
        # second query. A recipient can recompute every count in this block from `per_capture`,
        # which is the difference between a release claim they can check and one they must trust.
        "release": release_state(consent),
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
    for view in bundle["views"]:
        view["photo_bytes"] = descriptor(
            connection, workspace, scene.scene_id, view, bundle["recipient_evidence"], store
        )
    point_ids = {
        item["artifact_id"] for item in bundle["recipient_evidence"]["record"]["point_maps"]
    }
    for geometry in bundle["geometry"]:
        if geometry["kind"] == "point_map":
            geometry["source_lineage"] = (
                {"state": "available", "record_artifact_id": geometry["artifact_id"]}
                if geometry["artifact_id"] in point_ids
                else {"state": "unavailable", "reason": "frozen_point_binding_missing"}
            )
    if place is not None:
        # A place-addressed bundle carries the place it resolved through; a scene-addressed one
        # does not. The difference is visible in `recorded_keys` rather than hidden, and it is a
        # decision: putting a place history into every scene bundle would answer a question the
        # caller did not ask, and would make one bind move the digest of every scene in the place.
        bundle["place"] = place
    return _seal(bundle)


def _seal(bundle: dict[str, Any]) -> dict[str, Any]:
    """Compute both digests over a finished bundle and wrap it in its envelope.

    One function, called by every address, because two builders computing "the same" digest is how
    two answers for one world appear.
    """
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
    bundle["recorded_digest_profile"] = "exulanica.world-read-recorded/v2"
    # Delivery fields can change at expiry without writes. Exact response integrity remains
    # covered by bundle_sha256; retained cameras and outputs live in recipient_evidence.
    delivery_keys = {"generated", "scene", "views", "geometry", "rungs"}
    bundle["recorded_keys"] = sorted(key for key in bundle if key not in delivery_keys)
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
