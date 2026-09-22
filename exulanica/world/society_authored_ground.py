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

The lattice over that area is a declared discretisation, not a measurement, and the module states
its spacing rather than deriving a walkable shape from anything the world does not say.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.errors import InvalidStructuralData
from exulanica.world.objects import AlternateVersion, delta_sha256
from exulanica.world.society import society_state_sha256
from exulanica.world.society_composition import (
    ComposedObject,
    Obstacle,
    Point,
    SegmentBlocked,
    Supports,
    affordance_targets,
    composed_objects,
    object_dependency_refs,
    policy_dependency_refs,
    validate_reviewed_affordances,
)
from exulanica.world.society_input_policy import AUTHORED_GROUND_COMPOSITION, input_profile
from exulanica.world.society_planner import CLEARANCE_MM, input_sha256, validate_society_input

#: The descriptor profile. It names the ground a saved world states, the area the society walks,
#: and the structural snapshot both were read from.
GROUND_PROFILE: Final = "exulanica.authored-ground/v2"
NAVIGATION_PROFILE: Final = "authored-ground-lattice/v1"
FRAME_NAME: Final = "authored-ground-local-mm"

#: The declared spacing of the route lattice, in millimetres. A flat rectangle has no paths of
#: its own, so a route graph over it is a choice this profile makes rather than a fact the world
#: states. Two metres keeps every point of the area within 1,415 mm of a lattice node, which is
#: inside the reviewed object reach, and keeps a 24 m area at 121 nodes. Changing it changes
#: every digest, so it is a versioned profile constant and not a tunable.
LATTICE_MM: Final = 2_000

#: The half extent of the square a society declares on a ground that states no edge, centred on
#: the region origin. It is the society's own area, never the ground's: an endless plane stays
#: endless in the stored world. The figure keeps the lattice at 121 nodes, which is what holds one
#: tick of 128 inhabitants near a tenth of a second, and it equals the only bounded starter ground
#: the product has shipped, so an old and a new starter give a society the same area and the same
#: node identities. An object placed outside it is still in the world and still drawn; the society
#: records that activity as unreachable rather than stretching its area to meet it.
DECLARED_HALF_EXTENT_MM: Final = 12_000

AreaSource = Literal["ground", "declared"]


@dataclass(frozen=True, slots=True)
class WalkableArea:
    """The axis-aligned rectangle a society may route across, and where that rectangle came from.

    ``source`` is the honesty field. ``ground`` means the world's ground module states this
    extent. ``declared`` means the ground states none and the society chose this one; a reader of
    a stored input can tell the two apart without knowing which module version the world uses.
    """

    source: AreaSource
    centre_x_mm: int
    centre_z_mm: int
    half_width_mm: int
    half_depth_mm: int

    def document(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "centre_mm": [self.centre_x_mm, self.centre_z_mm],
            "half_width_mm": self.half_width_mm,
            "half_depth_mm": self.half_depth_mm,
        }


@dataclass(frozen=True, slots=True)
class SocietyGround:
    """A saved world's authored ground as a society reads it, bound to the snapshot it came from.

    ``ground_kind`` is what the ground module states, ``flat`` for a bounded rectangle and
    ``endless`` for a plane with no edge. ``area`` is where the society walks.
    """

    world_id: str
    snapshot_id: uuid.UUID
    snapshot_sha256: str
    region_id: str
    element_id: str
    module_key: str
    module_version: int
    ground_kind: Literal["flat", "endless"]
    elevation_mm: int
    area: WalkableArea

    @property
    def place_id(self) -> str:
        """The spatial identity this ground publishes as the society input's area identity."""
        return f"authored:{self.region_id}"

    def document(self) -> dict[str, Any]:
        """The canonical descriptor, digest included, that the input binds and replay rechecks.

        An endless ground's descriptor carries no ground extent. The only extent in it is the
        society's, under ``walkable_area`` with its source.
        """
        document = {
            "profile": GROUND_PROFILE,
            "world_id": self.world_id,
            "snapshot_id": str(self.snapshot_id),
            "snapshot_sha256": self.snapshot_sha256,
            "region_id": self.region_id,
            "element_id": self.element_id,
            "module": {"key": self.module_key, "version": self.module_version},
            "ground_kind": self.ground_kind,
            "elevation_mm": self.elevation_mm,
            "walkable_area": self.area.document(),
            "clearance_mm": CLEARANCE_MM,
            "lattice_mm": LATTICE_MM,
        }
        document["document_sha256"] = society_state_sha256(document)
        return document

    @property
    def document_sha256(self) -> str:
        return str(self.document()["document_sha256"])

    def frame(self) -> dict[str, Any]:
        """East/south integer millimetres about the region origin.

        A saved world's ground is source-independent, so this frame states no geodetic origin
        rather than placing an authored world somewhere on the Earth it was never measured on.
        """
        return {
            "name": FRAME_NAME,
            "axis_order": ["east", "south"],
            "horizontal_unit": "millimetre",
            "altitude_reference": "authored-flat-ground",
        }

    def registration(self) -> dict[str, Any]:
        """The scoped registration a runtime binding and a stored input must both agree with."""
        return {
            "world_id": self.world_id,
            "snapshot_id": str(self.snapshot_id),
            "region_id": self.region_id,
            "element_id": self.element_id,
            "ground_document_sha256": self.document_sha256,
        }


