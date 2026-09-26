"""Starter arrangements: several world objects a person asks for in one request.

``assets/catalogs/world-objects/world-arrangement.v<N>.json`` states each arrangement once: its
title and summary, how far in front of the person it stands, and its placements, each a kind of
the world object catalog (:mod:`exulanica.world.object_catalog`) at a position and a number of
quarter turns in the arrangement's own frame. That frame is the object catalog's: ``+x`` across,
``+y`` toward the person who asked, and a quarter turn carries an object's front from ``+y`` to
``-x``, the turn a yaw of a quarter circle gives it (:func:`exulanica.world.society_composition.
turned_point`).

**One resolver behind preview and apply.** :func:`preview_arrangement` and
:func:`apply_arrangement` both call ``_resolve``, which reads the version, its base and its ground
and returns the placements or a refusal by name, so the two cannot disagree about one stored
state. The placements are a pure function of that base state, the arrangement's key and version,
and the person's position and heading, so apply needs no token from preview: it resolves again,
inside the caller's transaction, and a base that moved since is refused as ``stale_base``.

**Where it stands.** The person's heading is taken to the nearest quarter turn, the arrangement's
centre is its declared distance ahead of them along that heading and then moved to the nearest node
of the society's route lattice (``LATTICE_MM``), and the arrangement is turned to face the person.
Every placement stands on a lattice node, which the loader holds, so an arrangement meets the
lattice the same way wherever it stands and every place its objects state is reachable the way
``tests/test_world_arrangements.py`` measures once.

**It fits, or it is refused by name** (:data:`ARRANGEMENT_REFUSALS`). The world must stand on an
authored ground the society can read (``arrangement_needs_authored_ground``); every object and
every place its occupants stand at must lie on the ground people walk on, a navigation clearance
inside its edge (``arrangement_outside_ground``); no object may stand where people arrive
(``arrangement_covers_arrival``); and nothing may stand within two clearances of an object the
world already holds, or take a place people stand at to use one (``arrangement_overlaps``). An
existing object is judged by the box around the footprint the society gives it, turned, scaled and
swept by its motion as the society turns, scales and sweeps it, and by its places as the society
places them, so a refusal never lets the arrangement land on it or quietly cost it a place.

**Applied as ordinary edits.** Apply adds each object with
:meth:`~exulanica.world.object_repository.WorldObjectRepository.add_object`, in the arrangement's
order and each against the state the one before it left, inside the transaction the caller opens:
every object is one change in the version's history, taken back one at a time, newest first, by
the version's undo, and a refusal part way writes nothing. The objects carry the origin a person
gives any object they place; the arrangement is named in the answer, not stored on them. Nothing
here brings an inhabitant into a world.
"""

from __future__ import annotations

import contextlib
import functools
import json
import math
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

import psycopg
from psycopg import pq

