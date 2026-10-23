"""Lanes and spaces a network no longer drives: what placed things on the carriageway close.

A closed lane is one lane path, the stretch between the junction it leaves and the one it flows
into (lanes change only through connections, :mod:`exulanica.traffic.network`). Closing it takes
every class from it and from the connections into and out of it, so :func:`plan_route` never
routes through it, and drops every space reached from a closed path, so no vehicle parks, starts
or ends a trip inside it. A closed space (one a placed thing stands in) is dropped the same way.
Closing every lane of a segment closes the street. A closed connection (one a placed thing stands
on inside its junction, traffic rules 3) takes every class from that connection alone; closing every
connection of a junction closes the junction. Nothing else of the network changes; its
document names the closures and its digest covers them, so a state bound to a closed network is
never read against the open one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Collection
from typing import Final

from exulanica.canonical import sha256_of_canonical
from exulanica.traffic.errors import UnsupportedNetworkError
from exulanica.traffic.network import RoadNetwork

__all__ = ["CLOSURES_PROFILE", "CONNECTION_CLOSURES_PROFILE", "close_network"]

CLOSURES_PROFILE: Final = "exulanica.traffic-closures/v1"
#: The closures document where a connection is closed too; one with none keeps the first profile
#: and its bytes.
CONNECTION_CLOSURES_PROFILE: Final = "exulanica.traffic-closures/v2"


def close_network(
    network: RoadNetwork,
    lanes: Collection[str],
    spaces: Collection[str] = (),
    connectors: Collection[str] = (),
) -> RoadNetwork:
    """``network`` with the lane paths ``lanes``, the spaces ``spaces`` and the connection paths
    ``connectors`` closed; ``network`` itself where all are empty. A lane, space or connection the
    network does not hold is refused."""
    if not lanes and not spaces and not connectors:
        return network
    for path_id in lanes:
        path = network.paths.get(path_id)
        if path is None or path.kind != "lane":
            raise UnsupportedNetworkError(f"no lane {path_id} to close")
    for identity in spaces:
        if identity not in network.spaces:
            raise UnsupportedNetworkError(f"no space {identity} to close")
    for path_id in connectors:
        path = network.paths.get(path_id)
        if path is None or path.kind != "connector":
            raise UnsupportedNetworkError(f"no connection {path_id} to close")
    closed_lanes = set(lanes)
    shut = closed_lanes | set(connectors)
    for path in network.paths.values():
        if path.kind != "lane" and closed_lanes.intersection(
            (*path.successors, *path.predecessors)
        ):
            shut.add(path.path_id)
    paths = {
        path_id: dataclasses.replace(path, classes=()) if path_id in shut else path
        for path_id, path in network.paths.items()
    }
    kept = {
        identity: space
        for identity, space in network.spaces.items()
        if space.access_path not in shut and identity not in spaces
    }
    document = {
        **network.document,
        "paths": [
            {**item, "classes": []} if item["path_id"] in shut else item
            for item in network.document["paths"]
        ],
        "spaces": [item for item in network.document["spaces"] if item["identity"] in kept],
        "closures": {
            "profile": CONNECTION_CLOSURES_PROFILE if connectors else CLOSURES_PROFILE,
            "lanes": sorted(closed_lanes),
            "spaces": sorted(spaces),
            **({"connectors": sorted(connectors)} if connectors else {}),
        },
    }
    return dataclasses.replace(
        network,
        paths=paths,
        spaces=kept,
        document=document,
        digest=sha256_of_canonical(document).hex(),
    )
