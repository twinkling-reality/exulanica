"""Compose explicit source slots into an existing Atlas region without inventing evidence."""

from __future__ import annotations

import uuid
from typing import Any

from exulanica.ingest.repository import IngestRepository
from exulanica.world.personal_composition import (
    ComposedSource,
    register_composition,
    source_slot,
)


def compose_reference_sources(
    repository: IngestRepository,
    *,
    region_id: str,
    captures: list[tuple[uuid.UUID, str, str]],
    source_manifest_sha256: str,
    actor: uuid.UUID,
) -> dict[str, Any]:
    """Bind user-selected photographs to a region through the protected topology writer.

    Slot membership is an authored source-gallery choice, never a new temporal,
    metric, reconstruction or semantic assertion about the photographs.

    The photographs are composed into the workspace's personal-source world, created here by
    ``actor`` when the workspace has none and refused by name when the world count policy allows
    no more.
    """
    if not region_id or not captures or len({row[0] for row in captures}) != len(captures):
        raise ValueError("source composition needs a region and unique selected captures")
    sources = []
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
        source = ComposedSource(capture_id, expected_sha256, row["span_id"], region_id)
        sources.append(source)
        records.append({**source_slot(repository.workspace_id, source)[1], "source_label": label})
    record = {
        "profile": "exulanica.authored-reference-source-composition/v1",
        "workspace_id": str(repository.workspace_id),
        "region_id": region_id,
        "source_manifest_sha256": source_manifest_sha256,
        "source_slots": records,
        "interpretation": "authored gallery membership only; no new reconstruction or evidence",
    }
    registered = register_composition(
        repository.connection,
        repository.workspace_id,
        record=record,
        sources=sources,
        region_ids=(region_id,),
        actor=actor,
        reason="reference photographs composed into a region",
    )
    return {"record": record, **registered}
