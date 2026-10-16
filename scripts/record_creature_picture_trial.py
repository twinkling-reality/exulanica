"""Write the evaluation record of the first creature picture trial (route P) on Nebius AI Cloud.

Reads only tracked evidence under ``ml/appearance/evidence/creature-picture-trial-1/``:
- ``descriptions.txt``: the eight held-out descriptions, frozen before anything ran;
- ``drafting.json``: each description's drafts by the product's creature drafter, with each call's
  model and USD; a description whose every draft was refused is not made;
- ``bodies.json``: each item of the job, with its name, role (held-out or development), seed,
  request digest and words;
- the job record and its requests;
- the job's results and every fit receipt, each receipt named by its own digest and belonging to
  the result whose cut-out it names;
- ``blind-key.json``: the held-out description each letter of the blind sheet shows, and the item
  drawn for it;
- ``answers.json``: the judge's answer to each letter, when it was asked and the sheet's digest
  (the sheet's pictures are kept outside the repository);
- ``jobs.json``: the Serverless AI job's id, digests, times and rate.

Writes ``docs/evaluation/2026-10-15-creature-picture-trial.json`` as an
``exulanica.digest-bound-record/v1``. Every figure is computed here from that evidence; nothing is
typed in but the threshold of the rule the trial was pre-registered with (its document's digest is
in the record), which this script applies:
- an item passes when its fit passes every rig check with chains that move;
- a held-out creature counts when one of its two items passes and its blind answer is yes;
- the picture-led route becomes the default look path at 5 held-out creatures of 8 or more;
- still chains, likeness, seconds per stage and the development rows are reported, never counted.

Run: ``.venv/bin/python scripts/record_creature_picture_trial.py``
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
TRIAL = ROOT / "ml/appearance/evidence/creature-picture-trial-1"
OUTPUT = ROOT / "docs/evaluation/2026-10-15-creature-picture-trial.json"
#: The pre-registration's own digest (kept out of the repository with the trial's working notes);
#: the rule below is the one it states.
PREREGISTRATION_SHA256 = "3bba6c989a2acec5550fb87f8b8c365c5f97ca59ef6c0a52eb3497d943e95aad"
DEFAULT_AT = 5


def _same(found: object, expected: object, what: str) -> None:
    """Refuse to write a record from evidence that does not hold together."""
    if found != expected:
        raise ValueError(f"{what}: {found!r} is not {expected!r}")


def _instant(text: str) -> datetime:
    """A UTC instant as the service or the watcher states it, to the microsecond (a longer
    fraction is cut, never rounded)."""
    whole, _, fraction = text.removesuffix("Z").partition(".")
    return datetime.fromisoformat(f"{whole}.{fraction[:6].ljust(6, '0')}").replace(tzinfo=UTC)


def _milliseconds(start: str, end: str) -> int:
    """Milliseconds from ``start`` to ``end``, rounded up."""
    microseconds = (_instant(end) - _instant(start)) // timedelta(microseconds=1)
    return -(-microseconds // 1000)


def _microdollars(rate_cents_per_hour: int, milliseconds: int) -> int:
    """Rate times milliseconds, in millionths of a dollar, rounded up."""
    return -(-rate_cents_per_hour * 10_000 * milliseconds // 3_600_000)


def _likeness(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """The likeness after the fit's colour move where the receipt keeps one, else before it."""
    matched = receipt.get("likeness_matched")
    likeness = matched or receipt.get("likeness")
    if likeness is None:
        return None
    return {
        "colour_difference_milli": likeness["colour_difference_milli"],
        "colour_matched": matched is not None,
        "outline_overlap_per_mille": likeness["outline_overlap_per_mille"],
    }


