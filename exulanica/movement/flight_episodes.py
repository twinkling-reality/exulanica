"""Whole flight episodes: what the flight's worker process computes, and the windows cut from them.

A flight is a function of its input and its step (:mod:`exulanica.movement.flight`), and every
episode starts from its own genesis, so an episode can be computed whole, once, anywhere, and any
window of steps read from the episodes it spans. This module holds the three parts of that:

- the **wire form** of an input (:func:`wire`): integers, text, bytes, lists and mappings, which a
  worker process receives and :func:`from_wire` turns back into the same input, refusing one whose
  digest differs, so the process never computes over anything but the input the server composed;
- :func:`compute_episode`, the worker's job: an episode's steps from its genesis, packed as 32-bit
  integers for each flyer and field, and the flyers not home at its last step;
- :func:`window_of`, a served window read from the packed episodes that span it, equal to the one
  :func:`exulanica.movement.flight.flight_window` computes.

Pure: no connection, no store, no world, no process of its own
(:mod:`exulanica.world.flight_worker` runs the job in one).
"""

from __future__ import annotations

import multiprocessing
import multiprocessing.connection
import signal
import sys
import threading
from array import array
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from exulanica.movement.air import (
    AirVolume,
    Column,
    PartBox,
    PerchSite,
    Placement,
    Solid,
    occupancy_from_cells,
)
from exulanica.movement.flight import (
    FLIGHT_MODULE,
    STATES,
    WINDOW_PROFILE,
    FlightInput,
    FlightKind,
    FlightRefused,
    Flyer,
    check_request,
    flight_input,
    genesis,
    window_from,
)
from exulanica.movement.registry import FLIGHT

__all__ = [
    "FIELDS",
    "PackedEpisode",
    "compute_episode",
    "from_wire",
    "watch_parent",
    "window_of",
    "wire",
    "worker_report",
]

EPISODE: Final = FLIGHT_MODULE.value("episode_steps")
#: The samples a window holds for each flyer, in order, and how many integers each takes a step.
FIELDS: Final = (
    ("position_mm", 3),
    ("velocity_mm_s", 3),
    ("turn_mm_s2", 1),
    ("state", 1),
    ("flap", 1),
    ("held", 1),
)
#: Packed samples are signed 32-bit integers: a position a volume holds, a speed and a turning
#: acceleration a kind's bounds admit all fit, and one that does not is refused, never wrapped.
_TYPECODE: Final = "i"
_BYTES: Final = array(_TYPECODE).itemsize
if _BYTES != 4:
    raise ImportError("this platform's C int is not 32 bits; the packing assumes it is")


@dataclass(frozen=True, slots=True)
class PackedEpisode:
    """One episode of one input: every flyer's samples, packed, and who was late home."""

    input_sha256: str
    episode: int
    #: For each flyer in the input's order, each field of :data:`FIELDS` as native 32-bit integers.
    flyers: tuple[tuple[bytes, ...], ...]
    #: The flyers not perching at home at the episode's last step, in the input's order.
    late_home: tuple[str, ...]

    @property
    def byte_size(self) -> int:
        return sum(len(field) for fields in self.flyers for field in fields)


# -- the wire form ------------------------------------------------------------------------------


def wire(flight: FlightInput) -> dict[str, Any]:
    """Plain data from which :func:`from_wire` rebuilds ``flight`` exactly."""
    volume = flight.volume
    return {
        "input_sha256": flight.sha256,
        "world_id": flight.world_id,
        "version_id": flight.version_id,
        "seed": flight.seed,
        "volume": {
            "source": volume.source,
            "min_x_mm": volume.min_x_mm,
            "max_x_mm": volume.max_x_mm,
            "min_z_mm": volume.min_z_mm,
            "max_z_mm": volume.max_z_mm,
            "ground_mm": volume.ground_mm,
            "ceiling_mm": volume.ceiling_mm,
            "cell_mm": volume.cell_mm,
        },
        "clearance_mm": flight.occupancy.clearance_mm,
        "cells": flight.occupancy.solid,
        "perches": [
            {
                "perch_id": perch.perch_id,
                "object_id": perch.object_id,
                "point_mm": tuple(perch.point_mm),
                "span_mm": perch.span_mm,
                "columns": {
                    kind: (column.approach_mm, column.own_cells, column.cells)
                    for kind, column in perch.columns.items()
                },
                "refused": dict(perch.refused),
            }
            for perch in flight.perches
        ],
        "kinds": {key: kind.document() for key, kind in flight.kinds.items()},
        "flyers": [
            (flyer.flyer_id, flyer.kind, flyer.home_perch_id, flyer.ordinal)
            for flyer in flight.flyers
        ],
        "solids": [
            (
                solid.object_id,
                (
                    solid.box.min_x_mm,
                    solid.box.max_x_mm,
                    solid.box.min_y_mm,
                    solid.box.max_y_mm,
                    solid.box.min_z_mm,
                    solid.box.max_z_mm,
                ),
                (
                    solid.placement.x_mm,
                    solid.placement.y_mm,
                    solid.placement.z_mm,
                    solid.placement.yaw_microradians,
                    solid.placement.scale_milli,
                ),
                tuple(solid.travel_mm),
            )
            for solid in flight.solids
        ],
        "unplaced": [dict(row) for row in flight.unplaced],
    }


