"""Workspace-scoped operational projections over derivative and scene-build ledgers."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from exulanica.ingest.derivative_queue import DERIVATIVES
from exulanica.ingest.spine.reconstruction_jobs import MAX_SCENE_CLAIMS

__all__ = [
    "derivative_job_events",
    "derivative_job_metrics",
    "reconstruction_scene_job",
    "reconstruction_scene_metrics",
    "retry_reconstruction_scene_job",
]


def derivative_job_metrics(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> dict[str, Any]:
    """Queue depth, age, attempts, duration, cost and terminal failure classes.

    Every value is computed from a durable row. A missing duration or cost remains absent from
    its population rather than being treated as zero work.
    """
    row = connection.execute(
        "select "
        " count(*) filter (where state = 'queued') as queued, "
        " count(*) filter (where state = 'running') as running, "
        " count(*) filter (where state in "
        "   ('done','failed','cancelled','missing','unavailable')) as terminal, "
        " max(attempts) as max_attempts, "
        " avg(duration_ms) filter (where duration_ms is not null) as average_duration_ms, "
        " max(duration_ms) filter (where duration_ms is not null) as maximum_duration_ms, "
        " extract(epoch from (clock_timestamp() - min(created_at) "
        "   filter (where state = 'queued'))) * 1000 as oldest_queued_age_ms, "
        " coalesce(sum((cost ->> 'model_calls')::bigint) "
        "   filter (where cost ? 'model_calls'), 0) as model_calls, "
        " coalesce(sum((cost ->> 'input_tokens')::bigint) "
        "   filter (where cost ? 'input_tokens'), 0) as input_tokens, "
        " coalesce(sum((cost ->> 'output_tokens')::bigint) "
        "   filter (where cost ? 'output_tokens'), 0) as output_tokens, "
        " coalesce(sum((cost ->> 'usd_estimate')::numeric) "
        "   filter (where cost ? 'usd_estimate'), 0) as usd_estimate "
        "from job where workspace_id = %s and kind = %s",
        (workspace_id, DERIVATIVES),
    ).fetchone()
    assert row is not None
    states = {
        item["state"]: int(item["n"])
        for item in connection.execute(
            "select state, count(*) as n from job "
            "where workspace_id = %s and kind = %s group by state order by state",
            (workspace_id, DERIVATIVES),
        ).fetchall()
    }
    failures = {
        item["failure_class"]: int(item["n"])
        for item in connection.execute(
            "select failure_class, count(*) as n from job "
            "where workspace_id = %s and kind = %s and failure_class is not null "
            "group by failure_class order by failure_class",
            (workspace_id, DERIVATIVES),
        ).fetchall()
    }
    return {
        "depth": {"queued": int(row["queued"]), "running": int(row["running"])},
        "terminal": int(row["terminal"]),
        "states": states,
        "oldest_queued_age_ms": _integer_or_none(row["oldest_queued_age_ms"]),
        "attempts": {"maximum": int(row["max_attempts"] or 0)},
        "duration_ms": {
            "average": _integer_or_none(row["average_duration_ms"]),
            "maximum": _integer_or_none(row["maximum_duration_ms"]),
        },
        "cost": {
            "model_calls": int(row["model_calls"]),
            "input_tokens": int(row["input_tokens"]),
            "output_tokens": int(row["output_tokens"]),
            "usd_estimate": str(row["usd_estimate"]),
        },
        "failure_classes": failures,
    }


def derivative_job_events(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """The complete delivery replay for one job, or empty for foreign and unknown ids alike."""
    rows = connection.execute(
        "select event_id, job_id, worker_id, event_type, claim_token, attempt, capture_id, "
        "progress_completed, progress_total, duration_ms, cost, failure_class, message, "
        "occurred_at from derivative_job_event "
        "where workspace_id = %s and job_id = %s order by occurred_at, event_id",
        (workspace_id, job_id),
    ).fetchall()
    return [
        {
            key: (
                str(value)
                if isinstance(value, uuid.UUID)
                else value.isoformat()
                if hasattr(value, "isoformat")
                else value
            )
            for key, value in dict(row).items()
            if value is not None
        }
        for row in rows
    ]


def reconstruction_scene_metrics(
    connection: psycopg.Connection, workspace_id: uuid.UUID
) -> dict[str, Any]:
    """Queue health, dependency waits and immutable build history for scene reconstruction."""
    row = connection.execute(
        "select count(*) filter (where status='queued') as queued,"
        "count(*) filter (where status='running') as running,"
        "count(*) filter (where status='failed' and attempts<%s) as retryable,"
        "count(*) filter (where status='succeeded') as succeeded,"
        "count(*) filter (where status='failed') as failed,"
        "count(*) filter (where status='cancelled') as cancelled,"
        "max(attempts) as max_attempts,"
        "extract(epoch from (clock_timestamp()-min(created_at) filter "
        "(where status='queued' or (status='failed' and attempts<%s))))*1000 "
        "as oldest_ready_age_ms from reconstruction_scene_job where workspace_id=%s",
        (MAX_SCENE_CLAIMS, MAX_SCENE_CLAIMS, workspace_id),
    ).fetchone()
    assert row is not None
    waiting = connection.execute(
        "select count(*) as count from derived_artifact d where d.workspace_id=%s "
        "and d.kind='scene_group' and not d.stale and cardinality(d.source_ids)>=3 "
        "and exists (select 1 from unnest(d.source_ids) as member(capture_id) "
        "join capture c on c.workspace_id=d.workspace_id "
        "and c.capture_id=member.capture_id and c.deleted_at is null "
        "where not tombstone_blocks_capture(c.workspace_id,c.capture_id) "
        "and not exists (select 1 from artifact a where a.workspace_id=c.workspace_id "
        "and a.source_blob_sha256=c.blob_sha256 and a.kind='point_map' "
        "and a.superseded_by is null and a.purged_at is null "
        "and a.content_sha256 is not null and a.storage_key is not null "
        "and a.byte_size is not null))",
        (workspace_id,),
    ).fetchone()
    scene_counts = connection.execute(
        "select count(*) as scenes,count(*) filter (where current_job_id is not null) "
        "as published from reconstruction_scene where workspace_id=%s "
        "and not tombstone_blocks_scene(workspace_id,scene_id)",
        (workspace_id,),
    ).fetchone()
    superseded = connection.execute(
        "select count(*) as count from reconstruction_scene_job j "
        "where j.workspace_id=%s and j.status='succeeded' and not exists "
        "(select 1 from reconstruction_scene s where s.workspace_id=j.workspace_id "
        "and s.current_job_id=j.job_id)",
        (workspace_id,),
    ).fetchone()
    recent_builds = connection.execute(
        "select j.job_id,j.scene_id,j.status,j.attempts,j.failure_class,j.created_at,"
        "j.updated_at,j.completed_at,coalesce(s.current_job_id=j.job_id,false) as current "
        "from reconstruction_scene_job j left join reconstruction_scene s "
        "on s.workspace_id=j.workspace_id and s.scene_id=j.scene_id "
        "where j.workspace_id=%s order by j.updated_at desc,j.job_id desc limit 50",
        (workspace_id,),
    ).fetchall()
    dependencies = connection.execute(
        "select count(*) filter (where state='queued') as queued,"
        "count(*) filter (where state='running') as running from job "
        "where workspace_id=%s and kind=%s",
        (workspace_id, DERIVATIVES),
    ).fetchone()
    active = (
        int(dependencies["queued"])
        + int(dependencies["running"])
        + int(row["queued"])
        + int(row["running"])
        + int(row["retryable"])
    )
    reasons: list[str] = []
    if active:
        coordination = "building"
        reasons.append("Derivative or scene work remains eligible or running.")
    elif int(waiting["count"]):
        coordination = "blocked"
        reasons.append("A selected scene group still lacks one or more point maps.")
    elif int(scene_counts["published"]):
        coordination = "ready"
        reasons.append("At least one current scene build is published and no work remains.")
    elif int(row["failed"]):
        coordination = "blocked"
        reasons.append("A scene build exhausted or retained a terminal failure.")
    else:
        coordination = "idle"
        reasons.append("No reconstruction scene has been selected for this workspace.")
    return {
        "coordination": {"state": coordination, "reasons": reasons},
        "dependency_queue": {
            "queued": int(dependencies["queued"]),
            "running": int(dependencies["running"]),
        },
        "depth": {
            "queued": int(row["queued"]),
            "running": int(row["running"]),
            "retryable": int(row["retryable"]),
            "waiting_for_point_maps": int(waiting["count"]),
        },
        "states": {
            "succeeded": int(row["succeeded"]),
            "failed": int(row["failed"]),
            "cancelled": int(row["cancelled"]),
        },
        "oldest_ready_age_ms": _integer_or_none(row["oldest_ready_age_ms"]),
        "attempts": {"maximum": int(row["max_attempts"] or 0)},
        "scenes": {
            "live": int(scene_counts["scenes"]),
            "published": int(scene_counts["published"]),
            "superseded_builds": int(superseded["count"]),
        },
        "recent_builds": [_json_value(dict(build)) for build in recent_builds],
    }


def reconstruction_scene_job(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict[str, Any] | None:
    """One build, its exact inputs, registration outcomes and durable outputs."""
    row = connection.execute(
        "select j.job_id,j.scene_id,j.member_digest,j.selection_policy,"
        "j.selection_policy_digest,j.build_inputs,j.build_input_digest,j.status,j.attempts,"
        "j.privacy_admission_id,j.privacy_admission_digest,"
        "j.available_at,j.claimed_by,j.lease_expires_at,j.pose_manifest_digest,"
        "j.pose_receipt_artifact_id,j.placement_artifact_id,j.gate_artifact_id,"
        "j.rung_assertion_id,"
        "j.failure_class,j.failure_message,j.created_at,j.updated_at,j.completed_at,"
        "coalesce(s.current_job_id=j.job_id,false) as current "
        "from reconstruction_scene_job j "
        "left join reconstruction_scene s on s.workspace_id=j.workspace_id "
        "and s.scene_id=j.scene_id where j.workspace_id=%s and j.job_id=%s",
        (workspace_id, job_id),
    ).fetchone()
    if row is None:
        return None
    members = connection.execute(
        "select m.capture_id,m.ordinal,b.registered from reconstruction_scene_job_member m "
        "left join reconstruction_scene_build_member b on b.workspace_id=m.workspace_id "
        "and b.job_id=m.job_id and b.capture_id=m.capture_id "
        "where m.workspace_id=%s and m.job_id=%s order by m.ordinal,m.capture_id",
        (workspace_id, job_id),
    ).fetchall()
    result = _json_value(dict(row))
    result["members"] = [_json_value(dict(member)) for member in members]
    return result


def retry_reconstruction_scene_job(
    connection: psycopg.Connection,
    workspace_id: uuid.UUID,
    job_id: uuid.UUID,
) -> str | None:
    """Make a retryable failed build immediately eligible without altering its identity."""
    row = connection.execute(
        "select status,attempts from reconstruction_scene_job "
        "where workspace_id=%s and job_id=%s for update",
        (workspace_id, job_id),
    ).fetchone()
    if row is None:
        return None
    if row["status"] != "failed":
        return str(row["status"])
    if int(row["attempts"]) >= MAX_SCENE_CLAIMS:
        return "exhausted"
    connection.execute(
        "update reconstruction_scene_job set available_at=now(),updated_at=now() "
        "where workspace_id=%s and job_id=%s and status='failed' and attempts<%s",
        (workspace_id, job_id, MAX_SCENE_CLAIMS),
    )
    return "retryable"


def _integer_or_none(value: Any) -> int | None:
    return None if value is None else int(value)


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
