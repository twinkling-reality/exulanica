"""Measure what each model-run being of a world version chose, from its stored decision records.

    uv run python scripts/measure_being_choices.py --api http://127.0.0.1:20051 \\
        --world-id WORLD --version-id VERSION --token-file PATH --out measures.json \\
        [--subject-id SUBJECT]

Reads only, by GET, through the World API, with the reader of ``trace_completeness.py`` beside it:
the version's models read, every page of its society events and each decision record those name.
So both tools count the same asks: every request a ``decision_applied`` event closed and each
being's latest, a request no minute consumed (a timeout before a pause) among them. The bearer is
read from ``--token-file`` into memory and sent only in the ``Authorization`` header; the API must
be on this machine (a loopback host), since the tool reads runtime copies.

For each being asked at least once (or the one ``--subject-id`` names) it reports, in the order the
being was asked:

*   asks, answers accepted, choices applied, refused when the minute came (accepted, then rejected),
    not taken up (stale or superseded), no answer (a receipt that was not accepted, or none), and
    asks no minute consumed;
*   the longest run of consecutive identical chosen labels, and of identical option kinds; distinct
    labels and kinds; the share of accepted answers that chose to wait;
*   applied moves (an applied choice whose recorded path, from its minute until the being's next
    applied decision, is longer than zero) and the metres of those paths, as the trace reads them;
*   lines the being said (its ``said`` events) and how many repeat an earlier one word for word;
*   each request's context in bytes of canonical JSON (median, maximum), the prompt versions and
    models asked, model calls, and the known cost per accepted answer from the receipts.

It writes the report as JSON and prints a plain summary. It never calls a model.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import statistics
import sys
import urllib.parse
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

PROFILE = "exulanica.being-choice-measures/v1"
#: The hosts the tool reads from: runtime copies on this machine.
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def _trace_module() -> ModuleType:
    """``trace_completeness.py`` beside this script, the reader both tools share."""
    path = Path(__file__).resolve().with_name("trace_completeness.py")
    spec = importlib.util.spec_from_file_location("trace_completeness", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


trace_completeness = _trace_module()


def _canonical_bytes(value: Any) -> int:
    """The bytes of ``value`` as canonical JSON, as the decision contract counts a context."""
    from exulanica.canonical import canonical_json

    return len(canonical_json(value))


def _taken(row: Mapping[str, Any]) -> str:
    """What became of one ask, in the words the being's own memory keeps, or ``not_consumed``."""
    if row["status"] != "accepted" or row["chose"] is None:
        return "no_answer"
    if row["consumed_tick"] is None:
        return "not_consumed"
    if row["disposition"] == "applied":
        return "applied"
    return "refused" if row["disposition"] == "rejected" else "not_taken_up"


def _longest_run(values: Sequence[Any]) -> int:
    longest = current = 0
    previous: Any = object()
    for value in values:
        current = current + 1 if value == previous else 1
        previous = value
        longest = max(longest, current)
    return longest


