"""Human-confirmed identity between memory place entities and canonical places."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from exulanica.db.session import set_workspace
from exulanica.selection.validation import RejectionCode, SelectionRejected

__all__ = ["PlaceBridgeDecision", "PlaceBridgeRepository"]


@dataclass(frozen=True, slots=True)
class PlaceBridgeDecision:
    decision_id: uuid.UUID
    place_id: uuid.UUID
    entity_id: uuid.UUID
    decision: str
    supersedes_decision_id: uuid.UUID | None
    decided_by: uuid.UUID
    reason: str | None
    decided_at: str


class PlaceBridgeRepository:
    """Append-only bridge decisions scoped to one workspace."""

    def __init__(self, connection: psycopg.Connection, workspace_id: uuid.UUID) -> None:
        connection.row_factory = dict_row
        set_workspace(connection, workspace_id)
        self.connection = connection
        self.workspace_id = workspace_id

    def confirm(
        self,
        *,
        place_id: uuid.UUID,
        entity_id: uuid.UUID,
        actor: uuid.UUID,
        reason: str | None = None,
        supersedes_decision_id: uuid.UUID | None = None,
    ) -> PlaceBridgeDecision:
        self._require_pair(place_id, entity_id)
        return self._insert(
            place_id=place_id,
            entity_id=entity_id,
            decision="confirmed",
            actor=actor,
            reason=reason,
            supersedes_decision_id=supersedes_decision_id,
        )

    def revoke(
        self, decision_id: uuid.UUID, *, actor: uuid.UUID, reason: str | None = None
    ) -> PlaceBridgeDecision:
        row = self.connection.execute(
            """
            select active.decision_id,active.place_id,active.entity_id
              from confirmed_place_entity_bridge active
             where active.workspace_id=%s and active.decision_id=%s
            """,
            (self.workspace_id, decision_id),
        ).fetchone()
        if row is None:
            raise SelectionRejected(
                RejectionCode.UNKNOWN_REFERENCE,
                "the confirmed place bridge is not available",
            )
        return self._insert(
            place_id=row["place_id"],
            entity_id=row["entity_id"],
            decision="revoked",
            actor=actor,
            reason=reason,
            supersedes_decision_id=row["decision_id"],
        )

    def confirmed(self) -> tuple[PlaceBridgeDecision, ...]:
        rows = self.connection.execute(
            """
            select d.decision_id,d.place_id,d.entity_id,d.decision,
                   d.supersedes_decision_id,d.decided_by,d.reason,d.decided_at
              from place_entity_bridge_decision d
              join confirmed_place_entity_bridge active
                on active.workspace_id=d.workspace_id
               and active.decision_id=d.decision_id
             where d.workspace_id=%s
             order by d.decided_at,d.decision_id
            """,
            (self.workspace_id,),
        ).fetchall()
        return tuple(self._decision(row) for row in rows)

    def history(
        self, *, place_id: uuid.UUID, entity_id: uuid.UUID
    ) -> tuple[PlaceBridgeDecision, ...]:
        rows = self.connection.execute(
            """
            select decision_id,place_id,entity_id,decision,supersedes_decision_id,
                   decided_by,reason,decided_at
              from place_entity_bridge_decision
             where workspace_id=%s and place_id=%s and entity_id=%s
             order by decided_at,decision_id
            """,
            (self.workspace_id, place_id, entity_id),
        ).fetchall()
        return tuple(self._decision(row) for row in rows)

    def _require_pair(self, place_id: uuid.UUID, entity_id: uuid.UUID) -> None:
        if place_id == entity_id:
            raise SelectionRejected(
                RejectionCode.MALFORMED_PLAN,
                "canonical place ids and memory place entity ids must remain distinct",
            )
        place = self.connection.execute(
            "select 1 from place where workspace_id=%s and place_id=%s",
            (self.workspace_id, place_id),
        ).fetchone()
        entity = self.connection.execute(
            """
            select class,deleted_at,merged_into from entity
             where workspace_id=%s and entity_id=%s
            """,
            (self.workspace_id, entity_id),
        ).fetchone()
        if place is None or entity is None:
            raise SelectionRejected(
                RejectionCode.UNKNOWN_REFERENCE,
                "the canonical place or memory entity is not available",
            )
        if (
            entity["class"] != "place"
            or entity["deleted_at"] is not None
            or entity["merged_into"] is not None
        ):
            raise SelectionRejected(
                RejectionCode.MALFORMED_PLAN,
                "a place bridge requires a live, unmerged place-class entity",
            )

    def _insert(
        self,
        *,
        place_id: uuid.UUID,
        entity_id: uuid.UUID,
        decision: str,
        actor: uuid.UUID,
        reason: str | None,
        supersedes_decision_id: uuid.UUID | None,
    ) -> PlaceBridgeDecision:
        row = self.connection.execute(
            """
            insert into place_entity_bridge_decision(
              workspace_id,place_id,entity_id,decision,supersedes_decision_id,decided_by,reason)
            values(%s,%s,%s,%s,%s,%s,%s)
            returning decision_id,place_id,entity_id,decision,supersedes_decision_id,
                      decided_by,reason,decided_at
            """,
            (
                self.workspace_id,
                place_id,
                entity_id,
                decision,
                supersedes_decision_id,
                actor,
                reason,
            ),
        ).fetchone()
        assert row is not None
        return self._decision(row)

    @staticmethod
    def _decision(row: dict[str, object]) -> PlaceBridgeDecision:
        decided_at = row["decided_at"]
        return PlaceBridgeDecision(
            decision_id=row["decision_id"],  # type: ignore[arg-type]
            place_id=row["place_id"],  # type: ignore[arg-type]
            entity_id=row["entity_id"],  # type: ignore[arg-type]
            decision=str(row["decision"]),
            supersedes_decision_id=row["supersedes_decision_id"],  # type: ignore[arg-type]
            decided_by=row["decided_by"],  # type: ignore[arg-type]
            reason=row["reason"] if isinstance(row["reason"], str) else None,
            decided_at=decided_at.isoformat(),  # type: ignore[union-attr]
        )
