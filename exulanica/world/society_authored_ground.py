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
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from exulanica.things.catalogs import thing_catalogs
from exulanica.things.kinds import ThingKind
from exulanica.world.arrival_selection import ArrivalDescriptor
from exulanica.world.authored_delta import AlternateVersion, version_delta_sha256
from exulanica.world.errors import InvalidStructuralData, InvalidThingPlacement
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.objects import AuthoredObject, ElementOverride, Transform
from exulanica.world.placed_things import PlacedThing, placed_thing_document, shipped_kind
from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import (
    PurposefulRoutine,
    check_object_kinds,
    purposeful_routine,
)
from exulanica.world.society_composition import (
    PLACES_FIELD,
    REVIEWED_REACH_MM,
    ComposedObject,
    Obstacle,
    Point,
    SegmentBlocked,
    Supports,
    affordance_targets,
    clearance_test,
    composed_objects,
    footprint_ring,
    object_affordance,
    object_dependency_refs,
    offers_activity,
    policy_dependency_refs,
    prune_navigation,
    turned_point,
    validate_reviewed_affordances,
    validate_workspace_obstacles,
)
from exulanica.world.society_grounds import (
    SocietyGroundKind,
    UnknownSocietyGround,
    society_ground_for_composer,
)
from exulanica.world.society_input_policy import (
    AUTHORED_GROUND_COMPOSITION,
    AUTHORED_GROUND_COMPOSITION_V2,
    AUTHORED_GROUND_COMPOSITION_V3,
    AUTHORED_GROUND_COMPOSITION_V4,
    AUTHORED_GROUND_COMPOSITION_V5,
    MOVES,
    NO_AUTHORED_FRAME,
    OFF_GROUND,
    UNREACHABLE,
    UNSUPPORTED_BEHAVIOUR,
    input_profile,
)
from exulanica.world.society_place import ceil_distance
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    DURATIONS,
    WALKING_SURFACES_ALTITUDE,
    WALKING_SURFACES_FRAME,
    input_sha256,
    validate_society_input,
)
from exulanica.world.starter import AUTHORED_STARTER_COMPOSER

#: The descriptor profile. It names the ground a saved world states, the area the society walks,
#: and the structural snapshot both were read from.
GROUND_PROFILE: Final = "exulanica.authored-ground/v2"
FRAME_NAME: Final = "authored-ground-local-mm"

#: The built-in starter's ground, as the society ground catalog states it: the one ground this
#: module composes over. The names below are its figures, kept for their readers; each reason is
#: the catalog entry's.
STARTER_GROUND: Final = society_ground_for_composer(AUTHORED_STARTER_COMPOSER)
NAVIGATION_PROFILE: Final = STARTER_GROUND.navigation_profile
#: The spacing of the route lattice, in millimetres (``lattice_reason``).
LATTICE_MM: Final = STARTER_GROUND.lattice_mm
#: The half extent of the square a society declares on a ground that states no edge, centred on
#: the region origin (``declared_area_reason``). It is the society's own area, never the ground's.
#: An object placed outside it is still in the world and still drawn; the society records that
#: activity as unreachable rather than stretching its area to meet it.
DECLARED_HALF_EXTENT_MM: Final = STARTER_GROUND.declared_half_extent_mm
#: How many inhabitants a society on the starter's ground starts with (``population_reason``); a
#: district keeps ``SOCIETY_POPULATION``.
AUTHORED_GROUND_POPULATION: Final = STARTER_GROUND.population

AreaSource = Literal["ground", "declared"]
#: How a saved world's input names its area: this prefix and the authored region's identity.
_PLACE_PREFIX: Final = "authored:"


def ground_place_id(region_id: str) -> str:
    """The place identity a society on a saved world's ground publishes for ``region_id``."""
    return f"{_PLACE_PREFIX}{region_id}"


