"""The ground a society over a saved world walks on, read from the world.

A saved world's authored ground, a starter's, a made world's declared floor or a town's walking
surfaces give a :class:`SocietyGround`: the area inhabitants may walk (:class:`WalkableArea`, the
world's own extent or one the society declares where the ground states none), the lattice over it,
and the navigation and supports the society's input carries. The lattice spacing, the declared area
and the starting population are the ground's entry in the society ground catalog
(:mod:`exulanica.world.society_grounds`). :mod:`exulanica.world.society_authored_ground` builds the
society's input over this ground.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row

from exulanica.world.errors import InvalidStructuralData
from exulanica.world.objects import Transform
from exulanica.world.society import society_state_sha256
from exulanica.world.society_composition import Point, Supports
from exulanica.world.society_grounds import (
    SocietyGroundKind,
    UnknownSocietyGround,
    society_ground_for_composer,
)
from exulanica.world.society_planner import (
    CLEARANCE_MM,
    WALKING_SURFACES_ALTITUDE,
    WALKING_SURFACES_FRAME,
)
from exulanica.world.starter import AUTHORED_STARTER_COMPOSER

#: The descriptor profile. It names the ground a saved world states, the area the society walks,
#: and the structural snapshot both were read from.


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
