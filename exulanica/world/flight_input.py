"""A saved world's flight: its air, its solids, its perches and the flyers its objects host.

The flight module (:mod:`exulanica.movement.flight`) knows nothing of worlds. This module reads a
world version the way the society does and passes the module plain data:

- **the volume** over the ground the world's own structural snapshot states, read by the one
  reading the society uses (:func:`exulanica.world.society_authored_ground.read_authored_ground`):
  the ground's extent where it states one, the society's declared area where it states none, from
  the ground's elevation to the flight module's declared ceiling;
- **the solids**, every part of every placed object, from the world object catalog's recipe for
  the object's kind, turned, scaled and placed as the object stands; an object that moves along a
  bounded path is solid everywhere its path takes it;
- **the perches** each placed kind declares, placed with it;
- **the flyers** each placed kind hosts, each starting every episode on a perch of its host: an
  object's perches are one pool, which the widest kinds it hosts draw from first.

The air is grown around every part by half the widest flying kind's span, so a flyer whose point
keeps to free cells keeps its body out of every object. A grid of more than the module's
``max_cells`` cells or air built from more than its ``max_parts`` parts is refused by name,
``flight_world_too_large``.

Objects are decided one by one, as the society's second composition decides them. An object the
flight cannot state the geometry of (an asset with no catalog recipe, a behaviour with no rule, a
transform no writer produces, another region) makes the flight unavailable, named, because a
solid it cannot place is air a flyer might cross. An object whose perches cannot start the flyers
it hosts hosts none, and the input says why; the rest of the world flies.

A flight is derived, never stored: the same version gives the same input and the same flight.
Every flyer's identity derives from its world, its host object, its kind and its place among that
object's flyers, so the same bird lives in the same tree from one version to the next. Composed
inputs are kept in process by everything they are made from, so a page reading minute after minute
composes its world's air once; the windows' resume states and the inputs are shared between
request threads under a lock.
"""

from __future__ import annotations

import hashlib
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from typing import Any, Final

from exulanica.movement.air import (
    AirVolume,
    PartBox,
    PerchSite,
    Placement,
    Solid,
    build_occupancy,
    perch_column,
    placed_point,
)
from exulanica.movement.fixed import ceil_div
from exulanica.movement.flight import (
    FLIGHT_MODULE,
    FlightInput,
    FlightRefused,
    Flyer,
    advance_flight,
    check_request,
    flight_input,
    state_at,
    window_from,
)
from exulanica.world.authored_delta import AlternateVersion
from exulanica.world.errors import InvalidStructuralData, UnknownWorldResource
from exulanica.world.flight_kinds import FlightKindCatalog, flight_kind_catalog
from exulanica.world.object_catalog import (
    MarkerRecipe,
    WorldObjectCatalog,
    WorldObjectKind,
    world_object_catalog,
)
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.society_authored_ground import SocietyGround, read_authored_ground

__all__ = [
    "FLIGHT_NAMESPACE",
    "compose_flight_input",
    "saved_world_flight",
    "served_window",
]

#: The namespace every flyer identity is derived in.
FLIGHT_NAMESPACE: Final = uuid.uuid5(uuid.NAMESPACE_URL, "https://exulanica.invalid/flight/v1")
_CELL: Final = FLIGHT_MODULE.value("cell_mm")
_CEILING: Final = FLIGHT_MODULE.value("ceiling_mm")
_MAX_CELLS: Final = FLIGHT_MODULE.value("max_cells")
_MAX_PARTS: Final = FLIGHT_MODULE.value("max_parts")
#: The one behaviour whose extent the flight can state: it moves an object along one axis of its
#: region from where it was placed and back, so its parts are solid over that whole travel.
_BOUNDED_PATH: Final = ("motion.bounded-path", 1)
_MAX_TRANSFORM: Final = 10**9


def _volume(ground: SocietyGround) -> AirVolume:
    """The largest whole-cell box inside the ground's area, from the ground to the ceiling."""
    area = ground.area
    half_x = area.half_width_mm // _CELL * _CELL
    half_z = area.half_depth_mm // _CELL * _CELL
    return AirVolume(
        source=area.source,
        min_x_mm=area.centre_x_mm - half_x,
        max_x_mm=area.centre_x_mm + half_x,
        min_z_mm=area.centre_z_mm - half_z,
        max_z_mm=area.centre_z_mm + half_z,
        ground_mm=ground.elevation_mm,
        ceiling_mm=ground.elevation_mm + _CEILING,
        cell_mm=_CELL,
    )


def _boxes(kind: WorldObjectKind) -> tuple[PartBox, ...]:
    """Each part of a kind as its bounds in the kind's own frame."""
    recipe = kind.recipe
    if isinstance(recipe, MarkerRecipe):
        half_x, half_y = recipe.size_x_mm // 2, recipe.size_y_mm // 2
        return (
            PartBox(
                -half_x,
                recipe.size_x_mm - half_x,
                -half_y,
                recipe.size_y_mm - half_y,
                0,
                recipe.size_z_mm,
            ),
        )
    boxes = []
    for part in recipe.parts:
        form = part.form
        low_x = form.offset_x_mm - form.size_x_mm // 2
        low_y = form.offset_y_mm - form.size_y_mm // 2
        boxes.append(
            PartBox(
                low_x,
                low_x + form.size_x_mm,
                low_y,
                low_y + form.size_y_mm,
                form.offset_z_mm,
                form.offset_z_mm + form.size_z_mm,
            )
        )
    return tuple(boxes)


