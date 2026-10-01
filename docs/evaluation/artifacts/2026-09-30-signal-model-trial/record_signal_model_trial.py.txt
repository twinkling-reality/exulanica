#!/usr/bin/env python3
"""Record the first paid trial of a model deciding a town's signals, from its retained receipts.

    EXULANICA_SIGNAL_TRIAL_DIR=<the retained trial's directory> \\
        uv run python scripts/record_signal_model_trial.py --root <repository root>

The trial played episode 0 of one generated small town and one generated market town twice: once
under the signal plan's fixed timing, and once with one signal of each town decided by a model,
asked through the hosted call path under a process budget. Its driver kept three files: a summary
of the pair, every request and receipt of the model's choice points, and root's validation of the
pair. This script reads those three files, from the directory the environment names, and writes the
record and its bound copies under ``--root``. It asks no model and plays no episode.

Everything the record states is read from the files and checked against them:

- every request and receipt is held to its own sealed digest, and every receipt to its request's;
- the receipts are counted per town against the summary's choice points, asks, statuses and reasons,
  and in all against its asks and its billed calls;
- the summary's measures are held to root's validation, town by town, and its known cost to the
  receipts' recorded costs.

A choice point the model was not asked at, or did not answer in time, is the plan's fixed timing
there, so the model arm is a model asked at some of its points. The record claims what the measures
show, the model arm's mean delay at the signalled junctions above fixed timing's in each town, and
no benefit, no ranking and nothing beyond these two episodes.

Bound copies are made by allowing: the summary keeps only the fields named below, so the modules the
driver read and where it kept its receipts are left out, and every copy, this script's own included,
is refused if it holds a home path, an em dash, or another string the evaluation gate refuses.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json
from exulanica.evaluation import visual_gate
from exulanica.world.role_decisions import seal

NAME = "2026-09-30-signal-model-trial"
KIND = "exulanica.signal-model-trial/v1"
SUMMARY = "w5-pair-a775-paid.json"
RECEIPTS = "w5-pair-a775-paid.receipts.jsonl"
VALIDATION = "root-validation.json"
#: The summary's fields a bound copy keeps, at the top and for each town. Anything else the driver
#: wrote, such as the paths of the modules it read and of its receipts, is left out.
SUMMARY_FIELDS = (
    "billed",
    "mode",
    "model_id",
    "process_ceiling_usd",
    "process_max_calls",
    "signal_ask_invocations",
    "source_commit",
    "spent_usd",
    "towns",
)
TOWN_FIELDS = (
    "choice_points",
    "composer",
    "departure_steps",
    "episode",
    "fixed",
    "grammar",
    "hosted_asks",
    "model",
    "preset",
    "receipt_sha256",
    "receipt_statuses",
    "receipt_reasons",
    "recipe_catalog_version",
    "roads_sha256",
    "selected_signal_id",
    "signal_ids",
    "specification",
    "world_id",
    "world_index",
)


def _refusals() -> tuple[str, ...]:
    """Text a bound copy may not hold, beside the evaluation gate's own: a home or temporary path
    prefix, this account's name and the em dash the pre-push gate refuses in added lines. Each is
    made at run time, so this script's own text, which it binds, holds none of them."""
    prefixes = (
        ("", "Users", ""),
        ("", "home", ""),
        ("", "private", ""),
        ("", "var", "folders", ""),
    )
    return (*("/".join(parts) for parts in prefixes), Path.home().name, chr(0x2014))


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _refused(name: str, data: bytes) -> None:
    text = data.decode("utf-8")
    for phrase in visual_gate._FORBIDDEN_TEXT:
        if phrase in text:
            raise SystemExit(f"{name} holds text the evaluation gate refuses")
    for phrase in _refusals():
        found = text.find(phrase)
        if found >= 0:
            raise SystemExit(f"{name} holds refused text at offset {found}")


def _no_floats(value: Any, where: str = "record") -> None:
    if isinstance(value, float):
        raise SystemExit(f"{where} holds a float")
    if isinstance(value, dict):
        for key, item in value.items():
            _no_floats(item, f"{where}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _no_floats(item, f"{where}[{index}]")


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"the retained trial does not hold together: {message}")


def _sealed(document: dict[str, Any]) -> bool:
    body = {key: value for key, value in document.items() if key != "document_sha256"}
    return seal(body)["document_sha256"] == document["document_sha256"]


