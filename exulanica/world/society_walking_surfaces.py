"""The society over a world whose own records state its walking surfaces.

A world generated from the city grammar states, in its records, every surface a person stands on:
footways beside their kerbs, corners, crossings and the entrances of its premises. Its society
walks those, not a lattice over a declared square. This module reads such a world's ground from
its structural snapshot (:func:`walking_surfaces_ground`) and composes the purposeful society's
input over the world's records (:func:`build_walking_surfaces_input`), under
``exulanica.society-composition/walking-surfaces-v1``:

* **The graph** is the city place the living society reads a city by
  (:func:`~exulanica.world.society_city_place.place_from_city_records`): its nodes and edges,
  each position turned into the region's east and south millimetres, each node named by the kind
  of surface it stands on and each edge by what it crosses. The positions are plan positions; the
  height a person stands at stays in the records.
* **The activities** are the world's own. Every premises whose use class admits visitors is
  somewhere to visit, stood at at its entrance, and every piece of street furniture whose use
  class seats people is somewhere to rest, one place per seat, each seat a node joined to the
  furniture's access node. Places keep a standing spacing apart in destination order; one that
  cannot is recorded as unreachable, as an object the person placed in the world is: the
  composition joins nothing a person placed to the world's surfaces.
* **The population** is the ground's rule over the world's premises: one inhabitant per place in
  a home, counted from every premises the place reaches (``population``). A count past the
  ground's figure is refused by name before the input is validated, and the repository holds the
  recorded figure to it again (:func:`~exulanica.world.society_grounds.society_population`).

Pure: no connection and no store. The caller reads the records through the world's receipt
(:func:`exulanica.world.generated_worlds.town_records`) and makes the place from them
(:func:`walking_surfaces_place`) before it takes any lock, so composing the input generates
nothing.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any, Final

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.composers import composer_module
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.society_authored_ground import (
    SocietyGround,
    StandingPolicy,
    WalkableArea,
    _refused_activity,
    objects_in_region,
)
from exulanica.world.society_catalogs import PurposefulRoutine, RoutineModel, purposeful_routine
from exulanica.world.society_city_place import place_from_city_records
from exulanica.world.society_composition import (
    object_dependency_refs,
    policy_dependency_refs,
    validate_reviewed_affordances,
    validate_workspace_obstacles,
)
from exulanica.world.society_grounds import (
    SocietyGroundKind,
    place_dependency_for,
    refuse_population_over_budget,
    society_ground_for_navigation,
)
from exulanica.world.society_input_policy import (
    NO_AUTHORED_FRAME,
    UNREACHABLE,
    WALKING_SURFACES_COMPOSITION,
    WALKING_SURFACES_COMPOSITION_V2,
    input_profile,
)
from exulanica.world.society_living import current_routine
from exulanica.world.society_place import ceil_distance
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    input_sha256,
    validate_society_input,
)

__all__ = [
    "SEAT_NODE_PREFIX",
    "build_walking_surfaces_input",
    "place_residents",
    "walking_surfaces_ground",
    "walking_surfaces_place",
]

#: How a seat's own node is named: this prefix and the seat's spot identity.
SEAT_NODE_PREFIX: Final = "seat:"
#: The purposeful activity each kind of the world's destination offers, by the affordance its
#: use class states: a premises that admits visitors is visited, furniture that seats people is
#: rested at. Anything else the world holds is somewhere people pass, not an activity.
_VISIT: Final = "visit"
_REST: Final = "rest"


def walking_surfaces_ground(
    kind: SocietyGroundKind,
    *,
    world_id: str,
    snapshot_id: uuid.UUID,
    snapshot_sha256: str,
    composer_key: str,
    composer_version: int,
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
    region_id: str | None,
) -> SocietyGround:
    """A generated world's ground: its one region, the rectangle its tiles cover and its spawn.

    The world's composer reads its own snapshot (``stated_extent``); a snapshot it refuses, or a
    region the world does not state, is refused by name. The walkable area is the rectangle a
    walking clearance beyond each edge, because the world's surfaces run to its edge and every
    route node keeps a clearance inside the area it is published under.
    """
    if (kind.navigation, kind.floor, kind.arrival) != ("walking_surfaces", "stated", "spawn"):
        raise InvalidStructuralData(
            f"a world's walking surfaces are read on a floor it states from its spawn, not "
            f"{kind.navigation} on a {kind.floor} floor from its {kind.arrival}"
        )
    try:
        stated = composer_module(composer_key, composer_version).stated_extent(topology, placement)
    except ValueError as exc:
        raise InvalidStructuralData(str(exc)) from exc
    if region_id is not None and region_id != stated.region_id:
        raise InvalidStructuralData(f"the generated world states no region {region_id!r}")
    west, east = stated.east_mm
    north, south = stated.south_mm
    return SocietyGround(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
        region_id=stated.region_id,
        element_id=None,
        module_key=composer_key,
        module_version=composer_version,
        ground_kind="surfaces",
        elevation_mm=0,
        area=WalkableArea(
            "ground",
            (west + east) // 2,
            (north + south) // 2,
            (east - west) // 2 + CLEARANCE_MM,
            (south - north) // 2 + CLEARANCE_MM,
        ),
        arrival_x_mm=stated.arrival_mm[0],
        arrival_z_mm=stated.arrival_mm[2],
        world_region_ids=stated.region_ids,
        lattice_mm=kind.lattice_mm,
        navigation_profile=kind.navigation_profile,
        navigation_form=kind.navigation,
    )


def _node_kind(node_id: str) -> str:
    """What a place node stands on, from its identity: the kind the place producer names it by."""
    return node_id.split(":", 1)[0]


def _squared(a: Sequence[int], b: Sequence[int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _world_target_record(
    version_id: uuid.UUID, destination: Mapping[str, Any], affordance: str
) -> dict[str, Any]:
    """An activity of the world's own that no place can be kept for, recorded as unreachable."""
    object_id, subject_id = _subject(destination)
    return {
        "target_id": f"{subject_id}:{affordance}",
        "subject_id": subject_id,
        "object_id": object_id,
        "version_id": str(version_id),
        "affordance": affordance,
        "reason": UNREACHABLE,
    }