def _items(bodies: list[dict[str, Any]], job: dict[str, Any]) -> list[dict[str, Any]]:
    """Every item of the job, each with its result and its fit receipt's measures."""
    _same(
        [(body["request_sha256"], body["seed"], body["variant"]) for body in bodies],
        [(item["request_sha256"], item["seed"], item["variant"]) for item in job["items"]],
        "the items bodies.json names, beside the job's",
    )
    [results_path] = sorted(TRIAL.glob("results-*.json"))
    results = json.loads(results_path.read_bytes())
    by_request = {(item["request_sha256"], item["variant"]): item for item in results["items"]}
    receipts = {}
    for path in sorted((TRIAL / "receipts").glob("*.json")):
        raw = path.read_bytes()
        _same(hashlib.sha256(raw).hexdigest(), path.stem, f"the digest of {path.name}")
        receipt = json.loads(raw)
        receipts[receipt["inputs"]["cutout"]] = (path.stem, receipt)
    _same(len(receipts), len(results["items"]), "receipts, one for each result")
    items = []
    for body in bodies:
        result = by_request[(body["request_sha256"], body["variant"])]
        _same(result["seed"], body["seed"], f"item {body['item']}'s seed")
        digest, receipt = receipts[result["inputs"]["cutout"]]
        request = json.loads((TRIAL / "requests" / f"{body['request_sha256']}.json").read_bytes())
        _same(receipt["plan"]["sha256"], request["plan"]["sha256"], f"item {body['item']}'s plan")
        rig = receipt.get("rig", {})
        moving = sum(moved > 0 for moved in rig.get("joint_moved_mm", {}).values())
        # The rule's pass: every rig check passed (no refusal, ``rig_nothing_moves`` among them)
        # and at least one bone of the plan moved in the rig check.
        passes = receipt["outcome"] == "passed" and "refusal" not in receipt and moving > 0
        simplifiers = sorted(
            {
                step["parameters"]["simplifier"]
                for step in receipt.get("steps", [])
                if step.get("step") == "simplify"
            }
        )
        items.append(
            {
                "body": body["body"],
                "description": body["description"],
                "fit_seconds": receipt.get("seconds", {}),
                "fit_simplifier": simplifiers[0] if simplifiers else None,
                "gpu_seconds": result["seconds"],
                "item": body["item"],
                "likeness": _likeness(receipt),
                "made": result["outcome"] == "made",
                "mesh_sha256": result["mesh"]["sha256"],
                "mesh_triangles": result["mesh"]["triangles"],
                "moving_bones": moving,
                "name": body["name"],
                "outcome": receipt["outcome"],
                "output_sha256": receipt.get("output", {}).get("sha256"),
                "passes": passes,
                "plan_key": request["plan"]["key"],
                "plan_sha256": request["plan"]["sha256"],
                "receipt": digest,
                "refusal": receipt.get("refusal", {}).get("code"),
                # The refusal's own sentence, which names the chain or bone it broke on.
                "refusal_detail": receipt.get("refusal", {}).get("detail"),
                "request_sha256": body["request_sha256"],
                "role": body["role"],
                "seed": body["seed"],
                # Bones the fit keeps still because the model has no part for them; None where
                # the fit stopped before laying chains.
                "still": receipt.get("embed", {}).get("still"),
                "variant": body["variant"],
            }
        )
    return items


def _judged_by_the_rule(own: list[dict[str, Any]]) -> int | None:
    """The item the rule shows the judge: the first passing item by seed, else the first made."""
    by_seed = sorted(own, key=lambda item: item["seed"])
    for item in by_seed:
        if item["passes"]:
            return item["item"]
    return next((item["item"] for item in by_seed if item["made"]), None)


