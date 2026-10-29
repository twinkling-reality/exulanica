"""PostgreSQL persistence and society-state hydration for 20 Hz real-time world rooms.

Connects :class:`~exulanica.world.realtime_runtime.RealtimeWorldRoom` to saved world versions
and societies in PostgreSQL:

1. **Hydration (:func:`hydrate_room_from_society_state`, :func:`hydrate_room_from_postgres`)**:
   - Reads a world version's society state (``inhabitants``, ``tick``, ``things``), its latest
     society input (``targets``, ``living.place.destinations``, ``navigation.nodes``) or generated
     town places, its living sessions (:func:`~exulanica.world.society_sessions.sessions_from`),
     and its recorded model / Door / player deciders (``world_society_model_choice``).
   - Builds an authoritative :class:`~exulanica.world.realtime_runtime.RealtimeWorldRoom` with
     integer-millimeter coordinates and deterministic AOI spatial hashing.
2. **Epoch checkpoints (:class:`RealtimeCheckpointRepository`)**:
   - Keeps :meth:`~exulanica.world.realtime_runtime.RealtimeWorldRoom.flush_epoch_checkpoint`
     envelopes (``exulanica.realtime-epoch-checkpoint/v1``: canonical ``state_sha256``, tick,
     positions, and applied/refused Tier 2 decision receipts) in this process, keyed by
     workspace, world and version, and verifies exact ``state_sha256`` round-trip restoration.
   - No table holds them. A table may only come from a migration, with its grants and a place in
     the workspace's erasure; this module once created one at run time, which only an owner
     connection could do and which no erasure reached, so a durable store waits for that migration.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from exulanica.canonical import canonical_json
from exulanica.world.deciders import decider as validate_decider
from exulanica.world.errors import UnknownWorldResource
from exulanica.world.realtime_runtime import (
    DEFAULT_CHECKPOINT_INTERVAL_TICKS,
    DEFAULT_SPEED_MM_PER_TICK,
    EPOCH_CHECKPOINT_PROFILE,
    SUBTICKS_PER_WORLD_MINUTE,
    AffordancePlace,
    EpochCheckpoint,
    RealtimeWorldRoom,
)
from exulanica.world.society_sessions import sessions_from

__all__ = [
    "RealtimeCheckpointRepository",
    "clear_in_memory_checkpoints",
    "default_generated_town_places",
    "hydrate_room_from_postgres",
    "hydrate_room_from_society_state",
]


# The process's checkpoints, keyed by (str(workspace_id), world_id, str(version_id)), held across
# requests and connections for as long as the process runs.
_PROCESS_CHECKPOINTS: dict[tuple[str, str, str], list[dict[str, Any]]] = {}


def clear_in_memory_checkpoints() -> None:
    """Clear the process-scoped checkpoint mirror (used by test teardown)."""
    _PROCESS_CHECKPOINTS.clear()


def _int_coord(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    return default


def _extract_xyz_mm(
    raw_pos: Any,
    *,
    fallback_x: int = 0,
    fallback_y: int = 0,
) -> tuple[int, int, int]:
    if isinstance(raw_pos, Sequence) and not isinstance(raw_pos, str | bytes):
        if len(raw_pos) >= 3:
            return (
                _int_coord(raw_pos[0], fallback_x),
                _int_coord(raw_pos[1], fallback_y),
                _int_coord(raw_pos[2], 0),
            )
        if len(raw_pos) == 2:
            return (
                _int_coord(raw_pos[0], fallback_x),
                _int_coord(raw_pos[1], fallback_y),
                0,
            )
    if isinstance(raw_pos, Mapping):
        return (
            _int_coord(raw_pos.get("x_mm", fallback_x), fallback_x),
            _int_coord(raw_pos.get("y_mm", raw_pos.get("z_mm", fallback_y)), fallback_y),
            _int_coord(raw_pos.get("z_mm", 0), 0),
        )
    return (fallback_x, fallback_y, 0)


def default_generated_town_places(seed: str = "exulanica-realtime-v1") -> list[AffordancePlace]:
    """Deterministic generated town places when hydrating a generated world without targets."""
    specs = (
        ("place-town-square", "town square bench", "bench", 8_000, 8_000, 8),
        ("place-market-north", "north market stall", "stall", 24_000, 8_000, 6),
        ("place-bakery-counter", "bakery counter", "shop", 8_000, 24_000, 4),
        ("place-harbor-steps", "harbor steps", "lookout", 24_000, 24_000, 8),
        ("place-lantern-well", "lantern courtyard well", "well", 16_000, 16_000, 6),
        ("place-east-garden", "east terrace garden", "garden", 36_000, 16_000, 6),
    )
    places: list[AffordancePlace] = []
    for place_id, label, kind, base_x, base_y, capacity in specs:
        jitter = int.from_bytes(
            hashlib.sha256(f"{seed}:place:{place_id}".encode()).digest()[:4], "big"
        )
        offset_x = (jitter % 1_000) - 500
        offset_y = ((jitter >> 10) % 1_000) - 500
        places.append(
            AffordancePlace(
                place_id=place_id,
                label=label,
                kind=kind,
                x_mm=base_x + offset_x,
                y_mm=base_y + offset_y,
                z_mm=0,
                capacity=capacity,
            )
        )
    return places


def _extract_places_from_input(
    society_input: Mapping[str, Any] | None,
    generated_places: Sequence[AffordancePlace | Mapping[str, Any]] | None,
    seed: str,
) -> list[AffordancePlace]:
    places: list[AffordancePlace] = []

    if generated_places:
        for idx, item in enumerate(generated_places):
            if isinstance(item, AffordancePlace):
                places.append(item)
            elif isinstance(item, Mapping):
                pid = str(item.get("place_id") or item.get("id") or f"gen-place-{idx:02d}")
                label = str(item.get("label") or item.get("name") or pid)
                kind = str(item.get("kind") or item.get("use_class") or "place")
                x_mm, y_mm, z_mm = _extract_xyz_mm(
                    item.get("position_mm") or item,
                    fallback_x=(idx + 1) * 6_000,
                    fallback_y=(idx + 1) * 4_000,
                )
                places.append(
                    AffordancePlace(
                        place_id=pid,
                        label=label,
                        kind=kind,
                        x_mm=x_mm,
                        y_mm=y_mm,
                        z_mm=z_mm,
                        capacity=int(item.get("capacity", 6)),
                        enabled=bool(item.get("enabled", True)),
                    )
                )

    if society_input is not None:
        nav = society_input.get("navigation")
        nodes_by_id: dict[str, tuple[int, int, int]] = {}
        if isinstance(nav, Mapping):
            for node in nav.get("nodes", ()):
                if isinstance(node, Mapping) and "node_id" in node:
                    nodes_by_id[str(node["node_id"])] = _extract_xyz_mm(node.get("position_mm"))

        for idx, target in enumerate(society_input.get("targets", ())):
            if not isinstance(target, Mapping):
                continue
            pid = str(
                target.get("target_id")
                or target.get("place_node_id")
                or target.get("object_id")
                or f"target-{idx:02d}"
            )
            node_id = str(target.get("place_node_id") or target.get("node_id") or "")
            if node_id in nodes_by_id:
                x_mm, y_mm, z_mm = nodes_by_id[node_id]
            else:
                x_mm, y_mm, z_mm = _extract_xyz_mm(
                    target.get("position_mm"),
                    fallback_x=(idx + 1) * 5_000,
                    fallback_y=((idx % 4) + 1) * 5_000,
                )
            label = str(
                target.get("label")
                or target.get("activity")
                or target.get("kind")
                or f"place {idx + 1}"
            )
            kind = str(target.get("activity") or target.get("kind") or "target")
            places.append(
                AffordancePlace(
                    place_id=pid,
                    label=label,
                    kind=kind,
                    x_mm=x_mm,
                    y_mm=y_mm,
                    z_mm=z_mm,
                    capacity=int(target.get("capacity", 4)),
                )
            )

        living = society_input.get("living")
        if isinstance(living, Mapping):
            place_block = living.get("place")
            if isinstance(place_block, Mapping):
                for idx, dest in enumerate(place_block.get("destinations", ())):
                    if not isinstance(dest, Mapping) or not dest.get("enabled", True):
                        continue
                    pid = str(dest.get("destination_id") or f"dest-{idx:02d}")
                    node_id = str(dest.get("node_id") or "")
                    if node_id in nodes_by_id:
                        x_mm, y_mm, z_mm = nodes_by_id[node_id]
                    else:
                        x_mm, y_mm, z_mm = _extract_xyz_mm(
                            dest.get("position_mm"),
                            fallback_x=(idx + 1) * 6_000,
                            fallback_y=((idx % 5) + 1) * 6_000,
                        )
                    places.append(
                        AffordancePlace(
                            place_id=pid,
                            label=str(dest.get("label") or pid),
                            kind=str(dest.get("use_class") or "destination"),
                            x_mm=x_mm,
                            y_mm=y_mm,
                            z_mm=z_mm,
                            capacity=int(dest.get("capacity", 6)),
                        )
                    )

    if not places:
        places = default_generated_town_places(seed)

    deduped: dict[str, AffordancePlace] = {}
    for place in places:
        deduped[place.place_id] = place
    return [deduped[k] for k in sorted(deduped)]


def hydrate_room_from_society_state(
    *,
    world_id: str,
    version_id: str,
    society_state: Mapping[str, Any] | None = None,
    society_input: Mapping[str, Any] | None = None,
    generated_places: Sequence[AffordancePlace | Mapping[str, Any]] | None = None,
    assigned_models: Mapping[str, Mapping[str, Any]] | None = None,
    control_receipts: Sequence[Mapping[str, Any]] | None = None,
    world_title: str | None = None,
    seed: str = "exulanica-realtime-v1",
    checkpoint_interval_ticks: int = DEFAULT_CHECKPOINT_INTERVAL_TICKS,
) -> RealtimeWorldRoom:
    """Hydrate a ``RealtimeWorldRoom`` from a world version's society state or generated town."""
    resolved_title = world_title
    if not resolved_title and isinstance(society_input, Mapping):
        world_meta = society_input.get("world")
        if isinstance(world_meta, Mapping) and isinstance(world_meta.get("title"), str):
            resolved_title = world_meta["title"]
    if not resolved_title:
        resolved_title = "A Living Town"

    # Validate session receipts through exulanica.world.society_sessions.sessions_from when provided
    if control_receipts:
        sessions_from(control_receipts)

    room = RealtimeWorldRoom(
        world_id=world_id,
        version_id=version_id,
        world_title=resolved_title,
        seed=seed,
        checkpoint_interval_ticks=checkpoint_interval_ticks,
    )

    if society_state is not None and "tick" in society_state:
        room.tick = int(society_state["tick"]) * SUBTICKS_PER_WORLD_MINUTE
        room.epoch_start_tick = room.tick

    places = _extract_places_from_input(society_input, generated_places, seed)
    for place in places:
        room.add_place(place)

    inhabitants = society_state.get("inhabitants", ()) if isinstance(society_state, Mapping) else ()
    assigned = assigned_models or {}

    nav_nodes: dict[str, tuple[int, int, int]] = {}
    if isinstance(society_input, Mapping):
        nav = society_input.get("navigation")
        if isinstance(nav, Mapping):
            for node in nav.get("nodes", ()):
                if isinstance(node, Mapping) and "node_id" in node:
                    nav_nodes[str(node["node_id"])] = _extract_xyz_mm(node.get("position_mm"))

    if inhabitants:
        for idx, person in enumerate(inhabitants):
            if not isinstance(person, Mapping):
                continue
            being_id = str(person.get("id") or person.get("being_id") or f"being-{idx:03d}")
            label = str(person.get("name") or person.get("label") or f"inhabitant {idx + 1}")
            came_by = str(person.get("came_by") or "populated")
            if came_by not in ("populated", "placed", "crossed"):
                came_by = "populated"

            raw_decider = assigned.get(being_id) or person.get("decider")
            if isinstance(raw_decider, Mapping):
                if "kind" in raw_decider:
                    being_decider = validate_decider(raw_decider)
                elif "provider" in raw_decider and "model_id" in raw_decider:
                    being_decider = validate_decider(
                        {
                            "kind": "model",
                            "model_id": str(raw_decider["model_id"]),
                            "provider": str(raw_decider["provider"]),
                        }
                    )
                else:
                    being_decider = {"kind": "routine"}
            else:
                being_decider = {"kind": "routine"}

            # Extract position from person["position_mm"] or person["location"]
            fallback_x = (idx % 16) * 4_000 + 2_000
            fallback_y = (idx // 16) * 4_000 + 2_000
            if "position_mm" in person:
                x_mm, y_mm, z_mm = _extract_xyz_mm(
                    person["position_mm"], fallback_x=fallback_x, fallback_y=fallback_y
                )
            elif isinstance(person.get("location"), Mapping):
                loc = person["location"]
                if "position_mm" in loc:
                    x_mm, y_mm, z_mm = _extract_xyz_mm(
                        loc["position_mm"], fallback_x=fallback_x, fallback_y=fallback_y
                    )
                elif str(loc.get("node_id", "")) in nav_nodes:
                    x_mm, y_mm, z_mm = nav_nodes[str(loc["node_id"])]
                elif "from_position_mm" in loc:
                    x_mm, y_mm, z_mm = _extract_xyz_mm(
                        loc["from_position_mm"], fallback_x=fallback_x, fallback_y=fallback_y
                    )
                else:
                    x_mm, y_mm, z_mm = (fallback_x, fallback_y, 0)
            else:
                x_mm, y_mm, z_mm = (fallback_x, fallback_y, 0)

            room.add_being(
                being_id=being_id,
                label=label,
                came_by=came_by,
                decider=being_decider,
                x_mm=x_mm,
                y_mm=y_mm,
                z_mm=z_mm,
                speed_mm_per_tick=DEFAULT_SPEED_MM_PER_TICK,
            )
    else:
        # Generated town starter inhabitants when no society state is present yet
        for idx, place in enumerate(places[:8]):
            being_id = f"resident-{idx + 1:02d}"
            raw_decider = assigned.get(being_id) or {"kind": "routine"}
            room.add_being(
                being_id=being_id,
                label=f"resident {idx + 1}",
                came_by="populated",
                decider=validate_decider(raw_decider),
                x_mm=place.x_mm + (idx + 1) * 400,
                y_mm=place.y_mm + (idx + 1) * 300,
                z_mm=place.z_mm,
            )

    return room


class RealtimeCheckpointRepository:
    """This process's store for ``exulanica.realtime-epoch-checkpoint/v1``, one per workspace."""

    def __init__(self, workspace_id: uuid.UUID) -> None:
        self.workspace_id = workspace_id

    def save_checkpoint(
        self,
        room: RealtimeWorldRoom,
        checkpoint: EpochCheckpoint | None = None,
    ) -> dict[str, Any]:
        """Keep a flushed ``EpochCheckpoint`` and its canonical room state for this workspace."""
        record = room.to_checkpoint_record(checkpoint)
        # Verify zero-float canonical serialization before keeping it
        canonical_json(record)

        key = (str(self.workspace_id), room.world_id, str(room.version_id))
        bucket = _PROCESS_CHECKPOINTS.setdefault(key, [])
        bucket[:] = [item for item in bucket if item["epoch_seq"] != record["epoch_seq"]]
        bucket.append(record)
        bucket.sort(key=lambda item: int(item["epoch_seq"]))
        return record

    def load_checkpoint_record(
        self,
        *,
        world_id: str,
        version_id: str | uuid.UUID,
        epoch_seq: int | None = None,
    ) -> dict[str, Any] | None:
        """The latest (or the given ``epoch_seq``) checkpoint record kept for this world version."""
        key = (str(self.workspace_id), world_id, str(version_id))
        bucket = _PROCESS_CHECKPOINTS.get(key, [])
        if not bucket:
            return None
        if epoch_seq is None:
            return dict(bucket[-1])
        for item in bucket:
            if int(item["epoch_seq"]) == epoch_seq:
                return dict(item)
        return None

    def restore_room(
        self,
        *,
        world_id: str,
        version_id: str | uuid.UUID,
        epoch_seq: int | None = None,
    ) -> RealtimeWorldRoom | None:
        """Restore a ``RealtimeWorldRoom`` from its saved checkpoint and verify ``state_sha256``."""
        record = self.load_checkpoint_record(
            world_id=world_id, version_id=version_id, epoch_seq=epoch_seq
        )
        if record is None:
            return None
        if record.get("profile") != EPOCH_CHECKPOINT_PROFILE:
            raise ValueError(f"unexpected checkpoint profile {record.get('profile')!r}")
        return RealtimeWorldRoom.from_checkpoint_record(record)


def hydrate_room_from_postgres(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    version_id: uuid.UUID,
    world_id: str | None = None,
    prefer_checkpoint: bool = True,
) -> RealtimeWorldRoom:
    """Hydrate a ``RealtimeWorldRoom`` for ``(workspace_id, version_id)`` from PostgreSQL."""
    # 1. Check if a society exists for this version_id in PostgreSQL
    society_row: dict[str, Any] | None = None
    try:
        with connection.transaction():
            if world_id is not None:
                society_row = (
                    connection.cursor(row_factory=dict_row)
                    .execute(
                        """
                        select society_id, world_id, version_id, seed, current_tick, state
                          from world_society
                         where workspace_id = %s and world_id = %s and version_id = %s
                        """,
                        (workspace_id, world_id, version_id),
                    )
                    .fetchone()
                )
            else:
                society_row = (
                    connection.cursor(row_factory=dict_row)
                    .execute(
                        """
                        select society_id, world_id, version_id, seed, current_tick, state
                          from world_society
                         where workspace_id = %s and version_id = %s
                        """,
                        (workspace_id, version_id),
                    )
                    .fetchone()
                )
    except Exception:
        society_row = None

    resolved_world_id = (
        str(society_row["world_id"]) if society_row is not None else (world_id or "")
    )

    # 2. If no society row, check if the world version exists in world_alternate_version
    version_exists = society_row is not None
    if not version_exists:
        try:
            with connection.transaction():
                if resolved_world_id:
                    v_row = (
                        connection.cursor(row_factory=dict_row)
                        .execute(
                            """
                            select world_id, version_id
                              from world_alternate_version
                             where workspace_id = %s and world_id = %s and version_id = %s
                            """,
                            (workspace_id, resolved_world_id, version_id),
                        )
                        .fetchone()
                    )
                else:
                    v_row = (
                        connection.cursor(row_factory=dict_row)
                        .execute(
                            """
                            select world_id, version_id
                              from world_alternate_version
                             where workspace_id = %s and version_id = %s
                            """,
                            (workspace_id, version_id),
                        )
                        .fetchone()
                    )
                if v_row is not None:
                    version_exists = True
                    resolved_world_id = str(v_row["world_id"])
        except Exception:
            version_exists = False

    repo = RealtimeCheckpointRepository(workspace_id)
    if prefer_checkpoint and resolved_world_id:
        restored = repo.restore_room(world_id=resolved_world_id, version_id=version_id)
        if restored is not None:
            return restored

    if not version_exists:
        raise UnknownWorldResource(str(version_id))

    if society_row is None:
        return hydrate_room_from_society_state(
            world_id=resolved_world_id,
            version_id=str(version_id),
            seed=f"exulanica-{resolved_world_id}-{version_id}",
        )

    society_id = society_row["society_id"]
    latest_input: dict[str, Any] | None = None
    assigned_models: dict[str, dict[str, Any]] = {}
    control_receipts: list[dict[str, Any]] = []

    try:
        with connection.transaction():
            in_row = (
                connection.cursor(row_factory=dict_row)
                .execute(
                    """
                    select document
                      from world_society_input
                     where workspace_id = %s and society_id = %s
                     order by input_seq desc
                     limit 1
                    """,
                    (workspace_id, society_id),
                )
                .fetchone()
            )
            if in_row is not None and isinstance(in_row.get("document"), Mapping):
                latest_input = dict(in_row["document"])

            choice_rows = (
                connection.cursor(row_factory=dict_row)
                .execute(
                    """
                    select document
                      from world_society_model_choice
                     where workspace_id = %s and world_id = %s and society_id = %s
                     order by choice_seq asc
                    """,
                    (workspace_id, resolved_world_id, society_id),
                )
                .fetchall()
            )
            for crow in choice_rows:
                doc = crow.get("document")
                if not isinstance(doc, Mapping):
                    continue
                dec = doc.get("decider")
                if not isinstance(dec, Mapping):
                    model_val = doc.get("model")
                    dec = (
                        {
                            "kind": "model",
                            "model_id": model_val["model_id"],
                            "provider": model_val["provider"],
                        }
                        if isinstance(model_val, Mapping)
                        else {"kind": "routine"}
                    )
                for subj in doc.get("people", doc.get("subjects", ())):
                    assigned_models[str(subj)] = dict(dec)

            event_rows = (
                connection.cursor(row_factory=dict_row)
                .execute(
                    """
                    select document
                      from world_society_control_event
                     where workspace_id = %s and society_id = %s
                     order by event_seq asc
                    """,
                    (workspace_id, society_id),
                )
                .fetchall()
            )
            for erow in event_rows:
                if isinstance(erow.get("document"), Mapping):
                    control_receipts.append(dict(erow["document"]))
    except Exception:
        pass

    return hydrate_room_from_society_state(
        world_id=resolved_world_id,
        version_id=str(version_id),
        society_state=society_row["state"],
        society_input=latest_input,
        assigned_models=assigned_models,
        control_receipts=control_receipts,
        seed=str(society_row["seed"]),
    )
