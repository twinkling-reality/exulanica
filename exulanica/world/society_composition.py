"""Pure authored-object projection into society inputs, using caller-supplied A geometry checks.

The environment layer owns geometry validation. Injecting its reviewed predicates keeps the
world layer below environment and avoids a second polygon/collision implementation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from typing import Any

from exulanica.world.assets import reviewed_assets
from exulanica.world.objects import AlternateVersion, delta_sha256, object_document
from exulanica.world.society import society_state_sha256
from exulanica.world.society_input_policy import (
    LEGACY_COMPOSITION,
    LOCAL_COMPOSITION,
    UNREACHABLE,
    input_profile,
)
from exulanica.world.society_planner import DURATIONS, input_sha256, validate_society_input

COMPOSITION_PROFILE = LEGACY_COMPOSITION
Point = tuple[int, int]
Supports = Callable[[Point, Point, int], Sequence[str]]
SegmentBlocked = Callable[[Point, Point, list[Point], int], bool]
_REVIEWED = {
    "cc0.marker-cube": ("visit", [250, 250], True),
    "cc0.marker-pillar": ("visit", [125, 125], True),
    "cc0.marker-plate": ("rest", [500, 500], False),
}


def _registration_reason(
    registration: Mapping[str, Any] | None,
    version: AlternateVersion,
    interpretation: dict[str, Any],
) -> str | None:
    if registration is None:
        return "unregistered_authored_frame"
    fields = {
        "world_id",
        "version_id",
        "source_snapshot_id",
        "region_id",
        "district_id",
        "frame_name",
        "translation_mm",
        "yaw_microradians",
        "scale_milli",
    }
    if set(registration) != fields:
        return "invalid_frame_registration"
    if (
        registration["world_id"] != version.world_id
        or registration["version_id"] != str(version.version_id)
        or registration["source_snapshot_id"] != str(version.source_snapshot_id)
        or registration["district_id"] != interpretation["district_id"]
        or registration["frame_name"] != interpretation["frame"]["name"]
        or not isinstance(registration["region_id"], str)
        or not registration["region_id"]
    ):
        return "frame_registration_scope_mismatch"
    translation = registration["translation_mm"]
    if (
        not isinstance(translation, list)
        or len(translation) != 3
        or any(type(v) is not int or abs(v) > 10**9 for v in translation)
    ):
        return "invalid_frame_translation"
    if (
        type(registration["yaw_microradians"]) is not int
        or registration["yaw_microradians"] != 0
        or type(registration["scale_milli"]) is not int
        or registration["scale_milli"] != 1000
    ):
        return "unsupported_frame_rotation_or_scale"
    return None


def _validate_registry(mapping: Mapping[str, dict[str, Any]]) -> None:
    actual = {asset.asset_key: asset.content_sha256 for asset in reviewed_assets()}
    expected_fields = {
        "asset_key",
        "affordance",
        "duration_ticks",
        "footprint_half_extents_mm",
        "blocks_navigation",
        "reach_mm",
    }
    for digest, row in mapping.items():
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValueError("invalid reviewed society affordance assignment")
        expected = _REVIEWED.get(row["asset_key"])
        if (
            expected is None
            or actual[row["asset_key"]] != digest
            or (row["affordance"], row["footprint_half_extents_mm"], row["blocks_navigation"])
            != expected
            or type(row["blocks_navigation"]) is not bool
            or type(row["duration_ticks"]) is not int
            or row["duration_ticks"] != DURATIONS[row["affordance"]]
            or type(row["reach_mm"]) is not int
            or not 1 <= row["reach_mm"] <= 10000
            or any(type(v) is not int for v in row["footprint_half_extents_mm"])
        ):
            raise ValueError("unreviewed society asset, footprint, action or reach")


def build_society_input(
    *,
    interpretation: dict[str, Any],
    base_bytes: bytes,
    version: AlternateVersion,
    registration: Mapping[str, Any] | None,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    supports: Supports,
    segment_blocked: SegmentBlocked,
    composition_profile: str = COMPOSITION_PROFILE,
) -> dict[str, Any]:
    """Compose a prevalidated A artifact and accepted authored version without mutating either.

    ``supports`` is A's DistrictGeometry(base).supports; ``segment_blocked`` is A's geometry
    helper of that name. The caller validates the A document/base and live dependencies first.
    Both policies support one explicitly registered region, ground-plane objects, zero yaw and
    unit scale. The default preserves v1 receipts. Explicit composition/v2 records only known
    unreachable activities locally; unsupported consequential state still fails globally.
    Malformed binding/digest/registry data raises ValueError rather than publishing a false receipt.
    """
    profile = input_profile(composition_profile)
    if interpretation.get("profile") != "exulanica.district-interpretation/v1":
        raise ValueError("unsupported district interpretation profile")
    if hashlib.sha256(base_bytes).hexdigest() != interpretation["base_artifact_sha256"]:
        raise ValueError("district base artifact digest mismatch")
    if input_sha256(interpretation) != interpretation["document_sha256"]:
        raise ValueError("district interpretation digest mismatch")
    if (
        delta_sha256(version.objects, version.element_overrides, version.environment_instances)
        != version.state_sha256
    ):
        raise ValueError("authored delta digest mismatch")
    _validate_registry(reviewed_affordances)
    if availability not in ("available", "unavailable"):
        raise ValueError("invalid current availability")
    if (availability == "available") != (unavailable_reason is None):
        raise ValueError("availability and reason disagree")

    nav = deepcopy(interpretation["navigation"])
    reason = unavailable_reason or nav["unavailable_reason"]
    reason = reason or _registration_reason(registration, version, interpretation)
    if version.source_invalidated:
        reason = reason or "authored_source_invalidated"
    if version.element_overrides:
        reason = reason or "unsupported_structural_overrides"
    if version.environment_instances:
        reason = reason or "unsupported_environment_composition"
    refs = deepcopy(list(dependency_refs))
    refs.extend(
        [
            {
                "kind": "society_composition_policy",
                "identity": composition_profile,
                "sha256": society_state_sha256({"profile": composition_profile}),
            },
            {
                "kind": "society_frame_registration",
                "identity": str(version.version_id),
                "sha256": society_state_sha256(
                    dict(registration) if registration is not None else None
                ),
            },
            {
                "kind": "society_affordance_registry",
                "identity": composition_profile,
                "sha256": society_state_sha256(dict(reviewed_affordances)),
            },
        ]
    )
    # Complete authored object documents bind origin.role and transform even though the frozen
    # target shape carries only origin='authored'. No personal meaning is inferred from assets.
    for obj in sorted(version.objects, key=lambda value: value.object_id):
        reviewed = reviewed_affordances.get(obj.asset_sha256)
        if not obj.removed and reviewed is not None:
            refs.append(
                {
                    "kind": "reviewed_asset",
                    "identity": reviewed["asset_key"],
                    "sha256": obj.asset_sha256,
                }
            )
        refs.append(
            {
                "kind": "authored_object",
                "identity": f"{version.version_id}:{obj.object_id}",
                "sha256": society_state_sha256(object_document(obj)),
            }
        )

    objects = []
    obstacles: list[tuple[str, list[Point]]] = []
    if reason is None:
        assert registration is not None
        tx, ty, tz = registration["translation_mm"]
        for obj in sorted(version.objects, key=lambda value: value.object_id):
            if obj.removed:
                continue
            reviewed = reviewed_affordances.get(obj.asset_sha256)
            if obj.region_id != registration["region_id"]:
                reason = f"unregistered_object_region:{obj.object_id}"
            elif reviewed is None:
                reason = f"unknown_active_asset:{obj.object_id}"
            elif obj.behaviour is not None:
                reason = f"unsupported_active_behaviour:{obj.object_id}"
            elif obj.origin.kind != "authored" or obj.origin.role not in ("fictional", "personal"):
                reason = f"unsupported_object_origin:{obj.object_id}"
            elif (
                composition_profile == LOCAL_COMPOSITION
                and any(
                    type(value) is not int or abs(value) > 10**9
                    for value in (
                        obj.transform.x_mm,
                        obj.transform.y_mm,
                        obj.transform.z_mm,
                        obj.transform.yaw_microradians,
                        obj.transform.scale_milli,
                    )
                )
            ) or (
                obj.transform.yaw_microradians != 0
                or obj.transform.scale_milli != 1000
                or obj.transform.y_mm + ty != 0
            ):
                reason = f"unsupported_object_transform:{obj.object_id}"
            if reason:
                break
            assert reviewed is not None
            center = (obj.transform.x_mm + tx, obj.transform.z_mm + tz)
            objects.append((obj, reviewed, center))
            if reviewed["blocks_navigation"]:
                hx, hz = reviewed["footprint_half_extents_mm"]
                x, z = center
                obstacles.append(
                    (
                        obj.object_id,
                        [
                            (x - hx, z - hz),
                            (x + hx, z - hz),
                            (x + hx, z + hz),
                            (x - hx, z + hz),
                            (x - hx, z - hz),
                        ],
                    )
                )

    targets = []
    unavailable_affordances = []
    if reason is None:
        clearance = nav["clearance_mm"]

        def clear(a: Point, b: Point, excluded: str | None = None) -> bool:
            return bool(supports(a, b, clearance)) and not any(
                segment_blocked(a, b, ring, clearance)
                for identity, ring in obstacles
                if identity != excluded
            )

        nav["nodes"] = [
            n for n in nav["nodes"] if clear(tuple(n["position_mm"]), tuple(n["position_mm"]))
        ]
        nodes = {n["node_id"]: n for n in nav["nodes"]}
        nav["edges"] = [
            e
            for e in nav["edges"]
            if e["from_node_id"] in nodes
            and e["to_node_id"] in nodes
            and clear(
                tuple(nodes[e["from_node_id"]]["position_mm"]),
                tuple(nodes[e["to_node_id"]]["position_mm"]),
            )
        ]
        nav["destinations"] = [d for d in nav["destinations"] if d["node_id"] in nodes]
        for dest in nav["destinations"]:
            targets.append(
                {
                    "target_id": dest["destination_id"],
                    "subject_id": dest["subject_id"],
                    "node_id": dest["node_id"],
                    "affordance": dest["affordance"],
                    "duration_ticks": dest["duration_ticks"],
                    "origin": "district",
                    "object_id": None,
                    "version_id": str(version.version_id),
                    "enabled": True,
                }
            )
        connected = {e[key] for e in nav["edges"] for key in ("from_node_id", "to_node_id")}
        for obj, reviewed, center in objects:
            candidates = []
            for node in nav["nodes"]:
                point = tuple(node["position_mm"])
                squared = (point[0] - center[0]) ** 2 + (point[1] - center[1]) ** 2
                # This is bounded object-use reach from an existing access node, NOT a new
                # movement edge, and never a change to object/player/inhabitant placement.
                if (
                    node["node_id"] in connected
                    and squared <= reviewed["reach_mm"] ** 2
                    and clear(point, center, excluded=obj.object_id)
                ):
                    candidates.append((squared, node["node_id"]))
            if not candidates:
                if composition_profile == LOCAL_COMPOSITION:
                    subject_id = f"authored:{version.version_id}:{obj.object_id}"
                    unavailable_affordances.append(
                        {
                            "target_id": f"{subject_id}:{reviewed['affordance']}",
                            "subject_id": subject_id,
                            "object_id": obj.object_id,
                            "version_id": str(version.version_id),
                            "affordance": reviewed["affordance"],
                            "reason": UNREACHABLE,
                        }
                    )
                    continue
                reason = f"authored_affordance_unreachable:{obj.object_id}"
                break
            node_id = min(candidates)[1]
            subject_id = f"authored:{version.version_id}:{obj.object_id}"
            targets.append(
                {
                    "target_id": f"{subject_id}:{reviewed['affordance']}",
                    "subject_id": subject_id,
                    "node_id": node_id,
                    "affordance": reviewed["affordance"],
                    "duration_ticks": reviewed["duration_ticks"],
                    "origin": "authored",
                    "object_id": obj.object_id,
                    "version_id": str(version.version_id),
                    "enabled": True,
                }
            )
        if not nav["nodes"]:
            reason = reason or "authored_obstacles_block_navigation"
    if reason is not None:
        # An unknown obstacle/frame is not permission to keep using the uncomposed base graph.
        nav.update(nodes=[], edges=[], destinations=[], unavailable_reason=reason)
        targets = []
        unavailable_affordances = []
    nav["nodes"].sort(key=lambda n: n["node_id"])
    nav["edges"].sort(key=lambda e: e["edge_id"])
    targets.sort(key=lambda target: target["target_id"])
    deduplicated = {(r["kind"], r["identity"], r["sha256"]): r for r in refs}
    document = {
        "profile": profile,
        "input_seq": input_seq,
        "world_id": version.world_id,
        "version_id": str(version.version_id),
        "district_id": interpretation["district_id"],
        "district_document_sha256": interpretation["document_sha256"],
        "base_artifact_sha256": interpretation["base_artifact_sha256"],
        "frame": deepcopy(interpretation["frame"]),
        "authored_state": {"edit_seq": version.edit_seq, "delta_sha256": version.state_sha256},
        "navigation": nav,
        "targets": targets,
        "dependency_refs": [deduplicated[k] for k in sorted(deduplicated)],
        "availability": "available" if reason is None else "unavailable",
        "unavailable_reason": reason,
    }
    if composition_profile == LOCAL_COMPOSITION:
        document["unavailable_affordances"] = sorted(
            unavailable_affordances, key=lambda row: row["target_id"]
        )
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    return document
