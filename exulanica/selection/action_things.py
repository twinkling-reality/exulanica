"""The Companion's things: a thing added by its kind, and one of a world's beings asked to act.

Two typed steps join a world-edit plan (:mod:`exulanica.selection.action_plan`). Each is the exact
request a direct client sends to a route that already exists, so it meets that route's permission,
validation, transaction and refusal:

*   ``place_thing`` is ``POST /world/versions/{version_id}/things`` (``add_thing``): a shipped kind
    an author may place, by key, version and digest; an id minted when the plan is made; a pose
    laid out here (:func:`lay_out`) beside what the person named, or at the spot the page points
    at; and the origin role the person stated. The route has no preview, so its own pure checks run
    here before the step is offered (:func:`placement_refusal`), and the route stays the authority
    when the step is sent.
*   ``direct_thing`` is ``POST /world/versions/{version_id}/society/actions`` (``record_action``):
    one of the world's own beings asked to walk to a place its society lists, or to use it. The
    request is built by the function the route builds it with
    (:func:`~exulanica.world.society_actions.build_action_request`), on the society's state and the
    input a request would be made against now, so a step is offered only where the route would
    take it. Its pins are that minute's, so a client prepares it again just before sending it;
    while the society holds an input it has not taken in, the being is in the middle of something,
    or it was already asked something at this minute, preparing says so by code
    (:data:`WAIT_CODES`) and the client waits for the next minute.

What the drafter is shown about these comes from reads, by opaque label: the kinds of thing an
author may place (by kind key), the version's placed objects (``thing-N``), the society's beings
(``being-N``) and the places its consumed input lists (``place-N``). A being is described by its
display name, kind and the look it wears; a being from outside is shown by kind and number only,
so nothing an outside program declared reaches a hosted request. Positions are never the model's.

A kind whose first look draws a reviewed world object's own container (a bench, a cafe table) is
not offered here: "add a bench" stays the reviewed object's placement, the measured path, until
that placement moves onto kinds.

Pure but for :func:`read_things`' arguments: no connection and no SQL.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cache
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.things.kinds import ThingKind, shipped_thing_kinds
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.object_catalog import world_object_catalog
from exulanica.world.objects import MAX_YAW_MICRORADIANS, ObjectOrigin, Transform
from exulanica.world.placed_things import (
    PLACED_THINGS_MAXIMUM,
    UNSCALED_MILLI,
    PlacedThing,
    ThingKindReference,
    placeable_by_author,
    shipped_kind,
    validate_placed_thing,
)
from exulanica.world.society_actions import ActionIntent, build_action_request
from exulanica.world.society_things import THING_NAMESPACE
from exulanica.world.thing_library import shipped_looks

__all__ = [
    "BEING_HALF_MM",
    "DIRECT",
    "DIRECT_ACTS",
    "MAX_THING_CHOICES",
    "THING_PLACE",
    "WAIT_CODES",
    "BeingRead",
    "Footprint",
    "KindChoice",
    "PlaceRead",
    "PlacedRead",
    "SocietyRead",
    "ThingsRead",
    "direct_body",
    "facing_yaw",
    "lay_out",
    "minted_thing_id",
    "offered_kinds",
    "placement_refusal",
    "read_things",
    "society_thing_id",
]

_VERSION: Final = "/world/versions/{version_id}"
#: The two routes a things step is sent to.
THING_PLACE: Final = f"POST {_VERSION}/things"
DIRECT: Final = f"POST {_VERSION}/society/actions"

#: What a direct step asks of a being, and the intent the route takes for it: walk to a place, or
#: use it (``perform`` its activity there).
DIRECT_ACTS: Final = {"go_to": "go_to", "use": "perform"}
#: The codes that say a direct step is waiting for the society's next minute, not refused: an input
#: it has not taken in yet (after a thing was placed), or a being in the middle of something or
#: already asked something at this minute (a later step asking the same being).
WAIT_CODES: Final = frozenset({"society_input_queued", "inhabitant_action_in_progress"})

#: How many beings, placed things and places the drafter is shown, the nearest to the person first,
#: as many as it is shown of the version's objects.
MAX_THING_CHOICES: Final = 24
#: The half-size a being takes on the ground, for laying out what is placed beside it.
BEING_HALF_MM: Final = 300
#: The gap kept between what is placed and what stands there already.
CLEARANCE_MM: Final = 300
#: The room kept free about where the person stands.
PERSON_ROOM_MM: Final = 1_000
#: The rings about the pointed spot that a thing takes when the spot itself is taken, near first.
RINGS_MM: Final = (2_500, 5_000)
#: Turns from the line the person looks along, in microradians: ahead, to either side, then behind.
RING_TURNS: Final = (0, 1_047_198, -1_047_198, 2_094_395, -2_094_395, 3_141_593)
#: The sides of what a thing is placed beside: toward the person first, then right, left, behind.
SIDE_TURNS: Final = (0, 1_570_796, -1_570_796, 3_141_593)
#: The namespace a direct step's idempotency key is made in, from what the request asks and the
#: minute it is made in: the same request at the same minute is one request, a later minute a new
#: one.
_DIRECT_KEYS: Final = uuid.uuid5(uuid.NAMESPACE_URL, "exulanica.companion-direct-request/v1")


# -- the reads ------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class KindChoice:
    """A kind of thing an author may place, at its newest shipped version."""

    key: str
    version: int
    sha256: str
    label: str
    summary: str
    being: bool
    #: Half its width and depth on the ground: its box for an object, a being's for a being.
    half_mm: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Footprint:
    """Where something stands on the ground, region-local, and half its size there."""

    x_mm: int
    z_mm: int
    half_mm: tuple[int, int]

    @property
    def radius_mm(self) -> int:
        """The circle it stands in, rounded up."""
        half_x, half_z = self.half_mm
        return math.isqrt(half_x * half_x + half_z * half_z) + 1


@dataclass(frozen=True, slots=True)
class PlacedRead:
    """An object the author placed in the version by its kind, as the drafter may name it."""

    thing_id: str
    label: str
    look_label: str | None
    region_id: str
    transform: Transform
    footprint: Footprint


@dataclass(frozen=True, slots=True)
class BeingRead:
    """One of the society's beings, as the drafter may name it."""

    id: str
    display_name: str
    kind_label: str | None
    look_label: str | None
    came_by: str | None
    footprint: Footprint

    @property
    def from_outside(self) -> bool:
        return self.came_by == "crossed"


