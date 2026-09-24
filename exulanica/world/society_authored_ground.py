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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.errors import InvalidStructuralData
from exulanica.world.objects import AuthoredObject, ElementOverride, Transform
from exulanica.world.society import society_state_sha256
from exulanica.world.society_composition import (
    PLACES_FIELD,
    ComposedObject,
    Obstacle,
    Point,
    SegmentBlocked,
    Supports,
    affordance_targets,
    clearance_test,
    composed_objects,
    footprint_ring,
    object_dependency_refs,
    offers_activity,
    policy_dependency_refs,
    prune_navigation,
    turned_point,
    validate_reviewed_affordances,
)
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION_V2,
    MOVES,
    NO_AUTHORED_FRAME,
    OFF_GROUND,
    UNREACHABLE,
    UNSUPPORTED_BEHAVIOUR,
    input_profile,
)
from exulanica.world.society_place import ceil_distance
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

#: How many inhabitants a society on a saved world's own ground starts with. The area is a square
#: about 23 metres across with 121 places to stand, and a population sized for a district (128)
#: would stand people on top of each other from the first minute. A handful reads as people living
#: somewhere. The repository reads this at the moment it creates a society, so a measurement can
#: set another value in-process; a district keeps ``SOCIETY_POPULATION``.
AUTHORED_GROUND_POPULATION: Final = 8

AreaSource = Literal["ground", "declared"]

#: How a place's node is named: this prefix, the object's own identity and the place's index in
#: the order ``destination_places`` fills them, so a place keeps its identity when another drops.
PLACE_NODE_PREFIX: Final = "place:"


@dataclass(frozen=True, slots=True)
class StandingPolicy:
    """How far apart two standing people keep and how wide one of them is, in millimetres.

    Both are read from the society policy catalog (``standing_spacing_mm`` and
    ``standing_radius_mm``), where their reasons are stated, so the places a destination offers
    and the spacing the living society keeps are one pair of figures. A composed input records
    the spacing it used, so replay never reads the catalog.
    """

    spacing_mm: int
    radius_mm: int


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
    #: Where a person arrives in this world, on the ground plane: the snapshot's own spawn.
    arrival_x_mm: int
    arrival_z_mm: int

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
            "arrival_mm": [self.arrival_x_mm, self.arrival_z_mm],
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

    def element_transform(self) -> Transform:
        """Where the ground element stands, as the snapshot places it.

        The starter authority accepts a snapshot only when its ground element stands at the
        region origin, unturned and unscaled, at the stated elevation
        (``exulanica.world.starter._authored_starter_candidate``), so this is read, not assumed.
        """
        return Transform(
            x_mm=0, y_mm=self.elevation_mm, z_mm=0, yaw_microradians=0, scale_milli=1000
        )


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
        # Where a person arrives. Inhabitants never start on it or beside it; see the initializer.
        "arrival_mm": [ground.arrival_x_mm, ground.arrival_z_mm],
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
    if version_delta_sha256(version) != version.state_sha256:
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


# The second saved-world composition. An object the society cannot use costs its own activity
# and nothing else; only something that leaves the society unable to say where it may walk
# takes the whole world with it. Every activity also states the places its occupants stand at.


def convex_ring(points: Sequence[Point]) -> list[Point]:
    """The closed convex hull of integer points, counter-clockwise, in exact integer arithmetic."""
    ordered = sorted(set(points))
    if len(ordered) < 3:
        return [*ordered, ordered[0]]

    def cross(o: Point, a: Point, b: Point) -> int:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for point in ordered:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], point) <= 0:
            lower.pop()
        lower.append(point)
    upper: list[Point] = []
    for point in reversed(ordered):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], point) <= 0:
            upper.pop()
        upper.append(point)
    hull = lower[:-1] + upper[:-1]
    return [*hull, hull[0]]


