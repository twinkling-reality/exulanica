"""Check that every model decision of a world version can be traced from request to result.

    uv run python scripts/trace_completeness.py --api http://127.0.0.1:8000 \\
        --world-id WORLD --version-id VERSION --token-file PATH --out trace.json

Reads only, by GET, through the World API: the version's models read
(``/world/versions/{v}/society/models``), every page of its society events
(``/society/events``), and each decision record (``/society/decisions/{request_id}``). The bearer is
read from ``--token-file`` into memory and sent only in the ``Authorization`` header.

Request ids come from the records the API returns, never from recomputing them: each
``decision_applied`` event names the request it closed, and the models read names each being's
latest. There is no route that lists every request, so a request no event and no ``latest`` names
is found only as a gap in the society-wide ``decision_seq`` of the receipts that are read; the
models read's own decision count is compared too.

For each request it reports: whether a receipt is recorded and its status and reason, the minute
that consumed it and that minute's disposition, whether a ``decision_applied`` event records it and
binds the receipt's digest, and for an applied choice the being's recorded path from that minute
until its next applied decision. It writes the report as JSON (``--out``) and prints a plain summary.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

PROFILE = "exulanica.trace-completeness/v1"
#: The most event pages one run reads; a longer history is reported as not read to its start.
EVENT_PAGES_MAXIMUM = 200

#: ``get(path, query)`` answers the parsed JSON body of a GET, or raises :class:`ReadFailed`.
Get = Callable[[str, Mapping[str, str]], Any]


class ReadFailed(Exception):
    """A GET that did not answer 200, with its status."""

    def __init__(self, path: str, status: int) -> None:
        super().__init__(f"GET {path} answered {status}")
        self.status = status


def http_get(api: str, token: str, world_id: str) -> Get:
    """A GET against ``api`` naming ``world_id``, with the bearer in its header only."""

    def get(path: str, query: Mapping[str, str]) -> Any:
        url = f"{api.rstrip('/')}{path}?{urllib.parse.urlencode({**query, 'world_id': world_id})}"
        request = urllib.request.Request(
            url, method="GET", headers={"Authorization": f"Bearer {token}"}
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            raise ReadFailed(path, error.code) from None

    return get


def read_world(get: Get, version_id: str) -> dict[str, Any]:
    """The models read, every events page (newest first), and each named decision record."""
    base = f"/world/versions/{urllib.parse.quote(version_id)}"
    models = get(f"{base}/society/models", {})
    events: list[dict[str, Any]] = []
    before: str | None = None
    complete = False
    for _ in range(EVENT_PAGES_MAXIMUM):
        page = get(
            f"{base}/society/events",
            {"limit": "256", **({} if before is None else {"before": before})},
        )
        events.extend(page["events"])
        before = page.get("next")
        if before is None:
            complete = True
            break
    records: dict[str, Any] = {}
    for request_id in named_requests(models, events):
        try:
            records[request_id] = get(
                f"{base}/society/decisions/{urllib.parse.quote(request_id)}", {}
            )
        except ReadFailed as failed:
            records[request_id] = {"read_failed": failed.status}
    return {"models": models, "events": events, "events_complete": complete, "records": records}


def named_requests(models: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> list[str]:
    """Every request id the records name: a decision event's, and each being's latest."""
    named = {
        event["document"]["request_id"]
        for event in events
        if event.get("event_kind") == "decision_applied" and event["document"].get("request_id")
    }
    named |= {entry["request_id"] for entry in models.get("latest", []) if entry.get("request_id")}
    return sorted(named)


def _length(path: Sequence[Sequence[float]]) -> float:
    return sum(math.dist(path[index - 1][:2], path[index][:2]) for index in range(1, len(path)))


def recorded_path(
    events: Sequence[Mapping[str, Any]], subject_id: str, request_id: str, applied_at: int
) -> dict[str, Any]:
    """The being's walked path from ``applied_at`` until its next applied decision, by minute."""
    own = sorted(
        (
            event
            for event in events
            if event.get("subject_id") == subject_id and event["tick"] >= applied_at
        ),
        key=lambda event: (event["tick"], event["document"].get("order", 0)),
    )
    following = next(
        (
            event["tick"]
            for event in own
            if event.get("event_kind") == "decision_applied"
            and event["document"].get("request_id") != request_id
            and event["document"].get("disposition") == "applied"
            and event["tick"] > applied_at
        ),
        None,
    )
    minutes: list[dict[str, Any]] = []
    arrived_at = None
    for event in own:
        if following is not None and event["tick"] >= following:
            break
        if event.get("event_kind") != "route_progressed":
            continue
        path = event["document"].get("motion_path_mm") or []
        minutes.append(
            {"minute": event["tick"], "points": len(path), "metres": round(_length(path) / 1000, 1)}
        )
        if event["document"].get("reason") == "arrived_at_access_node":
            arrived_at = event["tick"]
    return {
        "minutes": minutes,
        "metres": round(float(sum(minute["metres"] for minute in minutes)), 1),
        "arrived_at": arrived_at,
        "until": following,
    }