@dataclass(frozen=True, slots=True)
class PlaceRead:
    """A place the society's consumed input lists, which a being may be asked to go to or use."""

    target_id: str
    title: str
    affordance: str


@dataclass(frozen=True, slots=True)
class SocietyRead:
    """The society a direct request would be made against now, and what the drafter is shown of
    it. ``state`` and ``document`` are the state and the input its state consumed, as the actions
    route reads them; ``newest_input_seq`` is the newest input's sequence."""

    society_id: str
    engine: str
    region_id: str
    tick: int
    state_sha256: str
    state: Mapping[str, Any]
    document: Mapping[str, Any]
    newest_input_seq: int
    beings: tuple[BeingRead, ...]
    places: tuple[PlaceRead, ...]
    #: The beings a request was already made for at this minute: the route takes one per being
    #: per minute, so another waits for the minute that takes the first.
    asked: frozenset[str] = frozenset()

    @property
    def input_queued(self) -> bool:
        """Whether an input waits that the society's state has not taken in yet."""
        return int(self.state["input_seq"]) != self.newest_input_seq


@dataclass(frozen=True, slots=True)
class ThingsRead:
    """What a plan of things rests on: the kinds, the placed objects, the society, the ground."""

    kinds: tuple[KindChoice, ...]
    placed: tuple[PlacedRead, ...]
    society: SocietyRead | None
    #: The ground's elevation where things stand, where the version's ground states one.
    elevation_mm: int | None
    #: Every placed thing's footprint in the version, beings and objects, for laying out.
    taken: tuple[tuple[str, Footprint], ...]
    #: How many placed things the version holds, removed ones included, as the route counts them.
    placed_count: int
    #: The ids the version's placed things use, removed ones included.
    placed_ids: frozenset[str]
    #: What a thing may be put beside, by ``thing`` or ``object`` and its id: where it stands (a
    #: thing the society holds, where it is now, or its holder), its region and its height.
    anchors: Mapping[tuple[str, str], tuple[Footprint, str, int]]
    #: The newest object the Companion placed of each reviewed kind, by asset key.
    newest_objects: Mapping[str, str]

    def kind(self, key: str) -> KindChoice | None:
        return next((choice for choice in self.kinds if choice.key == key), None)

    def footprint(self, prefix: str, named: str) -> tuple[Footprint, str, int] | None:
        """What a ``near`` names, by its prefix: a placed thing, a placed object, or the newest
        object the Companion placed of a reviewed kind."""
        if prefix == "newest-object":
            prefix, named = "object", self.newest_objects.get(named, "")
        return self.anchors.get((prefix, named))

    def being(self, being_id: str) -> BeingRead | None:
        if self.society is None:
            return None
        return next((being for being in self.society.beings if being.id == being_id), None)

    def place(self, target_id: str) -> PlaceRead | None:
        if self.society is None:
            return None
        return next((place for place in self.society.places if place.target_id == target_id), None)


