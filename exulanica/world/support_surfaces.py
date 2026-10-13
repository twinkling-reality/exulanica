"""Canonical horizontal supports and explicit connections, independent of rendered meshes."""

from __future__ import annotations

import json
import re
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.world.society_place import STEP_LIMIT_MM

PROFILE: Final = "exulanica.support-network/v1"
# Bounded authoring inputs: matching site record coordinate precision, with bounded sweep work.
_COORDINATE: Final = 10_000_000
_ID: Final = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_:./-]{0,159}")
_SHA: Final = re.compile(r"[0-9a-f]{64}")


class SupportRefused(ValueError):
    """A support declaration or traversal cannot be used as stated."""

    code = "support_network_invalid"

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"{self.code}: {where}: {detail}")
        self.where, self.detail = where, detail


def _require(condition: bool, where: str, detail: str) -> None:
    if not condition:
        raise SupportRefused(where, detail)


def _keys(raw: Any, fields: str, where: str) -> dict[str, Any]:
    _require(
        type(raw) is dict and set(raw) == set(fields.split()), where, f"states exactly {fields}"
    )
    return raw


def _integer(raw: Any, low: int, high: int, where: str) -> int:
    _require(type(raw) is int and low <= raw <= high, where, f"is an integer from {low} to {high}")
    return raw


def _identity(raw: Any, where: str) -> str:
    _require(type(raw) is str and _ID.fullmatch(raw) is not None, where, "is a bounded identity")
    return raw


def _rows(raw: Any, maximum: int, where: str, *, minimum: int = 0) -> list[Any]:
    _require(type(raw) is list and minimum <= len(raw) <= maximum, where, "has a bounded list")
    return raw


def _figures(raw: Any, count: int, where: str) -> tuple[int, ...]:
    _rows(raw, count, where, minimum=count)
    return tuple(_integer(v, -_COORDINATE, _COORDINATE, where) for v in raw)


def _rectangle(raw: Any, where: str) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = _figures(raw, 4, where)
    _require(x0 < x1 and y0 < y1, where, "has positive width and depth")
    return x0, y0, x1, y1


def _indexed(rows: list[Any], key: str, where: str) -> dict[str, dict[str, Any]]:
    found = {}
    for index, row in enumerate(rows):
        _require(type(row) is dict, where, "contains only objects")
        identity = _identity(row.get(key), f"{where}[{index}].{key}")
        _require(identity not in found, where, "does not repeat identities")
        found[identity] = row
    _require(list(found) == sorted(found), where, "is sorted by identity")
    return found