def _travel(parameters: Mapping[str, Any]) -> tuple[int, int, int]:
    """Where a bounded path's far end lies from where the object was placed, or a refusal."""
    travel = parameters.get("travel_mm")
    axis = parameters.get("axis")
    if type(travel) is not int or not 0 <= travel <= _MAX_TRANSFORM or axis not in ("x", "y", "z"):
        raise ValueError("unreadable bounded path")
    return (
        travel if axis == "x" else 0,
        travel if axis == "y" else 0,
        travel if axis == "z" else 0,
    )


def _unavailable(code: str, object_id: str) -> FlightRefused:
    return FlightRefused("flight_unavailable", f"{code}:{object_id}")


def compose_flight_input(
    *,
    world_id: str,
    version: AlternateVersion,
    ground: SocietyGround,
    asset_keys: Mapping[str, str],
    objects: WorldObjectCatalog | None = None,
    flying: FlightKindCatalog | None = None,
) -> FlightInput:
    """The flight over one saved world version, or a refusal naming the object it could not read.

    ``asset_keys`` maps each reviewed asset's content digest to its registry key, as the reviewed
    registry holds them.
    """
    if version.world_id != world_id or ground.world_id != world_id:
        raise FlightRefused("flight_unavailable", "the version or its ground is another world's")
    catalog = world_object_catalog() if objects is None else objects
    flyers_catalog = flight_kind_catalog() if flying is None else flying
    kinds_by_asset = catalog.by_asset_key()
    flying_kinds = flyers_catalog.by_key()
    volume = _volume(ground)
    nx, ny, nz = volume.shape
    if nx * ny * nz > _MAX_CELLS:
        raise FlightRefused(
            "flight_world_too_large",
            f"the air over this ground is {nx * ny * nz} cells; at most {_MAX_CELLS}",
        )
    solids: list[Solid] = []
    placed: list[tuple[str, WorldObjectKind, Placement, bool]] = []
    for obj in sorted(version.objects, key=lambda value: value.object_id):
        if obj.removed:
            continue
        if obj.region_id != ground.region_id:
            raise _unavailable("unregistered_object_region", obj.object_id)
        kind = kinds_by_asset.get(asset_keys.get(obj.asset_sha256, ""))
        if kind is None:
            raise _unavailable("unknown_object_geometry", obj.object_id)
        transform = obj.transform
        numbers = (
            transform.x_mm,
            transform.y_mm,
            transform.z_mm,
            transform.yaw_microradians,
            transform.scale_milli,
        )
        if (
            any(type(value) is not int or abs(value) > _MAX_TRANSFORM for value in numbers)
            or transform.scale_milli < 1
        ):
            raise _unavailable("unsupported_object_transform", obj.object_id)
        placement = Placement(*numbers)
        travel = (0, 0, 0)
        if obj.behaviour is not None:
            key = (obj.behaviour.behaviour_key, obj.behaviour.behaviour_version)
            if key != _BOUNDED_PATH:
                raise _unavailable("unsupported_active_behaviour", obj.object_id)
            try:
                travel = _travel(obj.behaviour.parameters)
            except ValueError:
                raise _unavailable("unsupported_active_behaviour", obj.object_id) from None
        solids.extend(Solid(obj.object_id, box, placement, travel) for box in _boxes(kind))
        placed.append((obj.object_id, kind, placement, travel != (0, 0, 0)))
        if len(solids) > _MAX_PARTS:
            raise FlightRefused(
                "flight_world_too_large",
                f"this world's objects have more than {_MAX_PARTS} parts to build its air from",
            )
    clearance = max(
        (ceil_div(flyer_kind.figures.body_span_mm, 2) for flyer_kind in flyers_catalog.kinds),
        default=0,
    )
    occupancy = build_occupancy(volume, solids, clearance_mm=clearance)
    perches: list[PerchSite] = []
    flyers: list[Flyer] = []
    unplaced: list[dict[str, Any]] = []
    for object_id, kind, placement, moves in placed:
        sites = []
        for index, perch in enumerate(kind.perches):
            point = placed_point(perch.position_mm, placement)
            span = perch.span_mm * placement.scale_milli // 1000
            columns, refused = {}, {}
            for flyer_kind in flyers_catalog.kinds:
                figures = flyer_kind.figures
                if moves:
                    refused[flyer_kind.key] = "perch_moves"
                    continue
                if figures.body_span_mm > span:
                    refused[flyer_kind.key] = "perch_too_narrow"
                    continue
                column = perch_column(
                    occupancy,
                    point,
                    object_id=object_id,
                    approach_height_mm=figures.approach_height_mm,
                    min_altitude_mm=figures.min_altitude_mm,
                    max_altitude_mm=figures.max_altitude_mm,
                )
                if isinstance(column, str):
                    refused[flyer_kind.key] = column
                else:
                    columns[flyer_kind.key] = column
            sites.append(
                PerchSite(f"{object_id}:perch:{index}", object_id, point, span, columns, refused)
            )
        perches.extend(sites)
        # One pool of homes an object: the widest kinds it hosts choose first, since a perch wide
        # enough for a wide kind is wide enough for a narrower one.
        taken: set[str] = set()
        hosts = sorted(
            kind.hosts, key=lambda host: (-flying_kinds[host.kind].figures.body_span_mm, host.kind)
        )
        for host in hosts:
            usable = [
                site for site in sites if host.kind in site.columns and site.perch_id not in taken
            ]
            if len(usable) < host.count:
                unplaced.append(
                    {
                        "object_id": object_id,
                        "kind": host.kind,
                        "count": host.count,
                        "reason": "home_perch_unusable",
                    }
                )
                continue
            for index in range(host.count):
                taken.add(usable[index].perch_id)
                flyers.append(
                    Flyer(
                        flyer_id=str(
                            uuid.uuid5(
                                FLIGHT_NAMESPACE, f"{world_id}:{object_id}:{host.kind}:{index}"
                            )
                        ),
                        kind=host.kind,
                        home_perch_id=usable[index].perch_id,
                        ordinal=len(flyers),
                    )
                )
    seed = hashlib.sha256(
        f"exulanica-flight/v1:{world_id}:{version.version_id}".encode()
    ).hexdigest()
    return flight_input(
        world_id=world_id,
        version_id=str(version.version_id),
        seed=seed,
        occupancy=occupancy,
        perches=perches,
        kinds={key: flying_kinds[key].figures for key in sorted(flying_kinds)},
        flyers=flyers,
        solids=solids,
        unplaced=unplaced,
    )