def _subject(destination: Mapping[str, Any]) -> tuple[str, str]:
    """A destination's object and the record subject it names: the place states its subject
    (``city.premises:<identity>`` for a city's premises, ``site.structure:<identity>`` for a site's
    structure), whose identity is the destination's own after its prefix."""
    object_id = destination["destination_id"].split(":", 1)[1]
    subject_id = str(destination["subject_id"])
    if subject_id.split(":", 1)[1] != object_id:
        raise ValueError("a destination's subject names another record than the destination")
    return object_id, subject_id


def _affordance(destination: Mapping[str, Any]) -> str | None:
    if destination["origin"] == "premises" and destination["visitor_capacity"] > 0:
        return _VISIT
    if destination["origin"] == "furniture" and _REST in destination["affordances"]:
        return _REST
    return None


def walking_surfaces_place(
    place_id: str, records: Sequence[object], routine: RoutineModel | None = None
) -> dict[str, Any]:
    """The city place a generated world's records make: its walking surfaces, spots, premises and
    furniture, as the living society reads a city (:func:`place_from_city_records`), under
    ``routine`` (the living routine a new district reads when left out; a town's living input
    names the routine its place was made under). The costly half of composing the world's input,
    so a caller makes it before taking any lock and hands it to
    :func:`build_walking_surfaces_input`, which does no generation of its own."""
    return place_from_city_records(
        place_id=place_id,
        records=list(records),
        routine=current_routine() if routine is None else routine,
    )


def place_residents(place: Mapping[str, Any]) -> int:
    """The population the ``residents`` rule gives a place: one inhabitant for each place in a home,
    the resident capacity of every destination the place reaches. The society's input records it,
    and a world's composer refuses a candidate whose count no society over its ground may hold."""
    return sum(
        int(destination.get("resident_capacity", 0)) for destination in place["destinations"]
    )


