"""What a society over a saved world's ground may use: the objects placed on it and its things.

Each reviewed object in the authored region becomes the places its use offers (a seat, a stand, a
bed, a path swept by a behaviour) with how a person stands there (:class:`StandingPolicy`), or a
refusal by name where the society cannot use it; each placed thing becomes the activities its kind
offers, held to where it stands above the plane, and a made kind's run form is stated once.
:mod:`exulanica.world.society_authored_ground` composes these into the society's input.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

from exulanica.things.catalogs import thing_catalogs
from exulanica.things.kinds import ThingKind
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.objects import AuthoredObject, ElementOverride, Transform
from exulanica.world.placed_things import (
    PlacedThing,
    WorkspaceKindReference,
    placed_thing_document,
    shipped_kind,
)
from exulanica.world.society import society_state_sha256
from exulanica.world.society_authored_ground_area import SocietyGround
from exulanica.world.society_composition import (
    PLACES_FIELD,
    REVIEWED_REACH_MM,
    Obstacle,
    Point,
    footprint_ring,
    object_affordance,
    offers_activity,
    turned_point,
)
from exulanica.world.society_input_policy import (
    MOVES,
    OFF_GROUND,
    UNREACHABLE,
    UNSUPPORTED_BEHAVIOUR,
)
from exulanica.world.society_kinds import (
    KINDS_FIELD,
    THINGS_GONE_FIELD,
    MadeKind,
    made_reference,
)
from exulanica.world.society_place import ceil_distance
from exulanica.world.society_planner import CLEARANCE_MM, DURATIONS

#: How a place's node is named: this prefix, the object's own identity and the place's index in
#: the order ``destination_places`` fills them, so a place keeps its identity when another drops.


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


def things_in_region(
    version: AlternateVersion,
    ground: SocietyGround,
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[PlacedThing]:
    """The version's placed things this society reads, in id order: each placed in its region,
    removed ones included, as its input's references bind them.

    A thing of a kind its workspace keeps (a creature drafted from a person's words) is read only
    where ``made_kinds`` states that kind's run form (:mod:`exulanica.things.run_forms`), which
    is all a society runs of it, and its workspace still holds the kind. One whose kind is gone
    (erased, or erased after the thing was placed), or whose run form nobody stated, is left out,
    by name, whatever its region: it is never one of the society's and never stops a society that
    runs beside it."""
    return sorted(
        (
            thing
            for thing in version.things
            if thing.region_id == ground.region_id and _read_by_a_society(thing, made_kinds)
        ),
        key=lambda value: value.thing_id,
    )


def _of_a_workspace_kind(thing: PlacedThing) -> bool:
    """Whether ``thing`` names a kind its workspace keeps rather than a shipped kind."""
    return isinstance(thing.kind, WorkspaceKindReference)


def _read_by_a_society(
    thing: PlacedThing, made_kinds: Mapping[str, Mapping[str, Any]] | None
) -> bool:
    if not _of_a_workspace_kind(thing):
        return True
    return made_kinds is not None and not thing.kind_gone and thing.kind.sha256 in made_kinds


def made_things_gone(
    version: AlternateVersion,
    ground: SocietyGround,
    made_kinds: Mapping[str, Mapping[str, Any]] | None,
) -> list[str]:
    """The placed ids of the things placed in the region and not removed whose kind, one their
    workspace kept, is gone (erased, or erased after the thing was placed), in order: what an
    input states as ``things_gone``, so a being that was one of them leaves because its kind was
    erased. A thing whose kind the workspace still holds but whose run form nobody stated (its
    plan or recipe no longer reads) is left out of the input and is not listed: its kind was not
    erased. None where nobody stated the workspace's kinds."""
    if made_kinds is None:
        return []
    return sorted(
        {
            thing.thing_id
            for thing in version.things
            if thing.region_id == ground.region_id
            and _of_a_workspace_kind(thing)
            and not thing.removed
            and thing.kind_gone
        }
    )


def _thing_kinds(
    things: Sequence[PlacedThing],
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, ThingKind | MadeKind], str | None]:
    """The kind of each placed thing not removed, by its id: a shipped kind, or a made kind as
    its run form states it; or the reason the input is unavailable: a thing whose kind is not
    shipped at the digest it names."""
    kinds: dict[str, ThingKind | MadeKind] = {}
    for thing in things:
        if thing.removed:
            continue
        if _of_a_workspace_kind(thing):
            assert made_kinds is not None
            kinds[thing.thing_id] = MadeKind(made_kinds[thing.kind.sha256], thing.kind.sha256)
            continue
        try:
            kinds[thing.thing_id] = shipped_kind(thing.kind)
        except InvalidThingPlacement:
            return {}, f"unknown_thing_kind:{thing.thing_id}"
    return kinds, None


