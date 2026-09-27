#!/usr/bin/env python3
"""What do open models choose for a person in a world once they may stand and talk, and where
does a decision's time go?

    uv run python scripts/measure_society_model_actions.py contexts
    uv run python scripts/measure_society_model_actions.py preregister-probe
    uv run python scripts/measure_society_model_actions.py probe
    uv run python scripts/measure_society_model_actions.py probe-record
    uv run python scripts/measure_society_model_actions.py dry-run
    uv run python scripts/measure_society_model_actions.py preregister-run
    uv run python scripts/measure_society_model_actions.py run

**The question.** Under the decision contract's second version a person may go somewhere, wait,
stand a while nearby or stop to talk with somebody, each only as the routine itself could let
them. Where does the time of one decision go for each open model the manifest offers a person's
decisions, provider time or the length of the answer, and does asking by a forced call of ``act``
or by a JSON schema change it? Each model deciding for every person of the small square for an
hour of simulated time, what does it choose, how many conversations start, what is refused and
why, how long do answers take, how many time out and what does an hour cost?

**The probe** asks every offered model each of ``PROBE_CASES`` recorded choices once by each
mechanism, one at a time, through the product's client (``ModelClient.choose``) as the host asks:
the contract's instruction and the person's situation (``decision_messages``), the choice built
from the contract's options (``choice_request``), the host's token bound for the model
(``answer_tokens``) and the contract's deadline. The choices are people at a choice point in the
small square under its routine alone, read by ``contexts`` from its first ``CONTEXT_MINUTES``
minutes before any model is asked. Its pre-registration states the tree it measures and two
rules, each applied to the probe's calls alone: an answering order for a model, and a per-attempt
bound with one retry.

**The run** plays one fresh starter world per arm, the routine alone and each model the manifest
offers, with the small square placed where a person arrives and its people brought in with the
browser's own seed, for ``TICKS`` simulated minutes, every person chosen for the arm's model
through the owner's route. Every minute is a claim of the playback worker the application builds
for the workspaces it lists (``Services.build_society_control_worker``): the claim, the host's
decision phase before the minute, then the minute. The one thing the harness does that a host does
not is make each claim due at once. Its pre-registration is written after the probe and whatever
the probe's rules selected, and binds the tree the run measures.

**Spend.** The key is read from the environment, ``KEY_VARIABLE`` only, and reaches nothing but the
client. Each asking step reads its bound from ``BUDGET_VARIABLE`` and refuses one above the bound
pre-registered for it. The run's bound is what people's decisions may spend: the process's ceiling
is set so that the share the decision contract lets them use is the bound, and nothing else in the
process asks a model. Every record and artifact is written by this script and none is edited after.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

ROOT: Final = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from measure_living_square import bring_in, make_square, minute_of  # noqa: E402
from measure_living_world_pace import Api, seeds  # noqa: E402
from measure_society_person_models import (  # noqa: E402
    ScriptedChooser,
    _application,
    _bound,
    _ceiling,
    _ceiling_calls,
    _due_now,
    _grant,
    _latest_input,
    _manifest_sha256,
    _measured,
    _nearest_rank,
    _offered,
    _read_record,
    _receipts,
    _sha256,
    _step,
    _tree,
    _write_new,
    _write_new_bytes,
    pick_cases,
)

from exulanica.canonical import canonical_json  # noqa: E402

PROBE_PREREGISTRATION: Final = (
    "docs/evaluation/2026-09-26-society-model-actions-probe-preregistration.json"
)
PROBE_RECORD: Final = "docs/evaluation/2026-09-26-society-model-actions-probe.json"
RUN_PREREGISTRATION: Final = "docs/evaluation/2026-09-26-society-model-actions-preregistration.json"
RECORD: Final = "docs/evaluation/2026-09-26-society-model-actions.json"
ARTIFACTS: Final = "docs/evaluation/artifacts/2026-09-26-society-model-actions"
CONTEXTS: Final = f"{ARTIFACTS}/contexts.json"
PROBE_RUN: Final = f"{ARTIFACTS}/probe-run.json"
DRY_RUN: Final = f"{ARTIFACTS}/dry-run.json"
RUN: Final = f"{ARTIFACTS}/run.json"
PROBE_AS_RUN: Final = f"{ARTIFACTS}/measure_society_model_actions-probe-as-run.py.txt"
PROBE_RECORD_AS_RUN: Final = f"{ARTIFACTS}/measure_society_model_actions-probe-record-as-run.py.txt"
RUN_AS_RUN: Final = f"{ARTIFACTS}/measure_society_model_actions-run-as-run.py.txt"
SCRIPT: Final = "scripts/measure_society_model_actions.py"
#: Where this script's records and artifacts go: the one part of a tree a step does not measure.
RECORDS_DIRECTORY: Final = "docs/evaluation/"
BUDGET_VARIABLE: Final = "EXULANICA_BUDGET_USD"
MAX_CALLS_VARIABLE: Final = "EXULANICA_BUDGET_MAX_CALLS"

#: The browser's own seed, the one "Bring in inhabitants" sends first.
SEED: Final = seeds()[0]
CONTEXT_MINUTES: Final = 30
#: How many recorded choices the probe asks of each model by each mechanism.
PROBE_CASES: Final = 16
TICKS: Final = 60
MINUTES_PER_HOUR: Final = 60
PROBE_BOUND_USD: Final = Decimal("0.03")
RUN_BOUND_USD: Final = Decimal("0.20")
#: Far above what either step makes; the dollar bound is what stops one.
MAX_CALLS: Final = 4000
BENCHMARK_REASON: Final = (
    "decision contexts of the simulated people of a synthetic square: invented people, invented "
    "places, no account holder's data"
)
#: The answering-order rule. A model is asked by the other mechanism first when, over the probe's
#: cases, it answered with an offered action at least as often, wrote at most this share of the
#: tokens (median) and had a lower 95th-percentile answer time than by the mechanism the contract
#: asks it by. Writing is what a reasoning model's time and cost grow with.
ORDER_TOKENS_SHARE_AT_MOST: Final = Decimal("0.5")
#: The per-attempt rule. A stall is an answer slower than this many times its model and
#: mechanism's median while writing at most ``STALL_TOKENS_TIMES`` its median tokens (slow
#: without writing more), or a call that timed out for a model whose answered calls all came
#: within a third of the deadline. A model with at least ``STALLS_AT_LEAST`` stalls over its
#: probe calls is given an attempt bound: this many times its median, rounded up to a whole second,
#: and only when two such attempts fit inside the decision deadline.
STALL_TIMES_MEDIAN: Final = 3
STALL_TOKENS_TIMES: Final = Decimal("1.5")
STALLS_AT_LEAST: Final = 2


# -- records --------------------------------------------------------------------------------------


def _registered(relative: str, tree: Mapping[str, Any]) -> dict[str, Any]:
    """The pre-registration at ``relative``, refusing a tree other than the one it states."""
    registered = _read_record(relative)
    measured, bound = _measured(tree), _measured(registered["tree"])
    differ = sorted(
        path
        for path in {*measured["files_sha256"], *bound["files_sha256"]}
        if measured["files_sha256"].get(path) != bound["files_sha256"].get(path)
    )
    if measured["head"] != bound["head"] or differ:
        raise SystemExit(f"the tree is not the pre-registered one: {measured['head']} {differ}")
    return registered


def _as_run_is_the_script(as_run: bytes, tree: Mapping[str, Any]) -> None:
    if _sha256(as_run) != tree["files_sha256"].get(SCRIPT):
        raise SystemExit("the bytes running are not the script the tree binds")


# -- contexts -------------------------------------------------------------------------------------


def contexts() -> None:
    """Choices people make in the square under its routine alone, before any model is asked."""
    from exulanica.world.society_decision_contract import (
        at_choice_point,
        choice_options,
        decision_context,
        decision_contract,
    )

    contract = decision_contract()
    owner = _grant()
    found: list[dict[str, Any]] = []
    with _application([owner]) as (http, _services, urls):
        api = Api(http, owner["token"])
        world = make_square(api, "Society model actions: contexts")
        bring_in(api, world, SEED)
        society = f"/world/versions/{world['version']}/society"
        control = api("GET", society + "/control", params=world["scope"])
        state = api("GET", society, params=world["scope"])
        for _ in range(CONTEXT_MINUTES):
            document = _latest_input(urls["owner"], state["society_id"])
            for person in state["state"]["inhabitants"]:
                if not at_choice_point(person):
                    continue
                options = choice_options(
                    state["state"], document, person["id"], contract, seed=SEED
                )
                if options:
                    found.append(decision_context(state["state"], document, person["id"], options))
            control, state = _step(api, world, control, state)
    cases = pick_cases(found, PROBE_CASES)
    kinds = Counter(option["kind"] for case in cases for option in case["options"])
    if not (kinds["talk"] and kinds["stand"]):
        raise SystemExit(f"the cases offer no conversation or no standing: {dict(kinds)}")
    _write_new(
        CONTEXTS,
        {
            "profile": "exulanica.society-model-action-contexts/v1",
            "seed": SEED,
            "minutes": CONTEXT_MINUTES,
            "choices_found": len(found),
            "contract": contract.binding(),
            "cases": cases,
        },
        record=False,
    )


# -- the probe ------------------------------------------------------------------------------------


def _probe_rules() -> dict[str, Any]:
    return {
        "answering_order": (
            "A model is asked first by the mechanism other than the one the contract asks it by "
            "when, over the probe's cases, that mechanism answered with an offered action at least "
            f"as often, its median completion tokens were at most {ORDER_TOKENS_SHARE_AT_MOST} of "
            "the other's, and its 95th-percentile answer time (nearest rank) was lower. Otherwise "
            "the contract's order stands."
        ),
        "attempt_bound": (
            f"A stall is an answer slower than {STALL_TIMES_MEDIAN} times its model and "
            f"mechanism's median while writing at most {STALL_TOKENS_TIMES} times their median "
            "completion tokens, or a call that timed out for a model all of whose answered calls "
            "came within a third of the deadline. A model with at least "
            f"{STALLS_AT_LEAST} stalls over all its probe calls is given a per-attempt bound of "
            f"{STALL_TIMES_MEDIAN} times the median answer time of the mechanism it is asked by, "
            "rounded up to a whole second, with one retry, only when two such attempts fit inside "
            "the decision deadline. Otherwise no model has one."
        ),
    }


def preregister_probe() -> None:
    from exulanica.world.society_decision_contract import PROMPT_VERSION, decision_contract

    if (ROOT / PROBE_PREREGISTRATION).exists():
        raise SystemExit(f"{PROBE_PREREGISTRATION} is already written")
    from exulanica.models.manifest import load_manifest

    tree = _tree()
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    cases = json.loads(context_bytes)["cases"]
    contract = decision_contract()
    models = [spec.model_id for spec in _offered(load_manifest(), contract)]
    _write_new(
        PROBE_PREREGISTRATION,
        {
            "question": (
                "Where does the time of one decision go for each open model the manifest offers "
                "a person's decisions under the decision contract's second version, provider time "
                "or the length of its answer, and does asking by a forced call of act or by a "
                "JSON schema change it?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "earlier_measurements": [
                "The decision contract's first version was probed and measured by "
                "docs/evaluation/2026-09-25-society-person-models-probe.json and "
                "docs/evaluation/2026-09-25-society-person-models.json, over places and "
                "waiting only, and compared by docs/evaluation/2026-09-26-society-model-"
                "comparison.json; none of their calls is read here."
            ],
            "models": models,
            "cases": [
                {
                    "tick": case["tick"],
                    "subject_id": case["subject_id"],
                    "options": len(case["options"]),
                    "kinds": dict(sorted(Counter(o["kind"] for o in case["options"]).items())),
                    "context_sha256": _sha256(canonical_json(case)),
                }
                for case in cases
            ],
            "contexts_artifact": CONTEXTS,
            "contexts_sha256": _sha256(context_bytes),
            "mechanisms": ["tool_call", "json_schema"],
            "asked": (
                "each case once per mechanism per model, one call at a time, through "
                "ModelClient.choose with decision_messages, choice_request, the host's token bound "
                "for the model (answer_tokens), the contract's deadline and temperature 0; no retry"
            ),
            "measured": [
                "each call's answer time, prompt and completion tokens, finish, and whether it "
                "was one of the offered actions",
                "per model and mechanism: answer time p50, p95 and longest; completion tokens "
                "median and p95; a least-squares line of answer time against completion tokens, "
                "whose intercept is the time not spent writing and whose slope is the time per "
                "written token",
            ],
            "rules": _probe_rules(),
            "bound_usd": str(PROBE_BOUND_USD),
            "prompt_version": PROMPT_VERSION,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": tree,
            "record": PROBE_RECORD,
            "not_covered": [
                "Sixteen recorded choices of one square and one seed, asked once each by each "
                "mechanism: how often an answer varies between identical asks is not measured.",
                "One call at a time: a host asks everybody at a choice point at once, and the "
                "answer time of calls made together is measured by the run, not here.",
                "Answer time is the provider's from this machine at the time of the probe, not a "
                "deployment's.",
            ],
        },
    )


def _median(values: Sequence[int]) -> str | None:
    """The median, exact, as a decimal string: a record holds no float."""
    if not values:
        return None
    ordered = sorted(Decimal(value) for value in values)
    middle = len(ordered) // 2
    exact = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2
    return str(exact)


def _fit(points: Sequence[tuple[int, int]]) -> dict[str, Any]:
    """The least-squares line of answer time (ms) against completion tokens, when tokens vary:
    the intercept in whole milliseconds and the slope in milliseconds per token to 0.001."""
    if len(points) < 2 or len({tokens for tokens, _ in points}) < 2:
        return {"intercept_ms": None, "ms_per_token": None}
    count = Decimal(len(points))
    mean_t = sum(Decimal(t) for t, _ in points) / count
    mean_l = sum(Decimal(latency) for _, latency in points) / count
    slope = sum((Decimal(t) - mean_t) * (Decimal(latency) - mean_l) for t, latency in points) / sum(
        (Decimal(t) - mean_t) ** 2 for t, _ in points
    )
    return {
        "intercept_ms": int((mean_l - slope * mean_t).quantize(Decimal(1))),
        "ms_per_token": str(slope.quantize(Decimal("0.001"))),
    }


def probe_findings(calls: Sequence[Mapping[str, Any]], contract: Any, manifest: Any) -> dict:
    """Each model's figures by mechanism, and what the pre-registered rules select for it."""
    deadline_ms = contract.value("decision_deadline_ms")
    by_model: dict[str, Any] = {}
    for spec in _offered(manifest, contract):
        figures = {}
        for mechanism in ("tool_call", "json_schema"):
            asked = [
                c for c in calls if c["model_id"] == spec.model_id and c["mechanism"] == mechanism
            ]
            answered = [c for c in asked if c["completion_tokens"] is not None]
            latencies = [c["latency_ms"] for c in answered]
            tokens = [c["completion_tokens"] for c in answered]
            figures[mechanism] = {
                "asked": len(asked),
                "offered_action": sum(1 for c in asked if c["outcome"] == "offered_action"),
                "timed_out": sum(1 for c in asked if c["outcome"] == "timed_out"),
                "latency_ms": {
                    "p50": _nearest_rank(latencies, 50),
                    "p95": _nearest_rank(latencies, 95),
                    "longest": max(latencies) if latencies else None,
                },
                "completion_tokens": {
                    "median": _median(tokens),
                    "p95": _nearest_rank(tokens, 95),
                },
                "fit": _fit(list(zip(tokens, latencies, strict=True))),
            }
        first = str(contract.mechanism_for(spec))
        other = next(m for m in ("tool_call", "json_schema") if m != first)
        a, b = figures[first], figures[other]
        order = None
        if (
            b["offered_action"] >= a["offered_action"]
            and a["completion_tokens"]["median"]
            and b["completion_tokens"]["median"] is not None
            and Decimal(b["completion_tokens"]["median"])
            <= ORDER_TOKENS_SHARE_AT_MOST * Decimal(a["completion_tokens"]["median"])
            and a["latency_ms"]["p95"] is not None
            and b["latency_ms"]["p95"] is not None
            and b["latency_ms"]["p95"] < a["latency_ms"]["p95"]
        ):
            order = [other, first]
        asked_by = (order or [first])[0]
        stalls = 0
        answered_all = [
            c for c in calls if c["model_id"] == spec.model_id and c["latency_ms"] is not None
        ]
        quick = all(
            c["latency_ms"] <= deadline_ms / 3
            for c in answered_all
            if c["completion_tokens"] is not None
        )
        for c in calls:
            if c["model_id"] != spec.model_id:
                continue
            f = figures[c["mechanism"]]
            if c["outcome"] == "timed_out":
                stalls += quick
            elif (
                c["completion_tokens"] is not None
                and f["latency_ms"]["p50"]
                and c["latency_ms"] > STALL_TIMES_MEDIAN * f["latency_ms"]["p50"]
                and Decimal(c["completion_tokens"])
                <= STALL_TOKENS_TIMES * Decimal(f["completion_tokens"]["median"])
            ):
                stalls += 1
        bound = None
        median = figures[asked_by]["latency_ms"]["p50"]
        if stalls >= STALLS_AT_LEAST and median:
            candidate = 1000 * math.ceil(STALL_TIMES_MEDIAN * median / 1000)
            if 2 * candidate <= deadline_ms:
                bound = candidate
        by_model[spec.model_id] = {
            "name": manifest.model_name(spec.model_id),
            "asked_by_the_contract": first,
            "figures": figures,
            "answering_order_selected": order,
            "stalls": stalls,
            "attempt_bound_ms_selected": bound,
        }
    return by_model


