"""Explicit support admission for passive rigid things, independent of authored mesh edits.

The source producer supplies an already reconciled network and current authored obstruction
proxies. A valid declaration or digest alone does not establish source completeness. This pure
resolver returns a checked placement and receipt; it neither writes durable affinity nor makes
an elevated affordance or locomotion host available.
"""

from __future__ import annotations

import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.errors import CanonicalisationError
from exulanica.things.kinds import ThingKind
from exulanica.world.errors import InvalidThingPlacement
from exulanica.world.placed_things import (
    PlacedThing,
    ThingPlacement,
    WorkspaceKindReference,
    placed_thing_document,
    validate_placed_thing,
)
from exulanica.world.support_surfaces import (
    SupportNetwork,
    SupportRefused,
    _covered,
    _overlaps,
    read_support_network,
)

REFERENCE_PROFILE: Final = "exulanica.support-reference/v1"
RECEIPT_PROFILE: Final = "exulanica.support-placement/v1"
_SHA: Final = re.compile(r"[0-9a-f]{64}")
_COORDINATE: Final = 10_000_000
_SOLIDS_MAXIMUM: Final = 512


class SupportPlacementRefused(InvalidThingPlacement):
    """A support placement cannot be admitted as requested."""

    code = "support_placement_invalid"

    def __init__(self, where: str, detail: str) -> None:
        super().__init__(f"{self.code}: {where}: {detail}")
        self.where, self.detail = where, detail


def _require(condition: bool, where: str, detail: str) -> None:
    if not condition:
        raise SupportPlacementRefused(where, detail)


@dataclass(frozen=True, slots=True)
class PlacementSolid:
    """A producer-owned volume in region east/south/up millimetres."""

    solid_id: str
    box_mm: tuple[int, int, int, int, int, int]

    def document(self) -> dict[str, Any]:
        return {"solid_id": self.solid_id, "box_mm": list(self.box_mm)}


@dataclass(frozen=True, slots=True)
class PlacementContext:
    """The writer's exact source and state, never a client's purported saved network.

    Network source geometry is reconciled by its producer. Every surrounding authored item
    needs a conservative volume proxy or an explicit unknown entry, including nonblocking
    rendered items: this physical placement check does not infer geometry from an affordance.
    """

    world_id: str
    version_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    receipt_sha256: str
    base_state_sha256: str
    region_id: str
    network: SupportNetwork
    other_solids: tuple[PlacementSolid, ...] = ()
    unknown_obstructions: tuple[str, ...] = ()
    actor_volumes: tuple[PlacementSolid, ...] = ()

    def reference(self, surface_id: str) -> dict[str, Any]:
        return {
            "profile": REFERENCE_PROFILE,
            "world_id": self.world_id,
            "source_snapshot_id": str(self.source_snapshot_id),
            "receipt_sha256": self.receipt_sha256,
            "network_sha256": self.network.sha256,
            "region_id": self.region_id,
            "surface_id": surface_id,
        }


@dataclass(frozen=True, slots=True)
class SupportedPlacement:
    """Canonical admission evidence. Persistence remains the authored writer's responsibility."""

    placement: ThingPlacement
    encoded: bytes
    sha256: str

    def document(self) -> dict[str, Any]:
        return json.loads(self.encoded)


def _other_solids(context: PlacementContext) -> list[dict[str, Any]]:
    _require(
        not context.unknown_obstructions,
        "obstructions",
        "surrounding authored content has no authoritative volume proxy",
    )
    return _volume_documents(context.other_solids, maximum=_SOLIDS_MAXIMUM)


def _volume_documents(volumes: tuple[PlacementSolid, ...], *, maximum: int) -> list[dict[str, Any]]:
    _require(
        type(volumes) is tuple and len(volumes) <= maximum,
        "obstructions",
        "contains a bounded immutable list of producer-owned volumes",
    )
    identities = []
    solids = []
    for solid in volumes:
        _require(isinstance(solid, PlacementSolid), "obstructions", "states typed volume proxies")
        _require(
            type(solid.solid_id) is str and 0 < len(solid.solid_id) <= 256,
            "obstructions.solid_id",
            "has a bounded identity",
        )
        box = solid.box_mm
        _require(
            type(box) is tuple
            and len(box) == 6
            and all(type(v) is int and -_COORDINATE <= v <= _COORDINATE for v in box),
            "obstructions.box_mm",
            "has six bounded whole millimetres",
        )
        _require(
            box[0] < box[3] and box[1] < box[4] and box[2] < box[5],
            "obstructions.box_mm",
            "has positive volume",
        )
        identities.append(solid.solid_id)
        solids.append(solid.document())
    _require(
        len(set(identities)) == len(identities), "obstructions", "does not repeat volume identities"
    )
    return sorted(solids, key=lambda s: s["solid_id"])


