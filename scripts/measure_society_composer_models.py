"""Compare the models that may choose the lines of an answer about what happened in a world.

    uv run python scripts/measure_society_composer_models.py preregister
    uv run python scripts/measure_society_composer_models.py dry-run
    EXULANICA_BUDGET_USD=<bound> uv run python scripts/measure_society_composer_models.py run

THE RUN STEP SPENDS MONEY. It reads the provider's key from its own environment only, and its
bound from ``EXULANICA_BUDGET_USD``, which may not exceed the bound the pre-registration states.

The world is the small square the society question tests run (``tests/test_society_question.py``:
the first development seed, 40 simulated minutes), so its 24 event lines are the same bytes every
time; the pre-registration binds their digest. Every candidate is asked every question through
``compose_society_answer``, the product's own composer path, with the composer role pointed at the
candidate on an in-memory copy of the manifest. Within each question the candidates take turns,
so a slow minute at the provider falls on all of them rather than on one.

The composer's own clock is held still here, so a refused choice is asked for again; the
client's deadline for the composer still ends a slow call. The run the record binds (its as-run
copy beside it) allowed one repair per question and waited each role's whole timeout, and no answer
used a repair; this live copy asks as the product does, and its run step refuses to run again,
because the pre-registration binds the as-run bytes.

``preregister`` writes the questions, the world's digest, the candidates, the rule that chooses a
default and the bound, before any model is asked. ``dry-run`` drives the whole run over a scripted
transport that answers every call with the first line's token, spending nothing, so the record
path is exercised before money is. ``run`` refuses unless the pre-registration still matches.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from exulanica.canonical import canonical_json  # noqa: E402

PROFILE: Final = "exulanica.digest-bound-record/v1"
STEM: Final = "2026-09-29-society-composer-models"
PREREGISTRATION: Final = f"docs/evaluation/{STEM}-preregistration.json"
RECORD: Final = f"docs/evaluation/{STEM}.json"
ARTIFACTS: Final = f"docs/evaluation/artifacts/{STEM}"
RUN_ARTIFACT: Final = f"{ARTIFACTS}/run.json"
DRY_RUN_ARTIFACT: Final = f"{ARTIFACTS}/dry-run.json"
AS_RUN: Final = f"{ARTIFACTS}/measure_society_composer_models-as-run.py.txt"
SCRIPT: Final = "scripts/measure_society_composer_models.py"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
KEY_VARIABLE: Final = "NEBIUS_API_KEY"

#: The most the run may spend. The expected spend is about 0.03 USD (the candidates' prices at
#: about 1.2 thousand prompt tokens and a few thousand completion tokens per call, a repair at
#: most per question); the rest is room for the largest reservation the guard holds before a call,
#: the most expensive candidate's completion ceiling at its output price (about 0.015 USD).
BOUND_USD: Final = Decimal("0.10")
#: The completion ceiling every candidate is asked with: the ceiling at which the slowest
#: reasoning candidate conformed on a 24-line packet (the manifest's reasoning_cheap max_tokens
#: basis), which is this world's packet size. One ceiling for all, so none is truncated by a
#: choice made for another.
MAX_TOKENS: Final = 16384
#: The attempts the pre-registered run allowed per question: one try and one repair.
ATTEMPTS: Final = 2
#: The use cases a model's catalog entry must declare to be a candidate: the composer reads text
#: and chooses tokens from it, which is the text use case and nothing more.
REQUIRED_USE_CASES: Final = ("text",)
#: Text models the manifest declares that may not become the default, so are not asked: a default
#: must be a model whose licence entry in docs/license-matrix.md has nothing unresolved.
LICENCE_UNRESOLVED: Final = {
    "MiniMaxAI/MiniMax-M3": "UNVERIFIED: its licence text was never read (L-2, section 8)",
    "nvidia/Nemotron-3-Ultra-550b-a55b": "UNVERIFIED direction of error: catalog-only (section 5)",
    "openbmb/MiniCPM-V-4_5": "OPEN: its Hugging Face card frontmatter was never read",
}

#: The fixed questions, each about what happened over the whole world, as the planner routes them
#: to the composer. Worded as people ask, from the one the Companion's evidence run asked.
QUESTIONS: Final = (
    "What happened in the square this morning?",
    "What has been going on here?",
    "Did anyone talk to each other?",
    "Who has been resting?",
    "What did people do in the last few minutes?",
    "Tell me what happened while I was away.",
    "Has anyone finished what they were doing?",
    "What is everyone up to?",
)

#: The rule that chooses the default, written before any model is asked.
RULE: Final = {
    "eligible": (
        "a candidate is eligible when at least 7 of the 8 questions were composed and accepted "
        "by the extractive checks, after at most one repair"
    ),
    "speed_bound_ms": 10000,
    "speed_bound_reason": (
        "the Companion's evidence run measured the product's composer (Nano) at 12.3 to 19.6 s "
        "per answer; an NVIDIA default must answer faster than that at its slowest to be worth "
        "preferring. A longest call of 10 s gives, through the manifest's timeout rule (twice the "
        "longest, rounded up to 5 s), a per-call timeout of 20 s, and a whole-question budget of "
        "the planner's 25 s plus two such attempts, 65 s; a slower default moves both up"
    ),
    "p95_with_eight": "with 8 questions per model the p95 by nearest rank is the slowest of the 8",
    "choice": (
        "the eligible NVIDIA model (identifier beginning nvidia/) with the lowest p95 answer time "
        "is chosen when that p95 is at most speed_bound_ms; otherwise the eligible model with the "
        "lowest p95 answer time. Ties go to the lower total cost."
    ),
    "fallback": (
        "the fallback is the next eligible model in the same order (NVIDIA first when within "
        "speed_bound_ms, then by p95), or none when no other model is eligible"
    ),
    "answer_time": (
        "one question's answer time is the sum of its composer attempts' latencies, as the "
        "client measured each"
    ),
    "why_nvidia_first": (
        "AGENTS.md prefers NVIDIA models where they meet the task; meeting it here is being "
        "eligible and answering within speed_bound_ms at the 95th percentile"
    ),
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _document(record: Mapping[str, Any]) -> dict[str, Any]:
    return {"profile": PROFILE, "record": record, "record_sha256": _sha256(canonical_json(record))}


def _write_new(relative: str, value: Mapping[str, Any], *, record: bool = True) -> None:
    target = ROOT / relative
    if target.exists():
        raise SystemExit(f"{relative} exists, and docs/evaluation is append-only")
    target.parent.mkdir(parents=True, exist_ok=True)
    body = _document(value) if record else value
    target.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {relative}", flush=True)


def _read_record(relative: str) -> dict[str, Any]:
    document = json.loads((ROOT / relative).read_bytes())
    if _sha256(canonical_json(document["record"])) != document["record_sha256"]:
        raise SystemExit(f"{relative} does not match its own digest")
    return document["record"]


def _head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, check=True, text=True
    ).stdout.strip()


def _manifest_sha256() -> str:
    from exulanica.models.manifest import MANIFEST_PATH

    return _sha256(MANIFEST_PATH.read_bytes())


# -- the world and the candidates --------------------------------------------------------------


def _packet(question: str) -> Any:
    """The packet the composer is sent for ``question`` over the square: the product's builder."""
    import test_society_question as square

    from exulanica.selection.inhabitant_words import inhabitant_words_catalog
    from exulanica.selection.society_question import _Builder, _happened

    builder = _Builder(square._scene(question), inhabitant_words_catalog())
    _happened(builder)
    return builder.packet()