#: Composed inputs by everything they are made from, most recently used last.
_INPUT_LIMIT: Final = 16
_inputs: OrderedDict[tuple[Any, ...], FlightInput] = OrderedDict()
#: The state each recent window ended on, by input digest and step, so a page asking for the
#: next minute costs that minute and not the episode before it. Bounded, in process, and exact:
#: a state here is the one :func:`state_at` would compute.
_RESUME_LIMIT: Final = 64
_resume: OrderedDict[tuple[str, int], dict[str, Any]] = OrderedDict()
#: Request threads share both caches; each is read and written under this lock, never computed in.
_lock = threading.Lock()


def cached_input(key: tuple[Any, ...], compose: Callable[[], FlightInput]) -> FlightInput:
    """The input composed for ``key``, composing it the first time it is asked for."""
    with _lock:
        found = _inputs.get(key)
        if found is not None:
            _inputs.move_to_end(key)
            return found
    made = compose()
    with _lock:
        _inputs[key] = made
        _inputs.move_to_end(key)
        while len(_inputs) > _INPUT_LIMIT:
            _inputs.popitem(last=False)
    return made


def saved_world_flight(
    repository: WorldObjectRepository,
    version_id: uuid.UUID,
    asset_keys: Mapping[str, str],
) -> FlightInput:
    """The flight over a saved world version the repository's world holds, read as the society
    reads it: the version, then the ground its source snapshot states.

    The input is composed once for each version state, snapshot, registry and catalogs, and kept.
    An unknown version is ``UnknownWorldResource``; a ground the society has no rule for, or an
    object the flight cannot place, is a ``FlightRefused`` naming it.
    """
    version = repository.version(version_id, with_availability=False)
    key = (
        repository.workspace_id,
        repository.world_id,
        str(version.version_id),
        version.state_sha256,
        str(version.source_snapshot_id),
        hashlib.sha256(repr(sorted(asset_keys.items())).encode()).hexdigest(),
        world_object_catalog().sha256,
        flight_kind_catalog().sha256,
    )

    def compose() -> FlightInput:
        try:
            ground = read_authored_ground(
                repository.connection,
                repository.workspace_id,
                repository.world_id,
                version.source_snapshot_id,
            )
        except InvalidStructuralData as error:
            raise FlightRefused(
                "flight_unavailable", f"authored ground is unreadable: {error}"
            ) from error
        if ground is None:
            raise UnknownWorldResource("no such structural snapshot")
        return compose_flight_input(
            world_id=repository.world_id, version=version, ground=ground, asset_keys=asset_keys
        )

    return cached_input(key, compose)


def served_window(flight: FlightInput, from_step: int, steps: int) -> dict[str, Any]:
    """:func:`exulanica.movement.flight.flight_window`, resuming from where a recent window ended.

    A cold request computes from its episode's genesis, at most one episode of steps.
    """
    check_request(from_step, steps)
    with _lock:
        start = _resume.pop((flight.sha256, from_step), None)
    if start is None:
        start = state_at(flight, from_step)
    window, last = window_from(flight, start, steps)
    following = advance_flight(flight, last)
    with _lock:
        _resume[(flight.sha256, following["step"])] = following
        while len(_resume) > _RESUME_LIMIT:
            _resume.popitem(last=False)
    return window
