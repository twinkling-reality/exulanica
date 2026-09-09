"""Measure the Companion question path against the retained bowl workspace, with real models.

    EXULANICA_BUDGET_USD=0.50 EXULANICA_BUDGET_MAX_CALLS=40 \
      uv run python scripts/measure_companion_questions.py \
        --cap-usd 0.50 --max-calls 40 --api http://127.0.0.1:8000 --out /tmp/companion-questions

THIS SCRIPT SPENDS MONEY. It refuses to start unless the operator's cap is stated twice, once in
the environment where ``BudgetGuard`` reads it and once on the command line where a person typed
it. The two must agree exactly. A single statement would make an accidental default look like an
authorisation, and the guard's default ceiling is five dollars.

It measures three things, and they are three because they answer three different questions:

1.  **Five questions through the real HTTP route**, against the retained bowl workspace. This is
    the product path and nothing is substituted in it: the same uvicorn, the same read-only
    executor role, the same planner and composer. The five are chosen to span what the workspace
    can and cannot support. The bowl has 51 citable captures, zero entities and zero captions, so
    "who is in them" and "what is this place" have nothing to answer from and MUST abstain; time
    and count questions are answerable; and one question is about nothing in the library at all.

2.  **The same packets composed by the fallback model.** `nvidia/Nemotron-3_5-Lightning` was
    measured at 80.4 s on a 24-item packet, which is a latency somebody waits through in a demo.
    Whether `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B` is faster at the same job, and whether it
    conforms at all, is the evidence a role change would have to rest on. Run in process against
    packets rebuilt from the SAME plans through the same read-only connection, because the point
    is to vary one thing.

3.  **One call to `nvidia/nemotron-3-super-120b-a12b`**, which was recorded returning text that
    is not JSON. Recorded once, as a fact with a date on it, because a model that starts
    conforming should not go unnoticed and neither should one that never did.

Nothing here writes. The API is read through its own read-only executor role, the in-process
half opens the read-only URL, and no manifest file and no `pipeline_version` is edited: the
pinned comparison replaces one role binding on an in-memory copy.

The bearer token and the API key are read and never printed, never written to the output, and
never put in a URL.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from exulanica.db import Database
from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import Role, load_manifest
from exulanica.selection import (
    SelectionPlan,
    Session,
    build_packet,
    execute,
    validate,
)
from exulanica.selection.question import (
    COMPOSER_MAX_TOKENS,
    PROMPT_VERSION,
    CallLog,
    compose_answer,
)

ROOT = Path(__file__).resolve().parents[1]
#: The one database this experiment is permitted to read. Stated rather than configurable.
DATABASE = "postgresql://localhost:5433/exulanica_spine_test"
READONLY = DATABASE + "?options=-crole%3Dexulanica_ro"
STATE = ROOT / ".exulanica/reference-baseline/runtime"

#: A micro-dollar. Costs are recorded as integers of this unit because an evaluation record in
#: this repository carries no floats: a float rewrites its own last digits on a JSON round trip,
#: and a digest over it stops reproducing.
MICRO = Decimal("0.000001")

#: The five, in the order they are asked. Each one names what it is FOR, because a question set
#: whose choices are not argued is a question set that was chosen to pass.
QUESTIONS: tuple[tuple[str, str, str], ...] = (
    (
        "when",
        "When were these photographs taken?",
        "Answerable. The captures carry captured_at, and the packet mints date value references "
        "for it, so an answer can name a date without inventing one.",
    ),
    (
        "how_many",
        "How many photographs are there?",
        "Answerable. capture_count is a value reference computed from the query result, which is "
        "the only way a number may appear in an answer at all.",
    ),
    (
        "what_place",
        "What is this place?",
        "MUST ABSTAIN or decline to name it. The workspace holds no place entity and no caption, "
        "so there is nothing an answer could cite for a name.",
    ),
    (
        "who",
        "Who is in these photographs?",
        "MUST ABSTAIN. Zero entities, so the planner catalogue is empty and nobody has been "
        "named. An answer that named somebody would be the failure the whole path exists against.",
    ),
    (
        "unrelated",
        "What is the current exchange rate for the pound?",
        "MUST ABSTAIN. Nothing in a photograph library answers it, and the honest reply is that "
        "there is no evidence rather than a guess from general knowledge.",
    ),
)


def micro_usd(value: Decimal) -> int:
    """A cost as whole micro-dollars, rounded up. Never a float, and never rounded down."""
    return int((value / MICRO).to_integral_value(rounding="ROUND_CEILING"))


def cost_of(manifest, model_id: str, prompt: int | None, completion: int | None) -> int:
    """What one call cost, from the reported usage and the manifest's published prices."""
    if prompt is None and completion is None:
        return 0
    spec = manifest.spec(model_id)
    return micro_usd(spec.cost_usd(prompt_tokens=prompt or 0, completion_tokens=completion or 0))


