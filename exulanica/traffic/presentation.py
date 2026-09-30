"""The record a vehicle presents for drawing: what the tessellator reads, and nothing it invents.

``exulanica.traffic-vehicle-presentation/v1``, one record per vehicle per second:

``vehicle_id``, ``vehicle_class``
    The uuid5 identity and the vehicle-class catalog key.
``body_family``, ``colour``
    Presentation keys from the class entry, chosen once per vehicle from the seed. The
    tessellator owns what a body family looks like; traffic owns only the key.
``dimensions_mm``
    ``length``, ``width``, ``height``, ``wheelbase``, ``front_overhang``, ``rear_overhang``,
    copied from the catalog entry so a reader needs no catalog, with ``catalog_sha256`` to prove
    which one.
``front_axle_mm``, ``rear_axle_mm``
    Integer plan points, in the road records' frame, of the front and rear axle centres. The
    heading is rear to front; no angle is stored. On a curve both points lie on the path, so the
    body is placed on its chord. A vehicle parked in a carriageway bay stands centred in the bay,
    facing the way its access lane runs. A vehicle at a footway stand group stands in its
    ``slot``: the footprint is divided into ``capacity`` equal places along its longer side, and
    the vehicle is centred in its place, across the footprint, front away from the access lane.
``motion_path_mm``
    Every point the front passed during the second that produced this record, first and last
    included. A renderer interpolates along it, never across its corners.
``mode``, ``speed_mm_per_s``, ``slot``
    ``parked``, ``leaving``, ``driving`` or ``arriving``, the speed over the last second, and the
    place of its space a parked vehicle stands in (-1 otherwise).
``synthetic``
    Always true: these vehicles are simulation, never evidence.

Not supplied in v1, and a reader must not invent them: lamps, indicators, wheel angles, doors,
occupants, and any height other than the catalog's.

**Signals** (``exulanica.traffic-signal-presentation/v1``). For each signal of the network, in
identity order: its identity, its junction's, and each group of its plan, in the plan's order, with
its kind (``vehicle`` or ``pedestrian``) and the plan points a head of it stands at: beside the stop
line of every lane whose movements the group releases, on the driving side just outside the corridor
the lane's widest vehicle sweeps, and both ends of every crosswalk it releases.
What a group shows at a second is the index of its indication in :data:`VEHICLE_INDICATIONS` or
:data:`PEDESTRIAN_INDICATIONS` (:func:`signal_codes`), the one the step obeyed at that second. Where
a head stands and what it shows are all a reader may rely on; a head's look is the renderer's.
"""

from __future__ import annotations

from collections.abc import Mapping
from math import isqrt
from typing import Any, Final

from exulanica.canonical import round_half_down
from exulanica.traffic.catalogs import TrafficCatalogs, VehicleClass
from exulanica.traffic.geometry import Point
from exulanica.traffic.network import RoadNetwork
from exulanica.traffic.signal_actuation import SignalTimeline
from exulanica.traffic.signals import (
    PEDESTRIAN_INDICATIONS,
    VEHICLE_INDICATIONS,
    pedestrian_indication,
    vehicle_indication,
)

__all__ = [
    "PRESENTATION_PROFILE",
    "SIGNAL_PRESENTATION_PROFILE",
    "presentation_frame",
    "signal_codes",
    "signal_heads",
    "vehicle_presentation",
]

PRESENTATION_PROFILE: Final = "exulanica.traffic-vehicle-presentation/v1"
SIGNAL_PRESENTATION_PROFILE: Final = "exulanica.traffic-signal-presentation/v1"


