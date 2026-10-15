"""The source media and source rows a world's style versions were made from.

A part of :class:`~exulanica.world.repository.WorldStyleRepository` (its methods read the
repository's connection, workspace, world and current state): the media a version names, the
capture a source binds, and the source rows, their topology digest and which of them have lapsed.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from typing import Any

from exulanica.errors import BlobNotFoundError, IntegrityError
from exulanica.evidence import BlobId
from exulanica.store.base import ContentAddressedStore
from exulanica.world.errors import (
    InvalidatedSourceVersion,
    UnavailableAsset,
    UnknownWorldResource,
)
from exulanica.world.models import (
    SourceMediaState,
    WorldSourceMedia,
)
from exulanica.world.reviewed_sources import lapsed_personal_captures
from exulanica.world.style_structure import (
    CompatibilityIntent,
    ComposedTopologyRef,
    StructuralSnapshotRef,
)


class StyleSourceReads:
    """The source reads of :class:`~exulanica.world.repository.WorldStyleRepository`."""

    def source_media(
        self,
        store: ContentAddressedStore,
        *,
        topology_digest: str | None = None,
        source_snapshot_id: uuid.UUID | None = None,
    ) -> tuple[WorldSourceMedia, ...]:
        digest = self._source_topology_digest(topology_digest, source_snapshot_id)
        rows = self._source_rows(digest)
        lapsed = self._lapsed(rows)
        return tuple(self._source_from_row(row, store, lapsed) for row in rows)

    def source_capture_binding(
        self, source_snapshot_id: uuid.UUID, capture_id: uuid.UUID
    ) -> tuple[str, str] | None:
        """The current source region and viewer digest for an owned capture, from rows only.

        An arrival reader checks the viewer bytes before the asset lock, then compares this
        binding again under it. This method deliberately performs no store access.
        """
        digest = self._source_topology_digest(None, source_snapshot_id)
        rows = self._source_rows(digest)
        lapsed = self._lapsed(rows)
        matches = [row for row in rows if capture_id in (row["capture_ids"] or ())]
        if len(matches) != 1:
            return None
        row = matches[0]
        if (
            row["region_id"] is None
            or row["evidence_span_id"] is None
            or row["tombstoned"]
            or not row["live_capture"]
            or capture_id in lapsed
            or row["purged_at"] is not None
            or row["storage_key"] is None
            or row["blob_sha256"] is None
            or row["viewer_sha256"] is None
        ):
            return None
        return row["region_id"], bytes(row["viewer_sha256"]).hex()

    def require_source_media(
        self,
        source_id: uuid.UUID,
        store: ContentAddressedStore,
        *,
        topology_digest: str | None = None,
        source_snapshot_id: uuid.UUID | None = None,
    ) -> WorldSourceMedia:
        digest = self._source_topology_digest(topology_digest, source_snapshot_id)
        rows = self._source_rows(digest, source_id=source_id)
        if not rows:
            raise UnknownWorldResource("no such world source slot")
        source = self._source_from_row(rows[0], store, self._lapsed(rows))
        if source.state is not SourceMediaState.AVAILABLE:
            raise UnavailableAsset(
                f"world source {source.slot_key} is {source.state.value}: {source.reason}"
            )
        return source

    def _source_rows(
        self, topology_digest: str, *, source_id: uuid.UUID | None = None
    ) -> Sequence[Mapping[str, Any]]:
        source_filter = " and ws.source_id=%s" if source_id is not None else ""
        params: list[Any] = [self.workspace_id, self.world_id, topology_digest]
        if source_id is not None:
            params.append(source_id)
        return self.connection.execute(
            "select ws.source_id,ws.region_id,ws.slot_key,ws.evidence_span_id,ws.missing_reason,"
            "s.modality,s.track_key,b.blob_sha256,b.media_type,b.byte_size,b.storage_key,b.purged_at,"
            "t.disp_w,t.disp_h,t.coded_w,t.coded_h,a.utc_instant,a.uncertainty_ms,"
            "case when s.span_id is null then false else "
            "tombstone_blocks_any_span(ws.workspace_id,array[s.span_id]) end as tombstoned,"
            "exists(select 1 from capture c where c.workspace_id=ws.workspace_id "
            "and c.blob_sha256=s.blob_sha256 and c.deleted_at is null) as live_capture "
            ",array(select c.capture_id from capture c where c.workspace_id=ws.workspace_id "
            "and c.blob_sha256=s.blob_sha256 and c.deleted_at is null "
            "order by c.capture_id) as capture_ids "
            ",case when b.media_type like 'image/%%' or s.track_key='img' then "
            "asset_image_source(ws.workspace_id,s.blob_sha256,statement_timestamp(),false) "
            "else s.blob_sha256 end as viewer_sha256 "
            "from world_topology_source ws "
            "left join evidence_span s on s.workspace_id=ws.workspace_id "
            "and s.span_id=ws.evidence_span_id "
            "left join blob b on b.blob_sha256=s.blob_sha256 "
            "left join media_track t on t.blob_sha256=s.blob_sha256 and t.track_key=s.track_key "
            "left join lateral (select ca.utc_instant,ca.uncertainty_ms from clock_anchor ca "
            "where ca.track_id=t.track_id order by ca.uncertainty_ms,ca.anchor_id limit 1) a "
            "on true where ws.workspace_id=%s and ws.world_id=%s and ws.topology_digest=%s"
            + source_filter
            + " order by ws.region_id nulls first,ws.slot_key,ws.source_id",
            params,
        ).fetchall()

    def _source_topology_digest(
        self,
        requested: str | None,
        source_snapshot_id: uuid.UUID | None,
    ) -> str:
        if requested is not None and source_snapshot_id is not None:
            self._require_structure_style_compatibility(
                intent=CompatibilityIntent.CLASSIFY,
                composed=ComposedTopologyRef(requested),
                snapshot=StructuralSnapshotRef(source_snapshot_id),
                conflicting_addresses=True,
            )
        if source_snapshot_id is not None:
            snapshot = self.connection.execute(
                "select s.topology_sha256,exists(select 1 from world_structure_invalidation i "
                "where i.workspace_id=s.workspace_id and i.world_id=s.world_id "
                "and i.snapshot_id=s.snapshot_id) as invalidated "
                "from world_structure_snapshot s where s.workspace_id=%s "
                "and s.world_id=%s and s.snapshot_id=%s",
                (self.workspace_id, self.world_id, source_snapshot_id),
            ).fetchone()
            if snapshot is None:
                raise UnknownWorldResource("no such world structure snapshot")
            if snapshot["invalidated"]:
                raise InvalidatedSourceVersion("the source snapshot was invalidated")
            return str(snapshot["topology_sha256"])
        if requested is None:
            return str(self._require_state()["current_topology_digest"])
        known = self.connection.execute(
            "select 1 from world_topology_contract where workspace_id=%s "
            "and world_id=%s and topology_digest=%s",
            (self.workspace_id, self.world_id, requested),
        ).fetchone()
        if known is None:
            raise UnknownWorldResource("no such world topology")
        return requested

    def _lapsed(self, rows: Sequence[Mapping[str, Any]]) -> frozenset[uuid.UUID]:
        """The slots' personal photographs whose authorization or review is no longer current."""
        return lapsed_personal_captures(
            self.connection,
            self.workspace_id,
            sorted({capture for row in rows for capture in row["capture_ids"] or ()}),
        )

    @staticmethod
    def _source_from_row(
        row: Mapping[str, Any],
        store: ContentAddressedStore,
        lapsed: frozenset[uuid.UUID] = frozenset(),
    ) -> WorldSourceMedia:
        state = SourceMediaState.AVAILABLE
        reason: str | None = None
        if row["evidence_span_id"] is None:
            state = SourceMediaState.MISSING_EVIDENCE
            reason = row["missing_reason"]
        elif row["tombstoned"]:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source evidence was deleted"
        elif not row["live_capture"]:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source capture was deleted"
        elif any(capture in lapsed for capture in row["capture_ids"] or ()):
            # The rule saved-world references follow: the library keeps the photograph, and a
            # world stops drawing it until a new review admits it again.
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "its personal authorization or human review is no longer current"
        elif row["purged_at"] is not None or row["storage_key"] is None:
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source bytes were purged"
        elif row["blob_sha256"] is None or not store.exists(BlobId(bytes(row["blob_sha256"]))):
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "source bytes are missing from storage"
        elif row.get("viewer_sha256") is None or not store.exists(
            BlobId(bytes(row["viewer_sha256"]))
        ):
            state = SourceMediaState.UNAVAILABLE_ASSET
            reason = "current viewer image is unavailable; review or rebuild required"
        if state is SourceMediaState.AVAILABLE:
            try:
                store.get(BlobId(bytes(row["viewer_sha256"])))
            except (BlobNotFoundError, IntegrityError):
                state = SourceMediaState.UNAVAILABLE_ASSET
                reason = "current viewer bytes are missing or corrupt"
        available = state is SourceMediaState.AVAILABLE
        return WorldSourceMedia(
            source_id=row["source_id"],
            slot_key=row["slot_key"],
            region_id=row["region_id"],
            state=state,
            reason=reason,
            evidence_span_id=row["evidence_span_id"],
            evidence_path=(
                None
                if not available
                else f"/evidence/{row['evidence_span_id']}/masked"
                if row["track_key"] == "img"
                or (row["media_type"] and row["media_type"].startswith("image/"))
                else f"/evidence/{row['evidence_span_id']}"
            ),
            modality=row["modality"],
            media_type=row["media_type"],
            byte_size=row["byte_size"],
            width=row["disp_w"] or row["coded_w"],
            height=row["disp_h"] or row["coded_h"],
            captured_at=row["utc_instant"],
            captured_at_uncertainty_ms=row["uncertainty_ms"],
            capture_ids=(
                tuple(row["capture_ids"]) if row["live_capture"] and not row["tombstoned"] else ()
            ),
            viewer_sha256=bytes(row["viewer_sha256"]).hex() if available else None,
        )