def read_token(scene: str) -> tuple[str, str]:
    """The reference workspace's bearer token and workspace id. Returned, never printed."""
    config = json.loads((STATE / "access.json").read_bytes())
    entry = config["scenes"][scene]
    return entry["token"], entry["workspace_id"]


def ask_over_http(client: httpx.Client, question: str) -> tuple[int, dict[str, Any], int]:
    """One question through the real route. Returns the status, the body and the wall clock.

    **A non-200 is recorded rather than raised, and that is the point of measuring.** Measured on
    the retained bowl workspace, whose catalogue is empty: the planner returned a Selection
    naming an entity id that does not exist, the validator refused it, and the route answered
    404 `unknown_reference`. A harness that raised there would have reported a crash and lost the
    finding; the resolved-ids rule did exactly what it is for, and what the question got was
    still not an answer.

    The wall clock is measured here as well as read from the response, because they are two
    different numbers: the response reports what the model calls took and this reports what the
    person waited, which also contains the SQL, the packet build and the network.
    """
    started = time.monotonic()
    response = client.post("/selection/ask", json={"question": question})
    elapsed_ms = round((time.monotonic() - started) * 1000)
    try:
        body = response.json()
    except ValueError:
        body = {"non_json_body": response.text[:600]}
    return response.status_code, body, elapsed_ms


def packet_for(connection, plan: dict[str, Any], session: Session):
    """Rebuild the packet one plan resolved to, through the read-only executor role.

    The connection has to be WORKSPACE SCOPED, which a bare ``psycopg.connect`` is not. Row-level
    security is on, so an unscoped connection reads nothing and every packet rebuilt through one
    comes back empty; the first run of this script reported "the packet is empty" for all five
    questions against a workspace holding 51 captures. ``Database.session`` is what the API's own
    read-only dependency uses, so using it here is also what makes this a comparison rather than
    a differently-configured second system.
    """
    parsed = SelectionPlan.model_validate(plan)
    result = execute(connection, validate(connection, parsed, session))
    return build_packet(connection, result, workspace_id=session.workspace_id), result


def pinned_manifest(manifest, model_id: str):
    """The same manifest with the composer role pointed at one named model.

    In memory only. ``exulanica/models/models.manifest.json`` is not edited and
    ``pipeline_version`` does not move: this is a comparison, and a comparison that changed the
    product's own configuration would leave the thing it measured behind it.
    """
    binding = manifest[Role.REASONING_CHEAP]
    pinned = dataclasses.replace(binding, primary=manifest.spec(model_id), fallback=None)
    roles = dict(manifest.roles)
    roles[Role.REASONING_CHEAP] = pinned
    return dataclasses.replace(manifest, roles=roles)


