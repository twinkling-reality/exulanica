"""The two facts a personal-source world is arranged from, each read from its one owner.

Which photographs the account holder reviewed and may use
(:func:`exulanica.world.reviewed_sources.reviewed_personal_sources`, keeping only those whose
viewer bytes are present), and the live scene groups
(:func:`exulanica.graph.scene_groups.scene_group_rows`). Nothing here decides which region a
photograph is a slot of: that is one rule, :func:`exulanica.world.personal_composition.arrange`,
which reads these facts with the made world when there is one.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.evidence.blob import BlobId
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.store.base import ContentAddressedStore
from exulanica.world.personal_composition import (
    LiveSceneGroup,
    PersonalSources,
    ReviewedPhotograph,
)
from exulanica.world.reviewed_sources import reviewed_personal_sources

__all__ = ["personal_sources"]


def personal_sources(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    reviewed_for: uuid.UUID,
    store: ContentAddressedStore | None,
) -> PersonalSources:
    """The reviewed photographs ``reviewed_for`` may use now, and every live scene group."""
    return PersonalSources(
        reviewed=tuple(
            ReviewedPhotograph(
                capture_id=source.capture_id,
                source_sha256=BlobId(source.source_sha256).hex,
                evidence_span_id=source.evidence_span_id,
            )
            for source in reviewed_personal_sources(
                connection, workspace_id, reviewed_for=reviewed_for, store=store
            )
            if source.viewer_available
        ),
        groups=tuple(
            LiveSceneGroup(
                group_id=str(group.group_id),
                ordinal=group.ordinal,
                capture_ids=frozenset(group.capture_ids),
            )
            for group in scene_group_rows(connection, workspace_id)
        ),
    )
