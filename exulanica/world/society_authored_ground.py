"""The society projection of a saved world that has no district.

A person's saved world is a structural snapshot with one authored region and a flat authored
ground. This module turns that ground, and the reviewed objects the person placed on it, into the
same frozen simulation input the district adapter produces, so the existing deterministic policy,
persistence and replay apply unchanged.

Where inhabitants may walk is kept apart from what the ground is. A ground module that states a
horizontal extent gives the society that extent, read from the world. A ground module that states
it has none, an endless plane, gives the society nothing to read, so the society declares a
bounded area of its own and says in its input that it did. Neither case writes an edge into the
ground: the stored world keeps whatever its module states, and the declaration lives only in the
society's inputs, where replay reproduces it.

The lattice over that area is a declared discretisation, not a measurement. Its spacing, the area a
society declares where the ground states none, and how many people a society over the ground
starts with are the ground's entry in the society ground catalog
(:mod:`exulanica.world.society_grounds`), with their reasons; nothing here derives a walkable
shape from anything the world does not say.

The ground itself is :mod:`exulanica.world.society_authored_ground_area`'s, and what a society may
use on it :mod:`exulanica.world.society_authored_ground_uses`'s; this module composes the
society's input from them.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Any

from exulanica.world.arrival_selection import ArrivalDescriptor
from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.society_authored_ground_area import (
    AUTHORED_GROUND_POPULATION as AUTHORED_GROUND_POPULATION,
)
from exulanica.world.society_authored_ground_area import (
    DECLARED_FLOOR_ELEVATION_MM as DECLARED_FLOOR_ELEVATION_MM,
)
from exulanica.world.society_authored_ground_area import (
    DECLARED_HALF_EXTENT_MM as DECLARED_HALF_EXTENT_MM,
)

# Named here for the callers that read them from this module.
from exulanica.world.society_authored_ground_area import (
    GROUND_PROFILE as GROUND_PROFILE,
)
from exulanica.world.society_authored_ground_area import (
    LATTICE_MM as LATTICE_MM,
)
from exulanica.world.society_authored_ground_area import (
    MADE_WORLD_COMPOSER_VERSIONS as MADE_WORLD_COMPOSER_VERSIONS,
)
from exulanica.world.society_authored_ground_area import (
    NAVIGATION_PROFILE as NAVIGATION_PROFILE,
)
from exulanica.world.society_authored_ground_area import (
    STARTER_GROUND as STARTER_GROUND,
)
from exulanica.world.society_authored_ground_area import (
    SocietyGround,
    area_supports,
    ground_navigation,
)
from exulanica.world.society_authored_ground_area import (
    WalkableArea as WalkableArea,
)
from exulanica.world.society_authored_ground_area import (
    _made_world_ground as _made_world_ground,
)
from exulanica.world.society_authored_ground_area import (
    authored_ground_from_snapshot as authored_ground_from_snapshot,
)
from exulanica.world.society_authored_ground_area import (
    authored_input_region as authored_input_region,
)
from exulanica.world.society_authored_ground_area import (
    declared_floor as declared_floor,
)
from exulanica.world.society_authored_ground_area import (
    ground_place_id as ground_place_id,
)
from exulanica.world.society_authored_ground_area import (
    read_authored_ground as read_authored_ground,
)
from exulanica.world.society_authored_ground_uses import (
    PLACE_NODE_PREFIX as PLACE_NODE_PREFIX,
)
from exulanica.world.society_authored_ground_uses import (
    PLACED_THING_PREFIX as PLACED_THING_PREFIX,
)
from exulanica.world.society_authored_ground_uses import (
    SWEPT_BEHAVIOURS as SWEPT_BEHAVIOURS,
)
from exulanica.world.society_authored_ground_uses import (
    StandingPolicy,
    _fixed_duration,
    _ground_override_reason,
    _input_things,
    _objects_one_by_one,
    _place_targets,
    _thing_kinds,
    _things_one_by_one,
    _UsableObject,
    made_things_gone,
    objects_in_region,
    state_made_kinds,
    thing_dependency_refs,
    things_in_region,
)
from exulanica.world.society_authored_ground_uses import (
    _height_above_plane as _height_above_plane,
)
from exulanica.world.society_authored_ground_uses import (
    _refused_activity as _refused_activity,
)
from exulanica.world.society_authored_ground_uses import (
    _scaled as _scaled,
)
from exulanica.world.society_authored_ground_uses import (
    convex_ring as convex_ring,
)
from exulanica.world.society_authored_ground_uses import (
    destination_places as destination_places,
)
from exulanica.world.society_authored_ground_uses import (
    standing_places as standing_places,
)
from exulanica.world.society_authored_ground_uses import (
    supported_things_projection as supported_things_projection,
)
from exulanica.world.society_authored_ground_uses import (
    thing_activities as thing_activities,
)
from exulanica.world.society_catalogs import (
    PurposefulRoutine,
    check_object_kinds,
    purposeful_routine,
)
from exulanica.world.society_composition import (
    ComposedObject,
    Obstacle,
    SegmentBlocked,
    affordance_targets,
    clearance_test,
    composed_objects,
    object_dependency_refs,
    policy_dependency_refs,
    prune_navigation,
    validate_reviewed_affordances,
    validate_workspace_obstacles,
)
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION_V2,
    AUTHORED_GROUND_COMPOSITION_V3,
    AUTHORED_GROUND_COMPOSITION_V4,
    AUTHORED_GROUND_COMPOSITION_V5,
    NO_AUTHORED_FRAME,
    input_profile,
)
from exulanica.world.society_planner import input_sha256, validate_society_input
from exulanica.world.society_thing_inputs import record_modules


def build_authored_ground_society_input(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose one saved world's accepted authored version over its society's walkable area.

    The caller has already validated the ground against the world's structural authority and
    checked current asset rights; this function adds no authority of its own. It refuses
    malformed binding, digest or registry data rather than publishing a false receipt.
    """
    # Placed depth estimates take part in the digest and in nothing else here, as in the district
    # projection: they are drawn, and they are neither ground to stand on nor an obstacle.
    if version_delta_sha256(version) != version.state_sha256:
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
    validate_workspace_obstacles(workspace_obstacles)
    if availability not in ("available", "unavailable"):
        raise ValueError("invalid current availability")
    if (availability == "available") != (unavailable_reason is None):
        raise ValueError("availability and reason disagree")
    if version.world_id != ground.world_id:
        raise ValueError("authored ground belongs to another world")

    nav = ground_navigation(ground)
    reason = unavailable_reason or nav["unavailable_reason"]
    if version.source_snapshot_id != ground.snapshot_id:
        reason = reason or "authored_ground_snapshot_mismatch"
    if version.source_invalidated:
        reason = reason or "authored_source_invalidated"
    if version.element_overrides:
        reason = reason or "unsupported_structural_overrides"
    if version.environment_instances:
        reason = reason or "unsupported_environment_composition"
    refs = [dict(ref) for ref in dependency_refs]
    refs.extend(
        policy_dependency_refs(
            composition_profile=AUTHORED_GROUND_COMPOSITION,
            version_id=version.version_id,
            registration=ground.registration(),
            reviewed_affordances=reviewed_affordances,
        )
    )
    refs.extend(
        object_dependency_refs(
            version, reviewed_affordances, workspace_obstacles=workspace_obstacles
        )
    )

    objects: list[ComposedObject] = []
    obstacles: list[Obstacle] = []
    targets: list[dict[str, Any]] = []
    unavailable_affordances: list[dict[str, Any]] = []
    if reason is None:
        # The ground plane is at the region's declared elevation, so an object anywhere else
        # is refused rather than floated onto it. Authored coordinates are already this frame's.
        objects, obstacles, reason = composed_objects(
            version,
            reviewed_affordances,
            region_id=ground.region_id,
            translation_mm=(0, -ground.elevation_mm, 0),
            composition_profile=AUTHORED_GROUND_COMPOSITION,
            workspace_obstacles=workspace_obstacles,
        )
    if reason is None:
        targets, unavailable_affordances, reason = affordance_targets(
            nav,
            objects,
            obstacles,
            version_id=version.version_id,
            composition_profile=AUTHORED_GROUND_COMPOSITION,
            supports=area_supports(ground),
            segment_blocked=segment_blocked,
        )
    if reason is not None:
        # An unusable area is not permission to keep publishing the unpruned lattice.
        nav.update(nodes=[], edges=[], destinations=[], unavailable_reason=reason)
        targets = []
        unavailable_affordances = []
    nav["nodes"].sort(key=lambda node: node["node_id"])
    nav["edges"].sort(key=lambda edge: edge["edge_id"])
    targets.sort(key=lambda target: target["target_id"])
    deduplicated = {(r["kind"], r["identity"], r["sha256"]): r for r in refs}
    document = {
        "profile": input_profile(AUTHORED_GROUND_COMPOSITION),
        "input_seq": input_seq,
        "world_id": version.world_id,
        "version_id": str(version.version_id),
        "district_id": ground.place_id,
        "district_document_sha256": ground.document_sha256,
        "base_artifact_sha256": ground.snapshot_sha256,
        "frame": ground.frame(),
        "authored_state": {"edit_seq": version.edit_seq, "delta_sha256": version.state_sha256},
        "navigation": nav,
        "targets": targets,
        "dependency_refs": [deduplicated[key] for key in sorted(deduplicated)],
        "availability": "available" if reason is None else "unavailable",
        "unavailable_reason": reason,
        "unavailable_affordances": sorted(
            unavailable_affordances, key=lambda row: row["target_id"]
        ),
    }
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    return document


