"""Compose explicit source slots into an existing Atlas region without inventing evidence."""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.canonical import sha256_of_canonical
from exulanica.ingest.repository import IngestRepository
from exulanica.world import TopologyContract, TopologySourceSlot, WorldStyleRepository

SOURCE_NAMESPACE = uuid.UUID("d3f0565b-c4b2-4d19-8ea9-a3f79bbb5649")


def compose_reference_sources(
    repository: IngestRepository,
    *,
    region_id: str,
    captures: list[tuple[uuid.UUID, str, str]],
    source_manifest_sha256: str,
) -> dict[str, Any]:
    """Bind user-selected photographs to a region through the protected topology writer.

    Slot membership is an authored source-gallery choice, never a new temporal,
    metric, reconstruction or semantic assertion about the photographs.
    """
    if not region_id or not captures or len({row[0] for row in captures}) != len(captures):
        raise ValueError("source composition needs a region and unique selected captures")
    slots = []
    records = []
    for capture_id, expected_sha256, label in captures:
        capture = repository.capture(capture_id)
        if (
            capture is None
            or capture.deleted_at is not None
            or capture.blob_id.hex != expected_sha256
        ):
            raise ValueError("source composition contains unavailable or changed evidence")
        row = repository.connection.execute(
            "select span_id from evidence_span where workspace_id=%s and blob_sha256=%s "
            "and modality='still_image' and track_key='img' and region is null "
            "order by span_id limit 1",
            (repository.workspace_id, capture.blob_id.digest),
        ).fetchone()
        if row is None:
            raise ValueError("source composition needs an existing original-image evidence span")
        source_id = uuid.uuid5(SOURCE_NAMESPACE, f"{repository.workspace_id}:{capture_id}")
        slot_key = f"source-{capture_id}"
        slots.append(TopologySourceSlot(source_id, slot_key, region_id, row["span_id"], None))
        records.append(
            {
                "source_id": str(source_id),
                "capture_id": str(capture_id),
                "source_sha256": expected_sha256,
                "evidence_span_id": str(row["span_id"]),
                "slot_key": slot_key,
                "source_label": label,
            }
        )
    record = {
        "profile": "exulanica.authored-reference-source-composition/v1",
        "workspace_id": str(repository.workspace_id),
        "region_id": region_id,
        "source_manifest_sha256": source_manifest_sha256,
        "source_slots": records,
        "interpretation": "authored gallery membership only; no new reconstruction or evidence",
    }
    digest = sha256_of_canonical(record).hex()
    version = WorldStyleRepository(
        repository.connection, repository.workspace_id
    ).register_topology(TopologyContract(digest, (region_id,), tuple(slots)))
    return {
        "record": record,
        "topology_digest": digest,
        "style_version_id": str(version.version_id),
    }