def _semantics(kind: ThingKind | MadeKind) -> Mapping[str, Any]:
    """What a society reads of a kind: a shipped kind's semantics, a made kind's run form."""
    return kind.document if isinstance(kind, MadeKind) else kind.semantics()


def state_made_kinds(
    document: dict[str, Any],
    kinds: Mapping[str, ThingKind | MadeKind],
    gone: Sequence[str],
) -> None:
    """An available things input states the run form of each made kind a thing it lists is of,
    once, in digest order (``kinds``), and the placed things it leaves out because their kind is
    gone (``things_gone``): each only where there is one, so an input with no made thing keeps the
    bytes it always had."""
    made = {
        kind.sha256: dict(kind.document) for kind in kinds.values() if isinstance(kind, MadeKind)
    }
    if made:
        document[KINDS_FIELD] = dict(sorted(made.items()))
    if gone:
        document[THINGS_GONE_FIELD] = list(gone)


def _height_above_plane(ground: SocietyGround) -> Callable[[PlacedThing], int | None]:
    """How high a thing stands above a ground plane, or None for one resting on it."""

    def height(thing: PlacedThing) -> int | None:
        above = thing.transform.y_mm - ground.elevation_mm
        return None if above == 0 else above

    return height


def _things_one_by_one(
    things: Sequence[PlacedThing],
    kinds: Mapping[str, ThingKind | MadeKind],
    ground: SocietyGround,
    version_id: uuid.UUID,
    height_above: Callable[[PlacedThing], int | None] | None = None,
    omitted_support_ids: frozenset[str] = frozenset(),
) -> tuple[list[_UsableObject], list[Obstacle], list[dict[str, Any]]]:
    """Every placed object's obstacle and activity, decided for that thing alone.

    A placed being is no obstacle and offers no activity here: it lives in the society. A placed
    object stands at its kind's own size: its box is its footprint, in its slot frame, whose front
    (``+y``) is the region's ``-z``, as an authored object's catalog places are, turned by its yaw.
    It blocks walking where its kind says. Its places to rest or visit at are its kind's, turned
    with it, joined to the lattice within the reviewed reach; one that does not rest on the ground
    plane offers none (``OFF_GROUND``) and still blocks. ``height_above`` says how high a thing
    stands above the surface under it, or None where it rests on it; left out, the ground plane.
    """
    height = _height_above_plane(ground) if height_above is None else height_above
    usable: list[_UsableObject] = []
    obstacles: list[Obstacle] = []
    records: list[dict[str, Any]] = []
    for thing in things:
        if thing.removed or thing.thing_id in omitted_support_ids:
            continue
        semantics = _semantics(kinds[thing.thing_id])
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
        if height(thing) is not None:
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
    things: Sequence[PlacedThing],
    kinds: Mapping[str, ThingKind | MadeKind],
    ground: SocietyGround,
    height_above: Callable[[PlacedThing], int | None] | None = None,
    omitted_support_ids: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """The things list a v5 input states (:mod:`exulanica.world.society_thing_inputs`): a thing
    off the ground states its height above the ground's elevation, or above the surface under it
    where ``height_above`` says how high that is."""
    height = _height_above_plane(ground) if height_above is None else height_above
    entries = []
    for thing in things:
        if thing.removed or thing.thing_id in omitted_support_ids:
            continue
        kind = kinds[thing.thing_id]
        semantics = _semantics(kind)
        entry = {
            "placed_id": thing.thing_id,
            # A made kind's entry names it by digest alone; its run form is stated once.
            "kind": made_reference(kind.sha256) if isinstance(kind, MadeKind) else semantics,
            "position_mm": [thing.transform.x_mm, thing.transform.z_mm],
            "yaw_microradians": thing.transform.yaw_microradians,
            "arrival_mm": _arrival_point(semantics, thing),
        }
        above = height(thing)
        if above is not None:
            entry["height_mm"] = above
        entries.append(entry)
    return entries


