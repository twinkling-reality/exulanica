"""Write the evaluation record of three warm generated-asset sessions on Nebius AI Cloud.

The sessions are 3, 3b and 4 of route A, each one Serverless AI job serving lamp posts made to the
``lamp_post`` thing kind (version 2 in sessions 3 and 3b, version 3 in session 4). Their evidence
is held outside the repository, so the script takes its directory as an argument and the record
carries the SHA-256 of every evidence file it read; the committed record is then checked by
``tests/test_generated_asset_sessions_record.py`` from its own fields.

Per session the script reads the ``exulanica.appearance-gpu-run/v2`` record, the session record,
the instant the start command was given, the build listing with each entry's request, the entries
queued, the job's final status, the done markers and every receipt they name, the charge lines,
and for a session that claimed nothing the container log.
Writes ``docs/evaluation/2026-10-09-nebius-generated-asset-warm-sessions.json`` as an
``exulanica.digest-bound-record/v1``. Every figure is computed here from that evidence; nothing is
typed in.

Three costs per session, all at the rate the run record names. The computed cost is the
container's own milliseconds from the start to the finish the job's status states; the billed cost
is the run record's own, its billed seconds from the first STARTING state seen to the job's
deletion; the upper bound runs from the start command to the job's deletion, because the instance
can be held before the first STARTING state is seen. The provider's billing page, read by the
operator, is the only authoritative total.

Run: ``.venv/bin/python scripts/record_generated_asset_sessions.py <evidence directory>``; add
``--check`` to compare the record the evidence builds with the committed one without writing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evaluation/2026-10-09-nebius-generated-asset-warm-sessions.json"
#: The sessions, in the order they ran, by their folder under the evidence directory.
SESSIONS = ("session-3", "session-3b", "session-4")
_STATUS_INSTANT = re.compile(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?Z$")
_PHASE = re.compile(r"\] phase (\w+) ")


def nanoseconds(text: str) -> int:
    """A UTC instant as the job status states it, in integer nanoseconds since the epoch."""
    match = _STATUS_INSTANT.match(text)
    if match is None:
        raise ValueError(f"not a status instant: {text!r}")
    seconds = datetime.strptime(match[1], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)
    return int(seconds.timestamp()) * 1_000_000_000 + int((match[2] or "").ljust(9, "0"))


def seconds_between(start: str, end: str) -> int:
    """Whole seconds between two instants stated to the second, as the run record states them."""
    form = "%Y-%m-%dT%H:%M:%SZ"
    return int((datetime.strptime(end, form) - datetime.strptime(start, form)).total_seconds())


def microdollars(rate_cents_per_hour: int, milliseconds: int) -> int:
    """Rate times milliseconds, in millionths of a dollar, rounded up."""
    return -(-rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)


class _Evidence:
    """Reads files under the evidence directory and keeps the digest of each one read."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.read: dict[str, str] = {}

    def bytes(self, relative: str) -> bytes:
        data = (self.directory / relative).read_bytes()
        self.read[relative] = hashlib.sha256(data).hexdigest()
        return data

    def json(self, relative: str) -> Any:
        return json.loads(self.bytes(relative))

    def names(self, relative: str, pattern: str) -> list[str]:
        folder = self.directory / relative
        if not folder.is_dir():
            return []
        return sorted(f"{relative}/{path.name}" for path in folder.glob(pattern))


def _failure(evidence: _Evidence, folder: str, status: dict[str, Any]) -> str:
    """Why a session that claimed nothing failed: the last phase it entered and the last line."""
    log = evidence.bytes(f"{folder}/watch/logs-final.txt").decode("utf-8")
    lines = [line for line in log.splitlines() if line.strip()]
    phases = [m[1] for line in lines if (m := _PHASE.search(line))]
    last = lines[-1].split("] ", 1)[1]
    details = status["status"]["state_details"]
    return (
        f"failed in the {phases[-1]} phase, before any entry was claimed "
        f"({details['code']}: {details['message']}); the log's last line: {last}"
    )