def _creatures(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words = (TRIAL / "descriptions.txt").read_text("utf-8").splitlines()
    rows = json.loads((TRIAL / "drafting.json").read_bytes())["rows"]
    key = json.loads((TRIAL / "blind-key.json").read_bytes())
    answers = json.loads((TRIAL / "answers.json").read_bytes())["answers"]
    letters = {row["description"]: row for row in key["rows"]}
    _same(len(rows), len(words), "a drafting row for each description")
    _same(set(answers), {row["letter"] for row in key["rows"]}, "an answer for each letter")
    creatures = []
    for index, (text, row) in enumerate(zip(words, rows, strict=True)):
        _same(row["index"], index, "the drafting rows' order")
        _same(
            row["description_sha256"],
            hashlib.sha256(text.encode("utf-8")).hexdigest(),
            f"description {index}'s drafted words",
        )
        own = [item for item in items if item["description"] == index]
        _same(bool(own), row["drafted"], f"description {index} has items when it was drafted")
        letter = letters.get(index)
        passing = any(item["passes"] for item in own)
        if letter:
            judged = next(item for item in own if item["item"] == letter["item"])
            _same(letter["passed"], judged["passes"], f"the blind key's outcome for {index}")
        answer = answers[letter["letter"]] if letter else None
        creatures.append(
            {
                "answer": answer,
                "counted": passing and answer == "yes",
                "description": index,
                "draft_attempts": row["attempts"],
                "draft_refusals": [refusal[0] for refusal in row["refusals"]],
                "drafted": row["drafted"],
                "items": [item["item"] for item in own],
                "judged_item": letter["item"] if letter else None,
                "judged_item_by_the_rule": _judged_by_the_rule(own) if own else None,
                "letter": letter["letter"] if letter else None,
                "passing": passing,
                "words": text,
            }
        )
    _same(
        sorted(key["not_made"]),
        [creature["description"] for creature in creatures if not creature["items"]],
        "the descriptions the blind key calls not made",
    )
    return creatures


def _development(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    bodies: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        if item["role"] == "development":
            bodies.setdefault(item["body"], []).append(item)
    return {
        name: {
            "items": [item["item"] for item in own],
            "outcomes": [
                "passed" if item["passes"] else f"{item['outcome']}: {item['refusal']}"
                for item in own
            ],
            "passing": any(item["passes"] for item in own),
        }
        for name, own in sorted(bodies.items())
    }


def _seconds(items: list[dict[str, Any]], results: dict[str, Any]) -> dict[str, Any]:
    per_item = [sum(item["gpu_seconds"].values()) for item in items]
    totals: dict[str, dict[str, int]] = {"fit": {}, "gpu": {}}
    for item in items:
        for kind in ("fit", "gpu"):
            for stage, seconds in item[f"{kind}_seconds"].items():
                totals[kind][stage] = totals[kind].get(stage, 0) + seconds
    return {
        "fit_per_stage_total": totals["fit"],
        "gpu_item_first": per_item[0],
        "gpu_item_median_low": statistics.median_low(per_item),
        "gpu_item_most": max(per_item),
        "gpu_per_stage_total": totals["gpu"],
        "results_ended_at": results["ended_at"],
        "results_milliseconds": _milliseconds(results["started_at"], results["ended_at"]),
        "results_started_at": results["started_at"],
    }


def build() -> dict[str, Any]:
    job_raw = (TRIAL / "job.json").read_bytes()
    job = json.loads(job_raw)
    job_sha256 = hashlib.sha256(job_raw).hexdigest()
    [record] = json.loads((TRIAL / "jobs.json").read_bytes())["jobs"]
    [results_path] = sorted(TRIAL.glob("results-*.json"))
    results = json.loads(results_path.read_bytes())
    _same(record["job_sha256"], job_sha256, "the job's digest in jobs.json")
    _same(results["job_sha256"], job_sha256, "the job's digest in the results")
    _same(record["code_sha256"], job["code_sha256"], "the code archive's digest")
    bodies = json.loads((TRIAL / "bodies.json").read_bytes())["items"]
    items = _items(bodies, job)
    creatures = _creatures(items)
    counted = [creature["description"] for creature in creatures if creature["counted"]]
    development = _development(items)
    held_out = [item for item in items if item["role"] == "held_out"]
    developing = [item for item in items if item["role"] == "development"]
    passed = [item for item in items if item["passes"]]
    refusals: dict[str, int] = {}
    for item in items:
        if item["refusal"]:
            refusals[item["refusal"]] = refusals.get(item["refusal"], 0) + 1
    likeness = [item["likeness"] for item in passed if item["likeness"]]
    drafting = json.loads((TRIAL / "drafting.json").read_bytes())
    calls = [call for row in drafting["rows"] for call in row["calls"]]
    drafts_usd = sum((Decimal(call["usd"]) for call in calls), Decimal(0))
    _same(drafts_usd, Decimal(drafting["spent_usd"]), "the drafts' spend, call by call")
    rate = record["rate_cents_per_hour"]
    bound_ms = _milliseconds(record["upper_bound_from"], record["upper_bound_to"])
    container_ms = _milliseconds(record["container_started_at"], record["container_finished_at"])
    answers = json.loads((TRIAL / "answers.json").read_bytes())
    key = json.loads((TRIAL / "blind-key.json").read_bytes())
    return {
        "compute": {
            "gpu": results["runtime"]["gpu"],
            "gpu_memory_mib": results["runtime"]["gpu_memory_mib"],
            "model": results["runtime"]["model"],
            "platform": record["platform"],
            "preset": record["preset"],
            "provider": record["provider"],
            "rate_cents_per_hour": rate,
            "rate_source": record["rate_source"],
        },
        "creatures": creatures,
        "development": development,
        "evidence": {
            "descriptions_sha256": hashlib.sha256(
                (TRIAL / "descriptions.txt").read_bytes()
            ).hexdigest(),
            "folder": TRIAL.relative_to(ROOT).as_posix(),
            "job_sha256": job_sha256,
            "results": results_path.name,
            "results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
        },
        "items": items,
        "job": {
            "code_sha256": record["code_sha256"],
            "container_finished_at": record["container_finished_at"],
            "container_started_at": record["container_started_at"],
            "created_at": record["created_at"],
            "deleted_at": record["deleted_at"],
            "job_id": record["job_id"],
            "job_sha256": job_sha256,
            "outcome": record["outcome"],
            "submitted_at": record["submitted_at"],
            "terminal_seen_at": record["terminal_seen_at"],
            "terminal_state": record["terminal_state"],
        },
        "judging": {
            "answers": answers["answers"],
            "asked": answers["asked"],
            "letter_order_seed": key["seed"],
            "sheet_sha256": answers["sheet_sha256"],
        },
        "kind": "exulanica.creature-picture-trial/v1",
        "preregistration_sha256": PREREGISTRATION_SHA256,
        "reported": {
            "note": (
                "reported, never deciding the rule: the bones each fit keeps still, the likeness "
                "of each passed item to its picture, the seconds of each stage, and the "
                "development rows"
            ),
            "fit_simplifiers": sorted({item["fit_simplifier"] for item in items} - {None}),
            "held_out_creatures_whose_seeds_disagree": sorted(
                creature["description"]
                for creature in creatures
                if len({item["passes"] for item in items if item["item"] in creature["items"]}) > 1
            ),
            "likeness_of_passed_items": {
                "colour_difference_milli_median_low": statistics.median_low(
                    [entry["colour_difference_milli"] for entry in likeness]
                ),
                "colour_matched": sum(entry["colour_matched"] for entry in likeness),
                "items": len(likeness),
                "outline_overlap_per_mille_median_low": statistics.median_low(
                    [entry["outline_overlap_per_mille"] for entry in likeness]
                ),
            },
            "passed_items_with_still_bones": sum(bool(item["still"]) for item in passed),
            "seconds": _seconds(items, results),
        },
        "rule": {
            "counted": (
                "a held-out creature counts when one of its two items passes every rig check "
                "with chains that move and its blind answer is yes"
            ),
            "default_at": DEFAULT_AT,
            "verdict": (
                "the picture-led route is the default look path"
                if len(counted) >= DEFAULT_AT
                else "the sketch stays the default look path; a made look is offered only where "
                "an item passed"
            ),
        },
        "script": "scripts/record_creature_picture_trial.py",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "spend": {
            "authoritative_total": (
                "the providers' billing: Nebius AI Cloud's for the GPU job, Nebius Token "
                "Factory's for the drafts"
            ),
            "drafts": {
                "calls": len(calls),
                "models": sorted({call["model_id"] for call in calls}),
                "usd": str(drafts_usd),
            },
            "gpu": {
                "container_cost_microdollars": _microdollars(rate, container_ms),
                "container_milliseconds": container_ms,
                "rate_cents_per_hour": rate,
                # The bound's window, from the watcher's clock before submitting to after the
                # delete was read back, holds the service's own window from the job's creation
                # to the delete's finish.
                "upper_bound_holds_the_service_window": (
                    _instant(record["upper_bound_from"]) <= _instant(record["created_at"])
                    and _instant(record["deleted_at"]) <= _instant(record["upper_bound_to"])
                ),
                "upper_bound_cost_microdollars": _microdollars(rate, bound_ms),
                "upper_bound_from": record["upper_bound_from"],
                "upper_bound_milliseconds": bound_ms,
                "upper_bound_to": record["upper_bound_to"],
            },
        },
        "totals": {
            "creatures": len(creatures),
            "creatures_answered_yes": sum(creature["answer"] == "yes" for creature in creatures),
            "creatures_counted": len(counted),
            "creatures_drafted": sum(creature["drafted"] for creature in creatures),
            "creatures_passing": sum(creature["passing"] for creature in creatures),
            "development_bodies": len(development),
            "development_bodies_passing": sum(body["passing"] for body in development.values()),
            "development_items": len(developing),
            "development_items_passed": sum(item["passes"] for item in developing),
            "held_out_items": len(held_out),
            "held_out_items_passed": sum(item["passes"] for item in held_out),
            "items": len(items),
            "items_made": sum(item["made"] for item in items),
            "items_passed": len(passed),
            "refusals": dict(sorted(refusals.items())),
        },
    }


def main() -> int:
    record = build()
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": record,
        "record_sha256": hashlib.sha256(canonical_json(record)).hexdigest(),
    }
    OUTPUT.write_text(json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(ROOT)}: {record['totals']}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
