"""Measure grounded Companion answers on an isolated runtime, then compare the reasoning role.

    EXULANICA_BUDGET_USD=2.00 python scripts/measure_grounded_answers.py \
        --cap-usd 2.00 --state STATE.json --out OUT.json

THIS SCRIPT SPENDS MONEY. It refuses to start unless the ceiling is stated twice, once in the
environment where ``BudgetGuard`` reads it and once on the command line where a person typed it,
and the two must agree exactly. A single statement would make an accidental default look like an
authorisation.

Two halves, because they answer two different questions.

1.  **The pre-registered questions through the real HTTP route.** This is the product path and
    nothing is substituted in it: the same uvicorn, the same read-only executor role, the same
    planner and the same composer. What is recorded is what a person would have got, including
    every model call the response reports and the wall clock they waited through.

2.  **The same packets composed by each candidate.** Built from the SAME plans through the same
    read-only connection, with one role binding replaced on an in-memory copy of the manifest
    and nothing else varied. ``exulanica/models/models.manifest.json`` is not edited and
    ``pipeline_version`` does not move: a comparison that changed the product's configuration
    would leave behind the thing it was measuring.

Costs are whole micro-dollars, never floats: a float rewrites its own last digits on a JSON
round trip and a digest over it stops reproducing. The bearer token and the API key are read,
never printed and never written to the output.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.db import Database
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection import SelectionPlan, Session, build_packet, execute, validate
from exulanica.selection.question import CallLog, compose_answer

MICRO = Decimal("0.000001")

CANDIDATES = ("nvidia/nemotron-3-super-120b-a12b", "nvidia/Nemotron-3-Ultra-550b-a55b")


def micro_usd(value: Decimal) -> int:
    """A cost as whole micro-dollars, rounded up. Never a float, and never rounded down."""
    return int((value / MICRO).to_integral_value(rounding="ROUND_CEILING"))


def questions() -> list[dict[str, str]]:
    """The pre-registered held-out set, read from the record that froze it.

    Read rather than restated. A second copy of a question list is a second source of truth, and
    the one that drifts is always the copy nobody is looking at.
    """
    record = json.loads(
        (Path(__file__).resolve().parents[1]
         / "docs/evaluation/2026-09-22-model-selection-preregistration.json").read_bytes()
    )["record"]
    return list(record["comparison_a_reasoning"]["held_out_questions"])


def ask_over_http(base: str, token: str, question: str) -> tuple[int, Any, int]:
    """One question through the real route. A non-200 is recorded rather than raised.

    The wall clock is measured here as well as read from the response, because they are two
    different numbers: the response reports what the model calls took, and this reports what the
    person waited through, which also contains the SQL, the packet build and the network.
    """
    body = json.dumps({"question": question}).encode()
    request = urllib.request.Request(f"{base}/selection/ask", data=body, method="POST")
    request.add_header("Authorization", f"Bearer {token}")
    request.add_header("Content-Type", "application/json")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read()
    elapsed_ms = round((time.monotonic() - started) * 1000)
    try:
        return status, json.loads(raw or b"null"), elapsed_ms
    except json.JSONDecodeError:
        return status, {"non_json_body": raw.decode("utf-8", "replace")[:600]}, elapsed_ms


def pinned(manifest, model_id: str):
    """The same manifest with the composer role pointed at one named model. In memory only."""
    binding = manifest[Role.REASONING_CHEAP]
    roles = dict(manifest.roles)
    roles[Role.REASONING_CHEAP] = dataclasses.replace(
        binding, primary=manifest.spec(model_id), fallback=None
    )
    return dataclasses.replace(manifest, roles=roles)


def compose_with(manifest, question: str, packet, cap: Decimal) -> dict[str, Any]:
    """One composition, with its own budget guard so one arm cannot spend another's ceiling."""
    client = ModelClient(manifest=manifest, budget=BudgetGuard(ceiling_usd=cap))
    log = CallLog()
    started = time.monotonic()
    try:
        answer, repaired, rejections = compose_answer(client, question, packet, log=log)
        failure = None
    except ModelError as exc:
        answer, repaired, rejections, failure = None, False, (), f"{type(exc).__name__}: {exc}"
    elapsed_ms = round((time.monotonic() - started) * 1000)
    return {
        "latency_ms": elapsed_ms,
        "failure": failure,
        "repaired": repaired,
        "rejections": list(rejections),
        "micro_usd": micro_usd(client.budget.spent_usd),
        "calls": [
            {"role": call.role, "requested_model": call.requested_model,
             "served_model": call.served_model, "used_fallback": call.used_fallback,
             "attempts": call.attempts, "latency_ms": call.latency_ms,
             "prompt_tokens": call.prompt_tokens, "completion_tokens": call.completion_tokens,
             "reasoning_tokens": call.reasoning_tokens, "usd": call.usd}
            for call in log.calls
        ],
        "answer": None if answer is None else {
            "clauses": [
                {"text": clause.text, "type": str(clause.type),
                 "citations": list(clause.citations)}
                for clause in answer.clauses
            ],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True, help="the ceiling, stated again")
    parser.add_argument("--state", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--skip-candidates", action="store_true")
    arguments = parser.parse_args()

    stated = Decimal(arguments.cap_usd)
    from_environment = os.environ.get("EXULANICA_BUDGET_USD", "")
    if not from_environment or Decimal(from_environment) != stated:
        raise SystemExit(
            f"--cap-usd {stated} and EXULANICA_BUDGET_USD {from_environment!r} must agree; "
            "one statement of a ceiling is a default, not an authorisation"
        )

    state = json.loads(Path(arguments.state).read_text())
    base = f"http://127.0.0.1:{state['ports']['api']}"
    token = Path(state["token_file"]).read_text().strip()
    session = Session(workspace_id=uuid.UUID(state["workspace_id"]),
                      actor=uuid.UUID(state["actor"]))
    database = Database(url=state["database"]["owner_url_for_evidence_reads"])
    manifest = load_manifest()

    results = []
    for item in questions():
        status, body, elapsed_ms = ask_over_http(base, token, item["question"])
        entry = {
            "key": item["key"], "hard": item["hard"], "question": item["question"],
            "for": item["for"],
            "route": {
                "status": status,
                "route_latency_ms": elapsed_ms,
                "deterministic": (body or {}).get("deterministic"),
                "repaired": (body or {}).get("repaired"),
                "abstained": (body or {}).get("abstained"),
                "plan": (body or {}).get("plan"),
                "answer": (body or {}).get("answer"),
                "citations": (body or {}).get("citations"),
                "execution": (body or {}).get("execution"),
            },
            "candidates": {},
        }

        plan = (body or {}).get("plan")
        if not arguments.skip_candidates and status == 200 and plan:
            with database.session(session.workspace_id) as connection:
                parsed = SelectionPlan.model_validate(plan)
                result = execute(connection, validate(connection, parsed, session), world_id=None)
                packet = build_packet(connection, result, workspace_id=session.workspace_id)
            entry["packet"] = {
                "items": len(packet.items),
                "values": len(packet.values),
                "total_matched": packet.total_matched,
                "citable": packet.citable,
            }
            baseline_id = manifest[Role.REASONING_CHEAP].primary.model_id
            for model_id in (baseline_id, *CANDIDATES):
                entry["candidates"][model_id] = compose_with(
                    pinned(manifest, model_id), item["question"], packet, stated
                )
        results.append(entry)
        print(f"{item['key']:<16} route {status} {elapsed_ms:>6} ms "
              f"candidates {len(entry['candidates'])}")

    Path(arguments.out).write_text(json.dumps(
        {"questions": results,
         "manifest_pipeline_version": manifest.pipeline_version,
         "baseline_model": manifest[Role.REASONING_CHEAP].primary.model_id,
         "candidate_models": list(CANDIDATES)},
        indent=2, sort_keys=True) + "\n")
    print(f"wrote {arguments.out}")


if __name__ == "__main__":
    main()
