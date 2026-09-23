"""Draw the Companion's planner many times on worded questions, and score every plan it returns.

    EXULANICA_BUDGET_USD=0.50 python scripts/measure_planner_reliability.py \
        --cap-usd 0.50 --questions SET.json --draws 5 --arm baseline --out OUT.json

    python scripts/measure_planner_reliability.py --rescore OUT.json --questions SET.json

THIS SCRIPT SPENDS MONEY. It refuses to start unless the cap is stated twice, once in the
environment where ``BudgetGuard`` reads it and once on the command line, and the two agree.

What it measures is the planner and nothing downstream of it: ``propose_plan`` is called exactly as
``answer_question`` calls it, saved names redacted first, over a catalogue of invented entities
built in memory. No database, no route, no packet and no composer. A question set is a JSON file
holding the catalogue and the questions, each with what a right plan names (see ``score``); a
pre-registration record carries the same shape under ``record.held_out`` and is accepted directly,
with its digest checked, so a run can only be of the frozen set.

Which planner runs is whichever ``exulanica`` this interpreter imports. The output records that
path and the SHA-256 of every file that decides a plan, so a baseline arm run against an export of
the base commit and a candidate arm run in a worktree cannot be mistaken for each other.

Every attempt is kept whole: the model's full answer, the repair message it was sent, the
refusal the client raised, and the reason the plan schema gives when it refuses the answer,
computed here from the answer itself rather than read off that refusal. The provider's own usage
fields give tokens and cost, and they are read from the client's ledger, which records a call
before its reply is validated, so a refused draw is paid for in the totals. Nothing is estimated.

The credential is read by the model client from the environment and never printed or written.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
import uuid
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any

import exulanica
from exulanica.canonical import canonical_json
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError, StructuredOutputError
from exulanica.models.transport import HttpxTransport
from exulanica.selection import question as planner
from exulanica.selection.plan import SelectionPlan
from exulanica.selection.question import CallLog, EntityChoice, propose_plan
from exulanica.selection.saved_names import SavedName, redact_names

#: The files whose bytes decide what a plan is, hashed into every output so an arm names its code.
DECIDING_FILES = (
    "selection/question.py",
    "selection/plan.py",
    "selection/saved_names.py",
    "models/client.py",
    "models/response.py",
    "models/schema.py",
    "models/models.manifest.json",
)

#: Words that carry no content, dropped before a semantic query is compared with what a question
#: allows. Deliberately short: anything else a query carries must be named as allowed.
STOP_WORDS = frozenset(
    {"a", "an", "the", "of", "on", "in", "at", "and", "or", "with", "to", "for", "from", "by"}
)


def stem(word: str) -> str:
    """A crude plural fold, so "signs" and "sign" compare equal. Deterministic, never clever."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def query_words(text: str) -> list[str]:
    return [stem(word) for word in re.findall(r"[a-z]+", text.lower()) if word not in STOP_WORDS]


# -- the question set ----------------------------------------------------------------------------