def probe(as_run: bytes) -> None:
    from exulanica.api.society_person_decisions import answer_tokens
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.choice import ChoiceRefused
    from exulanica.models.client import ModelClient
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.errors import (
        BudgetExceededError,
        ModelError,
        TransportError,
        TruncatedResponseError,
    )
    from exulanica.models.manifest import AnsweringMechanism, load_manifest
    from exulanica.models.policy import BenchmarkInputs
    from exulanica.world.society_decision_contract import (
        PROMPT_VERSION,
        choice_request,
        decision_contract,
        decision_messages,
        person_role,
    )

    # The tree, before anything is asked.
    tree = _tree()
    registered = _registered(PROBE_PREREGISTRATION, tree)
    _as_run_is_the_script(as_run, tree)
    if (ROOT / PROBE_RECORD).exists():
        raise SystemExit(f"{PROBE_RECORD} exists")
    context_bytes = (ROOT / CONTEXTS).read_bytes()
    if _sha256(context_bytes) != registered["contexts_sha256"]:
        raise SystemExit("the contexts are not the ones the pre-registration binds")
    cases = json.loads(context_bytes)["cases"]
    bound = _bound(PROBE_BOUND_USD)
    manifest = load_manifest()
    contract = decision_contract()
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    budget = BudgetGuard(ceiling_usd=bound, max_calls=MAX_CALLS)
    client = ModelClient(manifest=manifest, budget=budget).with_policy(
        BenchmarkInputs(BENCHMARK_REASON)
    )
    deadline = contract.value("decision_deadline_ms") / 1000
    calls: list[dict[str, Any]] = []
    for spec in _offered(manifest, contract):
        for mechanism in (AnsweringMechanism.TOOL_CALL, AnsweringMechanism.JSON_SCHEMA):
            for number, case in enumerate(cases, 1):
                heard: list[Any] = []
                sender = client.with_attempts(heard.append)
                entry: dict[str, Any] = {
                    "model_id": spec.model_id,
                    "mechanism": mechanism.value,
                    "case": number,
                    "options": len(case["options"]),
                }
                started = time.monotonic()
                try:
                    chosen = sender.choose(
                        person_role().chosen,
                        spec.model_id,
                        decision_messages(case, mechanism),
                        choice_request(case),
                        mechanism=mechanism,
                        prompt_version=PROMPT_VERSION,
                        timeout=deadline,
                        max_tokens=answer_tokens(spec),
                    )
                except BudgetExceededError:
                    raise SystemExit("the probe reached its bound; nothing is written") from None
                except ChoiceRefused:
                    entry.update(outcome="not_an_offered_action")
                except TruncatedResponseError:
                    entry.update(outcome="truncated")
                except TransportError as exc:
                    entry.update(
                        outcome="timed_out" if exc.timed_out else "call_failed",
                        detail=type(exc).__name__,
                    )
                except ModelError as exc:
                    entry.update(outcome="model_error", detail=type(exc).__name__)
                else:
                    option = next(o for o in case["options"] if o["label"] == chosen.label)
                    entry.update(
                        outcome="offered_action",
                        chose_kind=option["kind"],
                        served_model_id=chosen.call.served_model_id,
                        finish_reason=chosen.call.finish_reason,
                    )
                entry["latency_ms"] = round((time.monotonic() - started) * 1000)
                entry["attempts"] = [
                    {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "usd": str(usage.usd),
                        "usd_known": usage.usd_known,
                    }
                    for usage in heard
                ]
                # The answer's own length when it came back; None for a call with no reply.
                entry["completion_tokens"] = (
                    heard[-1].completion_tokens
                    if heard and entry["outcome"] != "timed_out"
                    else None
                )
                calls.append(entry)
                print(
                    f"{spec.model_id} {mechanism.value} case {number}: {entry['outcome']} "
                    f"{entry['latency_ms']} ms",
                    flush=True,
                )
    run = {
        "profile": "exulanica.society-model-actions-probe-run/v1",
        "tree": tree,
        "manifest_sha256": _manifest_sha256(),
        "calls": calls,
        "spent_usd": str(budget.spent_usd),
        "bound_usd": str(bound),
    }
    _write_new(PROBE_RUN, run, record=False)
    _write_new_bytes(PROBE_AS_RUN, as_run)
    _write_probe_record(registered, run, {})