def protected_actor_volumes(
    place: Mapping[str, Any], network: SupportNetwork, *, north_positive: bool
) -> tuple[PlacementSolid, ...]:
    """Conservative envelopes for the producer's reconciled combined place, in east/south/up.

    The site producer carries legacy east/north points. The frame conversion is explicit and
    occurs once. The source producer, not a claimant, supplies the actual combined place.
    """
    from exulanica.world.society_place import PLACE_PROFILE_V2, place_sha256

    _require(
        place["profile"] == PLACE_PROFILE_V2
        and place["document_sha256"] == place_sha256(place)
        and place["source"]["profile"] == "exulanica.support-network/v1"
        and place["source"]["document_sha256"] == network.sha256,
        "actor.place",
        "matches the sealed producer place and support network",
    )
    actor = network.document()["actor"]
    radius, height = actor["radius_mm"], actor["height_mm"]
    nodes = {n["node_id"]: n for n in place["nodes"]}

    def point(node: Mapping[str, Any]) -> tuple[int, int, int]:
        x, y = node["position_mm"]
        return x, -y if north_positive else y, node["support_z_mm"]

    volumes = []
    for node in nodes.values():
        x, y, z = point(node)
        key = sha256_of_canonical(["node", node["node_id"]]).hex()
        volumes.append(
            PlacementSolid(key, (x - radius, y - radius, z, x + radius, y + radius, z + height))
        )
    for edge in place["edges"]:
        x0, y0, z0 = point(nodes[edge["from_node_id"]])
        x1, y1, z1 = point(nodes[edge["to_node_id"]])
        key = sha256_of_canonical(["edge", edge["edge_id"]]).hex()
        volumes.append(
            PlacementSolid(
                key,
                (
                    min(x0, x1) - radius,
                    min(y0, y1) - radius,
                    min(z0, z1),
                    max(x0, x1) + radius,
                    max(y0, y1) + radius,
                    max(z0, z1) + height,
                ),
            )
        )
    return tuple(sorted(volumes, key=lambda v: v.solid_id))


def _intersects(box: tuple[int, ...], other: tuple[int, ...]) -> bool:
    return (
        _overlaps((box[0], box[1], box[3], box[4]), (other[0], other[1], other[3], other[4]))
        and box[2] < other[5]
        and other[2] < box[5]
    )


def all_yaw_radius(box: Mapping[str, int]) -> int:
    """Whole-millimetre conservative radius of an admitted rigid box at every yaw."""
    squared = box["width"] ** 2 + box["depth"] ** 2
    diameter = math.isqrt(squared)
    diameter += diameter * diameter < squared
    return (diameter + 1) // 2


def _preserve_actor_network(raw: Mapping[str, Any], box: tuple[int, ...]) -> None:
    """Protect declared actor poses and swept corridors, not every conceivable body or route."""
    surfaces = {s["surface_id"]: s for s in raw["surfaces"]}
    nodes = {n["node_id"]: n for n in raw["nodes"]}
    radius, height = raw["actor"]["radius_mm"], raw["actor"]["height_mm"]
    for node in nodes.values():
        x, south = node["position_mm"]
        z = surfaces[node["surface_id"]]["support_z_mm"]
        volume = (x - radius, south - radius, z, x + radius, south + radius, z + height)
        _require(
            not _intersects(box, volume),
            "actor.nodes",
            "placement intersects a declared actor pose",
        )
    for connection in raw["connections"]:
        a, b = nodes[connection["from_node_id"]], nodes[connection["to_node_id"]]
        x0, y0 = a["position_mm"]
        x1, y1 = b["position_mm"]
        za = surfaces[a["surface_id"]]["support_z_mm"]
        zb = surfaces[b["surface_id"]]["support_z_mm"]
        swept = (
            min(x0, x1) - radius,
            min(y0, y1) - radius,
            min(za, zb),
            max(x0, x1) + radius,
            max(y0, y1) + radius,
            max(za, zb) + height,
        )
        _require(
            not _intersects(box, swept),
            "actor.connections",
            "placement intersects a declared actor's swept connection envelope",
        )


