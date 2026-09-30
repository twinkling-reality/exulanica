"""Read accounted traffic-light cost and sealed evidence in one workspace.

The seed check runs this once on the restored judge database. The rehearsal also reads it on
its source database before shutdown, including calls made while the seed was exported.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from decimal import Decimal
from typing import Any

from exulanica.db.session import Database


def fingerprint(rows: list[dict[str, Any]]) -> str:
    """Digest the ordered public identities and held document digests of a receipt table."""
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def read(workspace: uuid.UUID) -> dict[str, Any]:
    database = Database.from_env()
    with database.session(workspace) as connection:
        choices = connection.execute(
            "select world_id,version_id::text,choice_seq,signal_id,effective_second,"
            "document_sha256 from world_traffic_signal_choice where workspace_id=%s "
            "order by world_id,version_id,choice_seq",
            (workspace,),
        ).fetchall()
        requests = connection.execute(
            "select world_id,version_id::text,request_id::text,choice_seq,"
            "document_sha256 from world_traffic_signal_decision_request where workspace_id=%s "
            "order by world_id,version_id,request_id",
            (workspace,),
        ).fetchall()
        decisions = connection.execute(
            "select world_id,version_id::text,request_id::text,document_sha256,"
            "document->>'status' as status,document->'provider'->>'cost_usd' as cost_usd,"
            "document->'provider'->>'cost_known' as cost_known "
            "from world_traffic_signal_decision where workspace_id=%s "
            "order by world_id,version_id,request_id",
            (workspace,),
        ).fetchall()
        segments = connection.execute(
            "select world_id,version_id::text,episode,segment,choice_seq,active_second,"
            "decisions_sha256,frames_sha256,continuation_sha256 "
            "from world_traffic_signal_segment where workspace_id=%s "
            "order by world_id,version_id,episode,segment",
            (workspace,),
        ).fetchall()
    return summarize(workspace, choices, requests, decisions, segments)


def summarize(
    workspace: uuid.UUID,
    choices: list[dict[str, Any]],
    requests: list[dict[str, Any]],
    decisions: list[dict[str, Any]],
    segments: list[dict[str, Any]],
) -> dict[str, Any]:
    """Separate known charged cost from an unknown call's reserved upper bound."""
    groups = {
        "choices": list(choices),
        "requests": list(requests),
        "decisions": list(decisions),
        "segments": list(segments),
    }
    accounted = sum(
        (Decimal(row["cost_usd"]) for row in decisions if row["cost_usd"] is not None),
        Decimal(0),
    )
    known = sum(
        (
            Decimal(row["cost_usd"])
            for row in decisions
            if row["cost_usd"] is not None and row["cost_known"] == "true"
        ),
        Decimal(0),
    )
    unknown_calls = sum(
        row["cost_usd"] is not None and row["cost_known"] != "true" for row in decisions
    )
    decided = {(row["world_id"], row["version_id"], row["request_id"]) for row in decisions}
    pending = sum(
        (row["world_id"], row["version_id"], row["request_id"]) not in decided for row in requests
    )
    active = [
        {
            "world_id": choice["world_id"],
            "version_id": choice["version_id"],
            "subject_id": choice["signal_id"],
            "choice_seq": choice["choice_seq"],
            "active_second": segment["active_second"],
        }
        for choice in choices
        for segment in segments
        if choice["world_id"] == segment["world_id"]
        and choice["version_id"] == segment["version_id"]
        and choice["choice_seq"] == segment["choice_seq"]
        and segment["active_second"] is not None
    ]
    return {
        "profile": "exulanica.rehearsal-signal-receipts/v1",
        "workspace_id": str(workspace),
        "counts": {name: len(rows) for name, rows in groups.items()},
        "table_sha256": {name: fingerprint(rows) for name, rows in groups.items()},
        "accepted_decisions": sum(row["status"] == "accepted" for row in decisions),
        "accounted_usd": str(accounted),
        "known_cost_usd": str(known),
        "unknown_cost_calls": unknown_calls,
        "pending_requests": pending,
        "active_choices": active,
    }


def main() -> int:
    print(json.dumps(read(uuid.UUID(sys.argv[1])), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