def _write_probe_record(
    registered: Mapping[str, Any], run: Mapping[str, Any], written_by: Mapping[str, Any]
) -> None:
    """The probe's record, from the calls its step made, by the pre-registered rules."""
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import decision_contract

    if _manifest_sha256() != run["manifest_sha256"]:
        raise SystemExit("the manifest is not the one the probe asked under")
    findings = probe_findings(run["calls"], decision_contract(), load_manifest())
    # The bound pre-registered for the probe, which its step refused to exceed.
    spent, bound = Decimal(run["spent_usd"]), Decimal(registered["bound_usd"])
    _write_new(
        PROBE_RECORD,
        {
            "preregistration": PROBE_PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "run_artifact": PROBE_RUN,
            "run_sha256": _sha256((ROOT / PROBE_RUN).read_bytes()),
            "script_as_run": PROBE_AS_RUN,
            "script_sha256": _sha256((ROOT / PROBE_AS_RUN).read_bytes()),
            **written_by,
            "tree": run["tree"],
            "manifest_sha256": run["manifest_sha256"],
            "rules": registered["rules"],
            "models": findings,
            "spent_usd": str(spent),
            "bound_usd": str(bound),
            "within_bound": spent <= bound,
        },
    )


def probe_record(as_run: bytes) -> None:
    """The probe's record, written from the calls the probe's own step made and stored, asking
    nothing: for a probe whose step made every call and then could not write its record."""
    tree = _tree()
    registered = _read_record(PROBE_PREREGISTRATION)
    measured, bound = _measured(tree), _measured(registered["tree"])
    differ = sorted(
        path
        for path in {*measured["files_sha256"], *bound["files_sha256"]}
        if measured["files_sha256"].get(path) != bound["files_sha256"].get(path)
    )
    # The tree the probe measured, but for this script, whose record writing is what changed.
    if measured["head"] != bound["head"] or differ != [SCRIPT]:
        raise SystemExit(f"the tree is not the probe's, beyond this script: {differ}")
    _as_run_is_the_script(as_run, tree)
    if (ROOT / PROBE_RECORD).exists():
        raise SystemExit(f"{PROBE_RECORD} exists")
    run = json.loads((ROOT / PROBE_RUN).read_bytes())
    if _measured(run["tree"]) != bound:
        raise SystemExit("the stored calls were made on another tree than the pre-registered one")
    if _sha256((ROOT / PROBE_AS_RUN).read_bytes()) != bound["files_sha256"][SCRIPT]:
        raise SystemExit("the calls' script is not the one the pre-registration binds")
    _write_new_bytes(PROBE_RECORD_AS_RUN, as_run)
    _write_probe_record(
        registered,
        run,
        {
            "record_written_by": {
                "script_as_run": PROBE_RECORD_AS_RUN,
                "script_sha256": _sha256(as_run),
                "why": (
                    "The probe's own step made every call and wrote the calls artifact, then "
                    "refused to write this record, because the median of an even number of "
                    "completion counts is not a whole number and a record holds no float. This "
                    "record was written from that artifact, asking nothing, by the script with "
                    "two changes: medians and slopes are written as exact decimal strings, and "
                    "this step, which reads the stored calls, was added."
                ),
            },
        },
    )


