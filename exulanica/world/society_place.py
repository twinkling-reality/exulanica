"""The place contract: what a place hands its society, independent of where the place came from.

A place hands the society ``exulanica.society-place/v1``: a navigation graph in integer
millimetres, the spots where one person can stand, the destinations with their affordances and
capacities, the roles and homes its premises support, and what it cannot supply. Two producers
exist. :func:`place_from_society_input` projects the persisted Flatiron society input exactly as
it is, and ``exulanica.world.society_city_place`` derives a place from the city grammar's
records. The society never reads either source directly, so a third producer (a district v2,
a traffic-aware corridor) only has to publish this document.

Nothing here invents a destination, a path or a job. A place that lacks something says so in
``unsupported``, and a population is sized to what the place can hold.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any, Final

from exulanica.world.society import society_state_sha256
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_planner import validate_society_input

__all__ = [
    "PLACE_PROFILE",
    "ceil_distance",
    "place_capacity",
    "place_from_society_input",
    "place_sha256",
    "seal_place",
    "validate_place",
]

PLACE_PROFILE: Final = "exulanica.society-place/v1"
EDGE_KINDS: Final = ("crossing", "footway", "furniture_access", "premises_access", "sidewalk")
ORIGINS: Final = ("authored", "district", "furniture", "premises")
_FIELDS: Final = frozenset(
    {
        "profile",
        "place_id",
        "source",
        "frame",
        "routine_sha256",
        "clearance_mm",
        "nodes",
        "edges",
        "spots",
        "crossings",
        "destinations",
        "unavailable_destinations",
        "unsupported",
        "availability",
        "unavailable_reason",
        "document_sha256",
    }
)
_DESTINATION_FIELDS: Final = frozenset(
    {
        "destination_id",
        "subject_id",
        "node_id",
        "origin",
        "object_id",
        "affordances",
        "duration_ticks",
        "indoors",
        "enabled",
        "visitor_capacity",
        "spot_ids",
        "use_class",
        "label",
        "address_number",
        "street_segment_ordinal",
        "staff_capacity",
        "resident_capacity",
        "role",
        "shift",
    }
)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def ceil_distance(a: Iterable[int], b: Iterable[int]) -> int:
    squared = sum((x - y) ** 2 for x, y in zip(a, b, strict=True))
    root = math.isqrt(squared)
    return root + (root * root < squared)


def place_sha256(document: dict[str, Any]) -> str:
    return society_state_sha256({k: v for k, v in document.items() if k != "document_sha256"})


def seal_place(document: dict[str, Any]) -> dict[str, Any]:
    document["document_sha256"] = place_sha256(document)
    return document


def _int(value: Any, minimum: int = -(10**9), maximum: int = 10**9) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _text(value: Any) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 1000


def _point(value: Any) -> bool:
    return isinstance(value, list) and len(value) == 2 and all(_int(v) for v in value)


def _sorted_unique(values: list[str], message: str) -> None:
    _require(values == sorted(set(values)), message)


def validate_place(document: dict[str, Any], routine: RoutineModel) -> None:
    """Refuse any place the society could not use exactly as written."""
    try:
        _validate_place(document, routine)
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("malformed society place") from exc


def _validate_place(document: dict[str, Any], routine: RoutineModel) -> None:
    _require(isinstance(document, dict) and set(document) == _FIELDS, "invalid place fields")
    _require(document["profile"] == PLACE_PROFILE, "unsupported place profile")
    _require(_text(document["place_id"]), "invalid place identity")
    source = document["source"]
    _require(
        set(source) == {"kind", "profile", "input_seq", "document_sha256"}
        and _text(source["kind"])
        and _text(source["profile"])
        and _int(source["input_seq"], 1, 2**53 - 1)
        and isinstance(source["document_sha256"], str)
        and len(source["document_sha256"]) == 64,
        "invalid place source binding",
    )
    frame = document["frame"]
    _require(
        set(frame) == {"name", "axis_order", "horizontal_unit"}
        and _text(frame["name"])
        and frame["horizontal_unit"] == "millimetre"
        and isinstance(frame["axis_order"], list)
        and len(frame["axis_order"]) == 2,
        "invalid place frame",
    )
    _require(document["routine_sha256"] == routine.sha256, "place built under another routine")
    _require(_int(document["clearance_mm"], 0, 100_000), "invalid clearance")
    _require(document["availability"] in ("available", "unavailable"), "invalid availability")
    _require(
        (document["availability"] == "available") == (document["unavailable_reason"] is None)
        and (document["unavailable_reason"] is None or _text(document["unavailable_reason"])),
        "availability requires an explicit reason",
    )
    nodes = {}
    for node in document["nodes"]:
        _require(
            set(node) == {"node_id", "position_mm", "street_id"}
            and _text(node["node_id"])
            and _point(node["position_mm"])
            and (node["street_id"] is None or _text(node["street_id"])),
            "invalid place node",
        )
        nodes[node["node_id"]] = node
    _sorted_unique([n["node_id"] for n in document["nodes"]], "nodes must be sorted and unique")
    _require(len(nodes) <= 65_536, "node bound exceeded")
    pairs = set()
    for edge in document["edges"]:
        _require(
            set(edge) == {"edge_id", "from_node_id", "to_node_id", "length_mm", "kind"}
            and _text(edge["edge_id"])
            and edge["kind"] in EDGE_KINDS,
            "invalid place edge",
        )
        a, b = edge["from_node_id"], edge["to_node_id"]
        _require(a in nodes and b in nodes and a != b, "unknown edge endpoint")
        pair = tuple(sorted((a, b)))
        _require(pair not in pairs, "duplicate edge pair")
        pairs.add(pair)
        _require(
            _int(edge["length_mm"], 1, 2**53 - 1)
            and edge["length_mm"]
            == ceil_distance(nodes[a]["position_mm"], nodes[b]["position_mm"]),
            "edge length must be ceil Euclidean distance",
        )
    _sorted_unique([e["edge_id"] for e in document["edges"]], "edges must be sorted and unique")
    _require(len(pairs) <= 262_144, "edge bound exceeded")
    edge_ids = {e["edge_id"]: e for e in document["edges"]}
    for crossing in document["crossings"]:
        _require(
            set(crossing)
            == {"crossing_id", "edge_id", "street_segment_ordinal", "offset_mm", "signal_id"}
            and _text(crossing["crossing_id"])
            and (crossing["signal_id"] is None or _text(crossing["signal_id"]))
            and crossing["edge_id"] in edge_ids
            and edge_ids[crossing["edge_id"]]["kind"] == "crossing"
            and _int(crossing["street_segment_ordinal"], 0)
            and _int(crossing["offset_mm"], 0),
            "invalid crossing",
        )
    _sorted_unique(
        [c["crossing_id"] for c in document["crossings"]], "crossings must be sorted and unique"
    )
    _require(
        sorted(c["edge_id"] for c in document["crossings"])
        == sorted(e["edge_id"] for e in document["edges"] if e["kind"] == "crossing"),
        "every crossing edge is exactly one declared crossing",
    )
    spots = {}
    positions = set()
    for spot in document["spots"]:
        _require(
            set(spot) == {"spot_id", "node_id", "position_mm", "destination_ids"}
            and _text(spot["spot_id"])
            and spot["node_id"] in nodes
            and _point(spot["position_mm"]),
            "invalid spot",
        )
        key = tuple(spot["position_mm"])
        _require(key not in positions, "two spots share a position")
        positions.add(key)
        _require(
            ceil_distance(spot["position_mm"], nodes[spot["node_id"]]["position_mm"])
            <= document["clearance_mm"] + 4 * routine.policy["standing_spacing_mm"],
            "a spot lies within four standing spacings of its cleared access node",
        )
        spots[spot["spot_id"]] = spot
    _sorted_unique([s["spot_id"] for s in document["spots"]], "spots must be sorted and unique")
    destinations = set()
    affordances = {a.affordance for a in routine.activities.values()}
    for dest in document["destinations"]:
        _require(set(dest) == _DESTINATION_FIELDS, "invalid destination fields")
        _require(
            _text(dest["destination_id"])
            and _text(dest["subject_id"])
            and dest["node_id"] in nodes
            and dest["origin"] in ORIGINS
            and (dest["object_id"] is None or _text(dest["object_id"]))
            and type(dest["indoors"]) is bool
            and type(dest["enabled"]) is bool,
            "invalid destination",
        )
        _require(
            isinstance(dest["affordances"], list)
            and dest["affordances"] == sorted(set(dest["affordances"]))
            and set(dest["affordances"]) <= affordances,
            "destination affordances must be sorted and known to the routine",
        )
        _require(
            dest["duration_ticks"] is None or _int(dest["duration_ticks"], 1, 1440),
            "invalid reviewed duration",
        )
        for key in ("visitor_capacity", "staff_capacity", "resident_capacity"):
            _require(_int(dest[key], 0, 4096), f"invalid {key}")
        _require(
            isinstance(dest["spot_ids"], list)
            and dest["spot_ids"] == sorted(set(dest["spot_ids"]))
            and all(
                s in spots and dest["destination_id"] in spots[s]["destination_ids"]
                for s in dest["spot_ids"]
            ),
            "destination spots must be sorted and point back",
        )
        _require(
            dest["indoors"] or dest["visitor_capacity"] == len(dest["spot_ids"]),
            "an outdoor destination holds exactly one visitor per spot",
        )
        _require(not dest["indoors"] or not dest["spot_ids"], "an indoor destination has no spots")
        _require(
            dest["use_class"] is None or dest["use_class"] in routine.use_classes,
            "unknown use class",
        )
        _require(
            dest["role"] is None
            or (set(dest["role"]) == {"key", "label"} and _text(dest["role"]["label"])),
            "invalid destination role",
        )
        _require(
            (dest["staff_capacity"] > 0) == (dest["shift"] is not None),
            "exactly the staffed destinations declare a shift",
        )
        _require(
            dest["shift"] is None
            or (
                set(dest["shift"]) == {"start_minute", "minutes"}
                and _int(dest["shift"]["start_minute"], 0, 1439)
                and _int(dest["shift"]["minutes"], 1, 1440)
            ),
            "invalid shift",
        )
        _require(
            dest["address_number"] is None or _int(dest["address_number"], 1),
            "invalid address number",
        )
        _require(
            dest["street_segment_ordinal"] is None or _int(dest["street_segment_ordinal"], 0),
            "invalid frontage street segment",
        )
        _require(dest["label"] is None or _text(dest["label"]), "invalid destination label")
        destinations.add(dest["destination_id"])
    _sorted_unique(
        [d["destination_id"] for d in document["destinations"]],
        "destinations must be sorted and unique",
    )
    for spot in spots.values():
        _require(
            spot["destination_ids"] == sorted(set(spot["destination_ids"]))
            and set(spot["destination_ids"]) <= destinations,
            "spot names an unknown destination",
        )
    unavailable = document["unavailable_destinations"]
    for row in unavailable:
        _require(
            set(row) == {"destination_id", "reason"}
            and _text(row["destination_id"])
            and _text(row["reason"])
            and row["destination_id"] not in destinations,
            "invalid unavailable destination",
        )
    _sorted_unique([r["destination_id"] for r in unavailable], "unavailable must be sorted")
    _require(
        isinstance(document["unsupported"], list)
        and all(_text(v) for v in document["unsupported"]),
        "invalid unsupported list",
    )
    _sorted_unique(document["unsupported"], "unsupported must be sorted and unique")
    _require(place_sha256(document) == document["document_sha256"], "place digest mismatch")


def place_capacity(document: dict[str, Any]) -> int:
    """How many people the place holds at once: spots, indoor visitor places and home places."""
    indoor = sum(
        d["visitor_capacity"] + d["resident_capacity"]
        for d in document["destinations"]
        if d["enabled"] and d["indoors"]
    )
    return len(document["spots"]) + indoor


def place_from_society_input(document: dict[str, Any], routine: RoutineModel) -> dict[str, Any]:
    """Project a validated society input as it is: its graph, its targets and nothing else.

    Every node is one standing spot when the published clearance fits a standing person. A
    district or authored target publishes only an access node, so its one visitor stands on that
    node's spot. The input has no premises, homes, workplaces or street names, and says so.
    """
    validate_society_input(document)
    nav = document["navigation"]
    radius = routine.policy["standing_radius_mm"]
    standing = routine.capacities["standing_node"]
    fits = standing.rule == "node_clearance" and nav["clearance_mm"] >= radius
    positions = {n["node_id"]: n["position_mm"] for n in nav["nodes"]}
    nodes = [
        {"node_id": n["node_id"], "position_mm": list(n["position_mm"]), "street_id": None}
        for n in nav["nodes"]
    ]
    edges = [
        {
            "edge_id": e["edge_id"],
            "from_node_id": e["from_node_id"],
            "to_node_id": e["to_node_id"],
            "length_mm": e["length_mm"],
            "kind": "sidewalk",
        }
        for e in nav["edges"]
    ]
    usable = [t for t in document["targets"] if t["node_id"] in positions]
    at_node: dict[str, list[str]] = {}
    for target in usable:
        if target["enabled"]:
            at_node.setdefault(target["node_id"], []).append(target["target_id"])
    spots = []
    if fits:
        for node in nav["nodes"]:
            spots.append(
                {
                    "spot_id": node["node_id"],
                    "node_id": node["node_id"],
                    "position_mm": list(node["position_mm"]),
                    "destination_ids": sorted(at_node.get(node["node_id"], [])),
                }
            )
    destinations = []
    for target in usable:
        rule = routine.capacities[
            "district_target" if target["origin"] == "district" else "authored_object"
        ]
        spot_ids = [target["node_id"]] if fits and target["enabled"] else []
        destinations.append(
            {
                "destination_id": target["target_id"],
                "subject_id": target["subject_id"],
                "node_id": target["node_id"],
                "origin": target["origin"],
                "object_id": target["object_id"],
                "affordances": [target["affordance"]],
                "duration_ticks": target["duration_ticks"],
                "indoors": False,
                "enabled": target["enabled"],
                "visitor_capacity": min(rule.capacity, len(spot_ids)),
                "spot_ids": spot_ids[: rule.capacity],
                "use_class": None,
                "label": None,
                "address_number": None,
                "street_segment_ordinal": None,
                "staff_capacity": 0,
                "resident_capacity": 0,
                "role": None,
                "shift": None,
            }
        )
    unsupported = {
        "homes (the society input publishes no dwellings)",
        "premises, roles and workplaces (the society input publishes no premises records)",
        "street names (the society input publishes none)",
        "street segments and carriageway crossings (the society input publishes neither)",
    }
    unsupported.update(
        f"district interpretation: {reason}" for reason in _interpretation_gaps(document)
    )
    if not fits:
        unsupported.add("standing spots (navigation clearance is below the standing radius)")
    unavailable = [
        {"destination_id": row["target_id"], "reason": row["reason"]}
        for row in document.get("unavailable_affordances", [])
    ]
    unavailable += [
        {"destination_id": t["target_id"], "reason": "access_node_not_in_graph"}
        for t in document["targets"]
        if t["node_id"] not in positions and t["enabled"]
    ]
    reason = document["unavailable_reason"] or nav["unavailable_reason"]
    place = {
        "profile": PLACE_PROFILE,
        "place_id": document["district_id"],
        "source": {
            "kind": "society-input",
            "profile": document["profile"],
            "input_seq": document["input_seq"],
            "document_sha256": document["document_sha256"],
        },
        "frame": {
            "name": document["frame"]["name"],
            "axis_order": list(document["frame"]["axis_order"]),
            "horizontal_unit": "millimetre",
        },
        "routine_sha256": routine.sha256,
        "clearance_mm": nav["clearance_mm"],
        "nodes": nodes,
        "edges": edges,
        "spots": spots,
        "crossings": [],
        "destinations": destinations,
        "unavailable_destinations": sorted(unavailable, key=lambda r: r["destination_id"]),
        "unsupported": sorted(unsupported),
        "availability": "available"
        if document["availability"] == "available" and reason is None
        else "unavailable",
        "unavailable_reason": None
        if document["availability"] == "available" and reason is None
        else reason or "input_unavailable",
    }
    return seal_place(place)


def _interpretation_gaps(document: dict[str, Any]) -> list[str]:
    """The input carries no interpretation text; the graph's own extent is the measurable gap."""
    nodes = document["navigation"]["nodes"]
    if not nodes:
        return ["no navigation graph"]
    xs = [n["position_mm"][0] for n in nodes]
    zs = [n["position_mm"][1] for n in nodes]
    return [
        f"walkable graph spans {max(xs) - min(xs)} mm by {max(zs) - min(zs)} mm "
        f"({len(nodes)} nodes); routes outside it are not published"
    ]