def measure() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True, help="The operator's ceiling, stated again")
    parser.add_argument("--max-calls", required=True, type=int)
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--scene", default="bowl")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--skip-live",
        action="store_true",
        help="Exercise only the routes that spend nothing: the packet route and the 503.",
    )
    args = parser.parse_args()

    environment_cap = os.environ.get("EXULANICA_BUDGET_USD", "")
    environment_calls = os.environ.get("EXULANICA_BUDGET_MAX_CALLS", "")
    if not args.skip_live:
        if Decimal(environment_cap or "-1") != Decimal(args.cap_usd):
            raise SystemExit(
                f"EXULANICA_BUDGET_USD={environment_cap!r} does not match --cap-usd "
                f"{args.cap_usd!r}. The cap is stated twice on purpose: a default that nobody "
                "typed is not an authorisation."
            )
        if int(environment_calls or -1) != args.max_calls:
            raise SystemExit(
                f"EXULANICA_BUDGET_MAX_CALLS={environment_calls!r} does not match --max-calls "
                f"{args.max_calls}."
            )
        if not os.environ.get("NEBIUS_API_KEY"):
            raise SystemExit("NEBIUS_API_KEY is not set, so there is nothing to measure.")

    args.out.mkdir(parents=True, exist_ok=False)
    token, workspace_id = read_token(args.scene)
    manifest = load_manifest()

    runs: list[dict[str, Any]] = []
    with httpx.Client(
        base_url=args.api,
        headers={"authorization": f"Bearer {token}"},
        timeout=300.0,
    ) as http:
        health = http.get("/readyz")
        (args.out / "readyz.json").write_text(json.dumps(health.json(), indent=2) + "\n")

        # The deterministic half, first and always. It spends nothing, and it is the measurement
        # that says what the workspace actually holds, so a later abstention can be read as
        # honest rather than as an empty database.
        probe = {"intent": "captures", "limit": 5}
        packet_response = http.post("/selection/packet", json=probe)
        packet_response.raise_for_status()
        packet_body = packet_response.json()
        (args.out / "packet-probe.request.json").write_text(json.dumps(probe, indent=2) + "\n")
        (args.out / "packet-probe.response.json").write_text(
            json.dumps(packet_body, indent=2) + "\n"
        )

        if args.skip_live:
            unpaid = http.post("/selection/ask", json={"question": QUESTIONS[0][1]})
            (args.out / "ask-without-a-model.response.json").write_text(
                json.dumps(
                    {"status_code": unpaid.status_code, "body": unpaid.json()}, indent=2
                )
                + "\n"
            )
            summary = {
                "live": False,
                "packet_citable": packet_body["citable"],
                "packet_total_matched": packet_body["total_matched"],
                "ask_status_without_a_model": unpaid.status_code,
            }
            (args.out / "measurement.json").write_text(json.dumps(summary, indent=2) + "\n")
            print(json.dumps(summary))
            return 0

        for key, question, why in QUESTIONS:
            request = {"question": question}
            status, body, waited_ms = ask_over_http(http, question)
            (args.out / f"ask-{key}.request.json").write_text(json.dumps(request, indent=2) + "\n")
            (args.out / f"ask-{key}.response.json").write_text(
                json.dumps({"status_code": status, "body": body}, indent=2) + "\n"
            )
            if status != 200:
                runs.append(
                    {
                        "key": key,
                        "question": question,
                        "why_this_question": why,
                        "status_code": status,
                        "refusal": body,
                        "wall_clock_ms": waited_ms,
                        "answered": False,
                    }
                )
                print(f"{key}: {waited_ms} ms, HTTP {status}", file=sys.stderr)
                continue

            execution = body["execution"]
            calls = execution["calls"]
            runs.append(
                {
                    "key": key,
                    "question": question,
                    "why_this_question": why,
                    "status_code": status,
                    "answered": True,
                    # Both nullable since the planner-failure abstention: a question that never
                    # became a search has no Selection to report, and reporting an empty one
                    # would say the whole library was looked at.
                    "plan": body["plan"],
                    "packet_citable_items": len(body["citations"]),
                    "selection_total_matched": (
                        None if body["selection"] is None else body["selection"]["total_matched"]
                    ),
                    "answer": " ".join(c["text"] for c in body["answer"]["clauses"]),
                    "clause_types": [c["type"] for c in body["answer"]["clauses"]],
                    "abstained": body["abstained"],
                    "deterministic": body["deterministic"],
                    "repaired": body["repaired"],
                    "rejections": execution["rejections"],
                    "prompt_version": execution["prompt_version"],
                    "calls": calls,
                    "served_models": [c["served_model"] for c in calls],
                    "model_latency_ms": sum(c["latency_ms"] for c in calls),
                    "wall_clock_ms": waited_ms,
                    "cost_micro_usd": sum(
                        cost_of(
                            manifest,
                            c["requested_model"],
                            c["prompt_tokens"],
                            c["completion_tokens"],
                        )
                        for c in calls
                    ),
                }
            )
            print(f"{key}: {waited_ms} ms, abstained={body['abstained']}", file=sys.stderr)

    # -- the pinned comparison, in process against the same plans ----------------------------
    pinned_model = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    comparison: list[dict[str, Any]] = []
    conformance: dict[str, Any] = {}
    session = Session(workspace_id=uuid.UUID(workspace_id), actor=uuid.uuid4())
    with Database(READONLY).session(uuid.UUID(workspace_id)) as connection:
        pinned_client = ModelClient(
            manifest=pinned_manifest(manifest, pinned_model),
            budget=BudgetGuard(
                ceiling_usd=Decimal(args.cap_usd), max_calls=args.max_calls
            ),
        )
        for run in runs:
            if not run.get("answered"):
                comparison.append({"key": run["key"], "skipped": "the route refused this question"})
                continue
            if run["plan"] is None:
                comparison.append(
                    {"key": run["key"], "skipped": "the question never became a Selection"}
                )
                continue
            packet, _ = packet_for(connection, run["plan"], session)
            if packet.is_empty:
                comparison.append({"key": run["key"], "skipped": "the packet is empty"})
                continue
            log = CallLog()
            started = time.monotonic()
            answer, deterministic, rejections = compose_answer(
                pinned_client, run["question"], packet, log=log
            )
            comparison.append(
                {
                    "key": run["key"],
                    "packet_items": len(packet.items),
                    "answer": " ".join(clause.text for clause in answer.clauses),
                    "deterministic": deterministic,
                    "rejections": list(rejections),
                    "calls": [dataclasses.asdict(call) for call in log.calls],
                    "model_latency_ms": sum(call.latency_ms for call in log.calls),
                    "wall_clock_ms": round((time.monotonic() - started) * 1000),
                    "cost_micro_usd": sum(
                        cost_of(
                            manifest,
                            call.requested_model,
                            call.prompt_tokens,
                            call.completion_tokens,
                        )
                        for call in log.calls
                    ),
                }
            )

        # -- does the escalation tier still answer with something that is not JSON? ----------
        escalation = "nvidia/nemotron-3-super-120b-a12b"
        first = next(
            (
                r
                for r in runs
                if r.get("answered") and r["plan"] is not None and r["packet_citable_items"] > 0
            ),
            None,
        )
        if first is not None:
            packet, _ = packet_for(connection, first["plan"], session)
            escalation_client = ModelClient(
                manifest=pinned_manifest(manifest, escalation),
                budget=BudgetGuard(ceiling_usd=Decimal(args.cap_usd), max_calls=args.max_calls),
            )
            log = CallLog()
            try:
                _, deterministic, rejections = compose_answer(
                    escalation_client, first["question"], packet, log=log
                )
                conformance = {
                    "model_id": escalation,
                    "raised": None,
                    "fell_back_to_deterministic": deterministic,
                    "rejections": list(rejections),
                    "calls": [dataclasses.asdict(call) for call in log.calls],
                }
            except ModelError as exc:
                conformance = {
                    "model_id": escalation,
                    "raised": type(exc).__name__,
                    "detail": str(exc)[:600],
                    "calls": [dataclasses.asdict(call) for call in log.calls],
                }

    record = {
        "profile": "exulanica.companion-question-measurement/v1",
        "workspace": f"retained local reference, scene={args.scene}",
        "database_schema": "0038",
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": manifest.pipeline_version,
        "composer_max_tokens": COMPOSER_MAX_TOKENS,
        "cap_usd": str(Decimal(args.cap_usd)),
        "cap_max_calls": args.max_calls,
        "route": {"questions": runs},
        "pinned_composer": {"model_id": pinned_model, "runs": comparison},
        "escalation_conformance": conformance,
        "total_cost_micro_usd": (
            sum(run.get("cost_micro_usd", 0) for run in runs)
            + sum(entry.get("cost_micro_usd", 0) for entry in comparison)
        ),
        "experiment_script": "scripts/measure_companion_questions.py",
        "experiment_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (args.out / "measurement.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(json.dumps({
        "questions": len(runs),
        "answered": [r["key"] for r in runs if r.get("answered")],
        "abstained": [
            f"{r['key']}:{r['abstained']}" for r in runs if r.get("abstained") is not None
        ],
        "refused": [f"{r['key']}:{r['status_code']}" for r in runs if not r.get("answered")],
        "total_cost_micro_usd": record["total_cost_micro_usd"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(measure())