def _bounded_path_ring(parameters: Mapping[str, Any], ring: list[Point]) -> list[Point]:
    """Everywhere a ``motion.bounded-path`` object covers on its way out and back.

    The object travels ``travel_mm`` along one axis of its region from where it was placed and
    returns (``web/packages/atlas-core/src/behaviour/bounded-motion.ts``: the authored transform
    is one end of the path). Its footprint moved along a straight line sweeps exactly the convex
    hull of the footprint at the two ends. Travel along ``y`` leaves the plan footprint where it
    is. Malformed parameters are refused rather than read as no travel.
    """
    travel = parameters.get("travel_mm")
    axis = parameters.get("axis")
    if type(travel) is not int or not 0 <= travel <= 10**9 or axis not in ("x", "y", "z"):
        raise ValueError("unreadable bounded path")
    if axis == "y":
        return ring
    dx, dz = (travel, 0) if axis == "x" else (0, travel)
    corners = ring[:-1]
    return convex_ring([*corners, *((x + dx, z + dz) for x, z in corners)])


#: The behaviours whose extent the society can state, by reviewed registry key and version, each
#: mapped to the rule that turns a footprint into everywhere the object covers while it moves. A
#: behaviour with no rule here is refused by name.
SWEPT_BEHAVIOURS: Final[
    Mapping[tuple[str, int], Callable[[Mapping[str, Any], list[Point]], list[Point]]]
] = {("motion.bounded-path", 1): _bounded_path_ring}


@dataclass(frozen=True, slots=True)
class _UsableObject:
    obj: AuthoredObject
    reviewed: Mapping[str, Any]
    centre: Point
    half_extents: tuple[int, int]