def signal_heads(network: RoadNetwork, catalogs: TrafficCatalogs) -> list[dict[str, Any]]:
    """Every signal of ``network`` in identity order: its groups, with where their heads stand."""
    signals = []
    for junction in sorted(
        (junction for junction in network.junctions.values() if junction.signal is not None),
        key=lambda junction: junction.signal.identity,  # type: ignore[union-attr]
    ):
        signal = junction.signal
        assert signal is not None
        plan = catalogs.plan(signal.plan)
        by_group: dict[str, list[list[int]]] = {group.key: [] for group in plan.groups}
        for connector, group in signal.connector_groups:
            head = _beside_stop_line(network, network.paths[connector].predecessors[0])
            if head not in by_group[group]:
                by_group[group].append(head)
        bands = {band.band_id: band for band in network.bands}
        for band_id, group in signal.band_groups:
            for end in bands[band_id].line:
                by_group[group].append(list(end))
        signals.append(
            {
                "profile": SIGNAL_PRESENTATION_PROFILE,
                "signal_id": signal.identity,
                "junction_id": junction.identity,
                "groups": [
                    {
                        "group": group.key,
                        "kind": group.kind,
                        "points_mm": sorted(by_group[group.key]),
                    }
                    for group in plan.groups
                ],
            }
        )
    return signals


def _beside_stop_line(network: RoadNetwork, lane_id: str) -> list[int]:
    """Where a lane's signal head stands: level with its stop line, on the driving side, at the edge
    of the corridor its widest vehicle sweeps there, so no vehicle it holds passes through it."""
    lane = network.paths[lane_id]
    last = lane.line.piece_count - 1
    start, stop = lane.line.piece(last)
    dx, dy = stop[0] - start[0], stop[1] - start[1]
    left, right = lane.extents[last]
    # Right of the travel direction is (dy, -dx); a left-driving network would stand them left.
    if network.driving_side == "right":
        normal, reach = (dy, -dx), right
    else:
        normal, reach = (-dy, dx), left
    run = isqrt(dx * dx + dy * dy)
    return [
        stop[0] + round_half_down(normal[0] * reach, run),
        stop[1] + round_half_down(normal[1] * reach, run),
    ]


def signal_codes(
    network: RoadNetwork,
    catalogs: TrafficCatalogs,
    second: int,
    *,
    signal_timelines: Mapping[str, SignalTimeline] | None = None,
) -> list[list[int]]:
    """What each group of each signal shows at ``second``, in :func:`signal_heads`'s order: the
    index of its indication among the vehicle or pedestrian indications."""
    codes = []
    for junction in sorted(
        (junction for junction in network.junctions.values() if junction.signal is not None),
        key=lambda junction: junction.signal.identity,  # type: ignore[union-attr]
    ):
        signal = junction.signal
        assert signal is not None
        plan = catalogs.plan(signal.plan)
        timeline = None if signal_timelines is None else signal_timelines.get(signal.identity)
        row = []
        for group in plan.groups:
            if group.kind == "vehicle":
                shown = (
                    timeline.vehicle_indication(second, group.key)
                    if timeline is not None
                    else vehicle_indication(plan, signal.offset_s, second, group.key)
                )
                row.append(VEHICLE_INDICATIONS.index(shown))
            else:
                shown = (
                    timeline.pedestrian_indication(second, group.key)
                    if timeline is not None
                    else pedestrian_indication(plan, signal.offset_s, second, group.key)
                )
                row.append(PEDESTRIAN_INDICATIONS.index(shown))
        codes.append(row)
    return codes


def _route_point(network: RoadNetwork, route: list[str], position: int) -> Point:
    """The point at ``position`` along a route, clamped to its start."""
    position = max(position, 0)
    for path_id in route:
        line = network.paths[path_id].line
        if position <= line.length:
            return line.point_at(position)
        position -= line.length
    return network.paths[route[-1]].line.point_at(network.paths[route[-1]].line.length)


