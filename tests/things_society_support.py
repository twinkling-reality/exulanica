"""A society of things in a starter world, composed and advanced in memory, for v7's tests.

The small square's objects stand where a starter world's arrangement puts them, and the things
are placed by their shipped kinds; inputs are composed under the things composition as the
runtime composes them, and crossings are the documents a door hands over. Nothing here reads a
database except :class:`MemoryCrossings`, which keeps a door's crossings in memory and is
registered by the tests that use it.
"""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.environment.district_geometry import segment_blocked
from exulanica.things.kinds import shipped_thing_kinds
from exulanica.world.arrival_selection import ArrivalDescriptor
from exulanica.world.authored_delta import delta_sha256
from exulanica.world.crossings import (
    ARRIVAL_PROFILE,
    DEPARTURE_PROFILE,
    BoundCrossing,
    ConsumedCrossing,
    Crossing,
)
from exulanica.world.objects import AuthoredObject, ObjectOrigin, Transform
from exulanica.world.placed_things import PlacedThing, named_kind
from exulanica.world.society_authored_ground import build_authored_ground_society_input_v5

import living_square_support as square
import test_society_authored_ground as authored

#: The seed a society of things is made with here, and its id.
SEED = "7" * 64
SOCIETY = uuid.uuid5(authored.VERSION, "exulanica-society/v1")
GRANT = uuid.UUID(int=0x9A)
BRIDGE = "testbridge"


def thing(
    placed_id: str,
    kind: str,
    version: int,
    x_mm: int,
    z_mm: int,
    *,
    yaw: int = 0,
    y_mm: int = 0,
    removed: bool = False,
) -> PlacedThing:
    """A thing placed by a shipped kind in the starter's region."""
    return PlacedThing(
        placed_id,
        named_kind(kind, version),
        "region:starter",
        Transform(x_mm, y_mm, z_mm, yaw, 1000),
        ObjectOrigin("authored", "fictional"),
        removed,
    )