def measure(world: Mapping[str, Any], report: Mapping[str, Any], subject_id: str) -> dict[str, Any]:
    """The measures of one being from one read of a world version (``world``, as
    :func:`trace_completeness.read_world` answers it) and its trace (``report``)."""
    rows = [row for row in report["requests"] if row["subject_id"] == subject_id]
    records = world["records"]
    asks = []
    for row in rows:
        record = records.get(row["request_id"], {})
        request = record.get("request") or {}
        receipt = record.get("decision") or {}
        proposal = receipt.get("proposal") or {}
        provider = receipt.get("provider") or {}
        config = request.get("provider_config") or {}
        asks.append(
            {
                "request_id": row["request_id"],
                "asked_at": row["base_tick"],
                "consumed_at": row["consumed_tick"],
                "status": row["status"],
                "reason": row["reason"],
                "taken": _taken(row),
                "chose": row["chose"],
                "kind": (proposal.get("option") or {}).get("kind"),
                "metres": None if row["path"] is None else row["path"]["metres"],
                "context_bytes": None
                if "context" not in request
                else _canonical_bytes(request["context"]),
                "prompt_version": config.get("prompt_version"),
                "model_id": config.get("model_id"),
                # The attempts the call paid for, as the execution record lists them.
                "calls": len(provider.get("calls") or ()),
                "cost_usd": provider.get("cost_usd") if provider.get("cost_known") else None,
            }
        )
    accepted = [ask for ask in asks if ask["chose"] is not None]
    applied = [ask for ask in asks if ask["taken"] == "applied"]
    moves = [ask for ask in applied if (ask["metres"] or 0) > 0]
    contexts = [ask["context_bytes"] for ask in asks if ask["context_bytes"] is not None]
    known = [Decimal(str(ask["cost_usd"])) for ask in accepted if ask["cost_usd"] is not None]
    lines = [
        event["document"].get("thing", {}).get("line")
        for event in sorted(
            world["events"], key=lambda e: (e["tick"], e["document"].get("order", 0))
        )
        if event.get("event_kind") == "said" and event.get("subject_id") == subject_id
    ]
    repeats = sum(1 for index, line in enumerate(lines) if line in lines[:index])
    counted = {
        taken: sum(1 for ask in asks if ask["taken"] == taken)
        for taken in ("applied", "refused", "not_taken_up", "no_answer", "not_consumed")
    }
    return {
        "subject_id": subject_id,
        "asks": len(asks),
        "accepted": len(accepted),
        **counted,
        "longest_identical_labels": _longest_run([ask["chose"] for ask in accepted]),
        "longest_identical_kinds": _longest_run([ask["kind"] for ask in accepted]),
        "distinct_labels": len({ask["chose"] for ask in accepted}),
        "distinct_kinds": len({ask["kind"] for ask in accepted}),
        "wait_share": None
        if not accepted
        else round(sum(1 for ask in accepted if ask["kind"] == "wait") / len(accepted), 3),
        "applied_moves": len(moves),
        "metres_moved": round(sum(ask["metres"] for ask in moves), 1),
        "lines_said": len(lines),
        "lines_repeated": repeats,
        "context_bytes_median": None if not contexts else statistics.median(contexts),
        "context_bytes_maximum": None if not contexts else max(contexts),
        "prompt_versions": sorted({ask["prompt_version"] for ask in asks if ask["prompt_version"]}),
        "models": sorted({ask["model_id"] for ask in asks if ask["model_id"]}),
        "calls": sum(ask["calls"] for ask in asks),
        "cost_known_usd": str(sum(known, Decimal(0))),
        "cost_unknown_answers": sum(1 for ask in accepted if ask["cost_usd"] is None),
        "cost_per_accepted_usd": None
        if not known
        else str((sum(known, Decimal(0)) / len(known)).quantize(Decimal("0.00000001"))),
        "in_order": asks,
    }


def measures(world: Mapping[str, Any], subject_id: str | None = None) -> dict[str, Any]:
    """The report for one read of a world version: the trace's completeness and each being's
    measures, every being asked at least once or the one ``subject_id`` names."""
    report = trace_completeness.trace(world)
    subjects = sorted({row["subject_id"] for row in report["requests"] if row["subject_id"]})
    if subject_id is not None:
        subjects = [subject for subject in subjects if subject == subject_id]
    return {
        "profile": PROFILE,
        "society_id": report["society_id"],
        "trace_complete": report["complete"],
        "trace_checks": report["checks"],
        "beings": [measure(world, report, subject) for subject in subjects],
    }


def summary_lines(result: Mapping[str, Any]) -> list[str]:
    lines = [
        "Trace complete." if result["trace_complete"] else "Trace NOT complete; read the checks."
    ]
    for being in result["beings"]:
        lines.append(
            f"{being['subject_id']}: {being['asks']} asks, {being['accepted']} accepted, "
            f"{being['applied']} applied, {being['no_answer']} no answer, "
            f"{being['not_consumed']} not consumed; longest identical run "
            f"{being['longest_identical_labels']}; {being['distinct_labels']} distinct labels; "
            f"wait share {being['wait_share']}; {being['applied_moves']} moves, "
            f"{being['metres_moved']} m; {being['lines_said']} lines "
            f"({being['lines_repeated']} repeated); context median "
            f"{being['context_bytes_median']} B, maximum {being['context_bytes_maximum']} B; "
            f"cost per accepted answer {being['cost_per_accepted_usd']} USD"
        )
    return lines


def _loopback(api: str) -> str:
    host = urllib.parse.urlsplit(api).hostname
    if host not in LOOPBACK:
        raise SystemExit(f"refused: {api} is not on this machine; this tool reads runtime copies")
    return api


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True, help="the World API's base URL, on this machine")
    parser.add_argument("--world-id", required=True)
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--subject-id", default=None)
    parser.add_argument("--token-file", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    arguments = parser.parse_args(argv)
    api = _loopback(arguments.api)
    if arguments.out.exists():
        raise SystemExit(f"refused: {arguments.out} exists")
    token = arguments.token_file.read_text(encoding="utf-8").strip()
    get = trace_completeness.http_get(api, token, arguments.world_id)
    world = trace_completeness.read_world(get, arguments.version_id)
    result = {
        "world_id": arguments.world_id,
        "version_id": arguments.version_id,
        **measures(world, arguments.subject_id),
    }
    arguments.out.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("\n".join(summary_lines(result)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