@cache
def _kinds() -> Mapping[tuple[str, int], ThingKind]:
    return shipped_thing_kinds()


def _look_label(look: Mapping[str, Any] | None) -> str | None:
    """A shipped look's label, by key and version; None for any look the library does not ship."""
    if look is None:
        return None
    found = shipped_looks().get((str(look["look"]), int(look["version"])))
    return None if found is None or found.sha256 != look.get("sha256") else found.label


def _half(kind: ThingKind) -> tuple[int, int]:
    box = kind.document["body"].get("box_mm") if kind.klass == "object" else None
    if box is None:
        return (BEING_HALF_MM, BEING_HALF_MM)
    return (-(-int(box["width"]) // 2), -(-int(box["depth"]) // 2))


def offered_kinds(reviewed_containers: frozenset[str]) -> tuple[KindChoice, ...]:
    """Every kind an author may place, at its newest shipped version, in key order, but those whose
    first look draws a reviewed object's own container (offered as that object)."""
    newest: dict[str, ThingKind] = {}
    for (key, version), kind in _kinds().items():
        if key not in newest or version > newest[key].version:
            newest[key] = kind
    offered = []
    for key in sorted(newest):
        kind = newest[key]
        try:
            placeable_by_author(kind)
        except InvalidThingPlacement:
            continue
        first = kind.looks[0] if kind.looks else None
        look = None if first is None else shipped_looks().get((first["look"], first["version"]))
        container = None if look is None else (look.document.get("container") or {}).get("sha256")
        if container is not None and container in reviewed_containers:
            continue
        offered.append(
            KindChoice(
                key=kind.kind,
                version=kind.version,
                sha256=kind.sha256,
                label=kind.label,
                summary=str(kind.document["summary"]),
                being=kind.klass == "being",
                half_mm=_half(kind),
            )
        )
    return tuple(offered)


def society_thing_id(world_id: str, placed_id: str) -> str:
    """The id a placed thing has in its world's society of things."""
    return str(uuid.uuid5(THING_NAMESPACE, f"{world_id}:{placed_id}"))


def _distance_mm(a: tuple[int, int], b: tuple[int, int] | None) -> int:
    if b is None:
        return 0
    return math.isqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2)


def _object_half(asset_key: str | None) -> tuple[int, int]:
    """Half a reviewed object's width and depth, from the world object catalog; a metre square for
    an object the catalog does not state."""
    kind = None if asset_key is None else world_object_catalog().by_asset_key().get(asset_key)
    if kind is None:
        return (500, 500)
    width, depth, _height = kind.dimensions_mm
    return (-(-width // 2), -(-depth // 2))


def read_things(
    *,
    world_id: str,
    version: Any,
    reviewed: Mapping[str, Any],
    looks: Mapping[str, Mapping[str, Any]],
    society: tuple[Mapping[str, Any], Mapping[str, Any], int, frozenset[str]] | None,
    elevation_mm: int | None,
    viewer: tuple[int, int] | None,
) -> ThingsRead:
    """What a plan of things rests on, from reads a direct client makes.

    ``version`` is the alternate version; ``reviewed`` the reviewed assets by content digest;
    ``looks`` the latest look choice per thing (``GET .../thing-looks``), by the thing's society
    id; ``society`` what :meth:`~exulanica.world.society_action_repository.
    SocietyActionRepository.request_context` answers (the society, its consumed input, the newest
    input's sequence and the beings already asked at this minute), or None for a version whose
    society takes no direct request; ``viewer`` where the person stands, which orders each list
    nearest first.
    """
    kinds = offered_kinds(frozenset(reviewed))
    taken: list[tuple[str, Footprint]] = []
    placed: list[PlacedRead] = []
    beings_placed: set[str] = set()
    anchors: dict[tuple[str, str], tuple[Footprint, str, int]] = {}
    now = _where_things_are(society)
    for thing in version.things:
        if thing.removed:
            continue
        try:
            kind = shipped_kind(thing.kind)
        except InvalidThingPlacement:
            continue
        footprint = Footprint(thing.transform.x_mm, thing.transform.z_mm, _half(kind))
        taken.append((thing.thing_id, footprint))
        moved = now.get(society_thing_id(world_id, thing.thing_id))
        anchors[("thing", thing.thing_id)] = (
            footprint if moved is None else Footprint(moved[0], moved[1], footprint.half_mm),
            thing.region_id,
            thing.transform.y_mm,
        )
        if kind.klass == "being" and society is not None:
            # A being the society holds is named as one of its beings, where it stands now.
            beings_placed.add(thing.thing_id)
            continue
        chosen = looks.get(society_thing_id(world_id, thing.thing_id))
        first = kind.looks[0] if kind.looks else None
        placed.append(
            PlacedRead(
                thing_id=thing.thing_id,
                label=kind.label,
                look_label=_look_label(chosen) or _look_label(first),
                region_id=thing.region_id,
                transform=thing.transform,
                footprint=footprint,
            )
        )
    titles: dict[tuple[str, str], str] = {}
    for thing in version.things:
        if not thing.removed:
            found = _kinds().get((thing.kind.kind, thing.kind.version))
            if found is not None:
                titles[("thing", thing.thing_id)] = found.label
    for obj in version.objects:
        if obj.removed:
            continue
        row = reviewed.get(obj.asset_sha256)
        if row is not None:
            titles[("authored", obj.object_id)] = str(row.title).lower()
        footprint = Footprint(
            obj.transform.x_mm,
            obj.transform.z_mm,
            _object_half(None if row is None else row.asset_key),
        )
        taken.append((obj.object_id, footprint))
        anchors[("object", obj.object_id)] = (footprint, obj.region_id, obj.transform.y_mm)
    standing = {obj.object_id: obj for obj in version.objects if not obj.removed}
    newest: dict[str, str] = {}
    for edit in sorted(version.edits, key=lambda value: value.edit_seq):
        obj = standing.get(edit.object_id) if edit.object_id is not None else None
        row = None if obj is None else reviewed.get(obj.asset_sha256)
        if (
            edit.kind == "add_object"
            and row is not None
            and str(edit.object_id).startswith(f"companion:{row.asset_key}:")
        ):
            newest[row.asset_key] = str(edit.object_id)
    placed.sort(key=lambda item: (_near(item.footprint, viewer), item.thing_id))
    read_society = None if society is None else _society(society, looks, titles, viewer)
    return ThingsRead(
        kinds=kinds,
        placed=tuple(placed[:MAX_THING_CHOICES]),
        society=read_society,
        elevation_mm=elevation_mm,
        taken=tuple(taken),
        placed_count=len(version.things),
        placed_ids=frozenset(thing.thing_id for thing in version.things),
        anchors=anchors,
        newest_objects=newest,
    )


def _where_things_are(
    society: tuple[Mapping[str, Any], Mapping[str, Any], int, frozenset[str]] | None,
) -> dict[str, tuple[int, int]]:
    """Where each thing a society of things holds is now, by its society id: on the ground, or with
    the being holding it. Empty for any other society."""
    if society is None:
        return {}
    state = society[0]["state"]
    people = {
        person["id"]: tuple(int(value) for value in person["position_mm"])
        for person in state.get("inhabitants", ())
    }
    where: dict[str, tuple[int, int]] = {}
    for thing in state.get("things", ()):
        position = thing.get("position_mm")
        if position is not None:
            where[str(thing["id"])] = (int(position[0]), int(position[1]))
        elif thing.get("held_by") in people:
            x_mm, z_mm = people[thing["held_by"]]
            where[str(thing["id"])] = (x_mm, z_mm)
    return where


def _near(footprint: Footprint, viewer: tuple[int, int] | None) -> int:
    return _distance_mm((footprint.x_mm, footprint.z_mm), viewer)


def _society(
    society: tuple[Mapping[str, Any], Mapping[str, Any], int, frozenset[str]],
    looks: Mapping[str, Mapping[str, Any]],
    titles: Mapping[tuple[str, str], str],
    viewer: tuple[int, int] | None,
) -> SocietyRead:
    row, document, newest, asked = society
    state = row["state"]
    beings = []
    for person in state["inhabitants"]:
        reference = person.get("kind")
        kind = (
            None if reference is None else _kinds().get((reference["kind"], reference["version"]))
        )
        came_by = person.get("came_by")
        x_mm, z_mm = (int(value) for value in person["position_mm"])
        footprint = Footprint(x_mm, z_mm, (BEING_HALF_MM, BEING_HALF_MM))
        if came_by == "crossed":
            # A being from outside: its kind and number, never anything its program declared.
            beings.append(
                BeingRead(
                    id=person["id"],
                    display_name=str(person["display_name"]),
                    kind_label=None if kind is None else kind.label,
                    look_label=None,
                    came_by=came_by,
                    footprint=footprint,
                )
            )
            continue
        first = None if kind is None or not kind.looks else kind.looks[0]
        beings.append(
            BeingRead(
                id=person["id"],
                display_name=str(person["display_name"]),
                kind_label=None if kind is None else kind.label,
                look_label=_look_label(looks.get(person["id"])) or _look_label(first),
                came_by=came_by,
                footprint=footprint,
            )
        )
    beings.sort(key=lambda being: (_near(being.footprint, viewer), being.id))
    places = []
    for target in document["targets"]:
        if not target.get("enabled"):
            continue
        origin = "thing" if str(target.get("origin")) == "thing" else "authored"
        places.append(
            PlaceRead(
                target_id=str(target["target_id"]),
                title=titles.get((origin, str(target.get("object_id"))), "a place"),
                affordance=str(target["affordance"]),
            )
        )
    return SocietyRead(
        society_id=str(row["society_id"]),
        engine=str(row["engine_version"]),
        region_id=str(row["region_id"]),
        tick=int(row["current_tick"]),
        state_sha256=str(row["state_sha256"]),
        state=state,
        document=document,
        newest_input_seq=newest,
        beings=tuple(beings[:MAX_THING_CHOICES]),
        places=tuple(places[:MAX_THING_CHOICES]),
        asked=frozenset(asked),
    )


# -- laying a thing out ---------------------------------------------------------------------------


def _turned(direction: tuple[float, float], turn_microradians: int) -> tuple[float, float]:
    angle = turn_microradians / 1_000_000
    cos, sin = math.cos(angle), math.sin(angle)
    return (direction[0] * cos - direction[1] * sin, direction[0] * sin + direction[1] * cos)


def _unit(dx: float, dz: float, fallback: tuple[float, float]) -> tuple[float, float]:
    length = math.hypot(dx, dz)
    return fallback if length == 0 else (dx / length, dz / length)


def _clear(
    point: tuple[int, int],
    radius_mm: int,
    taken: Sequence[Footprint],
    viewer: tuple[int, int] | None,
) -> bool:
    for other in taken:
        room = radius_mm + other.radius_mm + CLEARANCE_MM
        if (point[0] - other.x_mm) ** 2 + (point[1] - other.z_mm) ** 2 < room * room:
            return False
    return viewer is None or _distance_mm(point, viewer) >= radius_mm + PERSON_ROOM_MM


def lay_out(
    half_mm: tuple[int, int],
    *,
    anchor: Footprint | None,
    spot: tuple[int, int] | None,
    viewer: tuple[int, int] | None,
    taken: Sequence[Footprint],
) -> tuple[int, int] | None:
    """Where a thing of ``half_mm`` stands, region-local, or None when nowhere near is free.

    Beside an ``anchor``: on its side toward the person first, then its right, its left and behind
    it, its own size, the thing's and :data:`CLEARANCE_MM` apart, and a millimetre more. Else at
    the pointed ``spot``, or when that is taken on the rings about it (:data:`RINGS_MM`), ahead
    first along the line the person looks, then to either side. A place is free when the thing's
    circle, with the clearance, meets nothing ``taken`` and keeps the person's own room.
    Deterministic: whole millimetres.
    """
    radius = Footprint(0, 0, half_mm).radius_mm
    if anchor is not None:
        toward = (
            (0.0, 1.0)
            if viewer is None
            else _unit(viewer[0] - anchor.x_mm, viewer[1] - anchor.z_mm, (0.0, 1.0))
        )
        # One millimetre over, so rounding to whole millimetres never brings it inside.
        distance = anchor.radius_mm + radius + CLEARANCE_MM + 1
        for turn in SIDE_TURNS:
            dx, dz = _turned(toward, turn)
            point = (round(anchor.x_mm + dx * distance), round(anchor.z_mm + dz * distance))
            if _clear(point, radius, taken, viewer):
                return point
        return None
    if spot is None:
        return None
    if _clear(spot, radius, taken, viewer):
        return spot
    ahead = (
        (0.0, -1.0)
        if viewer is None
        else _unit(spot[0] - viewer[0], spot[1] - viewer[1], (0.0, -1.0))
    )
    for ring in RINGS_MM:
        for turn in RING_TURNS:
            dx, dz = _turned(ahead, turn)
            point = (round(spot[0] + dx * ring), round(spot[1] + dz * ring))
            if _clear(point, radius, taken, viewer):
                return point
    return None


def facing_yaw(point: tuple[int, int], viewer: tuple[int, int] | None, otherwise: int) -> int:
    """The yaw that turns a thing at ``point`` to face the person, as a scene turns its things to
    face the person arriving; ``otherwise`` where the person's place is not known."""
    if viewer is None or tuple(viewer) == tuple(point):
        return otherwise % (MAX_YAW_MICRORADIANS + 1)
    forward = (point[0] - viewer[0], point[1] - viewer[1])
    return round(math.atan2(-forward[0], -forward[1]) * 1_000_000) % (MAX_YAW_MICRORADIANS + 1)


def minted_thing_id(version_id: uuid.UUID, base_state_sha256: str, step: int, kind: str) -> str:
    """The id a thing a plan adds gets: its kind and a digest of the plan's version, base and step.
    Minted when the plan is made and carried in the step's typed action, so a later step of the
    same plan can name it before it exists."""
    digest = hashlib.sha256(
        canonical_json(
            {
                "version_id": str(version_id),
                "base_state_sha256": base_state_sha256,
                "step": step,
                "kind": kind,
            }
        )
    ).hexdigest()
    return f"companion:{kind}:{digest[:12]}"


def placement_refusal(
    *,
    thing_id: str,
    kind: KindChoice,
    region_id: str,
    transform: Transform,
    origin_role: str,
    region_ids: frozenset[str],
    things: ThingsRead,
) -> str | None:
    """The code ``POST .../things`` would refuse this placement with, from the route's own pure
    checks, or None: an id taken, the version's limit, then the placement's own checks."""
    if thing_id in things.placed_ids:
        return "invalid_object_state"
    if things.placed_count >= PLACED_THINGS_MAXIMUM:
        return "thing_limit_reached"
    reference = ThingKindReference(kind.key, kind.version, kind.sha256)
    try:
        validate_placed_thing(
            PlacedThing(
                thing_id=thing_id,
                kind=reference,
                region_id=region_id,
                transform=transform,
                origin=ObjectOrigin("authored", origin_role),
            ),
            region_ids=region_ids,
        )
        placeable_by_author(shipped_kind(reference))
    except InvalidThingPlacement:
        return "invalid_thing_placement"
    return None


def thing_transform(point: tuple[int, int], y_mm: int, yaw: int) -> Transform:
    return Transform(point[0], y_mm, point[1], yaw, UNSCALED_MILLI)


# -- asking a being --------------------------------------------------------------------------------


def direct_body(
    society: SocietyRead,
    *,
    requested_by: uuid.UUID,
    subject_id: str,
    act: str,
    target_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """The body ``POST .../society/actions`` takes for this request now, or the code it would be
    refused with: built by the route's own function on the state and input it reads, so a step is
    offered only where the route would take it. A code in :data:`WAIT_CODES` says to wait for the
    next minute rather than that the request is refused."""
    if society.input_queued:
        return None, "society_input_queued"
    if subject_id in society.asked:
        return None, "inhabitant_action_in_progress"
    place = next((p for p in society.places if p.target_id == target_id), None)
    if place is None:
        return None, "canonical_target_changed"
    kind = DIRECT_ACTS[act]
    intent = ActionIntent(
        kind="perform" if kind == "perform" else "go_to",
        target_id=target_id,
        affordance=place.affordance if kind == "perform" else None,
    )
    key = uuid.uuid5(
        _DIRECT_KEYS,
        canonical_json(
            {
                "society_id": society.society_id,
                "subject_id": subject_id,
                "base_tick": society.tick,
                "base_state_sha256": society.state_sha256,
                "intent": {
                    "kind": intent.kind,
                    "target_id": target_id,
                    "affordance": intent.affordance,
                },
            }
        ).decode(),
    )
    try:
        build_action_request(
            dict(society.state),
            dict(society.document),
            request_id=key,
            requested_by=requested_by,
            subject_id=uuid.UUID(subject_id),
            intent=intent,
        )
    except ValueError as refused:
        reason = str(refused)
        return None, reason if reason.isidentifier() else "invalid_society_action"
    body: dict[str, Any] = {
        "idempotency_key": str(key),
        "base_tick": society.tick,
        "base_state_sha256": society.state_sha256,
        "subject_id": subject_id,
        "intent": (
            {"kind": "perform", "target_id": target_id, "affordance": place.affordance}
            if intent.kind == "perform"
            else {"kind": "go_to", "target_id": target_id}
        ),
    }
    return body, None


def valid_minted_id(thing_id: object, kind: str) -> bool:
    """Whether a client sent back an id of the shape this module mints for ``kind``."""
    if not isinstance(thing_id, str) or not thing_id.startswith(f"companion:{kind}:"):
        return False
    digest = thing_id.removeprefix(f"companion:{kind}:")
    return len(digest) == 12 and all(character in "0123456789abcdef" for character in digest)