def _session(evidence: _Evidence, folder: str) -> dict[str, Any]:
    (run_name,) = evidence.names(folder, "gpu-run-*.json")
    run = evidence.json(run_name)
    session = evidence.json(f"{folder}/record.json")
    build = evidence.json(f"{folder}/build/build.json")
    status = evidence.json(f"{folder}/watch/status-final.json")
    rate = run["rate_cents_per_hour"]

    requests: dict[str, dict[str, Any]] = {}
    for index in range(1, len(build["entries"]) + 1):
        for name in evidence.names(f"{folder}/build/entry-{index}/requests", "*.json"):
            data = evidence.bytes(name)
            requests[hashlib.sha256(data).hexdigest()] = json.loads(data)
    boxes = {canonical_json(r["slot_mm"]) for r in requests.values()}
    kinds = {canonical_json(r["thing_kind"]) for r in requests.values()}
    if len(boxes) != 1 or len(kinds) != 1:
        raise ValueError(f"{folder}: requests name more than one box or kind")
    request = next(iter(requests.values()))
    if request["thing_kind"] != build["kind"]:
        raise ValueError(f"{folder}: the requests' kind is not the build's")

    queued = {evidence.json(name)["job_sha256"] for name in evidence.names(folder, "submit-*.json")}
    entries = []
    entry_of: dict[str, str] = {}
    for entry in build["entries"]:
        how = "by key" if entry["words"] is None else "with words"
        entry_of[entry["request_sha256"]] = how
        entries.append(
            {
                "entry": how,
                "items": entry["items"],
                "job_sha256": entry["job_sha256"],
                "queued": entry["job_sha256"] in queued,
                "request_sha256": entry["request_sha256"],
                "words": entry["words"],
            }
        )

    charge_lines = evidence.json(f"{folder}/charges.json") if run["charges"] else []
    charges = []
    for line, listed in zip(run["charges"], charge_lines, strict=True):
        for key in ("job_sha256", "milliseconds", "request_sha256"):
            if line[key] != listed[key]:
                raise ValueError(f"{folder}: charge lines disagree on {key}")
        if line["cost_microdollars"] != microdollars(rate, line["milliseconds"]):
            raise ValueError(f"{folder}: a charge line is not its milliseconds at the rate")
        charges.append(
            {
                "cost_microdollars": line["cost_microdollars"],
                "entry": entry_of[line["request_sha256"]],
                "job_sha256": line["job_sha256"],
                "milliseconds": line["milliseconds"],
                "request_sha256": line["request_sha256"],
            }
        )

    done = [evidence.json(name) for name in evidence.names(f"{folder}/fetch/done", "*.json")]
    pieces = []
    for marker in sorted(done, key=lambda d: d["claimed_at"]):
        for digest in marker["receipts"]:
            receipt_name = f"{folder}/fetch/out/receipts/{digest}.json"
            data = evidence.bytes(receipt_name)
            if hashlib.sha256(data).hexdigest() != digest:
                raise ValueError(f"{receipt_name}: digest differs from its name")
            receipt = json.loads(data)
            measured = receipt["measured"]
            pieces.append(
                {
                    "box_fill_permille": measured["box_fill_permille"],
                    "entry": entry_of[receipt["request_sha256"]],
                    "over": receipt["verdict"]["over"],
                    "piece_sha256": receipt["output"]["sha256"],
                    "receipt_sha256": digest,
                    "request_sha256": receipt["request_sha256"],
                    "size_mm": measured["size_mm"],
                    "variant": receipt["variant"],
                    "within": receipt["verdict"]["within"],
                }
            )
    if sorted(p["receipt_sha256"] for p in pieces) != sorted(run["generations"]):
        raise ValueError(f"{folder}: done markers and the run record name different receipts")

    submitted = evidence.bytes(f"{folder}/start-time.txt").decode("ascii").strip()
    upper = microdollars(rate, seconds_between(submitted, run["deleted_at"]) * 1000)
    started = status["status"]["started_at"]
    finished = status["status"]["finished_at"]
    container_ms = (nanoseconds(finished) - nanoseconds(started)) // 1_000_000
    billed = run["billed_seconds"]
    if billed != seconds_between(run["started_at"], run["deleted_at"]):
        raise ValueError(f"{folder}: billed seconds are not the run record's interval")
    if run["cost_microdollars"] != microdollars(rate, billed * 1000):
        raise ValueError(f"{folder}: the billed cost is not the billed seconds at the rate")

    if done:
        made = sum(d["items"]["made"] for d in done)
        total = sum(d["items"]["total"] for d in done)
        within = sum(d["items"]["within"] for d in done)
        reasons = sorted({r for p in pieces for r in p["over"]})
        outcome = (
            f"{status['status']['state'].lower()}: {len(done)} entries claimed, {made} of "
            f"{total} items made with receipts, {within} within every check"
            + (f", the rest over: {', '.join(reasons)}" if reasons else "")
        )
    else:
        outcome = _failure(evidence, folder, status)

    return {
        "billed_cost_microdollars": run["cost_microdollars"],
        "billed_from": run["started_at"],
        "billed_seconds": billed,
        "billed_to": run["deleted_at"],
        "box_mm": request["slot_mm"],
        "charges": charges,
        "code_sha256": session["code_sha256"],
        "computed_cost_microdollars": microdollars(rate, container_ms),
        "container": session["manifest"]["container"],
        "container_finished_at": finished,
        "container_milliseconds": container_ms,
        "container_started_at": started,
        "entries": entries,
        "job_id": run["instance_name"],
        "kind": build["kind"],
        "outcome": outcome,
        "pack": build["pack"],
        "pieces": pieces,
        "route": session["route"],
        "session": folder.removeprefix("session-"),
        "session_sha256": session["session_sha256"],
        "upper_bound_cost_microdollars": upper,
        "upper_bound_from": submitted,
        "upper_bound_to": run["deleted_at"],
    }


