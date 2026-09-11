"""Measure the drafting call against its own token ceiling.

    EXULANICA_BUDGET_USD=0.50 EXULANICA_BUDGET_MAX_CALLS=40 \
      uv run python scripts/measure_drafting_ceiling.py \
        --cap-usd 0.50 --max-calls 40 --repeats 6 --out /tmp/drafting-ceiling

THIS SCRIPT SPENDS MONEY unless `--skip-live` is given, and it refuses to start a live run unless
the operator's ceiling is stated TWICE, once in the environment and once on the command line,
with the two agreeing exactly.

WHY THIS EXPERIMENT AND NOT THE OTHER TWO

The prompt-comparison record left three candidates for why the drafting call fails: a token
ceiling, a schema shape, and a different extraction model. The failure mode picks between them.
Across every recorded run of the SHIPPED prompt, all six failures were `TruncatedResponseError`
and none were `StructuredOutputError`: the call is not producing invalid JSON, it is running out
of room. `draft_appearance` passes no `max_tokens`, so it takes the role's default of 2048, and
nothing has ever checked whether that is enough.

`compose_answer` in `exulanica/selection/question.py` had the same problem and its constant
carries the argument this script is testing: "A ceiling is not a spend: an unused one costs
nothing and a low one costs a failed answer on a request somebody is waiting for."

WHAT IT RECORDS, AND WHY THE TOKEN COUNTS MATTER MORE THAN THE PASS RATE

A pass rate says whether a ceiling is high enough today. The COMPLETION TOKEN COUNT on every
successful draft says how much room the call actually needs, which is what a ceiling should be
sized from. Both are recorded per attempt, so the constant that comes out of this is argued from
a distribution rather than picked.

It also records the count on FAILURE where the provider reported one, because a truncated call
that spent its whole ceiling is a different fact from one that stopped just over it: the first
says the model is running away and a higher ceiling buys a longer runaway, the second says the
ceiling was simply too low.

The request is the two-part one, because the control-count defect only shows on a request that
names more than one thing, and it is the request every other measurement of this call has used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from exulanica.models.budget import BudgetGuard
from exulanica.models.client import ModelClient
from exulanica.models.errors import ModelError
from exulanica.models.manifest import load_manifest
from exulanica.selection import proposal as module
from exulanica.selection.proposal import (
    PROMPT_VERSION,
    SourceChoice,
    _proposable_profiles,
    _validate_draft,
)
from exulanica.selection.question import CallLog
from exulanica.world import STYLE_REGISTRY, StyleReference

MICRO = Decimal("0.000001")

#: The request every other measurement of this call has used, kept the same so the numbers are
#: comparable with the prompt-comparison record rather than merely adjacent to it.
REQUEST = "make this place feel warmer and less busy"

#: The ceilings under test in `--mode ceiling`. 2048 is what the role's default gives the call
#: today. The rest are doublings, because the question is which order of magnitude the call needs
#: rather than which exact number, and a doubling answers that in three arms instead of ten.
CEILINGS: tuple[int | None, ...] = (None, 4096, 8192)

#: The arms in `--mode recovery`, as (label, ceiling, retry-on-truncation).
#:
#: **This mode exists because the ceiling mode answered its question and the answer was no.** A
#: successful draft never exceeded 290 completion tokens against a ceiling of 2048, and raising
#: the ceiling to 4096 and 8192 changed nothing: the call is not cramped, it runs away, and a
#: runaway will spend whatever it is given. What the data pointed at instead is that
#: `draft_appearance` retries only on `StructuredOutputError`, and every recorded failure of the
#: shipped prompt was `TruncatedResponseError`, which propagates on the first attempt. The one
#: repair the function advertises does not cover the failure it actually has.
#:
#: 640 is the role's declared `min_max_tokens`, so it is the lowest this role may be asked for.
#: 1024 is the arm that matters: more than three times the largest observed success, and half the
#: current ceiling, so a runaway is cut off sooner and costs less without a success losing room.
RECOVERY: tuple[tuple[str, int | None, bool], ...] = (
    ("shipped: 2048, no truncation retry", None, False),
    ("2048, retry on truncation", None, True),
    ("1024, retry on truncation", 1024, True),
)


def micro_usd(value: Decimal) -> int:
    return int((value / MICRO).to_integral_value(rounding="ROUND_CEILING"))


def cost_of(manifest, model_id: str, prompt: int | None, completion: int | None) -> int:
    if prompt is None and completion is None:
        return 0
    try:
        spec = manifest.spec(model_id)
    except KeyError:
        return 0
    return micro_usd(spec.cost_usd(prompt_tokens=prompt or 0, completion_tokens=completion or 0))


def refuse_without_a_stated_ceiling(args) -> None:
    if args.skip_live:
        return
    environment_cap = os.environ.get("EXULANICA_BUDGET_USD", "")
    environment_calls = os.environ.get("EXULANICA_BUDGET_MAX_CALLS", "")
    if Decimal(environment_cap or "-1") != Decimal(args.cap_usd):
        raise SystemExit(
            f"EXULANICA_BUDGET_USD={environment_cap!r} does not match --cap-usd {args.cap_usd!r}."
        )
    if int(environment_calls or -1) != args.max_calls:
        raise SystemExit(
            f"EXULANICA_BUDGET_MAX_CALLS={environment_calls!r} does not match --max-calls "
            f"{args.max_calls}."
        )
    if not os.environ.get("NEBIUS_API_KEY"):
        raise SystemExit("NEBIUS_API_KEY is not set, so there is nothing to measure.")


def measure() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap-usd", required=True)
    parser.add_argument("--max-calls", required=True, type=int)
    parser.add_argument("--mode", choices=("ceiling", "recovery"), default="ceiling")
    parser.add_argument("--repeats", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-live", action="store_true")
    args = parser.parse_args()
    refuse_without_a_stated_ceiling(args)
    args.out.mkdir(parents=True, exist_ok=False)

    manifest = load_manifest()
    profile = _proposable_profiles(STYLE_REGISTRY)[0]
    current = STYLE_REGISTRY.validate_reference(
        StyleReference(profile.profile_id, profile.profile_version, {})
    )
    choices = tuple(
        SourceChoice(
            source_id=uuid.UUID(int=index + 1),
            evidence_span_id=uuid.UUID(int=1000 + index),
            region_id="region-a",
            slot_key=f"slot-{index:02d}",
        )
        for index in range(3)
    )

    plan = (
        [(f"ceiling {c or 2048}", c, False) for c in CEILINGS]
        if args.mode == "ceiling"
        else list(RECOVERY)
    )
    arms: list[dict[str, Any]] = []
    for label, ceiling, retry_truncated in plan:
        attempts: list[dict[str, Any]] = []
        for _ in range(args.repeats):
            log = CallLog()
            client = ModelClient(
                manifest=manifest,
                budget=BudgetGuard(ceiling_usd=Decimal(args.cap_usd), max_calls=args.max_calls),
            )
            try:
                raw, served = _draft(client, current, choices, ceiling, log, retry_truncated)
                verdict = _validate_draft(raw, current, choices, registry=STYLE_REGISTRY)
            except ModelError as exc:
                attempts.append(
                    {
                        "drafted": False,
                        "raised": type(exc).__name__,
                        "detail": str(exc)[:280],
                        # Present when the provider reported usage before the raise. A truncated
                        # call that spent its whole ceiling is a runaway; one that stopped just
                        # over it was merely cramped, and the two want different fixes.
                        "completion_tokens": [c.completion_tokens for c in log.calls],
                    }
                )
                continue
            changed = list(getattr(verdict, "changed", ()) or ())
            spoken = getattr(verdict, "spoken", None) or ""
            attempts.append(
                {
                    "drafted": hasattr(verdict, "profile"),
                    "refusal": getattr(getattr(verdict, "code", None), "value", None),
                    "control_count": len(changed),
                    "changed": changed,
                    "spoken": spoken,
                    "completion_tokens": [c.completion_tokens for c in log.calls],
                    "prompt_tokens": [c.prompt_tokens for c in log.calls],
                    "latency_ms": [c.latency_ms for c in log.calls],
                    "served_model": served,
                    "cost_micro_usd": sum(
                        cost_of(manifest, c.served_model, c.prompt_tokens, c.completion_tokens)
                        for c in log.calls
                    ),
                }
            )
        drafted = [a for a in attempts if a.get("drafted")]
        spent = [t for a in drafted for t in a["completion_tokens"] if t is not None]
        arms.append(
            {
                "label": label,
                "retries_on_truncation": retry_truncated,
                "max_tokens": ceiling,
                "effective_max_tokens": ceiling or manifest[
                    "structured_extraction"
                ].default_max_tokens,
                "drafted": len(drafted),
                "attempts": attempts,
                "completion_tokens_on_success": sorted(spent),
                "largest_completion_on_success": max(spent) if spent else None,
                "cost_micro_usd": sum(a.get("cost_micro_usd", 0) for a in attempts),
            }
        )

    record = {
        "profile": "exulanica.drafting-ceiling-measurement/v1",
        "prompt_version": PROMPT_VERSION,
        "pipeline_version": manifest.pipeline_version,
        "request": REQUEST,
        "repeats_per_arm": args.repeats,
        "why_this_experiment": (
            "Every recorded failure of the shipped prompt was TruncatedResponseError and none "
            "was StructuredOutputError, so the call is running out of room rather than emitting "
            "invalid JSON. `draft_appearance` passes no max_tokens and takes the role default."
        ),
        "arms": arms,
        "total_cost_micro_usd": sum(arm["cost_micro_usd"] for arm in arms),
        "experiment_script": "scripts/measure_drafting_ceiling.py",
        "experiment_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    (args.out / "measurement.json").write_text(json.dumps(record, indent=2, default=str) + "\n")
    print(
        json.dumps(
            {
                arm["label"]: {
                    "drafted": f"{arm['drafted']}/{args.repeats}",
                    "completion_on_success": arm["completion_tokens_on_success"],
                    "controls": [a["control_count"] for a in arm["attempts"] if a.get("drafted")],
                    "cost_micro_usd": arm["cost_micro_usd"],
                }
                for arm in arms
            },
            indent=2,
        )
    )
    return 0


def _draft(client, current, choices, ceiling, log, retry_truncated=False):
    """`draft_appearance`, with its ceiling overridden for the duration of one call.

    The function reads no module-level ceiling, so this cannot use the rebinding trick its
    siblings use. It calls the same two steps `draft_appearance` does, with the same schema, the
    same prompt and the same one repair, and differs only in the argument under test.
    """
    from exulanica.models.errors import StructuredOutputError, TruncatedResponseError
    from exulanica.models.manifest import Role

    schema = module._draft_model(_proposable_profiles(STYLE_REGISTRY), choices)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": module._DRAFTER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"{module._render_catalogue(_proposable_profiles(STYLE_REGISTRY), current, choices, STYLE_REGISTRY)}"
                f'\n\nThe request:\n"""{REQUEST}"""'
            ),
        },
    ]
    for attempt in range(1, module.DRAFT_ATTEMPTS + 1):
        try:
            drafted = client.structured(
                Role.STRUCTURED_EXTRACTION,
                messages,
                schema,
                prompt_version=PROMPT_VERSION,
                **({} if ceiling is None else {"max_tokens": ceiling}),
            )
            log.record(drafted.call)
            return drafted.value.model_dump(), drafted.call.served_model_id
        except (StructuredOutputError, TruncatedResponseError) as rejected:
            truncated = isinstance(rejected, TruncatedResponseError)
            if attempt == module.DRAFT_ATTEMPTS or (truncated and not retry_truncated):
                raise
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "That form ran past the room it had. Fill it in again, shorter: the same "
                        "change, one or two sentences in `spoken`, and nothing repeated."
                        if truncated
                        else f"That form was refused:\n{rejected}\n\nFill it in again, fixing "
                        "exactly that. Change nothing else about what the request is asking for."
                    ),
                }
            )
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(measure())