def _at_stand(
    vehicle: Mapping[str, Any], network: RoadNetwork, vehicle_class: VehicleClass
) -> tuple[Point, Point]:
    """Front and rear axle of a vehicle standing in its place of a footway stand group."""
    space = network.spaces[vehicle["space"]]
    corners = space.footprint
    sides = [
        (following[0] - corner[0], following[1] - corner[1])
        for corner, following in zip(corners, corners[1:] + corners[:1], strict=True)
    ]
    along = max(sides, key=lambda side: (side[0] * side[0] + side[1] * side[1], side))
    across = (-along[1], along[0])
    centre = (sum(point[0] for point in corners) // 4, sum(point[1] for point in corners) // 4)
    lane_point = network.paths[space.access_path].line.point_at(space.access_end)
    if (lane_point[0] - centre[0]) * across[0] + (lane_point[1] - centre[1]) * across[1] > 0:
        across = (-across[0], -across[1])
    places = space.capacity
    slot = min(max(vehicle["slot"], 0), places - 1)
    place = (
        centre[0] + round_half_down(along[0] * (2 * slot + 1 - places), 2 * places),
        centre[1] + round_half_down(along[1] * (2 * slot + 1 - places), 2 * places),
    )
    run = isqrt(across[0] * across[0] + across[1] * across[1])
    front = vehicle_class.length_mm // 2

    def ahead(distance: int) -> Point:
        return (
            place[0] + round_half_down(across[0] * distance, run),
            place[1] + round_half_down(across[1] * distance, run),
        )

    return (
        ahead(front - vehicle_class.front_overhang_mm),
        ahead(front - vehicle_class.front_overhang_mm - vehicle_class.wheelbase_mm),
    )


def vehicle_presentation(
    vehicle: Mapping[str, Any], network: RoadNetwork, catalogs: TrafficCatalogs
) -> dict[str, Any]:
    vehicle_class = catalogs.vehicle_class(vehicle["vehicle_class"])
    front_to_front_axle = vehicle_class.front_overhang_mm
    front_to_rear_axle = front_to_front_axle + vehicle_class.wheelbase_mm
    if vehicle["mode"] == "parked" and network.spaces[vehicle["space"]].placement != "carriageway":
        front_axle, rear_axle = _at_stand(vehicle, network, vehicle_class)
    elif vehicle["mode"] == "parked":
        space = network.spaces[vehicle["space"]]
        lane = network.paths[space.access_path].line
        middle = (space.access_start + space.access_end) // 2
        on_lane = lane.point_at(middle)
        centre_x = sum(point[0] for point in space.footprint) // 4
        centre_y = sum(point[1] for point in space.footprint) // 4
        shift = (centre_x - on_lane[0], centre_y - on_lane[1])
        # Centre the body in the stall, facing the way its access lane runs.
        front = middle + vehicle_class.length_mm // 2
        points = [
            lane.point_at(front - front_to_front_axle),
            lane.point_at(front - front_to_rear_axle),
        ]
        front_axle, rear_axle = ((x + shift[0], y + shift[1]) for x, y in points)
    else:
        route = vehicle["route"]
        offset = sum(network.paths[path_id].length for path_id in route[: vehicle["route_index"]])
        front = offset + vehicle["position_mm"]
        front_axle = _route_point(network, route, front - front_to_front_axle)
        rear_axle = _route_point(network, route, front - front_to_rear_axle)
    return {
        "profile": PRESENTATION_PROFILE,
        "vehicle_id": vehicle["id"],
        "vehicle_class": vehicle_class.key,
        "body_family": vehicle["body_family"],
        "colour": vehicle["colour"],
        "catalog_sha256": catalogs.digest,
        "dimensions_mm": {
            "length": vehicle_class.length_mm,
            "width": vehicle_class.width_mm,
            "height": vehicle_class.height_mm,
            "wheelbase": vehicle_class.wheelbase_mm,
            "front_overhang": vehicle_class.front_overhang_mm,
            "rear_overhang": vehicle_class.rear_overhang_mm,
        },
        "front_axle_mm": list(front_axle),
        "rear_axle_mm": list(rear_axle),
        "motion_path_mm": [list(point) for point in vehicle["motion_path_mm"]],
        "mode": vehicle["mode"],
        "speed_mm_per_s": vehicle["speed_mm_per_s"],
        "slot": vehicle["slot"],
        "synthetic": True,
    }


def presentation_frame(
    state: Mapping[str, Any], network: RoadNetwork, catalogs: TrafficCatalogs
) -> dict[str, Any]:
    return {
        "profile": "exulanica.traffic-presentation-frame/v1",
        "traffic_id": state["traffic_id"],
        "second": state["second"],
        "network_sha256": state["network_sha256"],
        "vehicles": [
            vehicle_presentation(vehicle, network, catalogs) for vehicle in state["vehicles"]
        ],
    }