def _town(summary: dict[str, Any], rows: list[dict[str, Any]], pair: dict[str, Any]) -> dict:
    """One town's part of the record, read from its receipts and checked against the summary and
    root's validation."""
    preset = summary["preset"]
    receipts = [row["receipt"] for row in rows]
    asked = [receipt for receipt in receipts if receipt["provider"] is not None]
    statuses = Counter(receipt["status"] for receipt in receipts)
    reasons = Counter(receipt["reason"] for receipt in receipts)
    chosen = Counter(
        receipt["proposal"]["option"]["kind"]
        for receipt in receipts
        if receipt["status"] == "accepted"
    )
    _check(len(receipts) == summary["choice_points"], f"{preset}: choice points")
    _check(len(asked) == summary["hosted_asks"], f"{preset}: asks")
    _check(dict(statuses) == summary["receipt_statuses"], f"{preset}: statuses")
    _check(dict(reasons) == summary["receipt_reasons"], f"{preset}: reasons")
    _check(
        {receipt["subject_id"] for receipt in receipts} == {summary["selected_signal_id"]},
        f"{preset}: every choice point is the selected signal's",
    )
    fixed, model = summary["fixed"], summary["model"]
    _check(
        (fixed["mean_delay_ms_at_signalled"], model["mean_delay_ms_at_signalled"])
        == (pair["fixed_delay_ms"], pair["model_delay_ms"]),
        f"{preset}: the measures root validated",
    )
    _check(
        (fixed["trips"]["arrived"], model["trips"]["arrived"])
        == (pair["fixed_arrived"], pair["model_arrived"]),
        f"{preset}: the arrivals root validated",
    )
    known = [receipt for receipt in asked if receipt["provider"]["cost_known"]]
    return {
        "preset": preset,
        "world_id": summary["world_id"],
        "world_index": summary["world_index"],
        "generation_receipt_sha256": summary["receipt_sha256"],
        "roads_sha256": summary["roads_sha256"],
        "episode": summary["episode"],
        "departure_steps": summary["departure_steps"],
        "signals": len(summary["signal_ids"]),
        "decided_by_the_model": summary["selected_signal_id"],
        "choice_points": len(receipts),
        "asked": len(asked),
        "receipts_by_status": dict(sorted(statuses.items())),
        "receipts_by_reason": dict(sorted(reasons.items())),
        "answers_by_kind": dict(sorted(chosen.items())),
        "known_cost_usd": format(
            sum((Decimal(r["provider"]["cost_usd"]) for r in known), Decimal(0)), "f"
        ),
        "asks_of_unknown_cost": len(asked) - len(known),
        "latencies_ms": [int(receipt["provider"]["latency_ms"]) for receipt in asked],
        "fixed": {
            "entries_at_signalled": fixed["entries_at_signalled"],
            "mean_delay_ms_at_signalled": fixed["mean_delay_ms_at_signalled"],
            "trips": fixed["trips"],
            "mean_door_to_door_s": fixed["mean_door_to_door_s"],
        },
        "model": {
            "entries_at_signalled": model["entries_at_signalled"],
            "mean_delay_ms_at_signalled": model["mean_delay_ms_at_signalled"],
            "trips": model["trips"],
            "mean_door_to_door_s": model["mean_door_to_door_s"],
        },
        "model_less_fixed_delay_ms": model["mean_delay_ms_at_signalled"]
        - fixed["mean_delay_ms_at_signalled"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, required=True, help="where docs/evaluation is")
    args = parser.parse_args()
    trial = Path(os.environ["EXULANICA_SIGNAL_TRIAL_DIR"])
    raw = {name: (trial / name).read_bytes() for name in (SUMMARY, RECEIPTS, VALIDATION)}
    summary = json.loads(raw[SUMMARY])
    validation = json.loads(raw[VALIDATION])
    rows = [json.loads(line) for line in raw[RECEIPTS].decode("utf-8").splitlines() if line]

    for row in rows:
        _check(_sealed(row["request"]), f"request {row['request']['request_id']} is sealed")
        _check(_sealed(row["receipt"]), f"receipt {row['receipt']['request_id']} is sealed")
        _check(
            row["receipt"]["request_sha256"] == row["request"]["document_sha256"],
            f"receipt {row['receipt']['request_id']} answers its request",
        )
    _check(summary["source_commit"] == validation["source_commit"], "one source commit")
    pairs = {pair["town"]: pair for pair in validation["pairs"]}
    towns = []
    for town in summary["towns"]:
        mine = [row for row in rows if row["town"] == town["preset"]]
        towns.append(_town(town, mine, pairs[town["preset"]]))
    _check({row["town"] for row in rows} == set(pairs), "the receipts' towns are the pair's")
    asked = sum(town["asked"] for town in towns)
    _check(asked == summary["signal_ask_invocations"] == summary["billed"], "asks billed")
    known = sum((Decimal(town["known_cost_usd"]) for town in towns), Decimal(0))
    _check(known == Decimal(validation["known_cost_usd"]), "the known cost root validated")
    _check(
        Decimal(summary["spent_usd"])
        == Decimal(validation["accounted_including_unknown_reservations_usd"]),
        "the accounted spend root validated",
    )
    for town in towns:
        _check(
            validation["point_counts"][town["preset"]] == town["receipts_by_reason"],
            f"{town['preset']}: the point counts root validated",
        )
    above = [town["preset"] for town in towns if town["model_less_fixed_delay_ms"] > 0]
    points = sum(town["choice_points"] for town in towns)
    not_asked = sum(town["receipts_by_reason"].get("process_share_spent", 0) for town in towns)
    timed_out = sum(town["receipts_by_reason"].get("model_timed_out", 0) for town in towns)

    copies_dir = Path("docs") / "evaluation" / "artifacts" / NAME
    bound_summary = {key: summary[key] for key in SUMMARY_FIELDS}
    bound_summary["towns"] = [{key: town[key] for key in TOWN_FIELDS} for town in summary["towns"]]
    copies = {
        copies_dir / "trial-summary.json": (
            json.dumps(bound_summary, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
        copies_dir / "trial-receipts.jsonl": raw[RECEIPTS],
        copies_dir / "root-validation.json": raw[VALIDATION],
        copies_dir / "record_signal_model_trial.py.txt": Path(__file__).read_bytes(),
    }
    for path, data in copies.items():
        _refused(str(path), data)

    record = {
        "kind": KIND,
        "name": NAME,
        # Where the trial's files were retained, by the names of their directory and its parent.
        "retained_as": f"{trial.parent.name}/{trial.name}",
        "question": (
            "What did one paid pair of episodes show of a model deciding one signal of a generated "
            "town, beside the signal plan's fixed timing?"
        ),
        "source": {
            "commit": summary["source_commit"],
            "mode": summary["mode"],
            "model_id": summary["model_id"],
            "process_ceiling_usd": summary["process_ceiling_usd"],
            "process_max_calls": summary["process_max_calls"],
            "files": [
                {"name": name, "bytes": len(raw[name]), "sha256": _sha256(raw[name])}
                for name in (SUMMARY, RECEIPTS, VALIDATION)
            ],
            "driver_retained": False,
        },
        "checks": {
            "requests_and_receipts_sealed": len(rows) * 2,
            "receipts_bound_to_their_requests": len(rows),
            "towns_held_to_root_validation": len(towns),
        },
        "spend": {
            "asks": asked,
            "known_cost_usd": format(known, "f"),
            "asks_of_unknown_cost": sum(town["asks_of_unknown_cost"] for town in towns),
            "accounted_usd": summary["spent_usd"],
        },
        "towns": towns,
        "finding": {
            "model_delay_above_fixed_in": above,
            "towns": len(towns),
            "statement": (
                f"In {len(above)} of {len(towns)} towns the model arm's mean delay at the "
                "signalled junctions was above fixed timing's ("
                + "; ".join(
                    f"{town['preset']}: {town['model']['mean_delay_ms_at_signalled']} ms against "
                    f"{town['fixed']['mean_delay_ms_at_signalled']} ms"
                    for town in towns
                )
                + "). No benefit and no ranking of models is claimed."
            ),
        },
        "limitations": [
            "One paid pair: episode 0 of one generated town of each of two presets, one signal of "
            "each town decided by the model and every other signal on fixed timing.",
            f"The model was asked at {asked} of {points} choice points: {not_asked} were not asked "
            f"because the process's share for the role was spent, and {timed_out} asked were not "
            "answered in time; fixed timing decided each of those.",
            "The measure is the trial driver's mean delay per entry at the signalled junctions in "
            "whole milliseconds, read from its summary; the driver is not retained, and the "
            "episodes are not replayed here.",
            "Not pre-registered and not held out; one model, one episode per town.",
        ],
        "artifacts": [
            {"path": str(path), "bytes": len(data), "sha256": _sha256(data)}
            for path, data in sorted(copies.items(), key=lambda item: str(item[0]))
        ],
    }
    _no_floats(record)
    envelope = {
        "profile": "exulanica.digest-bound-record/v1",
        "record_sha256": _sha256(canonical_json(record)),
        "record": record,
    }
    document = (json.dumps(envelope, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _refused(NAME, document)
    for path, data in copies.items():
        target = args.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    out = args.root / "docs" / "evaluation" / f"{NAME}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(document)
    print(f"wrote docs/evaluation/{NAME}.json, record_sha256 {envelope['record_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