# -- the run --------------------------------------------------------------------------------------


def _conversations(owner_url: str, society_id: str, world_id: str) -> dict[str, int]:
    """What the society's events say of standing and talking, one event per person, counted from
    the database: goals chosen, and actions begun."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(owner_url, row_factory=dict_row) as connection:
        row = connection.execute(
            "select "
            "count(*) filter (where e.document->>'outcome'='talk_started') as began_talking,"
            "count(*) filter (where e.event_kind='goal_selected' "
            "and e.document->>'reason'='chosen_by_their_model' "
            "and e.document->'goal'->>'kind'='talk') as talk_goals_a_model_chose,"
            "count(*) filter (where e.event_kind='goal_selected' "
            "and e.document->>'reason'='stopped_to_talk') as talk_goals_joined_or_the_routines,"
            "count(*) filter (where e.event_kind='goal_selected' "
            "and e.document->>'reason'='chosen_by_their_model' "
            "and e.document->'goal'->>'kind'='stand') as stand_goals_a_model_chose,"
            "count(*) filter (where e.document->>'reason'='standing_a_while' "
            "and e.document->>'outcome'='action_started') as began_standing,"
            "count(*) filter (where e.document->>'reason'='route_invalidated') "
            "as stopped_with_route_invalidated "
            "from world_society_event e join world_society s "
            "using(workspace_id,society_id) where e.society_id=%s and s.world_id=%s",
            (society_id, world_id),
        ).fetchone()
    return {key: int(value) for key, value in row.items()}


def _decision(row: Mapping[str, Any]) -> dict[str, Any]:
    receipt, request = row["document"], row["request"]
    provider = receipt["provider"] or {}
    proposal = receipt["proposal"]
    option = None if proposal is None else proposal["option"]
    return {
        "decision_seq": row["decision_seq"],
        "subject_id": receipt["subject_id"],
        "base_tick": receipt["base_tick"],
        "consumed_tick": row["tick"],
        "options": len(request["context"]["options"]),
        "offered_kinds": dict(
            sorted(Counter(o["kind"] for o in request["context"]["options"]).items())
        ),
        "mechanism": request["provider_config"]["mechanism"],
        "status": receipt["status"],
        "reason": receipt["reason"],
        "disposition": row["disposition"],
        "disposition_reason": row["disposition_reason"],
        "chose_kind": None if option is None else option["kind"],
        "chose_activity": None if option is None else option["activity"],
        "answers_asked": provider.get("answers_asked"),
        "outcomes": [call["outcome"] for call in provider.get("calls", [])],
        "latency_ms": provider.get("latency_ms"),
        "prompt_tokens": provider.get("prompt_tokens"),
        "completion_tokens": provider.get("completion_tokens"),
        "cost_usd": provider.get("cost_usd"),
        "cost_known": provider.get("cost_known"),
    }


def _arm(http, grant, services, worker, owner_url, model, billed) -> dict[str, Any]:
    """One world, played ``TICKS`` minutes by the playback worker, its people run by ``model`` or
    by their routine."""
    api = Api(http, grant["token"])
    label = "routine" if model is None else model["model_id"]
    world = make_square(api, f"Society model actions: {label}")
    bring_in(api, world, SEED)
    society = f"/world/versions/{world['version']}/society"
    state = api("GET", society, params=world["scope"])
    people = sorted(person["id"] for person in state["state"]["inhabitants"])
    if model is not None:
        api(
            "POST",
            society + "/models",
            params=world["scope"],
            json={"idempotency_key": str(uuid.uuid4()), "people": people, "model": dict(model)},
        )
    control = api("GET", society + "/control", params=world["scope"])
    api(
        "PUT",
        society + "/control",
        params=world["scope"],
        json={"base_revision": control["revision"], "mode": "playing", "speed": 1},
    )
    minutes: list[dict[str, Any]] = []
    claims: list[int] = []
    advanced: list[int] = []
    while state["current_tick"] < TICKS:
        _due_now(services.database, grant["id"], state["society_id"])
        claimed = time.monotonic()
        result = worker.run_once(grant["id"])
        claims.append(round((time.monotonic() - claimed) * 1000))
        if result is None or "receipt" not in result:
            raise SystemExit(f"{label}: a due claim advanced no minute: {result}")
        advanced.append(result["receipt"]["executed_ticks"])
        state = api("GET", society, params=world["scope"])
        counts = Counter(minute_of(person)[0] for person in state["state"]["inhabitants"])
        minutes.append({"tick": state["current_tick"], **dict(sorted(counts.items()))})
    read = api("GET", society + "/models", params=world["scope"])
    receipts = _receipts(owner_url, state["society_id"])
    before = billed()
    replay = api("GET", society + "/replay", params=world["scope"])
    return {
        "arm": label,
        "model": None if model is None else dict(model),
        "people": len(people),
        "minutes": minutes,
        "claim_ms": claims,
        "minutes_per_claim": advanced,
        "decisions": [_decision(row) for row in receipts],
        "events": _conversations(owner_url, state["society_id"], world["scope"]["world_id"]),
        "host_refusal": read["host_refusal"],
        "replay_verified": replay.get("replay_verified"),
        "billed_calls_during_replay": billed() - before,
        "state_sha256": state["state_sha256"],
    }


def _chose(decision: Mapping[str, Any]) -> str:
    kind = decision["chose_kind"]
    return f"go:{decision['chose_activity']}" if kind == "target" else str(kind)


def summarise(arm: Mapping[str, Any]) -> dict[str, Any]:
    """One arm's decisions, conversations and minutes."""
    decisions = arm["decisions"]
    asked = [d for d in decisions if d["answers_asked"]]
    settled = [d for d in decisions if d["disposition"] is not None]
    applied = [d for d in settled if d["disposition"] == "applied"]
    latencies = [d["latency_ms"] for d in asked if d["latency_ms"] is not None]
    cost = sum((Decimal(d["cost_usd"]) for d in asked), Decimal(0))
    person_minutes: Counter[str] = Counter()
    for minute in arm["minutes"]:
        person_minutes.update({k: v for k, v in minute.items() if k != "tick"})
    chose = [d for d in decisions if d["status"] == "accepted"]
    return {
        "arm": arm["arm"],
        "people": arm["people"],
        "decisions": len(decisions),
        "asked": len(asked),
        "accepted": len(chose),
        "first_answer_accepted": sum(1 for d in chose if d["answers_asked"] == 1),
        "applied": len(applied),
        "settled": len(settled),
        "offered": dict(
            sorted(
                Counter(
                    kind for d in decisions for kind, n in d["offered_kinds"].items() if n
                ).items()
            )
        ),
        "chose": dict(sorted(Counter(_chose(d) for d in chose).items())),
        "chose_by_kind": dict(sorted(Counter(str(d["chose_kind"]) for d in chose).items())),
        "applied_by_kind": dict(sorted(Counter(str(d["chose_kind"]) for d in applied).items())),
        "by_reason": dict(sorted(Counter(d["reason"] for d in decisions).items())),
        # Why each settled decision was not acted on, once each: the receipt's reason, or the
        # minute's when an accepted one was not acted on.
        "not_acted_on": dict(
            sorted(
                Counter(
                    d["reason"] if d["status"] != "accepted" else d["disposition_reason"]
                    for d in settled
                    if d["disposition"] != "applied"
                ).items()
            )
        ),
        "timeouts": sum(1 for d in decisions if d["reason"] == "model_timed_out"),
        "latency_ms": {
            "p50": _nearest_rank(latencies, 50),
            "p95": _nearest_rank(latencies, 95),
            "longest": max(latencies) if latencies else None,
        },
        "prompt_tokens": sum(d["prompt_tokens"] or 0 for d in asked),
        "completion_tokens": sum(d["completion_tokens"] or 0 for d in asked),
        "cost_usd": str(cost),
        "cost_known": all(d["cost_known"] for d in asked),
        "cost_usd_per_simulated_hour": str(
            (cost * MINUTES_PER_HOUR / TICKS).quantize(Decimal("0.000001"))
        ),
        "events": dict(arm["events"]),
        "person_minutes": dict(sorted(person_minutes.items())),
        "claim_ms": {
            "p50": _nearest_rank(arm["claim_ms"], 50),
            "p95": _nearest_rank(arm["claim_ms"], 95),
            "longest": max(arm["claim_ms"]),
        },
        "claims": len(arm["claim_ms"]),
        "claims_advancing_more_than_one_minute": sum(
            1 for minutes in arm["minutes_per_claim"] if minutes != 1
        ),
        "host_refusal_at_the_end": arm["host_refusal"],
        "replay_verified": arm["replay_verified"],
        "billed_calls_during_replay": arm["billed_calls_during_replay"],
    }


