"""Hold a live run to its stop rule: pause the world when a mind's provider keeps failing.

    python3 scripts/demo/provider_failure_guard.py --api <the stack's API address>
        --record <the world's record> --token-file <the owner's token file> --stop <a file>
        [--limit 3] [--log <a file>] [--tripped <a new file>]

Every few seconds it reads the society's events (newest first, until the ones it has seen) and
keeps, per being, how many of its decisions in a row ended in a provider failure: a timeout, an
error answer or a call that did not complete (``model_timed_out``, ``model_call_failed``,
``model_unavailable``). Any other decision ends that being's row. At ``--limit`` in a row it pauses
the society through the owner's playback control, writes ``--tripped`` (the being, its minutes, the
reasons) and exits 1: no model is asked while a world is paused. It exits 0 once ``--stop``
exists. The record is the one ``start_society.py`` or ``build_scene.py`` writes (``world_id``,
``version_id``). The token is read once and never written. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

#: What a decision's reason says when its provider, not its answer, failed.
PROVIDER_FAILURES = frozenset({"model_timed_out", "model_call_failed", "model_unavailable"})


class Streaks:
    """Each being's provider failures in a row, from decisions fed in any batches."""

    def __init__(self, limit: int = 3) -> None:
        self.limit = limit
        self.seen: set[str] = set()
        self.rows: dict[str, list[tuple[int, str]]] = {}

    def unseen(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [event for event in events if event["event_id"] not in self.seen]

    def feed(self, events: list[dict[str, Any]]) -> tuple[str, list[tuple[int, str]]] | None:
        """Count the new events' decisions in the world's order; the first being at the limit and
        its failures (minute, reason), else None."""
        fresh = sorted(
            self.unseen(events),
            key=lambda event: (event["tick"], (event.get("document") or {}).get("order", 0)),
        )
        for event in fresh:
            self.seen.add(event["event_id"])
            if event["event_kind"] != "decision_applied":
                continue
            subject = str(event.get("subject_id"))
            reason = (event.get("document") or {}).get("reason")
            if reason in PROVIDER_FAILURES:
                self.rows.setdefault(subject, []).append((event["tick"], reason))
            else:
                self.rows[subject] = []
            if len(self.rows.get(subject, [])) >= self.limit:
                return subject, self.rows[subject]
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--stop", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--log", type=Path, default=None)
    parser.add_argument("--tripped", type=Path, default=None)
    args = parser.parse_args()
    record = json.loads(args.record.read_text(encoding="utf-8"))
    token = args.token_file.read_text(encoding="utf-8").strip()
    base = f"{args.api.rstrip('/')}/world/versions/{record['version_id']}/society"
    query = urllib.parse.urlencode({"world_id": record["world_id"]})

    def call(method: str, path: str, body: Any = None, more: str = "") -> Any:
        request = urllib.request.Request(
            f"{base}{path}?{query}{more}",
            method=method,
            data=None if body is None else json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as answer:
            return json.load(answer)

    def say(line: str) -> None:
        text = f"{time.strftime('%H:%M:%S')} {line}"
        print(text, flush=True)
        if args.log:
            with args.log.open("a", encoding="utf-8") as out:
                out.write(text + "\n")

    streaks = Streaks(args.limit)
    reported: dict[str, int] = {}
    say("watching")
    while not args.stop.exists():
        time.sleep(3)
        try:
            fresh: list[dict[str, Any]] = []
            before = None
            while True:
                page = call("GET", "/events", more=f"&before={before}" if before else "")
                new = streaks.unseen(page["events"])
                fresh += new
                if len(new) < len(page["events"]) or not page.get("next"):
                    break
                before = str(page["next"])
        except Exception as error:  # a read that fails is tried again
            say(f"events unread: {type(error).__name__}")
            continue
        tripped = streaks.feed(fresh)
        for subject, row in streaks.rows.items():
            if len(row) > reported.get(subject, 0):
                minute, reason = row[-1]
                say(f"provider failure {len(row)} in a row: {subject[:8]} minute {minute} {reason}")
            reported[subject] = len(row)
        if tripped is not None:
            subject, failures = tripped
            control = call("GET", "/control")
            call(
                "PUT",
                "/control",
                {
                    "base_revision": control["revision"],
                    "mode": "paused",
                    "speed": control.get("speed") or 1,
                },
            )
            if args.tripped:
                detail = {
                    "subject": subject,
                    "failures": failures,
                    "paused_at": time.strftime("%H:%M:%S"),
                }
                args.tripped.write_text(json.dumps(detail, indent=1) + "\n", encoding="utf-8")
            say(f"STOP RULE: {len(failures)} provider failures in a row for {subject[:8]}; paused")
            return 1
    say("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
