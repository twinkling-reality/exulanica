"""The photographs a personal-source world is composed from, arranged by their scene groups.

Two facts, each read from its one owner and joined here: which photographs the account holder
reviewed and may use (:func:`exulanica.world.reviewed_sources.reviewed_personal_sources`), and
which live scene group each belongs to (:func:`exulanica.graph.scene_groups.scene_group_rows`).
A scene group becomes one region of the composed topology, named by the group's id, so the
regions are the grouping the graph already states and not a choice made here or by a caller.

**A reviewed photograph in no live scene group is left out and counted**, not refused. Grouping
clusters photographs by when and where they were taken, and a photograph it cannot place, such as
one with no capture time, stays ungrouped for good. Refusing the whole composition over it would
keep every other reviewed photograph out of the world; leaving it out and saying how many were
left out lets the person see the gap. A photograph in several groups is a slot of the first one
in the grouping's own order, because a source slot belongs to one region.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.evidence.blob import BlobId
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.store.base import ContentAddressedStore
from exulanica.world.personal_composition import ComposedSource, PersonalComposition
from exulanica.world.reviewed_sources import reviewed_personal_sources

__all__ = ["personal_composition"]


def personal_composition(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    *,
    reviewed_for: uuid.UUID,
    store: ContentAddressedStore | None,
) -> PersonalComposition:
    """What the personal-source world would be composed from now, for ``reviewed_for``."""
    reviewed = [
        source
        for source in reviewed_personal_sources(
            connection, workspace_id, reviewed_for=reviewed_for, store=store
        )
        if source.viewer_available
    ]
    by_capture = {source.capture_id: source for source in reviewed}
    placed: set[uuid.UUID] = set()
    composed: list[ComposedSource] = []
    region_ids: list[str] = []
    for group in scene_group_rows(connection, workspace_id):
        members = sorted(
            capture_id
            for capture_id in group.capture_ids
            if capture_id in by_capture and capture_id not in placed
        )
        if not members:
            continue
        region_id = str(group.group_id)
        region_ids.append(region_id)
        for capture_id in members:
            source = by_capture[capture_id]
            placed.add(capture_id)
            composed.append(
                ComposedSource(
                    capture_id=capture_id,
                    source_sha256=BlobId(source.source_sha256).hex,
                    evidence_span_id=source.evidence_span_id,
                    region_id=region_id,
                )
            )
    return PersonalComposition(
        reviewed=len(reviewed),
        outside_scene_groups=len(reviewed) - len(placed),
        sources=tuple(composed),
        region_ids=tuple(region_ids),
        reviewed_spans=frozenset(source.evidence_span_id for source in reviewed),
    )
