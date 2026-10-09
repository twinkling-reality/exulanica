"""The evaluation record of one pictured crossing (``run/check.py --play NAME --pictures``).

    <checkout>/.venv/bin/python bridges/luanti/tools/crossing_record.py decisions RUN \
        --api URL --token-file FILE
    <checkout>/.venv/bin/python bridges/luanti/tools/crossing_record.py write RUN --tree FILE \
        --world-pictures FILE --side-by-side FILE --out RECORD

``decisions`` reads, from the world the run crossed into, every decision about its character as the
world's own events recorded it (who decided, what the minute did with it, the option chosen and the
receipt's digest) and the character's arrival and leaving, into ``RUN/decisions.json``. The world
owner's token is read once from the file and stays in this process; nothing secret is written.

``write`` makes the digest-bound record from the run folder: the run's summary and the gate's
recording (each named by its digest), the timings read from the gate's own clock, the words the
player read, what came home and why, the decisions with their receipts' digests, the tree the run
used (``--tree``, written before the run), and every picture by its SHA-256: the game window's,
the world's (``--world-pictures``, a JSON list of ``{moment, file, sha256, bytes}``) and the
side-by-side ones (``--side-by-side``, the list ``side_by_side.py`` writes). The pictures
themselves are kept beside the run, never in the repository: the game's art in them is the game's
own. No figure is a float, and the text no retained record may carry is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
CHECKOUT = HERE.parents[3]
KIND = "exulanica.game-crossing-round-trip/v1"
#: The most pages of the world's events (256 a page) read back for the character.
EVENT_PAGES_MAXIMUM = 200


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _lines(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _characters(run: Path) -> list[str]:
    """The things the run's character became in the world, from the gate's recording."""
    found: list[str] = []
    for entry in _lines(run / "exchanges.jsonl"):
        if entry.get("mark") == "arrived" and entry.get("subject") not in found:
            found.append(str(entry["subject"]))
    return found


def decisions(run: Path, api: str, token_file: Path) -> dict[str, Any]:
    summary = json.loads((run / "summary.json").read_text())
    placed = json.loads(Path(summary["stack"]["record"]).read_text())
    characters = set(_characters(run))
    token = token_file.read_text().strip()
    base = f"{api.rstrip('/')}/world/versions/{placed['version_id']}/society/events"
    kept: list[dict[str, Any]] = []
    moments: list[dict[str, Any]] = []
    before = None
    for _ in range(EVENT_PAGES_MAXIMUM):
        query = {"world_id": placed["world_id"]} | ({"before": before} if before else {})
        request = urllib.request.Request(
            f"{base}?{urllib.parse.urlencode(query)}", headers={"Authorization": "Bearer " + token}
        )
        page = json.loads(urllib.request.urlopen(request, timeout=60).read())
        for event in page.get("events", []):
            if str(event.get("subject_id")) not in characters:
                continue
            document = event.get("document") or {}
            kind = event.get("event_kind")
            if kind == "decision_applied":
                kept.append(
                    {
                        "tick": event.get("tick"),
                        "origin": document.get("origin"),
                        "disposition": document.get("disposition"),
                        "reason": document.get("reason"),
                        "model": document.get("model"),
                        "chose": document.get("chose"),
                        "request_id": document.get("request_id"),
                        "decision_sha256": document.get("decision_sha256"),
                    }
                )
            elif kind in ("thing_arrived", "thing_left", "thing_departed"):
                moments.append({"tick": event.get("tick"), "event": kind})
        before = page.get("next")
        if not before or any(moment["event"] == "thing_arrived" for moment in moments):
            break
    del token
    found = {
        "characters": sorted(characters),
        "decisions": sorted(
            kept, key=lambda entry: (entry["tick"] or 0, entry["request_id"] or "")
        ),
        "moments": sorted(moments, key=lambda entry: entry["tick"] or 0),
    }
    (run / "decisions.json").write_text(json.dumps(found, indent=2) + "\n")
    return found


def _ms(seconds: Any) -> int | None:
    return None if seconds is None else round(float(seconds) * 1000)


def _acts(acts: dict[str, Any]) -> dict[str, Any]:
    """The run's acts with their times in whole milliseconds after the character arrived."""
    kept: dict[str, Any] = {}
    for name, act in acts.items():
        entry = {key: value for key, value in act.items() if key != "after_arrival_s"}
        entry["after_arrival_ms"] = _ms(act.get("after_arrival_s"))
        kept[name] = entry
    return kept