# The second saved-world composition. An object the society cannot use costs its own activity
# and nothing else; only something that leaves the society unable to say where it may walk
# takes the whole world with it. Every activity also states the places its occupants stand at.


def build_authored_ground_society_input_v3(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    routine: PurposefulRoutine | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a saved world under ``exulanica.society-composition/authored-ground-v3``.

    The second composition's projection, object by object and with every place stated, which also
    records the purposeful routine it was composed under (left out, the one a new input records)
    and names, for each activity, the routine's entry for its object's kind, or its affordance's
    default where the kind has none, in place of a fixed duration. The society reads how long a
    stay there lasts, and how it varies, from that entry. A routine naming a kind the world object
    catalog does not state, or states with another affordance, is refused by name here, before any
    input records it; an input that recorded a routine is never read against that catalog.
    """
    return _authored_ground_with_routine(
        AUTHORED_GROUND_COMPOSITION_V3,
        ground=ground,
        version=version,
        input_seq=input_seq,
        dependency_refs=dependency_refs,
        availability=availability,
        unavailable_reason=unavailable_reason,
        reviewed_affordances=reviewed_affordances,
        segment_blocked=segment_blocked,
        standing=standing,
        routine=routine,
        workspace_obstacles=workspace_obstacles,
    )


def build_authored_ground_society_input_v4(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    arrival: ArrivalDescriptor,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    routine: PurposefulRoutine | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a new made-world society at its pinned, region-local opening pose."""
    if (
        arrival.source.world_id != version.world_id
        or arrival.source.version_id != version.version_id
        or arrival.source.source_snapshot_id != ground.snapshot_id
        or arrival.region_id != ground.region_id
    ):
        raise ValueError("arrival source does not belong to this authored ground and version")
    x, _, z = arrival.position_local_mm
    arrived_ground = replace(ground, arrival_x_mm=x, arrival_z_mm=z)
    return _authored_ground_with_routine(
        AUTHORED_GROUND_COMPOSITION_V4,
        ground=arrived_ground,
        version=version,
        input_seq=input_seq,
        dependency_refs=dependency_refs,
        availability=availability,
        unavailable_reason=unavailable_reason,
        reviewed_affordances=reviewed_affordances,
        segment_blocked=segment_blocked,
        standing=standing,
        routine=routine,
        arrival=arrival,
        workspace_obstacles=workspace_obstacles,
    )


def build_authored_ground_society_input_v5(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    arrival: ArrivalDescriptor | None,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    routine: PurposefulRoutine | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a society of things' input, ``exulanica.society-composition/authored-ground-v5``.

    The fourth composition's projection, at the opening pose the version pins where the ground
    states no arrival of its own (``arrival``; None where it does, and the ground's own arrival
    stands), and the things the world's author placed in the region (``_things_one_by_one``): a
    placed object whose kind blocks walking is an obstacle, its box turned with it; one whose kind
    offers a rest or a visit offers it at the places its kind states, turned with it, unless it is
    off the ground; and every placed thing not removed is listed with its kind's semantics, where
    it stands and, for a gate, where visitors arrive. A thing whose kind is not shipped at the
    digest it names makes the input unavailable by name. A thing of a kind its workspace keeps is
    read where ``made_kinds`` states that kind's run form, by its digest: it is listed by that
    reference alone, a being that lives in the society, and the input states the run form once.
    """
    if arrival is not None:
        if (
            arrival.source.world_id != version.world_id
            or arrival.source.version_id != version.version_id
            or arrival.source.source_snapshot_id != ground.snapshot_id
            or arrival.region_id != ground.region_id
        ):
            raise ValueError("arrival source does not belong to this authored ground and version")
        x, _, z = arrival.position_local_mm
        ground = replace(ground, arrival_x_mm=x, arrival_z_mm=z)
    return _authored_ground_with_routine(
        AUTHORED_GROUND_COMPOSITION_V5,
        ground=ground,
        version=version,
        input_seq=input_seq,
        dependency_refs=dependency_refs,
        availability=availability,
        unavailable_reason=unavailable_reason,
        reviewed_affordances=reviewed_affordances,
        segment_blocked=segment_blocked,
        standing=standing,
        routine=routine,
        arrival=arrival,
        workspace_obstacles=workspace_obstacles,
        things=True,
        made_kinds=made_kinds,
    )


def _authored_ground_with_routine(
    composition: str,
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    routine: PurposefulRoutine | None,
    arrival: ArrivalDescriptor | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
    things: bool = False,
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    chosen = purposeful_routine() if routine is None else routine
    catalog = world_object_catalog()
    check_object_kinds(chosen, catalog)
    kinds = catalog.by_asset_key()

    def activity(item: _UsableObject) -> dict[str, Any]:
        # A placed thing's activity is the routine's entry for its own kind, where it has one.
        kind = (
            item.reviewed["thing_kind"]
            if item.origin == "thing"
            else kinds[item.reviewed["asset_key"]].key
        )
        return {"activity": chosen.at_object(item.reviewed["affordance"], kind).key}

    document = _authored_ground_input(
        composition,
        activity,
        ground=ground,
        version=version,
        input_seq=input_seq,
        dependency_refs=dependency_refs,
        availability=availability,
        unavailable_reason=unavailable_reason,
        reviewed_affordances=reviewed_affordances,
        segment_blocked=segment_blocked,
        standing=standing,
        workspace_obstacles=workspace_obstacles,
        things=things,
        made_kinds=made_kinds,
    )
    del document["document_sha256"]
    document["routine"] = chosen.binding()
    # The things composition states its arrival either way: the pinned one, or none.
    if arrival is not None or things:
        document["arrival"] = None if arrival is None else arrival.model_dump(mode="json")
    if things:
        # Its population is made of the kind the ground's catalog entry names, recorded here so
        # genesis and replay read it from the input, whatever a later catalog version says.
        from exulanica.world.society_grounds import society_ground_for_navigation

        kind = society_ground_for_navigation(ground.navigation_profile).population_kind
        if kind is None:
            raise ValueError("the ground's catalog entry names no kind its population is made of")
        document["population_kind"] = dict(kind)
        # A society's first input records the modules its minutes run, by version.
        record_modules(document)
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    return document


def build_authored_ground_society_input_v2(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a saved world under ``exulanica.society-composition/authored-ground-v2``.

    What the first composition refused for the whole world it decides here object by object
    (``_objects_one_by_one``), and every activity it can offer carries the places its occupants
    stand at (``_place_targets``). An environment placement is named as unread: a saved world's
    ground states no surveyed origin to place an admitted source against, and the renderer draws
    no such placement in a saved world. Like the first composition it adds no authority of its
    own and refuses malformed binding, digest or registry data.
    """
    document = _authored_ground_input(
        AUTHORED_GROUND_COMPOSITION_V2,
        _fixed_duration,
        ground=ground,
        version=version,
        input_seq=input_seq,
        dependency_refs=dependency_refs,
        availability=availability,
        unavailable_reason=unavailable_reason,
        reviewed_affordances=reviewed_affordances,
        segment_blocked=segment_blocked,
        standing=standing,
        workspace_obstacles=workspace_obstacles,
    )
    validate_society_input(document)
    return document


def _authored_ground_input(
    composition: str,
    terms: Callable[[_UsableObject], dict[str, Any]],
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    segment_blocked: SegmentBlocked,
    standing: StandingPolicy,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
    things: bool = False,
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The projection the second and later compositions share, with its digest, unvalidated:
    with ``things``, the things composition's placed things too, those of a kind its workspace
    keeps where ``made_kinds`` states the kind's run form."""
    if version_delta_sha256(version) != version.state_sha256:
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
    validate_workspace_obstacles(workspace_obstacles)
    if availability not in ("available", "unavailable"):
        raise ValueError("invalid current availability")
    if (availability == "available") != (unavailable_reason is None):
        raise ValueError("availability and reason disagree")
    if version.world_id != ground.world_id:
        raise ValueError("authored ground belongs to another world")
    if (
        type(standing.spacing_mm) is not int
        or type(standing.radius_mm) is not int
        or not 0 < 2 * standing.radius_mm <= standing.spacing_mm
    ):
        raise ValueError("standing spacing keeps two standing radii apart")

    nav = ground_navigation(ground)
    nav["standing_spacing_mm"] = standing.spacing_mm
    reason = unavailable_reason or nav["unavailable_reason"]
    if version.source_snapshot_id != ground.snapshot_id:
        reason = reason or "authored_ground_snapshot_mismatch"
    if version.source_invalidated:
        reason = reason or "authored_source_invalidated"
    reason = reason or _ground_override_reason(ground, version.element_overrides)
    refs = [dict(ref) for ref in dependency_refs]
    refs.extend(
        policy_dependency_refs(
            composition_profile=composition,
            version_id=version.version_id,
            registration=ground.registration(),
            reviewed_affordances=reviewed_affordances,
        )
    )
    refs.extend(
        object_dependency_refs(
            version,
            reviewed_affordances,
            objects=objects_in_region(version, ground),
            workspace_obstacles=workspace_obstacles,
        )
    )
    placed = things_in_region(version, ground, made_kinds) if things else []
    if any(
        t.support is not None and not t.removed and t.region_id == ground.region_id
        for t in version.things
    ):
        reason = reason or "supported_thing_source_unavailable"
    thing_kinds, thing_refusal = _thing_kinds(placed, made_kinds)
    refs.extend(thing_dependency_refs(version.version_id, placed, thing_kinds))

    targets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    if reason is None:
        usable, obstacles, records, reason = _objects_one_by_one(
            version, reviewed_affordances, ground, workspace_obstacles
        )
    if reason is None and things:
        reason = thing_refusal
    if reason is None and things:
        thing_usable, thing_obstacles, thing_records = _things_one_by_one(
            placed, thing_kinds, ground, version.version_id
        )
        usable = [*usable, *thing_usable]
        obstacles = [*obstacles, *thing_obstacles]
        records = [*records, *thing_records]
    if reason is None:
        clear = clearance_test(
            obstacles,
            clearance_mm=nav["clearance_mm"],
            supports=area_supports(ground),
            segment_blocked=segment_blocked,
        )
        prune_navigation(nav, clear)
        if not nav["nodes"]:
            reason = "authored_obstacles_block_navigation"
    if reason is None:
        targets, unreachable = _place_targets(
            nav, usable, clear, version_id=version.version_id, standing=standing, terms=terms
        )
        records.extend(unreachable)
        unread = [
            {"instance_id": instance.instance_id, "reason": NO_AUTHORED_FRAME}
            for instance in sorted(
                version.environment_instances, key=lambda value: value.instance_id
            )
            if not instance.removed
        ]
    if reason is not None:
        nav.update(nodes=[], edges=[], destinations=[], unavailable_reason=reason)
        targets, records, unread = [], [], []
    nav["nodes"].sort(key=lambda node: node["node_id"])
    nav["edges"].sort(key=lambda edge: edge["edge_id"])
    targets.sort(key=lambda target: target["target_id"])
    deduplicated = {(r["kind"], r["identity"], r["sha256"]): r for r in refs}
    document = {
        "profile": input_profile(composition),
        "input_seq": input_seq,
        "world_id": version.world_id,
        "version_id": str(version.version_id),
        "district_id": ground.place_id,
        "district_document_sha256": ground.document_sha256,
        "base_artifact_sha256": ground.snapshot_sha256,
        "frame": ground.frame(),
        "authored_state": {"edit_seq": version.edit_seq, "delta_sha256": version.state_sha256},
        "navigation": nav,
        "targets": targets,
        "dependency_refs": [deduplicated[key] for key in sorted(deduplicated)],
        "availability": "available" if reason is None else "unavailable",
        "unavailable_reason": reason,
        "unavailable_affordances": sorted(records, key=lambda row: row["target_id"]),
        "unread_placements": unread,
    }
    if things:
        document["things"] = (
            [] if reason is not None else _input_things(placed, thing_kinds, ground)
        )
        if reason is None:
            state_made_kinds(document, thing_kinds, made_things_gone(version, ground, made_kinds))
    document["document_sha256"] = input_sha256(document)
    return document