def _axis(centre_mm: int, half_extent_mm: int) -> list[int]:
    """Lattice coordinates on one axis, inside the area and a full clearance from its edge.

    Coordinates are multiples of the lattice spacing about the region origin, so two areas that
    overlap give the same node identities where they overlap.
    """
    low = centre_mm - (half_extent_mm - CLEARANCE_MM)
    high = centre_mm + (half_extent_mm - CLEARANCE_MM)
    if low > high:
        return []
    first = -(-low // LATTICE_MM)
    last = high // LATTICE_MM
    return [value * LATTICE_MM for value in range(first, last + 1)]


def _node_id(x_mm: int, z_mm: int) -> str:
    return f"ground:{x_mm:+09d}:{z_mm:+09d}"


def area_supports(ground: SocietyGround) -> Supports:
    """A segment is supported when both ends lie in the area, a clearance inside its edge.

    The area is a convex rectangle, so two supported ends put the whole straight segment between
    them inside it; no sampling along it is needed or implied.
    """
    area = ground.area

    def supports(a: Point, b: Point, clearance_mm: int) -> Sequence[str]:
        width = area.half_width_mm - clearance_mm
        depth = area.half_depth_mm - clearance_mm
        if width < 0 or depth < 0:
            return ()
        for x_mm, z_mm in (a, b):
            if abs(x_mm - area.centre_x_mm) > width or abs(z_mm - area.centre_z_mm) > depth:
                return ()
        return (ground.element_id,)

    return supports


def ground_navigation(ground: SocietyGround) -> dict[str, Any]:
    """The route lattice over the society's area, before any object prunes it.

    Destinations are empty on purpose. A saved world's ground declares a spawn point, not an
    activity, and calling a spawn point a visit would invent an affordance the world never
    declared. Every activity in an authored world comes from a reviewed object on it.
    """
    area = ground.area
    xs = _axis(area.centre_x_mm, area.half_width_mm)
    zs = _axis(area.centre_z_mm, area.half_depth_mm)
    nodes = [
        {
            "node_id": _node_id(x_mm, z_mm),
            "subject_id": ground.element_id,
            "position_mm": [x_mm, z_mm],
        }
        for x_mm in xs
        for z_mm in zs
    ]
    edges = []
    for x_mm in xs:
        for z_mm in zs:
            for next_x, next_z in ((x_mm + LATTICE_MM, z_mm), (x_mm, z_mm + LATTICE_MM)):
                if next_x not in xs or next_z not in zs:
                    continue
                first, second = _node_id(x_mm, z_mm), _node_id(next_x, next_z)
                edges.append(
                    {
                        "edge_id": f"{first}|{second}",
                        "from_node_id": first,
                        "to_node_id": second,
                        "length_mm": LATTICE_MM,
                        "subject_id": ground.element_id,
                    }
                )
    nodes.sort(key=lambda node: node["node_id"])
    edges.sort(key=lambda edge: edge["edge_id"])
    return {
        "profile": NAVIGATION_PROFILE,
        "clearance_mm": CLEARANCE_MM,
        "walkable_area": area.document(),
        "nodes": nodes,
        "edges": edges,
        "destinations": [],
        "unavailable_reason": None if nodes else "walkable_area_smaller_than_clearance",
    }


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
) -> dict[str, Any]:
    """Compose one saved world's accepted authored version over its society's walkable area.

    The caller has already validated the ground against the world's structural authority and
    checked current asset rights; this function adds no authority of its own. It refuses
    malformed binding, digest or registry data rather than publishing a false receipt.
    """
    # Placed depth estimates take part in the digest and in nothing else here, as in the district
    # projection: they are drawn, and they are neither ground to stand on nor an obstacle.
    if (
        delta_sha256(
            version.objects,
            version.element_overrides,
            version.environment_instances,
            version.point_map_instances,
        )
        != version.state_sha256
    ):
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
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
    refs.extend(object_dependency_refs(version, reviewed_affordances))

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


def authored_ground_from_snapshot(
    *,
    world_id: str,
    snapshot_id: uuid.UUID,
    snapshot_sha256: str,
    composer_key: str,
    composer_version: int,
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
) -> SocietyGround:
    """Read a saved world's ground out of its own structural snapshot, and say where to walk.

    Delegates to the starter authority, which refuses any snapshot that is not exactly the
    built-in authored starter at a supported ground module version. A bounded ground gives the
    society the extent it states. An endless ground states none, so the society declares its own
    area and marks it declared. A ground of any other kind is refused with
    ``InvalidStructuralData``, never read by guessing which attributes it might have.
    """
    from exulanica.world.starter import (
        AUTHORED_STARTER_ELEMENT_ID,
        BoundedAuthoredGround,
        EndlessAuthoredGround,
        authored_starter_scene,
    )

    scene = authored_starter_scene(
        composer_key=composer_key,
        composer_version=composer_version,
        topology=topology,
        placement=placement,
    )
    region = scene.region
    stated = region.ground
    if isinstance(stated, BoundedAuthoredGround):
        kind: Literal["flat", "endless"] = "flat"
        area = WalkableArea("ground", 0, 0, stated.half_width_mm, stated.half_depth_mm)
    elif isinstance(stated, EndlessAuthoredGround):
        kind = "endless"
        area = WalkableArea("declared", 0, 0, DECLARED_HALF_EXTENT_MM, DECLARED_HALF_EXTENT_MM)
    else:
        raise InvalidStructuralData(
            f"a society has no rule for an authored ground of kind {type(stated).__name__}"
        )
    return SocietyGround(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
        region_id=region.region_id,
        element_id=AUTHORED_STARTER_ELEMENT_ID,
        module_key=region.module.key,
        module_version=region.module.version,
        ground_kind=kind,
        elevation_mm=stated.elevation_mm,
        area=area,
    )