def _world() -> dict[str, Any]:
    """The world's lines as words: each packet draws its tokens afresh, so they are not digested."""
    import test_society_question as square

    lines = [item.line for item in _packet(QUESTIONS[0]).items]
    return {
        "what": (
            "the small square of tests/test_society_question.py: its first development seed, "
            f"{square.MINUTES} simulated minutes, the latest lines as the composer is sent them"
        ),
        "lines": len(lines),
        "lines_sha256": _sha256("\n".join(lines).encode()),
        "tokens": "drawn afresh for every packet, as the product draws them",
    }


def _candidates() -> list[str]:
    """Every chat model the manifest declares with the text use case and a JSON schema."""
    from exulanica.models.manifest import load_manifest

    return [
        model_id
        for model_id, spec in sorted(load_manifest().models.items())
        if spec.is_chat
        and spec.supports_json_schema
        and all(use in spec.catalog_use_cases for use in REQUIRED_USE_CASES)
        and model_id not in LICENCE_UNRESOLVED
    ]


def _pinned(manifest: Any, model_id: str) -> Any:
    """The manifest with the composer's role pointed at ``model_id`` alone, in memory only."""
    from exulanica.selection.society_question import COMPOSER_ROLE

    binding = manifest[COMPOSER_ROLE]
    roles = dict(manifest.roles)
    roles[COMPOSER_ROLE] = dataclasses.replace(
        binding, primary=manifest.spec(model_id), fallback=None
    )
    return dataclasses.replace(manifest, roles=roles)


