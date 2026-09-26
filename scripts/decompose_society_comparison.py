"""Where the judged comparison's scores come from: the need its people were spared, and the turns
their models' answers were not applied.

    uv run python scripts/decompose_society_comparison.py

A person's score is the need relief less the share of their turns that were not applied
(``assets/catalogs/society/society-person-score.v1.json``: turns refused and turns unanswered each
weigh minus one, need relief plus one). The judged record
(``docs/evaluation/2026-09-26-society-model-comparison.json``) keeps, for every run, its score,
its turns and how many of them were not applied, so a run's relief is its score plus that share.
The record writes each score to four places, so a relief recovered here is within 0.00005 of the
exact value. The record keeps how many turns were not applied, not why: each turn's reason was in
the run's receipts, in the private database the measurement made for the run and removed after
it, so nothing here splits them by reason. What the record does keep of the asking, each run's
answer times, is set beside the contract's decision deadline.

This reads the judged record and its pre-registration, each held to its own digest, and checks
that the score and the decision contract read here are the ones the pre-registration bound. It
writes ``docs/evaluation/2026-09-26-society-model-comparison-decomposition.json`` and a copy of
itself as run beside the judged run's artifacts, and neither asks a model nor reads a database.
"""

from __future__ import annotations

import hashlib
import json
import sys
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from exulanica.canonical import canonical_json  # noqa: E402
from exulanica.world.society_catalogs import load_comparison_catalogs  # noqa: E402
from exulanica.world.society_comparison_result import scoring_binding  # noqa: E402
from exulanica.world.society_decision_contract import decision_contract  # noqa: E402
from exulanica.world.society_score import person_score  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
JUDGED: Final = "docs/evaluation/2026-09-26-society-model-comparison.json"
PREREGISTRATION: Final = "docs/evaluation/2026-09-26-society-model-comparison-preregistration.json"
RECORD: Final = "docs/evaluation/2026-09-26-society-model-comparison-decomposition.json"
AS_RUN: Final = (
    "docs/evaluation/artifacts/2026-09-26-society-model-comparison/"
    "decompose_society_comparison-as-run.py.txt"
)
SCRIPT: Final = "scripts/decompose_society_comparison.py"
#: The two terms a turn not applied is counted under, each at the weight the score gives it.
TURN_TERMS: Final = ("turns_refused", "turns_unanswered")
#: How the record writes a value: as the server does, to four places, half to even.
QUANTUM: Final = Decimal("0.0001")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(relative: str) -> dict[str, Any]:
    document = json.loads((ROOT / relative).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{relative} does not match its own digest")
    return document


def _text(value: Fraction) -> str:
    written = (Decimal(value.numerator) / Decimal(value.denominator)).quantize(
        QUANTUM, rounding=ROUND_HALF_EVEN
    )
    return format(written + Decimal(0), "f")


def _mean(values: list[Fraction]) -> Fraction:
    return sum(values, Fraction(0)) / len(values)


def decompose(judged: dict[str, Any], registered: dict[str, Any]) -> dict[str, Any]:
    """Each run's score as relief less the share of its turns not applied, and each registered
    difference, and the control's, as the part relief makes and the part those turns make."""
    catalogs = load_comparison_catalogs()
    if scoring_binding(catalogs) != registered["scoring"]:
        raise SystemExit("the score read here is not the one the comparison registered")
    weights = person_score(catalogs.score).weights
    if weights.get("need_relief") != 1000 or any(weights.get(t) != -1000 for t in TURN_TERMS):
        raise SystemExit(f"a score of other weights cannot be split this way: {weights}")
    contract = decision_contract(registered["contract"]["catalog_versions"])
    if contract.binding() != registered["contract"]:
        raise SystemExit("the decision contract read here is not the one the comparison registered")
    deadline = contract.value("decision_deadline_ms")
    arms = sorted(judged["summaries"])
    seeds = []
    parts: dict[str, dict[str, list[Fraction]]] = {
        arm: {"score": [], "relief": [], "share": []} for arm in arms
    }
    totals = {arm: {"turns": 0, "not_applied": 0} for arm in arms}
    for seed in judged["seeds"]:
        if seed["excluded"] is not None:
            raise SystemExit(f"{seed['name']} was excluded; this split reads scored seeds only")
        runs = {}
        for arm in arms:
            run = seed["runs"][arm]
            score = Fraction(run["score"])
            share = Fraction(run["not_applied"], run["turns"]) if run["turns"] else Fraction(0)
            relief = score + share
            for key, value in (("score", score), ("relief", relief), ("share", share)):
                parts[arm][key].append(value)
            totals[arm]["turns"] += run["turns"]
            totals[arm]["not_applied"] += run["not_applied"]
            latency = (run["calls"] or {}).get("latency_ms") or {}
            runs[arm] = {
                "score": run["score"],
                "turns": run["turns"],
                "not_applied": run["not_applied"],
                "not_applied_share": _text(share),
                "relief": _text(relief),
                "answer_ms_p95": latency.get("p95"),
                "answer_ms_p95_reached_the_deadline": None
                if latency.get("p95") is None
                else latency["p95"] >= deadline,
            }
        seeds.append({"name": seed["name"], "seed_digest": seed["seed_digest"], "runs": runs})
    per_arm = {
        arm: {
            "mean_score": _text(_mean(parts[arm]["score"])),
            "mean_relief": _text(_mean(parts[arm]["relief"])),
            "mean_not_applied_share": _text(_mean(parts[arm]["share"])),
            **totals[arm],
        }
        for arm in arms
    }
    pairs = [(d["first"], d["second"]) for d in judged["differences"]]
    pairs.append(tuple(registered["control"]))
    differences = []
    for first, second in pairs:
        pairs_of = {
            key: zip(parts[first][key], parts[second][key], strict=True)
            for key in ("relief", "share")
        }
        relief = _mean([b - a for a, b in pairs_of["relief"]])
        turns = _mean([a - b for a, b in pairs_of["share"]])
        differences.append(
            {
                "first": first,
                "second": second,
                "control": [first, second] == list(registered["control"]),
                "score": _text(relief + turns),
                "from_relief": _text(relief),
                "from_turns_not_applied": _text(turns),
            }
        )
    return {
        "deadline_ms": deadline,
        "arms": per_arm,
        "seeds": seeds,
        "differences": differences,
    }


def main() -> None:
    as_run = Path(__file__).read_bytes()
    for relative in (RECORD, AS_RUN):
        if (ROOT / relative).exists():
            raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    judged = _read(JUDGED)
    registered = _read(PREREGISTRATION)
    if judged["record"]["preregistration_record_sha256"] != registered["record_sha256"]:
        raise SystemExit("the judged record names another pre-registration")
    record = {
        "question": (
            "Where each arm's score in the judged comparison comes from: the need its people were "
            "spared, and the share of their turns whose model's answer was not applied."
        ),
        "judged_record": JUDGED,
        "judged_record_sha256": judged["record_sha256"],
        "preregistration_record_sha256": registered["record_sha256"],
        "method": (
            "A run's relief is its recorded score plus its turns not applied over its turns, the "
            "score's two turn terms each weighing minus one. Scores are recorded to four places, "
            "so each relief is within 0.00005 of the exact value. A difference is split as the "
            "mean over seeds of the relief it makes and of the turns not applied it makes, the "
            "two summing to the score's difference."
        ),
        "reasons_kept": False,
        "reasons": (
            "The judged record keeps how many of a run's turns were not applied, not why: each "
            "turn's reason was in the run's receipts, in the private database the measurement made "
            "for the run and removed after it. What the record keeps of the asking is each run's "
            "answer time at the 50th and 95th percentiles, set beside the deadline here."
        ),
        **decompose(judged["record"], registered["record"]),
        "script": SCRIPT,
        "script_as_run": AS_RUN,
        "script_sha256": _sha256(as_run),
    }
    target = ROOT / RECORD
    body = {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}
    target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / AS_RUN).write_bytes(as_run)
    print(f"wrote {RECORD} and {AS_RUN}")


if __name__ == "__main__":
    main()