def _play(models: Sequence[Mapping[str, str]], *, live: bool, client: Any = None) -> dict:
    """Every arm, the routine first, each in a workspace of its own in one application."""
    import dataclasses

    grants = {arm: _grant() for arm in ["routine", *(m["model_id"] for m in models)]}
    arms = []
    with _application(list(grants.values()), live=live, model_client=client) as (
        http,
        services,
        urls,
    ):
        listed = dataclasses.replace(
            services, society_control_workspaces=tuple(grant["id"] for grant in grants.values())
        )
        http.app.state.services = listed
        worker = listed.build_society_control_worker()
        if worker is None:
            raise SystemExit("the application built no playback worker for the listed workspaces")
        budget = listed.model_client.budget if listed.model_client is not None else None

        def billed() -> int:
            return 0 if budget is None else budget.billed_calls

        for model in [None, *models]:
            key = "routine" if model is None else model["model_id"]
            arm = _arm(http, grants[key], listed, worker, urls["owner"], model, billed)
            print(f"{key}: {len(arm['decisions'])} decisions {arm['events']}", flush=True)
            arms.append(arm)
        spent = None if budget is None else str(budget.spent_usd)
        ceiling = None if budget is None else str(budget.ceiling_usd)
    return {"arms": arms, "spent_usd": spent, "process_ceiling_usd": ceiling}


