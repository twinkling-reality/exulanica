"""Assemble one graph snapshot at one state version.

The parts are read on one connection in one request so that they were all true at the same
state version. A grouping fetched at a different moment from the graph it groups can disagree
with it, and the whole value of a snapshot is that its parts agree.

Two reads are inline rather than named. They are one statement each with no shape worth a
function: the pairs a split declared can never be the same person, and the entities that have
been deleted.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.graph.entities import entity_rows
from exulanica.graph.occurrences import occurrence_rows, proposal_rows
from exulanica.graph.payload import GraphPayload
from exulanica.graph.reconstruction_scenes import reconstruction_scene_rows
from exulanica.graph.review_sources import review_source_rows
from exulanica.graph.scene_groups import scene_group_rows
from exulanica.store.base import ContentAddressedStore

__all__ = ["read_snapshot"]


def read_snapshot(
    connection: psycopg.Connection,
    workspace: uuid.UUID,
    store: ContentAddressedStore | None = None,
) -> GraphPayload:
    """Every section of the graph, read together so they agree with each other."""
    return GraphPayload(
        state_version=_state_version(connection, workspace),
        review_sources=review_source_rows(connection, workspace, store),
        entities=entity_rows(connection, workspace),
        occurrences=occurrence_rows(connection, workspace),
        proposals=proposal_rows(connection, workspace),
        scene_groups=scene_group_rows(connection, workspace),
        reconstruction_scenes=reconstruction_scene_rows(connection, workspace, store),
        never_same=[
            (row["entity_a"], row["entity_b"])
            for row in connection.execute(
                "select entity_a, entity_b from never_same where workspace_id = %s "
                "order by entity_a, entity_b",
                (workspace,),
            ).fetchall()
        ],
        deleted_entity_ids=[
            row["entity_id"]
            for row in connection.execute(
                "select entity_id from entity where workspace_id = %s and deleted_at is not null "
                "order by entity_id",
                (workspace,),
            ).fetchall()
        ],
    )


def _state_version(connection: psycopg.Connection, workspace: uuid.UUID) -> int:
    """A number that increases whenever this graph changes, and never decreases.

    The sum of counts over identity, occurrence, assertion, scene, capture, person review
    and tombstone records. A reconstruction becoming drawable and a deletion withdrawing one
    must stale a frame even when neither event changed an occurrence.

    It is not a timestamp and it is not a hash. The read model asks only that a mismatch make a
    frame stale, and that an update proposal computed against an older graph be refused.
    """
    row = connection.execute(
        "select (select count(*) from identity_event where workspace_id = %s) "
        "     + (select count(*) from occurrence where workspace_id = %s) "
        "     + (select count(*) from assertion where workspace_id = %s) "
        "     + (select count(*) from reconstruction_scene where workspace_id = %s) "
        "     + (select count(*) from tombstone where workspace_id = %s) "
        "     + (select count(*) from capture where workspace_id = %s) "
        "     + (select count(*) from person_region where workspace_id = %s) "
        "     + (select count(*) from person_presentation_consent where workspace_id = %s) "
        "as version",
        (workspace,) * 8,
    ).fetchone()
    return int(row["version"])
