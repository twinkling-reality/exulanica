"""A tile document: one tile's records as a bake reads them, and the checks that span records.

**The envelope**, profile ``exulanica.tile-document/v2``, is canonical JSON and nothing else::

    {
      "profile": "exulanica.tile-document/v2",
      "tile": <the city.tile record payload>,
      "grammars": [
        {
          "grammar_id": "city", "grammar_version": 2,
          "descriptor_sha256": <SHA-256 of the descriptor file's bytes>,
          "declared_semantics": {"subject_kind", "admissible_uses", "plane"},
          "subject_identity": <the admitted city identity every record identity derives from>,
          "owned": [<record payload>, ...],
          "halo": [<record payload>, ...],
          "external": [{"identity": <uuid>, "kind": <record kind>}, ...]
        }
      ]
    }

A record payload is exactly ``record_payload``'s. ``grammars`` is sorted by id and states exactly
the pins the tile record's ``grammar_versions`` states, in order. ``owned`` and ``halo`` are each
sorted by kind, then version, then identity, and no identity is in both.

**External references.** A carried record may name a subject the tile does not carry: a segment
crossing the tile names a node far away, and a street names every segment along it. Each such
identity is listed once in ``external``, sorted by identity, with the kind of the record it names,
so a tile stays a bounded unit of work and every reference still resolves: to a carried record, or
to an external entry whose kind the naming field admits. Every external entry is named by a carried
record, and no identity is both carried and external. A check across records that needs both ends
runs only when both are carried; ``docs/grammar-package.md`` lists which. That every external
identity is carried by some tile of the same city is a rule for a whole generated city, and is not
checked here. A bake draws owned records
only and reads halo records for context. Membership follows the tile record's rules (see
:mod:`~exulanica.grammar.grammars.city.tile`): an owned record's anchor lies in the tile, a halo
record is not owned and its extent meets the tile grown by the halo radius, and a record with no
extent (:data:`RELATION_FIELDS`) belongs wherever the record it relates to belongs. A record with
no anchor (a district, a named street) is never owned.
Profile 1 of this envelope had no subject identity and no membership, so it could not be checked
and is not read.

**The checks.** :func:`validate_city_document` runs every record's own validator, then the checks
no single record can make: every reference resolves to a record of the admitted kind, every
identity is its rule's derivation, every catalog key resolves and means what the record says, the
geometry of each record agrees with the records it stands on, membership matches the anchors, and
the tile's pins match the descriptor and catalogs actually loaded. It returns
:class:`CityDocumentReport`, the mechanical measures the corridor is gated on, each counted from
the records.
"""

from __future__ import annotations

import dataclasses
import hashlib
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar import shapes
from exulanica.grammar.catalogs import Catalog, catalog_digest
from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.documents import parse_json
from exulanica.grammar.errors import CatalogError, GrammarError, InvalidRecordError
from exulanica.grammar.geometry import (
    BOUNDARY,
    INSIDE,
    OUTSIDE,
    Extent,
    edge_run_length,
    integer_sqrt,
    point_in_ring,
    ring_within_ring,
    rings_disjoint,
)
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES
from exulanica.grammar.grammars.city.catalogs import city_vocabularies, entry_fields, form_parts
from exulanica.grammar.grammars.city.common import SIDE_CODES, FormPart
from exulanica.grammar.grammars.city.corners import (
    corner_box,
    frontage_corner,
    junction_fill_box,
    strip_box,
)
from exulanica.grammar.grammars.city.corners import corner_centre as _corner_centre
from exulanica.grammar.grammars.city.corners import walk_round_face as _walk_round_face
from exulanica.grammar.grammars.city.descriptor import (
    CITY_DESCRIPTOR_PATH,
    CITY_GRAMMAR_ID,
    CITY_GRAMMAR_VERSION,
)
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.facade import (
    EntranceRecord,
    FacadeRecord,
    GroundBayRecord,
    facade_output_digest,
)
from exulanica.grammar.grammars.city.massing import (
    MassingRecord,
    RooftopObjectRecord,
    storey_floor_mm,
    tier_top_mm,
)
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord, scaled_module_mm
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.roads import (
    JunctionApproachRecord,
    JunctionRecord,
    LaneConnectionRecord,
    LaneRecord,
    ParkingSpaceRecord,
    RoadMarkingRecord,
    SignalRecord,
)
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord, StreetTreeRecord
from exulanica.grammar.grammars.city.streets import (
    BlockRecord,
    CrossingRecord,
    CurbEdgeRecord,
    StreetNodeRecord,
    StreetRecord,
    StreetSegmentRecord,
)
from exulanica.grammar.grammars.city.terrain import TerrainRecord
from exulanica.grammar.grammars.city.tile import (
    HALO,
    OWNED,
    GrammarPin,
    TileRecord,
    membership,
)
from exulanica.grammar.grammars.city.tile import (
    SHAPE as TILE_SHAPE,
)
from exulanica.grammar.grammars.city.vitrine import VitrineRecord
from exulanica.grammar.records import record_payload, require_identity

__all__ = [
    "ANCHORLESS_KINDS",
    "ANCHOR_OWNER_FIELDS",
    "BAY_PITCH_TARGET_MM",
    "OWN_ANCHOR_KINDS",
    "RELATION_FIELDS",
    "SUPPORT_KINDS",
    "TILE_DOCUMENT_PROFILE",
    "CityDocumentReport",
    "GrammarRecords",
    "TileDocument",
    "descriptor_sha256",
    "document_bytes",
    "read_tile_document",
    "record_sort_key",
    "select_tile",
    "support_top_mm",
    "validate_city_document",
]

TILE_DOCUMENT_PROFILE: Final = "exulanica.tile-document/v2"
#: The target architecture's bay pitch band, which the report measures frontage faces against.
BAY_PITCH_TARGET_MM: Final = (2_400, 3_500)
_SHAPES_BY_KIND: Final = {shape.kind: shape for shape in CITY_SHAPES}
_SHAPES_BY_TYPE: Final = {shape.record_type: shape for shape in CITY_SHAPES}
_ENVELOPE_KEYS: Final = frozenset({"profile", "tile", "grammars"})
_GRAMMAR_KEYS: Final = frozenset(
    {
        "grammar_id",
        "grammar_version",
        "descriptor_sha256",
        "declared_semantics",
        "subject_identity",
        "owned",
        "halo",
        "external",
    }
)
#: For each record kind with no extent, the field naming the record whose membership it shares.
RELATION_FIELDS: Final[Mapping[type, str]] = {
    JunctionApproachRecord: "junction_identity",
    SignalRecord: "controls_identity",
    SurfaceMaterialRecord: "surface_identity",
}
#: For each record kind anchored by its owner, the field naming the owner. The owner is carried
#: wherever the record is, and the record's extent lies inside the owner's in plan, so a tile that
#: carries the record by its extent always carries its owner too.
ANCHOR_OWNER_FIELDS: Final[Mapping[type, str]] = {
    CurbEdgeRecord: "segment_identity",
    LaneRecord: "segment_identity",
    CrossingRecord: "segment_identity",
    ParkingSpaceRecord: "segment_identity",
    StreetFurnitureRecord: "segment_identity",
    StreetTreeRecord: "segment_identity",
    RoadMarkingRecord: "marks_identity",
    LaneConnectionRecord: "junction_identity",
    MassingRecord: "parcel_identity",
    RooftopObjectRecord: "building_identity",
    FacadeRecord: "building_identity",
    PremisesRecord: "building_identity",
    GroundBayRecord: "facade_identity",
    EntranceRecord: "facade_identity",
    VitrineRecord: "building_identity",
}
#: Record kinds anchored by their own fields, which no absent owner can leave unanchored.
OWN_ANCHOR_KINDS: Final = (
    TerrainRecord,
    StreetNodeRecord,
    StreetSegmentRecord,
    BlockRecord,
    ParcelRecord,
    JunctionRecord,
)
#: Record kinds with no single anchor, which no tile owns.
ANCHORLESS_KINDS: Final = (DistrictRecord, StreetRecord)
#: How close, in millimetres, a point derived with one floored integer normal must land.
_NORMAL_ROUNDING_MM: Final = 2
#: The height of the capsule the nav envelope keeps clear, from the descriptor's measures.
_CAPSULE_HEIGHT_MM: Final = next(
    dict(row.measures)["height_mm"]
    for row in CITY_GRAMMAR.projection("nav_envelope").preserved
    if row.property == "capsule_clearance"
)
#: The record kinds whose drawn horizontal surfaces a person stands on, from the descriptor.
SUPPORT_KINDS: Final = frozenset(
    row.kind for row in CITY_GRAMMAR.navigation if row.ground == "support"
)


def support_top_mm(record: Any) -> int:
    """The highest a support record's drawn surface stands, for a clearance above it.

    Each support kind the descriptor names has a rule here, read from its own fields rather than
    its extent, which may hold things that are not its surface (a lot's building, a segment's
    curbs): terrain's highest sample; a segment's highest crown point; a curb's kerb top plus its
    footway's rise; a junction's and a crossing's extent tops, which hold only their surfaces; a
    block's and a lot's grade; an entrance's threshold; a tree's pit, at its trunk base.
    """
    kind = type(record)
    if kind is TerrainRecord:
        return max(record.height_mm)
    if kind is StreetSegmentRecord:
        return max(point[2] for point in record.centreline_mm)
    if kind is CurbEdgeRecord:
        return strip_box(record).max_z_mm
    if kind in (JunctionRecord, CrossingRecord):
        return record.extent.max_z_mm
    if kind in (BlockRecord, ParcelRecord):
        return record.grade_elevation_mm
    if kind is EntranceRecord:
        return record.threshold_z_mm
    if kind is StreetTreeRecord:
        return record.z_mm
    raise InvalidRecordError(f"{kind.__name__} states no support surface")