def dry_run() -> None:
    """Every arm with a scripted model, played as the run plays them. Asks no model."""
    from exulanica.models.budget import BudgetGuard
    from exulanica.models.client import ModelClient
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import decision_contract

    if (ROOT / DRY_RUN).exists():
        raise SystemExit(f"{DRY_RUN} exists")
    tree = _tree()
    manifest = load_manifest()
    transport = ScriptedChooser(SEED)
    client = ModelClient(
        api_key="dry-run-not-a-credential",
        manifest=manifest,
        transport=transport,
        budget=BudgetGuard(ceiling_usd=Decimal("1"), max_calls=10 * MAX_CALLS),
    )
    models = [
        {"provider": spec.provider, "model_id": spec.model_id}
        for spec in _offered(manifest, decision_contract())
    ]
    played = _play(models, live=False, client=client)
    _write_new(
        DRY_RUN,
        {
            "profile": "exulanica.society-model-actions-dry-run/v1",
            "tree": tree,
            "models": models,
            "scripted_calls": transport.call_count,
            "summaries": [summarise(arm) for arm in played["arms"]],
        },
        record=False,
    )


def preregister_run() -> None:
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import PROMPT_VERSION, decision_contract

    if (ROOT / RUN_PREREGISTRATION).exists():
        raise SystemExit(f"{RUN_PREREGISTRATION} is already written")
    tree = _tree()
    dry_bytes = (ROOT / DRY_RUN).read_bytes()
    dry = json.loads(dry_bytes)
    if _measured(dry["tree"]) != _measured(tree):
        raise SystemExit("the tree changed since the dry run; run the dry run again")
    probed = _read_record(PROBE_RECORD)
    contract = decision_contract()
    manifest = load_manifest()
    offered = _offered(manifest, contract)
    _write_new(
        RUN_PREREGISTRATION,
        {
            "question": (
                "Each open model the manifest offers deciding for the eight people of the small "
                f"square for {TICKS} simulated minutes, as a host's playback plays a world, under "
                "the decision contract's second version: what does it choose, by kind, how many "
                "conversations start, what is refused and why, how long do answers take, how many "
                "time out and what does a simulated hour cost, beside the routine alone?"
            ),
            "written_before_this_measurement_asked_any_model": True,
            "earlier_measurements": [
                f"The probe ({PROBE_RECORD}) asked every offered model recorded choices by both "
                "mechanisms before this was written; what its rules selected is what the tree "
                "below holds, and its calls are not read here."
            ],
            "probe_record": PROBE_RECORD,
            "probe_record_sha256": _sha256(canonical_json(probed)),
            "probe_selected": {
                model_id: {
                    "answering_order": found["answering_order_selected"],
                    "attempt_bound_ms": found["attempt_bound_ms_selected"],
                }
                for model_id, found in probed["models"].items()
            },
            "arms": ["routine", *(spec.model_id for spec in offered)],
            "mechanisms": {spec.model_id: str(contract.mechanism_for(spec)) for spec in offered},
            "world": (
                "a starter world per arm, the small square placed where a person arrives, its "
                "people brought in with the profile exulanica-society/v2, every person chosen for "
                "the arm's model, and the world set playing at speed 1 through the control route"
            ),
            "seed": SEED,
            "ticks": TICKS,
            "played_by": (
                "the playback worker the application builds for the workspaces it lists "
                "(Services.build_society_control_worker), one claim at a time: the claim, the "
                "host's decision phase before the minute (DecisionHost.before_minute), "
                "then the minute"
            ),
            "harness_intervention": (
                "each claim is made due at once, its next_due_at set a millisecond back, where "
                "a host waits its base interval"
            ),
            "measured": [
                "decisions, asked, accepted, accepted on the first answer, applied",
                "what was offered and what was chosen, by kind (go by activity, wait, stand, "
                "talk), and what was applied, by kind",
                "conversations started, conversations a model chose, people who joined one, "
                "stands a model chose and stands started, from the society's events",
                "why each settled decision was not acted on, by reason",
                "timeouts; answer time p50, p95 and longest; prompt and completion tokens; cost, "
                "and per simulated hour",
                "person-minutes walking, using, waiting, standing and talking",
                "each claim's wall time; claims that advanced more than one minute",
                "the host's refusal, if any, when each arm ends",
                "replay verified, and the billed calls made during replay",
            ],
            "bound_usd": str(RUN_BOUND_USD),
            "process_ceiling_usd": str(_ceiling(RUN_BOUND_USD, contract)),
            "process_max_calls": _ceiling_calls(MAX_CALLS, contract),
            "bound_why": (
                "the decision contract lets people's decisions spend all but "
                "process_reserve_percent of the process's ceiling, and nothing else in the "
                "run's process asks a model, so the run spends at most its bound"
            ),
            "dry_run": {
                "artifact": DRY_RUN,
                "sha256": _sha256(dry_bytes),
                "scripted_calls": dry["scripted_calls"],
                "decisions_per_arm": {s["arm"]: s["decisions"] for s in dry["summaries"]},
            },
            "prompt_version": PROMPT_VERSION,
            "contract": contract.binding(),
            "manifest_sha256": _manifest_sha256(),
            "tree": tree,
            "record": RECORD,
            "not_covered": [
                "One square, one seed and one hour of simulated time per model; other worlds, "
                "seeds and longer runs are not measured.",
                "The people are all run by one model in each arm; worlds mixing models, or "
                "mixing models with the routine, are not measured.",
                "Whether a model's choices are better for the people than the routine's is not "
                "judged; the record states what each chose and what came of it.",
                "Answer time is the provider's from this machine at the time of the run, not a "
                "deployment's.",
            ],
        },
    )