def build_walking_surfaces_input(
    *,
    ground: SocietyGround,
    version: AlternateVersion,
    place: Mapping[str, Any],
    input_seq: int,
    dependency_refs: Sequence[dict[str, str]],
    availability: str,
    unavailable_reason: str | None,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    standing: StandingPolicy,
    routine: PurposefulRoutine | None = None,
    living: RoutineModel | None = None,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compose a generated world's input over the walking surfaces its records state, from the
    place :func:`walking_surfaces_place` made of them for ``ground``.

    With ``living``, the living routine ``place`` was made under, the input is a
    walking-surfaces-v2 input that also carries the place itself, for the living town to walk;
    without it, the walking-surfaces-v1 input the purposeful society reads."""
    if version_delta_sha256(version) != version.state_sha256:
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
    validate_workspace_obstacles(workspace_obstacles)
    if availability not in ("available", "unavailable"):
        raise ValueError("invalid current availability")
    if (availability == "available") != (unavailable_reason is None):
        raise ValueError("availability and reason disagree")
    if version.world_id != ground.world_id:
        raise ValueError("the ground belongs to another world")
    if ground.navigation_form != "walking_surfaces":
        raise ValueError("this composition walks a world's own surfaces")
    chosen = purposeful_routine() if routine is None else routine
    composition = (
        WALKING_SURFACES_COMPOSITION if living is None else WALKING_SURFACES_COMPOSITION_V2
    )
    if living is not None and place.get("routine_sha256") != living.sha256:
        raise ValueError("the place was made under another living routine")
    if place.get("place_id") != ground.place_id:
        raise ValueError("the place was made for another ground")
    reason = unavailable_reason
    if version.source_snapshot_id != ground.snapshot_id:
        reason = reason or "authored_ground_snapshot_mismatch"
    if version.source_invalidated:
        reason = reason or "authored_source_invalidated"
    if version.element_overrides:
        reason = reason or "unsupported_structural_overrides"
    if place["availability"] != "available":
        reason = reason or f"walking_surfaces_unavailable:{place['unavailable_reason']}"

    def point(position: Sequence[int]) -> list[int]:
        return [position[0], -position[1]]

    nodes = [
        {
            "node_id": node["node_id"],
            "subject_id": _node_kind(node["node_id"]),
            "position_mm": point(node["position_mm"]),
        }
        for node in place["nodes"]
    ]
    edges = [
        {
            "edge_id": edge["edge_id"],
            "from_node_id": edge["from_node_id"],
            "to_node_id": edge["to_node_id"],
            "length_mm": edge["length_mm"],
            "subject_id": edge["kind"],
        }
        for edge in place["edges"]
    ]
    by_node = {node["node_id"]: node for node in nodes}
    spots = {spot["spot_id"]: spot for spot in place["spots"]}
    targets: list[dict[str, Any]] = []
    records_list: list[dict[str, Any]] = []
    kept: list[list[int]] = []
    residents = place_residents(place)
    for destination in sorted(place["destinations"], key=lambda d: d["destination_id"]):
        affordance = _affordance(destination)
        if affordance is None or not destination["enabled"]:
            continue
        if destination["origin"] == "premises":
            candidates = [(destination["node_id"], by_node[destination["node_id"]]["position_mm"])]
        else:
            candidates = [
                (f"{SEAT_NODE_PREFIX}{spot_id}", point(spots[spot_id]["position_mm"]))
                for spot_id in destination["spot_ids"]
            ]
        places = []
        for node_id, position in candidates:
            if any(_squared(position, other) < standing.spacing_mm**2 for other in kept):
                continue
            kept.append(position)
            places.append((node_id, position))
        if not places:
            records_list.append(_world_target_record(version.version_id, destination, affordance))
            continue
        object_id, subject_id = _subject(destination)
        if destination["origin"] == "furniture":
            access = by_node[destination["node_id"]]
            for node_id, position in places:
                nodes.append(
                    {"node_id": node_id, "subject_id": subject_id, "position_mm": position}
                )
                edges.append(
                    {
                        "edge_id": f"{access['node_id']}|{node_id}",
                        "from_node_id": access["node_id"],
                        "to_node_id": node_id,
                        "length_mm": ceil_distance(access["position_mm"], position),
                        "subject_id": subject_id,
                    }
                )
        targets.append(
            {
                "target_id": f"{subject_id}:{affordance}",
                "subject_id": subject_id,
                "node_id": destination["node_id"],
                "affordance": affordance,
                "activity": chosen.default(affordance).key,
                "origin": destination["origin"],
                "object_id": object_id,
                "version_id": str(version.version_id),
                "enabled": True,
                "place_node_ids": [node_id for node_id, _ in places],
            }
        )
    # A world whose homes hold more people than a society over its ground may is refused by that
    # name here, before the input is validated against the schema's own ceiling of 512.
    refuse_population_over_budget(
        residents, society_ground_for_navigation(ground.navigation_profile)
    )
    in_region = objects_in_region(version, ground)
    for obj in in_region:
        reviewed = reviewed_affordances.get(obj.asset_sha256)
        if not obj.removed and reviewed is not None and reviewed.get("affordance"):
            records_list.append(_refused_activity(version.version_id, obj, reviewed, UNREACHABLE))
    unread = [
        {"instance_id": instance.instance_id, "reason": NO_AUTHORED_FRAME}
        for instance in sorted(version.environment_instances, key=lambda value: value.instance_id)
        if not instance.removed
    ]
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
            objects=in_region,
            workspace_obstacles=workspace_obstacles,
        )
    )
    refs.append(
        {
            # The kind of place its ground says the producer of its surfaces makes.
            "kind": place_dependency_for(ground.navigation_profile),
            "identity": ground.place_id,
            "sha256": place["document_sha256"],
        }
    )
    navigation = {
        "profile": ground.navigation_profile,
        "clearance_mm": CLEARANCE_MM,
        "walkable_area": ground.area.document(),
        "arrival_mm": [ground.arrival_x_mm, ground.arrival_z_mm],
        "nodes": sorted(nodes, key=lambda node: node["node_id"]),
        "edges": sorted(edges, key=lambda edge: edge["edge_id"]),
        "destinations": [],
        "unavailable_reason": None,
        "standing_spacing_mm": standing.spacing_mm,
    }
    if reason is not None:
        navigation.update(nodes=[], edges=[], unavailable_reason=reason)
        targets, records_list, unread = [], [], []
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
        "navigation": navigation,
        "targets": sorted(targets, key=lambda target: target["target_id"]),
        "dependency_refs": [deduplicated[key] for key in sorted(deduplicated)],
        "availability": "available" if reason is None else "unavailable",
        "unavailable_reason": reason,
        "unavailable_affordances": sorted(records_list, key=lambda row: row["target_id"]),
        "unread_placements": unread,
        "routine": chosen.binding(),
        "population": {"rule": "residents", "size": residents},
    }
    if living is not None:
        document["living"] = {
            "routine": living.binding(),
            "place": dict(place) if reason is None else None,
        }
    document["document_sha256"] = input_sha256(document)
    validate_society_input(document)
    return document