def from_wire(data: Mapping[str, Any]) -> FlightInput:
    """The input :func:`wire` describes, checked: its grid's cells and its whole description must
    give the digests the server's input has, or it is refused."""
    volume = AirVolume(**data["volume"])
    occupancy = occupancy_from_cells(volume, data["cells"], clearance_mm=data["clearance_mm"])
    perches = [
        PerchSite(
            perch_id=row["perch_id"],
            object_id=row["object_id"],
            point_mm=tuple(row["point_mm"]),
            span_mm=row["span_mm"],
            columns={
                kind: Column(tuple(approach), tuple(map(tuple, own)), tuple(map(tuple, cells)))
                for kind, (approach, own, cells) in row["columns"].items()
            },
            refused=dict(row["refused"]),
        )
        for row in data["perches"]
    ]
    kinds = {
        key: FlightKind.checked(
            key, {name: value for name, value in document.items() if name != "key"}
        )
        for key, document in data["kinds"].items()
    }
    rebuilt = flight_input(
        world_id=data["world_id"],
        version_id=data["version_id"],
        seed=data["seed"],
        occupancy=occupancy,
        perches=perches,
        kinds=kinds,
        flyers=[Flyer(*row) for row in data["flyers"]],
        solids=[
            Solid(object_id, PartBox(*box), Placement(*placement), tuple(travel))
            for object_id, box, placement, travel in data["solids"]
        ],
        unplaced=data["unplaced"],
    )
    if rebuilt.sha256 != data["input_sha256"]:
        raise ValueError("the flight's wire form does not rebuild the input it names")
    return rebuilt


# -- an episode, computed and packed ------------------------------------------------------------


def compute_episode(data: Mapping[str, Any], episode: int) -> PackedEpisode:
    """Every step of ``episode`` of the input ``data`` describes, packed: the worker's job."""
    if type(episode) is not int or episode < 0:
        raise FlightRefused("flight_step_out_of_range", f"no episode {episode!r}")
    flight = from_wire(data)
    window, _ = window_from(flight, genesis(flight, episode), EPISODE)
    flyers = []
    for row in window["flyers"]:
        packed = []
        for name, _width in FIELDS:
            try:
                packed.append(array(_TYPECODE, row[name]).tobytes())
            except OverflowError:
                raise FlightRefused(
                    "flight_world_too_large",
                    f"a flyer's {name} leaves the 32-bit range its samples are served in",
                ) from None
        flyers.append(tuple(packed))
    return PackedEpisode(
        input_sha256=flight.sha256,
        episode=episode,
        flyers=tuple(flyers),
        late_home=tuple(late["flyer_id"] for late in window["late_home"]),
    )


# -- a window, cut from episodes ----------------------------------------------------------------


def window_of(
    flight: FlightInput, episodes: Mapping[int, PackedEpisode], from_step: int, steps: int
) -> dict[str, Any]:
    """The window of ``steps`` steps from ``from_step``, read from the packed ``episodes`` it spans:
    the window :func:`exulanica.movement.flight.flight_window` computes, sample for sample."""
    check_request(from_step, steps)
    end = from_step + steps
    spans = []
    for episode in range(from_step // EPISODE, (end - 1) // EPISODE + 1):
        packed = episodes.get(episode)
        if packed is None or packed.input_sha256 != flight.sha256:
            raise ValueError(f"episode {episode} of this input was not handed in")
        first = episode * EPISODE
        spans.append((packed, max(from_step, first) - first, min(end, first + EPISODE) - first))
    flyers = []
    for ordinal, flyer in enumerate(flight.flyers):
        row: dict[str, Any] = {"flyer_id": flyer.flyer_id, "kind": flyer.kind}
        for index, (name, width) in enumerate(FIELDS):
            values = array(_TYPECODE)
            for packed, low, high in spans:
                field = memoryview(packed.flyers[ordinal][index])
                values.frombytes(field[low * width * _BYTES : high * width * _BYTES])
            row[name] = values.tolist()
        flyers.append(row)
    late = [
        {"step": (packed.episode + 1) * EPISODE - 1, "flyer_id": flyer_id}
        for packed, _low, high in spans
        if high == EPISODE
        for flyer_id in packed.late_home
    ]
    return {
        "profile": WINDOW_PROFILE,
        "module": FLIGHT,
        "input_sha256": flight.sha256,
        "ground_mm": flight.volume.ground_mm,
        "step_ms": FLIGHT_MODULE.step_ms,
        "episode_steps": EPISODE,
        "from_step": from_step,
        "steps": steps,
        "states": list(STATES),
        "flyers": flyers,
        "late_home": late,
    }


def worker_report() -> dict[str, Any]:
    """The process answering and the ``exulanica`` modules it has loaded: a diagnostic a server or
    a test asks the flight's worker for, to see which process computes and what it has imported."""
    return {
        "pid": multiprocessing.current_process().pid,
        "modules": sorted(
            name for name in sys.modules if name == "exulanica" or name.startswith("exulanica.")
        ),
    }


def watch_parent() -> None:
    """In the flight's worker process: end it once the process that started it is gone.

    A server that stops cleanly stops its worker; one killed outright, or out of memory, cannot,
    and its worker would wait for work forever. The pool starts this in the worker: a thread waits
    on the parent's sentinel, which the operating system signals when the parent ends, however it
    ended, and then ends the worker the way a terminate would.
    """
    parent = multiprocessing.parent_process()
    if parent is None:
        return
    sentinel = parent.sentinel

    def watch() -> None:
        multiprocessing.connection.wait([sentinel])
        signal.raise_signal(signal.SIGTERM)

    threading.Thread(target=watch, name="flight-worker-parent", daemon=True).start()