# -- pre-registration --------------------------------------------------------------------------


def _registration() -> dict[str, Any]:
    from exulanica.selection.prompts import PROMPT_VERSION
    from exulanica.selection.society_question import COMPOSER_ROLE

    return {
        "question": (
            "Which model should choose the lines of a Companion answer about what happened in a "
            "world: the share of answers composed and accepted, answer time p50 and p95, and cost"
        ),
        "questions": list(QUESTIONS),
        "world": _world(),
        "candidates": _candidates(),
        "candidates_rule": (
            "every chat model the manifest declares with a JSON schema and the use cases "
            f"{list(REQUIRED_USE_CASES)}, except those whose licence entry is unresolved"
        ),
        "not_asked_for_licence": LICENCE_UNRESOLVED,
        "composer_role": str(COMPOSER_ROLE),
        "prompt_version": PROMPT_VERSION,
        "max_tokens": MAX_TOKENS,
        "attempts": ATTEMPTS,
        "per_call_timeout": (
            "the composer role's timeout_seconds in the manifest the run reads, the same for "
            "every candidate"
        ),
        "order": "question by question; within a question every candidate in turn",
        "rule": RULE,
        "bound_usd": str(BOUND_USD),
        "measured": [
            "per question and candidate: composed and accepted, repaired, fell back and why",
            "every attempt: latency, outcome, prompt, completion and reasoning tokens, cost",
            "per candidate: accepted share, answer time p50, p95 and longest, total cost",
        ],
        "earlier_measurements": [
            "The Companion's evidence run asked the product's composer (reasoning_cheap, Nano) "
            "What happened in the square this morning? five times on a live world: 5 of 5 "
            "composed, 12.3 to 19.6 s. No candidate has been asked this set before this "
            "pre-registration was written.",
            "A first pre-registration of this comparison digested the packet with its tokens, "
            "which each packet draws afresh, so its run refused before asking any model. This "
            "replaces it; nothing was asked under it and nothing was spent.",
        ],
        "written_before_any_model_was_asked": True,
        "script": SCRIPT,
        "script_sha256": _sha256((ROOT / SCRIPT).read_bytes()),
        "manifest_sha256": _manifest_sha256(),
        "head": _head(),
    }


def preregister() -> None:
    _write_new(PREREGISTRATION, _registration())


def _registered() -> dict[str, Any]:
    registered = _read_record(PREREGISTRATION)
    now = _registration()
    keys = ("questions", "world", "candidates", "rule", "bound_usd", "max_tokens", "script_sha256")
    for key in keys:
        if registered[key] != now[key]:
            raise SystemExit(f"the pre-registration's {key} is not what this tree would run")
    return registered


# -- the run -----------------------------------------------------------------------------------


def _percentile(values: Sequence[int], share: float) -> int | None:
    """The nearest-rank percentile: the smallest value at least ``share`` of them are at most."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def _ask(client: Any, question: str) -> dict[str, Any]:
    from exulanica.models.errors import BudgetExceededError
    from exulanica.selection.calls import CallLog
    from exulanica.selection.society_question import compose_society_answer

    attempts: list[Any] = []
    sender = client.with_attempts(attempts.append)
    try:
        chosen = compose_society_answer(
            sender,
            question,
            _packet(question),
            log=CallLog(),
            saved=(),
            max_tokens=MAX_TOKENS,
            # The deadline's clock held still: a refused choice is asked for again.
            clock=lambda: 0.0,
        )
    except BudgetExceededError:
        raise SystemExit("the run reached its bound; no record is written") from None
    return {
        "accepted": bool(chosen.items),
        "lines": len(chosen.items),
        "framing": None if chosen.framing is None else str(chosen.framing),
        "repaired": bool(chosen.items) and bool(chosen.rejections),
        "late": chosen.late,
        "rejections": list(chosen.rejections),
        "attempts": [
            {
                "model_id": usage.model_id,
                "provider": usage.provider,
                "outcome": str(usage.outcome),
                "failure": usage.failure[:200],
                "latency_ms": round(usage.latency_s * 1000),
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "reasoning_tokens": usage.reasoning_tokens,
                "usd": str(usage.usd),
                "cost_basis": str(usage.cost_basis),
            }
            for usage in attempts
        ],
    }


def _asks(client_for: Callable[[str], Any], candidates: Sequence[str]) -> list[dict[str, Any]]:
    asks = []
    for number, question in enumerate(QUESTIONS, 1):
        for model_id in candidates:
            started = time.monotonic()
            asked = _ask(client_for(model_id), question)
            asked.update(
                question=number,
                model_id=model_id,
                wall_ms=round((time.monotonic() - started) * 1000),
            )
            asks.append(asked)
            print(
                f"q{number} {model_id}: accepted={asked['accepted']} "
                f"{sum(a['latency_ms'] for a in asked['attempts'])} ms",
                flush=True,
            )
    return asks


def _why(ask: Mapping[str, Any]) -> str:
    """Why an ask fell back: what happened to the last attempt, or a refused choice's repair."""
    return str(ask["late"]) if ask["late"] is not None else "refused_after_repair"