def build(directory: Path) -> dict[str, Any]:
    evidence = _Evidence(directory)
    sessions = [_session(evidence, folder) for folder in SESSIONS]
    (first_run,) = evidence.names(SESSIONS[0], "gpu-run-*.json")
    run = evidence.json(first_run)
    pieces = [p for s in sessions for p in s["pieces"]]
    return {
        "authoritative_total": run["authoritative_total"],
        "compute": {
            "gpu": run["gpu"],
            "instance_type": run["instance_type"],
            "provider": run["provider"],
            "rate_cents_per_hour": run["rate_cents_per_hour"],
            "rate_source": run["rate_source"],
        },
        "evidence": {
            "files_sha256": dict(sorted(evidence.read.items())),
            "held": "outside the repository; paths are relative to the directory the script reads",
        },
        "kind": "exulanica.generated-asset-warm-sessions/v1",
        "script": "scripts/record_generated_asset_sessions.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sessions": sessions,
        "totals": {
            "billed_cost_microdollars": sum(s["billed_cost_microdollars"] for s in sessions),
            "computed_cost_microdollars": sum(s["computed_cost_microdollars"] for s in sessions),
            "pieces_with_receipts": len(pieces),
            "pieces_within_every_check": sum(p["within"] for p in pieces),
            "sessions": len(sessions),
            "upper_bound_cost_microdollars": sum(
                s["upper_bound_cost_microdollars"] for s in sessions
            ),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("evidence", type=Path, help="the directory holding the session folders")
    parser.add_argument("--check", action="store_true", help="compare, do not write")
    arguments = parser.parse_args()
    record = build(arguments.evidence)
    if arguments.check:
        committed = json.loads(OUTPUT.read_bytes())["record"]
        same = committed == record
        print(f"{OUTPUT.relative_to(ROOT)}: {'matches' if same else 'DIFFERS FROM'} the evidence")
        return 0 if same else 1
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    totals = record["totals"]
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {totals}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