def _overlaps(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _covered(rect: tuple[int, ...], supports: list[tuple[int, ...]]) -> bool:
    """Exact rectangle-union cover, conservatively covering a circular swept footprint."""
    x0, y0, x1, y1 = rect
    cuts = sorted({x0, x1, *(x for r in supports for x in (r[0], r[2]) if x0 < x < x1)})
    for left, right in pairwise(cuts):
        intervals = sorted((r[1], r[3]) for r in supports if r[0] <= left and right <= r[2])
        reached = y0
        for low, high in intervals:
            if low > reached:
                break
            reached = max(reached, high)
        if reached < y1:
            return False
    return True


@dataclass(frozen=True, slots=True)
class SupportNetwork:
    """An admitted immutable document; derived views cannot mutate its authority."""

    encoded: bytes
    sha256: str

    def document(self) -> dict[str, Any]:
        return json.loads(self.encoded)

    def support_at(self, surface_id: str, position_mm: tuple[int, int]) -> int:
        """Query one named surface, including the recorded actor's whole footprint and headroom."""
        document = self.document()
        surfaces = {s["surface_id"]: s for s in document["surfaces"]}
        _require(
            type(surface_id) is str and surface_id in surfaces,
            "surface_id",
            "names an admitted surface",
        )
        _require(type(position_mm) in (tuple, list), "position_mm", "is a plan point")
        point = _figures(list(position_mm), 2, "position_mm")
        surface = surfaces[surface_id]
        radius = document["actor"]["radius_mm"]
        rect = (point[0] - radius, point[1] - radius, point[0] + radius, point[1] + radius)
        _require(
            _covered(rect, [tuple(surface["rect_mm"])]),
            "position_mm",
            "whole footprint is supported",
        )
        _clear(document, rect, surface["support_z_mm"], surface["support_z_mm"])
        return int(surface["support_z_mm"])

    def reachable(self) -> frozenset[str]:
        document = self.document()
        neighbours: dict[str, list[str]] = {n["node_id"]: [] for n in document["nodes"]}
        for edge in document["connections"]:
            a, b = edge["from_node_id"], edge["to_node_id"]
            neighbours[a].append(b)
            neighbours[b].append(a)
        reached, queue = set(), deque([document["entry_node_id"]])
        while queue:
            node = queue.popleft()
            if node not in reached:
                reached.add(node)
                queue.extend(neighbours[node])
        return frozenset(reached)

    def motion_on_surface(
        self, surface_id: str, start_mm: tuple[int, int], end_mm: tuple[int, int]
    ) -> int:
        """Validate free motion on one flat support, conservatively sweeping the whole footprint."""
        height = self.support_at(surface_id, start_mm)
        self.support_at(surface_id, end_mm)
        document = self.document()
        radius = document["actor"]["radius_mm"]
        swept = (
            min(start_mm[0], end_mm[0]) - radius,
            min(start_mm[1], end_mm[1]) - radius,
            max(start_mm[0], end_mm[0]) + radius,
            max(start_mm[1], end_mm[1]) + radius,
        )
        _clear(document, swept, height, height)
        return height

    def connection_at(
        self, connection_id: str, from_surface_id: str, position_mm: tuple[int, int]
    ) -> tuple[str, int]:
        """Resolve a pose inside an explicit connection, never choosing a level by XY proximity.

        The connection's endpoints bound its travel axis. Its transverse portal uses only the
        two supports' shared width, with full actor coverage and solid clearance checked at
        the query. The caller keeps the connection active while the footprint straddles a step.
        """
        document = self.document()
        edges = {e["connection_id"]: e for e in document["connections"]}
        _require(
            type(connection_id) is str and connection_id in edges,
            "connection_id",
            "names an admitted connection",
        )
        nodes = {n["node_id"]: n for n in document["nodes"]}
        surfaces = {s["surface_id"]: s for s in document["surfaces"]}
        edge = edges[connection_id]
        a, b = nodes[edge["from_node_id"]], nodes[edge["to_node_id"]]
        _require(
            from_surface_id in (a["surface_id"], b["surface_id"]),
            "from_surface_id",
            "is an endpoint's current surface",
        )
        _require(type(position_mm) in (tuple, list), "position_mm", "is a plan point")
        x, y = _figures(list(position_mm), 2, "position_mm")
        axis = 0 if a["position_mm"][0] != b["position_mm"][0] else 1
        _require(
            min(a["position_mm"][axis], b["position_mm"][axis])
            <= (x, y)[axis]
            <= max(a["position_mm"][axis], b["position_mm"][axis]),
            "position_mm",
            "lies inside the explicit connection's travel span",
        )
        sa, sb = surfaces[a["surface_id"]], surfaces[b["surface_id"]]
        transverse = 1 - axis
        radius = document["actor"]["radius_mm"]
        _require(
            max(sa["rect_mm"][transverse], sb["rect_mm"][transverse]) + radius
            <= (x, y)[transverse]
            <= min(sa["rect_mm"][transverse + 2], sb["rect_mm"][transverse + 2]) - radius,
            "position_mm",
            "whole footprint fits the shared portal width",
        )
        footprint = (x - radius, y - radius, x + radius, y + radius)
        _require(
            _covered(footprint, [tuple(sa["rect_mm"]), tuple(sb["rect_mm"])]),
            "position_mm",
            "the straddling footprint has continuous support",
        )
        _clear(
            document,
            footprint,
            min(sa["support_z_mm"], sb["support_z_mm"]),
            max(sa["support_z_mm"], sb["support_z_mm"]),
            ignore_surfaces=frozenset({sa["surface_id"], sb["surface_id"]}),
        )
        current = surfaces[from_surface_id]
        target = sb if sa["surface_id"] == from_surface_id else sa

        def contains(surface: Mapping[str, Any]) -> bool:
            rect = surface["rect_mm"]
            return rect[0] <= x <= rect[2] and rect[1] <= y <= rect[3]

        if (target["support_z_mm"] > current["support_z_mm"] and contains(target)) or not contains(
            current
        ):
            current = target
        return current["surface_id"], current["support_z_mm"]

    def node_surfaces(self) -> dict[str, str]:
        return {n["node_id"]: n["surface_id"] for n in self.document()["nodes"]}


def _clear(
    document: Mapping[str, Any],
    rect: tuple[int, ...],
    low: int,
    high: int,
    *,
    ignore_surfaces: frozenset[str] = frozenset(),
    ignore_solids: frozenset[str] = frozenset(),
) -> None:
    for solid in document["solids"]:
        if solid["solid_id"] in ignore_solids:
            continue
        x0, y0, z0, x1, y1, z1 = solid["box_mm"]
        if (
            _overlaps(rect, (x0, y0, x1, y1))
            and low < z1
            and z0 < high + document["actor"]["height_mm"]
        ):
            raise SupportRefused("solids", "actor footprint/headroom intersects a declared solid")
    _clear_supports(document, rect, low, high, ignore_surfaces=ignore_surfaces)


def _clear_supports(
    document: Mapping[str, Any],
    rect: tuple[int, ...],
    low: int,
    high: int,
    *,
    ignore_surfaces: frozenset[str] = frozenset(),
) -> None:
    """Check support ceilings separately from source posture/solid semantics."""
    for surface in document["surfaces"]:
        if (
            surface["surface_id"] not in ignore_surfaces
            and low < surface["support_z_mm"] < high + document["actor"]["height_mm"]
            and _overlaps(rect, tuple(surface["rect_mm"]))
        ):
            raise SupportRefused("surfaces", "another support intrudes into actor headroom")


def read_support_network(
    document: Any, *, source: Mapping[str, Any] | None = None
) -> SupportNetwork:
    """Read a sealed declaration, optionally requiring its actual caller-held source binding.

    This validates declared geometry. Source completeness must be enforced by its composition
    producer, which reconciles the parent's solids rather than trusting a claimant's digest.
    """
    try:
        encoded = canonical_json(document)
    except (CanonicalisationError, TypeError, ValueError) as exc:
        raise SupportRefused("", "is canonical integer JSON") from exc
    raw = _keys(
        json.loads(encoded),
        "profile network_id source frame actor surfaces solids nodes connections "
        "entry_node_id document_sha256",
        "",
    )
    _require(raw["profile"] == PROFILE, "profile", f"is {PROFILE}")
    _identity(raw["network_id"], "network_id")
    binding = _keys(raw["source"], "world_id geometry_profile geometry_sha256", "source")
    for field in ("world_id", "geometry_profile"):
        _identity(binding[field], f"source.{field}")
    _require(
        type(binding["geometry_sha256"]) is str
        and _SHA.fullmatch(binding["geometry_sha256"]) is not None,
        "source.geometry_sha256",
        "is a lowercase SHA-256",
    )
    _require(
        source is None or dict(source) == binding,
        "source",
        "matches the caller's canonical world geometry",
    )
    frame = _keys(raw["frame"], "name axis_order horizontal_unit vertical_unit datum", "frame")
    for field in ("name", "datum"):
        _identity(frame[field], f"frame.{field}")
    _require(
        frame["axis_order"] == ["east", "south"]
        and frame["horizontal_unit"] == frame["vertical_unit"] == "millimetre",
        "frame",
        "is east/south, millimetres, against its stated vertical datum",
    )
    actor = _keys(raw["actor"], "radius_mm height_mm maximum_step_mm", "actor")
    _integer(actor["radius_mm"], 1, 50_000, "actor.radius_mm")
    _integer(actor["height_mm"], 1, 40_000, "actor.height_mm")
    _integer(actor["maximum_step_mm"], 0, STEP_LIMIT_MM, "actor.maximum_step_mm")
    surfaces = _indexed(_rows(raw["surfaces"], 32, "surfaces", minimum=1), "surface_id", "surfaces")
    for surface in surfaces.values():
        _keys(surface, "surface_id rect_mm support_z_mm", "surfaces")
        _rectangle(surface["rect_mm"], "surfaces.rect_mm")
        _integer(surface["support_z_mm"], -_COORDINATE, _COORDINATE, "surfaces.support_z_mm")
    solids = _indexed(_rows(raw["solids"], 128, "solids"), "solid_id", "solids")
    for solid in solids.values():
        _keys(solid, "solid_id box_mm", "solids")
        x0, y0, z0, x1, y1, z1 = _figures(solid["box_mm"], 6, "solids.box_mm")
        _require(x0 < x1 and y0 < y1 and z0 < z1, "solids.box_mm", "has positive volume")
    nodes = _indexed(_rows(raw["nodes"], 512, "nodes", minimum=1), "node_id", "nodes")
    # Build the temporary admitted shape only after its raw geometry is closed and validated.
    network = SupportNetwork(encoded, "")
    for node in nodes.values():
        _keys(node, "node_id surface_id position_mm", "nodes")
        surface_id = _identity(node["surface_id"], "nodes.surface_id")
        _figures(node["position_mm"], 2, "nodes.position_mm")
        network.support_at(surface_id, tuple(node["position_mm"]))
    _require(
        _identity(raw["entry_node_id"], "entry_node_id") in nodes, "entry_node_id", "names a node"
    )
    connections = _indexed(
        _rows(raw["connections"], 1024, "connections"), "connection_id", "connections"
    )
    pairs = set()
    for edge in connections.values():
        _keys(edge, "connection_id from_node_id to_node_id kind", "connections")
        a, b = (
            _identity(edge[field], f"connections.{field}")
            for field in ("from_node_id", "to_node_id")
        )
        _require(
            a in nodes and b in nodes and a != b, "connections", "names distinct admitted nodes"
        )
        pair = tuple(sorted((a, b)))
        _require(pair not in pairs, "connections", "does not repeat a node pair")
        pairs.add(pair)
        na, nb = nodes[a], nodes[b]
        pa, pb = na["position_mm"], nb["position_mm"]
        _require(
            (pa[0] == pb[0]) != (pa[1] == pb[1]),
            "connections",
            "is a nonzero axis-aligned path, never vertical teleport",
        )
        sa, sb = surfaces[na["surface_id"]], surfaces[nb["surface_id"]]
        za, zb = sa["support_z_mm"], sb["support_z_mm"]
        _require(edge["kind"] in ("walk", "step"), "connections.kind", "is walk or step")
        if edge["kind"] == "walk":
            _require(
                sa["surface_id"] == sb["surface_id"],
                "connections",
                "a walk stays on one named surface",
            )
        else:
            _require(
                sa["surface_id"] != sb["surface_id"] and abs(za - zb) <= actor["maximum_step_mm"],
                "connections",
                "an explicit step joins distinct supports within the actor's rise bound",
            )
        radius = actor["radius_mm"]
        swept = (
            min(pa[0], pb[0]) - radius,
            min(pa[1], pb[1]) - radius,
            max(pa[0], pb[0]) + radius,
            max(pa[1], pb[1]) + radius,
        )
        _require(
            _covered(swept, [tuple(sa["rect_mm"]), tuple(sb["rect_mm"])]),
            "connections",
            "entire swept footprint has continuous declared support",
        )
        _clear(
            raw,
            swept,
            min(za, zb),
            max(za, zb),
            ignore_surfaces=frozenset({sa["surface_id"], sb["surface_id"]}),
        )
    claimed = raw["document_sha256"]
    calculated = sha256_of_canonical({k: v for k, v in raw.items() if k != "document_sha256"}).hex()
    _require(
        type(claimed) is str and claimed == calculated,
        "document_sha256",
        "matches the whole canonical declaration",
    )
    return SupportNetwork(encoded, calculated)


def seal_support_network(
    document: Mapping[str, Any], *, source: Mapping[str, Any] | None = None
) -> SupportNetwork:
    """Seal authored integer data and admit it through the same reader used on replay."""
    raw = dict(document)
    raw.pop("document_sha256", None)
    try:
        raw["document_sha256"] = sha256_of_canonical(raw).hex()
    except (CanonicalisationError, TypeError, ValueError) as exc:
        raise SupportRefused("", "is canonical integer JSON") from exc
    return read_support_network(raw, source=source)