def trace(world: Mapping[str, Any]) -> dict[str, Any]:
    """The completeness report for one read of a world version."""
    models, events, records = world["models"], world["events"], world["records"]
    latest = {
        entry["request_id"]: entry for entry in models.get("latest", []) if entry.get("request_id")
    }
    closing = {
        event["document"]["request_id"]: event
        for event in events
        if event.get("event_kind") == "decision_applied" and event["document"].get("request_id")
    }
    oldest = min((event["tick"] for event in events), default=None)
    rows = []
    for request_id in sorted(records, key=lambda key: _order(records[key], latest.get(key))):
        record = records[request_id]
        event = closing.get(request_id)
        summary = latest.get(request_id)
        receipt = record.get("decision") if "read_failed" not in record else None
        request = record.get("request") or {}
        consumed = (
            event["tick"]
            if event is not None
            else summary.get("consumed_tick")
            if summary
            else None
        )
        disposition = (
            event["document"].get("disposition")
            if event is not None
            else summary.get("disposition")
            if summary
            else None
        )
        row: dict[str, Any] = {
            "request_id": request_id,
            "subject_id": request.get("subject_id") or (summary or {}).get("subject_id"),
            "base_tick": request.get("base_tick"),
            "read_failed": record.get("read_failed"),
            "receipt_present": receipt is not None,
            "decision_seq": None if receipt is None else receipt.get("decision_seq"),
            "status": None if receipt is None else receipt.get("status"),
            "reason": None if receipt is None else receipt.get("reason"),
            "chose": None
            if receipt is None or receipt.get("proposal") is None
            else receipt["proposal"].get("label"),
            "consumed_tick": consumed,
            "disposition": disposition,
            "decision_applied_event": event is not None,
            "event_binds_receipt": None
            if event is None or receipt is None
            else event["document"].get("decision_sha256") == receipt.get("document_sha256"),
            "path": None,
            "problems": [],
        }
        problems: list[str] = row["problems"]
        if record.get("read_failed") is not None:
            problems.append("record_unreadable")
        elif receipt is None:
            problems.append("no_receipt")
        # Consumed in a minute the events read covers, yet no event records what it did.
        covered = oldest is not None and consumed is not None and consumed >= oldest
        if event is None and covered and world.get("events_complete", True):
            problems.append("consumed_without_event")
        if event is not None and receipt is not None and row["event_binds_receipt"] is False:
            problems.append("event_receipt_digest_mismatch")
        if disposition == "applied" and receipt is not None and receipt.get("status") != "accepted":
            problems.append("applied_without_acceptance")
        if disposition == "applied" and row["subject_id"] is not None and consumed is not None:
            option = ((receipt or {}).get("proposal") or {}).get("option") or {}
            row["path"] = recorded_path(events, row["subject_id"], request_id, consumed)
            if option.get("action") == "go" and row["path"]["metres"] == 0:
                problems.append("applied_go_without_movement")
        rows.append(row)
    sequences = sorted(row["decision_seq"] for row in rows if isinstance(row["decision_seq"], int))
    gaps = sorted(set(range(sequences[0], sequences[-1] + 1)) - set(sequences)) if sequences else []
    window = models.get("decisions_read") or {}
    counted = sum(entry.get("decisions", 0) for entry in models.get("by_model", []))
    checks = {
        "events_read_to_start": bool(world.get("events_complete", False)),
        "decision_seq_gaps": gaps,
        # Comparable only while the models read counts every decision, not a latest window.
        "models_read_counts": counted,
        "models_read_counts_all": window.get("counted", 0) < window.get("maximum", 0),
        "models_read_count_matches": counted == len(rows)
        if window.get("counted", 0) < window.get("maximum", 0)
        else None,
    }
    complete = (
        all(not row["problems"] for row in rows)
        and not gaps
        and checks["events_read_to_start"]
        and checks["models_read_count_matches"] is not False
    )
    return {
        "profile": PROFILE,
        "society_id": models.get("society_id"),
        "requests": rows,
        "checks": checks,
        "complete": complete,
    }


