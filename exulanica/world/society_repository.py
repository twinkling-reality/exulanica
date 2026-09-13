"""PostgreSQL authority for deterministic synthetic societies."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.society import (
    SOCIETY_ENGINE_VERSION,
    SOCIETY_POPULATION,
    SOCIETY_TICK_SECONDS,
    StaleSocietyState,
    UnknownSociety,
    advance_society,
    event_document_sha256,
    initial_society,
    society_state_sha256,
)


class SocietyRepository:
    def __init__(
        self,
        connection: psycopg.Connection,
        workspace_id: uuid.UUID,
        *,
        world_id: str = DEFAULT_WORLD_ID,
    ) -> None:
        self.connection = connection
        self.workspace_id = workspace_id
        self.world_id = world_id

    def create(
        self,
        version_id: uuid.UUID,
        *,
        place_id: uuid.UUID,
        region_id: str,
        seed: str,
        actor: uuid.UUID,
    ) -> dict[str, Any]:
        existing = self._row(version_id, lock=True)
        if existing is not None:
            return self._snapshot(existing)
        version = self.connection.execute(
            "select 1 from world_alternate_version where workspace_id=%s and world_id=%s "
            "and version_id=%s for update",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()
        if version is None:
            raise UnknownSociety("world version is unavailable")
        society_id = uuid.uuid5(version_id, "exulanica-society/v1")
        state = initial_society(society_id, seed)
        digest = society_state_sha256(state)
        row = self.connection.execute(
            "insert into world_society("
            "workspace_id,society_id,world_id,version_id,place_id,region_id,engine_version,"
            "seed,population_size,tick_seconds,state,state_sha256,created_by"
            ") values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning *",
            (
                self.workspace_id,
                society_id,
                self.world_id,
                version_id,
                place_id,
                region_id,
                SOCIETY_ENGINE_VERSION,
                seed,
                SOCIETY_POPULATION,
                SOCIETY_TICK_SECONDS,
                Jsonb(state),
                digest,
                actor,
            ),
        ).fetchone()
        return self._snapshot(row)

    def snapshot(self, version_id: uuid.UUID) -> dict[str, Any]:
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        return self._snapshot(row)

    def advance(
        self,
        version_id: uuid.UUID,
        *,
        base_tick: int,
        base_state_sha256: str,
    ) -> dict[str, Any]:
        row = self._row(version_id, lock=True)
        if row is None:
            raise UnknownSociety("society is unavailable")
        if row["current_tick"] != base_tick or row["state_sha256"] != base_state_sha256:
            raise StaleSocietyState("society changed; reload before advancing")
        state, events = advance_society(row["state"], row["seed"])
        digest = society_state_sha256(state)
        self.connection.execute(
            "update world_society set current_tick=%s,state=%s,state_sha256=%s "
            "where workspace_id=%s and society_id=%s",
            (state["tick"], Jsonb(state), digest, self.workspace_id, row["society_id"]),
        )
        for event in events:
            self.connection.execute(
                "insert into world_society_event("
                "workspace_id,society_id,event_id,tick,event_kind,subject_id,object_id,"
                "place_id,document,document_sha256"
                ") values(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    self.workspace_id,
                    row["society_id"],
                    event.event_id,
                    event.tick,
                    event.kind,
                    event.subject_id,
                    event.object_id,
                    row["place_id"],
                    Jsonb(event.document),
                    event_document_sha256(event),
                ),
            )
        return self.snapshot(version_id)

    def events(self, version_id: uuid.UUID, *, limit: int = 256) -> tuple[dict[str, Any], ...]:
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        rows = self.connection.execute(
            "select event_id,tick,event_kind,subject_id,object_id,place_id,document,"
            "document_sha256,recorded_at from world_society_event "
            "where workspace_id=%s and society_id=%s order by tick desc,event_id limit %s",
            (self.workspace_id, row["society_id"], max(1, min(limit, 256))),
        ).fetchall()
        return tuple(dict(value) for value in rows)

    def replay(self, version_id: uuid.UUID) -> dict[str, Any]:
        row = self._row(version_id)
        if row is None:
            raise UnknownSociety("society is unavailable")
        state = initial_society(row["society_id"], row["seed"], population=row["population_size"])
        for _ in range(row["current_tick"]):
            state, _events = advance_society(state, row["seed"])
        if society_state_sha256(state) != row["state_sha256"]:
            raise ValueError("stored society state does not match deterministic replay")
        return self._snapshot(row) | {"replay_verified": True}

    def _row(self, version_id: uuid.UUID, *, lock: bool = False) -> dict[str, Any] | None:
        suffix = " for update" if lock else ""
        return self.connection.execute(
            "select * from world_society where workspace_id=%s and world_id=%s "
            f"and version_id=%s{suffix}",
            (self.workspace_id, self.world_id, version_id),
        ).fetchone()

    @staticmethod
    def _snapshot(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "profile": row["engine_version"],
            "society_id": row["society_id"],
            "world_id": row["world_id"],
            "version_id": row["version_id"],
            "place_id": row["place_id"],
            "region_id": row["region_id"],
            "seed": row["seed"],
            "population_size": row["population_size"],
            "tick_seconds": row["tick_seconds"],
            "current_tick": row["current_tick"],
            "state": row["state"],
            "state_sha256": row["state_sha256"],
            "created_by": row["created_by"],
            "created_at": row["created_at"],
        }