def _scaled(half_extents: Sequence[int], scale_milli: int) -> tuple[int, int]:
    """Reviewed half extents at an object's scale, rounded up to the whole millimetre."""
    hx, hz = half_extents
    return (-(-hx * scale_milli // 1000), -(-hz * scale_milli // 1000))


def _refused_activity(
    version_id: uuid.UUID, obj: AuthoredObject, reviewed: Mapping[str, Any], reason: str
) -> dict[str, Any]:
    subject_id = f"authored:{version_id}:{obj.object_id}"
    return {
        "target_id": f"{subject_id}:{reviewed['affordance']}",
        "subject_id": subject_id,
        "object_id": obj.object_id,
        "version_id": str(version_id),
        "affordance": reviewed["affordance"],
        "reason": reason,
    }


def _objects_one_by_one(
    version: AlternateVersion,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    ground: SocietyGround,
) -> tuple[list[_UsableObject], list[Obstacle], list[dict[str, Any]], str | None]:
    """Every object's obstacle and activity, decided for that object alone.

    A turned or scaled object is used as it stands: its reviewed footprint turns and scales with
    it. An object that moves blocks everywhere its motion covers and offers no activity. An
    object that does not rest on the ground plane still blocks its footprint, because the society
    cannot tell whether a body passes under it, and offers no activity. Only an object whose
    footprint the society cannot state (an unreviewed asset, a behaviour with no rule on an object
    that blocks) or that the saved world does not validly hold (another region, an origin or a
    transform no writer produces) makes the whole input unavailable, and the reason names it. A
    kind nobody uses (its registry row offers no activity) is only what it blocks: it is an
    obstacle wherever it stands, and it has no activity to offer or to record as refused.
    """
    usable: list[_UsableObject] = []
    obstacles: list[Obstacle] = []
    records: list[dict[str, Any]] = []
    for obj in sorted(version.objects, key=lambda value: value.object_id):
        if obj.removed:
            continue
        reviewed = reviewed_affordances.get(obj.asset_sha256)
        transform = obj.transform
        if obj.region_id != ground.region_id:
            return [], [], [], f"unregistered_object_region:{obj.object_id}"
        if reviewed is None:
            return [], [], [], f"unknown_active_asset:{obj.object_id}"
        if obj.origin.kind != "authored" or obj.origin.role not in ("fictional", "personal"):
            return [], [], [], f"unsupported_object_origin:{obj.object_id}"
        numbers = (
            transform.x_mm,
            transform.y_mm,
            transform.z_mm,
            transform.yaw_microradians,
            transform.scale_milli,
        )
        if (
            any(type(value) is not int or abs(value) > 10**9 for value in numbers)
            or transform.scale_milli < 1
        ):
            return [], [], [], f"unsupported_object_transform:{obj.object_id}"
        centre = (transform.x_mm, transform.z_mm)
        half = _scaled(reviewed["footprint_half_extents_mm"], transform.scale_milli)
        ring = footprint_ring(centre, half, transform.yaw_microradians)
        refusal: str | None = None
        if obj.behaviour is not None:
            rule = SWEPT_BEHAVIOURS.get(
                (obj.behaviour.behaviour_key, obj.behaviour.behaviour_version)
            )
            if rule is None:
                if reviewed["blocks_navigation"]:
                    return [], [], [], f"unsupported_active_behaviour:{obj.object_id}"
                refusal = UNSUPPORTED_BEHAVIOUR
            else:
                try:
                    ring = rule(obj.behaviour.parameters, ring)
                except ValueError:
                    return [], [], [], f"unsupported_active_behaviour:{obj.object_id}"
                refusal = MOVES
        if refusal is None and transform.y_mm != ground.elevation_mm:
            refusal = OFF_GROUND
        if reviewed["blocks_navigation"]:
            obstacles.append((obj.object_id, ring))
        if not offers_activity(reviewed):
            continue
        if refusal is None:
            usable.append(_UsableObject(obj, reviewed, centre, half))
        else:
            records.append(_refused_activity(version.version_id, obj, reviewed, refusal))
    return usable, obstacles, records, None


def _ground_override_reason(
    ground: SocietyGround, overrides: Sequence[ElementOverride]
) -> str | None:
    """An override that changes the ground changes where anybody stands, so it is refused.

    A saved world's snapshot has one element, its ground. An override that keeps the ground
    exactly where the snapshot places it changes nothing the society reads. Anything else is the
    ground itself being hidden or moved, which is not an object, and the input names it.
    """
    for override in sorted(overrides, key=lambda value: value.element_id):
        if override.element_id != ground.element_id:
            return f"unsupported_structural_override:{override.element_id}"
        if override.suppressed or override.transform != ground.element_transform():
            return f"unsupported_ground_override:{override.element_id}"
    return None


def destination_places(
    usable: _UsableObject, standing: StandingPolicy, clearance_mm: int
) -> list[Point]:
    """Where the occupants of one object's activity stand, in the order they are filled.

    A kind whose registry row states its places (``places_mm``, from the world object catalog)
    holds one person at each, in the catalog's order: the catalog derived each from the same
    clearance, radius and spacing, with the margin a turn can take from the gap between two
    (``TURNED_PLACE_MARGIN_MM``). Otherwise an object a person can walk on (one that
    blocks nothing, like a plate) holds a row of people along its own x axis, one standing
    spacing apart and centred on it, as many as have their centres on it, and an object that
    blocks walking holds one person in front of each face, a navigation clearance and a standing
    radius out from it, so the whole body stands outside the line no walker's centre crosses. The
    places turn and scale with the object.
    """
    hx, hz = usable.half_extents
    stated = usable.reviewed.get(PLACES_FIELD)
    offsets: list[tuple[float, float]]
    if stated is not None:
        scale = usable.obj.transform.scale_milli
        offsets = [(dx * scale / 1000, dz * scale / 1000) for dx, dz in stated]
    elif usable.reviewed["blocks_navigation"]:
        out = clearance_mm + standing.radius_mm
        offsets = [
            (0, -(hz + out)),
            (hx + out, 0),
            (0, hz + out),
            (-(hx + out), 0),
        ]
    else:
        count = 1 + (2 * hx) // standing.spacing_mm
        offsets = [((2 * k - count + 1) * standing.spacing_mm / 2, 0) for k in range(count)]
    yaw = usable.obj.transform.yaw_microradians
    return [turned_point(usable.centre, offset, yaw) for offset in offsets]


def standing_places(
    version: AlternateVersion,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    ground: SocietyGround,
    standing: StandingPolicy,
) -> dict[str, list[Point]]:
    """Where people would stand to use each object of a version, by object id.

    Every object the society offers an activity at, decided as the society decides it
    (``_objects_one_by_one``), with its places as the society turns and scales them
    (``destination_places``), before it keeps only those clear, spaced and reachable. A version
    the society cannot compose at all has nobody standing anywhere.
    """
    usable, _, _, reason = _objects_one_by_one(version, reviewed_affordances, ground)
    if reason is not None:
        return {}
    return {item.obj.object_id: destination_places(item, standing, CLEARANCE_MM) for item in usable}


def _squared(a: Sequence[int], b: Sequence[int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _place_targets(
    nav: dict[str, Any],
    usable: Sequence[_UsableObject],
    clear: Callable[..., bool],
    *,
    version_id: uuid.UUID,
    standing: StandingPolicy,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Give each usable activity the places its occupants stand at, joined to the lattice.

    A place is kept when it lies in the area, clear of every obstacle, at least a standing spacing
    from every place kept before it, and within the object's reviewed reach of a lattice node it
    can be walked to from in a straight clear line. It becomes a node joined by one edge to the
    nearest such lattice node, so a route ends where the person stands and nowhere else. An
    activity with no place kept is recorded as unreachable. ``nav`` is extended in place.
    """
    clearance = nav["clearance_mm"]
    connected = {e[key] for e in nav["edges"] for key in ("from_node_id", "to_node_id")}
    lattice = [n for n in nav["nodes"] if n["node_id"] in connected]
    kept: list[Point] = []
    targets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for item in sorted(usable, key=lambda value: value.obj.object_id):
        obj, reviewed = item.obj, item.reviewed
        subject_id = f"authored:{version_id}:{obj.object_id}"
        reach = reviewed["reach_mm"]
        chosen: list[tuple[str, Point, dict[str, Any]]] = []
        for index, point in enumerate(destination_places(item, standing, clearance)):
            if not clear(point, point):
                continue
            if any(_squared(point, other) < standing.spacing_mm**2 for other in kept):
                continue
            joins = sorted(
                (_squared(node["position_mm"], point), node["node_id"], node)
                for node in lattice
                if _squared(node["position_mm"], point) <= reach**2
                and clear(tuple(node["position_mm"]), point)
            )
            if not joins:
                continue
            kept.append(point)
            chosen.append((f"{PLACE_NODE_PREFIX}{obj.object_id}:{index}", point, joins[0][2]))
        if not chosen:
            records.append(_refused_activity(version_id, obj, reviewed, UNREACHABLE))
            continue
        for node_id, point, join in chosen:
            nav["nodes"].append(
                {"node_id": node_id, "subject_id": subject_id, "position_mm": list(point)}
            )
            nav["edges"].append(
                {
                    "edge_id": f"{join['node_id']}|{node_id}",
                    "from_node_id": join["node_id"],
                    "to_node_id": node_id,
                    "length_mm": ceil_distance(join["position_mm"], point),
                    "subject_id": subject_id,
                }
            )
        targets.append(
            {
                "target_id": f"{subject_id}:{reviewed['affordance']}",
                "subject_id": subject_id,
                "node_id": chosen[0][2]["node_id"],
                "affordance": reviewed["affordance"],
                "duration_ticks": reviewed["duration_ticks"],
                "origin": "authored",
                "object_id": obj.object_id,
                "version_id": str(version_id),
                "enabled": True,
                "place_node_ids": [node_id for node_id, _, _ in chosen],
            }
        )
    return targets, records


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
) -> dict[str, Any]:
    """Compose a saved world under ``exulanica.society-composition/authored-ground-v2``.

    What the first composition refused for the whole world it decides here object by object
    (``_objects_one_by_one``), and every activity it can offer carries the places its occupants
    stand at (``_place_targets``). An environment placement is named as unread: a saved world's
    ground states no surveyed origin to place an admitted source against, and the renderer draws
    no such placement in a saved world. Like the first composition it adds no authority of its
    own and refuses malformed binding, digest or registry data.
    """
    if version_delta_sha256(version) != version.state_sha256:
        raise ValueError("authored delta digest mismatch")
    validate_reviewed_affordances(reviewed_affordances)
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
            composition_profile=AUTHORED_GROUND_COMPOSITION_V2,
            version_id=version.version_id,
            registration=ground.registration(),
            reviewed_affordances=reviewed_affordances,
        )
    )
    refs.extend(object_dependency_refs(version, reviewed_affordances))

    targets: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    unread: list[dict[str, Any]] = []
    if reason is None:
        usable, obstacles, records, reason = _objects_one_by_one(
            version, reviewed_affordances, ground
        )
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
            nav, usable, clear, version_id=version.version_id, standing=standing
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
        "profile": input_profile(AUTHORED_GROUND_COMPOSITION_V2),
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
        arrival_x_mm=region.spawn.x_mm,
        arrival_z_mm=region.spawn.z_mm,
    )
