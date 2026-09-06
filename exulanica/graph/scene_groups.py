"""The time-and-position clustering ingest computed, and the rung each capture earned.

Together because a group's rung is the WORST any of its members earned, so the two reads are one
question asked at two granularities. Worst rather than best because a region is navigable at the
level of its weakest part, which is the reduction `payload.py` documents and `max` implements:
the rungs run 1 for a full splat to 4 for no geometry, so the largest number is the poorest
result. Neither is an island: ADR-0005 leaves that open until the corpus has been measured, and a
server that shipped an island id would settle it by accident.
"""

from __future__ import annotations

import uuid

import psycopg

from exulanica.graph.payload import SceneGroupRow

__all__ = ["rung_by_capture", "scene_group_rows"]


def scene_group_rows(connection: psycopg.Connection, workspace: uuid.UUID) -> list[SceneGroupRow]:
    """The stored clustering, live rows only.

    ``stale`` is filtered rather than reported. A stale grouping is one whose inputs have changed
    since it was computed, and handing it to a client that would arrange a world out of it would
    be arranging the world from a fact that is known to be out of date. An empty list is the
    honest answer when nothing current exists, and it is one the client already handles: with no
    grouping, every capture stands alone.

    Members are filtered against live captures, so a deleted photograph leaves the group smaller
    rather than leaving a dangling id the client would have to resolve to nothing.
    """
    rows = connection.execute(
        "select d.derived_id, d.payload from derived_artifact d "
        "where d.workspace_id = %s and d.kind = 'scene_group' and d.stale = false "
        "order by (d.payload->>'ordinal')::int",
        (workspace,),
    ).fetchall()
    rungs = rung_by_capture(connection, workspace)
    live = {
        row["capture_id"]
        for row in connection.execute(
            "select capture_id from capture where workspace_id = %s and deleted_at is null",
            (workspace,),
        ).fetchall()
    }
    groups: list[SceneGroupRow] = []
    for row in rows:
        payload = row["payload"] or {}
        members = [
            capture_id
            for capture_id in (uuid.UUID(value) for value in payload.get("capture_ids", []))
            if capture_id in live
        ]
        if not members:
            continue
        earned = [rungs[capture_id] for capture_id in members if capture_id in rungs]
        groups.append(
            SceneGroupRow(
                rung=max(earned) if earned else None,
                rung_capture_count=len(earned),
                group_id=row["derived_id"],
                ordinal=int(payload.get("ordinal", 0)),
                capture_ids=members,
                first_utc=payload.get("first_utc"),
                last_utc=payload.get("last_utc"),
                # Recounted from the live members rather than read from the payload, which
                # recorded the count at the moment the group was computed.
                member_count=len(members),
                positioned_member_count=int(payload.get("positioned_member_count", 0)),
                radius_m=payload.get("radius_m"),
                centroid_lat_e7=payload.get("centroid_lat_e7"),
                centroid_lon_e7=payload.get("centroid_lon_e7"),
            )
        )
    return groups


def rung_by_capture(connection: psycopg.Connection, workspace: uuid.UUID) -> dict[uuid.UUID, int]:
    """The rung each capture earned, from the claim that records it.

    Read from ``assertion`` rather than from a column, because the rung is not a property of the
    photograph: it is what a particular model at a particular version managed to place from it,
    and a different checkpoint gives a different answer over the same bytes. Migration 0005 seeds
    the predicate with ``allows_kind = {inference}`` alone, so the database refuses a rung filed
    as a capture-supported fact whatever the pipeline later tries.

    Active rows only, NEWEST FIRST, and the ordering is a backstop rather than decoration.
    **CORRECTED:** R16 was closed by migration 0006 and repaired by migration 0009.
    ``assertion_one_active_claim_per_functional_subject`` constrains the active row, and
    ``tg_assertion_supersedes_the_previous_functional_claim`` reads ``predicate.functional``.
    The ``distinct on`` remains useful for routes a BEFORE trigger cannot see and because the
    index is partial on active rows. Taking the newest per capture keeps that fallback
    deterministic without claiming the functional rule is unenforced.

    A superseded rung is what a previous run believed and stays readable in the history;
    presenting it as current would be presenting a stale reconstruction as the one on screen.
    """
    rows = connection.execute(
        "select distinct on (a.subject_ref->>'id') "
        "  a.subject_ref->>'id' as capture_id, a.object_value->>'rung' as rung "
        "from assertion a join predicate p on p.predicate_id = a.predicate_id "
        "where a.workspace_id = %s and p.key = 'reconstruction_rung_is' "
        "  and a.status = 'active' and a.subject_ref->>'type' = 'capture' "
        "order by a.subject_ref->>'id', a.asserted_at desc, a.assertion_id desc",
        (workspace,),
    ).fetchall()
    return {uuid.UUID(row["capture_id"]): int(row["rung"]) for row in rows if row["rung"]}