from exulanica.canonical import canonical_json
from exulanica.grammar.catalogs import (
    Catalog,
    CatalogSchema,
    Licence,
    catalog_digest,
    load_catalog,
    text_field,
)
from exulanica.grammar.errors import CatalogError
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import (
    InvalidatedSourceVersion,
    InvalidObjectData,
    InvalidObjectState,
    InvalidStructuralData,
    StaleObjectBase,
    UnavailableAsset,
    UnknownWorldResource,
)
from exulanica.world.object_catalog import (
    CATALOG_DIRECTORY,
    WorldObjectKind,
    world_object_catalog,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.objects import (
    MAX_YAW_MICRORADIANS,
    AuthoredObject,
    ObjectOrigin,
    Transform,
    object_document,
)

__all__ = [
    "ARRANGEMENT_REFUSALS",
    "CATALOG_ID",
    "CATALOG_VERSION",
    "AppliedArrangement",
    "Arrangement",
    "ArrangementCatalog",
    "ArrangementPlacement",
    "ArrangementPreview",
    "ArrangementRefused",
    "ArrangementRequest",
    "Layout",
    "PlacedObject",
    "apply_arrangement",
    "arrangement_catalog",
    "lay_out",
    "load_arrangement_catalog",
    "placed_at",
    "preview_arrangement",
]

CATALOG_ID: Final = "world-arrangement"
#: The version a running host reads. A new version is published beside this one, never edited in.
CATALOG_VERSION: Final = 1

#: Every code a refusal carries. Stable: codes are added, never renamed. A client holds words for
#: each, and a web test reads this list from here. (No quoted words in this block: that test
#: parses every quoted token between the frozenset's parentheses as a code.)
ARRANGEMENT_REFUSALS: frozenset[str] = frozenset(
    {
        "arrangement_unknown",
        "arrangement_needs_authored_ground",
        "arrangement_outside_ground",
        "arrangement_covers_arrival",
        "arrangement_overlaps",
        "stale_base",
        "source_invalidated",
        "asset_bytes_unavailable",
        "invalid_placement",
        "subject_already_present",
    }
)

_KEY: Final = re.compile(r"[a-z][a-z0-9_]*")
_CITATION: Final = re.compile(r"declared/(?P<declared>[a-z][a-z0-9_]*)")
_QUARTER_TURNS: Final = 4
#: A guard on the distances and offsets the file states, in millimetres, and not a rule of the
#: layout: a hundred metres, so a stray digit is refused where it is read. Whether a layout fits
#: is the ground's to say, and a layout that does not is refused by name
#: (``arrangement_outside_ground``).
_MAX_OFFSET_MM: Final = 100_000
#: Every refusal the durable writer can raise after a ready resolution, and its code, in the
#: order :mod:`exulanica.world.composition_preview` reads the same errors.
_WRITE_REFUSALS: Final[tuple[tuple[type[Exception], str], ...]] = (
    (InvalidatedSourceVersion, "source_invalidated"),
    (StaleObjectBase, "stale_base"),
    (UnavailableAsset, "asset_bytes_unavailable"),
    (InvalidObjectData, "invalid_placement"),
    (InvalidObjectState, "subject_already_present"),
)

Point = tuple[int, int]
#: An axis-aligned box in the region's ``x`` and ``z``: ``(min_x, min_z, max_x, max_z)``.
Box = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ArrangementPlacement:
    """One kind at a position and a number of quarter turns in the arrangement's frame."""

    kind: WorldObjectKind
    x_mm: int
    y_mm: int
    quarter_turns: int
    source: str


@dataclass(frozen=True, slots=True)
class Arrangement:
    key: str
    version: int
    title: str
    summary: str
    #: How far ahead of the person the arrangement's centre stands before it meets the lattice.
    anchor_distance_mm: int
    anchor_source: str
    placements: tuple[ArrangementPlacement, ...]
    declared: Mapping[str, str]
    reason: str
    licence: Licence

    def document(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "version": self.version,
            "title": self.title,
            "summary": self.summary,
        }


@dataclass(frozen=True, slots=True)
class ArrangementCatalog:
    version: int
    arrangements: tuple[Arrangement, ...]
    sha256: str

    def by_key(self) -> Mapping[str, Arrangement]:
        return MappingProxyType({item.key: item for item in self.arrangements})


# -- geometry in the region frame ---------------------------------------------------------------


def _turned(quarter_turns: int, dx: int, dz: int) -> Point:
    """An offset in an object's own ``x`` and ``z``, turned by whole quarter turns, exactly.

    The same turn :func:`exulanica.world.society_composition.turned_point` makes by a yaw of that
    many quarter circles, in integers: its own ``x`` goes to ``(cos, -sin)`` and ``z`` to
    ``(sin, cos)``.
    """
    return ((dx, dz), (dz, -dx), (-dx, -dz), (-dz, dx))[quarter_turns % _QUARTER_TURNS]


def _yaw_microradians(quarter_turns: int) -> int:
    """A whole number of quarter turns as the yaw a transform stores, to the nearest microradian."""
    yaw = round((quarter_turns % _QUARTER_TURNS) * math.pi / 2 * 1_000_000)
    return min(yaw, MAX_YAW_MICRORADIANS)


def _quarter_of(yaw_microradians: int) -> int:
    """The whole number of quarter turns nearest a yaw."""
    return round(yaw_microradians / 1_000_000 / (math.pi / 2)) % _QUARTER_TURNS


def _forward(quarter_turns: int) -> Point:
    """Where a person facing this many quarter turns looks: a yaw's ``(sin, cos)``."""
    return ((0, 1), (1, 0), (0, -1), (-1, 0))[quarter_turns % _QUARTER_TURNS]


def _snapped(value: int, spacing: int) -> int:
    """The nearest multiple of ``spacing``, a half rounded up."""
    return (value + spacing // 2) // spacing * spacing


def _box(centre: Point, half: Point, grow: int = 0) -> Box:
    return (
        centre[0] - half[0] - grow,
        centre[1] - half[1] - grow,
        centre[0] + half[0] + grow,
        centre[1] + half[1] + grow,
    )


def _overlap(a: Box, b: Box) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside(inner: Box, outer: Box) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _contains(box: Box, point: Point) -> bool:
    return box[0] <= point[0] <= box[2] and box[1] <= point[1] <= box[3]


@dataclass(frozen=True, slots=True)
class PlacedObject:
    """One placement as it stands: its centre, its footprint box and its places, region frame."""

    placement: ArrangementPlacement
    centre: Point
    quarter_turns: int
    footprint: Box
    places: tuple[Point, ...]

    @property
    def yaw_microradians(self) -> int:
        return _yaw_microradians(self.quarter_turns)


@dataclass(frozen=True, slots=True)
class Layout:
    """Where an arrangement stands in front of a person: its centre, its turn and its objects."""

    anchor: Point
    quarter_turns: int
    objects: tuple[PlacedObject, ...]


def lay_out(
    arrangement: Arrangement,
    *,
    viewer_x_mm: int,
    viewer_z_mm: int,
    viewer_yaw_microradians: int,
    spacing_mm: int,
) -> Layout:
    """The arrangement ahead of a person, turned to face them, its centre on the lattice.

    ``spacing_mm`` is the society's lattice spacing; a caller passes ``LATTICE_MM``.
    """
    turns = _quarter_of(viewer_yaw_microradians)
    ahead = _forward(turns)
    anchor = (
        _snapped(viewer_x_mm + ahead[0] * arrangement.anchor_distance_mm, spacing_mm),
        _snapped(viewer_z_mm + ahead[1] * arrangement.anchor_distance_mm, spacing_mm),
    )
    return Layout(anchor, turns, placed_at(arrangement, anchor, turns))


def placed_at(
    arrangement: Arrangement, anchor: Point, quarter_turns: int
) -> tuple[PlacedObject, ...]:
    """Every placement of ``arrangement`` with its centre at ``anchor``, turned to face the person.

    The catalog's frame has ``+y`` toward the person and the region's front is ``-z``, so a
    position ``(x, y)`` is ``(x, -y)`` before it is turned, as a stated place is.
    """
    out: list[PlacedObject] = []
    for placement in arrangement.placements:
        dx, dz = _turned(quarter_turns, placement.x_mm, -placement.y_mm)
        centre = (anchor[0] + dx, anchor[1] + dz)
        turns = (quarter_turns + placement.quarter_turns) % _QUARTER_TURNS
        hx, hy = placement.kind.use.footprint_half_extents_mm
        half = (hx, hy) if turns % 2 == 0 else (hy, hx)
        places = tuple(
            (centre[0] + px, centre[1] + pz)
            for px, pz in (_turned(turns, x, -y) for x, y in placement.kind.use.places or ())
        )
        out.append(PlacedObject(placement, centre, turns, _box(centre, half), places))
    return tuple(out)


def _standing() -> tuple[int, int]:
    """The standing spacing and radius, read where the society reads them."""
    from exulanica.world.society_catalogs import load_routine_model

    policy = load_routine_model().policy
    return policy["standing_spacing_mm"], policy["standing_radius_mm"]


# -- the catalog --------------------------------------------------------------------------------


def _int(where: str, value: object, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise CatalogError(f"{where} is an int in [{minimum}, {maximum}], got {value!r}")
    return value


def _object(where: str, value: object, keys: Sequence[str]) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise CatalogError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _citation(where: str, value: object) -> str:
    if type(value) is not str or _CITATION.fullmatch(value) is None:
        raise CatalogError(f"{where} cites declared/<key>, got {value!r}")
    return value


def _nested(reader: Any) -> Any:
    """A catalog field check that reads a nested value and carries it as canonical JSON text."""

    def check(where: str, value: object) -> str:
        reader(where, value)
        return canonical_json(value).decode("utf-8")

    return check


def _read_anchor(where: str, value: object) -> tuple[int, str]:
    item = _object(where, value, ("distance_mm", "source"))
    return (
        _int(f"{where}.distance_mm", item["distance_mm"], 1, _MAX_OFFSET_MM),
        _citation(f"{where}.source", item["source"]),
    )


def _read_placements(where: str, value: object) -> tuple[ArrangementPlacement, ...]:
    if not isinstance(value, list) or not value:
        raise CatalogError(f"{where} is a non-empty list of placements")
    kinds = world_object_catalog().by_key()
    out: list[ArrangementPlacement] = []
    for index, raw in enumerate(value):
        at = f"{where}[{index}]"
        item = _object(at, raw, ("kind", "x_mm", "y_mm", "quarter_turns", "source"))
        kind = kinds.get(item["kind"]) if isinstance(item["kind"], str) else None
        if kind is None:
            raise CatalogError(f"{at}.kind names no kind of the world object catalog")
        out.append(
            ArrangementPlacement(
                kind=kind,
                x_mm=_int(f"{at}.x_mm", item["x_mm"], -_MAX_OFFSET_MM, _MAX_OFFSET_MM),
                y_mm=_int(f"{at}.y_mm", item["y_mm"], -_MAX_OFFSET_MM, _MAX_OFFSET_MM),
                quarter_turns=_int(
                    f"{at}.quarter_turns", item["quarter_turns"], 0, _QUARTER_TURNS - 1
                ),
                source=_citation(f"{at}.source", item["source"]),
            )
        )
    return tuple(out)


def _read_declared(where: str, value: object) -> Mapping[str, str]:
    if not isinstance(value, dict):
        raise CatalogError(f"{where} maps a declared key to the sentence that states it")
    for key, sentence in value.items():
        if _KEY.fullmatch(key) is None:
            raise CatalogError(f"{where}: {key!r} is not a lowercase key")
        text_field(f"{where}.{key}", sentence)
    return MappingProxyType(dict(value))


_SCHEMAS: Final[Mapping[int, CatalogSchema]] = MappingProxyType(
    {
        1: CatalogSchema(
            CATALOG_ID,
            1,
            (
                ("title", text_field),
                ("summary", text_field),
                ("anchor", _nested(_read_anchor)),
                ("placements", _nested(_read_placements)),
                ("declared", _nested(_read_declared)),
                ("reason", text_field),
            ),
        )
    }
)


def _grown(box: Box, by: int) -> Box:
    return (box[0] - by, box[1] - by, box[2] + by, box[3] + by)


def _outside_by(point: Point, box: Box) -> float:
    """How far a point stands outside a box, zero when it is inside."""
    dx = max(box[0] - point[0], 0, point[0] - box[2])
    dz = max(box[1] - point[1], 0, point[1] - box[3])
    return math.hypot(dx, dz)


def _check(arrangement: Arrangement) -> None:
    """Hold an arrangement to the rules its placements must meet wherever it stands.

    Every citation names a declaration and every declaration is cited. Every placement stands on
    a lattice node. Between any two objects there is room for a walker: two navigation clearances.
    Every place any object states stands a navigation clearance and a standing radius outside
    every object in the arrangement, the rule the object catalog holds a kind's own places to, and
    a standing spacing from every other place. And after its centre moves to the nearest lattice
    node, at most half a spacing toward the person, the person stands at least a lattice spacing
    in front of its nearest edge.
    """
    from exulanica.world.society_authored_ground import LATTICE_MM
    from exulanica.world.society_planner import CLEARANCE_MM

    where = f"{CATALOG_ID} {arrangement.key}"
    sources = (arrangement.anchor_source, *(item.source for item in arrangement.placements))
    cited = {match["declared"] for match in map(_CITATION.fullmatch, sources) if match}
    missing = sorted(cited - set(arrangement.declared))
    if missing:
        raise CatalogError(f"{where} cites {missing}, which it does not declare")
    unused = sorted(set(arrangement.declared) - cited)
    if unused:
        raise CatalogError(f"{where} declares {unused} and nothing cites them")
    for placement in arrangement.placements:
        if placement.x_mm % LATTICE_MM or placement.y_mm % LATTICE_MM:
            raise CatalogError(
                f"{where}: {placement.kind.key} at ({placement.x_mm}, {placement.y_mm}) is not on "
                f"a lattice node, a multiple of {LATTICE_MM} mm"
            )
    spacing, radius = _standing()
    placed = placed_at(arrangement, (0, 0), 0)
    for index, item in enumerate(placed):
        for other in placed[:index]:
            if _overlap(item.footprint, _grown(other.footprint, 2 * CLEARANCE_MM)):
                raise CatalogError(
                    f"{where}: {item.placement.kind.key} and {other.placement.kind.key} leave no "
                    f"room to walk between them, two clearances ({2 * CLEARANCE_MM} mm)"
                )
    places = [(item, place) for item in placed for place in item.places]
    for index, (item, place) in enumerate(places):
        for other in placed:
            if _outside_by(place, other.footprint) < CLEARANCE_MM + radius:
                raise CatalogError(
                    f"{where}: a place of {item.placement.kind.key} at {list(place)} stands within "
                    f"a clearance and a standing radius ({CLEARANCE_MM + radius} mm) of "
                    f"{other.placement.kind.key}"
                )
        for _, earlier in places[:index]:
            if (place[0] - earlier[0]) ** 2 + (place[1] - earlier[1]) ** 2 < spacing**2:
                raise CatalogError(
                    f"{where}: places {list(earlier)} and {list(place)} stand closer than the "
                    f"standing spacing, {spacing} mm"
                )
    # Unturned at the origin the person stands on -z, so the nearest edge is the least z.
    front = max(
        *(-item.footprint[1] for item in placed),
        *(-place[1] + radius for _, place in places),
    )
    clear = arrangement.anchor_distance_mm - LATTICE_MM // 2 - front
    if clear < LATTICE_MM:
        raise CatalogError(
            f"{where}: its nearest edge stands {front} mm in front of its centre, so a centre "
            f"{arrangement.anchor_distance_mm} mm ahead, moved half a lattice spacing toward the "
            f"person, leaves them {clear} mm clear of it, less than a lattice spacing "
            f"({LATTICE_MM} mm)"
        )


def _arrangement(catalog: Catalog, index: int) -> Arrangement:
    entry = catalog.entries[index]
    values = dict(entry.values)
    where = f"{CATALOG_ID} {entry.key}"

    def nested(name: str) -> object:
        return json.loads(str(values[name]))

    distance, anchor_source = _read_anchor(f"{where}.anchor", nested("anchor"))
    return Arrangement(
        key=entry.key,
        version=catalog.catalog_version,
        title=str(values["title"]),
        summary=str(values["summary"]),
        anchor_distance_mm=distance,
        anchor_source=anchor_source,
        placements=_read_placements(f"{where}.placements", nested("placements")),
        declared=_read_declared(f"{where}.declared", nested("declared")),
        reason=str(values["reason"]),
        licence=entry.licence,
    )


def load_arrangement_catalog(
    directory: Path = CATALOG_DIRECTORY, version: int = CATALOG_VERSION
) -> ArrangementCatalog:
    """Read one version of the catalog and check every arrangement, or refuse with ``CatalogError``.

    The directory is asked what it holds, as the object catalog's loader asks it: a file of this
    catalog no schema claims, or a schema with no file, is refused.
    """
    claimed = {f"{CATALOG_ID}.v{number}.json" for number in _SCHEMAS}
    present = {path.name for path in directory.glob("*.json") if path.name.startswith(CATALOG_ID)}
    if present != claimed:
        raise CatalogError(
            f"{directory}: files with no schema {sorted(present - claimed)}, "
            f"schemas with no file {sorted(claimed - present)}"
        )
    schema = _SCHEMAS.get(version)
    if schema is None:
        raise CatalogError(f"{CATALOG_ID} v{version} has no schema")
    catalog = load_catalog(directory.joinpath(f"{CATALOG_ID}.v{version}.json"), schema)
    arrangements = tuple(_arrangement(catalog, index) for index in range(len(catalog.entries)))
    for arrangement in arrangements:
        _check(arrangement)
    return ArrangementCatalog(version, arrangements, catalog_digest([catalog]))


@functools.cache
def arrangement_catalog() -> ArrangementCatalog:
    """The catalog a running host reads, loaded and checked once per process."""
    return load_arrangement_catalog()


# -- resolution ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArrangementRequest:
    """What a person asked for, and where they stood: never a position the server did not work out.

    ``viewer_x_mm`` and ``viewer_z_mm`` are the person's position in the world's authored region
    and ``viewer_yaw_microradians`` the yaw an object placed facing them would take.
    """

    base_state_sha256: str
    key: str
    version: int
    viewer_x_mm: int
    viewer_z_mm: int
    viewer_yaw_microradians: int
    origin_role: str


def _declared(reason: str) -> str:
    """A refusal's code, which must be one :data:`ARRANGEMENT_REFUSALS` declares for clients."""
    if reason not in ARRANGEMENT_REFUSALS:
        raise ValueError(f"{reason!r} is not a declared arrangement refusal")
    return reason


class ArrangementRefused(Exception):
    """Apply refused. ``str()`` is exactly the reason code, which is what a problem body carries."""

    def __init__(self, reason: str, detail: str | None = None) -> None:
        super().__init__(_declared(reason))
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True, slots=True)
class ArrangementPreview:
    """The server's verdict on one request against the stored state it read."""

    blocked_reason: str | None
    blocked_detail: str | None
    arrangement: Arrangement | None
    version: Mapping[str, Any]
    anchor: Point | None
    quarter_turns: int | None
    objects: tuple[AuthoredObject, ...]
    #: The kind each object is, in the same order.
    kinds: tuple[WorldObjectKind, ...]

    @property
    def availability(self) -> str:
        return "ready" if self.blocked_reason is None else "blocked"

    def document(self) -> dict[str, Any]:
        return {
            "availability": self.availability,
            "blocked_reason": self.blocked_reason,
            "blocked_detail": self.blocked_detail,
            "arrangement": None if self.arrangement is None else self.arrangement.document(),
            "version": dict(self.version),
            "anchor": None
            if self.anchor is None
            else {
                "x_mm": self.anchor[0],
                "z_mm": self.anchor[1],
                "quarter_turns": self.quarter_turns,
            },
            "would_add": [
                {
                    "object_id": obj.object_id,
                    "asset_key": kind.asset_key,
                    "title": kind.title,
                    "document": object_document(obj),
                }
                for obj, kind in zip(self.objects, self.kinds, strict=True)
            ],
        }


@dataclass(frozen=True, slots=True)
class AppliedArrangement:
    """What apply wrote: the version it left, the arrangement, and each object it added."""

    version: AlternateVersion
    arrangement: Arrangement
    object_ids: tuple[str, ...]


@functools.cache
def _kinds_by_digest() -> Mapping[str, WorldObjectKind]:
    """Each generated reviewed asset's kind, by the digest an authored object names."""
    from exulanica.world.assets import reviewed_assets

    kinds = world_object_catalog().by_asset_key()
    return MappingProxyType(
        {
            asset.content_sha256: kinds[asset.asset_key]
            for asset in reviewed_assets()
            if asset.asset_key in kinds
        }
    )


def _occupied(obj: AuthoredObject) -> Box:
    """The box around what an object the world holds covers, as the society bounds it.

    Its reviewed footprint, scaled, turned and swept by its motion as the society composes it
    (``footprint_ring``, ``SWEPT_BEHAVIOURS``). An asset the catalog does not state, or a motion
    the society cannot sweep, still occupies the point it stands on.
    """
    from exulanica.world.society_authored_ground import SWEPT_BEHAVIOURS
    from exulanica.world.society_composition import footprint_ring

    centre = (obj.transform.x_mm, obj.transform.z_mm)
    kind = _kinds_by_digest().get(obj.asset_sha256)
    if kind is None:
        return _box(centre, (0, 0))
    scale = obj.transform.scale_milli
    hx, hz = kind.use.footprint_half_extents_mm
    half = (-(-hx * scale // 1000), -(-hz * scale // 1000))
    ring = footprint_ring(centre, half, obj.transform.yaw_microradians)
    if obj.behaviour is not None:
        rule = SWEPT_BEHAVIOURS.get((obj.behaviour.behaviour_key, obj.behaviour.behaviour_version))
        if rule is not None:
            # A motion the society cannot read still covers where the object stands.
            with contextlib.suppress(ValueError):
                ring = rule(obj.behaviour.parameters, ring)
    xs = [point[0] for point in ring]
    zs = [point[1] for point in ring]
    return (min(xs), min(zs), max(xs), max(zs))


def _places_in_use(version: AlternateVersion, ground: Any) -> Mapping[str, Sequence[Point]]:
    """Where people stand to use each object the version holds, as the society places them."""
    from exulanica.world.society_authored_ground import StandingPolicy, standing_places
    from exulanica.world.society_composition import reviewed_affordance_registry

    spacing, radius = _standing()
    return standing_places(
        version, reviewed_affordance_registry(), ground, StandingPolicy(spacing, radius)
    )


def _crowds(item: PlacedObject, used: Sequence[Point]) -> bool:
    """Whether a new object would take a place people stand at to use an object already there.

    The society keeps a place a navigation clearance from every obstacle and a standing spacing
    from every place it kept before, so a new blocking footprint within the clearance and a
    standing radius of such a place, or a new place within a standing spacing of it, costs the
    world a place without a word. It is refused instead, as landing on the object would be.
    """
    from exulanica.world.society_planner import CLEARANCE_MM

    spacing, radius = _standing()
    reach = (CLEARANCE_MM + radius, CLEARANCE_MM + radius)
    blocks = item.placement.kind.use.blocks_navigation
    return any(
        (blocks and _overlap(_box(place, reach), item.footprint))
        or any(
            (place[0] - new[0]) ** 2 + (place[1] - new[1]) ** 2 < spacing**2 for new in item.places
        )
        for place in used
    )


def _read_ground(repository: WorldObjectRepository, snapshot_id: uuid.UUID) -> Any:
    """The society's reading of the version's authored ground, or ``None`` when it has none.

    Read by the one reader the society runtime reads a saved world's ground by
    (:func:`~exulanica.world.society_authored_ground.read_authored_ground`); a ground the society
    has no rule for is no ground to stand an arrangement on.
    """
    from exulanica.world.society_authored_ground import read_authored_ground

    try:
        return read_authored_ground(
            repository.connection, repository.workspace_id, repository.world_id, snapshot_id
        )
    except InvalidStructuralData:
        return None


def _reason(exc: Exception) -> str | None:
    for kind, reason in _WRITE_REFUSALS:
        if isinstance(exc, kind):
            return reason
    return None


@dataclass(frozen=True, slots=True)
class _Frame:
    version: Mapping[str, Any]
    arrangement: Arrangement | None

    def blocked(
        self,
        reason: str,
        detail: str,
        anchor: Point | None = None,
        quarter_turns: int | None = None,
    ) -> ArrangementPreview:
        return ArrangementPreview(
            _declared(reason), detail, self.arrangement, self.version, anchor, quarter_turns, (), ()
        )


def _resolve(
    repository: WorldObjectRepository, version_id: uuid.UUID, request: ArrangementRequest
) -> ArrangementPreview:
    from exulanica.world.society_authored_ground import LATTICE_MM
    from exulanica.world.society_planner import CLEARANCE_MM

    row = repository.edit_base_row(version_id)
    arrangement = (
        arrangement_catalog().by_key().get(request.key)
        if request.version == arrangement_catalog().version
        else None
    )
    frame = _Frame(
        version={
            "authored_version_id": str(row["version_id"]),
            "world_id": row["world_id"],
            "state_sha256": row["state_sha256"],
            "edit_seq": int(row["edit_seq"]),
            "source_snapshot_id": str(row["source_snapshot_id"]),
        },
        arrangement=arrangement,
    )
    try:
        repository.require_edit_base(row, request.base_state_sha256)
    except (InvalidatedSourceVersion, StaleObjectBase) as exc:
        reason = _reason(exc)
        assert reason is not None
        return frame.blocked(reason, str(exc))
    if arrangement is None:
        return frame.blocked(
            "arrangement_unknown",
            f"no arrangement is published as {request.key} version {request.version}",
        )
    ground = _read_ground(repository, row["source_snapshot_id"])
    if ground is None:
        return frame.blocked(
            "arrangement_needs_authored_ground",
            "the version's snapshot is not an authored ground the society can read",
        )
    layout = lay_out(
        arrangement,
        viewer_x_mm=request.viewer_x_mm,
        viewer_z_mm=request.viewer_z_mm,
        viewer_yaw_microradians=request.viewer_yaw_microradians,
        spacing_mm=LATTICE_MM,
    )
    anchor, turns, placed = layout.anchor, layout.quarter_turns, layout.objects
    _, radius = _standing()
    area = ground.area
    walkable = (
        area.centre_x_mm - area.half_width_mm + CLEARANCE_MM,
        area.centre_z_mm - area.half_depth_mm + CLEARANCE_MM,
        area.centre_x_mm + area.half_width_mm - CLEARANCE_MM,
        area.centre_z_mm + area.half_depth_mm - CLEARANCE_MM,
    )
    for item in placed:
        if not _inside(item.footprint, walkable) or any(
            not _inside(_box(place, (radius, radius)), walkable) for place in item.places
        ):
            return frame.blocked(
                "arrangement_outside_ground",
                f"{item.placement.kind.key} would stand past the edge of the ground people walk on",
                anchor,
                turns,
            )
    arrival = (ground.arrival_x_mm, ground.arrival_z_mm)
    for item in placed:
        if _contains(_grown(item.footprint, CLEARANCE_MM + radius), arrival):
            return frame.blocked(
                "arrangement_covers_arrival",
                f"{item.placement.kind.key} would stand where people arrive",
                anchor,
                turns,
            )
    current = repository.version(version_id)
    used = _places_in_use(current, ground)
    for existing in sorted(current.objects, key=lambda value: value.object_id):
        if existing.removed:
            continue
        occupied = _occupied(existing)
        for item in placed:
            if _overlap(_grown(item.footprint, 2 * CLEARANCE_MM), occupied) or any(
                _overlap(_box(place, (CLEARANCE_MM + radius, CLEARANCE_MM + radius)), occupied)
                for place in item.places
            ):
                return frame.blocked(
                    "arrangement_overlaps",
                    f"{item.placement.kind.key} would stand on or beside {existing.object_id}",
                    anchor,
                    turns,
                )
            if _crowds(item, used.get(existing.object_id, ())):
                return frame.blocked(
                    "arrangement_overlaps",
                    f"{item.placement.kind.key} would stand where people use {existing.object_id}",
                    anchor,
                    turns,
                )
    objects: list[AuthoredObject] = []
    first_seq = int(row["edit_seq"]) + 1
    for index, item in enumerate(placed):
        kind = item.placement.kind
        try:
            asset = repository.reviewed_asset(kind.asset_key, repository.store)
        except UnknownWorldResource:
            return frame.blocked(
                "asset_bytes_unavailable",
                f"no reviewed asset is named {kind.asset_key} on this server",
                anchor,
                turns,
            )
        if asset.availability != "available":
            return frame.blocked(
                "asset_bytes_unavailable",
                f"the reviewed bytes of {kind.asset_key} are not in storage",
                anchor,
                turns,
            )
        obj = AuthoredObject(
            object_id=f"{arrangement.key}-{first_seq}-{index + 1}-{kind.key}",
            asset_sha256=asset.content_sha256,
            region_id=ground.region_id,
            transform=Transform(
                item.centre[0],
                ground.elevation_mm,
                item.centre[1],
                item.yaw_microradians,
                1000,
            ),
            origin=ObjectOrigin("authored", request.origin_role),
        )
        try:
            checked = repository.validate_object_placement(
                version_id, obj, base_state_sha256=request.base_state_sha256
            )
        except Exception as exc:
            reason = _reason(exc)
            if reason is None:
                raise
            return frame.blocked(reason, str(exc), anchor, turns)
        objects.append(checked)
    return ArrangementPreview(
        None,
        None,
        arrangement,
        frame.version,
        anchor,
        turns,
        tuple(objects),
        tuple(item.placement.kind for item in placed),
    )


@contextmanager
def _one_read_only_snapshot(connection: psycopg.Connection) -> Iterator[None]:
    """A read-only, repeatable-read transaction, or a savepoint in the caller's own transaction.

    The same rule :mod:`exulanica.world.composition_preview` reads a preview under, so the verdict
    and the version it names come from one snapshot.
    """
    if connection.info.transaction_status != pq.TransactionStatus.IDLE:
        with connection.transaction():
            yield
        return
    with connection.transaction():
        connection.execute("set transaction isolation level repeatable read, read only")
        yield


def preview_arrangement(
    repository: WorldObjectRepository, version_id: uuid.UUID, request: ArrangementRequest
) -> ArrangementPreview:
    """Resolve one request against stored state. Takes no lock and writes nothing.

    Raises ``UnknownWorldResource`` for an absent, foreign or other-world version; every other
    refusal is a blocked preview.
    """
    with _one_read_only_snapshot(repository.connection):
        return _resolve(repository, version_id, request)


def apply_arrangement(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    request: ArrangementRequest,
    *,
    actor: uuid.UUID,
) -> AppliedArrangement:
    """Resolve again and add exactly the resolved objects, or raise ``ArrangementRefused``.

    Call it inside the write transaction that also advances any saved-world entry, as
    :func:`exulanica.api.world_edit.commit_edit` opens it, so every object lands or none does.
    Each add is an ordinary object edit against the state the one before it left. A refusal the
    durable writer raises is translated into the code preview gives the same state; anything else
    it raises is not an arrangement verdict and propagates unchanged.
    """
    resolved = _resolve(repository, version_id, request)
    if resolved.blocked_reason is not None:
        raise ArrangementRefused(resolved.blocked_reason, resolved.blocked_detail)
    assert resolved.arrangement is not None
    base = request.base_state_sha256
    version: AlternateVersion | None = None
    # Every object's bytes are looked for before the first add, which may take the asset read lock.
    with repository.reviewed_bytes_read_first(obj.asset_sha256 for obj in resolved.objects):
        for obj in resolved.objects:
            try:
                version = repository.add_object(
                    version_id, obj, base_state_sha256=base, actor=actor
                )
            except Exception as exc:
                reason = _reason(exc)
                if reason is None:
                    raise
                raise ArrangementRefused(reason, str(exc)) from exc
            base = version.state_sha256
    assert version is not None, "a published arrangement places at least one object"
    return AppliedArrangement(
        version=version,
        arrangement=resolved.arrangement,
        object_ids=tuple(obj.object_id for obj in resolved.objects),
    )