def supported_things_projection(
    version: AlternateVersion,
    ground: SocietyGround,
    kinds: Mapping[str, Any],
    source: Any,
) -> tuple[frozenset[str], list[dict[str, Any]], str | None]:
    """A closed input may omit only freshly proven disjoint objects with a real activity record.

    The source and all current occupancy are checked on each projection. An absent/unknown or
    overlapping source is unavailable, never a lost obstacle disguised as an available input.
    """
    from exulanica.world.placed_things import ThingPlacement
    from exulanica.world.support_placement import (
        PlacementContext,
        SupportPlacementRefused,
        validate_supported_placement,
    )
    from exulanica.world.support_placement_source import SupportPlacementSource, occupancy

    bound = [
        t
        for t in version.things
        if t.support is not None and not t.removed and t.region_id == ground.region_id
    ]
    if not bound:
        return frozenset(), [], None
    if (
        not isinstance(source, SupportPlacementSource)
        or source.world_id != version.world_id
        or source.source_snapshot_id != version.source_snapshot_id
        or source.region_id != ground.region_id
    ):
        return frozenset(), [], "supported_thing_source_unavailable"
    omitted, records = set(), []
    for thing in bound:
        assert thing.support is not None
        kind = kinds.get(thing.thing_id)
        if not isinstance(kind, ThingKind):
            return frozenset(), [], "supported_thing_kind_unavailable"
        solids, unknown = occupancy(version, source, kinds, exclude_thing_id=thing.thing_id)
        context = PlacementContext(
            version.world_id,
            version.version_id,
            version.source_snapshot_id,
            source.receipt_sha256,
            version.state_sha256,
            source.region_id,
            source.network,
            solids,
            unknown,
            source.actor_volumes,
        )
        try:
            validate_supported_placement(
                ThingPlacement(
                    thing.thing_id, thing.kind, thing.region_id, thing.transform, thing.origin
                ),
                kind,
                thing.support.document(),
                context=context,
            )
        except SupportPlacementRefused:
            return frozenset(), [], "supported_thing_clearance_unavailable"
        offered = {offer["key"] for offer in kind.document["offers"]}
        found = next(
            ((key, activity) for key, activity in thing_activities() if key in offered), None
        )
        if found is None or _height_above_plane(ground)(thing) is None:
            # The closed input has no truthful generic unsupported-thing record. Do not invent
            # a rest/visit offer or label a ground-supported thing as off the ground plane.
            return frozenset(), [], "supported_thing_projection_unavailable"
        _, activity = found
        item = _PlacedUse(thing.thing_id, thing.transform)
        records.append(
            _refused_activity(
                version.version_id, item, {"affordance": activity}, OFF_GROUND, "thing"
            )
        )
        omitted.add(thing.thing_id)
    return frozenset(omitted), records, None


def thing_dependency_refs(
    version_id: uuid.UUID,
    things: Sequence[PlacedThing],
    kinds: Mapping[str, ThingKind | MadeKind],
) -> list[dict[str, str]]:
    """Bind every placed thing in the region, removed ones included, and the kind of each one that
    is not removed, by its digest: a made kind as ``made_thing_kind``, named by that digest alone,
    never by a key a person's words made."""
    refs: list[dict[str, str]] = []
    for thing in things:
        kind = kinds.get(thing.thing_id)
        if isinstance(kind, MadeKind):
            refs.append({"kind": "made_thing_kind", "identity": kind.sha256, "sha256": kind.sha256})
        elif kind is not None:
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
