"""Write the outcome of the Companion place-link measurement from its runs.

    python scripts/write_companion_place_link_outcome.py --before RUN.json --after RUN.json \\
        --browser DIR --browser-before-fixes DIR --measured-with FILE

``RUN.json`` is what ``scripts/measure_companion_place_link.py run`` wrote for an arm, and each
``DIR`` is an ``evidence.json`` with its screenshots from ``scripts/capture_companion_place_link.mjs``:
the final browser run, and the first one, whose findings changed the page before the final run.
``--measured-with`` is the exact copy of the measurement script the arms ran, whose digest must
equal the one the pre-registration binds.

The record carries every answer as the API returned it, the verdict of the registered rule, and
what every stage cost as the provider reported it. The screenshots are copied beside the record
and bound by SHA-256. Absolute paths are not copied: the runtime is named by its tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.canonical import canonical_json

ROOT = Path(__file__).resolve().parents[1]
PREREGISTRATION = "docs/evaluation/2026-09-23-companion-place-link-preregistration.json"
OUT = "docs/evaluation/2026-09-23-companion-place-link-outcome.json"
ARTIFACTS = "docs/evaluation/artifacts/2026-09-23-companion-place-link"
#: The page's own files the browser runs drew with, bound as they stand when this record is written.
WEB_SOURCES = (
    "web/packages/app/src/companion-names.ts",
    "web/packages/app/src/composition/companion.ts",
    "web/packages/app/src/ui/companion-encounter.ts",
    "web/packages/app/src/ui/companion-evidence.ts",
    "web/packages/app/src/ui/companion-speech.ts",
)
#: What a record may keep of one model call, all of it read off the response body.
CALL_FIELDS = (
    "role",
    "requested_model",
    "served_model",
    "used_fallback",
    "latency_ms",
    "prompt_tokens",
    "completion_tokens",
    "reasoning_tokens",
    "usd",
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _registered() -> tuple[dict[str, Any], str]:
    document = json.loads((ROOT / PREREGISTRATION).read_bytes())
    digest = _sha256(canonical_json(document["record"]))
    if digest != document["record_sha256"]:
        raise SystemExit(f"{PREREGISTRATION} does not match its own digest")
    return document["record"], digest


def _calls(execution: Any) -> list[dict[str, Any]]:
    return [
        {field: call.get(field) for field in CALL_FIELDS}
        for call in (execution or {}).get("calls", [])
    ]


def _usd(calls: list[dict[str, Any]]) -> Decimal:
    return sum((Decimal(str(call["usd"])) for call in calls if call["usd"]), Decimal(0))


def _arm(run: dict[str, Any]) -> dict[str, Any]:
    answers = []
    for answer in run["answers"]:
        calls = _calls(answer["execution"])
        answers.append(
            {
                "question_id": answer["question_id"],
                "question": answer["question"],
                "status": answer["status"],
                "clauses": answer["clauses"],
                "names": answer["names"],
                "abstained": answer["abstained"],
                "deterministic": answer["deterministic"],
                "plan": answer["plan"],
                "prompt_version": (answer["execution"] or {}).get("prompt_version"),
                "calls": calls,
                "usd": str(_usd(calls)),
                "score": answer["score"],
            }
        )
    job = (run["operations"] or {}).get("cost", {})
    return {
        "tree": run["runtime"]["tree"],
        "workspace_id": run["runtime"]["workspace_id"],
        "sources_sha256": run["sources_sha256"],
        "vision": {
            str(number): {
                "outcome": decision["outcome"],
                "written_label": decision["written_label"],
                "proposed_label": decision["proposed_label"],
                "usage": decision["usage"],
                "sign_usage": (decision.get("place_check") or {}).get("sign_usage"),
            }
            for number, decision in sorted(run["decisions"].items())
        },
        "derivative_jobs_cost": job,
        "confirmed_photographs": run["confirmed_photographs"],
        "confirmed_entity_id": run["named"]["entity_id"],
        "answers": answers,
        "right": sum(1 for answer in answers if answer["score"]["right"]),
        "asked": len(answers),
        "reported_usd": run["reported_usd"],
    }


def _browser(
    directory: Path, label: str, bind: frozenset[str] | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """One browser run's steps and its screenshots, bound beside the record.

    ``bind`` names the screenshots that carry evidence, or None for all of them; the others stay
    with the run and are named by the step that took them.
    """
    evidence = json.loads((directory / "evidence.json").read_bytes())
    target = ROOT / ARTIFACTS
    target.mkdir(parents=True, exist_ok=True)
    captures = []
    steps = []
    spent = Decimal(0)
    recorded = False
    for step in evidence["steps"]:
        shots = []
        for shot in step["screenshots"]:
            if bind is not None and shot["file"] not in bind:
                shots.append(f"not bound: {shot['file']}")
                continue
            name = f"{label}-{shot['file']}"
            data = (directory / "screens" / shot["file"]).read_bytes()
            if _sha256(data) != shot["sha256"]:
                raise SystemExit(f"{shot['file']} is not the screenshot its run recorded")
            shutil.copyfile(directory / "screens" / shot["file"], target / name)
            capture = {
                "path": f"{ARTIFACTS}/{name}",
                "byte_size": len(data),
                "sha256": shot["sha256"],
                "shows": shot["shows"],
            }
            captures.append(capture)
            shots.append(capture["path"])
        requests = []
        for request in step["requests"]:
            kept = {key: request[key] for key in ("method", "path", "status")}
            execution = request.get("execution")
            calls = _calls(execution) if isinstance(execution, dict) else []
            recorded = recorded or isinstance(execution, dict)
            if calls:
                kept["calls"] = calls
                spent += _usd(calls)
            requests.append(kept)
        steps.append(
            {
                "name": step["name"],
                "ok": step["ok"],
                "error": step["error"],
                "notes": step["notes"],
                **{
                    key: step[key]
                    for key in ("drawn", "view", "evidence", "injected", "back")
                    if key in step
                },
                "requests": requests,
                "screenshots": shots,
            }
        )
    return {
        "viewport": evidence["viewport"],
        "console": evidence["console"],
        "steps": steps,
        # None when the run kept no response body to read a cost from, which is not a cost of zero.
        "reported_usd": str(spent) if recorded else None,
    }, captures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--browser", required=True)
    parser.add_argument("--browser-before-fixes", required=True)
    parser.add_argument("--measured-with", required=True)
    arguments = parser.parse_args()

    registered, registered_sha256 = _registered()
    measured_with = _sha256(Path(arguments.measured_with).read_bytes())
    bound = registered["sources_sha256"]["scripts/measure_companion_place_link.py"]
    if measured_with != bound:
        raise SystemExit(f"the arms ran a measurement script at {measured_with}, not {bound}")
    before = _arm(json.loads(Path(arguments.before).read_bytes()))
    after = _arm(json.loads(Path(arguments.after).read_bytes()))
    for name, arm in (("before", before), ("after", after)):
        expected = registered["change"]["arms"][name]
        question = arm["sources_sha256"]["exulanica/selection/question.py"]
        if question != expected["exulanica/selection/question.py"]:
            raise SystemExit(f"the {name} arm ran question.py {question}, not the registered one")
        if any(answer["prompt_version"] != expected["prompt_version"] for answer in arm["answers"]):
            raise SystemExit(f"the {name} arm answered under another prompt version")
    browser, captures = _browser(Path(arguments.browser), "final")
    first, first_captures = _browser(
        Path(arguments.browser_before_fixes),
        "before-fixes",
        bind=frozenset({"02-answer-sign.png"}),
    )

    body = {
        "profile_note": (
            "Outcome of the Companion place-link measurement, scored once by the rule its "
            "pre-registration states. One draw per question per arm."
        ),
        "predecessor_record": {"path": PREREGISTRATION, "record_sha256": registered_sha256},
        "measured_with_sha256": measured_with,
        "arms": {"before": before, "after": after},
        "verdict": {
            "before": f"{before['right']} of {before['asked']} right",
            "after": f"{after['right']} of {after['asked']} right",
            "by_question": {
                answer["question_id"]: {
                    "before": before_answer["score"]["right"],
                    "after": answer["score"]["right"],
                }
                for before_answer, answer in zip(before["answers"], after["answers"], strict=True)
            },
        },
        "browser": {
            "final": {
                **browser,
                "web_sources_sha256": {
                    path: _sha256((ROOT / path).read_bytes()) for path in WEB_SOURCES
                },
                "runtime": "the after arm's runtime and workspace, after that arm's questions",
                "injected": (
                    "The refused photograph's read was answered 410 by the capture script "
                    "through the DevTools Fetch domain, because no route deletes a photograph; "
                    "the product's server was not asked that time. The shown photograph's read "
                    "was the server's own masked route."
                ),
            },
            "before_fixes": {
                **first,
                "found": [
                    "The composer wrote the placeholder as 'PLACE A', capitalised and without "
                    "its brackets, and the page showed it as written; the page reads an answer's "
                    "own labels in any case, with or without brackets, since.",
                    "The photograph's arrival redrew its face and dropped keyboard focus from the "
                    "way back; the redraw keeps it since.",
                ],
            },
        },
        "captures": [*captures, *first_captures],
        "spend": {
            "reported_usd": {
                "before_arm": before["reported_usd"],
                "after_arm": after["reported_usd"],
                "browser_final": browser["reported_usd"],
                "browser_before_fixes": first["reported_usd"],
            },
            "not_recorded": (
                "Two browser runs kept no response bodies, so their model calls were not read: "
                "the run before the fixes, bound here, and a second run between it and the final "
                "one, not bound. Each asked the same three questions through the same routes, "
                "which the final run reports at the cost above."
            ),
            "bound_usd": registered["spend"]["bound_usd"],
        },
        "not_established": registered["not_covered"],
    }
    document = {
        "profile": "exulanica.digest-bound-record/v1",
        "record": body,
        "record_sha256": _sha256(canonical_json(body)),
    }
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    for forbidden in ("/Users/", "Bearer ", "api-token"):
        if forbidden in text:
            raise SystemExit(f"the record would carry {forbidden!r}")
    (ROOT / OUT).write_text(text)
    print(f"{OUT} record_sha256 {document['record_sha256']}")


if __name__ == "__main__":
    main()
