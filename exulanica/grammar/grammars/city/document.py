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
from pathlib import Path
from typing import Any, Final

from exulanica.canonical import canonical_json
from exulanica.grammar import shapes
from exulanica.grammar.catalogs import Catalog, catalog_digest
from exulanica.grammar.contract import DeclaredSemantics
from exulanica.grammar.documents import parse_json
from exulanica.grammar.errors import CatalogError, GrammarError, InvalidRecordError
from exulanica.grammar.grammars.city import CITY_GRAMMAR, CITY_SHAPES
from exulanica.grammar.grammars.city.catalogs import city_vocabularies, entry_fields
from exulanica.grammar.grammars.city.descriptor import (
    CITY_DESCRIPTOR_PATH,
    CITY_DESCRIPTOR_PATHS,
    CITY_GENERATING_VERSIONS,
    CITY_GRAMMAR_ID,
)
from exulanica.grammar.grammars.city.districts import DistrictRecord
from exulanica.grammar.grammars.city.document_building_checks import _BuildingChecks
from exulanica.grammar.grammars.city.document_placed_checks import _PlacedChecks
from exulanica.grammar.grammars.city.document_plan import (
    _SHAPES_BY_TYPE,
    BAY_PITCH_TARGET_MM,
    SUPPORT_KINDS,
    _fail,
    _within_plan,
    support_top_mm,
)
from exulanica.grammar.grammars.city.document_street_checks import _StreetChecks
from exulanica.grammar.grammars.city.facade import EntranceRecord, FacadeRecord, GroundBayRecord
from exulanica.grammar.grammars.city.massing import MassingRecord, RooftopObjectRecord
from exulanica.grammar.grammars.city.material import SurfaceMaterialRecord
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
from exulanica.grammar.grammars.city.vitrine import InteriorBackingRecord, VitrineRecord
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
_SHAPES_BY_KIND: Final = {shape.kind: shape for shape in CITY_SHAPES}
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
    InteriorBackingRecord: "building_identity",
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
        _require_readable(where, (entry.grammar_id, entry.grammar_version))
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


def _require_readable(where: str, key: tuple[str, int]) -> None:
    if key[0] != CITY_GRAMMAR_ID or key[1] not in CITY_GENERATING_VERSIONS:
        raise InvalidRecordError(
            f"{where}: this reader knows city records at versions {CITY_GENERATING_VERSIONS}, "
            f"not {key}"
        )


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
        _require_readable(where, (item["grammar_id"], item["grammar_version"]))
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


class _Checker(_StreetChecks, _BuildingChecks, _PlacedChecks):
    """The checks across one grammar's records in a tile document.

    This class holds the records, their index and the report, and checks references, owners,
    membership and pins. Three parts hold the rest of the checks, each in its own module:
    ``_StreetChecks`` (document_street_checks) streets and roads, ``_BuildingChecks``
    (document_building_checks) lots and buildings, and ``_PlacedChecks`` (document_placed_checks)
    materials, street life, vitrines, walk groups, backings, premises and terrain.
    """

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

    def check_pins(self, descriptor_path: Path | None) -> None:
        """The pins against what was loaded. ``descriptor_path`` defaults to the shipped
        descriptor of the version the tile pins."""
        if descriptor_path is None:
            descriptor_path = CITY_DESCRIPTOR_PATHS[self.grammar.grammar_version]
        if self.grammar.descriptor_sha256 != descriptor_sha256(descriptor_path):
            raise _fail("descriptor_pin", "the tile pins a descriptor other than the one loaded")
        if self.grammar.declared_semantics != CITY_GRAMMAR.semantics:
            raise _fail("semantics", "the tile states other semantics than the city grammar")
        if self.tile.catalog_digest != catalog_digest(tuple(self.catalogs.values())):
            raise _fail("catalog_pin", "the tile pins a catalog digest other than the loaded one")
        for facade in self.of(FacadeRecord):
            if facade.seed != self.tile.city_seed:
                raise _fail("seed", f"facade {facade.identity} states another seed")
            if facade.grammar_version != self.grammar.grammar_version:
                raise _fail(
                    "facade_version",
                    f"facade {facade.identity} states version {facade.grammar_version} in a "
                    f"version {self.grammar.grammar_version} tile",
                )


_CHECKS: Final[tuple[Callable[[_Checker], None], ...]] = (
    _Checker.check_owners,
    _Checker.check_membership,
    _Checker.check_streets,
    _Checker.check_roads,
    _Checker.check_buildings,
    _Checker.check_materials,
    _Checker.check_streetlife,
    _Checker.check_vitrines,
    _Checker.check_backings,
    _Checker.check_walk_groups,
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
    [pin] = tile.grammar_versions
    _require_readable("the tile's grammar pin", (pin.grammar_id, pin.grammar_version))
    everything = GrammarRecords(
        grammar_id=pin.grammar_id,
        grammar_version=pin.grammar_version,
        descriptor_sha256=pin.descriptor_sha256,
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
    descriptor_path: Path | None = None,
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