#: How a place's node is named: this prefix, the object's own identity and the place's index in
#: the order ``destination_places`` fills them, so a place keeps its identity when another drops.
PLACE_NODE_PREFIX: Final = "place:"
#: How a placed thing's places and obstacle are named: after a separator no authored object's id
#: can hold (``OBJECT_ID_PATTERN``), so an authored object named like a placed thing never shares
#: a node or an obstacle with it.
PLACED_THING_PREFIX: Final = "thing/"


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
    ``endless`` for a plane with no edge, ``unstated`` for a world that states no ground at all,
    such as one made from photographs, whose people walk the plane its objects are placed on, or
    ``surfaces`` for a world whose own records state the surfaces people walk, such as one
    generated from the city grammar. ``area`` is where the society walks. ``element_id`` is the
    ground's element, or None where the world has no ground element. ``navigation_form`` is what
    people walk, as the ground's catalog entry states it: a lattice over ``area``, or the world's
    walking surfaces inside it.
    """

    world_id: str
    snapshot_id: uuid.UUID
    snapshot_sha256: str
    region_id: str
    element_id: str | None
    module_key: str
    module_version: int
    ground_kind: Literal["flat", "endless", "unstated", "surfaces"]
    elevation_mm: int
    area: WalkableArea
    #: Where a person arrives in this world, on the ground plane, by the ground's arrival rule in
    #: the society ground catalog: the snapshot's own spawn, or the region origin.
    arrival_x_mm: int
    arrival_z_mm: int
    #: Every region the world states. An object in another of them is in another place of the
    #: world, which this society does not stand in; an object naming a region the world does not
    #: state makes the input unavailable. Left out, only this ground's own region is the world's.
    world_region_ids: tuple[str, ...] = ()
    #: The route lattice's spacing and the navigation profile it is published under, as this
    #: ground's own entry in the society ground catalog states them; each reader passes its entry's.
    lattice_mm: int = LATTICE_MM
    navigation_profile: str = NAVIGATION_PROFILE
    #: What people walk: ``lattice`` or ``walking_surfaces`` (the catalog's navigation forms).
    navigation_form: str = "lattice"

    @property
    def support_id(self) -> str:
        """What people stand on, as the lattice's nodes and edges name it: the ground element, or,
        where the world states none, the plane the society declares in its region."""
        return self.element_id if self.element_id is not None else f"plane:{self.region_id}"

    @property
    def place_id(self) -> str:
        """The spatial identity this ground publishes as the society input's area identity."""
        return ground_place_id(self.region_id)

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
            "lattice_mm": self.lattice_mm,
        }
        if self.navigation_form != "lattice":
            # Stated only where it is not a lattice, so every ground document written before
            # grounds had forms keeps the digest its stored inputs bind.
            document["navigation_form"] = self.navigation_form
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
        if self.navigation_form == "walking_surfaces":
            return {
                "name": WALKING_SURFACES_FRAME,
                "axis_order": ["east", "south"],
                "horizontal_unit": "millimetre",
                "altitude_reference": WALKING_SURFACES_ALTITUDE,
            }
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


