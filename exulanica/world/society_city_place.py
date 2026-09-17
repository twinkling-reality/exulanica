"""The generated city as a society place: a pure function from grammar records to the contract.

Only the city grammar's record classes are read (streets, parcels, massing, premises and street
furniture), never a generator, so the corridor's real records drop in unchanged. Everything is
integer geometry:

- a footway runs along each side of a street segment, offset from the centreline by half the
  carriageway, the gutter and half the footway, with a standing station every catalogued spacing;
- footways meeting at a junction join only within the same corner, taken from the angular order
  of the segments, so nobody crosses a carriageway at a junction;
- a carriageway is crossed only where a segment's ``crossing_offsets_mm`` puts a crossing;
- a premises unit is an indoor destination whose use class maps, through the routine's use-class
  catalog, to its visitors, staff, residents, role and shift. Its access node is the projection
  of its parcel's centroid onto the frontage footway. That projection is a fallback until the
  city records carry a premises entrance; and
- street furniture whose item class has a use-class entry (a bench) is an outdoor destination
  with one standing spot per seat.

Offsets at a bend use the direction of the piece that leaves the vertex, not a mitre, and a
premises unit whose use class the routine does not know is listed as unsupported, never guessed.
No record carries a street name, so none is published.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from functools import cmp_to_key
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import sha256_of_canonical
from exulanica.grammar.grammars.city.massing import MassingRecord, validate_massing
from exulanica.grammar.grammars.city.parcels import ParcelRecord, validate_parcel
from exulanica.grammar.grammars.city.premises import PremisesRecord, validate_premises
from exulanica.grammar.grammars.city.streetlife import (
    StreetFurnitureRecord,
    validate_street_furniture,
)
from exulanica.grammar.grammars.city.streets import (
    StreetNodeRecord,
    StreetSegmentRecord,
    validate_street_node,
    validate_street_segment,
)
from exulanica.grammar.records import canonical_record
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import PLACE_PROFILE, ceil_distance, seal_place

__all__ = ["CITY_RECORDS_PROFILE", "place_from_city_records"]

CITY_RECORDS_PROFILE: Final = "exulanica.city-records/v1"
_VALIDATORS: Final = {
    StreetNodeRecord: validate_street_node,
    StreetSegmentRecord: validate_street_segment,
    ParcelRecord: validate_parcel,
    MassingRecord: validate_massing,
    PremisesRecord: validate_premises,
    StreetFurnitureRecord: validate_street_furniture,
}
_SIDES: Final = ("left", "right")

Point = tuple[int, int]


def _round_div(numerator: int, denominator: int) -> int:
    """Integer division rounded half away from zero; the same on every platform."""
    quotient, remainder = divmod(abs(numerator), denominator)
    if 2 * remainder >= denominator:
        quotient += 1
    return quotient if numerator >= 0 else -quotient


def _offset(start: Point, end: Point, distance: int, side: str) -> Point:
    """The vector ``distance`` millimetres to one side of the direction start to end."""
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.isqrt(dx * dx + dy * dy)
    sign = 1 if side == "left" else -1
    return (
        _round_div(-dy * distance * sign, length),
        _round_div(dx * distance * sign, length),
    )


class _Centreline:
    def __init__(self, points: Sequence[Point]) -> None:
        self.points = [tuple(p) for p in points]
        self.pieces = []
        along = 0
        for a, b in pairwise(self.points):
            length = ceil_distance(a, b)
            self.pieces.append((along, length, a, b))
            along += length
        self.length = along

    def at(self, along: int, distance: int, side: str) -> Point:
        """The footway point ``along`` millimetres from the start, on one side."""
        along = max(0, min(self.length, along))
        for start, length, a, b in self.pieces:
            if along <= start + length or (start, length, a, b) == self.pieces[-1]:
                t = along - start
                base = (
                    a[0] + _round_div((b[0] - a[0]) * t, length),
                    a[1] + _round_div((b[1] - a[1]) * t, length),
                )
                ox, oy = _offset(a, b, distance, side)
                return (base[0] + ox, base[1] + oy)
        raise AssertionError("unreachable")

    def project(self, point: Point) -> tuple[int, str]:
        """The along-distance and side of the centreline nearest to ``point``."""
        best = None
        for start, length, a, b in self.pieces:
            dx, dy = b[0] - a[0], b[1] - a[1]
            px, py = point[0] - a[0], point[1] - a[1]
            dot = px * dx + py * dy
            squared = dx * dx + dy * dy
            t = max(0, min(squared, dot))
            foot = (a[0] + _round_div(dx * t, squared), a[1] + _round_div(dy * t, squared))
            gap = (point[0] - foot[0]) ** 2 + (point[1] - foot[1]) ** 2
            side = "left" if dx * py - dy * px > 0 else "right"
            candidate = (gap, start + _round_div(length * t, squared), side)
            if best is None or candidate[:2] < best[:2]:
                best = candidate
        assert best is not None
        return best[1], best[2]


def _half_plane(vector: Point) -> int:
    return 0 if vector[1] > 0 or (vector[1] == 0 and vector[0] > 0) else 1


def _angular(a: tuple, b: tuple) -> int:
    """Counter-clockwise order of outward directions, by exact integer comparison."""
    va, vb = a[0], b[0]
    ha, hb = _half_plane(va), _half_plane(vb)
    if ha != hb:
        return ha - hb
    cross = va[0] * vb[1] - va[1] * vb[0]
    if cross:
        return -1 if cross > 0 else 1
    return (a[1] > b[1]) - (a[1] < b[1])


def place_from_city_records(
    *,
    place_id: str,
    records: Sequence[object],
    routine: RoutineModel,
    input_seq: int = 1,
) -> dict[str, Any]:
    """Derive the society place a generated city supports. Records are validated first."""
    by_type: dict[type, list] = {kind: [] for kind in _VALIDATORS}
    for record in records:
        validator = _VALIDATORS.get(type(record))
        if validator is None:
            continue
        validator(record)
        by_type[type(record)].append(record)
    street_nodes = {r.node_ordinal: r for r in by_type[StreetNodeRecord]}
    segments = {r.segment_ordinal: r for r in sorted(by_type[StreetSegmentRecord], key=_ordinal)}
    parcels = {r.parcel_ordinal: r for r in by_type[ParcelRecord]}
    massing = {r.building_identity: r for r in by_type[MassingRecord]}
    if not segments:
        raise ValueError("a city place needs street segments")
    for segment in segments.values():
        if segment.start_node not in street_nodes or segment.end_node not in street_nodes:
            raise ValueError(f"segment {segment.segment_ordinal} names an unknown street node")
    spacing = routine.policy["footway_station_spacing_mm"]
    unsupported: set[str] = {
        "premises entrances (access points project each parcel's centroid onto its frontage)",
        "signal plans (no crossing record names one)",
        "street names (no city record carries one)",
    }
    lines = {o: _Centreline(s.centreline_mm) for o, s in segments.items()}
    offsets = {
        o: s.carriageway_width_mm // 2 + s.gutter_width_mm + s.footway_width_mm // 2
        for o, s in segments.items()
    }
    # Stations: (segment, side, along) -> named candidate point on that footway.
    stations: dict[tuple[int, str], dict[int, str]] = {
        (o, side): {} for o in segments for side in _SIDES
    }
    names: dict[str, Point] = {}

    def station(segment: int, side: str, along: int, name: str) -> str:
        point = lines[segment].at(along, offsets[segment], side)
        held = stations[(segment, side)].get(along)
        if held is not None:
            return held
        stations[(segment, side)][along] = name
        names[name] = point
        return name

    for o, line in lines.items():
        for side in _SIDES:
            count = max(1, line.length // spacing)
            for index in range(count + 1):
                along = line.length * index // count
                station(o, side, along, f"footway:{o}:{side}:{along}")
    crossings = []
    crossing_pairs = []
    for o, segment in segments.items():
        for offset in segment.crossing_offsets_mm:
            if offset > lines[o].length:
                unsupported.add(f"crossing beyond segment {o}'s centreline")
                continue
            left = station(o, "left", offset, f"footway:{o}:left:{offset}")
            right = station(o, "right", offset, f"footway:{o}:right:{offset}")
            crossing_pairs.append((f"crossing:{o}:{offset}", o, offset, left, right))
    access: dict[int, str] = {}
    for parcel in sorted(parcels.values(), key=lambda p: p.parcel_ordinal):
        if parcel.frontage_segment_ordinal not in segments:
            unsupported.add(f"parcel {parcel.parcel_ordinal} fronts an unknown segment")
            continue
        ring = parcel.boundary_mm
        centroid = (
            _round_div(sum(p[0] for p in ring), len(ring)),
            _round_div(sum(p[1] for p in ring), len(ring)),
        )
        segment = parcel.frontage_segment_ordinal
        along, side = lines[segment].project(centroid)
        access[parcel.parcel_ordinal] = station(
            segment, side, along, f"footway:{segment}:{side}:{along}"
        )
    furniture_nodes = []
    for item in sorted(by_type[StreetFurnitureRecord], key=lambda r: r.item_ordinal):
        use = routine.use_classes.get(item.item_class)
        if use is None or use.kind != "furniture":
            continue
        if item.segment_ordinal not in segments:
            unsupported.add(f"street furniture {item.item_ordinal} names an unknown segment")
            continue
        segment = item.segment_ordinal
        link = station(
            segment,
            item.side,
            item.along_mm,
            f"footway:{segment}:{item.side}:{item.along_mm}",
        )
        furniture_nodes.append((item, use, link))

    # One node per distinct position; the lexicographically first name wins.
    canonical: dict[Point, str] = {}
    for name in sorted(names):
        canonical.setdefault(names[name], name)
    alias = {name: canonical[point] for name, point in names.items()}
    nodes = {alias[name]: names[name] for name in names}
    edges: dict[frozenset, dict] = {}

    def connect(a: str, b: str, kind: str) -> str | None:
        a, b = alias.get(a, a), alias.get(b, b)
        if a == b:
            return None
        key = frozenset((a, b))
        if key not in edges:
            low, high = sorted((a, b))
            edges[key] = {
                "edge_id": f"{low}|{high}",
                "from_node_id": low,
                "to_node_id": high,
                "length_mm": ceil_distance(nodes[low], nodes[high]),
                "kind": kind,
            }
        elif kind == "crossing":
            edges[key]["kind"] = "crossing"
        return edges[key]["edge_id"]

    for chain in stations.values():
        ordered = [chain[along] for along in sorted(chain)]
        for a, b in pairwise(ordered):
            connect(a, b, "footway")
    for crossing_id, o, offset, left, right in crossing_pairs:
        edge_id = connect(left, right, "crossing")
        if edge_id is not None:
            crossings.append(
                {
                    "crossing_id": crossing_id,
                    "edge_id": edge_id,
                    "street_segment_ordinal": o,
                    "offset_mm": offset,
                }
            )
    for ordinal in sorted(street_nodes):
        ends = []
        for o, segment in segments.items():
            line = lines[o]
            if segment.start_node == ordinal:
                first, second = line.points[0], line.points[1]
                ends.append(((second[0] - first[0], second[1] - first[1]), o, 0, False))
            if segment.end_node == ordinal:
                last, before = line.points[-1], line.points[-2]
                ends.append(((before[0] - last[0], before[1] - last[1]), o, line.length, True))
        if len(ends) < 2:
            continue
        ends.sort(key=cmp_to_key(_angular))
        for index, (_, o, along, reversed_) in enumerate(ends):
            _, o2, along2, reversed2 = ends[(index + 1) % len(ends)]
            outward_left = stations[(o, "right" if reversed_ else "left")][along]
            next_right = stations[(o2, "left" if reversed2 else "right")][along2]
            connect(outward_left, next_right, "footway")
    spot_positions: dict[Point, str] = {}
    spots: dict[str, dict] = {}
    destinations = []
    for item, use, link in furniture_nodes:
        name = f"furniture:{item.item_ordinal}"
        if (item.x_mm, item.y_mm) in canonical or name in nodes:
            unsupported.add(f"street furniture {item.item_ordinal} sits on a footway station")
            continue
        nodes[name] = (item.x_mm, item.y_mm)
        canonical[(item.x_mm, item.y_mm)] = name
        connect(link, name, "furniture_access")
        line = lines[item.segment_ordinal]
        a, b = line.pieces[0][2], line.pieces[0][3]
        for start, length, pa, pb in line.pieces:
            if item.along_mm <= start + length:
                a, b = pa, pb
                break
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.isqrt(dx * dx + dy * dy)
        seats = []
        count = use.visitor_capacity
        for seat in range(count):
            shift = (2 * seat - (count - 1)) * routine.policy["standing_spacing_mm"]
            point = (
                item.x_mm + _round_div(dx * shift, 2 * length),
                item.y_mm + _round_div(dy * shift, 2 * length),
            )
            if point in spot_positions:
                continue
            spot_id = f"{name}:seat:{seat}"
            spot_positions[point] = spot_id
            spots[spot_id] = {
                "spot_id": spot_id,
                "node_id": name,
                "position_mm": list(point),
                "destination_ids": [name],
            }
            seats.append(spot_id)
        destinations.append(
            {
                "destination_id": name,
                "subject_id": f"city.street_furniture:{item.item_ordinal}",
                "node_id": name,
                "origin": "furniture",
                "object_id": None,
                "affordances": sorted(use.visitor_affordances),
                "duration_ticks": None,
                "indoors": False,
                "enabled": True,
                "visitor_capacity": len(seats),
                "spot_ids": sorted(seats),
                "use_class": use.key,
                "label": use.label,
                "address_number": None,
                "street_segment_ordinal": item.segment_ordinal,
                "staff_capacity": 0,
                "resident_capacity": 0,
                "role": None,
                "shift": None,
            }
        )
    radius = routine.policy["standing_radius_mm"]
    clearance = min(s.footway_width_mm // 2 for s in segments.values())
    if clearance >= radius:
        for name, point in sorted(nodes.items()):
            if name.startswith("footway:") and point not in spot_positions:
                spot_positions[point] = name
                spots[name] = {
                    "spot_id": name,
                    "node_id": name,
                    "position_mm": list(point),
                    "destination_ids": [],
                }
    else:
        unsupported.add("standing spots (footways are narrower than two standing radii)")
    unknown_uses: dict[str, int] = {}
    for premises in sorted(
        by_type[PremisesRecord], key=lambda r: (r.building_identity, r.unit_ordinal)
    ):
        use = routine.use_classes.get(premises.use_class)
        building = massing.get(premises.building_identity)
        parcel = parcels.get(building.parcel_ordinal) if building else None
        if use is None or use.kind == "furniture":
            unknown_uses[premises.use_class] = unknown_uses.get(premises.use_class, 0) + 1
            continue
        if parcel is None or parcel.parcel_ordinal not in access:
            unsupported.add(
                f"premises of building {premises.building_identity} with no parcel frontage"
            )
            continue
        destination_id = f"premises:{premises.building_identity}:{premises.unit_ordinal}"
        destinations.append(
            {
                "destination_id": destination_id,
                "subject_id": f"city.premises:{premises.building_identity}:{premises.unit_ordinal}",
                "node_id": alias[access[parcel.parcel_ordinal]],
                "origin": "premises",
                "object_id": None,
                "affordances": sorted(use.visitor_affordances),
                "duration_ticks": None,
                "indoors": True,
                "enabled": True,
                "visitor_capacity": use.visitor_capacity,
                "spot_ids": [],
                "use_class": use.key,
                "label": use.label,
                "address_number": parcel.address_number,
                "street_segment_ordinal": parcel.frontage_segment_ordinal,
                "staff_capacity": use.staff_per_unit,
                "resident_capacity": use.resident_capacity,
                "role": {"key": use.role_key, "label": use.role_label},
                "shift": {"start_minute": use.shift_start, "minutes": use.shift_minutes}
                if use.kind == "workplace"
                else None,
            }
        )
    for key, count in sorted(unknown_uses.items()):
        unsupported.add(f"premises use class {key} ({count} units) has no routine mapping")
    # The record set's digest is independent of the order records were handed over.
    records_digest = sha256_of_canonical(
        sorted(
            [type(r).RECORD_KIND, canonical_record(r).decode("utf-8")]
            for kind in _VALIDATORS
            for r in by_type[kind]
        )
    ).hex()
    for spot in spots.values():
        spot["destination_ids"] = sorted(spot["destination_ids"])
    place = {
        "profile": PLACE_PROFILE,
        "place_id": place_id,
        "source": {
            "kind": "city-records",
            "profile": CITY_RECORDS_PROFILE,
            "input_seq": input_seq,
            "document_sha256": records_digest,
        },
        "frame": {
            "name": "city-grammar-mm",
            "axis_order": ["x", "y"],
            "horizontal_unit": "millimetre",
        },
        "routine_sha256": routine.sha256,
        "clearance_mm": clearance,
        "nodes": [
            {"node_id": name, "position_mm": list(point), "street_id": _street(name)}
            for name, point in sorted(nodes.items())
        ],
        "edges": sorted(edges.values(), key=lambda e: e["edge_id"]),
        "spots": [spots[k] for k in sorted(spots)],
        "crossings": sorted(crossings, key=lambda c: c["crossing_id"]),
        "destinations": sorted(destinations, key=lambda d: d["destination_id"]),
        "unavailable_destinations": [],
        "unsupported": sorted(unsupported),
        "availability": "available",
        "unavailable_reason": None,
    }
    return seal_place(place)


def _ordinal(record: StreetSegmentRecord) -> int:
    return record.segment_ordinal


def _street(name: str) -> str | None:
    if name.startswith("footway:"):
        return f"segment:{name.split(':')[1]}"
    return None