def _minds(summary: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The minds the world gave its own beings, from the scene builder's record the run joined
    (``minds``: each placed being and its decider); None where the record names none."""
    named = (summary.get("stack") or {}).get("record")
    if not named or not Path(named).is_file():
        return None
    return json.loads(Path(named).read_text()).get("minds")


def write(
    run: Path, tree: Path, world_pictures: Path, side_by_side: Path, out: Path
) -> dict[str, Any]:
    from exulanica.canonical import canonical_json
    from exulanica.evaluation.visual_gate import _FORBIDDEN_TEXT

    summary = json.loads((run / "summary.json").read_text())
    check = summary["check"]
    found = json.loads((run / "decisions.json").read_text())
    counts: dict[str, int] = {}
    for entry in found["decisions"]:
        key = f"{entry['origin']} {entry['disposition']}"
        counts[key] = counts.get(key, 0) + 1
    record = {
        "kind": KIND,
        "note": (
            "One crossing from a game into a world and home again, played by the game's own client "
            "with nobody at the keyboard: a director test mod walked the player into the gate, the "
            "character lived in the world with the mind the world gave it until it came home, and "
            "the client's window was pictured at each moment. Figures are read from the run's "
            "summary, the gate's own recording (its clock) and the world's events; the pictures "
            "are named by digest and kept outside the repository, since the game's art in them is "
            "the game's own (CC BY-SA 3.0). The minds' model calls were the world's own, made by "
            "the world's process; their cost is in the world's receipts, not here."
        ),
        "window": {
            "started": summary["started_at"],
            "ended": check["pictures"][-1]["at"] if check.get("pictures") else None,
        },
        "tree": json.loads(tree.read_text()),
        "run": {
            "summary_sha256": _digest(run / "summary.json"),
            "recording_sha256": _digest(run / "exchanges.jsonl"),
            "decisions_sha256": _digest(run / "decisions.json"),
        },
        "game": {
            "engine": "Luanti 5.17.0",
            "game": "Minetest Game, ContentDB release 38214",
            "adapter_version": summary["adapter_version"],
            "mapping": {"file": summary["mapping_file"], "sha256": summary["mapping_sha256"]},
        },
        "world": {
            "scene": summary["scene"],
            "minds": _minds(summary),
            "traveller_mind": summary.get("traveller_mind"),
            "playback": summary.get("playback"),
            "played_by_this_check": (summary.get("playback") or {}).get("played_by_this_check"),
        },
        "crossing": {
            "checks": [{"check": entry["check"], "ok": entry["ok"]} for entry in check["checks"]],
            "timings_ms": summary.get("timings"),
            "came_home": check.get("came_home"),
            "acts": _acts(summary.get("owner_acts") or {}),
            "told": check.get("told"),
            "lines": summary.get("lines"),
            "answers_posted": summary.get("answers_posted"),
            "home_calls": summary.get("home_calls"),
            "replay_verified": summary.get("replay_verified"),
            "grant_closed": summary.get("grant_closed"),
            "client": check.get("client"),
            "completed_by_a_second_step": summary.get("completed_by_a_second_step"),
        },
        "decisions": {
            "counts": counts,
            "receipts": found["decisions"],
            "moments": found["moments"],
        },
        "pictures": {
            "kept": "beside the run, outside the repository",
            "game_window": [
                {key: picture[key] for key in ("moment", "file", "sha256", "bytes")}
                for picture in check.get("pictures", [])
            ],
            "world": json.loads(world_pictures.read_text()),
            "side_by_side": json.loads(side_by_side.read_text())["pictures"],
        },
        "script_sha256": _digest(HERE),
    }
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    text = json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"
    # The text no retained record may carry, from the gate that refuses it.
    for forbidden in _FORBIDDEN_TEXT:
        if forbidden in text:
            raise SystemExit(f"the record would carry {forbidden!r}")
    out.write_text(text)
    return document


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    read = commands.add_parser("decisions")
    read.add_argument("run", type=Path)
    read.add_argument("--api", required=True)
    read.add_argument("--token-file", type=Path, required=True)
    made = commands.add_parser("write")
    made.add_argument("run", type=Path)
    made.add_argument("--tree", type=Path, required=True)
    made.add_argument("--world-pictures", type=Path, required=True)
    made.add_argument("--side-by-side", type=Path, required=True)
    made.add_argument("--out", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.command == "decisions":
        found = decisions(arguments.run, arguments.api, arguments.token_file)
        print(json.dumps({"decisions": len(found["decisions"]), "moments": found["moments"]}))
        return 0
    sys.path.insert(0, str(CHECKOUT))
    document = write(
        arguments.run,
        arguments.tree,
        arguments.world_pictures,
        arguments.side_by_side,
        arguments.out,
    )
    print(json.dumps({"out": arguments.out.name, "record_sha256": document["record_sha256"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