def _axis(centre_mm: int, half_extent_mm: int, lattice_mm: int) -> list[int]:
    """Lattice coordinates on one axis, inside the area and a full clearance from its edge.

    Coordinates are multiples of the lattice spacing about the region origin, so two areas that
    overlap give the same node identities where they overlap.
    """
    low = centre_mm - (half_extent_mm - CLEARANCE_MM)
    high = centre_mm + (half_extent_mm - CLEARANCE_MM)
    if low > high:
        return []
    first = -(-low // lattice_mm)
    last = high // lattice_mm
    return [value * lattice_mm for value in range(first, last + 1)]


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
        return (ground.support_id,)

    return supports


def ground_navigation(ground: SocietyGround) -> dict[str, Any]:
    """The route lattice over the society's area, before any object prunes it.

    Destinations are empty on purpose. A saved world's ground declares a spawn point, not an
    activity, and calling a spawn point a visit would invent an affordance the world never
    declared. Every activity in an authored world comes from a reviewed object on it.
    """
    area = ground.area
    spacing = ground.lattice_mm
    xs = _axis(area.centre_x_mm, area.half_width_mm, spacing)
    zs = _axis(area.centre_z_mm, area.half_depth_mm, spacing)
    nodes = [
        {
            "node_id": _node_id(x_mm, z_mm),
            "subject_id": ground.support_id,
            "position_mm": [x_mm, z_mm],
        }
        for x_mm in xs
        for z_mm in zs
    ]
    edges = []
    for x_mm in xs:
        for z_mm in zs:
            for next_x, next_z in ((x_mm + spacing, z_mm), (x_mm, z_mm + spacing)):
                if next_x not in xs or next_z not in zs:
                    continue
                first, second = _node_id(x_mm, z_mm), _node_id(next_x, next_z)
                edges.append(
                    {
                        "edge_id": f"{first}|{second}",
                        "from_node_id": first,
                        "to_node_id": second,
                        "length_mm": spacing,
                        "subject_id": ground.support_id,
                    }
                )
    nodes.sort(key=lambda node: node["node_id"])
    edges.sort(key=lambda edge: edge["edge_id"])
    return {
        "profile": ground.navigation_profile,
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
class _PlacedUse:
    """A placed thing as the places it offers are composed: its id and its pose."""

    object_id: str
    transform: Transform


@dataclass(frozen=True, slots=True)
class _UsableObject:
    obj: AuthoredObject | _PlacedUse
    reviewed: Mapping[str, Any]
    centre: Point
    half_extents: tuple[int, int]
    #: ``authored`` for an object the person placed, ``thing`` for a thing placed by its kind.
    origin: str = "authored"


def _scaled(half_extents: Sequence[int], scale_milli: int) -> tuple[int, int]:
    """Reviewed half extents at an object's scale, rounded up to the whole millimetre."""
    hx, hz = half_extents
    return (-(-hx * scale_milli // 1000), -(-hz * scale_milli // 1000))


def _subject(version_id: uuid.UUID, object_id: str, origin: str) -> str:
    """How an input names what offers an activity: an authored object by its version and id, a
    placed thing by its id (``PROFILE_RECORD_SUBJECTS``)."""
    return f"authored:{version_id}:{object_id}" if origin == "authored" else f"thing:{object_id}"


def _refused_activity(
    version_id: uuid.UUID,
    obj: AuthoredObject | _PlacedUse,
    reviewed: Mapping[str, Any],
    reason: str,
    origin: str = "authored",
) -> dict[str, Any]:
    subject_id = _subject(version_id, obj.object_id, origin)
    return {
        "target_id": f"{subject_id}:{reviewed['affordance']}",
        "subject_id": subject_id,
        "object_id": obj.object_id,
        "version_id": str(version_id),
        "affordance": reviewed["affordance"],
        "reason": reason,
    }


def objects_in_region(version: AlternateVersion, ground: SocietyGround) -> list[AuthoredObject]:
    """The version's objects this society reads, in object order: every one but those in another
    region the world states.

    An object in another region of a world made from photographs is in another place of it: no
    obstacle, activity, record, dependency or asset of this society's input, and an edit to it
    changes nothing this society reads. An object naming a region the world does not state is kept,
    so the input names it as unavailable (``unregistered_object_region``).
    """
    return [
        obj
        for obj in sorted(version.objects, key=lambda value: value.object_id)
        if obj.region_id == ground.region_id or obj.region_id not in ground.world_region_ids
    ]


def _objects_one_by_one(
    version: AlternateVersion,
    reviewed_affordances: Mapping[str, dict[str, Any]],
    ground: SocietyGround,
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
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
    obstacle wherever it stands, and it has no activity to offer or to record as refused. A
    person's own admitted asset is such a kind: its preparation measured its footprint
    (``workspace_obstacles``), so it blocks walking where it stands, withdrawn or not, until it is
    removed.
    """
    usable: list[_UsableObject] = []
    obstacles: list[Obstacle] = []
    records: list[dict[str, Any]] = []
    for obj in objects_in_region(version, ground):
        if obj.removed:
            continue
        reviewed = object_affordance(obj, reviewed_affordances, workspace_obstacles)
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

    A starter's snapshot has one element, its ground. An override that keeps the ground exactly
    where the snapshot places it changes nothing the society reads. Anything else is the ground
    itself being hidden or moved, which is not an object, and the input names it. A world that
    states no ground element has only elements nobody collides with (its reader refuses any other),
    so hiding or moving one changes nothing the society reads either.
    """
    if ground.element_id is None:
        return None
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
    workspace_obstacles: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, list[Point]]:
    """Where people would stand to use each object of a version, by object id.

    Every object the society offers an activity at, decided as the society decides it
    (``_objects_one_by_one``), with its places as the society turns and scales them
    (``destination_places``), before it keeps only those clear, spaced and reachable. A version
    the society cannot compose at all has nobody standing anywhere.
    """
    usable, _, _, reason = _objects_one_by_one(
        version, reviewed_affordances, ground, workspace_obstacles
    )
    if reason is not None:
        return {}
    return {item.obj.object_id: destination_places(item, standing, CLEARANCE_MM) for item in usable}


def _squared(a: Sequence[int], b: Sequence[int]) -> int:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _fixed_duration(item: _UsableObject) -> dict[str, Any]:
    """What an input that records no routine states of an activity: its reviewed duration."""
    return {"duration_ticks": item.reviewed["duration_ticks"]}


def _place_targets(
    nav: dict[str, Any],
    usable: Sequence[_UsableObject],
    clear: Callable[..., bool],
    *,
    version_id: uuid.UUID,
    standing: StandingPolicy,
    terms: Callable[[_UsableObject], dict[str, Any]] = _fixed_duration,
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
    for item in sorted(usable, key=lambda value: (value.origin, value.obj.object_id)):
        obj, reviewed = item.obj, item.reviewed
        subject_id = _subject(version_id, obj.object_id, item.origin)
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
            # A placed thing's places are named apart from every authored object's.
            name = (
                obj.object_id
                if item.origin == "authored"
                else f"{PLACED_THING_PREFIX}{obj.object_id}"
            )
            chosen.append((f"{PLACE_NODE_PREFIX}{name}:{index}", point, joins[0][2]))
        if not chosen:
            records.append(_refused_activity(version_id, obj, reviewed, UNREACHABLE, item.origin))
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
                **terms(item),
                "origin": item.origin,
                "object_id": obj.object_id,
                "version_id": str(version_id),
                "enabled": True,
                "place_node_ids": [node_id for node_id, _, _ in chosen],
            }
        )
    return targets, records


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
) -> dict[str, Any]:
    """Compose a society of things' input, ``exulanica.society-composition/authored-ground-v5``.

    The fourth composition's projection, at the opening pose the version pins where the ground
    states no arrival of its own (``arrival``; None where it does, and the ground's own arrival
    stands), and the things the world's author placed in the region (``_things_one_by_one``): a
    placed object whose kind blocks walking is an obstacle, its box turned with it; one whose kind
    offers a rest or a visit offers it at the places its kind states, turned with it, unless it is
    off the ground; and every placed thing not removed is listed with its kind's semantics, where
    it stands and, for a gate, where visitors arrive. A thing whose kind is not shipped at the
    digest it names makes the input unavailable by name.
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
    )


#: The ability module the purposeful planner is: its abilities are the activities it plans.
PURPOSEFUL_MODULE: Final = "exulanica-ability/purposeful/v1"


def thing_activities() -> tuple[tuple[str, str], ...]:
    """The activity a placed thing offers people, by the offer of its kind that states it, as the
    abilities catalog says: each ability the purposeful planner serves whose target offer states
    places, as (offer, activity), in the catalog's order. A thing offers one at most, the first its
    kind offers, since a place belongs to one activity."""
    catalogs = thing_catalogs()
    return tuple(
        (ability.target_offer, ability.key)
        for ability in catalogs.abilities.values()
        if ability.module == PURPOSEFUL_MODULE
        and ability.target_offer is not None
        and any(p.name == "places" for p in catalogs.offers[ability.target_offer].parameters)
    )


def things_in_region(version: AlternateVersion, ground: SocietyGround) -> list[PlacedThing]:
    """The version's placed things this society reads, in id order: each placed in its region,
    removed ones included, as its input's references bind them."""
    return sorted(
        (thing for thing in version.things if thing.region_id == ground.region_id),
        key=lambda value: value.thing_id,
    )


def _thing_kinds(things: Sequence[PlacedThing]) -> tuple[dict[str, ThingKind], str | None]:
    """The shipped kind of each placed thing not removed, by its id, or the reason the input is
    unavailable: a thing whose kind is not shipped at the digest it names."""
    kinds: dict[str, ThingKind] = {}
    for thing in things:
        if thing.removed:
            continue
        try:
            kinds[thing.thing_id] = shipped_kind(thing.kind)
        except InvalidThingPlacement:
            return {}, f"unknown_thing_kind:{thing.thing_id}"
    return kinds, None


def _things_one_by_one(
    things: Sequence[PlacedThing],
    kinds: Mapping[str, ThingKind],
    ground: SocietyGround,
    version_id: uuid.UUID,
) -> tuple[list[_UsableObject], list[Obstacle], list[dict[str, Any]]]:
    """Every placed object's obstacle and activity, decided for that thing alone.

    A placed being is no obstacle and offers no activity here: it lives in the society. A placed
    object stands at its kind's own size: its box is its footprint, in its slot frame, whose front
    (``+y``) is the region's ``-z``, as an authored object's catalog places are, turned by its yaw.
    It blocks walking where its kind says. Its places to rest or visit at are its kind's, turned
    with it, joined to the lattice within the reviewed reach; one that does not rest on the ground
    plane offers none (``OFF_GROUND``) and still blocks.
    """
    usable: list[_UsableObject] = []
    obstacles: list[Obstacle] = []
    records: list[dict[str, Any]] = []
    for thing in things:
        if thing.removed:
            continue
        semantics = kinds[thing.thing_id].semantics()
        if semantics["class"] != "object":
            continue
        body = semantics["body"]
        box = body["box_mm"]
        transform = thing.transform
        centre = (transform.x_mm, transform.z_mm)
        half = (-(-box["width"] // 2), -(-box["depth"] // 2))
        if body["blocks_walking"]:
            obstacles.append(
                (
                    f"{PLACED_THING_PREFIX}{thing.thing_id}",
                    footprint_ring(centre, half, transform.yaw_microradians),
                )
            )
        offers = {offer["key"]: offer["parameters"] for offer in semantics["offers"]}
        found = next(
            ((offer, affordance) for offer, affordance in thing_activities() if offer in offers),
            None,
        )
        if found is None:
            continue
        offer, affordance = found
        reviewed = {
            "affordance": affordance,
            "duration_ticks": DURATIONS[affordance],
            "footprint_half_extents_mm": list(half),
            "blocks_navigation": body["blocks_walking"],
            "reach_mm": REVIEWED_REACH_MM,
            PLACES_FIELD: [[place["x_mm"], -place["y_mm"]] for place in offers[offer]["places"]],
            "thing_kind": semantics["kind"],
        }
        item = _UsableObject(
            _PlacedUse(thing.thing_id, transform), reviewed, centre, half, origin="thing"
        )
        if transform.y_mm != ground.elevation_mm:
            records.append(_refused_activity(version_id, item.obj, reviewed, OFF_GROUND, "thing"))
        else:
            usable.append(item)
    return usable, obstacles, records


def _arrival_point(semantics: Mapping[str, Any], thing: PlacedThing) -> list[int] | None:
    """Where visitors step out of a gate, in the region's frame: its kind's arrival point turned
    with it, or None for a thing that is no gate."""
    for offer in semantics["offers"]:
        if offer["key"] == "arrive_through":
            point = offer["parameters"]["point"]
            centre = (thing.transform.x_mm, thing.transform.z_mm)
            turned = turned_point(
                centre, (point["x_mm"], -point["y_mm"]), thing.transform.yaw_microradians
            )
            return [turned[0], turned[1]]
    return None


def _input_things(
    things: Sequence[PlacedThing], kinds: Mapping[str, ThingKind], ground: SocietyGround
) -> list[dict[str, Any]]:
    """The things list a v5 input states (:mod:`exulanica.world.society_thing_inputs`): a thing
    off the ground states its height above the ground's elevation."""
    entries = []
    for thing in things:
        if thing.removed:
            continue
        semantics = kinds[thing.thing_id].semantics()
        entry = {
            "placed_id": thing.thing_id,
            "kind": semantics,
            "position_mm": [thing.transform.x_mm, thing.transform.z_mm],
            "yaw_microradians": thing.transform.yaw_microradians,
            "arrival_mm": _arrival_point(semantics, thing),
        }
        if thing.transform.y_mm != ground.elevation_mm:
            entry["height_mm"] = thing.transform.y_mm - ground.elevation_mm
        entries.append(entry)
    return entries


def thing_dependency_refs(
    version_id: uuid.UUID, things: Sequence[PlacedThing], kinds: Mapping[str, ThingKind]
) -> list[dict[str, str]]:
    """Bind every placed thing in the region, removed ones included, and the kind of each one that
    is not removed, by its digest."""
    refs: list[dict[str, str]] = []
    for thing in things:
        kind = kinds.get(thing.thing_id)
        if kind is not None:
            refs.append(
                {
                    "kind": "thing_kind",
                    "identity": f"{kind.kind}.v{kind.version}",
                    "sha256": kind.sha256,
                }
            )
        refs.append(
            {
                "kind": "placed_thing",
                "identity": f"{version_id}:{thing.thing_id}",
                "sha256": society_state_sha256(placed_thing_document(thing)),
            }
        )
    return refs


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
        if input_seq == 1:
            # A society's first input records the ability modules it runs, by version, and its
            # minute runs exactly those for its whole life, whatever a later table adds.
            from exulanica.abilities.registry import current_modules

            document["modules"] = list(current_modules())
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
) -> dict[str, Any]:
    """The projection the second and later compositions share, with its digest, unvalidated:
    with ``things``, the things composition's placed things too."""
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
    placed = things_in_region(version, ground) if things else []
    thing_kinds, thing_refusal = _thing_kinds(placed)
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
    document["document_sha256"] = input_sha256(document)
    return document


def read_authored_ground(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    world_id: str,
    snapshot_id: uuid.UUID,
    *,
    region_id: str | None = None,
) -> SocietyGround | None:
    """The society's reading of one world's structural snapshot, the one place it is read.

    None when the workspace holds no such snapshot for the world. A snapshot the society has no
    rule for raises ``InvalidStructuralData`` with the reason
    (:func:`authored_ground_from_snapshot`). The runtime refuses on either; an arrangement treats
    either as a world with no ground to stand on. Both read the same row by the same rule, so they
    cannot disagree about a world's ground.
    """
    with connection.cursor(row_factory=dict_row) as cursor:
        row = cursor.execute(
            "select composer_key,composer_version,topology,placement,snapshot_sha256 "
            "from world_structure_snapshot where workspace_id=%s and world_id=%s "
            "and snapshot_id=%s",
            (workspace_id, world_id, snapshot_id),
        ).fetchone()
    if row is None:
        return None
    return authored_ground_from_snapshot(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=row["snapshot_sha256"],
        composer_key=row["composer_key"],
        composer_version=row["composer_version"],
        topology=row["topology"],
        placement=row["placement"],
        region_id=region_id,
    )


def authored_input_region(document: Mapping[str, Any]) -> str:
    """The region a saved world's input was composed in, from the place identity it publishes
    (:attr:`SocietyGround.place_id`), or a refusal naming what it holds instead."""
    place = document.get("district_id")
    if not isinstance(place, str) or not place.startswith(_PLACE_PREFIX):
        raise InvalidStructuralData(f"a saved world's input names no authored region: {place!r}")
    return place[len(_PLACE_PREFIX) :]


def authored_ground_from_snapshot(
    *,
    world_id: str,
    snapshot_id: uuid.UUID,
    snapshot_sha256: str,
    composer_key: str,
    composer_version: int,
    topology: Mapping[str, Any],
    placement: Mapping[str, Any],
    region_id: str | None = None,
) -> SocietyGround:
    """Read a saved world's ground out of its own structural snapshot, and say where to walk.

    The snapshot's composer names its ground in the society ground catalog
    (:func:`~exulanica.world.society_grounds.society_ground_for_composer`), and the reader for
    that ground's navigation and floor forms reads it: a lattice on a ground the world states
    (the built-in starter's, :func:`_starter_ground`), a lattice on a floor the society declares
    (a world made from photographs, :func:`_made_world_ground`) or the walking surfaces a world's
    own records state (a generated world, :func:`_walking_surfaces_ground`). ``region_id`` is the
    region the society stands in, which a world of several regions needs named. A composer the
    catalog does not state, or forms with no reader, are refused with ``InvalidStructuralData``,
    never read by guessing.
    """
    try:
        kind = society_ground_for_composer(composer_key)
    except UnknownSocietyGround as exc:
        raise InvalidStructuralData(str(exc)) from exc
    reader = _GROUND_READERS.get((kind.navigation, kind.floor))
    if reader is None:
        raise InvalidStructuralData(
            f"no reader is implemented for a ground that walks a {kind.navigation} on a "
            f"{kind.floor} floor (society ground {kind.key!r})"
        )
    return reader(
        kind,
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
        composer_key=composer_key,
        composer_version=composer_version,
        topology=topology,
        placement=placement,
        region_id=region_id,
    )


def _starter_ground(
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
    """The built-in starter's ground, through the starter authority.

    The authority refuses any snapshot that is not exactly the built-in authored starter at a
    supported ground module version. A bounded ground gives the society the extent it states. An
    endless ground states none, so the society declares the catalog's area and marks it declared.
    A ground of any other kind is refused, never read by guessing which attributes it might have.
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
    if region_id is not None and region_id != region.region_id:
        raise InvalidStructuralData(
            f"{region_id!r} is not this world's authored region: the starter has one"
        )
    if (kind.arrival, kind.floor) != ("spawn", "stated"):
        raise InvalidStructuralData(
            f"the starter arrives at its spawn on the ground it states, not {kind.arrival} on a "
            f"{kind.floor} one"
        )
    stated = region.ground
    if isinstance(stated, BoundedAuthoredGround):
        ground_kind: Literal["flat", "endless", "unstated", "surfaces"] = "flat"
        area = WalkableArea("ground", 0, 0, stated.half_width_mm, stated.half_depth_mm)
    elif isinstance(stated, EndlessAuthoredGround):
        ground_kind = "endless"
        extent = kind.declared_half_extent_mm
        area = WalkableArea("declared", 0, 0, extent, extent)
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
        ground_kind=ground_kind,
        elevation_mm=stated.elevation_mm,
        area=area,
        arrival_x_mm=region.spawn.x_mm,
        arrival_z_mm=region.spawn.z_mm,
        world_region_ids=(region.region_id,),
        lattice_mm=kind.lattice_mm,
        navigation_profile=kind.navigation_profile,
    )


#: The versions of the made-world composer a society reads: the one
#: :func:`exulanica.world.composed.composed_candidate` writes (``SpatialCandidate``'s default).
MADE_WORLD_COMPOSER_VERSIONS: Final = (1,)
#: The height of a declared floor in its region's frame, in millimetres: the region origin's own
#: height, where a region's objects are placed and its people walk. A world whose ground's
#: catalog entry says its floor is declared states none, so this is declared, as its area is.
DECLARED_FLOOR_ELEVATION_MM: Final = 0


@dataclass(frozen=True, slots=True)
class DeclaredFloor:
    """The floor every region of a world that states no ground has: a square of this half extent
    about the region origin, at this height in the region's frame. The app draws it, places
    objects on it, and the society walks it."""

    half_extent_mm: int
    elevation_mm: int


def declared_floor(composer_key: str) -> DeclaredFloor | None:
    """The floor the society ground catalog declares in every region of a world made by this
    composer, or None where the world states its own ground or the catalog states no ground."""
    try:
        kind = society_ground_for_composer(composer_key)
    except UnknownSocietyGround:
        return None
    if kind.floor != "declared":
        return None
    return DeclaredFloor(kind.declared_half_extent_mm, DECLARED_FLOOR_ELEVATION_MM)


def _made_world_ground(
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
    """One region of a world made from photographs, as the ground its society stands on.

    Such a world states no ground, no spawn and no position for its regions: each photograph is
    an element drawn with no collision. So the society stands in one region, the one it names, on
    the plane its objects are placed on, walks the area its catalog entry declares about the
    region origin, and a person arrives at that origin, by the entry's rule. A region the world
    does not state, a world that names no region for its society, and an element anybody would
    collide with are refused by name.
    """
    if composer_version not in MADE_WORLD_COMPOSER_VERSIONS:
        raise InvalidStructuralData(
            f"a made world's composer version {composer_version} is not read"
        )
    regions = tuple(
        str(region["region_id"]) for region in topology.get("regions", ()) if "region_id" in region
    )
    if region_id is None:
        raise InvalidStructuralData("a made world's society names the region it stands in")
    if region_id not in regions:
        raise InvalidStructuralData(f"the made world states no region {region_id!r}")
    colliding = [
        str(element.get("element_id"))
        for element in topology.get("elements", ())
        if (element.get("collision") or {}).get("kind") != "none"
    ]
    if colliding:
        raise InvalidStructuralData(
            f"a made world's society has no rule for an element that collides: {colliding[0]}"
        )
    if (kind.arrival, kind.floor) != ("region_origin", "declared"):
        raise InvalidStructuralData(
            f"a made world arrives at its region origin on a declared floor, not {kind.arrival} "
            f"on a {kind.floor} one"
        )
    extent = kind.declared_half_extent_mm
    return SocietyGround(
        world_id=world_id,
        snapshot_id=snapshot_id,
        snapshot_sha256=snapshot_sha256,
        region_id=region_id,
        element_id=None,
        module_key=composer_key,
        module_version=composer_version,
        ground_kind="unstated",
        elevation_mm=DECLARED_FLOOR_ELEVATION_MM,
        area=WalkableArea("declared", 0, 0, extent, extent),
        arrival_x_mm=0,
        arrival_z_mm=0,
        world_region_ids=regions,
        lattice_mm=kind.lattice_mm,
        navigation_profile=kind.navigation_profile,
    )


def _walking_surfaces_ground(kind: SocietyGroundKind, **snapshot: Any) -> SocietyGround:
    """A world whose own records state its walking surfaces (:mod:`society_walking_surfaces`)."""
    from exulanica.world.society_walking_surfaces import walking_surfaces_ground

    return walking_surfaces_ground(kind, **snapshot)


#: The reader for each pair of forms a ground's catalog entry states, what people walk and what
#: they stand on, never the entry's name: another ground of the same forms needs only an entry.
#: Forms with no reader are refused by name.
_GROUND_READERS: Final[Mapping[tuple[str, str], Callable[..., SocietyGround]]] = {
    ("lattice", "stated"): _starter_ground,
    ("lattice", "declared"): _made_world_ground,
    ("walking_surfaces", "stated"): _walking_surfaces_ground,
}