def run(as_run: bytes) -> None:
    from exulanica.models.egress import EGRESS_ALLOWLIST_ENV
    from exulanica.models.manifest import load_manifest
    from exulanica.world.society_decision_contract import decision_contract

    # The tree, before anything is asked.
    tree = _tree()
    registered = _registered(RUN_PREREGISTRATION, tree)
    _as_run_is_the_script(as_run, tree)
    if (ROOT / RECORD).exists():
        raise SystemExit(f"{RECORD} exists")
    bound = _bound(RUN_BOUND_USD)
    manifest = load_manifest()
    contract = decision_contract()
    offered = _offered(manifest, contract)
    models = [{"provider": spec.provider, "model_id": spec.model_id} for spec in offered]
    ceiling = _ceiling(bound, contract)
    os.environ[EGRESS_ALLOWLIST_ENV] = json.dumps(sorted(manifest.bound_origins()))
    os.environ[BUDGET_VARIABLE] = str(ceiling)
    os.environ[MAX_CALLS_VARIABLE] = str(_ceiling_calls(MAX_CALLS, contract))
    played = _play(models, live=True)
    _write_new(
        RUN,
        {
            "profile": "exulanica.society-model-actions-run/v1",
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            **played,
        },
        record=False,
    )
    _write_new_bytes(RUN_AS_RUN, as_run)
    _write_new(
        RECORD,
        {
            "preregistration": RUN_PREREGISTRATION,
            "preregistration_record_sha256": _sha256(canonical_json(registered)),
            "probe_record": PROBE_RECORD,
            "run_artifact": RUN,
            "run_sha256": _sha256((ROOT / RUN).read_bytes()),
            "script_as_run": RUN_AS_RUN,
            "script_sha256": _sha256(as_run),
            "tree": tree,
            "manifest_sha256": _manifest_sha256(),
            "mechanisms": registered["mechanisms"],
            "summaries": [summarise(arm) for arm in played["arms"]],
            "spent_usd": played["spent_usd"],
            "bound_usd": str(bound),
            "process_ceiling_usd": played["process_ceiling_usd"],
            "within_bound": Decimal(played["spent_usd"]) <= bound,
        },
    )


def main(argv: Sequence[str] | None = None) -> None:
    # The bytes that run, read before anything else can change the file.
    as_run = Path(__file__).read_bytes()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    steps = (
        "contexts",
        "preregister-probe",
        "probe",
        "probe-record",
        "dry-run",
        "preregister-run",
        "run",
    )
    parser.add_argument("step", choices=steps)
    step = parser.parse_args(argv).step
    if step == "probe":
        probe(as_run)
    elif step == "probe-record":
        probe_record(as_run)
    elif step == "run":
        run(as_run)
    else:
        {
            "contexts": contexts,
            "preregister-probe": preregister_probe,
            "dry-run": dry_run,
            "preregister-run": preregister_run,
        }[step]()


if __name__ == "__main__":
    main()
