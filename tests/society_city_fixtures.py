"""A hand-written city block built only from the grammar's record classes, never a generator.

Four streets ring one block, counter-clockwise, so each segment's left footway faces the block.
One crossing on the south street joins the inner and outer footways. Three buildings hold a
bakery, a cafe, a grocery, an office and nine dwellings; a fourth unit's use class has no routine
mapping. A bench and a tree stand on the south footway.
"""

from exulanica.grammar.grammars.city.massing import MassingRecord
from exulanica.grammar.grammars.city.parcels import ParcelRecord
from exulanica.grammar.grammars.city.premises import PremisesRecord
from exulanica.grammar.grammars.city.streetlife import StreetFurnitureRecord
from exulanica.grammar.grammars.city.streets import StreetNodeRecord, StreetSegmentRecord

BUILDINGS = (
    "3f1c7a52-0d7e-4b53-9c1e-5a2f0c6b7d01",
    "3f1c7a52-0d7e-4b53-9c1e-5a2f0c6b7d02",
    "3f1c7a52-0d7e-4b53-9c1e-5a2f0c6b7d03",
)
CORNERS = ((0, 0), (100_000, 0), (100_000, 80_000), (0, 80_000))


def _segment(ordinal, crossings=()):
    start, end = CORNERS[ordinal], CORNERS[(ordinal + 1) % 4]
    return StreetSegmentRecord(
        segment_ordinal=ordinal,
        start_node=ordinal,
        end_node=(ordinal + 1) % 4,
        centreline_mm=(start, end),
        hierarchy="local",
        carriageway_width_mm=7000,
        kerb_height_mm=150,
        gutter_width_mm=300,
        footway_width_mm=3000,
        corner_radius_mm=2000,
        crossing_offsets_mm=crossings,
    )


def _massing(building, parcel):
    return MassingRecord(
        building_identity=building,
        parcel_ordinal=parcel,
        typology="terrace",
        era="interwar",
        storeys=3,
        ground_storey_height_mm=4000,
        upper_storey_height_mm=3000,
        setbacks=(),
        party_wall_edges=(),
        light_well_count=0,
        roof_family="flat",
        parapet_height_mm=600,
        rooftop_plant_count=0,
        rooftop_tank_count=0,
    )


def _parcel(ordinal, frontage, box, lot="building", address=1):
    (x0, y0), (x1, y1) = box
    return ParcelRecord(
        parcel_ordinal=ordinal,
        block_ordinal=0,
        lot_class=lot,
        boundary_mm=((x0, y0), (x1, y0), (x1, y1), (x0, y1)),
        frontage_segment_ordinal=frontage,
        frontage_mm=x1 - x0,
        address_number=address,
        threshold_offset_mm=1500,
    )


def _premises(building, unit, use):
    return PremisesRecord(
        building_identity=building, unit_ordinal=unit, use_class=use, sign=f"{use}_sign"
    )


def city_block_records():
    records = [StreetNodeRecord(i, x, y) for i, (x, y) in enumerate(CORNERS)]
    records += [_segment(0, (50_000,)), _segment(1), _segment(2), _segment(3)]
    records += [
        _parcel(0, 0, ((10_000, 10_000), (40_000, 35_000)), address=12),
        _parcel(1, 0, ((60_000, 10_000), (90_000, 35_000)), address=14),
        _parcel(2, 2, ((10_000, 45_000), (45_000, 70_000)), address=3),
        _parcel(3, 1, ((70_000, 45_000), (90_000, 70_000)), lot="memory_precinct", address=5),
    ]
    records += [_massing(BUILDINGS[0], 0), _massing(BUILDINGS[1], 1), _massing(BUILDINGS[2], 2)]
    records += [
        _premises(BUILDINGS[0], 0, "bakery"),
        _premises(BUILDINGS[0], 1, "residential"),
        _premises(BUILDINGS[0], 2, "residential"),
        _premises(BUILDINGS[1], 0, "cafe"),
        _premises(BUILDINGS[1], 1, "residential"),
        _premises(BUILDINGS[1], 2, "residential"),
        _premises(BUILDINGS[1], 3, "residential"),
        _premises(BUILDINGS[1], 4, "laundrette"),
        _premises(BUILDINGS[2], 0, "grocery"),
        _premises(BUILDINGS[2], 1, "residential"),
        _premises(BUILDINGS[2], 2, "residential"),
        _premises(BUILDINGS[2], 3, "residential"),
        _premises(BUILDINGS[2], 4, "residential"),
        _premises(BUILDINGS[2], 5, "office"),
    ]
    records += [
        StreetFurnitureRecord(0, "bench", 0, "left", 60_000, 800, 60_000, 4600),
        StreetFurnitureRecord(1, "plane_tree", 0, "left", 30_000, 800, 30_000, 4600),
    ]
    return records