def descriptor_sha256(path: Path = CITY_DESCRIPTOR_PATH) -> str:
    """The pin a tile carries for a descriptor: SHA-256 of the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_sort_key(record: Any) -> tuple[str, int, str]:
    shape = _SHAPES_BY_TYPE[type(record)]
    return shape.kind, shape.version, record.identity


@dataclass(frozen=True, slots=True)
class GrammarRecords:
    grammar_id: str
    grammar_version: int
    descriptor_sha256: str
    declared_semantics: DeclaredSemantics
    subject_identity: str
    owned: tuple[object, ...]
    halo: tuple[object, ...]
    #: ``(identity, kind)`` of each subject a carried record names and the tile does not carry.
    external: tuple[tuple[str, str], ...]

    def records(self) -> tuple[object, ...]:
        return self.owned + self.halo


@dataclass(frozen=True, slots=True)
class TileDocument:
    tile: TileRecord
    grammars: tuple[GrammarRecords, ...]

    def payload(self) -> dict[str, object]:
        return {
            "profile": TILE_DOCUMENT_PROFILE,
            "tile": record_payload(self.tile),
            "grammars": [
                {
                    "grammar_id": entry.grammar_id,
                    "grammar_version": entry.grammar_version,
                    "descriptor_sha256": entry.descriptor_sha256,
                    "declared_semantics": record_payload(entry.declared_semantics),
                    "subject_identity": entry.subject_identity,
                    "owned": [record_payload(item) for item in entry.owned],
                    "halo": [record_payload(item) for item in entry.halo],
                    "external": [
                        {"identity": identity, "kind": kind} for identity, kind in entry.external
                    ],
                }
                for entry in self.grammars
            ],
        }


def document_bytes(document: TileDocument) -> bytes:
    """The one serialisation of a tile document: canonical JSON of its payload."""
    return canonical_json(document.payload())


def _object(where: str, value: object, keys: frozenset[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise InvalidRecordError(f"{where} is an object with exactly {sorted(keys)}")
    return value


def _records(where: str, raw: object) -> tuple[object, ...]:
    if not isinstance(raw, list):
        raise InvalidRecordError(f"{where} is a list of record payloads")
    records = []
    for index, payload in enumerate(raw):
        kind = payload.get("kind") if isinstance(payload, dict) else None
        shape = _SHAPES_BY_KIND.get(kind)  # type: ignore[arg-type]
        if shape is None or shape is TILE_SHAPE:
            raise InvalidRecordError(f"{where}[{index}] is no city record kind: {kind!r}")
        records.append(shapes.read_record(payload, shape, f"{where}[{index}]"))
    _require_sorted(where, records)
    return tuple(records)


def _require_sorted(where: str, records: Sequence[object]) -> None:
    keys = [record_sort_key(record) for record in records]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise InvalidRecordError(f"{where} is sorted by kind, version and identity, each once")


def _check_envelope(document: TileDocument) -> None:
    """What the envelope promises beyond each record: the pins, the grammar, order, membership."""
    pins = tuple(
        GrammarPin(entry.grammar_id, entry.grammar_version, entry.descriptor_sha256)
        for entry in document.grammars
    )
    if pins != document.tile.grammar_versions:
        raise InvalidRecordError("grammars state exactly the tile's grammar pins, in order")
    for index, entry in enumerate(document.grammars):
        where = f"grammars[{index}]"
        key = (entry.grammar_id, entry.grammar_version)
        if key != (CITY_GRAMMAR_ID, CITY_GRAMMAR_VERSION):
            raise InvalidRecordError(f"{where}: this reader knows city v2 records only, not {key}")
        require_identity("subject_identity", entry.subject_identity)
        _require_sorted(f"{where}.owned", entry.owned)
        _require_sorted(f"{where}.halo", entry.halo)
        overlap = {item.identity for item in entry.owned} & {  # type: ignore[attr-defined]
            item.identity
            for item in entry.halo  # type: ignore[attr-defined]
        }
        if overlap:
            raise InvalidRecordError(f"identities both owned and halo: {sorted(overlap)}")
        _check_external(where, entry)


def _check_external(where: str, entry: GrammarRecords) -> None:
    if not isinstance(entry.external, tuple):
        raise _fail("external_order", f"{where}.external is a tuple of (identity, kind)")
    identities = []
    for position, pair in enumerate(entry.external):
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise _fail("external_order", f"{where}.external[{position}] is (identity, kind)")
        identity, kind = pair
        require_identity(f"{where}.external[{position}].identity", identity)
        shape = _SHAPES_BY_KIND.get(kind)  # type: ignore[arg-type]
        if shape is None or shape.identity is None:
            raise _fail(
                "external_kind",
                f"{where}.external[{position}] names {kind!r}, which is no city subject kind",
            )
        identities.append(identity)
    if identities != sorted(set(identities)):
        raise _fail("external_order", f"{where}.external is sorted by identity, each once")
    carried = {item.identity for item in entry.records()}  # type: ignore[attr-defined]
    both = sorted(carried & set(identities))
    if both:
        raise _fail("external_carried", f"{where}: identities both carried and external: {both}")


def _external(where: str, raw: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, list):
        raise InvalidRecordError(f"{where} is a list")
    pairs = []
    for position, item in enumerate(raw):
        entry = _object(f"{where}[{position}]", item, frozenset({"identity", "kind"}))
        pairs.append((entry["identity"], entry["kind"]))
    return tuple(pairs)


def read_tile_document(data: bytes) -> TileDocument:
    """The tile document in ``data``, refused unless it is exactly its canonical form."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidRecordError("a tile document is UTF-8") from error
    try:
        raw = parse_json(text, "tile document")
    except CatalogError as error:
        raise InvalidRecordError(str(error)) from error
    if canonical_json(raw) != data:
        raise InvalidRecordError("a tile document is exactly its canonical JSON")
    envelope = _object("tile document", raw, _ENVELOPE_KEYS)
    if envelope["profile"] != TILE_DOCUMENT_PROFILE:
        raise InvalidRecordError(f"a tile document's profile is {TILE_DOCUMENT_PROFILE!r}")
    tile = shapes.read_record(envelope["tile"], TILE_SHAPE, "tile")
    if not isinstance(envelope["grammars"], list):
        raise InvalidRecordError("grammars is a list")
    grammars = []
    for index, entry in enumerate(envelope["grammars"]):
        where = f"grammars[{index}]"
        item = _object(where, entry, _GRAMMAR_KEYS)
        key = (item["grammar_id"], item["grammar_version"])
        if key != (CITY_GRAMMAR_ID, CITY_GRAMMAR_VERSION):
            raise InvalidRecordError(f"{where}: this reader knows city v2 records only, not {key}")
        grammars.append(
            GrammarRecords(
                grammar_id=item["grammar_id"],
                grammar_version=item["grammar_version"],
                descriptor_sha256=item["descriptor_sha256"],
                declared_semantics=shapes.read_record(
                    item["declared_semantics"],
                    shapes.SEMANTICS_SHAPE,
                    f"{where}.declared_semantics",
                ),
                subject_identity=item["subject_identity"],
                owned=_records(f"{where}.owned", item["owned"]),
                halo=_records(f"{where}.halo", item["halo"]),
                external=_external(f"{where}.external", item["external"]),
            )
        )
    document = TileDocument(tile, tuple(grammars))
    _check_envelope(document)
    return document


@dataclass(slots=True)
class CityDocumentReport:
    """What a tile's records measure, each figure counted from the records themselves."""

    record_counts: dict[str, int] = field(default_factory=dict)
    buildings: int = 0
    buildings_with_every_facade: int = 0
    frontage_faces_with_bays: int = 0
    frontage_faces_in_pitch_band: int = 0
    edges_over_threshold_without_bays: int = 0
    kerb_heights_mm: tuple[int, ...] = ()
    objects_inside_footprints: int = 0
    materials: int = 0
    materials_with_texture_set: int = 0
    facades: int = 0
    facades_with_section_5_1_fields: int = 0
    unavailable_surfaces: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "record_counts": dict(sorted(self.record_counts.items())),
            "buildings": self.buildings,
            "buildings_with_every_facade": self.buildings_with_every_facade,
            "frontage_faces_with_bays": self.frontage_faces_with_bays,
            "frontage_faces_in_pitch_band": self.frontage_faces_in_pitch_band,
            "edges_over_threshold_without_bays": self.edges_over_threshold_without_bays,
            "kerb_height_range_mm": (
                [min(self.kerb_heights_mm), max(self.kerb_heights_mm)]
                if self.kerb_heights_mm
                else []
            ),
            "objects_inside_footprints": self.objects_inside_footprints,
            "materials": self.materials,
            "materials_with_texture_set": self.materials_with_texture_set,
            "facades": self.facades,
            "facades_with_section_5_1_fields": self.facades_with_section_5_1_fields,
            "unavailable_surfaces": list(self.unavailable_surfaces),
        }


def _fail(check: str, message: str) -> InvalidRecordError:
    return InvalidRecordError(f"[{check}] {message}")


