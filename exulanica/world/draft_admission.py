"""Shared durable admission for native kind and whole-world drafts."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg


def bind(
    connection: psycopg.Connection[Any],
    actor: uuid.UUID,
    maximum: int,
    workspace_maximum: int,
) -> None:
    connection.execute(
        "select set_config('exulanica.world_draft_actor',%s,true),"
        "set_config('exulanica.world_draft_starts_maximum',%s,true),"
        "set_config('exulanica.draft_workspace_maximum',%s,true)",
        (str(actor), str(maximum), str(workspace_maximum)),
    )


def allowance(
    connection: psycopg.Connection[Any],
    workspace: uuid.UUID,
    actor: uuid.UUID,
    maximum: int,
) -> dict:
    with connection.transaction():
        connection.execute(
            "select set_config('exulanica.world_draft_actor',%s,true)", (str(actor),)
        )
        row = connection.execute(
            "select draft_person_allowance(%s,%s) as document", (actor, maximum)
        ).fetchone()
        assert row is not None
        result = row["document"]
        rows = connection.execute(
            "select s.draft_id,s.actor_id,s.purpose from ("
            "select draft_id,actor_id,job_id,started_at,'kind' as purpose from kind_draft_start "
            "where workspace_id=%s "
            "union all select draft_id,actor_id,job_id,started_at,'world' as purpose from "
            "world_draft_start where workspace_id=%s"
            ") s join job j using(job_id) where j.state in ('queued','running') order by "
            "s.started_at",
            (workspace, workspace),
        ).fetchall()
        return dict(result, running=rows[0] if rows else None, running_count=len(rows))


def refusal(failure: psycopg.errors.RaiseException) -> tuple[str, int | None] | None:
    code = failure.diag.message_primary
    if code not in {"kind_draft_limit", "kind_draft_busy"}:
        return None
    detail = json.loads(failure.diag.message_detail or "{}")
    return code, detail.get("retry_after_seconds")