def compose(
    things: Sequence[PlacedThing],
    *,
    objects: Sequence[AuthoredObject] | None = None,
    input_seq: int = 1,
    edit_seq: int | None = None,
    arrival: ArrivalDescriptor | None = None,
    version_id: uuid.UUID | None = None,
    world_id: str | None = None,
    source_snapshot_id: uuid.UUID | None = None,
    made_kinds: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """The things input of a starter version holding the small square and ``things``, at the
    opening pose ``arrival`` pins, or the ground's own; the starter's own version unless the
    version, world and snapshot are given, as a test holding a version of its own gives them.
    ``made_kinds`` are the run forms of the kinds its workspace keeps, by digest."""
    held = tuple(square.square_objects() if objects is None else objects)
    starter = square.version(held, edit_seq)
    version = dataclasses.replace(
        starter,
        version_id=version_id or starter.version_id,
        world_id=world_id or starter.world_id,
        source_snapshot_id=source_snapshot_id or starter.source_snapshot_id,
        things=tuple(things),
        state_sha256=delta_sha256(
            objects=held,
            element_overrides=(),
            environment_instances=(),
            point_map_instances=(),
            things=tuple(things),
        ),
    )
    return build_authored_ground_society_input_v5(
        # The starter's ground, in the version's own world and over its own snapshot.
        ground=dataclasses.replace(
            authored.endless(),
            world_id=version.world_id,
            snapshot_id=version.source_snapshot_id,
        ),
        version=version,
        arrival=arrival,
        input_seq=input_seq,
        dependency_refs=(),
        availability="available",
        unavailable_reason=None,
        reviewed_affordances=square.REGISTRY,
        segment_blocked=segment_blocked,
        standing=square.STANDING,
        made_kinds=made_kinds,
    )


def pinned_arrival() -> ArrivalDescriptor:
    """An opening pose pinned to a photograph of the starter's version, as a made world's is."""
    return ArrivalDescriptor.model_validate(
        {
            "profile": "exulanica.arrival-descriptor/v1",
            "presentation_policy": "exulanica.arrival-presentation/v1",
            "region_id": "region:starter",
            "position_local_mm": [0, 0, 2_000],
            "forward_local_millionths": [0, 0, -1_000_000],
            "source": {
                "profile": "exulanica.arrival-photograph-pin/v1",
                "world_id": authored.WORLD,
                "version_id": str(authored.VERSION),
                "source_snapshot_id": str(authored.SNAPSHOT),
                "region_id": "region:starter",
                "capture_id": str(uuid.UUID(int=0xCA)),
            },
        }
    )


def _origin(grant_id: uuid.UUID) -> dict[str, Any]:
    return {
        "profile": "exulanica.origin/v1",
        "class": "crossed",
        "by": {
            "kind": "program",
            "bridge": BRIDGE,
            "adapter_version": "0.1.0",
            "mapping_sha256": "b" * 64,
            "grant_id": str(grant_id),
        },
        "sources": [],
        "licence": {
            "spdx": "CC0-1.0",
            "verdict": "SHIP",
            "attribution": None,
            "share_alike": False,
            "licence_url": None,
            "licence_text_sha256": None,
        },
        "authors": [],
        "lineage": {"ingredients": [], "receipts": [], "translation_manifest_sha256": "c" * 64},
        "distribution": "public",
    }


def reference(kind: str, version: int) -> dict[str, Any]:
    return dict(shipped_thing_kinds()[(kind, version)].reference())


def arrival(
    index: int,
    *,
    kind: Mapping[str, Any] | None = None,
    carried: Sequence[Mapping[str, Any]] = (),
    gate: str | None = None,
    grant_id: uuid.UUID = GRANT,
    decided_by: str | None = None,
    may_carry_out: bool = False,
    carries_out: Sequence[str] | None = None,
) -> Crossing:
    """The ``index``th arrival a door hands over: a visitor, by default of the shipped visitor
    kind, under the test grant, stating who decides for it only when ``decided_by`` is given, that
    it may carry the world's things out only when ``may_carry_out`` is, and which kinds only when
    ``carries_out`` is."""
    arrival_id = uuid.uuid5(grant_id, f"arrival:{index}")
    document = {
        "profile": ARRIVAL_PROFILE,
        "arrival_id": str(arrival_id),
        "thing_id": str(uuid.uuid5(grant_id, f"thing:{index}")),
        "kind": dict(kind or reference("visitor", 1)),
        "origin": _origin(grant_id),
        "translation_manifest_sha256": "c" * 64,
        "carried": [dict(held) for held in carried],
        "grant_id": str(grant_id),
        "gate": gate,
    }
    if decided_by is not None:
        document["decided_by"] = decided_by
    if may_carry_out:
        document["may_carry_out"] = True
    if carries_out is not None:
        document["carries_out"] = list(carries_out)
    return Crossing(arrival_id, document)


def departure(
    thing_id: str, index: int, *, reason: str = "sent_away", called_by: str | None = None
) -> Crossing:
    """The ``index``th departure a door hands over: the world's owner sending its visitor away by
    default, its player calling it home where ``called_by`` is ``player``."""
    departure_id = uuid.uuid5(GRANT, f"departure:{index}")
    return Crossing(
        departure_id,
        {
            "profile": DEPARTURE_PROFILE,
            "departure_id": str(departure_id),
            "thing_id": thing_id,
            "reason": reason,
            **({"called_by": called_by} if called_by is not None else {}),
        },
    )


class MemoryCrossings:
    """A door's crossings kept in memory: handed over in order, each consumed by one minute once,
    as :class:`exulanica.world.crossings.CrossingStream` asks."""

    def __init__(self) -> None:
        self.handed: dict[uuid.UUID, list[Crossing]] = {}
        self.bound: dict[uuid.UUID, list[ConsumedCrossing]] = {}

    def hand(self, society_id: uuid.UUID, crossing: Crossing) -> None:
        self.handed.setdefault(society_id, []).append(crossing)

    def pending(self, connection, workspace_id, society_id, tick, *, limit) -> list[Crossing]:
        consumed = {each.crossing.crossing_id for each in self.bound.get(society_id, [])}
        waiting = [c for c in self.handed.get(society_id, []) if c.crossing_id not in consumed]
        return waiting[:limit]

    def bind(self, connection, workspace_id, society_id, tick, bound: Sequence[BoundCrossing]):
        by_id = {c.crossing_id: c for c in self.handed.get(society_id, [])}
        held = self.bound.setdefault(society_id, [])
        for each in bound:
            assert each.crossing_id not in {taken.crossing.crossing_id for taken in held}
            held.append(ConsumedCrossing(tick, by_id[each.crossing_id], each))

    def consumed(self, connection, workspace_id, society_id) -> list[ConsumedCrossing]:
        return list(self.bound.get(society_id, []))
