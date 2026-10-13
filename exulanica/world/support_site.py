"""Admit support authoring against real generated site geometry and preserve its base activities."""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.grammar.grammars.site.records import SiteExtentRecord, SiteFixtureRecord
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import seal_place, validate_place
from exulanica.world.support_place import SupportProjection, project_support_place, qualified_node
from exulanica.world.support_surfaces import (
    PROFILE,
    SupportNetwork,
    SupportRefused,
    _clear,
    _identity,
    _keys,
    _require,
    _rows,
    read_support_network,
    seal_support_network,
)

AUTHORING_PROFILE = "exulanica.support-authoring/v1"
BINDING_PROFILE = "exulanica.site-support/v1"
BASE_SURFACE = "base-ground"
ENTRY_NODE = "source-entry"


def _entry(place: Mapping[str, Any]) -> Mapping[str, Any]:
    # Entry is a canonical port of the site producer, not a scene/entity-name branch.
    return next(n for n in place["nodes"] if n["node_id"] == "entry")


def _source(world_id: str, place: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "world_id": world_id,
        "geometry_profile": place["source"]["profile"],
        "geometry_sha256": place["source"]["document_sha256"],
    }


def _base_surface(records: Sequence[object]) -> dict[str, Any]:
    extent = next(r for r in records if isinstance(r, SiteExtentRecord))
    return {
        "surface_id": BASE_SURFACE,
        "rect_mm": [0, -extent.depth_mm, extent.width_mm, 0],
        "support_z_mm": 0,
    }


