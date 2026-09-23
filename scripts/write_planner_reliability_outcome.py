"""Score the held-out planner runs against their pre-registration and write the outcome record.

    python scripts/write_planner_reliability_outcome.py OUT.json \
        --preregistration docs/evaluation/2026-09-22-companion-planner-preregistration.json \
        --baseline RUN.json [RUN.json ...] --candidate RUN.json [RUN.json ...] \
        --base-plan PATH/TO/BASE/exulanica/selection/plan.py --notes NOTES.json

``--notes`` holds what a person wrote after reading the numbers (what the candidate changed, what
was observed, what is not covered), kept verbatim under ``notes`` and never mixed into a number.

Makes no model call. Every run must name the pre-registration by its digest and must have been
produced by the scorer the pre-registration binds, byte for byte; the baseline runs must have
imported the base commit's files and the candidate runs one frozen set of files. Rows are scored
again here with that scorer and must agree with what each run recorded.

``no_loosening`` validates every answer either arm received, first attempts and repairs, with
both arms' ``SelectionPlan``. The base commit's is loaded from ``--base-plan`` on its own, which
works because ``plan.py`` imports nothing from this package.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from measure_planner_reliability import DECIDING_FILES, score

from exulanica.canonical import canonical_json
from exulanica.selection.plan import SelectionPlan

ROOT = Path(__file__).resolve().parents[1]
KINDS = ("place", "person", "content")


def load_record(path: Path) -> tuple[dict[str, Any], str]:
    document = json.loads(path.read_bytes())
    digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
    if digest != document["record_sha256"]:
        raise SystemExit(f"{path} does not reproduce its record_sha256")
    return document["record"], digest


def base_files(base_commit: str) -> dict[str, str]:
    """The SHA-256 of each deciding file at the base commit, read from git, not from a copy."""
    return {
        name: hashlib.sha256(
            subprocess.run(
                ["git", "show", f"{base_commit}:exulanica/{name}"],
                cwd=ROOT, check=True, capture_output=True,
            ).stdout
        ).hexdigest()
        for name in DECIDING_FILES
    }


def load_plan_class(path: Path) -> type:
    spec = importlib.util.spec_from_file_location("base_selection_plan", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # Pydantic resolves the module's postponed annotations through ``sys.modules``. Unregistered,
    # every model in it is "not fully defined" and refuses every answer, which reads as the two
    # arms disagreeing about all of them.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.SelectionPlan


#: The acceptance comparison's own control: each class must accept the first and refuse the
#: second, or the comparison measured the loader instead of the rules.
CONTROL_RIGHT = {
    "intent": "captures", "entities": None, "time": [],
    "place": {"ids": ["00000000-0000-4000-8000-000000000001"]}, "capture": None, "content": None,
    "epistemic": "confirmed", "semantic_query": "sign", "limit": 10,
}
CONTROL_WRONG = {
    **CONTROL_RIGHT, "intent": "content", "content": {"scope": "memories_only", "after": None},
}


def controlled(plan_class: type, name: str) -> dict[str, bool]:
    result = {
        "accepts_the_right_plan": accepts(plan_class, json.dumps(CONTROL_RIGHT)),
        "refuses_the_wrong_plan": not accepts(plan_class, json.dumps(CONTROL_WRONG)),
    }
    if not all(result.values()):
        raise SystemExit(f"the {name} SelectionPlan failed the acceptance control: {result}")
    return result


def accepts(plan_class: type, answer: str) -> bool:
    try:
        plan_class.model_validate(json.loads(answer))
    except Exception:
        return False
    return True


def p95(values: list[int]) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, (95 * len(ordered)) // 100)]


def arm_rows(runs: list[dict[str, Any]], held_out: dict[str, Any], arm: str) -> list[dict[str, Any]]:
    """Every scored draw of one arm, re-scored here, as compact rows for the record."""
    expected = {entry["id"]: entry["expect"] for entry in held_out["questions"]}
    rows = []
    for run_index, run in enumerate(runs):
        for row in run["rows"]:
            problems = score(row["plan"], expected[row["question"]], held_out)
            if problems != row["problems"]:
                raise SystemExit(f"{arm} run {run_index} {row['question']}: rescoring disagrees")
            last = row["attempts"][-1] if row["attempts"] else {}
            # A reply the model ran past its token limit is its failure, not the provider's: the
            # pre-registration excluded provider errors and did not anticipate this, so it is
            # counted as a failed draw, which can only lower a rate.
            outcome = (
                "truncated"
                if row["outcome"] == "error" and (row["error"] or "").startswith(
                    "TruncatedResponseError"
                )
                else row["outcome"]
            )
            rows.append({
                "arm": arm,
                "run": run_index,
                "question": row["question"],
                "kind": row["kind"],
                "outcome": outcome,
                "right": not problems,
                "problems": problems,
                # One compact line per plan, so every plan stays re-scorable from the record.
                "plan": (
                    json.dumps(row["plan"], sort_keys=True, separators=(",", ":"))
                    if row["plan"] is not None else None
                ),
                "refused_because": (
                    [f"{reason['loc']}: {reason['msg']}" for reason in last.get("schema_reasons") or []]
                    if row["outcome"] == "refused" else []
                ),
                "error": row["error"],
                "attempts": len(row["attempts"]),
                "wall_ms": row["wall_ms"],
                "input_tokens": row["input_tokens"],
                "output_tokens": row["output_tokens"],
                "usd": row["usd"],
            })
    return rows


def rates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in (*KINDS, "all"):
        chosen = [row for row in rows if kind in ("all", row["kind"])]
        scored = [row for row in chosen if row["outcome"] != "error"]
        right = sum(row["right"] for row in scored)
        out[kind] = {
            "draws": len(chosen),
            "provider_errors": len(chosen) - len(scored),
            "plans": sum(row["outcome"] == "plan" for row in scored),
            "refused": sum(row["outcome"] == "refused" for row in scored),
            "truncated": sum(row["outcome"] == "truncated" for row in scored),
            "questions_always_right": sum(
                all(row["right"] for row in scored if row["question"] == question)
                for question in sorted({row["question"] for row in scored})
            ),
            "questions": len({row["question"] for row in scored}),
            "repaired": sum(row["attempts"] > 1 for row in scored),
            "right": right,
            "right_bp": (10000 * right) // len(scored) if scored else None,
            "wall_ms_p95": p95([row["wall_ms"] for row in scored]) if scored else None,
            "mean_usd_per_draw": str(
                (sum((Decimal(row["usd"]) for row in scored), Decimal(0)) / len(scored)).quantize(
                    Decimal("0.00000001")
                )
            ) if scored else None,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("out")
    parser.add_argument("--preregistration", required=True)
    parser.add_argument("--baseline", nargs="+", required=True)
    parser.add_argument("--candidate", nargs="+", required=True)
    parser.add_argument("--base-plan", required=True)
    parser.add_argument("--notes", required=True)
    arguments = parser.parse_args()
    notes = json.loads(Path(arguments.notes).read_bytes())

    prereg_path = Path(arguments.preregistration)
    prereg, prereg_digest = load_record(prereg_path)
    scorer = prereg["procedure"]["scorer"]
    if hashlib.sha256((ROOT / scorer["path"]).read_bytes()).hexdigest() != scorer["sha256"]:
        raise SystemExit("the scorer on disk is not the one the pre-registration binds")
    held_out = prereg["held_out"]
    expected_draws = prereg["procedure"]["draws_per_question_per_arm"]

    base = base_files(prereg["base_commit"])
    base_plan_bytes = Path(arguments.base_plan).read_bytes()
    if hashlib.sha256(base_plan_bytes).hexdigest() != base["selection/plan.py"]:
        raise SystemExit("--base-plan is not the base commit's plan.py")

    arms: dict[str, list[dict[str, Any]]] = {}
    identity: dict[str, dict[str, str]] = {}
    for arm, paths in (("baseline", arguments.baseline), ("candidate", arguments.candidate)):
        runs = [json.loads(Path(path).read_bytes()) for path in paths]
        if len(runs) * runs[0]["draws_per_question"] != expected_draws:
            raise SystemExit(f"{arm}: {len(runs)} runs is not {expected_draws} draws per question")
        for run in runs:
            if run["provenance"].get("preregistration_record_sha256") != prereg_digest:
                raise SystemExit(f"{arm}: a run did not use the pre-registered question set")
            if run["script_sha256"] != scorer["sha256"]:
                raise SystemExit(f"{arm}: a run was made by a different scorer")
            if run["package"]["files"] != runs[0]["package"]["files"]:
                raise SystemExit(f"{arm}: the runs did not all import the same files")
            if {row["question"] for row in run["rows"]} != {
                entry["id"] for entry in held_out["questions"]
            }:
                raise SystemExit(f"{arm}: a run did not ask every held-out question")
        if arm == "baseline" and runs[0]["package"]["files"] != base:
            raise SystemExit("the baseline runs did not import the base commit's files")
        identity[arm] = {
            "files": runs[0]["package"]["files"],
            "prompt_version": runs[0]["package"]["prompt_version"],
            "planner_system_sha256": runs[0]["package"]["planner_system_sha256"],
            "run_started_at": [run["started_at"] for run in runs],
        }
        arms[arm] = arm_rows(runs, held_out, arm)
    if identity["candidate"]["files"] == identity["baseline"]["files"]:
        raise SystemExit("the candidate imported the base commit's files: there is no change")

    measured = {arm: rates(rows) for arm, rows in arms.items()}
    base_rates, cand_rates = measured["baseline"], measured["candidate"]
    gates = prereg["gates"]

    # no_loosening: every answer either arm received, validated by both arms' SelectionPlan.
    base_class = load_plan_class(Path(arguments.base_plan))
    controls = {
        "baseline": controlled(base_class, "baseline"),
        "candidate": controlled(SelectionPlan, "candidate"),
    }
    answers: list[str] = []
    for path in (*arguments.baseline, *arguments.candidate):
        for row in json.loads(Path(path).read_bytes())["rows"]:
            answers.extend(
                attempt["answer"] for attempt in row["attempts"]
                if isinstance(attempt.get("answer"), str)
            )
    disagreements = [
        answer for answer in answers
        if accepts(base_class, answer) != accepts(SelectionPlan, answer)
    ]

    errors_over = any(
        rows["all"]["provider_errors"] * 10 > rows["all"]["draws"] for rows in measured.values()
    )
    checks = {
        "place_rate": cand_rates["place"]["right_bp"] >= gates["place_rate"]["candidate_min_bp"],
        "place_improvement": (
            cand_rates["place"]["right_bp"] - base_rates["place"]["right_bp"]
            >= gates["place_improvement"]["candidate_minus_baseline_min_bp"]
        ),
        "person_no_regression": (
            cand_rates["person"]["right_bp"] - base_rates["person"]["right_bp"]
            >= gates["person_no_regression"]["candidate_minus_baseline_min_bp"]
        ),
        "content_no_regression": (
            cand_rates["content"]["right_bp"] - base_rates["content"]["right_bp"]
            >= gates["content_no_regression"]["candidate_minus_baseline_min_bp"]
        ),
        "latency": (
            cand_rates["all"]["wall_ms_p95"] <= gates["latency"]["candidate_p95_ms_max"]
            and 100 * cand_rates["all"]["wall_ms_p95"]
            <= gates["latency"]["candidate_p95_max_percent_of_baseline_p95"]
            * base_rates["all"]["wall_ms_p95"]
        ),
        "cost": (
            Decimal(cand_rates["all"]["mean_usd_per_draw"])
            <= Decimal(gates["cost"]["candidate_mean_usd_per_draw_max"])
            and 100 * Decimal(cand_rates["all"]["mean_usd_per_draw"])
            <= gates["cost"]["candidate_mean_max_percent_of_baseline_mean"]
            * Decimal(base_rates["all"]["mean_usd_per_draw"])
        ),
        "no_loosening": len(disagreements) <= gates["no_loosening"]["disagreements_max"],
    }
    collapsed: list[str] = []
    if "per_question_no_collapse" in gates:
        # Declared by the second pre-registration, after the first experiment's aggregate person
        # gate held while one person question fell from 5 of 5 to 1 of 5.
        rule = gates["per_question_no_collapse"]
        for entry in held_out["questions"]:
            right = {
                arm: sum(row["right"] for row in rows if row["question"] == entry["id"])
                for arm, rows in arms.items()
            }
            if (
                right["baseline"] >= rule["baseline_min_right"]
                and right["candidate"] <= rule["candidate_max_right_counted_as_collapse"]
            ):
                collapsed.append(entry["id"])
        checks["per_question_no_collapse"] = not collapsed
    if errors_over:
        verdict = "void: provider errors exceeded a tenth of an arm's draws"
    elif base_rates["place"]["right_bp"] >= 6000:
        verdict = "the held-out split did not reproduce the defect; no improvement is claimed"
    elif all(checks.values()):
        verdict = "pass: every pre-registered gate holds"
    else:
        verdict = "fail: " + ", ".join(name for name, held in checks.items() if not held)

    by_question = []
    for entry in held_out["questions"]:
        line: dict[str, Any] = {"id": entry["id"], "kind": entry["kind"], "text": entry["text"]}
        for arm, rows in arms.items():
            mine = [row for row in rows if row["question"] == entry["id"]]
            line[arm] = {
                "right": sum(row["right"] for row in mine),
                "draws": len(mine),
                "problems": sorted({problem for row in mine for problem in row["problems"]}),
            }
        by_question.append(line)

    spend = {
        arm: {
            "calls": sum(row["attempts"] for row in rows),
            "input_tokens": sum(row["input_tokens"] for row in rows),
            "output_tokens": sum(row["output_tokens"] for row in rows),
            "usd": str(sum((Decimal(row["usd"]) for row in rows), Decimal(0))),
        }
        for arm, rows in arms.items()
    }
    body = {
        "predecessor_records": [{
            "path": prereg_path.as_posix()
            if not prereg_path.is_absolute() else prereg_path.relative_to(ROOT).as_posix(),
            "record_sha256": prereg_digest,
        }],
        "profile_note": "Outcome of the pre-registered planner reliability experiment, scored "
                        "once per arm on the held-out split. No model call is made to write it.",
        "verdict": verdict,
        "gates": {name: {"held": held} for name, held in checks.items()},
        "measured": measured,
        "no_loosening": {
            "answers_validated": len(answers),
            "disagreements": len(disagreements),
            "controls": controls,
            "method": "every attempt's answer from both arms, validated by the base commit's "
                      "SelectionPlan and by the candidate's",
        },
        "arms": identity,
        "by_question": by_question,
        "spend": spend,
        "spend_note": "provider-reported tokens times the manifest's listed prices, every attempt "
                      "included, refused ones too",
        "notes": notes,
        "not_covered": prereg["not_covered"],
        "rows": [*arms["baseline"], *arms["candidate"]],
    }
    if "per_question_no_collapse" in gates:
        # Only where a pre-registration declares the gate, so an earlier record regenerated by
        # this script reproduces its bound digest.
        body["collapsed_questions"] = collapsed
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": hashlib.sha256(canonical_json(body)).hexdigest(),
    }
    Path(arguments.out).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(f"{arguments.out} record_sha256 {document['record_sha256']}")
    print(verdict)
    print(json.dumps({"gates": checks, "measured": measured}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
