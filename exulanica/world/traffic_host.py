"""A world's traffic: its road records read where the world states them, and windows of episodes.

The traffic simulation (:mod:`exulanica.traffic`) knows nothing of worlds, and the movement package
may not import it, so this host sits above both. It owns what traffic needs and no module below
may hold: the road source, the fleet, the trips and the episodes' receipts.

**The road source.** Traffic reads a world's city road records, keyed by the world and its
version, through one function per kind of world that states them:

- :func:`generated_tile_roads`, a generated city a development preview draws: the current bake of
  every tile of its ``world_seed``, each container read from the tile store, held to its digest and
  checked again under the final read check, and every record its header carries (owned and halo)
  merged by identity, where two copies of one record must agree. The world is the seed; its
  version is the digest over the tiles' coordinates and container digests, so a rebake is a new
  version. A tile is read, never delivered, so no tile quota is spent;
- :func:`saved_world_roads`, a saved world: the records its snapshot states, read through the
  one interface a generated world's records are read by (``town_records``), which generates them
  again from the world's receipt and holds them to its output digest. The world is the saved
  world; its version is the receipt's digest, so every version of one world drives the same
  traffic, and a world generated again under other records is other traffic. Nothing is read from
  the store. A world whose snapshot states no records, or whose records state no lane, is refused
  as ``roads_not_stated``: the rule is the world's records, never its kind or its name.

**The clock** is shared real time (:func:`traffic_clock`): second ``n`` is the ``n``\\ th second
since the Unix epoch, so every page showing a world shows its vehicles in the same places.

**The work** is off the request's thread: whole episodes computed in a worker process of their own
(:class:`TrafficEpisodes`, the episode worker bound to the roads module), kept by the input's
digest, the next asked for ahead of need. A request's own work is its window cut from them.
"""

from __future__ import annotations

import hashlib
import json
import struct
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from concurrent.futures import Executor
from typing import Any, Final

import psycopg

from exulanica.canonical import canonical_json
from exulanica.db.read_check import final_read_check
from exulanica.evidence.blob import BlobId
from exulanica.grammar import shapes
from exulanica.grammar.grammars.city import CITY_SHAPES_BY_TYPE
from exulanica.grammar.grammars.city.descriptor import CITY_GENERATING_VERSIONS, CITY_GRAMMAR_ID
from exulanica.grammar.grammars.city.roads import LaneRecord
from exulanica.movement.flight_episodes import watch_parent
from exulanica.world.baked_tiles import BakedTile, BakedTileRepository, TileBytesMissing
from exulanica.world.episode_worker import (
    EPISODE_LIMIT,
    QUEUE_LIMIT,
    WAIT_SECONDS,
    EpisodeWorker,
    Line,
    worker_pool,
)
from exulanica.world.generated_worlds import generation_receipt, states_records, town_records
from exulanica.world.traffic_episodes import (
    EPISODE,
    PackedTrafficEpisode,
    TrafficInput,
    TrafficRefused,
    check_request,
    compute_episode,
    road_records,
    traffic_input,
    window_of,
    wire,
)

__all__ = [
    "TrafficEpisodes",
    "TrafficWorkerUnavailable",
    "close_traffic_worker",
    "generated_tile_roads",
    "saved_world_roads",
    "served_window",
    "traffic_clock",
    "traffic_process_pool",
]

#: A container's layout, as the tessellator writes it (``web/packages/loom-tess/README.md``): four
#: magic bytes, the header's length as a little-endian 32-bit integer, then the header, canonical
#: JSON, which carries every record the tile's document did.
_MAGIC: Final = b"OWD3"
_HEADER_LENGTH: Final = struct.Struct("<I")
_CONTAINER_PROFILE: Final = "exulanica.owd/v3"
_SHAPES_BY_KIND: Final = {shape.kind: shape for shape in CITY_SHAPES_BY_TYPE.values()}
_TILE_KIND: Final = "city.tile"
#: Composed inputs kept, by everything they are made from; a page reads one world at a time.
_INPUT_LIMIT: Final = 8


class TrafficWorkerUnavailable(TrafficRefused):
    """The worker process died, or did not finish an episode in time: a server failure, retried."""

    def __init__(self, detail: str) -> None:
        super().__init__("traffic_worker_unavailable", detail)

    def __reduce__(self) -> tuple[Any, ...]:
        return (type(self), (self.detail,))


def traffic_process_pool() -> Executor:
    """The traffic's own worker process, apart from the flight's, so a world's network compiling
    never holds up a bird."""
    return worker_pool(watch_parent)


