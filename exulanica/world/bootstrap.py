"""Open the first structural snapshot and alternate from the current composed topology."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from exulanica.canonical import sha256_of_canonical
from exulanica.world.composed import composed_candidate
from exulanica.world.errors import InvalidatedSourceVersion, ProtectedTopologyConflict
from exulanica.world.models import DEFAULT_WORLD_ID
from exulanica.world.object_repository import WorldObjectRepository
from exulanica.world.repository import WorldStyleRepository
from exulanica.world.structure_repository import WorldStructureRepository


def bootstrap_world(
    connection: psycopg.Connection,
    *,
    workspace_id: uuid.UUID,
    actor: uuid.UUID,
    base_topology_digest: str,
    title: str = "My alternate world",
    world_id: str = DEFAULT_WORLD_ID,
) -> dict[str, Any]:
    """CAS the composed contract and atomically reuse or create the two first versions."""
    with connection.transaction():
        connection.execute(
            "select pg_advisory_xact_lock(hashtextextended(%s::text,%s))", (workspace_id, 880_024)
        )
        styles = WorldStyleRepository(connection, workspace_id, world_id=world_id)
        contract = styles.current_topology_contract()
        if contract.topology_digest != base_topology_digest:
            raise ProtectedTopologyConflict("the composed topology changed; read it again")
        structures = WorldStructureRepository(connection, workspace_id, world_id=world_id)
        snapshot = structures.current()
        composed = "reused"
        if snapshot is None:
            candidate = composed_candidate(
                contract,
                _plane_digest(
                    connection,
                    "select capture_id, blob_sha256 from capture "
                    "where workspace_id=%s and deleted_at is null order by capture_id",
                    workspace_id,
                ),
                _plane_digest(
                    connection,
                    "select artifact_id, kind, content_sha256 from artifact "
                    "where workspace_id=%s and purged_at is null order by artifact_id",
                    workspace_id,
                ),
            )
            preview = structures.preview(candidate, proposed_by=actor)
            snapshot = structures.apply(
                preview.preview_id,
                base_snapshot_id=preview.base_snapshot_id,
                base_graph_sha256=preview.base_graph_sha256,
                base_reconstruction_sha256=preview.base_reconstruction_sha256,
                committed_by=actor,
                base_composed_topology_digest=base_topology_digest,
            )
            composed = "applied"
        if snapshot.invalidated:
            raise InvalidatedSourceVersion("the current structural snapshot was invalidated")
        objects = WorldObjectRepository(connection, workspace_id, world_id=world_id)
        existing = objects.versions()
        version = (
            existing[0]
            if existing
            else objects.create_version(
                source_snapshot_id=snapshot.snapshot_id, title=title, created_by=actor
            )
        )
        if version.source_invalidated:
            raise InvalidatedSourceVersion("the latest alternate version's source was invalidated")
        return {
            "snapshot": composed,
            "snapshot_id": str(snapshot.snapshot_id),
            "regions": list(contract.region_ids),
            "version": "reused" if existing else "created",
            "version_id": str(version.version_id),
            "state_sha256": version.state_sha256,
        }


def _plane_digest(connection: psycopg.Connection, statement: str, workspace_id: uuid.UUID) -> str:
    rows = connection.execute(statement, (workspace_id,)).fetchall()
    return sha256_of_canonical(
        [{key: str(value) for key, value in row.items()} for row in rows]
    ).hex()