def _summaries(
    asks: Sequence[Mapping[str, Any]], candidates: Sequence[str]
) -> list[dict[str, Any]]:
    summaries = []
    for model_id in candidates:
        mine = [ask for ask in asks if ask["model_id"] == model_id]
        answer_ms = [sum(a["latency_ms"] for a in ask["attempts"]) for ask in mine]
        calls = [a for ask in mine for a in ask["attempts"]]
        call_ms = [a["latency_ms"] for a in calls]
        summaries.append(
            {
                "model_id": model_id,
                "questions": len(mine),
                "accepted": sum(ask["accepted"] for ask in mine),
                "accepted_first_try": sum(ask["accepted"] and not ask["repaired"] for ask in mine),
                "fell_back": {
                    reason: sum(1 for ask in mine if not ask["accepted"] and _why(ask) == reason)
                    for reason in sorted({_why(ask) for ask in mine if not ask["accepted"]})
                },
                "answer_ms": {
                    "p50": _percentile(answer_ms, 0.5),
                    "p95_slowest_of_8": _percentile(answer_ms, 0.95),
                    "longest": max(answer_ms, default=None),
                },
                "calls": {
                    "rows": len(call_ms),
                    "p50_ms": _percentile(call_ms, 0.5),
                    "p99_ms": _percentile(call_ms, 0.99),
                    "longest_ms": max(call_ms, default=None),
                    "timed_out": sum(1 for a in calls if a["outcome"] == "timed_out"),
                },
                "cost_usd": str(sum((Decimal(a["usd"]) for a in calls), Decimal(0))),
                "cost_known": all(a["cost_basis"] == "reported" for a in calls),
            }
        )
    return summaries


