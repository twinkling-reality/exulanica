"""Live admitted photographs for inspection, independently of reconstruction or topology."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg

from exulanica.epistemics.source_images import selected_image
from exulanica.evidence.blob import BlobId
from exulanica.graph.asset_read_policy import evaluation_time, image_source
from exulanica.graph.payload import ReviewSourceRow
from exulanica.graph.person_regions import person_regions_for_captures, review_states_for_captures
from exulanica.store.base import ContentAddressedStore
from exulanica.store.resolve import address_from_span_row


def _live_sources(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    at: dt.datetime,
    capture_ids: list[uuid.UUID] | None = None,
) -> list[dict[str, Any]]:
    return connection.execute(
        "select c.capture_id,c.started_at,s.*,b.media_type from capture c "
        "join lateral (select e.* from evidence_span e where e.workspace_id=c.workspace_id "
        "and e.blob_sha256=c.blob_sha256 and e.modality='still_image' "
        "and e.track_key='img' and e.t_start_ns=0 and e.t_end_ns=1 "
        "and e.region is null and e.text_anchor is null "
        "order by e.span_id limit 1) s on true "
        "join blob b on b.blob_sha256=c.blob_sha256 "
        "where c.workspace_id=%s and asset_capture_live(%s,c.capture_id,%s) "
        "and not asset_tombstone_span(%s,s.blob_sha256,s.track_key,s.t_start_ns,s.t_end_ns,%s) "
        "and b.media_type like 'image/%%' "
        "and (%s::uuid[] is null or c.capture_id=any(%s)) order by c.capture_id",
        (workspace, workspace, at, workspace, at, capture_ids, capture_ids),
    ).fetchall()


def review_source_rows(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore | None,
) -> list[ReviewSourceRow]:
    """Read actual capture/span identities and buffer availability outside the final lock."""
    at = evaluation_time(connection)
    rows = _live_sources(connection, workspace, at)
    ids = [row["capture_id"] for row in rows]
    regions = person_regions_for_captures(connection, workspace, ids)
    states = review_states_for_captures(connection, workspace, ids)
    result = []
    for row in rows:
        address_from_span_row(row)  # Verify the immutable evidence address before offering it.
        selection = selected_image(connection, workspace, bytes(row["blob_sha256"]), at)
        selected = selection.sha256 if selection is not None else None
        available = selected is not None and store is not None and store.exists(BlobId(selected))
        result.append(
            ReviewSourceRow(
                kind="admitted_capture",
                capture_id=row["capture_id"],
                evidence_span_id=row["span_id"],
                captured_at=row["started_at"].isoformat() if row["started_at"] else None,
                media_type=row["media_type"] if selection is None else selection.media_type,
                state="available" if available else "unavailable_asset",
                reason=None if available else "Current authorized viewer bytes are unavailable.",
                evidence_path=f"/evidence/{row['span_id']}/masked" if available else None,
                content_sha256=selected.hex() if available else None,
                person_regions=regions.get(str(row["capture_id"]), []),
                person_review_state=states.get(str(row["capture_id"]), "unscreened"),
            )
        )
    return result


def reauthorize_review_sources(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    buffered: Sequence[ReviewSourceRow],
    at: dt.datetime,
) -> list[ReviewSourceRow]:
    """Recheck buffered metadata under final_check; no object-store reads under its lock.

    A withdrawn capture disappears. Changed image permission withholds the old reference.
    Person state is reread here so buffered names and outlines cannot outrun a review change.
    """
    if not buffered:
        return []
    live = {
        row["capture_id"]: row
        for row in _live_sources(connection, workspace, at, [item.capture_id for item in buffered])
    }
    ids = list(live)
    regions = person_regions_for_captures(connection, workspace, ids)
    states = review_states_for_captures(connection, workspace, ids)
    result = []
    for source in buffered:
        row = live.get(source.capture_id)
        if row is None or row["span_id"] != source.evidence_span_id:
            continue
        selected = image_source(connection, workspace, bytes(row["blob_sha256"]), at)
        available = (
            source.state == "available"
            and selected is not None
            and selected.hex() == source.content_sha256
        )
        result.append(
            source.model_copy(
                update={
                    "state": "available" if available else "unavailable_asset",
                    "reason": None
                    if available
                    else "Current authorized viewer bytes are unavailable.",
                    "evidence_path": source.evidence_path if available else None,
                    "content_sha256": source.content_sha256 if available else None,
                    "person_regions": regions.get(str(source.capture_id), []),
                    "person_review_state": states.get(str(source.capture_id), "unscreened"),
                }
            )
        )
    return result