def load_question_set(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(question set, provenance)``. A pre-registration record is digest-checked first."""
    document = json.loads(path.read_bytes())
    if "record" in document and "record_sha256" in document:
        digest = hashlib.sha256(canonical_json(document["record"])).hexdigest()
        if digest != document["record_sha256"]:
            raise SystemExit(f"{path} does not reproduce its record_sha256; refusing to run it")
        return document["record"]["held_out"], {"preregistration_record_sha256": digest}
    return document, {"question_set_sha256": hashlib.sha256(canonical_json(document)).hexdigest()}


def catalogue_of(question_set: Mapping[str, Any]) -> tuple[tuple[EntityChoice, ...], tuple[SavedName, ...]]:
    entries = question_set["catalogue"]
    choices = tuple(
        EntityChoice(uuid.UUID(entry["id"]), entry["class"], entry["name"]) for entry in entries
    )
    names = tuple(SavedName(uuid.UUID(entry["id"]), entry["class"], entry["name"]) for entry in entries)
    return choices, names


# -- scoring ---------------------------------------------------------------------------------------


def score(plan: Mapping[str, Any] | None, expect: Mapping[str, Any], question_set: Mapping[str, Any]) -> list[str]:
    """Every way ``plan`` is not the right plan for its question. Empty means right.

    ``expect`` holds:

    * ``intents``: the intents that answer the question. CAPTURES and ENTITIES resolve the same
      photographs and hand the composer the same packet, so a question about what photographs
      show accepts both; CONTENT is a different answer entirely (a deterministic listing across
      memories, admitted geography and authored versions, with no composer).
    * ``place`` and ``entities``: the exact id sets the plan must carry in those selectors.
    * ``modes``: the entity modes accepted when ``entities`` is not empty.
    * ``scopes``: the content scopes accepted when the intent is CONTENT.
    * ``query``: ``null`` (whether no semantic query is right), ``required`` (at least one of
      these words must be in a query) and ``allowed`` (every word of a query must be one of these,
      after stop words and plural folding). A question that names no visible or written content
      allows nothing, so any query fails it: the text dimension is an inner join, and a word in no
      caption removes the photograph the rest of the plan found.

    And every question carries no time, no capture property and no request about guesses, so a
    plan that fills ``time``, ``capture`` or ``epistemic`` has added a filter nobody asked for.
    """
    if plan is None:
        return ["no_plan"]
    problems: list[str] = []
    classes = {entry["id"]: entry["class"] for entry in question_set["catalogue"]}
    place = sorted((plan.get("place") or {}).get("ids") or [])
    entity_selector = plan.get("entities") or {}
    entities = sorted(entity_selector.get("ids") or [])
    for entity_id in [*place, *entities]:
        if entity_id not in classes:
            problems.append(f"unknown_reference:{entity_id}")
    for entity_id in place:
        if classes.get(entity_id) not in (None, "place"):
            problems.append(f"place_selector_holds_a_{classes[entity_id]}")
    if plan.get("intent") not in expect["intents"]:
        problems.append(f"intent:{plan.get('intent')}")
    if place != sorted(expect["place"]):
        problems.append("place_ids")
    if entities != sorted(expect["entities"]):
        problems.append("entity_ids")
    if entities and entity_selector.get("mode") not in expect.get("modes", ["any"]):
        problems.append(f"mode:{entity_selector.get('mode')}")
    if plan.get("intent") == "content":
        content = plan.get("content") or {}
        if content.get("scope") not in expect.get("scopes", []):
            problems.append(f"scope:{content.get('scope')}")
    if plan.get("time"):
        problems.append("time_added")
    if plan.get("capture") is not None:
        problems.append("capture_added")
    if plan.get("epistemic") != "confirmed":
        problems.append(f"epistemic:{plan.get('epistemic')}")
    rule = expect["query"]
    query = plan.get("semantic_query")
    if query is None:
        if not rule["null"]:
            problems.append("query:null")
    else:
        words = query_words(query)
        allowed = {stem(word) for word in rule["allowed"]}
        required = {stem(word) for word in rule["required"]}
        outside = sorted({word for word in words if word not in allowed})
        if not words:
            problems.append("query:no_content_words")
        if outside:
            problems.append("query:not_allowed:" + ",".join(outside))
        if required and not required & set(words):
            problems.append("query:missing_required")
    return problems


# -- the network, recorded -------------------------------------------------------------------------


class RecordingTransport:
    """``HttpxTransport`` with every chat exchange kept. Headers are never kept: they hold the key."""

    def __init__(self, inner: HttpxTransport) -> None:
        self._inner = inner
        # The client checks the endpoint against this at construction, as it would the real one.
        self.egress = inner.egress
        self.exchanges: list[dict[str, Any]] = []

    def post_json(self, url: str, *, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float) -> Any:
        response = self._inner.post_json(url, headers=headers, payload=payload, timeout=timeout)
        self.exchanges.append(
            {"messages": payload.get("messages"), "status": response.status_code, "body": response.text}
        )
        return response

    def get_json(self, url: str, *, headers: Mapping[str, str], timeout: float) -> Any:
        return self._inner.get_json(url, headers=headers, timeout=timeout)


def schema_reasons(answer: str) -> list[dict[str, Any]]:
    """What ``SelectionPlan`` says about this answer, computed from the answer, not from a message."""
    try:
        parsed = json.loads(answer)
    except json.JSONDecodeError as exc:
        return [{"loc": "<body>", "msg": f"not JSON: {exc}", "type": "json"}]
    try:
        SelectionPlan.model_validate(parsed)
    except Exception as exc:  # pydantic.ValidationError, kept general so a baseline export works
        errors = getattr(exc, "errors", None)
        if not callable(errors):
            return [{"loc": "<root>", "msg": str(exc), "type": type(exc).__name__}]
        return [
            {
                "loc": "/".join(str(part) for part in error["loc"]) or "<root>",
                "msg": error["msg"],
                "type": error["type"],
            }
            for error in errors(include_url=False)
        ]
    return []


def attempt_rows(exchanges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, exchange in enumerate(exchanges):
        row: dict[str, Any] = {"status": exchange["status"]}
        messages = exchange["messages"] or []
        if index > 0 and messages:
            row["repair_sent"] = messages[-1].get("content")
        try:
            body = json.loads(exchange["body"])
        except json.JSONDecodeError:
            row["body_excerpt"] = exchange["body"][:500]
            rows.append(row)
            continue
        choice = (body.get("choices") or [{}])[0]
        answer = (choice.get("message") or {}).get("content")
        row.update(
            {
                "served_model": body.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "usage": body.get("usage"),
                "answer": answer,
                "schema_reasons": schema_reasons(answer) if isinstance(answer, str) else None,
            }
        )
        rows.append(row)
    return rows


# -- one run ---------------------------------------------------------------------------------------


def package_identity() -> dict[str, Any]:
    root = Path(exulanica.__file__).resolve().parent
    return {
        "package_dir": str(root),
        "files": {
            name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in DECIDING_FILES
        },
        "prompt_version": planner.PROMPT_VERSION,
        "planner_system_sha256": hashlib.sha256(planner._PLANNER_SYSTEM.encode()).hexdigest(),
    }


def run(arguments: argparse.Namespace) -> None:
    declared = os.environ.get("EXULANICA_BUDGET_USD")
    if declared is None or Decimal(declared) != Decimal(arguments.cap_usd):
        raise SystemExit(
            "state the cap twice: EXULANICA_BUDGET_USD in the environment and --cap-usd on the "
            f"command line, equal. Environment has {declared!r}, command line {arguments.cap_usd!r}."
        )
    question_set, provenance = load_question_set(Path(arguments.questions))
    identity = package_identity()
    if arguments.expect_package_dir and identity["package_dir"] != str(
        Path(arguments.expect_package_dir).resolve()
    ):
        raise SystemExit(f"this interpreter imports {identity['package_dir']}, not the arm asked for")
    catalogue, names = catalogue_of(question_set)
    selected = [
        entry for entry in question_set["questions"]
        if not arguments.only or entry["id"] in arguments.only
    ]
    transport = RecordingTransport(HttpxTransport())
    client = ModelClient(transport=transport)
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    rows = []
    for draw in range(arguments.draws):
        for entry in selected:
            transport.exchanges.clear()
            before = len(client.ledger.calls)
            log = CallLog()
            # Exactly answer_question's order: the question is redacted once, then the planner is
            # handed the redacted text, every saved name and the placeholders already assigned.
            asked = redact_names(entry["text"], names)
            started = time.perf_counter()
            plan: dict[str, Any] | None = None
            refusal = None
            error = None
            try:
                proposed = propose_plan(
                    client,
                    asked.text,
                    catalogue,
                    names=names,
                    placeholders=asked.placeholders,
                    now=now,
                    log=log,
                )
                plan = proposed.model_dump(mode="json")
            except StructuredOutputError as exc:
                refusal = str(exc)
            except ModelError as exc:
                error = f"{type(exc).__name__}: {exc}"
            wall_ms = round((time.perf_counter() - started) * 1000)
            calls = client.ledger.calls[before:]
            problems = score(plan, entry["expect"], question_set)
            rows.append(
                {
                    "draw": draw,
                    "question": entry["id"],
                    "kind": entry["kind"],
                    "asked": asked.text,
                    "outcome": "plan" if plan is not None else ("refused" if refusal else "error"),
                    "plan": plan,
                    "refusal": refusal,
                    "error": error,
                    "problems": problems,
                    "right": not problems,
                    "wall_ms": wall_ms,
                    "calls": len(calls),
                    "input_tokens": sum(call.prompt_tokens for call in calls),
                    "output_tokens": sum(call.completion_tokens for call in calls),
                    "usd": str(sum((call.usd for call in calls), Decimal(0))),
                    "attempts": attempt_rows(transport.exchanges),
                }
            )
            print(
                f"{entry['id']} draw {draw}: {rows[-1]['outcome']} "
                f"{problems or 'RIGHT'} {wall_ms} ms",
                flush=True,
            )
    output = {
        "arm": arguments.arm,
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "started_at": now.isoformat(),
        "draws_per_question": arguments.draws,
        "provenance": provenance,
        "package": identity,
        "spend": client.ledger.as_cost_json(),
        "rows": rows,
        "summary": summarise(rows),
    }
    Path(arguments.out).write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps(output["summary"], indent=2, sort_keys=True))
    print(f"spend {output['spend']}")


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per kind and overall: draws, plans returned, right plans, repairs, latency and cost."""
    summary: dict[str, Any] = {}
    for kind in [*sorted({row["kind"] for row in rows}), "all"]:
        chosen = [row for row in rows if kind in ("all", row["kind"])]
        walls = sorted(row["wall_ms"] for row in chosen)
        summary[kind] = {
            "draws": len(chosen),
            "plans": sum(row["outcome"] == "plan" for row in chosen),
            "right": sum(row["right"] for row in chosen),
            "refused": sum(row["outcome"] == "refused" for row in chosen),
            "errors": sum(row["outcome"] == "error" for row in chosen),
            "repaired": sum(row["calls"] > 1 for row in chosen),
            "wall_ms_p50": walls[len(walls) // 2] if walls else None,
            "wall_ms_p95": walls[min(len(walls) - 1, (95 * len(walls)) // 100)] if walls else None,
            "usd": str(sum((Decimal(row["usd"]) for row in chosen), Decimal(0))),
        }
    return summary


def rescore(arguments: argparse.Namespace) -> None:
    """Score a recorded run again, offline. Makes no call."""
    question_set, _ = load_question_set(Path(arguments.questions))
    expected = {entry["id"]: entry["expect"] for entry in question_set["questions"]}
    recorded = json.loads(Path(arguments.rescore).read_bytes())
    for row in recorded["rows"]:
        row["problems"] = score(row["plan"], expected[row["question"]], question_set)
        row["right"] = not row["problems"]
    recorded["summary"] = summarise(recorded["rows"])
    print(json.dumps(recorded["summary"], indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--questions", required=True, help="a question set, or a pre-registration record")
    parser.add_argument("--rescore", help="score a recorded run again, offline")
    parser.add_argument("--cap-usd")
    parser.add_argument("--draws", type=int, default=1)
    parser.add_argument("--arm", default="unnamed")
    parser.add_argument("--out")
    parser.add_argument("--only", nargs="*", help="question ids to run; all when absent")
    parser.add_argument("--expect-package-dir", help="refuse unless exulanica is imported from here")
    arguments = parser.parse_args()
    if arguments.rescore:
        rescore(arguments)
        return
    if not arguments.out or not arguments.cap_usd:
        parser.error("a measuring run needs --out and --cap-usd")
    run(arguments)


if __name__ == "__main__":
    sys.exit(main())