def choose(summaries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The default and its fallback by the pre-registered rule, with the order it read them in."""
    eligible = [s for s in summaries if s["accepted"] >= len(QUESTIONS) - 1]
    bound = RULE["speed_bound_ms"]

    def key(summary: Mapping[str, Any]) -> tuple[int, int, Decimal]:
        p95 = summary["answer_ms"]["p95_slowest_of_8"]
        nvidia_in_time = summary["model_id"].startswith("nvidia/") and p95 <= bound
        return (0 if nvidia_in_time else 1, p95, Decimal(summary["cost_usd"]))

    order = [s["model_id"] for s in sorted(eligible, key=key)]
    return {
        "eligible": [s["model_id"] for s in eligible],
        "order": order,
        "primary": order[0] if order else None,
        "fallback": order[1] if len(order) > 1 else None,
    }


def _run(
    client_for: Callable[[str], Any],
    registered: Mapping[str, Any],
    *,
    dry: bool,
    spent: Callable[[], Decimal],
) -> dict[str, Any]:
    candidates = registered["candidates"]
    started = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    asks = _asks(client_for, candidates)
    summaries = _summaries(asks, candidates)
    return {
        "dry_run": dry,
        "window": {"started": started, "ended": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
        "head": _head(),
        "manifest_sha256": _manifest_sha256(),
        "asks": asks,
        "summaries": summaries,
        "decision": choose(summaries),
        "spent_usd": str(spent()),
    }


def dry_run() -> None:
    """The whole run over a transport that chooses the first line of every packet it is sent."""
    import re

    from model_fakes import FakeTransport, RecordingPolicy, chat_body

    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.models.transport import HttpResponse

    class FirstLine(FakeTransport):
        def post_json(self, url, *, headers, payload, timeout):  # type: ignore[no-untyped-def]
            self.requests.append({"url": url, "payload": dict(payload)})
            sent = payload["messages"][1]["content"]
            token = re.search(r"^\[([A-Z0-9]+)\]", sent, re.MULTILINE).group(1)  # type: ignore[union-attr]
            reply = json.dumps({"lines": [token], "framing": None})
            body = chat_body(reply, model=payload["model"])
            return HttpResponse(status_code=200, text=json.dumps(body))

    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=BOUND_USD)

    def client_for(model_id: str) -> Any:
        return ModelClient(
            api_key="dry-run-key-not-real",
            manifest=_pinned(manifest, model_id),
            transport=FirstLine(),
            budget=budget,
            policy=RecordingPolicy(),
        )

    # Before the pre-registration: what it would register, so the dry run can come first.
    run = _run(client_for, _registration(), dry=True, spent=lambda: budget.spent_usd)
    _write_new(DRY_RUN_ARTIFACT, run, record=False)


def run(as_run: bytes) -> None:
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.models.policy import BenchmarkInputs

    registered = _registered()
    raw = os.environ.get(BUDGET_VARIABLE)
    if not raw:
        raise SystemExit(f"{BUDGET_VARIABLE} must state this run's bound")
    bound = Decimal(raw)
    if not Decimal(0) < bound <= Decimal(registered["bound_usd"]):
        raise SystemExit(f"{BUDGET_VARIABLE}={bound} is not within (0, {registered['bound_usd']}]")
    if not os.environ.get(KEY_VARIABLE):
        raise SystemExit(f"{KEY_VARIABLE} is not in this process's environment")
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists")
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(load_manifest().bound_origins()))
    manifest = load_manifest()
    budget = BudgetGuard(ceiling_usd=bound)
    reason = "the event lines of a simulated square no account holder's data is part of"
    clients = {
        model_id: ModelClient(manifest=_pinned(manifest, model_id), budget=budget).with_policy(
            BenchmarkInputs(reason)
        )
        for model_id in registered["candidates"]
    }
    measured = _run(clients.__getitem__, registered, dry=False, spent=lambda: budget.spent_usd)
    _write_new(RUN_ARTIFACT, measured, record=False)
    (ROOT / AS_RUN).write_bytes(as_run)
    print(f"wrote {AS_RUN}", flush=True)
    decision = measured["decision"]
    primary = next((s for s in measured["summaries"] if s["model_id"] == decision["primary"]), None)
    _write_new(
        RECORD,
        {
            "preregistration": PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "run_artifact": RUN_ARTIFACT,
            "run_sha256": _sha256((ROOT / RUN_ARTIFACT).read_bytes()),
            "script_as_run": AS_RUN,
            "script_sha256": _sha256(as_run),
            "head": measured["head"],
            "manifest_sha256": measured["manifest_sha256"],
            "window": measured["window"],
            "rule": registered["rule"],
            "summaries": measured["summaries"],
            "decision": decision,
            # The survey's shape (scripts/survey_hosted_call_latency.py), so the manifest's
            # timeout_basis for the composer's role can quote this record as it quotes that one.
            "measured": {
                "roles": {
                    registered["composer_role"]: {
                        "primary": decision["primary"],
                        "primary_measured": None
                        if primary is None
                        else {
                            "rows": primary["calls"]["rows"],
                            "p50_ms": primary["calls"]["p50_ms"],
                            "p99_ms": primary["calls"]["p99_ms"],
                            "longest_ms": primary["calls"]["longest_ms"],
                        },
                    }
                }
            },
            "spent_usd": measured["spent_usd"],
            "bound_usd": str(bound),
            "within_bound": Decimal(measured["spent_usd"]) <= bound,
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("preregister", "dry-run", "run"))
    step = parser.parse_args().step
    as_run = (ROOT / SCRIPT).read_bytes()
    if step == "preregister":
        preregister()
    elif step == "dry-run":
        dry_run()
    elif step == "run":
        run(as_run)
    else:
        raise SystemExit(f"unknown step {step!r}")


if __name__ == "__main__":
    main()
