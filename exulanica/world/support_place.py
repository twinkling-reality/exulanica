"""Project a canonical support network to society heights and a person-navigation adapter."""

from __future__ import annotations

import copy
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from exulanica.canonical import canonical_json, sha256_of_canonical
from exulanica.world.society_catalogs import RoutineModel
from exulanica.world.society_place import (
    _DESTINATION_FIELDS,
    PLACE_PROFILE_V2,
    ceil_distance,
    seal_place,
    validate_place,
)
from exulanica.world.support_surfaces import (
    PROFILE,
    SupportNetwork,
    SupportRefused,
    read_support_network,
)


@dataclass(frozen=True, slots=True)
class SupportProjection:
    """The existing society place and its surface-qualified navigation binding."""

    encoded: bytes
    network: SupportNetwork

    def place(self) -> dict[str, Any]:
        return json.loads(self.encoded)

    def adapter_document(self) -> dict[str, Any]:
        """A future person consumer uses the same supports, actor limits, nodes and connections.

        Its active surface must be retained; a projected XY crossing does not select a level.
        This payload does not connect an existing height-zero renderer by itself.
        """
        network = self.network.document()
        return {
            "profile": "exulanica.support-adapter/v1",
            "network": network,
            "place_sha256": self.place()["document_sha256"],
            "node_surfaces": {
                qualified_node(network["network_id"], n["surface_id"], n["node_id"]): n[
                    "surface_id"
                ]
                for n in network["nodes"]
            },
        }


def qualified_node(network_id: str, surface_id: str, node_id: str) -> str:
    """Length-delimited canonical tuple hashing avoids ambiguous identity concatenations."""
    digest = sha256_of_canonical([network_id, surface_id, node_id]).hex()
    return f"support-node:{digest}"


def project_support_place(
    network: SupportNetwork,
    routine: RoutineModel,
    *,
    place_id: str,
    destinations: Sequence[Mapping[str, Any]] = (),
    spots: Mapping[str, str] | None = None,
) -> SupportProjection:
    """Use existing destination schema and explicitly supplied standing nodes, never infer uses.

    Destination node_id and each spots value name original network nodes. The adapter publishes
    qualified IDs to both consumers. Declared spots and enabled destinations must be reachable
    from the network's entry; full existing place/routine validation remains authoritative.
    """
    network = read_support_network(network.document())
    document = network.document()
    source = document["source"]
    surfaces = {s["surface_id"]: s for s in document["surfaces"]}
    nodes = {n["node_id"]: n for n in document["nodes"]}
    identities = {
        key: qualified_node(document["network_id"], node["surface_id"], key)
        for key, node in nodes.items()
    }
    reachable = network.reachable()
    given_spots = {} if spots is None else dict(spots)
    if any(type(dest) is not dict or set(dest) != _DESTINATION_FIELDS for dest in destinations):
        raise SupportRefused("destinations", "uses the existing closed destination fields")
    targets = copy.deepcopy([dict(dest) for dest in destinations])
    for target in targets:
        if (
            type(target["spot_ids"]) is not list
            or any(type(s) is not str for s in target["spot_ids"])
            or type(target["destination_id"]) is not str
        ):
            raise SupportRefused("destinations", "states identities and standing spots")
        node = target.get("node_id")
        if type(node) is not str or node not in nodes:
            raise SupportRefused("destinations.node_id", "names an admitted network node")
        if target.get("enabled") and node not in reachable:
            raise SupportRefused(
                "destinations.node_id", "enabled destination is not reachable from entry"
            )
        target["node_id"] = identities[node]
    standing = []
    for key, node in sorted(given_spots.items()):
        if type(key) is not str or type(node) is not str or node not in reachable:
            raise SupportRefused("spots", "standing spots name reachable support nodes")
        standing.append(
            {
                "spot_id": key,
                "node_id": identities[node],
                "position_mm": list(nodes[node]["position_mm"]),
                "support_z_mm": surfaces[nodes[node]["surface_id"]]["support_z_mm"],
                "destination_ids": sorted(
                    t["destination_id"] for t in targets if key in t["spot_ids"]
                ),
            }
        )
    edges = []
    for edge in document["connections"]:
        a, b = edge["from_node_id"], edge["to_node_id"]
        digest = sha256_of_canonical([document["network_id"], edge["connection_id"]]).hex()
        edges.append(
            {
                "edge_id": f"support-edge:{digest}",
                "from_node_id": identities[a],
                "to_node_id": identities[b],
                "length_mm": ceil_distance(nodes[a]["position_mm"], nodes[b]["position_mm"]),
                "kind": "footway",
            }
        )
    place = seal_place(
        {
            "profile": PLACE_PROFILE_V2,
            "place_id": place_id,
            "source": {
                "kind": "support-network",
                "profile": PROFILE,
                "input_seq": 1,
                "document_sha256": network.sha256,
            },
            "frame": dict(document["frame"]),
            "routine_sha256": routine.sha256,
            "clearance_mm": document["actor"]["radius_mm"],
            "nodes": sorted(
                [
                    {
                        "node_id": identities[key],
                        "position_mm": list(node["position_mm"]),
                        "street_id": None,
                        "support_z_mm": surfaces[node["surface_id"]]["support_z_mm"],
                    }
                    for key, node in nodes.items()
                ],
                key=lambda n: n["node_id"],
            ),
            "edges": sorted(edges, key=lambda e: e["edge_id"]),
            "spots": standing,
            "crossings": [],
            "destinations": sorted(targets, key=lambda t: t["destination_id"]),
            "unavailable_destinations": [],
            "unsupported": [
                "ramps, lifts and transit",
                "source geometry completeness requires its composition producer",
            ],
            "availability": "available",
            "unavailable_reason": None,
        }
    )
    try:
        validate_place(place, routine)
    except ValueError as exc:
        raise SupportRefused("place", str(exc)) from exc
    # The source/world binding stays in the exact network carried beside the place.
    assert source == network.document()["source"]
    return SupportProjection(canonical_json(place), network)