def _order(record: Mapping[str, Any], summary: Mapping[str, Any] | None) -> tuple[int, int]:
    receipt = record.get("decision") or {}
    request = record.get("request") or {}
    return (
        receipt.get("decision_seq", 1 << 30),
        request.get("base_tick", (summary or {}).get("base_tick", 1 << 30)),
    )


def summary_lines(report: Mapping[str, Any]) -> list[str]:
    """The report in plain sentences, one request per line."""
    rows = report["requests"]
    lines = [f"{len(rows)} decision requests found from the records."]
    for row in rows:
        state = "no receipt" if not row["receipt_present"] else f"{row['status']} ({row['reason']})"
        minute = (
            "not consumed by any minute"
            if row["consumed_tick"] is None
            else f"consumed in minute {row['consumed_tick']}, {row['disposition']}"
        )
        event = "event recorded" if row["decision_applied_event"] else "no decision event"
        moved = ""
        if row["path"] is not None:
            path = row["path"]
            moved = f"; path {path['metres']} m over {len([m for m in path['minutes'] if m['metres'] > 0])} minute(s)"
            if path["arrived_at"] is not None:
                moved += f", arrived in minute {path['arrived_at']}"
        problems = f"; PROBLEMS: {', '.join(row['problems'])}" if row["problems"] else ""
        chose = "" if row["chose"] is None else f" chose “{row['chose']}”;"
        lines.append(
            f"- seq {row['decision_seq']}, asked at minute {row['base_tick']}:{chose} {state}; "
            f"{minute}; {event}{moved}{problems}"
        )
    checks = report["checks"]
    lines.append(
        "Events read to the start of the history."
        if checks["events_read_to_start"]
        else "Events were NOT read to the start of the history."
    )
    lines.append(
        "No gap in the decision sequence."
        if not checks["decision_seq_gaps"]
        else f"Gaps in the decision sequence: {checks['decision_seq_gaps']}."
    )
    if checks["models_read_count_matches"] is not None:
        lines.append(
            f"The models read counts {checks['models_read_counts']} decisions; "
            f"{'that matches' if checks['models_read_count_matches'] else 'that does NOT match'} the requests found."
        )
    lines.append("Trace complete." if report["complete"] else "Trace NOT complete.")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True, help="the World API's base URL")
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="where the JSON report is written")
    arguments = parser.parse_args(argv)
    token = arguments.token_file.read_text(encoding="utf-8").strip()
    world = read_world(http_get(arguments.api, token, arguments.world_id), arguments.version_id)
    report = {"world_id": arguments.world_id, "version_id": arguments.version_id, **trace(world)}
    arguments.out.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("\n".join(summary_lines(report)))
    return 0 if report["complete"] else 1


if __name__ == "__main__":
    sys.exit(main())