def _cross(a: tuple[int, int], b: tuple[int, int], p: tuple[int, int]) -> int:
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _near_segment(
    p: tuple[int, int], a: tuple[int, int], b: tuple[int, int], tolerance: int
) -> bool:
    """Whether ``p`` is within ``tolerance`` mm of segment ``ab``, by exact integers."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length_squared = dx * dx + dy * dy
    cross = _cross(a, b, p)
    if cross * cross > tolerance * tolerance * length_squared:
        return False
    along = (p[0] - a[0]) * dx + (p[1] - a[1]) * dy
    reach = tolerance * integer_sqrt(length_squared) + 1
    return -reach <= along <= length_squared + reach


def _near_ring(p: tuple[int, int], ring: tuple[tuple[int, int], ...], tolerance: int) -> bool:
    return any(
        _near_segment(p, ring[index], ring[(index + 1) % len(ring)], tolerance)
        for index in range(len(ring))
    )


def _plan(point: tuple[int, ...]) -> tuple[int, int]:
    return point[0], point[1]


def _extent_ring(extent: Extent) -> tuple[tuple[int, int], ...]:
    return (
        (extent.min_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.min_y_mm),
        (extent.max_x_mm, extent.max_y_mm),
        (extent.min_x_mm, extent.max_y_mm),
    )


def _holds(outer: Extent, inner: Extent) -> bool:
    """Whether ``outer`` contains ``inner`` on every axis, height included."""
    return (
        _within_plan(inner, outer)
        and outer.min_z_mm <= inner.min_z_mm
        and inner.max_z_mm <= outer.max_z_mm
    )


def _within_plan(inner: Extent, outer: Extent) -> bool:
    return (
        outer.min_x_mm <= inner.min_x_mm
        and inner.max_x_mm <= outer.max_x_mm
        and outer.min_y_mm <= inner.min_y_mm
        and inner.max_y_mm <= outer.max_y_mm
    )


def _in_extent_plan(extent: Extent, x: int, y: int) -> bool:
    return extent.min_x_mm <= x <= extent.max_x_mm and extent.min_y_mm <= y <= extent.max_y_mm


def _counter_clockwise(directions: Sequence[tuple[int, int]]) -> bool:
    for (ax, ay), (bx, by) in pairwise(directions):
        half_a = 0 if (ay > 0 or (ay == 0 and ax > 0)) else 1
        half_b = 0 if (by > 0 or (by == 0 and bx > 0)) else 1
        if half_a != half_b:
            if half_a > half_b:
                return False
            continue
        if ax * by - ay * bx <= 0:
            return False
    return True


class _Checker:
    def __init__(
        self,
        document: TileDocument,
        grammar: GrammarRecords,
        catalogs: Sequence[Catalog],
    ) -> None:
        self.document = document
        self.tile = document.tile
        self.grammar = grammar
        self.records = grammar.records()
        self.index = shapes.index_records(self.records, _SHAPES_BY_TYPE)
        self.catalogs = {catalog.catalog_id: catalog for catalog in catalogs}
        self.by_type: dict[type, list[Any]] = defaultdict(list)
        for record in self.records:
            self.by_type[type(record)].append(record)
        self.report = CityDocumentReport(
            record_counts=dict(
                Counter(_SHAPES_BY_TYPE[type(record)].kind for record in self.records)
            )
        )
        self._anchors: dict[str, tuple[int, int] | None] = {}
        self.owned_identities = frozenset(record.identity for record in grammar.owned)
        self._footprints: list[tuple[tuple[int, int], ...]] = []

    def of(self, record_type: type) -> list[Any]:
        return self.by_type.get(record_type, [])

    def get(self, identity: str) -> Any:
        return self.index[identity]

    def carried(self, identity: str) -> Any | None:
        """The carried record ``identity`` names, or ``None`` when the tile lists it as external."""
        return self.index.get(identity)

    def complete(self, owner_identity: str) -> bool:
        """Whether every record anchored by this owner is carried: the tile owns the owner.

        A halo owner's parts are carried only where their own extents reach the grown square, so a
        rule that counts an owner's parts runs on an owned owner alone.
        """
        return owner_identity in self.owned_identities

    def check_references(self) -> None:
        external = dict(self.grammar.external)
        named: set[str] = set()
        for record in self.records:
            shape = _SHAPES_BY_TYPE[type(record)]
            for field_shape, target in shapes.named_identities(record, shape):
                referent = self.index.get(target)
                if referent is not None:
                    kind = _SHAPES_BY_TYPE[type(referent)].kind
                elif target in external:
                    kind = external[target]
                    named.add(target)
                else:
                    raise _fail(
                        "references",
                        f"{shape.name}.{field_shape.name} names {target}, which is neither "
                        "carried nor external",
                    )
                if field_shape.refers_to and kind not in field_shape.refers_to:
                    raise _fail(
                        "reference_kind",
                        f"{shape.name}.{field_shape.name} names a {kind}, not one of "
                        f"{field_shape.refers_to}",
                    )
        unnamed = sorted(set(external) - named)
        if unnamed:
            raise _fail(
                "external_unnamed", f"external identities no carried record names: {unnamed}"
            )

    def entry(self, catalog: str, key: str) -> dict[str, Any]:
        return entry_fields(self.catalogs[catalog], key)

    # -- anchors and membership ------------------------------------------------------------

    def anchor(self, record: Any) -> tuple[int, int] | None:
        identity = record.identity
        if identity not in self._anchors:
            self._anchors[identity] = self._compute_anchor(record)
        return self._anchors[identity]

    def _compute_anchor(self, record: Any) -> tuple[int, int] | None:
        kind = type(record)
        through = RELATION_FIELDS.get(kind) or ANCHOR_OWNER_FIELDS.get(kind)
        if through is not None:
            return self.anchor(self.get(getattr(record, through)))
        if kind is TerrainRecord:
            return record.tile_x * self.tile.tile_size_mm, record.tile_y * self.tile.tile_size_mm
        if kind is StreetNodeRecord:
            return record.x_mm, record.y_mm
        if kind in (BlockRecord, ParcelRecord):
            return record.centroid_x_mm, record.centroid_y_mm
        if kind is StreetSegmentRecord:
            start, end = record.centreline_mm[0], record.centreline_mm[-1]
            return (start[0] + end[0]) // 2, (start[1] + end[1]) // 2
        if kind is JunctionRecord:
            extent = record.extent
            return (extent.min_x_mm + extent.max_x_mm) // 2, (
                extent.min_y_mm + extent.max_y_mm
            ) // 2
        return None

    def check_owners(self) -> None:
        """A record anchored by another names a carried one, inside whose extent it lies."""
        for record in self.records:
            kind = type(record)
            field_name = RELATION_FIELDS.get(kind) or ANCHOR_OWNER_FIELDS.get(kind)
            if field_name is None:
                continue
            where = f"{_SHAPES_BY_TYPE[kind].kind} {record.identity}"
            owner = self.carried(getattr(record, field_name))
            if owner is None:
                raise _fail(
                    "anchor_owner",
                    f"{where} belongs with its {field_name} {getattr(record, field_name)}, "
                    "which the tile does not carry",
                )
            if kind in ANCHOR_OWNER_FIELDS and not _within_plan(record.extent, owner.extent):
                raise _fail("owner_extent", f"{where} reaches outside its owner's extent")

    def expected_membership(self, record: Any) -> str:
        """Where the tile's rules put ``record``: by its anchor and extent, or its relation's."""
        related = RELATION_FIELDS.get(type(record))
        if related is not None:
            return self.expected_membership(self.get(getattr(record, related)))
        return membership(self.tile, self.anchor(record), record.extent)

    def check_membership(self) -> None:
        for listed, records in ((OWNED, self.grammar.owned), (HALO, self.grammar.halo)):
            for record in records:
                expected = self.expected_membership(record)
                if expected != listed:
                    raise _fail(
                        "membership",
                        f"{_SHAPES_BY_TYPE[type(record)].kind} {record.identity} is listed "
                        f"{listed} and its anchor and extent make it {expected}",
                    )

    # -- pins ------------------------------------------------------------------------------

    def check_pins(self, descriptor_path: Path) -> None:
        if self.grammar.descriptor_sha256 != descriptor_sha256(descriptor_path):
            raise _fail("descriptor_pin", "the tile pins a descriptor other than the one loaded")
        if self.grammar.declared_semantics != CITY_GRAMMAR.semantics:
            raise _fail("semantics", "the tile states other semantics than the city grammar")
        if self.tile.catalog_digest != catalog_digest(tuple(self.catalogs.values())):
            raise _fail("catalog_pin", "the tile pins a catalog digest other than the loaded one")
        for facade in self.of(FacadeRecord):
            if facade.seed != self.tile.city_seed:
                raise _fail("seed", f"facade {facade.identity} states another seed")

    # -- streets ---------------------------------------------------------------------------

    def check_streets(self) -> None:
        for segment in self.of(StreetSegmentRecord):
            start = self.carried(segment.start_node_identity)
            end = self.carried(segment.end_node_identity)
            if start is not None and segment.centreline_mm[0] != (
                start.x_mm,
                start.y_mm,
                start.z_mm,
            ):
                raise _fail("segment_ends", f"segment {segment.identity} starts off its node")
            if end is not None and segment.centreline_mm[-1] != (end.x_mm, end.y_mm, end.z_mm):
                raise _fail("segment_ends", f"segment {segment.identity} ends off its node")
            street = self.carried(segment.street_identity)
            if street is None:
                continue
            if segment.identity not in street.segment_identities:
                raise _fail("street_segments", f"street {street.identity} omits a segment")
            name = self.entry("street-name", street.name)
            if segment.hierarchy not in name["hierarchies"]:
                raise _fail("street_name", f"{street.name} does not suit a {segment.hierarchy}")
        for street in self.of(StreetRecord):
            if street.name_text != self.entry("street-name", street.name)["text"]:
                raise _fail("street_name", f"street {street.identity} states another name text")
            for identity in street.segment_identities:
                segment = self.carried(identity)
                if segment is not None and segment.street_identity != street.identity:
                    raise _fail("street_segments", f"a segment of {street.identity} names another")
        self._check_curbs()
        self._check_camber()
        self._check_crossings()

    def _segment_curbs(self, segment_identity: str) -> dict[str, CurbEdgeRecord]:
        return {
            curb.side: curb
            for curb in self.of(CurbEdgeRecord)
            if curb.segment_identity == segment_identity
        }

    def _check_curbs(self) -> None:
        followers: Counter[str] = Counter()
        for curb in self.of(CurbEdgeRecord):
            self.report.kerb_heights_mm += (curb.kerb_height_mm,)
            segment = self.get(curb.segment_identity)
            for point in curb.kerb_line_mm:
                if not _in_extent_plan(segment.extent, point[0], point[1]):
                    raise _fail("kerb_line", f"curb {curb.identity} leaves its segment's extent")
            if not _holds(curb.extent, strip_box(curb)):
                raise _fail(
                    "curb_extent", f"curb {curb.identity}'s extent does not hold its straight part"
                )
            for block_identity in curb.block_identity:
                block = self.carried(block_identity)
                if block is not None:
                    self._check_frontage_line(curb, block)
            for next_identity in curb.next_curb_identity:
                followers[next_identity] += 1
                follower = self.carried(next_identity)
                if follower is None:
                    continue
                ends = {segment.start_node_identity, segment.end_node_identity}
                other = self.get(follower.segment_identity)
                if not ends & {other.start_node_identity, other.end_node_identity}:
                    raise _fail("curb_graph", f"curb {curb.identity} is followed across no node")
                self._check_corner(curb, follower)
                self._check_corner_extent(curb, follower)
        branching = [identity for identity, count in followers.items() if count > 1]
        if branching:
            raise _fail("curb_graph", f"curbs followed by more than one curb: {branching}")

    def _check_corner(self, curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> None:
        """The tangent points of the corner from ``curb`` to ``follower`` fit its radius."""
        before, after = _walk_round_face(curb), _walk_round_face(follower)
        p, q = before[-1], after[0]
        radius = curb.corner_radius_mm
        where = f"curb {curb.identity}'s corner to {follower.identity}"
        if radius == 0:
            if p != q:
                raise _fail("corner_radius", f"{where} has no radius and {p} is not {q}")
            return
        leaving = (p[0] - before[-2][0], p[1] - before[-2][1])
        joining = (after[1][0] - q[0], after[1][1] - q[1])
        cross = leaving[0] * joining[1] - leaving[1] * joining[0]
        if cross == 0:
            raise _fail("corner_radius", f"{where} runs straight on and states a radius")
        turn = 1 if cross > 0 else -1
        from_p = _corner_centre(p, leaving, radius, turn)
        from_q = _corner_centre(q, joining, radius, turn)
        if (
            abs(from_p[0] - from_q[0]) > _NORMAL_ROUNDING_MM
            or abs(from_p[1] - from_q[1]) > _NORMAL_ROUNDING_MM
        ):
            raise _fail(
                "corner_radius",
                f"{where}: tangent points {p} and {q} find centres {from_p} and {from_q}, "
                f"not one arc of radius {radius}",
            )

    def _check_corner_extent(self, curb: CurbEdgeRecord, follower: CurbEdgeRecord) -> None:
        """The curb stating a radius owns its corner, and its extent holds the corner's box."""
        try:
            box = corner_box(curb, follower)
        except InvalidRecordError as error:
            raise _fail("corner_extent", str(error)) from error
        if box is None:
            return
        if not _holds(curb.extent, box):
            raise _fail(
                "corner_extent",
                f"curb {curb.identity}'s extent does not hold its corner to {follower.identity}, "
                f"{box}",
            )
        for block_identity in curb.block_identity:
            block = self.carried(block_identity)
            if block is not None and frontage_corner(curb, follower) not in block.boundary_mm:
                raise _fail(
                    "corner_extent",
                    f"curb {curb.identity}'s frontage corner is not a corner of block "
                    f"{block.identity}",
                )

    def _check_junction_extent(self, junction: JunctionRecord) -> None:
        """A junction owns the carriageway fill inside its kerb arcs, and its extent holds it."""
        node = self.carried(junction.node_identity)
        legs = [self.carried(identity) for identity in junction.segment_identities]
        if node is None or None in legs:
            return
        box = junction_fill_box(node, legs, self._segment_curbs, self.carried)
        if box is not None and not _holds(junction.extent, box):
            raise _fail(
                "junction_extent",
                f"junction {junction.identity}'s extent does not hold its fill inside the kerb "
                f"arcs, {box}",
            )

    def _check_frontage_line(self, curb: CurbEdgeRecord, block: BlockRecord) -> None:
        offset = curb.kerb_width_mm + curb.footway_width_mm
        sign = 1 if curb.side == "left" else -1
        for here, after in zip(curb.kerb_line_mm, curb.kerb_line_mm[1:], strict=False):
            dx, dy = after[0] - here[0], after[1] - here[1]
            length = integer_sqrt(dx * dx + dy * dy)
            if length == 0:
                continue
            middle = ((here[0] + after[0]) // 2, (here[1] + after[1]) // 2)
            point = (
                middle[0] + (sign * -dy * offset) // length,
                middle[1] + (sign * dx * offset) // length,
            )
            if not _near_ring(point, block.boundary_mm, _NORMAL_ROUNDING_MM):
                raise _fail(
                    "frontage_line",
                    f"curb {curb.identity}: kerb plus footway does not reach block "
                    f"{block.identity}'s frontage line at {point}",
                )

    def _check_camber(self) -> None:
        """On a level segment, every kerb line point lies the camber's fall below the crown."""
        for curb in self.of(CurbEdgeRecord):
            segment = self.get(curb.segment_identity)
            crowns = {point[2] for point in segment.centreline_mm}
            if len(crowns) != 1:
                continue
            crown = crowns.pop()
            fall = (segment.carriageway_width_mm // 2) * segment.camber_millionths // 1_000_000
            if any(point[2] != crown - fall for point in curb.kerb_line_mm):
                raise _fail(
                    "camber", f"curb {curb.identity} is not the camber's fall below the crown"
                )

    def _check_crossings(self) -> None:
        by_segment: dict[str, list[CrossingRecord]] = defaultdict(list)
        for crossing in self.of(CrossingRecord):
            segment = self.get(crossing.segment_identity)
            if crossing.offset_mm > segment.length_mm:
                raise _fail("crossing_offset", f"crossing {crossing.identity} is off its segment")
            kind = self.entry("crossing-type", crossing.crossing_type)
            if not kind["width_minimum_mm"] <= crossing.width_mm <= kind["width_maximum_mm"]:
                raise _fail("crossing_width", f"crossing {crossing.identity} is outside its type")
            if (kind["signal"] == "required") != bool(crossing.signal_identity):
                raise _fail(
                    "crossing_signal", f"crossing {crossing.identity} and its type disagree"
                )
            if kind["kerb"] == "flush" and crossing.kerb_upstand_mm:
                raise _fail(
                    "crossing_kerb", f"crossing {crossing.identity} is flush with an upstand"
                )
            by_segment[crossing.segment_identity].append(crossing)
        for crossings in by_segment.values():
            ordered = sorted(crossings, key=lambda item: item.crossing_ordinal)
            offsets = [item.offset_mm for item in ordered]
            if offsets != sorted(set(offsets)):
                raise _fail("crossing_order", "crossing ordinals increase with offset")

    # -- roads -----------------------------------------------------------------------------

    def _lane_end_node(self, lane: LaneRecord) -> str:
        segment = self.get(lane.segment_identity)
        return (
            segment.end_node_identity
            if lane.direction == "forward"
            else segment.start_node_identity
        )

    def _lane_start_node(self, lane: LaneRecord) -> str:
        segment = self.get(lane.segment_identity)
        return (
            segment.start_node_identity
            if lane.direction == "forward"
            else segment.end_node_identity
        )

    def check_roads(self) -> None:
        lanes_by_segment: dict[str, list[LaneRecord]] = defaultdict(list)
        for lane in self.of(LaneRecord):
            lanes_by_segment[lane.segment_identity].append(lane)
            use = self.entry("lane-use", lane.lane_use)
            if (use["traffic"] == "none") != (lane.direction == "none"):
                raise _fail("lane_use", f"lane {lane.identity} and its use disagree on traffic")
            if not use["width_minimum_mm"] <= lane.width_mm <= use["width_maximum_mm"]:
                raise _fail("lane_width", f"lane {lane.identity} is outside its use's widths")
            segment = self.get(lane.segment_identity)
            if max(lane.start_offset_mm, lane.end_offset_mm) > segment.length_mm:
                raise _fail("lane_offsets", f"lane {lane.identity} runs past its segment")
        for segment_identity, lanes in lanes_by_segment.items():
            if not self.complete(segment_identity):
                continue
            segment = self.get(segment_identity)
            indices = sorted(lane.lane_index for lane in lanes)
            if indices != list(range(len(indices))):
                raise _fail(
                    "lane_indices", f"segment {segment_identity} numbers its lanes with gaps"
                )
            curbs = self._segment_curbs(segment_identity)
            if set(curbs) == set(SIDE_CODES):
                total = sum(lane.width_mm for lane in lanes) + sum(
                    curb.gutter_width_mm for curb in curbs.values()
                )
                if total != segment.carriageway_width_mm:
                    raise _fail(
                        "carriageway_width",
                        f"segment {segment_identity}: lanes and gutters make {total}, "
                        f"not {segment.carriageway_width_mm}",
                    )
        self._check_junctions()
        self._check_connections()
        self._check_signals()
        self._check_parking()
        self._check_stop_lines()

    def _check_junctions(self) -> None:
        segments = self.of(StreetSegmentRecord)
        for junction in self.of(JunctionRecord):
            self._check_junction_extent(junction)
            node = self.carried(junction.node_identity)
            touching = {
                segment.identity
                for segment in segments
                if junction.node_identity
                in (segment.start_node_identity, segment.end_node_identity)
            }
            listed = [self.carried(identity) for identity in junction.segment_identities]
            carried_listed = {segment.identity for segment in listed if segment is not None}
            if carried_listed != touching:
                raise _fail(
                    "junction_segments", f"junction {junction.identity} lists other segments"
                )
            if node is not None and None not in listed:
                directions = []
                for segment in listed:
                    line = segment.centreline_mm
                    away = (
                        line[1]
                        if segment.start_node_identity == junction.node_identity
                        else line[-2]
                    )
                    directions.append((away[0] - node.x_mm, away[1] - node.y_mm))
                if not _counter_clockwise(directions):
                    raise _fail(
                        "junction_order", f"junction {junction.identity} is not counter-clockwise"
                    )
            control = self.entry("junction-control", junction.control)
            if (control["signal"] == "required") != bool(junction.signal_identity):
                raise _fail(
                    "junction_signal", f"junction {junction.identity} and its control disagree"
                )
            for signal_identity in junction.signal_identity:
                signal = self.carried(signal_identity)
                if signal is not None and signal.controls_identity != junction.identity:
                    raise _fail(
                        "junction_signal", f"junction {junction.identity}'s signal is elsewhere"
                    )
            inbound = {
                lane.segment_identity
                for lane in self.of(LaneRecord)
                if lane.direction != "none" and self._lane_end_node(lane) == junction.node_identity
            }
            approaches = {
                approach.segment_identity: approach
                for approach in self.of(JunctionApproachRecord)
                if approach.junction_identity == junction.identity
            }
            lane_complete = {identity for identity in approaches if self.complete(identity)}
            if not inbound <= set(approaches) or not lane_complete <= inbound:
                raise _fail(
                    "approaches",
                    f"junction {junction.identity} needs one approach per inbound segment",
                )
            for approach in approaches.values():
                if (
                    junction.segment_identities[approach.approach_ordinal]
                    != approach.segment_identity
                ):
                    raise _fail("approaches", f"approach {approach.identity} has another ordinal")
                if approach.control not in control["approach_controls"]:
                    raise _fail(
                        "approaches",
                        f"approach {approach.identity} is not a {junction.control} control",
                    )

    def _check_connections(self) -> None:
        for connection in self.of(LaneConnectionRecord):
            junction = self.get(connection.junction_identity)
            source = self.carried(connection.from_lane_identity)
            target = self.carried(connection.to_lane_identity)
            for lane in (source, target):
                if lane is not None and lane.direction == "none":
                    raise _fail(
                        "connection_lanes",
                        f"connection {connection.identity} joins a lane without traffic",
                    )
            if source is not None and self._lane_end_node(source) != junction.node_identity:
                raise _fail(
                    "connection_lanes",
                    f"connection {connection.identity}'s lane does not reach the node",
                )
            if target is not None and self._lane_start_node(target) != junction.node_identity:
                raise _fail(
                    "connection_lanes",
                    f"connection {connection.identity}'s lane does not leave the node",
                )
            if source is not None and connection.path_mm[0] != source.centreline_mm[-1]:
                raise _fail(
                    "connection_path", f"connection {connection.identity} starts off its stop line"
                )
            if target is not None and connection.path_mm[-1] != target.centreline_mm[0]:
                raise _fail(
                    "connection_path", f"connection {connection.identity} ends off its lane"
                )
            if source is not None and connection.movement not in source.turns:
                raise _fail(
                    "connection_turn",
                    f"connection {connection.identity} makes a turn its lane forbids",
                )

    def _check_signals(self) -> None:
        for signal in self.of(SignalRecord):
            controlled = self.get(signal.controls_identity)
            members = [
                identity
                for group in signal.groups
                for identity in (*group.connection_identities, *group.crossing_identities)
            ]
            if isinstance(controlled, JunctionRecord):
                junction_connections = {
                    connection.identity
                    for connection in self.of(LaneConnectionRecord)
                    if connection.junction_identity == controlled.identity
                }
                grouped = {
                    identity for group in signal.groups for identity in group.connection_identities
                }
                complete = self.complete(controlled.identity)
                if not junction_connections <= grouped or (
                    complete and grouped != junction_connections
                ):
                    raise _fail(
                        "signal_groups", f"signal {signal.identity} groups another set of movements"
                    )
                touching = set(controlled.segment_identities)
                for group in signal.groups:
                    for identity in group.crossing_identities:
                        crossing = self.carried(identity)
                        if crossing is not None and crossing.segment_identity not in touching:
                            raise _fail(
                                "signal_groups", f"signal {signal.identity} releases a far crossing"
                            )
            elif any(group.connection_identities for group in signal.groups):
                raise _fail(
                    "signal_groups", f"crossing signal {signal.identity} releases movements"
                )
            for crossing in self.of(CrossingRecord):
                if (
                    crossing.signal_identity == (signal.identity,)
                    and crossing.identity not in members
                ):
                    raise _fail(
                        "signal_groups", f"signal {signal.identity} leaves its crossing out"
                    )
            for head in signal.heads:
                furniture = self.carried(head.furniture_identity)
                if (
                    furniture is not None
                    and self.entry("street-furniture", furniture.furniture_class)["category"]
                    != "signal"
                ):
                    raise _fail("signal_heads", f"signal {signal.identity}'s head is not a signal")
                if head.serves_identity not in members:
                    raise _fail("signal_heads", f"signal {signal.identity}'s head serves no group")

    def _check_parking(self) -> None:
        for space in self.of(ParkingSpaceRecord):
            kind = self.entry("parking-kind", space.parking_kind)
            if kind["placement"] != space.placement:
                raise _fail(
                    "parking_placement", f"space {space.identity} is not where its kind goes"
                )
            curb = self.carried(space.curb_identity)
            if curb is not None and curb.segment_identity != space.segment_identity:
                raise _fail("parking_curb", f"space {space.identity}'s curb is on another segment")
            access = self.carried(space.access_lane_identity)
            if access is not None:
                if access.segment_identity != space.segment_identity or access.direction == "none":
                    raise _fail("parking_access", f"space {space.identity}'s access lane is wrong")
                low, high = sorted((access.start_offset_mm, access.end_offset_mm))
                if not low <= space.access_start_mm < space.access_end_mm <= high:
                    raise _fail(
                        "parking_access", f"space {space.identity}'s access stretch leaves its lane"
                    )
            sides = sorted(edge_run_length(space.footprint_mm, index) for index in range(4))
            if not (
                kind["width_minimum_mm"] <= sides[0] <= kind["width_maximum_mm"]
                and kind["length_minimum_mm"] <= sides[-1] <= kind["length_maximum_mm"]
            ):
                raise _fail("parking_size", f"space {space.identity} is not its kind's size")
            if space.placement == "carriageway":
                parking_lane = self.carried(space.lane_identity[0])
                if parking_lane is not None and (
                    parking_lane.segment_identity != space.segment_identity
                    or parking_lane.lane_use != "parking"
                ):
                    raise _fail("parking_lane", f"space {space.identity} is not in a parking lane")
            else:
                self._check_footway_parking(space)

    def _check_footway_parking(self, space: ParkingSpaceRecord) -> None:
        capacity = 0
        stands = [self.carried(identity) for identity in space.furniture_identities]
        for stand in stands:
            if stand is None:
                continue
            entry = self.entry("street-furniture", stand.furniture_class)
            if entry["category"] != "cycle_parking" or stand.curb_identity != space.curb_identity:
                raise _fail(
                    "cycle_parking", f"space {space.identity} lists a stand that is not its own"
                )
            if point_in_ring((stand.x_mm, stand.y_mm), space.footprint_mm) != INSIDE:
                raise _fail("cycle_parking", f"space {space.identity}'s stand stands outside it")
            capacity += entry["bicycles_per_stand"]
        if None not in stands and space.capacity > capacity:
            raise _fail(
                "cycle_parking", f"space {space.identity} holds more bicycles than its stands"
            )
        for tree in self.of(StreetTreeRecord):
            if not rings_disjoint(tree.pit_mm, space.footprint_mm):
                raise _fail("cycle_parking", f"space {space.identity} overlaps a tree pit")
        for crossing in self.of(CrossingRecord):
            if not rings_disjoint(_extent_ring(crossing.extent), space.footprint_mm):
                raise _fail("cycle_parking", f"space {space.identity} overlaps a crossing")
        for furniture in self.of(StreetFurnitureRecord):
            if furniture.identity in space.furniture_identities:
                continue
            if point_in_ring((furniture.x_mm, furniture.y_mm), space.footprint_mm) != OUTSIDE:
                raise _fail(
                    "cycle_parking", f"space {space.identity} covers furniture it does not list"
                )

    def _check_stop_lines(self) -> None:
        """No crossing band contains a stop line, and a crossing a junction's signal releases lies
        between that junction's stop lines and its node."""
        junctions = {junction.node_identity: junction for junction in self.of(JunctionRecord)}
        for crossing in self.of(CrossingRecord):
            low = crossing.offset_mm - crossing.width_mm // 2
            high = low + crossing.width_mm
            released_by = {
                signal.controls_identity
                for signal in map(self.carried, crossing.signal_identity)
                if signal is not None
            }
            for lane in self.of(LaneRecord):
                if lane.segment_identity != crossing.segment_identity or lane.direction == "none":
                    continue
                node = self._lane_end_node(lane)
                if node not in junctions:
                    continue
                stop = lane.end_offset_mm
                if low < stop < high:
                    raise _fail("stop_line", f"crossing {crossing.identity} contains a stop line")
                if junctions[node].identity not in released_by:
                    continue
                beyond = low >= stop if lane.direction == "forward" else high <= stop
                if not beyond:
                    raise _fail(
                        "stop_line",
                        f"crossing {crossing.identity} is not between lane {lane.identity}'s "
                        "stop line and its junction",
                    )

    # -- lots and buildings ----------------------------------------------------------------

    def check_buildings(self) -> None:
        for parcel in self.of(ParcelRecord):
            block = self.carried(parcel.block_identity)
            if block is not None and not ring_within_ring(parcel.boundary_mm, block.boundary_mm):
                raise _fail("parcel_in_block", f"parcel {parcel.identity} leaves its block")
            for frontage in parcel.frontages:
                curb = self.carried(frontage.curb_identity)
                if curb is not None and curb.block_identity != (parcel.block_identity,):
                    raise _fail(
                        "frontage_curb", f"parcel {parcel.identity} fronts another block's curb"
                    )
        facades_by_building: dict[str, dict[tuple[int, int], FacadeRecord]] = defaultdict(dict)
        for facade in self.of(FacadeRecord):
            facades_by_building[facade.building_identity][
                (facade.tier_ordinal, facade.edge_ordinal)
            ] = facade
        footprints = []
        for building in self.of(MassingRecord):
            parcel = self.get(building.parcel_identity)
            if parcel.lot_class != "building":
                raise _fail("building_lot", f"building {building.identity} stands on a precinct")
            footprint = building.tiers[0].ring_mm
            footprints.append(footprint)
            if not ring_within_ring(footprint, parcel.boundary_mm):
                raise _fail(
                    "footprint_in_parcel", f"building {building.identity} leaves its parcel"
                )
            self._check_building_vocabulary(building)
            edges = {
                (tier_index, edge)
                for tier_index, tier in enumerate(building.tiers)
                for edge in range(len(tier.ring_mm))
            }
            present = facades_by_building.get(building.identity, {})
            if self.complete(building.identity):
                self.report.buildings += 1
                self.report.buildings_with_every_facade += set(present) == edges
            if set(present) - edges:
                raise _fail("facade_edges", f"building {building.identity} has a facade on no edge")
        self._footprints = footprints
        for obj in self.of(RooftopObjectRecord):
            self._check_rooftop(obj)
        for facade in self.of(FacadeRecord):
            self._check_facade(facade)
        for bay in self.of(GroundBayRecord):
            self._check_bay(bay)
        for entrance in self.of(EntranceRecord):
            self._check_entrance(entrance)

    def _check_building_vocabulary(self, building: MassingRecord) -> None:
        typology = self.entry("typology", building.typology)
        era = self.entry("era", building.era)
        family = self.entry("roof-family", building.roof_family)
        where = f"building {building.identity}"
        if building.era not in typology["eras"]:
            raise _fail(
                "typology", f"{where}: a {building.typology} is not of the {building.era} era"
            )
        if (
            building.roof_family not in typology["roof_families"]
            or building.roof_family not in era["roof_families"]
        ):
            raise _fail(
                "roof_family", f"{where}: {building.roof_family} does not suit its typology and era"
            )
        if not typology["storeys_minimum"] <= building.storeys <= typology["storeys_maximum"]:
            raise _fail("typology", f"{where} has storeys its typology does not")
        if (
            not era["upper_storey_minimum_mm"]
            <= building.upper_storey_height_mm
            <= era["upper_storey_maximum_mm"]
        ):
            raise _fail("era", f"{where}'s storeys are not its era's height")
        if family["form"] != building.roof_form:
            raise _fail(
                "roof_family", f"{where}: a {building.roof_family} roof is {family['form']}"
            )
        if not family["rise_minimum_mm"] <= building.roof_rise_mm <= family["rise_maximum_mm"]:
            raise _fail("roof_family", f"{where}'s roof rise is outside its family")
        parapet = building.tiers[-1].parapet_height_mm
        if (family["parapet"] == "required" and not parapet) or (
            family["parapet"] == "none" and parapet
        ):
            raise _fail("roof_family", f"{where}'s parapet disagrees with its roof family")

    def _check_rooftop(self, obj: RooftopObjectRecord) -> None:
        building = self.get(obj.building_identity)
        family = self.entry("roof-family", building.roof_family)
        entry = self.entry("rooftop-object", obj.object_class)
        where = f"rooftop object {obj.identity}"
        if building.roof_form != "flat" or family["rooftop_objects"] != "allowed":
            raise _fail("rooftop", f"{where} stands on a roof that takes none")
        if obj.parts != form_parts(entry["parts"]):
            raise _fail("rooftop", f"{where}'s parts are not its class's parts")
        if obj.clearance_mm < entry["clearance_minimum_mm"]:
            raise _fail("rooftop", f"{where} keeps less clearance than its class")
        tiers = building.tiers
        for index, tier in enumerate(tiers):
            covered = (
                index + 1 < len(tiers)
                and point_in_ring((obj.x_mm, obj.y_mm), tiers[index + 1].ring_mm) != OUTSIDE
            )
            if point_in_ring((obj.x_mm, obj.y_mm), tier.ring_mm) == INSIDE and not covered:
                if obj.z_mm != tier_top_mm(building, tier):
                    raise _fail("rooftop", f"{where} is not on its roof deck")
                return
        raise _fail("rooftop", f"{where} stands on no exposed roof")

    def _check_facade(self, facade: FacadeRecord) -> None:
        self.report.facades += 1
        self.report.facades_with_section_5_1_fields += 1
        building = self.get(facade.building_identity)
        where = f"facade {facade.identity}"
        if facade.tier_ordinal >= len(building.tiers):
            raise _fail("facade_edges", f"{where} stands on no tier")
        tier = building.tiers[facade.tier_ordinal]
        if facade.edge_ordinal >= len(tier.ring_mm):
            raise _fail("facade_edges", f"{where} stands on no edge")
        if facade.run_length_mm != edge_run_length(tier.ring_mm, facade.edge_ordinal):
            raise _fail("facade_run", f"{where}'s run is not its edge's")
        if (facade.first_storey, facade.last_storey) != (tier.first_storey, tier.last_storey):
            raise _fail("facade_storeys", f"{where} covers other storeys than its tier")
        if facade.first_storey == 0 and facade.band_top_mm != building.ground_storey_height_mm:
            raise _fail("ground_band", f"{where}'s ground band is not its ground storey")
        if facade.exposure == "frontage":
            curb = self.carried(facade.faces_curb_identity[0])
            if curb is not None and curb.segment_identity != facade.faces_segment_identity[0]:
                raise _fail("facade_frontage", f"{where} faces a curb of another segment")
            self.report.frontage_faces_with_bays += facade.bays.count > 0
            low, high = BAY_PITCH_TARGET_MM
            self.report.frontage_faces_in_pitch_band += (
                facade.bays.count > 0 and low <= facade.bays.pitch_mm <= high
            )
        if facade.exposure == "party_wall":
            parcel = self.get(building.parcel_identity)
            ring = tier.ring_mm
            for vertex in (ring[facade.edge_ordinal], ring[(facade.edge_ordinal + 1) % len(ring)]):
                if point_in_ring(vertex, parcel.boundary_mm) != BOUNDARY:
                    raise _fail("party_wall", f"{where} is not on its lot line")
        elif facade.run_length_mm > 1_200 and facade.bays.count == 0:
            self.report.edges_over_threshold_without_bays += 1
        era = self.entry("era", building.era)
        if era["cornice"] == "none" and facade.cornice:
            raise _fail("cornice", f"{where} has a cornice its era does not")
        top_frontage = (
            facade.exposure == "frontage" and facade.tier_ordinal == len(building.tiers) - 1
        )
        if era["cornice"] == "required" and top_frontage and not facade.cornice:
            raise _fail("cornice", f"{where} lacks the cornice its era requires")
        self._check_facade_clearance(facade, building)
        bays = tuple(
            bay for bay in self.of(GroundBayRecord) if bay.facade_identity == facade.identity
        )
        expected_bays = list(range(facade.bays.count)) if facade.first_storey == 0 else []
        present_bays = sorted(bay.bay_ordinal for bay in bays)
        complete = self.complete(facade.identity)
        if not set(present_bays) <= set(expected_bays) or (
            complete and present_bays != expected_bays
        ):
            raise _fail("ground_bays", f"{where} has one ground bay record per bay, and no other")
        bound = {binding.name: binding.value for binding in facade.parameters}
        for grid in facade.openings:
            for name, value in (
                ("opening_width_mm", grid.width_mm),
                ("opening_height_mm", grid.height_mm),
                ("sill_height_mm", grid.sill_height_mm),
                ("reveal_depth_mm", grid.reveal_depth_mm),
                ("sill_projection_mm", grid.sill_projection_mm),
                ("sill_thickness_mm", grid.sill_thickness_mm),
                ("head_treatment", grid.head_treatment),
                ("head_rise_mm", grid.head_rise_mm),
                ("head_band_mm", grid.head_band_mm),
                ("head_projection_mm", grid.head_projection_mm),
            ):
                if bound[name] != value:
                    raise _fail("facade_parameters", f"{where}'s openings disagree with {name}")
        entrances = tuple(
            entrance
            for entrance in self.of(EntranceRecord)
            if entrance.facade_identity == facade.identity
        )
        if complete and facade.output_digest != facade_output_digest(facade, bays, entrances):
            raise _fail("output_digest", f"{where}'s output digest is not its layout's")

    def _check_facade_clearance(self, facade: FacadeRecord, building: MassingRecord) -> None:
        """Every part a face puts beyond its building's base ring stands at least the capsule
        height above the building's base: its mouldings, and its openings' projecting sills and
        heads. Panels are set into the wall and project nothing."""
        where = f"facade {facade.identity}"
        for moulding in (*facade.string_courses, *facade.cornice):
            if moulding.z_bottom_mm < _CAPSULE_HEIGHT_MM:
                raise _fail(
                    "facade_clearance",
                    f"{where} projects a moulding {moulding.z_bottom_mm} mm above its base, below "
                    f"the {_CAPSULE_HEIGHT_MM} mm capsule",
                )
        for grid in facade.openings:
            for storey in grid.storeys:
                floor = storey_floor_mm(building, storey) - building.base_elevation_mm
                bottoms = []
                if grid.sill_projection_mm:
                    bottoms.append(floor + grid.sill_height_mm - grid.sill_thickness_mm)
                if grid.head_projection_mm:
                    bottoms.append(floor + grid.sill_height_mm + grid.height_mm)
                if bottoms and min(bottoms) < _CAPSULE_HEIGHT_MM:
                    raise _fail(
                        "facade_clearance",
                        f"{where} projects an opening's sill or head below the "
                        f"{_CAPSULE_HEIGHT_MM} mm capsule on storey {storey}",
                    )

    def _check_bay(self, bay: GroundBayRecord) -> None:
        facade = self.get(bay.facade_identity)
        layout = facade.bays
        where = f"bay {bay.identity}"
        if facade.first_storey != 0:
            raise _fail("ground_bay", f"{where} is on a face above the ground band")
        if bay.bay_ordinal >= layout.count:
            raise _fail("ground_bay", f"{where} is past its face's bays")
        if (bay.u_start_mm, bay.width_mm) != (
            layout.margin_start_mm + bay.bay_ordinal * layout.pitch_mm,
            layout.pitch_mm,
        ):
            raise _fail("ground_bay", f"{where} is not where its face's layout puts it")
        if max(panel.z_top_mm for panel in bay.panels) != facade.band_top_mm:
            raise _fail("ground_bay", f"{where} is not as tall as its ground band")
        for awning in bay.awning:
            if awning.front_z_mm - awning.valance_mm < _CAPSULE_HEIGHT_MM:
                raise _fail(
                    "facade_clearance",
                    f"{where}'s awning hangs to {awning.front_z_mm - awning.valance_mm} mm above "
                    f"its base, below the {_CAPSULE_HEIGHT_MM} mm capsule",
                )

    def _check_entrance(self, entrance: EntranceRecord) -> None:
        facade = self.get(entrance.facade_identity)
        bay = self.carried(entrance.bay_identity)
        building = self.get(facade.building_identity)
        where = f"entrance {entrance.identity}"
        left = entrance.u_centre_mm - entrance.width_mm // 2
        right = left + entrance.width_mm
        if bay is not None:
            if bay.facade_identity != facade.identity:
                raise _fail("entrance", f"{where}'s bay is on another face")
            if left < bay.u_start_mm or right > bay.u_start_mm + bay.width_mm:
                raise _fail("entrance", f"{where} leaves its bay")
            if not any(
                panel.role == "door" and panel.u_start_mm <= left and right <= panel.u_end_mm
                for panel in bay.panels
            ):
                raise _fail("entrance", f"{where} has no door panel")
        tier = building.tiers[facade.tier_ordinal]
        ring = tier.ring_mm
        start, end = ring[facade.edge_ordinal], ring[(facade.edge_ordinal + 1) % len(ring)]
        if not _near_segment(
            (entrance.threshold_x_mm, entrance.threshold_y_mm), start, end, _NORMAL_ROUNDING_MM
        ):
            raise _fail("entrance", f"{where}'s threshold is off its face")
        run = facade.run_length_mm
        along = (entrance.threshold_x_mm - start[0]) * (end[0] - start[0]) + (
            entrance.threshold_y_mm - start[1]
        ) * (end[1] - start[1])
        expected = entrance.u_centre_mm * run
        if abs(along - expected) > _NORMAL_ROUNDING_MM * run:
            raise _fail("entrance", f"{where}'s threshold is not at its centre along the face")
        if entrance.threshold_z_mm != building.base_elevation_mm:
            raise _fail("entrance", f"{where}'s threshold is not at the building's base")
        if (
            facade.faces_curb_identity
            and entrance.approach_curb_identity != facade.faces_curb_identity
        ):
            raise _fail("entrance", f"{where} opens onto another curb than its face")

    # -- materials -------------------------------------------------------------------------

    def check_materials(self) -> None:
        dressed: set[tuple[str, str]] = set()
        for material in self.of(SurfaceMaterialRecord):
            self.report.materials += 1
            surface = self.get(material.surface_identity)
            where = f"material {material.identity}"
            if _SHAPES_BY_TYPE[type(surface)].kind != material.surface_kind:
                raise _fail(
                    "material_surface", f"{where} names a {material.surface_kind} it is not"
                )
            entry = self.entry("material", material.material)
            if entry["texture_set_id"] != material.texture_set_id:
                raise _fail("material_texture", f"{where} names another set than its material")
            self.report.materials_with_texture_set += 1
            if material.role not in entry["surfaces"]:
                raise _fail(
                    "material_role",
                    f"{where}: {material.material} does not dress a {material.role}",
                )
            for name, module in (
                ("course_module_mm", "course_module_mm"),
                ("mortar_module_mm", "mortar_module_mm"),
            ):
                if getattr(material, name) != scaled_module_mm(
                    entry[module], material.repeat_size_millionths
                ):
                    raise _fail("material_module", f"{where}'s {name} is not its set's, scaled")
            dressed.add((material.surface_identity, material.role))
        for facade in self.of(FacadeRecord):
            if (facade.identity, "wall") not in dressed:
                raise _fail("material_wall", f"facade {facade.identity} has no wall material")
            building = self.get(facade.building_identity)
            if facade.exposure != "party_wall" and (facade.identity, "wall") in dressed:
                wall = next(
                    material
                    for material in self.of(SurfaceMaterialRecord)
                    if material.surface_identity == facade.identity and material.role == "wall"
                )
                if wall.material not in self.entry("era", building.era)["wall_materials"]:
                    raise _fail(
                        "material_era", f"facade {facade.identity}'s wall is not of its era"
                    )
        unavailable = []
        for bay in self.of(GroundBayRecord):
            for panel in bay.panels:
                if panel.role in ("glazing", "transom", "door"):
                    unavailable.append(f"{bay.identity}:{panel.role}")
        for marking in self.of(RoadMarkingRecord):
            unavailable.append(f"{marking.identity}:marking")
        for tree in self.of(StreetTreeRecord):
            unavailable.append(f"{tree.identity}:tree")
        self.report.unavailable_surfaces = tuple(sorted(unavailable))

    # -- streetlife, vitrines, premises ----------------------------------------------------

    def _check_placed(self, record: Any, parts: tuple[FormPart, ...], exclusion: int) -> None:
        curb = self.carried(record.curb_identity)
        where = f"{_SHAPES_BY_TYPE[type(record)].kind} {record.identity}"
        if curb is not None and curb.segment_identity != record.segment_identity:
            raise _fail("placement", f"{where}'s curb is on another segment")
        if record.parts != parts:
            raise _fail("placement", f"{where}'s parts are not its class's parts")
        if record.exclusion_radius_mm < exclusion:
            raise _fail("placement", f"{where} keeps less clear than its class")
        for footprint in self._footprints:
            if point_in_ring((record.x_mm, record.y_mm), footprint) != OUTSIDE:
                raise _fail("footprint_intersection", f"{where} stands inside a building")
        for crossing in self.of(CrossingRecord):
            if _in_extent_plan(crossing.extent, record.x_mm, record.y_mm):
                raise _fail("placement", f"{where} stands in a crossing")

    def check_streetlife(self) -> None:
        placed = []
        for furniture in self.of(StreetFurnitureRecord):
            entry = self.entry("street-furniture", furniture.furniture_class)
            self._check_placed(furniture, form_parts(entry["parts"]), entry["exclusion_radius_mm"])
            if (
                not entry["kerb_offset_minimum_mm"]
                <= furniture.kerb_offset_mm
                <= entry["kerb_offset_maximum_mm"]
            ):
                raise _fail(
                    "placement",
                    f"furniture {furniture.identity} is outside its class's kerb offsets",
                )
            placed.append(furniture)
        for tree in self.of(StreetTreeRecord):
            self._check_placed(tree, tree.parts, 0)
            self._check_canopy_clearance(tree)
            placed.append(tree)
        for index, first in enumerate(placed):
            for second in placed[index + 1 :]:
                dx, dy = first.x_mm - second.x_mm, first.y_mm - second.y_mm
                reach = first.exclusion_radius_mm + second.exclusion_radius_mm
                if dx * dx + dy * dy < reach * reach:
                    raise _fail(
                        "exclusion", f"{first.identity} and {second.identity} crowd each other"
                    )

    def _check_canopy_clearance(self, tree: StreetTreeRecord) -> None:
        """A canopy part whose plan box meets a support record stands at least the capsule height
        above that record's support surface."""
        supports = [
            record for record in self.records if _SHAPES_BY_TYPE[type(record)].kind in SUPPORT_KINDS
        ]
        for index, part in enumerate(tree.parts):
            if part.surface_role != "canopy":
                continue
            half_x, half_y = (part.size_x_mm + 1) // 2, (part.size_y_mm + 1) // 2
            low_x, high_x = (
                tree.x_mm + part.offset_x_mm - half_x,
                tree.x_mm + part.offset_x_mm + half_x,
            )
            low_y, high_y = (
                tree.y_mm + part.offset_y_mm - half_y,
                tree.y_mm + part.offset_y_mm + half_y,
            )
            bottom = tree.z_mm + part.offset_z_mm
            for support in supports:
                extent = support.extent
                if (
                    extent.min_x_mm <= high_x
                    and low_x <= extent.max_x_mm
                    and extent.min_y_mm <= high_y
                    and low_y <= extent.max_y_mm
                    and bottom < support_top_mm(support) + _CAPSULE_HEIGHT_MM
                ):
                    raise _fail(
                        "canopy_clearance",
                        f"tree {tree.identity}'s canopy part {index} hangs to {bottom} mm over "
                        f"{support.identity}, less than the {_CAPSULE_HEIGHT_MM} mm capsule above "
                        "its surface",
                    )

    def check_vitrines(self) -> None:
        for vitrine in self.of(VitrineRecord):
            bay = self.carried(vitrine.bay_identity)
            facade = self.carried(vitrine.facade_identity)
            where = f"vitrine {vitrine.identity}"
            if (
                bay is not None and facade is not None and bay.facade_identity != facade.identity
            ) or (facade is not None and facade.building_identity != vitrine.building_identity):
                raise _fail("vitrine", f"{where} names a bay, face and building that disagree")
            left, right = vitrine.u_start_mm, vitrine.u_start_mm + vitrine.width_mm
            bottom, top = vitrine.sill_mm, vitrine.sill_mm + vitrine.height_mm
            covered = 0
            for panel in bay.panels if bay is not None else ():
                if panel.role != "glazing":
                    continue
                width = min(right, panel.u_end_mm) - max(left, panel.u_start_mm)
                height = min(top, panel.z_top_mm) - max(bottom, panel.z_bottom_mm)
                if width > 0 and height > 0:
                    covered += width * height
            if bay is not None and covered != vitrine.width_mm * vitrine.height_mm:
                raise _fail("vitrine", f"{where} is not wholly behind glazing")
            unit = form_parts(self.entry("fitout", vitrine.fitout)["parts"])
            for part in vitrine.parts:
                if not any(
                    dataclasses.replace(part, offset_x_mm=other.offset_x_mm) == other
                    for other in unit
                ):
                    raise _fail(
                        "vitrine",
                        f"{where} holds a part that is not its fitout's, moved along the run",
                    )
                half_x, half_y = part.size_x_mm // 2, part.size_y_mm // 2
                if (
                    part.offset_x_mm - half_x < 0
                    or part.offset_x_mm + half_x > vitrine.width_mm
                    or part.offset_y_mm - half_y < 0
                    or part.offset_y_mm + half_y > vitrine.depth_mm
                    or part.offset_z_mm < 0
                    or part.offset_z_mm + part.size_z_mm > vitrine.height_mm
                ):
                    raise _fail("vitrine", f"{where}'s fitout leaves its box")

    def check_premises(self) -> None:
        for premises in self.of(PremisesRecord):
            building = self.get(premises.building_identity)
            where = f"premises {premises.identity}"
            if premises.last_storey >= building.storeys:
                raise _fail("premises", f"{where} is above its building")
            faces = {
                facade.identity
                for facade in self.of(FacadeRecord)
                if facade.building_identity == building.identity
            }
            for identity in premises.bay_identities:
                bay = self.carried(identity)
                if bay is not None and bay.facade_identity not in faces:
                    raise _fail("premises", f"{where} occupies another building's bay")
            for identity in premises.entrance_identities:
                entrance = self.carried(identity)
                if entrance is not None and entrance.facade_identity not in faces:
                    raise _fail("premises", f"{where} is reached through another building")
            use = self.entry("use-class", premises.use_class)
            if (use["signage"] == "required") != bool(premises.sign):
                raise _fail("premises_sign", f"{where}'s sign disagrees with its use class")
            for key, text in zip(premises.sign, premises.sign_text, strict=True):
                sign = self.entry("signage-lexicon", key)
                if sign["use_class"] != premises.use_class or sign["text"] != text:
                    raise _fail("premises_sign", f"{where}'s sign is another use's or another text")
            typology = self.entry("typology", building.typology)
            uses = typology[
                "ground_floor_uses" if premises.first_storey == 0 else "upper_floor_uses"
            ]
            if premises.use_class not in uses:
                raise _fail(
                    "premises_use",
                    f"{where}: a {building.typology} has no {premises.use_class} there",
                )
            for vitrine in self.of(VitrineRecord):
                if vitrine.bay_identity in premises.bay_identities:
                    fitout = self.entry("fitout", vitrine.fitout)
                    if premises.use_class not in fitout["use_classes"]:
                        raise _fail(
                            "vitrine_fitout",
                            f"vitrine {vitrine.identity} is not dressed for a {premises.use_class}",
                        )

    def check_terrain(self) -> None:
        for terrain in self.grammar.owned:
            if isinstance(terrain, TerrainRecord) and (terrain.tile_x, terrain.tile_y) != (
                self.tile.tile_x,
                self.tile.tile_y,
            ):
                raise _fail("terrain", f"terrain {terrain.identity} is another tile's")


_CHECKS: Final[tuple[Callable[[_Checker], None], ...]] = (
    _Checker.check_owners,
    _Checker.check_membership,
    _Checker.check_streets,
    _Checker.check_roads,
    _Checker.check_buildings,
    _Checker.check_materials,
    _Checker.check_streetlife,
    _Checker.check_vitrines,
    _Checker.check_premises,
    _Checker.check_terrain,
)


def select_tile(
    tile: TileRecord, records: Sequence[object], *, subject_identity: str
) -> TileDocument:
    """The tile document one tile carries out of a whole city's records, by the tile's rules.

    ``records`` must name only one another. Each is owned, halo or left out by its anchor and
    extent; every identity a carried record names that is left out is listed as external. This
    selects and generates nothing: every record is one the caller already has.
    """
    everything = GrammarRecords(
        grammar_id=CITY_GRAMMAR_ID,
        grammar_version=CITY_GRAMMAR_VERSION,
        descriptor_sha256=descriptor_sha256(),
        declared_semantics=CITY_GRAMMAR.semantics,
        subject_identity=subject_identity,
        owned=tuple(sorted(records, key=record_sort_key)),
        halo=(),
        external=(),
    )
    checker = _Checker(TileDocument(tile, (everything,)), everything, ())
    checker.check_references()
    places: dict[str, list[object]] = {OWNED: [], HALO: []}
    for record in everything.owned:
        place = checker.expected_membership(record)
        if place in places:
            places[place].append(record)
    carried = {record.identity for record in (*places[OWNED], *places[HALO])}  # type: ignore[attr-defined]
    external: dict[str, str] = {}
    for record in (*places[OWNED], *places[HALO]):
        for _field, target in shapes.named_identities(record, _SHAPES_BY_TYPE[type(record)]):
            if target not in carried:
                external[target] = _SHAPES_BY_TYPE[type(checker.get(target))].kind
    return TileDocument(
        tile,
        (
            dataclasses.replace(
                everything,
                owned=tuple(places[OWNED]),
                halo=tuple(places[HALO]),
                external=tuple(sorted(external.items())),
            ),
        ),
    )


def validate_city_document(
    document: TileDocument,
    *,
    catalogs: Sequence[Catalog],
    descriptor_path: Path = CITY_DESCRIPTOR_PATH,
    vocabularies: Mapping[str, frozenset[str]] | None = None,
) -> CityDocumentReport:
    """Every check a tile's records can be held to without generating them. Refuses the first
    failure, naming the check that failed in brackets.

    A document built in memory is held to everything :func:`read_tile_document` holds bytes to:
    the envelope, and every record's own validator, before any check across records runs.
    """
    shapes.validate_record(document.tile, TILE_SHAPE)
    _check_envelope(document)
    for grammar in document.grammars:
        for record in grammar.records():
            shape = _SHAPES_BY_TYPE.get(type(record))
            if shape is None or shape is TILE_SHAPE:
                raise InvalidRecordError(f"{type(record).__name__} is no city record kind")
            shapes.validate_record(record, shape)
    report = CityDocumentReport()
    for grammar in document.grammars:
        checker = _Checker(document, grammar, catalogs)
        try:
            checker.check_references()
            shapes.check_identities(
                checker.records,
                _SHAPES_BY_TYPE,
                grammar_id=grammar.grammar_id,
                root_identity=grammar.subject_identity,
            )
            shapes.check_vocabularies(
                checker.records,
                _SHAPES_BY_TYPE,
                vocabularies if vocabularies is not None else city_vocabularies(catalogs),
            )
            checker.check_pins(descriptor_path)
            for check in _CHECKS:
                check(checker)
        except KeyError as error:
            raise InvalidRecordError(f"[references] {error} is named and not stated") from error
        except (CatalogError, GrammarError):
            raise
        report = checker.report
    return report