def site_solids(drawing: Mapping[str, Any], records: Sequence[object]) -> list[dict[str, Any]]:
    """Canonical wall pieces keep doors open, lintels/roofs carry height, fixtures use their boxes.

    Water/closed-zone keep-outs are exclusion volumes in this bounded attachment; it does not
    claim supported water bridges, underground traversal or fluid-depth reconstruction.
    """
    from exulanica.world.society_site_place import _fixture_box

    values = []
    for slot in drawing["slots"]:
        if slot["primitive"] != "box" or slot["lookRole"].split(".")[0] not in ("wall", "boundary"):
            continue
        x, y, z = slot["positionMm"]
        width, depth, height = slot["boxMm"]
        if slot["yawQuarterTurns"] % 2:
            width, depth = depth, width
        x0, y0 = x - width // 2, y - depth // 2
        values.append([x0, -(y0 + depth), z, x0 + width, -y0, z + height])
    for record in records:
        if isinstance(record, SiteFixtureRecord) and record.blocks:
            rect = _fixture_box(record)
            values.append([rect.x0, -rect.y1, 0, rect.x1, -rect.y0, record.height_mm])
    for rect in drawing["walk"]["keepOutMm"]:
        x0, y0, x1, y1 = rect
        values.append([x0, -y1, 0, x1, -y0, 40000])
    # A roof's lower envelope is conservative headroom; no invented curved-roof collision.
    for slot in drawing["slots"]:
        if slot["lookRole"].split(".")[0] != "roof":
            continue
        x, y, z = slot["positionMm"]
        width, depth, height = slot["boxMm"]
        if slot["yawQuarterTurns"] % 2:
            width, depth = depth, width
        values.append(
            [
                x - width // 2,
                -(y + depth // 2),
                z,
                x - width // 2 + width,
                -(y + depth // 2) + depth,
                z + max(1, height),
            ]
        )
    return [
        {"solid_id": f"source-solid:{index:04d}", "box_mm": box} for index, box in enumerate(values)
    ]


@dataclass(frozen=True, slots=True)
class SiteSupport:
    network: SupportNetwork
    projection: SupportProjection
    bindings: Mapping[str, str]
    declaration: Mapping[str, Any]

    def document(self) -> dict[str, Any]:
        return {
            "profile": BINDING_PROFILE,
            "network": self.network.document(),
            "declaration": copy.deepcopy(dict(self.declaration)),
            "place_sha256": self.projection.place()["document_sha256"],
        }

    def adapter_document(self) -> dict[str, Any]:
        adapter = self.projection.adapter_document()
        adapter["node_surfaces"] = dict(sorted(self.bindings.items()))
        adapter["entry_surface_id"] = BASE_SURFACE
        adapter["entry_node_id"] = qualified_node(
            self.network.document()["network_id"], BASE_SURFACE, "entry"
        )
        return adapter


def _combine(
    network: SupportNetwork,
    base: Mapping[str, Any],
    routine: RoutineModel,
    declaration: Mapping[str, Any],
    source_seat_spots: Mapping[str, str],
) -> tuple[SupportProjection, dict[str, str]]:
    # The network uses region east/south. The carried site place keeps east/north for its
    # existing living-input adapter, which flips north to south exactly once.
    added = project_support_place(
        network,
        routine,
        place_id=base["place_id"],
        destinations=declaration["destinations"],
        spots=declaration["spots"],
    )
    place = added.place()
    raw = network.document()
    base_nodes = {n["node_id"]: n for n in base["nodes"]}
    kept = {}
    for key, node in base_nodes.items():
        p = (node["position_mm"][0], -node["position_mm"][1])
        try:
            network.support_at(BASE_SURFACE, p)
        except SupportRefused:
            continue
        kept[key] = {
            **node,
            "node_id": qualified_node(raw["network_id"], BASE_SURFACE, key),
            "position_mm": list(p),
        }
    entry = _entry(base)["node_id"]
    _require(entry in kept, "entry", "the actual source entry remains supported")
    aliases = {qualified_node(raw["network_id"], BASE_SURFACE, ENTRY_NODE): kept[entry]["node_id"]}
    merged = {n["node_id"]: n for n in kept.values()}
    for node in place["nodes"]:
        if node["node_id"] not in aliases:
            merged[node["node_id"]] = node
    edges = []
    for edge in base["edges"]:
        a, b = edge["from_node_id"], edge["to_node_id"]
        if a not in kept or b not in kept:
            continue
        try:
            network.motion_on_surface(
                BASE_SURFACE, tuple(kept[a]["position_mm"]), tuple(kept[b]["position_mm"])
            )
        except SupportRefused:
            continue
        edges.append({**edge, "from_node_id": kept[a]["node_id"], "to_node_id": kept[b]["node_id"]})
    for edge in place["edges"]:
        edges.append(
            {
                **edge,
                "from_node_id": aliases.get(edge["from_node_id"], edge["from_node_id"]),
                "to_node_id": aliases.get(edge["to_node_id"], edge["to_node_id"]),
            }
        )
    targets = []
    for target in base["destinations"]:
        _require(target["node_id"] in kept, "destinations", "a source destination lost support")
        targets.append({**target, "node_id": kept[target["node_id"]]["node_id"]})
    targets.extend(
        {**t, "node_id": aliases.get(t["node_id"], t["node_id"])} for t in place["destinations"]
    )
    spots = []
    for spot in base["spots"]:
        if spot["node_id"] not in kept:
            _require(not spot["destination_ids"], "spots", "a source activity spot lost support")
            continue
        # Source seat spots retain the admitted producer's posture semantics: its renderer
        # raises seated bodies separately. Check newly added support ceilings without
        # reclassifying inherited seated spots as standing cylinders inside their benches.
        position = (spot["position_mm"][0], -spot["position_mm"][1])
        legacy_seat = (
            spot["spot_id"] in source_seat_spots
            and base["source"]["profile"] == "exulanica.site-records/v1"
            and raw["actor"]["radius_mm"] == 340
            and raw["actor"]["height_mm"] == 1800
        )
        if legacy_seat:
            radius = raw["actor"]["radius_mm"]
            x, y = position
            _clear(
                raw,
                (x - radius, y - radius, x + radius, y + radius),
                0,
                0,
                ignore_solids=frozenset({source_seat_spots[spot["spot_id"]]}),
            )
        else:
            network.support_at(BASE_SURFACE, position)
        spots.append(
            {
                **spot,
                "node_id": kept[spot["node_id"]]["node_id"],
                "position_mm": [spot["position_mm"][0], -spot["position_mm"][1]],
            }
        )
    spots.extend({**s, "node_id": aliases.get(s["node_id"], s["node_id"])} for s in place["spots"])
    neighbours = {key: set() for key in merged}
    for edge in edges:
        neighbours[edge["from_node_id"]].add(edge["to_node_id"])
        neighbours[edge["to_node_id"]].add(edge["from_node_id"])
    reachable = set()
    waiting = [kept[entry]["node_id"]]
    while waiting:
        n = waiting.pop()
        if n not in reachable:
            reachable.add(n)
            waiting.extend(neighbours[n])
    _require(
        all(not t["enabled"] or t["node_id"] in reachable for t in targets),
        "destinations",
        "all enabled source and added destinations remain reachable",
    )
    _require(len(merged) <= 962, "nodes", "combined site graph stays within its published budget")
    bindings = {key: BASE_SURFACE for key in (n["node_id"] for n in kept.values())}
    bindings.update(
        {
            key: surface
            for key, surface in added.adapter_document()["node_surfaces"].items()
            if key not in aliases
        }
    )
    # Retain the existing site-local orientation, including real support heights.
    place.update(
        frame=copy.deepcopy(base["frame"]),
        nodes=sorted(
            [
                {**n, "position_mm": [n["position_mm"][0], -n["position_mm"][1]]}
                for n in merged.values()
            ],
            key=lambda n: n["node_id"],
        ),
        edges=sorted(edges, key=lambda e: e["edge_id"]),
        destinations=sorted(targets, key=lambda t: t["destination_id"]),
        spots=sorted(
            [{**s, "position_mm": [s["position_mm"][0], -s["position_mm"][1]]} for s in spots],
            key=lambda s: s["spot_id"],
        ),
        unsupported=sorted(set(base["unsupported"]) | set(place["unsupported"])),
    )
    if "words" in base:
        place["words"] = dict(base["words"])
    seal_place(place)
    validate_place(place, routine)
    return SupportProjection(canonical_json(place), network), bindings


def attach_site_support(
    authoring: Mapping[str, Any],
    *,
    world_id: str,
    records: Sequence[object],
    drawing: Mapping[str, Any],
    base_place: Mapping[str, Any],
    routine: RoutineModel,
) -> SiteSupport:
    raw = copy.deepcopy(dict(authoring))
    _keys(raw, "profile network_id actor surfaces nodes connections destinations spots", "support")
    _require(raw["profile"] == AUTHORING_PROFILE, "support.profile", f"is {AUTHORING_PROFILE}")
    _require(type(raw["spots"]) is dict, "support.spots", "is a standing-node map")
    _rows(raw["destinations"], 48, "support.destinations")
    base = _base_surface(records)
    extent = base["rect_mm"]
    surfaces = _rows(raw["surfaces"], 31, "support.surfaces")
    for surface in surfaces:
        _require(
            type(surface) is dict and surface.get("surface_id") != BASE_SURFACE,
            "support.surfaces",
            "base-ground is source-owned",
        )
        _identity(surface.get("surface_id"), "support.surfaces.surface_id")
        rect = surface.get("rect_mm")
        _require(
            type(rect) is list and len(rect) == 4 and all(type(v) is int for v in rect),
            "support.surfaces",
            "states whole-mm rectangles",
        )
        _require(
            extent[0] <= rect[0] < rect[2] <= extent[2]
            and extent[1] <= rect[1] < rect[3] <= extent[3],
            "support.surfaces",
            "lies within the actual site",
        )
    nodes = copy.deepcopy(_rows(raw["nodes"], 511, "support.nodes"))
    _require(
        all(type(n) is dict and n.get("node_id") != ENTRY_NODE for n in nodes),
        "support.nodes",
        "source-entry is source-owned",
    )
    for node in nodes:
        _identity(node.get("node_id"), "support.nodes.node_id")
    entry = _entry(base_place)
    nodes.append(
        {
            "node_id": ENTRY_NODE,
            "surface_id": BASE_SURFACE,
            "position_mm": [entry["position_mm"][0], -entry["position_mm"][1]],
        }
    )
    network = seal_support_network(
        {
            "profile": PROFILE,
            "network_id": raw["network_id"],
            "source": _source(world_id, base_place),
            "frame": {
                "name": "region:generated",
                "axis_order": ["east", "south"],
                "horizontal_unit": "millimetre",
                "vertical_unit": "millimetre",
                "datum": "region-origin",
            },
            "actor": raw["actor"],
            "surfaces": sorted([base, *surfaces], key=lambda s: s["surface_id"]),
            "solids": site_solids(drawing, records),
            "nodes": sorted(nodes, key=lambda n: n["node_id"]),
            "connections": raw["connections"],
            "entry_node_id": ENTRY_NODE,
        }
    )
    from exulanica.world.society_site_place import _fixture_box

    source_seat_spots = {}
    for record in records:
        if not isinstance(record, SiteFixtureRecord) or "seat" not in record.roles:
            continue
        rect = _fixture_box(record)
        box = [rect.x0, -rect.y1, 0, rect.x1, -rect.y0, record.height_mm]
        matches = [s["solid_id"] for s in network.document()["solids"] if s["box_mm"] == box]
        if record.blocks and len(matches) == 1:
            for index in range(record.seats):
                source_seat_spots[f"fixture:{record.identity}:seat:{index}"] = matches[0]
    projection, bindings = _combine(network, base_place, routine, raw, source_seat_spots)
    return SiteSupport(network, projection, bindings, raw)


def read_site_support(binding: Any, **context: Any) -> SiteSupport:
    raw = _keys(binding, "profile network declaration place_sha256", "supports")
    _require(raw["profile"] == BINDING_PROFILE, "supports.profile", f"is {BINDING_PROFILE}")
    replay = attach_site_support(raw["declaration"], **context)
    _require(
        replay.document() == raw, "supports", "matches actual regenerated geometry and projection"
    )
    read_support_network(raw["network"], source=_source(context["world_id"], context["base_place"]))
    return replay