def validate_supported_placement(
    placement: ThingPlacement,
    kind: ThingKind,
    reference: Mapping[str, Any],
    *,
    context: PlacementContext,
) -> SupportedPlacement:
    """Admit an explicit existing pose, with no floor inference or authored transform changes."""
    _require(isinstance(context, PlacementContext), "context", "is source-producer owned")
    _require(
        isinstance(context.version_id, uuid.UUID)
        and isinstance(context.source_snapshot_id, uuid.UUID),
        "context",
        "binds exact version and source snapshot identities",
    )
    for field in ("receipt_sha256", "base_state_sha256"):
        value = getattr(context, field)
        _require(type(value) is str and _SHA.fullmatch(value) is not None, field, "is a SHA-256")
    _require(isinstance(placement, ThingPlacement), "placement", "states a typed thing placement")
    _require(isinstance(kind, ThingKind), "kind", "is an admitted thing kind")
    _require(
        isinstance(context.network, SupportNetwork), "network", "is an admitted support network"
    )
    try:
        raw = read_support_network(context.network.document()).document()
        _require(
            context.network.sha256 == raw["document_sha256"],
            "network",
            "matches its immutable canonical declaration",
        )
        kind_document = json.loads(canonical_json(dict(kind.document)))
        _require(
            sha256_of_canonical(kind_document).hex() == kind.sha256,
            "kind",
            "matches its immutable admitted document",
        )
        validate_placed_thing(
            PlacedThing(
                placement.thing_id,
                placement.kind,
                placement.region_id,
                placement.transform,
                placement.origin,
            ),
            region_ids=frozenset({context.region_id}),
            kinds={(kind.kind, kind.version): kind},
        )
    except (
        SupportRefused,
        InvalidThingPlacement,
        CanonicalisationError,
        TypeError,
        ValueError,
    ) as exc:
        if isinstance(exc, SupportPlacementRefused):
            raise
        raise SupportPlacementRefused("placement", str(exc)) from exc
    _require(
        raw["source"]["world_id"] == context.world_id,
        "source",
        "network belongs to the writer's canonical world",
    )
    _require(
        placement.kind.sha256 == kind.sha256
        and (
            isinstance(placement.kind, WorkspaceKindReference)
            or (placement.kind.kind, placement.kind.version) == (kind.kind, kind.version)
        ),
        "kind",
        "matches the placed kind's exact reference",
    )
    body = kind_document["body"]
    _require(
        kind_document["class"] == "object"
        and body["plan"] == "rigid/v1"
        and not kind_document["moves"],
        "kind",
        "supports only passive rigid object-class things",
    )
    _require(
        type(reference) is dict
        and set(reference) == set(context.reference("").keys())
        and type(reference.get("surface_id")) is str
        and reference == context.reference(reference["surface_id"]),
        "support",
        "matches exact world, source snapshot, receipt, network, region and surface reference",
    )
    surface = next((s for s in raw["surfaces"] if s["surface_id"] == reference["surface_id"]), None)
    _require(surface is not None, "support.surface_id", "names an admitted support")
    assert surface is not None
    sides = body["box_mm"]
    # Ceiling(sqrt(width² + depth²) / 2) encloses the rigid box at every yaw. No float enters
    # geometry or digests, and refusal may be more conservative than the actual turned rectangle.
    radius = all_yaw_radius(sides)
    x, south, z = placement.transform.x_mm, placement.transform.z_mm, placement.transform.y_mm
    _require(
        z == surface["support_z_mm"], "pose.y_mm", "equals the explicitly named support height"
    )
    rect = (x - radius, south - radius, x + radius, south + radius)
    _require(
        _covered(rect, [tuple(surface["rect_mm"])]),
        "footprint",
        "the entire conservative all-yaw footprint fits the named support",
    )
    box = (rect[0], rect[1], z, rect[2], rect[3], z + sides["height"])
    other_solids = _other_solids(context)
    for solid in [*raw["solids"], *other_solids]:
        _require(
            not _intersects(box, tuple(solid["box_mm"])),
            "obstructions",
            "placement intersects an authoritative obstruction volume",
        )
    for other in raw["surfaces"]:
        _require(
            not (z < other["support_z_mm"] < box[5] and _overlaps(rect, tuple(other["rect_mm"]))),
            "headroom",
            "another support intrudes into the placed thing's height",
        )
    _preserve_actor_network(raw, box)
    actor_volumes = _volume_documents(context.actor_volumes, maximum=8192)
    for volume in actor_volumes:
        _require(
            not _intersects(box, tuple(volume["box_mm"])),
            "actor.place",
            "placement intersects the declared combined actor network envelope",
        )
    placed = PlacedThing(
        placement.thing_id,
        placement.kind,
        placement.region_id,
        placement.transform,
        placement.origin,
    )
    receipt = {
        "profile": RECEIPT_PROFILE,
        "version_id": str(context.version_id),
        "base_state_sha256": context.base_state_sha256,
        "support": dict(reference),
        "placement": placed_thing_document(placed),
        "body": {"kind_sha256": kind.sha256, "box_mm": sides, "all_yaw_radius_mm": radius},
        "other_solids_sha256": sha256_of_canonical(other_solids).hex(),
        "actor_volumes_sha256": sha256_of_canonical(actor_volumes).hex(),
    }
    digest = sha256_of_canonical(receipt).hex()
    receipt["document_sha256"] = digest
    return SupportedPlacement(placement, canonical_json(receipt), digest)


def read_supported_placement(
    document: Any,
    placement: ThingPlacement,
    kind: ThingKind,
    *,
    context: PlacementContext,
) -> SupportedPlacement:
    """Rebuild the whole receipt from current authoritative inputs, never trust a client seal."""
    _require(
        type(document) is dict and type(document.get("support")) is dict,
        "receipt",
        "states a support placement receipt",
    )
    rebuilt = validate_supported_placement(placement, kind, document["support"], context=context)
    _require(document == rebuilt.document(), "receipt", "matches the entire recomputed placement")
    return rebuilt
