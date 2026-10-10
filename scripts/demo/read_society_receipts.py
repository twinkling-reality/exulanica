"""Play a society for some minutes on a stack, pause it, and keep what a rehearsal or a take checks.

    EXULANICA_TOKEN=<the owner's token> python3 scripts/demo/read_society_receipts.py
        --base-url <the stack's API address> --record <the world's record> --out <a folder>
        [--minutes 1] [--speed 4] [--wait-seconds 900] [--decisions]

Reads the record ``build_scene.py`` or ``start_society.py`` wrote (world, version), plays the
version's society through the owner's playback control until it has run the given minutes or the
wait runs out, pauses it, then keeps:

- control.json: the final control read (minute, state digest, host playback);
- events.json: every society event, all pages;
- decisions.json: each being's latest decision and the totals over every model asked (decisions
  asked, accepted, applied, cost, whether every cost was known), summed: no per-model figure is
  kept, so the run makes no comparison of models;
- replay.json: the replay's state digest beside the society's, which must be equal;
- with --decisions, decisions-read.json: each decision the events name by request id, read back
  with every usage, token, cost and latency field removed, so what a being was offered and what it
  chose are kept and still no figure sets one model beside another.

With ``--minutes 0`` it plays nothing and leaves the control as it is: a world a stop rule paused
is read as it stands, and no model is asked. A stack's receipts live in its database, so this runs
before the stack goes down. Standard library only. The token is read from the environment and
never written or printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from decimal import Decimal
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def call(base: str, token: str, method: str, path: str, query: dict, body: Any = None) -> Any:
    url = f"{base}{path}?{urllib.parse.urlencode(query)}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as error:
        raise SystemExit(f"{method} {path}: {error.code} {error.read()[:400]!r}") from None


_FIGURES = ("usage", "token", "cost", "latency", "price", "elapsed", "duration")


def _without_figures(value: Any) -> Any:
    """``value`` with every field whose name holds a usage, token, cost or timing word removed."""
    if isinstance(value, dict):
        return {
            key: _without_figures(item)
            for key, item in value.items()
            if not any(word in key.lower() for word in _FIGURES)
        }
    if isinstance(value, list):
        return [_without_figures(item) for item in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--record", type=Path, required=True)
    parser.add_argument("--minutes", type=int, default=10)
    parser.add_argument("--speed", type=int, choices=(1, 2, 4), default=4)
    parser.add_argument("--wait-seconds", type=int, default=900)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--decisions", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("EXULANICA_TOKEN")
    if not token:
        print("set EXULANICA_TOKEN", file=sys.stderr)
        return 2
    record = json.loads(args.record.read_text(encoding="utf-8"))
    base, query = args.base_url.rstrip("/"), {"world_id": record["world_id"]}
    society = f"/world/versions/{record['version_id']}/society"
    args.out.mkdir(parents=True, exist_ok=True)

    control = call(base, token, "GET", f"{society}/control", query)
    start_tick = control["current_tick"]
    if args.minutes == 0:
        print(
            f"{time.strftime('%H:%M:%S')} read at minute {start_tick}, "
            f"{control['mode']}, without playing"
        )
    elif control["host_playback"]["running"] is not True:
        raise SystemExit(f"this host does not play the world: {control['host_playback']['reason']}")
    if args.minutes > 0:
        control = call(
            base,
            token,
            "PUT",
            f"{society}/control",
            query,
            {"base_revision": control["revision"], "mode": "playing", "speed": args.speed},
        )
        started = time.monotonic()
        print(f"{time.strftime('%H:%M:%S')} playing from minute {start_tick} at speed {args.speed}")
        last = None
        while time.monotonic() - started < args.wait_seconds:
            control = call(base, token, "GET", f"{society}/control", query)
            if control["current_tick"] != last:
                last = control["current_tick"]
                print(f"{time.strftime('%H:%M:%S')} minute {last}")
            if control["current_tick"] >= start_tick + args.minutes:
                break
            time.sleep(2)
        control = call(
            base,
            token,
            "PUT",
            f"{society}/control",
            query,
            {"base_revision": control["revision"], "mode": "paused", "speed": args.speed},
        )
        print(f"{time.strftime('%H:%M:%S')} paused at minute {control['current_tick']}")
    (args.out / "control.json").write_text(json.dumps(control, indent=1) + "\n", encoding="utf-8")

    events: list[Any] = []
    page: dict = {}
    while True:
        answer = call(base, token, "GET", f"{society}/events", {**query, **page})
        events.extend(answer["events"])
        if not answer.get("next"):
            break
        page = {"before": str(answer["next"])}  # newest first; "next" is the older page's cursor
    (args.out / "events.json").write_text(json.dumps(events, indent=1) + "\n", encoding="utf-8")

    models = call(base, token, "GET", f"{society}/models", query)
    beings = {mind["person_id"]: mind["thing_id"] for mind in record["society"]["minds"]}
    totals: dict[str, Any] = {}
    cost = Decimal(0)
    known = True
    longest = None
    for summary in models.get("by_model", []):
        for key, value in summary.items():
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                totals[key] = totals.get(key, 0) + value
        cost += Decimal(summary.get("cost_usd") or "0")
        known = known and bool(summary.get("cost_known", False))
        slowest = (summary.get("latency_ms") or {}).get("longest")
        if slowest is not None and (longest is None or slowest > longest):
            longest = slowest
    # Summed over every model, so nothing here sets one model beside another.
    totals["cost_usd"] = str(cost)
    totals["cost_known"] = known
    totals["longest_latency_ms"] = longest
    kept = {
        "host_refusal": models.get("host_refusal"),
        "latest": [
            {
                **{k: v for k, v in d.items() if k not in ("model_id", "provider", "name")},
                "thing_id": beings.get(d["subject_id"]),
            }
            for d in models.get("latest", [])
            if d["subject_id"] in beings
        ],
        "totals_over_every_model_asked": totals,
        "decisions_read": models.get("decisions_read"),
    }
    (args.out / "decisions.json").write_text(json.dumps(kept, indent=1) + "\n", encoding="utf-8")

    if args.decisions:
        asked = sorted(
            {e["document"]["request_id"] for e in events if e["document"].get("request_id")}
        )
        read = [
            _without_figures(call(base, token, "GET", f"{society}/decisions/{request_id}", query))
            for request_id in asked
        ]
        (args.out / "decisions-read.json").write_text(
            json.dumps(read, indent=1) + "\n", encoding="utf-8"
        )

    held = call(base, token, "GET", society, query)
    replay = call(base, token, "GET", f"{society}/replay", query)
    replayed = replay.get("state_sha256") if isinstance(replay, dict) else None
    same = {"society_state_sha256": held["state_sha256"], "replay": replay}
    (args.out / "replay.json").write_text(json.dumps(same, indent=1) + "\n", encoding="utf-8")
    print(
        f"events {len(events)}; latest decisions {len(kept['latest'])}; "
        f"replay state equal: {replayed == held['state_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