class _Roads:
    """The roads module, as the episode worker reads a module."""

    subject: Final = "traffic"
    episode_steps: Final = EPISODE
    refusal: Final = TrafficWorkerUnavailable
    compute: Final = staticmethod(compute_episode)

    def check(self, from_step: int, steps: int) -> None:
        check_request(from_step, steps)

    def digest(self, value: TrafficInput) -> str:
        return value.sha256

    def line(self, value: TrafficInput) -> Line:
        return (value.world_id, value.version_id)

    def wire(self, value: TrafficInput) -> dict[str, Any]:
        return wire(value)

    def window(
        self,
        value: TrafficInput,
        episodes: dict[int, PackedTrafficEpisode],
        from_step: int,
        steps: int,
    ) -> dict[str, Any]:
        return window_of(value, episodes, from_step, steps)


class TrafficEpisodes(EpisodeWorker[TrafficInput, PackedTrafficEpisode]):
    """Traffic episodes one worker computes, kept and cut into windows; safe to share between
    threads."""

    def __init__(
        self,
        executor: Callable[[], Executor] = traffic_process_pool,
        *,
        limit: int = EPISODE_LIMIT,
        queue_limit: int = QUEUE_LIMIT,
        wait_seconds: float = WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(
            _Roads(),
            executor,
            limit=limit,
            queue_limit=queue_limit,
            wait_seconds=wait_seconds,
            clock=clock,
        )


# -- the road source of a generated city ---------------------------------------------------------


def _container(repository: BakedTileRepository, tile: BakedTile) -> bytes:
    """A served tile's stored bytes, held to their digest and checked again under the final read
    check; nothing is delivered and nothing charged."""
    served = repository.servable(tile.baked_tile_id)
    data = repository.store.get(BlobId(bytes.fromhex(served.container_sha256)))
    if hashlib.sha256(data).hexdigest() != served.container_sha256:
        raise TileBytesMissing(f"baked tile {tile.baked_tile_id}'s bytes are not what it records")
    with final_read_check(
        repository.connection, not_idle="a baked tile is read only on an idle connection"
    ):
        now = repository.read(tile.baked_tile_id)
    if now.state != "baked" or now.container_sha256 != served.container_sha256:
        raise TrafficRefused(
            "roads_unavailable", f"baked tile {tile.baked_tile_id} changed while it was read"
        )
    return data


def _header(data: bytes, what: str) -> dict[str, Any]:
    if data[: len(_MAGIC)] != _MAGIC or len(data) < len(_MAGIC) + _HEADER_LENGTH.size:
        raise TrafficRefused("roads_unavailable", f"{what} is not a tile container")
    (length,) = _HEADER_LENGTH.unpack_from(data, len(_MAGIC))
    start = len(_MAGIC) + _HEADER_LENGTH.size
    header = json.loads(data[start : start + length])
    if not isinstance(header, dict) or header.get("profile") != _CONTAINER_PROFILE:
        raise TrafficRefused("roads_unavailable", f"{what} is not a {_CONTAINER_PROFILE} container")
    return header


_inputs: OrderedDict[tuple[Any, ...], TrafficInput] = OrderedDict()
_inputs_lock = threading.Lock()


def generated_tile_roads(repository: BakedTileRepository, world_seed: str) -> TrafficInput:
    """The road records of the generated city ``world_seed``, from the current bake of each of its
    tiles, keyed by the seed and the digest of those bakes; ``roads_not_stated`` when no tile of it
    is stored, ``roads_unavailable`` when a tile cannot be read as one city at one version."""
    tiles = [tile for tile in repository.tiles_of_world(world_seed) if tile.state == "baked"]
    if not tiles:
        raise TrafficRefused("roads_not_stated", f"no baked tile of world {world_seed} is stored")
    version = hashlib.sha256(
        canonical_json(
            sorted([tile.tile_x, tile.tile_y, tile.lod, tile.container_sha256] for tile in tiles)
        )
    ).hexdigest()
    key = (world_seed, version)
    with _inputs_lock:
        found = _inputs.get(key)
        if found is not None:
            _inputs.move_to_end(key)
            return found
    records: dict[str, tuple[bytes, object]] = {}
    pins: set[tuple[str, int, str]] = set()
    for tile in sorted(tiles, key=lambda item: (item.lod, item.tile_y, item.tile_x)):
        what = f"baked tile {tile.baked_tile_id}"
        header = _header(_container(repository, tile), what)
        for grammar in header["grammars"]:
            pins.add(
                (grammar["grammar_id"], grammar["grammar_version"], grammar["subject_identity"])
            )
        for row in header["records"]:
            if row["kind"] == _TILE_KIND:
                continue
            shape = _SHAPES_BY_KIND.get(row["kind"])
            if shape is None:
                raise TrafficRefused("roads_unavailable", f"{what} carries a {row['kind']} record")
            payload = {"kind": row["kind"], "version": row["version"], "fields": row["fields"]}
            record = shapes.read_record(payload, shape, f"{what} {row['identity']}")
            stated = canonical_json(payload)
            earlier = records.get(row["identity"])
            if earlier is not None and earlier[0] != stated:
                raise TrafficRefused(
                    "roads_unavailable",
                    f"record {row['identity']} is stated two ways by the world's tiles",
                )
            records[row["identity"]] = (stated, record)
    if len(pins) != 1:
        raise TrafficRefused(
            "roads_unavailable", f"world {world_seed}'s tiles pin {sorted(pins)}, not one city"
        )
    [(grammar_id, grammar_version, city_identity)] = pins
    if grammar_id != CITY_GRAMMAR_ID or grammar_version not in CITY_GENERATING_VERSIONS:
        raise TrafficRefused(
            "roads_unavailable",
            f"world {world_seed} is {grammar_id} version {grammar_version}, which traffic "
            "does not read",
        )
    made = traffic_input(
        world_id=world_seed,
        version_id=version,
        city_identity=city_identity,
        grammar_version=grammar_version,
        records=road_records([record for _, record in records.values()]),
    )
    with _inputs_lock:
        _inputs[key] = made
        _inputs.move_to_end(key)
        while len(_inputs) > _INPUT_LIMIT:
            _inputs.popitem(last=False)
    return made


# -- the road source of a saved world ------------------------------------------------------------


def saved_world_roads(
    connection: psycopg.Connection, workspace_id: uuid.UUID, world_id: str, snapshot_id: uuid.UUID
) -> TrafficInput:
    """The road records a saved world's snapshot states, keyed by the world and its receipt.

    ``roads_not_stated`` when the snapshot states no records read through ``town_records`` or its
    records state no lane: a world made from a world kind is refused so before anything is
    generated (its roads are drawn as surfaces nobody drives, and its records are generated only in
    the kind worker). A world whose receipt no longer generates its records raises
    ``InvalidStructuralData``, named by the reader (``unreadable_reason``).
    """
    if not states_records(connection, workspace_id, world_id, snapshot_id):
        raise TrafficRefused(
            "roads_not_stated", f"world {world_id} states no records, so no roads to drive"
        )
    # An input made from this receipt is answered as it is. Generating a town's records again
    # takes seconds, and the records kept (``town_records``) are fewer than the inputs kept here, so
    # a host reading more towns in turn than records are kept would otherwise generate each town
    # again at every read. Within one process the records a receipt generates do not change.
    receipt_sha256, _receipt = generation_receipt(connection, workspace_id, world_id, snapshot_id)
    key = ("saved", str(workspace_id), world_id, receipt_sha256)
    with _inputs_lock:
        found = _inputs.get(key)
        if found is not None:
            _inputs.move_to_end(key)
            return found
    generated = town_records(connection, workspace_id, world_id, snapshot_id)
    records = road_records(generated.records)
    if not any(isinstance(record, LaneRecord) for record in records):
        raise TrafficRefused("roads_not_stated", f"world {world_id}'s records state no lane")
    grammar = generated.receipt["grammar"]
    made = traffic_input(
        world_id=world_id,
        version_id=generated.receipt_sha256,
        city_identity=str(generated.receipt["subject_identity"]),
        grammar_version=int(grammar["grammar_version"]),
        records=records,
    )
    with _inputs_lock:
        _inputs[key] = made
        _inputs.move_to_end(key)
        while len(_inputs) > _INPUT_LIMIT:
            _inputs.popitem(last=False)
    return made


# -- the clock and the episodes ------------------------------------------------------------------


def _now_ms() -> int:
    """This server's clock: milliseconds since the Unix epoch."""
    return time.time_ns() // 1_000_000


def traffic_clock() -> int:
    """The traffic's shared clock read now: the second every page showing a world is at."""
    return _now_ms() // 1000


#: This server's traffic episodes and the worker process computing them, started at the first read.
_episodes = TrafficEpisodes()


def served_window(value: TrafficInput, from_second: int, seconds: int) -> dict[str, Any]:
    """The window of ``seconds`` seconds from ``from_second``, cut from episodes the worker
    computes; the request's thread computes no second. Raises :class:`TrafficWorkerUnavailable`
    when the worker has stopped or does not finish in time."""
    return _episodes.window(value, from_second, seconds)


def traffic_episodes() -> TrafficEpisodes:
    """This server's episodes and their worker."""
    return _episodes


def close_traffic_worker() -> None:
    """Stop the worker process; the server's lifespan calls this as it ends."""
    _episodes.close()


def world_line(value: TrafficInput) -> Mapping[str, str]:
    """The keys a window names its world by."""
    return {"world_id": value.world_id, "version_id": value.version_id}
